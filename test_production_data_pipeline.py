import datetime as dt

import numpy as np
import pandas as pd

from amfi_ingestion import current_ranking_records, parse_amfi_open_nav
from prediction_validation import (
    PRODUCTION_CALIBRATION_POLICY,
    TARGET_VERSION,
    TargetDefinition,
    compute_forward_target,
    evidence_maturity,
)
from production_repository import ProductionRepository
from scheduled_collector import resolve_mode


def test_repository_disabled_health_never_echoes_connection_material():
    result = ProductionRepository("").health()
    assert result == {"configured": False, "connected": False, "status": "Not configured"}


def test_amfi_new_format_is_strict_and_only_ranks_current_direct_growth():
    header = "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date"
    lines = ["Open Ended Schemes(Equity Scheme - Large Cap Fund)", "Example Mutual Fund", header]
    for code in range(1000, 2001):
        plan = "Direct Plan" if code % 2 == 0 else "Regular Plan"
        lines.append(f"{code};INF{code}A;;Fund {code};{plan};Growth;10.25;01-Sep-2026")
    lines.append("9999;INF9999A;;Segregated Portfolio;Direct Plan;Growth;0;01-Sep-2026")
    result = parse_amfi_open_nav("\n".join(lines))
    assert len(result.records) == 1001
    assert all(float(record["nav"]) > 0 for record in result.records)
    ranked = current_ranking_records(result)
    assert ranked and all(record["is_direct_growth"] for record in ranked)


def test_exact_intraday_entry_and_target_before_stop_sequence():
    days = pd.bdate_range("2026-01-02", periods=8)
    prices = pd.DataFrame({
        "Open": [100] * 8, "High": [101, 111, 101, 101, 101, 101, 101, 101],
        "Low": [99, 94, 99, 99, 99, 99, 99, 99], "Close": [100] * 8,
    }, index=days)
    minute_index = pd.date_range("2026-01-05 09:15", periods=7, freq="min")
    intraday = pd.DataFrame({
        "Open": [100] * 7, "High": [101, 102, 103, 104, 105, 111, 100],
        "Low": [99, 99, 99, 99, 99, 99, 94], "Close": [100] * 7,
        "Volume": [10] * 7,
    }, index=minute_index)
    result = compute_forward_target(
        prices, days[0], TargetDefinition(5, entry_rule="exact_intraday"),
        stop=95, target=110, intraday=intraday,
    )
    assert result["target_version"] == TARGET_VERSION
    assert result["entry_quality"] == "next_session_opening_5m_ohlcv_vwap"
    assert result["outcome"] == "target"


def test_benchmark_return_stops_on_the_signal_outcome_date():
    days = pd.bdate_range("2026-01-02", periods=7)
    prices = pd.DataFrame({
        "Open": [100] * 7, "High": [101, 120, 101, 101, 101, 101, 101],
        "Low": [99] * 7, "Close": [100] * 7,
    }, index=days)
    benchmark = pd.DataFrame({
        "Open": [100] * 7, "High": [100] * 7, "Low": [100] * 7,
        "Close": [100, 101, 150, 160, 170, 180, 190],
    }, index=days)
    result = compute_forward_target(
        prices, days[0], TargetDefinition(5), stop=50, target=110, benchmark=benchmark,
    )
    assert result["outcome_date"] == days[1].date().isoformat()
    assert np.isclose(result["benchmark_return"], 0.01)


def test_production_evidence_requires_time_samples_regimes_and_probability_bands():
    rows = pd.DataFrame({
        "as_of_date": pd.bdate_range("2026-01-01", periods=100),
        "market_regime": ["TREND"] * 100,
    })
    maturity = evidence_maturity(rows, np.repeat(0.75, 100), PRODUCTION_CALIBRATION_POLICY)
    assert maturity["credible"] is False
    assert any("2000" in reason for reason in maturity["reasons"])


def test_schedule_auto_mode_uses_ist_and_weekly_maintenance():
    assert resolve_mode("auto", dt.datetime(2026, 9, 2, 9, 25)) == "open"
    assert resolve_mode("auto", dt.datetime(2026, 9, 2, 15, 45)) == "close"
    assert resolve_mode("auto", dt.datetime(2026, 9, 5, 18, 0)) == "weekly"
