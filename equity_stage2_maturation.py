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

Price basis (corporate actions): the recorded entry, stop and target are on the price basis of
the decision day, but Upstox history is back-adjusted to the day it is fetched. A split, bonus,
rights issue or large dividend between the two would make the levels meaningless against the
fetched bars (a 1:1 bonus halves the history: every stop looks hit). Two guards, both fail-closed:

- events: the stock's Upstox corporate actions (one request per stock per run, before any history
  request); a decision is held back (`corporate_action`) when any action other than a dividend
  below 2% of the entry has an ex-date after the decision day and on or before the run day. The
  held-back stock's actions are archived in `corporate_actions`, and PENDING_SQL leaves out
  passes with an archived non-dividend action in that window, so they take no later slot;
- basis (`basis_mismatch`): both histories must hold the decision day with the recorded entry
  (the scan's own quote) inside its range, and one of the fetched daily bars just before the
  decision day must equal the last completed bar the scan recorded (`latest_indicators` Open,
  High and Low, within 0.1%; the close is left out because sources and revisions differ on it),
  and the minutes' decision-day low and high must equal the daily bar's (0.5%). A rescale of the
  daily history above 0.1%, or of the minutes alone above 0.5%, whatever the cause, fails these,
  so events the feed does not list (a demerger) are caught whenever the provider adjusted them.
  Actions the module cannot read hold the decision back and make the run PARTIAL.

Not covered: an event the feed omits that the provider also did not adjust (the raw ex-date jump
then sits inside the window).

Each label is one append-only `prediction_targets` row under a shadow-only target version
`stage2-shadow:<label version>:<policy>`, so the app's calibration, readiness counts and training
(which read `net-excess-execution-v2`) never see them. Buy and Watch, the score and repeated scans
are all kept: the read-only report `sql/stage2_shadow_outcomes_report.sql` splits by them.

Why not a DECISION_EVALUATED event per pass (the spec's other Phase 5 option): the app's
`pending_observations` would then pick the passes up and write production-version labels into the
app's calibration evidence, and each event costs about 5 KB of never-deleted ledger.

Upstox use: one NIFTY daily request per run plus, per stock, one corporate-actions request and,
per stock and decision day, one daily and one one-minute history request (ending at the horizon's
last session), and one NIFTY one-minute request per decision window, each after the 0.2 s pause
the shadow Stage-2 uses; at most
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
import re
import time
import urllib.parse
from typing import Callable, Mapping

import pandas as pd

from equity_stage2_collector import (
    IST, NIFTY_KEY, REQUEST_PAUSE_SECONDS, STAGE2_SHADOW_VERSION, UPSTOX_API, LeaseLost,
)
# Exact-intraday labels always carry TARGET_VERSION: compute_forward_target never falls back there.
from prediction_validation import TARGET_VERSION, TargetDefinition, compute_forward_target
from production_repository import SCHEMA, _date_value

LOGGER = logging.getLogger(__name__)

ENABLE_ENV = "SCHEDULED_STAGE2_MATURATION"
HORIZON_SESSIONS = 15
INCUMBENT = "incumbent-levels-v1"
CHALLENGER = "atr15-stop-v1"
POLICIES = (INCUMBENT, CHALLENGER)
VERSION_PREFIX = "stage2-shadow"
SHADOW_LABEL_VERSION = f"{TARGET_VERSION}.minute-aligned-v1"
MAX_DECISIONS_PER_RUN = 60   # <= 241 requests a run: Upstox allows 1000 per 30 min per API
BUDGET_SECONDS = 300.0
FIRST_ELIGIBLE_DAYS = 22   # 15 sessions after the decision day, the run day's bar excluded
RETRY_DAYS = 60            # stop retrying an unlabelled decision after this many days
DEFAULT_COST_BPS = 30.0    # the existing maturation's fallback when no estimate was recorded
STALE_BENCHMARK_DAYS = 6   # NSE closures never exceed this: an older last NIFTY bar is a stale answer
BENCH_GAP = pd.Timedelta(minutes=5)   # furthest a NIFTY minute may sit from the stock's entry/exit minute
LARGE_DIVIDEND = 0.02      # a dividend at least this share of the entry moves the price basis
BASIS_TOLERANCE = 0.005    # recorded entry vs the fetched decision-day range: same basis, rounding only
ANCHOR_TOLERANCE = 0.001   # the scan's last completed daily bar re-fetched: float rounding only
# Trade-set prices only: a close can be the last trade or the official (last-30-minute) close and
# differ by source or revision (AVTNPL 10 Nov: 100.14 Upstox vs 100.31 elsewhere, O/H/L equal).
ANCHOR_FIELDS = ("Open", "High", "Low")
ANCHOR_LOOKBACK = 2        # bars before the decision day searched for it: one session of feed lag at
                           # scan time; more would let an older bar match after a rescale
HISTORY_LEAD_DAYS = 10     # daily history starts this long before the decision day (anchor + holidays)
ISIN_PATTERN = re.compile(r"IN[A-Z0-9]{9}[0-9]")
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
      AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.corporate_actions c
                      WHERE c.isin = split_part(o.instrument_key, '|', 2)
                        AND lower(trim(c.action_type)) = ANY(%s)
                        AND c.ex_date > o.as_of_date AND c.ex_date <= %s)
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


def _anchor(bar) -> dict | None:
    """The scan's last completed daily bar (ANCHOR_FIELDS as recorded), or None if unreadable."""
    if not isinstance(bar, Mapping):
        return None
    try:
        values = {name: float(bar[name]) for name in ANCHOR_FIELDS}
    except (KeyError, TypeError, ValueError):
        return None
    return values if all(math.isfinite(v) and v > 0 for v in values.values()) else None


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
        anchor=_anchor(inputs.get("latest_indicators")),
        stored_versions=set(item.get("stored_versions") or ()),
    )
    return item


