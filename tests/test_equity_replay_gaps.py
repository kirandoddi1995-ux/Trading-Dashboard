"""Synthetic paths only; OHLC scenario fills are not executable evidence."""
import pandas as pd
import pytest

from event_backtest import run_long_bracket_backtest


def replay(opening, high, low, close):
    bars = pd.DataFrame({
        'Open': [100, 100, opening], 'High': [101, 102, high],
        'Low': [99, 99, low], 'Close': [100, 101, close],
    }, index=pd.date_range('2024-01-02', periods=3, freq='B', tz='Asia/Kolkata'))
    return run_long_bracket_backtest(
        bars, signal=lambda history: len(history) == 1,
        levels=lambda history, entry, holding: (95., 110.),
        maximum_holding_bars=3, round_trip_cost_bps=30)


def test_adverse_gap_does_not_receive_unavailable_stop_price():
    result = replay(90, 96, 89, 94)
    trade = result['trades'][0]
    assert trade['outcome'] == 'STOP' and trade['exit_price'] == 90
    assert trade['net_return'] == pytest.approx(-.103)
    assert result['engine'] == 'event-driven-bracket-v2'
    assert result['fill_evidence'] is False


def test_open_above_limit_precedes_later_low_without_gap_up_credit():
    result = replay(115, 116, 90, 100)
    trade = result['trades'][0]
    assert trade['outcome'] == 'TARGET' and trade['exit_price'] == 110
    assert trade['net_return'] == pytest.approx(.097)


def test_inside_bracket_still_uses_stop_first_for_ambiguous_bar():
    trade = replay(100, 112, 94, 100)['trades'][0]
    assert trade['outcome'] == 'STOP' and trade['exit_price'] == 95


def test_open_at_stop_is_not_a_target_even_if_high_later_touches():
    trade = replay(95, 112, 94, 100)['trades'][0]
    assert trade['outcome'] == 'STOP' and trade['exit_price'] == 95
