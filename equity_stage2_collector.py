"""Shadow-only Stage-2 for the scheduled collector. It never places orders.

The scheduled scan (scheduled_collector.py, `scan` mode) already runs Stage-1
and archives the whole PIT universe. When `SCHEDULED_STAGE2_SHADOW` is enabled,
this module then runs app.py's Stage-2 decision core
(`equity_stage2_decision.evaluate_stage2`, a parity-tested copy) on every
Stage-1-shortlisted ticker, with the app's default scan settings, and archives
the result as separate shadow evidence:

* one immutable `DECISION_BATCH_EVALUATED` ledger event, aggregate
  ``scan:<run_id>:stage2-shadow``, covering the COMPLETE shortlist: every ticker
  is EVALUATED (pass or reject, with the app's reject category/reason) or
  NOT_EVALUATED (with the reason the data needed to decide was missing);
* one `scanner_observations` row per shortlisted ticker, strategy version
  `STAGE2_SHADOW_VERSION`, written only after that event is durable. Like the
  Stage-1 rows, a row whose evidence is in the ledger keeps only a pointer.

Stage-1 rows and the Stage-1 batch are untouched: they still say Stage-2 was not
run by the Stage-1 scanner. Stage-2 runs after all Stage-1 evidence is
committed, so a Stage-2 failure can never lose Stage-1 evidence.

What the shadow result means (and does not mean)
------------------------------------------------
`stage2_pass` = the candidate passed every Stage-2 SIGNAL gate. The live app's
governance step (manual quote verification, model registry, signers) is NOT
evaluated here (`governance_evaluated: False`), so the app could still reject
it. The ledger action is therefore only ever "Watch" (passed) or "No Trade";
the app's would-be action ("Buy"/"Watch") is kept as data in `signal_action`.

How the inputs match the app
----------------------------
* History: app.py fetches 1200 days of Upstox V3 daily candles, parses them
  with `_history_to_dataframe`, writes them to its SQLite candle cache and
  returns the re-read window. On GitHub every run is a cold cache, so this
  module does exactly that in an in-memory SQLite with the app's SQL
  (`cold_cache_history`). A warm app cache can hold different rows (older
  fetches, incremental refreshes); that is an app-side difference to compare
  in Phase 4, not something to copy.
* Features: computed from scratch (`ComputeOnlyFeatureStore`), as the app does
  on a feature-cache miss.
* NIFTY 50: 400 days, parsed the same way, fetched once per run (app.py
  fetches it once per page run).
* Quote: the Stage-1 snapshot (Upstox Full Market Quote V3). The decision core
  reads bid/ask only from `market_data.bid_price/ask_price`, which this snapshot
  does not carry (its depth is under `market_depth`), so costs are modelled
  without a measured spread - exactly as in app.py's Full NSE scan, whose
  full-universe quotes are REST LTP + OHLC. (The app's Quick scan over visible
  instruments can carry websocket bid/ask and so estimate a different cost.)
* `market_open`: the exchange status Stage-1 already verified (NORMAL_OPEN).

A data failure is never recorded as a strategy decision: if a history or the
NIFTY fetch fails, or a history index is not a clean DatetimeIndex, the ticker
is NOT_EVALUATED. A fetch that succeeds with too few candles is the app's own
"Data" reject, so it stays EVALUATED.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import sqlite3
import time
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

import trade_contracts
from decision_evidence import DecisionEvidenceSpine
from equity_observation_capture import INPUTS as CAPTURE_INPUTS
from equity_observation_capture import EquityCapture
from equity_stage2_decision import evaluate_stage2
from equity_stage2_engine import _history_to_dataframe, normalize_market_timestamp_series
from prediction_validation import TARGET_VERSION
from risk_engine import RiskEngine

LOGGER = logging.getLogger(__name__)
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

STAGE2_SHADOW_VERSION = "equity-stage2-scheduled-shadow-v1"
STAGE2_CODE_VERSION = "v22.2-STAGE2-SHADOW-COLLECTION"
STAGE2_RUN_SUFFIX = ":stage2-shadow"
ENABLE_ENV = "SCHEDULED_STAGE2_SHADOW"
BUDGET_ENV = "SCHEDULED_STAGE2_BUDGET_SECONDS"
DEFAULT_BUDGET_SECONDS = 900
REQUEST_PAUSE_SECONDS = 0.2
UPSTOX_API = "https://api.upstox.com"
NIFTY_KEY = "NSE_INDEX|Nifty 50"
HISTORY_DAYS = 1200        # evaluate_stage2 requests exactly this (app.py's evaluate_stock)
NIFTY_HISTORY_DAYS = 400   # app.py's nifty_hist_df fetch
HISTORY_SOURCE = "Upstox V3 historical-candle days/1 (cold-cache read-back)"
COLUMNS = ["Open", "High", "Low", "Close", "Volume", "OI"]
NOT_EVALUATED = "NOT_EVALUATED"
EVALUATED = "EVALUATED"
FEATURES_RETENTION = "ledger_v1"

# Everything whose code shapes a Stage-2 shadow decision (pinned by a test to the
# local import closure of this module, plus the Stage-1 code that picks the shortlist).
STAGE2_CODE_FILES = (
    "app_runtime.py", "decision_evidence.py", "equity_observation_capture.py",
    "equity_scan_profiling.py", "equity_stage2_collector.py", "equity_stage2_decision.py",
    "equity_stage2_engine.py", "evidence_ledger.py", "feature_store.py", "live_evidence.py",
    "observability.py", "prediction_validation.py", "quantitative_services.py", "risk_engine.py",
    "scanner_funnel.py", "scheduled_collector.py", "technical_indicators.py", "trade_contracts.py",
)


@dataclasses.dataclass(frozen=True)
class ScanSettings:
    """The app's scan settings. Defaults = app.py's widget defaults (test-pinned)."""

    custom_days: int = 15
    max_stock_price: float = 50000.0
    require_weekly_align: bool = False
    use_advanced_signal_filters: bool = False
    investment_capital: float = 1000000.0
    max_risk_pct: float = 2.0
    max_position_pct: float = 20.0


APP_DEFAULT_SETTINGS = ScanSettings()


class HistoryUnavailable(RuntimeError):
    """A history request failed: the ticker cannot be evaluated (not a reject)."""


class LeaseLost(RuntimeError):
    """The collector lease was lost; a fenced worker must stop writing."""


def stage2_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """True only when the operator switched the shadow Stage-2 on explicitly."""
    value = str((os.environ if environ is None else environ).get(ENABLE_ENV) or "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def budget_seconds(environ: Mapping[str, str] | None = None) -> float:
    """Wall-clock budget for the whole shortlist; invalid values use the default."""
    raw = (os.environ if environ is None else environ).get(BUDGET_ENV)
    try:
        value = float(raw) if raw not in (None, "") else float(DEFAULT_BUDGET_SECONDS)
    except (TypeError, ValueError):
        value = float(DEFAULT_BUDGET_SECONDS)
    return value if value > 0 else float(DEFAULT_BUDGET_SECONDS)


def stage2_hashes(settings: ScanSettings = APP_DEFAULT_SETTINGS, *,
                  root: Path | None = None, stage1_top_n: int | None = None) -> tuple[str, str, str]:
    """(code, config, policy) digests binding the shadow evidence to its source."""
    base = root or Path(__file__).resolve().parent
    code = hashlib.sha256()
    for name in STAGE2_CODE_FILES:
        code.update(name.encode())
        code.update((base / name).read_bytes())
    # Same parse as scheduled_collector's Stage-1 (it passes the value it used).
    top_n = stage1_top_n if stage1_top_n is not None else max(
        1, int(os.environ.get("SCHEDULED_STAGE1_TOP_N", "150")))
    config = hashlib.sha256(json.dumps({
        "settings": dataclasses.asdict(settings),
        "history_days": HISTORY_DAYS, "nifty_history_days": NIFTY_HISTORY_DAYS,
        "history_source": HISTORY_SOURCE, "stage1_top_n": int(top_n),
        "shadow_only": True, "governance_evaluated": False,
    }, sort_keys=True).encode()).hexdigest()
    policy_path = base / "resilience_policy.json"
    policy = (hashlib.sha256(policy_path.read_bytes()).hexdigest()
              if policy_path.exists() else "unavailable")
    return code.hexdigest(), config, policy


# ---------------------------------------------------------------- history ---

def fetch_daily_candles(client, token: str, instrument_key: str, days: int, *,
                        today: dt.date) -> pd.DataFrame:
    """app.py's `_fetch_upstox_history_impl` request, parsed by its own parser.

    Differs only in failure handling: app.py turns any failure into an empty frame
    (which it then rejects as "Data"); here a failure raises, so it is recorded as
    NOT_EVALUATED instead of a strategy reject.
    """
    start = today - dt.timedelta(days=max(int(days), 30))
    encoded = urllib.parse.quote(str(instrument_key), safe="")
    url = f"{UPSTOX_API}/v3/historical-candle/{encoded}/days/1/{today.isoformat()}/{start.isoformat()}"
    response = client.get(
        url, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        timeout=(5, 25),
    )
    if response.status_code in {401, 403}:
        raise PermissionError("Upstox rejected the Analytics Token")
    if response.status_code != 200:
        raise HistoryUnavailable(f"Historical candle API returned HTTP {response.status_code}")
    # An HTTP 200 can still carry a provider error or a changed schema. app.py
    # reads those as "no candles" (a Data reject); here they are a fetch failure.
    try:
        payload = response.json()
    except ValueError as exc:
        raise HistoryUnavailable("Historical candle API returned a non-JSON body") from exc
    if not isinstance(payload, Mapping) or payload.get("status") not in (None, "success"):
        raise HistoryUnavailable("Historical candle API returned an error body")
    data = payload.get("data")
    candles = data.get("candles") if isinstance(data, Mapping) else None
    if not isinstance(candles, list):
        raise HistoryUnavailable("Historical candle API response has no candle list")
    return _history_to_dataframe(candles)


# app.py's own SQL (whitespace aside; a test compares the texts).
_CANDLE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS candles (
        instrument_key TEXT NOT NULL,
        dt TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        oi REAL,
        PRIMARY KEY (instrument_key, dt)
    )
"""
_CANDLE_INSERT = """
    INSERT INTO candles(instrument_key, dt, open, high, low, close, volume, oi)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(instrument_key, dt) DO UPDATE SET
      open=excluded.open,
      high=excluded.high,
      low=excluded.low,
      close=excluded.close,
      volume=excluded.volume,
      oi=excluded.oi
"""
_CANDLE_READ = (
    "SELECT dt AS Date, open AS Open, high AS High, low AS Low, close AS Close, volume AS Volume, oi AS OI "
    "FROM candles WHERE instrument_key = ? AND dt >= ? ORDER BY dt"
)


