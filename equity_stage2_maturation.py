"""Forward outcome labels for scheduled Stage-2 shadow passes (Phase 5). Shadow-only; never orders.

Each scheduled scan's shadow Stage-2 (equity_stage2_collector) records its decisions in one
ledger batch and one scanner row per shortlisted ticker, but nothing ever measured what happened
next: the existing maturation (`scheduled_collector.update_matured_targets`) only labels app
decisions that carry a DECISION_EVALUATED event, and only in `close` mode, which is switched off.

When `SCHEDULED_STAGE2_MATURATION` is on, every scan run labels shadow passes whose 15-session
horizon has completed, under two frozen level policies on the same decision:

- `incumbent-levels-v1`: the stop and target the decision was recorded with
  (`derive_long_trade_levels`: stop = min(entry - 1.5 ATR, 20-day low - 0.15 ATR)).
- `atr15-stop-v1`: the research challenger, stop = entry - 1.5 ATR with the same target logic.

Label `SHADOW_LABEL_VERSION`: `prediction_validation.compute_forward_target` (the production
label: entry at the first one-minute open after the decision, minute-ordered stop/target touches,
stop first on ties, net of the decision's estimated round-trip costs), with two execution changes
so that tight and wide stops are compared fairly:

- a stop touched by a minute bar that opens below it fills at that open (a gap through the stop),
  not at the stop. Targets stay filled at the target (conservative);
- the NIFTY benchmark covers the stock's own holding window, on NIFTY one-minute bars: from the
  open of the entry minute to the close of the exit minute (to the daily close for a time exit).
  The production label measures NIFTY from the entry day's 09:15 open to the outcome day's close,
  which for a 10:07 decision adds NIFTY's first hour and, for a stop or target exit, the rest of
  that day to the excess return.

A label whose NIFTY evidence is missing is not stored (counted as `no_benchmark`, retried later).

Each label is one append-only `prediction_targets` row under a shadow-only target version
`stage2-shadow:<label version>:<policy>`, so the app's calibration, readiness counts and training
(which read `net-excess-execution-v2`) never see them. Buy and Watch, the score and repeated scans
are all kept: the read-only report `sql/stage2_shadow_outcomes_report.sql` splits by them.

Why not a DECISION_EVALUATED event per pass (the spec's other Phase 5 option): the app's
`pending_observations` would then pick the passes up and write production-version labels into the
app's calibration evidence, and each event costs about 5 KB of never-deleted ledger.

Upstox use: one NIFTY daily request per run plus, per stock and decision day, one daily and one
one-minute history request (ending at the horizon's last session), and one NIFTY one-minute
request per decision window, each after the 0.2 s pause the shadow Stage-2 uses; at most
`MAX_DECISIONS_PER_RUN` decisions and `BUDGET_SECONDS` per run (checked between decisions; a
budget stop makes the run PARTIAL). Only decisions whose 15 sessions have completed on the NIFTY
calendar take one of those slots, so decisions still waiting (holiday clusters) never use one.
Half the slots go to the newest completed decisions, half to the oldest (ties within a day
reshuffled daily): new decisions never wait behind ones that stay unlabelled (ambiguous evidence;
retried until `RETRY_DAYS` old), and the ones closest to expiry go first. Every failure except a
lost lease is contained: the scan's own evidence is already committed and stays the run's result.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import math
import os
import time
from typing import Callable, Mapping

import pandas as pd

from equity_stage2_collector import (
    IST, NIFTY_KEY, REQUEST_PAUSE_SECONDS, STAGE2_SHADOW_VERSION, LeaseLost,
)
# Exact-intraday labels always carry TARGET_VERSION: compute_forward_target never falls back there.
from prediction_validation import TARGET_VERSION, TargetDefinition, compute_forward_target
from production_repository import SCHEMA

LOGGER = logging.getLogger(__name__)

ENABLE_ENV = "SCHEDULED_STAGE2_MATURATION"
HORIZON_SESSIONS = 15
INCUMBENT = "incumbent-levels-v1"
CHALLENGER = "atr15-stop-v1"
POLICIES = (INCUMBENT, CHALLENGER)
VERSION_PREFIX = "stage2-shadow"
SHADOW_LABEL_VERSION = f"{TARGET_VERSION}.minute-aligned-v1"
MAX_DECISIONS_PER_RUN = 60   # <= 181 history requests a run: Upstox allows 1000 per 30 min per API
BUDGET_SECONDS = 300.0
FIRST_ELIGIBLE_DAYS = 22   # 15 sessions after the decision day, the run day's bar excluded
RETRY_DAYS = 60            # stop retrying an unlabelled decision after this many days
DEFAULT_COST_BPS = 30.0    # the existing maturation's fallback when no estimate was recorded
STALE_BENCHMARK_DAYS = 6   # NSE closures never exceed this: an older last NIFTY bar is a stale answer
BENCH_GAP = pd.Timedelta(minutes=5)   # furthest a NIFTY minute may sit from the stock's entry/exit minute
FAILURE_DETAIL_LIMIT = 20

_MISSING = f"""(SELECT count(*) FROM {SCHEMA}.prediction_targets t
           WHERE t.observation_id = o.observation_id AND t.target_version = ANY(%s)) < %s"""

# Cheap: every shadow pass in the window still missing a label (ids and decision days only).
PENDING_SQL = f"""
    SELECT o.observation_id, o.as_of_date
    FROM {SCHEMA}.scanner_observations o
    WHERE o.strategy_version = %s AND o.stage2_pass
      AND o.entry IS NOT NULL AND o.stop IS NOT NULL AND o.target IS NOT NULL
      AND o.as_of_date BETWEEN %s AND %s
      AND {_MISSING}
    ORDER BY o.as_of_date DESC, o.observation_id
