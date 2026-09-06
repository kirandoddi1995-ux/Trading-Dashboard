import sqlite3

import numpy as np
import pandas as pd

from point_in_time import PointInTimeStore
from prediction_validation import (
    CalibrationPolicy,
    TARGET_VERSION,
    PlattCalibrator,
    TargetDefinition,
    ValidationStore,
    calibration_metrics,
    compute_forward_target,
    decide_abstention,
    purged_walk_forward_splits,
    run_purged_walk_forward_validation,
    scanner_composite_score,
)


def _connect(path):
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _universe(count, prefix="K"):
    return [{
        "instrument_key": f"{prefix}{i}", "trading_symbol": f"S{i}", "isin": f"ISIN{i}",
        "exchange": "NSE_EQ", "instrument_type": "EQ", "security_type": "NORMAL",
    } for i in range(count)]


def test_point_in_time_store_never_uses_a_future_snapshot(tmp_path):
    store = PointInTimeStore(_connect, str(tmp_path / "pit.sqlite3"), minimum_complete_universe=2)
    store.archive_universe(_universe(2, "A"), "2026-01-10")
    store.archive_universe(_universe(3, "B"), "2026-02-10")
    assert store.universe_as_of("2026-01-09").empty
    january = store.universe_as_of("2026-01-31")
    assert set(january.instrument_key) == {"A0", "A1"}
    february = store.universe_as_of("2026-02-10")
    assert set(february.instrument_key) == {"B0", "B1", "B2"}


def test_incomplete_universe_is_not_valid_replay_evidence(tmp_path):
    store = PointInTimeStore(_connect, str(tmp_path / "pit.sqlite3"), minimum_complete_universe=3)
    result = store.archive_universe(_universe(2), "2026-01-10")
    assert result["complete"] is False
    assert store.universe_as_of("2026-01-10", require_complete=True).empty
    assert len(store.universe_as_of("2026-01-10", require_complete=False)) == 2


def test_point_in_time_versions_respect_when_data_became_known(tmp_path):
    store = PointInTimeStore(_connect, str(tmp_path / "pit.sqlite3"), minimum_complete_universe=1)
    store.archive_universe(_universe(1, "A"), "2026-01-10")
    conn = _connect(store._db_path)
    observed_at = conn.execute("SELECT observed_at FROM pit_universe_snapshot_versions").fetchone()[0]
    conn.close()
    before = pd.Timestamp(observed_at) - pd.Timedelta(seconds=1)
    after = pd.Timestamp(observed_at) + pd.Timedelta(seconds=1)
    assert store.universe_as_known_at("2026-01-10", before).empty
    assert set(store.universe_as_known_at("2026-01-10", after).instrument_key) == {"A0"}


def test_point_in_time_universe_lineage_requires_known_membership(tmp_path):
    store = PointInTimeStore(_connect, str(tmp_path / "pit.sqlite3"), minimum_complete_universe=1)
    store.archive_universe(_universe(1, "A"), "2026-01-10")
    conn = _connect(store._db_path)
    observed_at = conn.execute("SELECT observed_at FROM pit_universe_snapshot_versions").fetchone()[0]
    conn.close()
    after = pd.Timestamp(observed_at) + pd.Timedelta(seconds=1)
    lineage = store.universe_lineage_as_known_at("2026-01-10", after, instrument_key="A0")
    assert lineage["complete"] is True
    assert lineage["snapshot_date"] == "2026-01-10"
    assert lineage["member"] is True
    assert lineage["instrument_key"] == "A0"
    assert store.universe_lineage_as_known_at("2026-01-10", after, instrument_key="MISSING") is None


def test_feature_store_never_returns_a_future_revision(tmp_path):
    store = PointInTimeStore(_connect, str(tmp_path / "pit.sqlite3"), minimum_complete_universe=1)
    store.record_feature_observation(
        instrument_key="K1", feature_name="earnings", value={"eps": 10},
        effective_at="2026-01-01T00:00:00+00:00", available_at="2026-01-02T10:00:00+00:00",
        source="official filing",
    )
    store.record_feature_observation(
        instrument_key="K1", feature_name="earnings", value={"eps": 12},
        effective_at="2026-01-01T00:00:00+00:00", available_at="2026-02-02T10:00:00+00:00",
        source="official filing revision",
    )
    january = store.features_as_of("K1", "2026-01-15T10:00:00+00:00")
    february = store.features_as_of("K1", "2026-02-15T10:00:00+00:00")
    assert january["earnings"]["value"]["eps"] == 10
    assert february["earnings"]["value"]["eps"] == 12


def test_corporate_actions_are_deduplicated(tmp_path):
    store = PointInTimeStore(_connect, str(tmp_path / "pit.sqlite3"))
    actions = [{"type": "Split", "ex_date": "2026-01-15", "ratio": "1:2"}]
    assert store.record_corporate_actions("ISIN1", actions) == 1
    assert store.record_corporate_actions("ISIN1", actions) == 0


