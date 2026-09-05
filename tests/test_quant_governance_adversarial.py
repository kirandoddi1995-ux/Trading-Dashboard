import concurrent.futures
import datetime as dt
import sqlite3

import numpy as np
import pandas as pd
import pytest

from evidence_ledger import ImmutableEvidenceLedger
from point_in_time import PointInTimeStore
from prediction_validation import TargetDefinition, chronological_holdout_split, compute_forward_target
from quant_foundation import (
    calibration_evidence_status,
    execution_quality_gate,
    portfolio_risk_report,
    system_kill_switch,
    validate_point_in_time_features,
)


def connect(path):
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def test_concurrent_ledger_writers_keep_one_contiguous_chain(tmp_path):
    path = str(tmp_path / "ledger.sqlite3")
    ImmutableEvidenceLedger(connect, path, signing_key="test-key")

    def append(index):
        ledger = ImmutableEvidenceLedger(connect, path, signing_key="test-key")
        return ledger.append(
            aggregate_id="same-signal", event_type="SIGNAL_AMENDED",
            payload={"index": index}, effective_at="2026-09-02T10:00:00Z",
            idempotency_key=f"amend-{index}",
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(append, range(40)))
    assert sorted(row["sequence_no"] for row in results) == list(range(1, 41))
    assert ImmutableEvidenceLedger(connect, path, signing_key="test-key").verify("same-signal")["valid"]


def test_idempotency_key_cannot_alias_different_evidence(tmp_path):
    ledger = ImmutableEvidenceLedger(connect, str(tmp_path / "ledger.sqlite3"), signing_key="test-key")
    args = dict(
        aggregate_id="signal-a", event_type="SIGNAL_CREATED", payload={"entry": 100},
        effective_at="2026-09-02T10:00:00Z", idempotency_key="stable-key",
    )
    ledger.append(**args)
    assert ledger.append(**args)["duplicate"] is True
    with pytest.raises(ValueError, match="different evidence"):
        ledger.append(**{**args, "aggregate_id": "signal-b"})


def test_entry_day_pre_signal_target_touch_is_not_counted():
    days = pd.bdate_range("2026-09-01", periods=3)
    prices = pd.DataFrame({
        "Open": [100, 100, 102], "High": [101, 112, 104],
        "Low": [99, 98, 100], "Close": [100, 102, 103],
    }, index=days)
    intraday = pd.DataFrame({
        "Open": [100, 108, 102, 102], "High": [111, 109, 103, 104],
        "Low": [99, 107, 101, 101], "Close": [108, 108, 102, 103],
        "Volume": [100, 100, 100, 100],
    }, index=pd.to_datetime([
        "2026-09-02 09:30", "2026-09-02 10:00", "2026-09-02 10:02", "2026-09-03 09:16",
    ]))
    result = compute_forward_target(
        prices, days[0], TargetDefinition(2, entry_rule="exact_intraday"),
        stop=95, target=110, intraday=intraday, signal_timestamp="2026-09-02 10:01",
    )
    assert result is not None
    assert result["outcome"] == "horizon"
    assert result["target_before_stop"] == 0


def test_final_holdout_purges_crossing_labels_and_embargo():
    dates = pd.bdate_range("2025-01-01", periods=160)
    rows = pd.DataFrame({"as_of_date": dates, "label_end_date": dates + pd.offsets.BDay(10)})
    development, holdout = chronological_holdout_split(
        rows, holdout_fraction=0.20, minimum_holdout_dates=20, embargo_sessions=5,
    )
    holdout_start = holdout["as_of_date"].min()
    assert development["label_end_date"].max() < holdout_start - pd.offsets.BDay(5)


