"""Synthetic policy candidates only, no real holdout or live data."""
from copy import deepcopy
from typing import Any

import pytest

from forward_revision_policy import project, specification
from forward_revision_quarantine import snapshot
from research_integrity import IntegrityError
from test_forward_revision_evidence import records
from test_forward_revision_quarantine import config as _fixture, candles, baseline, received

config = _fixture


def test_future_receipt_does_not_rewrite_old_projection(config: dict[str, Any]) -> None:
    source = records(config)
    first = project(source[:1], received(config, 10))
    assert project(source, received(config, 10)) == first
    assert first['status'] == 'INPUT_CANDIDATE_ONLY'
    assert first['decision_eligible'] is False and first['training_eligible'] is False
    later = project(source, received(config, 15))
    assert later['projection_sha256'] != first['projection_sha256']
    assert len(later['revision_annotations']) == 2  # no false replay of baseline
    assert all(row['changed_fields'] == ['close'] for row in later['revision_annotations'])


def test_empty_and_receipts_not_yet_available(config: dict[str, Any]) -> None:
    result = project(records(config), '2022-01-03T09:25:29+05:30')
    assert result['bars'] == [] and result['source_sha256s'] == []
    assert result['blockers'] == ['NO_RECEIVED_SOURCE_AT_CUTOFF']


def test_numeric_equality_is_only_trivial_case(config: dict[str, Any]) -> None:
    rows = candles(config, 2)
    rows[0][4] = float(rows[0][4])
    same = project([snapshot(config, rows, received(config), baseline(config), 'a'*64)], received(config))
    assert same['revision_annotations'] == []
    rows[0][4] += 0.00000001
    changed = project([snapshot(config, rows, received(config), baseline(config), 'a'*64)], received(config))
    assert changed['revision_annotations'][0]['classification'] == 'SOURCE_REVISION_REVIEW'


def test_missing_bar_blocks_not_backfilled(config: dict[str, Any]) -> None:
    rows = candles(config, 3)[1:]
    record = snapshot(config, rows, received(config, 15), [], 'a'*64)
    result = project([record], received(config, 15))
    assert result['status'] == 'BLOCKED' and len(result['missing_bar_starts']) == 1


def test_stale_source_and_timezone_equivalence(config: dict[str, Any]) -> None:
    source = records(config)[:1]
    assert 'STALE_RECEIVED_SOURCE' in project(source, '2022-01-03T09:29:00+05:30')['blockers']
    assert project(source, received(config)) == project(source, '2022-01-03T03:55:30+00:00')


def test_identity_duplicate_and_time_fail_closed(config: dict[str, Any]) -> None:
    source = records(config)
    with pytest.raises(IntegrityError):
        project([source[0], source[0]], received(config))
    source[1] = snapshot(config, candles(config, 3), received(config, 15), baseline(config), 'b'*64)
    with pytest.raises(IntegrityError):
        project(source, received(config, 15))
    with pytest.raises(IntegrityError):
        project([], '2022-01-03T09:25:30')
    with pytest.raises(IntegrityError):
        project(source[:1], '2022-01-04T09:25:30+05:30')


def test_bounds_damage_and_input_immutability(config: dict[str, Any]) -> None:
    source = records(config)
    original = deepcopy(source)
    projection = project(source, received(config, 15))
    projection['bars'][0]['values'][3] = 123
    assert source == original
    with pytest.raises(IntegrityError):
        project(source * 38, received(config, 15))
    source[0]['training_eligible'] = True
    with pytest.raises(IntegrityError):
        project(source, received(config, 15))
    policy = specification()
    policy['decision_eligible'] = True
    assert specification()['decision_eligible'] is False


def test_input_order_and_snapshot_boundary_are_deterministic(config: dict[str, Any]) -> None:
    source = records(config)
    assert project(source, received(config, 15)) == project(list(reversed(source)), received(config, 15))
    missing = project(source[:1], '2022-01-03T09:30:30+05:30')
    assert 'MISSING_COMPLETED_PREFIX' in missing['blockers']
    assert len(missing['missing_bar_starts']) == 1
