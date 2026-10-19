"""Contained structural recovery check ONLY. Not a catalogue, research or restore gate."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import socket
import signal
import errno
import time
from typing import Any, NoReturn
import os
import zipfile

import archive_catalog_reconcile as catalog
import archive_catalog_verify as original
import archive_recovery_review as review
from outcomes_footer_diagnostic import PRIOR_FAILURE_ORDINALS, inspect_footer
from outcomes_large_profile import candidate_matches, MAX_ROW_BYTES

KERNEL_FIELDS = frozenset({'nonroot', 'non_pid1', 'no_new_privileges', 'zero_capabilities',
    'host_socket_absent', 'no_routes', 'finite_memory_cgroup', 'finite_pid_cgroup', 'core_dumps_disabled'})
SAFE_ERROR_CODES = frozenset({'BYTE_HASH', 'CANDIDATE_METADATA_REJECTED', 'ROW_COUNT', 'ROW_BYTE_BOUND',
    'ROW_SCHEMA', 'ROW_KEY', 'EXACT_ROW_JSON_MISMATCH', 'DUPLICATE_ROW_KEY',
    'ANALYTICAL_COLUMN_MISMATCH', 'NAIVE_ROW_TIMESTAMP', 'CONTENT_ID_MISMATCH',
    'ORIGINAL_GENERATION_PINS_REQUIRED', 'EXACT_EIGHT_OUTCOMES_REQUIRED',
    'PRIOR_FAILURE_PATTERN_CHANGED', 'AGGREGATE_EXPANSION_BOUND', 'CATALOG_BOUND',
    'KERNEL_CONTAINMENT_UNVERIFIED', 'LINUX_CONTAINMENT_REQUIRED', 'SYNTHETIC_CONTAINMENT_CHECK_FAILED',
    'CONTAINED_FORMAT_OR_RUNTIME_ERROR', 'PRIVATE_INPUT_READ_DENIED', 'PRIVATE_INPUT_NOT_FOUND'}) | frozenset(
        'KERNEL_' + name.upper() + '_UNVERIFIED' for name in KERNEL_FIELDS)


def exact(value: Any) -> str:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('NONFINITE_VALUE')
        return str(value)
    if isinstance(value, dict):
        return '{' + ','.join(json.dumps(k) + ':' + exact(v) for k, v in sorted(value.items())) + '}'
    if isinstance(value, list):
        return '[' + ','.join(exact(v) for v in value) + ']'
    return json.dumps(value, ensure_ascii=True, allow_nan=False)


def decode_row(text: Any) -> dict[str, Any]:
    if type(text) is not str or not 0 < len(text.encode('utf-8')) <= MAX_ROW_BYTES:
        raise ValueError('ROW_BYTE_BOUND')
    value = json.loads(text, parse_float=Decimal, object_pairs_hook=review._pairs,
                       parse_constant=review._constant)
    if type(value) is not dict or set(value) != set(review.SPECS['equity_research.outcomes']):
        raise ValueError('ROW_SCHEMA')
    if type(value['snapshot_id']) is not str or not 0 < len(value['snapshot_id']) <= 4096:
        raise ValueError('ROW_KEY')
    return value


def verify_batch(data: bytes, receipt: review.Receipt) -> int:
    """Value equality and content identity; no values/dates/labels leave the worker."""
    if hashlib.sha256(data).hexdigest() != receipt.file_sha256:
        raise ValueError('BYTE_HASH')
    observation = inspect_footer(data, receipt)
    if not candidate_matches(receipt.source_table, observation):
        raise ValueError('CANDIDATE_METADATA_REJECTED')
    import pyarrow.parquet as pq
    reader = pq.ParquetFile(io.BytesIO(data), thrift_string_size_limit=review.MAX_FOOTER_BYTES,  # type: ignore[no-untyped-call]
                            thrift_container_size_limit=16384, pre_buffer=False)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for batch in reader.iter_batches(batch_size=1, use_threads=False):  # type: ignore[no-untyped-call]
        values = batch.to_pylist()
        if len(values) != 1 or len(rows) >= receipt.row_count:
            raise ValueError('ROW_COUNT')
        column = values[0]
        row = decode_row(column['_row_json'])
        if exact(row) != column['_row_json']:
            raise ValueError('EXACT_ROW_JSON_MISMATCH')
        key = row['snapshot_id']
        if key in seen:
            raise ValueError('DUPLICATE_ROW_KEY')
        seen.add(key)
        for name in ('snapshot_id', 'decision_id'):
            expected = None if row[name] is None else str(row[name])
            if column[name] != expected:
                raise ValueError('ANALYTICAL_COLUMN_MISMATCH')
        expected_payload = None if row['payload'] is None else exact(row['payload'])
        if column['payload'] != expected_payload:
            raise ValueError('ANALYTICAL_COLUMN_MISMATCH')
        recorded = row['recorded_at']
        at = None if recorded is None else datetime.fromisoformat(recorded.replace('Z', '+00:00'))
        if at is not None and at.tzinfo is None:
            raise ValueError('NAIVE_ROW_TIMESTAMP')
        if column['recorded_at'] != (at.astimezone(timezone.utc) if at is not None else None):
            raise ValueError('ANALYTICAL_COLUMN_MISMATCH')
        rows.append(row)
    if len(rows) != receipt.row_count:
        raise ValueError('ROW_COUNT')
    rows.sort(key=lambda row: str(row['snapshot_id']))
    identity = exact({'version': review.FORMAT, 'table': receipt.source_table, 'rows': rows})
    if hashlib.sha256(identity.encode()).hexdigest() != receipt.batch_id:
        raise ValueError('CONTENT_ID_MISMATCH')
    return len(rows)


def verify_selected(raw: bytes, stream: Any, catalog_sha256: str, bundle_sha256: str) -> dict[str, Any]:
    if bundle_sha256 != original.PRESERVED_BUNDLE_SHA256 or not catalog._sha(catalog_sha256):
        raise ValueError('ORIGINAL_GENERATION_PINS_REQUIRED')
    structure = catalog.reconcile_stream(raw, stream, catalog_sha256=catalog_sha256,
                                         bundle_sha256=bundle_sha256)
    envelope, rows = catalog._parse(raw)
    original._cohort(envelope, rows, structure)
    selected = [(ordinal, row) for ordinal, row in enumerate(sorted(rows, key=lambda r: r['batch_id']), 1)
                if ordinal in PRIOR_FAILURE_ORDINALS]
    if len(selected) != 8 or any(row['source_table'] != 'equity_research.outcomes' for _, row in selected):
        raise ValueError('EXACT_EIGHT_OUTCOMES_REQUIRED')
    checked = total_rows = expanded = 0
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive:
        files, prefix = review._zip_index(archive)
        for _, row in selected:
            receipt = review.Receipt(row['batch_id'], row['source_table'], row['row_count'], row['file_sha256'],
                row['drive_file_id'], row['drive_manifest_id'], row['deleted_count'] or 0, row['completed_at'] or '')
            stem = prefix + receipt.source_table + '-' + receipt.batch_id
            review._manifest(review._member(archive, files[stem + '.manifest.json'], review.MAX_INDEX_BYTES), receipt)
            data = review._member(archive, files[stem + '.parquet'], review.MAX_PARQUET_BYTES)
            observation = inspect_footer(data, receipt)
            if not observation['only_column_size_predicate_failed']:
                raise ValueError('PRIOR_FAILURE_PATTERN_CHANGED')
            expanded += observation['declared_expanded_bytes']
            if expanded > 512 * 1024**2:
                raise ValueError('AGGREGATE_EXPANSION_BOUND')
            total_rows += verify_batch(data, receipt)
            checked += 1
            del data
    return dict(status='EIGHT_OUTCOMES_STRUCTURAL_CHECK_NOT_CATALOG_ACCEPTANCE', batches=checked,
                rows=total_rows, historical_original_catalog_matched=868, original_catalog_total=876,
                full_catalog_byte_footer_coverage=False, row_values_printed=False,
                receipt_claims_authenticated=False, independent_custody_verified=False,
                restore_verified=False, deletion_authorised=False, training_eligible=False)


def kernel_checks() -> dict[str, bool]:
    import resource
    checks: dict[str, bool] = {'nonroot': getattr(os, 'geteuid', lambda: -1)() == 65534,
                              'non_pid1': os.getpid() != 1}
    status = Path('/proc/self/status').read_text()
    checks['no_new_privileges'] = 'NoNewPrivs:\t1' in status
    checks['zero_capabilities'] = 'CapEff:\t0000000000000000' in status
    checks['host_socket_absent'] = not Path('/var/run/docker.sock').exists()
    checks['no_routes'] = len(Path('/proc/net/route').read_text().splitlines()) == 1
    memory, pids = Path('/sys/fs/cgroup/memory.max').read_text().strip(), Path('/sys/fs/cgroup/pids.max').read_text().strip()
    checks['finite_memory_cgroup'] = memory.isdecimal() and 0 < int(memory) <= 768 * 1024**2
    checks['finite_pid_cgroup'] = pids.isdecimal() and 0 < int(pids) <= 16
    checks['core_dumps_disabled'] = getattr(resource, 'getrlimit')(getattr(resource, 'RLIMIT_CORE')) == (0, 0)
    return checks


def require_kernel() -> dict[str, bool]:
    checks = kernel_checks()
    if set(checks) != KERNEL_FIELDS:
        raise ValueError('KERNEL_CONTAINMENT_UNVERIFIED')
    for name in sorted(KERNEL_FIELDS):
        if checks[name] is not True:
            raise ValueError('KERNEL_' + name.upper() + '_UNVERIFIED')
    return checks


def selftest() -> dict[str, Any]:
    """Kernel denial probes and synthetic codec check; never run against real mounts."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    checks = require_kernel()
    with Path('/inputs/catalog.json').open('rb') as stream:
        first = stream.read(128)
    with Path('/inputs/bundle.zip').open('rb') as stream:
        second = stream.read(128)
    checks['synthetic_inputs_exact'] = first == b'{"SYNTHETIC_ONLY":true}' and second == b'SYNTHETIC_ONLY_NOT_A_RECOVERY_ZIP'
    for name, path in [('root_readonly', '/app/never-create'), ('input_readonly', '/inputs/catalog.json')]:
        try:
            fd = os.open(path, os.O_WRONLY | (os.O_CREAT | os.O_EXCL if name == 'root_readonly' else 0))
        except OSError as error:
            checks[name] = error.errno == errno.EROFS
        else:
            os.close(fd)
            checks[name] = False
    checks['host_socket_absent'] = not Path('/var/run/docker.sock').exists()
    routes = Path('/proc/net/route').read_text().splitlines()
    checks['no_routes'] = len(routes) == 1
    try:
        with socket.create_connection(('198.51.100.1', 9), timeout=0.5):
            checks['network_denied'] = False
    except OSError:
        checks['network_denied'] = True
    row = dict(snapshot_id='SYNTHETIC_ONLY', decision_id='SYNTHETIC_ONLY',
               payload={'synthetic_opaque': 'x' * (300 * 1024)}, recorded_at='2022-01-01T00:00:00Z')
    rows = [{**row, 'snapshot_id': f'SYNTHETIC_{i:03}'} for i in range(80)]
    batch_id = hashlib.sha256(exact({'version': review.FORMAT, 'table': 'equity_research.outcomes', 'rows': rows}).encode()).hexdigest()
    schema = pa.schema([pa.field('snapshot_id', pa.string()), pa.field('decision_id', pa.string()),
        pa.field('payload', pa.string()), pa.field('recorded_at', pa.timestamp('us', tz='UTC')),
        pa.field('_row_json', pa.string(), nullable=False)], metadata={b'quant_archive': exact(dict(
            format=review.FORMAT, table='equity_research.outcomes', batch_id=batch_id,
            postgres_types=review.SPECS['equity_research.outcomes'], numeric_encoding='decimal-string')).encode()})
    table = pa.Table.from_pydict(dict(snapshot_id=[r['snapshot_id'] for r in rows], decision_id=[r['decision_id'] for r in rows],
        payload=[exact(r['payload']) for r in rows], recorded_at=[datetime(2022, 1, 1, tzinfo=timezone.utc)] * 80,
        _row_json=[exact(r) for r in rows]), schema=schema)
    sink = io.BytesIO()
    pq.write_table(table, sink, compression='zstd', use_dictionary=False)  # type: ignore[no-untyped-call]
    data = sink.getvalue()
    receipt = review.Receipt(batch_id, 'equity_research.outcomes', 80, hashlib.sha256(data).hexdigest(), 'synthetic-data', 'synthetic-manifest', 0, '')
    checks['codec'] = verify_batch(data, receipt) == 80
    return dict(status='SYNTHETIC_CONTAINER_CHECK_PASSED' if all(checks.values()) else 'SYNTHETIC_CONTAINER_CHECK_FAILED',
                checks=checks, private_decode_authorised=False)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError('ARGUMENTS_REVIEW_REQUIRED')