def cold_cache_history(instrument_key: str, fresh: pd.DataFrame | None, days: int, *,
                       now: pd.Timestamp) -> pd.DataFrame:
    """What app.py's `get_cached_history(..., days)` returns for `fresh` on a cold cache.

    Same steps as app.py's `_serialize_history` then `_read_cached_history`
    (tz-stripped ISO text keys, float/NULL values, `dt >= cutoff` window, text
    order, re-parsed dates), in a throwaway in-memory SQLite. `now` is the naive
    IST wall clock (app.py uses `pd.Timestamp.now()` on an IST machine).
    """
    empty = pd.DataFrame(columns=COLUMNS)
    if fresh is None or fresh.empty:
        return empty
    rows = []
    for idx, row in fresh.iterrows():
        try:
            stamp = pd.Timestamp(idx).tz_localize(None).isoformat()
        except Exception:
            stamp = str(idx)
        rows.append((instrument_key, stamp, *(
            float(row.get(column)) if pd.notna(row.get(column)) else None for column in COLUMNS
        )))
    cutoff = (pd.Timestamp(now).normalize() - pd.Timedelta(days=int(days))).isoformat()
    with contextlib.closing(sqlite3.connect(":memory:")) as conn:
        conn.execute(_CANDLE_SCHEMA)
        conn.executemany(_CANDLE_INSERT, rows)
        df = pd.read_sql_query(_CANDLE_READ, conn, params=(instrument_key, cutoff))
    if df.empty:
        return empty
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Date"] = normalize_market_timestamp_series(df["Date"])
    return df.dropna(subset=["Date"]).set_index("Date")


