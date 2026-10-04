import datetime as dt
import json
import logging

from live_evidence import unavailable_bundle
from live_governance import GovernanceServices, evaluate_live_governance, _backlog_diagnostic
from resilience_control_plane import ResilienceControlPlane


def test_backlog_logs_exact_evaluation_and_not_private_payload(caplog):
    class Ledger:
        def outbox_stats(self):
            return {"pending": 161, "oldest_pending_seconds": 37.8, "maximum_attempts": 0,
                    "private": "NEVER_LOG_THIS_TOKEN"}
    class Metrics:
        def record(self, *args, **kwargs):
            pass
    bundle = unavailable_bundle(strategy_id="test", asset_class="equity", target_version="v1",
        horizon_sessions=15, instrument="DIVISLAB", decision_at=dt.datetime.now(dt.timezone.utc))
    with caplog.at_level(logging.INFO):
        result = evaluate_live_governance(instrument="DIVISLAB", entry=100, stop=95, target=108,
            evidence=bundle, services=GovernanceServices(control_plane=ResilienceControlPlane(),
                evidence_ledger=Ledger(), observability=Metrics(), app_build="fixture"))
    record = next(r.message for r in caplog.records if r.message.startswith("EQUITY_GOVERNANCE_BACKLOG "))
    diagnostic = json.loads(record.split(" ", 1)[1])
    assert diagnostic["pending"] == 161
    assert diagnostic["oldest_pending_seconds"] == 37.8
    assert diagnostic["backlog_finding_present"] is True
    assert any(f["code"] == "OUTBOX_BACKLOG" for f in diagnostic["current_findings"])
    assert "NEVER_LOG_THIS_TOKEN" not in caplog.text
    assert result["allow_trade"] is False


def test_hysteresis_is_not_mislabeled_as_current_backlog():
    plane = ResilienceControlPlane()
    initial = plane.state_machine.evaluate(plane.operations.outbox({"pending": 161}))
    assert initial.state.name == "READ_ONLY"
    lower = plane.state_machine.evaluate([]).public_dict()
    report = _backlog_diagnostic({"pending": 0, "oldest_pending_seconds": 0}, lower, plane.policy)
    assert report["state"] == "READ_ONLY"
    assert report["backlog_finding_present"] is False
    assert report["maximum_recorded_failures"] is None
    assert report["clean_windows"] == 1


def test_invalid_or_missing_numbers_are_not_manufactured():
    plane = ResilienceControlPlane()
    state = plane.state_machine.evaluate([]).public_dict()
    report = _backlog_diagnostic({"pending": float("nan"), "oldest_pending_seconds": "password"}, state, plane.policy)
    assert report["pending"] is report["oldest_pending_seconds"] is None
    assert "password" not in json.dumps(report, allow_nan=False)