def _price_frame():
    index = pd.bdate_range("2026-01-01", periods=10)
    return pd.DataFrame({
        "Open": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        "High": [102, 105, 112, 106, 107, 108, 109, 110, 111, 112],
        "Low": [98, 99, 94, 100, 101, 102, 103, 104, 105, 106],
        "Close": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
    }, index=index)


def test_target_enters_next_session_and_same_bar_uses_stop_first():
    prices = _price_frame()
    # as-of first day -> entry is second day's open (101). Third bar touches
    # both stop 95 and target 110, and must be scored conservatively as stop.
    result = compute_forward_target(
        prices, prices.index[0], TargetDefinition(5), stop=95, target=110,
    )
    assert result["entry"] == 101
    assert result["outcome"] == "stop"
    assert result["target_before_stop"] == 0
    assert result["net_return"] < result["gross_return"]


def test_target_calculates_benchmark_excess_and_costs():
    prices = _price_frame()
    benchmark = prices.copy()
    benchmark[["Open", "High", "Low", "Close"]] = 100.0
    result = compute_forward_target(
        prices, prices.index[0], TargetDefinition(3, round_trip_cost_bps=30),
        stop=50, target=200, benchmark=benchmark,
    )
    assert result["benchmark_return"] == 0
    assert np.isclose(result["excess_return"], result["gross_return"] - .003)


def test_scanner_score_is_exact_weighted_formula_and_bounded():
    components = {
        "trend": 100, "momentum": 80, "volume": 70, "relative_strength": 60,
        "risk_reward": 90, "adx": 50, "volatility": 40, "historical_edge": 30,
        "momentum_beta": 20,
    }
    expected = 100*.15 + 80*.12 + 70*.10 + 60*.10 + 90*.15 + 50*.08 + 40*.06 + 30*.10 + 20*.14
    assert scanner_composite_score(components) == expected
    assert scanner_composite_score({key: 1000 for key in components}) == 100


def test_purged_split_has_label_purge_and_twenty_session_embargo():
    dates = pd.bdate_range("2020-01-01", periods=900)
    rows = pd.DataFrame({"as_of_date": dates, "label_end_date": dates + pd.offsets.BDay(20)})
    splits = purged_walk_forward_splits(rows, folds=4, min_train=100, embargo_sessions=20)
    assert splits
    for train, validation in splits:
        train_end = rows.iloc[train].label_end_date.max()
        validation_start = rows.iloc[validation].as_of_date.min()
        assert train_end < validation_start - pd.offsets.BDay(19)


def test_calibration_metrics_and_abstention_policy():
    scores = np.linspace(0, 100, 400)
    outcomes = (scores > 50).astype(int)
    model = PlattCalibrator().fit(scores, outcomes)
    probabilities = model.predict(scores)
    assert np.all((probabilities >= 0) & (probabilities <= 1))
    assert probabilities[-1] > probabilities[0]
    metrics = calibration_metrics(outcomes, probabilities)
    assert metrics["brier"] < metrics["baseline_brier"]
    abstain, _ = decide_abstention(
        .8, metrics, training_samples=400, positive_samples=200,
        negative_samples=200, pit_coverage=1.0,
        policy=CalibrationPolicy(maximum_ece=.20),
    )
    assert abstain is False
    abstain, reason = decide_abstention(
        .8, metrics, training_samples=10, positive_samples=5,
        negative_samples=5, pit_coverage=1.0,
    )
    assert abstain is True and "training" in reason.lower()


def test_walk_forward_returns_insufficient_instead_of_fake_probability():
    dates = pd.bdate_range("2025-01-01", periods=80)
    rows = pd.DataFrame({
        "as_of_date": dates, "label_end_date": dates + pd.offsets.BDay(5),
        "score": np.linspace(20, 90, len(dates)),
        "target_before_stop": np.arange(len(dates)) % 2,
        "excess_return": np.linspace(-.05, .08, len(dates)),
    })
    result = run_purged_walk_forward_validation(rows)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert "probability" not in result


def test_validation_store_uses_only_complete_pit_observations(tmp_path):
    path = str(tmp_path / "evidence.sqlite3")
    pit = PointInTimeStore(_connect, path, minimum_complete_universe=1)
    validation = ValidationStore(_connect, path)
    pit.archive_universe(_universe(1), "2026-01-01")
    observation_id = pit.record_scanner_observation(
        as_of_date="2026-01-01", instrument_key="K0", trading_symbol="S0",
        strategy_version="test", universe_snapshot_date="2026-01-01",
        stage1_pass=True, stage2_pass=True, features={"x": 1}, score=75,
        entry=100, stop=90, target=120,
    )
    target = {
        "horizon_sessions": 5, "target_version": TARGET_VERSION,
        "entry_date": "2026-01-02", "label_end_date": "2026-01-08", "outcome_date": "2026-01-07",
        "outcome": "target", "target_before_stop": 1, "gross_return": .2, "net_return": .197,
        "benchmark_return": .01, "excess_return": .187, "positive_excess": 1, "cost_bps": 30,
    }
    validation.save_target(observation_id, target)
    dataset = validation.validation_dataset(5)
    assert len(dataset) == 1 and dataset.iloc[0].trading_symbol == "S0"