def history_index_problem(frame: pd.DataFrame) -> str | None:
    """Why a non-empty history cannot be trusted by completed-bar logic, else None.

    `app_runtime.completed_daily_bars` filters by INDEX dates; anything but a
    sorted, unique, naive DatetimeIndex would silently keep unfinished bars.
    """
    if frame.empty:
        return None
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        return "history index is not a DatetimeIndex"
    if index.tz is not None:
        return "history index is timezone-aware"
    if index.hasnans:
        return "history index has missing dates"
    if not index.is_unique:
        return "history index has duplicate dates"
    if not index.is_monotonic_increasing:
        return "history index is not in date order"
    return None


def prefetched_history(instrument_key: str, frame: pd.DataFrame):
    """A `get_cached_history` stand-in serving one prefetched cold-cache frame."""
    def get_cached_history(key, token, days=365, fetch_fn=None, db_path=None):
        """Return a copy of the prefetched frame for the one agreed request."""
        if key != instrument_key or int(days) != HISTORY_DAYS:
            raise ValueError("Stage-2 asked for history outside the prefetched request")
        return frame.copy()
    return get_cached_history


class ComputeOnlyFeatureStore:
    """`TechnicalFeatureStore.enrich` on an empty cache: compute from scratch.

    The real store, empty, returns `compute_fn(source)` with mode "full_rebuild"
    (and writes its cache, which a stateless run never reads); a test compares
    both on a temporary database.
    """

    def enrich(self, instrument_key, source, compute_fn):
        """Return (features, mode) like the store's cold-cache path."""
        if source is None or source.empty:
            return source, "empty"
        return compute_fn(source), "full_rebuild"


