"""Opt-in research producer: immutable received versions and frozen observations.

Separate journal/format. Never edits first-seen capture, backfills missed slots,
places orders, approves trades, or establishes provider finality/training labels.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterator, cast

from forward_nifty_producer import ROOT, evaluate_prefix, validate_config
from forward_revision_policy import project, specification
from forward_revision_quarantine import snapshot, verify as verify_snapshot
from release_verification import release_members
from research_integrity import IntegrityError, canonical, digest, hash_value
from research_replay_comparison import Observation, instant

FORMAT = 'forward-versioned-research-bundle-v1'
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
FILES = ('forward_versioned_producer.py', 'forward_versioned_capture.py')


def environment(root: Path) -> dict[str, str]:
    """Pin transitive adapter/policy/math sources; no key discovery or network."""
    return {name: digest((root / name).read_bytes().replace(b'\r\n', b'\n'))
            for name in cast(Callable[[Path, tuple[str, ...]], list[str]], release_members)(root, FILES)}


def recipe(config: dict[str, Any], frozen_at: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Freeze a NEW opt-in interpretation before open, never revise an old recipe."""
    validate_config(config, root)
    at = instant(frozen_at)
    if not instant(config['frozen_at']) <= at < instant(config['session_open']):
        raise IntegrityError('VERSION_POLICY_PREOPEN_FREEZE_REQUIRED')
    return {'format': 'forward-versioned-recipe-v1', 'config_sha256': hash_value(config),
            'frozen_at': at.isoformat(), 'policy': specification(), 'sources': environment(root),
            'purpose': 'PROSPECTIVE_PARKED_RULE_OBSERVATIONS', 'training_eligible': False,
            'approval_authority': False, 'fill_evidence': False}


def validate_recipe(config: dict[str, Any], frozen: dict[str, Any], root: Path = ROOT) -> str:
    """Require exact source/policy/previous-close identity at each invocation."""
    if canonical(frozen) != canonical(recipe(config, frozen['frozen_at'], root=root)):
        raise IntegrityError('VERSION_POLICY_RECIPE_MISMATCH')
    return hash_value(frozen)


def _decision(config: dict[str, Any], frozen: dict[str, Any], sources: list[dict[str, Any]],
              computed_at: str) -> dict[str, Any] | None:
    last = sources[-1]
    projection = project(sources, last['received_at'])
    if projection['status'] == 'BLOCKED':
        return None  # Raw source remains visible; no synthetic decision fills the gap.
    prefix = [{'start': row['bar_start'], 'values': row['values'], 'available_at': row['known_at']}
              for row in projection['bars']]
    expected = instant(last['slot']) - timedelta(minutes=5)
    if not prefix or instant(prefix[-1]['start']) != expected:
        raise IntegrityError('VERSION_POLICY_LATEST_SLOT_MISMATCH')
    computed = instant(computed_at)
    if computed < instant(last['received_at']):
        raise IntegrityError('INVALID_COMPUTATION_RECEIPT')
    detail, direction, available = evaluate_prefix(config, prefix)
    observation = Observation(hash_value(frozen), config['session_open'], config['session_close'],
        last['slot'], last['received_at'], computed.isoformat(), projection['projection_sha256'],
        direction, available, hash_value(detail), 'recorded_bar_end', 'OBSERVED').normalized()
    return {'format': 'versioned-forward-observation-v1', 'observation': observation,
            'projection': projection, 'training_eligible': False, 'approval_authority': False,
            'fill_evidence': False, 'finality': 'NOT_ESTABLISHED'}


