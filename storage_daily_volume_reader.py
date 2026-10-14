"""Inactive exact-cut reader for quant_app.market_daily_volumes.

API: DailyVolumeRow, DailyVolumeSnapshot, encode_snapshot, decode_snapshot,
cut_declaration, recover_prior_average_volumes -> DailyVolumeResult.
Only explicit authenticated Candidate/CatalogCut/Tier inputs are accepted.
No SQL, connection, factory, environment, private-file or deletion path exists.
The original table has no availability or revisions: only as_of_at == known_at
is supported. Date filtering is the cut's IST date, not historical PIT inference.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import hashlib
import math
import re
from types import MappingProxyType
from typing import Protocol, cast

from overnight_storage_contracts import (Candidate, CatalogCut, ContractError, Readback,
    Tier, authenticated_catalog, digest, instant, name)
from overnight_storage_sources import SourceRouter

SOURCE = 'quant_app__market_daily_volumes'
FORMAT = 'daily-volume-snapshot-v1'
MAX_BYTES = 64 * 1024
MAX_ROWS = 400
MAX_KEYS = 128
MAX_OBJECTS = 16
MAX_TOTAL_ROWS = 1600
MAX_LOOKBACK = 400
MAX_CATALOG_PAGES = 512
MAX_VOLUME = Decimal('1e18')
IST = timezone(timedelta(hours=5, minutes=30))
ROW_FIELDS = {'instrument_key', 'trade_date', 'max_captured_volume'}
SNAPSHOT_FIELDS = {'format', 'source', 'snapshot', 'revision', 'lower', 'upper', 'known_at', 'rows'}


@dataclass(frozen=True)
class DailyVolumeRow:
    """Exact original three columns; NUMERIC stays Decimal, never a bool/float."""

    instrument_key: str
    trade_date: date
    max_captured_volume: Decimal


@dataclass(frozen=True)
class DailyVolumeSnapshot:
    """Immutable declared export cut, not row-level historical availability."""

    snapshot: str
    revision: int
    lower: datetime
    upper: datetime
    known_at: datetime
    rows: tuple[DailyVolumeRow, ...]


@dataclass(frozen=True)
class DailyVolumeResult:
    averages: Mapping[str, float]
    captured_dates: Mapping[str, tuple[date, ...]]
    rows: tuple[DailyVolumeRow, ...]
    known_at: datetime
    as_of_date: date
    catalog_root: str
    catalog_generation: int
    proofs: tuple[Readback, ...]
    authenticated_declared_cut_verified: bool = True
    complete_source_export_verified: bool = False
    native_sql_parity_verified: bool = False
    global_wired: bool = False
    physical_custody_verified: bool = False
    deletion_authority: bool = False
    historical_pit_verified: bool = False
    exchange_final_volume_verified: bool = False


class _TierCallbacks(Protocol):
    """Local structural type also retains typing with skipped backend imports."""

    @property
    def domain(self) -> str: ...

    def read(self, sha256: str, limit: int) -> bytes | None: ...


@dataclass(frozen=True)
class _RedactedTier:
    """Redact only caller callbacks; retain the router's own validation codes."""

    wrapped: _TierCallbacks

    @property
    def domain(self) -> str:
        try:
            return self.wrapped.domain
        except Exception:
            raise ContractError('DAILY_VOLUME_REPLICA_IDENTITY_UNAVAILABLE') from None

    def read(self, sha256: str, limit: int) -> bytes | None:
        try:
            return self.wrapped.read(sha256, limit)
        except Exception:
            raise ContractError('DAILY_VOLUME_REPLICA_GET_UNAVAILABLE') from None


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('ascii')
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ContractError('DAILY_VOLUME_CANONICAL_INVALID') from None


def _key(value: object) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 160
            or value != value.strip() or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        raise ContractError('DAILY_VOLUME_KEY_INVALID')
    return value


