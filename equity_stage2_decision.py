"""Headless Stage-2 decision core for the scheduled collector (shadow-only).

WHAT THIS IS
A guarded, verbatim copy of the decision core of app.py's scan-page
`evaluate_stock(ticker)`: the body of its `try:` block from the first statement
through `timing = trade_contracts.build_trade_timing(...)`, plus its `except`
handler. Every gate, threshold, formula and reject reason below is app.py's own
text. tests/test_equity_stage2_decision_parity.py compares the copied statements
one by one (allowing only the changes listed below), pins this function's and
this module's structure, and pins app.py's statements outside the copied core by
digest, so a change on either side fails until it is re-reviewed.

WHY A COPY: app.py's bytes are pinned by `equity_real_report.APP_SHA256` (study
evidence chain), so app.py cannot be refactored to call this module. The parity
test is what keeps the copy honest. See claude/spec_2026-11-09_stage2_auto_collector.md.

WHAT CHANGED (only these)
* app.py reads scan-page module globals; here they are keyword-only parameters
  with the SAME names: key, live_quote_data, access_token, get_cached_history,
  fetch_upstox_history, nifty_hist_df, custom_days, max_stock_price,
  require_weekly_align, use_advanced_signal_filters, risk_engine, observation,
  analysis_timing_log.
* Renamed: TECHNICAL_FEATURE_STORE -> feature_store, MARKET_OPEN -> market_open.
* nifty_hist_df / market_open are passed explicitly to the equity_stage2_engine
  helpers that need them (relative strength, volume quality, breakout quality),
  matching that module's signatures.
* `_reject` returns exactly what app.py's returns but does not archive; the
  caller archives from the returned reason and `observation.inputs`, the same
  fields app.py archives.

WHAT IS NOT HERE (live-only, stays in app.py)
After `timing`, app.py builds live evidence lineage, runs the governance gate
(`_evaluate_governance_fail_closed`: manual quote verification, model registry,
artifact signers, exchange-open) and archives decision evidence. Those are
live-execution permissions that need the app's runtime singletons, not
scanner-signal math. So a pass here means "passed every Stage-2 signal gate";
governance is NOT evaluated (`governance_evaluated: False`). The live app can
still reject such a candidate with category "Governance", and turns it into an
"Error" reject if any live-only step after `timing` raises.

ERROR PATH: app.py's `_reject` archives before returning, and that archival can
itself raise on a malformed provider quote (e.g. `market_data` not a dict), making
app.py's `evaluate_stock` raise. Here there is no archival, so the decision is
returned instead; the caller's own archival must handle malformed quotes.

RETURNS app.py's shape: ``(None, {"category": ..., "reason": ...})`` on reject,
or ``(decision, None)`` on pass, where ``decision`` carries exactly what app.py
passes to ``_archive_stage2(True, ...)`` (score/entry/stop/target/features) plus
action, action_reason, timing and ``governance_evaluated: False``.

SIDE EFFECTS: only app.py's own - profiling spans (equity_scan_profiling),
`analysis_timing_log.append`, `observation.observe` and `observation.settings.update`,
`feature_store.enrich` (its cache), a LOGGER warning on the error path, and
whatever the injected `get_cached_history` does.
"""
import datetime
import time

import numpy as np
import pandas as pd

import app_runtime as runtime
import technical_indicators as ta
import trade_contracts
from equity_scan_profiling import call as profile_call, span as profile_span
from equity_stage2_engine import (
    IST, LOGGER, _clamp, _scale, _session_elapsed_fraction, classify_ema_trend, classify_macd,
    compute_bollinger_percent_b, compute_breakout_quality_score, compute_historical_setup_probability,
    compute_trend_quality_score, compute_volume_quality_score, derive_long_trade_levels,
    get_ticker_sector, get_weekly_trend, relative_strength_vs_nifty,
)
from feature_store import compute_feature_frame
from prediction_validation import scanner_composite_score
from quantitative_services import estimate_execution_cost


