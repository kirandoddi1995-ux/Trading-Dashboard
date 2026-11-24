"""Tests for stage2_forward_test (PREREG3 v1.3: claude/PREREG_2026-11-24_live_pipeline_forward.md).

The SQL itself runs on the PGlite harness in tests/test_equity_stage2_maturation.py
(test_forward_rows_query_*); here: row validation, looks, the bootstrap, Q1 / Q2 verdicts, the
no-outcome rule, the description and the CLI, on synthetic rows.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest

import equity_stage2_maturation as m
import stage2_forward_test as f

ROOT = Path(__file__).resolve().parents[1]


def _days(n: int, start: dt.date = dt.date(2026, 11, 11)) -> list[str]:
    """n weekdays from `start` (ISO dates)."""
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += dt.timedelta(days=1)
    return out


STAMP = "2028-06-01T10:30:00"                 # after every synthetic day + 22


def _row(i, day, excess=0.01, *, score=65.0, time="10:07", action="Watch", settled=True, atr15=None,
         disposition=None, outcome="horizon", tv=1000.0, eligible=True, total=None):
    """One row exactly as sql/stage2_forward_test_rows.sql returns it (excess as a fraction)."""
    return {"observation_id": f"o{i}", "day": day, "eligible": eligible, "scan_time": time, "score": score,
            "action": action, "incumbent_outcome": outcome if excess is not None else None,
            "incumbent_excess": excess, "atr15_excess": atr15, "disposition": disposition, "settled": settled,
            "traded_value": tv, "queried_at": STAMP, "total_rows": total}


def _run(n_days, value, per_day=4, **kw):
    """per_day rows on each of n_days days; value(day_index, k) gives the excess fraction."""
    rows, i = [], 0
    for d, day in enumerate(_days(n_days)):
        for k in range(per_day):
            rows.append(_row(i, day, value(d, k), **kw))
            i += 1
    return rows


def _complete(raw):
    """Fill total_rows (left None) with the export's length, as the query's count(*) OVER () does."""
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("total_rows") is None:
                item["total_rows"] = len(raw)
    return raw


def _parse(raw):
    """parse_rows on a complete export."""
    return f.parse_rows(_complete(raw))


def _report(raw):
    """Validated rows straight into the report."""
    return f.report(_parse(raw))


def _look(raw):
    """The last look reached."""
    return _report(raw)["looks"][-1]


# ---------- rows ----------

def test_rows_become_percent_and_are_sorted_by_day_then_id():
    """Fractions become %, numeric strings parse, nulls stay None; order is day then id."""
    rows = _parse([_row(2, "2026-11-12", 0.0123), _row(1, "2026-11-12", None, settled=False),
                         _row(3, "2026-11-11", "-0.02", tv=None)])
    assert [r["id"] for r in rows] == ["o3", "o1", "o2"]
    assert rows[2]["excess"] == pytest.approx(1.23) and rows[0]["excess"] == pytest.approx(-2.0)
    assert rows[1]["excess"] is None and rows[0]["traded_value"] is None


@pytest.mark.parametrize("broken", [
    lambda r: {"not": "a list"},
    lambda r: [r, "row"],
    lambda r: [{k: v for k, v in r.items() if k != "settled"}],
    lambda r: [r, dict(r)],                                        # duplicate decision
    lambda r: [{**r, "observation_id": ""}],
    lambda r: [{**r, "day": "2026-13-01"}],
    lambda r: [{**r, "day": "26-11-12"}],
    lambda r: [{**r, "scan_time": "24:00"}],
    lambda r: [{**r, "scan_time": None}],
    lambda r: [{**r, "settled": "true"}],
    lambda r: [{**r, "eligible": "yes"}],
    lambda r: [{**r, "queried_at": "2028-06-01 10:30"}],
    lambda r: [r, {**_row(2, "2026-11-12"), "queried_at": "2028-06-02T10:30:00"}],   # two query runs
    lambda r: [{**r, "incumbent_excess": "inf"}],
    lambda r: [{**r, "incumbent_excess": "nan"}],
    lambda r: [{**r, "incumbent_excess": True}],
    lambda r: [{**r, "atr15_excess": "x"}],
    lambda r: [{**r, "traded_value": -1}],
    lambda r: [{**r, "score": [70]}],
    lambda r: [{**r, "action": 3}],
])
def test_rows_the_query_cannot_return_are_refused(broken):
    """Every malformed shape raises RowError instead of reaching a verdict."""
    with pytest.raises(f.RowError):
        f.parse_rows(_complete(broken(_row(1, "2026-11-12"))))


# ---------- looks ----------

@pytest.mark.parametrize("days, last", [(0, None), (19, None), (20, "L1"), (39, "L1"), (40, "L2"), (59, "L2"),
                                        (60, "L3"), (124, "L3"), (125, "L4"), (249, "L4"), (250, "L5"), (400, "L5")])
def test_every_look_reached_is_listed(days, last):
    """Boundaries of L1..L5 in eligible decision days; all earlier looks stay listed."""
    reached = [name for name, _ in f.looks_reached(days)]
    assert (reached[-1] if reached else None) == last and reached == [n for n, _ in f.LOOKS][:len(reached)]


def test_before_l1_only_describes():
    """Under 20 decision days: BEFORE_L1, a description and no verdict."""
    out = _report(_run(19, lambda d, k: 0.01))
    assert out["status"] == "BEFORE_L1" and out["looks"] == [] and out["queried_at"] == STAMP
    assert out["describe"]["eligible"] == 76


def test_a_look_uses_its_first_days_only_and_later_open_decisions_do_not_block_it():
    """v1.1 rule 1: exactly the first N days; an open decision after them does not matter."""
    raw = _run(25, lambda d, k: 0.01)
    raw.append(_row(999, _days(25)[22], None, settled=False))       # day 23: after L1's 20 days
    out = _look(raw)
    assert (out["status"], out["look"], out["last_day"]) == ("DESCRIBE_ONLY", "L1", _days(20)[-1])
    assert out["describe"]["eligible"] == 80 and out["describe"]["decision_days"] == 20


def test_a_look_is_ready_with_at_most_5pct_unlabelled_or_once_everything_is_settled():
    """v1.3 rule 1: 80 labelled + 5 open unlabelled (5.9%) waits; + 4 (4.8%) is ready (they are no-outcome);
    with everything settled it is ready whatever the share."""
    def with_open(k):
        """20 days of labelled passes plus k open, unlabelled ones on day 5 (fresh rows each call)."""
        return _run(20, lambda d, j: 0.01) + [_row(900 + i, _days(20)[4], None, settled=False) for i in range(k)]
    five = with_open(5)
    out = _look(five)
    assert out["status"] == "LOOK_NOT_READY" and (out["unlabelled"], out["unsettled"]) == (5, 5) and "describe" not in out
    four = with_open(4)
    ready = _look(four)
    assert ready["status"] == "DESCRIBE_ONLY" and ready["describe"]["labelled"] == 80 and ready["unlabelled"] == 4
    for row in five[-5:]:
        row["settled"] = True                                       # 61 days old: no label, settled
    assert _look(five)["status"] == "DESCRIBE_ONLY"


def test_l1_and_l2_report_short_block_intervals_and_no_verdict():
    """L1 / L2: intervals with blocks 3 / 5 / 10 at 95% and 90%, never Q1 or Q2."""
    looks = _report(_run(40, lambda d, k: 0.01 + 0.002 * (k - 1.5)))["looks"]
    assert [(e["look"], e["status"]) for e in looks] == [("L1", "DESCRIBE_ONLY"), ("L2", "DESCRIBE_ONLY")]
    out = looks[-1]
    assert set(out["intervals"]) == {"3", "5", "10"} and set(out["intervals"]["5"]) == {"95", "90"}
    assert "q1" not in out and "q2" not in out


# ---------- Q1 ----------

def test_clear_loss_when_the_highest_upper_bound_is_below_zero():
    """L3 with every draw negative: CLEAR_LOSS from blocks 5 / 10 / 15."""
    out = _look(_run(60, lambda d, k: -0.02 + 0.004 * (k - 1.5)))
    q1 = out["q1"]
    assert out["status"] == "VERDICT" and out["look"] == "L3" and q1["verdict"] == "CLEAR_LOSS"
    assert q1["high"] < 0 and set(q1["intervals"]) == {"5", "10", "15"}
    assert q1["no_outcome_rule"] == "not needed"


def test_edge_signal_needs_low_above_zero_plus_40bp_and_positive_months():
    """EDGE_SIGNAL needs all three checks; +0.30% or a losing complete month is not enough."""
    out = _look(_run(60, lambda d, k: 0.02 + 0.004 * (k - 1.5)))
    assert out["q1"]["verdict"] == "EDGE_SIGNAL" and out["q1"]["low"] > 0
    assert out["q1"]["complete_months"] == ["2026-12", "2027-01"]
    small = _look(_run(60, lambda d, k: 0.003))                  # +0.30%: interval above 0, fails +40 bp
    assert small["q1"]["low"] > 0 and not small["q1"]["checks"]["mean_after_40bp_above_0"]
    assert small["q1"]["verdict"] == "INCONCLUSIVE"
    days = _days(60)
    bad_january = _look(_run(60, lambda d, k: -0.01 if days[d].startswith("2027-01") else 0.03))
    assert bad_january["q1"]["positive_month_share"] == 0.5
    assert not bad_january["q1"]["checks"]["positive_months_at_least_60pct"]
    assert bad_january["q1"]["verdict"] != "EDGE_SIGNAL"


def test_noise_is_inconclusive():
    """Alternating winning and losing days: the interval spans 0."""
    out = _look(_run(60, lambda d, k: 0.03 if d % 2 else -0.03))
    assert out["q1"]["verdict"] == "INCONCLUSIVE"
    assert out["q1"]["low"] < 0 < out["q1"]["high"]


def test_no_complete_month_means_no_edge_signal():
    """v1.2 rule 3: no complete month -> the months check fails."""
    q1 = f.q1_verdict(["2026-11-11", "2026-12-01"], [{"day": "2026-11-11", "value": 5.0},
                                                      {"day": "2026-12-01", "value": 5.0}])
    assert q1["complete_months"] == [] and q1["verdict"] == "INCONCLUSIVE"


def test_more_than_5pct_without_outcome_must_survive_both_imputations():
    """Over 5% no-outcome the verdict must hold with them at 0% and at the worst decile; exactly 5% skips the rule."""
    # EDGE on labelled (+0.75%); 20% missing: as 0% still EDGE, as the worst decile (-6%) a loss -> NO_DECISION
    raw = _run(60, lambda d, k: None if k == 0 else (-0.06 if k == 4 else 0.03), per_day=5)
    out = _look(raw)
    rule = out["q1"]["no_outcome_rule"]
    assert out["q1"]["no_outcome_share"] == pytest.approx(0.2) and rule["worst_decile"] == pytest.approx(-6.0)
    assert (rule["as_zero"], rule["as_worst_decile"]) == ("EDGE_SIGNAL", "CLEAR_LOSS")
    assert not rule["verdict_survives"] and out["q1"]["verdict"] == "NO_DECISION"
    assert out["q1"]["mean"] == pytest.approx(0.75)                 # the labelled numbers are still shown
    # a clear loss stays a clear loss as 0% and as the worst decile -> it stands
    loss = _look(_run(60, lambda d, k: None if k == 0 and d % 2 == 0 else -0.03 + 0.004 * (k - 1.5),
                        per_day=5))
    assert loss["q1"]["no_outcome_rule"]["verdict_survives"] and loss["q1"]["verdict"] == "CLEAR_LOSS"
    # exactly 5% missing: the rule is not used
    few = _look(_run(60, lambda d, k: None if k == 0 and d % 4 == 0 else 0.02, per_day=5))
    assert few["q1"]["no_outcome_share"] == pytest.approx(0.05) and few["q1"]["no_outcome_rule"] == "not needed"


def test_no_labelled_decision_is_no_decision():
    """Nothing labelled: Q1 NO_DECISION, Q2 NOT_SHOWN."""
    out = _look(_run(60, lambda d, k: None))
    assert out["q1"]["verdict"] == "NO_DECISION" and out["q2"]["verdict"] == "NOT_SHOWN"


# ---------- Q2 ----------

def _scored(n_days, high, low):
    """Per day two passes scoring >= 60 at `high` and two below 60 at `low`."""
    rows, i = [], 0
    for day in _days(n_days):
        for score, value in ((72.0, high), (64.0, high), (55.0, low), (40.0, low)):
            rows.append(_row(i, day, value, score=score))
            i += 1
    return rows


def test_q2_ranks_reversed_and_not_shown():
    """Q2 verdicts, including one empty score group."""
    assert _look(_scored(60, 0.02, -0.02))["q2"]["verdict"] == "RANKS"
    assert _look(_scored(60, -0.02, 0.02))["q2"]["verdict"] == "REVERSED"
    raw = _run(60, lambda d, k: 0.03 if (d + k) % 2 else -0.03)
    for row in raw:
        row["score"] = 70.0 if int(row["observation_id"][1:]) % 4 < 2 else 50.0
    assert _look(raw)["q2"]["verdict"] == "NOT_SHOWN"
    one_group = _look(_run(60, lambda d, k: 0.01, score=65.0))["q2"]
    assert one_group["verdict"] == "NOT_SHOWN" and one_group["n_low"] == 0


def test_q2_splits_at_exactly_60_and_skips_missing_scores():
    """Score 60 is high; a missing score is in neither group."""
    raw = _scored(60, 0.02, -0.02)
    for row in raw:
        if row["score"] == 64.0:
            row["score"] = 60.0                                   # 60 belongs to the high group
        if row["score"] == 40.0:
            row["score"] = None                                   # no score: in neither group
    q2 = _look(raw)["q2"]
    assert (q2["n_high"], q2["n_low"]) == (120, 60) and q2["verdict"] == "RANKS"


# ---------- bootstrap ----------

def test_block_draws_are_seeded_circular_and_skip_empty_draws():
    """Same seed same draws; constant data gives constant draws; empty-group draws are skipped."""
    cells = [[(float(d), 1)] for d in range(10)]
    first = f.block_draws(cells, 3, f._pooled_mean, draws=500)
    assert first == f.block_draws(cells, 3, f._pooled_mean, draws=500) and first == sorted(first)
    assert len(first) == 500 and min(first) >= 0 and max(first) <= 9
    flat = f.block_draws([[(2.0, 1)]] * 7, 5, f._pooled_mean, draws=50)
    assert set(flat) == {2.0}
    sparse = [[(0.0, 0), (1.0, 1)] for _ in range(9)] + [[(5.0, 1), (1.0, 1)]]
    kept = f.block_draws(sparse, 1, f._difference, draws=400)     # most draws miss the one high day
    assert 0 < len(kept) < 400 and set(kept) == {4.0}
    assert f.block_draws([], 3, f._pooled_mean) == [] and f.block_draws(cells, 0, f._pooled_mean) == []


def test_bounds_use_the_replay_index_convention():
    """int(q x (draws - 1)) for 95% and 90%."""
    values = list(range(1000))
    assert f.bounds(values, "95") == {"low": 24, "high": 974, "draws": 1000}
    assert f.bounds(values, "90") == {"low": 49, "high": 949, "draws": 1000}
    assert f.bounds([], "95") is None


def test_low_high_take_the_widest_decision_level_bounds():
    """LOW / HIGH come from the 95% bounds across blocks; a missing one gives None."""
    shown = {"5": {"95": {"low": -1.0, "high": 2.0}, "90": {"low": -0.5, "high": 1.0}},
             "10": {"95": {"low": -2.0, "high": 1.5}, "90": {"low": -9.0, "high": 9.0}}}
    assert f._low_high(shown) == (-2.0, 2.0)
    assert f._low_high({"5": {"95": None, "90": None}}) == (None, None)


def test_complete_months_exclude_the_first_and_last_months():
    """Only months strictly between the first and last months count."""
    assert f.complete_months(["2026-11-11", "2026-12-01", "2027-01-05", "2027-02-01"]) == ["2026-12", "2027-01"]
    assert f.complete_months(["2026-11-11", "2026-11-30"]) == []
    assert f.complete_months(["2026-11-11", "2027-01-04"]) == []            # no decision day in December
    assert f.complete_months(["2026-11-11", "2027-02-01", "2027-04-01"]) == ["2027-02"]


def test_worst_decile_is_the_mean_of_the_lowest_ceil_tenth():
    """ceil(n / 10) lowest values, at least one."""
    assert f.worst_decile(list(range(1, 11))) == 1
    assert f.worst_decile(list(range(1, 12))) == 1.5
    assert f.worst_decile([]) is None


# ---------- description ----------

def test_describe_reports_every_prereg3_split():
    """No-outcome reasons, scan time (12:00 split), action, >= 70, exits, atr15, liquidity thirds."""
    day = "2026-11-12"
    raw = [_row(1, day, 0.02, time="11:59", score=72.0, action="Buy", atr15=-0.01, outcome="target", tv=10.0),
           _row(2, day, -0.01, time="12:00", score=50.0, atr15=0.01, outcome="stop", tv=20.0),
           _row(3, day, 0.00, time="14:37", score=None, action=None, tv=30.0),
           _row(4, day, None, disposition="no_fill"), _row(5, day, None, disposition="window_problem"),
           _row(6, day, None, disposition="open"), _row(7, day, None)]
    out = f.describe([day], _parse(raw))
    assert (out["eligible"], out["labelled"]) == (7, 3)
    assert out["no_outcome"] == {"execution": {"no_fill": 1},
                                 "data": {"window_problem": 1, "open": 1, "none": 1}}
    assert out["by_scan_time"]["morning"]["n"] == 1 and out["by_scan_time"]["afternoon"]["n"] == 2
    assert set(out["by_action"]) == {"Buy", "Watch", "unknown"}
    assert out["score_70_plus"]["n"] == 1 and out["exits"] == {"horizon": 1, "stop": 1, "target": 1}
    assert out["atr15_excess_pct"]["n"] == 2 and out["worst_decile"] == -1.0
    assert out["liquidity_thirds"] == {"low": f._stats([2.0]), "mid": f._stats([-1.0]), "high": f._stats([0.0])}


def test_day_equal_mean_weights_each_day_once():
    """Day-equal mean vs trade-equal mean."""
    raw = [_row(1, "2026-11-11", 0.03), _row(2, "2026-11-12", -0.01), _row(3, "2026-11-12", -0.01),
           _row(4, "2026-11-12", -0.01)]
    out = f.describe(["2026-11-11", "2026-11-12"], _parse(raw))
    assert out["day_equal_mean"] == 1.0 and out["excess_pct"]["mean"] == 0.0


def test_liquidity_thirds_need_every_traded_value():
    """Equal low / high thirds; one missing traded value -> not reported."""
    rows = _parse([_row(i, "2026-11-12", 0.01, tv=float(i)) for i in range(7)])
    thirds = f._terciles(rows)
    assert [thirds[k]["n"] for k in ("low", "mid", "high")] == [2, 3, 2]
    rows[3]["traded_value"] = None
    assert f._terciles(rows) is None


# ---------- CLI ----------

def test_cli_writes_the_report_and_refuses_bad_rows(tmp_path, capsys):
    """Exit 0 with --out written; exit 2 for bad rows, bad JSON or a missing file."""
    good, out = tmp_path / "rows.json", tmp_path / "report.json"
    good.write_text(json.dumps(_complete(_run(20, lambda d, k: 0.01))))
    assert f.main([str(good), "--out", str(out)]) == 0
    written = json.loads(out.read_text())
    assert written["looks"][0]["status"] == "DESCRIBE_ONLY"
    assert written["input_sha256"] == __import__("hashlib").sha256(good.read_bytes()).hexdigest()
    assert json.loads(capsys.readouterr().out)["looks"][0]["look"] == "L1"
    for encoding in ("utf-8-sig", "utf-16"):                       # a BOM, a PowerShell 5 redirect
        good.write_bytes(json.dumps(_complete(_run(20, lambda d, k: 0.01))).encode(encoding))
        assert f.main([str(good)]) == 0
    assert f.main([str(good), "--out", str(tmp_path / "no-dir" / "r.json")]) == 2
    good.write_bytes(b"\xff\xfe\x00")                              # broken UTF-16
    assert f.main([str(good)]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"observation_id": "x"}]))
    assert f.main([str(bad)]) == 2
    bad.write_text("not json")
    assert f.main([str(bad)]) == 2
    assert f.main([str(tmp_path / "missing.json")]) == 2


# ---------- the SQL file ----------

def _shared(text: str) -> str:
    """The CTEs both files share: from WITH policies to the CTE after decisions."""
    return text[text.index("WITH policies(policy) AS ("):text.index("\nactions AS (" if "\nactions AS (" in text
                                                                      else "\nper_decision AS (")]


def test_rows_sql_reads_the_outcomes_report_population_byte_for_byte():
    """Shared CTEs identical; label versions from maturation; read-only; columns = FIELDS in order."""
    report = (ROOT / "sql/stage2_shadow_outcomes_report.sql").read_text()
    rows = (ROOT / "sql/stage2_forward_test_rows.sql").read_text()
    assert _shared(rows) == _shared(report)
    assert f"'{m.shadow_target_version(m.INCUMBENT)}'" in rows and f"'{m.shadow_target_version(m.CHALLENGER)}'" in rows
    assert f"ds.label_version = '{m.SHADOW_LABEL_VERSION}'" in rows
    code = "\n".join(line.split("--")[0] for line in rows.splitlines())
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|CREATE|DROP|GRANT|REVOKE|TRUNCATE|COPY|MERGE|CALL|DO|SET|"
                         r"LOCK|INTO|NEXTVAL|SETVAL|VACUUM|COMMENT|NOTIFY)\b", code, re.I)
    selected = re.findall(r"\bAS (\w+),?\n", code.split("per_decision AS (", 1)[1])
    assert tuple(selected) == f.FIELDS


# ---------- boundaries and pinned pre-registered values ----------

def test_the_pre_registered_values_are_pinned():
    """PREREG3 v1.3 numbers: a change here is a v2 and must be written before the look it affects."""
    assert (f.LOOKS, f.VERDICT_LOOKS) == ((("L1", 20), ("L2", 40), ("L3", 60), ("L4", 125), ("L5", 250)),
                                          ("L3", "L4", "L5"))
    assert (f.DESCRIBE_BLOCKS, f.VERDICT_BLOCKS, f.DRAWS, f.SEED) == ((3, 5, 10), (5, 10, 15), 10_000, 20261125)
    assert (f.LEVELS, f.DECISION_LEVEL) == ({"95": (0.025, 0.975), "90": (0.05, 0.95)}, "95")
    assert (f.EXTRA_COST_PCT, f.MAX_NO_OUTCOME_PCT, f.MIN_POSITIVE_MONTHS) == (0.40, 5, 0.60)
    assert (f.SCORE_SPLIT, f.HIGH_SCORE, f.MORNING_BEFORE) == (60.0, 70.0, "12:00")


@pytest.mark.parametrize("low, high, mean, share, verdict", [
    (-1.0, -0.0001, -0.5, 1.0, "CLEAR_LOSS"),
    (-1.0, 0.0, -0.5, 1.0, "INCONCLUSIVE"),            # HIGH exactly 0 is not below 0
    (0.0001, 2.0, 0.41, 0.6, "EDGE_SIGNAL"),           # 60% of months is enough
    (0.0, 2.0, 1.0, 1.0, "INCONCLUSIVE"),              # LOW exactly 0 is not above 0
    (-0.1, 2.0, 1.0, 1.0, "INCONCLUSIVE"),
    (0.1, 2.0, 0.40, 1.0, "INCONCLUSIVE"),             # mean - 0.40 must be above 0
    (0.1, 2.0, 1.0, 0.59, "INCONCLUSIVE"),
    (0.1, 2.0, 1.0, None, "INCONCLUSIVE"),             # no complete month
    (None, None, 1.0, 1.0, "INCONCLUSIVE"),
])
def test_classify_boundaries(low, high, mean, share, verdict):
    """Each Q1 threshold at and around its boundary."""
    assert f.classify(low, high, mean, share)[0] == verdict


def test_block_draws_round_runs_up_and_wrap_around():
    """ceil(days / block) runs per draw; a run starting near the end wraps to the first days."""
    cells = [[(float(d), 1)] for d in range(10)]
    counts = f.block_draws(cells, 3, lambda s, c: c[0], draws=200)
    assert set(counts) == {12}                                    # 4 runs of 3 days, not 3 runs
    whole = f.block_draws(cells, 10, f._pooled_mean, draws=200)
    assert set(whole) == {4.5}                                    # one run = every day once, wherever it starts


def test_the_zero_imputation_alone_can_refuse_a_verdict():
    """Labelled loss on the first 15 days, the other 45 all without outcome: as the worst decile it is
    still a loss; as 0%, over 2.5% of the 15-day-block draws fall wholly in the empty days and are 0 ->
    HIGH = 0 -> not CLEAR_LOSS -> NO_DECISION."""
    raw = _run(60, lambda d, k: -0.003 if d < 15 else None)
    q1 = _look(raw)["q1"]
    rule = q1["no_outcome_rule"]
    assert (rule["as_worst_decile"], rule["as_zero"]) == ("CLEAR_LOSS", "INCONCLUSIVE")
    assert q1["verdict"] == "NO_DECISION"


def test_liquidity_thirds_keep_low_and_high_equal_for_eight():
    """n // 3 in each outer third: 8 decisions -> 2 / 4 / 2."""
    thirds = f._terciles(_parse([_row(i, "2026-11-12", 0.01, tv=float(i)) for i in range(8)]))
    assert [thirds[k]["n"] for k in ("low", "mid", "high")] == [2, 4, 2]


