"""Private bounded verified Drive backups; no database writes or deletion."""
from __future__ import annotations

import gzip
import io
import json
import argparse
import math
from datetime import timedelta
from contextlib import closing
from pathlib import Path
from typing import Any, Protocol, cast

from research_integrity import IntegrityError, canonical, digest, hash_value, require_hash
from research_replay_comparison import Observation, instant
from forward_nifty_producer import ROOT, Producer, evaluate_prefix, validate_config
from research_input_archive import InputArchive
from automated_development_checks import write_once

MAX_PACKED = 2 * 1024 * 1024
MAX_EXPANDED = 8 * 1024 * 1024


class Drive(Protocol):
    """Only existing narrow upload/download transport is required."""
    def put(self, name: str, data: bytes, batch_id: str, kind: str, mime: str) -> str: ...
    def download(self, file_id: str) -> bytes: ...


def verify(raw: bytes) -> dict[str, Any]:
    """Recover logical inputs/journal and verify every consumed-prefix identity."""
    if not raw or len(raw) > MAX_PACKED:
        raise IntegrityError('FORWARD_ARCHIVE_SIZE_INVALID')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(MAX_EXPANDED + 1)
    if len(expanded) > MAX_EXPANDED:
        raise IntegrityError('FORWARD_ARCHIVE_EXPANSION_EXCEEDED')
    parsed = json.loads(expanded)
    if not isinstance(parsed, dict):
        raise IntegrityError('FORWARD_ARCHIVE_OBJECT_REQUIRED')
    bundle = cast(dict[str, Any], parsed)
    if (bundle.get('format') != 'forward-nifty-bundle-v1' or bundle.get('mode') != 'RESEARCH_ONLY'
            or bundle.get('approval_authority') is not False or bundle.get('fill_evidence') is not False
            or hash_value(bundle['config']) != bundle['spec_hash']
            or len(bundle['bars']) > 75 or len(bundle['observations']) > 75):
        raise IntegrityError('FORWARD_ARCHIVE_IDENTITY_INVALID')
    starts = [row['start'] for row in bundle['bars']]
    if starts != sorted(set(starts)):
        raise IntegrityError('FORWARD_ARCHIVE_BAR_ORDER_INVALID')
    opening, ending = instant(bundle['config']['session_open']), instant(bundle['config']['session_close'])
    for bar in bundle['bars']:
        start, receipt = instant(bar['start']), instant(bar['available_at'])
        values = bar['values']
        if (set(bar) != {'start', 'available_at', 'values'} or not opening <= start < ending
                or (start-opening).total_seconds() % 300
                or not start + timedelta(minutes=5) <= receipt <= ending + timedelta(minutes=15)
                or not isinstance(values, list) or len(values) != 6
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)):
            raise IntegrityError('FORWARD_ARCHIVE_BAR_INVALID')
        o, high, low, close, volume, oi = values
        if min(o, high, low, close) <= 0 or min(volume, oi) < 0 or low > min(o, close) or high < max(o, close):
            raise IntegrityError('FORWARD_ARCHIVE_OHLC_INVALID')
    keys = set()
    for record in bundle['observations']:
        data = dict(record)
        if (data.pop('record_type', None) != 'RESEARCH_OBSERVATION'
                or data.pop('approval_authority', None) is not False or data.pop('fill_evidence', None) is not False):
            raise IntegrityError('FORWARD_ARCHIVE_CLASSIFICATION_INVALID')
        row = Observation(**data)
        normalized = row.normalized()
        if (row.origin != 'OBSERVED' or row.spec_hash != bundle['spec_hash']
                or row.decision_at in keys
                or instant(row.session_open) != instant(bundle['config']['session_open'])
                or instant(row.session_close) != instant(bundle['config']['session_close'])):
            raise IntegrityError('FORWARD_ARCHIVE_OBSERVATION_INVALID')
        keys.add(row.decision_at)
        prefix = [bar for bar in bundle['bars'] if instant(bar['start']) < instant(row.decision_at)
                  and instant(bar['available_at']) <= instant(row.received_at)]
        original = {'version': 'forward-consumed-prefix-v1', 'config': bundle['config'], 'bars': prefix}
        if digest(canonical(original)) != normalized['input_hash']:
            raise IntegrityError('FORWARD_ARCHIVE_PREFIX_MISMATCH')
    if (bundle['expected_decisions'] != 75 or bundle['recorded_decisions'] != len(keys)
            or bundle['missing_decisions'] != 75-len(keys)):
        raise IntegrityError('FORWARD_ARCHIVE_COUNT_MISMATCH')
    return bundle


