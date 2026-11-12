"""Forward outcome labels for scheduled Stage-2 shadow passes (equity_stage2_maturation.py).

Synthetic bars only (minute bars first, daily bars built from them, so both sources agree);
no network and no hosted database. The pending query and the read-only report run on the
local PGlite harness when it is configured.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pytest

import equity_stage2_collector as s2
import equity_stage2_maturation as m
import scheduled_collector as collector
from equity_stage2_engine import derive_long_trade_levels
from prediction_validation import TARGET_VERSION

ROOT = Path(__file__).resolve().parents[1]
IST = m.IST
D0 = dt.date(2026, 11, 2)                      # decision day (Monday)
TODAY = D0 + dt.timedelta(days=30)
EVALUATED = dt.datetime(2026, 11, 2, 10, 9, tzinfo=IST)
ENABLED = {m.ENABLE_ENV: "1"}
INC, CH = m.shadow_target_version(m.INCUMBENT), m.shadow_target_version(m.CHALLENGER)


# ---------- synthetic evidence ----------

def _days(start: dt.date, count: int) -> list[dt.date]:
    """`count` weekdays from `start` (inclusive)."""
    out, day = [], start
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def _bars(prices_by_day: dict[dt.date, list[tuple[float, float]]]):
    """Minute bars from (open, close) pairs, high/low = their max/min, and the daily bars they imply."""
    rows = []
    for day, prices in prices_by_day.items():
        start = pd.Timestamp(day) + pd.Timedelta(hours=9, minutes=15)
        for i, (opening, price) in enumerate(prices):
            rows.append((start + pd.Timedelta(minutes=i), opening, price))
    index = pd.DatetimeIndex([t for t, _, _ in rows])
    opens, closes = [o for _, o, _ in rows], [p for _, _, p in rows]
    minutes = pd.DataFrame({"Open": opens, "High": np.maximum(opens, closes), "Low": np.minimum(opens, closes),
                            "Close": closes, "Volume": 1000.0}, index=index)
    grouped = minutes.groupby(minutes.index.normalize())
    daily = pd.DataFrame({"Open": grouped["Open"].first(), "High": grouped["High"].max(),
                          "Low": grouped["Low"].min(), "Close": grouped["Close"].last(),
                          "Volume": grouped["Volume"].sum()})
    return daily, minutes


def _path(sessions: int = 20, *, jump_day: int | None = None, jump_to: float = 105.0,
          drop_day: int | None = None, drop_to: float = 96.0, gap_day: int | None = None,
          gap_to: float = 90.0, base: float = 100.0):
    """Flat path from a week before D0; on session N (D0 = 0) a one-minute spike/dip, or a gap open."""
    prices, session = {}, -1
    for day in _days(D0 - dt.timedelta(days=7), sessions + 5):
        minute_prices = [(base, base)] * 375
        if day >= D0:
            session += 1
            if session == jump_day:
                minute_prices[200] = (base, jump_to)
            if session == drop_day:
                minute_prices[200] = (base, drop_to)
            if session == gap_day:
                minute_prices = [(gap_to, gap_to)] * 375
        prices[day] = minute_prices
    return _bars(prices)


def _custom_path(mods: dict[int, dict[int, tuple[float, float]]], base: float = 100.0):
    """Flat path with given (open, close) minute bars: {session: {minute index: (open, close)}}."""
    prices, session = {}, -1
    for day in _days(D0 - dt.timedelta(days=7), 25):
        minute_prices = [(base, base)] * 375
        if day >= D0:
            session += 1
            for minute, bar in mods.get(session, {}).items():
                minute_prices[minute] = bar
        prices[day] = minute_prices
    return _bars(prices)


def _candidate(**over):
    """A shadow pass as the Stage-2 ledger batch records it (only the fields maturation reads)."""
    inputs = {"atr_val": 2.0, "levels": {"support20": 79.0, "resistance20": 103.0, "resistance60": 103.0}}
    used = {"stage2_pass": True, "evaluated_at": EVALUATED.astimezone(dt.timezone.utc).isoformat(),
            "signal_action": "Watch", "equity_capture": {"inputs": inputs}}
    candidate = {"instrument_key": "NSE_EQ|SYN", "decision_id": "obs-1", "costs": {"round_trip_bps": 20.0},
                 "inputs_used": used}
    candidate.update(over)
    return candidate


def _row(obs="obs-1", key="NSE_EQ|SYN", day=D0, stored=(), candidate=None):
    """A raw pending row exactly as PENDING_SQL returns it."""
    return (obs, day, key, key.split("|")[1], 100.0, 80.0, 128.0,
            json.dumps(candidate or _candidate(instrument_key=key, decision_id=obs)), list(stored))


def _decision(**kw):
    """Parse a pending row exactly as the run does."""
    return m.parse_pending_row(_row(**kw))


# ---------- levels ----------

def _incumbent_stop(df, price, atr):
    """derive_long_trade_levels' unrounded stop and levels, recomputed from the frame."""
    prior = df.tail(60).iloc[:-1]
    s20, r20, r60 = prior["Low"].tail(20).min(), prior["High"].tail(20).max(), prior["High"].max()
    atr_stop = price - 1.5 * atr
    stop = min(atr_stop, s20 - 0.15 * atr if s20 < price else atr_stop)
    return (stop if 0 < stop < price else price - 1.5 * atr), r20, r60


def test_levels_for_stop_reproduces_the_incumbent_target_exactly():
    """Differential: with the incumbent stop, the target half equals derive_long_trade_levels."""
    rng = np.random.default_rng(7)
    checked = 0
    for _ in range(400):
        close = 100 * np.exp(np.cumsum(rng.normal(0.002, 0.02, 80)))
        high = close * (1 + rng.uniform(0, 0.03, 80))
        low = close * (1 - rng.uniform(0, 0.03, 80))
        df = pd.DataFrame({"Open": close, "High": high, "Low": low, "Close": close})
        price, atr = float(close[-1] * rng.uniform(0.97, 1.05)), float(close[-1] * rng.uniform(0.005, 0.08))
        expected = derive_long_trade_levels(df, price, atr, 15)
        stop, r20, r60 = _incumbent_stop(df, price, atr)
        got = m.levels_for_stop(price, atr, stop, r20, r60, 15)
        if expected[0] is None:
            assert got is None
            continue
        assert got == (expected[0], expected[1])
        checked += 1
    assert checked > 350


def test_challenger_is_the_atr_stop_with_the_same_target_logic():
    """SADBHIN, 11 Nov: entry 3.09, ATR 0.1707 -> stop 2.83; no suitable resistance -> ATR target."""
    assert m.challenger_levels(3.09, 0.17074242509889112, 3.4, 3.4) == (2.83, 3.5)
    # Suitable resistance caps the target at the floor (1.4 x risk) at horizon 15.
    assert m.challenger_levels(100.0, 2.0, 110.0, 110.0) == (97.0, 104.2)
    assert m.challenger_levels(100.0, 70.0, 0, 0) is None        # stop would be negative
    assert m.levels_for_stop(100.0, 2.0, 100.0, 0, 0) is None    # stop not below entry
    assert m.levels_for_stop(100.0, 0.0, 90.0, 0, 0) is None     # no volatility


def test_shadow_versions_never_collide_with_the_production_label():
    """Calibration, readiness counts and training read TARGET_VERSION only."""
    assert {INC, CH} == {"stage2-shadow:net-excess-execution-v2.minute-aligned-v1:incumbent-levels-v1",
                         "stage2-shadow:net-excess-execution-v2.minute-aligned-v1:atr15-stop-v1"}
    assert TARGET_VERSION not in {INC, CH}
    source = (ROOT / "production_repository.py").read_text()
    assert "target_version='net-excess-execution-v2'" in source  # the readiness count is exact
    assert "place_order" not in (ROOT / "equity_stage2_maturation.py").read_text()
    report = (ROOT / "sql/stage2_shadow_outcomes_report.sql").read_text()
    assert f"'stage2-shadow:{m.SHADOW_LABEL_VERSION}:' || p.policy" in report