# ---------------------------------------------------------------- capture ---

_CAPTURE_CONSTANTS = (
    "schema", "purpose", "timestamp_semantics", "source_feature_available_at",
    "source_feature_availability_reason", "calculation_defaults",
)


def _capture_constants() -> dict:
    """The snapshot fields that are the same for every EquityCapture v1."""
    snapshot = EquityCapture(identity={}, settings={}).snapshot()
    return {name: snapshot[name] for name in _CAPTURE_CONSTANTS} | {
        "costs_note": snapshot["costs"]["note"]}


def compact_capture(snapshot: Mapping[str, Any]) -> dict:
    """Per-candidate part of an EquityCapture snapshot, for a small ledger batch.

    Dropped (recoverable with `expand_capture`): the constant prose fields, the
    identity (except ticker; the rest is the batch's strategy/hash fields), the
    derived missing-input list and composite-score copy. Dropped for good: the
    raw quote (same snapshot is in market_quotes and the Stage-1 batch) and the
    per-input capture times (kept as first/last).
    """
    times = sorted(str(value) for value in (snapshot.get("captured_at") or {}).values())
    quote = {k: v for k, v in (snapshot.get("quote") or {}).items() if k != "raw"}
    return {
        "schema": "equity-observation-capture-v1-compact",
        "ticker": (snapshot.get("identity") or {}).get("ticker"),
        "settings": snapshot.get("settings"),
        "inputs": snapshot.get("inputs"),
        "captured_at_range": [times[0], times[-1]] if times else None,
        "quote": quote,
        "costs": {k: v for k, v in (snapshot.get("costs") or {}).items() if k != "note"},
    }


def expand_capture(compact: Mapping[str, Any], *, batch: Mapping[str, Any]) -> dict:
    """Rebuild the app-shaped snapshot (raw quote and per-input times excepted)."""
    constants = _capture_constants()
    inputs = dict(compact.get("inputs") or {})
    return {
        "schema": constants["schema"], "purpose": constants["purpose"],
        "identity": {
            "strategy_id": batch["strategy_id"], "scanner_strategy_id": batch["strategy_id"],
            "target_version": batch["target_version"], "code_hash": batch["code_hash"],
            "config_hash": batch["config_hash"], "policy_hash": batch["policy_hash"],
            "ticker": compact.get("ticker"),
        },
        "settings": compact.get("settings"),
        "inputs": inputs, "scanner_composite_score": inputs.get("score"),
        "timestamp_semantics": constants["timestamp_semantics"],
        "source_feature_available_at": constants["source_feature_available_at"],
        "source_feature_availability_reason": constants["source_feature_availability_reason"],
        "quote": dict(compact.get("quote") or {}),
        "costs": {**dict(compact.get("costs") or {}), "note": constants["costs_note"]},
        "missing_or_uncomputed_inputs": [k for k in CAPTURE_INPUTS if inputs.get(k) is None],
        "calculation_defaults": constants["calculation_defaults"],
    }


# ------------------------------------------------------------- evaluation ---

def _not_evaluated(ticker: str, key: str, reason: str, *, at: dt.datetime) -> dict:
    """A shortlisted ticker the shadow Stage-2 could not decide on."""
    return {
        "ticker": ticker, "instrument_key": key, "status": NOT_EVALUATED,
        "stage2_pass": False, "category": "Not Evaluated", "reason": reason,
        "score": None, "entry": None, "stop": None, "target": None,
        "signal_action": None, "signal_action_reason": None, "timing": None, "features": None,
        "governance_evaluated": False, "equity_capture": None, "history": None,
        "evaluated_at": at.isoformat(),
    }


