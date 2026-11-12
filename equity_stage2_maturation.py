"""Forward outcome labels for scheduled Stage-2 shadow passes (Phase 5). Shadow-only; never orders.

Each scheduled scan's shadow Stage-2 (equity_stage2_collector) records its decisions in one
ledger batch and one scanner row per shortlisted ticker, but nothing ever measured what happened
next: the existing maturation (`scheduled_collector.update_matured_targets`) only labels app
decisions that carry a DECISION_EVALUATED event, and only in `close` mode, which is switched off.

When `SCHEDULED_STAGE2_MATURATION` is on, every scan run labels shadow passes whose 15-session
exit session has completed, under two frozen level policies on the same decision:

- `incumbent-levels-v1`: the stop and target the decision was recorded with
  (`derive_long_trade_levels`: stop = min(entry - 1.5 ATR, 20-day low - 0.15 ATR)).
- `atr15-stop-v1`: the research challenger, stop = entry - 1.5 ATR with the same target logic.

Label `SHADOW_LABEL_VERSION`: the app's own trade plan (`trade_contracts.build_trade_timing`,
what the app shows with every decision), executed on the stock's one-minute bars, net of the
decision's estimated round-trip costs:

- entry at the open of the first minute bar that starts after the decision time and within the
  entry window the app showed (15 minutes, never past 15:15) on the decision day; no such bar =
  no trade (`no_fill`, no label), never a later day;
- exit at the first bar that reaches the stop (stop first when a bar reaches both; filled at the
  bar's open when it opened below the stop, a gap through it) or the target (filled at the
  target), else at 15:15 on the 15th regular session after the decision day (the app's mandatory
  exit; build_trade_timing counts weekdays, NIFTY's bars apply holidays, special sessions such as
  Muhurat never count), priced within 5 minutes of 15:15;
- every session of that window must have the stock's daily bar (neither feed: `no_trading`; only
  the minutes: a reported gap) and valid minute bars, and each session's minutes and daily bar must agree on whether a level was
  reached, up to the outcome (else `window_problem`, reported): no touch only one feed shows;
- the NIFTY benchmark covers the same minutes: from the open of the entry minute to the open of
  the exit minute when the stock exits at a bar's open (15:15 time exit, gap stop), else to the
  close of the exit minute (a stop or target inside the bar, a last-close time exit).

Both policies are labelled from one fetch and stored together, or not at all (a missing NIFTY
window for either, `no_benchmark`, retries both later), so a pair never mixes two fetches.
The production label (`prediction_validation.compute_forward_target`, `net-excess-execution-v2`)
is unchanged: it reads minute bars only on days whose daily bar shows a touch, lets an in-session
entry slip to a later day and ends a time exit after the 14th session, which is why it is not
used here (the earlier shadow version built on it never stored a label).

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

Dispositions (`save_dispositions`, table `stage2_shadow_dispositions`, DDL
`sql/stage2_shadow_dispositions.sql`, run by the owner): at the end of a run, every decision it
attempted gets one row per label version, upserted with what that attempt concluded (`labelled`,
or the reason it was not: the summary counter it moved, see `disposition`), every conclusion the
decision has had (`reasons`), the counters and messages behind the last one, and the attempt
count. The run summary only counts reasons; the table keeps which decision had which reason, so
held, failed and expired passes can be listed (`sql/stage2_shadow_dispositions_report.sql`) and
the passes ever rejected by a check counted, also when a retry labelled them. A run stopped by a
rejected token keeps the rows of the decisions before it; a lost lease or a killed job writes none
(the report starts from the shadow passes and takes "labelled" from the stored labels, so a pass
labelled then is still final, and a pass with no row shows as `no_record`). It
records, it never selects: retries, exclusions and expiry are unchanged. A failed disposition
write makes the run PARTIAL (`DispositionWriteFailed`); the labels already stored stand.
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
from nifty_session_calendar import SPECIAL
from production_repository import SCHEMA, _date_value, _executemany
from trade_contracts import INTRADAY_TIME_EXIT, build_trade_timing

LOGGER = logging.getLogger(__name__)

ENABLE_ENV = "SCHEDULED_STAGE2_MATURATION"
HORIZON_SESSIONS = 15
INCUMBENT = "incumbent-levels-v1"
CHALLENGER = "atr15-stop-v1"
POLICIES = (INCUMBENT, CHALLENGER)
VERSION_PREFIX = "stage2-shadow"
# The app's own trade plan, executed on one-minute bars (see label_decision). Replaces
# "net-excess-execution-v2.minute-aligned-v1", which no stored label ever used.
SHADOW_LABEL_VERSION = "net-excess-app-contract-v1"
ENTRY_QUALITY = "app_contract_first_minute_in_entry_window"
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

# One row per decision and label version; each attempt replaces the conclusion, adds it to the
# conclusions seen (first-seen order) and counts itself.
DISPOSITION_SQL = f"""
    INSERT INTO {SCHEMA}.stage2_shadow_dispositions AS d
        (observation_id, label_version, disposition, reasons, detail, attempts, first_at, last_at)
    SELECT v.observation_id, v.label_version, v.disposition, ARRAY[v.disposition], v.detail::jsonb,
           1, now(), now()
    FROM (VALUES (%s, %s, %s, %s)) AS v(observation_id, label_version, disposition, detail)
    ON CONFLICT (observation_id, label_version) DO UPDATE SET
        disposition = EXCLUDED.disposition, detail = EXCLUDED.detail,
        reasons = CASE WHEN EXCLUDED.disposition = ANY(d.reasons) THEN d.reasons
                       ELSE d.reasons || EXCLUDED.disposition END,
        attempts = d.attempts + 1, last_at = EXCLUDED.last_at
