"""Synthetic digest identities only: no historical data/DB/filesystem reads."""
from __future__ import annotations

from dataclasses import asdict, replace
from itertools import permutations

import pytest

import archive_restore_policy as p


def row(n: int = 0, *, key: str = 'a', value: str = 'b', table: str = 'market_quotes') -> p.RowIdentity:
    return p.RowIdentity(table, 'c' * 64, n, key * 64, value * 64, 'd' * 64)


def test_duplicates_preserved_as_counts_never_removed_or_authorised() -> None:
    result = p.review_versions([row(), row(1), row(2, key='e')], expected_rows=3)
    assert (result.rows, result.unique_keys, result.unique_versions,
            result.exact_duplicate_occurrences, result.conflicting_keys) == (3, 2, 2, 1, 0)
    assert all(value is False for value in asdict(result).values() if type(value) is bool)
    assert 'a' * 64 not in repr(result)


@pytest.mark.parametrize('order', list(permutations(range(3))))
def test_conflict_never_latest_file_or_order_wins(order: tuple[int, ...]) -> None:
    source = [row(), row(1, value='f'), row(2)]
    result = p.review_versions((source[i] for i in order), expected_rows=3)
    assert result.conflicting_keys == 1
    assert result.unique_versions == 2
    assert result.exact_duplicate_occurrences == 1
    assert result.restore_authorised is False


def test_tables_scoped_and_cross_batch_duplicate_is_not_source_position_duplicate() -> None:
    result = p.review_versions([row(), replace(row(), batch_sha256='e' * 64),
                               row(table='mf_nav')], expected_rows=3)
    assert result.unique_keys == 2 and result.exact_duplicate_occurrences == 1
    with pytest.raises(ValueError, match='DUPLICATE_SOURCE_POSITION'):
        p.review_versions([row(), row()], expected_rows=2)


def test_mixed_schema_blocks_even_when_row_digest_equal() -> None:
    with pytest.raises(ValueError, match='SCHEMA_VERSION_MIX'):
        p.review_versions([row(), replace(row(1), schema_sha256='e' * 64)], expected_rows=2)


@pytest.mark.parametrize('count', [True, 0, -1, 1.0, p.MAX_ROWS + 1])
def test_denominator_validation(count: int) -> None:
    with pytest.raises(ValueError, match='BOUNDED_INTEGER'):
        p.review_versions([], expected_rows=count)


def test_stream_count_bounds_and_type() -> None:
    with pytest.raises(ValueError, match='MISMATCH'):
        p.review_versions([], expected_rows=1)
    with pytest.raises(ValueError, match='EXCEEDED'):
        p.review_versions([row(), row(1)], expected_rows=1)
    with pytest.raises(ValueError, match='ROW_IDENTITY_REQUIRED'):
        p.review_versions([None], expected_rows=1)  # type: ignore[list-item]


@pytest.mark.parametrize('field,value', [('table', 'arbitrary'), ('ordinal', True),
    ('ordinal', -1), ('key_sha256', 'A' * 64), ('row_sha256', ''),
    ('schema_sha256', 'not a digest'), ('batch_sha256', 3)])
def test_row_identity_fields(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(row(), **{field: value})


@pytest.mark.parametrize('available,fit', [(59, False), (60, True), (61, True)])
def test_space_budgets_include_all_new_allocations_not_ciphertext_size(available: int, fit: bool) -> None:
    result = p.review_space(retained_inputs=10, staging=10, restored_heap=10,
        indexes=10, wal_and_temp=10, safety_reserve=10, available_bytes=available)
    assert result.planned_peak_bytes == 60 and result.planned_budget_fits is fit
    assert result.restore_authorised is False and result.estimate_is_measurement is False


@pytest.mark.parametrize('field,value', [('staging', 0), ('wal_and_temp', 0),
    ('safety_reserve', 0), ('restored_heap', -1), ('indexes', True),
    ('available_bytes', p.MAX_BYTES + 1), ('retained_inputs', 1.5)])
def test_space_unknown_invalid_or_overflow_rejected(field: str, value: object) -> None:
    values = dict(retained_inputs=0, staging=1, restored_heap=1,
        indexes=1, wal_and_temp=1, safety_reserve=1, available_bytes=100)
    values[field] = value  # type: ignore[assignment]
    with pytest.raises(ValueError):
        p.review_space(**values)
    with pytest.raises(ValueError):
        p.review_space(retained_inputs=p.MAX_BYTES, staging=1, restored_heap=1,
            indexes=1, wal_and_temp=1, safety_reserve=1, available_bytes=p.MAX_BYTES)
