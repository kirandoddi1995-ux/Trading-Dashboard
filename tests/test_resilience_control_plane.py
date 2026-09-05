import datetime as dt
import json
import sqlite3
import threading

import pytest

from evidence_ledger import ImmutableEvidenceLedger
from model_registry import ModelRegistry
from resilience_acceptance import run_acceptance
from resilience_control_plane import (
    CalibrationDriftMonitor,
    ExecutionSurveillance,
    MarketDataSupervisor,
    ModelPromotionGate,
    OperationalGuard,
    QuoteObservation,
    ReleaseDecision,
    ResilienceControlPlane,
    ResiliencePolicy,
    RetentionAuditGuard,
    RuntimeAttestor,
    SLOMonitor,
    SafetyFinding,
    SafetyState,
    SafetyStateMachine,
    SecretLifecycleMonitor,
    UTC,
)
from scheduled_collector import CollectorLease


NOW = dt.datetime(2026, 9, 5, 5, 0, tzinfo=UTC)


def policy():
    return ResiliencePolicy.load()


def test_policy_checksum_and_acceptance_suite_pass():
    result = run_acceptance(game_day=True)
    assert result["ok"] is True
    assert all(result["checks"].values())


def test_tampered_policy_is_rejected(tmp_path):
    path = tmp_path / "resilience_policy.json"
    path.write_text(json.dumps(policy().raw), encoding="utf-8")
    path.with_suffix(".sha256").write_text("0" * 64, encoding="ascii")
    with pytest.raises(ValueError, match="checksum"):
        ResiliencePolicy.load(path)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "bad"])
def test_bad_quote_age_fails_closed(bad):
    snapshot = ResilienceControlPlane(policy()).evaluate_recommendation(
        price=100, quote_at=NOW, quote_age_seconds=bad,
        provider_available=True, exchange_open=True,
    )
    assert snapshot.state >= SafetyState.NO_TRADE


def test_stale_and_future_quotes_are_rejected():
    supervisor = MarketDataSupervisor(policy())
    stale = QuoteObservation(100, NOW - dt.timedelta(seconds=10), NOW, "primary")
    future = QuoteObservation(100, NOW + dt.timedelta(seconds=3), NOW, "primary")
    assert any(item.code == "STALE_QUOTE" for item in supervisor.evaluate(stale, now=NOW))
    assert any(item.code == "FUTURE_QUOTE" for item in supervisor.evaluate(future, now=NOW))


def test_crossed_book_and_provider_divergence_are_rejected():
    supervisor = MarketDataSupervisor(policy())
    crossed = QuoteObservation(100, NOW, NOW, "primary", bid=101, ask=99)
    assert any(item.code == "INVALID_BOOK" for item in supervisor.evaluate(crossed, now=NOW))
    primary = QuoteObservation(100, NOW, NOW, "primary")
    secondary = QuoteObservation(101, NOW, NOW, "secondary")
    assert any(item.code == "QUOTE_DIVERGENCE" for item in supervisor.evaluate(primary, secondary=secondary, now=NOW))


def test_emergency_stop_cannot_self_clear():
    machine = SafetyStateMachine(policy())
    machine.evaluate([SafetyFinding("secret", "LEAK", "test", SafetyState.EMERGENCY_STOP)])
    for _ in range(10):
        result = machine.evaluate([])
    assert result.state == SafetyState.EMERGENCY_STOP
    for _ in range(3):
        result = machine.evaluate([], authorized_recovery=True)
    assert result.state == SafetyState.NORMAL


def test_read_only_preserves_exit_and_audit_access():
    machine = SafetyStateMachine(policy())
    result = machine.evaluate([SafetyFinding("ledger", "CHAIN", "test", SafetyState.READ_ONLY)])
    assert not result.allow_new_trades
    assert not result.allow_writes
    assert result.allow_exits and result.allow_audit_reads


def test_calibration_nan_and_consecutive_drift_abstain():
    monitor = CalibrationDriftMonitor(policy())
    evidence = {
        "oos_samples": 1000, "brier": float("nan"), "ece": 0.01, "log_loss": 0.5,
        "validated_at": NOW, "brier_deterioration": 0,
    }
    first = monitor.evaluate(evidence, now=NOW)
    second = monitor.evaluate(evidence, now=NOW)
    assert first[0].state == SafetyState.DEGRADED
    assert second[0].state == SafetyState.NO_TRADE


def test_execution_state_machine_blocks_overfill_and_terminal_mutation():
    surveillance = ExecutionSurveillance(policy())
    overfill = surveillance.evaluate(
        previous_status="ACKNOWLEDGED", status="FILLED",
        ordered_quantity=10, cumulative_quantity=11,
    )
    mutation = surveillance.evaluate(
        previous_status="FILLED", status="CANCELLED",
        ordered_quantity=10, cumulative_quantity=10,
    )
    assert any(item.state == SafetyState.READ_ONLY for item in overfill)
    assert any(item.code == "INVALID_TRANSITION" for item in mutation)


def test_outbox_backlog_forces_read_only():
    findings = OperationalGuard(policy()).outbox({"pending": 101, "oldest_pending_seconds": 0})
    assert findings[0].state == SafetyState.READ_ONLY


