"""Read-only all-history receipt/name join; never opens ZIP members or market rows."""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Any, BinaryIO, NoReturn
import zipfile

import archive_recovery_review as review

FORMAT = 'archive-all-catalog-v1'
MAX_CATALOG = 5 * 1024 * 1024  # SQL records <=4 MiB, plus bounded envelope
MAX_RECORDS = 4096
SAFE_CODES = frozenset({'CATALOG_TIME_INVALID', 'CATALOG_SIZE_BOUND', 'COMPLETE_CATALOG_REQUIRED',
    'CATALOG_RECEIPT_SHAPE_INVALID', 'CATALOG_DUPLICATE_BATCH', 'CATALOG_DRIVE_REFERENCE_INVALID',
    'CATALOG_DUPLICATE_DRIVE_REFERENCE', 'EXACT_GENERATION_PINS_REQUIRED',
    'EXACT_GENERATION_BYTES_REQUIRED', 'ZIP_SIZE_BOUND', 'ARGUMENTS_REVIEW_REQUIRED'})
FIELDS = frozenset({'batch_id', 'source_table', 'row_count', 'file_sha256',
    'drive_file_id', 'drive_manifest_id', 'deleted_count', 'verified_at', 'completed_at'})
STATES = ('NO_DELETION_RECORDED', 'DELETION_RECORDED_FULL',
          'DELETION_RECORDED_PARTIAL', 'INCONSISTENT_RECEIPT')


def _time(value: object) -> datetime:
    if type(value) is not str or len(value) > 40:
        raise ValueError('CATALOG_TIME_INVALID')
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except ValueError:
        raise ValueError('CATALOG_TIME_INVALID') from None


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def _count(value: object) -> bool:
    return type(value) is int and 0 <= value <= 2**31 - 1