def _history_summary(frame: pd.DataFrame) -> dict:
    """Rows and date span of the history the decision saw (before completed bars)."""
    return {
        "rows": int(len(frame)), "days_requested": HISTORY_DAYS, "source": HISTORY_SOURCE,
        "first": frame.index.min().isoformat() if len(frame) else None,
        "last": frame.index.max().isoformat() if len(frame) else None,
    }


def evaluate_candidate(ticker: str, key: str, *, history: pd.DataFrame, quotes: Mapping,
                       nifty: pd.DataFrame, market_open: bool, settings: ScanSettings,
                       identity: Mapping[str, Any], now: Callable[[], dt.datetime]) -> dict:
    """Run app.py's Stage-2 decision core on one ticker with prefetched inputs."""
    observation = EquityCapture(
        identity={**identity, "ticker": ticker},
        settings={"horizon_sessions": settings.custom_days,
                  "minimum_net_rr": trade_contracts.EQUITY_MIN_NET_REWARD_RISK,
                  "scan_mode": "Scheduled Stage-1 shortlist", "market_regime": None},
    )
    result, rejection = evaluate_stage2(
        ticker, key=key, live_quote_data=quotes, access_token="prefetched",
        get_cached_history=prefetched_history(key, history), fetch_upstox_history=None,
        feature_store=ComputeOnlyFeatureStore(), nifty_hist_df=nifty, market_open=market_open,
        custom_days=settings.custom_days, max_stock_price=settings.max_stock_price,
        require_weekly_align=settings.require_weekly_align,
        use_advanced_signal_filters=settings.use_advanced_signal_filters,
        risk_engine=RiskEngine(investment_capital=settings.investment_capital,
                               max_risk_pct=settings.max_risk_pct,
                               max_position_pct=settings.max_position_pct),
        observation=observation, analysis_timing_log=[],
    )
    snapshot = observation.snapshot()
    base = {
        "ticker": ticker, "instrument_key": key, "status": EVALUATED,
        "governance_evaluated": False, "equity_capture": compact_capture(snapshot),
        "history": _history_summary(history), "evaluated_at": now().isoformat(),
    }
    if result is not None:
        return {**base, "stage2_pass": True, "category": None, "reason": None,
                "score": result["score"], "entry": result["entry"], "stop": result["stop"],
                "target": result["target"], "signal_action": result["action"],
                "signal_action_reason": result["action_reason"], "timing": result["timing"],
                "features": result["features"]}
    # Same levels app.py's `_reject` archives: whatever was computed before the gate.
    return {**base, "stage2_pass": False, "category": rejection["category"],
            "reason": rejection["reason"], "score": observation.inputs.get("score"),
            "entry": observation.inputs.get("price"), "stop": observation.inputs.get("sl"),
            "target": observation.inputs.get("tgt"), "signal_action": None,
            "signal_action_reason": None, "timing": None, "features": None}


