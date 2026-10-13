"""Read-only in-app research orchestration; no live data, schedules or model fitting."""
from __future__ import annotations

from typing import Any

from overnight_research_runner import offline_boundary, synthetic_self_check
from research_lab_grounding import grounded_explanation


def readiness() -> dict[str, object]:
    """Unknown evidence remains unknown, not zero or an invented measured count."""
    return {'status': 'INSUFFICIENT_EVIDENCE', 'verified_sessions': None,
        'verified_executable_labels': None, 'approval_authority': False, 'training_eligible': False,
        'orders_enabled': False, 'scheduled_research_enabled': False,
        'requirements': [
            'Independent custody and successful restore of admitted source bytes',
            'Explicit source rights for intended ML and paper use',
            'Version-as-of receipt replay and verified prospective outcome labels',
            'Dated NIFTY contract, calendar, expiry, lot, tariff and broker margin references',
            'Executable quotes/depth and pre-registered fill/slippage/stop assumptions',
            'Frozen session-level study, adequate out-of-sample sessions and all-trial ledger',
            'Independent review and forward paper evidence before any decision influence'],
        'llm': grounded_explanation()}


@offline_boundary()
def plumbing_demo() -> dict[str, Any]:
    """Execute existing generated fixture with whole-session folds; no real inputs."""
    result = synthetic_self_check(session_groups=True)
    # Keep only fixed, locally generated fields. Do not import arbitrary reports.
    return {'status': 'SYNTHETIC_PLUMBING_ONLY', 'real_data_reads': 0,
        'dataset_sha256': result['dataset_manifest']['manifest_sha256'],
        'rows': result['dataset_manifest']['row_count'],
        'ml_status': result['ml_result']['status'], 'ml_reasons': result['ml_result']['reasons'],
        'scenario_status': result['scenario_summary']['status'],
        'paper_status': result['paper_gate']['status'], 'trials': len(result['trials']),
        'approval_authority': False, 'training_eligible': False, 'fill_evidence': False}