"""

# A decision's disposition when it is not labelled: the first summary counter it moved, in this
# order (the most specific reason first: an unreadable action also counts as corporate_action).
NOT_LABELLED = ("unreadable_action", "corporate_action", "provider_rejected", "failed", "deferred",
                "basis_mismatch", "window_problem", "no_trading", "no_fill", "no_benchmark",
                "invalid_levels", "outside_levels")
# Label counts, never a reason: `unlabelled` moves with every policy left without a label, so it
# names a decision only when nothing else moved (a reason counted later is named, not hidden by it).
LABEL_COUNTS = ("stored", "already_stored", "unlabelled")


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


def _recorded_time(value) -> pd.Timestamp | None:
    """A recorded timezone-aware timestamp, or None when absent or unreadable."""
    try:
        stamp = pd.Timestamp(value) if value else None
    except (TypeError, ValueError):
        return None
    return stamp if stamp is not None and stamp.tzinfo is not None else None


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
        entry_valid_until=_recorded_time((inputs.get("timing") or {}).get("entry_valid_until")),
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
    sessions = [pd.Timestamp(d) for d in _regular(benchmark.index)]
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


def _before(frame: pd.DataFrame | None, today: dt.date) -> pd.DataFrame:
    """Completed evidence only: drop anything stamped on or after the run's IST date."""
    if frame is None or frame.empty:
        return pd.DataFrame(index=pd.DatetimeIndex([]))
    return frame.loc[frame.index.normalize() < pd.Timestamp(today)]


def _regular(index: pd.DatetimeIndex) -> list[dt.date]:
    """Sorted weekday dates of `index` without the special sessions (see regular_sessions)."""
    return sorted({d.date() for d in index.normalize() if d.weekday() < 5 and str(d.date()) not in SPECIAL})


def regular_sessions(benchmark: pd.DataFrame | None, today: dt.date) -> list[dt.date]:
    """Completed regular NSE sessions: NIFTY's bar dates before today, weekdays only, without the
    special sessions `nifty_session_calendar.SPECIAL` lists (Muhurat, budget weekends, DR drills).

    The app counts weekdays for its exit day; NIFTY's bars apply the holidays. A special session
    never counts towards the horizon (its bars still sit on the label's minute path).
    """
    return _regular(_before(benchmark, today).index)


