"""Stage-2 equity scoring/decision math, extracted verbatim from app.py so it
can be unit-tested and reused headlessly (e.g. by scheduled_collector.py)
without importing app.py itself — app.py is a top-to-bottom executing
Streamlit script (st.set_page_config() etc. fire at import time), so it
cannot safely be imported from a non-Streamlit process.

WHY THIS IS A GUARDED COPY, NOT A MOVE
app.py is NOT edited to import from here. Its exact bytes are pinned by
`equity_real_report.APP_SHA256` and re-checked by
`equity_private_acquire._source_binding()` (raises STUDY_SOURCE_CHANGED), so
the private study's evidence stays bound to the source that produced it. Any
app.py edit — even a pure refactor — breaks that chain. De-duplicating app.py
onto this module is therefore a separate, deliberate re-pin decision for the
owner, not something a refactor may do on its own.

Drift between the two copies is prevented by
tests/test_equity_stage2_engine_parity.py: every definition here must be
AST-identical to its app.py original, except for the explicit, enumerated
signature changes below. Change one side without the other and that test fails.

Extraction rule: no behavior change versus the original app.py functions.
The only edits are explicit parameters added where the original function
silently read a Streamlit-page-scoped module global:

  - `compute_volume_quality_score(df, market_open=False)` — the original read
    the module-level `MARKET_OPEN` (reassigned per Streamlit script run by
    `is_market_open()`). Callers must now pass the current value explicitly.
  - `compute_breakout_quality_score(df, ..., market_open=False)` — same
    reason; threaded through to its own internal, rarely-hit fallback call to
    `compute_volume_quality_score` when `volume_quality` isn't pre-computed.
  - `relative_strength_vs_nifty(df, nifty_hist_df, lookback=20)` — the
    original read the module-level `nifty_hist_df` (assigned once per
    Streamlit script run from a live NIFTY history fetch). Callers must now
    pass that dataframe explicitly.

See claude/spec_2026-11-09_stage2_auto_collector.md for the full extraction
plan this is Phase 1a of (pure scoring engine only — governance/evidence
capture and the full evaluate_stock() orchestration are later phases).
"""
from __future__ import annotations

import datetime
import logging

import numpy as np
import pandas as pd

import app_runtime as runtime
import technical_indicators as ta

LOGGER = logging.getLogger("god_mode_quant")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

_MARKET_OPEN_MIN = 9 * 60 + 15
_MARKET_CLOSE_MIN = 15 * 60 + 30
_SESSION_MINUTES = _MARKET_CLOSE_MIN - _MARKET_OPEN_MIN