def test_exit_reasons_are_counted():
    """Two time exits and one stop."""
    raw = [_row(1, "2026-11-12", 0.01), _row(2, "2026-11-12", 0.02), _row(3, "2026-11-12", -0.01, outcome="stop")]
    assert f.describe(["2026-11-12"], _parse(raw))["exits"] == {"horizon": 2, "stop": 1}


def test_the_score_70_cohort_excludes_65():
    """The reported >= 70 sub-cohort is the live Buy gate, not the Q2 split."""
    raw = [_row(1, "2026-11-12", 0.01, score=72.0), _row(2, "2026-11-12", 0.01, score=65.0),
           _row(3, "2026-11-12", 0.01, score=70.0)]
    assert f.describe(["2026-11-12"], _parse(raw))["score_70_plus"]["n"] == 2


# ---------- review round 1 (24 Nov): gaps and v1.2 rules ----------

def test_an_open_decision_holds_a_verdict_look_but_earlier_looks_still_print():
    """v1.2 rule 2: every reached look is reported; L3 waits (over 5% open) while L1 / L2 describe."""
    raw = _run(60, lambda d, k: 0.01)
    raw += [_row(900 + i, _days(60)[50], None, settled=False) for i in range(13)]   # 13 of 253 = 5.1%
    looks = _report(raw)["looks"]
    assert [(e["look"], e["status"]) for e in looks] == [("L1", "DESCRIBE_ONLY"), ("L2", "DESCRIBE_ONLY"),
                                                          ("L3", "LOOK_NOT_READY")]
    assert looks[2]["unsettled"] == 13 and "q1" not in looks[2]