def recheck(raw: bytes) -> dict[str, Any]:
    """Offline reproduction with actual availability; missing decisions stay missing."""
    bundle = verify(raw)
    validate_config(bundle['config'], ROOT)
    matches = 0
    for row in bundle['observations']:
        prefix = [bar for bar in bundle['bars'] if instant(bar['start']) < instant(row['decision_at'])
                  and instant(bar['available_at']) <= instant(row['received_at'])]
        detail, direction, available = evaluate_prefix(bundle['config'], prefix)
        if (hash_value(detail), direction, available) != (row['detail_hash'], row['direction'], row['available']):
            raise IntegrityError('FORWARD_REPLAY_MISMATCH')
        matches += 1
    return {'status': 'RECORDED_DECISIONS_REPRODUCED', 'matched': matches,
            'missing_decisions': bundle['missing_decisions'], 'complete_session': matches == 75,
            'approval_authority': False, 'fill_evidence': False}


def restore(raw: bytes, destination: Path) -> dict[str, Any]:
    """Restore to a new private directory; preserve receipt times, never rescore history."""
    bundle = verify(raw)
    validate_config(bundle['config'], ROOT)
    if destination.resolve().is_relative_to(ROOT) or destination.exists():
        raise IntegrityError('NEW_PRIVATE_RESTORE_DIRECTORY_REQUIRED')
    destination.mkdir(parents=True)
    producer = Producer(bundle['config'], destination / 'observations.sqlite', InputArchive(destination / 'inputs'))
    with closing(producer.journal.connect()) as connection:
        connection.execute('BEGIN IMMEDIATE')
        try:
            for bar in bundle['bars']:
                payload = canonical(bar)
                connection.execute('INSERT INTO forward_context VALUES (?,?,?,?)',
                                   (producer.identity, bar['start'], payload.decode(), digest(payload)))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    for record in bundle['observations']:
        prefix = [bar for bar in bundle['bars'] if instant(bar['start']) < instant(record['decision_at'])
                  and instant(bar['available_at']) <= instant(record['received_at'])]
        producer.archive.put(canonical({'version': 'forward-consumed-prefix-v1', 'config': bundle['config'], 'bars': prefix}))
        data = {key: value for key, value in record.items() if key not in ('record_type', 'approval_authority', 'fill_evidence')}
        producer.journal.record(Observation(**data))
    result = {'status': 'RESTORED', 'archive_sha256': digest(raw), 'spec_hash': producer.identity,
              'recorded_decisions': len(bundle['observations']), 'approval_authority': False, 'fill_evidence': False}
    write_once(destination / 'restore.json', result)
    return result


def publish(drive: Drive, bundle: dict[str, Any]) -> dict[str, Any]:
    """Acknowledge only after both data and manifest download verification."""
    raw = gzip.compress(canonical(bundle), mtime=0)
    verify(raw)
    identity = digest(raw)
    data_id = drive.put('nifty-forward-' + identity + '.json.gz', raw, identity, 'data', 'application/gzip')
    downloaded = drive.download(data_id)
    if downloaded != raw or canonical(verify(downloaded)) != canonical(bundle):
        raise IntegrityError('FORWARD_REMOTE_VERIFICATION_FAILED')
    manifest = {'format': 'forward-backup-manifest-v1', 'sha256': identity, 'spec_hash': bundle['spec_hash'],
                'data_file_id': data_id, 'recorded_decisions': bundle['recorded_decisions'],
                'approval_authority': False, 'fill_evidence': False}
    encoded = canonical(manifest)
    manifest_id = drive.put('nifty-forward-' + identity + '.manifest.json', encoded, identity, 'manifest', 'application/json')
    if drive.download(manifest_id) != encoded:
        raise IntegrityError('FORWARD_MANIFEST_VERIFICATION_FAILED')
    return dict(manifest, manifest_file_id=manifest_id, status='REMOTE_VERIFIED')


def main(argv: list[str] | None = None) -> int:
    """Owner-downloaded private archive: hash-first offline check or new-dir restore."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--restore', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.archive.resolve().is_relative_to(ROOT) or args.archive.stat().st_size > MAX_PACKED:
            raise IntegrityError('PRIVATE_BOUNDED_ARCHIVE_REQUIRED')
        raw = args.archive.read_bytes()
        if digest(raw) != require_hash(args.sha256):
            raise IntegrityError('ARCHIVE_HASH_MISMATCH')
        result = restore(raw, args.restore) if args.restore is not None else recheck(raw)
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'code': 'FORWARD_ARCHIVE_CHECK_FAILED', 'approval_authority': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