def _numeric(value: object) -> Decimal:
    if (type(value) is not str or len(value) > 64
            or re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value) is None):
        raise ContractError('DAILY_VOLUME_NUMERIC_INVALID')
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ContractError('DAILY_VOLUME_NUMERIC_INVALID') from None
    if not number.is_finite() or number.copy_abs() > MAX_VOLUME:
        raise ContractError('DAILY_VOLUME_NUMERIC_INVALID')
    return number


def _clock(value: object) -> datetime:
    if type(value) is not str or len(value) > 40:
        raise ContractError('DAILY_VOLUME_CLOCK_INVALID')
    try:
        parsed = datetime.fromisoformat(value)
        instant(parsed)
        moment = parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise ContractError('DAILY_VOLUME_CLOCK_INVALID') from None
    if moment.isoformat() != value:
        raise ContractError('DAILY_VOLUME_UTC_CANONICAL_REQUIRED')
    return moment


def _date(value: object) -> date:
    if type(value) is not str:
        raise ContractError('DAILY_VOLUME_DATE_INVALID')
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise ContractError('DAILY_VOLUME_DATE_INVALID') from None
    if day.isoformat() != value:
        raise ContractError('DAILY_VOLUME_DATE_INVALID')
    return day


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ContractError('DAILY_VOLUME_DUPLICATE_FIELD')
        result[key] = value
    return result


def _payload(snapshot: DailyVolumeSnapshot) -> dict[str, object]:
    if type(snapshot.rows) is not tuple or len(snapshot.rows) > MAX_ROWS:
        raise ContractError('DAILY_VOLUME_ROWS_BOUND')
    rows: list[dict[str, object]] = []
    for row in snapshot.rows:
        if (type(row) is not DailyVolumeRow or type(row.trade_date) is not date
                or type(row.max_captured_volume) is not Decimal):
            raise ContractError('DAILY_VOLUME_TYPED_ROW_REQUIRED')
        rows.append({'instrument_key': row.instrument_key, 'trade_date': row.trade_date.isoformat(),
                     'max_captured_volume': str(row.max_captured_volume)})
    return {'format': FORMAT, 'source': SOURCE, 'snapshot': snapshot.snapshot,
            'revision': snapshot.revision, 'lower': instant(snapshot.lower).isoformat(),
            'upper': instant(snapshot.upper).isoformat(), 'known_at': instant(snapshot.known_at).isoformat(),
            'rows': rows}


def encode_snapshot(snapshot: DailyVolumeSnapshot) -> bytes:
    """Pure codec, not an SQL exporter or an attestation of table completeness.

    Order is (instrument_key, trade_date); no columns are added to individual rows.
    Original NUMERIC is an exact decimal string; NOT NULL is enforced.
    """
    raw = _canonical(_payload(snapshot))
    decode_snapshot(raw)
    return raw