# ---------- parsing and labels ----------

def test_pending_row_parsing_takes_the_recorded_inputs():
    """ATR, levels, costs and decision time come from the ledger batch; a 0 cost stays 0."""
    decision = _decision(stored=["x"])
    assert decision["as_of_date"] == D0 and decision["atr"] == 2.0
    assert (decision["resistance20"], decision["resistance60"], decision["cost_bps"]) == (103.0, 103.0, 20.0)
    assert decision["evaluated_at"] == pd.Timestamp(EVALUATED)
    assert decision["stored_versions"] == {"x"}
    assert _decision(candidate=_candidate(costs={}))["cost_bps"] == m.DEFAULT_COST_BPS
    assert _decision(candidate=_candidate(costs={"round_trip_bps": 0}))["cost_bps"] == 0.0
    broken = _candidate()
    del broken["inputs_used"]["equity_capture"]
    with pytest.raises(KeyError):
        _decision(candidate=broken)


def test_signal_time_is_ist_and_only_inside_the_session():
    """In session: the decision minute (IST, naive). Outside 09:15-15:30: None (next-open entry)."""
    assert m._signal_timestamp(pd.Timestamp(EVALUATED)) == pd.Timestamp("2026-11-02 10:09")
    assert m._signal_timestamp(pd.Timestamp("2026-11-02T15:30:00+05:30")) == pd.Timestamp("2026-11-02 15:30")
    assert m._signal_timestamp(pd.Timestamp("2026-11-02T15:40:00+05:30")) is None
    assert m._signal_timestamp(pd.Timestamp("2026-11-02 09:00")) is None


def test_horizon_end_needs_fifteen_completed_sessions_and_ignores_today():
    """14 sessions after D0: not yet. 15: the 15th date. A bar stamped today never counts."""
    daily, _ = _path()
    after = daily.loc[daily.index > pd.Timestamp(D0)]
    decision = _decision()
    assert m.horizon_end(decision, daily.loc[:after.index[13]], TODAY) is None
    assert m.horizon_end(decision, daily.loc[:after.index[14]], TODAY) == after.index[14].date()
    assert m.horizon_end(decision, daily.loc[:after.index[14]], after.index[14].date()) is None
    assert m.horizon_end(decision, pd.DataFrame(), TODAY) is None      # empty Upstox answer
    assert m.horizon_end(decision, None, TODAY) is None


def test_completed_evidence_drops_bars_stamped_today_or_later():
    """_before keeps only bars strictly before the run day."""
    daily, minutes = _path()
    cut = daily.index[10].date()
    assert m._before(daily, cut).index.max() < pd.Timestamp(cut)
    assert m._before(minutes, cut).index.max() < pd.Timestamp(cut)
    assert m._before(None, cut).empty and isinstance(m._before(None, cut).index, pd.DatetimeIndex)


def test_challenger_hits_its_target_while_the_wide_incumbent_times_out():
    """Same decision, two policies: 105 spike on session 5 > challenger target 104.86 < 128."""
    daily, minutes = _path(jump_day=5)
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily, benchmark_minutes=minutes, today=TODAY)
    inc, ch = labels[m.INCUMBENT], labels[m.CHALLENGER]
    assert inc["outcome"] == "horizon" and (inc["stop"], inc["target"]) == (80.0, 128.0)
    assert ch["outcome"] == "target" and (ch["stop"], ch["target"]) == (97.0, 104.86)
    assert (inc["target_version"], ch["target_version"]) == (INC, CH)
    assert inc["entry_quality"] == "first_minute_after_signal" and inc["cost_bps"] == 20.0
    assert inc["net_return"] == pytest.approx(-0.002)            # flat path, 20 bps costs
    assert ch["net_return"] == pytest.approx(104.86 / 100 - 1 - 0.002)
    assert inc["excess_return"] is not None


def test_a_late_touch_inside_the_horizon_still_counts():
    """Spike on session 14 (the last one in the window) hits the challenger target."""
    daily, minutes = _path(jump_day=14)
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily, benchmark_minutes=minutes, today=TODAY)
    assert labels[m.CHALLENGER]["outcome"] == "target"


def test_a_dip_stops_the_challenger_only_and_fills_at_the_stop():
    """96 low inside a minute that opens at 100: stop 97 is reached in the bar -> fill at 97."""
    daily, minutes = _path(drop_day=3)
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily, benchmark_minutes=minutes, today=TODAY)
    ch = labels[m.CHALLENGER]
    assert ch["outcome"] == "stop" and labels[m.INCUMBENT]["outcome"] == "horizon"
    assert ch["exit"] == 97.0 and "stop_fill" not in ch


def test_a_gap_through_the_stop_fills_at_the_open():
    """Session 3 opens at 90, below stop 97: exit 90, not 97 (production label would say 97)."""
    daily, minutes = _path(gap_day=3)
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily, benchmark_minutes=minutes, today=TODAY)
    ch = labels[m.CHALLENGER]
    assert ch["outcome"] == "stop" and ch["exit"] == 90.0 and ch["stop_fill"] == "gap_open"
    assert ch["net_return"] == pytest.approx(0.90 - 1 - 0.002)
    assert ch["excess_return"] == pytest.approx(ch["net_return"] - ch["benchmark_return"])
    assert labels[m.INCUMBENT]["outcome"] == "horizon"           # stop 80 never reached


def test_missing_minute_evidence_on_a_touch_day_is_not_labelled():
    """Daily says touched, minute data absent that day: ambiguous -> None (retried later)."""
    daily, minutes = _path(jump_day=5)
    touch_day = daily.loc[daily["High"] >= 105].index[0]
    minutes = minutes.loc[minutes.index.normalize() != touch_day]
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily, benchmark_minutes=minutes, today=TODAY)
    assert labels[m.CHALLENGER] is None
    assert labels[m.INCUMBENT]["outcome"] == "horizon"            # no touch for the wide levels


def test_a_label_without_a_benchmark_return_is_not_stored():
    """No NIFTY evidence: excess unknown -> no label (retried later)."""
    daily, minutes = _path(jump_day=5)
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=None,
                            benchmark_minutes=None, today=TODAY)
    assert labels == {m.INCUMBENT: None, m.CHALLENGER: None}


def test_invalid_challenger_levels_give_no_label():
    """An ATR so large the challenger stop would be <= 0 is never labelled."""
    huge = _candidate()
    huge["inputs_used"]["equity_capture"]["inputs"]["atr_val"] = 80.0
    daily, minutes = _path()
    labels = m.label_decision(_decision(candidate=huge), daily=daily, minutes=minutes, benchmark=daily,
                              benchmark_minutes=minutes, today=TODAY)
    assert labels[m.CHALLENGER] is None and labels[m.INCUMBENT] is not None


# ---------- the run ----------

class Repo:
    """Records label writes and quality events."""

    def __init__(self):
        """Start empty."""
        self.saved, self.events = [], []

    def save_prediction_target(self, observation_id, target):
        """Append-only label write."""
        self.saved.append((observation_id, target["target_version"], target["outcome"], target))

    def record_quality_event(self, *args):
        """Quality index entry."""
        self.events.append(args)


class Fetch:
    """Upstox history fakes; `fail` maps an instrument to an exception; `log` is shared with sleep.

    NIFTY gets the same bars unless `bench_minutes` is set."""

    def __init__(self, fail=None):
        """Synthetic path with a session-5 spike."""
        self.daily, self.minutes = _path(jump_day=5)
        self.bench_minutes = None
        self.calls, self.fail, self.log = [], fail or {}, []

    def day(self, client, token, key, start, end):
        """Daily bars from start to end."""
        self.calls.append(("daily", key, start, end))
        self.log.append("daily")
        if key in self.fail:
            raise self.fail[key]
        return self.daily.loc[pd.Timestamp(start):pd.Timestamp(end)]

    def minute(self, client, token, key, start, end):
        """One-minute bars from start to end (inclusive days)."""
        self.calls.append(("minutes", key, start, end))
        self.log.append("minutes")
        source = self.bench_minutes if key == m.NIFTY_KEY and self.bench_minutes is not None else self.minutes
        return source.loc[pd.Timestamp(start):pd.Timestamp(end) + pd.Timedelta(days=1)]


