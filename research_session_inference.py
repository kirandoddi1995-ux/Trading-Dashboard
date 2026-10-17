"""Pure, bounded paired session-loss randomization; never study admission.

Scores must already be computed by the caller. No market-data, model, capture,
file, clock or activation access occurs here. A supplied plan is not proof of
preregistration. Symmetric, approximately independent blocks are assumptions,
not properties verified by this calculation.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import random
import re

MIN_SESSIONS = 120
MAX_SESSIONS = 2000
MAX_TRIALS = 16
MAX_LOSS = 1e12
BLOCK_SIZE = 5
DRAWS = 999
SEED = 1729


@dataclass(frozen=True)
class StudyPlan:
    """Caller-supplied complete frozen family, in its declared order."""

    trial_ids: tuple[str, ...]


@dataclass(frozen=True)
class TrialOutcome:
    """Paired per-session means, not individual bars or inferred returns."""

    trial_id: str
    session_ids: tuple[str, ...]
    baseline_losses: tuple[float, ...]
    candidate_losses: tuple[float, ...]
    completed: bool = True


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'),
                     ensure_ascii=True, allow_nan=False).encode('ascii')
    return hashlib.sha256(raw).hexdigest()


def _identity(value: str) -> None:
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value) is None:
        raise ValueError('INVALID_TRIAL_ID')


def _losses(values: tuple[float, ...]) -> list[float]:
    result: list[float] = []
    for value in values:
        if type(value) not in (int, float) or not 0 <= value <= MAX_LOSS:
            raise ValueError('INVALID_LOSS')
        score = float(value)
        if not math.isfinite(score):
            raise ValueError('INVALID_LOSS')
        result.append(score)
    return result


def infer(plan: StudyPlan, outcomes: Sequence[TrialOutcome]) -> dict[str, object]:
    """Return all-family outputs or no inference; malformed inputs raise ValueError.

    Blocks are consecutive groups of five ordered sessions. A final shorter
    block is retained with its actual session weight. Each draw uses one sign
    per block shared across the entire family. No trial is chosen or promoted.
    """
    if type(plan.trial_ids) is not tuple or not 1 <= len(plan.trial_ids) <= MAX_TRIALS:
        raise ValueError('INVALID_FAMILY_SIZE')
    for trial_id in plan.trial_ids:
        _identity(trial_id)
    if len(set(plan.trial_ids)) != len(plan.trial_ids):
        raise ValueError('DUPLICATE_PLANNED_TRIAL')
    if len(outcomes) > MAX_TRIALS:
        raise ValueError('TOO_MANY_OUTCOMES')
    normalized: dict[str, dict[str, object]] = {}
    differences: dict[str, list[float]] = {}
    common: tuple[str, ...] | None = None
    for outcome in outcomes:
        _identity(outcome.trial_id)
        if outcome.trial_id not in plan.trial_ids:
            raise ValueError('UNREPORTED_TRIAL_OUTSIDE_FROZEN_FAMILY')
        if outcome.trial_id in normalized:
            raise ValueError('DUPLICATE_OUTCOME')
        if type(outcome.completed) is not bool:
            raise ValueError('INVALID_COMPLETION_FLAG')
        sessions = outcome.session_ids
        if (type(sessions) is not tuple or len(sessions) > MAX_SESSIONS
                or type(outcome.baseline_losses) is not tuple
                or type(outcome.candidate_losses) is not tuple
                or len(outcome.baseline_losses) != len(sessions)
                or len(outcome.candidate_losses) != len(sessions)):
            raise ValueError('INVALID_OR_UNBALANCED_ROWS')
        previous = ''
        for session in sessions:
            if type(session) is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}', session) is None:
                raise ValueError('INVALID_SESSION_DAY')
            try:
                valid = date.fromisoformat(session).isoformat() == session
            except ValueError:
                valid = False
            if not valid or session <= previous:
                raise ValueError('INVALID_OR_UNORDERED_SESSION_DAY')
            previous = session
        if outcome.completed:
            if common is None:
                common = sessions
            elif common != sessions:
                raise ValueError('COMMON_ORDERED_SESSIONS_REQUIRED')
        baseline = _losses(outcome.baseline_losses)
        candidate = _losses(outcome.candidate_losses)
        differences[outcome.trial_id] = [a-b for a, b in zip(baseline, candidate)]
        normalized[outcome.trial_id] = dict(trial_id=outcome.trial_id,
            session_ids=list(sessions), baseline_losses=baseline,
            candidate_losses=candidate, completed=outcome.completed)

    method = dict(version='paired-session-block-sign-flip-v1',
        hypothesis='MEAN_BASELINE_MINUS_CANDIDATE_GT_ZERO', weighting='EQUAL_SESSION',
        min_distinct_sessions=MIN_SESSIONS, max_sessions_per_trial=MAX_SESSIONS,
        max_trials=MAX_TRIALS, max_loss=MAX_LOSS, block_size_sessions=BLOCK_SIZE,
        draws=DRAWS, seed=SEED, correction='HOLM_COMPLETE_FROZEN_FAMILY',
        exceedance='RANDOMIZED_MEAN_GREATER_THAN_OR_EQUAL_TO_OBSERVED',
        p_formula='(1+exceedances)/(draws+1)', shared_block_signs_across_family=True,
        final_partial_block='RETAIN_ACTUAL_SESSION_WEIGHT')
    frozen = dict(trial_ids=list(plan.trial_ids), method=method)
    ordered = [normalized.get(t) for t in plan.trial_ids]
    count = len(common) if common is not None else 0
    missing = [t for t in plan.trial_ids if t not in normalized]
    incomplete = [t for t in plan.trial_ids
                  if t in normalized and normalized[t]['completed'] is not True]
    result: dict[str, object] = dict(status='INSUFFICIENT_EVIDENCE',
        trial_family=list(plan.trial_ids), method=method, session_count=count,
        missing_trials=missing, incomplete_trials=incomplete,
        plan_sha256=_hash(frozen), input_sha256=_hash(dict(plan=frozen, outcomes=ordered)),
        training_eligible=False, approval=False, approval_authority=False, promotable=False,
        selection_performed=False, input_provenance='CALLER_SUPPLIED_NOT_ATTESTED',
        assumptions_verified=False, licence_verified=False, study_admission_verified=False,
        assumptions=['BLOCK_SIGN_SYMMETRY', 'APPROXIMATE_INDEPENDENCE_BETWEEN_BLOCKS'],
        adequacy='FIXED_DESIGN_FLOOR_NOT_UNIVERSAL_SAMPLE_ADEQUACY')
    if missing or incomplete or count < MIN_SESSIONS:
        return result

    blocks = {t: [math.fsum(differences[t][i:i+BLOCK_SIZE])
                  for i in range(0, count, BLOCK_SIZE)] for t in plan.trial_ids}
    observed = {t: math.fsum(blocks[t]) / count for t in plan.trial_ids}
    exceed = dict.fromkeys(plan.trial_ids, 0)
    rng = random.Random(SEED)
    block_count = len(blocks[plan.trial_ids[0]])
    for _ in range(DRAWS):
        signs = [1 if rng.getrandbits(1) else -1 for _ in range(block_count)]
        for t in plan.trial_ids:
            randomized = math.fsum(sign * value for sign, value in zip(signs, blocks[t])) / count
            if randomized >= observed[t]:
                exceed[t] += 1
    raw = {t: (1+exceed[t]) / (DRAWS+1) for t in plan.trial_ids}
    ranked = sorted(plan.trial_ids, key=lambda t: raw[t])
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, t in enumerate(ranked):
        running = max(running, min(1.0, (len(ranked)-rank)*raw[t]))
        adjusted[t] = running
    trials: list[dict[str, object]] = []
    for t in plan.trial_ids:
        record = normalized[t]
        # Means use the original paired session arrays, never bar counts.
        original = next(o for o in outcomes if o.trial_id == t)
        trials.append(dict(trial_id=record['trial_id'],
            baseline_mean_loss=math.fsum(original.baseline_losses)/count,
            candidate_mean_loss=math.fsum(original.candidate_losses)/count,
            mean_loss_improvement=observed[t], raw_p=raw[t], holm_adjusted_p=adjusted[t],
            exceedances=exceed[t]))
    result.update(status='METHOD_OUTPUT_UNADMITTED', trials=trials,
                  block_count=block_count,
                  block_session_counts=[min(BLOCK_SIZE, count-i) for i in range(0, count, BLOCK_SIZE)])
    return result
