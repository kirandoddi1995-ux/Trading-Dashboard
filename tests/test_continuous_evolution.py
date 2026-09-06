import datetime as dt
from pathlib import Path

import numpy as np

from continuous_evolution import (
    adaptive_conformal_interval,
    decision_evidence_bundle,
    evaluate_model_ensemble,
    executable_fill_adjusted_ev,
    predictive_correctness_claim,
    unified_control_findings,
    validate_calibration_package,
    validate_fill_model,
)
from resilience_control_plane import ResilienceControlPlane, ResiliencePolicy, SafetyState


NOW = dt.datetime.now(dt.timezone.utc)
SCHEMA_HASH = "f" * 64


def model(model_id="baseline", family="logistic", probability=.72, **overrides):
    row = {
        "model_id": model_id, "model_family": family, "probability": probability,
        "role": "CHAMPION", "status": "ACTIVE", "deployment_mode": "PRODUCTION",
        "promotion_attested": True, "artifact_signature_valid": True, "calibrated": True,
        "feature_schema_hash": SCHEMA_HASH, "regime": "TREND", "version": "m1",
        "artifact_hash": "a" * 64, "feature_at": (NOW - dt.timedelta(seconds=1)).isoformat(),
        "inference_at": NOW.isoformat(), "maximum_feature_age_seconds": 5,
    }
    row.update(overrides)
    return row


def calibration(ensemble_hash="ensemble"):
    return {
        "status": "VALIDATED", "probability": .72,
        "probability_interval_low": .66, "probability_interval_high": .77,
        "oos_samples": 1200, "positive_samples": 600, "negative_samples": 600,
        "observation_days": 300, "ece": .03, "brier": .17, "baseline_brier": .25,
        "log_loss": .52, "baseline_log_loss": .69, "log_loss_skill": .246,
        "log_loss_improvement_ci_low": .03,
        "model_version": "m1", "ensemble_hash": ensemble_hash,
        "validated_at": (NOW - dt.timedelta(days=1)).isoformat(),
        "valid_until": (NOW + dt.timedelta(days=20)).isoformat(),
        "feature_psi": .05, "calibration_decay": .01,
        "nested_chronological": True, "untouched_holdout": True,
        "pit_verified": True, "costs_applied": True,
        "reliability": [{"count": 100, "predicted": .7, "actual": .69}],
    }


def fill_evidence():
    return {
        "fill_probability": .85, "fill_probability_low": .75,
        "oos_samples": 1000, "brier": .15, "ece": .04,
        "chronological_oos": True, "partial_fills_modelled": True,
        "model_version": "fill-v1",
    }


def test_shadow_specialists_cannot_influence_live_probability_without_promotion():
    deep = model("deep", "deep_order_book", .99, deployment_mode="SHADOW", promotion_attested=False)
    result = evaluate_model_ensemble(
        [model(), deep], weights={"baseline": 1.0, "deep": 999.0},
        selected_regime="TREND", expected_feature_schema_hash=SCHEMA_HASH, decision_at=NOW,
    )
    assert result["status"] == "PASS"
    assert result["probability"] == .72
    assert result["shadow_models"] == ["deep"]


def test_feature_schema_or_inference_chronology_mismatch_abstains():
    bad = model(feature_schema_hash="wrong", inference_at=(NOW + dt.timedelta(seconds=1)).isoformat())
    result = evaluate_model_ensemble(
        [bad], weights={"baseline": 1}, selected_regime="TREND",
        expected_feature_schema_hash=SCHEMA_HASH, decision_at=NOW,
    )
    assert result["status"] == "ABSTAIN"
    assert result["probability"] is None


def test_model_disagreement_abstains_even_when_models_are_individually_valid():
    result = evaluate_model_ensemble(
        [model(probability=.60), model("boost", "boosted", .80)],
        weights={"baseline": .5, "boost": .5}, selected_regime="TREND",
        expected_feature_schema_hash=SCHEMA_HASH, decision_at=NOW,
    )
    assert result["status"] == "ABSTAIN"
    assert any("disagreement" in failure for failure in result["failures"])


def test_calibration_requires_nested_holdout_reliability_and_ensemble_lineage():
    good = calibration("correct")
    assert validate_calibration_package(good, expected_ensemble_hash="correct")["status"] == "PASS"
    bad = dict(good, nested_chronological=False, ensemble_hash="wrong", log_loss=float("nan"))
    result = validate_calibration_package(bad, expected_ensemble_hash="correct")
    assert result["status"] == "ABSTAIN" and len(result["failures"]) >= 3


def test_near_coin_flip_log_loss_cannot_pass_on_a_tiny_improvement():
    weak = dict(
        calibration("correct"),
        log_loss=.688,
        baseline_log_loss=.690,
        log_loss_skill=(.690 - .688) / .690,
        log_loss_improvement_ci_low=-.004,
    )
    result = validate_calibration_package(weak, expected_ensemble_hash="correct")
    assert result["status"] == "ABSTAIN"
    assert any("log-loss" in failure.casefold() for failure in result["failures"])


