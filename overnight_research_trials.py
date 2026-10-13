"""Private future-owner append-only trial ledger; no production model registry."""
from __future__ import annotations

from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from overnight_research_dataset import ResearchError, canonical, fingerprint, instant, sha, unique_pairs
from overnight_research_ml import Fold, ModelSpec


class DurableTrialRegistry:
    """Persist STARTED before fitting; unfinished trials survive crash as UNKNOWN.

    Explicit private path only, outside source repository. No discovery, retries,
    implicit completion, or deletion. Each completion is a new immutable event.
    """

    def __init__(self, path: Path, *, create: bool = False) -> None:
        self.path = path
        self._safe_path()
        new = not path.exists()
        if (new and not create) or (not new and create):
            raise ResearchError('TRIAL_LEDGER_MISSING_OR_CREATION_CONFLICT')
        if not path.parent.is_dir():
            raise ResearchError('PRIVATE_TRIAL_PARENT_REQUIRED')
        with closing(self._connect(create=new)) as conn:
            if new:
                conn.executescript('''
                    CREATE TABLE events(seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, sha TEXT NOT NULL);
                    CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
                    CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
                ''')
                conn.commit()
            self._audit(conn)

    def _safe_path(self) -> None:
        source_root = Path(__file__).resolve().parent
        if (not self.path.is_absolute() or not self.path.name.startswith('overnight_research_')
                or self.path.suffix != '.sqlite' or self.path.resolve().is_relative_to(source_root)
                or any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
                       for p in (self.path, *self.path.parents))):
            raise ResearchError('PRIVATE_TRIAL_PATH_REQUIRED')

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        self._safe_path()
        if not create and not self.path.is_file():
            raise ResearchError('TRIAL_LEDGER_MISSING')
        if self.path.exists() and self.path.stat().st_size > 64 * 1024 * 1024:
            raise ResearchError('TRIAL_LEDGER_CAPACITY_REVIEW_REQUIRED')
        conn = sqlite3.connect(self.path.as_uri() + ('?mode=rwc' if create else '?mode=rw'), uri=True, timeout=2)
        conn.execute('PRAGMA synchronous=FULL')
        return conn

    def _audit(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        from dataclasses import asdict
        expected = {
            'events_no_update': "CREATE TRIGGER events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END",
            'events_no_delete': "CREATE TRIGGER events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END",
        }
        def normalize(value: str) -> str:
            return ''.join(value.split()).lower().rstrip(';')
        triggers = dict(conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        if (set(triggers) != set(expected)
                or any(normalize(triggers[name]) != normalize(sql) for name, sql in expected.items())):
            raise ResearchError('TRIAL_APPEND_GUARDS_MISSING')
        previous, events, states = None, [], {}
        for expected_seq, (seq, payload, digest) in enumerate(conn.execute('SELECT seq,payload,sha FROM events ORDER BY seq'), 1):
            if expected_seq > 8192 or len(payload) > 256 * 1024:
                raise ResearchError('TRIAL_LEDGER_CAPACITY_REVIEW_REQUIRED')
            event = json.loads(payload, object_pairs_hook=unique_pairs)
            if (seq != expected_seq or fingerprint(event) != digest or event.get('previous_sha256') != previous
                    or event.get('seq') != seq or canonical(event).decode() != payload
                    or any(event.get(flag) is not False for flag in ('training_eligible', 'approval_authority'))):
                raise ResearchError('TRIAL_LEDGER_CORRUPT')
            trial_id, state = event['trial_id'], event['state']
            if state == 'STARTED':
                if (trial_id in states or event.get('reference_kind') not in
                        ('DATASET_MANIFEST', 'REJECTED_INPUT_SHAPE')):
                    raise ResearchError('TRIAL_LEDGER_CORRUPT')
                spec = ModelSpec(**{**event['spec'], 'feature_names': tuple(event['spec']['feature_names'])})
                if spec.identity() != event['model_sha256']:
                    raise ResearchError('TRIAL_LEDGER_CORRUPT')
                if fingerprint([asdict(Fold(**{**f, 'train': tuple(f['train']), 'test': tuple(f['test']),
                                             'purged': tuple(f['purged'])})) for f in event['folds']]) != event['folds_sha256']:
                    raise ResearchError('TRIAL_LEDGER_CORRUPT')
                states[trial_id] = event
            elif state in ('COMPLETED', 'FAILED', 'INSUFFICIENT_DATA'):
                start = states.get(trial_id)
                if (start is None or start['state'] != 'STARTED'
                        or event['started_event_sha256'] != start['event_sha256']
                        or instant(event['at']) < instant(start['at'])):
                    raise ResearchError('TRIAL_LEDGER_CORRUPT')
                states[trial_id] = event
            else:
                raise ResearchError('TRIAL_LEDGER_CORRUPT')
            previous = digest
            events.append({**event, 'event_sha256': digest})
            states[trial_id]['event_sha256'] = digest
        return events

    def _append(self, conn: sqlite3.Connection, events: Sequence[Mapping[str, Any]], body: Mapping[str, Any]) -> str:
        event = {**body, 'seq': len(events)+1,
            'previous_sha256': events[-1]['event_sha256'] if events else None,
            'training_eligible': False, 'approval_authority': False}
        digest = fingerprint(event)
        if len(events) >= 8192 or len(canonical(event)) > 256 * 1024:
            raise ResearchError('TRIAL_LEDGER_CAPACITY_REVIEW_REQUIRED')
        conn.execute('INSERT INTO events VALUES(?,?,?)', (event['seq'], canonical(event).decode(), digest))
        conn.commit()  # Unknown COMMIT must be audited, never automatically resent.
        return digest

    def start(self, *, trial_id: str, spec: ModelSpec, dataset_sha256: str,
              folds: Sequence[Fold], started_at: str,
              reference_kind: str = 'DATASET_MANIFEST') -> str:
        from dataclasses import asdict
        model_id = spec.identity()
        sha(dataset_sha256)
        started = instant(started_at)
        if (not trial_id or instant(spec.registered_at) > started
                or reference_kind not in ('DATASET_MANIFEST', 'REJECTED_INPUT_SHAPE')):
            raise ResearchError('TRIAL_START_INVALID')
        with closing(self._connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            events = self._audit(conn)
            if any(event['trial_id'] == trial_id for event in events):
                raise ResearchError('TRIAL_ALREADY_STARTED')
            return self._append(conn, events, {'trial_id': trial_id, 'state': 'STARTED', 'at': started.isoformat(),
                'spec': asdict(spec), 'model_sha256': model_id, 'dataset_sha256': dataset_sha256,
                'reference_kind': reference_kind,
                'folds': [asdict(fold) for fold in folds],
                'folds_sha256': fingerprint([asdict(fold) for fold in folds])})

    def finish(self, *, trial_id: str, completed_at: str, status: str,
               metrics: Mapping[str, float], failure_code: str | None = None) -> str:
        completed = instant(completed_at)
        if (status not in ('COMPLETED', 'FAILED', 'INSUFFICIENT_DATA')
                or (status != 'COMPLETED' and metrics)
                or (status == 'FAILED' and not failure_code)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in metrics.values())):
            raise ResearchError('TRIAL_COMPLETION_INVALID')
        with closing(self._connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            events = self._audit(conn)
            matching = [event for event in events if event['trial_id'] == trial_id]
            if not matching or matching[-1]['state'] != 'STARTED' or completed < instant(matching[0]['at']):
                raise ResearchError('TRIAL_NOT_STARTED_OR_ALREADY_FINISHED')
            if status == 'COMPLETED' and (not matching[0]['folds'] or any(
                    not fold['train'] or not fold['test'] for fold in matching[0]['folds'])
                    or matching[0]['reference_kind'] != 'DATASET_MANIFEST'):
                raise ResearchError('TRIAL_FOLDS_INSUFFICIENT')
            return self._append(conn, events, {'trial_id': trial_id, 'state': status,
                'at': completed.isoformat(), 'started_event_sha256': matching[0]['event_sha256'],
                'metrics': dict(metrics), 'failure_code': failure_code})

    def events(self) -> tuple[dict[str, Any], ...]:
        with closing(self._connect()) as conn:
            return tuple(self._audit(conn))

    def unresolved_trials(self) -> tuple[str, ...]:
        states = {event['trial_id']: event['state'] for event in self.events()}
        return tuple(sorted(trial_id for trial_id, state in states.items() if state == 'STARTED'))