NSE_SECTOR_MAP = {
    "RELIANCE": "Energy & Oil", "ONGC": "Energy & Oil", "COALINDIA": "Energy & Oil", "POWERGRID": "Utilities", "NTPC": "Utilities", "TATAPOWER": "Utilities", "ADANIENT": "Conglomerate", "ADANIPORTS": "Infrastructure",
    "TCS": "Information Technology", "INFY": "Information Technology", "WIPRO": "Information Technology", "HCLTECH": "Information Technology", "TECHM": "Information Technology", "LTIM": "Information Technology", "KPITTECH": "Information Technology", "PERSISTENT": "Information Technology", "COFORGE": "Information Technology", "MPHASIS": "Information Technology",
    "HDFCBANK": "Financial Services", "ICICIBANK": "Financial Services", "AXISBANK": "Financial Services", "SBIN": "Financial Services", "KOTAKBANK": "Financial Services", "INDUSINDBK": "Financial Services", "BAJFINANCE": "Financial Services", "BAJAJFINSV": "Financial Services", "SBILIFE": "Financial Services", "HDFCLIFE": "Financial Services", "ICICIPRULI": "Financial Services", "PFC": "Financial Services", "RECLTD": "Financial Services", "CHOLAFIN": "Financial Services", "MUTHOOTFIN": "Financial Services", "PNB": "Financial Services", "BANKBARODA": "Financial Services", "FEDERALBNK": "Financial Services", "IDFCFIRSTB": "Financial Services",
    "MARUTI": "Automobile", "TATAMOTORS": "Automobile", "M&M": "Automobile", "BAJAJ-AUTO": "Automobile", "EICHERMOT": "Automobile", "TVSMOTOR": "Automobile", "HEROMOTOCO": "Automobile", "ASHOKLEY": "Automobile",
    "SUNPHARMA": "Healthcare", "DRREDDY": "Healthcare", "CIPLA": "Healthcare", "APOLLOHOSP": "Healthcare",
    "ITC": "FMCG", "HINDUNILVR": "FMCG", "BRITANNIA": "FMCG", "NESTLEIND": "FMCG", "TATACONSUM": "FMCG", "DABUR": "FMCG", "GODREJCP": "FMCG", "MARICO": "FMCG",
    "TATASTEEL": "Metals & Mining", "JSWSTEEL": "Metals & Mining", "HINDALCO": "Metals & Mining", "VEDL": "Metals & Mining", "SAIL": "Metals & Mining", "NMDC": "Metals & Mining",
    "LT": "Capital Goods & Construction", "BEL": "Capital Goods & Construction", "HAL": "Capital Goods & Construction", "BHEL": "Capital Goods & Construction", "POLYCAB": "Capital Goods & Construction", "HAVELLS": "Capital Goods & Construction", "VOLTAS": "Capital Goods & Construction", "DIXON": "Capital Goods & Construction", "PIDILITIND": "Chemicals", "GRASIM": "Cement & Construction", "ULTRACEMCO": "Cement & Construction", "SHREECEM": "Cement & Construction",
    "ASIANPAINT": "Consumer Durables", "TITAN": "Consumer Durables", "ZOMATO": "Consumer Services", "PAYTM": "Financial Services", "INDIGO": "Aviation", "IRCTC": "Consumer Services", "CONCOR": "Logistics", "NAUKRI": "Consumer Services", "INDIAMART": "Consumer Services", "TRENT": "Retail", "DMART": "Retail", "JUBLFOOD": "Consumer Services", "MAZDOCK": "Capital Goods & Construction", "SUZLON": "Power & Renewables", "IREDA": "Financial Services", "NHPC": "Utilities", "RVNL": "Infrastructure", "IRFC": "Financial Services"
}


def get_ticker_sector(ticker):
    return NSE_SECTOR_MAP.get(ticker.upper(), "Unclassified")


def get_sector_bucket(ticker):
    """Cap unknown exposure without inventing industry classifications."""
    ticker = str(ticker or "").upper()
    return NSE_SECTOR_MAP.get(ticker, "Unclassified")


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(value)))


def _scale(value, low, high):
    if high <= low:
        return 50.0
    return _clamp((float(value) - low) / (high - low) * 100.0)


def _percentile_rank(series, current_value):
    """What percentile `current_value` sits at within `series`'s own recent
    history (0-100). This is what actually makes a threshold adaptive: a VIX
    of 22 means something different in a calm year vs a volatile one, and
    percentile rank adjusts for that automatically instead of hardcoding a
    fixed number that only fits 'typical' conditions."""
    try:
        clean = series.dropna()
        if clean.empty or current_value is None or len(clean) < 20:
            return None
        return float((clean < current_value).mean() * 100.0)
    except Exception:
        return None


def _session_elapsed_fraction(now=None):
    now = now or datetime.datetime.now(IST)
    if now.weekday() >= 5:
        return None
    open_dt = now.replace(hour=9, minute=15, second=0, microsecond=0)
    close_dt = now.replace(hour=15, minute=30, second=0, microsecond=0)
    total = (close_dt - open_dt).total_seconds()
    elapsed = (now - open_dt).total_seconds()
    if elapsed <= 0 or elapsed >= total:
        return None
    return min(max(elapsed / total, 0.15), 1.0)


def classify_ema_trend(latest):
    """Classifies EMA(20/50/200) alignment on the latest bar into a trend label."""
    try:
        e20 = float(latest['EMA_20'])
        e50 = float(latest['EMA_50'])
        e200 = float(latest['EMA_200']) if 'EMA_200' in latest and pd.notna(latest['EMA_200']) else None
        if e200 is not None and e20 > e50 > e200:
            return "🟢 Strong Uptrend (20>50>200)"
        if e200 is not None and e20 < e50 < e200:
            return "🔴 Strong Downtrend (20<50<200)"
        if e20 > e50:
            return "🟢 Uptrend (20>50)"
        return "🔴 Downtrend (20<50)"
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return "⚪ Unclear"