def _select(monkeypatch, rows, *, missing=()):
    """Fake both selection queries over raw `rows` (ids in `missing` have no ledger entry)."""
    monkeypatch.setattr(m, "pending_shadow_passes", lambda repo_, today: [(r[0], r[1]) for r in rows])
    monkeypatch.setattr(m, "decision_rows", lambda repo_, ids: [r for r in rows if r[0] in ids and r[0] not in missing])


def _run(monkeypatch, rows, *, fetch=None, environ=ENABLED, check_lease=None, clock=None):
    """One maturation run over raw pending `rows` with fake fetchers; sleeps go to fetch.log."""
    repo, fetch = Repo(), fetch or Fetch()
    _select(monkeypatch, rows)
    summary = m.mature_shadow_passes(
        repo, None, "token", today=TODAY, fetch_daily=fetch.day, fetch_minutes=fetch.minute,
        check_lease=check_lease, environ=environ, sleep=lambda s: fetch.log.append(("sleep", s)),
        **({"clock": clock} if clock else {}))
    return summary, repo, fetch


def test_switch_off_does_nothing(monkeypatch):
    """Default: no query, no request, no write."""
    monkeypatch.setattr(m, "pending_shadow_passes", lambda *a, **k: pytest.fail("queried"))
    summary = m.mature_shadow_passes(Repo(), None, "t", today=TODAY, fetch_daily=None,
                                     fetch_minutes=None, environ={})
    assert summary == {"status": "DISABLED", "reason": f"{m.ENABLE_ENV} is not enabled"}


def test_run_stores_both_policy_labels_with_a_pause_before_every_request(monkeypatch):
    """One decision -> two labels with excess return; NIFTY daily once; minutes end at the horizon."""
    summary, repo, fetch = _run(monkeypatch, [_row()])
    assert summary["status"] == "SUCCESS" and summary["stored"] == 2 and summary["pending"] == 1
    assert sorted(s[:3] for s in repo.saved) == sorted([("obs-1", INC, "horizon"), ("obs-1", CH, "target")])
    assert all(s[3]["excess_return"] is not None for s in repo.saved)
    pause = ("sleep", s2.REQUEST_PAUSE_SECONDS)
    assert fetch.log == [pause, "daily", pause, "daily", pause, "minutes", pause, "minutes"]
    assert [c[1] for c in fetch.calls] == [m.NIFTY_KEY, "NSE_EQ|SYN", "NSE_EQ|SYN", m.NIFTY_KEY]
    after = fetch.daily.loc[fetch.daily.index > pd.Timestamp(D0)].index
    assert fetch.calls[1][2:] == (D0 - dt.timedelta(days=5), TODAY - dt.timedelta(days=1))
    assert fetch.calls[2][2:] == fetch.calls[3][2:] == (D0, after[14].date())   # NIFTY: same window
    assert repo.events == []


def test_two_scans_of_one_stock_day_share_one_history_fetch(monkeypatch):
    """10:07 and 14:37 passes of the same stock and day: one daily and one minute request each."""
    second = _candidate(decision_id="obs-2")
    second["inputs_used"]["evaluated_at"] = "2026-11-02T09:09:00+00:00"
    summary, repo, fetch = _run(monkeypatch, [_row(), _row(obs="obs-2", candidate=second)])
    assert summary["stored"] == 4 and [c[0] for c in fetch.calls] == ["daily", "daily", "minutes", "minutes"]


def test_an_already_stored_policy_is_not_written_again(monkeypatch):
    """Retry after a partial label writes only the missing policy (labels are immutable)."""
    summary, repo, _ = _run(monkeypatch, [_row(stored=[INC])])
    assert [s[1] for s in repo.saved] == [CH]
    assert (summary["stored"], summary["already_stored"]) == (1, 1)


def test_an_incomplete_horizon_awaits_sessions_without_stock_requests(monkeypatch):
    """Too few NIFTY sessions since the decision (3 of 15): no stock request, no write, no failure."""
    fetch = Fetch()
    recent = fetch.daily.index[-4].date()
    summary, repo, fetch = _run(monkeypatch, [_row(day=recent)], fetch=fetch)
    assert (summary["awaiting_sessions"], summary["selected"]) == (1, 0)
    assert summary["status"] == "SUCCESS" and repo.saved == [] and [c[1] for c in fetch.calls] == [m.NIFTY_KEY]


def test_a_stock_short_of_sessions_is_deferred(monkeypatch):
    """NIFTY complete but the stock has fewer bars (suspension): deferred, no minute request."""
    fetch = Fetch()
    real, short = fetch.day, fetch.daily.loc[:pd.Timestamp(D0) + pd.Timedelta(days=10)]
    fetch.day = lambda c, t, key, s_, e: real(c, t, key, s_, e) if key == m.NIFTY_KEY else short
    summary, repo, _ = _run(monkeypatch, [_row()], fetch=fetch)
    assert summary["deferred"] == 1 and summary["status"] == "SUCCESS" and repo.saved == []


def test_completed_decisions_fill_the_cap_while_waiting_ones_take_no_slot():
    """Holiday cluster: 70 newest still waiting, 5 older complete -> the 5 are selected."""
    daily, _ = _path(sessions=40)
    last = daily.index.max().date()
    waiting = [(f"w{i}", last - dt.timedelta(days=1)) for i in range(70)]
    done = [(f"d{i}", D0) for i in range(5)]
    selected, awaiting = m.completed_decisions(waiting + done, daily, today=TODAY, limit=60)
    assert selected == [f"d{i}" for i in range(5)] and awaiting == 70
    sessions = sorted(daily.index.normalize())
    edge = sessions[-16].date()            # exactly 15 sessions after it: complete
    short = sessions[-15].date()           # 14 sessions after it: still waiting
    assert m.completed_decisions([("e", edge), ("s", short)], daily, today=TODAY) == (["e"], 1)


def test_over_the_cap_half_newest_and_half_the_oldest_with_daily_tie_shuffles():
    """Newest first: 40 on D0+1, then 40 on D0. The 30 newest always; the other 30 all from D0
    (closest to expiry); which D0 ties win changes by day, never repeating within a run."""
    daily, _ = _path(sessions=40)
    newer = [(f"n{i}", D0 + dt.timedelta(days=1)) for i in range(40)]
    older = [(f"o{i}", D0) for i in range(40)]
    picks = [m.completed_decisions(newer + older, daily, today=TODAY + dt.timedelta(days=k), limit=60)[0]
             for k in range(3)]
    for picked in picks:
        assert picked[:30] == [f"n{i}" for i in range(30)] and len(set(picked)) == 60
        assert all(x.startswith("o") for x in picked[30:])
    assert len({tuple(sorted(p_[30:])) for p_ in picks}) > 1          # ties reshuffled by day
    assert m.completed_decisions(newer + older, daily, today=TODAY, limit=1)[0] == ["n0"]
    assert m.completed_decisions(older[:60], daily, today=TODAY, limit=60)[0] == [f"o{i}" for i in range(40)]


def test_selection_rotates_on_the_run_day(monkeypatch):
    """The run hands its own date to the selection (the tie shuffle changes daily)."""
    seen = []

    def spy(pending, benchmark, *, today, limit=m.MAX_DECISIONS_PER_RUN):
        """Record the date; select nothing."""
        seen.append(today)
        return [], 0
    monkeypatch.setattr(m, "completed_decisions", spy)
    summary, _, _ = _run(monkeypatch, [_row()])
    assert seen == [TODAY] and summary["selected"] == 0