"""

# Full rows for the decisions selected this run, with the inputs their ledger batch recorded.
DECISIONS_SQL = f"""
    SELECT o.observation_id, o.as_of_date, o.instrument_key, o.trading_symbol,
           o.entry, o.stop, o.target, c.value AS candidate,
           ARRAY(SELECT t.target_version FROM {SCHEMA}.prediction_targets t
                 WHERE t.observation_id = o.observation_id AND t.target_version = ANY(%s)
                 ORDER BY 1) AS stored_versions
    FROM {SCHEMA}.scanner_observations o
    JOIN {SCHEMA}.evidence_ledger_events e
      ON e.aggregate_id = 'scan:' || (o.feature_json->>'scan_run_id')
     AND e.event_type = 'DECISION_BATCH_EVALUATED'
    CROSS JOIN LATERAL jsonb_array_elements(e.payload->'candidates') c
    WHERE o.observation_id = ANY(%s) AND c.value->>'decision_id' = o.observation_id
    ORDER BY o.as_of_date DESC, o.observation_id
"""


def maturation_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """True only when the operator switched shadow maturation on explicitly."""
    value = str((os.environ if environ is None else environ).get(ENABLE_ENV) or "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def shadow_target_version(policy: str, label_version: str = SHADOW_LABEL_VERSION) -> str:
    """The shadow-only prediction_targets version for one label definition and level policy."""
    return f"{VERSION_PREFIX}:{label_version}:{policy}"


def levels_for_stop(entry: float, atr: float, stop: float, resistance20: float, resistance60: float,
                    horizon_days: int = HORIZON_SESSIONS) -> tuple[float, float] | None:
    """Target for a given stop: the target half of `derive_long_trade_levels`, unchanged.

    Returns rounded (stop, target), or None for invalid levels. With the incumbent stop this
    reproduces `derive_long_trade_levels` exactly (differential test).
    """
    if not (entry > 0 and atr > 0 and 0 < stop < entry):
        return None
    risk_distance = entry - stop
    target_floor = entry + max(2.0 * atr, risk_distance * 1.4)
    atr_target = entry + 2.0 * (1.0 + horizon_days / 70.0) * atr
    resistance_candidates = [r for r in (resistance20, resistance60) if r > entry * 1.005]
    suitable = [r for r in resistance_candidates if r >= entry + risk_distance * 1.5]
    if suitable:
        target = min(min(suitable), max(target_floor, entry + 0.85 * (atr_target - entry)))
    else:
        target = max(target_floor, atr_target)
    if target <= entry:
        return None
    return round(float(stop), 2), round(float(target), 2)


def challenger_levels(entry: float, atr: float, resistance20: float, resistance60: float,
                      horizon_days: int = HORIZON_SESSIONS) -> tuple[float, float] | None:
    """`atr15-stop-v1`: stop = entry - 1.5 ATR, target as the incumbent computes it for that stop."""
    return levels_for_stop(entry, atr, entry - 1.5 * atr, resistance20, resistance60, horizon_days)


def parse_pending_row(row: tuple) -> dict:
    """One pending shadow pass with the decision inputs its ledger batch recorded (raises if absent)."""
    names = ("observation_id", "as_of_date", "instrument_key", "trading_symbol",
             "entry", "stop", "target", "candidate", "stored_versions")
    item = dict(zip(names, row))
    candidate = item.pop("candidate")
    if isinstance(candidate, str):
        candidate = json.loads(candidate)
    used = candidate["inputs_used"]
    inputs = used["equity_capture"]["inputs"]
    levels = inputs["levels"]
    cost = (candidate.get("costs") or {}).get("round_trip_bps")
    item.update(
        as_of_date=pd.Timestamp(item["as_of_date"]).date(),
        entry=float(item["entry"]), stop=float(item["stop"]), target=float(item["target"]),
        atr=float(inputs["atr_val"]),
        resistance20=float(levels["resistance20"]), resistance60=float(levels["resistance60"]),
        cost_bps=DEFAULT_COST_BPS if cost is None else float(cost),
        evaluated_at=pd.Timestamp(used["evaluated_at"]),
        stored_versions=set(item.get("stored_versions") or ()),
    )
    return item


def pending_shadow_passes(repo, *, today: dt.date) -> list[tuple]:
    """(observation_id, as_of_date) of every shadow pass 22-60 days old missing a label; newest first."""
    versions = [shadow_target_version(policy) for policy in POLICIES]
    with repo.connect() as conn:
        return list(conn.execute(PENDING_SQL, (
            STAGE2_SHADOW_VERSION, today - dt.timedelta(days=RETRY_DAYS),
            today - dt.timedelta(days=FIRST_ELIGIBLE_DAYS), versions, len(versions),
        )).fetchall())


def decision_rows(repo, observation_ids: list[str]) -> list[tuple]:
    """Raw full rows for the selected decisions (parsed one by one by the caller); newest first."""
    if not observation_ids:
        return []
    versions = [shadow_target_version(policy) for policy in POLICIES]
    with repo.connect() as conn:
        return list(conn.execute(DECISIONS_SQL, (versions, list(observation_ids))).fetchall())


def completed_decisions(pending: list[tuple], benchmark: pd.DataFrame, *, today: dt.date,
                        limit: int = MAX_DECISIONS_PER_RUN) -> tuple[list[str], int]:
    """Ids of pending decisions whose horizon has completed on the NIFTY session calendar.

    Returns (up to `limit` ids; count still awaiting sessions). Counting sessions on the
    benchmark's own bars (already fetched) means decisions that cannot complete yet never use a
    slot or a stock request, so holiday clusters cannot crowd completed decisions out. Over the
    cap, half the slots go to the newest (`pending` is newest first) and half to the oldest of the
    rest, ties within a decision day reshuffled each day: decisions closest to RETRY_DAYS go first,
    and a block of same-day decisions that stays unlabelled cannot hold the same slots every day.
    """
    sessions = sorted(set(benchmark.index.normalize()))
    done, awaiting = [], 0
    for observation_id, as_of in pending:
        if sum(1 for d in sessions if d > pd.Timestamp(as_of)) >= HORIZON_SESSIONS:
            done.append((observation_id, pd.Timestamp(as_of)))
        else:
            awaiting += 1
    if len(done) > limit:
        newest = limit - limit // 2
        rest = sorted(done[newest:], key=lambda item: (
            item[1], hashlib.sha256(f"{today}:{item[0]}".encode()).hexdigest()))
        done = done[:newest] + rest[:limit // 2]
    return [observation_id for observation_id, _ in done], awaiting


def _signal_timestamp(evaluated_at: pd.Timestamp) -> pd.Timestamp | None:
    """Decision time in IST if inside the cash session, else None (next-open entry rule)."""
    at = evaluated_at.tz_convert(IST) if evaluated_at.tzinfo else evaluated_at.tz_localize(IST)
    at = at.tz_localize(None)
    opens, closes = at.replace(hour=9, minute=15, second=0, microsecond=0), \
        at.replace(hour=15, minute=30, second=0, microsecond=0)
    return at if opens <= at <= closes else None


def _before(frame: pd.DataFrame | None, today: dt.date) -> pd.DataFrame:
    """Completed evidence only: drop anything stamped on or after the run's IST date."""
    if frame is None or frame.empty:
        return pd.DataFrame(index=pd.DatetimeIndex([]))
    return frame.loc[frame.index.normalize() < pd.Timestamp(today)]


