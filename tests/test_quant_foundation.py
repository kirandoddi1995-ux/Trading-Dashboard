import datetime as dt
import sqlite3

import numpy as np
import pandas as pd
import pytest

from evidence_ledger import ImmutableEvidenceLedger
from prediction_validation import (
    CalibrationPolicy,
    calibration_metrics,
    chronological_holdout_split,
    deflated_sharpe_ratio,
    moving_block_bootstrap_interval,
    run_advanced_chronological_validation,
    wilson_score_interval,
)
from quant_foundation import (
    AdvancedQuantConfig,
    EvidencePolicy,
    ExecutionPolicy,
    PortfolioRiskPolicy,
    calibration_evidence_status,
    decision_transparency_report,
    executable_expected_value,
    execution_quality_gate,
    fractional_kelly_weight,
    historical_expected_shortfall,
    market_breadth_features,
    options_surface_features,
    order_book_features,
    portfolio_risk_report,
    system_kill_switch,
    validate_point_in_time_features,
)


def connect(path):
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def calibrated_evidence(probability=0.70, low=0.64):
    return {
        "status": "VALIDATED", "probability": probability,
        "probability_interval_low": low, "probability_interval_high": 0.76,
        "oos_samples": 1000, "positive_samples": 500, "negative_samples": 500,
        "observation_days": 300, "ece": 0.03, "brier": 0.18,
        "baseline_brier": 0.25, "model_version": "model-v1",
    }


def test_evidence_ledger_is_idempotent_hash_chained_and_immutable(tmp_path):
    path = str(tmp_path / "ledger.sqlite3")
    ledger = ImmutableEvidenceLedger(connect, path, signing_key="test-key")
    first = ledger.append(
        aggregate_id="signal-1", event_type="SIGNAL_CREATED", payload={"entry": 100},
        idempotency_key="create-signal-1",
    )
    duplicate = ledger.append(
        aggregate_id="signal-1", event_type="SIGNAL_CREATED", payload={"entry": 999},
        idempotency_key="create-signal-1",
    )
    second = ledger.append(
        aggregate_id="signal-1", event_type="SIGNAL_AMENDED", payload={"stop": 95},
        idempotency_key="amend-signal-1",
    )
    assert duplicate["duplicate"] is True and duplicate["event_id"] == first["event_id"]
    assert second["sequence_no"] == 2 and second["previous_hash"] == first["event_hash"]
    assert ledger.verify("signal-1") == {
        "valid": True, "events_checked": 2, "aggregates_checked": 1,
        "failures": [], "integrity_mode": "HMAC-SHA256",
    }
    conn = connect(path)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE evidence_ledger_events SET event_type='EXIT_STOP'")
    conn.close()


def test_point_in_time_firewall_rejects_future_stale_and_unlined_features():
    decision = dt.datetime(2026, 9, 2, 10, 0, tzinfo=dt.timezone.utc)
    result = validate_point_in_time_features(decision, {
        "future": {"value": 1, "source": "provider", "available_at": "2026-09-02T10:01:00+00:00"},
        "stale": {"value": 2, "source": "provider", "available_at": "2026-09-02T09:00:00+00:00", "maximum_age_seconds": 60},
        "missing": {"value": 3},
    })
    assert result["status"] == "NO_TRADE"
    assert {failure["code"] for failure in result["failures"]} == {"LOOKAHEAD", "STALE", "MISSING_LINEAGE"}


def test_expected_value_is_unavailable_without_calibration_and_conservative_when_available():
    unavailable = executable_expected_value(entry=100, stop=90, target=125, round_trip_cost_bps=30)
    assert unavailable["status"] == "UNAVAILABLE" and unavailable["probability"] is None
    available = executable_expected_value(
        entry=100, stop=90, target=125, round_trip_cost_bps=30,
        calibration_evidence=calibrated_evidence(),
    )
    assert available["status"] == "PASS"
    assert available["conservative_probability"] == 0.64
    assert available["expected_value_per_unit"] > 0
    weak = calibrated_evidence()
    weak["ece"] = 0.50
    assert calibration_evidence_status(weak)["usable"] is False


def test_execution_gate_and_order_book_features_fail_closed():
    book = order_book_features(
        [{"price": 99.9, "quantity": 100}, {"price": 99.8, "quantity": 200}],
        [{"price": 100.1, "quantity": 50}, {"price": 100.2, "quantity": 100}],
    )
    assert book["status"] == "PASS" and book["queue_imbalance"] > 0
    assert book["microprice"] > book["mid"]
    gate = execution_quality_gate(
        spread_bps=100, order_value=1_000_000, average_daily_value=2_000_000,
        quote_age_seconds=20, market_depth_value=100_000,
    )
    assert gate["status"] == "NO_TRADE" and gate["fill_probability"] is None
    assert len(gate["failures"]) == 4


def test_options_surface_and_breadth_are_descriptive_not_auto_promoted():
    strikes = np.arange(80, 125, 5)
    chain = pd.DataFrame({
        "strike": list(strikes) * 2,
        "dte": [10] * len(strikes) + [40] * len(strikes),
        "iv": [0.20 + 0.4 * (np.log(k / 100) ** 2) - 0.05 * np.log(k / 100) for k in strikes]
              + [0.23 + 0.3 * (np.log(k / 100) ** 2) for k in strikes],
    })
    surface = options_surface_features(chain, spot=100)
    assert surface["status"] == "PASS" and surface["smile_curvature"] > 0
    assert surface["production_score_eligible"] is False
    breadth = market_breadth_features(pd.DataFrame({
        "close": [101, 99, 100], "previous_close": [100, 100, 100], "sma20": [99, 100, 100],
    }))
    assert breadth["eligible"] == 3 and breadth["advancing"] == 1 and breadth["declining"] == 1


