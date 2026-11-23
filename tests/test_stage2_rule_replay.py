"""Stage-2 rule replay (stage2_rule_replay.py): level rules, decision parity, outcomes, summary."""
import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import equity_stage2_decision as decision_core
import stage2_rule_replay as replay

REAL_WAIT_OUTSIDE_SCANS = replay.wait_outside_scans


@pytest.fixture(autouse=True)
def _no_scan_pause(monkeypatch):
    """Tests never sleep through a live scan window (the real clock); the pause has its own tests."""
    monkeypatch.setattr(replay, "wait_outside_scans", lambda: 0.0)
from equity_stage2_collector import APP_DEFAULT_SETTINGS, evaluate_candidate
from equity_stage2_engine import derive_long_trade_levels
from equity_stage2_maturation import challenger_levels

DAYS = pd.bdate_range("2022-01-03", periods=520)


def _bars(drift, vol, seed, days=DAYS):
    """Synthetic OHLCV on business days (a fixture, not market data)."""
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, len(days))))
    opening = close * np.exp(rng.normal(0, vol / 3, len(days)))
    high = np.maximum(opening, close) * (1 + abs(rng.normal(0, vol / 2, len(days))))
    low = np.minimum(opening, close) * (1 - abs(rng.normal(0, vol / 2, len(days))))
    return pd.DataFrame({"Open": opening, "High": high, "Low": low, "Close": close,
                         "Volume": rng.integers(100_000, 1_000_000, len(days)).astype(float), "OI": np.nan},
                        index=days)


def _flat(lows, highs, price=100.0):
    """A 61-bar frame whose prior 20 lows / 60 highs are set, last bar at `price`."""
    n = 61
    frame = pd.DataFrame({"Open": price, "High": price, "Low": price, "Close": price, "Volume": 1.0},
                         index=pd.bdate_range("2024-01-01", periods=n))
    frame.iloc[-21:-1, frame.columns.get_loc("Low")] = lows
    frame.iloc[:-1, frame.columns.get_loc("High")] = highs
    return frame


@pytest.mark.parametrize("support,expected_stop", [(99.0, 97.0), (90.0, 95.0), (96.0, 95.7)])
def test_capped25_stop_is_the_structural_stop_clamped_to_1_5_and_2_5_atr(support, expected_stop):
    """ATR 2: near structure -> 1.5 ATR (97); far -> 2.5 ATR (95); between -> structural (support - 0.15 ATR)."""
    stop, target, rr, levels = replay.capped25_levels(_flat(support, 100.0), 100.0, 2.0)
    assert stop == expected_stop and levels["support20"] == support
    assert target == 108.0 and rr == round(8.0 / (100 - expected_stop), 2)   # no resistance: entry + 4 ATR


def test_capped25_target_is_a_reachable_resistance_else_4_atr():
    """Resistance between entry + 1.3 x risk and entry + 4 ATR is the target; too near or beyond: 4 ATR."""
    assert replay.capped25_levels(_flat(99.0, 106.0), 100.0, 2.0)[1] == 106.0     # risk 3: 103.9 <= 106 < 108
    assert replay.capped25_levels(_flat(99.0, 103.0), 100.0, 2.0)[1] == 108.0     # 103 < 103.9: too near
    assert replay.capped25_levels(_flat(99.0, 104.2), 100.0, 2.0)[1] == 104.2     # 1.3 R is enough (not 1.5 R)
    assert replay.capped25_levels(_flat(99.0, 112.0), 100.0, 2.0)[1] == 108.0     # beyond 4 ATR


def test_capped25_target_needs_1_3_risk_from_the_resistance():
    """Risk 5 (far support): 106 < 100 + 1.3 x 5 = 106.5, so the 4 ATR target is used."""
    stop, target, _, _ = replay.capped25_levels(_flat(90.0, 106.0), 100.0, 2.0)
    assert stop == 95.0 and target == 108.0


@pytest.mark.parametrize("rule", [replay.capped25_levels, replay.atr15_levels])
def test_level_rules_never_raise_and_reject_bad_inputs(rule):
    """Same contract as derive_long_trade_levels: (None,)*4 for empty frames, zero price or ATR."""
    assert rule(pd.DataFrame(), 100.0, 2.0) == (None, None, None, None)
    assert rule(_flat(99.0, 100.0), 0.0, 2.0) == (None, None, None, None)
    assert rule(_flat(99.0, 100.0), 100.0, 0.0) == (None, None, None, None)
    assert rule(None, 100.0, 2.0) == (None, None, None, None)


def test_atr15_matches_the_shadow_challenger():
    """atr15-stop-v1 = equity_stage2_maturation.challenger_levels on the same resistances."""
    frame = _bars(0.001, 0.02, 3).iloc[:300]
    price, atr = float(frame["Close"].iloc[-1]), 2.5
    _, r20, r60 = replay._resistances(frame, price, atr)
    stop, target, _, _ = replay.atr15_levels(frame, price, atr)
    assert (stop, target) == challenger_levels(price, atr, r20, r60, replay.HORIZON)


def test_resistances_match_the_incumbent_rule():
    """The shared reader returns exactly what derive_long_trade_levels reports."""
    frame = _bars(0.001, 0.02, 4).iloc[:300]
    price = float(frame["Close"].iloc[-1])
    _, _, _, levels = derive_long_trade_levels(frame, price, 2.0)
    s20, r20, r60 = replay._resistances(frame, price, 2.0)
    assert levels == {"support20": round(s20, 2), "resistance20": round(r20, 2), "resistance60": round(r60, 2)}


def test_rescored_changes_only_the_risk_reward_part_on_the_rr13_scale():
    """Live scale: the score as recorded; rr13: 0.15 x scale(net R:R, 1.3, 3.0) replaces the part."""
    components = {"risk_reward": 12.0}
    assert replay.rescored(60.0, components, 1.4, "incumbent-levels-v1") == 60.0
    assert replay.rescored(60.0, components, 1.4, "capped25-atr4-v1") == 60.0
    assert replay.rescored(60.0, components, 3.0, "capped25-atr4-rr13-v1") == pytest.approx(60 - 1.8 + 15)
    assert replay.rescored(60.0, components, 1.3, "capped25-atr4-rr13-v1") == pytest.approx(60 - 1.8)


def test_incumbent_decision_equals_the_collector_decision():
    """The incumbent variant is the live decision core: same pass, score, levels and action."""
    stock, nifty = _bars(0.0015, 0.015, 11), _bars(0.0004, 0.008, 12)
    found = 0
    for index in range(260, 500, 7):
        history, price = stock.iloc[:index], float(stock.iloc[index]["Open"])
        mine = replay.decide("SYN", "K", history, price, nifty.iloc[:index], "incumbent-levels-v1",
                             features=replay._CachedFeatures(), probability_cache={})
        theirs = evaluate_candidate("SYN", "K", history=history, quotes={"K": {"last_price": price}},
                                    nifty=nifty.iloc[:index], market_open=False, settings=APP_DEFAULT_SETTINGS,
                                    identity={}, now=lambda: dt.datetime.now(dt.timezone.utc))
        assert mine["pass"] == theirs["stage2_pass"]
        if mine["pass"]:
            found += 1
            assert (mine["score"], mine["stop"], mine["target"], mine["action"]) == (
                round(theirs["score"], 2), theirs["stop"], theirs["target"], theirs["signal_action"])
        else:
            assert mine["category"] == theirs["category"]
    assert found > 0


def test_decide_restores_the_decision_core_even_when_it_raises(monkeypatch):
    """The level rule (decision core and engine) and probability estimate are swapped back."""
    import equity_stage2_engine as engine
    before = (decision_core.derive_long_trade_levels, decision_core.compute_historical_setup_probability,
              engine.derive_long_trade_levels)

    def broken(*_a, **_k):
        """The decision core fails."""
        raise RuntimeError("boom")

    monkeypatch.setattr(decision_core, "evaluate_stage2", broken)
    with pytest.raises(RuntimeError):
        replay.decide("SYN", "K", _bars(0.001, 0.02, 5), 100.0, _bars(0.0, 0.01, 6), "capped25-atr4-v1",
                      features=replay._CachedFeatures(), probability_cache={})
    assert (decision_core.derive_long_trade_levels, decision_core.compute_historical_setup_probability,
            engine.derive_long_trade_levels) == before


def test_the_setup_estimate_uses_the_variant_levels_and_is_shared_per_level_rule(monkeypatch):
    """compute_historical_setup_probability reads engine.derive_long_trade_levels: it gets the variant's
    rule; the two capped25 variants share one estimate, the incumbent has its own."""
    import equity_stage2_engine as engine
    seen = []
    original = decision_core.compute_historical_setup_probability
    monkeypatch.setattr(decision_core, "compute_historical_setup_probability",
                        lambda df, **k: seen.append(engine.derive_long_trade_levels) or original(df, **k))
    stock, nifty = _bars(0.0015, 0.015, 11), _bars(0.0004, 0.008, 12)
    index = next(i for i in range(260, 500) if replay.decide(
        "SYN", "K", stock.iloc[:i], float(stock.iloc[i]["Open"]), nifty.iloc[:i], "incumbent-levels-v1",
        features=replay._CachedFeatures(), probability_cache={})["pass"])
    seen.clear()
    cache = {}
    for variant in ("incumbent-levels-v1", "capped25-atr4-v1", "capped25-atr4-rr13-v1"):
        replay.decide("SYN", "K", stock.iloc[:index], float(stock.iloc[index]["Open"]), nifty.iloc[:index],
                      variant, features=replay._CachedFeatures(), probability_cache=cache)
    assert seen == [derive_long_trade_levels, replay.capped25_levels] and len(cache) == 2


def test_probability_and_features_are_computed_once_per_day_for_all_variants(monkeypatch):
    """Variants share the slow estimate and the feature frame."""
    calls, frames = [], []
    original = decision_core.compute_historical_setup_probability
    original_frame = decision_core.compute_feature_frame
    monkeypatch.setattr(decision_core, "compute_feature_frame",
                        lambda source, ta: frames.append(1) or original_frame(source, ta))
    monkeypatch.setattr(decision_core, "compute_historical_setup_probability",
                        lambda df, **k: calls.append(1) or original(df, **k))
    stock, nifty = _bars(0.0015, 0.015, 11), _bars(0.0004, 0.008, 12)
    features, cache = replay._CachedFeatures(), {}
    index = next(i for i in range(260, 500) if replay.decide(
        "SYN", "K", stock.iloc[:i], float(stock.iloc[i]["Open"]), nifty.iloc[:i], "incumbent-levels-v1",
        features=replay._CachedFeatures(), probability_cache={})["pass"])
    calls.clear()
    frames.clear()
    for variant in replay.VARIANTS:
        replay.decide("SYN", "K", stock.iloc[:index], float(stock.iloc[index]["Open"]), nifty.iloc[:index],
                      variant, features=features, probability_cache=cache)
    assert len(calls) <= 3 and len(frames) == 1 and len(features.frames) == 1   # one estimate per level rule


def _path(prices):
    """Bars with the given (open, high, low, close) rows on business days."""
    return pd.DataFrame(prices, columns=["Open", "High", "Low", "Close"],
                        index=pd.bdate_range("2024-01-01", periods=len(prices)))


def test_outcome_stop_target_and_time_with_nifty_excess(monkeypatch):
    """Entry at the start bar's open; stop first; NIFTY from that open to the exit day's close."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    nifty = _path([(1000, 1000, 1000, 990), (1000, 1000, 1000, 1010), (1000, 1000, 1000, 1020),
                   (1000, 1000, 1000, 1030)])
    hit = replay.outcome(_path([(100, 101, 99, 100), (100, 111, 99, 110), (110, 111, 109, 110),
                                (110, 110, 110, 110)]), 0, 95, 110, nifty)
    assert hit["reason"] == "TARGET" and hit["gross_pct"] == pytest.approx(10) and hit["nifty_pct"] == pytest.approx(1)
    stop = replay.outcome(_path([(100, 101, 94, 96), (96, 97, 95, 96), (96, 96, 96, 96), (1, 1, 1, 1)]),
                          0, 95, 110, nifty)
    assert stop["reason"] == "STOP" and stop["gross_pct"] == pytest.approx(-5) and stop["sessions"] == 1
    timed = replay.outcome(_path([(100, 101, 99, 100), (100, 101, 99, 101), (101, 102, 100, 102),
                                  (1, 1, 1, 1)]), 0, 95, 110, nifty)
    assert timed["reason"] == "TIME" and timed["nifty_pct"] == pytest.approx(2) and timed["exit_index"] == 2


def test_outcome_none_for_short_window_bad_levels_or_missing_nifty(monkeypatch):
    """No partial windows, no invalid trades, no unmatched NIFTY day."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    bars = _path([(100, 101, 99, 100)] * 4)
    nifty = _path([(1000, 1000, 1000, 1000)] * 4)
    assert replay.outcome(bars, 2, 95, 110, nifty) is None
    assert replay.outcome(bars, 0, 101, 110, nifty) is None
    assert replay.outcome(bars, 0, 95, 110, nifty.iloc[1:]) is None
    gap = nifty.copy()
    gap.iloc[0, gap.columns.get_loc("Open")] = float("nan")
    assert replay.outcome(bars, 0, 95, 110, gap) is None                 # NaN is not a price
    assert replay.baseline(bars, 0, gap) == {"pass": False, "category": "BaselineUnavailable"}
    assert replay.baseline(bars, 2, nifty) == {"pass": False, "category": "BaselineUnavailable"}
    assert replay.baseline(bars, 10, nifty) == {"pass": False, "category": "BaselineUnavailable"}   # past the end
    endless = nifty.astype(float)
    endless.iloc[:, endless.columns.get_loc("Close")] = float("inf")
    assert replay.outcome(bars, 0, 95, 110, endless) is None and not replay.baseline(bars, 0, endless)["pass"]


