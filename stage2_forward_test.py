"""PREREG3 forward test of the live pipeline (claude/PREREG_2026-11-24_live_pipeline_forward.md, v1.3).

Question: if you bought every pass the live pipeline produces (Stage-1 top-150 shortlist + Stage-2 pass;
first scan of each stock-day; incumbent levels; label net-excess-app-contract-v2, net of the decision's own
costs), would you beat NIFTY? Q2: do passes scoring >= 60 beat those below 60?

Input: the rows of sql/stage2_forward_test_rows.sql as a JSON array (the read-only query's output).
Output: one entry per look reached (L1..L5 = 20 / 40 / 60 / 125 / 250 eligible decision days). A look uses
exactly its first N eligible decision days and is READY at the first run where those days are fixed (no
earlier first-scan day still waiting to become eligible) and either every decision of them is settled or at
most 5% lack an incumbent label (else LOOK_NOT_READY). The first READY export is frozen (saved with its
sha256) and is that look forever; re-running this tool on the frozen file reproduces it exactly. Before L1
and at L1 / L2: describe only; L3-L5: the pre-registered verdicts. Research only: no database writes, no
orders, no network.

Usage: python stage2_forward_test.py rows.json [--out report.json]
"""
from __future__ import annotations

import argparse
import codecs
import datetime as dt
import hashlib
import json
import logging
import math
import random
import re
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

LOGGER = logging.getLogger("stage2_forward_test")

VERSION = "prereg3-v1.3"
LOOKS = (("L1", 20), ("L2", 40), ("L3", 60), ("L4", 125), ("L5", 250))
VERDICT_LOOKS = ("L3", "L4", "L5")
DESCRIBE_BLOCKS = (3, 5, 10)                 # L1 / L2: intervals reported, no verdict
VERDICT_BLOCKS = (5, 10, 15)                 # L3-L5
DRAWS = 10_000
SEED = 20261125
LEVELS = {"95": (0.025, 0.975), "90": (0.05, 0.95)}
DECISION_LEVEL = "95"
EXTRA_COST_PCT = 0.40                        # +40 bp per trade, in percentage points
MAX_NO_OUTCOME_PCT = 5                       # integer percent: compared exactly (5% of 300 is 15, not 15.000...02)
MIN_POSITIVE_MONTHS = 0.60
SCORE_SPLIT = 60.0                           # Q2
HIGH_SCORE = 70.0                            # reported sub-cohort (the live Buy gate)
MORNING_BEFORE = "12:00"
EXECUTION_REASONS = ("no_fill", "no_trading", "outside_levels")
FIELDS = ("observation_id", "day", "eligible", "scan_time", "score", "action", "incumbent_outcome",
          "incumbent_excess", "atr15_excess", "disposition", "settled", "traded_value", "queried_at",
          "total_rows")
