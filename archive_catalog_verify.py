"""Full preserved 876-receipt byte/footer review. No row decoding, restore or deletion."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import io
import json
from pathlib import Path
from typing import Any, BinaryIO, NoReturn
import zipfile

import archive_catalog_reconcile as catalog
import archive_recovery_review as review

PRESERVED_BUNDLE_SHA256 = '4f6bd76d5368226d23fb9d369b4635e0fd485247755e443f7d18add2b9dd095b'
EXPECTED = {'market_quotes': 245, 'mf_nav': 231, 'universe_membership': 154,
    'universe_membership_versions': 119, 'scanner_observations': 109,
    'equity_research.outcomes': 18}
EXPECTED_BATCHES = 876
# New all-catalog metadata budget, NOT a change to the fixed incident verifier.
# Footer-declared expansion only; these bytes are never decoded or allocated.
MAX_DECLARED_EXPANDED = 4 * 1024**3
SAFE_ERRORS = frozenset({'DOWNLOADED_MANIFEST_MISMATCH', 'PARQUET_BYTE_HASH_MISMATCH',
    'PARQUET_SIZE_OR_MAGIC', 'PARQUET_FOOTER_BOUND', 'PARQUET_SCHEMA_OR_ROWS_MISMATCH',
    'PARQUET_ARCHIVE_METADATA_MISMATCH', 'PARQUET_METADATA_BOUND',
    'PARQUET_ROW_GROUP_BOUND', 'PARQUET_COLUMN_EXPANSION_BOUND',
    'PARQUET_COLUMN_LOCATION_BOUND', 'PARQUET_EXPANSION_BOUND',
    'PARQUET_FOOTER_PARSE_FAILED', 'PYARROW_REQUIRED_FOR_CONFIRMED_REVIEW',
    'TOTAL_DECLARED_EXPANSION_BOUND'})


def _cohort(envelope: dict[str, Any], rows: list[dict[str, Any]],
            structure: dict[str, Any]) -> None:
    if len(rows) != EXPECTED_BATCHES or structure['standard_pairs'] != EXPECTED_BATCHES:
        raise ValueError('FULL_876_COHORT_REQUIRED')
    if (structure['standard_orphan_sides'] or structure['nonstandard_archive_names'] != 5
            or structure['other_files'] != 1 or structure['files'] != 1758
            or structure['central_entries'] != 1758 or structure['explicit_directory_entries'] != 0):
        raise ValueError('PRESERVED_DIRECTORY_DENOMINATOR_REQUIRED')
    totals: dict[str, int] = {}
    no_delete: dict[str, int] = {}
    measured = catalog._time(envelope['measured_at'])
    for row in rows:
        table = row['source_table']
        state, _, _ = catalog._state(row, measured)
        if table not in EXPECTED or state not in ('DELETION_RECORDED_FULL', 'NO_DELETION_RECORDED'):
            raise ValueError('RECEIPT_COHORT_CLAIMS_MISMATCH')
        if not 0 < row['row_count'] <= 2000:
            raise ValueError('LEGACY_BATCH_ROW_BOUND')
        totals[table] = totals.get(table, 0) + 1
        if state == 'NO_DELETION_RECORDED':
            no_delete[table] = no_delete.get(table, 0) + 1
    if totals != EXPECTED or no_delete != {'equity_research.outcomes': 1, 'universe_membership': 1}:
        raise ValueError('RECEIPT_COHORT_CLAIMS_MISMATCH')
    for table, counters in structure['tables'].items():
        if (counters['receipt_missing_both'] or counters['receipt_missing_parquet']
                or counters['receipt_missing_manifest'] or counters['zip_without_receipt_paired']
                or counters['zip_without_receipt_orphan_side']):
            raise ValueError('FULL_NAME_MATCH_REQUIRED')


def verify_stream(raw: bytes, stream: BinaryIO, *, catalog_sha256: str,
                  bundle_sha256: str) -> dict[str, Any]:
    """Pure API with caller pins; CLI additionally binds the preserved real ZIP pin."""
    structure = catalog.reconcile_stream(raw, stream, catalog_sha256=catalog_sha256,
                                         bundle_sha256=bundle_sha256)
    envelope, rows = catalog._parse(raw)
    _cohort(envelope, rows, structure)
    failures: list[dict[str, object]] = []
    tables: dict[str, dict[str, int]] = {t: dict(expected_batches=n, checked_batches=0,
        matched_batches=0, declared_rows=0, matched_footer_rows=0, claimed_deleted_rows=0)
        for t, n in sorted(EXPECTED.items())}
    for row in rows:
        tables[row['source_table']]['declared_rows'] += row['row_count']
        tables[row['source_table']]['claimed_deleted_rows'] += row['deleted_count'] or 0
    expanded = opened = 0
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive:
        files, prefix = review._zip_index(archive)
        for ordinal, row in enumerate(sorted(rows, key=lambda x: x['batch_id']), 1):
            table = row['source_table']
            receipt = review.Receipt(row['batch_id'], table, row['row_count'], row['file_sha256'],
                row['drive_file_id'], row['drive_manifest_id'], row['deleted_count'] or 0,
                row['completed_at'] or '')
            counts = tables[table]
            counts['checked_batches'] += 1
            stem = prefix + table + '-' + row['batch_id']
            stage = 'MANIFEST'
            try:
                opened += 1
                review._manifest(review._member(archive, files[stem + '.manifest.json'], review.MAX_INDEX_BYTES), receipt)
                stage = 'PARQUET_BYTES'
                opened += 1
                data = review._member(archive, files[stem + '.parquet'], review.MAX_PARQUET_BYTES)
                if hashlib.sha256(data).hexdigest() != row['file_sha256']:
                    raise ValueError('PARQUET_BYTE_HASH_MISMATCH')
                stage = 'PARQUET_FOOTER'
                expanded += review._footer(data, receipt)
                if expanded > MAX_DECLARED_EXPANDED:
                    raise ValueError('TOTAL_DECLARED_EXPANSION_BOUND')
                counts['matched_batches'] += 1
                counts['matched_footer_rows'] += row['row_count']
                del data
            except Exception as error:
                code = str(error) if isinstance(error, ValueError) and str(error) in SAFE_ERRORS else 'BOUNDED_MEMBER_REVIEW_FAILED'
                failures.append(dict(catalog_ordinal=ordinal, source_table=table, stage=stage, code=code))
                if expanded > MAX_DECLARED_EXPANDED:
                    break  # No partial report can become full coverage.
    matched = sum(t['matched_batches'] for t in tables.values())
    full = not failures and matched == EXPECTED_BATCHES
    return dict(status='ALL_876_BYTES_AND_FOOTERS_MATCH_NOT_RESTORE_OR_CUSTODY' if full else 'BLOCKED',
        failures=failures, catalog_sha256=catalog_sha256, bundle_sha256=bundle_sha256,
        catalog_receipts=EXPECTED_BATCHES, expected_batches=EXPECTED_BATCHES,
        matched_batches=matched, matched_footer_rows=sum(t['matched_footer_rows'] for t in tables.values()),
        tables=tables, full_catalog_byte_footer_coverage=full,
        declared_expanded_bytes=expanded, zip_member_open_attempts=opened,
        nonstandard_archive_names_unopened=5, other_files_unopened=1,
        row_pages_decoded=0, row_values_printed=False, network_requests=0, credential_reads=0, writes=0,
        logical_restore_verified=False, postgres_restore_verified=False, application_recovery_verified=False,
        independent_custody_verified=False, historical_row_dates_verified=False,
        content_derived_batch_ids_verified=False, receipt_claims_authenticated=False,
        manifest_drive_ids_authenticated=False, deletion_authorised=False,
        training_eligible=False, approval_authority=False)


def verify_bytes(raw: bytes, bundle: bytes, *, catalog_sha256: str,
                 bundle_sha256: str) -> dict[str, Any]:
    if type(bundle) is not bytes or not 0 < len(bundle) <= review.MAX_ZIP_BYTES:
        raise ValueError('ZIP_SIZE_BOUND')
    return verify_stream(raw, io.BytesIO(bundle), catalog_sha256=catalog_sha256,
                         bundle_sha256=bundle_sha256)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError('ARGUMENTS_REVIEW_REQUIRED')


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        for name in ('catalog', 'bundle', 'catalog-sha256', 'bundle-sha256'):
            parser.add_argument('--' + name)
        parser.add_argument('--confirm-byte-footer-read', action='store_true')
        args = parser.parse_args(argv)
        if not args.confirm_byte_footer_read:
            result: dict[str, Any] = dict(status='PREVIEW', input_reads=0, zip_member_open_attempts=0,
                row_pages_decoded=0, network_requests=0, credential_reads=0, writes=0, approval_authority=False)
        else:
            if (not args.catalog or not args.bundle or not catalog._sha(args.catalog_sha256)
                    or args.bundle_sha256 != PRESERVED_BUNDLE_SHA256):
                raise ValueError('PRESERVED_GENERATION_PINS_REQUIRED')
            with review._private_file(Path(args.catalog), catalog.MAX_CATALOG) as source:
                raw = source.read(catalog.MAX_CATALOG + 1)
            with review._private_file(Path(args.bundle), review.MAX_ZIP_BYTES) as stream:
                result = verify_stream(raw, stream, catalog_sha256=args.catalog_sha256,
                                       bundle_sha256=args.bundle_sha256)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 2 if result['status'] == 'BLOCKED' else 0
    except Exception as error:
        safe = {'PRESERVED_GENERATION_PINS_REQUIRED', 'FULL_876_COHORT_REQUIRED',
                'PRESERVED_DIRECTORY_DENOMINATOR_REQUIRED', 'RECEIPT_COHORT_CLAIMS_MISMATCH',
                'LEGACY_BATCH_ROW_BOUND', 'FULL_NAME_MATCH_REQUIRED', 'ARGUMENTS_REVIEW_REQUIRED'} | set(catalog.SAFE_CODES)
        code = str(error) if type(error) is ValueError and str(error) in safe else 'CATALOG_BYTE_FOOTER_REVIEW_FAILED'
        print(json.dumps(dict(status='BLOCKED', code=code, raw_error_printed=False, writes=0,
            full_catalog_byte_footer_coverage=False, deletion_authorised=False, approval_authority=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