def test_an_empty_stock_answer_is_deferred_not_failed(monkeypatch):
    """HTTP 200 with no candles for the stock (benchmark fine): deferred, run stays SUCCESS."""
    fetch = Fetch()
    real = fetch.day
    fetch.day = lambda c, t, key, s, e: real(c, t, key, s, e) if key == m.NIFTY_KEY else pd.DataFrame()
    summary, repo, _ = _run(monkeypatch, [_row()], fetch=fetch)
    assert summary["deferred"] == 1 and summary["status"] == "SUCCESS" and repo.events == []


def test_an_empty_benchmark_fails_the_run_before_stock_requests(monkeypatch):
    """No NIFTY history: FAILED, no stock request, no label, an ERROR event."""
    fetch = Fetch()
    fetch.daily = fetch.daily.iloc[0:0]
    summary, repo, fetch = _run(monkeypatch, [_row()], fetch=fetch)
    assert summary["status"] == "FAILED" and len(fetch.calls) == 1 and repo.saved == []
    assert repo.events[0][1] == "ERROR"


def test_a_failed_stock_is_contained_and_reported(monkeypatch):
    """One stock's fetch error: PARTIAL (a WARNING event), the other stock still labelled."""
    fetch = Fetch(fail={"NSE_EQ|BAD": ValueError("HTTP 200 error body")})
    summary, repo, _ = _run(monkeypatch, [_row(obs="obs-bad", key="NSE_EQ|BAD"), _row()], fetch=fetch)
    assert summary["status"] == "PARTIAL" and summary["failed"] == 1 and summary["stored"] == 2
    (source, severity, code, _message, detail), = repo.events
    assert (source, severity, code) == ("scheduled_stage2_maturation", "WARNING", "STAGE2_MATURATION_FAILED")
    assert detail["failures"][0]["observation_id"] == "obs-bad"


def test_a_malformed_row_is_counted_and_never_stops_the_run(monkeypatch):
    """A batch entry missing its capture inputs: one failure, the next decision still labelled."""
    broken = _candidate(decision_id="obs-x")
    del broken["inputs_used"]["equity_capture"]
    summary, repo, _ = _run(monkeypatch, [_row(obs="obs-x", candidate=broken), _row()])
    assert summary["failed"] == 1 and summary["stored"] == 2 and summary["status"] == "PARTIAL"
    assert repo.events[0][4]["failures"][0] == {"observation_id": "obs-x", "error_kind": "KeyError",
                                                "message": "'equity_capture'"}


def test_a_rejected_token_stops_the_run(monkeypatch):
    """PermissionError: no more requests with a rejected token; FAILED, not raised."""
    fetch = Fetch(fail={"NSE_EQ|DENIED": PermissionError("Upstox rejected the Analytics Token")})
    summary, repo, fetch = _run(monkeypatch, [_row(obs="o-d", key="NSE_EQ|DENIED"), _row()], fetch=fetch)
    assert summary["status"] == "FAILED" and summary["error_type"] == "PermissionError"
    assert len(fetch.calls) == 2 and repo.saved == [] and len(repo.events) == 1


def _lease_valid_for(checks: int):
    """A lease that is lost after `checks` successful checks."""
    calls = []

    def lease():
        """Raise once the allowance is used."""
        calls.append(1)
        if len(calls) > checks:
            raise RuntimeError("Collector lease was lost; fenced worker stopped")
    return lease


def _fenced_run(monkeypatch, checks):
    """A run whose lease is lost after `checks` checks; returns (repo, fetch)."""
    repo, fetch = Repo(), Fetch()
    _select(monkeypatch, [_row()])
    with pytest.raises(s2.LeaseLost):
        m.mature_shadow_passes(repo, None, "t", today=TODAY, fetch_daily=fetch.day, fetch_minutes=fetch.minute,
                               check_lease=_lease_valid_for(checks), environ=ENABLED, sleep=lambda s: None)
    return repo, fetch


def test_a_lease_lost_before_the_write_stops_with_nothing_saved(monkeypatch):
    """Checks 1-2 pass (run start, decision start); the pre-write check fails: nothing saved."""
    repo, fetch = _fenced_run(monkeypatch, 2)
    assert repo.saved == [] and repo.events == []
    assert [c[0] for c in fetch.calls] == ["daily", "daily", "minutes", "minutes"]


def test_a_lease_lost_at_a_decision_start_stops_before_its_requests(monkeypatch):
    """Only the run-start check passes: the stock is never fetched."""
    repo, fetch = _fenced_run(monkeypatch, 1)
    assert [c[1] for c in fetch.calls] == [m.NIFTY_KEY] and repo.saved == []


def test_a_fenced_failure_writes_no_quality_event():
    """FAILED after the lease is gone: the report write is skipped, never raised."""
    repo, summary = Repo(), {"status": "FAILED", "failed": 0}
    m._report(repo, summary, [], _lease_valid_for(0))
    assert repo.events == []


def test_guard_turns_any_lease_error_into_lease_lost():
    """Direct: no lease check is a no-op; a valid one passes; any error becomes LeaseLost."""
    m._guard(None)
    m._guard(lambda: None)
    with pytest.raises(s2.LeaseLost, match="RuntimeError"):
        m._guard(lambda: (_ for _ in ()).throw(RuntimeError()))


def test_mature_one_defers_without_a_horizon_and_skips_stored_policies():
    """Direct: no horizon end -> deferred, nothing written; a stored policy is not written again."""
    repo, summary = Repo(), {"deferred": 0, "unlabelled": 0, "already_stored": 0, "stored": 0}
    daily, minutes = _path(jump_day=5)
    m._mature_one(repo, _decision(), history=(daily, minutes, None, minutes), benchmark=daily,
                  today=TODAY, check_lease=None, summary=summary)
    assert summary["deferred"] == 1 and repo.saved == []
    m._mature_one(repo, _decision(stored=[INC]), history=(daily, minutes, D0, minutes), benchmark=daily,
                  today=TODAY, check_lease=None, summary=summary)
    assert (summary["already_stored"], summary["stored"]) == (1, 1) and [s[1] for s in repo.saved] == [CH]


def test_the_budget_stops_the_run_as_partial(monkeypatch):
    """Over budget: stop before the next decision, keep what is stored, say PARTIAL (a WARNING)."""
    ticks = iter([0.0, 0.0, m.BUDGET_SECONDS + 1, m.BUDGET_SECONDS + 1])
    summary, repo, _ = _run(monkeypatch, [_row(), _row(obs="obs-2")], clock=lambda: next(ticks))
    assert summary["stopped"] == "BUDGET" and summary["stored"] == 2 and summary["status"] == "PARTIAL"
    (_source, severity, _code, message, _detail), = repo.events
    assert severity == "WARNING" and message.endswith("stopped by BUDGET")
    assert [s[0] for s in repo.saved] == ["obs-1", "obs-1"]          # obs-2 untouched: retried later


def test_no_pending_decisions_makes_no_request(monkeypatch):
    """Nothing old enough: no NIFTY request."""
    summary, _, fetch = _run(monkeypatch, [])
    assert summary["pending"] == 0 and fetch.calls == []


def test_a_selected_decision_missing_from_its_ledger_batch_is_a_failure(monkeypatch):
    """Selected but no batch entry: counted with its id, the run goes on (PARTIAL)."""
    repo, fetch = Repo(), Fetch()
    _select(monkeypatch, [_row(obs="obs-gone"), _row()], missing={"obs-gone"})
    summary = m.mature_shadow_passes(repo, None, "t", today=TODAY, fetch_daily=fetch.day,
                                     fetch_minutes=fetch.minute, environ=ENABLED, sleep=lambda s_: None)
    assert summary["failed"] == 1 and summary["stored"] == 2 and summary["status"] == "PARTIAL"
    assert repo.events[0][4]["failures"][0]["error_kind"] == "MissingDecisionInputs"


