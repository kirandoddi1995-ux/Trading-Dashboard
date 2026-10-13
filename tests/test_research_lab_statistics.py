"""Synthetic descriptive diagnostics, including missing/causal/bounded failures."""
from dataclasses import replace
import math
from typing import Any

import pytest

from overnight_research_dataset import ResearchError
from research_lab_statistics import (ProbabilityObservation, calibration_diagnostics,
    histogram_drift, holm_adjust, paired_session_interval)

AT = '2026-10-15T16:00:00+05:30'


def sample(identity: str = 'one', day: int = 13, p: float = 0.8, outcome: int = 1) -> ProbabilityObservation:
    return ProbabilityObservation(identity, f'2026-10-{day}T09:30:00+05:30',
        f'2026-10-{day}T09:29:59+05:30', f'2026-10-{day}T09:35:01+05:30', p, outcome)


def test_holm_family_and_order() -> None:
    assert holm_adjust([0.04, 0.01, 0.03], attempts=3) == pytest.approx((0.06, 0.03, 0.06))
    assert holm_adjust([0.01], attempts=100) == (1.0,)
    assert holm_adjust([0, 1], attempts=2) == (0, 1)


@pytest.mark.parametrize('values,attempts', [([], 1), ([math.nan], 1), ([True], 1),
    ([-1], 1), ([1.1], 1), ([0.1, 0.2], 1), ([0.1], True), ([0.1], 100001), ([10**500], 1)])
def test_holm_invalid(values: list[float], attempts: int) -> None:
    with pytest.raises(ResearchError):
        holm_adjust(values, attempts=attempts)


def test_equal_session_weighting_not_row_weighting() -> None:
    rows = [sample('one', p=0, outcome=1), sample('two', 14, 1), sample('three', 14, 1)]
    result = calibration_diagnostics(rows, evaluated_at=AT)
    assert result['brier'] == 0.5
    assert result['sessions'] == 2
    assert result['log_loss'] is None
    assert result['log_loss_status'] == 'INFINITE_WRONG_CERTAINTY'
    assert result['approval_authority'] is False


def test_calibration_missing_and_exact_probabilities() -> None:
    empty = calibration_diagnostics([], evaluated_at=AT)
    assert empty['status'] == 'INSUFFICIENT_DATA' and empty['brier'] is None
    perfect = calibration_diagnostics([sample(p=1), sample('two', 14, 0, 0)], evaluated_at=AT)
    assert perfect['brier'] == perfect['log_loss'] == 0
    assert perfect['single_class'] is False
    normal = calibration_diagnostics([sample()], evaluated_at=AT)
    assert normal['brier'] == pytest.approx(0.04)
    assert normal['log_loss'] == pytest.approx(-math.log(0.8))


@pytest.mark.parametrize('changes', [{'probability': -0.1}, {'probability': math.inf},
    {'probability': True}, {'outcome': True}, {'outcome': 2}, {'identity': ''},
    {'prediction_available_at': '2026-10-13T09:30:01+05:30'},
    {'label_available_at': '2026-10-13T09:30:00+05:30'},
    {'label_available_at': '2026-10-16T09:30:00+05:30'},
    {'decision_at': '2026-10-12T09:30:00+05:30'},
    {'decision_at': '2025-10-13T09:30:00+05:30'}, {'decision_at': '2026-10-13T09:30:00'}])
def test_calibration_rejects_invalid(changes: dict[str, Any]) -> None:
    with pytest.raises(ResearchError):
        calibration_diagnostics([replace(sample(), **changes)], evaluated_at=AT)


def test_duplicates_and_bins() -> None:
    with pytest.raises(ResearchError):
        calibration_diagnostics([sample(), sample()], evaluated_at=AT)
    with pytest.raises(ResearchError):
        calibration_diagnostics([], evaluated_at=AT, bins=True)


def test_ist_boundary_sessions() -> None:
    a = replace(sample(), decision_at='2026-10-13T18:29:59Z',
        prediction_available_at='2026-10-13T18:29:58Z', label_available_at='2026-10-13T18:30:01Z')
    b = replace(sample('two'), decision_at='2026-10-13T18:30:00Z',
        prediction_available_at='2026-10-13T18:29:59Z', label_available_at='2026-10-13T18:30:02Z')
    assert calibration_diagnostics([a, b], evaluated_at=AT)['sessions'] == 2


def test_interval_reproducibility_direction_and_insufficiency() -> None:
    args = dict(minimum_sessions=2, seed=9, repetitions=100)
    first = paired_session_interval([1, 2, 3], [2, 3, 4], **args)
    assert first == paired_session_interval([1, 2, 3], [2, 3, 4], **args)
    assert first['lower'] == first['upper'] == first['mean'] == -1
    assert paired_session_interval([1], [2], **args)['status'] == 'INSUFFICIENT_DATA'


@pytest.mark.parametrize('kwargs', [{'minimum_sessions': True}, {'minimum_sessions': 1},
    {'seed': True}, {'repetitions': 99}, {'repetitions': 10001}])
def test_interval_invalid(kwargs: dict[str, int]) -> None:
    args = dict(minimum_sessions=2, seed=0, repetitions=100)
    args.update(kwargs)
    with pytest.raises(ResearchError):
        paired_session_interval([1, 2], [1, 2], **args)


def test_interval_invalid_values_and_length() -> None:
    pairs: list[tuple[list[float], list[float]]] = [([], []), ([1], [1, 2]), ([math.inf], [1])]
    for a, b in pairs:
        with pytest.raises(ResearchError):
            paired_session_interval(a, b, minimum_sessions=2, seed=0)


def test_drift_descriptive_bounds_symmetry() -> None:
    assert histogram_drift([1, 1], [2, 2])['js_divergence_bits'] == 0
    result = histogram_drift([1, 0], [0, 1])
    assert result['js_divergence_bits'] == 1 and result['alarm_threshold'] is None
    assert histogram_drift([2, 7], [5, 1])['js_divergence_bits'] == histogram_drift([5, 1], [2, 7])['js_divergence_bits']


@pytest.mark.parametrize('a,b', [([0, 0], [1, 1]), ([1], [1]), ([1, 2], [1, 2, 3]),
    ([-1, 2], [1, 2]), ([0.5, 2], [1, 2]), ([math.nan, 1], [1, 2])])
def test_drift_invalid(a: list[float], b: list[float]) -> None:
    with pytest.raises(ResearchError):
        histogram_drift(a, b)
