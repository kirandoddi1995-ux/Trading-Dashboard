"""Generated 2022 calendar-day toy loss scores, not market data or returns."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import math
import random
from typing import cast

import pytest

from research_session_inference import StudyPlan, TrialOutcome, infer


def toy(trial: str = 'toy', n: int = 120, baseline: float = 2.0,
        candidate: float = 1.0) -> TrialOutcome:
    assert 0 <= n <= 365  # Only generated 2022 dates in these fixtures.
    sessions = tuple((date(2022, 1, 1)+timedelta(days=i)).isoformat() for i in range(n))
    return TrialOutcome(trial, sessions, (baseline,)*n, (candidate,)*n)


def trials(result: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], result['trials'])


def test_positive_fixed_design_never_admits_or_selects() -> None:
    result = infer(StudyPlan(('toy',)), [toy()])
    assert result['status'] == 'METHOD_OUTPUT_UNADMITTED'
    row = trials(result)[0]
    assert row['mean_loss_improvement'] == 1.0 and row['raw_p'] == .001
    assert result['block_count'] == 24
    for flag in ('training_eligible', 'approval', 'promotable', 'selection_performed',
                 'assumptions_verified', 'licence_verified', 'study_admission_verified'):
        assert result[flag] is False


@pytest.mark.parametrize('baseline,candidate', [(0., 0.), (2., 2.), (0., 1.)])
def test_negative_neutral_zero_stability(baseline: float, candidate: float) -> None:
    row = trials(infer(StudyPlan(('toy',)), [toy(baseline=baseline, candidate=candidate)]))[0]
    assert row['raw_p'] == row['holm_adjusted_p'] == 1.0


@pytest.mark.parametrize('kind', ['missing', 'unrun', 'failed', 'short', 'empty', 'unrun_empty'])
def test_incomplete_family_has_no_pvalues_or_selection(kind: str) -> None:
    outcomes = [toy('a'), toy('b')]
    if kind == 'missing':
        outcomes.pop()
    elif kind in ('unrun', 'failed'):
        outcomes[1] = replace(outcomes[1], completed=False)
    elif kind == 'short':
        outcomes = [toy('a', 119), toy('b', 119)]
    elif kind == 'unrun_empty':
        outcomes[1] = replace(toy('b', 0), completed=False)
    else:
        outcomes = []
    result = infer(StudyPlan(('a', 'b')), outcomes)
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert 'trials' not in result and 'raw_p' not in result
    assert result['selection_performed'] is False


def test_shared_draws_family_holm_monotonic_and_complete() -> None:
    outcomes = [toy('positive'), toy('neutral', candidate=2.), toy('negative', candidate=3.), toy('copy')]
    result = infer(StudyPlan(tuple(o.trial_id for o in outcomes)), outcomes)
    rows = trials(result)
    assert [r['trial_id'] for r in rows] == ['positive', 'neutral', 'negative', 'copy']
    assert rows[0]['raw_p'] == rows[3]['raw_p']
    ordered = sorted(rows, key=lambda r: cast(float, r['raw_p']))
    prior = 0.0
    for rank, row in enumerate(ordered):
        prior = max(prior, min(1., (len(rows)-rank)*cast(float, row['raw_p'])))
        assert row['holm_adjusted_p'] == prior


def test_equal_session_weight_partial_block_and_determinism() -> None:
    outcome = toy(n=121, baseline=0., candidate=0.)
    outcome = replace(outcome, baseline_losses=(120.,)+(0.,)*120)
    result = infer(StudyPlan(('toy',)), [outcome])
    assert result == infer(StudyPlan(('toy',)), [outcome])
    assert trials(result)[0]['mean_loss_improvement'] == 120/121
    assert result['block_session_counts'] == [5]*24+[1]
    assert trials(result)[0]['raw_p'] == (1+cast(int, trials(result)[0]['exceedances']))/1000


def test_hash_binds_plan_scores_sessions_completion_and_normalizes_outcome_order() -> None:
    plan = StudyPlan(('a', 'b'))
    outcomes = [toy('a'), toy('b')]
    base = infer(plan, outcomes)
    assert infer(plan, outcomes[::-1]) == base
    assert infer(StudyPlan(('b', 'a')), outcomes)['plan_sha256'] != base['plan_sha256']
    for changed in (replace(outcomes[1], candidate_losses=(0.,)*120),
                    replace(outcomes[1], completed=False)):
        assert infer(plan, [outcomes[0], changed])['input_sha256'] != base['input_sha256']
    shifted = [replace(o, session_ids=toy(n=121).session_ids[1:]) for o in outcomes]
    assert infer(plan, shifted)['input_sha256'] != base['input_sha256']
    assert len(cast(str, base['plan_sha256'])) == 64


@pytest.mark.parametrize('value', [True, False, math.nan, math.inf, -math.inf, -1., 1e12+1])
def test_bad_scores_rejected(value: float) -> None:
    outcome = replace(toy(), candidate_losses=(value,)+(1.,)*119)
    with pytest.raises(ValueError):
        infer(StudyPlan(('toy',)), [outcome])


@pytest.mark.parametrize('kind', ['duplicate', 'reversed', 'invalid', 'noncanonical', 'different', 'unbalanced'])
def test_strict_common_unique_chronological_dates(kind: str) -> None:
    a, b = toy('a'), toy('b')
    keys = b.session_ids
    if kind == 'duplicate':
        b = replace(b, session_ids=(keys[0],)+keys[:-1])
    elif kind == 'reversed':
        b = replace(b, session_ids=keys[::-1])
    elif kind == 'invalid':
        b = replace(b, session_ids=('2022-02-30',)+keys[1:])
    elif kind == 'noncanonical':
        b = replace(b, session_ids=('20220101',)+keys[1:])
    elif kind == 'different':
        b = replace(b, session_ids=toy(n=121).session_ids[1:])
    else:
        b = replace(b, candidate_losses=(1.,))
    with pytest.raises(ValueError):
        infer(StudyPlan(('a', 'b')), [a, b])


@pytest.mark.parametrize('kind', ['empty', 'duplicate', 'extra', 'duplicate_outcome', 'id', 'many', 'rows', 'flag'])
def test_policy_and_identity_bounds(kind: str) -> None:
    plan, outcomes = StudyPlan(('toy',)), [toy()]
    if kind == 'empty':
        plan = StudyPlan(())
    elif kind == 'duplicate':
        plan = StudyPlan(('toy', 'toy'))
    elif kind == 'extra':
        outcomes = [toy('unreported')]
    elif kind == 'duplicate_outcome':
        outcomes *= 2
    elif kind == 'id':
        plan = StudyPlan(('bad id',))
    elif kind == 'many':
        plan = StudyPlan(tuple(str(i) for i in range(17)))
    elif kind == 'rows':
        outcomes = [replace(toy(), session_ids=('2022-01-01',)*2001)]
    else:
        outcomes = [replace(toy(), completed=cast(bool, 1))]
    with pytest.raises(ValueError):
        infer(plan, outcomes)


def test_fixed_method_policy_and_loss_ceiling() -> None:
    result = infer(StudyPlan(('toy',)), [toy(baseline=1e12, candidate=1e12)])
    method = cast(dict[str, object], result['method'])
    assert (method['min_distinct_sessions'], method['block_size_sessions'], method['draws'], method['seed']) == (120, 5, 999, 1729)
    assert method['max_sessions_per_trial'] == 2000 and method['max_trials'] == 16
    assert result['input_provenance'] == 'CALLER_SUPPLIED_NOT_ATTESTED'


def test_block_randomization_matches_explicit_toy_reference() -> None:
    # Each five-day block moves together; reference uses the same signs for both
    # trials. Integer toy losses make exact exceedance comparisons transparent.
    vectors = [tuple(float((i//5)%3-1) for i in range(121)),
               tuple(float(2 if (i//5)%4 else -1) for i in range(121))]
    outcomes = [replace(toy(name, 121), baseline_losses=tuple(3.+v for v in vector),
                        candidate_losses=(3.,)*121)
                for name, vector in zip(('a', 'b'), vectors)]
    rows = trials(infer(StudyPlan(('a', 'b')), outcomes))
    generator = random.Random(1729)
    exceed = [0, 0]
    for _ in range(999):
        signs = [1 if generator.getrandbits(1) else -1 for _ in range(25)]
        for index, vector in enumerate(vectors):
            transformed = sum(signs[i//5]*value for i, value in enumerate(vector))
            if transformed >= sum(vector):
                exceed[index] += 1
    assert [row['raw_p'] for row in rows] == [(1+n)/1000 for n in exceed]
    assert [row['mean_loss_improvement'] for row in rows] == [sum(v)/121 for v in vectors]


def test_full_sixteen_trial_family_is_returned_without_selection() -> None:
    family = tuple(f'toy{i}' for i in range(16))
    result = infer(StudyPlan(family), [toy(t) for t in family])
    assert len(trials(result)) == 16
    assert all(row['holm_adjusted_p'] == .016 for row in trials(result))
    assert result['selection_performed'] is False