def verify(bundle: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    """Replay every frozen as-of input, not today's final/corrected history."""
    if (set(bundle) != {'format', 'config', 'recipe', 'polls', 'recorded_decisions',
                       'missing_decisions', 'expected_decisions', 'approval_authority',
                       'fill_evidence', 'training_eligible'}
            or bundle['format'] != FORMAT or type(bundle['polls']) is not list
            or not 0 <= len(bundle['polls']) <= 75
            or any(bundle[flag] is not False for flag in
                   ('approval_authority', 'fill_evidence', 'training_eligible'))
            or len(canonical(bundle)) > MAX_BUNDLE_BYTES):
        raise IntegrityError('VERSION_POLICY_BUNDLE_INVALID')
    validate_recipe(bundle['config'], bundle['recipe'], root)
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    count = 0
    for item in bundle['polls']:
        if set(item) != {'source', 'decision', 'computed_at'}:
            raise IntegrityError('VERSION_POLICY_POLL_INVALID')
        source = verify_snapshot(canonical(item['source']))
        if (source['config'] != bundle['config'] or source['accepted_baseline'] != []
                or source['capture_code_hash'] != hash_value(bundle['recipe'])
                or source['slot'] in seen
                or (sources and instant(source['received_at']) <= instant(sources[-1]['received_at']))):
            raise IntegrityError('VERSION_POLICY_SOURCE_IDENTITY_CONFLICT')
        seen.add(source['slot'])
        sources.append(source)
        if instant(item['computed_at']) < instant(source['received_at']):
            raise IntegrityError('INVALID_COMPUTATION_RECEIPT')
        if _decision(bundle['config'], bundle['recipe'], sources, item['computed_at']) != item['decision']:
            raise IntegrityError('VERSION_POLICY_DECISION_REPLAY_MISMATCH')
        count += item['decision'] is not None
    for field, value in (('expected_decisions', 75), ('recorded_decisions', count),
                         ('missing_decisions', 75 - count)):
        if type(bundle[field]) is not int or bundle[field] != value:
            raise IntegrityError('VERSION_POLICY_COUNTS_INVALID')
    return bundle


class Producer:
    """Atomic raw poll + frozen decision commits in a NEW versioned namespace."""

    def __init__(self, config: dict[str, Any], frozen: dict[str, Any], path: Path,
                 *, source_root: Path = ROOT) -> None:
        self.root, self.config, self.frozen = source_root, config, frozen
        self.identity = validate_recipe(config, frozen, source_root)
        self.path = path
        if (not path.is_absolute() or path.name != 'journal.sqlite'
                or path.parent.name != 'versioned-v1'
                or path.resolve().is_relative_to(source_root.resolve())
                or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))):
            raise IntegrityError('VERSION_POLICY_PRIVATE_NAMESPACE_REQUIRED')
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock():
            new = not path.exists()
            with closing(self._connect(create=new)) as conn:
                if new:
                    conn.executescript('''
                        CREATE TABLE metadata(id INTEGER PRIMARY KEY CHECK(id=1), recipe TEXT NOT NULL);
                        CREATE TABLE polls(slot TEXT PRIMARY KEY, payload TEXT NOT NULL, sha TEXT NOT NULL);
                        CREATE TRIGGER metadata_no_update BEFORE UPDATE ON metadata BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
                        CREATE TRIGGER metadata_no_delete BEFORE DELETE ON metadata BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
                        CREATE TRIGGER polls_no_update BEFORE UPDATE ON polls BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
                        CREATE TRIGGER polls_no_delete BEFORE DELETE ON polls BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
                    ''')
                    conn.execute('INSERT INTO metadata VALUES(1,?)', (canonical(frozen).decode(),))
                    conn.commit()
                if conn.execute('SELECT recipe FROM metadata WHERE id=1').fetchall() != [(canonical(frozen).decode(),)]:
                    raise IntegrityError('VERSION_POLICY_RECIPE_MISMATCH')
            self.bundle()  # Existing state must revalidate, never silently reset.

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        if (any(p.is_symlink() or p.is_junction() for p in (self.path, *self.path.parents))
                or (not create and not self.path.is_file())):
            raise IntegrityError('VERSION_POLICY_JOURNAL_MISSING_OR_UNSAFE')
        # Existing-state reads must never recreate a missing journal.
        conn = sqlite3.connect(self.path.as_uri() + ('?mode=rwc' if create else '?mode=rw'),
                               uri=True, timeout=2)
        conn.execute('PRAGMA synchronous=FULL')
        return conn

    @contextmanager
    def _lock(self) -> Iterator[None]:
        lock = self.path.with_suffix('.producer-lock')
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise IntegrityError('PRODUCER_ALREADY_RUNNING_OR_STALE_LOCK') from None
        try:
            yield
        finally:
            os.close(descriptor)
            lock.unlink()

    def _bundle(self, conn: sqlite3.Connection) -> dict[str, Any]:
        if conn.execute('SELECT recipe FROM metadata WHERE id=1').fetchall() != [(canonical(self.frozen).decode(),)]:
            raise IntegrityError('VERSION_POLICY_RECIPE_MISMATCH')
        polls = []
        for slot, payload, sha in conn.execute('SELECT slot,payload,sha FROM polls ORDER BY slot LIMIT 76'):
            if digest(payload.encode()) != sha:
                raise IntegrityError('VERSION_POLICY_JOURNAL_CORRUPT')
            item = json.loads(payload)
            if item['source']['slot'] != slot:
                raise IntegrityError('VERSION_POLICY_JOURNAL_CORRUPT')
            polls.append(item)
        triggers = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if triggers != {'metadata_no_update', 'metadata_no_delete', 'polls_no_update', 'polls_no_delete'}:
            raise IntegrityError('VERSION_POLICY_APPEND_GUARDS_MISSING')
        count = sum(item['decision'] is not None for item in polls)
        result = {'format': FORMAT, 'config': self.config, 'recipe': self.frozen, 'polls': polls,
                  'recorded_decisions': count, 'missing_decisions': 75-count, 'expected_decisions': 75,
                  'approval_authority': False, 'fill_evidence': False, 'training_eligible': False}
        return verify(result, root=self.root)

    def bundle(self) -> dict[str, Any]:
        """Verified logical export; original journal and raw quarantine untouched."""
        with closing(self._connect()) as conn:
            return self._bundle(conn)

    def record_poll(self, bars: list[list[Any]], *, received_at: str,
                    computed_clock: Callable[[], datetime]) -> dict[str, Any]:
        """Current slot only; later corrections affect only this new observation."""
        source = snapshot(self.config, bars, received_at, [], self.identity)
        with self._lock(), closing(self._connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                before = self._bundle(conn)
                if before['polls'] and instant(received_at) <= instant(before['polls'][-1]['source']['received_at']):
                    raise IntegrityError('RECEIPT_CLOCK_MOVED_BACKWARDS')
                if any(item['source']['slot'] == source['slot'] for item in before['polls']):
                    raise IntegrityError('VERSION_POLICY_SLOT_ALREADY_RECORDED')
                sources = [item['source'] for item in before['polls']] + [source]
                decision = _decision(self.config, self.frozen, sources, received_at)
                computed = computed_clock().isoformat()
                if instant(computed) < instant(received_at):
                    raise IntegrityError('INVALID_COMPUTATION_RECEIPT')
                if decision is not None:
                    decision['observation']['received_at'] = instant(computed).isoformat()
                item = {'source': source, 'computed_at': computed,
                        'decision': decision}
                payload = canonical(item)
                conn.execute('INSERT INTO polls VALUES(?,?,?)', (source['slot'], payload.decode(), digest(payload)))
                result = self._bundle(conn)
                conn.commit()  # Unknown COMMIT must be inspected, not automatically resent.
            except BaseException:
                conn.rollback()
                raise
        return {'status': 'VERSIONED_OBSERVATION_RECORDED' if item['decision'] is not None else 'VERSIONED_INPUT_BLOCKED',
                'recorded_decisions': result['recorded_decisions'], 'missing_decisions': result['missing_decisions'],
                '_versioned_bundle': result}


def publish(drive: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Verify full versioned generation and downloaded bytes before receipt."""
    bundle = result['_versioned_bundle']
    verify(bundle)
    raw = canonical(bundle)
    sha = digest(raw)
    data_id = drive.put('nifty-versioned-' + sha + '.json', raw, sha, 'data', 'application/json')
    if drive.download(data_id) != raw:
        raise IntegrityError('FORWARD_REMOTE_VERIFICATION_FAILED')
    manifest = {'format': 'forward-versioned-manifest-v1', 'status': 'REMOTE_VERIFIED',
                'sha256': sha, 'spec_hash': hash_value(bundle['recipe']), 'data_file_id': data_id,
                'recorded_decisions': bundle['recorded_decisions'], 'training_eligible': False,
                'approval_authority': False, 'fill_evidence': False}
    encoded = canonical(manifest)
    manifest_id = drive.put('nifty-versioned-manifest-' + sha + '.json', encoded, sha, 'manifest', 'application/json')
    if drive.download(manifest_id) != encoded:
        raise IntegrityError('FORWARD_MANIFEST_VERIFICATION_FAILED')
    return dict(manifest, manifest_file_id=manifest_id)