def horizon_end(decision: Mapping, daily: pd.DataFrame, today: dt.date) -> dt.date | None:
    """Date of the HORIZON_SESSIONS-th completed session after the decision day, or None if not yet."""
    sessions = sorted({d for d in _before(daily, today).index.normalize() if d > pd.Timestamp(decision["as_of_date"])})
    return sessions[HORIZON_SESSIONS - 1].date() if len(sessions) >= HORIZON_SESSIONS else None


def _exit_bar(label: dict, minutes: pd.DataFrame, stop: float, target: float) -> pd.Series | None:
    """The minute bar that ended a stop or target label (its `.name` is the minute).

    The first bar on the outcome day, at or after entry, that reaches the stop or the target:
    the bar compute_forward_target stopped on.
    """
    day = minutes.loc[minutes.index.normalize() == pd.Timestamp(label["outcome_date"])]
    if label.get("entry_timestamp"):
        day = day.loc[day.index >= pd.Timestamp(label["entry_timestamp"])]
    touched = day.loc[(day["Low"].astype(float) <= stop) | (day["High"].astype(float) >= target)]
    return None if touched.empty else touched.iloc[0]


def _benchmark_return(label: dict, exit_at: pd.Timestamp | None, bench_daily: pd.DataFrame,
                      bench_minutes: pd.DataFrame) -> float | None:
    """NIFTY over the stock's holding window, or None when that evidence is missing or bad.

    From the open of the first NIFTY minute at or after the stock's entry minute to the close of
    the NIFTY minute at (or just before) the exit minute, each at most BENCH_GAP away and in that
    order; a time exit (`exit_at` None) ends at NIFTY's daily close on the label's last session,
    as the stock's exit does. For a next-open entry (a decision outside the session) the entry
    minute is the last of the five opening minutes the entry price averages: a few minutes of
    NIFTY, not its whole first hour.
    """
    if not label.get("entry_timestamp") or bench_minutes.empty:
        return None
    entry_at, at = pd.Timestamp(label["entry_timestamp"]), bench_minutes.index
    # Within BENCH_GAP of a session minute: the window cannot reach another day.
    start = bench_minutes.loc[(at >= entry_at) & (at <= entry_at + BENCH_GAP), "Open"]
    if start.empty:
        return None
    if exit_at is None:
        last = pd.Timestamp(label["label_end_date"])
        end = bench_daily.loc[bench_daily.index.normalize() == last, "Close"] if not bench_daily.empty \
            else pd.Series(dtype=float)
    else:
        end = bench_minutes.loc[(at <= exit_at) & (at >= max(exit_at - BENCH_GAP, start.index[0])), "Close"]
    if end.empty:
        return None
    base, final = float(start.iloc[0]), float(end.iloc[-1])
    if not (math.isfinite(base) and math.isfinite(final) and base > 0 and final > 0):
        return None
    return final / base - 1.0