def main() -> int:
    parser = _Parser()
    parser.add_argument('--selftest', action='store_true')
    parser.add_argument('--contained-private', action='store_true')
    parser.add_argument('--watchdog-probe', action='store_true')
    parser.add_argument('--catalog-sha256')
    parser.add_argument('--bundle-sha256')
    try:
        args = parser.parse_args()
    except ValueError:
        print(json.dumps(dict(status='BLOCKED', code='ARGUMENTS_REVIEW_REQUIRED', raw_error_printed=False)))
        return 2
    if not args.selftest and not args.contained_private and not args.watchdog_probe:
        print(json.dumps(dict(status='PREVIEW', input_reads=0, row_pages_decoded=0)))
        return 0
    armed = False
    try:
        # Kernel-delivered default signal, not a Python thread needing the GIL.
        if os.name != 'posix' or os.getpid() == 1:
            raise ValueError('LINUX_CONTAINMENT_REQUIRED')
        signal.signal(getattr(signal, 'SIGALRM'), signal.SIG_DFL)
        getattr(signal, 'alarm')(1 if args.watchdog_probe else 120)
        armed = True
        if args.watchdog_probe:
            require_kernel()
            while True:
                time.sleep(1)
        if args.selftest:
            result = selftest()
        else:
            require_kernel()
            with Path('/inputs/catalog.json').open('rb') as source:
                raw = source.read(catalog.MAX_CATALOG + 1)
            if not 0 < len(raw) <= catalog.MAX_CATALOG:
                raise ValueError('CATALOG_BOUND')
            with Path('/inputs/bundle.zip').open('rb') as stream:
                result = verify_selected(raw, stream, args.catalog_sha256, args.bundle_sha256)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except Exception as error:
        code = ('PRIVATE_INPUT_READ_DENIED' if isinstance(error, PermissionError) else
                'PRIVATE_INPUT_NOT_FOUND' if isinstance(error, FileNotFoundError) else
                str(error) if type(error) is ValueError and str(error) in SAFE_ERROR_CODES else 'CONTAINED_FORMAT_OR_RUNTIME_ERROR')
        print(json.dumps(dict(status='BLOCKED', code=code,
            row_values_printed=False, deletion_authorised=False, training_eligible=False)))
        return 2
    finally:
        if armed:
            getattr(signal, 'alarm')(0)


if __name__ == '__main__':
    raise SystemExit(main())
