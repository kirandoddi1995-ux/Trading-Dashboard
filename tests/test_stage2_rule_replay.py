"""Stage-2 rule replay (stage2_rule_replay.py): level rules, decision parity, outcomes, summary."""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

import equity_stage2_decision as decision_core
import stage2_rule_replay as replay
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
    """Complete = shards 0..n-1 once each, one version, one shard count, one NIFTY 500 list."""
    good = [(replay.VERSION, i, 3, "h") for i in range(3)]
    assert replay.shard_problems(good, shards=3) == []
    assert replay.shard_problems(good[:2], shards=3)
    assert replay.shard_problems(good + [good[0]], shards=3)
    assert replay.shard_problems([*good[:2], (replay.VERSION, 2, 3, "other")], shards=3)
    assert replay.shard_problems([*good[:2], ("old", 2, 3, "h")], shards=3)
    assert replay.shard_problems([*good[:2], (replay.VERSION, 2, 4, "h")], shards=3)
    assert replay.shard_problems([(replay.VERSION, 0, 1, "h")], shards=8)          # a 1-shard run is not the 8
    assert replay.shard_problems(good, shards=3, failed=2, stocks=98) == []        # 2% failed: still complete
    assert replay.shard_problems(good, shards=3, failed=3, stocks=97)              # 3%: incomplete


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