def test_replay_days_need_full_live_windows_a_full_horizon_and_a_nifty_session(monkeypatch):
    """Every step-th session from the offset, once both live windows fit, with HORIZON bars left,
    that NIFTY also traded."""
    monkeypatch.setattr(replay, "HISTORY_DAYS", 7)
    monkeypatch.setattr(replay, "NIFTY_HISTORY_DAYS", 3)
    bars = _path([(1, 1, 1, 1)] * 40)          # business days from Mon 1 Jan 2024
    nifty = bars.drop(bars.index[10])
    assert replay.replay_days(bars, nifty, offset=0, step=5) == [5, 15, 20, 25]   # 5 = Mon 8 Jan
    assert replay.replay_days(bars, nifty, offset=2, step=5) == [7, 12, 17, 22]
    assert replay.replay_days(bars.iloc[:0], nifty) == []


def test_live_windows_hold_only_the_live_history_before_the_day():
    """Stock: HISTORY_DAYS calendar days before D; NIFTY: NIFTY_HISTORY_DAYS; never D itself."""
    days = pd.date_range("2020-01-01", periods=2000, freq="D")
    frame = pd.DataFrame({"Close": range(2000)}, index=days)
    stock, index = replay.live_windows(frame, frame, days[1500])
    assert stock.index[-1] == days[1499] and index.index[-1] == days[1499]
    assert stock.index[0] == days[1500 - replay.HISTORY_DAYS] and len(stock) == replay.HISTORY_DAYS
    assert index.index[0] == days[1500 - replay.NIFTY_HISTORY_DAYS] and len(index) == replay.NIFTY_HISTORY_DAYS


def test_stock_offset_is_stable_and_spread():
    """The same ticker always gets the same offset; offsets cover the step."""
    assert replay.stock_offset("RELIANCE") == replay.stock_offset("RELIANCE")
    assert {replay.stock_offset(f"S{i}") for i in range(100)} == set(range(replay.STEP))


def test_baseline_buys_the_open_and_sells_the_horizon_close(monkeypatch):
    """Unconditional comparison: entry D open, exit the HORIZON-th close, NIFTY over the same days."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    bars = _path([(100, 101, 99, 100), (100, 101, 99, 101), (101, 103, 100, 102), (1, 1, 1, 1)])
    nifty = _path([(1000, 1000, 1000, 990), (1000, 1000, 1000, 1000), (1000, 1000, 1000, 1010), (1, 1, 1, 1)])
    base = replay.baseline(bars, 0, nifty)
    assert base["pass"] and base["gross_pct"] == pytest.approx(2) and base["nifty_pct"] == pytest.approx(1)
    assert replay.baseline(bars, 2, nifty) == {"pass": False, "category": "BaselineUnavailable"}


def test_replay_stock_counts_non_overlapping_buys_per_variant(monkeypatch):
    """A Buy blocks that variant's next Buys on the same stock until its exit; errors are counted."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    bars = _path([(100, 101, 99, 100)] * 30)

    def fake(ticker, key, history, price, nifty, variant, **_k):
        """incumbent always Buys; atr15 raises; the rest Watch."""
        if variant == "atr15-stop-v1":
            raise ValueError("bad day")
        action = "Buy" if variant == "incumbent-levels-v1" else "Watch"
        return {"pass": True, "score": 75.0, "stop": 95.0, "target": 110.0, "net_rr": 1.9, "atr": 2.0,
                "action": action}

    monkeypatch.setattr(replay, "decide", fake)
    monkeypatch.setattr(replay, "replay_days", lambda b, n, **k: [5, 6, 7, 8, 9])
    rows = replay.replay_stock("SYN", "K", bars, bars)
    mine = [r for r in rows if r["variant"] == "incumbent-levels-v1"]
    assert [r["counted_buy"] for r in mine] == [True, False, False, True, False]   # 3-session TIME exits
    assert all(r["category"] == "ReplayError:ValueError" for r in rows if r["variant"] == "atr15-stop-v1")
    report = replay.summarise(rows)
    assert report["variants"]["incumbent-levels-v1"]["buys"] == 2
    assert report["variants"]["atr15-stop-v1"]["errors"] == 5
    assert report["variants"]["capped25-atr4-v1"]["actions"]["Watch"] == 5
    assert report["baseline_excess_60bp"]["n"] == 5 and sum(r["variant"] == replay.BASELINE for r in rows) == 5


def _rows(variant, gross, nifty=0.0, buy=True, score=75.0, count=1, year=2024):
    """Summary input rows."""
    return [{"ticker": f"S{i}", "day": f"{year}-01-{i % 28 + 1:02d}", "variant": variant, "pass": True,
             "action": "Buy" if buy else "Watch", "counted_buy": buy, "score": score, "gross_pct": gross,
             "nifty_pct": nifty, "reason": "TIME"} for i in range(count)]


def test_summary_costs_excess_buckets_and_the_choice_rule():
    """Net = gross - cost; excess also minus NIFTY; winner = best 60 bp excess with >= 30 Buys, > 0 at 100 bp."""
    rows = (_rows("incumbent-levels-v1", 2.0, nifty=0.5, count=40) + _rows("atr15-stop-v1", 5.0, count=10)
            + _rows("capped25-atr4-v1", 1.6, count=40) + _rows("capped25-atr4-rr13-v1", 0.9, count=40, score=55))
    report = replay.summarise(rows)
    incumbent = report["variants"]["incumbent-levels-v1"]
    assert incumbent["buy_net_30bp"]["mean"] == pytest.approx(1.7)
    assert incumbent["buy_excess_60bp"]["mean"] == pytest.approx(0.9)
    assert incumbent["pass_excess_60bp_by_score"]["70-100"]["n"] == 40
    assert report["variants"]["capped25-atr4-rr13-v1"]["pass_excess_60bp_by_score"]["50-60"]["n"] == 40
    # atr15 has the best mean but only 10 Buys; rr13 is negative at 100 bp; capped25 1.0 beats incumbent 0.9.
    assert report["choice_rule_winner"] == "capped25-atr4-v1"
    assert report["variants"]["capped25-atr4-v1"]["buy_excess_60bp_minus_baseline"] is None   # no baseline rows
    with_base = replay.summarise(rows + _rows(replay.BASELINE, 0.8, count=5))
    assert with_base["variants"]["capped25-atr4-v1"]["buy_excess_60bp_minus_baseline"] == pytest.approx(0.8)
    assert replay.summarise(_rows("incumbent-levels-v1", 0.5, count=40))["choice_rule_winner"] is None
    assert replay.summarise(rows, complete=False)["choice_rule_winner"] is None      # partial run: no winner


def test_summary_counts_errors_rejects_and_years():
    """evaluate_stage2's own "Error" rejects count as errors; rejects by category; Buys by year."""
    rows = (_rows("incumbent-levels-v1", 1.0, count=2, year=2023) + _rows("incumbent-levels-v1", 2.0, count=3)
            + [{"ticker": "X", "day": "2024-02-01", "variant": "incumbent-levels-v1", "pass": False, "category": c}
               for c in ("Error", "Trend", "Trend", "ReplayError:ValueError")])
    entry = replay.summarise(rows)["variants"]["incumbent-levels-v1"]
    assert entry["errors"] == 2 and entry["rejects"] == {"Error": 1, "ReplayError:ValueError": 1, "Trend": 2}
    assert entry["buy_excess_60bp_by_year"]["2023"]["mean"] == pytest.approx(0.4)
    assert entry["buy_excess_60bp_by_year"]["2024"]["n"] == 3


def test_shard_problems_need_every_shard_of_one_version_and_one_list():
    """Complete = shards 0..n-1 once each, one version, one shard count, one universe and member list."""
    good = [(replay.VERSION, i, 3, "h", "nifty500") for i in range(3)]
    assert replay.shard_problems(good, shards=3) == []
    assert replay.shard_problems(good[:2], shards=3)
    assert replay.shard_problems(good + [good[0]], shards=3)
    assert replay.shard_problems([*good[:2], (replay.VERSION, 2, 3, "other", "nifty500")], shards=3)
    assert replay.shard_problems([*good[:2], ("old", 2, 3, "h", "nifty500")], shards=3)
    assert replay.shard_problems([*good[:2], (replay.VERSION, 2, 4, "h", "nifty500")], shards=3)
    assert replay.shard_problems([(replay.VERSION, 0, 1, "h", "nifty500")], shards=8)   # 1 shard is not the 8
    assert replay.shard_problems(good, shards=3, failed=2, stocks=98) == []        # 2% failed: still complete
    assert replay.shard_problems(good, shards=3, failed=3, stocks=97)              # 3%: incomplete


def test_shard_problems_accept_the_17_nov_v1_files_and_infer_the_universe_shard_count():
    """The seen run's v1 shards (8, nifty500) re-summarise as complete; mixed versions or universes do
    not; without --shards the universe sets the count (8 nifty500, 20 holdout)."""
    v1 = [("stage2-rule-replay-v1", i, 8, "h", "nifty500") for i in range(8)]
    assert replay.shard_problems(v1) == []
    assert replay.shard_problems([*v1[:7], (replay.VERSION, 7, 8, "h", "nifty500")])      # one run, one version
    assert replay.shard_problems([*v1[:7], ("stage2-rule-replay-v1", 7, 8, "h", "holdout")])
    held = [(replay.VERSION, i, 20, "g", "holdout") for i in range(20)]
    assert replay.shard_problems(held) == [] and replay.shard_problems(held[:19])
    assert replay.shard_problems([(replay.VERSION, i, 8, "g", "holdout") for i in range(8)])   # holdout is 20
    assert replay.shard_problems([(replay.VERSION, 0, 1, "g", "elsewhere")], shards=1)
    assert replay.shard_problems([], shards=8)                                     # nothing downloaded


def test_an_outcome_error_is_one_counted_row_not_a_lost_stock(monkeypatch):
    """A bad bar in the holding window (trade_outcome raises) is a ReplayError row for that day."""
    monkeypatch.setattr(replay, "decide", lambda *a, **k: {"pass": True, "score": 75.0, "stop": 95.0,
                                                          "target": 110.0, "net_rr": 2.0, "atr": 2.0,
                                                          "action": "Buy"})
    monkeypatch.setattr(replay, "replay_days", lambda b, n, **k: [0])

    def broken(*_a, **_k):
        """A zero price inside the window."""
        raise ValueError("Invalid OHLC in holding window")

    monkeypatch.setattr(replay, "outcome", broken)
    rows = replay.replay_stock("SYN", "K", _path([(100, 101, 99, 100)] * 30), _path([(100, 101, 99, 100)] * 30))
    assert {r["category"] for r in rows if r["variant"] in replay.VARIANTS} == {"ReplayError:ValueError"}


def test_stats_handles_empty_and_single_values():
    """No division by zero."""
    assert replay._stats([]) == {"n": 0}
    assert replay._stats([1.0])["t"] is None


def test_shards_are_disjoint_and_complete():
    """Every member lands in exactly one shard."""
    items = list(range(23))
    shards = [replay._shard(items, i, 4) for i in range(4)]
    assert sorted(x for s in shards for x in s) == items
    with pytest.raises(ValueError):
        replay._shard(items, 4, 4)


def test_daily_index_converts_aware_stamps_to_ist_dates():
    """A 03:45 UTC candle is that IST day; duplicates keep the last row."""
    frame = pd.DataFrame({"Close": [1.0, 2.0, 3.0]},
                         index=pd.DatetimeIndex(["2024-01-02 03:45", "2024-01-01 20:00", "2024-01-02 04:00"],
                                                tz="UTC"))
    out = replay.daily_index(frame)
    assert list(out.index) == [pd.Timestamp("2024-01-02")] and out["Close"].iloc[0] == 3.0


class _Response:
    def __init__(self, text):
        """A canned CSV body."""
        self.text = text

    def raise_for_status(self):
        """OK."""


class _Client:
    def __init__(self, text):
        """Returns `text` for every GET."""
        self.text, self.urls = text, []

    def get(self, url, **_k):
        """Record the URL."""
        self.urls.append(url)
        return _Response(self.text)


def test_nifty500_maps_isins_to_upstox_keys_and_refuses_a_short_list():
    """Symbol + ISIN -> NSE_EQ|ISIN; a list under 400 members is an error, not a replay."""
    header = "Company Name,Industry,Symbol,Series,ISIN Code\n"
    good = header + "".join(f"Co{i},X,SYM{i},EQ,INE{i:08d}0\n" for i in range(450))
    members = replay.nifty500(_Client(good))
    assert len(members) == 450 and members[0] == ("SYM0", "NSE_EQ|INE000000000")
    odd = good + "Co,X,BAD\n::stop-commands::,EQ,INE999999990\nCo,X,M&M,EQ,ine00000000x\n"
    assert len(replay.nifty500(_Client(odd))) == 450          # bad symbol / malformed ISIN dropped
    with pytest.raises(RuntimeError):
        replay.nifty500(_Client(header + "Co,X,SYM,EQ,INE000000001\n"))


