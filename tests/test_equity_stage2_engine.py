"""Unit tests for equity_stage2_engine.py — the Stage-2 scoring/decision math
extracted verbatim from app.py (Phase 1a of the auto-Stage-2-in-collector
project, see claude/spec_2026-11-09_stage2_auto_collector.md). No Streamlit,
no network, no DB: pure functions over synthetic OHLCV data."""
import numpy as np
import pandas as pd
import pytest

import technical_indicators as ta
from feature_store import compute_feature_frame
import equity_stage2_engine as engine


def _synthetic_ohlcv(n=260, start_price=100.0, daily_drift=0.0025, seed=7, start_date="2025-01-01"):
    """A smooth-ish uptrending price series with enough history (252+ bars)
    for every indicator (ADX/ATR 252-day percentiles, 200-day EMA, etc.) to
    have real, non-NaN values — not just barely-enough-to-not-crash. Drift
    is kept well above noise so trailing-window checks (weekly resample,
    relative strength) are reliably directional, not just the overall level."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(start=start_date, periods=n)
    noise = rng.normal(0, 0.004, size=n)
    returns = daily_drift + noise
    close = start_price * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0, 0.004, size=n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, size=n)))
    open_ = close * (1 + rng.normal(0, 0.002, size=n))
    volume = rng.integers(500_000, 1_500_000, size=n).astype(float)
    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=index,
    )
    return compute_feature_frame(df, ta)


@pytest.fixture(scope="module")
def uptrend_df():
    return _synthetic_ohlcv()


@pytest.fixture(scope="module")
def nifty_df():
    # Independent synthetic benchmark series, different seed/drift so RS is
    # genuinely non-trivial rather than numerically identical to the stock.
    rng = np.random.default_rng(99)
    index = pd.bdate_range(start="2025-01-01", periods=260)
    returns = 0.0004 + rng.normal(0, 0.004, size=260)
    close = 20000.0 * np.cumprod(1 + returns)
    return pd.DataFrame({"Close": close}, index=index)


class TestClamp:
    def test_within_range_unchanged(self):
        assert engine._clamp(50) == 50

    def test_clamps_above_hi(self):
        assert engine._clamp(150) == 100.0

    def test_clamps_below_lo(self):
        assert engine._clamp(-10) == 0.0


class TestScale:
    def test_midpoint_maps_to_50(self):
        assert engine._scale(5, 0, 10) == 50.0

    def test_degenerate_range_returns_neutral(self):
        assert engine._scale(5, 10, 10) == 50.0

    def test_clamps_outside_range(self):
        assert engine._scale(100, 0, 10) == 100.0
        assert engine._scale(-100, 0, 10) == 0.0


class TestSectorLookup:
    def test_known_ticker(self):
        assert engine.get_sector_bucket("RELIANCE") == "Energy & Oil"
        assert engine.get_ticker_sector("tcs") == "Information Technology"

    def test_unknown_ticker_is_unclassified(self):
        assert engine.get_sector_bucket("NOT_A_REAL_TICKER") == "Unclassified"


class TestPercentileRank:
    def test_insufficient_history_returns_none(self):
        assert engine._percentile_rank(pd.Series([1, 2, 3]), 2) is None

    def test_value_above_all_history_is_near_100(self):
        series = pd.Series(range(1, 300))
        assert engine._percentile_rank(series, 10_000) == pytest.approx(100.0)

    def test_value_below_all_history_is_zero(self):
        series = pd.Series(range(1, 300))
        assert engine._percentile_rank(series, -1) == pytest.approx(0.0)


class TestClassifyEmaTrend:
    def test_strong_uptrend(self):
        latest = pd.Series({"EMA_20": 110, "EMA_50": 100, "EMA_200": 90})
        assert "Strong Uptrend" in engine.classify_ema_trend(latest)

    def test_strong_downtrend(self):
        latest = pd.Series({"EMA_20": 90, "EMA_50": 100, "EMA_200": 110})
        assert "Strong Downtrend" in engine.classify_ema_trend(latest)

    def test_missing_columns_is_unclear(self):
        assert engine.classify_ema_trend(pd.Series({})) == "⚪ Unclear"


class TestClassifyMacd:
    def test_bullish_crossover(self):
        df = pd.DataFrame({
            "MACD": [-1.0, 0.5],
            "MACD_signal": [0.0, 0.0],
        })
        assert engine.classify_macd(df) == "🟢 Bullish Crossover"

    def test_bearish_crossover(self):
        df = pd.DataFrame({
            "MACD": [1.0, -0.5],
            "MACD_signal": [0.0, 0.0],
        })
        assert engine.classify_macd(df) == "🔴 Bearish Crossover"

    def test_missing_columns_is_neutral(self):
        assert engine.classify_macd(pd.DataFrame({"x": [1]})) == "⚪ Neutral"


class TestBollingerPercentB:
    def test_at_midband_is_50_percent(self):
        latest = pd.Series({"BB_lower": 90.0, "BB_upper": 110.0, "Close": 100.0})
        assert engine.compute_bollinger_percent_b(latest) == pytest.approx(50.0)

    def test_degenerate_bands_returns_none(self):
        latest = pd.Series({"BB_lower": 100.0, "BB_upper": 100.0, "Close": 100.0})
        assert engine.compute_bollinger_percent_b(latest) is None


class TestWeeklyTrend:
    def test_uptrend_series_is_bullish(self, uptrend_df):
        assert engine.get_weekly_trend(uptrend_df) == "Bullish (Weekly)"

    def test_too_short_history_is_neutral(self):
        short_df = pd.DataFrame(
            {"Close": [100, 101, 102]},
            index=pd.bdate_range("2025-01-01", periods=3),
        )
        assert engine.get_weekly_trend(short_df) == "Neutral (Weekly)"


class TestRelativeStrengthVsNifty:
    def test_outperforming_stock_is_positive(self, uptrend_df, nifty_df):
        # uptrend_df drifts ~0.15%/day, nifty_df ~0.06%/day over the same
        # window, so the stock should show positive relative strength.
        rs = engine.relative_strength_vs_nifty(uptrend_df, nifty_df, lookback=20)
        assert rs is not None
        assert rs > 0

    def test_missing_benchmark_returns_none(self, uptrend_df):
        assert engine.relative_strength_vs_nifty(uptrend_df, None, lookback=20) is None

    def test_missing_benchmark_empty_df_returns_none(self, uptrend_df):
        assert engine.relative_strength_vs_nifty(uptrend_df, pd.DataFrame(), lookback=20) is None


class TestTrendQualityScore:
    def test_uptrend_scores_reasonably_high(self, uptrend_df):
        result = engine.compute_trend_quality_score(uptrend_df)
        assert result is not None
        assert 0 <= result["score"] <= 100
        assert result["label"] in (
            "Excellent Trend", "Strong Trend", "Average Trend", "Weak Trend",
        )

    def test_insufficient_history_returns_none(self):
        short_df = pd.DataFrame(
            {"Close": [1] * 5, "High": [1] * 5, "Low": [1] * 5, "EMA_20": [1] * 5, "ATR": [1] * 5, "ADX": [1] * 5},
            index=pd.bdate_range("2025-01-01", periods=5),
        )
        assert engine.compute_trend_quality_score(short_df) is None

    def test_missing_required_columns_returns_none(self):
        assert engine.compute_trend_quality_score(pd.DataFrame({"Close": range(40)})) is None


class TestVolumeQualityScore:
    def test_normal_volume_produces_score(self, uptrend_df):
        result = engine.compute_volume_quality_score(uptrend_df, market_open=False)
        assert result is not None
        assert 0 <= result["score"] <= 100
        assert "rvol" in result and "session_adjusted_rvol" in result

    def test_market_open_param_required_explicitly(self, uptrend_df):
        # Default (market_open=False) must not crash and must disable
        # session-adjustment rather than silently reading some ambient state.
        result = engine.compute_volume_quality_score(uptrend_df)
        assert result is not None
        assert result["is_session_adjusted"] is False

    def test_insufficient_history_returns_none(self):
        short_df = pd.DataFrame(
            {"Volume": [1000] * 5},
            index=pd.bdate_range("2025-01-01", periods=5),
        )
        assert engine.compute_volume_quality_score(short_df) is None


class TestBreakoutQualityScore:
    def test_composes_trend_and_volume(self, uptrend_df):
        trend = engine.compute_trend_quality_score(uptrend_df)
        volume = engine.compute_volume_quality_score(uptrend_df, market_open=False)
        result = engine.compute_breakout_quality_score(
            uptrend_df, rs_vs_nifty=5.0, trend_quality=trend, volume_quality=volume,
        )
        assert result is not None
        assert 0 <= result["score"] <= 100
        assert result["trend_component"] == trend["score"]
        assert result["volume_component"] == volume["score"]

    def test_falls_back_to_computing_subscores_when_not_precomputed(self, uptrend_df):
        # Exercises the internal fallback path (volume_quality=None) that is
        # dead in the live evaluate_stock() call path today but must still
        # behave sanely for other/future callers.
        result = engine.compute_breakout_quality_score(uptrend_df, market_open=False)
        assert result is not None

    def test_insufficient_history_returns_none(self):
        assert engine.compute_breakout_quality_score(pd.DataFrame({"Close": range(10)})) is None


class TestDeriveLongTradeLevels:
    def test_happy_path_returns_valid_bracket(self, uptrend_df):
        price = float(uptrend_df["Close"].iloc[-1])
        atr = float(uptrend_df["ATR"].iloc[-1])
        sl, tgt, rr, levels = engine.derive_long_trade_levels(uptrend_df, price, atr, horizon_days=15)
        assert sl is not None and tgt is not None
        assert 0 < sl < price < tgt
        assert rr > 0
        assert set(levels) == {"support20", "resistance20", "resistance60"}

    def test_invalid_inputs_return_all_none(self, uptrend_df):
        assert engine.derive_long_trade_levels(uptrend_df, price=0, atr=1) == (None, None, None, None)
        assert engine.derive_long_trade_levels(uptrend_df, price=100, atr=0) == (None, None, None, None)
        assert engine.derive_long_trade_levels(pd.DataFrame(), price=100, atr=1) == (None, None, None, None)


class TestExecutionCostBreakdown:
    def test_shapes_estimate_into_plain_dict(self):
        class FakeEstimate:
            round_trip_bps = 12.5
            spread_bps = 3.0
            slippage_bps = 2.0
            impact_bps = 1.0
            statutory_bps = 5.0
            brokerage_bps = 1.5

        result = engine._execution_cost_breakdown(FakeEstimate(), assumptions="test assumptions")
        assert result["round_trip_bps"] == 12.5
        assert result["breakdown_complete"] is True
        assert result["assumptions"] == "test assumptions"
