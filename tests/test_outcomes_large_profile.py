"""Candidate profile tests use invented metadata,never private outcome rows."""
from __future__ import annotations

import copy
from typing import Any

import pytest

import outcomes_large_profile as profile


def observation() -> dict[str, Any]:
    columns = {}
    for name in profile.COLUMNS:
        size = 17*profile.MIB if name in profile.LARGE_COLUMNS else 128
        failures = {key: int(key == 'uncompressed_within_16mib' and size > 16*profile.MIB)
                    for key in ('no_external_file', 'zstd_codec', 'value_count_matches',
                        'uncompressed_positive', 'uncompressed_within_16mib', 'compressed_positive',
                        'compressed_within_file', 'offsets_within_file')}
        columns[name] = dict(chunks=1, max_uncompressed_bytes=size, sum_uncompressed_bytes=size,
            max_compressed_bytes=100, sum_compressed_bytes=100, predicate_failures=failures)
    return dict(declared_rows=100, row_groups=1, file_bytes=100000, footer_bytes=1024,
        declared_expanded_bytes=sum(c['max_uncompressed_bytes'] for c in columns.values()), columns=columns,
        file_checks=dict(row_group_totals_match=True,row_group_rows_match=True,file_expansion_within_128mib=True),
        original_guard_result='PARQUET_COLUMN_EXPANSION_BOUND', failed_predicates=['uncompressed_within_16mib'])


def test_candidate_is_separate_and_never_admission() -> None:
    result = profile.assess('equity_research.outcomes', observation())
    assert result['candidate_metadata_match'] is True
    assert all(result[key] is False for key in ('commissioned','private_decode_authorised',
        'full_catalog_byte_footer_coverage','logical_restore_verified','independent_custody_verified',
        'deletion_authorised','training_eligible','approval_authority'))
    from archive_recovery_review import MAX_COLUMN_EXPANDED
    assert MAX_COLUMN_EXPANDED == 16*profile.MIB


@pytest.mark.parametrize('name', ['payload', '_row_json', 'snapshot_id', 'decision_id', 'recorded_at'])
def test_only_two_specific_columns_get_32mib_candidate_cap(name: str) -> None:
    value = observation()
    col = value['columns'][name]
    for size, expected in ((32*profile.MIB, name in profile.LARGE_COLUMNS), (32*profile.MIB+1, False)):
        col['max_uncompressed_bytes'] = col['sum_uncompressed_bytes'] = size
        col['predicate_failures']['uncompressed_within_16mib'] = 1
        value['declared_expanded_bytes'] = sum(c['max_uncompressed_bytes'] for c in value['columns'].values())
        assert profile.candidate_matches('equity_research.outcomes', value) is expected


@pytest.mark.parametrize('change', ['rows','groups','file','footer','total','bool','codec','offset','values','external','parse','extra_column','wrong_source'])
def test_other_guards_cannot_be_waived(change: str) -> None:
    value = copy.deepcopy(observation())
    source = 'equity_research.outcomes'
    if change == 'rows': value['declared_rows'] = 101
    elif change == 'groups': value['row_groups'] = 2
    elif change == 'file': value['file_bytes'] = 32*profile.MIB+1
    elif change == 'footer': value['footer_bytes'] = 256*1024+1
    elif change == 'total': value['declared_expanded_bytes'] += 1
    elif change == 'bool': value['file_checks']['row_group_totals_match'] = 1
    elif change == 'parse': value['original_guard_result'] = 'PARQUET_FOOTER_PARSE_FAILED'
    elif change == 'extra_column': value['columns']['PRIVATE_UNKNOWN'] = {}
    elif change == 'wrong_source': source = 'market_quotes'
    else:
        field = dict(codec='zstd_codec',offset='offsets_within_file',values='value_count_matches',external='no_external_file')[change]
        value['columns']['payload']['predicate_failures'][field] = 1
    assert profile.candidate_matches(source, value) is False


def test_malformed_observation_fails_closed() -> None:
    for value in ({}, {'columns': None}, {'declared_rows': True}):
        assert profile.candidate_matches('equity_research.outcomes', value) is False


@pytest.mark.parametrize('field', ['columns', 'file_checks', 'column', 'predicate_failures'])
def test_correct_names_in_wrong_container_are_rejected(field: str) -> None:
    value = observation()
    if field in ('columns', 'file_checks'):
        value[field] = list(value[field])
    elif field == 'column':
        value['columns']['payload'] = []
    else:
        value['columns']['payload']['predicate_failures'] = []
    assert profile.candidate_matches('equity_research.outcomes', value) is False
