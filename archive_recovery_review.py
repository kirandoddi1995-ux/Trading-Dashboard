"""Offline incident byte/footer review, NOT row restore or independent custody.

Default CLI preview has zero input IO. Confirmed paths are owner-selected private
inventory/Drive ZIP downloads. No credentials, transport, extraction or row reads.
PyArrow is imported lazily only for bounded synthetic/owner Parquet footer checks.
"""
from __future__ import annotations

import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
from typing import BinaryIO, NoReturn, cast
import zipfile

FORMAT = 'quant-archive-v1'
INVENTORY_FORMAT = 'archive-recovery-inventory-v1'
WINDOW_START = '2026-10-11T00:00:00+00:00'
WINDOW_END = '2026-10-17T18:25:14+00:00'
EXPECTED_BATCHES = 122
EXPECTED_DELETED_ROWS = 98755
INCIDENT_TABLE_TOTALS: tuple[tuple[str, int, int], ...] = (
    ('market_quotes', 44, 42700), ('scanner_observations', 24, 21350),
    ('universe_membership', 30, 13347), ('universe_membership_versions', 24, 21358),
)
MAX_INDEX_BYTES = 1024 * 1024
MAX_PARQUET_BYTES = 32 * 1024 * 1024
MAX_FOOTER_BYTES = 256 * 1024
MAX_ZIP_BYTES = 2 * 1024**3
MAX_CENTRAL_BYTES = 2 * 1024 * 1024
MAX_ZIP_ENTRIES = 4096
MAX_DECLARED_BYTES = 4 * 1024**3
MAX_RATIO = 200
MAX_COLUMN_EXPANDED = 16 * 1024 * 1024
MAX_PARQUET_EXPANDED = 128 * 1024 * 1024
MAX_TOTAL_PARQUET_EXPANDED = 512 * 1024 * 1024

# Fixed public drive_archive.SPECS schema; no import of its transport/row reader.
SPECS: dict[str, dict[str, str]] = {
    'universe_membership': dict(snapshot_date='date', instrument_key='text', trading_symbol='text',
        isin='text', name='text', exchange='text', segment='text', instrument_type='text',
        security_type='text', sector='text', source='text', observed_at='timestamptz', raw='jsonb'),
    'equity_research.outcomes': dict(snapshot_id='text', decision_id='text', payload='jsonb', recorded_at='timestamptz'),
    'mf_nav': dict(scheme_code='text', nav_date='date', isin_growth='text', isin_reinvestment='text',
        scheme_name='text', amc='text', category='text', plan='text', option_name='text', nav='numeric',
        source='text', observed_at='timestamptz', source_hash='text'),
    'market_quotes': dict(observed_at='timestamptz', trade_date='date', instrument_key='text', source='text',
        last_price='numeric', open='numeric', high='numeric', low='numeric', previous_close='numeric',
        volume='numeric', open_interest='numeric', raw='jsonb'),
    'universe_membership_versions': dict(snapshot_id='text', instrument_key='text', trading_symbol='text',
        isin='text', name='text', exchange='text', segment='text', instrument_type='text', security_type='text',
        sector='text', source='text', observed_at='timestamptz', raw='jsonb'),
    'scanner_observations': dict(observation_id='text', as_of_date='date', observed_at='timestamptz',
        instrument_key='text', trading_symbol='text', strategy_version='text', universe_snapshot_date='date',
        stage1_pass='boolean', stage2_pass='boolean', rejection_reason='text', score='double precision',
        entry='double precision', stop='double precision', target='double precision', feature_json='jsonb'),
}


class ReviewError(ValueError):
    """Only fixed non-sensitive codes are supplied by this module."""


@dataclass(frozen=True)
class Receipt:
    batch_id: str
    source_table: str
    row_count: int
    file_sha256: str
    drive_file_id: str
    drive_manifest_id: str
    deleted_count: int
    completed_at: str


