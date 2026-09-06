import ast
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from event_backtest import run_long_bracket_backtest
from model_training_pipeline import ConvexProbabilityStacker
from prediction_validation import calibration_metrics, paired_log_loss_improvement
from quant_foundation import fractional_kelly_weight
from track_record import build_complete_track_record
from volatility_models import GarchPolicy, fit_student_t_garch11


ROOT = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc


def _calibration(probability=.60):
    now = dt.datetime.now(UTC)
    return {
        "status": "VALIDATED", "probability": probability,
        "probability_interval_low": probability, "probability_interval_high": .75,
        "oos_samples": 1000, "positive_samples": 500, "negative_samples": 500,
        "observation_days": 200, "ece": .02, "brier": .18,
        "baseline_brier": .25, "model_version": "m1",
        "validated_at": (now - dt.timedelta(days=1)).isoformat(),
        "valid_until": (now + dt.timedelta(days=10)).isoformat(),
        "feature_psi": .01, "calibration_decay": .01,
    }


def test_canonical_kelly_matches_standard_derivation_and_is_the_only_definition():
    result = fractional_kelly_weight(.60, 2.0, calibration_evidence=_calibration())
    assert result["full_kelly"] == pytest.approx(.60 - .40 / 2.0)
    assert result["weight"] == pytest.approx(.10)

    violations = []
    for path in ROOT.glob("*.py"):
        if path.name == "quant_foundation.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "kelly" in node.name.casefold():
                violations.append(f"{path.name}:{node.lineno}: parallel Kelly function")
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [target.id for target in targets if isinstance(target, ast.Name)]
                value = node.value
                if any("kelly" in name.casefold() for name in names) and isinstance(value, ast.BinOp):
                    violations.append(f"{path.name}:{node.lineno}: inline Kelly arithmetic")
    assert violations == []
    assert "fractional_kelly_weight(" in (ROOT / "live_governance.py").read_text(encoding="utf-8")
    assert "fractional_kelly_weight(" not in (ROOT / "app.py").read_text(encoding="utf-8")


def test_event_backtest_never_fills_on_signal_event_and_uses_stop_first():
    index = pd.date_range("2026-01-05", periods=4, freq="B", tz="Asia/Kolkata")
    bars = pd.DataFrame({
        "Open": [100, 100, 100, 100],
        "High": [102, 111, 102, 102],
        "Low": [99, 94, 99, 99],
        "Close": [101, 100, 101, 101],
    }, index=index)

    result = run_long_bracket_backtest(
        bars,
        signal=lambda history: len(history) == 1,
        levels=lambda history, entry, hold: (95.0, 110.0),
        maximum_holding_bars=3,
        round_trip_cost_bps=30,
    )

    assert result["status"] == "PASS" and result["trade_count"] == 1
    trade = result["trades"][0]
    assert trade["outcome"] == "STOP"
    assert trade["net_return"] == pytest.approx(-.053)
    submitted = next(row for row in result["events"] if row["kind"] == "ORDER_SUBMITTED")
    filled = next(row for row in result["events"] if row["kind"] == "ORDER_FILLED")
    assert pd.Timestamp(filled["available_at"]) > pd.Timestamp(submitted["available_at"])


def test_event_backtest_rejects_naive_timestamps():
    bars = pd.DataFrame(
        {"Open": [1], "High": [1], "Low": [1], "Close": [1]},
        index=pd.DatetimeIndex(["2026-01-01"]),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        run_long_bracket_backtest(
            bars, signal=lambda history: False, levels=lambda history, entry, hold: None,
            maximum_holding_bars=1, round_trip_cost_bps=0,
        )


def test_student_t_garch_is_real_fitted_shadow_evidence_not_a_constant_fallback():
    rng = np.random.default_rng(1729)
    count = 700
    variance = np.empty(count)
    shocks = np.empty(count)
    variance[0] = .0001
    shocks[0] = rng.normal(scale=np.sqrt(variance[0]))
    for index in range(1, count):
        variance[index] = 0.000005 + .08 * shocks[index - 1] ** 2 + .87 * variance[index - 1]
        shocks[index] = rng.standard_t(8) * np.sqrt(variance[index] * 6 / 8)

    result = fit_student_t_garch11(
        shocks,
        observed_through="2026-09-05T10:00:00Z",
        available_at="2026-09-05T10:05:00Z",
        forecast_horizon=5,
        policy=GarchPolicy(minimum_observations=250),
    )

    assert result["status"] in {"PASS", "ABSTAIN"}
    assert result["production_score_eligible"] is False
    assert len(result["variance_forecast"]) == 5
    assert all(np.isfinite(result["variance_forecast"]))
    assert 0 <= result["parameters"]["persistence"] < 0.999


def test_log_loss_gate_uses_relative_skill_and_paired_confidence():
    outcomes = np.asarray([0, 1] * 300)
    probabilities = np.where(outcomes == 1, .78, .22)
    metrics = calibration_metrics(outcomes, probabilities, baseline_probability=.5)
    improvement = paired_log_loss_improvement(
        outcomes, probabilities, baseline_probability=.5,
        bootstrap_samples=300, block_length=5,
    )
    assert metrics["log_loss"] < metrics["baseline_log_loss"]
    assert metrics["log_loss_skill"] > .01
    assert improvement["status"] == "PASS" and improvement["lower_one_sided"] > 0


def test_convex_stacker_includes_all_interpretable_candidates_with_auditable_weights():
    outcomes = np.asarray([0, 1] * 100)
    probabilities = np.column_stack([
        np.where(outcomes, .70, .30),
        np.where(outcomes, .65, .35),
        np.where(outcomes, .80, .20),
    ])
    stacker = ConvexProbabilityStacker().fit(probabilities, outcomes)
    predicted = stacker.predict_proba(probabilities)
    assert stacker.model_names_ == ("logistic", "gam", "monotonic_boosted")
    assert np.all(stacker.weights_ >= 0)
    assert float(np.sum(stacker.weights_)) == pytest.approx(1.0)
    assert predicted.shape == (len(outcomes), 2)


def test_complete_track_record_never_drops_losses_or_pending_decisions():
    records = [
        {"decision_id": "1", "decision_at": "2026-01-01T10:00:00Z", "asset_class": "equity",
         "strategy_id": "s", "action": "Buy", "matured": True, "outcome": "TARGET",
         "actual_forward_return": .03, "training_eligible": True},
        {"decision_id": "2", "decision_at": "2026-01-02T10:00:00Z", "asset_class": "equity",
         "strategy_id": "s", "action": "Watch", "matured": True, "outcome": "STOP",
         "actual_forward_return": -.02, "training_eligible": True},
        {"decision_id": "3", "decision_at": "2026-01-03T10:00:00Z", "asset_class": "equity",
         "strategy_id": "s", "action": "No Trade", "matured": False,
         "training_eligible": False},
    ]
    result = build_complete_track_record(records, generated_at=dt.datetime.now(UTC))
    assert result["denominators"]["all_decisions"] == 3
    assert result["denominators"]["matured"] == 2
    assert result["denominators"]["pending"] == 1
    assert result["performance"]["wins"] == 1
    assert result["performance"]["losses"] == 1
    assert any(row["actual_forward_return"] == -.02 for row in result["rows"])