def _execution_adjusted(label: dict, minutes: pd.DataFrame, bench_daily: pd.DataFrame,
                        bench_minutes: pd.DataFrame, stop: float, target: float,
                        notes: dict | None) -> dict | None:
    """The shadow label: gap-down stop fill at the bar open, NIFTY over the holding window.

    None (no label, retried later) when the exit bar or a positive gap price is missing, or the
    NIFTY evidence is (counted in `notes["no_benchmark"]`). A NaN open keeps the stop fill.
    """
    bar, exit_price, fill = None, float(label["exit"]), {}
    if label["outcome"] != "horizon":
        bar = _exit_bar(label, minutes, stop, target)
        if bar is None:
            return None
        opened = float(bar["Open"])
        if label["outcome"] == "stop" and math.isfinite(opened) and opened < stop:
            if opened <= 0:
                return None
            exit_price, fill = opened, {"stop_fill": "gap_open"}
    bench = _benchmark_return(label, None if bar is None else bar.name, bench_daily, bench_minutes)
    if bench is None:
        if notes is not None:
            notes["no_benchmark"] = notes.get("no_benchmark", 0) + 1
        return None
    gross = exit_price / float(label["entry"]) - 1.0
    net = gross - float(label["cost_bps"]) / 10_000.0
    return {**label, **fill, "exit": exit_price, "gross_return": gross, "net_return": net,
            "benchmark_return": bench, "excess_return": net - bench, "positive_excess": int(net - bench > 0)}