def exit_session(as_of: dt.date, benchmark: pd.DataFrame | None, today: dt.date) -> dt.date | None:
    """The HORIZON_SESSIONS-th completed regular session after the decision day, or None if not yet.

    The app's mandatory exit day; completed_decisions selects on the same count (regular_sessions),
    so selection, the fetch range and the label window agree.
    """
    sessions = [d for d in regular_sessions(benchmark, today) if d > as_of]
    return sessions[HORIZON_SESSIONS - 1] if len(sessions) >= HORIZON_SESSIONS else None


def _naive_ist(value) -> pd.Timestamp:
    """A timestamp as a naive IST wall-clock time (the bars' own convention)."""
    at = pd.Timestamp(value)
    return at.tz_convert(IST).tz_localize(None) if at.tzinfo else at


def trade_contract(decision: Mapping, benchmark: pd.DataFrame, today: dt.date) -> tuple[dict | None, str]:
    """(the app's trade plan for this decision, "" ) or (None, why not).

    `build_trade_timing` is what the app showed: enter within ENTRY_WINDOW_MINUTES of the decision
    (never past 15:15), exit at the stop or target, else no later than 15:15 on the 15th session.
    Entry is the open of the first minute bar that starts after the decision time and by the end
    of that window (a bar that started before the decision could not be bought at its open);
    the exit session comes from the NIFTY calendar. `sessions` is every session from the
    decision day to the exit session: the window both labels and the benchmark use.
    """
    decided_at = _naive_ist(decision["evaluated_at"])
    as_of = decision["as_of_date"]
    if decided_at.date() != as_of:
        return None, f"decision time {decided_at} is not on the decision day {as_of}"
    timing = build_trade_timing(decision["evaluated_at"], horizon_sessions=HORIZON_SESSIONS)
    if not timing["entry_window_open"]:
        return None, "no_entry_window"
    # The window the app showed (recorded with the decision), else the same function's answer.
    entry_until = decision.get("entry_valid_until") or timing["entry_valid_until"]
    end = exit_session(as_of, benchmark, today)
    if end is None:
        return None, "awaiting"
    calendar = regular_sessions(benchmark, today)
    if as_of not in calendar:
        return None, f"the decision day {as_of} is not a regular NIFTY session"
    return {"decided_at": decided_at, "entry_until": _naive_ist(entry_until),
            "exit_at": pd.Timestamp(dt.datetime.combine(end, INTRADAY_TIME_EXIT)),
            "sessions": [d for d in calendar if as_of <= d <= end]}, ""


def _bars_valid(frame: pd.DataFrame) -> bool:
    """Unique, ordered, finite, positive and internally consistent OHLC bars."""
    if not (frame.index.is_unique and frame.index.is_monotonic_increasing):
        return False
    values = frame[["Open", "High", "Low", "Close"]].astype(float)
    if not (values.map(math.isfinite).all().all() and (values > 0).all().all()):
        return False
    return bool((values["High"] >= values[["Open", "Close", "Low"]].max(axis=1)).all()
                and (values["Low"] <= values[["Open", "Close"]].min(axis=1)).all())


def _window_problem(contract: dict, daily: pd.DataFrame, minutes: pd.DataFrame) -> tuple[str, str] | None:
    """(kind, message) when the window's bars cannot carry a label, else None.

    kind "no_trading": a session with neither a daily nor a minute bar (the stock did not trade:
    suspended or halted). kind "missing": a data gap or a bad bar (one feed has the session and
    the other not, or invalid bars), reported. A special-session day inside the window (it never
    counts, see regular_sessions) is checked the same way when the stock has bars on it (those
    bars sit on the minute path); without any it is not part of the window.
    """
    days, minute_days = daily.index.normalize(), minutes.index.normalize()
    for session in _path_days(contract, daily, minutes):   # a special day only when it has bars
        stamp = pd.Timestamp(session)
        if not (days == stamp).any():
            if (minute_days == stamp).any():
                return "missing", f"no daily bar on {session} (minute bars present)"
            return "no_trading", f"no daily bar on {session}"
        if not (minute_days == stamp).any():
            return "missing", f"no minute bars on {session}"
        if not (_bars_valid(daily.loc[days == stamp]) and _bars_valid(minutes.loc[minute_days == stamp])):
            return "missing", f"invalid bars on {session}"
    return None


