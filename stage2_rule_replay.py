"""Historical replay of Stage-2 trade-level rules (0-Buys study, 17 Nov 2026). Research only.

WHY: the live rule gives 0 Buys. Two formula defects are proven on stored passes
(claude/status_2026-11-15_zero_buys_root_cause.md): the stop is the farther of 1.5 ATR and the
20-day low with no cap (median risk 5.5 ATR), and with no resistance above, the target is
1.4 x risk, so net reward:risk is pinned at ~1.38 and the score's risk_reward part is a
constant ~12.7. Which fix is right can only be judged on outcomes, so this replays the app's
own Stage-2 decision core (equity_stage2_decision.evaluate_stage2, the guarded copy of
app.py) on ~8 years of daily bars under four level rules fixed before any result was seen
(PRE-REGISTERED below), and scores every Buy on what happened next.

WHAT IT DOES, per stock and replay day D (every STEP-th session, offset per stock so no weekday
or expiry cycle is favoured; first D once a full live history window exists):
  history  daily bars strictly before D within the live windows: 1200 calendar days of the stock,
           400 of NIFTY (equity_stage2_collector.HISTORY_DAYS / NIFTY_HISTORY_DAYS);
  quote    D's open as the live price (live decides at 10:07 on a live quote; see LIMITS);
  decision evaluate_stage2 with the variant's level rule patched in, both in the decision core and
           in the historical-setup estimate (equity_stage2_engine), as a live change to the level
           routine would apply it; everything else live;
  outcome  app_runtime.trade_outcome on the stock's bars over the HORIZON NIFTY sessions from D
           (holding_window; v1 used bars D..D+HORIZON-1) (entry D open, stop first, gap stop at
           the open, target never improved), net of 30/60/100 bp round trip, minus NIFTY's
           return from D's open to the exit day's close (excess); `sessions` = stock bars held;
  Buys     non-overlapping per stock and variant: no new Buy until the previous one exits.

PRE-REGISTERED VARIANTS (frozen 17 Nov 2026 before the first run):
  incumbent-levels-v1   live rule, unchanged.
  atr15-stop-v1         stop = entry - 1.5 ATR, target as the incumbent computes for that stop
                        (the shadow challenger, equity_stage2_maturation.challenger_levels).
  capped25-atr4-v1      stop = 20-day structural stop clamped to [1.5, 2.5] ATR below entry;
                        target = nearest resistance at or above entry + 1.3 x risk if it is below
                        entry + 4 ATR, else entry + 4 ATR (target no longer derived from the stop;
                        4 ATR ~ one standard deviation of a 15-session move, ATR x sqrt(15);
                        with the 4 ATR target the 2.5 ATR cap keeps gross reward:risk >= 1.6, so the
                        live 1.30 net gate is met after costs; a resistance target from 1.3 x risk
                        gross can fail that net gate, and is then a Risk:Reward reject (reported);
                        a 3 ATR cap failed the gate on a synthetic dry run).
  capped25-atr4-rr13-v1 capped25-atr4-v1 levels, and the score's risk_reward part scaled over the
                        reward:risk the rule can produce (1.3 to 3.0) instead of 1.0 to 4.0.
  Choice rule (stated before running): prefer the variant whose Buys have the highest mean net
  excess at 60 bp with at least 30 Buys and a positive mean at 100 bp, on a complete run (every
  shard present on the same NIFTY 500 list); per-year results and the unconditional baseline
  (every replay day, same stocks, entry at the open, time exit) are shown beside it. Show Kiran
  before any live change (the live rule is app.py, pinned; a change is his decision).

LIMITS (reported with every result): the universe's current members (survivorship bias, which also
inflates the absolute check at 100 bp: compare against the baseline); daily bars only (no minute
order inside a day: a bar touching both levels counts as a stop, which costs tighter stops more);
entry at D's open, not 10:07; Upstox daily history is split/bonus adjusted, dividends are not; no
quote spread (live collector quotes carry none either: live round trip ~14.5 bp); excess runs to
the exit day's close; no governance gate; Buys cluster on dates, so t-stats overstate certainty;
costs are scenarios, not fills; Stage-1 ranking is not replayed (every stock is evaluated every
STEP-th session); a pass whose 15th NIFTY session is the last bar of the data but not a trading day
of the stock counts as no outcome (conservative). Development evidence, not a performance claim.

SIDE EFFECTS: none on the database. The `members` step reads NSE's NIFTY 500 list (and, for the
holdout, Upstox's public instrument master) once per run; `run` reads Upstox daily candles
(read-only, free) at a bounded rate (the workflow runs at most 8 shards at once: Upstox allows
2,000 history requests per 30 minutes per user, shared with the live collector); files only.

WIDTH TEST (v2 code, 23 Nov 2026; pre-registered in claude/PREREG_2026-11-23_width_rule_decision.md v5,
all versions written before any v2 run). Question: does the live width gate (app_runtime.equity_action: stop <= 20%
below entry AND target - entry <= ATR x max(4, 2 sqrt(15))) discard passes that beat NIFTY?
  universes  `nifty500` = the 17 Nov list (SEEN: its published score buckets already hint at the
             answer, so its width numbers are context only); `holdout` = the live collector's NSE EQ
             universe (scheduled_collector.fetch_nse_universe) minus the current NIFTY 500, i.e.
             stocks the 17 Nov replay never touched; the only decisive run.
  groups     incumbent-levels-v1 passes with an outcome. A70 = score >= 70 and Watch: at that score
             equity_action says Watch only for width (invalid levels are Unavailable), and v2 rows
             re-check it from the stored entry. A65 (65-69, width-blocked) and the stop-wide /
             target-only split need the entry, so v2 rows only. B = Buy. Baseline as above.
  verdict    PASS only if all PREREG checks hold for A70 (mean >= +1.0% at 60 bp, > 0 at 100 bp,
             the 90% month-block bootstrap interval for 1, 3 AND 6-month blocks above 0 (the
             "widest" interval: the lowest lower bound decides), median > 0, above the baseline,
             >= 3 positive years of 2022-2026 and > 0 without the best year, worst decile within
             5 pts of B's, stop-exit share within 10 pts of B's, and (v5) the most liquid third of
             A70 by 20-day traded value has a mean above 0); NO_DECISION if the run is
             incomplete, A70 has < 150 passes or < 24 months, B < 30, or over 2% of A70 passes have
             no outcome (possible hidden losses). Gates compare unrounded
             values (stop shares as exact fractions); the report shows them rounded. An incomplete
             run reports only its blockers and size, so a repeat run stays blind to its numbers.
  v2 rows    add the entry (D open), the exit day and gap_sessions: a stock day missing inside the
             15 NIFTY sessions (suspension, no trade) shortens the window instead of stretching
             the holding period past the 15th session (v1 counted 15 stock bars); a halt ON the 15th
             session sells at the first trade after it (it could not be sold before). Pass rows also
             carry traded_value_20d (median close x volume, 20 days before D): A70 is reported by
             liquidity tercile (flat costs understate micro-cap spreads). History fetches
             retry twice (60 s x attempt after an HTTP 429). Each shard header carries the
             universe size, the denominator of the 2% failure rule (v1: stocks with rows + failed).
  members    the workflow resolves the list once (`members` command: holdout removes the NIFTY 500
             by instrument key and by symbol, and records the NIFTY 500 digest it removed), and runs
             at most 8 shards at once (Upstox: 2,000 history requests / 30 min / user, shared);
             every fetch first sleeps through the live scan windows (weekdays 09:55-10:40 and
             14:25-15:10 IST: wait_outside_scans).
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import hashlib
import io
import json
import logging
import math
import os
import random
import re
import statistics
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

import pandas as pd

import app_runtime as runtime
import equity_stage2_decision as decision_core
import equity_stage2_engine as engine
import trade_contracts
from equity_observation_capture import EquityCapture
from equity_stage2_collector import (
    APP_DEFAULT_SETTINGS, HISTORY_DAYS, NIFTY_HISTORY_DAYS, NIFTY_KEY, fetch_daily_candles,
)
from equity_stage2_engine import _scale, derive_long_trade_levels
from equity_stage2_maturation import challenger_levels
from risk_engine import RiskEngine
from scheduled_collector import fetch_nse_universe

LOGGER = logging.getLogger("stage2_rule_replay")

VERSION = "stage2-rule-replay-v2"                     # v2: holdout universe; entry / exit day / gaps in rows
KNOWN_VERSIONS = ("stage2-rule-replay-v1", VERSION)   # v1 = the 17 Nov run (re-summarised, never re-run)
HORIZON = APP_DEFAULT_SETTINGS.custom_days            # 15 sessions, the app default
UNIVERSES = {"nifty500": 8, "holdout": 20}            # universe -> shard count (the workflow's matrix)
SHARDS = UNIVERSES["nifty500"]
FETCH_ATTEMPTS = 3                                    # one history request + two retries
MAX_FAILED_SHARE = 0.02                               # more failed stocks than this: run incomplete
STEP = 5                                              # replay every 5th session
COSTS_BPS = (30.0, 60.0, 100.0)
RR_WEIGHT = 0.15                                      # prediction_validation.scanner_composite_score
MIN_TRADES = 30
NIFTY500_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
SYMBOL = re.compile(r"[A-Z0-9&-]{1,20}")
ISIN = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
ERROR_CATEGORIES = ("Error",)                         # evaluate_stage2's own exception reject
VARIANTS = ("incumbent-levels-v1", "atr15-stop-v1", "capped25-atr4-v1", "capped25-atr4-rr13-v1")
# Width test (PREREG v5, 23 Nov 2026): fixed before any v2 run; change only with a new PREREG version.
WIDTH_VARIANT = "incumbent-levels-v1"
WIDTH = {"score": 70.0, "score_a65": 65.0, "mean_60bp": 1.0, "min_passes": 150, "min_months": 24,
         "max_no_outcome_share": 0.02,
         "years": ("2022", "2023", "2024", "2025", "2026"), "min_positive_years": 3,
         "tail_margin_pts": 5.0, "stop_share_margin": 0.10, "min_buys": 30}
BLOCK_MONTHS = (1, 3, 6)
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20261123
STOP_EXITS = ("STOP", "GAP_STOP", "BOTH_STOP")         # app_runtime.trade_outcome's stop reasons


# ------------------------------------------------------------------ level rules ---

def _resistances(df: pd.DataFrame, price: float, atr: float) -> tuple[float, float, float]:
    """support20, resistance20, resistance60 exactly as derive_long_trade_levels reads them."""
    lookback = df.tail(60)
    prior = lookback.iloc[:-1] if len(lookback) > 2 else lookback
    support20 = float(prior["Low"].tail(20).min()) if not prior.empty else float(price - atr)
    resistance20 = float(prior["High"].tail(20).max()) if not prior.empty else float(price + 2 * atr)
    resistance60 = float(prior["High"].max()) if not prior.empty else float(price + 3 * atr)
    return support20, resistance20, resistance60


def _result(price: float, stop: float, target: float, s20: float, r20: float, r60: float):
    """derive_long_trade_levels' return shape, or all None for invalid levels."""
    if not (0 < stop < price < target):
        return None, None, None, None
    rr = (target - price) / (price - stop)
    return round(float(stop), 2), round(float(target), 2), round(float(rr), 2), {
        "support20": round(s20, 2), "resistance20": round(r20, 2), "resistance60": round(r60, 2)}