def test_portfolio_expected_shortfall_stress_and_kelly_are_calibration_gated():
    rng = np.random.default_rng(42)
    returns = pd.DataFrame({
        "A": rng.normal(0.0005, 0.01, 500),
        "B": rng.normal(0.0003, 0.008, 500),
    })
    report = portfolio_risk_report(
        returns, {"A": 0.10, "B": 0.10}, sectors={"A": "X", "B": "Y"},
        stress_scenarios={"index_down": {"A": -0.08, "B": -0.05}},
        policy=PortfolioRiskPolicy(maximum_marginal_risk_share=0.70),
    )
    assert report["status"] == "PASS"
    assert report["expected_shortfall"]["expected_shortfall_loss"] > 0
    assert report["stress_returns"]["index_down"] < 0
    blocked = fractional_kelly_weight(.7, 2.0, calibration_evidence=None)
    assert blocked["status"] == "UNAVAILABLE" and blocked["weight"] == 0
    allowed = fractional_kelly_weight(.7, 2.0, calibration_evidence=calibrated_evidence())
    assert 0 < allowed["weight"] <= PortfolioRiskPolicy().maximum_fractional_kelly_weight


def test_derivative_exposure_limits_and_kill_switch_fail_closed():
    rng = np.random.default_rng(7)
    returns = pd.DataFrame({"A": rng.normal(0, .01, 250), "B": rng.normal(0, .01, 250)})
    report = portfolio_risk_report(
        returns, {"A": .2, "B": .2}, expiries={"A": "near", "B": "near"},
        greek_exposures={"A": {"delta": 2.0}, "B": {"delta": 2.0}},
        policy=PortfolioRiskPolicy(maximum_marginal_risk_share=1.0),
    )
    assert report["status"] == "NO_TRADE"
    assert "Expiry-weight limit exceeded" in report["failures"]
    assert "Net-delta limit exceeded" in report["failures"]
    halt = system_kill_switch(
        feed_age_seconds=30, broker_position_mismatch=True,
        daily_pnl_fraction=-.04, provider_available=False,
    )
    assert halt["status"] == "HALT" and not halt["allow_new_entries"]
    assert halt["exit_management_remains_enabled"] is True


def test_validation_intervals_and_search_adjustment_are_finite():
    low, high = wilson_score_interval(70, 100)
    assert 0 < low < 0.70 < high < 1
    values = np.tile([0.01, -0.004, 0.006, 0.002, -0.001], 100)
    interval = moving_block_bootstrap_interval(values, samples=200, block_length=5)
    assert interval["status"] == "PASS" and interval["lower"] <= interval["estimate"] <= interval["upper"]
    dsr = deflated_sharpe_ratio(values, trials=20)
    assert dsr["status"] == "PASS" and 0 <= dsr["deflated_sharpe_probability"] <= 1
    rows = pd.DataFrame({"as_of_date": pd.bdate_range("2020-01-01", periods=300), "x": range(300)})
    development, holdout = chronological_holdout_split(rows, holdout_fraction=.2, minimum_holdout_dates=20)
    assert development.as_of_date.max() < holdout.as_of_date.min()
    assert len(development) + len(holdout) == len(rows)


def test_calibration_metrics_include_decomposition_and_intervals():
    y = np.asarray([0, 0, 1, 1] * 50)
    p = np.asarray([.1, .2, .8, .9] * 50)
    metrics = calibration_metrics(y, p, bins=5)
    assert metrics["brier_skill"] > 0
    assert metrics["brier_uncertainty"] > 0
    assert all("actual_interval_low" in row for row in metrics["reliability"])


def test_advanced_validation_keeps_final_holdout_out_of_training():
    count = 1200
    dates = pd.bdate_range("2019-01-01", periods=count)
    scores = np.tile(np.linspace(5, 95, 20), count // 20)
    outcomes = (scores > 50).astype(int)
    returns = np.where(outcomes == 1, .01, -.003) + np.sin(np.arange(count)) * .001
    rows = pd.DataFrame({
        "as_of_date": dates, "label_end_date": dates + pd.offsets.BDay(5),
        "score": scores, "target_before_stop": outcomes,
        "excess_return": returns, "pit_coverage": 1.0,
    })
    policy = CalibrationPolicy(
        minimum_training_samples=100, minimum_class_samples=20,
        minimum_oos_samples=100, maximum_ece=.20,
        minimum_probability=.55, minimum_probability_margin=.01,
    )
    result = run_advanced_chronological_validation(
        rows, folds=4, embargo_sessions=5, holdout_fraction=.15,
        experiment_trials=3, bootstrap_samples=200, policy=policy,
    )
    assert result["status"] == "VALIDATED"
    assert result["training_samples"] + result["holdout_samples"] == count
    assert pd.Timestamp(result["holdout"]["start"]) > rows.iloc[result["training_samples"] - 1].as_of_date
    assert result["holdout"]["metrics"]["brier"] < result["holdout"]["metrics"]["baseline_brier"]


def test_transparency_report_caps_drivers_and_requires_every_gate():
    report = decision_transparency_report(
        decision_id="d1", generated_at="2026-09-02T10:00:00+05:30", instrument="NIFTY",
        model_version="m1",
        supporting_factors=[{"name": str(i), "contribution": i} for i in range(5)],
        opposing_risks=[{"name": "spread", "contribution": -2}],
        gates=[{"name": "R:R", "passed": True}, {"name": "EV", "passed": False}],
        market_data={"quote_age_seconds": 1}, uncertainty={"p10": -0.01, "p50": .01, "p90": .03},
    )
    assert report["actionable"] is False
    assert len(report["supporting_factors"]) == 3
