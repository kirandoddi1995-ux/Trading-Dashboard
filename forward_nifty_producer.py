"""Supervised NIFTY research decisions from actually received current-day bars."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, cast
from zoneinfo import ZoneInfo

import pandas as pd  # type: ignore[import-untyped]

from automated_directional_replay import replay_environment
from intraday_directional_replay import decisions
from nifty_session_calendar import cash_session as session
from nifty_previous_close import validate as validate_previous_close
from release_verification import release_members
from research_input_archive import InputArchive
from research_integrity import IntegrityError, canonical, digest, hash_value, require_hash
from research_replay_comparison import Observation, ObservationJournal, instant

ROOT = Path(__file__).resolve().parent
KEY = 'NSE_INDEX|Nifty 50'


def prepare_config(trading_date: str, previous_close: float, source_sha256: str,
                   frozen_at: str, *, root: Path = ROOT) -> dict[str, Any]:
    """Prepare an offline single-session recipe from an owner-verified close."""
    opening = datetime.fromisoformat(trading_date + 'T09:15:00').replace(tzinfo=ZoneInfo('Asia/Kolkata'))
    definition = cast(Callable[[Any], dict[str, Any]], session)(opening.date())
    config = {'version': 'nifty-forward-v1', 'instrument_key': KEY,
              'session_open': opening.isoformat(), 'session_close': (opening + timedelta(minutes=375)).isoformat(),
              'frozen_at': frozen_at, 'previous_close': previous_close,
              'previous_close_source_sha256': source_sha256, 'calendar_source': definition['source'],
              'environment': environment(root)}
    validate_config(config, root)
    return config


def environment(root: Path) -> dict[str, Any]:
    """Freeze transitive producer/math code as well as numeric dependencies."""
    result = replay_environment(root)
    names = cast(Callable[[Path, tuple[str, ...]], list[str]], release_members)(root, (
        'forward_nifty_producer.py', 'forward_nifty_archive.py', 'forward_nifty_job.py',
        'forward_nifty_schedule.py', 'forward_windows_credentials.py'))
    result['sources'].update({name: digest((root / name).read_bytes().replace(b'\r\n', b'\n')) for name in names})
    return result


def validate_config(config: dict[str, Any], root: Path) -> str:
    """Single regular session after freeze; no historical retrospective producer."""
    keys = {'version', 'instrument_key', 'session_open', 'session_close', 'frozen_at',
                       'previous_close', 'previous_close_source_sha256', 'calendar_source', 'environment'}
    if config.get('version') == 'nifty-forward-v2':
        keys.add('previous_close_provenance')
    if (set(config) != keys
            or config['version'] not in ('nifty-forward-v1', 'nifty-forward-v2') or config['instrument_key'] != KEY
            or config['environment'] != environment(root)):
        raise IntegrityError('FORWARD_CONFIG_MISMATCH')
    opening, closing, frozen = map(instant, (config['session_open'], config['session_close'], config['frozen_at']))
    local = opening.astimezone(ZoneInfo('Asia/Kolkata'))
    definition = cast(Callable[[Any], dict[str, Any]], session)(local.date())
    if (definition['kind'] != 'REGULAR' or definition['windows'] != [('09:15', '15:30')]
            or config['calendar_source'] != definition['source']
            or local.strftime('%H:%M:%S') != '09:15:00' or local.microsecond
            or closing - opening != timedelta(minutes=375) or frozen > opening):
        raise IntegrityError('VERIFIED_PROSPECTIVE_REGULAR_SESSION_REQUIRED')
    previous = config['previous_close']
    if type(previous) not in (int, float) or not math.isfinite(previous) or previous <= 0:
        raise IntegrityError('VERIFIED_PREVIOUS_CLOSE_REQUIRED')
    require_hash(config['previous_close_source_sha256'])
    if config['version'] == 'nifty-forward-v2':
        value = validate_previous_close(config['previous_close_provenance'], local.date(), config['frozen_at'])
        if value != previous or config['previous_close_provenance']['sha256'] != config['previous_close_source_sha256']:
            raise IntegrityError('NSE_CLOSE_CONFIG_MISMATCH')
    return hash_value(config)


def evaluate_prefix(config: dict[str, Any], prefix: list[dict[str, Any]]) -> tuple[dict[str, Any], int, bool]:
    """Reproduce one decision from only its received prefix, never later bars."""
    opening = instant(config['session_open'])
    complete = [instant(row['start']) for row in prefix] == [opening + timedelta(minutes=5*i) for i in range(len(prefix))]
    if not complete or not prefix:
        return {'bias': 'Unavailable', 'decision_reason': 'MISSING_PREFIX_BARS'}, 0, False
    if len(prefix) < 60:
        return {'bias': 'Unavailable', 'decision_reason': 'INDICATOR_OR_SESSION_TREND_WARMUP'}, 0, False
    frame = pd.DataFrame([dict(zip(('Open', 'High', 'Low', 'Close'), row['values'][:4]),
                               available_at=instant(row['available_at'])) for row in prefix],
                         index=pd.DatetimeIndex([instant(row['start']) for row in prefix]))
    frame['end'] = frame.index + pd.Timedelta(minutes=5)
    supplied = {'previous_close': config['previous_close'], 'reset_warmup': True}
    prepared = cast(Callable[[Any], list[Any]], decisions)([(supplied, frame)])
    decision = prepared[0][2][-1]
    return decision['detail'], decision['direction'], decision['available']


class Producer:
    """Local FULL-sync input persistence plus append-only research journal.

    No suggestions/orders, no historical decision backfill, no overnight positions.
    Only the newest completed bar received in a poll emits a decision. Older bars
    are retained as first-seen context; their earlier availability is never guessed.
    Revisions to committed closed bars block, rather than rewriting past evidence.
    """

    def __init__(self, config: dict[str, Any], journal_path: Path, archive: InputArchive,
                 *, source_root: Path = ROOT) -> None:
        self.identity = validate_config(config, source_root)
        self.config, self.archive = config, archive
        self.journal = ObservationJournal(journal_path)
        with closing(self.journal.connect()) as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS forward_context (
                    spec_hash TEXT NOT NULL, bar_start TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    PRIMARY KEY(spec_hash,bar_start));
                CREATE TRIGGER IF NOT EXISTS forward_no_update BEFORE UPDATE ON forward_context
                    BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS forward_no_delete BEFORE DELETE ON forward_context
                    BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
            ''')

    def context(self) -> list[dict[str, Any]]:
        """Verify first-seen inputs before reuse/restart; no price overwrites."""
        with closing(self.journal.connect()) as conn:
            rows = conn.execute('SELECT bar_start,payload,payload_hash FROM forward_context '
                                'WHERE spec_hash=? ORDER BY bar_start', (self.identity,)).fetchall()
        result: list[dict[str, Any]] = []
        for start, payload, sha in rows:
            row = json.loads(payload)
            if digest(payload.encode()) != sha or row['start'] != start:
                raise IntegrityError('FORWARD_INPUT_STORE_CORRUPT')
            result.append(row)
        return result

    def record_poll(self, candles: list[list[Any]], *, received_at: str,
                    computed_clock: Callable[[], datetime]) -> dict[str, Any]:
        """Commit inputs before return; real receipt times, no forming bars or fills."""
        lock = self.journal.path.with_suffix('.producer-lock')
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise IntegrityError('PRODUCER_ALREADY_RUNNING_OR_STALE_LOCK') from None
        try:
            return self._record_poll(candles, received_at=received_at, computed_clock=computed_clock)
        finally:
            os.close(descriptor)
            lock.unlink()  # Only this invocation's lock; never evidence/history.

    def _record_poll(self, candles: list[list[Any]], *, received_at: str,
                     computed_clock: Callable[[], datetime]) -> dict[str, Any]:
        """Single writer owns input commit, prefix archival and journal emission."""
        receipt = instant(received_at)
        opening, session_end = map(instant, (self.config['session_open'], self.config['session_close']))
        if not opening <= receipt <= session_end + timedelta(minutes=15) or len(candles) > 100:
            raise IntegrityError('FORWARD_POLL_OUTSIDE_BOUNDS')
        if any(instant(row['available_at']) > receipt for row in self.context()):
            raise IntegrityError('RECEIPT_CLOCK_MOVED_BACKWARDS')
        records: list[dict[str, Any]] = []
        seen: set[datetime] = set()
        for raw in candles:
            if not isinstance(raw, list) or len(raw) != 7:
                raise IntegrityError('CANDLE_SCHEMA_INVALID')
            start = instant(raw[0])
            if start in seen or not opening <= start < session_end or (start - opening).total_seconds() % 300:
                raise IntegrityError('CANDLE_GRID_INVALID')
            seen.add(start)
            if start + timedelta(minutes=5) > receipt:
                continue  # Forming values are not interpreted or persisted.
            values = raw[1:]
            if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
                raise IntegrityError('CANDLE_VALUES_INVALID')
            o, h, low, c, volume, oi = values
            if min(o, h, low, c) <= 0 or min(volume, oi) < 0 or low > min(o, c) or h < max(o, c):
                raise IntegrityError('CANDLE_OHLC_INVALID')
            records.append({'start': start.isoformat(), 'values': values, 'available_at': receipt.isoformat()})
        with closing(self.journal.connect()) as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                for row in records:
                    old = conn.execute('SELECT payload,payload_hash FROM forward_context WHERE spec_hash=? AND bar_start=?',
                                       (self.identity, row['start'])).fetchone()
                    if old:
                        if digest(old[0].encode()) != old[1] or json.loads(old[0])['values'] != row['values']:
                            raise IntegrityError('CLOSED_BAR_REVISION_REVIEW_REQUIRED')
                    else:
                        payload = canonical(row).decode()
                        conn.execute('INSERT INTO forward_context VALUES (?,?,?,?)',
                                     (self.identity, row['start'], payload, digest(payload.encode())))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        context = self.context()
        if not records:
            return self.bundle('NO_COMPLETED_BAR', context)
        latest = max(row['start'] for row in records)
        target = next(row for row in context if row['start'] == latest)
        prefix = [row for row in context if row['start'] <= latest]
        end = instant(latest) + timedelta(minutes=5)
        captured = self.journal.read(self.identity, self.config['session_open'])
        if any(instant(row.decision_at) == end for row in captured):
            return self.bundle('IDEMPOTENT_OBSERVATION', context)
        detail, direction, available = evaluate_prefix(self.config, prefix)
        computed = computed_clock()
        if computed.tzinfo is None or computed < receipt:
            raise IntegrityError('INVALID_COMPUTATION_RECEIPT')
        bundle = {'version': 'forward-consumed-prefix-v1', 'config': self.config, 'bars': prefix}
        stored = self.archive.put(canonical(bundle))
        observation = Observation(self.identity, self.config['session_open'], self.config['session_close'],
                                  end.isoformat(), target['available_at'], computed.isoformat(), stored['sha256'],
                                  direction, available, hash_value(detail), 'recorded_bar_end', 'OBSERVED')
        self.journal.record(observation)
        return self.bundle('OBSERVATION_RECORDED', context)

    def bundle(self, status: str, context: list[dict[str, Any]]) -> dict[str, Any]:
        """Logical journal backup with immutable input references; not live approval."""
        observations = [row.normalized() for row in self.journal.read(self.identity, self.config['session_open'])]
        return {'format': 'forward-nifty-bundle-v1', 'status': status, 'config': self.config,
                'spec_hash': self.identity, 'bars': context, 'observations': observations,
                'mode': 'RESEARCH_ONLY', 'approval_authority': False, 'fill_evidence': False,
                'expected_decisions': 75, 'recorded_decisions': len(observations),
                'missing_decisions': 75-len(observations), 'timing_basis': 'ACTUAL_FIRST_RECEIPT'}
