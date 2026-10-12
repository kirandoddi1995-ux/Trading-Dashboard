"""Owner-confirmed local inspection or one normal poll with redacted diagnostics.

Additive launcher: never edit frozen modules/config, reset state, delete a lock,
catch up a missed slot, relax a revision check or change a scheduled task.
Import and default preview perform no credential, state or network operations.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date
import errno
import json
import math
from pathlib import Path
import sqlite3
from typing import Any


LOCAL_CODES = frozenset({
    'PRODUCER_ALREADY_RUNNING_OR_STALE_LOCK', 'FORWARD_INPUT_STORE_CORRUPT',
    'RECEIPT_CLOCK_MOVED_BACKWARDS', 'FORWARD_POLL_OUTSIDE_BOUNDS',
    'CANDLE_SCHEMA_INVALID', 'CANDLE_GRID_INVALID', 'CANDLE_VALUES_INVALID',
    'CANDLE_OHLC_INVALID', 'CLOSED_BAR_REVISION_REVIEW_REQUIRED',
    'INVALID_COMPUTATION_RECEIPT', 'OBSERVATION_STORE_CORRUPT',
    'OBSERVATION_IDENTITY_CORRUPT', 'OBSERVATION_CLASSIFICATION_CORRUPT',
    'OBSERVATION_CONFLICT', 'OBSERVATION_BEFORE_AVAILABILITY',
    'AWARE_TIMESTAMP_REQUIRED', 'INVALID_TIMESTAMP', 'TIMESTAMP_STRING_REQUIRED',
    'ARCHIVE_CONTENT_INVALID', 'ARCHIVE_SCHEMA_INVALID', 'ARCHIVE_CONFLICT',
    'ARCHIVE_ACKNOWLEDGMENT_FAILED', 'ARCHIVE_SYMLINK_FORBIDDEN',
    'FORWARD_CONFIG_MISMATCH', 'LOCAL_STATE_SIDECARS_REQUIRE_REVIEW',
    'LOCAL_STATE_SIZE_BOUND', 'LOCAL_STATE_IDENTITY_MISMATCH',
    'LOCAL_STATE_QUERY_BOUND', 'LOCAL_STATE_INTEGRITY_FAILED',
    'LOCAL_STATE_PRIVATE_PATH_REQUIRED', 'LOCAL_STATE_INPUT_MISSING',
})


def local_category(error: Exception) -> str | None:
    """Fixed codes only. Never print exception messages, SQL, paths or prices."""
    from research_integrity import IntegrityError
    if isinstance(error, IntegrityError) and str(error) in LOCAL_CODES:
        return str(error)
    if isinstance(error, sqlite3.Error):
        code = getattr(error, 'sqlite_errorcode', None)
        if type(code) is int:
            return {sqlite3.SQLITE_BUSY: 'LOCAL_SQLITE_BUSY',
                    sqlite3.SQLITE_LOCKED: 'LOCAL_SQLITE_LOCKED',
                    sqlite3.SQLITE_READONLY: 'LOCAL_SQLITE_READONLY',
                    sqlite3.SQLITE_FULL: 'LOCAL_SQLITE_FULL',
                    sqlite3.SQLITE_CORRUPT: 'LOCAL_SQLITE_CORRUPT',
                    sqlite3.SQLITE_NOTADB: 'LOCAL_SQLITE_NOT_DATABASE',
                    sqlite3.SQLITE_CONSTRAINT: 'LOCAL_SQLITE_CONSTRAINT',
                    sqlite3.SQLITE_ERROR: 'LOCAL_SQLITE_SCHEMA_OR_QUERY_ERROR',
                    sqlite3.SQLITE_IOERR: 'LOCAL_SQLITE_IO_ERROR'}.get(code & 255, 'LOCAL_SQLITE_OTHER')
        return 'LOCAL_SQLITE_OTHER'
    if isinstance(error, OSError):
        if error.errno is None:
            return 'LOCAL_FILE_IO_ERROR'
        return {errno.ENOSPC: 'LOCAL_DISK_FULL', errno.EACCES: 'LOCAL_PERMISSION_DENIED',
                errno.EPERM: 'LOCAL_PERMISSION_DENIED', errno.ENOENT: 'LOCAL_FILE_MISSING',
                errno.EEXIST: 'LOCAL_FILE_ALREADY_EXISTS'}.get(error.errno, 'LOCAL_FILE_IO_ERROR')
    return None


def inspect_session(root: Path, day: date) -> dict[str, Any]:
    """Paused-writer, bounded SELECT-only check; never repair or open a missing DB."""
    from forward_nifty_producer import ROOT, validate_config
    from research_integrity import IntegrityError, digest
    from research_replay_comparison import ObservationJournal
    from research_input_archive import InputArchive

    def private(path: Path) -> None:
        if (not path.is_absolute() or path.resolve().is_relative_to(ROOT)
                or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))):
            raise IntegrityError('LOCAL_STATE_PRIVATE_PATH_REQUIRED')

    private(root)
    config_path = root / day.isoformat() / 'config.json'
    state = config_path.parent / 'state'
    journal_path = state / 'observations.sqlite'
    for path in (config_path, state, journal_path):
        private(path)
    if config_path.stat().st_size > 1024 * 1024 or not 0 < journal_path.stat().st_size <= 64 * 1024 * 1024:
        raise IntegrityError('LOCAL_STATE_SIZE_BOUND')
    if any(Path(str(journal_path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise IntegrityError('LOCAL_STATE_SIDECARS_REQUIRE_REVIEW')
    config = json.loads(config_path.read_bytes())
    identity = validate_config(config, ROOT)
    from research_replay_comparison import instant
    from zoneinfo import ZoneInfo
    if instant(config['session_open']).astimezone(ZoneInfo('Asia/Kolkata')).date() != day:
        raise IntegrityError('LOCAL_STATE_IDENTITY_MISMATCH')
    with closing(sqlite3.connect(journal_path.as_uri() + '?mode=ro', uri=True,
                               timeout=2, isolation_level=None)) as connection:
        connection.execute('PRAGMA query_only=ON')
        budget = 0
        def bounded() -> int:
            nonlocal budget
            budget += 1
            return int(budget > 1000)
        connection.set_progress_handler(bounded, 1000)
        connection.execute('BEGIN')
        if connection.execute('PRAGMA quick_check(1)').fetchone() != ('ok',):
            raise IntegrityError('LOCAL_STATE_INTEGRITY_FAILED')
        counts = {table: connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                  for table in ('observations', 'forward_context')}
        if any(not 0 <= count <= 75 for count in counts.values()):
            raise IntegrityError('LOCAL_STATE_SIZE_BOUND')
        context = connection.execute('SELECT spec_hash,bar_start,payload,payload_hash FROM forward_context').fetchall()
        for spec, start, payload, sha in context:
            if spec != identity or digest(payload.encode()) != sha or json.loads(payload)['start'] != start:
                raise IntegrityError('FORWARD_INPUT_STORE_CORRUPT')
        connection.rollback()
    # Caller must keep writers paused across the check; no concurrent-cut claim.
    rows = ObservationJournal(journal_path, read_only=True).read(identity, config['session_open'])
    if len(rows) != counts['observations']:
        raise IntegrityError('LOCAL_STATE_IDENTITY_MISMATCH')
    inputs = state / 'inputs'
    private(inputs)
    class ReadOnlyInputs(InputArchive):
        def __init__(self, path: Path) -> None:
            if not path.is_dir():
                raise IntegrityError('LOCAL_STATE_INPUT_MISSING')
            self.root = path
    archive = ReadOnlyInputs(inputs)
    for row in rows:
        archive.get(row.input_hash)
    return {'status': 'LOCAL_STATE_STRUCTURE_CHECK_PASSED', 'counts': counts,
            'producer_lock_exists': journal_path.with_suffix('.producer-lock').exists(),
            'input_references_verified': len(rows), 'network_calls': 0,
            'credential_reads': 0, 'writes': 0, 'approval_authority': False,
            'provider_revision_check': 'REQUIRES_FRESH_POLL', 'resume_authorised': False}


def compare_candles(context: list[dict[str, Any]], bars: list[list[Any]]) -> dict[str, Any]:
    """Compare numeric fields exactly as the producer does; expose no field values.

    Timestamp offsets and numeric int/float representation are not revisions.
    This report is diagnostic only: it cannot authorise capture or amend evidence.
    """
    from research_integrity import IntegrityError
    from research_replay_comparison import instant
    if len(context) > 75 or len(bars) > 100:
        raise IntegrityError('LOCAL_STATE_SIZE_BOUND')
    fields = ('open', 'high', 'low', 'close', 'volume', 'open_interest')
    old: dict[str, list[Any]] = {}
    for item in context:
        start = instant(item['start']).isoformat()
        values = item['values']
        if start in old or not isinstance(values, list) or len(values) != 6:
            raise IntegrityError('FORWARD_INPUT_STORE_CORRUPT')
        old[start] = values
    seen: set[str] = set()
    revisions: list[dict[str, Any]] = []
    matched = 0
    for bar in bars:
        if not isinstance(bar, list) or len(bar) != 7:
            raise IntegrityError('CANDLE_SCHEMA_INVALID')
        start = instant(bar[0]).isoformat()
        if start in seen:
            raise IntegrityError('CANDLE_GRID_INVALID')
        seen.add(start)
        if start not in old:
            continue  # Only immutable, already-recorded closed bars are compared.
        values = bar[1:]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in [*old[start], *values]):
            raise IntegrityError('CANDLE_VALUES_INVALID')
        changed = [name for name, previous, current in zip(fields, old[start], values)
                   if previous != current]
        if changed:
            revisions.append({'bar_start': start, 'changed_fields': changed})
        else:
            matched += 1
    return {'status': 'PROVIDER_REVISION_FIELD_CHECK', 'stored_closed_bars': len(old),
            'matched_closed_bars': matched, 'revised_closed_bars': len(revisions),
            'stored_bars_absent_from_response': len(old.keys() - seen),
            'revisions': revisions, 'price_values_printed': False, 'writes': 0,
            'approval_authority': False, 'resume_authorised': False}


def revision_report(root: Path, bars: list[list[Any]]) -> dict[str, Any]:
    """Read and verify the paused journal before comparing an existing guarded GET."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    day = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    checked = inspect_session(root, day)
    if checked['producer_lock_exists']:
        from research_integrity import IntegrityError
        raise IntegrityError('PRODUCER_ALREADY_RUNNING_OR_STALE_LOCK')
    path = root / day.isoformat() / 'state' / 'observations.sqlite'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as connection:
        connection.execute('PRAGMA query_only=ON')
        payloads = connection.execute('SELECT payload FROM forward_context LIMIT 76').fetchall()
    return compare_candles([json.loads(row[0]) for row in payloads], bars)


