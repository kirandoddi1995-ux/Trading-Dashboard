"""Private observation journal and exact replay checks; never execution evidence."""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

from research_integrity import IntegrityError, canonical, digest, hash_value, require_hash


def instant(value: str) -> datetime:
    """Normalize aware instants; naive time is never assumed to be IST."""
    if not isinstance(value, str):
        raise IntegrityError('TIMESTAMP_STRING_REQUIRED')
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise IntegrityError('INVALID_TIMESTAMP') from None
    if result.tzinfo is None:
        raise IntegrityError('AWARE_TIMESTAMP_REQUIRED')
    return result.astimezone(timezone.utc)


def regular_boundary(opening: datetime, closing: datetime) -> None:
    """Validate supplied regular-session bounds, not an exchange holiday calendar."""
    local = opening.astimezone(ZoneInfo('Asia/Kolkata'))
    if local.time().isoformat() != '09:15:00' or closing - opening != timedelta(minutes=375):
        raise IntegrityError('REGULAR_SESSION_BOUNDARY_REQUIRED')


@dataclass(frozen=True)
class Observation:
    """An emitted completed-bar research decision, not a recommendation/fill.

    input_hash binds the actually consumed input prefix, including previous-close,
    history/warmup, session boundary and availability basis. Hashing just the latest bar
    is insufficient. received_at records capture/computation time; origin distinguishes
    an observed decision from a reconstructed reference. Neither is execution evidence.
    Exact equality only diagnoses reproducibility; it never validates profitability.
    """

    spec_hash: str
    session_open: str
    session_close: str
    decision_at: str
    available_at: str
    received_at: str
    input_hash: str
    direction: int
    available: bool
    detail_hash: str
    basis: str
    origin: str

    def normalized(self) -> dict[str, Any]:
        """Validate and canonicalize identity/timing without inventing defaults."""
        for value in (self.spec_hash, self.input_hash, self.detail_hash):
            require_hash(value)
        if type(self.direction) is not int or self.direction not in (-1, 0, 1):
            raise IntegrityError('DIRECTION_REQUIRED')
        if type(self.available) is not bool or (not self.available and self.direction != 0):
            raise IntegrityError('AVAILABILITY_DIRECTION_CONFLICT')
        if self.basis not in ('recorded_bar_end', 'historical_final_assumed_bar_end'):
            raise IntegrityError('AVAILABILITY_BASIS_REQUIRED')
        if self.origin not in ('OBSERVED', 'REPLAY'):
            raise IntegrityError('OBSERVATION_ORIGIN_REQUIRED')
        opening, closing, decision, available, received = map(instant, (
            self.session_open, self.session_close, self.decision_at, self.available_at, self.received_at))
        regular_boundary(opening, closing)
        if (not opening < decision <= closing
                or (decision - opening).total_seconds() % 300 != 0):
            raise IntegrityError('REGULAR_COMPLETED_BAR_BOUNDARY_REQUIRED')
        if available < decision or received < available:
            raise IntegrityError('OBSERVATION_BEFORE_AVAILABILITY')
        result = asdict(self)
        for key, moment in zip(('session_open', 'session_close', 'decision_at', 'available_at', 'received_at'),
                              (opening, closing, decision, available, received)):
            result[key] = moment.isoformat()
        result.update(record_type='RESEARCH_OBSERVATION' if self.origin == 'OBSERVED' else 'REPLAY_REFERENCE',
                      approval_authority=False, fill_evidence=False)
        return result