def evaluate_shortlist(client, token: str, shortlist: Sequence[tuple[str, str]], *,
                       quotes: Mapping[str, Any], market_open: bool,
                       identity: Mapping[str, Any], settings: ScanSettings = APP_DEFAULT_SETTINGS,
                       budget: float = DEFAULT_BUDGET_SECONDS,
                       clock: Callable[[], float] | None = None,
                       sleep: Callable[[float], None] | None = None,
                       now: Callable[[], dt.datetime] | None = None,
                       check_lease: Callable[[], None] | None = None) -> dict:
    """Evaluate every shortlisted (ticker, key) in rank order; one result each.

    Never raises for data problems: they become NOT_EVALUATED results. Raises
    LeaseLost if the collector lease is lost (a fenced worker must stop).
    `now` is the wall clock (aware). Like app.py, the history request ends today
    and the cache window is cut from today; the decision core reads the same clock.
    """
    clock_now = now or (lambda: dt.datetime.now(dt.timezone.utc))
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    started = clock()
    wall = pd.Timestamp(clock_now()).tz_convert(IST)
    today, ist_now = wall.date(), wall.tz_localize(None)

    def lease_ok():
        """Re-check the fencing lease; convert its failure into LeaseLost."""
        if check_lease is None:
            return
        try:
            check_lease()
        except Exception as exc:
            raise LeaseLost(str(exc) or type(exc).__name__) from exc

    def remaining(reason):
        """NOT_EVALUATED results for every ticker not decided yet."""
        done = {item["instrument_key"] for item in results}
        return [_not_evaluated(t, k, reason, at=clock_now()) for t, k in shortlist if k not in done]

    results: list[dict] = []
    counts = {"history_failures": 0, "invalid_history": 0, "candidate_errors": 0}
    lease_ok()
    try:
        nifty = fetch_daily_candles(client, token, NIFTY_KEY, NIFTY_HISTORY_DAYS, today=today)
    except PermissionError:
        return {"results": remaining("History request rejected: Upstox Analytics Token not accepted"),
                "status": "FAILED", "error": "AUTH_REJECTED", **counts}
    except Exception as exc:
        LOGGER.warning("Stage-2 shadow NIFTY 50 history failed: %s", type(exc).__name__)
        return {"results": remaining(f"NIFTY 50 history unavailable ({type(exc).__name__})"),
                "status": "FAILED", "error": "BENCHMARK_UNAVAILABLE", **counts}
    if nifty.empty or history_index_problem(nifty):
        return {"results": remaining("NIFTY 50 history unavailable (empty or invalid dates)"),
                "status": "FAILED", "error": "BENCHMARK_UNAVAILABLE", **counts}

    status, error = "SUCCESS", None
    for ticker, key in shortlist:
        lease_ok()
        if clock() - started > budget:
            status, error = "PARTIAL", "TIME_BUDGET_EXHAUSTED"
            results.extend(remaining(f"Stage-2 time budget of {budget:.0f}s was exhausted"))
            break
        quote = quotes.get(key) if isinstance(quotes, Mapping) else None
        if quote is not None and not isinstance(quote, Mapping):
            counts["candidate_errors"] += 1
            results.append(_not_evaluated(ticker, key, "Quote snapshot is malformed", at=clock_now()))
            continue
        sleep(REQUEST_PAUSE_SECONDS)
        try:
            fresh = fetch_daily_candles(client, token, key, HISTORY_DAYS, today=today)
            history = cold_cache_history(key, fresh, HISTORY_DAYS, now=ist_now)
        except PermissionError:
            status, error = "FAILED", "AUTH_REJECTED"
            results.extend(remaining("History request rejected: Upstox Analytics Token not accepted"))
            break
        except Exception as exc:
            counts["history_failures"] += 1
            results.append(_not_evaluated(
                ticker, key, f"Price history unavailable ({type(exc).__name__})", at=clock_now()))
            continue
        problem = history_index_problem(history)
        if problem:
            counts["invalid_history"] += 1
            results.append(_not_evaluated(ticker, key, f"Price history rejected: {problem}",
                                          at=clock_now()))
            continue
        try:
            results.append(evaluate_candidate(
                ticker, key, history=history, quotes={key: dict(quote)} if quote else {},
                nifty=nifty, market_open=market_open, settings=settings,
                identity=identity, now=clock_now,
            ))
        except Exception as exc:
            # evaluate_stage2 already turns decision errors into the app's "Error"
            # reject; this only catches capture/serialisation faults around it.
            counts["candidate_errors"] += 1
            LOGGER.warning("Stage-2 shadow capture failed for %s: %s", ticker, type(exc).__name__)
            results.append(_not_evaluated(
                ticker, key, f"Stage-2 capture failed ({type(exc).__name__})", at=clock_now()))
    if status == "SUCCESS" and (counts["history_failures"] or counts["invalid_history"]
                                or counts["candidate_errors"]):
        status = "PARTIAL"
    return {"results": results, "status": status, "error": error,
            "seconds": round(clock() - started, 3), **counts}


# --------------------------------------------------------------- archival ---

def shadow_decision_id(run_id: str, instrument_key: str) -> str:
    """Stable id of one shadow Stage-2 decision (= scanner observation id)."""
    return hashlib.sha256(f"{run_id}|{instrument_key}|{STAGE2_SHADOW_VERSION}".encode()).hexdigest()


def _rejection_text(item: Mapping[str, Any]) -> str | None:
    """app.py's scanner rejection format: "<Category>: <reason>"."""
    if item["stage2_pass"]:
        return None
    return f"{item['category']}: {item['reason']}"


def _costs(item: Mapping[str, Any]) -> dict:
    """Cost evidence for the batch: the model estimate when Stage-2 reached it."""
    estimates = ((item.get("equity_capture") or {}).get("costs") or {}).get("estimates")
    if not estimates:
        return {"status": "NOT_EVALUATED", "reason": "Stage-2 stopped before the cost estimate"}
    return {"status": "MODEL_ESTIMATE", "round_trip_bps": estimates.get("round_trip_bps"),
            "assumptions": "Stage-2 execution-cost model; not measured executable spread"}