class _HTTPError(Exception):
    """requests.HTTPError stand-in: carries the response status."""

    def __init__(self, status):
        """Store a response with `status_code`."""
        super().__init__(f"HTTP {status}")
        self.response = type("R", (), {"status_code": status})()


@pytest.mark.parametrize("status,counter,run_status", [(400, "provider_rejected", "SUCCESS"),
                                                       (404, "provider_rejected", "SUCCESS"),
                                                       (429, "failed", "PARTIAL"),
                                                       (500, "failed", "PARTIAL")])
def test_an_instrument_the_provider_rejects_is_not_a_run_failure(monkeypatch, status, counter, run_status):
    """4xx for one instrument (dead key) is a data fact; rate limits and 5xx stay failures."""
    fetch = Fetch(fail={"NSE_EQ|DEAD": _HTTPError(status)})
    summary, repo, _ = _run(monkeypatch, [_row(obs="o-dead", key="NSE_EQ|DEAD"), _row()], fetch=fetch)
    assert summary[counter] == 1 and summary["stored"] == 2 and summary["status"] == run_status


def test_a_4xx_on_the_minute_request_is_a_failure_not_a_rejection(monkeypatch):
    """Only the per-instrument daily request can be 'provider_rejected'; the minute API failing is a failure."""
    fetch = Fetch()

    def minute(*args):
        """The minute endpoint answers 400 for everything."""
        raise _HTTPError(400)
    fetch.minute = minute
    summary, repo, _ = _run(monkeypatch, [_row()], fetch=fetch)
    assert summary["provider_rejected"] == 0 and summary["failed"] == 1 and summary["status"] == "PARTIAL"


def test_a_stale_benchmark_fails_the_run_before_stock_requests(monkeypatch):
    """NIFTY answers only bars older than STALE_BENCHMARK_DAYS: FAILED, nothing selected."""
    fetch = Fetch()
    fetch.daily = fetch.daily.loc[:pd.Timestamp(TODAY - dt.timedelta(days=m.STALE_BENCHMARK_DAYS + 1))]
    summary, repo, fetch = _run(monkeypatch, [_row()], fetch=fetch)
    assert summary["status"] == "FAILED" and [c[1] for c in fetch.calls] == [m.NIFTY_KEY]
    assert repo.saved == [] and repo.events[0][1] == "ERROR"
    assert repo.events[0][4]["summary"]["error_type"] == "ValueError"


def test_a_nan_open_on_the_stop_bar_keeps_the_stop_fill():
    """A touching bar with no open price is not a gap: exit stays at the stop."""
    daily, minutes = _custom_path({3: {200: (100.0, 96.0)}})
    stop_minute = minutes.index[(minutes["Low"] <= 97).to_numpy()][0]
    minutes.loc[stop_minute, "Open"] = float("nan")
    label = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily, benchmark_minutes=minutes, today=TODAY)[m.CHALLENGER]
    assert label["outcome"] == "stop" and label["exit"] == 97.0 and "stop_fill" not in label


def test_missing_nifty_minutes_on_the_entry_day_are_counted(monkeypatch):
    """NIFTY one-minute bars lack the decision day: no label for either policy, counted, retried."""
    fetch = Fetch()
    fetch.bench_minutes = fetch.minutes.loc[fetch.minutes.index.normalize() != pd.Timestamp(D0)]
    summary, repo, _ = _run(monkeypatch, [_row()], fetch=fetch)
    assert (summary["no_benchmark"], summary["unlabelled"], summary["stored"]) == (2, 2, 0)
    assert summary["status"] == "SUCCESS" and repo.saved == []


def test_an_empty_nifty_minute_answer_is_a_failure(monkeypatch):
    """HTTP 200 with no NIFTY minutes: a broken feed, not `no_benchmark`; PARTIAL with a WARNING."""
    fetch = Fetch()
    fetch.bench_minutes = fetch.minutes.iloc[0:0]
    summary, repo, _ = _run(monkeypatch, [_row()], fetch=fetch)
    assert (summary["failed"], summary["no_benchmark"], summary["status"]) == (1, 0, "PARTIAL")
    assert repo.events[0][4]["failures"][0]["message"] == "NIFTY minute history is empty"


def test_nifty_minutes_are_shared_per_window_only(monkeypatch):
    """Three stocks, one decision day: two share a horizon end (one NIFTY request), a suspended
    stock ends a session later (its own NIFTY request)."""
    fetch = Fetch()
    real = fetch.day
    suspended_day = fetch.daily.index[8]
    fetch.day = lambda c, t, key, s_, e: real(c, t, key, s_, e).drop(suspended_day, errors="ignore") \
        if key == "NSE_EQ|SUS" else real(c, t, key, s_, e)
    rows = [_row(obs="a", key="NSE_EQ|A"), _row(obs="b", key="NSE_EQ|B"), _row(obs="s", key="NSE_EQ|SUS")]
    _run(monkeypatch, rows, fetch=fetch)
    nifty = [c[3] for c in fetch.calls if c[:2] == ("minutes", m.NIFTY_KEY)]
    after = fetch.daily.loc[fetch.daily.index > pd.Timestamp(D0)].index
    assert sorted(nifty) == [after[14].date(), after[15].date()]


def test_one_stock_on_two_decision_days_gets_two_histories(monkeypatch):
    """The per-run cache is per stock AND decision day."""
    later = _candidate(decision_id="obs-2")
    later["inputs_used"]["evaluated_at"] = "2026-11-03T04:39:00+00:00"
    summary, _, fetch = _run(monkeypatch, [_row(), _row(obs="obs-2", day=D0 + dt.timedelta(days=1),
                                                         candidate=later)])
    assert [c[0] for c in fetch.calls] == ["daily", "daily", "minutes", "minutes", "daily", "minutes", "minutes"]


def test_a_pre_signal_dip_on_the_entry_day_is_not_the_stop_fill():
    """09:45 bar at 95 (before the 10:09 decision); 12:35 dip opens at 100: fill at the stop, 97."""
    daily, minutes = _custom_path({0: {30: (95.0, 95.0), 200: (100.0, 96.0)}})
    label = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily, benchmark_minutes=minutes, today=TODAY)[m.CHALLENGER]
    assert label["outcome"] == "stop" and label["exit"] == 97.0


def test_a_non_positive_open_on_the_stop_bar_gives_no_label():
    """A touching bar that opens at 0 is bad data, not a -100% gap: no label (retried later)."""
    daily, minutes = _custom_path({3: {200: (100.0, 96.0)}})
    stop_minute = minutes.index[(minutes["Low"] <= 97).to_numpy()][0]
    minutes.loc[stop_minute, "Open"] = 0.0
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily,
                              benchmark_minutes=minutes, today=TODAY)
    assert labels[m.CHALLENGER] is None and labels[m.INCUMBENT]["outcome"] == "horizon"


def _nifty(rises_at: tuple[int, int], to: float = 101.0):
    """NIFTY flat at 100, at `to` from (session, minute) on: its daily and one-minute bars."""
    session, minute = rises_at
    mods = {s_: {i: (to, to) for i in range(minute if s_ == session else 0, 375)} for s_ in range(session, 20)}
    return _custom_path(mods)


def test_the_benchmark_starts_at_the_entry_minute_not_the_day_open():
    """NIFTY +1% between 09:15 and the 10:10 entry, flat after: the stock's excess is not charged it."""
    daily, minutes = _path()                                   # stock flat at 100
    nifty_daily, nifty_minutes = _nifty((0, 30))               # 09:45: 100 -> 101
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=nifty_daily,
                              benchmark_minutes=nifty_minutes, today=TODAY)
    inc = labels[m.INCUMBENT]
    assert inc["entry_timestamp"] == "2026-11-02T10:10:00" and inc["outcome"] == "horizon"
    assert inc["benchmark_return"] == 0.0                      # the production label says +1%
    assert inc["excess_return"] == pytest.approx(inc["net_return"]) == pytest.approx(-0.002)


