"""Synthetic payloads only; no historical or forward data files."""
from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest

from research_claim_projection import ProjectionError, RESERVED, project_claims


def inputs() -> tuple[dict[str, object], dict[str, object]]:
    return ({'decision_id': 'synthetic', 'decision_at': '2022-01-03T09:20:00+05:30',
             'features': {'values': {'rsi': {'value': 50}, 'market_regime': 'NEUTRAL'}}},
            {'outcome': 'TARGET', 'outcome_at': '2022-01-03T03:55:00+00:00',
             'actual_forward_return': 0.2})


@pytest.mark.parametrize(('outcome', 'expected'), [('TARGET', 1), ('STOP', 0),
    ('UNKNOWN', None), ('AMBIGUOUS', None), ('TIMEOUT', None), ('target', None), (None, None)])
def test_candidates_never_grant_training_label(outcome: object, expected: object) -> None:
    decision, result = inputs()
    result['outcome'] = outcome
    result.update({'coverage_complete': True, 'horizon_complete': True, 'first_touch_verified': True})
    row = project_claims(decision, result)
    assert row['candidate_target_before_stop'] == expected
    assert row['target_before_stop'] is None
    assert row['training_eligible'] is False
    assert row['excess_return'] is None
    assert row['actual_forward_return'] == 0.2


@pytest.mark.parametrize('name', sorted(RESERVED - {'market_regime'}))
def test_collision_even_non_numeric(name: str) -> None:
    decision, result = inputs()
    decision['features'] = {'values': {name: {'value': None}}}
    with pytest.raises(ProjectionError, match='PROJECTION_RESERVED_FEATURE_COLLISION'):
        project_claims(decision, result)


@pytest.mark.parametrize('value', [True, '4', None, float('nan'), float('inf'), 10**400])
def test_non_numbers_remain_missing(value: object) -> None:
    decision, result = inputs()
    decision['features'] = {'values': {'bad': value, 'good': 0}}
    result['actual_forward_return'] = value
    row = project_claims(decision, result)
    assert 'bad' not in row
    assert row['good'] == 0.0
    assert row['actual_forward_return'] is None


@pytest.mark.parametrize('stamp', [None, '', '2022-01-03T09:20:00',
    '2022-01-03T03:49:59Z', 'invalid'])
def test_bad_chronology_visible(stamp: object) -> None:
    decision, result = inputs()
    result['outcome_at'] = stamp
    row = project_claims(decision, result)
    assert 'chronology_unverified' in cast(list[str], row['eligibility_failures'])
    assert row['target_before_stop'] is None


def test_no_mutation_or_claim_promotion() -> None:
    decision, result = inputs()
    decision.update({'production_evidence': True, 'pit_verified': True, 'costs_applied': True})
    before = deepcopy((decision, result))
    row = project_claims(decision, result)
    assert (decision, result) == before
    assert row['rsi'] == 50.0 and row['market_regime'] == 'NEUTRAL'
    assert 'chronology_unverified' not in cast(list[str], row['eligibility_failures'])
    for name in ('ledger_verified', 'production_evidence', 'pit_verified', 'costs_applied'):
        assert row[name] is False


@pytest.mark.parametrize('bad', [None, [], {'features': None}, {'features': {'values': {1: 5}}}])
def test_invalid_shapes_fail_closed(bad: object) -> None:
    with pytest.raises(ProjectionError, match='PROJECTION_MAPPING_INVALID'):
        project_claims(cast(dict[str, object], bad), {})


def test_empty_payload_not_loss() -> None:
    row = project_claims({}, {})
    assert row['candidate_target_before_stop'] is None
    assert row['actual_forward_return'] is None
    assert row['target_before_stop'] is None


@pytest.mark.parametrize('values', [{str(n): n for n in range(1025)}, {'x' * 129: 1}])
def test_feature_bound(values: dict[str, object]) -> None:
    with pytest.raises(ProjectionError, match='PROJECTION_FEATURE_BOUND'):
        project_claims({'features': {'values': values}}, {})