def _path_days(contract: dict, daily: pd.DataFrame, minutes: pd.DataFrame) -> list[dt.date]:
    """The window's regular sessions plus any other day inside it that has the stock's bars."""
    first, last = contract["sessions"][0], contract["sessions"][-1]
    stamped = {d.date() for d in daily.index.normalize()} | {d.date() for d in minutes.index.normalize()}
    return sorted(set(contract["sessions"]) | {d for d in stamped if first < d < last})


def _walk(contract: dict, minutes: pd.DataFrame, stop: float, target: float) -> dict | str:
    """The trade on one-minute bars, or "no_fill" / "outside_levels" / "no_exit_bar".

    Entry: see trade_contract. Then bar by bar until the 15:15 exit: a bar whose low reaches the
    stop ends it (stop first when one bar reaches both), filled at the stop, or at the bar's open
    when it opened below the stop (a gap through it); a bar whose high reaches the target ends it
    at the target (conservative, even after a gap up). Otherwise the time exit sells at the open
    of the first bar from 15:15 on the exit day, or at the close of its last bar before 15:15,
    either within BENCH_GAP of 15:15 (else "no_exit_bar": the feed stops early or the stock did
    not trade near the exit; never an exit hours early). `exit_on_open` says which price the
    benchmark must match.
    """
    at = minutes.index
    # The entry window never leaves the decision day (build_trade_timing caps it at 15:15).
    entry_bars = minutes.loc[(at > contract["decided_at"]) & (at <= contract["entry_until"])]
    if entry_bars.empty:
        return "no_fill"
    entry_at, entry = entry_bars.index[0], float(entry_bars.iloc[0]["Open"])
    if not stop < entry < target:
        return "outside_levels"
    exit_at = contract["exit_at"]
    path = minutes.loc[(at >= entry_at) & (at < exit_at)]
    stopped = path["Low"].to_numpy(dtype=float) <= stop
    touched = stopped | (path["High"].to_numpy(dtype=float) >= target)
    if touched.any():
        first = int(touched.argmax())
        stamp, opened = path.index[first], float(path["Open"].iloc[first])
        if stopped[first]:
            gap = opened < stop   # never the entry bar: its open is the entry, above the stop
            return {"entry_at": entry_at, "entry": entry, "outcome": "stop", "exit_at": stamp,
                    "exit": opened if gap else float(stop), "exit_on_open": gap,
                    "fill": "gap_open" if gap else "stop"}
        return {"entry_at": entry_at, "entry": entry, "outcome": "target", "exit_at": stamp,
                "exit": float(target), "exit_on_open": False, "fill": "target"}
    after = minutes.loc[(at >= exit_at) & (at <= exit_at + BENCH_GAP)]
    if not after.empty:
        return {"entry_at": entry_at, "entry": entry, "outcome": "horizon", "exit_at": after.index[0],
                "exit": float(after.iloc[0]["Open"]), "exit_on_open": True, "fill": "time_exit_open"}
    before = minutes.loc[(at < exit_at) & (at >= exit_at - BENCH_GAP)]
    if before.empty:
        return "no_exit_bar"
    return {"entry_at": entry_at, "entry": entry, "outcome": "horizon", "exit_at": before.index[-1],
            "exit": float(before.iloc[-1]["Close"]), "exit_on_open": False, "fill": "time_exit_last_close"}


