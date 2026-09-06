"""PIT-safe GARCH-family volatility forecasts for shadow/risk use.

The implementation fits a Student-t GARCH(1,1) by maximum likelihood using
SciPy.  It never substitutes an EWMA constant when fitting or diagnostics fail;
callers must degrade/abstain instead.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import chi2, t


UTC = dt.timezone.utc


@dataclass(frozen=True)
class GarchPolicy:
    minimum_observations: int = 250
    maximum_iterations: int = 2_000
    persistence_cap: float = 0.999
    diagnostic_lags: int = 10
    minimum_diagnostic_pvalue: float = 0.01
    maximum_forecast_age_hours: float = 36.0


def _aware(value, name: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _ljung_box(values: np.ndarray, lags: int) -> tuple[float, float]:
    series = np.asarray(values, dtype=float)
    series = series[np.isfinite(series)]
    count = len(series)
    maximum_lag = min(max(int(lags), 1), max(count // 5, 1))
    if count <= maximum_lag + 5 or float(np.std(series)) <= 0:
        return math.nan, math.nan
    centered = series - float(np.mean(series))
    denominator = float(np.dot(centered, centered))
    correlations = []
    for lag in range(1, maximum_lag + 1):
        correlations.append(float(np.dot(centered[lag:], centered[:-lag]) / denominator))
    q_stat = count * (count + 2.0) * sum(
        correlation * correlation / (count - lag)
        for lag, correlation in enumerate(correlations, start=1)
    )
    return float(q_stat), float(chi2.sf(q_stat, maximum_lag))


def _variance_path(epsilon: np.ndarray, omega: float, alpha: float, beta: float) -> np.ndarray:
    unconditional = omega / max(1.0 - alpha - beta, 1e-8)
    variance = np.empty(len(epsilon), dtype=float)
    variance[0] = max(unconditional, float(np.var(epsilon)), 1e-8)
    for index in range(1, len(epsilon)):
        variance[index] = omega + alpha * epsilon[index - 1] ** 2 + beta * variance[index - 1]
    return np.clip(variance, 1e-12, None)


def fit_student_t_garch11(
    returns,
    *,
    observed_through,
    available_at=None,
    forecast_horizon=5,
    policy: GarchPolicy = GarchPolicy(),
) -> dict:
    """Fit a stationary Student-t GARCH(1,1) to chronological decimal returns."""
    try:
        observed = _aware(observed_through, "observed_through")
        available = _aware(available_at or dt.datetime.now(UTC), "available_at")
    except (TypeError, ValueError) as exc:
        return {"status": "UNAVAILABLE", "production_score_eligible": False, "reason": str(exc)}
    if available < observed:
        return {
            "status": "UNAVAILABLE", "production_score_eligible": False,
            "reason": "available_at precedes observed_through",
        }
    values = pd.to_numeric(pd.Series(returns), errors="coerce").dropna().to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < policy.minimum_observations:
        return {
            "status": "UNAVAILABLE", "production_score_eligible": False,
            "reason": f"At least {policy.minimum_observations} returns are required",
            "samples": int(len(values)),
        }
    if int(forecast_horizon) < 1:
        return {"status": "UNAVAILABLE", "production_score_eligible": False,
                "reason": "forecast_horizon must be positive"}
    scale = float(np.std(values, ddof=1))
    if not math.isfinite(scale) or scale <= 1e-12:
        return {"status": "UNAVAILABLE", "production_score_eligible": False,
                "reason": "Returns have no estimable variance"}
    scaled = values / scale
    mean_guess = float(np.mean(scaled))

    def objective(parameters):
        omega, alpha, beta, mean, degrees = map(float, parameters)
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= policy.persistence_cap or degrees <= 2:
            return 1e30
        epsilon = scaled - mean
        variance = _variance_path(epsilon, omega, alpha, beta)
        standardized = epsilon / np.sqrt(variance)
        standardizer = math.sqrt(degrees / (degrees - 2.0))
        log_density = (
            t.logpdf(standardized * standardizer, df=degrees)
            + math.log(standardizer)
            - 0.5 * np.log(variance)
        )
        value = -float(np.sum(log_density))
        return value if math.isfinite(value) else 1e30

    fitted = minimize(
        objective,
        x0=np.asarray([0.05, 0.07, 0.88, mean_guess, 8.0]),
        method="SLSQP",
        bounds=[(1e-8, 10.0), (0.0, 0.998), (0.0, 0.998), (-2.0, 2.0), (2.05, 100.0)],
        constraints=[{"type": "ineq", "fun": lambda p: policy.persistence_cap - p[1] - p[2]}],
        options={"maxiter": policy.maximum_iterations, "ftol": 1e-10},
    )
    if not fitted.success or not math.isfinite(float(fitted.fun)):
        return {
            "status": "UNAVAILABLE", "production_score_eligible": False,
            "reason": "GARCH maximum-likelihood fit did not converge",
            "samples": int(len(values)),
        }

    omega_scaled, alpha, beta, mean_scaled, degrees = map(float, fitted.x)
    epsilon_scaled = scaled - mean_scaled
    variance_scaled = _variance_path(epsilon_scaled, omega_scaled, alpha, beta)
    standardized = epsilon_scaled / np.sqrt(variance_scaled)
    residual_q, residual_p = _ljung_box(standardized, policy.diagnostic_lags)
    arch_q, arch_p = _ljung_box(standardized ** 2, policy.diagnostic_lags)
    persistence = alpha + beta
    last_variance = float(variance_scaled[-1])
    last_shock = float(epsilon_scaled[-1] ** 2)
    unconditional = omega_scaled / max(1.0 - persistence, 1e-8)
    forecasts = []
    next_variance = omega_scaled + alpha * last_shock + beta * last_variance
    for _ in range(int(forecast_horizon)):
        forecasts.append(float(max(next_variance, 1e-12) * scale * scale))
        next_variance = omega_scaled + persistence * next_variance

    diagnostic_values = (residual_p, arch_p)
    diagnostics_pass = all(
        math.isfinite(value) and value >= policy.minimum_diagnostic_pvalue
        for value in diagnostic_values
    )
    parameters = {
        "mean": mean_scaled * scale,
        "omega": omega_scaled * scale * scale,
        "alpha": alpha,
        "beta": beta,
        "persistence": persistence,
        "student_t_degrees_of_freedom": degrees,
        "unconditional_variance": unconditional * scale * scale,
    }
    material = {
        "parameters": parameters,
        "samples": len(values),
        "observed_through": observed.isoformat(),
        "policy": asdict(policy),
    }
    return {
        "status": "PASS" if diagnostics_pass else "ABSTAIN",
        "production_score_eligible": False,
        "reason": (
            "Shadow volatility forecast; independent validation still required"
            if diagnostics_pass else "Standardized-residual diagnostics failed"
        ),
        "model_family": "student-t-garch-1-1",
        "model_hash": hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "samples": int(len(values)),
        "observed_through": observed.isoformat(),
        "available_at": available.isoformat(),
        "parameters": parameters,
        "variance_forecast": forecasts,
        "volatility_forecast": [math.sqrt(value) for value in forecasts],
        "diagnostics": {
            "standardized_residual_ljung_box_q": residual_q,
            "standardized_residual_ljung_box_pvalue": residual_p,
            "squared_residual_arch_q": arch_q,
            "squared_residual_arch_pvalue": arch_p,
            "minimum_pvalue": policy.minimum_diagnostic_pvalue,
        },
    }