def test_an_earlier_day_that_is_not_eligible_yet_holds_the_look():
    """v1.3 rule 1: a first-scan day before the look's last day that is not eligible yet could still enter the
    first N days, so the look waits; one after the look's last day does not matter."""
    raw = _run(20, lambda d, k: 0.01)
    before = _row(900, "2026-11-14", None, settled=False, eligible=False)    # a Saturday: no eligible row
    after = _row(901, "2026-12-31", None, settled=False, eligible=False)
    out = _look(raw + [before])
    assert out["status"] == "LOOK_NOT_READY" and out["earlier_days_not_eligible"] == 1
    assert _look(raw + [after])["status"] == "DESCRIBE_ONLY"
    assert _report(raw + [after])["eligible_decision_days"] == 20  # not-eligible rows never count as days


def test_q1_draws_run_over_every_eligible_day_not_only_labelled_ones():
    """Days whose decisions all lack an outcome are still blocks of the bootstrap (some draws are empty)."""
    q1 = _look(_run(60, lambda d, k: -0.003 if d < 15 else None))["q1"]
    assert q1["intervals"]["15"]["95"]["draws"] < f.DRAWS


def test_q1_mean_weights_each_trade_not_each_day():
    """One +10% trade on day 1, three -0.5% trades on every other day: the trade mean decides."""
    raw, i = [], 0
    for d, day in enumerate(_days(60)):
        for _ in range(1 if d == 0 else 3):
            raw.append(_row(i, day, 0.10 if d == 0 else -0.005))
            i += 1
    q1 = _look(raw)["q1"]
    assert q1["mean"] == pytest.approx((10 - 0.5 * 177) / 178, abs=1e-4)


