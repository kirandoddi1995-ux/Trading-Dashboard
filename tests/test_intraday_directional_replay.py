import importlib

import numpy as np
import pandas as pd
import pytest

from intraday_directional_replay import decisions, replay_session, run, validate


def fixture(days=1):
    frames, sessions = [], []
    for day in pd.bdate_range("2026-09-01", periods=days):
        opening = pd.Timestamp(str(day.date()) + " 09:15", tz="Asia/Kolkata")
        closing = opening + pd.Timedelta(minutes=375)
        index = pd.date_range(opening, closing, freq="5min", inclusive="left")
        price = 25000.0 + np.arange(75) * 2 + len(frames) * 150
        frame = pd.DataFrame({"Open": price, "High": price + 3, "Low": price - 2,
                              "Close": price + 1, "available_at": index + pd.Timedelta(minutes=5)}, index=index)
        frames.append(frame)
        sessions.append({"open": opening.isoformat(), "close": closing.isoformat(),
                         "previous_close": 24900 + (len(frames) - 1) * 150,
                         "source": "SYNTHETIC_TEST_ONLY", "availability_basis": "historical_final_assumed_bar_end"})
    return pd.concat(frames), sessions


def signals(directions):
    return [{"direction": d, "available": d is not None} for d in directions]


@pytest.mark.parametrize('reset', [False, True])
def test_optimized_decisions_exactly_match_prefix_reference(reset):
    import technical_indicators as ta
    from intraday_directional_replay import trend
    from app_runtime import score_option_direction
    bars, sessions = fixture(6)
    # Oscillations exercise both directions and near-neutral crossings.
    bars['Close'] += np.sin(np.arange(len(bars)) / 6) * 40
    bars['High'] = bars[['Open', 'Close']].max(axis=1) + 3
    bars['Low'] = bars[['Open', 'Close']].min(axis=1) - 3
    accepted, _ = validate(bars, sessions)
    if reset:
        accepted[3][0]['reset_warmup'] = True
    optimized = decisions(accepted)
    history, closes = [], []
    for day, (session, frame) in enumerate(accepted):
        if session.get('reset_warmup'):
            history, closes = [], []
        expected = []
        for i in range(len(frame)):
            closes.append(float(frame.Close.iloc[i]))
            series = pd.Series(closes)
            ema = float(ta.ema(series, 20).iloc[-1])
            rsi = float(ta.rsi(series, 14).iloc[-1])
            histogram = float(ta.macd(series, 12, 26, 9).filter(like='MACDh_').iloc[-1, 0])
            current = history + [(session['open'], frame.iloc[:i + 1])]
            t15, t60 = trend(current, 15, session['open']), trend(current, 60, session['open'])
            detail = ({'bias': 'Unavailable', 'decision_reason': 'INDICATOR_OR_SESSION_TREND_WARMUP'}
                if not all(np.isfinite([ema, rsi, histogram])) or t15 is None else
                score_option_direction(price=float(frame.Close.iloc[i]), previous_close=session['previous_close'],
                    ema20=ema, rsi=rsi, macd_hist=histogram, trend_15m=t15, trend_1h=t60,
                    volume_confirmed=False, market_open=True, minimum_score=25))
            bias = detail['bias']
            expected.append({'at': frame.end.iloc[i].isoformat(), 'direction':
                1 if bias in {'Bullish', 'Mildly Bullish'} else -1 if bias in {'Bearish', 'Mildly Bearish'} else 0,
                'available': bias != 'Unavailable', 'detail': detail})
        assert optimized[day][2] == expected
        history.append((session['open'], frame))


def test_indicator_pass_count_does_not_grow_per_bar(monkeypatch):
    import technical_indicators as ta
    calls = []
    original = ta.ema
    def counted(*args, **kwargs):
        calls.append(len(args[0]))
        return original(*args, **kwargs)
    monkeypatch.setattr(ta, 'ema', counted)
    accepted, _ = validate(*fixture(20))
    decisions(accepted)
    assert len(calls) <= 10  # fixed passes, not 1,500 full-history rebuilds


def test_missing_bar_excludes_whole_session():
    bars, sessions = fixture()
    accepted, excluded = validate(bars.drop(bars.index[20]), sessions)
    assert not accepted
    assert excluded[0]["reason"] == "INCOMPLETE_OR_MISALIGNED_SESSION"


