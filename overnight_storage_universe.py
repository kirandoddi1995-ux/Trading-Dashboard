"""Inactive exact-row universe raw-payload shadow; never reads a DB or deletes.

This separates repeated JSONB payloads from membership identities without merging
snapshots, intervals, observations or revisions. Recovery originals stay primary.
Wire-byte estimates are not Postgres allocation or guaranteed reclaim estimates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
from typing import Any, Sequence

MAX_ROWS = 100_000
MAX_BYTES = 64 * 1024 * 1024
MAX_ROW = 32 * 1024
MAX_RAW = 16 * 1024
COMMON = frozenset(('instrument_key', 'trading_symbol', 'isin', 'name', 'exchange',
    'segment', 'instrument_type', 'security_type', 'sector', 'source', 'observed_at', 'raw'))
TABLES = {'quant_app.universe_membership': 'snapshot_date',
          'quant_app.universe_membership_versions': 'snapshot_id'}


class UniverseError(ValueError):
    """Redacted, stable projection/recovery error."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        if key in result:
            raise UniverseError('DUPLICATE_FIELD')
        result[key] = value
    return result


def read_row(raw: bytes, table: str) -> dict[str, Any]:
    """Require exact canonical supplied export row; no silent normalization."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_ROW or table not in TABLES:
            raise ValueError()
        row: Any = json.loads(raw, object_pairs_hook=pairs)
        if type(row) is not dict or set(row) != COMMON | {TABLES[table]} or canonical(row) != raw:
            raise ValueError()
        if type(row['raw']) is not dict or len(canonical(row['raw'])) > MAX_RAW:
            raise ValueError()
        for key, value in row.items():
            if key != 'raw' and value is not None and (type(value) is not str or len(value) > 1024):
                raise ValueError()
        for key in ('instrument_key', 'trading_symbol', 'source', 'observed_at', TABLES[table]):
            if type(row[key]) is not str or not row[key].strip():
                raise ValueError()
        at = datetime.fromisoformat(row['observed_at'])
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError()
        if TABLES[table] == 'snapshot_date':
            if date.fromisoformat(row['snapshot_date']).isoformat() != row['snapshot_date']:
                raise ValueError()
        elif re.fullmatch('[0-9a-f]{64}', row['snapshot_id']) is None:
            raise ValueError()
        return row
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise UniverseError('UNIVERSE_ROW_INVALID') from None


@dataclass(frozen=True)
class Member:
    identity: tuple[str, str]
    metadata: bytes
    raw_sha256: str
    original_sha256: str


@dataclass(frozen=True)
class UniverseShadow:
    table: str
    generation_sha256: str
    members: tuple[Member, ...]
    objects: tuple[tuple[str, bytes], ...]
    witness_sha256: str
    original_wire_bytes: int
    shadow_wire_bytes: int
    database_reclaim_verified: bool = False
    custody_verified: bool = False
    deletion_authority: bool = False


def witness(table: str, generation: str, members: tuple[Member, ...]) -> str:
    return digest(canonical({'format': 'universe-exact-raw-shadow-v1', 'table': table,
        'generation': generation, 'members': [{'identity': member.identity,
            'metadata_sha256': digest(member.metadata), 'raw_sha256': member.raw_sha256,
            'original_sha256': member.original_sha256} for member in members]}))


def build_shadow(rows: Sequence[bytes], *, table: str, generation_sha256: str) -> UniverseShadow:
    """Keep every PK identity; duplicate supplied identities block, even identical."""
    if (type(table) is not str or table not in TABLES or type(rows) not in (list, tuple)
            or type(generation_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', generation_sha256) is None
            or not 0 < len(rows) <= MAX_ROWS):
        raise UniverseError('UNIVERSE_INPUT_INVALID')
    members: list[Member] = []
    objects: dict[str, bytes] = {}
    seen: set[tuple[str, str]] = set()
    total = 0
    for original in rows:
        row = read_row(original, table)
        total += len(original)
        if total > MAX_BYTES:
            raise UniverseError('UNIVERSE_INPUT_LIMIT')
        identity = (row[TABLES[table]], row['instrument_key'])
        if identity in seen:
            raise UniverseError('UNIVERSE_DUPLICATE_IDENTITY')
        seen.add(identity)
        raw = canonical(row.pop('raw'))
        pointer = digest(raw)
        if pointer in objects and objects[pointer] != raw:
            raise UniverseError('UNIVERSE_HASH_CONFLICT')
        objects[pointer] = raw
        members.append(Member(identity, canonical(row), pointer, digest(original)))
    ordered = tuple(sorted(members, key=lambda member: member.identity))
    object_rows = tuple(sorted(objects.items()))
    size = sum(len(data) + 64 for _, data in object_rows) + sum(
        len(member.metadata) + 128 for member in ordered)
    result = UniverseShadow(table, generation_sha256, ordered, object_rows,
        witness(table, generation_sha256, ordered), total, size)
    recovered = restore_shadow(result)
    if sorted(recovered) != sorted(rows):
        raise UniverseError('UNIVERSE_PARITY_FAILED')
    return result


def restore_shadow(shadow: UniverseShadow) -> tuple[bytes, ...]:
    """Exact original-row parity; never grant authority or fall back to hot data."""
    try:
        if (type(shadow) is not UniverseShadow or type(shadow.table) is not str
                or shadow.table not in TABLES or type(shadow.generation_sha256) is not str
                or re.fullmatch('[0-9a-f]{64}', shadow.generation_sha256) is None
                or type(shadow.members) is not tuple or type(shadow.objects) is not tuple
                or not 0 < len(shadow.objects) <= MAX_ROWS
                or not 0 < len(shadow.members) <= MAX_ROWS
                or witness(shadow.table, shadow.generation_sha256, shadow.members) != shadow.witness_sha256
                or any(type(flag) is not bool or flag for flag in
                    (shadow.database_reclaim_verified, shadow.custody_verified, shadow.deletion_authority))):
            raise ValueError()
        objects = dict(shadow.objects)
        if len(objects) != len(shadow.objects) or set(objects) != {m.raw_sha256 for m in shadow.members}:
            raise ValueError()
        identities: set[tuple[str, str]] = set()
        restored: list[bytes] = []
        total = 0
        for member in shadow.members:
            raw = objects[member.raw_sha256]
            if type(raw) is not bytes or len(raw) > MAX_RAW or digest(raw) != member.raw_sha256:
                raise ValueError()
            if type(member.metadata) is not bytes or len(member.metadata) > MAX_ROW:
                raise ValueError()
            metadata: Any = json.loads(member.metadata, object_pairs_hook=pairs)
            payload: Any = json.loads(raw, object_pairs_hook=pairs)
            if type(metadata) is not dict or 'raw' in metadata or canonical(metadata) != member.metadata:
                raise ValueError()
            original = canonical({**metadata, 'raw': payload})
            row = read_row(original, shadow.table)
            identity = (row[TABLES[shadow.table]], row['instrument_key'])
            if identity != member.identity or identity in identities or digest(original) != member.original_sha256:
                raise ValueError()
            identities.add(identity)
            total += len(original)
            if total > MAX_BYTES:
                raise ValueError()
            restored.append(original)
        if total != shadow.original_wire_bytes:
            raise ValueError()
        size = sum(len(data) + 64 for _, data in shadow.objects) + sum(
            len(member.metadata) + 128 for member in shadow.members)
        if size != shadow.shadow_wire_bytes:
            raise ValueError()
        return tuple(restored)
    except (KeyError, ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise UniverseError('UNIVERSE_SHADOW_RESTORE_BLOCKED') from None