def test_q2_uses_blocks_5_10_15():
    """Q2's bootstrap is the verdict looks' one."""
    assert set(_look(_scored(60, 0.02, -0.02))["q2"]["intervals"]) == {"5", "10", "15"}


def test_the_no_outcome_floor_is_the_worst_decile_mean_not_the_minimum():
    """20 labelled (one -10%, nineteen -1%) and 3 without outcome: floor = mean of the lowest 2 = -5.5%."""
    days = _days(3)
    rows = _parse([_row(i, days[i % 3], -0.10 if i == 0 else -0.01) for i in range(20)]
                        + [_row(100 + i, days[i], None) for i in range(3)])
    assert f.q1(days, rows)["no_outcome_rule"]["worst_decile"] == pytest.approx(-5.5)


def test_liquidity_thirds_only_need_the_labelled_decisions_traded_value():
    """A no-outcome decision without a traded value does not hide the thirds."""
    rows = _parse([_row(i, "2026-11-12", 0.01, tv=float(i)) for i in range(6)]
                        + [_row(99, "2026-11-12", None, tv=None)])
    assert [f._terciles(rows)[k]["n"] for k in ("low", "mid", "high")] == [2, 2, 2]


def test_months_without_a_decision_day_are_left_out_but_unlabelled_months_count_against():
    """v1.3 rule 3: Dec and Feb have no decision day (no trades to judge) -> not complete months; March has a
    decision day but no labelled decision -> a complete month that is not positive."""
    days = ["2026-11-20", "2027-01-15", "2027-03-15", "2027-04-01"]
    q1 = f.q1_verdict(days, [{"day": d, "value": 5.0} for d in days])
    assert q1["complete_months"] == ["2027-01", "2027-03"] and q1["positive_month_share"] == 1.0
    q1 = f.q1_verdict(days, [{"day": d, "value": 5.0} for d in days if not d.startswith("2027-03")])
    assert q1["positive_month_share"] == 0.5 and not q1["checks"]["positive_months_at_least_60pct"]