def _touch_problem(contract: dict, daily: pd.DataFrame, minutes: pd.DataFrame, stop: float,
                   target: float, until: dt.date) -> str | None:
    """A session up to the outcome where the daily and minute bars disagree on a stop or target touch.

    Each session's whole-day minute range must reach a level exactly when its daily bar does: a
    touch only one feed shows (a missed minute stop, a bad print) makes the path ambiguous.
    """
    days, minute_days = daily.index.normalize(), minutes.index.normalize()
    for session in (d for d in _path_days(contract, daily, minutes) if d <= until):
        stamp = pd.Timestamp(session)
        bar, day = daily.loc[days == stamp].iloc[0], minutes.loc[minute_days == stamp]
        checks = (("stop", float(bar["Low"]) <= stop, float(day["Low"].min()) <= stop),
                  ("target", float(bar["High"]) >= target, float(day["High"].max()) >= target))
        for name, daily_hit, minute_hit in checks:
            if daily_hit != minute_hit:
                return (f"the daily and minute bars disagree on the {name} touch on {session} "
                        f"(daily {'hit' if daily_hit else 'no hit'})")
    return None


def _nifty_return(bench_minutes: pd.DataFrame, entry_at: pd.Timestamp, exit_at: pd.Timestamp,
                  exit_on_open: bool) -> tuple[float, pd.Timestamp, pd.Timestamp] | None:
    """(NIFTY return, start minute, end minute) over the stock's own holding window, or None.

    From the open of the first NIFTY minute at or after the entry minute to the open of the first
    minute at or after the exit minute (an exit at a bar open) or the close of the last minute at
    or before it (an exit inside a bar), each at most BENCH_GAP away and never reversed.
    """
    if bench_minutes is None or bench_minutes.empty:
        return None
    at = bench_minutes.index
    start = bench_minutes.loc[(at >= entry_at) & (at <= entry_at + BENCH_GAP), "Open"]
    if start.empty:
        return None
    if exit_on_open:
        end = bench_minutes.loc[(at >= exit_at) & (at <= exit_at + BENCH_GAP), "Open"].head(1)
    else:
        end = bench_minutes.loc[(at <= exit_at) & (at >= max(exit_at - BENCH_GAP, start.index[0])), "Close"].tail(1)
    if end.empty:
        return None
    base, final = float(start.iloc[0]), float(end.iloc[0])
    if not (math.isfinite(base) and math.isfinite(final) and base > 0 and final > 0):
        return None
    return final / base - 1.0, start.index[0], end.index[0]


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
        if not all(math.isfinite(value) and value > 0 for value in (entry, low, high)) or low > high:
            return f"invalid {name} decision-day range or recorded entry"
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


def _problem(notes: dict | None, decision: Mapping, kind: str, message: str) -> None:
    """Count and list a label-window problem (reported: the run turns PARTIAL with the reason)."""
    LOGGER.warning("Stage-2 maturation: %s %s", decision.get("trading_symbol"), message)
    if notes is not None:
        notes["window_problem"] = notes.get("window_problem", 0) + 1
        notes.setdefault("basis_problems", []).append(
            {"observation_id": decision.get("observation_id"), "error_kind": kind, "message": message[:200]})


def _count(notes: dict | None, key: str) -> None:
    """Count a quiet, expected reason for no label."""
    if notes is not None:
        notes[key] = notes.get(key, 0) + 1