def label_decision(decision: Mapping, *, daily: pd.DataFrame, minutes: pd.DataFrame,
                   benchmark: pd.DataFrame | None, benchmark_minutes: pd.DataFrame | None,
                   today: dt.date, notes: dict | None = None) -> dict[str, dict | None]:
    """Labels per policy for one decision whose horizon has completed (see horizon_end).

    `benchmark` and `benchmark_minutes` are NIFTY's daily and one-minute bars. A policy maps to
    None when its levels are invalid, the evidence is incomplete or ambiguous
    (compute_forward_target refuses to label it) or the NIFTY evidence does not cover the holding
    window (counted in `notes["no_benchmark"]`); later runs retry it.
    """
    daily, minutes = _before(daily, today), _before(minutes, today)
    bench_daily, bench_minutes = _before(benchmark, today), _before(benchmark_minutes, today)
    levels = {
        INCUMBENT: (decision["stop"], decision["target"]),
        CHALLENGER: challenger_levels(decision["entry"], decision["atr"],
                                      decision["resistance20"], decision["resistance60"]),
    }
    definition = TargetDefinition(HORIZON_SESSIONS, round_trip_cost_bps=decision["cost_bps"],
                                  entry_rule="exact_intraday")
    labels = {}
    for policy, level in levels.items():
        label = None
        if level is not None:
            # benchmark=None: its day-bar NIFTY window is replaced by the holding-window one below.
            label = compute_forward_target(
                daily, decision["as_of_date"], definition, stop=level[0], target=level[1],
                benchmark=None, intraday=minutes,
                signal_timestamp=_signal_timestamp(decision["evaluated_at"]),
            )
        if label is not None:
            label = _execution_adjusted(label, minutes, bench_daily, bench_minutes, *level, notes)
        labels[policy] = None if label is None else {
            **label, "target_version": shadow_target_version(policy), "stop": level[0], "target": level[1]}
    return labels


def _guard(check_lease: Callable[[], None] | None) -> None:
    """Fenced worker: a lost lease stops the run before any further write."""
    if check_lease is None:
        return
    try:
        check_lease()
    except Exception as exc:
        raise LeaseLost(str(exc) or type(exc).__name__) from exc


class ProviderRejected(RuntimeError):
    """The daily history request for one instrument got an HTTP 4xx (not auth, not rate limit)."""