@dataclass(frozen=True)
class ReviewReport:
    status: str
    failures: tuple[str, ...]
    inventory_batches: int = 0
    inventory_deleted_rows: int = 0
    verified_batches: int = 0
    verified_footer_rows: int = 0
    missing_expected_entries: int = 0
    extraneous_entries: int = 0
    expected_batches: int = EXPECTED_BATCHES
    expected_deleted_rows: int = EXPECTED_DELETED_ROWS
    full_planned_byte_footer_coverage: bool = False
    row_values_read: int = 0
    logical_restore_verified: bool = False
    independent_custody_verified: bool = False
    inventory_completeness_authenticated: bool = False
    zip_provenance_authenticated: bool = False
    manifest_drive_id_authenticated: bool = False
    current_db_state_checked: bool = False
    network_requests: int = 0
    credential_reads: int = 0
    writes: int = 0
    inventory_sha256: str | None = None
    bundle_sha256: str | None = None


def _object(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ReviewError('OBJECT_REQUIRED')
    return cast(dict[str, object], value)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReviewError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _constant(_: str) -> object:
    raise ReviewError('NONFINITE_JSON_FORBIDDEN')


def _json(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_INDEX_BYTES:
        raise ReviewError('JSON_SIZE_BOUND')
    try:
        return _object(json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant))
    except (UnicodeError, RecursionError, json.JSONDecodeError):
        raise ReviewError('INVALID_JSON') from None


def _text(value: object, pattern: str) -> str:
    if type(value) is not str or len(value) > 200 or re.fullmatch(pattern, value) is None:
        raise ReviewError('INVALID_IDENTITY_OR_HASH')
    return value


def _integer(value: object) -> int:
    if type(value) is not int or not 0 < value <= EXPECTED_DELETED_ROWS:
        raise ReviewError('INVALID_ROW_COUNT')
    return value


def _utc(value: object) -> datetime:
    if type(value) is not str or not 1 <= len(value) <= 40:
        raise ReviewError('UTC_TIMESTAMP_REQUIRED')
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        raise ReviewError('UTC_TIMESTAMP_REQUIRED') from None
    if at.tzinfo is None or at.utcoffset() is None:
        raise ReviewError('UTC_TIMESTAMP_REQUIRED')
    return at.astimezone(timezone.utc)


def parse_inventory(raw: bytes) -> tuple[Receipt, ...]:
    """Pure parser for the fixed full incident denominator, not a DB verifier."""
    inventory = _json(raw)
    if (set(inventory) != {'format', 'window_start', 'window_end', 'measured_at', 'batches'}
            or inventory['format'] != INVENTORY_FORMAT
            or _utc(inventory['window_start']) != _utc(WINDOW_START)
            or _utc(inventory['window_end']) != _utc(WINDOW_END)
            or _utc(inventory['measured_at']) < _utc(WINDOW_END)):
        raise ReviewError('INCIDENT_INVENTORY_ENVELOPE_MISMATCH')
    batches = inventory['batches']
    if type(batches) is not list or len(batches) != EXPECTED_BATCHES:
        raise ReviewError('FULL_BATCH_DENOMINATOR_REQUIRED')
    receipts: list[Receipt] = []
    batches_seen: set[str] = set()
    ids_seen: set[str] = set()
    for value in batches:
        batch = _object(value)
        if set(batch) != {'batch_id', 'source_table', 'row_count', 'file_sha256', 'drive_file_id',
                          'drive_manifest_id', 'deleted_count', 'completed_at'}:
            raise ReviewError('RECEIPT_SCHEMA_MISMATCH')
        identity = _text(batch['batch_id'], '[a-f0-9]{64}')
        digest = _text(batch['file_sha256'], '[a-f0-9]{64}')
        table = _text(batch['source_table'], '[a-z_.]+')
        data_id = _text(batch['drive_file_id'], '[A-Za-z0-9_-]+')
        manifest_id = _text(batch['drive_manifest_id'], '[A-Za-z0-9_-]+')
        rows, deleted = _integer(batch['row_count']), _integer(batch['deleted_count'])
        complete = _utc(batch['completed_at'])
        if (identity in batches_seen or data_id in ids_seen or manifest_id in ids_seen or data_id == manifest_id):
            raise ReviewError('DUPLICATE_BATCH_OR_DRIVE_ID')
        if table not in SPECS or rows != deleted or not _utc(WINDOW_START) <= complete <= _utc(WINDOW_END):
            raise ReviewError('RECEIPT_INCIDENT_SCOPE_MISMATCH')
        batches_seen.add(identity)
        ids_seen.update((data_id, manifest_id))
        receipts.append(Receipt(identity, table, rows, digest, data_id, manifest_id, deleted, complete.isoformat()))
    if sum(row.deleted_count for row in receipts) != EXPECTED_DELETED_ROWS:
        raise ReviewError('FULL_DELETED_ROW_DENOMINATOR_REQUIRED')
    actual = {table: (sum(r.source_table == table for r in receipts),
                      sum(r.deleted_count for r in receipts if r.source_table == table))
              for table in {r.source_table for r in receipts}}
    if actual != {table: (batches, rows) for table, batches, rows in INCIDENT_TABLE_TOTALS}:
        raise ReviewError('INCIDENT_TABLE_DENOMINATOR_REQUIRED')
    return tuple(sorted(receipts, key=lambda row: row.batch_id))


def _manifest(raw: bytes, receipt: Receipt) -> None:
    manifest = _json(raw)
    if (set(manifest) != {'format', 'batch_id', 'source_table', 'rows', 'sha256', 'drive_file_id',
                         'postgres_types', 'numeric_encoding'}
            or manifest['format'] != FORMAT or manifest['batch_id'] != receipt.batch_id
            or manifest['source_table'] != receipt.source_table or type(manifest['rows']) is not int
            or manifest['rows'] != receipt.row_count or manifest['sha256'] != receipt.file_sha256
            or manifest['drive_file_id'] != receipt.drive_file_id
            or manifest['postgres_types'] != SPECS[receipt.source_table]
            or manifest['numeric_encoding'] != 'decimal-string'):
        raise ReviewError('DOWNLOADED_MANIFEST_MISMATCH')


def _footer(data: bytes, receipt: Receipt) -> int:
    """Read footer/schema metadata only; never invoke any Parquet row reader."""
    if (not 12 <= len(data) <= MAX_PARQUET_BYTES or data[:4] != b'PAR1' or data[-4:] != b'PAR1'):
        raise ReviewError('PARQUET_SIZE_OR_MAGIC')
    footer_size = int.from_bytes(data[-8:-4], 'little')
    if not 0 < footer_size <= MAX_FOOTER_BYTES or footer_size+12 > len(data):
        raise ReviewError('PARQUET_FOOTER_BOUND')
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise ReviewError('PYARROW_REQUIRED_FOR_CONFIRMED_REVIEW') from None
    try:
        reader = pq.ParquetFile(io.BytesIO(data), thrift_string_size_limit=MAX_FOOTER_BYTES,  # type: ignore[no-untyped-call]
                                thrift_container_size_limit=16384, pre_buffer=False)
        metadata = reader.metadata
        spec = SPECS[receipt.source_table]
        fields = [pa.field(name, pa.date32() if kind == 'date' else
                           pa.timestamp('us', tz='UTC') if kind == 'timestamptz' else pa.string())
                  for name, kind in spec.items()]
        fields.append(pa.field('_row_json', pa.string(), nullable=False))
        if (metadata.num_rows != receipt.row_count or metadata.num_columns != len(fields)
                or not 1 <= metadata.num_row_groups <= 64
                or not reader.schema_arrow.equals(pa.schema(fields), check_metadata=False)):
            raise ReviewError('PARQUET_SCHEMA_OR_ROWS_MISMATCH')
        archive_raw = (metadata.metadata or {}).get(b'quant_archive', b'')
        if type(archive_raw) is not bytes or len(archive_raw) > MAX_FOOTER_BYTES:
            raise ReviewError('PARQUET_METADATA_BOUND')
        archive = _json(archive_raw)
        if archive != dict(format=FORMAT, table=receipt.source_table, batch_id=receipt.batch_id,
                           postgres_types=spec, numeric_encoding='decimal-string'):
            raise ReviewError('PARQUET_ARCHIVE_METADATA_MISMATCH')
        total = 0
        rows = 0
        for index in range(metadata.num_row_groups):
            group = metadata.row_group(index)
            rows += group.num_rows
            group_expanded = 0
            if group.num_columns != len(fields) or group.num_rows <= 0:
                raise ReviewError('PARQUET_ROW_GROUP_BOUND')
            for column_index in range(group.num_columns):
                column = group.column(column_index)
                if (column.file_path or column.compression != 'ZSTD' or column.num_values != group.num_rows
                        or not 0 < column.total_uncompressed_size <= MAX_COLUMN_EXPANDED
                        or not 0 < column.total_compressed_size <= len(data)):
                    raise ReviewError('PARQUET_COLUMN_EXPANSION_BOUND')
                offsets = [column.data_page_offset]
                if column.dictionary_page_offset is not None:
                    offsets.append(column.dictionary_page_offset)
                first = min(offsets)
                if first < 4 or first+column.total_compressed_size > len(data)-footer_size-8:
                    raise ReviewError('PARQUET_COLUMN_LOCATION_BOUND')
                group_expanded += column.total_uncompressed_size
                total += column.total_uncompressed_size
                if total > MAX_PARQUET_EXPANDED:
                    raise ReviewError('PARQUET_EXPANSION_BOUND')
            if group.total_byte_size != group_expanded:
                raise ReviewError('PARQUET_ROW_GROUP_BOUND')
        if rows != receipt.row_count:
            raise ReviewError('PARQUET_SCHEMA_OR_ROWS_MISMATCH')
        return total
    except ReviewError:
        raise
    except Exception:
        raise ReviewError('PARQUET_FOOTER_PARSE_FAILED') from None


def _zip_header(stream: BinaryIO) -> None:
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    if not 22 <= size <= MAX_ZIP_BYTES:
        raise ReviewError('ZIP_SIZE_BOUND')
    stream.seek(max(0, size-65557))
    tail = stream.read(65557)
    offset = tail.rfind(b'PK\x05\x06')
    if offset < 0 or len(tail)-offset < 22:
        raise ReviewError('STANDARD_ZIP_REQUIRED')
    _, disk, cd_disk, disk_entries, entries, cd_size, cd_offset, comment = struct.unpack_from('<4s4H2LH', tail, offset)
    eocd = size-len(tail)+offset
    if (disk or cd_disk or entries != disk_entries or not 0 < entries <= MAX_ZIP_ENTRIES
            or cd_size > MAX_CENTRAL_BYTES or cd_offset+cd_size != eocd
            or offset+22+comment != len(tail) or cd_size == 0xffffffff or cd_offset == 0xffffffff):
        raise ReviewError('ZIP_DIRECTORY_BOUND_OR_UNSUPPORTED_ZIP64')


def _zip_index(archive: zipfile.ZipFile) -> tuple[dict[str, zipfile.ZipInfo], str]:
    files: dict[str, zipfile.ZipInfo] = {}
    seen: set[str] = set()
    prefixes: set[str] = set()
    total = 0
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise ReviewError('ZIP_DIRECTORY_BOUND_OR_UNSUPPORTED_ZIP64')
    for info in infos:
        name = info.filename
        if (info.orig_filename != name or not name or len(name) > 512 or '\\' in name or ':' in name or name.startswith('/')
                or any(ord(c) < 32 or ord(c) == 127 for c in name)):
            raise ReviewError('UNSAFE_ZIP_NAME')
        parts = name.rstrip('/').split('/')
        if (len(parts) > 2 or any(not p or p in ('.', '..') or p[-1:] in (' ', '.') for p in parts)):
            raise ReviewError('UNSAFE_ZIP_NAME')
        folded = name.rstrip('/').casefold()
        mode = (info.external_attr >> 16) & 0xffff
        if folded in seen:
            raise ReviewError('DUPLICATE_ZIP_NAME')
        seen.add(folded)
        if (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                or (stat.S_IFMT(mode) == stat.S_IFDIR and not info.is_dir())
                or info.flag_bits & 0x41 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise ReviewError('ZIP_LINK_ENCRYPTION_OR_COMPRESSION_FORBIDDEN')
        if (not 0 <= info.file_size <= MAX_PARQUET_BYTES or info.compress_size < 0
                or info.file_size > MAX_RATIO*max(1, info.compress_size)):
            raise ReviewError('ZIP_MEMBER_EXPANSION_BOUND')
        total += info.file_size
        if total > MAX_DECLARED_BYTES:
            raise ReviewError('ZIP_TOTAL_EXPANSION_BOUND')
        if info.is_dir():
            if len(parts) != 1 or info.file_size != 0:
                raise ReviewError('UNSAFE_ZIP_DIRECTORY')
            prefixes.add(parts[0]+'/')
            continue
        prefix = parts[0]+'/' if len(parts) == 2 else ''
        prefixes.add(prefix)
        files[name] = info
    if len(prefixes) != 1:
        raise ReviewError('ONE_COMMON_ZIP_PREFIX_REQUIRED')
    return files, next(iter(prefixes))


def _member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, maximum: int) -> bytes:
    if not 0 < info.file_size <= maximum:
        raise ReviewError('EXPECTED_MEMBER_SIZE_BOUND')
    with archive.open(info, 'r') as source:
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = source.read(min(65536, maximum+1-size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                raise ReviewError('MEMBER_READ_SIZE_BOUND')
        if size != info.file_size:
            raise ReviewError('INCOMPLETE_MEMBER_READ')
    return b''.join(chunks)


def _review(inventory: bytes, stream: BinaryIO) -> ReviewReport:
    receipts = parse_inventory(inventory)
    _zip_header(stream)
    inventory_hash = hashlib.sha256(inventory).hexdigest()
    stream.seek(0, os.SEEK_END)
    expected_size = stream.tell()
    stream.seek(0)
    bundle_digest = hashlib.sha256()
    size = 0
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_ZIP_BYTES:
            raise ReviewError('ZIP_SIZE_BOUND')
        bundle_digest.update(chunk)
    if size != expected_size:
        raise ReviewError('INCOMPLETE_BUNDLE_READ')
    bundle_hash = bundle_digest.hexdigest()
    failures: set[str] = set()
    verified = rows = missing = expanded = 0
    stream.seek(0)
    with zipfile.ZipFile(stream, 'r') as archive:
        files, prefix = _zip_index(archive)
        expected = {prefix+r.source_table+'-'+r.batch_id+suffix
                    for r in receipts for suffix in ('.manifest.json', '.parquet')}
        extra = len(set(files)-expected)
        missing = len(expected-set(files))
        if missing:
            failures.add('EXPECTED_ZIP_ENTRIES_MISSING')
        for receipt in receipts:
            stem = prefix+receipt.source_table+'-'+receipt.batch_id
            if stem+'.manifest.json' not in files or stem+'.parquet' not in files:
                continue
            try:
                _manifest(_member(archive, files[stem+'.manifest.json'], MAX_INDEX_BYTES), receipt)
                data = _member(archive, files[stem+'.parquet'], MAX_PARQUET_BYTES)
                if hashlib.sha256(data).hexdigest() != receipt.file_sha256:
                    raise ReviewError('PARQUET_BYTE_HASH_MISMATCH')
                expanded += _footer(data, receipt)
                if expanded > MAX_TOTAL_PARQUET_EXPANDED:
                    raise ReviewError('TOTAL_PARQUET_EXPANSION_BOUND')
                verified += 1
                rows += receipt.row_count
            except ReviewError as error:
                failures.add(str(error))
            except Exception:
                failures.add('EXPECTED_MEMBER_READ_FAILED')
        full = not failures and verified == EXPECTED_BATCHES and rows == EXPECTED_DELETED_ROWS
        return ReviewReport('INCIDENT_BYTES_AND_FOOTERS_MATCH_NOT_RESTORE_OR_CUSTODY' if full else 'BLOCKED',
            tuple(sorted(failures)), len(receipts), sum(r.deleted_count for r in receipts), verified, rows,
            missing, extra, full_planned_byte_footer_coverage=full,
            inventory_sha256=inventory_hash, bundle_sha256=bundle_hash)


def review_bytes(inventory: bytes, bundle: bytes) -> ReviewReport:
    """In-memory API; only bounded JSON, ZIP and Parquet metadata processing."""
    try:
        if type(bundle) is not bytes or len(bundle) > MAX_ZIP_BYTES:
            raise ReviewError('ZIP_SIZE_BOUND')
        return _review(inventory, io.BytesIO(bundle))
    except ReviewError as error:
        return ReviewReport('BLOCKED', (str(error),))
    except Exception:
        return ReviewReport('BLOCKED', ('BUNDLE_READ_OR_FORMAT_FAILED',))


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@contextmanager
def _private_file(path: Path, maximum: int) -> Iterator[BinaryIO]:
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ReviewError('ABSOLUTE_NON_UNC_PRIVATE_PATH_REQUIRED')
    if path.resolve().is_relative_to(Path(__file__).resolve().parent):
        raise ReviewError('PRIVATE_INPUT_OUTSIDE_SOURCE_REQUIRED')
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ReviewError('INPUT_LINK_OR_REPARSE_POINT_FORBIDDEN')
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
        raise ReviewError('PRIVATE_FILE_TYPE_OR_SIZE_BOUND')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        opened = os.fstat(stream.fileno())
        # Compare object identity across APIs, timestamps within the SAME API.
        # Windows path and descriptor stat timestamp representations can differ.
        if ((opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size)
                or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1):
            raise ReviewError('INPUT_CHANGED_OR_UNSAFE')
        yield stream
        if _identity(os.fstat(stream.fileno())) != _identity(opened) or _identity(path.lstat()) != _identity(before):
            raise ReviewError('INPUT_CHANGED_OR_UNSAFE')


def review_paths(inventory: Path, bundle: Path) -> ReviewReport:
    try:
        with _private_file(inventory, MAX_INDEX_BYTES) as source:
            raw = source.read(MAX_INDEX_BYTES+1)
            if len(raw) != os.fstat(source.fileno()).st_size:
                raise ReviewError('INCOMPLETE_INVENTORY_READ')
        with _private_file(bundle, MAX_ZIP_BYTES) as archive:
            return _review(raw, archive)
    except ReviewError as error:
        return ReviewReport('BLOCKED', (str(error),))
    except Exception:
        return ReviewReport('BLOCKED', ('PRIVATE_INPUT_READ_FAILED',))


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ReviewError('INVALID_ARGUMENTS')


def main(argv: Sequence[str] | None = None) -> int:
    try:
        parser = _Parser(description='Offline byte/footer review only; preview performs zero input IO.')
        parser.add_argument('--inventory')
        parser.add_argument('--bundle')
        parser.add_argument('--confirm-read', action='store_true')
        args = parser.parse_args(argv)
        if not args.confirm_read:
            print(json.dumps(dict(status='PREVIEW', input_reads=0, writes=0, row_values_read=0,
                                  network_requests=0, credential_reads=0)))
            return 0
        if not args.inventory or not args.bundle:
            raise ReviewError('INVENTORY_AND_ZIP_PATHS_REQUIRED')
        report = review_paths(Path(args.inventory), Path(args.bundle))
    except ReviewError as error:
        report = ReviewReport('BLOCKED', (str(error),))
    print(json.dumps(asdict(report), sort_keys=True, allow_nan=False))
    return 0 if report.full_planned_byte_footer_coverage else 2


if __name__ == '__main__':
    raise SystemExit(main())
