import datetime as dt
import ast
import hashlib
import inspect
import json
import copy
from pathlib import Path

import numpy as np
import pytest
import trade_contracts

from continuous_evolution import (
    _execution_outcome_ev,
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


def test_shared_ev_arithmetic_is_identical_to_pre_refactor_body():
    # Pin the AST of the original arithmetic, including its validation,
    # rounding, failures and result fields. Only the evidence validator moves.
    function = ast.parse(inspect.getsource(_execution_outcome_ev)).body[0]
    body = ast.Module(body=function.body[1:], type_ignores=[])
    digest = hashlib.sha256(ast.dump(body, include_attributes=False).encode()).hexdigest()
    assert digest == "3292adf9e0c30f88efda33704f07e32bfddfc224795e19d686c1f2287c19612e"


def test_non_equity_serialized_ev_result_is_unchanged():
    result = executable_fill_adjusted_ev(
        entry=100, stop=95, target=110, direction="long", quantity=2,
        round_trip_cost_bps=0, target_probability=.70, stop_probability=.20,
        time_exit_probability=.10, time_exit_return_per_unit=0,
        fill_evidence=fill_evidence(), adverse_selection_bps=5,
    )
    expected = {
        "status": "PASS", "expected_value_per_filled_unit": 5.95,
        "expected_value_per_order": 8.925,
        "expected_value_bps_per_order": 446.25000000000006,
        "conservative_fill_probability": .75, "non_fill_probability": .25,
        "outcome_probabilities": {"target": .7, "stop": .2, "time_exit": .1},
        "trade_math": {"gross_risk": 5.0, "gross_reward": 10.0,
                       "cost_per_unit": 0.0, "net_risk": 5.0, "net_reward": 10.0,
                       "net_ratio": 2.0, "minimum_ratio": 2.0, "passes_gate": True},
        "failures": [],
    }
    assert json.dumps(result, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.parametrize("change", [
    {}, {"target": 107}, {"target_probability": .1, "stop_probability": .8},
    {"direction": "short", "stop": 105, "target": 90},
    {"entry": None}, {"quantity": None}, {"round_trip_cost_bps": 14},
    {"time_exit_probability": None}, {"time_exit_return_per_unit": None},
    {"target_probability": .9}, {"adverse_selection_bps": None},
    {"fill_evidence": None}, {"fill_evidence": {}},
])
def test_non_equity_legacy_inline_path_matches_byte_for_byte(change):
    # Reconstitute the old inline function from the pinned original arithmetic.
    # The oracle does not call the extracted helper. The hash test above guards
    # against changing both paths together and accidentally blessing a regression.
    wrapper = ast.parse(inspect.getsource(executable_fill_adjusted_ev)).body[0]
    arithmetic = ast.parse(inspect.getsource(_execution_outcome_ev)).body[0]
    legacy = copy.deepcopy(wrapper)
    legacy.name = "legacy_inline_ev"
    legacy.body = legacy.body[:3] + copy.deepcopy(arithmetic.body[1:])
    namespace = dict(executable_fill_adjusted_ev.__globals__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[legacy], type_ignores=[])),
                 "<pinned-pre-refactor-ev>", "exec"), namespace)
    arguments = dict(
        entry=100, stop=95, target=110, direction="long", quantity=2,
        round_trip_cost_bps=0, target_probability=.7, stop_probability=.2,
        time_exit_probability=.1, time_exit_return_per_unit=0,
        fill_evidence=fill_evidence(), adverse_selection_bps=5,
    )
    arguments.update(change)
    before = namespace["legacy_inline_ev"](**arguments)
    after = executable_fill_adjusted_ev(**arguments)
    assert json.dumps(after, sort_keys=True).encode() == json.dumps(before, sort_keys=True).encode()


@pytest.mark.parametrize("missing", ["time_exit_probability", "time_exit_return_per_unit"])
def test_shared_ev_never_defaults_missing_outcomes(missing):
    arguments = dict(
        entry=100, stop=95, target=110, direction="long", quantity=1,
        round_trip_cost_bps=0, target_probability=.7, stop_probability=.2,
        time_exit_probability=.1, time_exit_return_per_unit=0,
        fill_evidence=fill_evidence(), minimum_ratio=1.30,
    )
    arguments[missing] = None
    result = executable_fill_adjusted_ev(**arguments)
    assert result["status"] == "ABSTAIN"
    assert result["expected_value_per_order"] is None


@pytest.mark.parametrize("evidence", [None, {},
    {"purpose": "RESEARCH_OBSERVATION"},
    {"purpose": "LIVE_EQUITY_MANUAL_QUOTE_CHECK", "confirmed": True}])
