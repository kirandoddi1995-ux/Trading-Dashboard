"""Offline quarantined-source audit and as-of version projection, never signals.

Default preview is inert. Explicit read confirmation is required for private
files. Local receipt verification is not a fresh Drive or independent-custody
check. These source versions remain ineligible for decisions and training.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import date, timedelta
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from forward_revision_quarantine import FORMAT, MANIFEST, MAX_BYTES, verify
from research_integrity import IntegrityError, canonical, digest, hash_value, require_hash
from research_replay_comparison import instant


def versions_as_of(records: list[dict[str, Any]], cutoff: str) -> dict[str, Any]:
    """Select only versions actually known by the cutoff; never infer finality."""
    end = instant(cutoff)
    if len(records) > 75:
        raise IntegrityError('REVISION_EVIDENCE_SIZE_BOUND')
    identities: set[tuple[str, str, str]] = set()
    versions: dict[tuple[str, str], dict[str, Any]] = {}
    slots: set[str] = set()
    for record in records:
        verify(canonical(record))
        identities.add((record['original_spec_hash'], record['capture_code_hash'], record['baseline_sha256']))
        if record['slot'] in slots:
            raise IntegrityError('REVISION_EVIDENCE_DUPLICATE_SLOT')
        slots.add(record['slot'])
        rows = [dict(start=row['start'], values=row['values'], known_at=row['available_at'])
                for row in record['accepted_baseline']]
        rows.extend(dict(start=row['start'], values=row['values'], known_at=row['received_at'])
                    for row in record['closed_bars'])
        for row in rows:
            start, known = instant(row['start']), instant(row['known_at'])
            key = (start.isoformat(), known.isoformat())
            item = {'bar_start': key[0], 'known_at': key[1], 'values': row['values'],
                    'finality': 'NOT_ESTABLISHED'}
            if key in versions and versions[key] != item:
                raise IntegrityError('REVISION_EVIDENCE_SAME_RECEIPT_CONFLICT')
            versions[key] = item
    if len(identities) > 1:
        raise IntegrityError('REVISION_EVIDENCE_IDENTITY_CONFLICT')
    selected: dict[str, dict[str, Any]] = {}
    for (start_key, known_key), row in sorted(versions.items()):
        if instant(known_key) <= end:
            selected[start_key] = row
    return {'format': 'quarantined-as-of-source-versions-v1', 'cutoff': end.isoformat(),
            'bars': [selected[key] for key in sorted(selected)],
            'approval_authority': False, 'fill_evidence': False,
            'training_eligible': False, 'decision_eligible': False,
            'finality': 'NOT_ESTABLISHED'}


def private_read(path: Path, maximum: int = MAX_BYTES) -> bytes:
    """Bounded read; refuse symlinks/junctions instead of following private aliases."""
    if type(maximum) is not int or not 0 < maximum <= MAX_BYTES:
        raise IntegrityError('REVISION_EVIDENCE_SIZE_BOUND')
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise IntegrityError('REVISION_EVIDENCE_PRIVATE_PATH_REQUIRED')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if not raw or len(raw) > maximum:
        raise IntegrityError('REVISION_EVIDENCE_SIZE_BOUND')
    return raw


def audit(root: Path, day: date) -> dict[str, Any]:
    """Paused/post-session SELECT-only audit; report counts/hashes, never prices."""
    from forward_local_diagnostic import inspect_session
    checked = inspect_session(root, day)
    if checked['producer_lock_exists']:
        raise IntegrityError('PRODUCER_ALREADY_RUNNING_OR_STALE_LOCK')
    directory = root / day.isoformat() / 'state' / 'quarantine-v1'
    if any(p.is_symlink() or p.is_junction() for p in (directory, *directory.parents)):
        raise IntegrityError('REVISION_EVIDENCE_PRIVATE_PATH_REQUIRED')
    if (directory / '.quarantine-lock').exists():
        raise IntegrityError('PRODUCER_ALREADY_RUNNING_OR_STALE_LOCK')
    if not directory.exists():
        return {'status': 'QUARANTINE_NOT_STARTED', 'raw_snapshots': 0, 'writes': 0,
                'network_calls': 0, 'credential_reads': 0, 'approval_authority': False}
    policy_raw = private_read(directory / 'policy.json')
    policy = json.loads(policy_raw)
    if (not isinstance(policy, dict) or policy.get('format') != FORMAT
            or policy.get('approval_authority') is not False or policy.get('training_eligible') is not False
            or set(policy) != {'format', 'original_spec_hash', 'capture_code_hash', 'baseline_sha256',
                               'approval_authority', 'training_eligible'}):
        raise IntegrityError('REVISION_EVIDENCE_IDENTITY_CONFLICT')
    for key in ('original_spec_hash', 'capture_code_hash', 'baseline_sha256'):
        require_hash(policy[key])
    config = json.loads(private_read(directory.parent.parent / 'config.json'))
    if hash_value(config) != policy['original_spec_hash']:
        raise IntegrityError('REVISION_EVIDENCE_IDENTITY_CONFLICT')
    journal = directory.parent / 'observations.sqlite'
    with closing(sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
        conn.execute('PRAGMA query_only=ON')
        context = [json.loads(row[0]) for row in
                   conn.execute('SELECT payload FROM forward_context ORDER BY bar_start LIMIT 76').fetchall()]
    if hash_value(context) != policy['baseline_sha256']:
        raise IntegrityError('REVISION_EVIDENCE_IDENTITY_CONFLICT')
    for path in (directory / 'snapshots', directory / 'receipts'):
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            raise IntegrityError('REVISION_EVIDENCE_PRIVATE_PATH_REQUIRED')
    files = sorted((directory / 'snapshots').glob('*.json'))
    if len(files) > 75:
        raise IntegrityError('REVISION_EVIDENCE_SIZE_BOUND')
    records: list[dict[str, Any]] = []
    snapshots: dict[str, dict[str, Any]] = {}
    for path in files:
        raw = private_read(path)
        record = verify(raw)
        if (re.fullmatch(r'\d{4}\.json', path.name) is None
                or instant(record['slot']).strftime('%H%M') + '.json' != path.name
                or any(record[key] != policy[key] for key in ('original_spec_hash', 'capture_code_hash', 'baseline_sha256'))):
            raise IntegrityError('REVISION_EVIDENCE_IDENTITY_CONFLICT')
        records.append(record)
        snapshots[digest(raw)] = record
    ending = instant(config['session_close'])
    versions_as_of(records, (ending + timedelta(minutes=15)).isoformat())
    receipts = list((directory / 'receipts').glob('*.json'))
    if len(receipts) > 300:
        raise IntegrityError('REVISION_EVIDENCE_SIZE_BOUND')
    acknowledged: set[str] = set()
    failures = 0
    for path in receipts:
        receipt = json.loads(private_read(path))
        if not isinstance(receipt, dict):
            raise IntegrityError('REVISION_EVIDENCE_RECEIPT_INVALID')
        if path.name.startswith('failure-'):
            if receipt.get('status') != 'BLOCKED' or receipt.get('approval_authority') is not False:
                raise IntegrityError('REVISION_EVIDENCE_RECEIPT_INVALID')
            failures += 1
            continue
        if (not path.name.startswith('receipt-') or receipt.get('format') != MANIFEST
                or receipt.get('status') != 'REMOTE_VERIFIED' or receipt.get('decisions_added') != 0
                or type(receipt.get('decisions_added')) is not int
                or any(receipt.get(flag) is not False for flag in ('approval_authority', 'fill_evidence', 'training_eligible'))
                or any(not isinstance(receipt.get(key), str) or not receipt[key]
                       for key in ('data_file_id', 'manifest_file_id'))):
            raise IntegrityError('REVISION_EVIDENCE_RECEIPT_INVALID')
        require_hash(receipt['sha256'])
        referenced = snapshots.get(receipt['sha256'])
        if referenced is None or any(receipt.get(key) != referenced[key] for key in ('original_spec_hash', 'slot', 'received_at')):
            raise IntegrityError('REVISION_EVIDENCE_RECEIPT_INVALID')
        acknowledged.add(receipt['sha256'])
    revised = sum(record['revision_check']['revised_closed_bars'] > 0 for record in records)
    return {'status': 'QUARANTINE_LOCAL_EVIDENCE_CHECK_PASSED',
            'accepted_observations': checked['counts']['observations'],
            'missing_accepted_decisions': 75 - checked['counts']['observations'],
            'raw_snapshots': len(records), 'raw_expected_regular_slots': 75,
            'raw_missing_slots': 75 - len(records),
            'locally_recorded_remote_verifications': len(acknowledged),
            'raw_snapshots_without_verified_receipt': len(records) - len(acknowledged),
            'snapshots_with_baseline_revisions': revised, 'failure_receipts': failures,
            'custody_scope': 'LOCAL_RECEIPT_CHECK_NOT_FRESH_REMOTE_OR_INDEPENDENT_CUSTODY',
            'decisions_added': 0, 'training_eligible': False, 'approval_authority': False,
            'writes': 0, 'credential_reads': 0, 'network_calls': 0}


def main(argv: list[str] | None = None) -> int:
    """Owner runs only with writers paused; fixed diagnostics omit private content."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--session-date', type=date.fromisoformat)
    parser.add_argument('--confirm-read', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_read:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'credential_reads': 0, 'writes': 0}))
        return 0
    try:
        if args.session_date is None:
            raise ValueError
        print(json.dumps(audit(args.root, args.session_date)))
        return 0
    except Exception:
        print(json.dumps({'status': 'BLOCKED', 'code': 'QUARANTINE_EVIDENCE_REVIEW_REQUIRED',
                          'approval_authority': False, 'writes': 0}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
