"""Exact source-level test traceability; no full-suite totals masquerade as proof.

Function selectors include parameter cases. No test is a real commissioning proof.
Entries without a selector explicitly require owner/native evidence instead.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

TESTS: dict[str, str | None] = {
    'NSE transport and daily preparation automation': 'tests/test_nse_close_transport_check.py::test_success_is_transport_only_and_single_request',
    'Standing role-based agent team': 'tests/test_programme_agent_team.py::test_runtime_agents_report_only',
    'Full Supabase database restore drill': None,
    'Upstox Analytics authorization and licence': None,
    'Runtime database credential rotation': None,
    'Setup and tools checkout': 'tests/test_forward_daily_owner.py::test_disabled_setup_partial_registration_proofs',
    'Dated poll task': 'tests/test_forward_ops_plan.py::test_disabled_date_pinned_and_versioned_audit',
    'Dated audit task': 'tests/test_forward_ops_plan.py::test_disabled_date_pinned_and_versioned_audit',
    'Fresh official owner-close file': 'tests/test_nse_owner_close.py::test_manual_recipe_poll_and_audit_acceptance',
    'Prepare and policy freeze': 'tests/test_forward_daily_contract.py::test_prepare_rejects_previous_evening_and_future_downloads',
    'Supervised Start admission': 'tests/test_forward_daily_owner.py::test_start_two_verified_polls_audit_first_poll_last',
    'Automatic recurrence': 'tests/test_forward_ops_plan.py::test_disabled_date_pinned_and_versioned_audit',
    'Version-aware capture and revisions': 'tests/test_forward_versioned_producer.py::test_provider_close_revision_does_not_stop_next_observation_or_rewrite_first',
    'Local journal and capture receipts': 'tests/test_forward_versioned_capture.py::test_unchanged_job_integrates_two_polls_and_separate_receipts',
    'Drive publish and remote readback': 'tests/test_forward_versioned_producer.py::test_remote_readback_mismatch_never_acknowledged',
    'Independent encrypted custody and restore': 'tests/test_recovery_custody_rehearsal.py::test_both_restores_authenticated_but_not_independent_custody',
    'Daily local audit': 'tests/test_forward_session_ops.py::test_gap_counts_and_no_fabricated_decision',
    'Remote custody audit': 'tests/test_forward_session_ops.py::test_complete_does_not_claim_custody_or_training',
    'Local alert notification': 'tests/test_forward_session_ops.py::test_report_append_and_alert_once',
    'Independent alert delivery': 'tests/test_storage_alert_delivery.py::test_acceptance_is_not_owner_receipt_or_commissioning',
    'Windows Time service': 'tests/test_forward_session_ops.py::test_preflight_stopped_service_does_not_imply_ntp_failure',
    'Producer fresh clock gate': 'tests/test_equity_runtime_health.py::test_clock_missing_invalid_stale_and_uncertain_fail',
    '14 October historical read-only audit': 'tests/test_forward_session_ops.py::test_read_only_audit_cli_never_saves_or_alerts',
    'Legacy audit result2 and shared-root writes': None,
    'OPTION_CAPTURE_ENABLED skipped schedules': None,
    'Consistent-cut exports': 'tests/test_storage_consistent_cut_export.py::test_exact_cut_reader_contract_and_native_query',
    'Writer guards and cold readers': 'tests/test_overnight_storage_cold_methods.py::test_actual_reader_exact_authenticated_rows',
    'Universe shadow deduplication': 'tests/test_overnight_storage_universe.py::test_payload_shared_but_snapshot_identity_and_originals_preserved',
    'Bounded retention and deletion': 'tests/test_overnight_storage_sources.py::test_each_source_exact_dedup_restore_retention',
    'Capacity guard across live writers': 'tests/test_storage_write_guard.py::test_uncertain_commit_must_reconcile_not_repeat',
    'Capacity alerts': 'tests/test_storage_capacity_watch.py::test_warning_growth_is_diagnostic_not_write_authorisation',
    'ML backtesting and Evidence Assistant': 'tests/test_research_assistant.py::test_synthetic_references_are_not_measured_reports',
    'Licensed frozen paper-first study': 'tests/test_model_training_pipeline.py::test_too_few_single_class_or_missing_features_fail_before_fitting',
    'Pinned Python and PowerShell toolchain': 'tests/test_forward_daily_owner.py::test_bootstrap_real_explicit_pinned_python_without_launcher',
    'Encrypted-disk 7-Zip tool': None,
}

SUPPORTING: dict[str, tuple[str, ...]] = {
    'Prepare and policy freeze': (
        'tests/test_forward_daily_contract.py::test_prepare_preopen_deadline_is_exclusive',
        'tests/test_forward_versioned_capture.py::test_prepare_no_overwrite_or_after_open',
        'tests/test_forward_versioned_capture.py::test_clock_failure_does_not_freeze'),
    'Automatic recurrence': (
        'tests/test_forward_daily_owner.py::test_start_two_verified_polls_audit_first_poll_last',
        'tests/test_forward_daily_owner.py::test_second_start_cannot_repeat_slot_or_replace_claim'),
    'Dated poll task': ('tests/test_forward_operations_runner.py::test_task_summary_empty_next_trigger_is_not_blocked',),
    'NSE transport and daily preparation automation': (
        'tests/test_forward_guided_owner.py::test_real_chain_exact_order_once',
        'tests/test_forward_guided_owner.py::test_prepare_failure_never_reaches_start'),
}

SCOPE: dict[str, str] = {
    'NSE transport and daily preparation automation':'Single synthetic transport request; guided child order and stop on failure. Browser download remains manual.',
    'Standing role-based agent team':'Runtime agent role is report-only; not a deployed standing team.',
    'Full Supabase database restore drill':'No automated full-project restore evidence; real owner drill required.',
    'Upstox Analytics authorization and licence':'No credential/provider/licence evidence inspected.',
    'Runtime database credential rotation':'No hosted credential rotation tested or performed.',
    'Setup and tools checkout':'Synthetic partial registration states and disabled-role reporting; not native owner-task creation.',
    'Dated poll task':'Generated date-specific disabled task plan; null/unset next-run metadata stays nonfatal and unknown.',
    'Dated audit task':'Generated action targets versioned audit at dated trigger, initially disabled; not actual firing.',
    'Fresh official owner-close file':'Synthetic owner-file recipe accepted by poll/audit validators; not independent CSV provenance.',
    'Prepare and policy freeze':'Real pure Prepare date gates plus no-overwrite/preopen/clock-failure freeze behavior using synthetic inputs.',
    'Supervised Start admission':'Actual coordinator stage code with synthetic callbacks enforces two verified polls and audit-first/poll-last enable order.',
    'Automatic recurrence':'Generated recurrence/date boundaries plus mocked coordinator admission and repeat-Start prevention; not native scheduler execution.',
    'Version-aware capture and revisions':'Changed provider close affects new observation without rewriting first observation.',
    'Local journal and capture receipts':'Real unchanged job integrates two synthetic polls into separate versioned receipt namespace.',
    'Drive publish and remote readback':'Synthetic remote byte/manifest mismatch never acknowledged; not current Drive availability.',
    'Independent encrypted custody and restore':'Authenticated synthetic replica restores; code refuses to call this independent custody.',
    'Daily local audit':'Synthetic slot coverage distinguishes absent observations from real decisions; not a dated owner journal audit.',
    'Remote custody audit':'Complete synthetic local coverage does not grant custody or training eligibility.',
    'Local alert notification':'Synthetic reports append and category alerts deduplicate; notifier is fake, no desktop delivery.',
    'Independent alert delivery':'Transport acceptance is not owner acknowledgement or commissioning.',
    'Windows Time service':'Mocked stopped service does not falsely establish independent NTP failure; no service continuity proof.',
    'Producer fresh clock gate':'Missing, malformed, stale and excessive-uncertainty clock samples fail closed; no live offset measured.',
    '14 October historical read-only audit':'CLI read-only mode neither saves reports nor alerts on synthetic state; does not examine14Oct data.',
    'Legacy audit result2 and shared-root writes':'No forensic result inspected; old exit code/shared-root attribution remains unknown.',
    'OPTION_CAPTURE_ENABLED skipped schedules':'No exact workflow variable/run-history diagnosis performed.',
    'Consistent-cut exports':'Fake database driver verifies query/transaction/cut contract; not a hosted export.',
    'Writer guards and cold readers':'Synthetic authenticated cold rows returned by selected real reader methods; not every live factory wired.',
    'Universe shadow deduplication':'Payload sharing preserves snapshot identities and exact originals; no hosted normalization.',
    'Bounded retention and deletion':'Each synthetic source round-trips exact bytes and retention gates; not real custody or deletion authority.',
    'Capacity guard across live writers':'Uncertain synthetic COMMIT requires reconciliation, not repeat; not global writer enforcement.',
    'Capacity alerts':'Synthetic trend warning is diagnostic, not write authorization or real alert delivery.',
    'ML backtesting and Evidence Assistant':'Synthetic source references cannot become measured reports; no real learned edge or LLM commission.',
    'Licensed frozen paper-first study':'Too little/single-class/missing-feature synthetic data fails before fitting; no real labels or licence approval.',
    'Pinned Python and PowerShell toolchain':'Actual explicit test interpreter bootstrap path checked without py fallback; not all future machines.',
    'Encrypted-disk 7-Zip tool':'No 7-Zip installation, native encryption or independent-disk restore proved.',
}


def selectors() -> tuple[str, ...]:
    return tuple(dict.fromkeys(s for concept, primary in TESTS.items()
                              for s in ((primary,) if primary else ()) + SUPPORTING.get(concept, ())))


def results(junit: Path) -> dict[str, Any]:
    """Owner-selected PUBLIC synthetic JUnit only; aggregate, no captured stdout."""
    with junit.open('rb') as stream:
        raw = stream.read(16*1024*1024+1)
    if len(raw) > 16*1024*1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('BOUNDED_PLAIN_JUNIT_REQUIRED')
    tree = ET.fromstring(raw)
    cases = list(tree.iter('testcase'))
    output: dict[str, Any] = {}
    for concept, selector in TESTS.items():
        selected = []
        subjects = ((selector,) if selector else ()) + SUPPORTING.get(concept, ())
        for c in cases:
            for subject in subjects:
                file, function = subject.split('::')
                module = file[:-3].replace('/', '.')
                if c.get('classname') == module and (c.get('name') == function or (c.get('name') or '').startswith(function+'[')):
                    selected.append(c)
                    break
        failed = sum(c.find('failure') is not None or c.find('error') is not None for c in selected)
        skipped = sum(c.find('skipped') is not None for c in selected)
        missing = []
        for subject in subjects:
            file, function = subject.split('::')
            module = file[:-3].replace('/', '.')
            if not any(c.get('classname') == module and
                       (c.get('name') == function or (c.get('name') or '').startswith(function+'[')) for c in selected):
                missing.append(subject)
        output[concept] = dict(selector=selector, passed=len(selected)-failed-skipped,
            failed=failed, skipped=skipped,
            supporting_selectors=SUPPORTING.get(concept, ()), what_this_tests=SCOPE[concept],
            does_not_prove='Live commissioning, custody, restore, licence or training approval; see scope limits.',
            selectors_not_found_in_report=missing,
            status='OWNER_OR_NATIVE_EVIDENCE_REQUIRED' if selector is None else
                   'NOT_RUN' if not selected else 'FAILED' if failed else 'PARTIAL_TEST_SELECTION' if missing else
                   'COMPONENT_CASES_PASSED' if len(selected)>skipped else 'SKIPPED_ONLY',
            commissioning_verified=False)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--junit', type=Path)
    args = parser.parse_args(argv)
    if args.junit is None:
        print(json.dumps(dict(status='SOURCE_SELECTORS_NOT_EXECUTION_PROOF', concepts=TESTS)))
        return 0
    try:
        print(json.dumps(dict(status='SYNTHETIC_JUNIT_PROJECTION_NOT_COMMISSIONING', concepts=results(args.junit))))
        return 0
    except Exception:
        print(json.dumps(dict(status='BLOCKED', code='PUBLIC_JUNIT_INVALID', raw_error_printed=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