def test_the_benchmark_ends_at_the_exit_minute_of_a_stop():
    """Challenger stopped at 12:35 on session 3; NIFTY falls 1% at 12:36: not in its benchmark."""
    daily, minutes = _path(drop_day=3)                         # stop 97 touched at minute 200
    nifty_daily, nifty_minutes = _nifty((3, 201), to=99.0)
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=nifty_daily,
                              benchmark_minutes=nifty_minutes, today=TODAY)
    ch, inc = labels[m.CHALLENGER], labels[m.INCUMBENT]
    assert ch["outcome"] == "stop" and ch["benchmark_return"] == 0.0
    assert ch["excess_return"] == pytest.approx(0.97 - 1 - 0.002)
    assert inc["outcome"] == "horizon" and inc["benchmark_return"] == pytest.approx(-0.01)  # held through it


def _nifty_ramp(close_bump: float = 0.0):
    """NIFTY rising every minute (open != close), daily closes bumped by `close_bump`."""
    prices, k = {}, 0
    for day in _days(D0 - dt.timedelta(days=7), 25):
        bars = []
        for _ in range(375):
            bars.append((100 + 0.001 * k, 100 + 0.001 * k + 0.0005))
            k += 1
        prices[day] = bars
    daily, minutes = _bars(prices)
    daily["Close"] = daily["Close"] + close_bump
    return daily, minutes


def test_the_benchmark_uses_exactly_the_entry_open_the_exit_close_and_the_daily_close():
    """Stop exit: open of the 10:10 entry minute -> close of the 12:35 exit minute. Time exit:
    -> NIFTY's daily close (deliberately unlike its last minute here)."""
    daily, minutes = _path(drop_day=3)
    nifty_daily, nifty_minutes = _nifty_ramp(close_bump=0.5)
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=nifty_daily,
                              benchmark_minutes=nifty_minutes, today=TODAY)
    base = nifty_minutes.loc[pd.Timestamp("2026-11-02 10:10"), "Open"]
    exit_at = pd.Timestamp(_days(D0, 4)[3]) + pd.Timedelta(hours=9, minutes=15 + 200)
    assert labels[m.CHALLENGER]["benchmark_return"] == pytest.approx(nifty_minutes.loc[exit_at, "Close"] / base - 1)
    inc = labels[m.INCUMBENT]
    end = nifty_daily.loc[pd.Timestamp(inc["label_end_date"]), "Close"]
    assert inc["benchmark_return"] == pytest.approx(end / base - 1)


def test_nifty_minutes_too_far_from_entry_or_exit_give_no_label():
    """NIFTY missing 10:10-10:20 on the entry day: no start within 5 min -> no label for either policy.
    Missing 12:28-12:35 on the stop day: the challenger's exit has no NIFTY minute -> no label."""
    daily, minutes = _path(drop_day=3)
    nifty_daily, nifty_minutes = _nifty_ramp()
    late = nifty_minutes.drop(pd.date_range("2026-11-02 10:10", "2026-11-02 10:20", freq="min"))
    notes = {}
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=nifty_daily,
                              benchmark_minutes=late, today=TODAY, notes=notes)
    assert labels == {m.INCUMBENT: None, m.CHALLENGER: None} and notes == {"no_benchmark": 2}
    exit_at = pd.Timestamp(_days(D0, 4)[3]) + pd.Timedelta(hours=9, minutes=15 + 200)
    early = nifty_minutes.drop(pd.date_range(exit_at - pd.Timedelta(minutes=7), exit_at, freq="min"))
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=nifty_daily,
                              benchmark_minutes=early, today=TODAY)
    assert labels[m.CHALLENGER] is None and labels[m.INCUMBENT] is not None


def test_a_benchmark_window_never_runs_backwards():
    """Entry 10:10, stop at 10:11, NIFTY missing 10:10-10:13: its first minute (10:14) is after the
    exit, so no benchmark (never close-before-open)."""
    daily, minutes = _custom_path({0: {56: (100.0, 96.0)}})      # 10:11 dip through the 97 stop
    nifty_daily, nifty_minutes = _nifty_ramp()
    gap = nifty_minutes.drop(pd.date_range("2026-11-02 10:10", "2026-11-02 10:13", freq="min"))
    labels = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=nifty_daily,
                              benchmark_minutes=gap, today=TODAY)
    assert labels[m.CHALLENGER] is None
    full = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=nifty_daily,
                            benchmark_minutes=nifty_minutes, today=TODAY)[m.CHALLENGER]
    assert full["outcome"] == "stop" and full["benchmark_return"] > 0


def test_execution_adjustment_refuses_missing_evidence():
    """Direct: no exit bar for a stop label, or no NIFTY minute at entry -> None; the latter counted."""
    daily, minutes = _path(drop_day=3)
    label = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily,
                             benchmark_minutes=minutes, today=TODAY)[m.CHALLENGER]
    notes = {}
    no_bar = minutes.loc[minutes.index.normalize() != pd.Timestamp(label["outcome_date"])]
    assert m._execution_adjusted(label, no_bar, daily, minutes, 97.0, 104.86, notes) is None and notes == {}
    late = minutes.loc[minutes.index.normalize() != pd.Timestamp(D0)]
    assert m._execution_adjusted(label, minutes, daily, late, 97.0, 104.86, notes) is None
    assert notes == {"no_benchmark": 1}
    assert m._benchmark_return({**label, "entry_timestamp": None}, None, daily, minutes) is None


def test_the_first_touching_bar_sets_the_stop_fill():
    """First touch opens above the stop (fill 97); a later gap bar at 90 must not be used."""
    daily, minutes = _custom_path({3: {200: (100.0, 96.0), 300: (90.0, 90.0)}})
    label = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily, benchmark_minutes=minutes, today=TODAY)[m.CHALLENGER]
    assert label["outcome"] == "stop" and label["exit"] == 97.0


def test_the_gap_fill_never_touches_a_target_exit():
    """Target hit at 12:35; a gap bar at 90 later that day does not change the exit."""
    daily, minutes = _custom_path({5: {200: (100.0, 105.0), 300: (90.0, 90.0)}})
    label = m.label_decision(_decision(), daily=daily, minutes=minutes, benchmark=daily, benchmark_minutes=minutes, today=TODAY)[m.CHALLENGER]
    assert label["outcome"] == "target" and label["exit"] == 104.86 and "stop_fill" not in label


# ---------- collector wiring ----------

def test_scan_reports_maturation_and_off_by_default(monkeypatch):
    """The scan result carries the maturation summary; the switch is off unless set."""
    from test_equity_stage2_collector import Repo as ScanRepo, _scan
    monkeypatch.delenv(m.ENABLE_ENV, raising=False)
    result, client = _scan(monkeypatch, ScanRepo(), enabled=False)
    assert result["stage2_maturation"]["status"] == "DISABLED" and client.calls == []


def test_scan_hands_maturation_the_lease_and_the_scan_date(monkeypatch):
    """Today = the scan's IST date; history fetchers = the collector's own."""
    from test_equity_stage2_collector import NOW, Repo as ScanRepo, _scan
    seen = {}

    def spy(repo, client, token, **kwargs):
        """Record the arguments."""
        seen.update(kwargs)
        return {"status": "SUCCESS", "stored": 3}

    monkeypatch.setattr(collector, "mature_shadow_passes", spy)
    lease = type("Lease", (), {"assert_valid": lambda self: None})()
    result, _ = _scan(monkeypatch, ScanRepo(), enabled=False, lease=lease)
    assert seen["today"] == NOW.astimezone(IST).date()
    assert seen["fetch_daily"] is collector.fetch_daily_history
    assert seen["fetch_minutes"] is collector.fetch_historical_minutes
    assert seen["check_lease"] == lease.assert_valid
    assert result["stage2_maturation"] == {"status": "SUCCESS", "stored": 3}


