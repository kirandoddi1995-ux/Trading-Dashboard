"""Credential-free acceptance and game-day checks for the resilience plane."""

from __future__ import annotations

import argparse
import datetime as dt
import json

from resilience_control_plane import (
    ModelPromotionGate,
    OperationalGuard,
    QuoteObservation,
    ReleaseDecision,
    ResilienceControlPlane,
    ResiliencePolicy,
    RetentionAuditGuard,
    SafetyFinding,
    SafetyState,
    SafetyStateMachine,
    UTC,
)
from continuous_evolution import (
    evaluate_model_ensemble,
    predictive_correctness_claim,
    unified_control_findings,
)


def run_acceptance(*, game_day=False):
    policy = ResiliencePolicy.load()
    now = dt.datetime.now(UTC)
    checks = {}

    fresh_plane = ResilienceControlPlane(policy)
    fresh = fresh_plane.evaluate_recommendation(
        price=100, quote_at=now, received_at=now, provider_available=True,
        exchange_open=True, quote_age_seconds=0, outbox_stats={"pending": 0, "oldest_pending_seconds": 0},
    )
    checks["fresh_quote_allows_trade"] = fresh.allow_new_trades
    checks["unconfigured_secondary_visible"] = any(
        item.code == "SECONDARY_UNAVAILABLE" for item in fresh.findings
    )

    stale_plane = ResilienceControlPlane(policy)
    stale = stale_plane.evaluate_recommendation(
        price=100, quote_at=now, received_at=now, provider_available=True,
        exchange_open=True, quote_age_seconds=60,
    )
    checks["stale_quote_no_trade"] = stale.state == SafetyState.NO_TRADE

    invalid_plane = ResilienceControlPlane(policy)
    invalid = invalid_plane.evaluate_recommendation(
        price=float("nan"), quote_at=now, received_at=now, provider_available=True,
        exchange_open=True, quote_age_seconds=float("nan"),
    )
    checks["nan_fails_closed"] = invalid.state == SafetyState.NO_TRADE

    machine = SafetyStateMachine(policy)
    emergency = machine.evaluate([
        SafetyFinding("configuration", "SIGNATURE_INVALID", "test", SafetyState.EMERGENCY_STOP)
    ])
    for _ in range(5):
        still_locked = machine.evaluate([], authorized_recovery=False)
    checks["emergency_requires_authorization"] = (
        emergency.state == SafetyState.EMERGENCY_STOP
        and still_locked.state == SafetyState.EMERGENCY_STOP
    )
    for _ in range(int(policy.section("state_machine")["clean_windows_to_recover"])):
        recovered = machine.evaluate([], authorized_recovery=True)
    checks["authorized_hysteretic_recovery"] = recovered.state == SafetyState.NORMAL

    outbox = OperationalGuard(policy).outbox({"pending": 101, "oldest_pending_seconds": 901})
    checks["outbox_backlog_read_only"] = max(item.state for item in outbox) == SafetyState.READ_ONLY

    rollback = ReleaseDecision.evaluate(
        canary_samples=[{"ok": True, "latency_ms": 100}] * 4 + [{"ok": False, "latency_ms": 100}],
        previous_release="v21.2", candidate_release="v22.0",
    )
    checks["failed_canary_rolls_back"] = rollback.get("action") == "ROLLBACK"

    gate = ModelPromotionGate()
    rejected = gate.evaluate({"oos_samples": 100, "regimes_tested": 1})
    approved = gate.evaluate({
        "artifact_signature_valid": True, "point_in_time_verified": True,
        "untouched_holdout": True, "costs_applied": True,
        "rollback_model_available": True, "independent_approval": True,
        "oos_samples": 750, "regimes_tested": 4,
    })
    checks["promotion_fails_closed"] = not rejected["promotion_allowed"]
    checks["promotion_attested"] = approved["promotion_allowed"] and bool(approved.get("attestation_hash"))

    retention = RetentionAuditGuard(policy).evaluate(
        evidence_retention_days=2555, log_retention_days=90,
        personal_data_retention_days=30, ledger_verified=True,
    )
    checks["retention_policy_valid"] = not retention

    model = evaluate_model_ensemble(
        [], weights={}, selected_regime="UNKNOWN", expected_feature_schema_hash="schema",
        decision_at=now,
    )
    checks["missing_model_abstains"] = model["status"] == "ABSTAIN" and model["probability"] is None
    claim = predictive_correctness_claim({
        "matured_actionable": 999, "correct_predictions": 999,
        "candidate_count": 999, "evaluated_count": 10_000,
    })
    checks["unsupported_99pct_claim_blocked"] = claim["claim"] == "99% not established"
    quantitative_findings = unified_control_findings(
        pit={"status": "PASS"}, model=model, calibration={"status": "PASS"},
        conformal={"status": "PASS"}, execution={"status": "PASS"},
        expected_value={"status": "PASS"}, portfolio={"status": "PASS"},
        allocation={"status": "PASS"}, kill_switch={"status": "PASS"},
    )
    quantitative_snapshot = ResilienceControlPlane(policy).evaluate_recommendation(
        price=100, quote_at=now, provider_available=True, exchange_open=True,
        calibration_evidence=None, control_findings=quantitative_findings,
    )
    checks["quantitative_abstention_drives_no_trade"] = quantitative_snapshot.state == SafetyState.NO_TRADE

    if game_day:
        scenarios = {
            "provider_outage": dict(price=100, quote_at=now, provider_available=False, exchange_open=True),
            "clock_skew": dict(price=100, quote_at=now, provider_available=True, exchange_open=True,
                               ntp_offset_seconds=5),
            "outbox_loss_risk": dict(price=100, quote_at=now, provider_available=True, exchange_open=True,
                                     outbox_stats={"pending": 1000, "oldest_pending_seconds": 3600}),
        }
        for name, kwargs in scenarios.items():
            snapshot = ResilienceControlPlane(policy).evaluate_recommendation(**kwargs)
            expected = SafetyState.READ_ONLY if name == "outbox_loss_risk" else SafetyState.NO_TRADE
            checks[f"game_day:{name}"] = snapshot.state == expected

    return {"ok": all(checks.values()), "policy_version": policy.version,
            "policy_hash": policy.digest, "checks": checks}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--game-day", action="store_true")
    args = parser.parse_args(argv)
    result = run_acceptance(game_day=args.game_day)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