def test_cli_run_needs_the_token_and_summarise_writes_the_report(tmp_path, monkeypatch):
    """`run` without a token exits 2; `summarise` merges shard files."""
    monkeypatch.delenv("UPSTOX_ANALYTICS_TOKEN", raising=False)
    assert replay.main(["run", "--shard", "0", "--shards", "1", "--out", str(tmp_path / "x.json")]) == 2
    shard = tmp_path / "s.json"
    shard.write_text(json.dumps({"version": replay.VERSION, "shard": 0, "shards": 1, "universe_sha256": "h",
                                 "rows": _rows("incumbent-levels-v1", 1.0, count=3), "failed": [{"symbol": "A"}]}))
    out = tmp_path / "report.json"
    assert replay.main(["summarise", str(shard), "--out", str(out), "--shards", "1"]) == 0
    report = json.loads(out.read_text())
    assert report["fetch_failures"] == 1 and report["variants"]["incumbent-levels-v1"]["buys"] == 3
    assert report["shards_present"] == [0] and report["problems"] == ["1 of 4 stocks failed (over 2%)"]
    assert not report["complete"]
    partial = tmp_path / "p.json"
    partial.write_text(json.dumps({"version": replay.VERSION, "shard": 0, "shards": 2, "universe_sha256": "h",
                                   "rows": [], "failed": []}))
    assert replay.main(["summarise", str(partial), "--out", str(out), "--shards", "2"]) == 0
    assert json.loads(out.read_text())["complete"] is False
    (tmp_path / "bad.json").write_text("[]")
    with pytest.raises(ValueError):
        replay.main(["summarise", str(tmp_path / "bad.json"), "--out", str(out)])


def test_run_shard_skips_failed_stocks_but_stops_on_a_rejected_token(tmp_path, monkeypatch):
    """A history failure is recorded; a 401 aborts the shard."""
    monkeypatch.setattr(replay, "nifty500", lambda c: [("A", "KA"), ("B", "KB")])
    monkeypatch.setattr(replay, "replay_stock", lambda *a, **k: [{"variant": "incumbent-levels-v1"}])

    def load(client, token, key, **_k):
        """KB fails; NIFTY and KA load."""
        if key == "KB":
            raise RuntimeError("HTTP 500")
        return _path([(1, 1, 1, 1)])

    monkeypatch.setattr(replay, "load_bars", load)
    counts = replay.run_shard(None, "t", shard=0, shards=1, out=tmp_path / "o.json",
                              today=dt.date(2026, 11, 17), days=100)
    assert counts == {"stocks": 2, "failed": 1, "rows": 1}
    written = json.loads((tmp_path / "o.json").read_text())
    assert written["failed"] == [{"symbol": "B", "error": "RuntimeError"}]
    assert written["universe_sha256"] == replay.universe_digest([("A", "KA"), ("B", "KB")])

    def replay_fails(symbol, *a, **k):
        """A replay error on A only."""
        if symbol == "A":
            raise ValueError("bad bar")
        return [{"variant": "incumbent-levels-v1"}]

    monkeypatch.setattr(replay, "load_bars", lambda *a, **k: _path([(1, 1, 1, 1)]))
    monkeypatch.setattr(replay, "replay_stock", replay_fails)
    assert replay.run_shard(None, "t", shard=0, shards=1, out=tmp_path / "o.json",
                            today=dt.date(2026, 11, 17), days=100) == {"stocks": 2, "failed": 1, "rows": 1}
    monkeypatch.setattr(replay, "replay_stock", lambda *a, **k: [{"variant": "incumbent-levels-v1"}])

    def rejected(client, token, key, **_k):
        """401 on a stock."""
        if key == "KA":
            raise PermissionError("401")
        return _path([(1, 1, 1, 1)])

    monkeypatch.setattr(replay, "load_bars", rejected)
    with pytest.raises(PermissionError):
        replay.run_shard(None, "t", shard=0, shards=1, out=tmp_path / "o.json", today=dt.date(2026, 11, 17), days=100)


