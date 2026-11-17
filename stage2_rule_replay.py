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
  outcome  app_runtime.trade_outcome on bars D..D+HORIZON-1 (entry D open, stop first, gap
           stop at the open, target never improved), net of 30/60/100 bp round trip, minus
           NIFTY's return from D's open to the exit day's close (excess);
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

LIMITS (reported with every result): current NIFTY 500 members (survivorship bias, which also
inflates the absolute check at 100 bp: compare against the baseline); daily bars only (no minute
order inside a day: a bar touching both levels counts as a stop, which costs tighter stops more);
entry at D's open, not 10:07; Upstox daily history is split/bonus adjusted, dividends are not; no
quote spread (live collector quotes carry none either: live round trip ~14.5 bp); excess runs to
the exit day's close; no governance gate; Buys cluster on dates, so t-stats overstate certainty;
costs are scenarios, not fills. Development evidence, not a performance claim.

SIDE EFFECTS: none on the database. The fetch step reads NSE's NIFTY 500 list and Upstox daily
candles (read-only, free); the run writes JSON files only.
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
import re
import statistics
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
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

LOGGER = logging.getLogger("stage2_rule_replay")

VERSION = "stage2-rule-replay-v1"
HORIZON = APP_DEFAULT_SETTINGS.custom_days            # 15 sessions, the app default
SHARDS = 8                                            # the workflow's matrix
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

def outcome(bars: pd.DataFrame, start: int, stop: float, target: float, nifty: pd.DataFrame) -> dict | None:
    """Entry at bar `start`'s open, HORIZON sessions; gross % and NIFTY % over the same days."""
    window = bars.iloc[start:start + HORIZON]
    if len(window) < HORIZON:
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
            "exit_index": start + traded["offset"]}


BASELINE = "baseline-open-time-exit"


def _positive(value) -> bool:
    """A finite price above zero (None and NaN are not)."""
    try:
        return value is not None and math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def baseline(bars: pd.DataFrame, start: int, nifty: pd.DataFrame) -> dict:
    """Unconditional comparison on the same stock and day: buy D's open, sell the HORIZON-th close."""
    window = bars.iloc[start:start + HORIZON]
    if len(window) < HORIZON:
        return {"pass": False, "category": "BaselineUnavailable"}
    first, last = window.index[0], window.index[-1]
    nifty_open, nifty_close = nifty["Open"].get(first), nifty["Close"].get(last)
    entry, close = float(window.iloc[0]["Open"]), float(window.iloc[-1]["Close"])
    if not (len(window) == HORIZON and _positive(entry) and _positive(close)
            and _positive(nifty_open) and _positive(nifty_close)):
        return {"pass": False, "category": "BaselineUnavailable"}
    return {"pass": True, "gross_pct": (close / entry - 1) * 100, "reason": "TIME",
            "nifty_pct": (float(nifty_close) / float(nifty_open) - 1) * 100}


def stock_offset(ticker: str, step: int = STEP) -> int:
    """A fixed per-stock start offset in [0, step): spreads replay days over weekdays and expiries."""
    return int(hashlib.sha256(ticker.encode()).hexdigest(), 16) % step


def replay_days(bars: pd.DataFrame, nifty: pd.DataFrame, *, offset: int = 0, step: int = STEP) -> list[int]:
    """Positions of the replay days: every `step`-th session from `offset` that NIFTY also traded,
    once both live history windows lie inside the data, with a full horizon after it."""
    if bars.empty or nifty.empty:
        return []
    shared = set(nifty.index)
    first = max(bars.index[0] + pd.Timedelta(days=HISTORY_DAYS), nifty.index[0] + pd.Timedelta(days=NIFTY_HISTORY_DAYS))
    return [i for i in range(offset, len(bars) - HORIZON + 1, step)
            if bars.index[i] >= first and bars.index[i] in shared]


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


def summarise(rows: Iterable[Mapping[str, Any]], *, complete: bool = True) -> dict:
    """Per variant summary, the unconditional baseline, and the pre-registered choice rule's winner
    (None if no variant qualifies or the run is incomplete)."""
    rows = list(rows)
    variants = {variant: _variant_summary([r for r in rows if r["variant"] == variant]) for variant in VARIANTS}
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
                                   if eligible and complete else None)}


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


def load_bars(client, token: str, key: str, *, today: dt.date, days: int, pause: float = 0.25) -> pd.DataFrame:
    """Daily bars as the app reads them (fetch_daily_candles), indexed by date, oldest first."""
    frame = fetch_daily_candles(client, token, key, days, today=today)
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