def classify_macd(df):
    """Classifies the most recent MACD/Signal relationship as a crossover or trend continuation."""
    try:
        if 'MACD' not in df.columns or 'MACD_signal' not in df.columns:
            return "⚪ Neutral"
        d = df.dropna(subset=['MACD', 'MACD_signal'])
        if len(d) < 2:
            return "⚪ Neutral"
        last_macd, last_sig = d['MACD'].iloc[-1], d['MACD_signal'].iloc[-1]
        prev_macd, prev_sig = d['MACD'].iloc[-2], d['MACD_signal'].iloc[-2]
        if prev_macd <= prev_sig and last_macd > last_sig:
            return "🟢 Bullish Crossover"
        if prev_macd >= prev_sig and last_macd < last_sig:
            return "🔴 Bearish Crossover"
        return "🟢 Above Signal" if last_macd > last_sig else "🔴 Below Signal"
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return "⚪ Neutral"


def compute_bollinger_percent_b(latest):
    """Computes Bollinger %B for the latest bar: 0% = lower band, 100% = upper band."""
    try:
        lower, upper, close = float(latest['BB_lower']), float(latest['BB_upper']), float(latest['Close'])
        if not np.isfinite(lower) or not np.isfinite(upper) or upper == lower:
            return None
        return round((close - lower) / (upper - lower) * 100.0, 1)
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return None


def get_weekly_trend(df):
    """Resamples a daily OHLC DataFrame to weekly bars and returns a multi-timeframe trend label."""
    try:
        if df is None or df.empty or len(df) < 60:
            return "Neutral (Weekly)"
        weekly_close = df['Close'].resample('W').last().dropna()
        if len(weekly_close) < 12:
            return "Neutral (Weekly)"
        ema10 = ta.ema(weekly_close, length=10)
        if ema10 is None or ema10.dropna().empty:
            return "Neutral (Weekly)"
        last_close, last_ema = weekly_close.iloc[-1], ema10.iloc[-1]
        if pd.isna(last_ema):
            return "Neutral (Weekly)"
        if last_close > last_ema:
            return "Bullish (Weekly)"
        if last_close < last_ema:
            return "Bearish (Weekly)"
        return "Neutral (Weekly)"
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return "Neutral (Weekly)"


def relative_strength_vs_nifty(df, nifty_hist_df, lookback=20):
    """Stock return minus NIFTY 50 return over the trailing `lookback` sessions
    (percentage points). `nifty_hist_df` must be passed explicitly — the
    original app.py function read it from a module-level global populated
    once per Streamlit script run."""
    try:
        if df is None or df.empty or nifty_hist_df is None or nifty_hist_df.empty:
            return None
        stock = pd.to_numeric(df['Close'], errors='coerce').dropna().copy()
        benchmark = pd.to_numeric(nifty_hist_df['Close'], errors='coerce').dropna().copy()
        stock.index = pd.to_datetime(stock.index, errors='coerce').normalize()
        benchmark.index = pd.to_datetime(benchmark.index, errors='coerce').normalize()
        aligned = pd.concat(
            [stock.rename("stock"), benchmark.rename("benchmark")], axis=1, join="inner",
        ).dropna().sort_index()
        aligned = aligned[~aligned.index.duplicated(keep="last")]
        if len(aligned) <= lookback:
            return None
        stock_ret = (float(aligned['stock'].iloc[-1]) / float(aligned['stock'].iloc[-lookback - 1]) - 1.0) * 100.0
        nifty_ret = (float(aligned['benchmark'].iloc[-1]) / float(aligned['benchmark'].iloc[-lookback - 1]) - 1.0) * 100.0
        return round(stock_ret - nifty_ret, 2)
    except Exception as e:
        LOGGER.debug("Suppressed exception: %s", e)
        return None