def test_load_bars_fetches_like_the_app_and_returns_naive_session_dates(monkeypatch):
    """fetch_daily_candles' frame (IST-aware) becomes one naive row per date, oldest first."""
    seen = []

    def fetch(client, token, key, days, *, today):
        """Two candles, newest first, aware."""
        seen.append((key, days, today))
        return pd.DataFrame({"Close": [2.0, 1.0]},
                            index=pd.DatetimeIndex(["2024-01-03", "2024-01-02"]).tz_localize("Asia/Kolkata"))

    monkeypatch.setattr(replay, "fetch_daily_candles", fetch)
    frame = replay.load_bars(None, "t", "K", today=dt.date(2026, 11, 17), days=1600, pause=0)
    assert seen == [("K", 1600, dt.date(2026, 11, 17))]
    assert list(frame.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")] and frame.index.tz is None


# ------------------------------------------------- v2: holdout universe, gaps, width test ---

def test_holdout_is_the_live_universe_minus_the_nifty_500_sorted(monkeypatch):
    """Live NSE EQ universe (fetch_nse_universe) minus NIFTY 500 instrument keys; sorted; < 1000 refused."""
    live = [{"trading_symbol": f"S{i:04d}", "instrument_key": f"NSE_EQ|K{i:04d}"} for i in range(1200, 0, -1)]
    monkeypatch.setattr(replay, "fetch_nse_universe", lambda client: live)
    monkeypatch.setattr(replay, "nifty500", lambda client: [("X", f"NSE_EQ|K{i:04d}") for i in range(1, 101)])
    members = replay.holdout(None)
    assert len(members) == 1100 and members == sorted(members) and members[0] == ("S0101", "NSE_EQ|K0101")
    assert not {key for _s, key in members} & {f"NSE_EQ|K{i:04d}" for i in range(1, 101)}
    monkeypatch.setattr(replay, "nifty500", lambda client: [("X", f"NSE_EQ|K{i:04d}") for i in range(1, 300)])
    with pytest.raises(RuntimeError):
        replay.holdout(None)                                           # 901 left: not the live universe


def test_run_shard_records_the_universe_it_replayed(tmp_path, monkeypatch):
    """`holdout` loads the holdout list; the shard header names the universe and digests its list."""
    monkeypatch.setattr(replay, "holdout", lambda c: [("H", "KH")])
    monkeypatch.setattr(replay, "nifty500", lambda c: pytest.fail("the NIFTY 500 list is not the holdout"))
    monkeypatch.setattr(replay, "load_bars", lambda *a, **k: _path([(1, 1, 1, 1)]))
    monkeypatch.setattr(replay, "replay_stock", lambda *a, **k: [{"variant": "incumbent-levels-v1"}])
    replay.run_shard(None, "t", shard=0, shards=1, out=tmp_path / "h.json", today=dt.date(2026, 11, 23),
                     days=100, universe_name="holdout")
    written = json.loads((tmp_path / "h.json").read_text())
    assert written["universe"] == "holdout" and written["version"] == replay.VERSION
    assert written["universe_sha256"] == replay.universe_digest([("H", "KH")])


def test_load_bars_retries_transient_failures_but_never_a_rejected_token(monkeypatch):
    """Two failures then data: loaded; three failures: the last error; a 401: raised at once."""
    calls = []

    def flaky(failures, error):
        """Fail `failures` times with `error`, then return one candle."""
        def fetch(client, token, key, days, *, today):
            """Count the call."""
            calls.append(key)
            if len(calls) <= failures:
                raise error
            return pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2024-01-02"]))
        return fetch

    monkeypatch.setattr(replay, "fetch_daily_candles", flaky(2, RuntimeError("HTTP 500")))
    assert len(replay.load_bars(None, "t", "K", today=dt.date(2026, 11, 23), days=10, pause=0)) == 1
    assert len(calls) == 3
    calls.clear()
    monkeypatch.setattr(replay, "fetch_daily_candles", flaky(3, RuntimeError("HTTP 503")))
    with pytest.raises(RuntimeError, match="503"):
        replay.load_bars(None, "t", "K", today=dt.date(2026, 11, 23), days=10, pause=0)
    assert len(calls) == replay.FETCH_ATTEMPTS == 3
    calls.clear()
    monkeypatch.setattr(replay, "fetch_daily_candles", flaky(5, PermissionError("401")))
    with pytest.raises(PermissionError):
        replay.load_bars(None, "t", "K", today=dt.date(2026, 11, 23), days=10, pause=0)
    assert len(calls) == 1


def test_a_missing_stock_session_shortens_the_hold_instead_of_stretching_it(monkeypatch):
    """HORIZON 3 NIFTY sessions from D: a stock gap on session 2 leaves 2 bars, exit at session 3's
    close (not session 4's), gap_sessions 1; the baseline sells the same close."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    nifty = _path([(1000, 1000, 1000, 1000), (1000, 1000, 1000, 1010), (1000, 1000, 1000, 1020),
                   (1000, 1000, 1000, 1030)])
    bars = _path([(100, 101, 99, 100), (100, 101, 99, 101), (101, 102, 100, 104), (104, 105, 103, 120)])
    bars = bars.drop(bars.index[1])                                    # suspended on session 2
    window, gaps = replay.holding_window(bars, 0, nifty)
    assert list(window.index) == [nifty.index[0], nifty.index[2]] and gaps == 1
    timed = replay.outcome(bars, 0, 95, 130, nifty)
    assert timed["reason"] == "TIME" and timed["gross_pct"] == pytest.approx(4) and timed["gap_sessions"] == 1
    assert timed["exit_day"] == str(nifty.index[2].date()) and timed["nifty_pct"] == pytest.approx(2)
    base = replay.baseline(bars, 0, nifty)
    assert base["gross_pct"] == pytest.approx(4) and base["gap_sessions"] == 1
    whole = replay.outcome(_path([(100, 101, 99, 100)] * 4), 0, 95, 130, nifty)
    assert whole["gap_sessions"] == 0 and whole["sessions"] == 3   # no gap: the v1 window


def test_no_holding_window_when_the_data_ends_before_the_last_session(monkeypatch):
    """Stock data ending before the HORIZON-th NIFTY session (or a start past the end) is no outcome."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    nifty = _path([(1000, 1000, 1000, 1000)] * 5)
    short = _path([(100, 101, 99, 100)] * 2)
    assert replay.holding_window(short, 0, nifty) == (None, 0)
    assert replay.outcome(short, 0, 95, 110, nifty) is None
    assert replay.baseline(short, 0, nifty) == {"pass": False, "category": "BaselineUnavailable"}
    assert replay.holding_window(short, 5, nifty) == (None, 0) and replay.holding_window(short, -1, nifty) == (None, 0)


def test_replay_rows_carry_the_entry_exit_day_and_gaps(monkeypatch):
    """A pass row stores D's open as entry and the outcome's exit day and gap count."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    monkeypatch.setattr(replay, "decide", lambda *a, **k: {"pass": True, "score": 72.0, "stop": 70.0,
                                                          "target": 140.0, "net_rr": 1.3, "atr": 2.0,
                                                          "action": "Watch"})
    monkeypatch.setattr(replay, "replay_days", lambda b, n, **k: [0])
    bars = _path([(100, 101, 99, 100)] * 10)
    rows = replay.replay_stock("SYN", "K", bars, bars, variants=("incumbent-levels-v1",))
    row = next(r for r in rows if r["variant"] == "incumbent-levels-v1")
    assert row["entry"] == 100.0 and row["exit_day"] == "2024-01-03" and row["gap_sessions"] == 0
    assert "exit_index" not in row


def _wrow(day, gross, *, score=72.0, action="Watch", ticker=None, entry=100.0, stop=70.0, target=142.0,
          reason="TIME", nifty=0.0, variant="incumbent-levels-v1", exit_day=None, gaps=0):
    """One width-test row (entry 100, stop 30% below: width-blocked by default)."""
    row = {"ticker": ticker or f"T{day}{gross}", "day": day, "variant": variant, "pass": True,
           "score": score, "action": action, "stop": stop, "target": target, "atr": 2.0,
           "gross_pct": gross, "nifty_pct": nifty, "reason": reason, "gap_sessions": gaps,
           "exit_day": exit_day or day, "traded_value_20d": 1e7}
    if entry is not None:
        row["entry"] = entry
    return row


def _width_run(months=30, shift=0.0, buys=40, losses=None):
    """A70 rows (6 a month from Jan 2022), Buys and baseline rows for a decisive width test."""
    rows, pattern = [], [4.0, 3.0, 5.0, -1.0, 2.0, 6.0]
    for i in range(months):
        day = f"{2022 + i // 12}-{i % 12 + 1:02d}-10"
        rows += [_wrow(day, g + shift, ticker=f"A{i}-{j}") for j, g in enumerate(pattern)]
        rows.append({"ticker": f"Z{i}", "day": day, "variant": replay.BASELINE, "pass": True,
                     "gross_pct": 0.0, "nifty_pct": 0.0, "reason": "TIME"})
    rows += [_wrow("2022-03-10", 1.0, action="Buy", score=75.0, stop=90.0, target=110.0, ticker=f"B{k}")
             for k in range(buys)]
    rows += [_wrow("2022-04-10", loss, ticker=f"L{k}", reason="STOP") for k, loss in enumerate(losses or [])]
    return rows


def test_width_blocked_rechecks_the_live_gate_from_the_stored_entry():
    """30% stop: blocked; 10% stop and 8 ATR target: blocked; 10% stop, 5 ATR target: not; v1 row: None."""
    assert replay.width_blocked(_wrow("2024-01-10", 1.0)) is True
    assert replay.width_blocked(_wrow("2024-01-10", 1.0, stop=90.0, target=116.0)) is True   # 8 ATR > 7.75
    assert replay.width_blocked(_wrow("2024-01-10", 1.0, stop=90.0, target=110.0)) is False
    assert replay.width_blocked(_wrow("2024-01-10", 1.0, entry=None)) is None


def test_width_groups_a70_a65_buys_and_baseline():
    """A70 = score >= 70 and Watch (v1 rows trusted, v2 rows re-checked); A65 needs a v2 width block."""
    rows = [_wrow("2024-01-10", 1.0), _wrow("2024-01-10", 1.0, entry=None),
            _wrow("2024-01-10", 1.0, score=69.9), _wrow("2024-01-10", 1.0, score=66.0, stop=90.0, target=110.0),
            _wrow("2024-01-10", 1.0, score=66.0, entry=None), _wrow("2024-01-10", 1.0, score=64.9),
            _wrow("2024-01-10", 1.0, action="Buy", stop=90.0, target=110.0),
            _wrow("2024-01-10", 1.0, action="Unavailable"), _wrow("2024-01-10", 1.0, variant="atr15-stop-v1"),
            {**_wrow("2024-01-10", 1.0), "pass": False}]
    groups = replay.width_groups(rows)
    assert len(groups["a70"]) == 2 and [r["score"] for r in groups["a65"]] == [69.9]
    assert len(groups["b"]) == 1 and groups["baseline"] == []


def test_calendar_months_include_empty_months_across_years():
    """From the first day's month to the last day's month."""
    assert replay.calendar_months("2021-11-15", "2022-02-01") == ["2021-11", "2021-12", "2022-01", "2022-02"]
    assert replay.calendar_months("2024-05-31", "2024-05-01") == ["2024-05"]      # same month
    assert replay.calendar_months("2024-06-01", "2024-05-01") == []


def test_block_interval_is_seeded_and_brackets_the_pooled_mean():
    """Constant excess: the interval is that value; mixed months: low < mean < high, same on rerun."""
    months = replay.calendar_months("2022-01-01", "2023-12-31")
    flat = [_wrow(f"{m}-10", 2.6) for m in months]
    assert replay.block_interval(flat, months, 3, draws=200) == {"low": pytest.approx(2.0), "high": pytest.approx(2.0),
                                                                  "draws": 200}
    mixed = [_wrow(f"{m}-10", 6.0 if i % 2 else -2.0) for i, m in enumerate(months)]
    first = replay.block_interval(mixed, months, 1, draws=500)
    assert first == replay.block_interval(mixed, months, 1, draws=500)
    assert first["low"] < 1.4 < first["high"]
    assert replay.block_interval([], months, 1) is None and replay.block_interval(flat, [], 1) is None


def test_width_test_passes_only_when_every_preregistered_check_holds():
    """A70 +2.57% at 60 bp in every month for 30 months, 3 positive years, tails like the Buys: PASS."""
    report = replay.width_test(_width_run(), complete=True, universe="holdout")
    assert report["verdict"] == "PASS" and report["decisive"] and report["blockers"] == []
    assert all(report["checks"].values()) and report["size"] == {"passes": 180, "months": 30, "buys": 40, "no_outcome": 0}
    assert report["a70_excess_60bp"]["mean"] == pytest.approx(2.567, abs=1e-3)
    assert report["a70_widest_low"] > 0 and set(report["a70_interval_90"]) == {"1m", "3m", "6m"}
    assert report["best_year"] in {"2022", "2023", "2024"} and report["a70_gap_trades"] == 0
    assert report["a70_split"]["stop_wide_60bp"]["n"] == 180 and report["a65_excess_60bp"] == {"n": 0}


@pytest.mark.parametrize("kwargs,failed", [
    ({"shift": -2.2}, "a_mean_60bp_at_least_1pct"),                # mean +0.37%
    ({"losses": [-60.0] * 40}, "e_worst_decile"),                   # 40 stop-outs at -60%
    ({"losses": [-0.5] * 60}, "e_stop_share"),                     # 25% stop exits vs 0% for Buys
])
def test_width_test_fails_on_any_failed_check(kwargs, failed):
    """One failed check is a FAIL (not NO_DECISION)."""
    report = replay.width_test(_width_run(**kwargs), complete=True, universe="holdout")
    assert report["verdict"] == "FAIL" and not report["checks"][failed]


def test_width_test_year_checks_catch_one_good_year():
    """Gains only in 2022 (losses in 2023-24): fewer than 3 positive years -> FAIL."""
    rows = [r if r["day"] < "2023" or r["variant"] != "incumbent-levels-v1" or r["action"] != "Watch"
            else {**r, "gross_pct": -1.0} for r in _width_run()]
    report = replay.width_test(rows, complete=True, universe="holdout")
    assert report["verdict"] == "FAIL" and not report["checks"]["d_positive_years"]


@pytest.mark.parametrize("kwargs,complete,blocker", [
    ({"months": 20}, True, "A70 in under 24 months"),
    ({"months": 24, "buys": 29}, True, "under 30 Buys: the tail check cannot be made"),
    ({}, False, "run incomplete"),
])
def test_width_test_has_no_decision_below_the_floors(kwargs, complete, blocker):
    """Too few months / Buys or an incomplete run: NO_DECISION whatever the numbers."""
    report = replay.width_test(_width_run(**kwargs), complete=complete, universe="holdout")
    assert report["verdict"] == "NO_DECISION" and blocker in report["blockers"]


def test_width_test_on_seen_data_is_context_only_and_handles_v1_rows():
    """The NIFTY 500 run never decides; v1 rows (no entry / exit day) give A70 but no split or overlap cut."""
    rows = [{k: v for k, v in r.items() if k not in ("entry", "exit_day", "gap_sessions")} for r in _width_run()]
    report = replay.width_test(rows, complete=True, universe="nifty500")
    assert report["verdict"] == "CONTEXT_ONLY (nifty500 recent run, not decisive; would be PASS)" and not report["decisive"]
    assert report["a70_split"] is None and report["a70_non_overlapping_60bp"] is None
    assert report["a65_excess_60bp"] is None and report["size"]["passes"] == 180
    assert replay.width_test([], complete=True, universe="holdout")["verdict"] == "NO_DECISION"
    v1 = replay.width_test([{k: v for k, v in r.items() if k != "traded_value_20d"} for r in rows],
                           complete=True, universe="nifty500")              # real v1 rows: no traded value
    assert v1["verdict"].endswith("would be FAIL)") and v1["notes"][0].startswith("check g not computable")


def test_non_overlapping_keeps_a_stocks_next_pass_only_after_its_exit():
    """Per ticker: a pass inside the previous kept trade is skipped."""
    rows = [_wrow("2024-01-01", 1.0, ticker="A", exit_day="2024-01-20"),
            _wrow("2024-01-08", 1.0, ticker="A", exit_day="2024-01-28"),
            _wrow("2024-01-22", 1.0, ticker="A", exit_day="2024-02-10"),
            _wrow("2024-01-08", 1.0, ticker="B", exit_day="2024-01-28")]
    assert [(r["ticker"], r["day"]) for r in replay.non_overlapping(rows)] == [
        ("A", "2024-01-01"), ("A", "2024-01-22"), ("B", "2024-01-08")]
    assert replay.non_overlapping([{k: v for k, v in rows[0].items() if k != "exit_day"}]) is None


def test_summarise_cli_reads_the_universe_from_the_shard_header(tmp_path):
    """A holdout shard set (20 files) is complete without --shards; the report carries the width test."""
    rows = _width_run(months=2, buys=1)
    for shard in range(20):
        (tmp_path / f"s{shard}.json").write_text(json.dumps({
            "version": replay.VERSION, "shard": shard, "shards": 20, "universe": "holdout",
            "universe_sha256": "g", "rows": rows if shard == 0 else [], "failed": []}))
    out = tmp_path / "report.json"
    assert replay.main(["summarise", *map(str, sorted(tmp_path.glob("s*.json"))), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["complete"] and report["universe"] == "holdout" and report["problems"] == []
    assert report["width_test"]["verdict"] == "NO_DECISION" and report["width_test"]["decisive"]


def test_width_group_boundaries_70_and_65_are_inclusive():
    """Score 70.0 is A70 (not A65); 65.0 is A65; invalid levels are not width-blocked."""
    rows = [_wrow("2024-01-10", 1.0, score=70.0), _wrow("2024-01-10", 1.0, score=65.0)]
    groups = replay.width_groups(rows)
    assert [r["score"] for r in groups["a70"]] == [70.0] and [r["score"] for r in groups["a65"]] == [65.0]
    assert replay.width_blocked(_wrow("2024-01-10", 1.0, stop=101.0)) is False      # Unavailable, not Watch


def test_holding_window_edges(monkeypatch):
    """D must be a NIFTY session; data ending exactly on the last session is a full window; a negative
    start is no window (even when one bar would do)."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    nifty = _path([(1000, 1000, 1000, 1000)] * 5)
    exact = _path([(100, 101, 99, 100)] * 3)
    window, gaps = replay.holding_window(exact, 0, nifty)
    assert len(window) == 3 and gaps == 0
    assert replay.holding_window(_path([(100, 101, 99, 100)] * 5), 0, nifty.iloc[1:]) == (None, 0)   # D not a session
    monkeypatch.setattr(replay, "HORIZON", 1)
    assert replay.holding_window(exact, -1, nifty) == (None, 0)


def test_block_interval_quantiles_are_the_5th_and_95th_percentiles():
    """24 months alternating +6 / -2, one trade each, 1-month blocks: the pooled mean is k/3 - 2 with
    k ~ Binomial(24, 1/2), so the 5% / 95% points are k = 8 / 16 -> 0.667 / 3.333."""
    months = replay.calendar_months("2022-01-01", "2023-12-31")
    rows = [_wrow(f"{m}-10", (6.0 if i % 2 else -2.0) + 0.6) for i, m in enumerate(months)]
    assert replay.block_interval(rows, months, 1) == {"low": pytest.approx(2 / 3), "high": pytest.approx(10 / 3),
                                                       "draws": 10_000}


def test_a_whole_period_block_resamples_every_month_once():
    """block = all months: every draw is the full set (a rotation), so low = high = the pooled mean."""
    months = replay.calendar_months("2022-01-01", "2022-12-31")
    rows = [_wrow(f"{m}-10", float(i) + 0.6) for i, m in enumerate(months)]
    assert replay.block_interval(rows, months, len(months), draws=50) == {"low": pytest.approx(5.5),
                                                                          "high": pytest.approx(5.5), "draws": 50}


def test_worst_decile_and_stop_count():
    """Lowest tenth (rounded up, at least one value); every stop reason counts as a stop exit."""
    assert replay._worst_decile([float(v) for v in range(20, 0, -1)]) == 1.5
    assert replay._worst_decile([3.0, 1.0, 2.0]) == 1.0 and replay._worst_decile([]) is None
    rows = [{"reason": r} for r in ("STOP", "GAP_STOP", "BOTH_STOP", "TARGET", "TIME")]
    assert replay._stop_count(rows) == (3, 5) and replay._stop_count([]) == (0, 0)


def _gates(**changes):
    """Unrounded gate inputs that pass every check; `changes` override single entries."""
    good = {"mean_60": 1.5, "mean_100": 1.1, "median_60": 0.4, "baseline_mean_60": 0.2,
            "interval_lows": {"1m": 0.3, "3m": 0.2, "6m": 0.1},
            "year_means": {y: 1.0 for y in ("2022", "2023", "2024")}, "best_year": "2022",
            "without_best_year_mean": 0.8, "worst_decile": {"a70": -14.0, "b": -10.0},
            "stop_exits": {"a70": (25, 100), "b": (20, 100)}, "liquid_tercile_mean_60": 0.5}
    return {**good, **changes}


@pytest.mark.parametrize("check,changes", [
    ("a_mean_60bp_at_least_1pct", {"mean_60": 0.99955}),            # shows as 1.0 rounded; the gate is raw
    ("a_mean_100bp_above_0", {"mean_100": 0.0}),
    ("a_widest_interval_above_0", {"interval_lows": {"1m": 0.3, "3m": -0.01, "6m": 0.1}}),   # the LOWEST low decides
    ("a_widest_interval_above_0", {"interval_lows": {"1m": None, "3m": 0.2, "6m": 0.1}}),
    ("b_median_above_0", {"median_60": 0.0}),
    ("c_above_baseline", {"baseline_mean_60": 1.5}),
    ("c_above_baseline", {"baseline_mean_60": None}),
    ("d_positive_years", {"year_means": {"2022": 2.0, "2023": 2.0, "2024": 0.0, "2021": 5.0}}),
    ("d_without_best_year_above_0", {"without_best_year_mean": -0.1}),
    ("e_worst_decile", {"worst_decile": {"a70": -15.0001, "b": -10.0}}),
    ("e_worst_decile", {"worst_decile": {"a70": -1.0, "b": None}}),
    ("e_stop_share", {"stop_exits": {"a70": (301, 1000), "b": (20, 100)}}),
    ("e_stop_share", {"stop_exits": {"a70": (0, 0), "b": (20, 100)}}),
    ("g_liquid_tercile_above_0", {"liquid_tercile_mean_60": 0.0}),
    ("g_liquid_tercile_above_0", {"liquid_tercile_mean_60": None}),
])
def test_each_preregistered_check_fails_alone(check, changes):
    """Every check is a real gate: breaking only its input fails only that check (boundaries included)."""
    assert all(replay._width_checks(_gates()).values())
    checks = replay._width_checks(_gates(**changes))
    assert not checks[check] and sum(not v for v in checks.values()) == 1


def test_check_boundaries_pass_exactly_at_the_preregistered_values():
    """mean = +1.0%, worst decile = B - 5 pts, stop share = B + 10 pts pass; 0.7 + 0.1 is not 0.7999..."""
    checks = replay._width_checks(_gates(mean_60=1.0, worst_decile={"a70": -15.0, "b": -10.0},
                                         stop_exits={"a70": (8, 10), "b": (7, 10)}))
    assert all(checks.values())


def test_blockers_name_every_floor():
    """149 passes, 23 months, 29 Buys, incomplete: four blockers; 150 / 24 / 30 / complete: none."""
    ok = {"passes": 150, "months": 24, "buys": 30, "no_outcome": 0}
    assert replay._width_blockers(ok, True) == []
    assert len(replay._width_blockers({"passes": 149, "months": 23, "buys": 29, "no_outcome": 9}, False)) == 5
    assert replay._width_blockers({**ok, "passes": 149}, True) == ["A70 under 150 passes"]


def test_best_year_is_the_highest_mean_and_2021_joins_2022():
    """December 2021 rows (the recent runs start 14 Dec 2021) count as 2022; the best year is removed for
    check d. Out-of-time days (to Nov 2021) keep their own year."""
    groups = {"a70": [_wrow("2021-12-20", 9.6), _wrow("2022-02-10", 1.6), _wrow("2023-02-10", -0.4)],
              "b": [], "baseline": []}
    gate = replay._gate_inputs(groups, {"1m": None})
    assert set(gate["year_means"]) == {"2022", "2023"} and gate["year_means"]["2022"] == pytest.approx(5.0)
    assert gate["best_year"] == "2022" and gate["without_best_year_mean"] == pytest.approx(-1.0)
    assert [replay._year(d) for d in ("2021-11-30", "2021-12-01", "2015-03-25")] == ["2021", "2022", "2015"]


def test_a_pass_on_the_previous_exit_day_overlaps():
    """Entering at the open of the day the previous trade exits at the close is an overlap."""
    rows = [_wrow("2024-01-01", 1.0, ticker="A", exit_day="2024-01-20"),
            _wrow("2024-01-20", 1.0, ticker="A", exit_day="2024-02-08")]
    assert [r["day"] for r in replay.non_overlapping(rows)] == ["2024-01-01"]


def test_summarise_cli_reads_v1_shards_without_a_universe_field_as_the_nifty_500(tmp_path):
    """The 17 Nov files (v1, 8 shards, no `universe`): complete, nifty500, width test context only."""
    for shard in range(8):
        (tmp_path / f"v{shard}.json").write_text(json.dumps({
            "version": "stage2-rule-replay-v1", "shard": shard, "shards": 8, "universe_sha256": "h",
            "rows": _rows("incumbent-levels-v1", 1.0, count=2) if shard == 0 else [], "failed": []}))
    out = tmp_path / "report.json"
    assert replay.main(["summarise", *map(str, sorted(tmp_path.glob("v*.json"))), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["complete"] and report["universe"] == "nifty500" and not report["width_test"]["decisive"]


def test_a_rate_limit_waits_minutes_not_seconds(monkeypatch):
    """HTTP 429: rate_wait x attempt (the provider's window is 30 min); other errors: 8 x pause x attempt."""
    waits = []
    monkeypatch.setattr(replay.time, "sleep", waits.append)

    def failing_then_ok(errors):
        """Raise each of `errors` once, then return one candle."""
        pending = list(errors)

        def fetch(client, token, key, days, *, today):
            """The next error, else data."""
            if pending:
                raise pending.pop(0)
            return pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2024-01-02"]))
        return fetch

    for errors, expected in (([RuntimeError("Historical candle API returned HTTP 429")] * 2, [60.0, 120.0, 0.25]),
                             ([TimeoutError("read timed out")], [2.0, 0.25])):
        waits.clear()
        monkeypatch.setattr(replay, "fetch_daily_candles", failing_then_ok(errors))
        replay.load_bars(None, "t", "K", today=dt.date(2026, 11, 23), days=10, pause=0.25, rate_wait=60.0)
        assert waits == expected


def test_a70_leaves_out_a_watch_row_whose_stored_levels_fit_the_gate():
    """A v2 row at score >= 70 marked Watch but inside the gate (inconsistent) is not A70."""
    rows = [_wrow("2024-01-10", 1.0, score=75.0, stop=90.0, target=110.0), _wrow("2024-01-10", 1.0, score=75.0)]
    assert [r["stop"] for r in replay.width_groups(rows)["a70"]] == [70.0]


def test_the_lowest_interval_low_decides(monkeypatch):
    """1m / 3m above 0 but 6m below: the widest reading fails check a; the report shows the lowest low."""
    lows = {1: 0.4, 3: 0.2, 6: -0.05}
    monkeypatch.setattr(replay, "block_interval",
                        lambda rows, months, block, **k: {"low": lows[block], "high": 5.0, "draws": 10})
    report = replay.width_test(_width_run(), complete=True, universe="holdout")
    assert report["a70_widest_low"] == -0.05 and not report["checks"]["a_widest_interval_above_0"]
    assert report["verdict"] == "FAIL" and report["gate_inputs"]["interval_lows"] == {"1m": 0.4, "3m": 0.2, "6m": -0.05}


def test_an_incomplete_run_shows_only_its_blockers():
    """No checks, numbers or intervals from an incomplete run (a repeat must stay blind)."""
    report = replay.width_test(_width_run(), complete=False, universe="holdout")
    assert set(report) == {"universe", "period", "decisive", "blockers", "size", "verdict"}
    assert report["verdict"] == "NO_DECISION" and report["blockers"] == ["run incomplete"]
    seen = replay.width_test(_width_run(), complete=False, universe="nifty500")
    assert seen["verdict"] == "CONTEXT_ONLY (run incomplete)" and "checks" not in seen


def test_holdout_also_removes_nifty_500_symbols_under_a_new_isin(monkeypatch):
    """A NIFTY 500 stock whose ISIN changed (split) is removed by symbol; given lists are not refetched."""
    live = [{"trading_symbol": f"S{i:04d}", "instrument_key": f"NSE_EQ|K{i:04d}"} for i in range(1, 1102)]
    monkeypatch.setattr(replay, "fetch_nse_universe", lambda client: live)
    monkeypatch.setattr(replay, "nifty500", lambda client: pytest.fail("the given NIFTY 500 list is reused"))
    members = replay.holdout(None, [("S0001", "NSE_EQ|OLDISIN"), ("X", "NSE_EQ|K0002")])
    assert len(members) == 1099 and ("S0001", "NSE_EQ|K0001") not in members and ("S0002", "NSE_EQ|K0002") not in members


def test_resolve_members_records_the_list_digest_and_the_removed_nifty_500(monkeypatch, tmp_path):
    """One list per run: digest, the NIFTY 500 digest it was built against, the universe's shard count;
    read_members round-trips it and refuses a tampered list."""
    nifty = [("A", "NSE_EQ|KA"), ("B", "NSE_EQ|KB")]
    monkeypatch.setattr(replay, "nifty500", lambda client: nifty)
    monkeypatch.setattr(replay, "holdout", lambda client, given: [("H", "NSE_EQ|KH")] if given == nifty else [])
    monkeypatch.setattr(replay, "load_bars", lambda client, token, key, **k: _path([(1, 1, 1, 1)] * 3)
                        if key == replay.NIFTY_KEY and token == "t" else pytest.fail("only NIFTY, with the token"))
    held = replay.resolve_members(None, "holdout", "t")
    assert held.pop("as_of") == "2024-01-03" and held == {
        "universe": "holdout", "members": [["H", "NSE_EQ|KH"]], "shards": 20,
        "sha256": replay.universe_digest([("H", "NSE_EQ|KH")]), "nifty500_sha256": replay.universe_digest(nifty)}
    seen = replay.resolve_members(None, "nifty500", "t")
    assert seen["shards"] == 8 and seen["sha256"] == seen["nifty500_sha256"]
    path = tmp_path / "members.json"
    path.write_text(json.dumps(held))   # (as_of popped above: absent -> None)
    assert replay.read_members(path) == {"universe": "holdout", "members": [("H", "NSE_EQ|KH")],
                                         "nifty500_sha256": replay.universe_digest(nifty), "as_of": None}
    path.write_text(json.dumps({**held, "members": [["H", "NSE_EQ|KH"], ["X", "NSE_EQ|KX"]]}))
    with pytest.raises(ValueError):
        replay.read_members(path)
    path.write_text(json.dumps({**held, "universe": "elsewhere"}))
    with pytest.raises(ValueError):
        replay.read_members(path)


def test_run_shard_reads_the_members_file_and_records_the_universe_size(tmp_path, monkeypatch):
    """With a members file no shard fetches a list; the header carries the whole list's size."""
    members = [("A", "KA"), ("B", "KB"), ("C", "KC")]
    path = tmp_path / "members.json"
    path.write_text(json.dumps({"universe": "holdout", "members": [list(m) for m in members],
                                "sha256": replay.universe_digest(members)}))
    monkeypatch.setattr(replay, "nifty500", lambda c: pytest.fail("no list fetch in a shard"))
    monkeypatch.setattr(replay, "holdout", lambda c: pytest.fail("no list fetch in a shard"))
    monkeypatch.setattr(replay, "load_bars", lambda *a, **k: _path([(1, 1, 1, 1)]))
    monkeypatch.setattr(replay, "replay_stock", lambda symbol, *a, **k: [{"ticker": symbol}])
    counts = replay.run_shard(None, "t", shard=1, shards=2, out=tmp_path / "s.json", today=dt.date(2026, 11, 23),
                              days=10, members_file=path)
    written = json.loads((tmp_path / "s.json").read_text())
    assert counts == {"stocks": 1, "failed": 0, "rows": 1} and written["rows"] == [{"ticker": "B"}]
    assert written["universe"] == "holdout" and written["universe_size"] == 3
    assert written["universe_sha256"] == replay.universe_digest(members) and written["as_of"] == "2026-11-23"
    assert written["nifty500_sha256"] is None


def _holdout_shards(tmp_path, *, size, failed, sizes=None):
    """20 holdout shard files: one ticker with rows, `failed` failed stocks, header universe_size."""
    for shard in range(20):
        (tmp_path / f"h{shard}.json").write_text(json.dumps({
            "version": replay.VERSION, "shard": shard, "shards": 20, "universe": "holdout", "universe_sha256": "g",
            "universe_size": (sizes or {}).get(shard, size), "rows": _rows("incumbent-levels-v1", 1.0, count=2)
            if shard == 0 else [], "failed": [{"symbol": f"F{k}", "error": "X"} for k in range(failed)]
            if shard == 1 else []}))
    return sorted(map(str, tmp_path.glob("h*.json")))


@pytest.mark.parametrize("failed,sizes,complete", [(2, None, True), (3, None, False), (0, {5: 99}, False)])
def test_the_failure_rule_counts_against_the_whole_member_list(tmp_path, failed, sizes, complete):
    """100 members, most with no rows: 2 failed is 2% (complete), 3 is not; shards that disagree on the
    size are incomplete. (The v1 rule would have counted 2 of 3 = 67%.)"""
    out = tmp_path / "report.json"
    files = _holdout_shards(tmp_path, size=100, failed=failed, sizes=sizes)
    assert replay.main(["summarise", *files, "--out", str(out), "--source-run", "123"]) == 0
    report = json.loads(out.read_text())
    assert report["complete"] is complete and report["source_run"] == "123" and report["universe_sha256"] == ["g"]
    assert report["universe_size"] == (100 if sizes is None else None)


def test_members_cli_writes_the_list_and_the_workflow_matrix(tmp_path, monkeypatch):
    """`members --github-output`: the list file plus shards=N and matrix=[0..N-1] for the workflow."""
    monkeypatch.setattr(replay, "resolve_members", lambda client, name, token, end=None: {
        "universe": name, "members": [["H", "K"]], "sha256": "d", "nifty500_sha256": "n", "shards": 20,
        "as_of": "2026-11-20"})
    out, gh = tmp_path / "m.json", tmp_path / "gh.txt"
    monkeypatch.delenv("UPSTOX_ANALYTICS_TOKEN", raising=False)
    assert replay.main(["members", "--universe", "holdout", "--out", str(out)]) == 2    # needs the token (NIFTY end)
    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", "t")
    gh.write_text("earlier=1\n")
    assert replay.main(["members", "--universe", "holdout", "--out", str(out), "--github-output", str(gh)]) == 0
    assert json.loads(out.read_text())["members"] == [["H", "K"]]
    assert gh.read_text() == f"earlier=1\nshards=20\nmatrix={json.dumps(list(range(20)))}\ndays=3000\n"


def test_the_failure_share_divides_by_the_member_list_not_members_plus_failures(tmp_path):
    """2,450 members, 50 failed = 2.04% (over 2%): incomplete, though 50 / 2,500 would be exactly 2%."""
    out = tmp_path / "report.json"
    assert replay.main(["summarise", *_holdout_shards(tmp_path, size=2450, failed=50), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["problems"] == ["50 of 2450 stocks failed (over 2%)"]


def test_a_pass_without_an_outcome_counts_and_over_2_percent_blocks():
    """A70 passes with no holding period are counted; 4 of 200 (2%) is allowed, 5 of 201 is NO DECISION."""
    ok = {"passes": 196, "months": 30, "buys": 40, "no_outcome": 4}
    assert replay._width_blockers(ok, True) == []
    assert replay._width_blockers({**ok, "no_outcome": 5}, True) == [
        "over 2% of A70 passes have no outcome (possible hidden losses)"]
    rows = _width_run() + [{k: v for k, v in _wrow("2023-05-10", 0.0).items()
                            if k not in ("gross_pct", "nifty_pct", "reason", "exit_day")} for _ in range(4)]
    report = replay.width_test(rows, complete=True, universe="holdout")
    assert report["size"]["no_outcome"] == 4 and report["verdict"] == "NO_DECISION"


def test_a_halt_on_the_last_session_sells_at_the_next_trade(monkeypatch):
    """No trade on session 3 (of 3): the hold runs to session 4's close, the first possible sale."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    nifty = _path([(1000, 1000, 1000, 1000), (1000, 1000, 1000, 1010), (1000, 1000, 1000, 1020),
                   (1000, 1000, 1000, 1030), (1000, 1000, 1000, 1040)])
    bars = _path([(100, 101, 99, 100), (100, 101, 99, 101), (101, 102, 100, 104), (90, 91, 80, 85),
                  (86, 87, 85, 86)])
    halted = bars.drop(bars.index[2])                                   # no trade on session 3
    window, gaps = replay.holding_window(halted, 0, nifty)
    assert list(window.index) == [nifty.index[0], nifty.index[1], nifty.index[3]] and gaps == 1
    sold = replay.outcome(halted, 0, 70, 130, nifty)
    assert sold["exit_day"] == str(nifty.index[3].date()) and sold["gross_pct"] == pytest.approx(-15)
    assert sold["nifty_pct"] == pytest.approx(3) and sold["gap_sessions"] == 1
    stopped = replay.outcome(halted, 0, 95, 130, nifty)                 # gap below the stop on resumption
    assert stopped["reason"] == "GAP_STOP" and stopped["exit_day"] == str(nifty.index[3].date())
    assert replay.baseline(halted, 0, nifty)["gross_pct"] == pytest.approx(-15)   # same sale as the trade
    assert replay.holding_window(halted.iloc[:2], 0, nifty) == (None, 0)   # never trades again: no outcome


def test_traded_value_is_the_median_of_the_last_20_days():
    """Close x Volume, last 20 bars before D; missing volume, short or non-finite history: None."""
    history = pd.DataFrame({"Close": [10.0] * 25, "Volume": [100.0] * 5 + list(range(1, 21))})
    assert replay.traded_value(history) == pytest.approx(105.0)          # median of 10..200
    assert replay.traded_value(history.drop(columns="Volume")) is None
    assert replay.traded_value(history.tail(19)) is None
    assert replay.traded_value(history.assign(Volume=float("nan"))) is None
    assert replay.traded_value(history.assign(Volume=[1.0] * 24 + [float("nan")])) is None   # 19 finite days


def test_liquidity_split_reports_a70_by_traded_value_tercile():
    """Low / mid / high thirds by 20-day traded value; None if any row lacks it."""
    rows = [{**_wrow("2024-01-10", float(i)), "traded_value_20d": float(i)} for i in range(1, 10)]
    split = replay.liquidity_split(rows)
    assert [split[k]["n"] for k in ("low", "mid", "high")] == [3, 3, 3]
    assert split["low"]["mean"] == pytest.approx(1.4) and split["high"]["mean"] == pytest.approx(7.4)
    partial = replay.liquidity_split(rows + [{**_wrow("2024-01-10", 1.0), "traded_value_20d": None}])   # one lacks it
    assert partial["without_value"] == 1 and partial["low"]["n"] == 3 and split["without_value"] == 0
    assert replay.liquidity_split([{**_wrow("2024-01-10", 1.0), "traded_value_20d": None}]) is None


@pytest.mark.parametrize("moment,slept", [
    (dt.datetime(2026, 11, 24, 10, 0), 2400.0),       # Tue 10:00 IST: until 10:40
    (dt.datetime(2026, 11, 24, 9, 54, 59), 0.0),
    (dt.datetime(2026, 11, 24, 10, 40), 0.0),
    (dt.datetime(2026, 11, 24, 14, 25), 2700.0),      # until 15:10
    (dt.datetime(2026, 11, 28, 10, 0), 0.0),          # Saturday: no scan
])
def test_the_replay_sleeps_through_the_live_scan_windows(moment, slept):
    """Weekday 09:55-10:40 and 14:25-15:10 IST pause the fetch loop (shared Upstox quota)."""
    naps = []
    now = moment.replace(tzinfo=replay.IST)
    assert REAL_WAIT_OUTSIDE_SCANS(now=lambda: now, sleep=naps.append) == slept
    assert naps == ([slept] if slept else [])
    utc = (now - dt.timedelta(hours=5, minutes=30)).replace(tzinfo=dt.timezone.utc)   # a UTC clock converts
    assert REAL_WAIT_OUTSIDE_SCANS(now=lambda: utc, sleep=lambda s: None) == slept


def test_every_history_request_and_retry_waits_outside_the_scan_windows(monkeypatch):
    """The wait runs before each attempt in load_bars (NIFTY, stocks and retries alike)."""
    checks, pending = [], [RuntimeError("HTTP 500")]
    monkeypatch.setattr(replay, "wait_outside_scans", lambda: checks.append(1) or 0.0)

    def fetch(client, token, key, days, *, today):
        """One failure, then data."""
        if pending:
            raise pending.pop()
        return pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2024-01-02"]))

    monkeypatch.setattr(replay, "fetch_daily_candles", fetch)
    replay.load_bars(None, "t", replay.NIFTY_KEY, today=dt.date(2026, 11, 23), days=10, pause=0)
    assert len(checks) == 2


def _keys(value):
    """Every dict key anywhere inside `value`."""
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(v) for v in value)) if value else set()
    return set()


def test_an_incomplete_run_is_blind_everywhere(tmp_path):
    """19 of 20 holdout shards: no mean, median, interval or excess figure anywhere in the report; counts stay."""
    report = replay.summarise(_width_run(), complete=False, universe="holdout")
    assert not _keys(report) & {"mean", "median", "low", "high", "win_rate", "t"}
    assert report["variants"]["incumbent-levels-v1"]["passes"] == 220 and report["baseline_excess_60bp"] is None
    files = _holdout_shards(tmp_path, size=100, failed=0)[:-1]
    out = tmp_path / "blind.json"
    assert replay.main(["summarise", *files, "--out", str(out)]) == 0
    blind = json.loads(out.read_text())
    assert not blind["complete"] and not _keys(blind) & {"mean", "median", "low", "high"}


def test_gate_inputs_use_the_median_and_the_best_middle_year():
    """Median and mean of different sign stay apart; the best year can be any year, not the first."""
    groups = {"a70": [_wrow("2022-02-10", -0.4), _wrow("2022-03-10", -0.4), _wrow("2022-04-10", -0.4),
                      _wrow("2023-02-10", 30.6), _wrow("2024-02-10", 0.6)], "b": [], "baseline": []}
    gate = replay._gate_inputs(groups, {"1m": None})                     # 60 bp excess: -1, -1, -1, 30, 0
    assert gate["median_60"] == pytest.approx(-1.0) and gate["mean_60"] == pytest.approx(5.4)
    assert gate["best_year"] == "2023" and gate["without_best_year_mean"] == pytest.approx(-0.75)


def test_the_mean_gate_sees_the_unrounded_value_end_to_end():
    """A70 excess exactly +0.9996% (shown as 1.0): check a fails."""
    rows = [r if r["variant"] != "incumbent-levels-v1" or r["action"] != "Watch" else {**r, "gross_pct": 1.5996}
            for r in _width_run()]
    report = replay.width_test(rows, complete=True, universe="holdout")
    assert report["a70_excess_60bp"]["mean"] == 1.0 and not report["checks"]["a_mean_60bp_at_least_1pct"]


def test_a_lower_bound_of_exactly_zero_fails():
    """'Above 0' is strict."""
    checks = replay._width_checks(_gates(interval_lows={"1m": 0.3, "3m": 0.0, "6m": 0.1}))
    assert not checks["a_widest_interval_above_0"]


def test_the_report_says_whether_the_seen_nifty_500_list_was_removed(tmp_path):
    """--seen-sha256 equal to every shard's nifty500_sha256: True; different: False; absent: None; bad: refused."""
    files = _holdout_shards(tmp_path, size=100, failed=0)
    for path in files:
        payload = json.loads(Path(path).read_text())
        Path(path).write_text(json.dumps({**payload, "nifty500_sha256": "a" * 64}))
    out = tmp_path / "r.json"
    for seen, expected in (("a" * 64, True), ("b" * 64, False), ("", None)):
        assert replay.main(["summarise", *files, "--out", str(out), "--seen-sha256", seen]) == 0
        assert json.loads(out.read_text())["seen_list_removed"] is expected
    with pytest.raises(SystemExit):
        replay.main(["summarise", *files, "--out", str(out), "--seen-sha256", "not-a-digest"])


def test_only_an_http_429_is_a_rate_limit(monkeypatch):
    """An ISIN or URL containing 429 is an ordinary retry (2 s), not a 60 s rate-limit wait."""
    waits, pending = [], [TimeoutError("read timed out: NSE_EQ|INE429A01010")]
    monkeypatch.setattr(replay.time, "sleep", waits.append)

    def fetch(client, token, key, days, *, today):
        """One error, then data."""
        if pending:
            raise pending.pop()
        return pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex(["2024-01-02"]))

    monkeypatch.setattr(replay, "fetch_daily_candles", fetch)
    replay.load_bars(None, "t", "K", today=dt.date(2026, 11, 23), days=10, pause=0.25, rate_wait=60.0)
    assert waits == [2.0, 0.25]


def test_every_shard_replays_to_the_members_day(tmp_path, monkeypatch):
    """as_of in the members file is the history end for every shard, whatever day the shard runs."""
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"universe": "nifty500", "members": [["A", "KA"]], "as_of": "2026-11-20",
                                "sha256": replay.universe_digest([("A", "KA")]), "nifty500_sha256": "n"}))
    ends = []
    monkeypatch.setattr(replay, "load_bars", lambda *a, today, **k: ends.append(today) or _path([(1, 1, 1, 1)]))
    monkeypatch.setattr(replay, "replay_stock", lambda *a, **k: [])
    replay.run_shard(None, "t", shard=0, shards=1, out=tmp_path / "s.json", today=dt.date(2026, 11, 23),
                     days=10, members_file=path)
    assert ends == [dt.date(2026, 11, 20)] * 2                          # NIFTY and the stock
    assert json.loads((tmp_path / "s.json").read_text())["nifty500_sha256"] == "n"


def test_pass_rows_carry_liquidity_and_the_report_splits_a70_by_it(monkeypatch):
    """traded_value_20d is stored on every pass row; the width report shows the A70 liquidity terciles."""
    monkeypatch.setattr(replay, "HORIZON", 3)
    monkeypatch.setattr(replay, "traded_value", lambda history: 123.0)
    monkeypatch.setattr(replay, "decide", lambda *a, **k: {"pass": True, "score": 72.0, "stop": 70.0,
                                                          "target": 140.0, "net_rr": 1.3, "atr": 2.0, "action": "Watch"})
    monkeypatch.setattr(replay, "replay_days", lambda b, n, **k: [0])
    bars = _path([(100, 101, 99, 100)] * 10)
    row = next(r for r in replay.replay_stock("SYN", "K", bars, bars, variants=("incumbent-levels-v1",))
               if r["variant"] == "incumbent-levels-v1")
    assert row["traded_value_20d"] == 123.0
    rows = [{**r, "traded_value_20d": float(i)} for i, r in enumerate(_width_run())]
    split = replay.width_test(rows, complete=True, universe="holdout")["a70_by_liquidity"]
    assert sum(split[k]["n"] for k in ("low", "mid", "high")) == 180


def test_replay_days_need_nifty_sessions_not_stock_bars(monkeypatch):
    """A stock that stops trading still has replay days inside its last HORIZON bars (NIFTY continues)."""
    monkeypatch.setattr(replay, "HISTORY_DAYS", 7)
    monkeypatch.setattr(replay, "NIFTY_HISTORY_DAYS", 3)
    nifty = _path([(1, 1, 1, 1)] * 60)
    stock = nifty.iloc[:30]                                   # halted for good after 30 sessions
    days = replay.replay_days(stock, nifty, offset=0, step=5)
    assert days == [5, 10, 15, 20, 25] and max(days) > len(stock) - replay.HORIZON
    assert replay.replay_days(nifty, nifty, offset=0, step=5) == [5, 10, 15, 20, 25, 30, 35, 40, 45]


def test_a_stock_halted_for_good_shows_up_as_a70_passes_without_outcome(monkeypatch):
    """End to end (replay_stock -> width_groups): passes in the last HORIZON sessions before a permanent
    halt are counted as no outcome, so the > 2% guard can fire."""
    monkeypatch.setattr(replay, "HISTORY_DAYS", 7)
    monkeypatch.setattr(replay, "NIFTY_HISTORY_DAYS", 3)
    monkeypatch.setattr(replay, "decide", lambda *a, **k: {"pass": True, "score": 75.0, "stop": 70.0,
                                                          "target": 140.0, "net_rr": 1.3, "atr": 2.0, "action": "Watch"})
    nifty = _path([(100, 101, 99, 100)] * 80)
    rows = replay.replay_stock("HALT", "K", nifty.iloc[:40], nifty, variants=("incumbent-levels-v1",))
    groups = replay.width_groups(rows)
    assert len(groups["a70_no_outcome"]) == 3 and len(groups["a70"]) >= 3   # 3 replay days in the last 14 bars


def test_a_stock_trading_to_the_data_end_has_no_passes_without_outcome(monkeypatch):
    """Data-end boundary: the last replay day still has HORIZON NIFTY sessions, so the end of the data
    is never counted as censoring (one day later would be)."""
    monkeypatch.setattr(replay, "HISTORY_DAYS", 7)
    monkeypatch.setattr(replay, "NIFTY_HISTORY_DAYS", 3)
    monkeypatch.setattr(replay, "decide", lambda *a, **k: {"pass": True, "score": 75.0, "stop": 70.0,
                                                          "target": 140.0, "net_rr": 1.3, "atr": 2.0, "action": "Watch"})
    real = replay.replay_days
    monkeypatch.setattr(replay, "replay_days", lambda b, n, **k: real(b, n, offset=0, step=1))
    nifty = _path([(100, 101, 99, 100)] * 80)
    rows = replay.replay_stock("LIVE", "K", nifty, nifty, variants=("incumbent-levels-v1",))
    assert max(r["day"] for r in rows) == str(nifty.index[-replay.HORIZON].date())
    assert replay.width_groups(rows)["a70_no_outcome"] == []


def test_a_shard_whose_nifty_ends_before_as_of_records_its_own_last_day(tmp_path, monkeypatch):
    """nifty_last_day is NIFTY's real last bar, not as_of, so a short NIFTY fetch is visible."""
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"universe": "nifty500", "members": [["A", "KA"]], "as_of": "2024-01-05",
                                "sha256": replay.universe_digest([("A", "KA")]), "nifty500_sha256": "n"}))
    monkeypatch.setattr(replay, "load_bars", lambda *a, **k: _path([(1, 1, 1, 1)] * 3))      # to 3 Jan
    monkeypatch.setattr(replay, "replay_stock", lambda *a, **k: [])
    replay.run_shard(None, "t", shard=0, shards=1, out=tmp_path / "s.json", today=dt.date(2026, 11, 23),
                     days=10, members_file=path)
    header = json.loads((tmp_path / "s.json").read_text())
    assert (header["as_of"], header["nifty_last_day"], header["days"]) == ("2024-01-05", "2024-01-03", 10)