def run_shard(client, token: str, *, shard: int, shards: int, out: Path, today: dt.date, days: int) -> dict:
    """Fetch this shard's stocks and NIFTY, replay them, write rows; returns counts."""
    universe = nifty500(client)
    members = _shard(universe, shard, shards)
    nifty = load_bars(client, token, NIFTY_KEY, today=today, days=days)
    rows, failed = [], []
    for symbol, key in members:
        try:
            bars = load_bars(client, token, key, today=today, days=days)
            rows.extend(replay_stock(symbol, key, bars, nifty))
        except PermissionError:
            raise
        except Exception as exc:  # a fetch or replay failure loses that stock only; it is listed
            failed.append({"symbol": symbol, "error": type(exc).__name__})
            continue
        LOGGER.info("replayed %s (%d rows so far)", symbol, len(rows))
    out.write_text(json.dumps({"version": VERSION, "shard": shard, "shards": shards,
                               "universe_sha256": universe_digest(universe), "rows": rows,
                               "failed": failed}, default=str))
    return {"stocks": len(members), "failed": len(failed), "rows": len(rows)}


def _run(args) -> int:
    """The `run` command: one shard with the Analytics Token from the environment."""
    import requests
    token = os.environ.get("UPSTOX_ANALYTICS_TOKEN", "")
    if not token:
        print("UPSTOX_ANALYTICS_TOKEN is not set", file=sys.stderr)
        return 2
    counts = run_shard(requests.Session(), token, shard=args.shard, shards=args.shards, out=args.out,
                       today=dt.date.today(), days=args.days)
    print(json.dumps(counts))
    return 0


def shard_problems(seen: Sequence[tuple], *, failed: int = 0, stocks: int = 0,
                   shards: int = SHARDS) -> list[str]:
    """Why a set of shard headers is not one complete run (empty when it is): every one of the
    `shards` shards once, one version and NIFTY 500 list, and at most MAX_FAILED_SHARE of the
    universe failed."""
    problems = []
    if seen and {s[2] for s in seen} != {shards}:
        problems.append(f"shard count in the files is not {shards}")
    universe = stocks + failed
    if universe and failed / universe > MAX_FAILED_SHARE:
        problems.append(f"{failed} of {universe} stocks failed (over {MAX_FAILED_SHARE:.0%})")
    versions, totals, lists = {s[0] for s in seen}, {s[2] for s in seen}, {s[3] for s in seen}
    if versions != {VERSION}:
        problems.append(f"versions {sorted(map(str, versions))}")
    if len(totals) != 1 or len(lists) != 1:
        problems.append("shards disagree on the shard count or the NIFTY 500 list")
    expected = set(range(next(iter(totals)))) if len(totals) == 1 and isinstance(next(iter(totals)), int) else set()
    present = [s[1] for s in seen]
    if sorted(present) != sorted(expected):
        problems.append(f"shards present {sorted(map(str, present))}, expected {sorted(expected)}")
    return problems


def _summarise_files(files: Sequence[Path], out: Path, *, shards: int = SHARDS) -> int:
    """The `summarise` command: merge shard files, write the report, print the headline."""
    rows, failed, seen = [], [], []
    for path in files:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise ValueError(f"{path} is not a replay shard file")
        seen.append((payload.get("version"), payload.get("shard"), payload.get("shards"),
                     payload.get("universe_sha256")))
        rows.extend(payload["rows"])
        failed.extend(payload.get("failed", []))
    stocks = len({r.get("ticker") for r in rows if r.get("ticker")})
    problems = shard_problems(seen, failed=len(failed), stocks=stocks, shards=shards)
    report = summarise(rows, complete=not problems)
    report.update(fetch_failures=len(failed), shards_present=sorted(s[1] for s in seen if s[1] is not None),
                  problems=problems)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({v: {"passes": e["passes"], "buys": e["buys"], "buy_excess_60bp": e["buy_excess_60bp"]}
                      for v, e in report["variants"].items()}, indent=2))
    print("choice_rule_winner:", report["choice_rule_winner"])
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """`run` one shard (needs UPSTOX_ANALYTICS_TOKEN) or `summarise` shard files into a report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--shard", type=int, required=True)
    run.add_argument("--shards", type=int, required=True)
    run.add_argument("--days", type=int, default=3000)
    run.add_argument("--out", type=Path, required=True)
    summary = sub.add_parser("summarise")
    summary.add_argument("files", type=Path, nargs="+")
    summary.add_argument("--out", type=Path, required=True)
    summary.add_argument("--shards", type=int, default=SHARDS)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return _run(args) if args.command == "run" else _summarise_files(args.files, args.out, shards=args.shards)


if __name__ == "__main__":
    raise SystemExit(main())