def pending_shadow_passes(repo, *, today: dt.date) -> list[tuple]:
    """(observation_id, as_of_date) of every shadow pass 22-60 days old missing a label; newest first.

    Passes whose stock has an archived action of a known non-dividend type (KNOWN_ACTIONS) after the
    decision day (up to today) are left out: they can never be labelled, so they take no slot and no
    request. An archived action of any other type does not exclude: the pass reaches basis_events,
    which holds it back and reports the type (a new type must not drop passes unseen).
    """
    versions = [shadow_target_version(policy) for policy in POLICIES]
    with repo.connect() as conn:
        return list(conn.execute(PENDING_SQL, (
            STAGE2_SHADOW_VERSION, today - dt.timedelta(days=RETRY_DAYS),
            today - dt.timedelta(days=FIRST_ELIGIBLE_DAYS), versions, len(versions), list(KNOWN_ACTIONS),
            today,
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


def _basis_problem(decision: Mapping, *, daily: pd.DataFrame, minutes: pd.DataFrame) -> str | None:
    """Why the fetched history is not on the recorded price basis, or None.

    1. Both the daily and the one-minute history must hold the decision day, and the recorded
       entry (the scan's quote, or its last close without one) must lie inside that day's range
       in each (BASIS_TOLERANCE): a coarse check that catches large rescales in either feed. The
       two feeds' decision-day low and high must also agree within BASIS_TOLERANCE, so the
       minutes are on the daily feed's basis.
    2. Exact anchor: the scan recorded its last completed daily bar (`latest_indicators`, the
       same Upstox series); one of the fetched bars just before the decision day must match it
       within ANCHOR_TOLERANCE on Open, High and Low. A history back-adjusted for any later
       split, bonus, rights issue, demerger or dividend by more than the tolerance matches none.
       A pass without a readable recorded bar is a problem too (every Stage-2 pass records one).
    """
    as_of, entry = pd.Timestamp(decision["as_of_date"]), float(decision["entry"])
    ranges = {}
    for name, frame in (("daily", daily), ("minutes", minutes)):
        day = frame.loc[frame.index.normalize() == as_of] if not frame.empty else frame
        if day.empty:
            return f"no decision-day bars in the {name} history"
        low, high = float(day["Low"].min()), float(day["High"].max())
        # NaN bounds fail both comparisons: an unreadable range is a problem, not a pass.
        if not low * (1 - BASIS_TOLERANCE) <= entry <= high * (1 + BASIS_TOLERANCE):
            return f"recorded entry {entry} outside the {name} decision-day range {low}-{high}"
        ranges[name] = (low, high)
    # The anchor below checks the daily feed; the minutes (entry and exit order) must be on the
    # same basis: their decision-day range equals the daily bar's (a rescale of either fails it).
    ratios = [ranges["minutes"][i] / ranges["daily"][i] for i in (0, 1)]
    if not all(abs(ratio - 1) <= BASIS_TOLERANCE for ratio in ratios):
        return f"the minute and daily decision-day ranges differ (low ratio {ratios[0]:.4f}, high ratio {ratios[1]:.4f})"
    anchor = decision.get("anchor")
    if anchor is None:
        # Every Stage-2 pass records its last completed bar; without it the basis cannot be proven.
        return "no recorded last completed bar to check the price basis against"
    prior = daily.loc[daily.index.normalize() < as_of].tail(ANCHOR_LOOKBACK)
    if prior.empty:
        return "no daily bar before the decision day to check the price basis against"
    for _, bar in prior.iterrows():
        # NaN never matches: abs(nan) <= tolerance is False.
        if all(abs(float(bar[name]) / value - 1) <= ANCHOR_TOLERANCE for name, value in anchor.items()):
            return None
    ratio = float(prior["Low"].iloc[-1]) / anchor["Low"]
    return f"the scan's last completed bar is not in the fetched daily history (low ratio {ratio:.4f})"


def label_decision(decision: Mapping, *, daily: pd.DataFrame, minutes: pd.DataFrame,
                   benchmark: pd.DataFrame | None, benchmark_minutes: pd.DataFrame | None,
                   today: dt.date, notes: dict | None = None) -> dict[str, dict | None]:
    """Labels per policy for one decision whose horizon has completed (see horizon_end).

    `benchmark` and `benchmark_minutes` are NIFTY's daily and one-minute bars. A policy maps to
    None when its levels are invalid, the evidence is incomplete or ambiguous
    (compute_forward_target refuses to label it) or the NIFTY evidence does not cover the holding
    window (counted in `notes["no_benchmark"]`); both map to None when the history is not on the
    recorded price basis (`notes["basis_mismatch"]`). Later runs retry it.
    """
    daily, minutes = _before(daily, today), _before(minutes, today)
    bench_daily, bench_minutes = _before(benchmark, today), _before(benchmark_minutes, today)
    problem = _basis_problem(decision, daily=daily, minutes=minutes)
    if problem is not None:
        LOGGER.warning("Stage-2 maturation: %s %s", decision.get("trading_symbol"), problem)
        if notes is not None:
            notes["basis_mismatch"] = notes.get("basis_mismatch", 0) + 1
            notes.setdefault("basis_problems", []).append(
                {"observation_id": decision.get("observation_id"), "error_kind": "BasisMismatch",
                 "message": problem[:200]})
        return {policy: None for policy in POLICIES}
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


def isin_of(instrument_key: str) -> str:
    """The ISIN inside an NSE equity instrument key ('NSE_EQ|INE002A01018'); ValueError otherwise."""
    isin = str(instrument_key).partition("|")[2]
    if not ISIN_PATTERN.fullmatch(isin):
        raise ValueError(f"no ISIN in instrument key {instrument_key!r}")
    return isin


def fetch_corporate_actions(client, token: str, instrument_key: str) -> list:
    """Upstox corporate actions of one stock: the endpoint scheduled_collector.update_corporate_actions
    archives (past ~year plus announced ex-dates; 1,162 ISINs answered 200, 523 of them empty).

    A rejected token raises PermissionError; a key without an ISIN, any other non-200 answer or a
    changed schema raises ValueError: a decision is never labelled without this evidence.
    """
    isin = isin_of(instrument_key)
    response = client.get(
        f"{UPSTOX_API}/v2/fundamentals/{urllib.parse.quote(isin, safe='')}/corporate-actions",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"}, timeout=(5, 20),
    )
    if response.status_code in {401, 403}:
        raise PermissionError("Upstox rejected the Analytics Token")
    if response.status_code != 200:
        raise ValueError(f"Corporate-actions API returned HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, Mapping) or payload.get("status") != "success" or "data" not in payload:
        raise ValueError("Upstox corporate-actions answer is not a success")
    actions = [] if payload["data"] is None else payload["data"]
    if not isinstance(actions, list):
        raise ValueError("Upstox corporate-actions schema changed")
    return actions


# Non-dividend action types the corporate-actions feed lists (all 464 stored actions, 12 Nov, are
# these or "Dividend"); any other type still holds a decision back, reported (see basis_events),
# and only these exclude a pass in PENDING_SQL (lower-case, matched after trim).
KNOWN_ACTIONS = ("bonus", "split", "rights issue")
# A dash or "NA" in a date field means "no such date", not an unreadable one.
_NO_DATE = re.compile(r"[-\u2013\u2014]*|n/?a|nil|null|none")


def _ex_dates(item: Mapping) -> list:
    """Every ex-date an action carries: `ex_date`, `expiry_date` (the field the archived rows
    use) and each 'Ex ... date' detail (all agree in the 911 archived rows); unparsable ones come
    back as None, placeholders (_NO_DATE) are left out."""
    raw = [item.get("ex_date"), item.get("expiry_date")]
    raw += [d.get("value") for d in item.get("event_details") or ()
            if isinstance(d, Mapping) and re.fullmatch(r"ex\b.*\bdate", str(d.get("name") or "").strip().lower())]
    return [_date_value(value) for value in raw
            if value is not None and not _NO_DATE.fullmatch(str(value).strip().lower())]


def _dividend_amount(item: Mapping) -> float | None:
    """The dividend per share, or None when it cannot be read (missing, not a number, negative)."""
    try:
        amount = float(item.get("amount"))
    except (TypeError, ValueError):
        return None
    return amount if math.isfinite(amount) and amount >= 0 else None


def _basis_event(item, decision: Mapping, today: dt.date) -> tuple[str, bool] | None:
    """(reason, unreadable) when one corporate action holds the decision back, else None.

    `unreadable` marks a hold-back that rests on data this module cannot read (the action, its
    type, a dividend's amount or its ex-dates) or a type it does not know, rather than on a dated
    event of a known type: see basis_events. Any type naming a dividend ("Interim Dividend") is one.
    """
    if not isinstance(item, Mapping):
        return "unreadable action", True
    name = str(item.get("name") or item.get("type") or "").strip()
    dividend = "dividend" in name.lower()
    amount = _dividend_amount(item) if dividend else None
    if dividend and amount is not None and 0 < amount < LARGE_DIVIDEND * float(decision["entry"]):
        return None                                   # a small dividend never moves the basis
    dates = _ex_dates(item)
    inside = sorted(d for d in dates if d is not None and decision["as_of_date"] < d <= today)
    if inside:
        reason = f"{name or 'action'} ex {inside[0].isoformat()}"
        if not name:
            return f"{reason} of an unreadable type", True
        if dividend and amount is None:
            return f"{reason} with an unreadable amount", True
        if not dividend and name.lower() not in KNOWN_ACTIONS:
            return f"{reason} of an unknown type", True
        return reason, False                          # amount 0: not announced yet, held back
    if not dates or None in dates:
        return f"{name or 'action'} without a readable ex-date", True
    return None


def basis_events(actions: list, decision: Mapping, today: dt.date) -> list[tuple[str, bool]]:
    """(reason, unreadable) per corporate action that holds the decision back.

    Every action except a dividend below LARGE_DIVIDEND of the entry counts (splits, bonuses,
    rights, and any type not known here), when any of its ex-dates is after the decision day and
    on or before the run day: the provider back-adjusts history up to the day it is fetched, so
    an ex-date after the window still shifts it. Fail closed on what cannot be read or is not
    known: an action, its type, an unknown type or a dividend's amount in the window, or an
    unparsable ex-date when no ex-date in the window is readable. Those are `unreadable` and make
    the run PARTIAL (a renamed field or a new type must not hold decisions back unseen).
    """
    return [event for event in (_basis_event(item, decision, today) for item in actions) if event]


def _held_back(repo, cache: dict, decision: Mapping, *, client, token: str, today: dt.date,
               fetch_actions: Callable, sleep: Callable[[float], None],
               check_lease: Callable[[], None] | None, notes: dict) -> bool:
    """True (logged) when a price-basis corporate action since the decision day holds it back.

    A hold-back on unreadable data is counted in `notes["unreadable_action"]` and listed in
    `notes["basis_problems"]` (the run turns PARTIAL with the reason).

    The stock's corporate actions are fetched once per run, shared by all its decisions (a failed
    answer too: it is raised again, not re-requested). A held-back stock's actions are archived
    in `corporate_actions` (the close-mode archive's table and writer), which PENDING_SQL reads:
    a non-dividend action in the window keeps the decision out of later runs' selection.
    """
    key = ("corporate_actions", decision["instrument_key"])
    if key not in cache:
        sleep(REQUEST_PAUSE_SECONDS)
        try:
            cache[key] = fetch_actions(client, token, decision["instrument_key"])
        except PermissionError:
            raise
        except Exception as exc:
            cache[key] = exc
    if isinstance(cache[key], Exception):
        raise cache[key]
    events = basis_events(cache[key], decision, today)
    if events and ("archived", key) not in cache:
        cache[("archived", key)] = True
        _guard(check_lease)
        try:
            # Best effort: the hold-back stands without it; the mark only saves later runs a slot.
            repo.archive_corporate_actions(isin_of(decision["instrument_key"]),
                                           [item for item in cache[key] if isinstance(item, Mapping)])
        except Exception as exc:
            LOGGER.warning("Stage-2 maturation: corporate-actions archive write skipped: %s",
                           type(exc).__name__)
    unreadable = [reason for reason, bad in events if bad]
    if unreadable:
        LOGGER.warning("Stage-2 maturation: %s held back on unreadable corporate actions (%s)",
                       decision.get("trading_symbol"), "; ".join(unreadable[:3]))
        notes["unreadable_action"] = notes.get("unreadable_action", 0) + 1
        notes.setdefault("basis_problems", []).append(
            {"observation_id": decision.get("observation_id"), "error_kind": "UnreadableCorporateAction",
             "message": "; ".join(unreadable[:3])[:200]})
    elif events:
        LOGGER.info("Stage-2 maturation: %s held back (%s)", decision.get("trading_symbol"),
                    "; ".join(reason for reason, _ in events[:3]))
    return bool(events)


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
            daily = fetch_daily(client, token, decision["instrument_key"],
                                as_of - dt.timedelta(days=HISTORY_LEAD_DAYS), today - dt.timedelta(days=1))
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
            + (f", {summary['basis_mismatch']} price-basis mismatches" if summary.get("basis_mismatch") else "")
            + (f", {summary['unreadable_action']} held back on unreadable corporate actions"
               if summary.get("unreadable_action") else "")
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
                         fetch_actions: Callable = fetch_corporate_actions,
                         check_lease: Callable[[], None] | None = None,
                         environ: Mapping[str, str] | None = None,
                         sleep: Callable[[float], None] = time.sleep,
                         clock: Callable[[], float] = time.monotonic) -> dict:
    """Collector entry point. Returns a JSON summary; raises only LeaseLost.

    `fetch_daily(client, token, key, from_date, to_date)` and
    `fetch_minutes(client, token, key, from_date, to_date)` are the collector's Upstox history
    fetchers (injected: this module must not import scheduled_collector); `fetch_actions(client,
    token, instrument_key)` defaults to this module's corporate-actions request. A rejected token
    (PermissionError) or an empty or stale NIFTY benchmark stops the run as FAILED; an HTTP 4xx on one
    instrument's daily request is counted as `provider_rejected` (a 4xx on the minute request is a failure); any other per-decision error (including a
    malformed row, inputs missing from the ledger batch or an unreadable corporate-actions answer) is
    counted as failed and the run goes on. A decision whose stock had a price-basis corporate action
    since the decision day is held back before any history request (`corporate_action`).
    """
    if not maturation_enabled(environ):
        return {"status": "DISABLED", "reason": f"{ENABLE_ENV} is not enabled"}
    started = clock()
    summary = {"status": "SUCCESS", "pending": 0, "awaiting_sessions": 0, "selected": 0, "stored": 0,
               "already_stored": 0, "deferred": 0, "unlabelled": 0, "no_benchmark": 0,
               "corporate_action": 0, "unreadable_action": 0, "basis_mismatch": 0,
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
                if _held_back(repo, cache, decision, client=client, token=token, today=today,
                              fetch_actions=fetch_actions, sleep=sleep, check_lease=check_lease,
                              notes=summary):
                    summary["corporate_action"] += 1
                    continue
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
    # A basis mismatch is rare when the anchor works (an event the feed does not list) and total
    # when it does not (a restated feed): each one is reported, so neither can pass unseen.
    failures.extend(summary.pop("basis_problems", []))
    _report(repo, summary, failures, check_lease)
    summary["seconds"] = round(clock() - started, 1)
    return summary
