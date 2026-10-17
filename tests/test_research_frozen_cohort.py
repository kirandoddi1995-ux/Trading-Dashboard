"""Generated 2022 calendar-day toy observations/quotes, not market evidence."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, replace
from datetime import date, timedelta
import hashlib
import json
import math
from typing import cast

import pytest

import quote_faithful_futures_replay as paper
import research_dataset_boundary as boundary
import research_frozen_cohort as cohort

PIN = 'a'*64
BASELINE = 'b'*64


def evidence(day: str, direction: int = 1) -> cohort.SessionEvidence:
    def at(clock: str) -> str:
        return f'{day}T{clock}+05:30'
    entry = boundary.SourceVersion('entry', 1, at('09:59:00'), at('10:00:00'), 100., 1, PIN, PIN)
    target = boundary.SourceVersion('target', 1, at('10:05:00'), at('10:05:00'), 101., 1, PIN, PIN)
    decision = boundary.DecisionInput('toy', at('10:00:00'), ('entry',), 'entry', boundary.input_sha256((entry,)))
    label = boundary.ReferenceLabel('toy', at('10:05:00'), at('10:05:00'), 'target', boundary.version_sha256(target))
    dataset = boundary.DatasetPlan(PIN, PIN, 'DEVELOPMENT_2022_2024', '2022-01-02T00:00:00+05:30',
                                  ('toy',), PIN, PIN, True, True, True, False, 'SYNTHETIC')
    replay = paper.ReplayPlan(PIN, decision.input_sha256, at('10:00:00'), at('09:15:00'), at('15:30:00'),
                              at('10:00:00'), at('10:05:00'), direction, 1, 100, 500, 'SYNTHETIC')
    contract = paper.Contract('TOY', PIN, '2022-01-01T00:00:00+05:30',
                              '2022-01-01', '2022-12-30', '2022-12-30', '0.05', 10, 'INR', '1')
    costs = paper.DatedCosts(PIN, '2022-01-01T00:00:00+05:30', '2022-01-01', '2022-12-31',
                            '0.001', '0.002', '1', 1, 'INR')
    quotes = (paper.Quote('entry', 1, 'TOY', at('10:00:00.100'), at('10:00:00.200'), '99.95', '100.05', 10, 10, PIN),
              paper.Quote('exit', 1, 'TOY', at('10:05:00.100'), at('10:05:00.200'), '101.95', '102.05', 10, 10, PIN))
    result = cohort.SessionEvidence(PIN, BASELINE, 0, direction, at('10:00:00'), PIN,
                                    dataset, (entry, target), decision, label, replay, contract, costs, quotes)
    return reseal(result)


def reseal(e: cohort.SessionEvidence) -> cohort.SessionEvidence:
    return replace(e, frozen_decision_sha256=cohort.decision_sha256(e))


def fixture(n: int = 2) -> tuple[cohort.CohortPlan, tuple[cohort.TrialSession, ...]]:
    assert 1 <= n <= 360
    days = tuple((date(2022, 1, 3)+timedelta(days=i)).isoformat() for i in range(n))
    plan = cohort.CohortPlan(PIN, PIN, BASELINE, '2022-01-01T00:00:00+05:30',
                            (cohort.TrialDefinition('a', PIN), cohort.TrialDefinition('b', PIN)),
                            days, 'DEVELOPMENT_2022_2024', 'SYNTHETIC')
    jobs = tuple(cohort.TrialSession(trial.trial_id, day, 'RUN', evidence(day, 1 if trial.trial_id == 'a' else -1))
                 for trial in plan.trials for day in days)
    return plan, jobs


def evaluate(plan: cohort.CohortPlan, jobs: tuple[cohort.TrialSession, ...]) -> cohort.CohortResult:
    return cohort.evaluate(plan, jobs, frozen_plan_sha256=cohort.plan_sha256(plan),
                           evaluated_at='2022-12-31T18:00:00+05:30')


def get_evidence(job: cohort.TrialSession) -> cohort.SessionEvidence:
    assert job.evidence is not None
    return job.evidence


def no_metrics(result: cohort.CohortResult) -> None:
    method = json.loads(result.inference_json)
    assert result.status == 'INSUFFICIENT_EVIDENCE'
    assert method['trial_family'] == ['a', 'b']
    assert method['status'] == 'INSUFFICIENT_EVIDENCE'
    assert 'trials' not in method
    assert all(flag is False for flag in (result.training_eligible, result.promotable,
        result.approval_authority, result.authenticated_admission, result.selection_performed,
        result.successful_subset_performance_reported))


def test_complete_full_family_calls_actual_block_holm_inference_never_selects() -> None:
    plan, jobs = fixture(120)
    result = evaluate(plan, jobs)
    assert result.status == 'COHORT_METHOD_OUTPUT_UNADMITTED'
    method = json.loads(result.inference_json)
    assert [t['trial_id'] for t in method['trials']] == ['a', 'b']
    assert method['trials'][0]['baseline_mean_loss'] == 1
    assert method['trials'][0]['candidate_mean_loss'] == 0
    assert method['trials'][1]['candidate_mean_loss'] == 4
    assert method['trials'][0]['raw_p'] == .001
    assert method['trials'][0]['holm_adjusted_p'] == .002
    assert method['trials'][1]['raw_p'] == 1
    assert method['session_count'] == 120 and method['block_count'] == 24
    assert all(t.complete and len(t.sessions) == 120 for t in result.trials)
    assert result.training_eligible is result.promotable is result.approval_authority is False
    assert result == evaluate(plan, jobs[::-1])


def test_one_missing_last_cell_blocks_good_120_session_trial_no_subset_performance() -> None:
    plan, jobs = fixture(120)
    result = evaluate(plan, jobs[:-1])
    no_metrics(result)
    assert result.trials[0].complete and not result.trials[1].complete
    assert result.trials[1].sessions[-1].status == 'NOT_REPORTED'
    assert sum(len(t.sessions) for t in result.trials) == 240


def test_all_missing_family_and_short_complete_cohort_still_have_all_slots() -> None:
    plan, jobs = fixture()
    missing = evaluate(plan, ())
    no_metrics(missing)
    assert all(c.status == 'NOT_REPORTED' for t in missing.trials for c in t.sessions)
    short = evaluate(plan, jobs)
    no_metrics(short)
    assert all(t.complete for t in short.trials)


@pytest.mark.parametrize('kind', ['failed', 'unrun', 'empty', 'no_fills', 'no_label', 'bad_tick', 'bad_version', 'nonfinite'])
def test_adversarial_cell_retained_without_successful_subset_metrics(kind: str) -> None:
    plan, jobs = fixture()
    target = jobs[-1]
    e = get_evidence(target)
    expected = 'REJECTED'
    if kind == 'failed':
        target = replace(target, state='FAILED')
        expected = 'FAILED'
    elif kind == 'unrun':
        target = replace(target, state='UNRUN', evidence=None)
        expected = 'UNRUN'
    elif kind == 'empty':
        target = replace(target, evidence=None)
        expected = 'MISSING_EVIDENCE'
    elif kind == 'no_fills':
        target = replace(target, evidence=replace(e, quotes=()))
        expected = 'NO_FILLS'
    elif kind == 'no_label':
        target = replace(target, evidence=replace(e, label=None))
        expected = 'DATASET_WITHHELD'
    elif kind == 'bad_tick':
        target = replace(target, evidence=replace(e, quotes=(replace(e.quotes[0], ask='100.01'), e.quotes[1])))
    elif kind == 'bad_version':
        target = replace(target, evidence=replace(e, versions=e.versions+(e.versions[0],)))
    else:
        target = replace(target, evidence=replace(e, versions=(replace(e.versions[0], reference_price=math.nan), e.versions[1])))
    result = evaluate(plan, jobs[:-1]+(target,))
    no_metrics(result)
    cell = result.trials[1].sessions[-1]
    assert cell.status == expected
    assert len(result.trials) == 2 and all(len(t.sessions) == 2 for t in result.trials)
    if kind == 'nonfinite':
        assert cell.input_sha256 is None and cell.reason == 'UNHASHABLE_NONFINITE_INPUT'


@pytest.mark.parametrize('kind', ['baseline', 'reference'])
def test_same_session_different_reference_problem_rejects_all_conflicting_complete_cells(kind: str) -> None:
    plan, jobs = fixture()
    e = get_evidence(jobs[-1])
    if kind == 'baseline':
        e = reseal(replace(e, baseline_direction=1))
    else:
        target = replace(e.versions[1], reference_price=99.)
        assert e.label is not None
        e = replace(e, versions=(e.versions[0], target),
                    label=replace(e.label, target_version_sha256=boundary.version_sha256(target)))
    result = evaluate(plan, jobs[:-1]+(replace(jobs[-1], evidence=e),))
    no_metrics(result)
    assert all(t.sessions[-1].reason == 'COMMON_SESSION_EVIDENCE_CONFLICT' for t in result.trials)


@pytest.mark.parametrize('kind', ['study', 'source', 'strategy', 'baseline_code', 'prediction', 'prefix',
                                 'forecast', 'session', 'horizon', 'freeze_pin', 'bool_prediction'])
def test_binding_leakage_or_frozen_forecast_mutation_rejects_cell(kind: str) -> None:
    plan, jobs = fixture()
    e = get_evidence(jobs[-1])
    if kind == 'study':
        e = replace(e, replay_plan=replace(e.replay_plan, study_sha256='c'*64))
    elif kind == 'source':
        e = replace(e, dataset_plan=replace(e.dataset_plan, source_sha256='c'*64))
    elif kind == 'strategy':
        e = replace(e, strategy_sha256='c'*64)
    elif kind == 'baseline_code':
        e = replace(e, baseline_strategy_sha256='c'*64)
    elif kind == 'prediction':
        e = replace(e, candidate_direction=1)
    elif kind == 'prefix':
        e = replace(e, decision=replace(e.decision, input_sha256='c'*64))
    elif kind == 'forecast':
        e = replace(e, forecast_at=e.replay_plan.exit_decision_at)
    elif kind == 'session':
        e = replace(e, replay_plan=replace(e.replay_plan, session_close='2022-01-05T15:30:00+05:30'))
    elif kind == 'horizon':
        assert e.label is not None
        e = replace(e, label=replace(e.label, horizon_end=e.decision.decision_at))
    elif kind == 'freeze_pin':
        e = replace(e, baseline_direction=1)  # Deliberately do not reseal.
    else:
        e = replace(e, baseline_direction=cast(int, True))
    result = evaluate(plan, jobs[:-1]+(replace(jobs[-1], evidence=e),))
    no_metrics(result)
    assert result.trials[1].sessions[-1].status == 'REJECTED'


@pytest.mark.parametrize('kind', ['duplicate', 'unknown_trial', 'unknown_session', 'bad_state'])
def test_ambiguous_or_undeclared_outcomes_cannot_be_silently_dropped(kind: str) -> None:
    plan, jobs = fixture()
    if kind == 'duplicate':
        jobs += jobs[:1]
    elif kind == 'unknown_trial':
        jobs = (replace(jobs[0], trial_id='unregistered'),)
    elif kind == 'unknown_session':
        jobs = (replace(jobs[0], session_id='2022-12-31'),)
    else:
        jobs = (replace(jobs[0], state='SUCCEEDED_BEST_ONLY'),)
    with pytest.raises(ValueError):
        evaluate(plan, jobs)


@pytest.mark.parametrize('kind', ['sessions', 'duplicate_trial', 'unfreeze', 'sealed', 'real', 'bound', 'naive'])
def test_invalid_frozen_plan_is_rejected_before_child_evaluation(kind: str) -> None:
    plan, jobs = fixture()
    if kind == 'sessions':
        plan = replace(plan, session_ids=plan.session_ids[::-1])
    elif kind == 'duplicate_trial':
        plan = replace(plan, trials=plan.trials[:1]*2)
    elif kind == 'unfreeze':
        plan = replace(plan, frozen_at='2022-01-03T10:00:00+05:30')
    elif kind == 'sealed':
        plan = replace(plan, session_ids=('2025-01-03',))
    elif kind == 'real':
        plan = replace(plan, input_kind='REAL')
    elif kind == 'bound':
        plan = replace(plan, session_ids=plan.session_ids*2001)
    else:
        plan = replace(plan, frozen_at='2022-01-01T00:00:00')
    with pytest.raises(ValueError):
        evaluate(plan, jobs)


def test_plan_input_child_and_result_digests_are_bound_and_immutable() -> None:
    plan, jobs = fixture()
    pin = cohort.plan_sha256(plan)
    with pytest.raises(ValueError, match='FROZEN_COHORT_HASH_MISMATCH'):
        cohort.evaluate(replace(plan, study_sha256='c'*64), jobs, frozen_plan_sha256=pin,
                        evaluated_at='2022-12-31T18:00:00+05:30')
    result = evaluate(plan, jobs)
    assert hashlib.sha256(result.manifest).hexdigest() == result.manifest_sha256
    e = get_evidence(jobs[0])
    changed = replace(e, quotes=(replace(e.quotes[0], payload_sha256='c'*64), e.quotes[1]))
    revised = evaluate(plan, (replace(jobs[0], evidence=changed),)+jobs[1:])
    assert revised.trials[0].sessions[0].input_sha256 != result.trials[0].sessions[0].input_sha256
    assert revised.manifest_sha256 != result.manifest_sha256
    assert revised.trials[0].sessions[0].replay_manifest_sha256 != result.trials[0].sessions[0].replay_manifest_sha256
    with pytest.raises(FrozenInstanceError):
        setattr(result, 'training_eligible', True)


def test_resource_limits_are_global_not_just_per_child() -> None:
    plan, jobs = fixture()
    e = get_evidence(jobs[0])
    with pytest.raises(ValueError, match='CELL_RESOURCE_BOUND'):
        evaluate(plan, (replace(jobs[0], evidence=replace(e, quotes=e.quotes*129)),))
    with pytest.raises(ValueError, match='SCALAR_BOUND'):
        evaluate(plan, (replace(jobs[0], evidence=replace(e, strategy_sha256='a'*129)),))


def test_no_paper_profit_aggregation_or_loss_coercion() -> None:
    plan, jobs = fixture()
    result = evaluate(plan, jobs)
    manifest = json.loads(result.manifest)
    assert manifest['pnl_performance_reported'] is False
    assert manifest['successful_subset_performance_reported'] is False
    assert not any('loss' in field or 'pnl' in field or 'profit' in field
                   for trial in manifest['trials'] for cell in trial['sessions'] for field in cell)
    assert manifest['frozen']['loss'] == 'SQUARED_REFERENCE_DIRECTION_ERROR_ONE_DECISION_PER_SESSION'


def test_earlier_forecast_cannot_claim_prefix_observed_only_at_later_decision() -> None:
    plan, jobs = fixture()
    e = get_evidence(jobs[-1])
    earlier = e.forecast_at.replace('10:00:00', '09:50:00')
    e = reseal(replace(e, forecast_at=earlier, replay_plan=replace(e.replay_plan, frozen_at=earlier)))
    result = evaluate(plan, jobs[:-1]+(replace(jobs[-1], evidence=e),))
    no_metrics(result)
    assert result.trials[1].sessions[-1].reason == 'CELL_BINDING_OR_TIME_REJECTED'


@pytest.mark.parametrize('clock,complete', [('10:05:00', False), ('10:05:00.199', False), ('10:05:00.200', True)])
def test_selected_exit_quote_must_be_available_by_evaluation_cutoff(clock: str, complete: bool) -> None:
    plan, jobs = fixture(1)
    result = cohort.evaluate(plan, jobs, frozen_plan_sha256=cohort.plan_sha256(plan),
                             evaluated_at=f'2022-01-03T{clock}+05:30')
    assert all(t.complete is complete for t in result.trials)
    if not complete:
        assert all(c.status == 'NO_FILLS' for t in result.trials for c in t.sessions)
    no_metrics(result)  # One day cannot satisfy the 120-session inference floor.


def test_future_quote_outcomes_do_not_change_asof_replay_or_enable_family_inference() -> None:
    plan, jobs = fixture(1)
    at = '2022-01-03T10:05:00+05:30'
    def asof(batch: tuple[cohort.TrialSession, ...], cutoff: str = at) -> cohort.CohortResult:
        return cohort.evaluate(plan, batch, frozen_plan_sha256=cohort.plan_sha256(plan), evaluated_at=cutoff)
    base = asof(jobs)
    e = get_evidence(jobs[0])
    # A future off-tick outcome must not be consumed or reject the known stream.
    changed = replace(e, quotes=(e.quotes[0], replace(e.quotes[1], ask='102.01', ask_units=0)))
    revised = asof((replace(jobs[0], evidence=changed),)+jobs[1:])
    left, right = base.trials[0].sessions[0], revised.trials[0].sessions[0]
    assert left.status == right.status == 'NO_FILLS'
    assert left.replay_manifest_sha256 == right.replay_manifest_sha256
    assert left.input_sha256 != right.input_sha256  # Full supplied batch still bound.
    no_metrics(revised)
    later = asof((replace(jobs[0], evidence=changed),)+jobs[1:], '2022-01-03T10:05:00.200+05:30')
    assert later.trials[0].sessions[0].reason == 'REPLAY_INPUT_REJECTED'


def test_future_last_session_exit_blocks_otherwise_complete_120_session_family() -> None:
    plan, jobs = fixture(120)
    result = cohort.evaluate(plan, jobs, frozen_plan_sha256=cohort.plan_sha256(plan),
                             evaluated_at=f'{plan.session_ids[-1]}T10:05:00+05:30')
    no_metrics(result)
    assert all(not t.complete and t.sessions[-1].status == 'NO_FILLS' for t in result.trials)
    assert all(c.status == 'COMPLETE' for t in result.trials for c in t.sessions[:-1])


@pytest.mark.parametrize('bad', [math.nan, math.inf, -math.inf])
def test_nonfinite_early_scalar_never_skips_later_scalar_bounds(bad: float) -> None:
    plan, jobs = fixture()
    e = get_evidence(jobs[0])
    first = replace(e.versions[0], reference_price=bad, payload_sha256='c'*129)
    changed = replace(jobs[0], evidence=replace(e, versions=(first, e.versions[1])))
    with pytest.raises(ValueError, match='SCALAR_BOUND'):
        evaluate(plan, (changed,))


def test_unhashable_cells_still_consume_cumulative_input_byte_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    plan, jobs = fixture()
    changed: list[cohort.TrialSession] = []
    for job in jobs[:2]:
        e = get_evidence(job)
        e = replace(e, versions=(replace(e.versions[0], reference_price=math.nan), e.versions[1]))
        changed.append(replace(job, evidence=e))
    # Allow one cell including conservative invalid-float tag overhead, not two.
    one_size = len(json.dumps(asdict(changed[0]), sort_keys=True, separators=(',', ':'), allow_nan=True).encode())
    monkeypatch.setattr(cohort, 'MAX_INPUT_BYTES', one_size+100)
    one = evaluate(plan, (changed[0],))
    assert one.trials[0].sessions[0].input_sha256 is None
    assert one.trials[0].sessions[0].reason == 'UNHASHABLE_NONFINITE_INPUT'
    with pytest.raises(ValueError, match='TOTAL_INPUT_BYTE_BOUND'):
        evaluate(plan, tuple(changed))