def atr15_levels(df, price, atr, horizon_days=HORIZON):
    """atr15-stop-v1: the shadow challenger's levels."""
    try:
        if df.empty or price <= 0 or atr <= 0:
            return None, None, None, None
        s20, r20, r60 = _resistances(df, price, atr)
        levels = challenger_levels(price, atr, r20, r60, horizon_days)
        return (None, None, None, None) if levels is None else _result(price, *levels, s20, r20, r60)
    except Exception as exc:  # same contract as derive_long_trade_levels: never raise
        LOGGER.debug("atr15 levels failed: %s", exc)
        return None, None, None, None


def capped25_levels(df, price, atr, horizon_days=HORIZON):
    """capped25-atr4-v1: structural stop clamped to [1.5, 2.5] ATR; target independent of the stop."""
    try:
        if df.empty or price <= 0 or atr <= 0:
            return None, None, None, None
        s20, r20, r60 = _resistances(df, price, atr)
        structural = s20 - 0.15 * atr if s20 < price else price - 1.5 * atr
        stop = min(max(structural, price - 2.5 * atr), price - 1.5 * atr)
        risk = price - stop
        cap = price + 4.0 * atr
        reachable = [r for r in (r20, r60) if price + 1.3 * risk <= r < cap]
        target = min(reachable) if reachable else cap
        return _result(price, stop, target, s20, r20, r60)
    except Exception as exc:
        LOGGER.debug("capped25 levels failed: %s", exc)
        return None, None, None, None


LEVELS: dict[str, Callable] = {
    "incumbent-levels-v1": derive_long_trade_levels,
    "atr15-stop-v1": atr15_levels,
    "capped25-atr4-v1": capped25_levels,
    "capped25-atr4-rr13-v1": capped25_levels,
}
RR_SCALE = {"capped25-atr4-rr13-v1": (1.3, 3.0)}       # others: the live 1.0 to 4.0


def rescored(score: float, components: Mapping[str, float], net_rr: float, variant: str) -> float:
    """The composite with risk_reward on the variant's scale (live scale: unchanged)."""
    if variant not in RR_SCALE:
        return float(score)
    low, high = RR_SCALE[variant]
    return float(score) - RR_WEIGHT * float(components["risk_reward"]) + RR_WEIGHT * _scale(net_rr, low, high)


# ------------------------------------------------------------------- decision core ---

class _CachedFeatures:
    """Feature frames computed once per (stock, day) and shared by every variant."""

    def __init__(self):
        """Empty cache."""
        self.frames: dict[Any, pd.DataFrame] = {}

    def enrich(self, instrument_key, source, compute_fn):
        """ComputeOnlyFeatureStore.enrich, memoised on the key and the last bar."""
        if source is None or source.empty:
            return source, "empty"
        marker = (instrument_key, source.index[-1], len(source))
        if marker not in self.frames:
            self.frames[marker] = compute_fn(source)
        return self.frames[marker].copy(), "full_rebuild"


@contextlib.contextmanager
def _patched(levels: Callable, probability_cache: dict):
    """Swap the level rule into the decision core; memoise the slow setup-probability estimate."""
    original_levels = decision_core.derive_long_trade_levels
    original_engine_levels = engine.derive_long_trade_levels
    original_probability = decision_core.compute_historical_setup_probability

    def probability(df, horizon_days=HORIZON, **kwargs):
        """compute_historical_setup_probability (which reads engine.derive_long_trade_levels), once per
        (level rule, last bar, length, horizon): variants sharing a rule share the estimate."""
        marker = (id(levels), df.index[-1], len(df), horizon_days)
        if marker not in probability_cache:
            probability_cache[marker] = original_probability(df, horizon_days=horizon_days, **kwargs)
        return probability_cache[marker]

    decision_core.derive_long_trade_levels = levels
    engine.derive_long_trade_levels = levels
    decision_core.compute_historical_setup_probability = probability
    try:
        yield
    finally:
        decision_core.derive_long_trade_levels = original_levels
        engine.derive_long_trade_levels = original_engine_levels
        decision_core.compute_historical_setup_probability = original_probability