def compute_trend_quality_score(df):
    """PHASE 1 — Trend Quality Engine. Real, inspectable formula, not a fake
    AI score. Requires df to already have Close/High/Low/EMA_20/EMA_50/ADX/ATR
    columns (matches the exact columns already computed in the equities
    screener — no new indicators, no duplicate calculation of what's already
    there when called from that path).

    Components (each 0-100, weighted):
    1. EMA-20 slope (20%) — 6-bar % change in EMA20, linearly mapped so a
       +/-5% slope over 6 bars maps to the 0-100 extremes. This is a disclosed
       linear transform of a real computed value, not a trained/fitted score.
    2. Higher-High count (15%) — % of the last 10 bars where High > prior High.
    3. Higher-Low count (15%) — % of the last 10 bars where Low > prior Low.
    4. ADX percentile (20%) — real percentile rank vs the stock's own 252-day
       ADX history (reuses _percentile_rank, same adaptive-threshold approach
       as Market Regime).
    5. Trend duration (15%) — consecutive bars price has stayed above EMA_20,
       capped at 20 bars = 100.
    6. Volatility-adjusted trend strength (15%) — EMA slope % divided by
       ATR-as-%-of-price. The same raw % move means more in a low-ATR stock
       than a high-ATR one; this normalizes for that instead of ignoring it.

    Returns {"score": 0-100, "label": str, ...component breakdown...} or None
    if there isn't enough history to compute meaningfully."""
    try:
        required_cols = {'Close', 'High', 'Low', 'EMA_20', 'ATR', 'ADX'}
        if df is None or df.empty or not required_cols.issubset(df.columns) or len(df) < 30:
            return None
        d = df.dropna(subset=['EMA_20', 'ATR', 'ADX'])
        if len(d) < 30:
            return None

        # 1. EMA slope
        ema_now, ema_prev = float(d['EMA_20'].iloc[-1]), float(d['EMA_20'].iloc[-6])
        slope_pct = (ema_now / ema_prev - 1.0) * 100.0 if ema_prev else 0.0
        slope_score = min(100.0, max(0.0, 50.0 + slope_pct * 10.0))

        # 2 & 3. Higher highs / higher lows over the last 10 bars (vectorized)
        recent = d.tail(11)  # need 11 to get 10 comparisons
        hh_count = int((recent['High'].diff().dropna() > 0).sum())
        hl_count = int((recent['Low'].diff().dropna() > 0).sum())
        hh_score = min(100.0, hh_count / 10.0 * 100.0)
        hl_score = min(100.0, hl_count / 10.0 * 100.0)

        # 4. ADX percentile — real, adaptive, same methodology as Market Regime
        adx_val = float(d['ADX'].iloc[-1])
        adx_percentile = _percentile_rank(d['ADX'].tail(252), adx_val)
        adx_score = adx_percentile if adx_percentile is not None else 50.0

        # 5. Trend duration: consecutive bars close has stayed above EMA_20
        above_ema = (d['Close'] > d['EMA_20']).values
        duration = 0
        for v in above_ema[::-1]:
            if not v:
                break
            duration += 1
        duration_score = min(100.0, duration / 20.0 * 100.0)

        # 6. Volatility-adjusted trend strength
        last_close = float(d['Close'].iloc[-1])
        atr_val = float(d['ATR'].iloc[-1])
        atr_pct_of_price = (atr_val / last_close * 100.0) if last_close > 0 else None
        vol_adj_strength = (slope_pct / atr_pct_of_price) if atr_pct_of_price and atr_pct_of_price > 0 else 0.0
        vol_adj_score = min(100.0, max(0.0, 50.0 + vol_adj_strength * 15.0))

        composite = (
            slope_score * 0.20 + hh_score * 0.15 + hl_score * 0.15 +
            adx_score * 0.20 + duration_score * 0.15 + vol_adj_score * 0.15
        )
        composite = round(composite, 1)

        if composite >= 80:
            label = "Excellent Trend"
        elif composite >= 65:
            label = "Strong Trend"
        elif composite >= 45:
            label = "Average Trend"
        else:
            label = "Weak Trend"

        return {
            "score": composite, "label": label,
            "ema_slope_pct": round(slope_pct, 2),
            "hh_count": hh_count, "hl_count": hl_count,
            "adx_percentile": round(adx_percentile, 0) if adx_percentile is not None else None,
            "trend_duration_bars": duration,
            "vol_adjusted_strength": round(vol_adj_strength, 2),
        }
    except Exception as exc:
        LOGGER.debug("Trend quality computation failed: %s", exc)
        return None