def decode_snapshot(raw: bytes) -> DailyVolumeSnapshot:
    """Bounded canonical decoder, suitable as a SourceRouter restore closure."""
    if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES:
        raise ContractError('DAILY_VOLUME_BYTES_BOUND')
    try:
        value: object = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise ContractError('DAILY_VOLUME_JSON_INVALID') from None
    if type(value) is not dict:
        raise ContractError('DAILY_VOLUME_SCHEMA_INVALID')
    obj = cast(dict[str, object], value)
    if set(obj) != SNAPSHOT_FIELDS or obj['format'] != FORMAT or obj['source'] != SOURCE:
        raise ContractError('DAILY_VOLUME_SCHEMA_INVALID')
    if type(obj['snapshot']) is not str:
        raise ContractError('DAILY_VOLUME_SNAPSHOT_INVALID')
    snapshot_id = name(obj['snapshot'])
    revision = obj['revision']
    if type(revision) is not int or not 1 <= revision <= 2**31 - 1:
        raise ContractError('DAILY_VOLUME_REVISION_INVALID')
    lower, upper, known = (_clock(obj[k]) for k in ('lower', 'upper', 'known_at'))
    if not lower < upper <= known:
        raise ContractError('DAILY_VOLUME_PROVENANCE_CUT_INVALID')
    if type(obj['rows']) is not list:
        raise ContractError('DAILY_VOLUME_ROWS_BOUND')
    items = cast(list[object], obj['rows'])
    if len(items) > MAX_ROWS:
        raise ContractError('DAILY_VOLUME_ROWS_BOUND')
    rows: list[DailyVolumeRow] = []
    seen: dict[tuple[str, date], Decimal] = {}
    keys: set[str] = set()
    for item in items:
        if type(item) is not dict:
            raise ContractError('DAILY_VOLUME_ROW_SCHEMA_INVALID')
        row = cast(dict[str, object], item)
        if set(row) != ROW_FIELDS:
            raise ContractError('DAILY_VOLUME_ROW_SCHEMA_INVALID')
        key, day, volume = _key(row['instrument_key']), _date(row['trade_date']), _numeric(row['max_captured_volume'])
        midnight = datetime.combine(day, datetime.min.time(), IST).astimezone(timezone.utc)
        if not lower <= midnight < upper or day > known.astimezone(IST).date():
            raise ContractError('DAILY_VOLUME_FUTURE_OR_OUT_OF_CUT_ROW')
        identity = (key, day)
        if identity in seen:
            raise ContractError('DAILY_VOLUME_DUPLICATE_CONFLICT' if seen[identity] != volume
                                else 'DAILY_VOLUME_DUPLICATE_ROW')
        seen[identity] = volume
        keys.add(key)
        if len(keys) > MAX_KEYS:
            raise ContractError('DAILY_VOLUME_KEYS_BOUND')
        rows.append(DailyVolumeRow(key, day, volume))
    if rows != sorted(rows, key=lambda row: (row.instrument_key, row.trade_date)):
        raise ContractError('DAILY_VOLUME_ROW_ORDER_INVALID')
    if _canonical(obj) != raw:
        raise ContractError('DAILY_VOLUME_NONCANONICAL_BYTES')
    return DailyVolumeSnapshot(snapshot_id, revision, lower, upper, known, tuple(rows))


def restore_witness(raw: bytes) -> str:
    """Canonical semantic witness; source hashes still authenticate original bytes."""
    decode_snapshot(raw)
    return hashlib.sha256(b'daily-volume-restored-v1:' + raw).hexdigest()


def cut_declaration(cut_id: str, known_at: datetime,
                    candidates: Sequence[Candidate]) -> dict[str, object]:
    """Metadata to place in an authenticated catalog, NOT a publication/exporter.

    The caller must independently pin the CatalogCut and externally supplied keys.
    Catalog key is 'daily-volume-cut:' + cut_id. A signed declaration asserts its
    exact object set only: it does not prove that SQL exported every source row.
    """
    name(cut_id)
    if type(candidates) not in (list, tuple) or not 1 <= len(candidates) <= MAX_OBJECTS:
        raise ContractError('DAILY_VOLUME_OBJECTS_BOUND')
    if (any(type(c) is not Candidate or c.source != SOURCE for c in candidates)
            or len({c.snapshot for c in candidates}) != len(candidates)):
        raise ContractError('DAILY_VOLUME_CANDIDATE_SOURCE_OR_DUPLICATE')
    return {'format': 'daily-volume-cut-v1', 'source': SOURCE, 'cut_id': cut_id,
            'known_at': instant(known_at).isoformat(),
            'objects': [c.metadata() for c in sorted(candidates, key=lambda c: c.identity)],
            'coverage': 'DECLARED_WHOLE_SNAPSHOT_NOT_DATABASE_COMPLETENESS'}