def decide(ticker: str, key: str, history: pd.DataFrame, price: float, nifty: pd.DataFrame,
           variant: str, *, features: _CachedFeatures, probability_cache: dict) -> dict:
    """One Stage-2 decision under `variant` on bars before D with D's open as the price."""
    settings = APP_DEFAULT_SETTINGS
    observation = EquityCapture(identity={"ticker": ticker, "replay": VERSION},
                                settings={"horizon_sessions": settings.custom_days})
    with _patched(LEVELS[variant], probability_cache):
        result, rejection = decision_core.evaluate_stage2(
            ticker, key=key, live_quote_data={key: {"last_price": price}}, access_token="replay",
            get_cached_history=lambda *_a, **_k: history, fetch_upstox_history=None,
            feature_store=features, nifty_hist_df=nifty, market_open=False,
            custom_days=settings.custom_days, max_stock_price=settings.max_stock_price,
            require_weekly_align=settings.require_weekly_align,
            use_advanced_signal_filters=settings.use_advanced_signal_filters,
            risk_engine=RiskEngine(investment_capital=settings.investment_capital,
                                   max_risk_pct=settings.max_risk_pct,
                                   max_position_pct=settings.max_position_pct),
            observation=observation, analysis_timing_log=[],
        )
    if result is None:
        return {"pass": False, "category": rejection["category"]}
    features_used = result["features"]
    net_rr = trade_contracts.calculate_trade_math(
        price, result["stop"], result["target"], direction="long",
        round_trip_cost_bps=features_used["execution_cost_bps"],
        minimum_ratio=trade_contracts.EQUITY_MIN_NET_REWARD_RISK)["net_ratio"]
    score = rescored(result["score"], features_used["components"], net_rr, variant)
    action, _ = runtime.equity_action(score, price, result["stop"], result["target"],
                                      features_used["atr"], settings.custom_days)
    return {"pass": True, "score": round(score, 2), "stop": result["stop"], "target": result["target"],
            "net_rr": net_rr, "atr": features_used["atr"], "action": action}


# ---------------------------------------------------------------------- outcomes ---

def holding_window(bars: pd.DataFrame, start: int, nifty: pd.DataFrame) -> tuple[pd.DataFrame | None, int]:
    """The stock's bars over the HORIZON NIFTY sessions starting at bar `start` (D = session 1), and
    how many of those sessions the stock did not trade (suspension, no trade). A gap inside shortens
    the window; a halt ON the HORIZON-th session cannot be sold through, so the window runs to the
    first trade after it (sold at that close; stop / target still checked on it). (None, 0) when D
    is not a NIFTY session or either series ends before that last session (no outcome: counted)."""
    if not 0 <= start < len(bars):
        return None, 0
    day = bars.index[start]
    sessions = nifty.index[nifty.index >= day][:HORIZON]
    if len(sessions) < HORIZON or sessions[0] != day or bars.index[-1] < sessions[-1]:
        return None, 0
    tail = bars.iloc[start:]
    window = tail[tail.index <= sessions[-1]].iloc[:HORIZON]
    gaps = HORIZON - len(window)
    if window.index[-1] < sessions[-1]:            # halted on the last session: sell when it trades again
        window = tail.iloc[:len(window) + 1]
    return window, gaps


def outcome(bars: pd.DataFrame, start: int, stop: float, target: float, nifty: pd.DataFrame) -> dict | None:
    """Entry at bar `start`'s open, HORIZON NIFTY sessions (holding_window); gross % and NIFTY %
    over the same days; the exit day and the stock's missing sessions are kept for the width test."""
    window, gaps = holding_window(bars, start, nifty)
    if window is None:
        return None
    rows = [tuple(float(window.iloc[i][c]) for c in ("Open", "High", "Low", "Close")) for i in range(len(window))]
    entry = rows[0][0]
    if not (_positive(entry) and 0 < stop < entry < target):
        return None
    traded = runtime.trade_outcome(rows, entry, stop, target, cost_pct=0.0)
    exit_day = window.index[traded["offset"]]
    first_day = window.index[0]
    nifty_open = nifty["Open"].get(first_day)
    nifty_close = nifty["Close"].get(exit_day)
    if not (_positive(nifty_open) and _positive(nifty_close)):
        return None
    return {"gross_pct": traded["net_return_pct"], "reason": traded["reason"], "sessions": traded["offset"] + 1,
            "nifty_pct": (float(nifty_close) / float(nifty_open) - 1) * 100,
            "exit_index": start + traded["offset"], "exit_day": str(exit_day.date()), "gap_sessions": gaps}


BASELINE = "baseline-open-time-exit"


def _positive(value) -> bool:
    """A finite price above zero (None and NaN are not)."""
    try:
        return value is not None and math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def baseline(bars: pd.DataFrame, start: int, nifty: pd.DataFrame) -> dict:
    """Unconditional comparison on the same stock and day: buy D's open, sell the last close of the
    holding window (holding_window: the HORIZON-th session, or the first trade after a halt on it)."""
    window, gaps = holding_window(bars, start, nifty)
    if window is None:
        return {"pass": False, "category": "BaselineUnavailable"}
    first, last = window.index[0], window.index[-1]
    nifty_open, nifty_close = nifty["Open"].get(first), nifty["Close"].get(last)
    entry, close = float(window.iloc[0]["Open"]), float(window.iloc[-1]["Close"])
    if not (_positive(entry) and _positive(close) and _positive(nifty_open) and _positive(nifty_close)):
        return {"pass": False, "category": "BaselineUnavailable"}
    return {"pass": True, "gross_pct": (close / entry - 1) * 100, "reason": "TIME",
            "nifty_pct": (float(nifty_close) / float(nifty_open) - 1) * 100, "gap_sessions": gaps}


def traded_value(history: pd.DataFrame) -> float | None:
    """Median close x volume of the last 20 bars before D (outcome-blind liquidity), None without volume."""
    if "Volume" not in history:
        return None
    values = (history["Close"] * history["Volume"]).tail(20)
    values = values[values.map(lambda v: math.isfinite(float(v)))]
    return float(values.median()) if len(values) == 20 else None


def stock_offset(ticker: str, step: int = STEP) -> int:
    """A fixed per-stock start offset in [0, step): spreads replay days over weekdays and expiries."""
    return int(hashlib.sha256(ticker.encode()).hexdigest(), 16) % step


def replay_days(bars: pd.DataFrame, nifty: pd.DataFrame, *, offset: int = 0, step: int = STEP) -> list[int]:
    """Positions of the replay days: every `step`-th session from `offset` that NIFTY also traded,
    once both live history windows lie inside the data, with HORIZON NIFTY sessions from it (v1:
    HORIZON stock bars). A stock that stops trading inside those sessions is still replayed, so its
    pass is counted as having no outcome instead of silently never existing."""
    if bars.empty or nifty.empty:
        return []
    position = {day: i for i, day in enumerate(nifty.index)}
    first = max(bars.index[0] + pd.Timedelta(days=HISTORY_DAYS), nifty.index[0] + pd.Timedelta(days=NIFTY_HISTORY_DAYS))
    return [i for i in range(offset, len(bars), step)
            if bars.index[i] >= first and bars.index[i] in position
            and position[bars.index[i]] + HORIZON <= len(nifty)]