def test_an_excess_below_minus_100_percent_is_a_valid_label():
    """No lower bound on excess (a -100% stock while NIFTY rose); only non-finite values are refused."""
    assert _parse([_row(1, "2026-11-12", -1.05)])[0]["excess"] == pytest.approx(-105.0)



# ---------- review round 2 (24 Nov) ----------

def test_a_cut_off_export_is_refused():
    """total_rows (count(*) OVER ()) must equal the rows received: a tool's output limit cuts the newest days."""
    raw = _complete(_run(20, lambda d, k: 0.01))
    with pytest.raises(f.RowError, match="cut off"):
        f.parse_rows(raw[:-4])
    for bad in (True, "80", 80.0):
        with pytest.raises(f.RowError, match="total_rows"):
            f.parse_rows([{**_row(1, "2026-11-12"), "total_rows": bad}])
    assert f.parse_rows([]) == []


def test_eligibility_is_per_day_and_rows_are_at_least_22_days_old():
    """Shapes the query cannot return: mixed eligibility on one day; a decision under 22 days before the query."""
    with pytest.raises(f.RowError, match="same day"):
        _parse([_row(1, "2026-11-12"), _row(2, "2026-11-12", None, settled=False, eligible=False)])
    young = {**_row(1, "2028-05-11"), "queried_at": STAMP}                   # 21 days before 1 Jun 2028
    with pytest.raises(f.RowError, match="21 days"):
        _parse([young])
    assert _parse([{**_row(1, "2028-05-10"), "queried_at": STAMP}])          # 22 days: returned by the query


def test_complete_months_without_a_labelled_decision_are_listed_as_none():
    """The month table shows every complete month; one without a labelled decision is None (not positive)."""
    days = ["2026-11-20", "2027-01-15", "2027-03-15", "2027-04-01"]
    q1 = f.q1_verdict(days, [{"day": "2027-01-15", "value": 5.0}])
    assert q1["month_means"] == {"2027-01": 5.0, "2027-03": None}


def test_exactly_5pct_unlabelled_is_ready():
    """4 open unlabelled of 80 decisions = 5%: ready (at most 5%), compared exactly."""
    raw = _run(20, lambda d, k: None if d < 4 and k == 0 else 0.01, settled=True)
    for row in raw:
        if row["incumbent_excess"] is None:
            row["settled"] = False
    out = _look(raw)
    assert (out["status"], out["unlabelled"], out["describe"]["eligible"]) == ("DESCRIBE_ONLY", 4, 80)
