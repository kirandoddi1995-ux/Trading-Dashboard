"""Typed synthetic leakage, fold, transform, and trial-registry tests."""
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest

from overnight_research_dataset import ResearchError, fingerprint, instant
from overnight_research_ml import LabelInterval, ModelSpec, RidgeModel, Standardizer, TrialRegistry, chronological_folds, mean_baseline, walk_forward_ridge


def samples() -> list[LabelInterval]:
    opening = datetime.fromisoformat('2022-01-03T10:00:00+05:30')
    result: list[LabelInterval] = []
    for i in range(6):
        moment = opening + timedelta(minutes=10*i)
        for version in ('nifty-forward-v1', 'nifty-forward-v2'):
            result.append(LabelInterval(fingerprint([i, version]), version, moment.isoformat(),
                (moment-timedelta(minutes=1)).isoformat(), moment.isoformat(),
                (moment+timedelta(minutes=2)).isoformat(),
                (moment+timedelta(minutes=3)).isoformat(), str(i)))
    return result


def spec() -> ModelSpec:
    return ModelSpec('baseline', ('range',), 'MEAN_BASELINE', '{}', 'c'*64,
                     '2022-01-02T00:00:00+05:30', 0)


def test_chronological_grouped_folds_and_no_overlap() -> None:
    data = samples()
    folds = chronological_folds(list(reversed(data)), minimum_train_groups=2, test_groups=2)
    assert len(folds) == 2 and len(folds[0].test) == 4 and len(folds[0].train) == 4
    lookup = {sample.row_id: sample for sample in data}
    for fold in folds:
        for train_id in fold.train:
            for test_id in fold.test:
                assert instant(lookup[train_id].label_end) < instant(lookup[test_id].feature_start)
            assert instant(lookup[train_id].label_available_at) < instant(fold.fit_at)


@pytest.mark.parametrize('damage', ['overlap', 'late_label', 'gap'])
def test_group_purged_if_any_version_is_unsafe(damage: str) -> None:
    data = samples()
    gap = 0
    if damage == 'overlap':
        data[2] = replace(data[2], label_end='2022-01-03T10:20:00+05:30',
                          label_available_at='2022-01-03T10:21:00+05:30')
    elif damage == 'late_label':
        data[2] = replace(data[2], label_available_at='2022-01-03T10:20:00+05:30')
    else:
        gap = 601
    fold = chronological_folds(data, minimum_train_groups=2, test_groups=1, gap_seconds=gap)[0]
    assert data[2].row_id in fold.purged and data[3].row_id in fold.purged
    assert len(fold.train) == 2


def test_feature_history_overlap_purges_all_and_is_insufficient() -> None:
    data = samples()
    data[4] = replace(data[4], feature_start='2022-01-03T09:00:00+05:30')
    fold = chronological_folds(data, minimum_train_groups=2, test_groups=1)[0]
    assert fold.status == 'INSUFFICIENT_DATA' and not fold.train
    assert len(fold.purged) == 4


@pytest.mark.parametrize('damage', ['duplicate', 'split_group', 'naive', 'sealed', 'backwards'])
def test_invalid_fold_inputs(damage: str) -> None:
    data = samples()
    if damage == 'duplicate':
        data.append(data[0])
    elif damage == 'split_group':
        data[0] = replace(data[0], group_id='other')
    elif damage == 'naive':
        data[0] = replace(data[0], decision_at='2022-01-03T10:00:00')
    elif damage == 'sealed':
        data[0] = replace(data[0], label_available_at='2025-01-03T10:00:00+05:30')
    else:
        data[0] = replace(data[0], label_end=data[0].decision_at)
    with pytest.raises(ResearchError):
        chronological_folds(data, minimum_train_groups=2, test_groups=1)


def test_scaler_and_baseline_use_training_only() -> None:
    scaler = Standardizer.fit([[1.0, 7.0], [3.0, 7.0]])
    assert scaler.means == (2.0, 7.0) and scaler.scales == (1.0, 1.0)
    assert scaler.transform([[1000.0, 7.0]]) == ((998.0, 0.0),)
    assert mean_baseline([1.0, 3.0], [1000.0]) == {'prediction': 2.0, 'mae': 998.0, 'mse': 996004.0}
    with pytest.raises(ResearchError):
        Standardizer.fit([[float('nan')]])


def test_registry_retains_failed_trials_and_defensive_copies() -> None:
    registry = TrialRegistry()
    kwargs: dict[str, Any] = {'spec': spec(), 'dataset_sha256': 'd'*64, 'folds': (),
        'started_at': '2022-01-03T16:00:00+05:30', 'completed_at': '2022-01-03T16:01:00+05:30',
        'metrics': {}}
    first = registry.record(trial_id='1', status='FAILED', failure_code='FIT_FAILED', **kwargs)
    second = registry.record(trial_id='2', status='INSUFFICIENT_DATA', **kwargs)
    assert registry.events()[1]['previous_sha256'] == first and registry.head == second
    registry.events()[0]['status'] = 'CHANGED'
    assert registry.events()[0]['status'] == 'FAILED'
    with pytest.raises(ResearchError):
        registry.record(trial_id='1', status='INSUFFICIENT_DATA', **kwargs)
    with pytest.raises(ResearchError):
        registry.record(trial_id='3', status='COMPLETED', **kwargs)
    with pytest.raises(ResearchError):
        replace(spec(), feature_names=('label',)).identity()


def test_completed_trial_has_hash_bound_folds_and_metrics() -> None:
    registry = TrialRegistry()
    folds = chronological_folds(samples(), minimum_train_groups=2, test_groups=1)
    registry.record(trial_id='complete', spec=spec(), dataset_sha256='d'*64, folds=folds,
        started_at='2022-01-03T16:00:00+05:30', completed_at='2022-01-03T16:01:00+05:30',
        status='COMPLETED', metrics={'mae': 2.0})
    assert registry.events()[0]['metrics'] == {'mae': 2.0}
    assert not registry.events()[0]['training_eligible']


