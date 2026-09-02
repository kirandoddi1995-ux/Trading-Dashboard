"""Shared, auditable trade-level maths and timing contracts.

The helpers deliberately separate rule scores from calibrated probabilities.
They also distinguish price-triggered exits (target/stop) from the mandatory
time exit, because no model can know an exact profitable exit timestamp.
"""

from __future__ import annotations

import datetime as dt
import math


IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MIN_NET_REWARD_RISK = 2.0
ENTRY_WINDOW_MINUTES = 15
INTRADAY_TIME_EXIT = dt.time(15, 15)


def _finite(value) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Trade levels must be finite")
    return result


def calculate_trade_math(
    entry,
    stop,
    target,
    *,
    direction="long",
    round_trip_cost_bps=0.0,
    minimum_ratio=MIN_NET_REWARD_RISK,
) -> dict:
    """Return gross and cost-adjusted reward/risk for a long or short trade."""
    entry = _finite(entry)
    stop = _finite(stop)
    target = _finite(target)
    cost_bps = max(_finite(round_trip_cost_bps), 0.0)
    side = str(direction).strip().lower()
    is_short = side in {"short", "sell", "bearish", "pe_short"}

    gross_risk = (stop - entry) if is_short else (entry - stop)
    gross_reward = (entry - target) if is_short else (target - entry)
    if entry <= 0 or gross_risk <= 0 or gross_reward <= 0:
        raise ValueError("Entry, stop and target are inconsistent with trade direction")

    cost_per_unit = entry * cost_bps / 10_000.0
    net_risk = gross_risk + cost_per_unit
    net_reward = gross_reward - cost_per_unit
    net_ratio = net_reward / net_risk if net_risk > 0 else 0.0
    threshold = max(_finite(minimum_ratio), 0.0)
    return {
        "gross_risk": round(gross_risk, 4),
        "gross_reward": round(gross_reward, 4),
        "cost_per_unit": round(cost_per_unit, 4),
        "net_risk": round(net_risk, 4),
        "net_reward": round(net_reward, 4),
        "net_ratio": round(net_ratio, 2),
        "minimum_ratio": round(threshold, 2),
        "passes_gate": bool(net_reward > 0 and net_ratio + 1e-12 >= threshold),
    }


def _as_ist(value=None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(IST)
    if not isinstance(value, dt.datetime):
        raise TypeError("generated_at must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=IST)
    return value.astimezone(IST)


def _add_weekday_sessions(start: dt.date, sessions: int) -> dt.date:
    """Deterministic weekday estimate; callers must label holiday uncertainty."""
    result = start
    remaining = max(int(sessions), 0)
    while remaining:
        result += dt.timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def build_trade_timing(
    generated_at=None,
    *,
    horizon_sessions=0,
    intraday=False,
    entry_window_minutes=ENTRY_WINDOW_MINUTES,
    time_exit=INTRADAY_TIME_EXIT,
) -> dict:
    """Create an exact entry window and a deterministic mandatory time exit.

    For multi-session ideas, the date is a weekday estimate. Exchange holidays
    can move the final session, so the returned qualification is explicit.
    """
    generated = _as_ist(generated_at).replace(second=0, microsecond=0)
    entry_until = generated + dt.timedelta(minutes=max(int(entry_window_minutes), 1))
    if intraday:
        exit_date = generated.date()
        qualification = "same-session mandatory time exit"
    else:
        exit_date = _add_weekday_sessions(generated.date(), max(int(horizon_sessions), 1))
        qualification = "weekday estimate; NSE holidays move the final session"
    exit_at = dt.datetime.combine(exit_date, time_exit, tzinfo=IST)
    entry_cutoff = dt.datetime.combine(generated.date(), time_exit, tzinfo=IST)
    entry_until = min(entry_until, entry_cutoff)
    return {
        "generated_at": generated,
        "entry_at": generated,
        "entry_valid_until": entry_until,
        "mandatory_exit_at": exit_at,
        "entry_at_text": generated.strftime("[%Y-%m-%d %H:%M]"),
        "entry_valid_until_text": entry_until.strftime("[%Y-%m-%d %H:%M]"),
        "mandatory_exit_at_text": exit_at.strftime("[%Y-%m-%d %H:%M]"),
        "timing_qualification": qualification,
        "entry_window_open": generated < entry_cutoff,
    }


def rule_confidence(score, *, medium=60.0, high=75.0) -> str:
    """Label a rule score without misrepresenting it as a probability."""
    score = _finite(score)
    if score >= high:
        return "High (rule score, not probability)"
    if score >= medium:
        return "Medium (rule score, not probability)"
    return "Low (rule score, not probability)"


def indicator_formula_reference() -> list[dict]:
    """Concise formulas shown in the transparency panel."""
    return [
        {"Indicator": "EMA(n)", "Formula": "EMA_t = α·Price_t + (1−α)·EMA_(t−1), α=2/(n+1)"},
        {"Indicator": "RSI(14)", "Formula": "100 − 100/(1 + AvgGain_14/AvgLoss_14)"},
        {"Indicator": "MACD", "Formula": "EMA(12) − EMA(26); histogram = MACD − EMA(9 of MACD)"},
        {"Indicator": "Bollinger Bands", "Formula": "SMA(20) ± 2·standard deviation(20)"},
        {"Indicator": "VWAP", "Formula": "Σ(TypicalPrice·Volume) / ΣVolume"},
        {"Indicator": "ATR(14)", "Formula": "Wilder average of max(H−L, |H−PrevClose|, |L−PrevClose|)"},
        {"Indicator": "PCR", "Formula": "Put open interest / Call open interest"},
        {"Indicator": "Fibonacci", "Formula": "Low + (High−Low)·{0.236, 0.382, 0.500, 0.618, 0.786}"},
        {"Indicator": "Net reward:risk", "Formula": "(Reward−estimated costs) / (Risk+estimated costs)"},
    ]
