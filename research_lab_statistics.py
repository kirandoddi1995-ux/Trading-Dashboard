"""Bounded descriptive diagnostics; never data admission or trading significance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import random
from typing import Sequence
from zoneinfo import ZoneInfo

from overnight_research_dataset import ResearchError, scoped_time

MAX_ROWS = 100_000
IST = ZoneInfo('Asia/Kolkata')


def numbers(values: Sequence[float]) -> tuple[float, ...]:
    """Reject bool, nonfinite and unbounded arrays instead of dropping bad rows."""
    if not values or len(values) > MAX_ROWS or any(type(v) not in (int, float) for v in values):
        raise ResearchError('FINITE_BOUNDED_VALUES_REQUIRED')
    try:
        result = tuple(float(v) for v in values)
    except (OverflowError, ValueError):
        raise ResearchError('FINITE_BOUNDED_VALUES_REQUIRED') from None
    if any(not math.isfinite(v) or abs(v) > 1e100 for v in result):
        raise ResearchError('FINITE_BOUNDED_VALUES_REQUIRED')
    return result


def holm_adjust(p_values: Sequence[float], *, attempts: int) -> tuple[float, ...]:
    """Holm family-wise correction, including untested attempts as p=1.

    Caller must supply valid pre-specified p-values and the complete trial count.
    Dependence between tests is allowed; this does not fix an invalid raw test.
    """
    values = numbers(p_values)
    if (type(attempts) is not int or not len(values) <= attempts <= MAX_ROWS
            or any(not 0 <= p <= 1 for p in values)):
        raise ResearchError('COMPLETE_TRIAL_FAMILY_REQUIRED')
    result = [0.0] * len(values)
    running = 0.0
    for rank, (index, value) in enumerate(sorted(enumerate(values), key=lambda item: item[1])):
        running = max(running, min(1.0, (attempts - rank) * value))
        result[index] = running
    return tuple(result)


@dataclass(frozen=True)
class ProbabilityObservation:
    """Frozen OOS probability with actual decision and label availability times."""

    identity: str
    decision_at: str
    prediction_available_at: str
    label_available_at: str
    probability: float
    outcome: int


def calibration_diagnostics(observations: Sequence[ProbabilityObservation], *,
                            evaluated_at: str, bins: int = 5) -> dict[str, object]:
    """Equal-session weighted proper scores and fixed bins; no fitting/calibration.

    Explicit prospective dates only, no historical 2025/2026 input. Multiple rows
    from a session do not multiply that session's weight. No calibrated-win-rate
    or independent-session claim follows from these descriptive measurements.
    """
    evaluated = scoped_time(evaluated_at, 'PROSPECTIVE_VERSIONED')
    if type(bins) is not int or not 2 <= bins <= 20 or len(observations) > MAX_ROWS:
        raise ResearchError('DIAGNOSTIC_BOUNDS_INVALID')
    seen: set[str] = set()
    groups: dict[date, list[ProbabilityObservation]] = {}
    for item in observations:
        decision = scoped_time(item.decision_at, 'PROSPECTIVE_VERSIONED')
        predicted = scoped_time(item.prediction_available_at, 'PROSPECTIVE_VERSIONED')
        labelled = scoped_time(item.label_available_at, 'PROSPECTIVE_VERSIONED')
        if (type(item.identity) is not str or not item.identity or len(item.identity) > 128 or item.identity in seen
                or predicted > decision or not decision < labelled <= evaluated
                or type(item.outcome) is not int or item.outcome not in (0, 1)):
            raise ResearchError('PROBABILITY_CHRONOLOGY_OR_IDENTITY_INVALID')
        probability = numbers([item.probability])[0]
        if not 0 <= probability <= 1:
            raise ResearchError('PROBABILITY_RANGE_INVALID')
        seen.add(item.identity)
        groups.setdefault(decision.astimezone(IST).date(), []).append(item)
    base: dict[str, object] = {'status': 'INSUFFICIENT_DATA', 'rows': len(observations),
        'sessions': len(groups), 'weighting': 'EQUAL_IST_SESSION', 'training_eligible': False,
        'approval_authority': False, 'calibration_verified': False}
    if not groups:
        return {**base, 'brier': None, 'log_loss': None, 'reliability': []}
    briers: list[float] = []
    losses: list[float] = []
    buckets: list[list[tuple[float, int, float]]] = [[] for _ in range(bins)]
    infinite = False
    for items in groups.values():
        briers.append(math.fsum((o.probability - o.outcome)**2 for o in items) / len(items))
        day_loss = 0.0
        for item in items:
            likelihood = item.probability if item.outcome else 1 - item.probability
            if likelihood == 0:
                infinite = True
            else:
                day_loss += -math.log(likelihood) / len(items)
            bucket_index = min(bins - 1, int(item.probability * bins))
            buckets[bucket_index].append((item.probability, item.outcome, 1 / (len(groups) * len(items))))
        losses.append(day_loss)
    reliability: list[dict[str, object]] = []
    for index, bucket in enumerate(buckets):
        weight = math.fsum(item[2] for item in bucket)
        reliability.append({'lower': index / bins, 'upper': (index + 1) / bins,
            'rows': len(bucket), 'weight': weight,
            'mean_probability': math.fsum(p*w for p, _, w in bucket) / weight if weight else None,
            'observed_fraction': math.fsum(y*w for _, y, w in bucket) / weight if weight else None})
    return {**base, 'status': 'DESCRIPTIVE_ONLY', 'brier': math.fsum(briers) / len(groups),
        'log_loss': None if infinite else math.fsum(losses) / len(groups),
        'log_loss_status': 'INFINITE_WRONG_CERTAINTY' if infinite else 'FINITE',
        'single_class': len({o.outcome for o in observations}) < 2, 'reliability': reliability}


def paired_session_interval(model_losses: Sequence[float], baseline_losses: Sequence[float], *,
                            minimum_sessions: int, seed: int, repetitions: int = 2000) -> dict[str, object]:
    """Bootstrap paired SESSION mean-loss differences, not individual intraday rows.

    Lower is better. Each supplied entry must already be one equal-weight session.
    IID-session resampling is a declared approximation, not a guarantee for serial
    dependence. Minimum is a frozen caller study choice, not a production gate.
    """
    model, baseline = numbers(model_losses), numbers(baseline_losses)
    if (len(model) != len(baseline) or type(minimum_sessions) is not int or not 2 <= minimum_sessions <= MAX_ROWS
            or type(seed) is not int or type(repetitions) is not int or not 100 <= repetitions <= 10_000
            or len(model) * repetitions > 2_000_000):
        raise ResearchError('SESSION_INTERVAL_BOUNDS_INVALID')
    base: dict[str, object] = {'sessions': len(model), 'approval_authority': False,
        'assumption': 'IID_SESSION_RESAMPLING_NOT_PROVEN', 'seed': seed,
        'repetitions': repetitions, 'confidence': 0.95}
    if len(model) < minimum_sessions:
        return {**base, 'status': 'INSUFFICIENT_DATA', 'lower': None, 'upper': None, 'mean': None}
    differences = tuple(a - b for a, b in zip(model, baseline))
    rng = random.Random(seed)
    means = sorted(math.fsum(differences[rng.randrange(len(model))] for _ in model) / len(model)
                   for _ in range(repetitions))
    # Empirical inverse CDF, explicitly fixed rather than platform quantile defaults.
    return {**base, 'status': 'DESCRIPTIVE_INTERVAL', 'mean': math.fsum(differences) / len(model),
        'lower': means[math.ceil(0.025 * repetitions) - 1],
        'upper': means[math.ceil(0.975 * repetitions) - 1]}


def histogram_drift(reference_counts: Sequence[float], current_counts: Sequence[float]) -> dict[str, object]:
    """Jensen-Shannon divergence on caller-frozen identical bins; not an alarm cutoff."""
    reference, current = numbers(reference_counts), numbers(current_counts)
    if (len(reference) != len(current) or not 2 <= len(reference) <= 100
            or any(v < 0 or not v.is_integer() for v in (*reference, *current))
            or math.fsum(reference) <= 0 or math.fsum(current) <= 0):
        raise ResearchError('FROZEN_HISTOGRAM_REQUIRED')
    p = tuple(v / math.fsum(reference) for v in reference)
    q = tuple(v / math.fsum(current) for v in current)
    midpoint = tuple((a + b) / 2 for a, b in zip(p, q))
    divergence = math.fsum(0.5 * x * math.log2(x / m)
        for distribution in (p, q) for x, m in zip(distribution, midpoint) if x)
    return {'status': 'DESCRIPTIVE_ONLY', 'js_divergence_bits': max(0.0, min(1.0, divergence)),
        'reference_rows': int(math.fsum(reference)), 'current_rows': int(math.fsum(current)),
        'alarm_threshold': None, 'retuning_authorized': False, 'approval_authority': False}