def test_same_day_scans_are_distinct_and_stage1_cannot_erase_stage2(tmp_path):
    path = str(tmp_path / "pit.sqlite3")
    store = PointInTimeStore(connect, path, minimum_complete_universe=1)
    universe = [{"instrument_key": "NSE_EQ|A", "trading_symbol": "A"}]
    store.archive_universe(universe, snapshot_date="2026-09-02")
    evidence = [{"instrument_key": "NSE_EQ|A", "trading_symbol": "A", "stage1_pass": True}]
    store.record_stage1_batch(as_of_date="2026-09-02", strategy_version="v1",
                              universe_snapshot_date="2026-09-02", evidence=evidence, scan_run_id="run-1")
    first = store.record_scanner_observation(
        as_of_date="2026-09-02", instrument_key="NSE_EQ|A", trading_symbol="A",
        strategy_version="v1", universe_snapshot_date="2026-09-02", stage1_pass=True,
        stage2_pass=True, features={"score": 80}, entry=100, stop=95, target=111,
        scan_run_id="run-1",
    )
    store.record_stage1_batch(as_of_date="2026-09-02", strategy_version="v1",
                              universe_snapshot_date="2026-09-02", evidence=evidence, scan_run_id="run-1")
    second = store.record_scanner_observation(
        as_of_date="2026-09-02", instrument_key="NSE_EQ|A", trading_symbol="A",
        strategy_version="v1", universe_snapshot_date="2026-09-02", stage1_pass=True,
        stage2_pass=False, features={"score": 20}, rejection_reason="later scan",
        scan_run_id="run-2",
    )
    assert first != second
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT stage2_pass,entry,stop,target FROM scanner_observations WHERE observation_id=?", (first,)
        ).fetchone()
        assert row == (1, 100.0, 95.0, 111.0)
        assert conn.execute("SELECT COUNT(*) FROM scanner_observations").fetchone()[0] == 2
    finally:
        conn.close()


def test_feature_store_normalizes_timezones_and_blocks_future_effective_value(tmp_path):
    store = PointInTimeStore(connect, str(tmp_path / "pit.sqlite3"), minimum_complete_universe=1)
    store.record_feature_observation(
        instrument_key="A", feature_name="rsi", value=55,
        effective_at="2026-09-02T16:00:00+05:30", available_at="2026-09-02T10:29:00Z", source="provider",
    )
    store.record_feature_observation(
        instrument_key="A", feature_name="future", value=99,
        effective_at="2026-09-02T11:00:00Z", available_at="2026-09-02T10:00:00Z", source="provider",
    )
    result = store.features_as_of("A", "2026-09-02T10:30:00Z")
    assert result["rsi"]["value"] == 55
    assert "future" not in result


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_non_finite_policy_inputs_fail_closed(value):
    assert execution_quality_gate(
        spread_bps=value, order_value=100, average_daily_value=10000, quote_age_seconds=0,
    )["status"] == "NO_TRADE"
    assert system_kill_switch(feed_age_seconds=value)["status"] == "HALT"
    assert validate_point_in_time_features(
        "2026-09-02T10:00:00Z",
        {"x": {"value": value, "source": "provider", "available_at": "2026-09-02T10:00:00Z"}},
        universe_observed_at="2026-09-02T09:59:00Z",
        universe_effective_at="2026-09-02T09:59:00Z",
    )["status"] == "NO_TRADE"


def test_nan_calibration_and_missing_portfolio_history_are_unavailable():
    now = dt.datetime.now(dt.timezone.utc)
    evidence = {
        "status": "VALIDATED", "probability": 0.7, "probability_interval_low": 0.6,
        "probability_interval_high": 0.8, "oos_samples": 1000, "positive_samples": 500,
        "negative_samples": 500, "observation_days": 300, "ece": np.nan, "brier": 0.18,
        "baseline_brier": 0.25, "model_version": "v1",
        "validated_at": (now - dt.timedelta(days=1)).isoformat(),
        "valid_until": (now + dt.timedelta(days=10)).isoformat(),
        "feature_psi": 0.05, "calibration_decay": 0.01,
    }
    assert calibration_evidence_status(evidence)["usable"] is False
    returns = pd.DataFrame({"A": np.repeat(0.001, 100)})
    report = portfolio_risk_report(returns, {"A": 0.1, "B": 0.1})
    assert report["status"] == "UNAVAILABLE"
    assert "B" in report["reason"]