def test_excluded_trading_date_resets_warmup():
    import intraday_directional_replay as replay
    bars, sessions = fixture(3)
    accepted, excluded = validate(bars.drop(bars.index[90]), sessions)
    assert len(excluded) == 1
    assert accepted[1][0]["reset_warmup"]
    all_rows = replay.decisions(accepted)
    standalone = replay.decisions([accepted[1]])
    assert all_rows[1][2] == standalone[0][2]


def test_forming_bar_is_rejected():
    bars, sessions = fixture()
    bars.loc[bars.index[0], "available_at"] = bars.index[0]
    with pytest.raises(ValueError, match="Forming"):
        run(bars, sessions)


def test_delayed_availability_never_backdates_execution():
    bars, sessions = fixture()
    bars["available_at"] += pd.Timedelta(seconds=1)
    result = run(bars, sessions)
    assert result["accepted_sessions"] == 0
    assert result["excluded_sessions"][0]["reason"] == "DELAYED_BAR_AVAILABILITY_UNSUPPORTED"


@pytest.mark.parametrize("problem", ["duplicate", "naive", "invalid_ohlc", "outside_calendar"])
def test_invalid_inputs(problem):
    bars, sessions = fixture()
    if problem == "duplicate":
        bars = pd.concat([bars.iloc[:1], bars])
    elif problem == "naive":
        bars.index = bars.index.tz_localize(None)
    elif problem == "invalid_ohlc":
        bars.loc[bars.index[0], "Low"] = 99999
    else:
        sessions = []
    with pytest.raises(ValueError):
        run(bars, sessions)


def test_next_bar_reference_and_no_same_open_flip():
    bars, _ = fixture()
    trades = replay_session(bars.iloc[:5], signals([1, -1, -1, 0, 0]), 1)
    assert trades[0]["entry_reference"] == bars.Open.iloc[1]
    assert trades[0]["exit_reference"] == bars.Open.iloc[2]
    assert trades[1]["entry_reference"] == bars.Open.iloc[3]
    assert trades[0]["reason"] == "REVERSAL_NEXT_OPEN_REFERENCE"
    assert trades[1]["reason"] == "SESSION_END_CLOSE_REFERENCE"


def test_persistence_resets_on_neutral_and_unavailable():
    bars, _ = fixture()
    assert not replay_session(bars.iloc[:6], signals([1, 0, 1, None, 1, 1]), 2)
    trades = replay_session(bars.iloc[:5], signals([1, 1, 0, 0, 0]), 2)
    assert trades[0]["entry_reference"] == bars.Open.iloc[2]


def test_final_bar_cannot_open_trade():
    bars, _ = fixture()
    assert not replay_session(bars.iloc[:3], signals([0, 0, 1]), 1)


def test_directional_excursions_for_short():
    bars, _ = fixture()
    trade = replay_session(bars.iloc[:4], signals([-1, 0, 0, 0]), 1)[0]
    assert trade["mae_pct"] <= 0 <= trade["mfe_pct"]
    assert trade["directional_return_pct"] < 0


def test_future_changes_do_not_change_earlier_decisions():
    bars, sessions = fixture(5)
    accepted, _ = validate(bars, sessions)
    before = decisions(accepted)
    changed = bars.copy()
    changed.loc[changed.index[-20:], ["Open", "High", "Low", "Close"]] *= 1.1
    after = decisions(validate(changed, sessions)[0])
    assert before[-1][2][:-20] == after[-1][2][:-20]


def test_hour_confirmation_does_not_use_yesterdays_last_hour():
    bars, sessions = fixture(5)
    prepared = decisions(validate(bars, sessions)[0])
    detail = prepared[-1][2][5]["detail"]  # Today's 09:45 decision, no full hour yet.
    assert detail.get("trend_1h") is None


def test_research_authority_and_labels():
    bars, sessions = fixture(5)
    result = run(bars, sessions)
    assert result["mode"] == "DIRECTIONAL_RESEARCH"
    assert result["option_pnl"] is None
    assert not result["approval_authority"] and not result["fill_evidence"]
    assert result["availability_bases"] == ["historical_final_assumed_bar_end"]
    assert len(result["variants"]) == 2


def test_import_has_no_provider_dependency():
    assert importlib.import_module("intraday_directional_replay").main