FIRST_ELIGIBLE_DAYS = 22                     # the query returns first-scan passes at least this old
DAY = re.compile(r"\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
CLOCK = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class RowError(ValueError):
    """A row the rows query cannot produce: the whole report is refused (fail loud, never a quiet verdict)."""


def _number(row: Mapping[str, Any], key: str, *, low: float | None = None) -> float | None:
    """A finite float (JSON number or numeric string), None for null; RowError otherwise or below `low`."""
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise RowError(f"{row.get('observation_id')}: {key} is not a number")
    try:
        number = float(value)
    except ValueError:
        raise RowError(f"{row.get('observation_id')}: {key} is not a number") from None
    if not math.isfinite(number) or (low is not None and number < low):
        raise RowError(f"{row.get('observation_id')}: {key} out of range ({value!r})")
    return number


def _text(row: Mapping[str, Any], key: str, pattern: re.Pattern | None = None, *, required: bool = False) -> str | None:
    """A non-empty string (matching `pattern` if given), None for null unless required; RowError otherwise."""
    value = row.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or (pattern is not None and not pattern.fullmatch(value)):
        raise RowError(f"{row.get('observation_id')}: bad {key} ({value!r})")
    return value


def parse_rows(raw: Any) -> list[dict]:
    """Validated rows (excess in %), sorted by day then id. RowError on anything the query cannot return."""
    if not isinstance(raw, list):
        raise RowError("rows must be a JSON array")
    rows, seen, stamps, totals = [], set(), set(), set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise RowError("every row must be an object")
        missing = [key for key in FIELDS if key not in item]
        if missing:
            raise RowError(f"{item.get('observation_id')}: missing {', '.join(missing)}")
        oid = _text(item, "observation_id", required=True)
        if oid in seen:
            raise RowError(f"{oid}: duplicate decision")
        seen.add(oid)
        for flag in ("settled", "eligible"):
            if not isinstance(item[flag], bool):
                raise RowError(f"{oid}: {flag} must be true or false")
        stamps.add(_text(item, "queried_at", STAMP, required=True))
        if isinstance(item["total_rows"], bool) or not isinstance(item["total_rows"], int):
            raise RowError(f"{oid}: total_rows must be an integer")
        totals.add(item["total_rows"])
        excess = _number(item, "incumbent_excess")
        atr15 = _number(item, "atr15_excess")
        rows.append({
            "id": oid, "day": _text(item, "day", DAY, required=True), "eligible": item["eligible"],
            "time": _text(item, "scan_time", CLOCK, required=True),
            "score": _number(item, "score"), "action": _text(item, "action"),
            "outcome": _text(item, "incumbent_outcome"),
            "excess": None if excess is None else 100.0 * excess,
            "atr15": None if atr15 is None else 100.0 * atr15,
            "disposition": _text(item, "disposition"), "settled": item["settled"],
            "traded_value": _number(item, "traded_value", low=0.0), "queried_at": item["queried_at"],
        })
    if len(stamps) > 1:
        raise RowError("rows come from more than one query run")
    if rows and totals != {len(rows)}:
        raise RowError(f"{len(rows)} rows but the query returned {sorted(totals)}: the export was cut off")
    _check_days(rows)
    rows.sort(key=lambda r: (r["day"], r["id"]))
    return rows


def _check_days(rows: Sequence[Mapping[str, Any]]) -> None:
    """Eligibility is per day, and every row is at least FIRST_ELIGIBLE_DAYS old at query time."""
    flags: dict[str, set] = {}
    for row in rows:
        flags.setdefault(row["day"], set()).add(row["eligible"])
        age = (dt.date.fromisoformat(row["queried_at"][:10]) - dt.date.fromisoformat(row["day"])).days
        if age < FIRST_ELIGIBLE_DAYS:
            raise RowError(f"{row['id']}: decided {age} days before the query (under {FIRST_ELIGIBLE_DAYS})")
    mixed = sorted(day for day, seen in flags.items() if len(seen) > 1)
    if mixed:
        raise RowError(f"eligible and not-eligible rows on the same day: {', '.join(mixed)}")


# ---------- statistics ----------

def _stats(values: Sequence[float]) -> dict:
    """n, mean, median, win rate, t (rounded for display)."""
    if not values:
        return {"n": 0}
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return {"n": len(values), "mean": round(mean, 3), "median": round(statistics.median(values), 3),
            "win_rate": round(sum(v > 0 for v in values) / len(values), 3),
            "t": round(mean / (sd / math.sqrt(len(values))), 2) if sd > 0 else None}


def worst_decile(values: Sequence[float]) -> float | None:
    """Mean of the lowest ceil(n / 10) values, unrounded."""
    ordered = sorted(values)
    return statistics.fmean(ordered[:max(1, math.ceil(len(ordered) / 10))]) if ordered else None


def block_draws(cells: Sequence[Sequence[tuple[float, int]]], block: int,
                stat: Callable[[list[float], list[int]], float | None], *,
                draws: int = DRAWS, seed: int = SEED) -> list[float]:
    """Sorted statistic of each circular moving-block draw over ordered decision days.

    cells[d] = one (sum, count) pair per group for day d. A draw joins ceil(days / block) runs of
    `block` consecutive days (wrapping), pooling every decision of those days; a draw whose statistic
    is None (an empty group) is skipped. Same algorithm as stage2_rule_replay.block_interval, by day.
    """
    if not cells or block < 1:
        return []
    rng, days, groups = random.Random(seed), len(cells), len(cells[0])
    runs, values = math.ceil(days / block), []
    for _ in range(draws):
        sums, counts = [0.0] * groups, [0] * groups
        for _ in range(runs):
            start = rng.randrange(days)
            for k in range(start, start + block):
                for g, (total, n) in enumerate(cells[k % days]):
                    sums[g] += total
                    counts[g] += n
        value = stat(sums, counts)
        if value is not None:
            values.append(value)
    values.sort()
    return values


def bounds(values: Sequence[float], level: str) -> dict | None:
    """Interval from sorted draws (replay convention: index int(q x (draws - 1))); None without draws."""
    if not values:
        return None
    lo, hi = LEVELS[level]
    return {"low": values[int(lo * (len(values) - 1))], "high": values[int(hi * (len(values) - 1))],
            "draws": len(values)}


def _pooled_mean(sums: list[float], counts: list[int]) -> float | None:
    """Group 0's pooled mean (Q1), None when the draw holds no decision."""
    return sums[0] / counts[0] if counts[0] else None


def _difference(sums: list[float], counts: list[int]) -> float | None:
    """Group 0 minus group 1 pooled means (Q2), None when either group is empty in the draw."""
    return sums[0] / counts[0] - sums[1] / counts[1] if counts[0] and counts[1] else None


def _cells(days: Sequence[str], groups: Sequence[Sequence[Mapping[str, Any]]]) -> list[list[tuple[float, int]]]:
    """Per day, one (sum of excess, count) per group of valued rows."""
    index = {day: i for i, day in enumerate(days)}
    cells = [[(0.0, 0) for _ in groups] for _ in days]
    for g, rows in enumerate(groups):
        for row in rows:
            i = index[row["day"]]
            total, n = cells[i][g]
            cells[i][g] = (total + row["value"], n + 1)
    return cells


def intervals(days: Sequence[str], groups: Sequence[Sequence[Mapping[str, Any]]], blocks: Sequence[int],
              stat: Callable[[list[float], list[int]], float | None]) -> dict:
    """{block: {"95": {...}, "90": {...}}} from one set of draws per block."""
    cells = _cells(days, groups)
    out = {}
    for block in blocks:
        values = block_draws(cells, block, stat)
        out[str(block)] = {level: bounds(values, level) for level in LEVELS}
    return out


def _low_high(shown: Mapping[str, Mapping[str, dict | None]]) -> tuple[float | None, float | None]:
    """LOW = lowest decision-level lower bound over blocks, HIGH = highest upper bound (None if any is missing)."""
    chosen = [levels[DECISION_LEVEL] for levels in shown.values()]
    if not chosen or any(c is None for c in chosen):
        return None, None
    return min(c["low"] for c in chosen), max(c["high"] for c in chosen)


def complete_months(days: Sequence[str]) -> list[str]:
    """Months strictly after the first day's month and strictly before the last day's month that hold at least
    one decision day (v1.3: a month without any decision day — an outage, or no pass at all — has no trades
    to judge and is left out; a month whose decisions all lack a label counts as not positive)."""
    first, last = days[0][:7], days[-1][:7]
    return sorted({day[:7] for day in days if first < day[:7] < last})


# ---------- Q1 / Q2 ----------

def classify(low: float | None, high: float | None, mean: float, positive_share: float | None) -> tuple[str, dict]:
    """PREREG3 Q1 verdict from unrounded inputs: CLEAR_LOSS if HIGH < 0; EDGE_SIGNAL if LOW > 0 and
    mean - 0.40 > 0 and >= 60% of complete months positive; else INCONCLUSIVE."""
    checks = {
        "high_below_0": high is not None and high < 0,
        "low_above_0": low is not None and low > 0,
        "mean_after_40bp_above_0": mean - EXTRA_COST_PCT > 0,
        "positive_months_at_least_60pct": positive_share is not None and positive_share >= MIN_POSITIVE_MONTHS,
    }
    if checks["high_below_0"]:
        return "CLEAR_LOSS", checks
    if checks["low_above_0"] and checks["mean_after_40bp_above_0"] and checks["positive_months_at_least_60pct"]:
        return "EDGE_SIGNAL", checks
    return "INCONCLUSIVE", checks


def q1_verdict(days: Sequence[str], valued: Sequence[Mapping[str, Any]]) -> dict:
    """The pre-registered Q1 verdict on one set of valued decisions (labelled, or with imputed no-outcomes)."""
    values = [row["value"] for row in valued]
    if not values:
        return {"verdict": "NO_DECISION", "reason": "no labelled decision"}
    mean = statistics.fmean(values)
    shown = intervals(days, [valued], VERDICT_BLOCKS, _pooled_mean)
    low, high = _low_high(shown)
    months = complete_months(days)
    month_means = {m: (statistics.fmean([r["value"] for r in valued if r["day"][:7] == m])
                       if any(r["day"][:7] == m for r in valued) else None) for m in months}
    positive_share = (sum(v is not None and v > 0 for v in month_means.values()) / len(months)) if months else None
    verdict, checks = classify(low, high, mean, positive_share)
    return {"verdict": verdict, "checks": checks, "mean": mean, "low": low, "high": high,
            "complete_months": months, "month_means": month_means, "positive_month_share": positive_share,
            "intervals": shown}


def _valued(rows: Sequence[Mapping[str, Any]], key: str = "excess") -> list[dict]:
    """Labelled decisions as {day, value} (value = `key` in %)."""
    return [{"day": r["day"], "value": r[key]} for r in rows if r[key] is not None]


def no_outcome_reasons(rows: Sequence[Mapping[str, Any]]) -> dict:
    """No-outcome decisions by disposition: execution (no_fill, no_trading, outside_levels) or data (every
    other reason, named; "none" = no disposition recorded)."""
    out = {"execution": {}, "data": {}}
    for row in rows:
        if row["excess"] is not None:
            continue
        name = row["disposition"] or "none"
        kind = "execution" if name in EXECUTION_REASONS else "data"
        out[kind][name] = out[kind].get(name, 0) + 1
    return out


def q1(days: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> dict:
    """Q1 with the no-outcome rule: > 5% no-outcome -> the labelled verdict must survive both imputations."""
    labelled = _valued(rows)
    missing_count = len(rows) - len(labelled)
    base = q1_verdict(days, labelled)
    result = {**base, "no_outcome_share": missing_count / len(rows) if rows else 1.0, "no_outcome_rule": "not needed"}
    if missing_count * 100 > MAX_NO_OUTCOME_PCT * len(rows) and labelled:
        floor = worst_decile([r["value"] for r in labelled])
        missing = [{"day": r["day"], "value": None} for r in rows if r["excess"] is None]
        as_zero = q1_verdict(days, labelled + [{**m, "value": 0.0} for m in missing])["verdict"]
        as_worst = q1_verdict(days, labelled + [{**m, "value": floor} for m in missing])["verdict"]
        survives = as_zero == as_worst == base["verdict"]
        result["no_outcome_rule"] = {"as_zero": as_zero, "as_worst_decile": as_worst, "worst_decile": floor,
                                     "verdict_survives": survives}
        if not survives:
            result["verdict"] = "NO_DECISION"
    return result


def q2(days: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> dict:
    """D = mean(score >= 60) - mean(score < 60) on labelled decisions with a score."""
    scored = [r for r in rows if r["excess"] is not None and r["score"] is not None]
    high = [{"day": r["day"], "value": r["excess"]} for r in scored if r["score"] >= SCORE_SPLIT]
    low = [{"day": r["day"], "value": r["excess"]} for r in scored if r["score"] < SCORE_SPLIT]
    if not high or not low:
        return {"verdict": "NOT_SHOWN", "reason": "a score group is empty", "n_high": len(high), "n_low": len(low)}
    shown = intervals(days, [high, low], VERDICT_BLOCKS, _difference)
    lo, hi = _low_high(shown)
    verdict = "RANKS" if lo is not None and lo > 0 else "REVERSED" if hi is not None and hi < 0 else "NOT_SHOWN"
    return {"verdict": verdict, "d": statistics.fmean(r["value"] for r in high) - statistics.fmean(r["value"] for r in low),
            "low": lo, "high": hi, "n_high": len(high), "n_low": len(low), "intervals": shown}


# ---------- description ----------

def _terciles(rows: Sequence[Mapping[str, Any]]) -> dict | None:
    """Labelled decisions by traded value: equal low / high thirds (n // 3 each), the rest mid."""
    labelled = [r for r in rows if r["excess"] is not None]
    if not labelled or any(r["traded_value"] is None for r in labelled):
        return None
    ordered = sorted(labelled, key=lambda r: (r["traded_value"], r["id"]))
    k = len(ordered) // 3
    parts = {"low": ordered[:k], "mid": ordered[k:len(ordered) - k], "high": ordered[len(ordered) - k:]}
    return {name: _stats([r["excess"] for r in part]) for name, part in parts.items()}


def describe(days: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> dict:
    """Everything PREREG3 reports (no gates)."""
    labelled = [r for r in rows if r["excess"] is not None]
    values = [r["excess"] for r in labelled]
    by_day: dict[str, list[float]] = {}
    for r in labelled:
        by_day.setdefault(r["day"], []).append(r["excess"])

    def split(key: Callable[[Mapping[str, Any]], str | None]) -> dict:
        """Stats of the labelled decisions grouped by key(row); rows keyed None are left out."""
        groups: dict[str, list[float]] = {}
        for r in labelled:
            name = key(r)
            if name is not None:
                groups.setdefault(name, []).append(r["excess"])
        return {name: _stats(v) for name, v in sorted(groups.items())}

    exits: dict[str, int] = {}
    for r in labelled:
        exits[r["outcome"] or "unknown"] = exits.get(r["outcome"] or "unknown", 0) + 1
    worst = worst_decile(values)
    return {
        "eligible": len(rows), "labelled": len(labelled), "decision_days": len(days),
        "first_day": days[0] if days else None, "last_day": days[-1] if days else None,
        "no_outcome": no_outcome_reasons(rows),
        "excess_pct": _stats(values),
        "day_equal_mean": round(statistics.fmean(statistics.fmean(v) for v in by_day.values()), 3) if by_day else None,
        "worst_decile": None if worst is None else round(worst, 3),
        "exits": dict(sorted(exits.items())),
        "atr15_excess_pct": _stats([r["atr15"] for r in rows if r["atr15"] is not None]),
        "by_action": split(lambda r: r["action"] or "unknown"),
        "score_70_plus": _stats([r["excess"] for r in labelled if r["score"] is not None and r["score"] >= HIGH_SCORE]),
        "by_scan_time": split(lambda r: "morning" if r["time"] < MORNING_BEFORE else "afternoon"),
        "by_month": split(lambda r: r["day"][:7]),
        "liquidity_thirds": _terciles(rows),
    }


# ---------- the looks ----------

def looks_reached(day_count: int) -> list[tuple[str, int]]:
    """Every look the eligible decision days reach, in order (empty before L1)."""
    return [(name, n) for name, n in LOOKS if n <= day_count]


def _rounded(obj: Any) -> Any:
    """Floats rounded to 4 places for the printed report (verdicts use the unrounded values)."""
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rounded(v) for v in obj]
    return obj


def read_look(name: str, n: int, all_days: Sequence[str], eligible: Sequence[Mapping[str, Any]],
              waiting: Sequence[str]) -> dict:
    """One look on its first n eligible days. LOOK_NOT_READY while an earlier first-scan day (in `waiting`)
    can still become eligible and shift the days, or while more than 5% of the decisions lack an incumbent
    label and not all are settled. Unlabelled decisions at the ready run are no-outcome."""
    days = all_days[:n]
    chosen = set(days)
    mine = [r for r in eligible if r["day"] in chosen]
    entry: dict[str, Any] = {"look": name, "look_days": n, "first_day": days[0], "last_day": days[-1]}
    unsettled = sum(not r["settled"] for r in mine)
    unlabelled = sum(r["excess"] is None for r in mine)
    earlier = sum(day <= days[-1] for day in waiting)
    few_missing = unlabelled * 100 <= MAX_NO_OUTCOME_PCT * len(mine)
    entry.update(unlabelled=unlabelled, unsettled=unsettled, earlier_days_not_eligible=earlier)
    if earlier or not (unsettled == 0 or few_missing):
        entry.update(status="LOOK_NOT_READY",
                     line=f"{name}: wait ({unlabelled} unlabelled, {unsettled} open, {earlier} earlier days not eligible)")
        return entry
    entry["describe"] = describe(days, mine)
    if name not in VERDICT_LOOKS:
        entry.update(status="DESCRIBE_ONLY",
                     intervals=intervals(days, [_valued(mine)], DESCRIBE_BLOCKS, _pooled_mean),
                     line=f"{name}: describe only")
        return entry
    first, second = q1(days, mine), q2(days, mine)
    entry.update(status="VERDICT", q1=first, q2=second,
                 line=f"{name} ({days[0]}..{days[-1]}): Q1 {first['verdict']}, Q2 {second['verdict']}")
    return entry


def report(rows: Sequence[Mapping[str, Any]], *, input_sha256: str | None = None) -> dict:
    """Every reached look's entry (or the BEFORE_L1 description) from validated rows (see parse_rows)."""
    eligible = [r for r in rows if r["eligible"]]
    all_days = sorted({r["day"] for r in eligible})
    waiting = sorted({r["day"] for r in rows if not r["eligible"]})
    out: dict[str, Any] = {"version": VERSION, "queried_at": rows[0]["queried_at"] if rows else None,
                           "input_sha256": input_sha256, "eligible_decision_days": len(all_days), "looks": []}
    reached = looks_reached(len(all_days))
    if not reached:
        out.update(status="BEFORE_L1", describe=describe(all_days, eligible),
                   line=f"{len(all_days)} eligible decision days (< 20): describe only")
        return _rounded(out)
    out["looks"] = [read_look(name, n, all_days, eligible, waiting) for name, n in reached]
    out.update(status="LOOKS", line="; ".join(entry["line"] for entry in out["looks"]))
    return _rounded(out)


def _decode(raw: bytes) -> str:
    """UTF-16 when it starts with a UTF-16 byte-order mark (PowerShell 5 redirects), else UTF-8 (BOM allowed)."""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: read the rows JSON, print the report; exit 2 when the rows are refused or --out cannot be written."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("rows", help="JSON array from sql/stage2_forward_test_rows.sql")
    parser.add_argument("--out", help="also write the report here")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        with open(args.rows, "rb") as handle:
            raw = handle.read()
        rows = parse_rows(json.loads(_decode(raw)))
    except (OSError, UnicodeError, ValueError) as exc:     # ValueError covers JSONDecodeError and RowError
        LOGGER.error("rows refused: %s", exc)
        return 2
    result = report(rows, input_sha256=hashlib.sha256(raw).hexdigest())
    text = json.dumps(result, indent=1, sort_keys=True)
    print(text)
    LOGGER.info("%s", result["line"])
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text + "\n")
        except OSError as exc:
            LOGGER.error("report printed but not written to %s: %s", args.out, exc)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