def label_decision(decision: Mapping, *, daily: pd.DataFrame, minutes: pd.DataFrame,
                   benchmark: pd.DataFrame | None, benchmark_minutes: pd.DataFrame | None,
                   today: dt.date, notes: dict | None = None) -> dict[str, dict | None]:
    """Labels per policy for one decision whose exit session has completed (see exit_session).

    `benchmark` and `benchmark_minutes` are NIFTY's daily and one-minute bars. The label executes
    the app's own trade plan (trade_contract, _walk) on the stock's one-minute bars, net of the
    decision's estimated round-trip costs, against NIFTY over the same minutes.

    Both policies share the decision, the entry and one fetch, and are labelled together or not
    at all: every policy maps to None when the history is off the recorded price basis
    (`basis_mismatch`), the window's bars are missing, invalid or disagree on a touch
    (`window_problem`, reported), the stock did not trade on a session (`no_trading`), no bar
    traded in the entry window (`no_fill`), or either policy's NIFTY window is missing
    (`no_benchmark`): a later run retries with fresh bars for both. Only a policy whose own
    levels are invalid (`invalid_levels`), or that the actual entry price is not strictly inside
    (`outside_levels`), maps to None alone: that never changes on a retry.
    """
    daily, minutes = _before(daily, today), _before(minutes, today)
    bench_daily, bench_minutes = _before(benchmark, today), _before(benchmark_minutes, today)
    none = {policy: None for policy in POLICIES}
    problem = _basis_problem(decision, daily=daily, minutes=minutes)
    if problem is not None:
        LOGGER.warning("Stage-2 maturation: %s %s", decision.get("trading_symbol"), problem)
        if notes is not None:
            notes["basis_mismatch"] = notes.get("basis_mismatch", 0) + 1
            notes.setdefault("basis_problems", []).append(
                {"observation_id": decision.get("observation_id"), "error_kind": "BasisMismatch",
                 "message": problem[:200]})
        return none
    contract, why = trade_contract(decision, bench_daily, today)
    if contract is None:
        if why == "no_entry_window":
            _count(notes, "no_fill")
        elif why != "awaiting":
            _problem(notes, decision, "WindowProblem", why)
        return none
    window = _window_problem(contract, daily, minutes)
    if window is not None:
        if window[0] == "no_trading":
            _count(notes, "no_trading")
        else:
            _problem(notes, decision, "WindowProblem", window[1])
        return none
    levels = {
        INCUMBENT: (decision["stop"], decision["target"]),
        CHALLENGER: challenger_levels(decision["entry"], decision["atr"],
                                      decision["resistance20"], decision["resistance60"]),
    }
    labels = {}
    for policy, level in levels.items():
        if level is None:
            _count(notes, "invalid_levels")
            labels[policy] = None
            continue
        trade = _walk(contract, minutes, *level)
        if trade == "no_fill":
            _count(notes, "no_fill")
            return none
        if trade == "outside_levels":
            _count(notes, "outside_levels")
            labels[policy] = None
            continue
        if trade == "no_exit_bar":
            _problem(notes, decision, "WindowProblem",
                     f"no minute bar within {BENCH_GAP.seconds // 60} minutes of the "
                     f"{contract['exit_at']:%Y-%m-%d %H:%M} time exit")
            return none
        touch = _touch_problem(contract, daily, minutes, *level, until=trade["exit_at"].date())
        if touch is not None:
            _problem(notes, decision, "TouchDisagreement", touch)
            return none
        bench = _nifty_return(bench_minutes, trade["entry_at"], trade["exit_at"], trade["exit_on_open"])
        if bench is None:
            _count(notes, "no_benchmark")
            return none
        gross = trade["exit"] / trade["entry"] - 1.0
        net = gross - float(decision["cost_bps"]) / 10_000.0
        labels[policy] = {
            "target_version": shadow_target_version(policy), "horizon_sessions": HORIZON_SESSIONS,
            "entry_date": contract["sessions"][0].isoformat(),
            "label_end_date": contract["sessions"][-1].isoformat(),
            "outcome_date": trade["exit_at"].date().isoformat(), "outcome": trade["outcome"],
            "target_before_stop": int(trade["outcome"] == "target"),
            "entry": trade["entry"], "exit": trade["exit"], "fill": trade["fill"],
            "entry_timestamp": trade["entry_at"].isoformat(), "exit_timestamp": trade["exit_at"].isoformat(),
            "benchmark_start": bench[1].isoformat(), "benchmark_end": bench[2].isoformat(),
            "gross_return": gross, "net_return": net, "benchmark_return": bench[0],
            "excess_return": net - bench[0], "positive_excess": int(net - bench[0] > 0),
            "cost_bps": float(decision["cost_bps"]), "entry_quality": ENTRY_QUALITY,
            "stop": level[0], "target": level[1],
        }
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
    actions = payload["data"]   # Upstox answers [] for no actions (233 of 563 stored, 0 null): null is unreadable
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
    dates = _ex_dates(item)
    inside = sorted(d for d in dates if d is not None and decision["as_of_date"] < d <= today)
    if dividend and amount is not None and 0 < amount < LARGE_DIVIDEND * float(decision["entry"]):
        # A small dividend never moves the basis, but only one clear date proves it is the
        # dividend it says: an unreadable date, or dates that disagree with one in the window,
        # is reported; dates that all lie outside the window do not matter.
        if not dates or None in dates:
            return f"{name} without a readable ex-date", True
        if inside and len(set(dates)) > 1:
            return f"{name} with conflicting ex-dates", True
        return None
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
             fetch_daily: Callable, fetch_minutes: Callable, sleep: Callable[[float], None],
             benchmark: pd.DataFrame):
    """(daily, minutes, exit session, NIFTY minutes) for a stock and decision day, once per run.

    Minutes (the stock's, then NIFTY's for the same window, shared by every stock with that
    window) are fetched only once the exit session (exit_session, NIFTY calendar) has completed,
    from the decision day to it.
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
        # An empty answer (HTTP 200, no candles: a renamed or delisted key) stays quietly deferred.
        end = None if _before(daily, today).empty else exit_session(as_of, benchmark, today)
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
    """Label one decision under both policies and store, together, the labels it does not have yet.

    label_decision returns every policy's label from one fetch or none of them (see there), so a
    pair is never mixed from two fetches. shortcut: the two inserts are separate statements, so
    a crash between them leaves one policy stored and the next run labels the other from fresh
    bars; upgrade to a single-transaction insert in production_repository if that is ever seen.
    """
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
            + (f", {summary['window_problem']} label-window problems" if summary.get("window_problem") else "")
            + (f", {summary['unreadable_action']} held back on unreadable corporate actions"
               if summary.get("unreadable_action") else "")
            + (f", stopped by {summary['stopped']}" if summary.get("stopped") else "")
            + (f", dispositions not written ({summary['disposition_error']})"
               if summary.get("disposition_error") else ""),
            {"summary": summary, "failures": failures[:FAILURE_DETAIL_LIMIT]},
        )
    except Exception as exc:
        LOGGER.warning("Stage-2 maturation quality-event write skipped: %s", type(exc).__name__)


def _counters(summary: dict) -> dict:
    """The run summary's counters, to diff one decision's attempt against."""
    return {key: value for key, value in summary.items() if type(value) is int}


def _disposition_row(observation_id: str, name: str, counts: dict, notes: list[dict]) -> tuple:
    """(observation_id, label version, disposition, detail JSON); messages naming the decision, at most 3."""
    # jsonb rejects a NUL character, and one bad row would lose the whole run's batch.
    messages = [f"{note.get('error_kind')}: {note.get('message')}".replace("\x00", "")[:200]
                for note in notes if note.get("observation_id") == observation_id][:3]
    detail = {"counts": counts, **({"messages": messages} if messages else {})}
    return (observation_id, SHADOW_LABEL_VERSION, name, json.dumps(detail, sort_keys=True))


def disposition(observation_id: str, before: dict, summary: dict, failures: list[dict]) -> tuple:
    """One decision's disposition row from the summary counters its attempt moved.

    Every path through a decision moves at least one counter, so a reason added later can never
    go unrecorded: `labelled` when every policy now has its label (stored this run or before),
    else the first moved counter in NOT_LABELLED, else the first other moved counter that is not
    in LABEL_COUNTS (a reason counted later, e.g. by _count), else `unlabelled`.
    `before` is _counters(summary) at the attempt's start; messages are the reported problems
    and failures naming the decision (a run attempts each decision once).
    """
    after = _counters(summary)
    moved = {key: after[key] - before.get(key, 0) for key in after if after[key] != before.get(key, 0)}
    if moved.get("stored", 0) + moved.get("already_stored", 0) == len(POLICIES):
        name = "labelled"
    else:
        other = (key for key in moved if key not in LABEL_COUNTS)
        name = next((key for key in NOT_LABELLED if moved.get(key)), next(other, "unlabelled"))
    return _disposition_row(observation_id, name, moved, summary.get("basis_problems", []) + failures)


def save_dispositions(repo, rows: list[tuple], check_lease: Callable[[], None] | None) -> None:
    """Upsert a run's disposition rows in one transaction (no connection when there are none)."""
    if not rows:
        return
    _guard(check_lease)
    with repo.connect() as conn:
        _executemany(conn, DISPOSITION_SQL, rows)
        conn.commit()


