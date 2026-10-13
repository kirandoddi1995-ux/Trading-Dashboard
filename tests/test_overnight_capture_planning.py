from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, TypedDict, cast

import pytest

from overnight_capture_audit import Generation
from overnight_capture_calendar import CalendarEvidence, analyze_close, diagnose_nse_source, upstox_timing
from overnight_capture_planning import EligibilityInputs, Preregistration, plan_tasks, research_gate


def at(day: str, time: str) -> datetime:
    return datetime.fromisoformat(day + 'T' + time + ':00+05:30')


def test_owner_plan_is_inert_and_collisions_do_not_replace(tmp_path: Path) -> None:
    opening, closing = at('2026-10-14', '09:15'), at('2026-10-14', '15:30')
    class Options(TypedDict):
        owner_sid: str
        namespace: str
        calendar_reviewed: bool
        license_reviewed: bool
        private_namespace_reviewed: bool
        python_executable: Path
        working_directory: Path
        private_root: Path

    kwargs: Options = dict(owner_sid='S-1-5-21-123', namespace='overnight_capture_new',
                  calendar_reviewed=True, license_reviewed=True, private_namespace_reviewed=True,
                  python_executable=tmp_path / 'code' / '.venv' / 'Scripts' / 'python.exe',
                  working_directory=tmp_path / 'code', private_root=tmp_path / 'private')
    plan = plan_tasks(opening, closing, existing_names=frozenset({'KiranTrading-Forward-poll'}), **kwargs)
    assert not plan.blockers and len(plan.tasks) == 3
    assert all(not task.enabled and task.action == 'REVIEW_ONLY' for task in plan.tasks)
    assert all(task.logon == 'InteractiveToken' and task.privilege == 'LeastPrivilege' for task in plan.tasks)
    assert not plan.installation_performed and not plan.deletion_performed
    assert plan.tasks[0].mode == 'prepare-policy'
    assert plan.tasks[1].repeat_count == 75 and plan.tasks[1].repeat_interval_minutes == 5
    assert plan.tasks[1].last_at == at('2026-10-14', '15:30') + timedelta(seconds=30)
    assert plan.tasks[2].at == at('2026-10-14', '15:40')
    assert '--session-date' in plan.tasks[1].arguments and '2026-10-14' in plan.tasks[1].arguments
    assert '--confirm-versioned-research' in plan.tasks[1].arguments
    assert plan.tasks[1].executable == str(kwargs['python_executable'])
    collision = plan_tasks(opening, closing, existing_names=frozenset({plan.tasks[0].name.upper()}), **kwargs)
    assert collision.tasks == () and collision.blockers == ('TASK_NAME_COLLISION',)
    blocked = plan_tasks(opening, closing, owner_sid='S-1-5-21-123',
                         namespace='overnight_capture_new', existing_names=frozenset(),
                         python_executable=kwargs['python_executable'], working_directory=kwargs['working_directory'],
                         private_root=kwargs['private_root'])
    assert len(blocked.blockers) == 3 and not blocked.tasks


def registration() -> Preregistration:
    return Preregistration('a' * 64, at('2026-10-13', '08:00'), at('2026-10-14', '09:15'),
                           2, 'fixed hypothesis', 'forward outcomes', 'exclude incomplete', 'date split')


def generation(day: str, sha: str = 'b') -> Generation:
    return Generation(sha * 64, 'c' * 64, at(day, '09:15').isoformat(), 75, 75, 0, 75,
                      policy_sha256='a' * 64)


def test_insufficient_inputs_and_monday_not_relabelled() -> None:
    result = research_gate(registration(), EligibilityInputs())
    assert result.status == 'BLOCKED' and len(result.blockers) == 5
    monday = generation('2026-10-12')
    result = research_gate(registration(), EligibilityInputs((monday,)))
    assert 'SESSION_OUTSIDE_PREREGISTRATION' in result.blockers
    assert result.qualifying_sessions == 0
    assert not result.retrospective_relabeling_allowed
    assert not result.training_eligible and not result.approval_authority


def test_review_readiness_never_grants_training_or_trading() -> None:
    inputs = EligibilityInputs((generation('2026-10-14'), generation('2026-10-15', 'd')),
                               'e' * 64, 'f' * 64, '1' * 64, '2' * 64)
    result = research_gate(registration(), inputs)
    assert result.research_review_ready and not result.training_eligible and not result.approval_authority
    duplicated = replace(inputs, generations=(inputs.generations[0], inputs.generations[0]))
    assert 'DUPLICATE_SESSION_OR_GENERATION' in research_gate(registration(), duplicated).blockers
    incomplete = replace(inputs, generations=(replace(inputs.generations[0], missing_decisions=1),))
    assert 'SESSION_EVIDENCE_INSUFFICIENT' in research_gate(registration(), incomplete).blockers
    late = replace(registration(), registered_at=registration().first_session_open)
    assert 'PREREGISTRATION_NOT_PROSPECTIVE' in research_gate(late, inputs).blockers