def compute_volume_quality_score(df, market_open=False):
    """PHASE 2 — Volume Quality Engine. Real formula, reuses the Volume column
    already present in every df computed elsewhere in the app — no new API
    calls, no duplicate volume fetching.

    `market_open` must be passed explicitly — the original app.py function
    read it from the module-level `MARKET_OPEN` global (reassigned per
    Streamlit script run by `is_market_open()`). Pass the real current value
    from the caller; defaulting to False only disables session-adjustment,
    it does not change anything else.

    Components (each 0-100, weighted):
    1. Session-Adjusted RVOL (25%) — uniform-time heuristic, NOT a validated
       opening/midday seasonal volume curve. Completed prior days stay raw.
    2. Volume percentile (25%) — real percentile rank vs the stock's own
       252-day volume history.
    3. Volume acceleration (20%) — 5-day average volume vs the PRIOR 5-day
       average volume (is participation actually increasing, not just today).
    4. Volume expansion (15%) — % of the last 5 days with volume higher than
       the day before (consistent expansion vs one noisy spike).
    5. Volume consistency (15%) — inverse coefficient of variation over the
       last 20 days (std/mean) — steady elevated volume scores higher than
       one wild spike surrounded by dead days.

    SESSION-AWARE RVOL — exact formula:
        raw_rvol             = current_volume / avg_volume_20d
        session_adjusted_rvol = min(raw_volume_pace_ratio, 5.0)
        where raw_volume_pace_ratio = raw_rvol / elapsed_session_fraction

    elapsed_session_fraction reuses the EXISTING shared _session_elapsed_fraction()
    helper (already used elsewhere in this app for the identical purpose) rather
    than reimplementing it — per explicit reuse requirement. That helper handles:
      - Pre-market (before 9:15 IST): returns a 0.05 floor
      - Market open (just after 9:15): floored at 0.15 minimum, so the first few
        minutes of trading don't produce an artificially explosive ratio (e.g.
        2 minutes of volume compared to a tiny elapsed-fraction denominator)
      - Mid-session: proportional elapsed/total time
      - At/after close (15:30 IST): returns 1.0 (no adjustment needed — the
        day's volume IS the full day's volume by then)

    WHY THIS MATTERS (bug found in prior pass): comparing partial-day volume-so-far
    directly against a 20-day average of COMPLETE days understates RVOL for
    anything evaluated before market close — e.g. at 11am (~30% of the session
    elapsed), even a genuinely strong volume day would show raw RVOL well below
    1.0x just because 70% of the day's volume hasn't happened yet, wrongly
    reading as weak participation.

    SOURCE-DATE CHECK: elapsed_session_fraction uses the current wall-clock
    time. The daily equity scanner now supplies completed prior-date bars,
    which are NOT paced. Other callers must supply a verified current-date
    volume observation. Session-adjustment is applied ONLY when the market is
    genuinely open AND df's last row is dated today; otherwise (market closed,
    weekend, stale/unpatched data) it falls back to the plain, unadjusted
    ratio, since a fraction-of-day adjustment is meaningless on a day that's
    already fully complete.

    Returns {"score": 0-100, "label": str, "rvol": raw, "session_adjusted_rvol":
    adjusted, ...} or None if insufficient data."""
    try:
        if df is None or df.empty or 'Volume' not in df.columns or len(df) < 30:
            return None
        d = df.dropna(subset=['Volume'])
        if len(d) < 30:
            return None

        current_vol = float(d['Volume'].iloc[-1])
        avg_vol20 = float(d['Volume'].tail(20).mean())

        # 1. RVOL — both raw and session-adjusted, shown separately for comparison.
        raw_rvol = min(current_vol / avg_vol20, 5.0) if avg_vol20 > 0 else 0.0

        session_adjusted_rvol = raw_rvol
        is_session_adjusted = False
        try:
            last_row_is_today = runtime.market_date(d.index[-1]) == datetime.datetime.now(IST).date()
        except Exception:
            last_row_is_today = False
        if market_open and last_row_is_today and avg_vol20 > 0:
            elapsed_fraction = _session_elapsed_fraction()
            if elapsed_fraction is not None and elapsed_fraction > 0:
                session_adjusted_rvol = runtime.volume_pace(current_vol / avg_vol20,
                    d.index[-1], datetime.datetime.now(IST), elapsed_fraction, market_open)
                is_session_adjusted = True

        # Session-adjusted RVOL is the correct number to score on during live
        # market hours (see docstring) — falls back to raw RVOL when adjustment
        # doesn't apply (market closed / stale data), matching the existing
        # volume_pace_ratio's own fallback behavior elsewhere in this app.
        rvol_for_scoring = session_adjusted_rvol
        rvol_score = min(100.0, rvol_for_scoring / 3.0 * 100.0)  # RVOL of 3x+ maps to 100

        # 2. Volume percentile — real, adaptive
        vol_percentile = _percentile_rank(d['Volume'].tail(252), current_vol)
        vol_pct_score = vol_percentile if vol_percentile is not None else 50.0

        # 3. Volume acceleration: recent 5-day avg vs prior 5-day avg
        accel_score = 50.0
        if len(d) >= 10:
            recent5 = float(d['Volume'].tail(5).mean())
            prior5 = float(d['Volume'].iloc[-10:-5].mean())
            if prior5 > 0:
                accel_pct = (recent5 / prior5 - 1.0) * 100.0
                accel_score = min(100.0, max(0.0, 50.0 + accel_pct * 2.0))

        # 4. Volume expansion: consistency of day-over-day increases, not one spike
        last5_diffs = d['Volume'].tail(6).diff().dropna()
        expansion_days = int((last5_diffs > 0).sum())
        expansion_score = min(100.0, expansion_days / 5.0 * 100.0)

        # 5. Volume consistency: inverse coefficient of variation (lower CV = more consistent)
        vol20 = d['Volume'].tail(20)
        cv = float(vol20.std() / vol20.mean()) if vol20.mean() > 0 else 1.0
        consistency_score = min(100.0, max(0.0, 100.0 - cv * 50.0))

        composite = (
            rvol_score * 0.25 + vol_pct_score * 0.25 + accel_score * 0.20 +
            expansion_score * 0.15 + consistency_score * 0.15
        )
        composite = round(composite, 1)

        if composite >= 80:
            label = "Exceptional"
        elif composite >= 65:
            label = "Strong"
        elif composite >= 45:
            label = "Average"
        else:
            label = "Weak"

        return {
            "score": composite, "label": label,
            "rvol": round(raw_rvol, 2),
            "session_adjusted_rvol": round(session_adjusted_rvol, 2),
            "is_session_adjusted": is_session_adjusted,
            "volume_percentile": round(vol_percentile, 0) if vol_percentile is not None else None,
            "expansion_days_of_5": expansion_days,
        }
    except Exception as exc:
        LOGGER.debug("Volume quality computation failed: %s", exc)
        return None


