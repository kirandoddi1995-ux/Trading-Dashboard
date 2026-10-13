"""The application cannot turn a synthetic self-check into market evidence."""
import json

from research_lab import plumbing_demo, readiness


def test_readiness_is_unknown_and_inactive() -> None:
    result = readiness()
    assert result['status'] == 'INSUFFICIENT_EVIDENCE'
    assert result['verified_sessions'] is None and result['verified_executable_labels'] is None
    assert result['orders_enabled'] is result['training_eligible'] is result['approval_authority'] is False
    assert 'API_KEY' not in json.dumps(result)


def test_demo_keeps_one_session_insufficient() -> None:
    result = plumbing_demo()
    assert result['status'] == 'SYNTHETIC_PLUMBING_ONLY'
    assert result['rows'] == 6 and result['trials'] == 1
    assert result['ml_status'] == 'INSUFFICIENT_DATA'
    assert result['real_data_reads'] == 0
    assert result['approval_authority'] is result['fill_evidence'] is result['training_eligible'] is False