def supervised_poll(root: Path) -> int:
    """Delegate to unchanged scheduler with process-local classifier injection only."""
    import forward_nifty_job as job
    import forward_nifty_schedule as schedule
    original = job.failure_category
    original_read = job.read_current
    def classify(error: Exception) -> str:
        previous = original(error)
        return previous if previous != 'UNCLASSIFIED_FAILURE' else (local_category(error) or previous)
    job.failure_category = classify
    def read_with_report(session: Any, token: str) -> list[list[Any]]:
        bars = original_read(session, token)
        try:
            print(json.dumps(revision_report(root, bars)))
        except Exception as error:
            # Diagnostic failures do not replace the unchanged producer checks.
            print(json.dumps({'status': 'REVISION_DIAGNOSTIC_BLOCKED',
                              'category': local_category(error) or 'LOCAL_DIAGNOSTIC_FAILED',
                              'resume_authorised': False, 'approval_authority': False}))
        return bars
    job.read_current = read_with_report
    try:
        return schedule.main(['--root', str(root), '--mode', 'poll', '--confirm-run'])
    finally:
        job.failure_category = original
        job.read_current = original_read


def main(argv: list[str] | None = None) -> int:
    """No implicit execution. Inspect never loads credentials; poll uses usual guard."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--mode', choices=('inspect', 'poll'), default='inspect')
    parser.add_argument('--session-date', type=date.fromisoformat)
    parser.add_argument('--confirm-run', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_run:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'credential_reads': 0, 'writes': 0}))
        return 0
    try:
        if args.mode == 'poll':
            if args.session_date is not None:
                raise ValueError
            return supervised_poll(args.root)
        if args.session_date is None:
            raise ValueError
        print(json.dumps(inspect_session(args.root, args.session_date)))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'BLOCKED', 'category': local_category(error) or 'LOCAL_DIAGNOSTIC_FAILED',
                          'approval_authority': False, 'resume_authorised': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