def test_adaptive_conformal_interval_requires_disjoint_chronology_and_coverage():
    residuals = np.linspace(-.1, .1, 600)
    good = adaptive_conformal_interval(
        .02, residuals, training_end="2026-01-01T00:00:00Z",
        calibration_start="2026-01-02T00:00:00Z", calibration_end="2026-05-01T00:00:00Z",
        observed_coverage=.91,
    )
    assert good["status"] == "PASS" and good["lower"] <= .02 <= good["upper"]
    overlap = adaptive_conformal_interval(
        .02, residuals, training_end="2026-01-03T00:00:00Z",
        calibration_start="2026-01-02T00:00:00Z", calibration_end="2026-05-01T00:00:00Z",
        observed_coverage=.80,
    )
    assert overlap["status"] == "ABSTAIN" and len(overlap["failures"]) == 2


def test_fill_model_is_fail_closed_for_non_finite_or_unmodelled_partial_fills():
    assert validate_fill_model(fill_evidence())["status"] == "PASS"
    bad = dict(fill_evidence(), fill_probability=float("nan"), partial_fills_modelled=False)
    assert validate_fill_model(bad)["status"] == "ABSTAIN"


def test_fill_adjusted_ev_prices_target_stop_time_exit_and_nonfill():
    result = executable_fill_adjusted_ev(
        entry=100, stop=95, target=110, direction="long", quantity=2,
        round_trip_cost_bps=0, target_probability=.70, stop_probability=.20,
        time_exit_probability=.10, time_exit_return_per_unit=0,
        fill_evidence=fill_evidence(), adverse_selection_bps=5,
    )
    assert result["status"] == "PASS"
    assert result["expected_value_per_order"] > 0
    assert result["non_fill_probability"] == .25


def test_outcome_probabilities_must_sum_to_one():
    result = executable_fill_adjusted_ev(
        entry=100, stop=95, target=110, direction="long", quantity=1,
        round_trip_cost_bps=0, target_probability=.8, stop_probability=.4,
        time_exit_probability=.1, time_exit_return_per_unit=0, fill_evidence=fill_evidence(),
    )
    assert result["status"] == "ABSTAIN"


def test_99_percent_claim_is_blocked_until_sample_coverage_and_wilson_gate_pass():
    insufficient = predictive_correctness_claim({
        "matured_actionable": 129, "correct_predictions": 129,
        "candidate_count": 129, "evaluated_count": 10000,
    })
    assert insufficient["claim"] == "99% not established"
    established = predictive_correctness_claim({
        "matured_actionable": 1000, "correct_predictions": 1000,
        "candidate_count": 1000, "evaluated_count": 10000,
        "regime_samples": {"TREND": 400, "RANGE": 300, "STRESS": 300},
        "untouched_chronological_holdout": True, "pit_verified": True,
        "executable_prices": True, "full_costs_applied": True, "ledger_verified": True,
    })
    assert established["established"] is True
    assert established["wilson_95"]["lower"] >= .99


def test_unified_findings_drive_no_trade_read_only_and_emergency_stop():
    passed = {"status": "PASS"}
    findings = unified_control_findings(
        pit=passed, model={"status": "ABSTAIN", "failures": ["model drift"]},
        calibration=passed, conformal=passed, execution=passed, expected_value=passed,
        portfolio=passed, allocation=passed, kill_switch=passed,
        ledger_status={"chain_valid": False, "append_durable": False, "signature_valid": True},
    )
    snapshot = ResilienceControlPlane(ResiliencePolicy.load()).evaluate_recommendation(
        price=100, quote_at=NOW, quote_age_seconds=0, provider_available=True,
        exchange_open=True, calibration_evidence=calibration(), control_findings=findings,
    )
    assert snapshot.state == SafetyState.READ_ONLY
    emergency = unified_control_findings(
        pit=passed, model=passed, calibration=passed, conformal=passed, execution=passed,
        expected_value=passed, portfolio=passed, allocation=passed, kill_switch=passed,
        ledger_status={"chain_valid": True, "append_durable": True, "signature_valid": False},
    )
    assert max(item.state for item in emergency) == SafetyState.EMERGENCY_STOP


def test_decision_bundle_is_stable_and_excludes_raw_features():
    safety = {"state": "NO_TRADE", "correlation_id": "cid"}
    kwargs = dict(
        instrument="NSE_EQ|A", decision_at=NOW, pit={"status": "PASS"},
        model={"status": "PASS", "ensemble_hash": "h"},
        calibration={"status": "PASS", "model_version": "m1"}, conformal={"status": "PASS"},
        execution={"status": "PASS"}, expected_value={"status": "PASS"},
        portfolio={"status": "PASS"}, allocation={"status": "PASS"},
        kill_switch={"status": "PASS"},
        safety=safety, claim={"claim": "99% not established"},
    )
    first = decision_evidence_bundle(**kwargs)
    second = decision_evidence_bundle(**kwargs)
    assert first == second and "features" not in first


def test_live_source_blocks_unavailable_ev_and_portfolio():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'expected_value["status"] != "PASS"' in source
    assert 'portfolio["status"] != "PASS"' in source
    assert '"available_at": decision_at' not in source