def _record_dispositions(repo, rows: list[tuple], summary: dict, failures: list[dict],
                         check_lease: Callable[[], None] | None) -> None:
    """save_dispositions for the run; a failure is loud, not fatal (only LeaseLost raises).

    The labels already stored stand; the run turns PARTIAL with `DispositionWriteFailed` and
    `summary["disposition_error"]`, so a missing table or grant cannot go unseen.
    """
    try:
        save_dispositions(repo, rows, check_lease)
        summary["dispositions"] = len(rows)
    except LeaseLost:
        raise
    except Exception as exc:
        LOGGER.warning("Stage-2 maturation: disposition write failed: %s", type(exc).__name__)
        summary["disposition_error"] = type(exc).__name__
        failures.append({"observation_id": None, "error_kind": "DispositionWriteFailed",
                         "message": f"{type(exc).__name__}: {exc}"[:200]})


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
    since the decision day is held back before any history request (`corporate_action`). Every
    attempted decision's disposition is upserted at the end (save_dispositions; a failed write
    makes the run PARTIAL).
    """
    if not maturation_enabled(environ):
        return {"status": "DISABLED", "reason": f"{ENABLE_ENV} is not enabled"}
    started = clock()
    summary = {"status": "SUCCESS", "pending": 0, "awaiting_sessions": 0, "selected": 0, "stored": 0,
               "already_stored": 0, "deferred": 0, "unlabelled": 0, "no_benchmark": 0,
               "no_fill": 0, "no_trading": 0, "outside_levels": 0, "invalid_levels": 0, "window_problem": 0,
               "corporate_action": 0, "unreadable_action": 0, "basis_mismatch": 0,
               "provider_rejected": 0, "failed": 0, "stopped": None}
    failures: list[dict] = []
    dispositions: list[tuple] = []
    try:
        _guard(check_lease)
        benchmark, rows = _select(repo, client, token, today=today, fetch_daily=fetch_daily, sleep=sleep,
                                  summary=summary, failures=failures)
        # Selected decisions missing from their ledger batch (the only failures _select records).
        dispositions += [_disposition_row(item["observation_id"], "failed", {"failed": 1}, [item])
                         for item in failures]
        cache: dict = {}
        for row in rows:
            if clock() - started > BUDGET_SECONDS:
                # Selected work left undone: PARTIAL, so the scan run says so; later runs retry it.
                summary.update(stopped="BUDGET", status="PARTIAL")
                break
            _guard(check_lease)
            before = _counters(summary)
            try:
                decision = parse_pending_row(row)
                if _held_back(repo, cache, decision, client=client, token=token, today=today,
                              fetch_actions=fetch_actions, sleep=sleep, check_lease=check_lease,
                              notes=summary):
                    summary["corporate_action"] += 1
                else:
                    history = _history(cache, decision, client=client, token=token, today=today,
                                       fetch_daily=fetch_daily, fetch_minutes=fetch_minutes, sleep=sleep,
                                       benchmark=benchmark)
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
            dispositions.append(disposition(row[0], before, summary, failures))
    except LeaseLost:
        raise
    except Exception as exc:
        LOGGER.error("Stage-2 shadow maturation failed: %s", type(exc).__name__)
        summary.update(status="FAILED", error_type=type(exc).__name__)
    _record_dispositions(repo, dispositions, summary, failures, check_lease)
    # A basis mismatch is rare when the anchor works (an event the feed does not list) and total
    # when it does not (a restated feed): each one is reported, so neither can pass unseen.
    failures.extend(summary.pop("basis_problems", []))
    _report(repo, summary, failures, check_lease)
    summary["seconds"] = round(clock() - started, 1)
    return summary
