"""Vectorized Smart Money Concepts helpers used by the research page."""

from __future__ import annotations

import numpy as np
import pandas as pd


def detect_market_structure(frame: pd.DataFrame, lookback: int = 5):
    lookback = max(int(lookback), 1)
    if frame is None or frame.empty or len(frame) < lookback * 2 + 1:
        return "Neutral / Ranging", "None"
    highs = pd.to_numeric(frame["High"], errors="coerce")
    lows = pd.to_numeric(frame["Low"], errors="coerce")
    window = lookback * 2 + 1
    swing_high_mask = highs.eq(highs.rolling(window, center=True, min_periods=window).max())
    swing_low_mask = lows.eq(lows.rolling(window, center=True, min_periods=window).min())
    swing_highs = highs[swing_high_mask].to_numpy(dtype=float)
    swing_lows = lows[swing_low_mask].to_numpy(dtype=float)

    trend_state = "Neutral / Ranging"
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        last_sh, prev_sh = swing_highs[-1], swing_highs[-2]
        last_sl, prev_sl = swing_lows[-1], swing_lows[-2]
        if last_sh > prev_sh and last_sl > prev_sl:
            trend_state = "Bullish (HH-HL)"
        elif last_sh < prev_sh and last_sl < prev_sl:
            trend_state = "Bearish (LH-LL)"

    event = "None"
    if len(swing_highs) and len(swing_lows):
        last_close = float(frame["Close"].iloc[-1])
        last_sh, last_sl = float(swing_highs[-1]), float(swing_lows[-1])
        if trend_state == "Bearish (LH-LL)" and last_close > last_sh:
            event = "🔄 Bullish CHoCH (reversal signal)"
        elif trend_state == "Bullish (HH-HL)" and last_close < last_sl:
            event = "🔄 Bearish CHoCH (reversal signal)"
        elif trend_state == "Bullish (HH-HL)" and last_close > last_sh:
            event = "➡️ Bullish BOS (continuation)"
        elif trend_state == "Bearish (LH-LL)" and last_close < last_sl:
            event = "➡️ Bearish BOS (continuation)"
    return trend_state, event


def detect_order_block(frame: pd.DataFrame, atr_series_full, atr_latest):
    try:
        if frame is None or len(frame) < 2:
            return "No Clear OB Detected"
        opens = pd.to_numeric(frame["Open"], errors="coerce").to_numpy(dtype=float)
        closes = pd.to_numeric(frame["Close"], errors="coerce").to_numpy(dtype=float)
        highs = pd.to_numeric(frame["High"], errors="coerce").to_numpy(dtype=float)
        lows = pd.to_numeric(frame["Low"], errors="coerce").to_numpy(dtype=float)
        atr_values = pd.to_numeric(pd.Series(atr_series_full), errors="coerce").to_numpy(dtype=float)
        start = max(len(frame) - 25, 0)
        candidates = np.arange(start, len(frame) - 1)
        next_idx = candidates + 1
        impulse_atr = np.where(
            next_idx < len(atr_values), atr_values[np.minimum(next_idx, len(atr_values) - 1)], np.nan,
        )
        impulse_atr = np.where(np.isfinite(impulse_atr), impulse_atr, float(atr_latest))
        bullish = (closes[candidates] < opens[candidates]) & (
            closes[next_idx] - opens[next_idx] > 1.5 * impulse_atr
        )
        bearish = (closes[candidates] > opens[candidates]) & (
            opens[next_idx] - closes[next_idx] > 1.5 * impulse_atr
        )
        matches = np.flatnonzero(bullish | bearish)
        if not len(matches):
            return "No Clear OB Detected"
        pos = int(matches[-1])
        candle_idx = int(candidates[pos])
        label = "Bullish" if bullish[pos] else "Bearish"
        return f"{label} OB Zone: ₹{lows[candle_idx]:,.2f} - ₹{highs[candle_idx]:,.2f}"
    except Exception:
        return "No Clear OB Detected"


def detect_liquidity_sweep(frame: pd.DataFrame, lookback: int = 10):
    try:
        if frame is None or len(frame) < lookback + 2:
            return "No Sweep Detected"
        recent = frame.iloc[-(lookback + 1):-1]
        prior_high, prior_low = recent["High"].max(), recent["Low"].min()
        last = frame.iloc[-1]
        if last["High"] > prior_high and last["Close"] < prior_high:
            return f"🔺 Bearish Liquidity Sweep — swept high ₹{prior_high:,.2f}"
        if last["Low"] < prior_low and last["Close"] > prior_low:
            return f"🔻 Bullish Liquidity Sweep — swept low ₹{prior_low:,.2f}"
        return "No Sweep Detected"
    except Exception:
        return "No Sweep Detected"