class RunRepo:
    """The run/lease API run('scan') needs."""

    def __init__(self):
        """Start empty."""
        self.finished = []

    def acquire_collector_lease(self, *a, **k):
        """Grant the lease."""
        return {"fencing_token": 7}

    def renew_collector_lease(self, *a, **k):
        """Keep the lease."""
        return True

    def release_collector_lease(self, *a, **k):
        """Release the lease."""
        return True

    def start_run(self, *a, **k):
        """Run id."""
        return "run-1"

    def finish_run(self, run_id, **kwargs):
        """Record the final status."""
        self.finished.append(kwargs)


@pytest.mark.parametrize("status,expected", [("SUCCESS", "SUCCESS"), ("PARTIAL", "PARTIAL"),
                                             ("FAILED", "PARTIAL")])
def test_run_status_and_record_count_include_maturation(monkeypatch, status, expected):
    """A PARTIAL/FAILED maturation makes the scan run PARTIAL; stored labels count as records."""
    repo = RunRepo()
    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", "token")
    monkeypatch.setattr(collector, "ProductionRepository", lambda *a, **k: repo)
    monkeypatch.setattr(collector, "session", lambda: None)
    monkeypatch.setattr(collector, "_scheduled_stage1", lambda *a, **k: {
        "status": "SUCCESS", "scanner_observations": 5, "stage2_shadow": {"status": "SUCCESS"},
        "stage2_maturation": {"status": status, "stored": 4}})
    result = collector.run("scan")
    assert result["status"] == expected and repo.finished[-1]["status"] == expected
    assert repo.finished[-1]["record_count"] == 5 + 4


def test_workflow_passes_the_switch():
    """Repository variable, unset = off."""
    workflow = (ROOT / ".github/workflows/scheduled-collector.yml").read_text()
    assert "SCHEDULED_STAGE2_MATURATION: ${{ vars.SCHEDULED_STAGE2_MATURATION }}" in workflow


# ---------- SQL on the local PGlite harness ----------

needs_sql = pytest.mark.skipif(not os.environ.get("EQUITY_TEST_PGLITE_MODULE"),
                               reason="Local SQL harness not configured")


@pytest.fixture
def db():
    """Real column shapes: scanner rows and ledger (drive_archive SPECS), production label DDL."""
    from drive_archive import SPECS
    from test_archive_maintenance_sql import Pg
    pg = Pg()
    source = (ROOT / "production_repository.py").read_text()
    ddl = re.search(r"CREATE TABLE IF NOT EXISTS \{SCHEMA\}\.prediction_targets \((.*?)\n\s*\)\n",
                    source, re.S).group(1).replace("{SCHEMA}", "quant_app")
    try:
        pg.send({"script": "CREATE SCHEMA quant_app;"})
        for table, key in (("scanner_observations", "observation_id"), ("evidence_ledger_events", "event_id")):
            columns = ",".join(f"{n} {k}" for n, k in SPECS[table].items())
            pg.execute(f"CREATE TABLE quant_app.{table} ({columns}, PRIMARY KEY({key}))")
        pg.send({"script": f"CREATE TABLE quant_app.prediction_targets ({ddl});"})
        yield pg
    finally:
        pg.send({"close": True})
        pg.process.communicate(timeout=15)


class SqlRepo:
    """repo.connect() over the harness."""

    def __init__(self, pg):
        """Wrap the harness."""
        self.pg = pg

    def connect(self):
        """The harness' transaction context."""
        return self.pg.connect()


def _seed(pg, run="run-1", day=D0, symbol="SYN", observed=None, score=72.0, passed=True,
          strategy=s2.STAGE2_SHADOW_VERSION, action="Buy", obs=None):
    """One shadow scanner row and its entry in the run's ledger batch (created once per run)."""
    key, obs = f"NSE_EQ|{symbol}", obs or f"obs-{run}-{symbol}"
    observed = observed or f"{day.isoformat()}T04:37:57Z"
    pg.execute("INSERT INTO quant_app.scanner_observations VALUES (%s,%s,%s::timestamptz,%s,%s,%s,%s,true,%s,"
               "NULL,%s,100,80,128,%s::jsonb)",
               (obs, day, observed, key, symbol, strategy, day, passed, score,
                json.dumps({"retention": "ledger_v1", "scan_run_id": f"{run}{s2.STAGE2_RUN_SUFFIX}"})))
    aggregate = f"scan:{run}{s2.STAGE2_RUN_SUFFIX}"
    existing = pg.execute("SELECT payload FROM quant_app.evidence_ledger_events WHERE aggregate_id=%s",
                          (aggregate,)).fetchone()
    candidate = _candidate(instrument_key=key, decision_id=obs)
    candidate["inputs_used"].update(stage2_pass=passed, signal_action=action)
    if existing is None:
        pg.execute("INSERT INTO quant_app.evidence_ledger_events VALUES (gen_random_uuid(),%s,1,"
                   "'DECISION_BATCH_EVALUATED',now(),now(),'t','a',%s,%s::jsonb,'p',%s,'sha256',1,NULL)",
                   (aggregate, aggregate, json.dumps({"candidates": [candidate]}), aggregate))
    else:
        payload = existing[0] if isinstance(existing[0], dict) else json.loads(existing[0])
        payload["candidates"].append(candidate)
        pg.execute("UPDATE quant_app.evidence_ledger_events SET payload=%s::jsonb WHERE aggregate_id=%s",
                   (json.dumps(payload), aggregate))
    return obs


def _label(pg, obs, version, outcome="target", net=0.03, excess=0.01, horizon=15):
    """One stored label under `version` (a policy name means its shadow version)."""
    version = m.shadow_target_version(version) if version in m.POLICIES else version
    pg.execute("INSERT INTO quant_app.prediction_targets(observation_id,horizon_sessions,target_version,"
               "entry_date,label_end_date,outcome_date,outcome,target_before_stop,gross_return,net_return,"
               "benchmark_return,excess_return,positive_excess,cost_bps,entry_quality) VALUES "
               "(%s,%s,%s,'2026-11-02','2026-11-20','2026-11-10',%s,%s,%s,%s,0.02,%s,%s,20,"
               "'first_minute_after_signal')",
               (obs, horizon, version, outcome, outcome == "target", net + 0.002, net, excess, excess > 0))


@needs_sql
def test_pending_query_selects_unlabelled_shadow_passes_newest_first(db):
    """Window [today-60, today-22] inclusive; passes only; shadow strategy only; not fully labelled."""
    partial = _seed(db, run="r30", symbol="B", day=TODAY - dt.timedelta(days=30))
    _label(db, partial, m.INCUMBENT)
    _label(db, partial, TARGET_VERSION)               # a production label never counts as shadow
    done = _seed(db, run="r30", symbol="C", day=TODAY - dt.timedelta(days=30))
    for policy in m.POLICIES:
        _label(db, done, policy)
    edge_new = _seed(db, run="r22", symbol="N", day=TODAY - dt.timedelta(days=22))
    edge_old = _seed(db, run="r60", symbol="O", day=TODAY - dt.timedelta(days=60))
    _seed(db, run="r21", symbol="Y", day=TODAY - dt.timedelta(days=21))
    _seed(db, run="r61", symbol="Z", day=TODAY - dt.timedelta(days=61))
    _seed(db, run="r30", symbol="REJ", day=TODAY - dt.timedelta(days=30), passed=False)
    _seed(db, run="app", symbol="APP", day=TODAY - dt.timedelta(days=30), strategy="equity-scanner-v19.0:quick")
    pending = m.pending_shadow_passes(SqlRepo(db), today=TODAY)
    assert [r[0] for r in pending] == [edge_new, partial, edge_old]   # newest first, no cap here
    assert [pd.Timestamp(r[1]).date() for r in pending] == [TODAY - dt.timedelta(days=d) for d in (22, 30, 60)]
    rows = m.decision_rows(SqlRepo(db), [edge_old, partial])
    assert [r[0] for r in rows] == [partial, edge_old]                # full rows, newest first
    parsed = {r[0]: m.parse_pending_row(r) for r in rows}
    assert parsed[partial]["stored_versions"] == {INC}
    assert parsed[edge_old]["stored_versions"] == set() and parsed[edge_old]["atr"] == 2.0
    assert m.decision_rows(SqlRepo(db), []) == []


