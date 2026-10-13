"""Offline, licensed-development-only source admission; never a downloader.

Publicly accessible is not synonymous with licensed for speculative/ML use. A
trusted verifier must authenticate an external source-specific permission record.
Daily rows remain EOD observations: this cannot create historical intraday fills.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import csv
import hashlib
import io
import json
import re
import stat
import zipfile

MAX_ORIGINAL_BYTES = 8 * 1024 * 1024
MAX_ROWS = 100_000
SOURCE_NAMES = frozenset({'nse_index_daily', 'nse_fo_bhavcopy_legacy',
                          'nse_fo_bhavcopy_udiff', 'nse_contract_master', 'upstox_expired_candles'})


class HistoryError(ValueError):
    """Stable redacted source errors; never print private raw data or permit bytes."""


@dataclass(frozen=True, repr=False)
class Permission:
    """External canonical permission record plus detached authentication evidence."""
    record: bytes = field(repr=False)
    signature: bytes = field(repr=False)


@dataclass(frozen=True, repr=False)
class AdmittedOriginal:
    """Exact original, separate parsed rows and immutable provenance; no fills."""
    original: bytes = field(repr=False)
    rows: tuple[tuple[str, ...], ...] = field(repr=False)
    manifest: bytes = field(repr=False)
    approval_authority: bool = False
    intraday_fill_evidence: bool = False


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def _time(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise HistoryError('HISTORY_TIME_INVALID')
    return value.astimezone(timezone.utc)


def _csv_bytes(original: bytes, *, zipped: bool) -> bytes:
    if type(original) is not bytes or not 0 < len(original) <= MAX_ORIGINAL_BYTES:
        raise HistoryError('HISTORY_ORIGINAL_SIZE_BOUND')
    if not zipped:
        return original
    try:
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise ValueError
            item = entries[0]
            mode = item.external_attr >> 16
            if (item.is_dir() or not re.fullmatch('[A-Za-z0-9_.-]+\\.csv', item.filename)
                    or '..' in item.filename or stat.S_ISLNK(mode) or item.flag_bits & 1
                    or not 0 < item.file_size <= MAX_ORIGINAL_BYTES
                    or item.file_size > max(item.compress_size, 1) * 100):
                raise ValueError
            with archive.open(item) as stream:
                data = stream.read(MAX_ORIGINAL_BYTES + 1)
            if len(data) != item.file_size:
                raise ValueError
            return data
    except Exception:
        raise HistoryError('HISTORY_ARCHIVE_INVALID') from None


def admit_csv(original: bytes, *, source: str, session: date, available_at: datetime,
              received_at: datetime, columns: tuple[str, ...], permission: Permission | None,
              verify_permission: Callable[[bytes, bytes], bool], zipped: bool = False) -> AdmittedOriginal:
    """Authenticate source-specific rights, then parse one bounded exact-schema file.

    Permission is externally issued/reviewed, not generated here. Its fields bind
    source, purpose, schema, zero fee, date range and byte allowance. A verifier
    must check a trusted signature; a permissive callback is NOT commissioning.
    Data date inside each row still needs the source-specific reconciler before
    research use. No model accepts this admission as proof of market authenticity.
    """
    if type(source) is not str or source not in SOURCE_NAMES or type(session) is not date or not date(2022, 1, 1) <= session <= date(2024, 12, 31):
        raise HistoryError('HISTORY_DEVELOPMENT_SCOPE_REQUIRED')
    if type(zipped) is not bool or type(original) is not bytes:
        raise HistoryError('HISTORY_INPUT_TYPE_INVALID')
    available, received = _time(available_at), _time(received_at)
    if available > received or available < datetime.combine(session, time(), timezone(timedelta(hours=5, minutes=30))):
        raise HistoryError('HISTORY_AVAILABILITY_INVALID')
    if (type(columns) is not tuple or not 0 < len(columns) <= 128
            or any(type(name) is not str or not 0 < len(name) <= 128 for name in columns)
            or len(set(columns)) != len(columns)):
        raise HistoryError('HISTORY_SCHEMA_INVALID')
    if permission is None or type(permission) is not Permission:
        raise HistoryError('HISTORY_USAGE_PERMISSION_MISSING')
    schema_sha = hashlib.sha256(_canonical(list(columns))).hexdigest()
    try:
        if (type(permission.record) is not bytes or type(permission.signature) is not bytes
                or not 0 < len(permission.record) <= 16_384 or not 0 < len(permission.signature) <= 4096
                or verify_permission(permission.record, permission.signature) is not True):
            raise ValueError
        record = json.loads(permission.record)
        if (_canonical(record) != permission.record
                or set(record) != {'version', 'source', 'purpose', 'schema_sha256', 'fee_rupees',
                    'start', 'end', 'max_original_bytes', 'storage_allowed', 'revoked'}
                or record['version'] != 'history-usage-permission-v1'
                or record['storage_allowed'] is not True or record['revoked'] is not False
                or record['source'] != source or record['purpose'] != 'PRIVATE_DEVELOPMENT_RESEARCH'
                or record['schema_sha256'] != schema_sha or record['fee_rupees'] != '0'
                or type(record['max_original_bytes']) is not int
                or not 0 < len(original) <= record['max_original_bytes'] <= MAX_ORIGINAL_BYTES
                or not date.fromisoformat(record['start']) <= session <= date.fromisoformat(record['end'])
                or date.fromisoformat(record['end']) > date(2024, 12, 31)):
            raise ValueError
    except Exception:
        raise HistoryError('HISTORY_USAGE_PERMISSION_UNVERIFIED') from None
    content = _csv_bytes(original, zipped=zipped)
    try:
        reader = csv.reader(io.StringIO(content.decode('utf-8-sig'), newline=''), strict=True)
        if tuple(next(reader)) != columns:
            raise ValueError
        rows: list[tuple[str, ...]] = []
        for row in reader:
            if len(row) != len(columns) or any(len(cell) > 8192 or '\x00' in cell for cell in row):
                raise ValueError
            rows.append(tuple(row))
            if len(rows) > MAX_ROWS:
                raise ValueError
        if not rows:
            raise ValueError
    except Exception:
        raise HistoryError('HISTORY_CSV_INVALID') from None
    manifest = _canonical({'version': 'development-source-original-v1', 'source': source,
        'session': session.isoformat(), 'available_at': available.isoformat(),
        'received_at': received.isoformat(), 'original_sha256': hashlib.sha256(original).hexdigest(),
        'original_bytes': len(original), 'parsed_content_sha256': hashlib.sha256(content).hexdigest(),
        'schema_sha256': schema_sha, 'permission_sha256': hashlib.sha256(permission.record).hexdigest(),
        'row_count': len(rows), 'zipped': zipped, 'source_authenticity_verified': False,
        'row_date_reconciliation_verified': False, 'intraday_fill_evidence': False,
        'training_eligible': False, 'approval_authority': False})
    return AdmittedOriginal(original, tuple(rows), manifest)