def test_equity_threshold_does_not_replace_missing_execution_evidence(evidence):
    result = executable_fill_adjusted_ev(
        entry=100, stop=95, target=110, direction="long", quantity=1,
        round_trip_cost_bps=0, target_probability=.7, stop_probability=.2,
        time_exit_probability=.1, time_exit_return_per_unit=0,
        fill_evidence=evidence, minimum_ratio=1.30,
    )
    assert result["status"] == "ABSTAIN"
    assert result["expected_value_per_order"] is None


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


@pytest.mark.parametrize("asset", ["equity", "options", "futures", "mcx", "equity_smc"])
def test_keyless_model_evaluation_is_equity_only_and_retains_other_gates(asset):
    kwargs = dict(weights={"baseline": 1}, selected_regime="TREND",
                  expected_feature_schema_hash=SCHEMA_HASH, decision_at=NOW, asset_class=asset)
    prediction = model(artifact_signature_valid=False, artifact_integrity_valid=True)
    result = evaluate_model_ensemble([prediction], **kwargs)
    assert result["status"] == ("PASS" if asset == "equity" else "ABSTAIN")
    for bad in (dict(prediction, artifact_integrity_valid=False),
                dict(prediction, feature_schema_hash="wrong"),
                dict(prediction, calibrated=False), dict(prediction, status="SHADOW")):
        assert evaluate_model_ensemble([bad], **kwargs)["status"] == "ABSTAIN"


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


@pytest.mark.parametrize("ratio,expected", [(1.299, "NO_TRADE"), (1.30, "PASS"), (1.301, "PASS")])
def test_equity_fill_ev_uses_unrounded_net_boundary(ratio, expected):
    # Synthetic fixture: net risk 5.14 and cost 0.14 at entry 100.
    result = executable_fill_adjusted_ev(
        entry=100, stop=95, target=100 + .14 + ratio * 5.14,
        direction="long", quantity=1, round_trip_cost_bps=14,
        target_probability=.7, stop_probability=.2, time_exit_probability=.1,
        time_exit_return_per_unit=0, fill_evidence=fill_evidence(),
        minimum_ratio=trade_contracts.EQUITY_MIN_NET_REWARD_RISK,
    )
    assert result["status"] == expected
    assert result["trade_math"]["minimum_ratio"] == 1.30
    assert result["expected_value_per_order"] > 0
    assert not any("EV is not positive" in reason for reason in result["failures"])


def test_default_fill_ev_keeps_two_and_reports_ratio_failure_separately():
    kwargs = dict(entry=100, stop=95, target=107, direction="long", quantity=1,
                  round_trip_cost_bps=0, target_probability=.7, stop_probability=.2,
                  time_exit_probability=.1, time_exit_return_per_unit=0,
                  fill_evidence=fill_evidence())
    default = executable_fill_adjusted_ev(**kwargs)
    equity = executable_fill_adjusted_ev(**kwargs, minimum_ratio=1.30)
    assert default["status"] == "NO_TRADE"
    assert default["failures"] == ["Net reward/risk 1.40 is below the 2.00 threshold"]
    assert equity["status"] == "PASS"
    assert default["expected_value_per_order"] == equity["expected_value_per_order"]
    negative = executable_fill_adjusted_ev(
        **{**kwargs, "target_probability": .1, "stop_probability": .8}, minimum_ratio=1.30)
    assert negative["status"] == "NO_TRADE"
    assert negative["failures"] == ["Fill-adjusted executable EV is not positive"]


def test_simple_ev_equity_override_preserves_shared_default():
    from quant_foundation import executable_expected_value
    kwargs = dict(entry=100, stop=95, target=107, round_trip_cost_bps=0,
                  calibration_evidence=calibration())
    default = executable_expected_value(**kwargs)
    equity = executable_expected_value(**kwargs, minimum_ratio=1.30)
    assert default["status"] == "NO_TRADE"
    assert default["trade_math"]["minimum_ratio"] == 2.00
    assert equity["status"] == "PASS"
    assert equity["trade_math"]["minimum_ratio"] == 1.30


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
    root = Path(__file__).resolve().parents[1]
    governance_source = (root / "live_governance.py").read_text(encoding="utf-8")
    controls_source = (root / "continuous_evolution.py").read_text(encoding="utf-8")
    assert 'portfolio = {"status": "UNAVAILABLE"' in governance_source
    assert '"Validated calibration and fill-model evidence are required"' in governance_source
    assert '("execution", execution, "PASS"), ("expected_value", expected_value, "PASS")' in controls_source
    assert '("portfolio", portfolio, "PASS"), ("allocation", allocation, "PASS")' in controls_source
    assert "if status != expected:" in controls_source
    assert '"available_at": decision_at' not in governance_source