@cast(Callable[[Callable[[str, str, int], None]], Callable[[str, str, int], None]],
      pytest.mark.parametrize('kind,close,slots', [('CASH_INDEX', '15:30', 75), ('EQUITY_DERIVATIVES', '15:40', 77)]))
def test_source_specific_windows(kind: str, close: str, slots: int) -> None:
    from overnight_capture_calendar import Kind
    selected = cast(Kind, kind)
    day = date(2026, 10, 14)
    assert analyze_close(day, selected).status == 'BLOCKED'
    evidence = CalendarEvidence(day, selected, at(str(day), '09:15'), at(str(day), close),
                                'https://example.invalid/synthetic', 'a' * 64, True)
    result = analyze_close(day, selected, evidence)
    assert result.full_five_minute_windows == slots and result.original_capture_slots == 75
    assert result.verification_not_before == at(str(day), '15:45' if slots == 77 else '15:35')
    assert result.owner_index_audit_at == (at(str(day), '15:40') if slots == 75 else None)
    assert analyze_close(day, selected, replace(evidence, special_session=True)).status == 'BLOCKED'
    assert analyze_close(day, selected, replace(evidence, reviewed=False)).status == 'BLOCKED'


def test_wrong_derivatives_close_and_cas_block() -> None:
    day = date(2026, 10, 14)
    evidence = CalendarEvidence(day, 'EQUITY_DERIVATIVES', at(str(day), '09:15'), at(str(day), '15:30'),
                                'https://example.invalid/synthetic', 'a' * 64, True)
    assert 'REFERENCE_TIMING_CONFLICT_REQUIRES_REVIEW' in analyze_close(day, evidence.kind, evidence).blockers
    cas = replace(evidence, kind='CAS_EQUITY')
    assert 'AUCTION_AND_CONTINUOUS_BARS_REQUIRE_SEPARATE_POLICY' in analyze_close(day, cas.kind, cas).blockers
    assert analyze_close(date(2026, 8, 2), 'EQUITY_DERIVATIVES').regular_reference_close == '15:30'


def test_offline_upstox_timing_segment_mapping() -> None:
    day = date(2026, 10, 14)
    rows = [{'exchange': code, 'start_time': int(at(str(day), '09:15').timestamp() * 1000),
             'end_time': int(at(str(day), close).timestamp() * 1000)}
            for code, close in [('NSE', '15:30'), ('NFO', '15:40')]]
    payload = {'status': 'success', 'data': rows}
    cash = upstox_timing(payload, day, 'CASH_INDEX', reviewed=True)
    fo = upstox_timing(payload, day, 'EQUITY_DERIVATIVES', reviewed=True)
    assert cash.closing != fo.closing
    assert analyze_close(day, fo.kind, fo).full_five_minute_windows == 77
    assert analyze_close(day, cash.kind, cash).full_five_minute_windows == 75
    with pytest.raises(ValueError):
        upstox_timing({'status': 'success', 'data': []}, day, 'CASH_INDEX')
    with pytest.raises(ValueError):
        upstox_timing({'status': 'success', 'data': rows + rows}, day, 'CASH_INDEX')
    with pytest.raises(ValueError):
        upstox_timing(payload, date(2026, 10, 15), 'CASH_INDEX')


def test_source_diagnosis_never_commissions_network_or_bypasses_terms() -> None:
    mismatch = diagnose_nse_source(browser_download_observed=True,
                                   python_transport_status='NSE_CLOSE_CONNECTION_ERROR')
    assert mismatch.conclusion == 'BROWSER_PYTHON_CLIENT_OR_ROUTE_DIFFERENCE_CAUSE_UNPROVEN'
    assert mismatch.automated_route_status == 'BLOCKED'
    assert mismatch.owner_file_route == 'EXISTING_REVIEWED_EXPLICIT_OWNER_FILE_ONLY'
    assert mismatch.network_calls == mismatch.writes == 0 and not mismatch.session_prepared
    success = diagnose_nse_source(browser_download_observed=True,
                                  python_transport_status='TRANSPORT_CHECK_COMPLETE')
    assert success.automated_route_status == 'BLOCKED'
    assert 'SOURCE_SPECIFIC_ZERO_COST_USAGE_TERMS_UNVERIFIED' in success.blockers
    assert 'NOT_CSV_OR_SOURCE_VALIDATION' in success.conclusion
    absent = diagnose_nse_source(browser_download_observed=None, python_transport_status=None)
    assert absent.automated_route_status == 'BLOCKED'
    with pytest.raises(ValueError):
        diagnose_nse_source(browser_download_observed=True, python_transport_status='PRIVATE RAW ERROR')