def _history(cache: dict, decision: Mapping, *, client, token: str, today: dt.date,
             fetch_daily: Callable, fetch_minutes: Callable, sleep: Callable[[float], None]):
    """(daily, minutes, horizon end, NIFTY minutes) for a stock and decision day, once per run.

    Minutes (the stock's, then NIFTY's for the same window, shared by every stock with that
    window) are fetched only once the horizon has completed, from the decision day to its end.
    """
    key = (decision["instrument_key"], decision["as_of_date"])
    if key not in cache:
        as_of = decision["as_of_date"]
        sleep(REQUEST_PAUSE_SECONDS)
        try:
            daily = fetch_daily(client, token, decision["instrument_key"], as_of - dt.timedelta(days=5),
                                today - dt.timedelta(days=1))
        except Exception as exc:
            # Only the per-instrument daily request: NIFTY already proved that endpoint works.
            if _provider_rejected(exc):
                raise ProviderRejected(str(exc)) from exc
            raise
        end = horizon_end(decision, daily, today)
        minutes = bench_minutes = None
        if end is not None:
            sleep(REQUEST_PAUSE_SECONDS)
            minutes = fetch_minutes(client, token, decision["instrument_key"], as_of, end)
            window = (NIFTY_KEY, as_of, end)
            if window not in cache:
                sleep(REQUEST_PAUSE_SECONDS)
                cache[window] = fetch_minutes(client, token, NIFTY_KEY, as_of, end)
            bench_minutes = cache[window]
            if bench_minutes is None or bench_minutes.empty:
                # A completed NIFTY window always has minutes: an empty answer is a broken feed (a
                # failure, PARTIAL), not a per-label gap that would leave the run looking healthy.
                raise ValueError("NIFTY minute history is empty")
        cache[key] = (daily, minutes, end, bench_minutes)
    return cache[key]


def _mature_one(repo, decision: Mapping, *, history: tuple, benchmark: pd.DataFrame, today: dt.date,
                check_lease: Callable[[], None] | None, summary: dict) -> None:
    """Label one decision under both policies and store the labels it does not have yet."""
    daily, minutes, end, bench_minutes = history
    if end is None:
        summary["deferred"] += 1
        return
    labels = label_decision(decision, daily=daily, minutes=minutes, benchmark=benchmark,
                            benchmark_minutes=bench_minutes, today=today, notes=summary)
    for policy in POLICIES:
        label = labels[policy]
        if label is None:
            # shortcut: a never-valid challenger level is retried until RETRY_DAYS too; cheap
            # (cached per run, newest first so it never blocks new decisions) and rare.
            summary["unlabelled"] += 1
        elif label["target_version"] in decision["stored_versions"]:
            summary["already_stored"] += 1
        else:
            _guard(check_lease)
            repo.save_prediction_target(decision["observation_id"], label)
            summary["stored"] += 1


def _report(repo, summary: dict, failures: list[dict], check_lease: Callable[[], None] | None) -> None:
    """One quality event for a run that did not fully succeed (never raises; skipped if fenced)."""
    if failures and summary["status"] == "SUCCESS":
        summary["status"] = "PARTIAL"
    if summary["status"] == "SUCCESS":
        return
    try:
        _guard(check_lease)
        repo.record_quality_event(
            "scheduled_stage2_maturation", "ERROR" if summary["status"] == "FAILED" else "WARNING",
            "STAGE2_MATURATION_FAILED",
            f"Shadow Stage-2 maturation {summary['status']}: {summary['failed']} decision failures"
            + (f", stopped by {summary['stopped']}" if summary.get("stopped") else ""),
            {"summary": summary, "failures": failures[:FAILURE_DETAIL_LIMIT]},
        )
    except Exception as exc:
        LOGGER.warning("Stage-2 maturation quality-event write skipped: %s", type(exc).__name__)


