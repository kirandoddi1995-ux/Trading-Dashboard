"""Independent option valuation, Greeks checks, and no-arbitrage diagnostics."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm


@dataclass(frozen=True)
class OptionValidationPolicy:
    maximum_delta_error: float = 0.10
    maximum_gamma_relative_error: float = 0.50
    maximum_theta_relative_error: float = 0.50
    maximum_vega_relative_error: float = 0.50
    maximum_iv_relative_error: float = 0.25
    maximum_iv_absolute_error: float = 0.05
    price_tolerance: float = 0.05
    parity_tolerance_fraction: float = 0.01
    monotonicity_tolerance: float = 0.05


def _finite(value, *, positive=False):
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        return None
    return parsed


def _expiry_timestamp(expiry, now):
    current = pd.Timestamp(now)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    expiry_ts = pd.Timestamp(expiry)
    if expiry_ts.tzinfo is None:
        expiry_ts = expiry_ts.tz_localize("Asia/Kolkata")
    if expiry_ts.hour == 0 and expiry_ts.minute == 0:
        expiry_ts = expiry_ts.normalize() + pd.Timedelta(hours=15, minutes=30)
    return expiry_ts.tz_convert(current.tz)


def black_scholes_price(spot, strike, years, volatility, *, option_type,
                        risk_free_rate=0.06, dividend_yield=0.0):
    s, k, t, sigma = map(float, (spot, strike, years, volatility))
    if min(s, k, t, sigma) <= 0 or not all(math.isfinite(x) for x in (s, k, t, sigma)):
        raise ValueError("Black-Scholes inputs must be finite and positive")
    r, q = float(risk_free_rate), float(dividend_yield)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if str(option_type).upper() in {"CE", "CALL", "C"}:
        return s * math.exp(-q * t) * norm.cdf(d1) - k * math.exp(-r * t) * norm.cdf(d2)
    if str(option_type).upper() in {"PE", "PUT", "P"}:
        return k * math.exp(-r * t) * norm.cdf(-d2) - s * math.exp(-q * t) * norm.cdf(-d1)
    raise ValueError("option_type must be call/CE or put/PE")


def black_scholes_greeks(spot, strike, years, volatility, *, option_type,
                         risk_free_rate=0.06, dividend_yield=0.0):
    s, k, t, sigma = map(float, (spot, strike, years, volatility))
    r, q = float(risk_free_rate), float(dividend_yield)
    if min(s, k, t, sigma) <= 0:
        raise ValueError("Greek inputs must be positive")
    root_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    density = norm.pdf(d1)
    discounted_spot = s * math.exp(-q * t)
    gamma = math.exp(-q * t) * density / (s * sigma * root_t)
    vega_per_point = discounted_spot * density * root_t / 100.0
    call = str(option_type).upper() in {"CE", "CALL", "C"}
    if call:
        delta = math.exp(-q * t) * norm.cdf(d1)
        theta_year = (
            -discounted_spot * density * sigma / (2 * root_t)
            - r * k * math.exp(-r * t) * norm.cdf(d2)
            + q * discounted_spot * norm.cdf(d1)
        )
    else:
        delta = -math.exp(-q * t) * norm.cdf(-d1)
        theta_year = (
            -discounted_spot * density * sigma / (2 * root_t)
            + r * k * math.exp(-r * t) * norm.cdf(-d2)
            - q * discounted_spot * norm.cdf(-d1)
        )
    return {"delta": delta, "gamma": gamma, "theta": theta_year / 365.0,
            "vega": vega_per_point}


def implied_volatility(price, spot, strike, years, *, option_type,
                       risk_free_rate=0.06, dividend_yield=0.0):
    target = _finite(price, positive=True)
    if target is None:
        return None
    try:
        fn = lambda sigma: black_scholes_price(
            spot, strike, years, sigma, option_type=option_type,
            risk_free_rate=risk_free_rate, dividend_yield=dividend_yield,
        ) - target
        low, high = fn(1e-4), fn(5.0)
        if low == 0:
            return 1e-4
        if high == 0:
            return 5.0
        if low * high > 0:
            return None
        return float(brentq(fn, 1e-4, 5.0, maxiter=200))
    except (ValueError, OverflowError):
        return None


def _relative_error(actual, expected):
    return abs(actual - expected) / max(abs(expected), 1e-8)


def normalize_iv_surface(chain, spot, expiry, now=None, *, risk_free_rate=0.06,
                         dividend_yield=0.0, policy=OptionValidationPolicy()):
    now = pd.Timestamp.now(tz="Asia/Kolkata") if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    expiry_ts = _expiry_timestamp(expiry, now)
    seconds = (expiry_ts - now).total_seconds()
    if seconds <= 0:
        return pd.DataFrame()
    years, dte = seconds / (365.0 * 86400.0), seconds / 86400.0
    spot_value = _finite(spot, positive=True)
    if spot_value is None:
        raise ValueError("spot must be finite and positive")
    rows = []
    for item in chain or []:
        strike = _finite(item.get("strike_price"), positive=True)
        if strike is None:
            continue
        for side, option_type in (("call_options", "CE"), ("put_options", "PE")):
            option = item.get(side) or {}
            greeks = option.get("option_greeks") or {}
            market = option.get("market_data") or {}
            bid, ask = _finite(market.get("bid_price")), _finite(market.get("ask_price"))
            failures = []
            if bid is None or ask is None or bid < 0 or ask <= 0 or bid > ask:
                failures.append("Executable bid/ask is invalid")
                mid = None
            else:
                mid = (bid + ask) / 2.0
            discounted_spot = spot_value * math.exp(-float(dividend_yield) * years)
            discounted_strike = strike * math.exp(-float(risk_free_rate) * years)
            lower = max(discounted_spot - discounted_strike, 0.0) if option_type == "CE" else max(discounted_strike - discounted_spot, 0.0)
            upper = discounted_spot if option_type == "CE" else discounted_strike
            if mid is not None and not lower - policy.price_tolerance <= mid <= upper + policy.price_tolerance:
                failures.append("Option mid violates model-free price bounds")
            model_iv = implied_volatility(
                mid, spot_value, strike, years, option_type=option_type,
                risk_free_rate=risk_free_rate, dividend_yield=dividend_yield,
            ) if mid is not None else None
            if model_iv is None:
                failures.append("Implied volatility cannot be recovered from executable mid")
                model_greeks = {"delta": None, "gamma": None, "theta": None, "vega": None}
            else:
                model_greeks = black_scholes_greeks(
                    spot_value, strike, years, model_iv, option_type=option_type,
                    risk_free_rate=risk_free_rate, dividend_yield=dividend_yield,
                )
            provider_iv = _finite(greeks.get("iv"), positive=True)
            if provider_iv is not None and provider_iv > 3:
                provider_iv /= 100.0
            provider_values = {key: _finite(greeks.get(key)) for key in ("delta", "gamma", "theta", "vega")}
            greek_failures = []
            if provider_iv is None:
                greek_failures.append("Provider IV is missing or invalid")
            elif model_iv is not None and (
                abs(provider_iv - model_iv) > policy.maximum_iv_absolute_error
                and _relative_error(provider_iv, model_iv) > policy.maximum_iv_relative_error
            ):
                greek_failures.append("Provider IV differs materially from executable-mid IV")
            tolerances = {
                "delta": (policy.maximum_delta_error, False),
                "gamma": (policy.maximum_gamma_relative_error, True),
                "theta": (policy.maximum_theta_relative_error, True),
                "vega": (policy.maximum_vega_relative_error, True),
            }
            for name, (tolerance, relative) in tolerances.items():
                provider_value, model_value = provider_values[name], model_greeks[name]
                if provider_value is None or model_value is None:
                    greek_failures.append(f"Provider {name} is missing or invalid")
                else:
                    error = _relative_error(provider_value, model_value) if relative else abs(provider_value - model_value)
                    if error > tolerance:
                        greek_failures.append(f"Provider {name} differs materially from recomputed {name}")
            rows.append({
                "strike": strike, "option_type": option_type, "dte": dte,
                "years": years, "log_moneyness": float(np.log(strike / spot_value)),
                "iv": provider_iv * 100 if provider_iv is not None else None,
                "model_iv": model_iv * 100 if model_iv is not None else None,
                **provider_values,
                **{f"model_{key}": value for key, value in model_greeks.items()},
                "bid": bid, "ask": ask, "mid": mid, "lower_bound": lower, "upper_bound": upper,
                "spread_pct": ((ask - bid) / max(mid, 1e-9) * 100 if mid is not None else None),
                "pricing_valid": not failures, "greeks_valid": not greek_failures,
                "validation_failures": failures + greek_failures,
            })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["iv_zscore"] = frame.groupby(["dte", "option_type"])["iv"].transform(
        lambda x: (x - x.median()) / max(float((x - x.median()).abs().median()) * 1.4826, 1e-9)
    )
    frame["surface_outlier"] = frame["iv_zscore"].abs() > 4
    frame["no_arbitrage_valid"] = True

    for option_type, group in frame.dropna(subset=["mid"]).groupby("option_type"):
        ordered = group.sort_values("strike")
        mids = ordered["mid"].to_numpy(dtype=float)
        strikes = ordered["strike"].to_numpy(dtype=float)
        differences = np.diff(mids)
        monotonic_failure = np.any(differences > policy.monotonicity_tolerance) if option_type == "CE" else np.any(differences < -policy.monotonicity_tolerance)
        slopes = np.diff(mids) / np.diff(strikes) if len(strikes) >= 2 else np.array([])
        convex_failure = len(slopes) >= 2 and np.any(np.diff(slopes) < -policy.monotonicity_tolerance)
        if monotonic_failure or convex_failure:
            frame.loc[ordered.index, "no_arbitrage_valid"] = False
            reason = "Strike monotonicity/convexity violation"
            frame.loc[ordered.index, "validation_failures"] = frame.loc[ordered.index, "validation_failures"].map(lambda items: list(items) + [reason])

    calls = frame[(frame["option_type"] == "CE") & frame["mid"].notna()].set_index("strike")
    puts = frame[(frame["option_type"] == "PE") & frame["mid"].notna()].set_index("strike")
    for strike in calls.index.intersection(puts.index):
        lhs = float(calls.loc[strike, "mid"] - puts.loc[strike, "mid"])
        rhs = spot_value * math.exp(-dividend_yield * years) - strike * math.exp(-risk_free_rate * years)
        if abs(lhs - rhs) > max(policy.price_tolerance, spot_value * policy.parity_tolerance_fraction):
            mask = frame["strike"].eq(strike)
            frame.loc[mask, "no_arbitrage_valid"] = False
            frame.loc[mask, "validation_failures"] = frame.loc[mask, "validation_failures"].map(lambda items: list(items) + ["Put-call parity violation"])
    frame["production_valid"] = (
        frame["pricing_valid"] & frame["greeks_valid"]
        & frame["no_arbitrage_valid"] & ~frame["surface_outlier"]
    )
    return frame


def calendar_total_variance_check(surface: pd.DataFrame, *, moneyness_tolerance=0.05) -> dict:
    """Check that nearby-moneyness total variance does not fall with maturity."""
    required = {"log_moneyness", "years", "model_iv"}
    if not isinstance(surface, pd.DataFrame) or not required.issubset(surface.columns):
        return {"status": "UNAVAILABLE", "failures": ["Surface columns are missing"]}
    frame = surface.dropna(subset=list(required)).copy()
    if frame["years"].nunique() < 2:
        return {"status": "UNAVAILABLE", "failures": ["At least two expiries are required"]}
    failures = []
    grid = np.arange(-0.30, 0.31, max(float(moneyness_tolerance), 0.01))
    for point in grid:
        rows = []
        for years, group in frame.groupby("years"):
            nearest = group.iloc[(group["log_moneyness"] - point).abs().argmin()]
            if abs(float(nearest["log_moneyness"]) - point) <= moneyness_tolerance:
                iv = float(nearest["model_iv"]) / 100.0
                rows.append((float(years), iv * iv * float(years)))
        rows.sort()
        if len(rows) >= 2 and any(rows[index + 1][1] + 1e-8 < rows[index][1] for index in range(len(rows) - 1)):
            failures.append(f"Calendar total variance decreases near log-moneyness {point:.2f}")
    return {"status": "PASS" if not failures else "NO_TRADE", "failures": failures}