def test_outbox_stats_report_age_without_payload(tmp_path):
    db = tmp_path / "ledger.sqlite"
    ledger = ImmutableEvidenceLedger(sqlite3.connect, str(db))
    event = ledger.append(
        aggregate_id="signal-1", event_type="SIGNAL_CREATED", payload={"entry": 100},
        idempotency_key="outbox-test",
    )
    ledger.queue_delivery(event, "offline")
    stats = ledger.outbox_stats(now=dt.datetime.now(UTC) + dt.timedelta(minutes=2))
    assert stats["pending"] == 1
    assert stats["oldest_pending_seconds"] >= 119
    assert "event" not in stats and "payload" not in stats


def test_secret_value_exposure_emergency_stops():
    findings = SecretLifecycleMonitor(policy()).evaluate([{
        "name": "UPSTOX", "value": "forbidden", "rotated_at": NOW,
        "expires_at": NOW + dt.timedelta(days=10),
    }], now=NOW)
    assert findings[0].state == SafetyState.EMERGENCY_STOP


def test_runtime_signature_failure_emergency_stops():
    findings = RuntimeAttestor().evaluate(expected={"build": "a"}, actual={"build": "a"}, signature_valid=False)
    assert findings[0].state == SafetyState.EMERGENCY_STOP


def test_slo_fast_burn_blocks_new_trades():
    monitor = SLOMonitor(policy())
    for index in range(100):
        monitor.observe(latency_ms=100, ok=index >= 10, at=NOW)
    findings = monitor.evaluate(now=NOW)
    assert any(item.state == SafetyState.NO_TRADE for item in findings)


def test_failed_release_canary_selects_immutable_rollback_id():
    decision = ReleaseDecision.evaluate(
        canary_samples=[{"ok": True, "latency_ms": 100}] * 4 + [{"ok": False, "latency_ms": 100}],
        previous_release="release-a", candidate_release="release-b",
    )
    assert decision == {"action": "ROLLBACK", "reason": "failures=1, p95=100.0ms", "rollback_to": "release-a"}


def test_model_gate_requires_independent_approval_and_rollback():
    package = {
        "artifact_signature_valid": True, "point_in_time_verified": True,
        "untouched_holdout": True, "costs_applied": True,
        "rollback_model_available": True, "independent_approval": False,
        "oos_samples": 1000, "regimes_tested": 4,
    }
    result = ModelPromotionGate().evaluate(package)
    assert result["promotion_allowed"] is False
    assert "independent_approval" in result["failures"]


def test_model_registry_promotion_is_atomic_and_audited(tmp_path):
    path = str(tmp_path / "models.sqlite")
    registry = ModelRegistry(sqlite3.connect, path)
    registry.register("old", "logistic", "TREND", "1", "champion", {}, {}, status="ACTIVE")
    registry.register("new", "logistic", "TREND", "2", "challenger", {}, {}, status="CANARY")
    gate = ModelPromotionGate().evaluate({
        "artifact_signature_valid": True, "point_in_time_verified": True,
        "untouched_holdout": True, "costs_applied": True,
        "rollback_model_available": True, "independent_approval": True,
        "oos_samples": 800, "regimes_tested": 4,
    })
    result = registry.promote("new", gate, approved_by="risk-owner")
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT role,status FROM model_registry WHERE model_id='new'").fetchone() == ("champion", "ACTIVE")
        assert conn.execute("SELECT role,status FROM model_registry WHERE model_id='old'").fetchone() == ("challenger", "ROLLBACK")
        assert conn.execute("SELECT COUNT(*) FROM model_promotions").fetchone()[0] == 1
    finally:
        conn.close()
    assert result["previous_model_id"] == "old"


class FakeLeaseRepository:
    def __init__(self):
        self.active = False
        self.token = 0

    def acquire_collector_lease(self, name, owner, ttl_seconds):
        if self.active:
            return None
        self.active = True
        self.token += 1
        return {"fencing_token": self.token}

    def renew_collector_lease(self, *args, **kwargs):
        return self.active

    def release_collector_lease(self, *args, **kwargs):
        self.active = False
        return True


def test_collector_lease_allows_only_one_active_owner():
    repo = FakeLeaseRepository()
    first = CollectorLease(repo, ttl_seconds=30)
    first.__enter__()
    try:
        with pytest.raises(RuntimeError, match="Another"):
            CollectorLease(repo, ttl_seconds=30).__enter__()
    finally:
        first.__exit__(None, None, None)


def test_retention_drift_forces_read_only():
    findings = RetentionAuditGuard(policy()).evaluate(
        evidence_retention_days=30, log_retention_days=90,
        personal_data_retention_days=30, ledger_verified=True,
    )
    assert findings[0].state == SafetyState.READ_ONLY


def test_operational_controls_share_the_same_state_machine():
    plane = ResilienceControlPlane(policy())
    result = plane.evaluate_operations(secret_records=[{
        "name": "ledger-key", "secret": "must-not-be-here",
        "rotated_at": NOW, "expires_at": NOW + dt.timedelta(days=30),
    }])
    assert result.state == SafetyState.EMERGENCY_STOP
    assert result.allow_exits and result.allow_audit_reads