def _select(repo, client, token: str, *, today: dt.date, fetch_daily: Callable,
            sleep: Callable[[float], None], summary: dict, failures: list[dict]):
    """(NIFTY benchmark, raw rows of the completed decisions selected this run).

    Raises when the benchmark is empty: no label can carry an excess return without it.
    """
    pending = pending_shadow_passes(repo, today=today)
    summary["pending"] = len(pending)
    if not pending:
        return None, []
    earliest = min(pd.Timestamp(as_of).date() for _, as_of in pending) - dt.timedelta(days=5)
    sleep(REQUEST_PAUSE_SECONDS)
    benchmark = _before(fetch_daily(client, token, NIFTY_KEY, earliest, today - dt.timedelta(days=1)), today)
    if benchmark.empty:
        raise ValueError("NIFTY benchmark history is empty")
    if benchmark.index.max().date() < today - dt.timedelta(days=STALE_BENCHMARK_DAYS):
        raise ValueError("NIFTY benchmark history is stale")
    selected, summary["awaiting_sessions"] = completed_decisions(pending, benchmark, today=today)
    summary["selected"] = len(selected)
    rows = decision_rows(repo, selected)
    for missing in sorted(set(selected) - {row[0] for row in rows}):
        summary["failed"] += 1
        failures.append({"observation_id": missing, "error_kind": "MissingDecisionInputs",
                         "message": "decision not found in its ledger batch"})
    return benchmark, rows


def _provider_rejected(exc: Exception) -> bool:
    """An HTTP 4xx answer for one instrument (not auth, not rate limit): a data fact, not a run failure."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return isinstance(status, int) and 400 <= status < 500 and status not in (401, 403, 429)


def mature_shadow_passes(repo, client, token: str, *, today: dt.date,
                         fetch_daily: Callable, fetch_minutes: Callable,
                         check_lease: Callable[[], None] | None = None,
                         environ: Mapping[str, str] | None = None,
                         sleep: Callable[[float], None] = time.sleep,
                         clock: Callable[[], float] = time.monotonic) -> dict:
    """Collector entry point. Returns a JSON summary; raises only LeaseLost.

    `fetch_daily(client, token, key, from_date, to_date)` and
    `fetch_minutes(client, token, key, from_date, to_date)` are the collector's Upstox history
    fetchers (injected: this module must not import scheduled_collector). A rejected token
    (PermissionError) or an empty or stale NIFTY benchmark stops the run as FAILED; an HTTP 4xx on one
    instrument's daily request is counted as `provider_rejected` (a 4xx on the minute request is a failure); any other per-decision error (including a
    malformed row or inputs missing from the ledger batch) is counted as failed and the run goes on.
    """
    if not maturation_enabled(environ):
        return {"status": "DISABLED", "reason": f"{ENABLE_ENV} is not enabled"}
    started = clock()
    summary = {"status": "SUCCESS", "pending": 0, "awaiting_sessions": 0, "selected": 0, "stored": 0,
               "already_stored": 0, "deferred": 0, "unlabelled": 0, "no_benchmark": 0,
               "provider_rejected": 0, "failed": 0, "stopped": None}
    failures: list[dict] = []
    try:
        _guard(check_lease)
        benchmark, rows = _select(repo, client, token, today=today, fetch_daily=fetch_daily, sleep=sleep,
                                  summary=summary, failures=failures)
        cache: dict = {}
        for row in rows:
            if clock() - started > BUDGET_SECONDS:
                # Selected work left undone: PARTIAL, so the scan run says so; later runs retry it.
                summary.update(stopped="BUDGET", status="PARTIAL")
                break
            _guard(check_lease)
            try:
                decision = parse_pending_row(row)
                history = _history(cache, decision, client=client, token=token, today=today,
                                   fetch_daily=fetch_daily, fetch_minutes=fetch_minutes, sleep=sleep)
                _mature_one(repo, decision, history=history, benchmark=benchmark, today=today,
                            check_lease=check_lease, summary=summary)
            except (LeaseLost, PermissionError):
                raise
            except ProviderRejected:
                summary["provider_rejected"] += 1
            except Exception as exc:
                summary["failed"] += 1
                failures.append({"observation_id": row[0], "error_kind": type(exc).__name__,
                                 "message": str(exc)[:200]})
    except LeaseLost:
        raise
    except Exception as exc:
        LOGGER.error("Stage-2 shadow maturation failed: %s", type(exc).__name__)
        summary.update(status="FAILED", error_type=type(exc).__name__)
    _report(repo, summary, failures, check_lease)
    summary["seconds"] = round(clock() - started, 1)
    return summary