def test_shards_cut_their_data_at_as_of_and_record_nifty_s_last_day(tmp_path, monkeypatch):
    """Bars after as_of are dropped (published later); the header carries NIFTY's last day."""
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"universe": "nifty500", "members": [["A", "KA"]], "as_of": "2024-01-03",
                                "sha256": replay.universe_digest([("A", "KA")]), "nifty500_sha256": "n"}))
    seen_bars = []
    monkeypatch.setattr(replay, "load_bars", lambda *a, **k: _path([(1, 1, 1, 1)] * 5))      # to 5 Jan
    monkeypatch.setattr(replay, "replay_stock", lambda symbol, key, bars, nifty: seen_bars.append(
        (bars.index[-1], nifty.index[-1])) or [])
    replay.run_shard(None, "t", shard=0, shards=1, out=tmp_path / "s.json", today=dt.date(2026, 11, 23),
                     days=10, members_file=path)
    assert seen_bars == [(pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-03"))]
    assert json.loads((tmp_path / "s.json").read_text())["nifty_last_day"] == "2024-01-03"


def test_shards_on_different_data_sets_are_incomplete(tmp_path):
    """Shards disagreeing on as_of or NIFTY's last day: a problem (not one data set)."""
    files = _holdout_shards(tmp_path, size=100, failed=0)
    for i, path in enumerate(files):
        payload = json.loads(Path(path).read_text())
        Path(path).write_text(json.dumps({**payload, "as_of": "2026-11-20",
                                          "nifty_last_day": "2026-11-20" if i else "2026-11-19"}))
    out = tmp_path / "r.json"
    assert replay.main(["summarise", *files, "--out", str(out)]) == 0
    assert "shards disagree on as_of or NIFTY's last day (different data sets)" in json.loads(out.read_text())["problems"]


def test_the_seen_list_check_is_only_for_a_holdout_run(tmp_path):
    """A NIFTY 500 re-summary given a digest says None, not False."""
    for shard in range(8):
        (tmp_path / f"v{shard}.json").write_text(json.dumps({
            "version": "stage2-rule-replay-v1", "shard": shard, "shards": 8, "universe_sha256": "h",
            "rows": [], "failed": []}))
    out = tmp_path / "r.json"
    assert replay.main(["summarise", *map(str, sorted(tmp_path.glob("v*.json"))), "--out", str(out),
                        "--seen-sha256", "a" * 64]) == 0
    assert json.loads(out.read_text())["seen_list_removed"] is None


def test_the_most_liquid_third_of_a70_must_also_beat_nifty():
    """Micro-caps cannot carry the pooled mean alone: gains only in the least liquid two thirds -> FAIL (g)."""
    rows = _width_run()
    a70 = [r for r in rows if r["variant"] == "incumbent-levels-v1" and r["action"] == "Watch"]
    for i, row in enumerate(sorted(a70, key=lambda r: r["ticker"])):
        row["traded_value_20d"] = float(i)
        if i >= 120:                                     # top third (60 of 180) loses ...
            row["gross_pct"] = 10.0 if i == 179 else -1.0  # ... except its single most liquid row
    report = replay.width_test(rows, complete=True, universe="holdout")
    assert not report["checks"]["g_liquid_tercile_above_0"] and report["verdict"] == "FAIL"
    assert report["gate_inputs"]["liquid_tercile_mean_60"] == pytest.approx((59 * -1.6 + 9.4) / 60)
    assert report["notes"] == [] and report["a70_liquid_third_100bp"]["n"] == 60
    assert report["a70_liquid_third_100bp"]["mean"] == pytest.approx((59 * -2.0 + 9.0) / 60, abs=1e-3)
    partial = replay.width_test([{**r, "traded_value_20d": None} if r in a70[:30] else r for r in rows],
                                complete=True, universe="holdout")
    assert partial["notes"] == ["check g on 50 rows of a top third cut from 150 of 180 A70 rows (30 without a traded value)"]
    tied = [{**r, "traded_value_20d": 1.0} for r in a70[:6]]       # ties at the cut: input order is irrelevant
    assert replay._liquid_tercile_mean(tied) == replay._liquid_tercile_mean(tied[::-1])
    assert replay._liquid_tercile_mean([{**r, "traded_value_20d": None} for r in a70]) is None
    assert [[len(p) for p in replay._terciles(a70[:n])] for n in (1, 2, 4, 5, 6, 7, 10, 151)] == [
        [0, 0, 1], [0, 1, 1], [1, 1, 2], [1, 2, 2], [2, 2, 2], [2, 2, 3], [3, 3, 4], [50, 50, 51]]   # as equal as possible


# ------------------------------------------------- out-of-time tests (PREREG target-only + scanner edge v1) ---

def _oot_day(i):
    """The i-th month of the out-of-time period, from March 2015."""
    month = 2 + i
    return f"{2015 + month // 12}-{month % 12 + 1:02d}-10"


def _to_row(day, gross, **kw):
    """A TO70 row: score 72, stop 15% below entry (inside the cap), target 21 ATR away (blocked by the target only)."""
    return _wrow(day, gross, stop=85.0, target=142.0, **kw)


def _oot_run(months=36, shift=0.0, buys=40):
    """TO70 rows (6 a month from Mar 2015), Buys and baseline rows for a decisive target-only test."""
    rows, pattern = [], [4.0, 3.0, 5.0, -1.0, 2.0, 6.0]
    for i in range(months):
        day = _oot_day(i)
        rows += [_to_row(day, g + shift, ticker=f"A{i}-{j}") for j, g in enumerate(pattern)]
        rows.append({"ticker": f"Z{i}", "day": day, "variant": replay.BASELINE, "pass": True,
                     "gross_pct": 0.0, "nifty_pct": 0.0, "reason": "TIME"})
    rows += [_wrow("2015-04-10", 1.0, action="Buy", score=75.0, stop=90.0, target=110.0, ticker=f"B{k}")
             for k in range(buys)]
    return rows


def _edge_run(months=36, pattern=(3.0, 1.0, 2.0, -1.0, 4.0), baseline=0.0, values=None):
    """Incumbent Buys (len(pattern) a month from Mar 2015) and baseline rows for a decisive scanner-edge test;
    `values` gives each Buy's 20-day traded value by its position in the month."""
    rows = []
    for i in range(months):
        day = _oot_day(i)
        rows += [_wrow(day, g, action="Buy", score=75.0, stop=90.0, target=110.0, ticker=f"B{i}-{j}")
                 | ({"traded_value_20d": values[j]} if values else {}) for j, g in enumerate(pattern)]
        rows.append({"ticker": f"Z{i}", "day": day, "variant": replay.BASELINE, "pass": True,
                     "gross_pct": baseline, "nifty_pct": 0.0, "reason": "TIME"})
    return rows


def test_period_of_names_runs_that_end_before_the_seen_days_out_of_time():
    """Data ending before 14 Dec 2021 replays only unseen days; the seen runs and v1 files are recent."""
    assert [replay.period_of(d, 3640) for d in ("2015-01-01", "2021-11-30", "2021-12-01", "2021-12-14", None)] == [
        "recent", "out_of_time", "recent", "recent", "recent"]
    assert replay.period_of("2021-11-30", 3000) == "recent" and replay.period_of("2021-11-30") == "recent"
    assert replay.PERIODS["out_of_time"]["years"] == ("2015", "2016", "2017", "2018", "2019", "2020", "2021")
    assert replay.PERIODS["recent"]["years"] == replay.WIDTH["years"]


def test_the_live_universe_is_the_whole_collector_list_sorted(monkeypatch):
    """`live` = every collector NSE EQ stock (NIFTY 500 included), sorted; a short list is refused."""
    rows = [{"trading_symbol": f"S{k:04d}", "instrument_key": f"NSE_EQ|K{k:04d}"} for k in range(2100, 0, -1)]
    monkeypatch.setattr(replay, "fetch_nse_universe", lambda client: rows)
    members = replay.live(None)
    assert len(members) == 2100 and members == sorted(members) and members[0] == ("S0001", "NSE_EQ|K0001")
    monkeypatch.setattr(replay, "fetch_nse_universe", lambda client: rows[:1999])
    with pytest.raises(RuntimeError):
        replay.live(None)


def test_members_with_an_end_date_cut_as_of_there(monkeypatch):
    """`--end`: NIFTY is fetched up to that day and as_of is its last bar; a later bar is refused."""
    calls = []
    monkeypatch.setattr(replay, "nifty500", lambda client: [("A", "NSE_EQ|KA")])
    monkeypatch.setattr(replay, "live", lambda client: [("A", "NSE_EQ|KA"), ("H", "NSE_EQ|KH")])
    monkeypatch.setattr(replay, "load_bars", lambda client, token, key, *, today, days: calls.append(today) or _path([(1, 1, 1, 1)] * 3))
    got = replay.resolve_members(None, "live", "t", end=dt.date(2024, 1, 3))
    assert calls == [dt.date(2024, 1, 3)] and got["as_of"] == "2024-01-03" and got["shards"] == 24
    assert got["members"] == [["A", "NSE_EQ|KA"], ["H", "NSE_EQ|KH"]]
    with pytest.raises(RuntimeError):                 # bars to 3 Jan cannot belong to a run ending 2 Jan
        replay.resolve_members(None, "live", "t", end=dt.date(2024, 1, 2))


def test_members_cli_period_sets_the_end_date_and_the_days(tmp_path, monkeypatch):
    """`members --period out_of_time`: data ends 2021-11-30 and the workflow fetches 3,640 days (one Upstox
    request); the default period has no end and 3,000 days; an unknown period is an argparse error."""
    seen, gh = {}, tmp_path / "gh.txt"
    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", "t")
    monkeypatch.setattr(replay, "resolve_members", lambda client, name, token, end=None: seen.update(end=end) or {
        "universe": name, "members": [], "sha256": "d", "nifty500_sha256": "n", "shards": 24, "as_of": "2021-11-30"})
    assert replay.main(["members", "--universe", "live", "--out", str(tmp_path / "m.json"), "--period", "out_of_time",
                        "--github-output", str(gh)]) == 0
    assert seen["end"] == dt.date(2021, 11, 30) and gh.read_text().endswith("days=3640\n")
    assert replay.main(["members", "--universe", "live", "--out", str(tmp_path / "m.json")]) == 0 and seen["end"] is None
    with pytest.raises(SystemExit):
        replay.main(["members", "--universe", "live", "--out", str(tmp_path / "m.json"), "--period", "2015"])


@pytest.mark.parametrize("days,ok", [(30, True), (3640, True), (3650, True), (3651, False), (29, False)])
def test_run_days_stay_inside_upstox_one_decade_limit(days, ok):
    """Upstox serves at most one decade of daily bars per request: a longer --days is refused up front."""
    if ok:
        assert replay._days_arg(str(days)) == days
    else:
        with pytest.raises(argparse.ArgumentTypeError):
            replay._days_arg(str(days))


def test_target_only_groups_keep_a70_passes_blocked_only_by_the_target():
    """TO70: A70 with stop <= 20% below entry (exactly 20% counts as inside the cap); 20.1% is stop-wide; a
    non-blocked score-72 Watch is not A70; v1 rows (no entry) are in neither TO70 nor stop-wide."""
    rows = [_to_row("2016-01-10", 1.0, ticker="T"), _wrow("2016-01-10", 1.0, stop=80.0, target=142.0, ticker="E"),
            _wrow("2016-01-10", 1.0, stop=79.9, target=142.0, ticker="W"), _wrow("2016-01-10", 1.0, ticker="S"),
            _wrow("2016-01-10", 1.0, stop=90.0, target=110.0, ticker="N"), _wrow("2016-01-10", 1.0, entry=None, ticker="V"),
            _to_row("2016-01-10", 1.0, score=66.0, ticker="F"), _wrow("2016-01-10", 1.0, score=66.0, ticker="G"),
            {**_to_row("2016-02-10", 0.0, ticker="X"), "gross_pct": None}]
    rows[-1].pop("gross_pct")
    groups = replay.target_only_groups(rows)
    assert sorted(r["ticker"] for r in groups["to70"]) == ["E", "T"]
    assert sorted(r["ticker"] for r in groups["stop_wide70"]) == ["S", "W"]
    assert [r["ticker"] for r in groups["to65"]] == ["F"] and [r["ticker"] for r in groups["to70_no_outcome"]] == ["X"]


def test_target_only_test_passes_on_a_good_out_of_time_live_run_and_is_context_elsewhere(monkeypatch):
    """Decisive only for `live` + out_of_time; it uses the out-of-time years (4 of 7 positive) and seed."""
    seeds = []
    real = replay.block_interval
    monkeypatch.setattr(replay, "block_interval", lambda *a, **k: seeds.append(k.get("seed")) or real(*a, **k))
    report = replay.target_only_test(_oot_run(), complete=True, universe="live", period="out_of_time")
    assert report["verdict"] == "PASS" and report["decisive"] and all(report["checks"].values()), report["checks"]
    assert set(seeds) == {20261124} and report["size"] == {"passes": 216, "months": 36, "buys": 40, "no_outcome": 0}
    assert set(report["to70_by_year"]) == {"2015", "2016", "2017", "2018"} and report["notes"] == []
    assert report["to70_excess_60bp"]["n"] == 216 and report["stop_exit_share"] == {"to70": 0.0, "b": 0.0}
    held = replay.target_only_test(_oot_run(), complete=True, universe="holdout", period="out_of_time")
    assert held["verdict"] == "CONTEXT_ONLY (holdout out_of_time run, not decisive; would be PASS)"
    recent = replay.target_only_test(_oot_run(), complete=True, universe="live", period="recent")
    assert not recent["decisive"] and recent["verdict"].startswith("CONTEXT_ONLY") and recent["verdict"].endswith("FAIL)")
    assert not replay.width_test(_width_run(), complete=True, universe="holdout", period="out_of_time")["decisive"]
    assert replay.width_test(_width_run(), complete=True, universe="holdout", period="recent")["decisive"]


def test_target_only_test_fails_a_losing_group_and_blocks_a_small_one():
    """Shifted down: FAIL. 20 months (120 passes): NO_DECISION naming TO70. Incomplete: blind."""
    assert replay.target_only_test(_oot_run(shift=-3.0), complete=True, universe="live", period="out_of_time")["verdict"] == "FAIL"
    small = replay.target_only_test(_oot_run(months=20), complete=True, universe="live", period="out_of_time")
    assert small["verdict"] == "NO_DECISION" and small["blockers"] == ["TO70 under 150 passes", "TO70 in under 24 months"]
    blind = replay.target_only_test(_oot_run(), complete=False, universe="live", period="out_of_time")
    assert set(blind) == {"universe", "period", "decisive", "blockers", "size", "verdict"} and blind["verdict"] == "NO_DECISION"


def test_four_positive_years_of_seven_are_enough_for_the_out_of_time_target_only_test():
    """Years 2015-2018 positive, 2019-2021 negative: 4 of 7 passes d (3 would not)."""
    spec = replay.PERIODS["out_of_time"]
    years = {y: (1.0 if y < "2019" else -1.0) for y in spec["years"]}
    gate = _gates(year_means=years, worst_decile={"to70": -14.0, "b": -10.0}, stop_exits={"to70": (25, 100), "b": (20, 100)})
    assert replay._width_checks(gate, "to70", spec)["d_positive_years"] is True
    years["2018"] = 0.0
    assert replay._width_checks({**gate, "year_means": years}, "to70", spec)["d_positive_years"] is False


def test_scanner_edge_test_finds_an_edge_in_good_buys(monkeypatch):
    """Positive Buys every month, above a 0 baseline, in 4 years, liquid third positive: EDGE (out-of-time seed)."""
    seeds, real = [], replay.block_interval
    monkeypatch.setattr(replay, "block_interval", lambda *a, **k: seeds.append(k.get("seed")) or real(*a, **k))
    rows = _edge_run() + [_wrow("2016-01-10", -50.0, score=70.0, ticker="W70")]     # a width-blocked Watch at 70
    report = replay.scanner_edge_test(rows, complete=True, universe="live", period="out_of_time")
    assert seeds == [20261124] * 3
    assert report["b_minus_passes_mean"] == pytest.approx(1.2 - (180 * 1.2 - 50.6) / 181, abs=1e-3)
    assert report["verdict"] == "EDGE" and all(report["checks"].values()), report["checks"]
    assert report["size"] == {"buys": 180, "months": 36, "no_outcome": 0} and report["notes"] == []
    assert report["gate_inputs"]["mean_60"] == pytest.approx(1.2) and report["gate_inputs"]["mean_100"] == pytest.approx(0.8)
    assert set(report["passes_by_score_60bp"]) == {"70-100", "50-69", "under-50"}
    assert report["passes_by_score_60bp"]["70-100"]["n"] == 181 and report["b_by_year"]["2019"] == {"n": 0}
    context = replay.scanner_edge_test(_edge_run(), complete=True, universe="nifty500", period="recent")
    assert context["verdict"].startswith("CONTEXT_ONLY (nifty500 recent run") and not context["decisive"]
    assert not replay.scanner_edge_test(_edge_run(), complete=True, universe="live", period="recent")["decisive"]
    losing = replay.scanner_edge_test(_edge_run(pattern=(-1.0,) * 5), complete=True, universe="live", period="out_of_time")
    assert losing["verdict"] == "NO_EDGE" and losing["checks"]["edge_mean_60bp_above_0"] is False


@pytest.mark.parametrize("check,kwargs", [
    ("edge_mean_100bp_above_0", {"pattern": (0.9,) * 5}),                       # +0.3 at 60 bp, -0.1 at 100 bp
    ("edge_above_baseline", {"baseline": 5.0}),
    ("edge_positive_years", {"months": 34}),                                    # 2015-2017 only: 3 years
    ("edge_liquid_third_above_0", {"pattern": (4.0, 4.0, 4.0, 4.0, -0.5, -0.5), "values": (1, 2, 3, 4, 9, 9)}),
])
def test_each_scanner_edge_check_can_fail_alone(check, kwargs):
    """Each check flips on its own; the verdict is then NO_EDGE."""
    report = replay.scanner_edge_test(_edge_run(**kwargs), complete=True, universe="live", period="out_of_time")
    failed = [name for name, ok in report["checks"].items() if not ok]
    assert failed == [check] and report["verdict"] == "NO_EDGE"


def test_the_scanner_edge_interval_check_uses_the_lowest_low(monkeypatch):
    """One block length below 0 is enough to fail (the widest interval decides)."""
    lows = iter([0.5, -0.01, 0.3])
    monkeypatch.setattr(replay, "block_interval", lambda *a, **k: {"low": next(lows), "high": 2.0, "draws": 10})
    report = replay.scanner_edge_test(_edge_run(), complete=True, universe="live", period="out_of_time")
    assert [n for n, ok in report["checks"].items() if not ok] == ["edge_widest_interval_above_0"]


def test_scanner_edge_floors_and_the_hidden_loss_gate():
    """Under 150 Buys or 24 months: NO_DECISION; 4 of 184 Buys without outcome (2.2%) blocks, 3 (1.6%) does not."""
    few = replay.scanner_edge_test(_edge_run(months=29), complete=True, universe="live", period="out_of_time")
    assert few["verdict"] == "NO_DECISION" and few["blockers"] == ["under 150 Buys"]
    short = replay.scanner_edge_test(_edge_run(months=20, pattern=(3.0, 1.0) * 5), complete=True, universe="live",
                                     period="out_of_time")
    assert short["blockers"] == ["Buys in under 24 months"]
    for missing, blocked in ((4, True), (3, False)):
        rows = _edge_run() + [{k: v for k, v in _wrow("2016-05-10", 0.0, action="Buy", score=75.0, stop=90.0, target=110.0,
                                                       ticker=f"M{k}").items() if k != "gross_pct"} for k in range(missing)]
        got = replay.scanner_edge_test(rows, complete=True, universe="live", period="out_of_time")
        assert got["size"]["no_outcome"] == missing and (got["verdict"] == "NO_DECISION") is blocked


def test_the_buy_no_outcome_share_counts_every_buy():
    """196 Buys + 4 without outcome = 4 / 200 = 2%: allowed (4 / 196 would be over 2%)."""
    rows = _edge_run(months=28, pattern=(3.0, 1.0, 2.0, -1.0, 4.0, 2.0, 1.0)) + [
        {k: v for k, v in _wrow("2016-05-10", 0.0, action="Buy", score=75.0, stop=90.0, target=110.0, ticker=f"M{k}").items()
         if k != "gross_pct"} for k in range(4)]
    got = replay.scanner_edge_test(rows, complete=True, universe="live", period="out_of_time")
    assert got["size"] == {"buys": 196, "months": 28, "no_outcome": 4} and got["blockers"] == []


def test_scanner_edge_flags_a_mean_carried_by_a_few_big_winners():
    """Mean > 0 but median < 0: the report says so (not a gate)."""
    report = replay.scanner_edge_test(_edge_run(pattern=(-0.5, -0.5, -0.5, -0.5, 10.0)), complete=True,
                                      universe="live", period="out_of_time")
    assert report["notes"] == ["skewed: a few big winners carry the mean (mean > 0, median < 0)"]


def test_an_incomplete_out_of_time_run_is_blind_in_every_test():
    """Counts only in all three sections (a re-run must not have seen any number)."""
    report = replay.summarise(_oot_run() + _edge_run(), complete=False, universe="live", period="out_of_time")
    assert not _keys(report) & {"mean", "median", "low", "high", "win_rate", "t"}
    assert report["period"] == "out_of_time" and report["scanner_edge_test"]["verdict"] == "NO_DECISION"
    assert report["target_only_test"]["verdict"] == "NO_DECISION" and report["width_test"]["verdict"].startswith("CONTEXT_ONLY")


def test_shards_with_different_as_of_are_incomplete_and_not_out_of_time(tmp_path):
    """One shard ending 2021-11-30 and one ending today are two data sets: incomplete, period recent."""
    for shard, as_of in ((0, "2021-11-30"), (1, "2026-11-20")):
        (tmp_path / f"x{shard}.json").write_text(json.dumps({
            "version": replay.VERSION, "shard": shard, "shards": 2, "universe": "live", "universe_sha256": "l",
            "universe_size": 10, "as_of": as_of, "nifty_last_day": as_of, "rows": [], "failed": []}))
    out = tmp_path / "r.json"
    assert replay.main(["summarise", *sorted(map(str, tmp_path.glob("x*.json"))), "--out", str(out), "--shards", "2"]) == 0
    report = json.loads(out.read_text())
    assert not report["complete"] and report["period"] == "recent"
    assert "shards disagree on as_of or NIFTY's last day (different data sets)" in report["problems"]


@pytest.mark.parametrize("as_of,days,flagged,period", [
    ("2021-12-01", 3640, True, "recent"), ("2021-12-13", 3640, True, "recent"),   # between the end and the seen start
    ("2019-06-28", 3640, True, "recent"), ("2021-11-30", 3000, True, "recent"),   # other early data / other history
    ("2021-11-30", 3640, False, "out_of_time"), ("2021-12-14", 3000, False, "recent"),
    ("2026-11-20", 3640, True, "recent"), ("2026-11-20", None, False, "recent"),   # recent with more history: no
    ("2021-11-30", "3640", True, "recent"), ("2026-11-20", "3000", True, "recent")])    # days not a whole number
def test_only_the_pre_registered_out_of_time_data_decides(tmp_path, as_of, days, flagged, period):
    """Data ending before the seen days decides only if it is exactly the PREREG's (as_of 2021-11-30, 3,640
    days); any other early run is a problem, so it is incomplete and blind."""
    for shard in range(24):
        (tmp_path / f"g{shard}.json").write_text(json.dumps({
            "version": replay.VERSION, "shard": shard, "shards": 24, "universe": "live", "universe_sha256": "l",
            "universe_size": 10, "as_of": as_of, "nifty_last_day": as_of, "days": days, "rows": [], "failed": []}))
    out = tmp_path / "r.json"
    assert replay.main(["summarise", *sorted(map(str, tmp_path.glob("g*.json"))), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    unregistered = [p for p in report["problems"] if p.startswith(("data ends before the first seen day",
                                                                    "a recent run with more than 3000 days",
                                                                    "a shard header's days is not"))]
    assert bool(unregistered) is flagged and report["complete"] is not flagged and report["period"] == period


def test_shards_that_fetched_different_history_lengths_are_incomplete(tmp_path):
    """Same as_of but shard 0 fetched 3,640 days and the rest 3,000: two data sets, so incomplete, recent."""
    for shard in range(24):
        (tmp_path / f"d{shard}.json").write_text(json.dumps({
            "version": replay.VERSION, "shard": shard, "shards": 24, "universe": "live", "universe_sha256": "l",
            "universe_size": 10, "as_of": "2021-11-30", "nifty_last_day": "2021-11-30",
            "days": 3640 if shard == 0 else 3000, "rows": [], "failed": []}))
    out = tmp_path / "r.json"
    assert replay.main(["summarise", *sorted(map(str, tmp_path.glob("d*.json"))), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert not report["complete"] and report["period"] == "recent"
    assert "shards disagree on the history length (days)" in report["problems"]


def test_summarise_cli_names_a_run_ending_before_the_seen_days_out_of_time(tmp_path, capsys):
    """24 live shards with as_of 2021-11-30: period out_of_time, tests A and B decisive, headlines printed."""
    for shard in range(24):
        (tmp_path / f"o{shard}.json").write_text(json.dumps({
            "version": replay.VERSION, "shard": shard, "shards": 24, "universe": "live", "universe_sha256": "l",
            "universe_size": 100, "as_of": "2021-11-30", "nifty_last_day": "2021-11-30", "days": 3640,
            "rows": _oot_run() + _edge_run() if shard == 0 else [], "failed": []}))
    out = tmp_path / "r.json"
    assert replay.main(["summarise", *sorted(map(str, tmp_path.glob("o*.json"))), "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["complete"] and report["period"] == "out_of_time"
    assert report["target_only_test"]["decisive"] and report["scanner_edge_test"]["decisive"]
    assert not report["width_test"]["decisive"]
    printed = capsys.readouterr().out
    assert "target_only_test:" in printed and "scanner_edge_test:" in printed and '"period": "out_of_time"' in printed