def evaluate_stage2(
    ticker, *, key, live_quote_data, access_token, get_cached_history, fetch_upstox_history,
    feature_store, nifty_hist_df, market_open, custom_days, max_stock_price,
    require_weekly_align, use_advanced_signal_filters, risk_engine, observation,
    analysis_timing_log,
):
    """Run app.py's Stage-2 decision core for one ticker (see module docstring).

    Parameters mirror the app.py globals of the same name:
    key: Upstox instrument key for `ticker` (None -> "Data" reject).
    live_quote_data: {instrument_key: Upstox quote dict}; entry price source.
    access_token, get_cached_history, fetch_upstox_history: history retrieval,
        called as ``get_cached_history(key, access_token, days=1200,
        fetch_fn=fetch_upstox_history)``; must return a daily OHLCV DataFrame.
    feature_store: object with ``enrich(key, df, compute_fn) -> (df, mode)``
        (feature_store.TechnicalFeatureStore in the app).
    nifty_hist_df: NIFTY 50 daily history (relative strength and beta).
    market_open: whether the NSE session is open now (volume pacing).
    custom_days: holding horizon in sessions.
    max_stock_price, require_weekly_align, use_advanced_signal_filters: scan
        settings, same meaning as the app's scan page.
    risk_engine: risk_engine.RiskEngine (cost budget, risk per share).
    observation: equity_observation_capture.EquityCapture for this ticker.
    analysis_timing_log: list collecting (stage, seconds) timings.
    """
    raw_quote = {}

    def _reject(category, reason):
        """Same return value as app.py's `_reject`; archival is left to the caller."""
        return None, {"category": category, "reason": reason}

    try:
        if not key:
            return _reject("Data", "No instrument key found for this ticker")

        raw_quote = live_quote_data.get(key, {}) if live_quote_data else {}
        live_price = raw_quote.get("last_price")
        observation.observe(locals(), now=datetime.datetime.now(datetime.timezone.utc))

        # Use a long history so the fixed-setup probability can gather a
        # meaningful non-overlapping sample after indicator warm-up. The
        # estimator still returns N/A when evidence is insufficient.
        _hist_t0 = time.perf_counter()
        df = profile_call("history_retrieval", get_cached_history, key, access_token, days=1200, fetch_fn=fetch_upstox_history)
        if df.empty or len(df) < 210:
            analysis_timing_log.append(("history_retrieval", time.perf_counter() - _hist_t0))
            return _reject("Data", "Insufficient price history (need 210+ trading days)")

        # Daily setups must match completed-bar historical evidence.
        # The live quote remains the entry reference, not an indicator candle.
        df = profile_call("history_completed_bars", runtime.completed_daily_bars, df)
        analysis_timing_log.append(("history_retrieval", time.perf_counter() - _hist_t0))
        if df.empty or len(df) < 210:
            return _reject("Data", "Insufficient completed daily price history")

        price = float(live_price) if live_price and float(live_price) > 0 else float(df['Close'].iloc[-1])

        _indicators_t0 = time.perf_counter()
        df, feature_cache_mode = profile_call("indicator_enrichment", feature_store.enrich,
            key, df, lambda source: compute_feature_frame(source, ta),
        )
        last_dir = df['ST_direction'].iloc[-1] if 'ST_direction' in df.columns else np.nan
        supertrend_bullish = (last_dir == 1) if not pd.isna(last_dir) else None

        weekly_trend = profile_call("indicator_weekly_trend", get_weekly_trend, df)
        rs_vs_nifty = profile_call("indicator_relative_strength", relative_strength_vs_nifty, df, nifty_hist_df, lookback=min(20, len(df) - 1))
        analysis_timing_log.append((f"indicators_{feature_cache_mode}", time.perf_counter() - _indicators_t0))

        df_clean = df.dropna(subset=['EMA_20', 'EMA_50', 'EMA_200', 'ATR'])
        if df_clean.empty:
            return _reject("Data", "Indicators could not be computed (NaN in EMA/ATR)")
        latest = df_clean.iloc[-1]
        observation.settings.update({"max_stock_price": max_stock_price,
                                     "require_weekly": require_weekly_align,
                                     "advanced_filters": use_advanced_signal_filters})
        observation.observe(locals(), now=datetime.datetime.now(datetime.timezone.utc))

        if price > max_stock_price:
            return _reject("Price Filter", f"Price ₹{price:,.2f} exceeds your ₹{max_stock_price:,.0f} filter")
        if float(latest['Close']) < float(latest['EMA_50']):
            return _reject("Trend", "Completed daily close is below the 50-day EMA")
        if require_weekly_align and weekly_trend != "Bullish (Weekly)":
            return _reject("Weekly Trend", f"Weekly trend is '{weekly_trend}', not confirmed Bullish")

        if not bool(supertrend_bullish):
            return _reject("Trend", "SuperTrend indicator is bearish")
        if float(latest['EMA_20']) < float(latest['EMA_50']):
            return _reject("Trend", "20-day EMA is below the 50-day EMA")

        atr_val = float(latest['ATR'])
        observation.observe(locals(), now=datetime.datetime.now(datetime.timezone.utc))
        if not np.isfinite(atr_val) or atr_val <= 0:
            return _reject("Data", "Invalid ATR (zero or non-finite)")

        if use_advanced_signal_filters:
            _breakout_t0 = time.perf_counter()
            adx_val = float(latest['ADX']) if pd.notna(latest['ADX']) else None
            current_vol = float(latest['Volume']) if pd.notna(latest.get('Volume')) else 0.0
            avg_vol20 = float(df_clean['Volume'].tail(20).mean()) if 'Volume' in df_clean.columns else 0.0

            # No-Trade Zone: choppy ADX (18-22) + low volume + weekly not
            # confirming the daily/supertrend direction = a transitional,
            # low-conviction period. Skip rather than force a trade.
            is_choppy_adx = adx_val is not None and 18 <= adx_val <= 22
            is_low_volume = avg_vol20 > 0 and current_vol < avg_vol20 * 0.7
            timeframes_mixed = weekly_trend != "Bullish (Weekly)"
            observation.observe(locals(), now=datetime.datetime.now(datetime.timezone.utc))
            if is_choppy_adx and is_low_volume and timeframes_mixed:
                analysis_timing_log.append(("false_breakout_filter", time.perf_counter() - _breakout_t0))
                return _reject("Volume", "No-Trade Zone: choppy ADX, low volume, and weekly trend not confirming")

            # False Breakout Filter: require ADX, volume, AND ATR to all
            # genuinely be rising vs a few sessions ago — a breakout without
            # rising participation/volatility behind it is more likely fake.
            if len(df_clean) >= 11:
                adx_prev = float(df_clean['ADX'].iloc[-6]) if pd.notna(df_clean['ADX'].iloc[-6]) else None
                atr_prev = float(df_clean['ATR'].iloc[-6]) if pd.notna(df_clean['ATR'].iloc[-6]) else None
                vol_prev_avg = float(df_clean['Volume'].iloc[-11:-6].mean())
                adx_rising = adx_val is not None and adx_prev is not None and adx_val > adx_prev
                atr_expanding = atr_val > atr_prev if atr_prev is not None else False
                vol_rising = vol_prev_avg > 0 and current_vol > vol_prev_avg
                if not (adx_rising and atr_expanding and vol_rising):
                    analysis_timing_log.append(("false_breakout_filter", time.perf_counter() - _breakout_t0))
                    return _reject("Volume", "Breakout not confirmed: ADX, volume, and ATR aren't all rising together")
            analysis_timing_log.append(("false_breakout_filter", time.perf_counter() - _breakout_t0))

        sl, tgt, rr_ratio, levels = derive_long_trade_levels(
            df_clean, price, atr_val, horizon_days=custom_days
        )
        observation.observe(locals(), now=datetime.datetime.now(datetime.timezone.utc))
        if sl is None or tgt is None or not 0 < sl < price < tgt:
            return _reject("Risk:Reward", "Invalid structural trade levels")
        average_daily_value = float(pd.to_numeric(df_clean['Volume'], errors='coerce').tail(20).mean()) * price
        market_data = raw_quote.get("market_data") or raw_quote
        cost_estimate = estimate_execution_cost(
            price=price, bid=market_data.get("bid_price"), ask=market_data.get("ask_price"),
            order_value=risk_engine.position_capital_budget(), average_daily_value=average_daily_value,
            asset_class="equity",
        )
        cost_per_share = price * cost_estimate.round_trip_bps / 10_000.0
        risk_per_share = risk_engine.calculate_risk_per_unit(price, sl, cost_buffer=cost_per_share)
        trade_math = trade_contracts.calculate_trade_math(
            price, sl, tgt, direction="long",
            round_trip_cost_bps=cost_estimate.round_trip_bps,
            minimum_ratio=trade_contracts.EQUITY_MIN_NET_REWARD_RISK,
        )
        rr_ratio = trade_math["net_ratio"]
        observation.observe(locals(), now=datetime.datetime.now(datetime.timezone.utc))
        if not trade_math["passes_gate"]:
            return _reject(
                "Risk:Reward",
                f"Net reward:risk {rr_ratio:.2f} is below {trade_math['minimum_ratio']:.2f} after estimated "
                f"{cost_estimate.round_trip_bps:.0f} bps costs",
            )
        if risk_per_share <= 0:
            return _reject("Data", "Invalid risk-per-share calculation")
        # Reference qty for this screener signal (shows risk % per share
        # separately below) — not risk-sized like the options recommendations.
        qty_to_buy = 1

        exp_return_pct = ((tgt - price) / price) * 100.0
        risk_pct = (risk_per_share / price) * 100.0 if price else 0.0
        r_multiple = round(float(rr_ratio), 2)
        risk_reward_str = f"1 : {r_multiple}"

        adx_val = latest.get('ADX')
        rsi_val = latest.get('RSI')
        adx_display = round(float(adx_val), 1) if not pd.isna(adx_val) else "N/A"
        rsi_display = round(float(rsi_val), 1) if not pd.isna(rsi_val) else "N/A"
        ema_trend = classify_ema_trend(latest)
        macd_status = classify_macd(df_clean)
        bb_percent_b = compute_bollinger_percent_b(latest)

        ema20_now = float(latest['EMA_20'])
        slope_base_idx = max(len(df_clean) - 11, 0)
        ema20_prev = float(df_clean['EMA_20'].iloc[slope_base_idx])
        ema20_slope_pct = ((ema20_now / ema20_prev) - 1.0) * 100.0 if ema20_prev else 0.0

        volume_series = pd.to_numeric(df_clean['Volume'], errors='coerce').dropna() if 'Volume' in df_clean.columns else pd.Series(dtype=float)
        current_day_volume = float(volume_series.iloc[-1]) if not volume_series.empty else 0.0
        last_volume_is_today = (
            not volume_series.empty and runtime.market_date(volume_series.index[-1]) == datetime.datetime.now(IST).date()
        )
        historical_volume = volume_series.iloc[-21:-1] if last_volume_is_today else volume_series.iloc[-20:]
        avg_vol20 = float(historical_volume.mean()) if not historical_volume.empty else 0.0
        elapsed_fraction = _session_elapsed_fraction()
        raw_volume_ratio = current_day_volume / avg_vol20 if avg_vol20 > 0 else None
        volume_pace_ratio = runtime.volume_pace(raw_volume_ratio,
            volume_series.index[-1] if not volume_series.empty else None,
            datetime.datetime.now(IST), elapsed_fraction, market_open)

        # Historical frequency of this fixed setup. This is not labelled
        # as trained/OOS probability, and insufficient evidence is N/A.
        _prob_t0 = time.perf_counter()
        # Use the original full history. Passing df_clean discarded the
        # EMA-200 warm-up period before this estimator performed its own
        # EMA/ADX warm-up, making the sample minimum structurally
        # unreachable for common 15-day horizons.
        with profile_span("historical_probability"):
            probability_result = compute_historical_setup_probability(df, horizon_days=custom_days)
        analysis_timing_log.append(("historical_probability", time.perf_counter() - _prob_t0))
        historical_win_prob = probability_result.get('win_probability') if probability_result else None
        probability_ci = (
            f"{probability_result['ci_low']:.1f}–{probability_result['ci_high']:.1f}%"
            if probability_result and probability_result.get('ci_low') is not None else "N/A"
        )
        sample_tier = probability_result['sample_tier'] if probability_result else "Insufficient evidence"

        # Multi-Factor Model (Beta, Momentum Factor, Volatility Factor)
        stock_rets = df_clean['Close'].pct_change().dropna()
        nifty_rets = nifty_hist_df['Close'].pct_change().dropna() if nifty_hist_df is not None and not nifty_hist_df.empty else pd.Series(dtype=float)
        aligned_rets = pd.concat([stock_rets, nifty_rets], axis=1).dropna()
        if len(aligned_rets) > 30:
            cov = np.cov(aligned_rets.iloc[:, 0], aligned_rets.iloc[:, 1], ddof=1)[0][1]
            var_nifty = np.var(aligned_rets.iloc[:, 1], ddof=1)
            stock_beta = float(cov / var_nifty) if var_nifty > 0 else 1.0
        else:
            stock_beta = 1.0

        mom_factor = ((price / float(df_clean['Close'].iloc[-252])) - 1.0) * 100.0 if len(df_clean) >= 252 else 0.0
        beta_score = _clamp(100.0 - abs(stock_beta - 1.0) * 40.0)
        factor_score = (_scale(mom_factor, -20.0, 50.0) * 0.5) + (beta_score * 0.5)

        confirmations = 0
        if supertrend_bullish: confirmations += 1
        if macd_status in ("🟢 Bullish Crossover", "🟢 Above Signal"): confirmations += 1
        if weekly_trend == "Bullish (Weekly)": confirmations += 1
        if rs_vs_nifty is not None and rs_vs_nifty > 0: confirmations += 1
        if not pd.isna(adx_val) and float(adx_val) > 25: confirmations += 1
        if ema_trend.startswith("🟢"): confirmations += 1
        if price > float(latest.get('VWAP20', price)): confirmations += 1
        if volume_pace_ratio is not None and volume_pace_ratio >= 1.2: confirmations += 1

        aligned_indicators = []
        if ema_trend.startswith("🟢"): aligned_indicators.append("EMA20/50/200 alignment")
        if supertrend_bullish: aligned_indicators.append("Supertrend")
        if macd_status in ("🟢 Bullish Crossover", "🟢 Above Signal"): aligned_indicators.append("MACD")
        if not pd.isna(rsi_val) and 50.0 <= float(rsi_val) <= 70.0: aligned_indicators.append("RSI")
        if not pd.isna(adx_val) and float(adx_val) > 25: aligned_indicators.append("ADX")
        if weekly_trend == "Bullish (Weekly)": aligned_indicators.append("Weekly trend")
        if rs_vs_nifty is not None and rs_vs_nifty > 0: aligned_indicators.append("Relative strength")
        if price > float(latest.get('VWAP20', price)): aligned_indicators.append("VWAP20")
        if volume_pace_ratio is not None and volume_pace_ratio >= 1.2: aligned_indicators.append("Volume pace")

        trend_score = _clamp(
            (40 if ema_trend.startswith("🟢") else 20)
            + (20 if supertrend_bullish else 0)
            + _scale(ema20_slope_pct, -2.0, 2.0) * 0.40
        )
        momentum_20d = ((price / float(df_clean['Close'].iloc[-21])) - 1.0) * 100.0 if len(df_clean) > 21 else 0.0
        momentum_score = _scale(momentum_20d, -10.0, 10.0)
        volume_score = _scale(volume_pace_ratio if volume_pace_ratio is not None else 1.0, 0.5, 3.0)
        rs_score = _scale(rs_vs_nifty if rs_vs_nifty is not None else 0.0, -5.0, 10.0)
        rr_score = _scale(r_multiple, 1.0, 4.0)
        adx_score = _scale(float(adx_val), 15.0, 45.0) if not pd.isna(adx_val) else 50.0
        volatility_pct = (atr_val / price) * 100.0 if price else 0.0
        volatility_score = _clamp(100.0 - abs(volatility_pct - 2.0) * 30.0)
        # Rank conservatively by the lower confidence bound. Unknown
        # evidence contributes a neutral score, never a made-up win rate.
        edge_score = (
            _scale(probability_result['ci_low'], 35.0, 65.0)
            if probability_result and probability_result.get('ci_low') is not None else 50.0
        )

        scanner_components = {
            "trend": trend_score, "momentum": momentum_score, "volume": volume_score,
            "relative_strength": rs_score, "risk_reward": rr_score, "adx": adx_score,
            "volatility": volatility_score, "historical_edge": edge_score,
            "momentum_beta": factor_score,
        }
        score = scanner_composite_score(scanner_components)
        observation.observe(locals(), now=datetime.datetime.now(datetime.timezone.utc))

        if score >= 78:
            conviction = "🟢🟢🟢 High"
        elif score >= 62:
            conviction = "🟢🟢 Medium"
        else:
            conviction = "🟢 Low"

        signal_strength = round(float(_clamp(score)), 1)
        ticker_sector = get_ticker_sector(ticker)

        # PHASE 1/2 — Trend Quality & Volume Quality Engines: shown as
        # separate, clearly-labeled columns rather than blended into the
        # existing `score` composite above. There's real conceptual
        # overlap between these and the existing trend_score/adx_score/
        # volume_score components — silently merging them without
        # re-validating the existing (already-working) composite would
        # risk changing signal_strength/Conviction results in ways not
        # yet tested. Shown side-by-side so you can compare, not replace.
        _tq_t0 = time.perf_counter()
        trend_quality = profile_call("indicator_trend_quality", compute_trend_quality_score, df_clean)
        analysis_timing_log.append(("trend_quality", time.perf_counter() - _tq_t0))
        _vq_t0 = time.perf_counter()
        volume_quality = profile_call("indicator_volume_quality", compute_volume_quality_score, df_clean, market_open=market_open)
        analysis_timing_log.append(("volume_quality", time.perf_counter() - _vq_t0))
        # PHASE 3 — Breakout Quality Engine: composed from the two
        # functions above (already computed, passed in — zero duplicate
        # calculation) plus ATR expansion, ADX percentile, and RS.
        breakout_quality = profile_call("indicator_breakout_quality", compute_breakout_quality_score,
            df_clean, rs_vs_nifty=rs_vs_nifty,
            trend_quality=trend_quality, volume_quality=volume_quality,
            market_open=market_open,
        )

        if use_advanced_signal_filters and breakout_quality is not None:
            observation.observe(locals(), now=datetime.datetime.now(datetime.timezone.utc))
            # Extends the EXISTING opt-in Advanced Signal Filters toggle
            # (built earlier this session, off by default) rather than
            # adding a second, separate always-on gate — "reject weak
            # breakouts" per Phase 3, applied only when the person has
            # already chosen the stricter filtering mode.
            if breakout_quality["score"] < 40:
                return _reject("Volume", f"Breakout Quality score {breakout_quality['score']:.0f}/100 is below the 40 minimum")

        action, action_reason = runtime.equity_action(score, price, sl, tgt, atr_val, custom_days)
        timing = trade_contracts.build_trade_timing(
            datetime.datetime.now(IST), horizon_sessions=custom_days, intraday=False,
        )
        # ---- end of the verbatim app.py slice (ends at `timing = ...`) ----
        # app.py continues with live-only steps (evidence lineage, governance
        # gate, evidence archival); see the module docstring. Return what app.py
        # passes to `_archive_stage2(True, ...)` for a passing candidate, after
        # app.py's final capture call (so the observation records the same inputs).
        observation.observe(locals(), now=datetime.datetime.now(datetime.timezone.utc))
        return {
            "score": score, "entry": price, "stop": sl, "target": tgt,
            "features": {
                "components": scanner_components, "horizon_days": custom_days,
                "require_weekly": require_weekly_align, "advanced_filters": use_advanced_signal_filters,
                "ema20": float(latest['EMA_20']), "ema50": float(latest['EMA_50']),
                "ema200": float(latest['EMA_200']), "atr": float(atr_val),
                "adx": (float(adx_val) if pd.notna(adx_val) else None),
                "rsi": (float(rsi_val) if pd.notna(rsi_val) else None),
                "supertrend_bullish": bool(supertrend_bullish), "weekly_trend": weekly_trend,
                "volume_pace_ratio": volume_pace_ratio, "relative_strength": rs_vs_nifty,
                "execution_cost_bps": float(cost_estimate.round_trip_bps),
            },
            "action": action, "action_reason": action_reason, "timing": timing,
            "governance_evaluated": False,
        }, None
    except Exception as exc:
        error_label = runtime.safe_exception_label(exc)
        LOGGER.warning("Equity analysis failed for %s: %s", ticker, error_label)
        return _reject("Error", f"Analysis error: {error_label}")