def live_windows(bars: pd.DataFrame, nifty: pd.DataFrame, day) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The stock and NIFTY history the live scan would hold on `day`: strictly before it, within
    HISTORY_DAYS / NIFTY_HISTORY_DAYS calendar days (fetch_daily_candles' request range)."""
    day = pd.Timestamp(day)
    stock = bars.loc[(bars.index < day) & (bars.index >= day - pd.Timedelta(days=HISTORY_DAYS))]
    index = nifty.loc[(nifty.index < day) & (nifty.index >= day - pd.Timedelta(days=NIFTY_HISTORY_DAYS))]
    return stock, index


def replay_stock(ticker: str, key: str, bars: pd.DataFrame, nifty: pd.DataFrame,
                 variants: Sequence[str] = VARIANTS) -> list[dict]:
    """Every replay day x variant for one stock: decision, and the outcome of every pass."""
    features, probability_cache, rows = _CachedFeatures(), {}, []
    busy_until = {variant: -1 for variant in variants}
    for index in replay_days(bars, nifty, offset=stock_offset(ticker)):
        day = bars.index[index]
        history, index_history = live_windows(bars, nifty, day)
        price = float(bars.iloc[index]["Open"])
        if not price > 0:
            continue
        rows.append({"ticker": ticker, "day": str(day.date()), "variant": BASELINE, **baseline(bars, index, nifty)})
        for variant in variants:
            row = {"ticker": ticker, "day": str(day.date()), "variant": variant}
            try:  # one bad day must not stop a long replay; it is counted
                made = decide(ticker, key, history, price, index_history, variant,
                              features=features, probability_cache=probability_cache)
                row.update(made)
                if made["pass"]:
                    row["entry"] = price   # D's open, the decision price: the width test re-checks the gate
                    row["traded_value_20d"] = traded_value(history)
                    result = outcome(bars, index, made["stop"], made["target"], nifty)
                    if result is not None:
                        row.update({k: v for k, v in result.items() if k != "exit_index"})
                        row["counted_buy"] = made["action"] == "Buy" and index > busy_until[variant]
                        if row["counted_buy"]:
                            busy_until[variant] = result["exit_index"]
            except Exception as exc:
                row.update({"pass": False, "category": f"ReplayError:{type(exc).__name__}"})
            rows.append(row)
    return rows


# ----------------------------------------------------------------------- summary ---

def _stats(values: list[float]) -> dict:
    """n, mean, median, win rate, t-stat (None when too few)."""
    if not values:
        return {"n": 0}
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return {"n": len(values), "mean": round(mean, 3), "median": round(statistics.median(values), 3),
            "win_rate": round(sum(v > 0 for v in values) / len(values), 3),
            "t": round(mean / (sd / math.sqrt(len(values))), 2) if sd > 0 else None}


def _variant_summary(mine: list[Mapping[str, Any]]) -> dict:
    """Passes, Buys, exit reasons, net / excess at each cost, and 60 bp excess by score bucket."""
    passes = [r for r in mine if r.get("pass") and "gross_pct" in r]
    buys = [r for r in passes if r.get("counted_buy")]
    entry: dict[str, Any] = {
        "decisions": len(mine), "passes": len(passes),
        "errors": sum(str(r.get("category", "")).startswith("ReplayError")
                      or r.get("category") in ERROR_CATEGORIES for r in mine),
        "rejects": {c: sum(r.get("category") == c for r in mine)
                    for c in sorted({str(r["category"]) for r in mine if r.get("category")})},
        "buys": len(buys),
        "actions": {a: sum(r.get("action") == a for r in passes) for a in ("Buy", "Watch", "Unavailable")},
        "buy_exit_reasons": {k: sum(r["reason"] == k for r in buys) for k in sorted({r["reason"] for r in buys})},
    }
    for cost in COSTS_BPS:
        net = cost / 100
        entry[f"buy_net_{int(cost)}bp"] = _stats([r["gross_pct"] - net for r in buys])
        entry[f"buy_excess_{int(cost)}bp"] = _stats([r["gross_pct"] - net - r["nifty_pct"] for r in buys])
        entry[f"pass_excess_{int(cost)}bp"] = _stats([r["gross_pct"] - net - r["nifty_pct"] for r in passes])
    entry["pass_excess_60bp_by_score"] = {
        f"{low}-{min(high, 100)}": _stats([r["gross_pct"] - 0.6 - r["nifty_pct"] for r in passes
                                          if low <= r["score"] < high])
        for low, high in ((0, 50), (50, 60), (60, 70), (70, 101))}
    entry["buy_excess_60bp_by_year"] = {
        year: _stats([r["gross_pct"] - 0.6 - r["nifty_pct"] for r in buys if r["day"][:4] == year])
        for year in sorted({r["day"][:4] for r in buys})}
    return entry


def _excess(row: Mapping[str, Any], bp: float) -> float:
    """Net excess vs NIFTY in % after a `bp` round trip."""
    return row["gross_pct"] - bp / 100 - row["nifty_pct"]


def width_blocked(row: Mapping[str, Any]) -> bool | None:
    """The live width gate on the row's own levels (score set to 100, so only width can say Watch);
    None for v1 rows, which do not store the entry price."""
    if row.get("entry") is None:
        return None
    action, _ = runtime.equity_action(100.0, row["entry"], row["stop"], row["target"], row["atr"], HORIZON)
    return action == "Watch"


def _a70(rows: Sequence[Mapping[str, Any]]) -> list:
    """Width-blocked incumbent passes with score >= 70 (outcome or not)."""
    return [r for r in rows if r.get("variant") == WIDTH_VARIANT and r.get("pass") and r["score"] >= WIDTH["score"]
            and r.get("action") == "Watch" and width_blocked(r) is not False]


def width_groups(rows: Sequence[Mapping[str, Any]]) -> dict[str, list]:
    """A70, A65, B (Buy) and baseline rows of the width test (WIDTH TEST in the module docstring);
    `a70_no_outcome` = A70 passes whose stock has no complete holding period (counted, gated)."""
    passes = [r for r in rows if r.get("variant") == WIDTH_VARIANT and r.get("pass") and "gross_pct" in r]
    return {
        "a70": [r for r in _a70(rows) if "gross_pct" in r],
        "a70_no_outcome": [r for r in _a70(rows) if "gross_pct" not in r],
        "a65": [r for r in passes if WIDTH["score_a65"] <= r["score"] < WIDTH["score"] and width_blocked(r)],
        "b": [r for r in passes if r.get("action") == "Buy"],
        "baseline": [r for r in rows if r.get("variant") == BASELINE and r.get("pass")],
    }


def calendar_months(first: str, last: str) -> list[str]:
    """Every 'YYYY-MM' from the month of date `first` to the month of `last`, empty months included."""
    year, month, months = int(first[:4]), int(first[5:7]), []
    while (year, month) <= (int(last[:4]), int(last[5:7])):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def block_interval(rows: Sequence[Mapping[str, Any]], months: Sequence[str], block: int, *, bp: float = 60.0,
                   draws: int = BOOTSTRAP_DRAWS, seed: int = BOOTSTRAP_SEED) -> dict | None:
    """90% interval of the pooled mean excess from a circular moving-block bootstrap over calendar
    months: each draw joins ceil(M / block) runs of `block` consecutive months (empty months count,
    so quiet spells stay in), pooling their trades. Same-day trades, the 15-session overlap and
    regimes up to `block` months stay together. Unrounded low / high (the gate compares these);
    None without trades or months."""
    if not rows or not months:
        return None
    position = {month: i for i, month in enumerate(months)}
    sums, counts = [0.0] * len(months), [0] * len(months)
    for row in rows:
        i = position[row["day"][:7]]
        sums[i] += _excess(row, bp)
        counts[i] += 1
    rng, means, runs = random.Random(seed), [], math.ceil(len(months) / block)
    for _ in range(draws):
        total, n = 0.0, 0
        for _ in range(runs):
            start = rng.randrange(len(months))
            for k in range(start, start + block):
                total, n = total + sums[k % len(months)], n + counts[k % len(months)]
        if n:
            means.append(total / n)
    means.sort()
    return {"low": means[int(0.05 * (len(means) - 1))], "high": means[int(0.95 * (len(means) - 1))],
            "draws": len(means)}


def _year(day: str) -> str:
    """Calendar year of a replay day; the late-2021 days join 2022 (PREREG check d)."""
    return "2022" if day[:4] == "2021" else day[:4]


def _worst_decile(values: Sequence[float]) -> float | None:
    """Mean of the lowest tenth (at least one value), unrounded."""
    ordered = sorted(values)
    return statistics.fmean(ordered[:max(1, math.ceil(len(ordered) / 10))]) if ordered else None


def _stop_count(rows: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """(trades that left at the stop, trades): exact, so the share gate compares fractions."""
    return sum(r["reason"] in STOP_EXITS for r in rows), len(rows)


def non_overlapping(rows: Sequence[Mapping[str, Any]]) -> list | None:
    """Per stock, the next pass only after the previous kept one exits (reported, not a gate);
    None when a row has no exit day (v1)."""
    if any("exit_day" not in r for r in rows):
        return None
    kept, free_after = [], {}
    for row in sorted(rows, key=lambda r: (r["ticker"], r["day"])):
        if row["day"] > free_after.get(row["ticker"], ""):
            kept.append(row)
            free_after[row["ticker"]] = row["exit_day"]
    return kept


def _split(rows: Sequence[Mapping[str, Any]]) -> dict | None:
    """Stop-wide (stop > 20% below entry) vs target-only-wide; None without the entry (v1)."""
    if not rows or any(r.get("entry") is None for r in rows):
        return None
    stop_wide = [r for r in rows if (r["entry"] - r["stop"]) / r["entry"] > 0.20]
    target_only = [r for r in rows if (r["entry"] - r["stop"]) / r["entry"] <= 0.20]
    return {name: _stats([_excess(r, 60) for r in part]) for name, part in
            (("stop_wide_60bp", stop_wide), ("target_only_60bp", target_only))}


def liquidity_split(rows: Sequence[Mapping[str, Any]]) -> dict | None:
    """A70 60 bp excess by tercile of the 20-day traded value before D (reported: micro-caps' real
    spreads exceed flat costs), over the rows that have one; `without_value` counts the rest (v1
    rows, < 20 finite volume days). None when no row has one."""
    parts = _terciles(rows)
    valued = sum(len(part) for part in parts)
    if not valued:
        return None
    split = {name: _stats([_excess(r, 60) for r in part]) for name, part in zip(("low", "mid", "high"), parts)}
    return {**split, "without_value": len(rows) - valued}


def _terciles(rows: Sequence[Mapping[str, Any]]) -> tuple[list, list, list]:
    """Rows with a traded_value_20d, least liquid first, cut at n // 3 and 2n // 3: thirds as equal as
    possible (sizes differ by at most 1; the top third is never empty when n >= 1). One cut for the
    report and check g."""
    ordered = sorted((r for r in rows if r.get("traded_value_20d") is not None),
                     key=lambda r: (r["traded_value_20d"], r.get("ticker", ""), r.get("day", "")))   # ties: fixed order
    low, high = len(ordered) // 3, 2 * len(ordered) // 3
    return ordered[:low], ordered[low:high], ordered[high:]


def _mean(values: Sequence[float]) -> float | None:
    """Unrounded mean, None when empty."""
    return statistics.fmean(values) if values else None


def _above(value: float | None, floor: float | None) -> bool:
    """value > floor, False when either is missing."""
    return value is not None and floor is not None and value > floor


def _at_least(value: float | None, floor: float | None) -> bool:
    """value >= floor, False when either is missing."""
    return value is not None and floor is not None and value >= floor


def _gate_inputs(groups: Mapping[str, list], intervals: Mapping[str, dict | None]) -> dict:
    """The unrounded numbers the PREREG checks compare (the report shows them rounded)."""
    a70 = groups["a70"]
    a70_60 = [_excess(r, 60) for r in a70]
    year_means = {year: _mean([_excess(r, 60) for r in a70 if _year(r["day"]) == year])
                  for year in sorted({_year(r["day"]) for r in a70})}
    best = max(year_means, key=lambda y: year_means[y], default=None)
    return {
        "mean_60": _mean(a70_60), "mean_100": _mean([_excess(r, 100) for r in a70]),
        "median_60": statistics.median(a70_60) if a70_60 else None,
        "baseline_mean_60": _mean([_excess(r, 60) for r in groups["baseline"]]),
        # "Widest" interval (PREREG): every block length's lower bound must clear 0, so the lowest low decides.
        "interval_lows": {name: (i["low"] if i else None) for name, i in intervals.items()},
        "year_means": year_means, "best_year": best,
        "without_best_year_mean": _mean([_excess(r, 60) for r in a70 if _year(r["day"]) != best]),
        "worst_decile": {"a70": _worst_decile(a70_60), "b": _worst_decile([_excess(r, 60) for r in groups["b"]])},
        "stop_exits": {"a70": _stop_count(a70), "b": _stop_count(groups["b"])},
        "liquid_tercile_mean_60": _liquid_tercile_mean(a70),
    }


def _liquid_tercile_mean(a70: Sequence[Mapping[str, Any]]) -> float | None:
    """Unrounded 60 bp mean of the most liquid third of A70 (the report's "high" tercile), None when
    no row has a value (e.g. v1 rows): check g then fails."""
    return _mean([_excess(r, 60) for r in _terciles(a70)[2]])


def _stop_share_ok(stops: Mapping[str, tuple[int, int]]) -> bool:
    """A70's stop-exit share <= B's + 10 points, compared exactly as fractions."""
    (a_k, a_n), (b_k, b_n) = stops["a70"], stops["b"]
    margin = Fraction(WIDTH["stop_share_margin"]).limit_denominator(1000)
    return a_n > 0 and b_n > 0 and Fraction(a_k, a_n) <= Fraction(b_k, b_n) + margin


def _width_checks(g: Mapping[str, Any]) -> dict[str, bool]:
    """PREREG checks a-e and g on the unrounded gate inputs `g` (_gate_inputs)."""
    lows, worst = list(g["interval_lows"].values()), g["worst_decile"]
    positive_years = sum(_above(g["year_means"].get(y), 0.0) for y in WIDTH["years"])
    return {
        "a_mean_60bp_at_least_1pct": _at_least(g["mean_60"], WIDTH["mean_60bp"]),
        "a_mean_100bp_above_0": _above(g["mean_100"], 0.0),
        "a_widest_interval_above_0": bool(lows) and None not in lows and min(lows) > 0,
        "b_median_above_0": _above(g["median_60"], 0.0),
        "c_above_baseline": _above(g["mean_60"], g["baseline_mean_60"]),
        "d_positive_years": positive_years >= WIDTH["min_positive_years"],
        "d_without_best_year_above_0": _above(g["without_best_year_mean"], 0.0),
        "e_worst_decile": _at_least(worst["a70"], None if worst["b"] is None else worst["b"] - WIDTH["tail_margin_pts"]),
        "e_stop_share": _stop_share_ok(g["stop_exits"]),
        "g_liquid_tercile_above_0": _above(g["liquid_tercile_mean_60"], 0.0),
    }


def _width_blockers(size: Mapping[str, int], complete: bool) -> list[str]:
    """Why the run cannot decide (PREREG: NO DECISION), empty when it can."""
    censored = Fraction(size["no_outcome"], size["passes"] + size["no_outcome"]) if size["no_outcome"] else 0
    return [reason for reason, bad in (
        ("run incomplete", not complete),
        ("over 2% of A70 passes have no outcome (possible hidden losses)",
         censored > Fraction(WIDTH["max_no_outcome_share"]).limit_denominator(1000)),
        (f"A70 under {WIDTH['min_passes']} passes", size["passes"] < WIDTH["min_passes"]),
        (f"A70 in under {WIDTH['min_months']} months", size["months"] < WIDTH["min_months"]),
        (f"under {WIDTH['min_buys']} Buys: the tail check cannot be made", size["buys"] < WIDTH["min_buys"]),
    ) if bad]


def _rounded(value: float | None) -> float | None:
    """3-decimal display value."""
    return None if value is None else round(value, 3)


def _width_measures(groups: Mapping[str, list], g: Mapping[str, Any], intervals: Mapping[str, dict | None]) -> dict:
    """The decisive numbers for display (rounded; the gates use `g`)."""
    a70, (a_k, a_n), (b_k, b_n) = groups["a70"], g["stop_exits"]["a70"], g["stop_exits"]["b"]
    return {
        "a70_excess_60bp": _stats([_excess(r, 60) for r in a70]),
        "a70_excess_100bp": _stats([_excess(r, 100) for r in a70]),
        "baseline_excess_60bp": _stats([_excess(r, 60) for r in groups["baseline"]]),
        "a70_interval_90": {name: None if i is None else {"low": _rounded(i["low"]), "high": _rounded(i["high"]),
                                                          "draws": i["draws"]} for name, i in intervals.items()},
        "a70_widest_low": _rounded(min((v for v in g["interval_lows"].values() if v is not None), default=None)),
        "a70_by_year": {y: _stats([_excess(r, 60) for r in a70 if _year(r["day"]) == y]) for y in g["year_means"]},
        "best_year": g["best_year"],
        "a70_without_best_year": _stats([_excess(r, 60) for r in a70 if _year(r["day"]) != g["best_year"]]),
        "worst_decile_60bp": {k: _rounded(v) for k, v in g["worst_decile"].items()},
        "stop_exit_share": {"a70": _rounded(a_k / a_n) if a_n else None, "b": _rounded(b_k / b_n) if b_n else None},
    }


def _width_context(groups: Mapping[str, list], universe: str) -> dict:
    """Reported, not gates: B, A70 minus B, exits, minimum, non-overlap, gaps, A65 and the splits."""
    a70, b_60 = groups["a70"], [_excess(r, 60) for r in groups["b"]]
    a70_60 = [_excess(r, 60) for r in a70]
    kept = non_overlapping(a70)
    return {
        "b_excess_60bp": _stats(b_60),
        "a70_minus_b_mean": round(statistics.fmean(a70_60) - statistics.fmean(b_60), 3) if a70_60 and b_60 else None,
        "a70_exit_reasons": {k: sum(r["reason"] == k for r in a70) for k in sorted({r["reason"] for r in a70})},
        "a70_min_60bp": round(min(a70_60), 3) if a70_60 else None,
        "a70_non_overlapping_60bp": None if kept is None else _stats([_excess(r, 60) for r in kept]),
        "a70_gap_trades": sum(bool(r.get("gap_sessions")) for r in a70),
        "a70_without_gap_trades_60bp": _stats([_excess(r, 60) for r in a70 if not r.get("gap_sessions")]),
        "a65_excess_60bp": _stats([_excess(r, 60) for r in groups["a65"]]) if universe == "holdout" else None,
        "a70_split": _split(a70), "a65_split": _split(groups["a65"]),
        "a70_by_liquidity": liquidity_split(a70),
        "a70_liquid_third_100bp": _stats([_excess(r, 100) for r in _terciles(a70)[2]]),   # beside check g
    }


def _width_notes(a70: Sequence[Mapping[str, Any]], gate: Mapping[str, Any]) -> list[str]:
    """Plain-language warnings for the report (not gates): check g cannot be computed, or rests on
    only part of A70 (rows without a traded value are left out of the terciles)."""
    if gate["liquid_tercile_mean_60"] is None:
        return ["check g not computable: no A70 row has a traded_value_20d (v1 rows, or no A70 passes) -> g fails"]
    valued = sum(len(part) for part in _terciles(a70))
    if valued < len(a70):
        return [f"check g on {len(_terciles(a70)[2])} rows of a top third cut from {valued} of {len(a70)} "
                f"A70 rows ({len(a70) - valued} without a traded value)"]
    return []


def width_test(rows: Sequence[Mapping[str, Any]], *, complete: bool, universe: str) -> dict:
    """The pre-registered width test on one run (WIDTH TEST in the module docstring): gate inputs,
    checks a-e and g, NO DECISION floors (f, completeness, Buys), verdict and the reported context. An
    incomplete run reports only its blockers and size: a re-run must stay blind to its numbers."""
    groups = width_groups(rows)
    a70 = groups["a70"]
    size = {"passes": len(a70), "months": len({r["day"][:7] for r in a70}), "buys": len(groups["b"]),
            "no_outcome": len(groups["a70_no_outcome"])}
    blockers = _width_blockers(size, complete)
    decisive = universe == "holdout"
    head = {"universe": universe, "decisive": decisive, "blockers": blockers, "size": size}
    if not complete:
        return {**head, "verdict": "NO_DECISION" if decisive else "CONTEXT_ONLY (run incomplete)"}
    days = [r["day"] for r in rows if r.get("day")]
    months = calendar_months(min(days), max(days)) if days else []
    intervals = {f"{block}m": block_interval(a70, months, block) for block in BLOCK_MONTHS}
    gate = _gate_inputs(groups, intervals)
    checks = _width_checks(gate)
    verdict = "NO_DECISION" if blockers else ("PASS" if all(checks.values()) else "FAIL")
    return {**head, "verdict": verdict if decisive else f"CONTEXT_ONLY ({universe} run, not decisive; would be {verdict})",
            "checks": checks, **_width_measures(groups, gate, intervals), **_width_context(groups, universe),
            "gate_inputs": gate,
            "notes": _width_notes(a70, gate),
            "limits": "Stage-1 ranking is not replayed (every stock is evaluated every 5th session); "
                      "survivorship (stocks listed today); daily bars; D-open entry without spread; flat costs."}


COUNT_KEYS = ("decisions", "passes", "errors", "rejects", "buys", "actions")


def summarise(rows: Iterable[Mapping[str, Any]], *, complete: bool = True, universe: str = "nifty500") -> dict:
    """Per variant summary, the unconditional baseline, the pre-registered choice rule's winner
    (None if no variant qualifies or the run is incomplete) and the width test. An incomplete run
    is blind: counts only, no outcome statistic anywhere (a repeat run must not have seen them)."""
    rows = list(rows)
    variants = {variant: _variant_summary([r for r in rows if r["variant"] == variant]) for variant in VARIANTS}
    if not complete:
        return {"version": VERSION, "horizon": HORIZON, "step": STEP, "costs_bps": COSTS_BPS,
                "stocks": len({r["ticker"] for r in rows}), "days": len({r["day"] for r in rows}),
                "complete": False, "variants": {v: {k: e[k] for k in COUNT_KEYS} for v, e in variants.items()},
                "baseline_excess_60bp": None, "choice_rule_winner": None, "universe": universe,
                "width_test": width_test(rows, complete=False, universe=universe)}
    base = [r for r in rows if r["variant"] == BASELINE and r.get("pass")]
    eligible = {v: e for v, e in variants.items()
                if e["buy_excess_60bp"].get("n", 0) >= MIN_TRADES and e["buy_excess_100bp"].get("mean", -1) > 0}
    baseline_60 = _stats([r["gross_pct"] - 0.6 - r["nifty_pct"] for r in base])
    for entry in variants.values():   # read beside the absolute check: survivorship lifts both
        entry["buy_excess_60bp_minus_baseline"] = (
            round(entry["buy_excess_60bp"]["mean"] - baseline_60["mean"], 3)
            if entry["buy_excess_60bp"].get("n") and baseline_60.get("n") else None)
    return {"version": VERSION, "horizon": HORIZON, "step": STEP, "costs_bps": COSTS_BPS,
            "stocks": len({r["ticker"] for r in rows}), "days": len({r["day"] for r in rows}),
            "complete": complete, "variants": variants, "baseline_excess_60bp": baseline_60,
            "choice_rule_winner": (max(eligible, key=lambda v: eligible[v]["buy_excess_60bp"]["mean"])
                                   if eligible and complete else None),
            "universe": universe, "width_test": width_test(rows, complete=complete, universe=universe)}


# --------------------------------------------------------------------- data fetch ---

def nifty500(client) -> list[tuple[str, str]]:
    """(symbol, Upstox instrument key) for the current NIFTY 500 list (survivorship: disclosed)."""
    response = client.get(NIFTY500_URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv"}, timeout=30)
    response.raise_for_status()
    members = []
    for row in csv.DictReader(io.StringIO(response.text)):
        symbol, isin = (row.get("Symbol") or "").strip(), (row.get("ISIN Code") or "").strip()
        if SYMBOL.fullmatch(symbol) and ISIN.fullmatch(isin):
            members.append((symbol, f"NSE_EQ|{isin}"))
    if len(members) < 400:
        raise RuntimeError(f"NIFTY 500 list looks wrong: {len(members)} members")
    return members


def holdout(client, nifty: Sequence[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """(symbol, Upstox instrument key) for the live collector's NSE EQ universe minus the current
    NIFTY 500 (`nifty`, fetched when None), removed by instrument key (NSE_EQ|ISIN) AND by symbol, so
    an ISIN change (split, merger) cannot slip a seen stock in: the stocks the 17 Nov replay never
    saw. Sorted, so every shard splits the same list (universe_digest proves it)."""
    nifty = nifty500(client) if nifty is None else nifty
    seen_keys, seen_symbols = {key for _s, key in nifty}, {symbol for symbol, _k in nifty}
    members = sorted({(str(row["trading_symbol"]), str(row["instrument_key"])) for row in fetch_nse_universe(client)
                      if str(row["instrument_key"]) not in seen_keys and str(row["trading_symbol"]) not in seen_symbols})
    if len(members) < 1000:
        raise RuntimeError(f"holdout universe looks wrong: {len(members)} members")
    return members


def resolve_members(client, universe_name: str, token: str) -> dict:
    """The `members` step: the universe's list, resolved ONCE per run (every shard then splits the
    same list, whatever day it starts), its digest, the NIFTY 500 digest it was built against (for the
    holdout: equal to the 17 Nov shards' universe_sha256 means exactly the seen list was removed), the
    shard count, and as_of = NIFTY's last published daily bar: every shard cuts its data there, so a
    run crossing the next day's publication (~07:00 IST) still replays one data set."""
    index_bars = load_bars(client, token, NIFTY_KEY, today=dt.datetime.now(IST).date(), days=30)
    as_of = index_bars.index[-1].date()
    nifty = nifty500(client)
    members = holdout(client, nifty) if universe_name == "holdout" else nifty
    return {"universe": universe_name, "members": [list(m) for m in members], "sha256": universe_digest(members),
            "nifty500_sha256": universe_digest(nifty), "shards": UNIVERSES[universe_name],
            "as_of": as_of.isoformat()}


def read_members(path: Path) -> dict:
    """A `members` file as {universe, members, nifty500_sha256, as_of}, refusing one whose list does
    not match its digest. as_of (the members day) is every shard's history end, so shards started
    hours apart still replay the same days."""
    payload = json.loads(path.read_text())
    members = [(str(symbol), str(key)) for symbol, key in payload["members"]]
    if payload.get("universe") not in UNIVERSES or universe_digest(members) != payload.get("sha256"):
        raise ValueError(f"{path} is not an intact members file")
    as_of = dt.date.fromisoformat(payload["as_of"]) if payload.get("as_of") else None
    return {"universe": payload["universe"], "members": members,
            "nifty500_sha256": payload.get("nifty500_sha256"), "as_of": as_of}


SCAN_BLACKOUTS = ((dt.time(9, 55), dt.time(10, 40)), (dt.time(14, 25), dt.time(15, 10)))   # IST, Mon-Fri
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def wait_outside_scans(now: Callable[[], dt.datetime] = lambda: dt.datetime.now(IST),
                       sleep: Callable[[float], None] = time.sleep) -> float:
    """Sleep through the live collector's scan windows (10:07 / 14:37 IST, weekdays, padded): the
    replay shares its Upstox history quota. Returns the seconds slept."""
    moment = now().astimezone(IST)
    if moment.weekday() >= 5:
        return 0.0
    for start, end in SCAN_BLACKOUTS:
        if start <= moment.time() < end:
            seconds = (dt.datetime.combine(moment.date(), end, IST) - moment).total_seconds()
            LOGGER.info("live scan window: pausing %.0f s", seconds)
            sleep(seconds)
            return seconds
    return 0.0


def load_bars(client, token: str, key: str, *, today: dt.date, days: int, pause: float = 0.25,
              attempts: int = FETCH_ATTEMPTS, rate_wait: float = 60.0) -> pd.DataFrame:
    """Daily bars as the app reads them (fetch_daily_candles), indexed by date, oldest first. A failed
    request is retried: after rate_wait x attempt when the provider says HTTP 429 (its limit is per
    30 minutes, a short pause would not help), else after 8 x pause x attempt (5xx, timeout, error
    body). A rejected token (PermissionError) never is. The last failure is raised (the stock is listed)."""
    for attempt in range(1, attempts + 1):
        wait_outside_scans()
        try:
            frame = fetch_daily_candles(client, token, key, days, today=today)
            break
        except PermissionError:
            raise
        except Exception as exc:
            if attempt >= attempts:
                raise
            limited = re.search(r"\bHTTP 429\b", str(exc)) is not None
            LOGGER.warning("history for %s failed (%s%s); retry %d of %d", key, type(exc).__name__,
                           ", rate limit" if limited else "", attempt, attempts - 1)
            time.sleep((rate_wait if limited else 8 * pause) * attempt)
    time.sleep(pause)
    return daily_index(frame)


def daily_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Naive IST session dates, oldest first, one row per day (aware stamps converted to IST first)."""
    index = pd.DatetimeIndex(frame.index)
    if index.tz is not None:
        index = index.tz_convert("Asia/Kolkata").tz_localize(None)
    frame = frame.set_axis(index.normalize()).sort_index()
    return frame[~frame.index.duplicated(keep="last")]


# ---------------------------------------------------------------------------- CLI ---

def _shard(items: Sequence, shard: int, shards: int) -> list:
    """Every shards-th item starting at shard (stable, disjoint, complete)."""
    if not 0 <= shard < shards:
        raise ValueError("shard must be in [0, shards)")
    return [item for position, item in enumerate(items) if position % shards == shard]


def universe_digest(members: Sequence[tuple[str, str]]) -> str:
    """Fingerprint of the member list, so shards can prove they split the same list."""
    return hashlib.sha256(json.dumps(sorted(members)).encode()).hexdigest()


def run_shard(client, token: str, *, shard: int, shards: int, out: Path, today: dt.date, days: int,
              universe_name: str = "nifty500", members_file: Path | None = None) -> dict:
    """Replay this shard's stocks and write rows; returns counts. The list comes from `members_file`
    (the workflow's one `members` step) or, for local use, is fetched for `universe_name`."""
    nifty500_sha256 = None
    if members_file is not None:
        listing = read_members(members_file)
        universe_name, universe, nifty500_sha256 = listing["universe"], listing["members"], listing["nifty500_sha256"]
        today = listing["as_of"] or today
    else:
        universe = {"nifty500": nifty500, "holdout": holdout}[universe_name](client)   # looked up per call
    members = _shard(universe, shard, shards)
    end = pd.Timestamp(today)
    nifty = load_bars(client, token, NIFTY_KEY, today=today, days=days)
    nifty = nifty[nifty.index <= end]
    rows, failed = [], []
    for symbol, key in members:
        try:
            bars = load_bars(client, token, key, today=today, days=days)
            bars = bars[bars.index <= end]      # one data set: nothing published after as_of
            rows.extend(replay_stock(symbol, key, bars, nifty))
        except PermissionError:
            raise
        except Exception as exc:  # a fetch or replay failure loses that stock only; it is listed
            failed.append({"symbol": symbol, "error": type(exc).__name__})
            continue
        LOGGER.info("replayed %s (%d rows so far)", symbol, len(rows))
    out.write_text(json.dumps({"version": VERSION, "shard": shard, "shards": shards, "universe": universe_name,
                               "universe_sha256": universe_digest(universe), "universe_size": len(universe),
                               "nifty500_sha256": nifty500_sha256, "as_of": str(today),
                               "nifty_last_day": str(nifty.index[-1].date()) if len(nifty) else None,
                               "rows": rows, "failed": failed}, default=str))
    return {"stocks": len(members), "failed": len(failed), "rows": len(rows)}


def _run(args) -> int:
    """The `run` command: one shard with the Analytics Token from the environment."""
    import requests
    token = os.environ.get("UPSTOX_ANALYTICS_TOKEN", "")
    if not token:
        print("UPSTOX_ANALYTICS_TOKEN is not set", file=sys.stderr)
        return 2
    counts = run_shard(requests.Session(), token, shard=args.shard, shards=args.shards, out=args.out,
                       today=dt.date.today(), days=args.days, universe_name=args.universe,
                       members_file=args.members_file)
    print(json.dumps(counts))
    return 0


def _members(args) -> int:
    """The `members` command: resolve the list once; with --github-output also write the shard matrix
    (shards=N, matrix=[0..N-1]) so the workflow's matrix and shard count come from UNIVERSES alone."""
    import requests
    token = os.environ.get("UPSTOX_ANALYTICS_TOKEN", "")
    if not token:
        print("UPSTOX_ANALYTICS_TOKEN is not set", file=sys.stderr)
        return 2
    payload = resolve_members(requests.Session(), args.universe, token)
    args.out.write_text(json.dumps(payload))
    print(json.dumps({k: payload[k] for k in ("universe", "sha256", "nifty500_sha256", "shards")}
                     | {"members": len(payload["members"])}))
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write(f"shards={payload['shards']}\nmatrix={json.dumps(list(range(payload['shards'])))}\n")
    return 0


def _universe_problems(universes: set, shards: int | None) -> tuple[list[str], int]:
    """A problem unless the shards name one known universe; the shard count to expect (`shards`
    when given, else that universe's count)."""
    named = next(iter(universes)) if len(universes) == 1 else None
    problems = [] if named in UNIVERSES else [f"universes {sorted(map(str, universes))}"]
    return problems, shards if shards is not None else UNIVERSES.get(named, SHARDS)


def shard_problems(seen: Sequence[tuple], *, failed: int = 0, stocks: int = 0,
                   shards: int | None = None) -> list[str]:
    """Why a set of shard headers (version, shard, shards, list digest, universe) is not one complete
    run (empty when it is): every one of the `shards` shards once (default: the universe's count),
    one known version, one universe and one member list, and at most MAX_FAILED_SHARE of the
    universe failed."""
    problems, expected_shards = _universe_problems({s[4] for s in seen}, shards)
    if seen and {s[2] for s in seen} != {expected_shards}:
        problems.append(f"shard count in the files is not {expected_shards}")
    universe = stocks + failed
    if universe and failed / universe > MAX_FAILED_SHARE:
        problems.append(f"{failed} of {universe} stocks failed (over {MAX_FAILED_SHARE:.0%})")
    versions, totals, lists = {s[0] for s in seen}, {s[2] for s in seen}, {s[3] for s in seen}
    if len(versions) != 1 or not versions <= set(KNOWN_VERSIONS):
        problems.append(f"versions {sorted(map(str, versions))}")
    if len(totals) != 1 or len(lists) != 1:
        problems.append("shards disagree on the shard count or the member list")
    expected = set(range(next(iter(totals)))) if len(totals) == 1 and isinstance(next(iter(totals)), int) else set()
    present = [s[1] for s in seen]
    if sorted(present) != sorted(expected):
        problems.append(f"shards present {sorted(map(str, present))}, expected {sorted(expected)}")
    return problems


def _summarise_files(files: Sequence[Path], out: Path, *, shards: int | None = None,
                     source_run: str | None = None, seen_sha256: str | None = None) -> int:
    """The `summarise` command: merge shard files, write the report, print the headline. With
    `seen_sha256` (the 17 Nov shards' universe_sha256) a holdout report says whether exactly that
    NIFTY 500 list was removed (seen_list_removed)."""
    rows, failed, seen, sizes, removed, ends = [], [], [], set(), set(), set()
    for path in files:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise ValueError(f"{path} is not a replay shard file")
        seen.append((payload.get("version"), payload.get("shard"), payload.get("shards"),
                     payload.get("universe_sha256"), payload.get("universe", "nifty500")))   # v1: no field
        sizes.add(payload.get("universe_size"))
        removed.add(payload.get("nifty500_sha256"))
        ends.add((payload.get("as_of"), payload.get("nifty_last_day")))
        rows.extend(payload["rows"])
        failed.extend(payload.get("failed", []))
    # The 2% failure rule counts against the whole member list (v2 headers carry it); v1 headers do
    # not, so the 17 Nov run keeps its own rule: stocks with rows plus failed stocks.
    size = next(iter(sizes)) if len(sizes) == 1 and None not in sizes else None
    stocks = size - len(failed) if size else len({r.get("ticker") for r in rows if r.get("ticker")})
    problems = shard_problems(seen, failed=len(failed), stocks=stocks, shards=shards)
    if len(sizes) > 1:
        problems.append("shards disagree on the universe size")
    if len(ends) > 1:
        problems.append("shards disagree on as_of or NIFTY's last day (different data sets)")
    universes = {s[4] for s in seen}
    universe = next(iter(universes)) if len(universes) == 1 else "mixed"
    report = summarise(rows, complete=not problems, universe=universe)
    report.update(fetch_failures=len(failed), shards_present=sorted(s[1] for s in seen if s[1] is not None),
                  problems=problems, universe_size=size, source_run=source_run,
                  universe_sha256=sorted({str(s[3]) for s in seen}), nifty500_sha256=sorted(map(str, removed)),
                  seen_list_removed=None if not seen_sha256 or universe != "holdout" else removed == {seen_sha256})
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({v: {"passes": e["passes"], "buys": e["buys"], "buy_excess_60bp": e.get("buy_excess_60bp")}
                      for v, e in report["variants"].items()}, indent=2))
    print("choice_rule_winner:", report["choice_rule_winner"], "| universe_sha256:", report["universe_sha256"],
          "| nifty500_sha256:", report["nifty500_sha256"], "| seen_list_removed:", report["seen_list_removed"])
    width = report["width_test"]
    print("width_test:", json.dumps({k: width.get(k) for k in ("universe", "verdict", "blockers", "checks", "size",
                                                               "a70_excess_60bp", "a70_widest_low")}, indent=2))
    return 0


def _sha256_arg(value: str) -> str | None:
    """'' (no check) or 64 lowercase hex characters."""
    if value == "":
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise argparse.ArgumentTypeError("a sha256 is 64 lowercase hex characters")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """`members` (resolve the list once), `run` one shard (needs UPSTOX_ANALYTICS_TOKEN) or
    `summarise` shard files into a report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--shard", type=int, required=True)
    run.add_argument("--shards", type=int, required=True)
    run.add_argument("--days", type=int, default=3000)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--universe", choices=sorted(UNIVERSES), default="nifty500")
    run.add_argument("--members-file", type=Path, default=None,
                     help="the `members` step's list (default: fetch it in this shard)")
    listing = sub.add_parser("members")
    listing.add_argument("--universe", choices=sorted(UNIVERSES), required=True)
    listing.add_argument("--out", type=Path, required=True)
    listing.add_argument("--github-output", type=Path, default=None)
    summary = sub.add_parser("summarise")
    summary.add_argument("files", type=Path, nargs="+")
    summary.add_argument("--out", type=Path, required=True)
    summary.add_argument("--shards", type=int, default=None,
                         help="expected shard count (default: the files' universe's count)")
    summary.add_argument("--source-run", default=None, help="the run whose shards these are (recorded)")
    summary.add_argument("--seen-sha256", default=None, type=_sha256_arg,
                         help="the 17 Nov shards' universe_sha256: report whether the holdout removed exactly it")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "members":
        return _members(args)
    if args.command == "run":
        return _run(args)
    return _summarise_files(args.files, args.out, shards=args.shards, source_run=args.source_run,
                            seen_sha256=args.seen_sha256)


if __name__ == "__main__":
    raise SystemExit(main())
