import datetime as dt

import pytest

from trade_contracts import IST, build_trade_timing, calculate_trade_math, rule_confidence


def test_long_trade_math_includes_costs_and_enforces_two_to_one_gate():
    result = calculate_trade_math(100, 95, 111, round_trip_cost_bps=20)
    assert result["net_ratio"] == 2.08
    assert result["passes_gate"] is True


def test_short_trade_math_understands_reversed_levels():
    result = calculate_trade_math(100, 105, 89, direction="short", round_trip_cost_bps=20)
    assert result["net_ratio"] == 2.08
    assert result["passes_gate"] is True


def test_invalid_or_weak_trade_is_rejected():
    with pytest.raises(ValueError):
        calculate_trade_math(100, 105, 110)
    assert calculate_trade_math(100, 95, 109)["passes_gate"] is False


def test_intraday_timing_has_short_entry_window_and_same_day_time_exit():
    generated = dt.datetime(2026, 9, 2, 10, 7, 44, tzinfo=IST)
    result = build_trade_timing(generated, intraday=True)
    assert result["entry_at_text"] == "[2026-09-02 10:07]"
    assert result["entry_valid_until_text"] == "[2026-09-02 10:22]"
    assert result["mandatory_exit_at_text"] == "[2026-09-02 15:15]"


def test_rule_confidence_never_calls_score_a_probability():
    assert rule_confidence(80).startswith("High")
    assert "not probability" in rule_confidence(80)


def test_multi_session_entry_window_still_closes_before_same_day_cutoff():
    generated = dt.datetime(2026, 9, 2, 15, 10, tzinfo=IST)
    result = build_trade_timing(generated, horizon_sessions=15)
    assert result["entry_valid_until_text"] == "[2026-09-02 15:15]"
    assert result["entry_window_open"] is True
    after_cutoff = build_trade_timing(
        dt.datetime(2026, 9, 2, 15, 16, tzinfo=IST), horizon_sessions=15
    )
    assert after_cutoff["entry_window_open"] is False
