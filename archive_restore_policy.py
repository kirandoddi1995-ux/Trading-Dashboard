"""Inactive, digest-only cross-batch review. No row decoding, IO or restore authority.

The future typed decoder must derive key/row digests from validated canonical
values using one reviewed schema. Caller-supplied digests are NOT that proof.
Every original source position must remain in immutable staging, including
duplicates. This module returns counts only; it never chooses a winning row.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import re

TABLES = frozenset({'market_quotes', 'mf_nav', 'scanner_observations',
    'universe_membership', 'universe_membership_versions', 'equity_research.outcomes'})
MAX_ROWS = 1_000_000
MAX_BYTES = 2**63 - 1


def _hash(value: object) -> str:
    if type(value) is not str or re.fullmatch('[a-f0-9]{64}', value) is None:
        raise ValueError('EXACT_DIGEST_REQUIRED')
    return value


def _integer(value: object, maximum: int, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('BOUNDED_INTEGER_REQUIRED')
    return value


@dataclass(frozen=True, repr=False)
class RowIdentity:
    table: str
    batch_sha256: str
    ordinal: int
    key_sha256: str
    row_sha256: str
    schema_sha256: str

    def __post_init__(self) -> None:
        if type(self.table) is not str or self.table not in TABLES:
            raise ValueError('REVIEWED_TABLE_REQUIRED')
        for value in (self.batch_sha256, self.key_sha256, self.row_sha256, self.schema_sha256):
            _hash(value)
        _integer(self.ordinal, MAX_ROWS - 1)


@dataclass(frozen=True)
class ConflictReview:
    rows: int
    unique_keys: int
    unique_versions: int
    exact_duplicate_occurrences: int
    conflicting_keys: int
    status: str = field(default='DIGEST_REVIEW_NOT_TYPED_RESTORE', init=False)
    row_values_verified: bool = field(default=False, init=False)
    same_generation_verified: bool = field(default=False, init=False)
    custody_verified: bool = field(default=False, init=False)
    restore_authorised: bool = field(default=False, init=False)
    deletion_authorised: bool = field(default=False, init=False)
    training_eligible: bool = field(default=False, init=False)


def review_versions(rows: Iterable[RowIdentity], *, expected_rows: int) -> ConflictReview:
    """Reject repeated source positions/schema mixing; never latest-file-wins.

    Equality is scoped to table + schema + key + full-row digest, not a timestamp,
    receipt ordering, payload hash alone or a table-wide source hash. Memory is
    bounded by MAX_ROWS identities. A conflict remains a conflict in any order.
    Completeness is only against the supplied denominator, not the live database.
    """
    _integer(expected_rows, MAX_ROWS, minimum=1)
    positions: set[tuple[str, str, int]] = set()
    schemas: dict[str, str] = {}
    versions: dict[tuple[str, str], set[str]] = {}
    count = 0
    for row in rows:
        count += 1
        if count > expected_rows:
            raise ValueError('ROW_DENOMINATOR_EXCEEDED')
        if type(row) is not RowIdentity:
            raise ValueError('ROW_IDENTITY_REQUIRED')
        row.__post_init__()
        position = (row.table, row.batch_sha256, row.ordinal)
        if position in positions:
            raise ValueError('DUPLICATE_SOURCE_POSITION')
        positions.add(position)
        previous = schemas.setdefault(row.table, row.schema_sha256)
        if previous != row.schema_sha256:
            raise ValueError('SCHEMA_VERSION_MIX_REVIEW_REQUIRED')
        versions.setdefault((row.table, row.key_sha256), set()).add(row.row_sha256)
    if count != expected_rows:
        raise ValueError('ROW_DENOMINATOR_MISMATCH')
    distinct = sum(len(values) for values in versions.values())
    return ConflictReview(count, len(versions), distinct, count - distinct,
                          sum(len(values) > 1 for values in versions.values()))


@dataclass(frozen=True)
class SpaceReview:
    planned_peak_bytes: int
    available_bytes: int
    planned_budget_fits: bool
    restore_authorised: bool = field(default=False, init=False)
    estimate_is_measurement: bool = field(default=False, init=False)


def review_space(*, retained_inputs: int, staging: int, restored_heap: int,
                 indexes: int, wal_and_temp: int, safety_reserve: int,
                 available_bytes: int) -> SpaceReview:
    """One target filesystem's explicit NEW allocation budgets, not a size oracle.

    Never infer decompressed heap/index/WAL size from .7z size. For separate
    filesystems call separately; D: free space is not Docker VM free space.
    Retained inputs means copies still needing allocation on THIS filesystem.
    """
    parts = (retained_inputs, staging, restored_heap, indexes, wal_and_temp, safety_reserve)
    for value in (*parts, available_bytes):
        _integer(value, MAX_BYTES)
    if any(value == 0 for value in (staging, restored_heap, indexes, wal_and_temp, safety_reserve)):
        raise ValueError('NONZERO_RESTORE_BUDGETS_REQUIRED')
    total = _integer(sum(parts), MAX_BYTES, minimum=1)
    return SpaceReview(total, available_bytes, total <= available_bytes)