def _scan_days(pg, after, today, skip=()):
    """A shadow scan (one rejected row) on every weekday after `after` and before `today`."""
    day = after + dt.timedelta(days=1)
    while day < today:
        if day.weekday() < 5 and day not in skip:
            _seed(pg, run=f"s-{day}", symbol="SESS", day=day, passed=False)
        day += dt.timedelta(days=1)


def _ist_today():
    """The report's own date: the database clock in IST."""
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()


def _report(db):
    """Run the read-only report; {(sample, policy, action, band): (eligible, labelled, ...)}."""
    rows = db.execute((ROOT / "sql/stage2_shadow_outcomes_report.sql").read_text()).fetchall()
    return {tuple(r[0:4]): r[4:13] for r in rows}


@needs_sql
def test_report_scores_both_policies_on_the_same_first_scan_of_each_stock_day(db):
    """A1 (earliest scan) is the decision for stock A even though only A2 has a challenger label."""
    day = _ist_today() - dt.timedelta(days=30)
    a1 = _seed(db, run="r1", symbol="A", day=day, observed=f"{day}T04:37:57Z", score=70.0, action="Buy")
    a2 = _seed(db, run="r2", symbol="A", day=day, observed=f"{day}T09:07:57Z", score=70.0, action="Buy")
    b = _seed(db, run="r1", symbol="B", day=day, score=55.0, action="Watch")
    _label(db, a1, m.INCUMBENT, "horizon", 0.01)
    _label(db, a2, m.CHALLENGER, "stop", -0.03)      # later scan of the same stock-day: not the decision
    _label(db, b, m.CHALLENGER, "target", 0.04, 0.02)
    _label(db, b, m.INCUMBENT, "stop", -0.02, -0.01)
    _label(db, b, TARGET_VERSION, "target", 0.5)     # production label: ignored
    _label(db, a1, m.CHALLENGER, "target", 0.9, horizon=10)   # another horizon: ignored
    table = _report(db)
    # eligible, labelled, targets, stops, time exits, avg net %, median, excess, positive %
    assert table[("all", m.CHALLENGER, "ALL", "ALL")][:5] == (2, 1, 1, 0, 0)
    assert float(table[("all", m.CHALLENGER, "ALL", "ALL")][5]) == 4.0
    assert table[("all", m.INCUMBENT, "ALL", "ALL")][:5] == (2, 2, 0, 1, 1)
    assert table[("all", m.INCUMBENT, "Buy", "70+")][:2] == (1, 1)        # score exactly 70 -> 70+
    assert table[("all", m.CHALLENGER, "Buy", "70+")][:2] == (1, 0)       # A has no challenger label
    assert table[("paired", m.CHALLENGER, "ALL", "ALL")][:2] == (1, 1)    # only B is paired
    assert table[("paired", m.INCUMBENT, "Watch", "50-60")][:4] == (1, 1, 0, 1)
    assert float(table[("all", m.CHALLENGER, "ALL", "ALL")][8]) == 100.0  # positive share of labelled


@needs_sql
def test_report_eligibility_age_passes_only_and_missing_ledger_entries(db):
    """22 days old counts, 21 not; rejected rows never; a decision missing from its batch, or whose batch
    event is gone, still counts."""
    today = _ist_today()
    _scan_days(db, today - dt.timedelta(days=22), today)      # 21 days: exactly 15 weekdays
    _seed(db, run="r22", symbol="OLD", day=today - dt.timedelta(days=22))
    _seed(db, run="r21", symbol="NEW", day=today - dt.timedelta(days=21))
    _seed(db, run="r22", symbol="REJ", day=today - dt.timedelta(days=22), passed=False)
    lost = _seed(db, run="r22", symbol="LOST", day=today - dt.timedelta(days=22))
    db.execute("UPDATE quant_app.evidence_ledger_events SET payload = jsonb_build_object('candidates', "
               "(SELECT jsonb_agg(c) FROM jsonb_array_elements(payload->'candidates') c "
               "WHERE c->>'decision_id' <> %s)) WHERE aggregate_id = %s", (lost, f"scan:r22{s2.STAGE2_RUN_SUFFIX}"))
    gone = _seed(db, run="r22b", symbol="GONE", day=today - dt.timedelta(days=22))
    db.execute("DELETE FROM quant_app.evidence_ledger_events WHERE aggregate_id = %s", (f"scan:r22b{s2.STAGE2_RUN_SUFFIX}",))
    del gone
    table = _report(db)
    assert table[("all", m.INCUMBENT, "ALL", "ALL")][:2] == (3, 0)        # OLD, LOST and GONE
    assert table[("all", m.INCUMBENT, "unknown", "ALL")][:2] == (2, 0)    # LOST, GONE: no recorded action


def _weekdays_after(day, count):
    """The first `count` weekdays after `day`."""
    return [d for d in (day + dt.timedelta(days=i) for i in range(1, 15)) if d.weekday() < 5][:count]


@needs_sql
def test_report_waits_for_fifteen_shadow_scan_sessions(db):
    """A missed session leaves a 22-day-old decision at 14: not eligible. Neither an app scan on
    the missed day nor a shadow scan today makes it a 15th."""
    today = _ist_today()
    d22, d30 = today - dt.timedelta(days=22), today - dt.timedelta(days=30)
    missed, = _weekdays_after(d22, 1)
    _scan_days(db, d30, today, skip={missed})
    _seed(db, run="app", symbol="APP", day=missed, passed=False, strategy="equity-scanner-v19.0:quick")
    _seed(db, run="now", symbol="TOD", day=today, passed=False)
    _seed(db, run="r30", symbol="OLD", day=d30)
    _seed(db, run="r22", symbol="SHORT", day=d22)
    assert _report(db)[("all", m.INCUMBENT, "ALL", "ALL")][:2] == (1, 0)          # OLD only


@needs_sql
def test_report_counts_every_pass_of_a_day_once_any_of_it_is_labelled(db):
    """Two missed sessions: days 22 and 23 have 13 and 14. Day 23 has a shadow label, so all its
    passes count (LAB and SAME); day 22 has only a horizon-10 and a production label: not eligible."""
    today = _ist_today()
    d22, d23, d30 = (today - dt.timedelta(days=n) for n in (22, 23, 30))
    _scan_days(db, d30, today, skip=set(_weekdays_after(d22, 2)))
    _seed(db, run="r30", symbol="OLD", day=d30, score=45.0)
    _label(db, _seed(db, run="r23", symbol="LAB", day=d23, score=72.0), m.INCUMBENT)
    _seed(db, run="r23", symbol="SAME", day=d23, score=65.0)
    other = _seed(db, run="r22", symbol="OTHER", day=d22, score=55.0)
    _label(db, other, m.CHALLENGER, horizon=10)
    _label(db, other, TARGET_VERSION)
    table = _report(db)
    assert table[("all", m.INCUMBENT, "ALL", "ALL")][:2] == (3, 1)        # OLD, LAB, SAME
    assert table[("all", m.CHALLENGER, "ALL", "ALL")][:2] == (3, 0)
    # by score band: OLD <50, SAME 60-70 (unlabelled, same day as LAB), LAB 70+; OTHER (50-60) absent
    assert {k[3] for k in table if k[:3] == ("all", m.INCUMBENT, "Buy")} == {"ALL", "<50", "60-70", "70+"}