def archive_shadow_results(repo, *, run_id: str, observed_at: dt.datetime, as_of_date: dt.date,
                           results: Sequence[Mapping[str, Any]], quote_evidence: Mapping[str, Any],
                           universe: Mapping[str, Any], hashes: tuple[str, str, str],
                           settings: ScanSettings = APP_DEFAULT_SETTINGS,
                           check_lease: Callable[[], None] | None = None) -> dict:
    """Write the immutable shadow batch first, then compact scanner rows."""
    stage2_run_id = f"{run_id}{STAGE2_RUN_SUFFIX}"
    candidates, records = [], []
    for item in results:
        key = item["instrument_key"]
        decision_id = shadow_decision_id(run_id, key)
        # Shadow evidence never carries an executable action ("Buy").
        action = "Watch" if item["stage2_pass"] else "No Trade"
        # `timing` is not repeated here: it is in equity_capture.inputs.timing.
        inputs_used = {
            "parent_scan_run_id": run_id,
            "stage1_decision_scan": f"scan:{run_id}",
            **{name: item.get(name) for name in (
                "status", "stage2_pass", "category", "reason", "score", "entry", "stop", "target",
                "signal_action", "signal_action_reason", "features",
                "governance_evaluated", "history", "evaluated_at", "equity_capture")},
        }
        candidates.append({
            "decision_id": decision_id, "instrument_key": key, "instrument": item["ticker"],
            "action": action, "stage1_pass": True, "rejection_reason": _rejection_text(item),
            "inputs_used": inputs_used,
            "quote": dict(quote_evidence.get(key) or {"status": "UNAVAILABLE",
                                                       "reason": "No Stage-1 quote evidence"}),
            "costs": _costs(item),
        })
        records.append({
            "observation_id": decision_id, "as_of_date": as_of_date, "observed_at": observed_at,
            "instrument_key": key, "trading_symbol": item["ticker"],
            "strategy_version": STAGE2_SHADOW_VERSION, "universe_snapshot_date": as_of_date,
            "stage1_pass": True, "stage2_pass": bool(item["stage2_pass"]),
            "rejection_reason": _rejection_text(item), "score": item.get("score"),
            "entry": item.get("entry"), "stop": item.get("stop"), "target": item.get("target"),
            "features": {**inputs_used, "scan_run_id": stage2_run_id, "shadow_action": action},
        })
    if not candidates:
        return {"archive_status": "SKIPPED", "archive_reason": "Empty Stage-1 shortlist",
                "scanner_observations": 0}
    if check_lease is not None:
        try:
            check_lease()
        except Exception as exc:
            raise LeaseLost(str(exc) or type(exc).__name__) from exc
    code_hash, config_hash, policy_hash = hashes
    batch = DecisionEvidenceSpine(repo.append_evidence_event, repo).capture_candidate_batch(
        scan_run_id=stage2_run_id, observed_at=observed_at, strategy_id=STAGE2_SHADOW_VERSION,
        target_version=TARGET_VERSION, horizon_sessions=settings.custom_days,
        candidates=candidates, universe=universe, code_version=STAGE2_CODE_VERSION,
        code_hash=code_hash, config_hash=config_hash, policy_hash=policy_hash,
    )
    # Same storage rule as Stage-1 rows: evidence in the ledger -> pointer only;
    # a data-quality rejection keeps its full features and is never a pass.
    accepted = {row["decision_id"]: row for row in batch["record"]["candidates"]}
    for record in records:
        row = accepted[record["observation_id"]]
        if "data_quality" in row:
            record["stage2_pass"] = False
            record["rejection_reason"] = row["rejection_reason"]
            record["features"]["shadow_action"] = row["action"]
        else:
            record["features"] = {"scan_run_id": stage2_run_id, "retention": FEATURES_RETENTION}
    stored = repo.upsert_scanner_observations(records)
    failures = list(batch.get("quality_failures") or [])
    if failures:
        try:
            repo.record_quality_event(
                "scheduled_stage2_shadow", "WARNING", "CANDIDATE_DATA_QUALITY_REJECTED",
                f"Rejected {len(failures)} shadow Stage-2 candidate(s) with invalid evidence values",
                {"scan_run_id": stage2_run_id, "failures": failures},
            )
        except Exception as exc:
            LOGGER.warning("Stage-2 shadow quality-event index write failed: %s", type(exc).__name__)
    return {"archive_status": "STORED", "scan_run_id": stage2_run_id,
            "scanner_observations": stored, "data_quality_rejected": len(failures)}