class ObservationJournal:
    """Append-only local snapshots with atomic idempotency/conflict checking.

    No account, order or credential fields are accepted. Not wired to the live
    app. Local file survival/backups remain necessary; this is not a remote ledger.
    """

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        if path.resolve().is_relative_to(Path(__file__).resolve().parent):
            raise IntegrityError('PRIVATE_OBSERVATIONS_OUTSIDE_REPOSITORY_REQUIRED')
        if type(read_only) is not bool:
            raise IntegrityError('BOOLEAN_READ_ONLY_REQUIRED')
        self.path = path
        self.read_only = read_only
        if read_only:
            if not path.is_file():
                raise IntegrityError('OBSERVATION_JOURNAL_MISSING')
            with closing(self.connect()) as connection:
                connection.execute('SELECT spec_hash,session_open,decision_at,record_json,record_hash '
                                   'FROM observations LIMIT 0')
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS observations (
                    spec_hash TEXT NOT NULL, session_open TEXT NOT NULL,
                    decision_at TEXT NOT NULL, record_json TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    PRIMARY KEY(spec_hash,session_open,decision_at)
                );
                CREATE TRIGGER IF NOT EXISTS observations_no_update
                BEFORE UPDATE ON observations BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS observations_no_delete
                BEFORE DELETE ON observations BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
            ''')

    def connect(self) -> sqlite3.Connection:
        """Bounded durable local connection; callers close it deterministically."""
        if self.read_only:
            return sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True,
                                   timeout=5, isolation_level=None)
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute('PRAGMA synchronous=FULL')
        return connection

    def record(self, observation: Observation) -> str:
        """Acknowledge an identical retry; never overwrite contradictory evidence."""
        if self.read_only:
            raise IntegrityError('OBSERVATION_JOURNAL_READ_ONLY')
        record = observation.normalized()
        if observation.origin != 'OBSERVED':
            raise IntegrityError('REPLAY_CANNOT_SATISFY_OBSERVATION_JOURNAL')
        payload = canonical(record).decode()
        key = tuple(record[field] for field in ('spec_hash', 'session_open', 'decision_at'))
        with closing(self.connect()) as connection:
            connection.execute('BEGIN IMMEDIATE')
            try:
                old = connection.execute('SELECT record_json,record_hash FROM observations WHERE '
                                         'spec_hash=? AND session_open=? AND decision_at=?', key).fetchone()
                if old:
                    if digest(old[0].encode()) != old[1]:
                        raise IntegrityError('OBSERVATION_STORE_CORRUPT')
                    if old[0] != payload:
                        raise IntegrityError('OBSERVATION_CONFLICT')
                    outcome = 'IDEMPOTENT_SUCCESS'
                else:
                    connection.execute('INSERT INTO observations VALUES (?,?,?,?,?)',
                                       (*key, payload, digest(payload.encode())))
                    outcome = 'NEW'
                connection.commit()
                return outcome
            except BaseException:
                connection.rollback()
                raise

    def read(self, spec_hash: str, session_open: str) -> list[Observation]:
        """Verify stored payloads and indexed identities before returning a session."""
        require_hash(spec_hash)
        opening = instant(session_open).isoformat()
        with closing(self.connect()) as connection:
            rows = connection.execute('SELECT decision_at,record_json,record_hash FROM observations '
                                      'WHERE spec_hash=? AND session_open=? ORDER BY decision_at',
                                      (spec_hash, opening)).fetchall()
        result = []
        for at, text, sha in rows:
            if digest(text.encode()) != sha:
                raise IntegrityError('OBSERVATION_STORE_CORRUPT')
            data = json.loads(text)
            if not isinstance(data, dict):
                raise IntegrityError('OBSERVATION_STORE_CORRUPT')
            if (data.pop('record_type', None) != 'RESEARCH_OBSERVATION'
                    or data.pop('approval_authority', None) is not False
                    or data.pop('fill_evidence', None) is not False):
                raise IntegrityError('OBSERVATION_CLASSIFICATION_CORRUPT')
            try:
                observation = Observation(**data)
                normalized = observation.normalized()
            except (TypeError, ValueError):
                raise IntegrityError('OBSERVATION_STORE_CORRUPT') from None
            if observation.origin != 'OBSERVED':
                raise IntegrityError('OBSERVATION_CLASSIFICATION_CORRUPT')
            if (normalized['spec_hash'], normalized['session_open'], normalized['decision_at']) != (spec_hash, opening, at):
                raise IntegrityError('OBSERVATION_IDENTITY_CORRUPT')
            result.append(observation)
        return result


def compare_session(*, spec_hash: str, session_open: str, session_close: str,
                    observed: list[Observation], replayed: list[Observation]) -> dict[str, Any]:
    """Compare all 75 expected decisions, including unavailable/warmup decisions.

    No selected-subset match rate: omissions remain visible in the denominator.
    Different input bundles/bases and delayed availability are NOT matches.
    This API never opens datasets, so it cannot itself unseal held-out files.
    """
    require_hash(spec_hash)
    opening, closing = instant(session_open), instant(session_close)
    expected = [opening + timedelta(minutes=5 * (number + 1)) for number in range(75)]
    regular_boundary(opening, closing)

    def index(rows: list[Observation], origin: str) -> dict[datetime, dict[str, Any]]:
        result: dict[datetime, dict[str, Any]] = {}
        for row in rows:
            value = row.normalized()
            if row.origin != origin:
                raise IntegrityError('COMPARISON_ORIGIN_MISMATCH')
            if (value['spec_hash'] != spec_hash or instant(value['session_open']) != opening
                    or instant(value['session_close']) != closing):
                raise IntegrityError('COMPARISON_IDENTITY_MISMATCH')
            at = instant(value['decision_at'])
            if at in result:
                raise IntegrityError('DUPLICATE_DECISION')
            result[at] = value
        return result

    live, replay = index(observed, 'OBSERVED'), index(replayed, 'REPLAY')
    counts = dict.fromkeys(('MATCH', 'MISSING_BOTH', 'MISSING_OBSERVATION', 'MISSING_REPLAY',
                           'INPUT_OR_BASIS_MISMATCH', 'DELAYED_AVAILABILITY', 'DECISION_MISMATCH'), 0)
    checks = []
    for at in expected:
        left, right = live.get(at), replay.get(at)
        if left is None or right is None:
            status = 'MISSING_BOTH' if left is None and right is None else (
                'MISSING_OBSERVATION' if left is None else 'MISSING_REPLAY')
        elif (left['input_hash'], left['basis']) != (right['input_hash'], right['basis']):
            status = 'INPUT_OR_BASIS_MISMATCH'
        elif instant(left['available_at']) != at or instant(right['available_at']) != at:
            status = 'DELAYED_AVAILABILITY'
        elif any(left[field] != right[field] for field in ('direction', 'available', 'detail_hash')):
            status = 'DECISION_MISMATCH'
        else:
            status = 'MATCH'
        counts[status] += 1
        checks.append({'decision_at': at.isoformat(), 'status': status,
                       'observed_available': left['available'] if left is not None else None,
                       'replay_available': right['available'] if right is not None else None,
                       'capture_lag_seconds': (instant(left['received_at']) - at).total_seconds()
                       if left is not None else None})
    paired = len(set(live) & set(replay))
    return {'version': 'research-comparison-v1', 'spec_hash': spec_hash,
            'status': 'MATCH' if counts['MATCH'] == 75 else 'INCOMPLETE_OR_DIFFERENT',
            'expected': 75, 'observed': len(live), 'replayed': len(replay), 'paired': paired,
            'available_decision_matches': sum(row['status'] == 'MATCH' and row['observed_available'] is True
                                              for row in checks),
            'unavailable_decision_matches': sum(row['status'] == 'MATCH' and row['observed_available'] is False
                                                for row in checks),
            'match_fraction_of_expected': counts['MATCH'] / 75 if paired else None,
            'counts': counts, 'checks': checks, 'approval_authority': False, 'fill_evidence': False,
            'comparison_hash': hash_value(checks)}
