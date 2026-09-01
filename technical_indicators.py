"""Lightweight, deterministic technical indicators used by the dashboard.

This avoids importing the entire pandas-ta/Numba stack during Streamlit's
critical startup path.  Formulas use standard exponential/Wilder smoothing
and preserve the small API surface consumed by app.py.
"""

import numpy as np
import pandas as pd


def _series(values):
    return pd.to_numeric(pd.Series(values, index=getattr(values, "index", None)), errors="coerce").astype(float)


def _rma(values, length):
    length = max(int(length), 1)
    return _series(values).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def ema(close, length=10):
    length = max(int(length), 1)
    result = _series(close).ewm(span=length, adjust=False, min_periods=length).mean()
    result.name = f"EMA_{length}"
    return result


def true_range(high, low, close):
    high = _series(high)
    low = _series(low)
    close = _series(close)
    previous_close = close.shift(1)
    result = pd.concat(
        [(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    result.name = "TR"
    return result


def atr(high, low, close, length=14):
    length = max(int(length), 1)
    result = _rma(true_range(high, low, close), length)
    result.name = f"ATRr_{length}"
    return result


def rsi(close, length=14):
    length = max(int(length), 1)
    delta = _series(close).diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = _rma(gain, length)
    avg_loss = _rma(loss, length)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - (100.0 / (1.0 + rs))
    result = result.where(avg_loss != 0.0, 100.0)
    result = result.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), 50.0)
    result.name = f"RSI_{length}"
    return result


def adx(high, low, close, length=14):
    length = max(int(length), 1)
    high = _series(high)
    low = _series(low)
    close = _series(close)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0.0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0.0), 0.0)
    smoothed_tr = _rma(true_range(high, low, close), length).replace(0.0, np.nan)
    plus_di = 100.0 * _rma(plus_dm, length) / smoothed_tr
    minus_di = 100.0 * _rma(minus_dm, length) / smoothed_tr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx_value = _rma(dx, length)
    return pd.DataFrame({
        f"ADX_{length}": adx_value,
        f"DMP_{length}": plus_di,
        f"DMN_{length}": minus_di,
    }, index=close.index)


def macd(close, fast=12, slow=26, signal=9):
    fast = max(int(fast), 1)
    slow = max(int(slow), fast + 1)
    signal = max(int(signal), 1)
    close = _series(close)
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    suffix = f"{fast}_{slow}_{signal}"
    return pd.DataFrame({
        f"MACD_{suffix}": macd_line,
        f"MACDh_{suffix}": histogram,
        f"MACDs_{suffix}": signal_line,
    }, index=close.index)


def bbands(close, length=20, std=2.0):
    length = max(int(length), 1)
    close = _series(close)
    middle = close.rolling(length, min_periods=length).mean()
    deviation = close.rolling(length, min_periods=length).std(ddof=0)
    lower = middle - float(std) * deviation
    upper = middle + float(std) * deviation
    bandwidth = 100.0 * (upper - lower) / middle.replace(0.0, np.nan)
    percent = (close - lower) / (upper - lower).replace(0.0, np.nan)
    suffix = f"{length}_{float(std)}"
    return pd.DataFrame({
        f"BBL_{suffix}": lower,
        f"BBM_{suffix}": middle,
        f"BBU_{suffix}": upper,
        f"BBB_{suffix}": bandwidth,
        f"BBP_{suffix}": percent,
    }, index=close.index)


def supertrend(high, low, close, length=10, multiplier=3.0):
    length = max(int(length), 1)
    multiplier = float(multiplier)
    high = _series(high)
    low = _series(low)
    close = _series(close)
    atr_values = atr(high, low, close, length)
    midpoint = (high + low) / 2.0
    basic_upper = midpoint + multiplier * atr_values
    basic_lower = midpoint - multiplier * atr_values
    # The recurrence itself is sequential, but using contiguous NumPy arrays
    # removes thousands of costly pandas ``iloc`` reads/writes per symbol.
    # The equations and initialization are identical to the previous version.
    upper_values = basic_upper.to_numpy(dtype=float, copy=True)
    lower_values = basic_lower.to_numpy(dtype=float, copy=True)
    close_values = close.to_numpy(dtype=float, copy=False)
    direction_values = np.full(len(close), np.nan, dtype=float)
    trend_values = np.full(len(close), np.nan, dtype=float)

    valid_positions = np.flatnonzero(np.isfinite(atr_values.to_numpy(dtype=float, copy=False)))
    if not len(valid_positions):
        suffix = f"{length}_{multiplier}"
        trend = pd.Series(trend_values, index=close.index, dtype=float)
        direction = pd.Series(direction_values, index=close.index, dtype=float)
        return pd.DataFrame({
            f"SUPERT_{suffix}": trend,
            f"SUPERTd_{suffix}": direction,
            f"SUPERTl_{suffix}": trend,
            f"SUPERTs_{suffix}": trend,
            f"SUPERTu_{suffix}": pd.Series(upper_values, index=close.index, dtype=float),
            f"SUPERTb_{suffix}": pd.Series(lower_values, index=close.index, dtype=float),
        }, index=close.index)

    start = int(valid_positions[0])
    direction_values[start] = 1.0
    trend_values[start] = lower_values[start]
    for i in range(start + 1, len(close)):
        if not np.isfinite(upper_values[i]) or not np.isfinite(lower_values[i]):
            continue
        if upper_values[i] >= upper_values[i - 1] and close_values[i - 1] <= upper_values[i - 1]:
            upper_values[i] = upper_values[i - 1]
        if lower_values[i] <= lower_values[i - 1] and close_values[i - 1] >= lower_values[i - 1]:
            lower_values[i] = lower_values[i - 1]

        previous_direction = direction_values[i - 1] if np.isfinite(direction_values[i - 1]) else 1.0
        if close_values[i] > upper_values[i - 1]:
            current_direction = 1.0
        elif close_values[i] < lower_values[i - 1]:
            current_direction = -1.0
        else:
            current_direction = previous_direction
            if current_direction > 0 and lower_values[i] < lower_values[i - 1]:
                lower_values[i] = lower_values[i - 1]
            elif current_direction < 0 and upper_values[i] > upper_values[i - 1]:
                upper_values[i] = upper_values[i - 1]
        direction_values[i] = current_direction
        trend_values[i] = lower_values[i] if current_direction > 0 else upper_values[i]

    suffix = f"{length}_{multiplier}"
    direction = pd.Series(direction_values, index=close.index, dtype=float)
    trend = pd.Series(trend_values, index=close.index, dtype=float)
    long_line = trend.where(direction > 0)
    short_line = trend.where(direction < 0)
    return pd.DataFrame({
        f"SUPERT_{suffix}": trend,
        f"SUPERTd_{suffix}": direction,
        f"SUPERTl_{suffix}": long_line,
        f"SUPERTs_{suffix}": short_line,
        f"SUPERTu_{suffix}": pd.Series(upper_values, index=close.index, dtype=float),
        f"SUPERTb_{suffix}": pd.Series(lower_values, index=close.index, dtype=float),
    }, index=close.index)