def ridge_spec() -> ModelSpec:
    return ModelSpec('ridge', ('return',), 'LINEAR_RIDGE_RESEARCH',
        '{"alpha":1.0,"minimum_train_rows":2}', 'c'*64, '2022-01-02T00:00:00+05:30', 17)


def test_actual_ridge_fit_matches_closed_form() -> None:
    model = RidgeModel.fit([[1.0], [3.0]], [2.0, 6.0], alpha=1.0)
    assert model.intercept == 4.0
    assert model.coefficients == pytest.approx((4/3,))
    assert model.predict([[2.0], [5.0]]) == pytest.approx((4.0, 8.0))
    # Correlated columns and a constant feature remain solvable with positive alpha.
    correlated = RidgeModel.fit([[1.0, 2.0, 7.0], [3.0, 6.0, 7.0]], [2.0, 6.0], alpha=1.0)
    assert correlated.coefficients[2] == 0
    assert correlated.predict([[2.0, 4.0, 7.0]]) == pytest.approx((4.0,))


def test_session_grouping_never_splits_same_ist_day() -> None:
    all_rows = []
    for day in ('2022-01-03', '2022-01-04', '2022-01-05'):
        for index, sample in enumerate(samples()):
            all_rows.append(replace(sample,
                row_id=fingerprint({'day': day, 'row': index}),
                group_id=day + ':' + sample.group_id,
                **{field: getattr(sample, field).replace('2022-01-03', day)
                   for field in ('decision_at', 'feature_start', 'available_at',
                                 'label_end', 'label_available_at')}))
    folds = chronological_folds(all_rows, minimum_train_groups=2, test_groups=1, session_groups=True)
    lookup = {sample.row_id: sample for sample in all_rows}
    assert len(folds) == 1
    assert {lookup[key].decision_at[:10] for key in folds[0].test} == {'2022-01-05'}
    assert {lookup[key].decision_at[:10] for key in folds[0].train} == {'2022-01-03', '2022-01-04'}
    assert not set(folds[0].test) & set(folds[0].train)


def test_one_session_is_insufficient_even_with_many_decisions() -> None:
    assert chronological_folds(samples(), minimum_train_groups=2, test_groups=1, session_groups=True) == ()


def test_nonboolean_session_selector_rejected() -> None:
    with pytest.raises(ResearchError, match='FOLD_CONFIGURATION_INVALID'):
        chronological_folds(samples(), minimum_train_groups=2, test_groups=1, session_groups=1)  # type: ignore[arg-type]


def test_actual_walkforward_predictions_and_all_baselines() -> None:
    data = samples()
    features = {sample.row_id: [float(i//2)] for i, sample in enumerate(data)}
    targets = {key: 2*row[0]+1 for key, row in features.items()}
    kwargs: dict[str, Any] = {'samples': data, 'features': features, 'targets': targets, 'spec': ridge_spec(),
        'evaluated_at': '2022-01-03T16:00:00+05:30', 'minimum_train_groups': 2,
        'test_groups': 1, 'synthetic_fixture': True}
    first = walk_forward_ridge(**kwargs)
    assert first['status'] == 'COMPLETED_SYNTHETIC_EVALUATION'
    assert set(first['metrics']) == {'ridge', 'zero', 'mean', 'chance', 'rule'}
    assert len(first['predictions']) == 8
    assert first['metrics']['ridge']['mae'] < first['metrics']['zero']['mae']
    assert first == walk_forward_ridge(**kwargs)
    # Changing future targets affects evaluation only, never first-fold fit or prediction.
    changed = targets.copy()
    for key in first['folds'][0]['test']:
        changed[key] += 1000
    second = walk_forward_ridge(**{**kwargs, 'targets': changed})
    assert first['folds'][0]['model'] == second['folds'][0]['model']
    assert first['predictions'][0]['predictions'] == second['predictions'][0]['predictions']
    assert not first['training_eligible']


def test_real_fit_and_too_few_labels_fail_closed() -> None:
    data = samples()
    features = {sample.row_id: [float(i)] for i, sample in enumerate(data)}
    targets = dict.fromkeys(features, 1.0)
    kwargs: dict[str, Any] = {'samples': data, 'features': features, 'targets': targets, 'spec': ridge_spec(),
        'evaluated_at': '2022-01-03T16:00:00+05:30', 'minimum_train_groups': 2, 'test_groups': 1}
    assert walk_forward_ridge(**kwargs)['status'] == 'INSUFFICIENT_DATA'
    assert walk_forward_ridge(**{**kwargs, 'targets': {}, 'synthetic_fixture': True})['status'] == 'INSUFFICIENT_DATA'
    with pytest.raises(ResearchError):
        replace(ridge_spec(), parameters_json='{"alpha":0,"minimum_train_rows":2}').identity()


def test_prospective_fold_time_scope_and_metadata_registration() -> None:
    data = [replace(s, decision_at=s.decision_at.replace('2022-01-03', '2026-10-13'),
        feature_start=s.feature_start.replace('2022-01-03', '2026-10-13'),
        available_at=s.available_at.replace('2022-01-03', '2026-10-13'),
        label_end=s.label_end.replace('2022-01-03', '2026-10-13'),
        label_available_at=s.label_available_at.replace('2022-01-03', '2026-10-13'),
        data_scope='PROSPECTIVE_VERSIONED') for s in samples()]
    assert chronological_folds(data, minimum_train_groups=2, test_groups=1)
    assert replace(ridge_spec(), registered_at='2026-10-12T00:00:00+05:30').identity()
