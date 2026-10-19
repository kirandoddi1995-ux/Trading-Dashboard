"""Read-only outcomes footer observations. Never grants archive acceptance or decodes rows."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import io
import json
from pathlib import Path
from typing import Any, NoReturn, BinaryIO
import zipfile

import archive_catalog_verify as verifier
import archive_catalog_reconcile as catalog
import archive_recovery_review as review

PRIOR_FAILURE_ORDINALS = frozenset({135, 266, 318, 386, 395, 626, 698, 757})
COLUMN_CHECKS = ('no_external_file', 'zstd_codec', 'value_count_matches',
    'uncompressed_positive', 'uncompressed_within_16mib', 'compressed_positive',
    'compressed_within_file', 'offsets_within_file')


def _column_checks(column: Any, rows: int, size: int, footer: int) -> dict[str, bool]:
    offsets = [column.data_page_offset]
    if column.dictionary_page_offset is not None:
        offsets.append(column.dictionary_page_offset)
    valid_offsets = all(type(n) is int for n in offsets)
    return dict(no_external_file=not bool(column.file_path), zstd_codec=column.compression == 'ZSTD',
        value_count_matches=column.num_values == rows,
        uncompressed_positive=column.total_uncompressed_size > 0,
        uncompressed_within_16mib=column.total_uncompressed_size <= review.MAX_COLUMN_EXPANDED,
        compressed_positive=column.total_compressed_size > 0,
        compressed_within_file=column.total_compressed_size <= size,
        offsets_within_file=bool(valid_offsets and min(offsets) >= 4
            and min(offsets) + column.total_compressed_size <= size - footer - 8))


def inspect_footer(data: bytes, receipt: review.Receipt) -> dict[str, Any]:
    """Metadata only; retain original predicates as observations, never override them."""
    if (receipt.source_table != 'equity_research.outcomes' or not 12 <= len(data) <= review.MAX_PARQUET_BYTES
            or data[:4] != b'PAR1' or data[-4:] != b'PAR1'):
        raise ValueError('DIAGNOSTIC_FILE_SHAPE_REJECTED')
    footer_size = int.from_bytes(data[-8:-4], 'little')
    if not 0 < footer_size <= review.MAX_FOOTER_BYTES or footer_size + 12 > len(data):
        raise ValueError('DIAGNOSTIC_FOOTER_BOUND')
    import pyarrow as pa
    import pyarrow.parquet as pq
    reader = pq.ParquetFile(io.BytesIO(data), thrift_string_size_limit=review.MAX_FOOTER_BYTES,  # type: ignore[no-untyped-call]
        thrift_container_size_limit=16384, pre_buffer=False)
    metadata = reader.metadata
    spec = review.SPECS['equity_research.outcomes']
    names = [*spec, '_row_json']
    fields = [pa.field(name, pa.timestamp('us', tz='UTC') if kind == 'timestamptz' else pa.string())
              for name, kind in spec.items()]
    fields.append(pa.field('_row_json', pa.string(), nullable=False))
    if (metadata.num_rows != receipt.row_count or metadata.num_columns != len(fields)
            or not 1 <= metadata.num_row_groups <= 64
            or not reader.schema_arrow.equals(pa.schema(fields), check_metadata=False)):
        raise ValueError('DIAGNOSTIC_SCHEMA_OR_ROWS_REJECTED')
    archive_raw = (metadata.metadata or {}).get(b'quant_archive', b'')
    if type(archive_raw) is not bytes or len(archive_raw) > review.MAX_FOOTER_BYTES:
        raise ValueError('DIAGNOSTIC_ARCHIVE_METADATA_BOUND')
    if review._json(archive_raw) != dict(format=review.FORMAT, table=receipt.source_table,
        batch_id=receipt.batch_id, postgres_types=spec, numeric_encoding='decimal-string'):
        raise ValueError('DIAGNOSTIC_ARCHIVE_METADATA_REJECTED')
    columns: dict[str, Any] = {name: dict(chunks=0, max_uncompressed_bytes=0,
        sum_uncompressed_bytes=0, max_compressed_bytes=0, sum_compressed_bytes=0,
        predicate_failures={check: 0 for check in COLUMN_CHECKS}) for name in names}
    total = total_rows = 0
    groups_match = True
    for index in range(metadata.num_row_groups):
        group = metadata.row_group(index)
        if group.num_columns != len(fields) or group.num_rows <= 0:
            raise ValueError('DIAGNOSTIC_ROW_GROUP_BOUND')
        total_rows += group.num_rows
        group_expanded = 0
        for position, name in enumerate(names):
            column = group.column(position)
            counts = columns[name]
            counts['chunks'] += 1
            counts['max_uncompressed_bytes'] = max(counts['max_uncompressed_bytes'], column.total_uncompressed_size)
            counts['sum_uncompressed_bytes'] += column.total_uncompressed_size
            counts['max_compressed_bytes'] = max(counts['max_compressed_bytes'], column.total_compressed_size)
            counts['sum_compressed_bytes'] += column.total_compressed_size
            for check, passed in _column_checks(column, group.num_rows, len(data), footer_size).items():
                counts['predicate_failures'][check] += int(not passed)
            group_expanded += column.total_uncompressed_size
        groups_match &= group.total_byte_size == group_expanded
        total += group_expanded
    file_checks = dict(row_group_totals_match=groups_match, row_group_rows_match=total_rows == receipt.row_count,
        file_expansion_within_128mib=total <= review.MAX_PARQUET_EXPANDED)
    failed_checks = {check for col in columns.values()
                     for check, failed in col['predicate_failures'].items() if failed}
    failed_checks.update(check for check, passed in file_checks.items() if not passed)
    try:
        review._footer(data, receipt)
        old_result = 'PASS'
    except Exception as error:
        old_result = str(error) if isinstance(error, ValueError) and str(error) in verifier.SAFE_ERRORS else 'ORIGINAL_GUARD_REJECTED_OTHER'
    return dict(file_bytes=len(data), footer_bytes=footer_size, declared_rows=metadata.num_rows,
        row_groups=metadata.num_row_groups, declared_expanded_bytes=total, columns=columns,
        file_checks=file_checks, original_guard_result=old_result,
        failed_predicates=sorted(failed_checks),
        only_column_size_predicate_failed=(old_result == 'PARQUET_COLUMN_EXPANSION_BOUND'
            and failed_checks == {'uncompressed_within_16mib'}))


def diagnose_stream(raw: bytes, stream: BinaryIO, *, catalog_sha256: str,
                    bundle_sha256: str) -> dict[str, Any]:
    structure = catalog.reconcile_stream(raw, stream, catalog_sha256=catalog_sha256,
                                                  bundle_sha256=bundle_sha256)
    envelope, rows = catalog._parse(raw)
    verifier._cohort(envelope, rows, structure)
    selected = [(ordinal, row) for ordinal, row in enumerate(sorted(rows, key=lambda x: x['batch_id']), 1)
                if row['source_table'] == 'equity_research.outcomes']
    if len(selected) != 18:
        raise ValueError('ALL_18_OUTCOMES_REQUIRED')
    observations: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    opened = 0
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive:
        files, prefix = review._zip_index(archive)
        for ordinal, row in selected:
            stem = prefix + 'equity_research.outcomes-' + row['batch_id']
            receipt = review.Receipt(row['batch_id'], row['source_table'], row['row_count'], row['file_sha256'],
                row['drive_file_id'], row['drive_manifest_id'], row['deleted_count'] or 0, row['completed_at'] or '')
            stage = 'MANIFEST'
            try:
                opened += 1
                review._manifest(review._member(archive, files[stem + '.manifest.json'], review.MAX_INDEX_BYTES), receipt)
                stage = 'PARQUET_BYTES'
                opened += 1
                data = review._member(archive, files[stem + '.parquet'], review.MAX_PARQUET_BYTES)
                if hashlib.sha256(data).hexdigest() != row['file_sha256']:
                    raise ValueError('PARQUET_BYTE_HASH_MISMATCH')
                stage = 'FOOTER_METADATA'
                observation = inspect_footer(data, receipt)
                observations.append(dict(catalog_ordinal=ordinal, manifest_and_byte_hash_match=True, **observation))
            except Exception as error:
                safe = {'PARQUET_BYTE_HASH_MISMATCH', 'DOWNLOADED_MANIFEST_MISMATCH',
                    'DIAGNOSTIC_FILE_SHAPE_REJECTED', 'DIAGNOSTIC_FOOTER_BOUND', 'DIAGNOSTIC_SCHEMA_OR_ROWS_REJECTED',
                    'DIAGNOSTIC_ARCHIVE_METADATA_BOUND', 'DIAGNOSTIC_ARCHIVE_METADATA_REJECTED', 'DIAGNOSTIC_ROW_GROUP_BOUND'}
                code = str(error) if isinstance(error, ValueError) and str(error) in safe else 'BOUNDED_METADATA_INSPECTION_FAILED'
                failures.append(dict(catalog_ordinal=ordinal, stage=stage, code=code))
    blocked = [o for o in observations if o['original_guard_result'] != 'PASS']
    complete = not failures and len(observations) == 18
    reproduced = (complete and {o['catalog_ordinal'] for o in blocked} == PRIOR_FAILURE_ORDINALS
        and all(o['original_guard_result'] == 'PARQUET_COLUMN_EXPANSION_BOUND' for o in blocked))
    return dict(status='OUTCOMES_FOOTER_DIAGNOSTIC_ONLY_NOT_ACCEPTANCE' if complete else 'BLOCKED',
        catalog_sha256=catalog_sha256, bundle_sha256=bundle_sha256, expected_outcomes_batches=18,
        inspected_batches=len(observations), observations=observations, failures=failures,
        original_guard_passed=len(observations)-len(blocked), original_guard_blocked=len(blocked),
        prior_eight_failure_pattern_reproduced=reproduced,
        all_observed_original_rejections_size_only=bool(blocked) and all(o['only_column_size_predicate_failed'] for o in blocked),
        selected_declared_expanded_bytes=sum(o['declared_expanded_bytes'] for o in observations),
        blocked_declared_expanded_bytes=sum(o['declared_expanded_bytes'] for o in blocked),
        zip_member_open_attempts=opened, nonselected_members_opened=0, row_pages_decoded=0,
        row_values_printed=False, network_requests=0, credential_reads=0, writes=0,
        full_catalog_byte_footer_coverage=False, bounds_changed=False, verification_authorised=False,
        logical_restore_verified=False, independent_custody_verified=False, receipt_claims_authenticated=False,
        historical_row_dates_verified=False, deletion_authorised=False, training_eligible=False, approval_authority=False)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError('ARGUMENTS_REVIEW_REQUIRED')


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__)
        for name in ('catalog', 'bundle', 'catalog-sha256', 'bundle-sha256'):
            parser.add_argument('--' + name)
        parser.add_argument('--confirm-footer-diagnostic', action='store_true')
        args = parser.parse_args(argv)
        if not args.confirm_footer_diagnostic:
            result: dict[str, Any] = dict(status='PREVIEW', input_reads=0, zip_member_open_attempts=0,
                row_pages_decoded=0, credential_reads=0, network_requests=0, writes=0, approval_authority=False)
        else:
            if (not args.catalog or not args.bundle or not catalog._sha(args.catalog_sha256)
                    or args.bundle_sha256 != verifier.PRESERVED_BUNDLE_SHA256):
                raise ValueError('PRESERVED_GENERATION_PINS_REQUIRED')
            with review._private_file(Path(args.catalog), catalog.MAX_CATALOG) as source:
                raw = source.read(catalog.MAX_CATALOG + 1)
            with review._private_file(Path(args.bundle), review.MAX_ZIP_BYTES) as stream:
                result = diagnose_stream(raw, stream, catalog_sha256=args.catalog_sha256,
                                         bundle_sha256=args.bundle_sha256)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 2 if result['status'] == 'BLOCKED' else 0
    except Exception as error:
        allowed = {'PRESERVED_GENERATION_PINS_REQUIRED', 'ALL_18_OUTCOMES_REQUIRED', 'ARGUMENTS_REVIEW_REQUIRED'} | set(catalog.SAFE_CODES)
        code = str(error) if type(error) is ValueError and str(error) in allowed else 'OUTCOMES_DIAGNOSTIC_REVIEW_REQUIRED'
        print(json.dumps(dict(status='BLOCKED', code=code, raw_error_printed=False,
            writes=0, bounds_changed=False, verification_authorised=False, deletion_authorised=False, approval_authority=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