def recover_prior_average_volumes(*, candidates: Sequence[Candidate], cut: CatalogCut,
        cut_id: str, known_at: datetime, as_of_at: datetime,
        keys: Mapping[str, bytes], pages: Callable[[str], bytes | None],
        tiers: Sequence[Tier], instrument_keys: Sequence[str], lookback: int = 20,
        hot: Mapping[str, bytes] | None = None) -> DailyVolumeResult:
    """Recover a whole declared cut, then average prior captured dates per key.

    Every requested tier must pass SourceRouter.recover. Restore closures retain
    only immutable bytes after candidate size/hash checks, and those snapshots are
    used only after all proofs succeed. There are NO second tier reads, subset
    fast paths, SQL materialized-query fixtures or hot-only fallbacks.

    SQL reference: production_repository.prior_average_volumes and the original
    three-column SQL draft in public overnight-app-rehearsal. Finite zero/negative
    values participate; only strictly positive averages are returned. NaN/null/
    bool/exotic inputs fail rather than pretending that rows were absent. fsum on
    float-normalized NUMERIC is deterministic here but native SQL double parity
    must be commissioned before activation. Counts refer to captured dates, NOT
    calendar sessions or exchange-final volumes.
    """
    known = instant(known_at)
    if instant(as_of_at) != known:
        raise ContractError('DAILY_VOLUME_ASOF_NOT_EXACT_KNOWN_CUT')
    if type(lookback) is not int or not 1 <= lookback <= MAX_LOOKBACK:
        raise ContractError('DAILY_VOLUME_LOOKBACK_BOUND')
    if type(instrument_keys) not in (tuple, list) or len(instrument_keys) > MAX_KEYS:
        raise ContractError('DAILY_VOLUME_QUERY_KEYS_BOUND')
    requested = tuple(dict.fromkeys(_key(k) for k in instrument_keys))
    if type(candidates) not in (list, tuple) or not 1 <= len(candidates) <= MAX_OBJECTS:
        raise ContractError('DAILY_VOLUME_OBJECTS_BOUND')
    candidate_set = tuple(candidates)
    declaration = cut_declaration(cut_id, known, candidate_set)
    if not 1 <= len(keys) <= 16:
        raise ContractError('DAILY_VOLUME_EXPLICIT_KEYS_BOUND')
    keyring = dict(keys)
    if any(type(k) is not str or not 1 <= len(k) <= 128 or type(v) is not bytes
           or not 32 <= len(v) <= 4096 for k, v in keyring.items()):
        raise ContractError('DAILY_VOLUME_EXPLICIT_KEYS_INVALID')
    if hot is not None and len(hot) > MAX_OBJECTS:
        raise ContractError('DAILY_VOLUME_HOT_WHOLE_CUT_REQUIRED')
    hot_copy = None if hot is None else dict(hot)
    if hot_copy is not None and set(hot_copy) != {c.identity for c in candidate_set}:
        raise ContractError('DAILY_VOLUME_HOT_WHOLE_CUT_REQUIRED')
    if not 1 <= len(tiers) <= 4:
        raise ContractError('TIER_BOUND_INVALID')
    tier_set = tuple(_RedactedTier(tier) for tier in tiers)
    # Cache immutable authenticated catalog pages for all subsequent recoveries.
    # A complete traversal is required, never an early successful lookup prefix.
    cached_pages: dict[str, bytes | None] = {}
    def fetch(page_id: str) -> bytes | None:
        if page_id not in cached_pages:
            if len(cached_pages) >= MAX_CATALOG_PAGES:
                raise ContractError('DAILY_VOLUME_CATALOG_PAGE_BOUND')
            try:
                raw = pages(page_id)
            except Exception:
                raise ContractError('DAILY_VOLUME_CATALOG_GET_UNAVAILABLE') from None
            if raw is not None and (type(raw) is not bytes or len(raw) > MAX_BYTES):
                raise ContractError('DAILY_VOLUME_CATALOG_PAGE_INVALID')
            cached_pages[page_id] = raw
        return cached_pages[page_id]
    try:
        index = authenticated_catalog(cut, keyring, fetch)
        index.audit()
        if index.lookup('daily-volume-cut:' + cut_id) != declaration:
            raise ContractError('DAILY_VOLUME_AUTHENTICATED_WHOLE_CUT_MISSING')
    except ContractError:
        raise
    except Exception:
        raise ContractError('DAILY_VOLUME_CATALOG_AUTHENTICATION_OR_FULL_CUT_FAILED') from None
    proofs: list[Readback] = []
    snapshots: list[DailyVolumeSnapshot] = []
    for candidate in candidate_set:
        captured: list[tuple[bytes, DailyVolumeSnapshot]] = []
        def restore(raw: bytes) -> str:
            if (type(raw) is not bytes or len(raw) != candidate.size
                    or len(raw) > MAX_BYTES or digest(raw) != candidate.sha256):
                raise ContractError('DAILY_VOLUME_VERIFIED_BYTES_REQUIRED')
            snapshot = decode_snapshot(raw)
            if (snapshot.snapshot != candidate.snapshot or snapshot.revision != candidate.revision
                    or snapshot.lower != instant(candidate.lower) or snapshot.upper != instant(candidate.upper)
                    or snapshot.known_at != known):
                raise ContractError('DAILY_VOLUME_PROVENANCE_CUT_MISMATCH')
            witness = digest(b'daily-volume-restored-v1:' + raw)
            if witness != candidate.witness:
                raise ContractError('RESTORE_WITNESS_MISMATCH')
            if captured and captured[0][0] != raw:
                raise ContractError('DAILY_VOLUME_REPLICA_PARITY_MISMATCH')
            captured.append((raw, snapshot))
            return hashlib.sha256(b'daily-volume-restored-v1:' + raw).hexdigest()
        try:
            proof = SourceRouter({SOURCE: restore}).recover(candidate, cut, keyring, fetch, tier_set,
                hot=None if hot_copy is None else hot_copy[candidate.identity])
        except ContractError:
            raise
        except Exception:
            raise ContractError('DAILY_VOLUME_RECOVERY_UNAVAILABLE') from None
        if not captured or len(captured) != len(tier_set) + (1 if hot_copy is not None else 0):
            raise ContractError('DAILY_VOLUME_FULL_REPLICA_PROOF_REQUIRED')
        proofs.append(proof)
        snapshots.append(captured[0][1])
    all_rows: list[DailyVolumeRow] = []
    seen: dict[tuple[str, date], Decimal] = {}
    all_keys: set[str] = set()
    for snapshot in snapshots:
        for row in snapshot.rows:
            identity = (row.instrument_key, row.trade_date)
            if identity in seen:
                raise ContractError('DAILY_VOLUME_DUPLICATE_CONFLICT' if seen[identity] != row.max_captured_volume
                                    else 'DAILY_VOLUME_DUPLICATE_ROW')
            seen[identity] = row.max_captured_volume
            all_keys.add(row.instrument_key)
            all_rows.append(row)
            if len(all_rows) > MAX_TOTAL_ROWS or len(all_keys) > MAX_KEYS:
                raise ContractError('DAILY_VOLUME_WHOLE_CUT_BOUND')
    cutoff = known.astimezone(IST).date()
    averages: dict[str, float] = {}
    captured_dates: dict[str, tuple[date, ...]] = {}
    for key in requested:
        selected = sorted((row for row in all_rows if row.instrument_key == key
                           and row.trade_date < cutoff), key=lambda row: row.trade_date, reverse=True)[:lookback]
        captured_dates[key] = tuple(row.trade_date for row in selected)
        if selected:
            try:
                average = math.fsum(float(row.max_captured_volume) for row in selected) / len(selected)
            except (OverflowError, ValueError):
                raise ContractError('DAILY_VOLUME_NONFINITE_AVERAGE') from None
            if not math.isfinite(average):
                raise ContractError('DAILY_VOLUME_NONFINITE_AVERAGE')
            if average > 0:
                averages[key] = average
    return DailyVolumeResult(MappingProxyType(averages), MappingProxyType(captured_dates),
        tuple(sorted(all_rows, key=lambda row: (row.instrument_key, row.trade_date))),
        known, cutoff, cut.trusted.root, cut.trusted.generation, tuple(proofs))