def compute_breakout_quality_score(df, rs_vs_nifty=None, trend_quality=None, volume_quality=None, market_open=False):
    """PHASE 3 — False Breakout Filter, upgraded from binary pass/reject to a
    continuous 0-100 breakout_quality_score. Built by COMPOSING the already-
    validated Trend Quality and Volume Quality engines (Phases 1-2), not
    reimplementing their logic — per explicit reuse requirement, and because
    those two were specifically checked last turn for redundancy against the
    existing scoring system before being trusted as inputs here.

    trend_quality / volume_quality can be passed in pre-computed (the caller
    already computes both per-stock for its own display columns) to avoid
    calling those functions twice on the same df — zero duplicate calculation.
    `market_open` is only used if `volume_quality` is NOT pre-computed (see
    compute_volume_quality_score's own docstring for why it's now explicit).

    Components (each 0-100, weighted):
    1. Trend Quality (25%) — from compute_trend_quality_score, reused as-is.
    2. Volume Quality (25%) — from compute_volume_quality_score, reused as-is
       (already includes the session-adjusted RVOL fix from this session).
    3. ATR Expansion (15%) — % change in ATR over the last ~5 bars, mapped to
       0-100. A breakout without expanding volatility behind it is more often
       fake (same principle as the existing binary False Breakout Filter, made
       continuous instead of a hard yes/no).
    4. ADX Strength (20%) — real 252-day percentile rank of current ADX (same
       adaptive methodology as Market Regime and Trend Quality, not a fixed
       threshold).
    5. Relative Strength (15%) — the stock's RS vs NIFTY, normalized with the
       SAME scale already used by the existing scanner composite (_scale(rs,
       -5, 10)) rather than inventing a new, inconsistent normalization range.

    Returns {"score": 0-100, "label": str, ...} or None if insufficient data."""
    try:
        required_cols = {'Close', 'High', 'Low', 'ATR', 'ADX'}
        if df is None or df.empty or not required_cols.issubset(df.columns) or len(df) < 30:
            return None
        d = df.dropna(subset=['ATR', 'ADX'])
        if len(d) < 30:
            return None

        if trend_quality is None:
            trend_quality = compute_trend_quality_score(df)
        if volume_quality is None:
            volume_quality = compute_volume_quality_score(df, market_open=market_open)
        trend_score_component = trend_quality['score'] if trend_quality else 50.0
        volume_score_component = volume_quality['score'] if volume_quality else 50.0

        # 3. ATR Expansion — continuous version of the existing binary check
        atr_now = float(d['ATR'].iloc[-1])
        atr_expansion_score = 50.0
        if len(d) >= 6:
            atr_prev = float(d['ATR'].iloc[-6])
            if atr_prev > 0:
                atr_change_pct = (atr_now / atr_prev - 1.0) * 100.0
                atr_expansion_score = min(100.0, max(0.0, 50.0 + atr_change_pct * 5.0))

        # 4. ADX Strength — real percentile, same methodology as Market Regime
        adx_val = float(d['ADX'].iloc[-1])
        adx_percentile = _percentile_rank(d['ADX'].tail(252), adx_val)
        adx_strength_score = adx_percentile if adx_percentile is not None else 50.0

        # 5. Relative Strength — reuses the EXACT existing normalization scale
        # already used by the scanner's composite score, for consistency
        # rather than a second, differently-calibrated RS transform.
        rs_score_component = _scale(rs_vs_nifty if rs_vs_nifty is not None else 0.0, -5.0, 10.0)

        composite = (
            trend_score_component * 0.25 + volume_score_component * 0.25 +
            atr_expansion_score * 0.15 + adx_strength_score * 0.20 +
            rs_score_component * 0.15
        )
        composite = round(composite, 1)

        if composite >= 75:
            label = "High-Quality Breakout"
        elif composite >= 55:
            label = "Moderate Breakout"
        elif composite >= 35:
            label = "Weak Breakout"
        else:
            label = "Likely False Breakout"

        return {
            "score": composite, "label": label,
            "trend_component": round(trend_score_component, 1),
            "volume_component": round(volume_score_component, 1),
            "atr_expansion_component": round(atr_expansion_score, 1),
            "adx_strength_component": round(adx_strength_score, 1),
            "rs_component": round(rs_score_component, 1),
        }
    except Exception as exc:
        LOGGER.debug("Breakout quality computation failed: %s", exc)
        return None