def run_shadow_stage2(repo, client, token: str, run_id: str, *,
                      shortlist: Sequence[tuple[str, str]], quotes: Mapping[str, Any],
                      quote_evidence: Mapping[str, Any], universe: Mapping[str, Any],
                      now: dt.datetime, observed_at: dt.datetime, market_open: bool,
                      settings: ScanSettings = APP_DEFAULT_SETTINGS,
                      stage1_top_n: int | None = None,
                      check_lease: Callable[[], None] | None = None,
                      environ: Mapping[str, str] | None = None,
                      sleep: Callable[[float], None] | None = None,
                      wall_clock: Callable[[], dt.datetime] | None = None) -> dict:
    """Collector entry point. Returns a small JSON summary; raises only LeaseLost.

    Disabled unless `SCHEDULED_STAGE2_SHADOW` is on. Any other failure is recorded
    as a quality event and returned as status FAILED: Stage-1 evidence is already
    committed and must stay the run's result. `now` is the Stage-1 scan time (gives
    the as-of date); `wall_clock` is the evaluation clock (default: real UTC now);
    `stage1_top_n` is the shortlist size Stage-1 actually used (config hash).
    """
    if not stage2_enabled(environ):
        return {"status": "DISABLED", "reason": f"{ENABLE_ENV} is not enabled"}
    if not shortlist:
        return {"status": "SKIPPED", "reason": "Empty Stage-1 shortlist"}
    try:
        hashes = stage2_hashes(settings, stage1_top_n=stage1_top_n)
        code_hash, config_hash, policy_hash = hashes
        evaluation = evaluate_shortlist(
            client, token, shortlist, quotes=quotes, market_open=market_open, settings=settings, budget=budget_seconds(environ),
            identity={"strategy_id": STAGE2_SHADOW_VERSION,
                      "scanner_strategy_id": STAGE2_SHADOW_VERSION,
                      "target_version": TARGET_VERSION, "code_hash": code_hash,
                      "config_hash": config_hash, "policy_hash": policy_hash},
            check_lease=check_lease, sleep=sleep, now=wall_clock,
        )
        stored = archive_shadow_results(
            repo, run_id=run_id, observed_at=observed_at, as_of_date=now.astimezone(IST).date(),
            results=evaluation["results"], quote_evidence=quote_evidence, universe=universe,
            hashes=hashes, settings=settings, check_lease=check_lease,
        )
    except LeaseLost:
        raise
    except Exception as exc:
        LOGGER.error("Stage-2 shadow failed: %s", type(exc).__name__)
        try:
            repo.record_quality_event(
                "scheduled_stage2_shadow", "ERROR", "STAGE2_SHADOW_FAILED",
                f"Shadow Stage-2 failed: {type(exc).__name__}", {"scan_run_id": run_id},
            )
        except Exception as event_exc:
            LOGGER.warning("Stage-2 shadow failure event write failed: %s", type(event_exc).__name__)
        return {"status": "FAILED", "error_type": type(exc).__name__}
    results = evaluation["results"]
    summary = {
        "status": evaluation["status"], "error": evaluation["error"],
        "shortlisted": len(shortlist), "evaluated": sum(r["status"] == EVALUATED for r in results),
        "not_evaluated": sum(r["status"] == NOT_EVALUATED for r in results),
        "passed": sum(bool(r["stage2_pass"]) for r in results),
        # The decision core's own "Error" rejects (app.py shows these as Error too).
        "decision_errors": sum(r["status"] == EVALUATED and r["category"] == "Error"
                               for r in results),
        "history_failures": evaluation["history_failures"],
        "invalid_history": evaluation["invalid_history"],
        "candidate_errors": evaluation["candidate_errors"],
        "seconds": evaluation.get("seconds"), **stored,
    }
    if evaluation["status"] != "SUCCESS":
        try:
            repo.record_quality_event(
                "scheduled_stage2_shadow", "ERROR" if evaluation["status"] == "FAILED" else "WARNING",
                f"STAGE2_SHADOW_{evaluation['status']}",
                f"Shadow Stage-2 {evaluation['status'].lower()}: {summary['not_evaluated']} of "
                f"{len(shortlist)} shortlisted ticker(s) not evaluated",
                {k: summary[k] for k in ("error", "shortlisted", "evaluated", "not_evaluated",
                                         "history_failures", "invalid_history", "candidate_errors")}
                | {"scan_run_id": run_id},
            )
        except Exception as exc:
            LOGGER.warning("Stage-2 shadow status event write failed: %s", type(exc).__name__)
    return summary
