"""Additive raw-only capture: immutable provider versions, never decision evidence.

The unchanged scheduler/job enforce calendar, slot, token, licence, source and
clock checks. Only persistence/publication are replaced in this isolated process.
No frozen module, config or accepted journal is edited. Preview is offline.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, datetime, timedelta
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable

from research_integrity import IntegrityError, canonical, digest, hash_value
from research_replay_comparison import instant

FORMAT = 'forward-provider-quarantine-v1'
MANIFEST = 'forward-provider-quarantine-manifest-v1'
MAX_BYTES = 2 * 1024 * 1024


def validate_values(values: Any) -> None:
    """Six finite numeric candle fields; boolean/string coercion is forbidden."""
    if not isinstance(values, list) or len(values) != 6:
        raise IntegrityError('CANDLE_SCHEMA_INVALID')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise IntegrityError('CANDLE_VALUES_INVALID')
    o, h, low, c, volume, oi = values
    if min(o, h, low, c) <= 0 or min(volume, oi) < 0 or low > min(o, c) or h < max(o, c):
        raise IntegrityError('CANDLE_OHLC_INVALID')


def snapshot(config: dict[str, Any], bars: list[list[Any]], received_at: str,
             baseline: list[dict[str, Any]], code_hash: str) -> dict[str, Any]:
    """Validate bounded source rows; retain both versions with real receipt times."""
    from forward_local_diagnostic import compare_candles
    from research_integrity import require_hash
    require_hash(code_hash)
    received = instant(received_at)
    opening, ending = instant(config['session_open']), instant(config['session_close'])
    slot = opening + timedelta(seconds=int((received - opening).total_seconds() // 300) * 300)
    if not opening < slot <= ending or not timedelta() <= received - slot <= timedelta(seconds=120):
        raise IntegrityError('MISSED_OR_OUTSIDE_POLL_SLOT')
    if not isinstance(bars, list) or not bars or len(bars) > 100 or len(baseline) > 75:
        raise IntegrityError('CANDLE_SCHEMA_INVALID')
    closed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for old in baseline:
        if set(old) != {'start', 'values', 'available_at'}:
            raise IntegrityError('FORWARD_INPUT_STORE_CORRUPT')
        start, available = instant(old['start']), instant(old['available_at'])
        if (not opening <= start < ending or (start - opening).total_seconds() % 300
                or not start + timedelta(minutes=5) <= available <= received):
            raise IntegrityError('FORWARD_INPUT_STORE_CORRUPT')
        validate_values(old['values'])
    for raw in bars:
        if not isinstance(raw, list) or len(raw) != 7:
            raise IntegrityError('CANDLE_SCHEMA_INVALID')
        start = instant(raw[0])
        key = start.isoformat()
        if key in seen or not opening <= start < ending or (start - opening).total_seconds() % 300:
            raise IntegrityError('CANDLE_GRID_INVALID')
        seen.add(key)
        values = raw[1:]
        validate_values(values)
        if start + timedelta(minutes=5) <= received:
            closed.append({'start': key, 'values': values, 'received_at': received.isoformat(),
                           'finality': 'NOT_ESTABLISHED'})
    if not closed:
        raise IntegrityError('CANDLE_SCHEMA_INVALID')
    result = {'format': FORMAT, 'record_type': 'QUARANTINED_PROVIDER_SNAPSHOT',
              'source': 'UPSTOX_V3_INTRADAY_NIFTY_INDEX_MINUTES_5',
              'config': config, 'original_spec_hash': hash_value(config),
              'capture_code_hash': code_hash, 'slot': slot.isoformat(),
              'received_at': received.isoformat(), 'provider_rows': bars,
              'provider_rows_sha256': hash_value(bars), 'closed_bars': closed,
              'accepted_baseline': baseline, 'baseline_sha256': hash_value(baseline),
              'revision_check': compare_candles(baseline, bars),
              'decisions_added': 0, 'approval_authority': False, 'fill_evidence': False,
              'training_eligible': False, 'finality': 'NOT_ESTABLISHED'}
    if len(canonical(result)) > MAX_BYTES:
        raise IntegrityError('LOCAL_STATE_SIZE_BOUND')
    return result


def verify(raw: bytes) -> dict[str, Any]:
    """Rebuild all derived fields; reject tampering or promotion to decision evidence."""
    if not raw or len(raw) > MAX_BYTES:
        raise IntegrityError('LOCAL_STATE_SIZE_BOUND')
    record = json.loads(raw)
    if not isinstance(record, dict) or record.get('format') != FORMAT:
        raise IntegrityError('ARCHIVE_SCHEMA_INVALID')
    rebuilt = snapshot(record['config'], record['provider_rows'], record['received_at'],
                       record['accepted_baseline'], record['capture_code_hash'])
    if canonical(rebuilt) != raw:
        raise IntegrityError('ARCHIVE_CONTENT_INVALID')
    return record


def publish(drive: Any, result: dict[str, Any]) -> dict[str, Any]:
    """Verify downloaded snapshot and manifest before acknowledging raw-only custody."""
    record = result['_snapshot']
    raw = canonical(record)
    verify(raw)
    sha = digest(raw)
    drive.check_folder()
    data_id = drive.put('nifty-quarantine-' + sha + '.json', raw, sha,
                        'data', 'application/json')
    downloaded = drive.download(data_id)
    if downloaded != raw:
        raise IntegrityError('ARCHIVE_ACKNOWLEDGMENT_FAILED')
    verify(downloaded)
    manifest = {'format': MANIFEST, 'status': 'REMOTE_VERIFIED', 'sha256': sha,
                'data_file_id': data_id, 'original_spec_hash': record['original_spec_hash'],
                'slot': record['slot'], 'received_at': record['received_at'],
                'decisions_added': 0, 'approval_authority': False, 'fill_evidence': False,
                'training_eligible': False}
    encoded = canonical(manifest)
    manifest_id = drive.put('nifty-quarantine-manifest-' + sha + '.json', encoded, sha,
                            'manifest', 'application/json')
    if drive.download(manifest_id) != encoded:
        raise IntegrityError('ARCHIVE_ACKNOWLEDGMENT_FAILED')
    return dict(manifest, manifest_file_id=manifest_id)


class QuarantineProducer:
    """Read the accepted baseline; write only a separate, append-only raw namespace."""

    def __init__(self, config: dict[str, Any], journal_path: Path, archive: Any) -> None:
        from forward_local_diagnostic import inspect_session
        from forward_nifty_producer import ROOT, validate_config
        from zoneinfo import ZoneInfo
        self.config, self.state = config, journal_path.parent
        day = instant(config['session_open']).astimezone(ZoneInfo('Asia/Kolkata')).date()
        checked = inspect_session(self.state.parent.parent, day)
        if checked['producer_lock_exists']:
            raise IntegrityError('PRODUCER_ALREADY_RUNNING_OR_STALE_LOCK')
        self.identity = validate_config(config, ROOT)
        with closing(sqlite3.connect(journal_path.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
            conn.execute('PRAGMA query_only=ON')
            payloads = conn.execute('SELECT payload FROM forward_context ORDER BY bar_start LIMIT 76').fetchall()
        self.baseline = [json.loads(row[0]) for row in payloads]
        self.recorded = checked['counts']['observations']
        self.directory = self.state / 'quarantine-v1'
        for path in (self.directory, self.directory / 'receipts', self.directory / 'snapshots'):
            if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
                raise IntegrityError('LOCAL_STATE_PRIVATE_PATH_REQUIRED')
        self.code_hash = hash_value({name: digest((Path(__file__).parent / name).read_bytes())
                                     for name in ('forward_revision_quarantine.py', 'forward_local_diagnostic.py')})

    def record_poll(self, bars: list[list[Any]], *, received_at: str,
                    computed_clock: Callable[[], datetime]) -> dict[str, Any]:
        """No signals or journal writes. Duplicate slots block instead of overwriting."""
        from automated_development_checks import write_once
        record = snapshot(self.config, bars, received_at, self.baseline, self.code_hash)
        self.directory.mkdir(exist_ok=True)
        lock = self.directory / '.quarantine-lock'
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise IntegrityError('PRODUCER_ALREADY_RUNNING_OR_STALE_LOCK') from None
        try:
            policy = {'format': FORMAT, 'original_spec_hash': self.identity,
                      'capture_code_hash': self.code_hash, 'baseline_sha256': hash_value(self.baseline),
                      'approval_authority': False, 'training_eligible': False}
            policy_path = self.directory / 'policy.json'
            if policy_path.exists():
                if policy_path.stat().st_size > MAX_BYTES or policy_path.read_bytes() != canonical(policy):
                    raise IntegrityError('ARCHIVE_CONFLICT')
            else:
                write_once(policy_path, policy)
            target = self.directory / 'snapshots'
            target.mkdir(exist_ok=True)
            name = instant(record['slot']).strftime('%H%M') + '.json'
            if (target / name).exists():
                raise IntegrityError('QUARANTINE_SLOT_ALREADY_RECORDED')
            write_once(target / name, record)
        finally:
            os.close(descriptor)
            lock.unlink()
        return {'status': 'QUARANTINE_ONLY', 'recorded_decisions': self.recorded,
                'missing_decisions': 75 - self.recorded, '_snapshot': record}


def run(root: Path) -> int:
    """Process-scoped adapter: retain original scheduler/job admission gates."""
    import forward_nifty_job as job
    import forward_nifty_schedule as schedule
    from forward_local_diagnostic import local_category
    originals = {name: getattr(job, name) for name in ('Producer', 'publish', 'write_once', 'failure_category')}
    original_write: Callable[..., Any] = originals['write_once']
    def receipt_only(path: Path, record: dict[str, Any]) -> None:
        if path.parent.name != 'state' or not (path.name.startswith('receipt-') or path.name.startswith('failure-')):
            raise IntegrityError('LOCAL_STATE_PRIVATE_PATH_REQUIRED')
        directory = path.parent / 'quarantine-v1' / 'receipts'
        if any(p.is_symlink() or p.is_junction() for p in (directory, *directory.parents)):
            raise IntegrityError('LOCAL_STATE_PRIVATE_PATH_REQUIRED')
        directory.mkdir(parents=True, exist_ok=True)
        original_write(directory / path.name, record)
    def classify(error: Exception) -> str:
        if isinstance(error, IntegrityError) and str(error) == 'QUARANTINE_SLOT_ALREADY_RECORDED':
            return 'QUARANTINE_SLOT_ALREADY_RECORDED'
        previous: str = originals['failure_category'](error)
        return previous if previous != 'UNCLASSIFIED_FAILURE' else (local_category(error) or previous)
    replacements = {'Producer': QuarantineProducer, 'publish': publish,
                    'write_once': receipt_only, 'failure_category': classify}
    for name, value in replacements.items():
        setattr(job, name, value)
    try:
        print(json.dumps({'mode': 'QUARANTINE_ONLY', 'decisions_added': 0,
                          'training_eligible': False, 'approval_authority': False}))
        return schedule.main(['--root', str(root), '--mode', 'poll', '--confirm-run'])
    finally:
        for name, value in originals.items():
            setattr(job, name, value)


def main(argv: list[str] | None = None) -> int:
    """Explicit raw-only confirmation; no task installation, replay or catch-up."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--session-date', type=date.fromisoformat)
    parser.add_argument('--confirm-raw-quarantine', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_raw_quarantine:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'credential_reads': 0, 'writes': 0}))
        return 0
    try:
        import forward_nifty_schedule as schedule
        if args.session_date is None or schedule.now().astimezone(schedule.IST).date() != args.session_date:
            raise IntegrityError('OUTSIDE_RAW_CAPTURE_DATE')
        return run(args.root)
    except Exception as error:
        code = 'OUTSIDE_RAW_CAPTURE_DATE' if isinstance(error, IntegrityError) and str(error) == 'OUTSIDE_RAW_CAPTURE_DATE' else 'QUARANTINE_LAUNCHER_BLOCKED'
        print(json.dumps({'status': 'BLOCKED', 'code': code,
                          'decisions_added': 0, 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