def derive_long_trade_levels(df, price, atr, horizon_days=15):
    try:
        if df.empty or price <= 0 or atr <= 0:
            return None, None, None, None

        lookback = df.tail(60)
        prior = lookback.iloc[:-1] if len(lookback) > 2 else lookback
        support20 = float(prior["Low"].tail(20).min()) if not prior.empty else float(price - atr)
        resistance20 = float(prior["High"].tail(20).max()) if not prior.empty else float(price + 2 * atr)
        resistance60 = float(prior["High"].max()) if not prior.empty else float(price + 3 * atr)

        atr_stop = price - 1.5 * atr
        structural_stop = support20 - 0.15 * atr if support20 < price else atr_stop
        stop = min(atr_stop, structural_stop)
        if stop <= 0 or stop >= price:
            stop = price - 1.5 * atr

        risk_distance = price - stop
        target_floor = price + max(2.0 * atr, risk_distance * 1.4)
        horizon_mult = 2.0 * (1.0 + horizon_days / 70.0)
        atr_target = price + horizon_mult * atr

        resistance_candidates = [
            r for r in [resistance20, resistance60]
            if r > price * 1.005
        ]
        minimum_target = price + risk_distance * 1.5
        suitable_resistance = [r for r in resistance_candidates if r >= minimum_target]
        if suitable_resistance:
            target = min(min(suitable_resistance), max(target_floor, price + 0.85 * (atr_target - price)))
            target = min(target, min(suitable_resistance))
        else:
            target = max(target_floor, atr_target)

        if target <= price:
            return None, None, None, None

        rr = (target - price) / risk_distance if risk_distance > 0 else 0.0
        return round(float(stop), 2), round(float(target), 2), round(float(rr), 2), {
            "support20": round(support20, 2),
            "resistance20": round(resistance20, 2),
            "resistance60": round(resistance60, 2),
        }
    except Exception as exc:
        LOGGER.debug("Trade-level derivation failed: %s", exc)
        return None, None, None, None


def _execution_cost_breakdown(estimate, *, assumptions):
    return {
        "round_trip_bps": float(estimate.round_trip_bps),
        "spread_bps": float(estimate.spread_bps),
        "slippage_bps": float(estimate.slippage_bps),
        "impact_bps": float(estimate.impact_bps),
        "statutory_bps": float(estimate.statutory_bps),
        "brokerage_bps": float(estimate.brokerage_bps),
        "breakdown_complete": True,
        "assumptions": str(assumptions),
    }
