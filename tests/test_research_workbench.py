"""Offline generated fixtures only; no credentials, market files or hosted writes."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import socket
from typing import Any, cast

import pytest

import research_workbench as wb
from overnight_research_dataset import ResearchError
from overnight_research_ml import RidgeModel
from overnight_research_runner import offline_boundary

AFTER = datetime.fromisoformat('2026-10-13T16:00:00+05:30')


@pytest.fixture
def report() -> dict[str, Any]:
    return wb.run_generated('frozen_baseline', AFTER)


def reseal(report: dict[str, Any]) -> dict[str, Any]:
    report['report_sha256'] = hashlib.sha256(json.dumps(report['payload'], sort_keys=True,
        separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()
    return report


def test_catalog_is_cheap_and_admission_cannot_be_activated(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError('static API fitted or read a file')
    monkeypatch.setattr(RidgeModel, 'fit', denied)
    monkeypatch.setattr(Path, 'read_bytes', denied)
    studies = wb.catalog()['studies']
    assert isinstance(studies, list) and 'frozen_baseline' in studies
    assert wb.real_training_admission()['training_eligible'] is False


@pytest.mark.parametrize('study', wb.STUDIES)
def test_actual_generated_engine_and_canonical_roundtrip(study: str) -> None:
    result = cast(dict[str, Any], wb.run_generated(study, AFTER))
    encoded = wb.report_json(result)
    assert len(encoded) < wb.MAX_REPORT_BYTES
    assert wb.validate_report(encoded) == result
    assert wb.run_generated(study, AFTER) == result
    payload = result['payload']
    assert isinstance(payload, dict)
    validation = payload['validation']
    assert isinstance(validation, dict)
    assert validation['status'] == 'COMPLETED_SYNTHETIC_EVALUATION'
    assert len(validation['predictions']) == 8
    metrics = validation['metrics']
    assert isinstance(metrics, dict)
    assert set(metrics) == {'ridge', 'zero', 'mean', 'chance', 'rule'}
    assert payload['backtest']['returns'] is None
    assert payload['model_registry']['feature_importance']['status'] == 'NOT_ESTABLISHED'
    assert payload['drift']['alarm_threshold'] is None
    assert payload['readiness']['actual_derivative_backtest_available'] is False
    assert payload['readiness']['missing_matrix']['fills']['real_evidence'] is None
    assert payload['generated_execution']['status'] == 'SYNTHETIC_QUOTE_COST_ARITHMETIC_ONLY'
    assert payload['generated_execution']['result']['fill_evidence'] is False


@pytest.mark.parametrize(('clock', 'blocked'), [
    ('2026-10-13T09:14:59+05:30', False), ('2026-10-13T09:15:00+05:30', True),
    ('2026-10-13T15:40:00+05:30', True), ('2026-10-13T15:40:59+05:30', True),
    ('2026-10-13T15:41:00+05:30', False), ('2026-10-13T03:45:00+00:00', True),
    ('2026-10-11T12:00:00+05:30', True)])
def test_market_clock_boundaries(clock: str, blocked: bool) -> None:
    if blocked:
        with pytest.raises(ResearchError, match='MARKET_WINDOW'):
            wb.guard_compute(wb.WorkbenchSpec(), datetime.fromisoformat(clock))
    else:
        wb.guard_compute(wb.WorkbenchSpec(), datetime.fromisoformat(clock))


def test_naive_clock_and_real_file_study_rejected() -> None:
    with pytest.raises(ResearchError, match='AWARE_TIME'):
        wb.run_generated('frozen_baseline', datetime(2022, 1, 3))
    with pytest.raises(ResearchError, match='BOUNDS'):
        wb.run_generated('data/2026/real.csv', AFTER)


@pytest.mark.parametrize('damage', [
    {'sessions': 0}, {'sessions': 25}, {'sessions': True}, {'seed': -1},
    {'alpha': float('nan')}, {'alpha': float('inf')}, {'alpha': 0.0},
    {'minimum_train_sessions': 12}, {'minimum_train_sessions': 2}, {'gap_seconds': 86401}])
def test_work_is_rejected_before_source_read(damage: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def denied() -> None:
        raise AssertionError('work bounds checked too late')
    monkeypatch.setattr(wb, '_sources', denied)
    with pytest.raises(ResearchError, match='BOUNDS'):
        wb.run_synthetic(replace(wb.WorkbenchSpec(), **damage), now=AFTER)


@pytest.mark.parametrize('raw', [b'', b'[]', b'{}', b'{', b'NaN', b'{"a":1,"a":2}',
    b'[' * 1500 + b']' * 1500, b' ' * (wb.MAX_REPORT_BYTES + 1), b'"\xff"'],
    ids=['empty', 'array', 'object', 'broken', 'nan', 'duplicate', 'deep', 'oversized', 'invalid_utf8'])
def test_empty_invalid_and_excessive_reports(raw: bytes) -> None:
    with pytest.raises(ResearchError):
        wb.validate_report(raw)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf'), 1e101, True])
def test_invalid_numeric_metric(report: dict[str, Any], value: float) -> None:
    report['payload']['validation']['metrics']['ridge']['mae'] = value
    with pytest.raises(ResearchError):
        wb.validate_report(report)


def test_mapping_depth_nodes_and_arrays_are_bounded(report: dict[str, Any]) -> None:
    for value in ([0] * 257, 'x' * 513, {'extra': {'extra': {'extra': object()}}}):
        bad = deepcopy(report)
        bad['payload']['validation']['reasons'] = value
        with pytest.raises(ResearchError):
            wb.validate_report(bad)


@pytest.mark.parametrize('damage', ['schema', 'authority', 'synthetic', 'unknown', 'metric',
    'fold', 'scaler', 'coefficients', 'prediction', 'source', 'assumptions', 'registry',
    'execution', 'drift', 'input', 'model', 'empty_predictions', 'nested_unknown'])
def test_tamper_including_resealed_semantic_tamper(report: dict[str, Any], damage: str) -> None:
    p = report['payload']
    v = p['validation']
    if damage == 'schema':
        report['schema'] = 'research-workbench-report-v99'
    elif damage == 'authority':
        report['training_eligible'] = 0  # equality to False must not admit integers
    elif damage == 'synthetic':
        report['synthetic'] = False
    elif damage == 'unknown':
        report['hidden'] = 'unknown'
    elif damage == 'metric':
        v['metrics']['ridge']['mae'] += 1
    elif damage == 'fold':
        v['folds'][0]['train'].append(v['folds'][0]['test'][0])
    elif damage == 'scaler':
        v['folds'][0]['model']['scaler']['means'][0] += 1
    elif damage == 'coefficients':
        v['folds'][0]['model']['coefficients'][0] += 1
    elif damage == 'prediction':
        v['predictions'][0]['predictions']['ridge'] += 1
    elif damage == 'source':
        p['identities']['sources']['data/2025/private.csv'] = 'a' * 64
    elif damage == 'assumptions':
        p['assumptions']['costs'] = 'ZERO_COSTS'
    elif damage == 'registry':
        p['model_registry']['deployment_allowed'] = True
    elif damage == 'execution':
        p['backtest']['net_pnl'] = 0
    elif damage == 'drift':
        p['drift']['js_divergence_bits'] = -1
    elif damage == 'input':
        p['identities']['input_sha256'] = 'a' * 64
    elif damage == 'model':
        p['identities']['model_sha256'] = 'a' * 64
    elif damage == 'empty_predictions':
        v['predictions'] = []
    else:
        v['folds'][0]['model']['leaky'] = True
    with pytest.raises(ResearchError):
        wb.validate_report(reseal(report))


def test_unsealed_edit_rejected_and_inspection_defensive(report: dict[str, Any]) -> None:
    inspected = cast(dict[str, Any], wb.inspect_report(report))
    inspected['payload']['spec']['seed'] = 99
    assert report['payload']['spec']['seed'] == 17
    with pytest.raises(ResearchError, match='TAMPERED'):
        wb.validate_report(inspected)


def test_inspection_does_not_fit(report: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError('inspection fitted')
    monkeypatch.setattr(RidgeModel, 'fit', denied)
    assert wb.inspect_report(report) == report


def test_comparison_does_not_claim_edge(report: dict[str, Any]) -> None:
    same = cast(dict[str, Any], wb.compare_reports(report, report))
    assert same['status'] == 'DESCRIPTIVE_SYNTHETIC_COMPARISON'
    assert same['edge_status'] == 'NOT_ESTABLISHED'
    assert same['metric_deltas_b_minus_a']['ridge']['mae'] == 0
    alpha = wb.run_synthetic(replace(wb.WorkbenchSpec(), alpha=2.0), now=AFTER)
    assert wb.compare_reports(report, alpha)['status'] == 'DESCRIPTIVE_SYNTHETIC_COMPARISON'
    changes: tuple[dict[str, Any], ...] = ({'seed': 18}, {'gap_seconds': 120}, {'minimum_train_sessions': 5})
    for change in changes:
        other = wb.run_synthetic(replace(wb.WorkbenchSpec(), **change), now=AFTER)
        comparison = wb.compare_reports(report, other)
        assert comparison['status'] == 'INCOMPATIBLE_ASSUMPTIONS'
        assert comparison['metric_deltas_b_minus_a'] == {}


def test_train_only_purge_and_feature_label_causality() -> None:
    spec = wb.WorkbenchSpec()
    samples, features, targets = wb._fixture(spec)
    for sample in samples:
        assert sample.feature_start < sample.decision_at < sample.available_at < sample.label_end
        assert sample.label_end < sample.label_available_at
        assert len(features[sample.row_id]) == 2
    from overnight_research_ml import chronological_folds
    damaged = list(samples)
    damaged[0] = replace(damaged[0], label_available_at=samples[4].available_at)
    fold = chronological_folds(damaged, minimum_train_groups=4, test_groups=1, session_groups=True)[0]
    assert damaged[0].row_id in fold.purged
    changed = dict(targets)
    changed[samples[4].row_id] = 10000
    original_model = RidgeModel.fit([features[k] for k in fold.train], [targets[k] for k in fold.train], alpha=1.0)
    changed_model = RidgeModel.fit([features[k] for k in fold.train], [changed[k] for k in fold.train], alpha=1.0)
    assert original_model == changed_model


def test_actual_lag_dependency_intervals_purge_previous_session(report: dict[str, Any]) -> None:
    from overnight_research_ml import chronological_folds
    spec = wb.WorkbenchSpec()
    samples, features, _ = wb._fixture(spec)
    assert datetime.fromisoformat(samples[0].feature_start) == (
        datetime.fromisoformat(samples[0].decision_at) - timedelta(minutes=5))
    assert features[samples[0].row_id][1] == 0.0
    for previous, current in zip(samples, samples[1:]):
        assert current.feature_start == previous.decision_at
        assert features[current.row_id][1] == features[previous.row_id][0]
    folds = chronological_folds(samples, minimum_train_groups=4, test_groups=1,
        gap_seconds=spec.gap_seconds, session_groups=True)
    first = folds[0]
    assert first.test == (samples[4].row_id,)
    assert first.purged == (samples[3].row_id,)
    assert set(first.train) == {s.row_id for s in samples[:3]}
    lookup = {sample.row_id: sample for sample in samples}
    for fold in folds:
        for train_id in fold.train:
            for test_id in fold.test:
                train, test = lookup[train_id], lookup[test_id]
                assert datetime.fromisoformat(train.label_end) < datetime.fromisoformat(test.feature_start)
        previous_index = next(i for i, s in enumerate(samples) if s.row_id == fold.test[0]) - 1
        assert fold.purged == (samples[previous_index].row_id,)
    stored = report['payload']['validation']['folds'][0]
    assert stored['purged'] == [samples[3].row_id]
    assert set(stored['train']) == set(first.train)
    assert wb.validate_report(wb.report_json(report)) == report


def test_minimum_admitted_training_count_after_lag_purge() -> None:
    result = cast(dict[str, Any], wb.run_synthetic(
        replace(wb.WorkbenchSpec(), minimum_train_sessions=3), now=AFTER))
    first = result['payload']['validation']['folds'][0]
    assert len(first['train']) == 2 and len(first['purged']) == 1
    assert result['payload']['validation']['status'] == 'COMPLETED_SYNTHETIC_EVALUATION'


def test_only_allowlisted_code_read_and_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    reads: list[str] = []
    original = Path.read_bytes
    def code_only(path: Path) -> bytes:
        assert path.name in wb.SOURCE_FILES
        assert path.suffix == '.py'
        reads.append(path.name)
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', code_only)
    result = wb.run_generated('frozen_baseline', AFTER)
    assert set(reads) == set(wb.SOURCE_FILES)
    assert result['synthetic'] is True
    with offline_boundary(), pytest.raises(ResearchError, match='OFFLINE_NETWORK'):
        socket.getaddrinfo('example.invalid', 443)


def test_source_file_size_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    class Oversized:
        st_size = 262145
    monkeypatch.setattr(Path, 'stat', lambda *args, **kwargs: Oversized())
    monkeypatch.setattr(Path, 'is_symlink', lambda *args, **kwargs: False)
    with pytest.raises(ResearchError, match='SOURCE_CODE_BOUNDARY'):
        wb.run_generated('frozen_baseline', AFTER)


def test_integer_alpha_is_reproducible() -> None:
    result = wb.run_synthetic(replace(wb.WorkbenchSpec(), alpha=1), now=AFTER)
    assert wb.validate_report(wb.report_json(result)) == result


def test_engine_failure_propagates_without_success_report(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(*args: object, **kwargs: object) -> None:
        raise ResearchError('FIT_FAILED')
    monkeypatch.setattr(wb, 'walk_forward_ridge', failed)
    with pytest.raises(ResearchError, match='FIT_FAILED'):
        wb.run_generated('backtesting', AFTER)


@pytest.mark.parametrize('section', ['admission', 'model_registry', 'readiness'])
def test_nested_numeric_boolean_cannot_bypass_schema(report: dict[str, Any], section: str) -> None:
    p = report['payload']
    if section == 'admission':
        p[section]['training_eligible'] = 0
    elif section == 'model_registry':
        p[section]['deployment_allowed'] = 0
    else:
        p[section]['actual_derivative_backtest_available'] = 0
    with pytest.raises(ResearchError, match='TYPE_INVALID'):
        wb.validate_report(reseal(report))


def test_generated_quote_tamper_rejected(report: dict[str, Any]) -> None:
    report['payload']['generated_execution']['result']['net_pnl'] = '1000000'
    with pytest.raises(ResearchError, match='GENERATED_EXECUTION'):
        wb.validate_report(reseal(report))
