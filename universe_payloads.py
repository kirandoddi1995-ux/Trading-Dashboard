"""Bounded, lossless content-addressed universe payloads for offline shadow reads.

No database adapter, migration, deletion or inferred observation times. Preserve
the caller's exact serialized bytes; equivalent JSON with different bytes remains
distinct. This deliberately prefers missed savings over silently changing evidence.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import hashlib
import re

MAX_ROWS = 10_000
MAX_VALUE_BYTES = 1024 * 1024
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024


class PayloadError(ValueError):
    """Stable errors without private instruments, source JSON or paths."""


@dataclass(frozen=True)
class Member:
    """Explicit logical key, all non-raw fields, and exact serialized raw bytes."""
    instrument_key: str = field(repr=False)
    fields: bytes = field(repr=False)
    raw: bytes = field(repr=False)


@dataclass(frozen=True)
class Reference:
    """Membership identity remains per snapshot; only raw bytes are shared."""
    instrument_key: str = field(repr=False)
    fields: bytes = field(repr=False)
    raw_sha256: str


@dataclass(frozen=True)
class Payload:
    sha256: str
    data: bytes = field(repr=False)


@dataclass(frozen=True)
class ShadowSnapshot:
    """Owner-supplied full header, original order and fingerprint, not custody."""
    header: bytes = field(repr=False)
    references: tuple[Reference, ...] = field(repr=False)
    payloads: tuple[Payload, ...] = field(repr=False)
    source_sha256: str
    source_raw_bytes: int
    unique_raw_bytes: int


def _value(data: object) -> bytes:
    if type(data) is not bytes or not 1 <= len(data) <= MAX_VALUE_BYTES:
        raise PayloadError('UNIVERSE_VALUE_BOUND')
    return data


def _key(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise PayloadError('UNIVERSE_KEY_INVALID')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise PayloadError('UNIVERSE_KEY_INVALID') from None
    return value


def _hash(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise PayloadError('UNIVERSE_DIGEST_INVALID')
    return value


def _fingerprint(header: bytes, rows: tuple[Member, ...]) -> str:
    digest = hashlib.sha256(b'universe-shadow-v1\x00')
    digest.update(len(header).to_bytes(8, 'big'))
    digest.update(header)
    digest.update(len(rows).to_bytes(8, 'big'))
    for row in rows:
        for data in (row.instrument_key.encode('utf-8'), row.fields, row.raw):
            digest.update(len(data).to_bytes(8, 'big'))
            digest.update(data)
    return digest.hexdigest()


def _normalize(header: bytes, members: Iterable[Member]) -> ShadowSnapshot:
    _value(header)
    rows: list[Member] = []
    references: list[Reference] = []
    pool: dict[str, bytes] = {}
    seen: set[str] = set()
    size = len(header)
    raw_size = 0
    for row in members:
        if type(row) is not Member or len(rows) >= MAX_ROWS:
            raise PayloadError('UNIVERSE_ROW_BOUND')
        key = _key(row.instrument_key)
        if key in seen:
            raise PayloadError('UNIVERSE_DUPLICATE_MEMBER')
        fields, raw = _value(row.fields), _value(row.raw)
        size += len(key.encode('utf-8')) + len(fields) + len(raw)
        if size > MAX_SNAPSHOT_BYTES:
            raise PayloadError('UNIVERSE_SNAPSHOT_BOUND')
        digest = hashlib.sha256(raw).hexdigest()
        if digest in pool and pool[digest] != raw:
            raise PayloadError('UNIVERSE_DIGEST_COLLISION')
        pool[digest] = raw
        seen.add(key)
        rows.append(row)
        references.append(Reference(key, fields, digest))
        raw_size += len(raw)
    if not rows:
        raise PayloadError('UNIVERSE_EMPTY_SNAPSHOT')
    return ShadowSnapshot(header, tuple(references),
        tuple(Payload(k, v) for k, v in sorted(pool.items())),
        _fingerprint(header, tuple(rows)), raw_size, sum(map(len, pool.values())))


def normalize(header: bytes, members: Iterable[Member]) -> ShadowSnapshot:
    """Bound a snapshot, preserve every supplied field/order, share raw ONLY.

    Adapter must supply all header/column bytes, not a selected subset. No PIT
    timestamp, version ID or canonical snapshot is invented. Iterator exceptions
    are redacted; iterator owns its I/O timeout. No partial result is returned.
    """
    try:
        return _normalize(header, members)
    except PayloadError:
        raise
    except Exception:
        raise PayloadError('UNIVERSE_SOURCE_UNAVAILABLE') from None


def reconstruct(header: bytes, references: tuple[Reference, ...], *,
                get_payload: Callable[[str], bytes], expected_source_sha256: str) -> tuple[Member, ...]:
    """Resolve ALL payloads; missing/corrupt history never becomes an empty universe.

    Callback owns its I/O timeout and immutable-read custody. No cache fallback;
    referenced bytes and independently retained full source fingerprint must agree.
    """
    _value(header)
    _hash(expected_source_sha256)
    if type(references) is not tuple or not 1 <= len(references) <= MAX_ROWS:
        raise PayloadError('UNIVERSE_ROW_BOUND')
    members: list[Member] = []
    seen: set[str] = set()
    size = len(header)
    for reference in references:
        if type(reference) is not Reference:
            raise PayloadError('UNIVERSE_REFERENCE_INVALID')
        key = _key(reference.instrument_key)
        fields = _value(reference.fields)
        digest = _hash(reference.raw_sha256)
        if key in seen:
            raise PayloadError('UNIVERSE_DUPLICATE_MEMBER')
        try:
            raw = _value(get_payload(digest))
        except Exception:
            raise PayloadError('UNIVERSE_PAYLOAD_UNAVAILABLE') from None
        if hashlib.sha256(raw).hexdigest() != digest:
            raise PayloadError('UNIVERSE_PAYLOAD_CORRUPT')
        size += len(key.encode('utf-8')) + len(fields) + len(raw)
        if size > MAX_SNAPSHOT_BYTES:
            raise PayloadError('UNIVERSE_SNAPSHOT_BOUND')
        members.append(Member(key, fields, raw))
        seen.add(key)
    result = tuple(members)
    if _fingerprint(header, result) != expected_source_sha256:
        raise PayloadError('UNIVERSE_SOURCE_MISMATCH')
    return result