def _parse(raw: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_CATALOG:
        raise ValueError('CATALOG_SIZE_BOUND')
    obj = json.loads(raw, object_pairs_hook=review._pairs, parse_constant=review._constant)
    if (type(obj) is not dict or set(obj) != {'format', 'status', 'measured_at',
            'total_count', 'truncated', 'records'} or obj['format'] != FORMAT
            or obj['status'] != 'COMPLETE_METADATA_EXPORT' or obj['truncated'] is not False
            or not _count(obj['total_count']) or obj['total_count'] > MAX_RECORDS
            or type(obj['records']) is not list or len(obj['records']) != obj['total_count']):
        raise ValueError('COMPLETE_CATALOG_REQUIRED')
    _time(obj['measured_at'])
    seen: set[str] = set()
    drive_seen: set[str] = set()
    for row in obj['records']:
        if (type(row) is not dict or set(row) != FIELDS or not _sha(row['batch_id'])
                or not _sha(row['file_sha256']) or type(row['source_table']) is not str
                or not 0 < len(row['source_table']) <= 128):
            raise ValueError('CATALOG_RECEIPT_SHAPE_INVALID')
        if row['batch_id'] in seen:
            raise ValueError('CATALOG_DUPLICATE_BATCH')
        seen.add(row['batch_id'])
        for field in ('drive_file_id', 'drive_manifest_id'):
            value = row[field]
            if type(value) is not str or re.fullmatch('[A-Za-z0-9_-]{1,200}', value) is None:
                raise ValueError('CATALOG_DRIVE_REFERENCE_INVALID')
            if value in drive_seen:
                raise ValueError('CATALOG_DUPLICATE_DRIVE_REFERENCE')
            drive_seen.add(value)
    return obj, obj['records']


def _state(row: dict[str, Any], measured: datetime) -> tuple[str, str, str]:
    dates: list[str] = []
    invalid = False
    verified: datetime | None = None
    for name in ('verified_at', 'completed_at'):
        value = row[name]
        if value is None:
            dates.append('NOT_RECORDED')
            invalid |= name == 'verified_at'
        else:
            try:
                at = _time(value)
                invalid |= at > measured or (name == 'completed_at' and verified is not None and at < verified)
                if name == 'verified_at':
                    verified = at
                dates.append(at.date().isoformat())
            except ValueError:
                dates.append('INVALID')
                invalid = True
    rows, deleted = row['row_count'], row['deleted_count']
    invalid |= not _count(rows) or rows == 0
    invalid |= deleted is not None and (not _count(deleted) or (_count(rows) and deleted > rows))
    invalid |= row['completed_at'] is None and _count(deleted) and deleted > 0
    invalid |= row['completed_at'] is not None and deleted is None
    if invalid:
        state = 'INCONSISTENT_RECEIPT'
    elif deleted is None or deleted == 0:
        state = 'NO_DELETION_RECORDED'
    elif deleted == rows:
        state = 'DELETION_RECORDED_FULL'
    else:
        state = 'DELETION_RECORDED_PARTIAL'
    return state, dates[0], dates[1]


def reconcile(catalog: bytes, bundle: bytes, *, catalog_sha256: str,
              bundle_sha256: str) -> dict[str, object]:
    """Caller-pinned bytes; file hashes/Drive IDs in receipts are NOT authenticated."""
    if type(bundle) is not bytes or not 0 < len(bundle) <= review.MAX_ZIP_BYTES:
        raise ValueError('ZIP_SIZE_BOUND')
    return reconcile_stream(catalog, io.BytesIO(bundle), catalog_sha256=catalog_sha256,
                            bundle_sha256=bundle_sha256)


def reconcile_stream(catalog: bytes, stream: BinaryIO, *, catalog_sha256: str,
                     bundle_sha256: str) -> dict[str, object]:
    """Bounded sequential hash and central-directory inspection on the same handle."""
    if not _sha(catalog_sha256) or not _sha(bundle_sha256):
        raise ValueError('EXACT_GENERATION_PINS_REQUIRED')
    if type(catalog) is not bytes or not 0 < len(catalog) <= MAX_CATALOG:
        raise ValueError('CATALOG_SIZE_BOUND')
    if hashlib.sha256(catalog).hexdigest() != catalog_sha256:
        raise ValueError('EXACT_GENERATION_BYTES_REQUIRED')
    envelope, rows = _parse(catalog)
    stream.seek(0, 2)
    size = stream.tell()
    if not 0 < size <= review.MAX_ZIP_BYTES:
        raise ValueError('ZIP_SIZE_BOUND')
    stream.seek(0)
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        block = stream.read(min(65536, remaining))
        if not block:
            raise ValueError('EXACT_GENERATION_BYTES_REQUIRED')
        digest.update(block)
        remaining -= len(block)
    if stream.read(1) or digest.hexdigest() != bundle_sha256:
        raise ValueError('EXACT_GENERATION_BYTES_REQUIRED')
    measured = _time(envelope['measured_at'])
    review._zip_header(stream)
    stream.seek(0)
    pairs: dict[tuple[str, str], set[str]] = {}
    nonstandard = other = 0
    with zipfile.ZipFile(stream) as archive:
        files, prefix = review._zip_index(archive)
        central_entries = len(archive.infolist())
        directory_entries = sum(info.is_dir() for info in archive.infolist())
        for path in files:
            name = path[len(prefix):]
            match = re.fullmatch(r'([a-z_.]+)-([a-f0-9]{64})\.(parquet|manifest\.json)', name)
            if match is None or match[1] not in review.SPECS:
                if name.endswith(('.parquet', '.manifest.json')):
                    nonstandard += 1
                else:
                    other += 1
                continue
            pairs.setdefault((match[1], match[2]), set()).add(match[3])
    known = set(review.SPECS)
    tables: dict[str, Counter[str]] = {t: Counter() for t in sorted(known) + ['UNKNOWN_SOURCE']}
    dates: Counter[tuple[str, str, str, str]] = Counter()
    date_rows: Counter[tuple[str, str, str, str]] = Counter()
    date_deleted: Counter[tuple[str, str, str, str]] = Counter()
    date_null_deleted: Counter[tuple[str, str, str, str]] = Counter()
    receipts: set[tuple[str, str]] = set()
    joins = ('paired', 'missing_both', 'missing_parquet', 'missing_manifest')
    for row in rows:
        source = row['source_table']
        table = source if source in known else 'UNKNOWN_SOURCE'
        key = source, row['batch_id']
        receipts.add(key)
        state, verified_day, completed_day = _state(row, measured)
        counts = tables[table]
        counts['receipts'] += 1
        counts[state] += 1
        sides = pairs.get(key, set())
        join = ('paired' if len(sides) == 2 else 'missing_both' if not sides
                else 'missing_parquet' if 'manifest.json' in sides else 'missing_manifest')
        counts['receipt_' + join] += 1
        date_key = table, verified_day, completed_day, state
        dates[date_key] += 1
        date_rows[date_key] += row['row_count'] if _count(row['row_count']) else 0
        date_deleted[date_key] += row['deleted_count'] if _count(row['deleted_count']) else 0
        date_null_deleted[date_key] += int(row['deleted_count'] is None)
    for key, sides in pairs.items():
        if key not in receipts:
            tables[key[0]]['zip_without_receipt_' + ('paired' if len(sides) == 2 else 'orphan_side')] += 1
    output_tables = {t: {k: tables[t][k] for k in ('receipts', *STATES,
        *('receipt_' + j for j in joins), 'zip_without_receipt_paired', 'zip_without_receipt_orphan_side')}
        for t in tables}
    return dict(status='ALL_CATALOG_NAMES_RECONCILED_NOT_CONTENT_OR_CUSTODY',
        catalog_sha256=catalog_sha256, bundle_sha256=bundle_sha256,
        measured_at=measured.isoformat(), catalog_receipts=len(rows), tables=output_tables,
        date_summary=[dict(source_table=k[0], verified_day=k[1], completed_day=k[2], state=k[3],
            receipts=n, declared_rows=date_rows[k], declared_deleted_rows=date_deleted[k],
            null_deleted_count=date_null_deleted[k]) for k, n in sorted(dates.items())],
        central_entries=central_entries, explicit_directory_entries=directory_entries,
        files=len(files), standard_pairs=sum(len(sides) == 2 for sides in pairs.values()),
        standard_orphan_sides=sum(len(sides) == 1 for sides in pairs.values()),
        nonstandard_archive_names=nonstandard, other_files=other,
        zip_members_opened=0, row_pages_decoded=0, network_requests=0, credential_reads=0, writes=0,
        receipt_claims_authenticated=False, archive_file_hashes_verified=False,
        manifest_drive_ids_authenticated=False, historical_row_dates_verified=False,
        logical_restore_verified=False, independent_custody_verified=False,
        deletion_authorised=False, training_eligible=False, approval_authority=False)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError('ARGUMENTS_REVIEW_REQUIRED')


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        for name in ('catalog', 'bundle', 'catalog-sha256', 'bundle-sha256'):
            parser.add_argument('--' + name)
        parser.add_argument('--confirm-metadata-read', action='store_true')
        args = parser.parse_args(argv)
        if not args.confirm_metadata_read:
            result: dict[str, object] = dict(status='PREVIEW', input_reads=0, network_requests=0,
                credential_reads=0, writes=0, row_pages_decoded=0, approval_authority=False)
        else:
            if not all((args.catalog, args.bundle, args.catalog_sha256, args.bundle_sha256)):
                raise ValueError('EXACT_GENERATION_PINS_REQUIRED')
            if not _sha(args.catalog_sha256) or not _sha(args.bundle_sha256):
                raise ValueError('EXACT_GENERATION_PINS_REQUIRED')
            with review._private_file(Path(args.catalog), MAX_CATALOG) as cat:
                catalog = cat.read(MAX_CATALOG + 1)
            with review._private_file(Path(args.bundle), review.MAX_ZIP_BYTES) as zip_file:
                result = reconcile_stream(catalog, zip_file, catalog_sha256=args.catalog_sha256,
                                          bundle_sha256=args.bundle_sha256)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except Exception as error:
        code = str(error) if type(error) is ValueError and str(error) in SAFE_CODES else 'ALL_CATALOG_REVIEW_REQUIRED'
        print(json.dumps(dict(status='BLOCKED', code=code,
            raw_error_printed=False, writes=0, approval_authority=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
