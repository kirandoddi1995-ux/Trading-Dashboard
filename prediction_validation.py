"""Leakage-safe targets, scanner replay and calibrated probability validation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3
import threading
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm


TARGET_VERSION = "net-excess-execution-v2"


def canonical_target(values) -> tuple:
    """Normalize one stored target row for immutable collision comparison."""
    row = list(values or ())
    if len(row) != 14:
        return tuple(row)
    for index in (0, 2, 3, 4, 5, 6):
        row[index] = None if row[index] is None else str(row[index])
    row[1] = int(row[1])
    for index in (7, 12):
        row[index] = None if row[index] is None else bool(row[index])
    for index in (8, 9, 10, 11, 13):
        row[index] = None if row[index] is None else float(row[index])
    return tuple(row)
FALLBACK_TARGET_VERSION = "net-excess-next-open-fallback-v1"
STRATEGY_VERSION = "equity-scanner-v19.0"


@dataclass(frozen=True)
class TargetDefinition:
    horizon_sessions: int
    round_trip_cost_bps: float = 30.0
    entry_rule: str = "next_session_open"
    exit_rule: str = "first_target_or_stop_else_horizon_close"
    same_bar_rule: str = "stop_first_conservative"
    benchmark: str = "NSE_INDEX|Nifty 50"


@dataclass(frozen=True)
class CalibrationPolicy:
    minimum_training_samples: int = 200
    minimum_class_samples: int = 30
    minimum_oos_samples: int = 100
    maximum_ece: float = 0.10
    minimum_log_loss_skill: float = 0.01
    minimum_log_loss_improvement_ci_low: float = 0.0
    minimum_probability: float = 0.60
    minimum_probability_margin: float = 0.05
    minimum_pit_coverage: float = 0.90
    minimum_monitoring_days: int = 0
    credible_training_samples: int = 0
    credible_observation_days: int = 0
    minimum_regime_samples: int = 0
    minimum_confidence_band_samples: int = 0


# The production UI uses a deliberately stricter policy than the reusable
# validator defaults. Five hundred completed labels over sixty trading dates
# permits monitoring; investment-grade language remains blocked until the
# longer, diversified evidence requirements are met.
PRODUCTION_CALIBRATION_POLICY = CalibrationPolicy(
    minimum_training_samples=500,
    minimum_class_samples=75,
    minimum_oos_samples=500,
    maximum_ece=0.08,
    minimum_probability=0.60,
    minimum_probability_margin=0.05,
    minimum_pit_coverage=0.90,
    minimum_monitoring_days=60,
    credible_training_samples=2000,
    credible_observation_days=252,
    minimum_regime_samples=200,
    minimum_confidence_band_samples=100,
)


def _frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out.index = pd.to_datetime(out.index, errors="coerce").tz_localize(None)
    return out[~out.index.isna()].sort_index()


def compute_forward_target(prices: pd.DataFrame, as_of_date, definition: TargetDefinition,
                           stop: float, target: float, benchmark: pd.DataFrame | None = None,
                           intraday: pd.DataFrame | None = None, signal_timestamp=None) -> dict | None:
    """Label a long signal with explicit execution and conservative sequencing.

    Exact production labels use one-minute candles. After-market signals enter
    at the next session's opening five-minute OHLCV-VWAP proxy; during-market
    signals enter at the first one-minute open strictly after the signal. The
    legacy daily-open path remains available only as clearly versioned fallback
    evidence and is never mixed into production validation.
    """
    prices = _frame(prices)
    after = prices.loc[prices.index > pd.Timestamp(as_of_date)]
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(prices.columns):
        return None
    intraday_frame = _frame(intraday) if intraday is not None and not intraday.empty else pd.DataFrame()
    entry_quality = "daily_open_fallback"
    entry_timestamp = None
    window = after.iloc[:definition.horizon_sessions]
    if window.empty:
        return None
    entry = float(window.iloc[0]["Open"])

    if definition.entry_rule == "exact_intraday":
        if intraday_frame.empty or not required.issubset(intraday_frame.columns):
            return None
        signal_ts = pd.Timestamp(signal_timestamp) if signal_timestamp is not None else None
        if signal_ts is not None:
            if signal_ts.tzinfo is not None:
                signal_ts = signal_ts.tz_convert("Asia/Kolkata").tz_localize(None)
            candidates = intraday_frame.loc[intraday_frame.index > signal_ts]
            if candidates.empty:
                return None
            first = candidates.iloc[0]
            entry_timestamp = candidates.index[0]
            entry = float(first["Open"])
            entry_quality = "first_minute_after_signal"
            entry_day = entry_timestamp.normalize()
            daily = prices.loc[prices.index.normalize() >= entry_day]
            if len(daily) < definition.horizon_sessions:
                return None
            window = daily.iloc[:definition.horizon_sessions]
        else:
            if len(window) < definition.horizon_sessions:
                return None
            entry_day = window.index[0].normalize()
            opening = intraday_frame.loc[intraday_frame.index.normalize() == entry_day].iloc[:5]
            if len(opening) < 5 or "Volume" not in opening.columns:
                return None
            volume = pd.to_numeric(opening["Volume"], errors="coerce").fillna(0.0)
            typical = opening[["High", "Low", "Close"]].astype(float).mean(axis=1)
            if float(volume.sum()) <= 0:
                return None
            entry = float((typical * volume).sum() / volume.sum())
            entry_timestamp = opening.index[-1]
            entry_quality = "next_session_opening_5m_ohlcv_vwap"
    elif len(window) < definition.horizon_sessions:
        return None
    if not np.isfinite(entry) or entry <= 0:
        return None
    exit_price = float(window.iloc[-1]["Close"])
    outcome = "horizon"
    outcome_date = window.index[-1]
    # Exact labels never use an entry-day daily high/low because those extrema
    # may have occurred before the signal. When a daily bar indicates a touch,
    # one-minute evidence at/after entry is mandatory to establish ordering.
    for date, bar in window.iterrows():
        hit_stop = float(bar["Low"]) <= float(stop)
        hit_target = float(bar["High"]) >= float(target)
        if definition.entry_rule == "exact_intraday" and (hit_stop or hit_target):
            minute_rows = intraday_frame.loc[intraday_frame.index.normalize() == pd.Timestamp(date).normalize()]
            if entry_timestamp is not None and pd.Timestamp(date).normalize() == pd.Timestamp(entry_timestamp).normalize():
                minute_rows = minute_rows.loc[minute_rows.index >= pd.Timestamp(entry_timestamp)]
            if minute_rows.empty:
                return None
            for minute, minute_bar in minute_rows.iterrows():
                minute_stop = float(minute_bar["Low"]) <= float(stop)
                minute_target = float(minute_bar["High"]) >= float(target)
                if minute_stop:
                    exit_price, outcome, outcome_date = float(stop), "stop", minute
                    break
                if minute_target:
                    exit_price, outcome, outcome_date = float(target), "target", minute
                    break
            if outcome != "horizon":
                break
            if entry_timestamp is not None and pd.Timestamp(date).normalize() == pd.Timestamp(entry_timestamp).normalize():
                # The daily extreme occurred before entry; it is not an outcome.
                continue
            # Daily and minute sources disagree about a touch. Do not create a
            # production label from ambiguous evidence.
            return None
        if hit_stop:
            exit_price, outcome, outcome_date = float(stop), "stop", date
            break
        if hit_target:
            exit_price, outcome, outcome_date = float(target), "target", date
            break
    gross_return = exit_price / entry - 1.0
    net_return = gross_return - definition.round_trip_cost_bps / 10_000.0
    benchmark_return = None
    if benchmark is not None and not benchmark.empty:
        realized_window = window.loc[:pd.Timestamp(outcome_date)]
        bench = _frame(benchmark).reindex(realized_window.index).dropna(subset=["Open", "Close"])
        if len(bench) == len(realized_window):
            benchmark_return = float(bench.iloc[-1]["Close"] / bench.iloc[0]["Open"] - 1.0)
    excess = net_return - benchmark_return if benchmark_return is not None else None
    return {
        "target_version": TARGET_VERSION if entry_quality != "daily_open_fallback" else FALLBACK_TARGET_VERSION,
        "horizon_sessions": definition.horizon_sessions,
        "entry_date": window.index[0].date().isoformat(),
        "label_end_date": window.index[-1].date().isoformat(),
        "outcome_date": pd.Timestamp(outcome_date).date().isoformat(),
        "entry": entry, "exit": exit_price, "outcome": outcome,
        "target_before_stop": int(outcome == "target"),
        "gross_return": gross_return, "net_return": net_return,
        "benchmark_return": benchmark_return, "excess_return": excess,
        "positive_excess": (int(excess > 0) if excess is not None else None),
        "cost_bps": definition.round_trip_cost_bps,
        "entry_rule": definition.entry_rule,
        "entry_quality": entry_quality,
        "entry_timestamp": (pd.Timestamp(entry_timestamp).isoformat() if entry_timestamp is not None else None),
        "same_bar_rule": definition.same_bar_rule,
    }


def scanner_composite_score(components: dict[str, float]) -> float:
    """The exact v16.2 live ranking weights, shared by live and replay paths."""
    weights = {
        "trend": .15, "momentum": .12, "volume": .10, "relative_strength": .10,
        "risk_reward": .15, "adx": .08, "volatility": .06, "historical_edge": .10,
        "momentum_beta": .14,
    }
    missing = set(weights) - set(components)
    if missing:
        raise ValueError(f"Missing scanner components: {sorted(missing)}")
    values = {key: float(np.clip(components[key], 0.0, 100.0)) for key in weights}
    return float(np.clip(sum(values[key] * weight for key, weight in weights.items()), 0.0, 100.0))


def purged_walk_forward_splits(rows: pd.DataFrame, *, folds=5, min_train=200, embargo_sessions=20):
    """Expanding time folds with overlapping labels purged from training."""
    required = {"as_of_date", "label_end_date"}
    if not required.issubset(rows.columns):
        raise ValueError(f"Rows require {sorted(required)}")
    ordered = rows.copy()
    ordered["as_of_date"] = pd.to_datetime(ordered["as_of_date"])
    ordered["label_end_date"] = pd.to_datetime(ordered["label_end_date"])
    ordered = ordered.sort_values("as_of_date").reset_index(drop=True)
    unique_dates = np.array(sorted(ordered["as_of_date"].dt.normalize().unique()))
    if len(unique_dates) < folds + 2:
        return []
    validation_dates = np.array_split(unique_dates[max(1, len(unique_dates) // 3):], folds)
    result = []
    for fold_dates in validation_dates:
        if len(fold_dates) == 0:
            continue
        val_start, val_end = pd.Timestamp(fold_dates[0]), pd.Timestamp(fold_dates[-1])
        # Leave an explicit business-session embargo between training labels
        # and validation observations, in addition to purging labels that
        # overlap the validation boundary.
        training_cutoff = val_start - pd.offsets.BDay(max(int(embargo_sessions), 0))
        train_mask = ((ordered["as_of_date"] < training_cutoff)
                      & (ordered["label_end_date"] < training_cutoff))
        val_mask = ordered["as_of_date"].dt.normalize().isin(fold_dates)
        train_idx = ordered.index[train_mask].to_numpy()
        val_idx = ordered.index[val_mask].to_numpy()
        if len(train_idx) < min_train or not len(val_idx):
            continue
        result.append((train_idx, val_idx))
        # Embargo is naturally enforced by the next fold's strict historical
        # training and label-end purge; retained in metadata by caller.
    return result


class PlattCalibrator:
    def __init__(self):
        self.intercept = 0.0
        self.slope = 0.0

    @staticmethod
    def _sigmoid(value):
        value = np.clip(value, -35.0, 35.0)
        return 1.0 / (1.0 + np.exp(-value))

    def fit(self, scores, outcomes):
        x = np.asarray(scores, dtype=float) / 100.0
        y = np.asarray(outcomes, dtype=float)
        if len(x) != len(y) or len(x) == 0 or len(np.unique(y)) < 2:
            raise ValueError("Calibration needs non-empty scores and both outcome classes")

        def objective(params):
            p = np.clip(self._sigmoid(params[0] + params[1] * x), 1e-9, 1 - 1e-9)
            loss = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
            return loss + 1e-3 * params[1] ** 2

        fitted = minimize(objective, np.array([0.0, 1.0]), method="L-BFGS-B")
        if not fitted.success:
            raise RuntimeError("Probability calibration did not converge")
        self.intercept, self.slope = map(float, fitted.x)
        return self

    def predict(self, scores):
        x = np.asarray(scores, dtype=float) / 100.0
        return self._sigmoid(self.intercept + self.slope * x)


def calibration_metrics(outcomes, probabilities, bins=10, *, baseline_probability=None) -> dict:
    y = np.asarray(outcomes, dtype=float)
    raw_p = np.asarray(probabilities, dtype=float)
    p = np.clip(raw_p, 1e-9, 1 - 1e-9)
    if not len(y) or len(y) != len(p):
        raise ValueError("Outcomes and probabilities must be equal and non-empty")
    if not np.isfinite(y).all() or not np.isfinite(raw_p).all():
        raise ValueError("Outcomes and probabilities must be finite")
    if not np.isin(y, [0.0, 1.0]).all():
        raise ValueError("Outcomes must be binary")
    if int(bins) < 2:
        raise ValueError("At least two calibration bins are required")
    brier = float(np.mean((p - y) ** 2))
    log_loss = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    base_probability = float(np.mean(y) if baseline_probability is None else baseline_probability)
    if not math.isfinite(base_probability) or not 0 <= base_probability <= 1:
        raise ValueError("baseline_probability must be finite and between zero and one")
    base_probability = float(np.clip(base_probability, 1e-9, 1 - 1e-9))
    baseline = float(np.mean((base_probability - y) ** 2))
    baseline_log_loss = float(-np.mean(
        y * np.log(base_probability) + (1 - y) * np.log(1 - base_probability)
    ))
    edges = np.linspace(0.0, 1.0, bins + 1)
    reliability, ece = [], 0.0
    base_rate = float(np.mean(y))
    calibration_component, resolution_component = 0.0, 0.0
    for index in range(bins):
        mask = (p >= edges[index]) & (p < edges[index + 1] if index < bins - 1 else p <= 1.0)
        if not mask.any():
            continue
        predicted, actual, count = float(p[mask].mean()), float(y[mask].mean()), int(mask.sum())
        ece += count / len(y) * abs(predicted - actual)
        calibration_component += count / len(y) * (predicted - actual) ** 2
        resolution_component += count / len(y) * (actual - base_rate) ** 2
        interval_low, interval_high = wilson_score_interval(int(y[mask].sum()), count)
        reliability.append({"lower": edges[index], "upper": edges[index + 1], "predicted": predicted,
                            "actual": actual, "count": count,
                            "actual_interval_low": interval_low, "actual_interval_high": interval_high})
    return {"samples": len(y), "brier": brier, "baseline_brier": baseline,
            "brier_skill": (1.0 - brier / baseline if baseline > 0 else None),
            "brier_reliability": float(calibration_component),
            "brier_resolution": float(resolution_component),
            "brier_uncertainty": float(base_rate * (1.0 - base_rate)),
            "log_loss": log_loss, "baseline_log_loss": baseline_log_loss,
            "log_loss_skill": (1.0 - log_loss / baseline_log_loss if baseline_log_loss > 0 else None),
            "baseline_probability": base_probability,
            "ece": float(ece), "reliability": reliability}


def paired_log_loss_improvement(
    outcomes,
    probabilities,
    *,
    baseline_probability,
    confidence=0.95,
    bootstrap_samples=1_000,
    block_length=5,
    seed=1729,
) -> dict:
    """One-sided block-bootstrap interval for baseline minus candidate log loss."""
    y = np.asarray(outcomes, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    if not len(y) or len(y) != len(p) or not np.isin(y, [0.0, 1.0]).all():
        return {"status": "UNAVAILABLE", "reason": "Valid paired binary outcomes are required"}
    try:
        base = float(baseline_probability)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNAVAILABLE", "reason": "Baseline probability is invalid"}
    if not np.isfinite(p).all() or not math.isfinite(base) or not 0 < base < 1:
        return {"status": "UNAVAILABLE", "reason": "Finite interior probabilities are required"}
    if len(y) < 30:
        return {"status": "UNAVAILABLE", "reason": "At least 30 paired observations are required"}
    p = np.clip(p, 1e-9, 1 - 1e-9)
    base = float(np.clip(base, 1e-9, 1 - 1e-9))
    candidate_loss = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    baseline_loss = -(y * math.log(base) + (1 - y) * math.log(1 - base))
    differences = baseline_loss - candidate_loss
    count = len(differences)
    block = max(1, min(int(block_length), count))
    draws = max(int(bootstrap_samples), 200)
    blocks_needed = int(math.ceil(count / block))
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=float)
    for draw in range(draws):
        starts = rng.integers(0, count, size=blocks_needed)
        sample = np.concatenate([
            np.take(differences, np.arange(start, start + block) % count)
            for start in starts
        ])[:count]
        estimates[draw] = float(np.mean(sample))
    alpha = 1.0 - float(confidence)
    if not 0 < alpha < 1:
        return {"status": "UNAVAILABLE", "reason": "confidence must be between zero and one"}
    return {
        "status": "PASS",
        "samples": count,
        "mean_improvement": float(np.mean(differences)),
        "lower_one_sided": float(np.quantile(estimates, alpha)),
        "confidence": float(confidence),
        "bootstrap_samples": draws,
        "block_length": block,
    }


def wilson_score_interval(successes: int, samples: int, confidence=0.95) -> tuple[float, float]:
    """Binomial interval used for win rates and reliability-diagram bins."""
    successes, samples = int(successes), int(samples)
    if samples <= 0 or successes < 0 or successes > samples:
        return (math.nan, math.nan)
    z = float(norm.ppf(0.5 + float(confidence) / 2.0))
    proportion = successes / samples
    denominator = 1.0 + z * z / samples
    centre = (proportion + z * z / (2.0 * samples)) / denominator
    half = z * math.sqrt(proportion * (1.0 - proportion) / samples + z * z / (4.0 * samples * samples)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def moving_block_bootstrap_interval(values, *, statistic="mean", samples=1000,
                                    block_length=10, confidence=0.95, seed=1729) -> dict:
    """Preserve short-range dependence when estimating a performance interval."""
    data = np.asarray(values, dtype=float)
    data = data[np.isfinite(data)]
    if len(data) < max(30, int(block_length) * 2):
        return {"status": "UNAVAILABLE", "reason": "Insufficient samples for block bootstrap"}
    if statistic not in {"mean", "median", "win_rate"}:
        raise ValueError("Unsupported bootstrap statistic")
    block_length = max(1, min(int(block_length), len(data)))
    rng = np.random.default_rng(seed)
    estimates = []
    blocks_needed = math.ceil(len(data) / block_length)
    for _ in range(max(int(samples), 100)):
        starts = rng.integers(0, len(data), size=blocks_needed)
        draw = np.concatenate([
            np.take(data, np.arange(start, start + block_length) % len(data)) for start in starts
        ])[:len(data)]
        if statistic == "mean":
            estimate = float(np.mean(draw))
        elif statistic == "median":
            estimate = float(np.median(draw))
        else:
            estimate = float(np.mean(draw > 0))
        estimates.append(estimate)
    alpha = (1.0 - float(confidence)) / 2.0
    observed = float(np.mean(data) if statistic == "mean" else np.median(data) if statistic == "median" else np.mean(data > 0))
    return {
        "status": "PASS", "statistic": statistic, "estimate": observed,
        "lower": float(np.quantile(estimates, alpha)),
        "upper": float(np.quantile(estimates, 1.0 - alpha)),
        "confidence": float(confidence), "samples": int(len(data)),
        "bootstrap_samples": max(int(samples), 100), "block_length": block_length,
    }


def deflated_sharpe_ratio(returns, *, trials=1, benchmark_sharpe=0.0,
                          periods_per_year=252) -> dict:
    """Search-adjusted Sharpe significance using the Bailey/Lopez de Prado form."""
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 30 or float(np.std(values, ddof=1)) <= 0:
        return {"status": "UNAVAILABLE", "reason": "At least 30 non-constant returns are required"}
    count = len(values)
    mean = float(np.mean(values))
    standard_deviation = float(np.std(values, ddof=1))
    observed = mean / standard_deviation
    skewness = float(np.mean(((values - mean) / standard_deviation) ** 3))
    kurtosis = float(np.mean(((values - mean) / standard_deviation) ** 4))
    denominator = math.sqrt(max(1.0 - skewness * observed + ((kurtosis - 1.0) / 4.0) * observed ** 2, 1e-12))
    trials = max(int(trials), 1)
    expected_maximum = float(benchmark_sharpe) / math.sqrt(float(periods_per_year))
    if trials > 1:
        euler_gamma = 0.5772156649015329
        standard_error = math.sqrt(max((1.0 + 0.5 * observed ** 2) / max(count - 1, 1), 1e-12))
        expected_maximum = standard_error * (
            (1.0 - euler_gamma) * norm.ppf(1.0 - 1.0 / trials)
            + euler_gamma * norm.ppf(1.0 - 1.0 / (trials * math.e))
        )
    test_statistic = (observed - expected_maximum) * math.sqrt(count - 1.0) / denominator
    return {
        "status": "PASS",
        "observed_sharpe_annualized": observed * math.sqrt(float(periods_per_year)),
        "search_adjusted_benchmark_annualized": expected_maximum * math.sqrt(float(periods_per_year)),
        "deflated_sharpe_probability": float(norm.cdf(test_statistic)),
        "trials": trials,
        "samples": count,
        "skewness": skewness,
        "kurtosis": kurtosis,
    }


def chronological_holdout_split(rows: pd.DataFrame, *, holdout_fraction=0.15,
                                 minimum_holdout_dates=20, embargo_sessions=0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reserve the most recent dates; callers must never tune on the holdout."""
    if "as_of_date" not in rows:
        raise ValueError("Rows require as_of_date")
    ordered = rows.copy()
    ordered["as_of_date"] = pd.to_datetime(ordered["as_of_date"], errors="coerce")
    ordered = ordered.dropna(subset=["as_of_date"]).sort_values("as_of_date")
    dates = np.asarray(sorted(ordered["as_of_date"].dt.normalize().unique()))
    requested = max(int(math.ceil(len(dates) * float(holdout_fraction))), int(minimum_holdout_dates))
    if len(dates) <= requested + 20:
        return ordered.iloc[0:0].copy(), ordered.copy()
    cutoff = pd.Timestamp(dates[-requested])
    holdout = ordered[ordered["as_of_date"] >= cutoff].copy()
    development_cutoff = cutoff - pd.offsets.BDay(max(int(embargo_sessions), 0))
    development_mask = ordered["as_of_date"] < development_cutoff
    if "label_end_date" in ordered:
        ordered["label_end_date"] = pd.to_datetime(ordered["label_end_date"], errors="coerce")
        development_mask &= ordered["label_end_date"].notna()
        development_mask &= ordered["label_end_date"] < development_cutoff
    development = ordered[development_mask].copy()
    return development, holdout


def decide_abstention(probability, metrics, *, training_samples, positive_samples,
                      negative_samples, pit_coverage, policy=CalibrationPolicy()) -> tuple[bool, str]:
    numeric_values = {
        "probability": probability, "pit_coverage": pit_coverage,
        "brier": metrics.get("brier"), "baseline_brier": metrics.get("baseline_brier"),
        "ece": metrics.get("ece"), "samples": metrics.get("samples"),
        "training_samples": training_samples, "positive_samples": positive_samples,
        "negative_samples": negative_samples,
    }
    try:
        if not all(np.isfinite(float(value)) for value in numeric_values.values()):
            return True, "Calibration or abstention input is non-finite"
    except (TypeError, ValueError, OverflowError):
        return True, "Calibration or abstention input is missing or invalid"
    checks = [
        (pit_coverage < policy.minimum_pit_coverage, "Point-in-time universe coverage is below 90%"),
        (training_samples < policy.minimum_training_samples, "Insufficient completed training samples"),
        (min(positive_samples, negative_samples) < policy.minimum_class_samples, "Insufficient examples in one outcome class"),
        (int(metrics.get("samples", 0)) < policy.minimum_oos_samples, "Insufficient out-of-sample validation samples"),
        (float(metrics.get("brier", math.inf)) >= float(metrics.get("baseline_brier", -math.inf)),
         "Calibrated model does not beat the base-rate Brier score"),
        (float(metrics.get("ece", math.inf)) > policy.maximum_ece, "Calibration error is too high"),
        (abs(float(probability) - 0.5) < policy.minimum_probability_margin, "Prediction is inside the uncertainty/no-trade zone"),
        (float(probability) < policy.minimum_probability, "Probability is below the validated trade threshold"),
    ]
    for failed, reason in checks:
        if failed:
            return True, reason
    return False, "Validated evidence threshold passed"


def evidence_maturity(rows: pd.DataFrame, oos_probabilities, policy: CalibrationPolicy) -> dict:
    """Measure whether evidence is broad enough for credible probability claims."""
    observed_days = int(pd.to_datetime(rows["as_of_date"], errors="coerce").dt.normalize().nunique())
    regime_counts = {}
    if "market_regime" in rows.columns:
        regimes = rows["market_regime"].fillna("UNKNOWN").astype(str).str.strip().str.upper()
        regime_counts = {str(key): int(value) for key, value in regimes.value_counts().items()}
    probabilities = np.asarray(oos_probabilities, dtype=float)
    trade_probabilities = probabilities[probabilities >= float(policy.minimum_probability)]
    confidence_counts = {}
    if len(trade_probabilities):
        bands = pd.cut(
            trade_probabilities, bins=[0.60, 0.70, 0.80, 0.90, 1.000001], right=False,
            labels=["60-70%", "70-80%", "80-90%", "90-100%"],
        )
        confidence_counts = {
            str(key): int(value) for key, value in pd.Series(bands).value_counts(sort=False).items()
            if int(value) > 0
        }
    reasons = []
    if policy.minimum_monitoring_days and observed_days < policy.minimum_monitoring_days:
        reasons.append(
            f"Only {observed_days} trading dates are archived; monitoring requires "
            f"{policy.minimum_monitoring_days}"
        )
    if policy.credible_training_samples and len(rows) < policy.credible_training_samples:
        reasons.append(
            f"Only {len(rows)} completed predictions are available; credible validation requires "
            f"{policy.credible_training_samples}"
        )
    if policy.credible_observation_days and observed_days < policy.credible_observation_days:
        reasons.append(
            f"Only {observed_days} trading dates are represented; credible validation requires "
            f"{policy.credible_observation_days}"
        )
    if policy.minimum_regime_samples:
        usable_regimes = {key: value for key, value in regime_counts.items() if key not in {"", "UNKNOWN", "NONE"}}
        if not usable_regimes:
            reasons.append("Market-regime evidence is missing")
        elif min(usable_regimes.values()) < policy.minimum_regime_samples:
            reasons.append(
                f"Each observed market regime needs {policy.minimum_regime_samples} completed outcomes"
            )
    if policy.minimum_confidence_band_samples:
        if not confidence_counts:
            reasons.append("No out-of-sample predictions reached the trade-confidence range")
        elif min(confidence_counts.values()) < policy.minimum_confidence_band_samples:
            reasons.append(
                f"Each used confidence range needs {policy.minimum_confidence_band_samples} out-of-sample outcomes"
            )
    return {
        "credible": not reasons,
        "observed_trading_days": observed_days,
        "regime_counts": regime_counts,
        "confidence_band_counts": confidence_counts,
        "reasons": reasons,
    }


def run_purged_walk_forward_validation(rows: pd.DataFrame, *, folds=5, embargo_sessions=20,
                                       policy=CalibrationPolicy()) -> dict:
    """Fit only on the past, predict each future fold, then assess calibration.

    `rows` must contain the exact archived scanner score and completed labels;
    this function never reconstructs candidates from today's universe.
    """
    required = {"as_of_date", "label_end_date", "score", "target_before_stop", "excess_return"}
    if not required.issubset(rows.columns):
        raise ValueError(f"Validation rows require {sorted(required)}")
    clean = rows.dropna(subset=list(required)).copy()
    clean["as_of_date"] = pd.to_datetime(clean["as_of_date"], errors="coerce")
    clean["label_end_date"] = pd.to_datetime(clean["label_end_date"], errors="coerce")
    clean = clean.dropna(subset=["as_of_date", "label_end_date"]).sort_values(
        ["as_of_date", "label_end_date"], kind="mergesort"
    ).reset_index(drop=True)
    splits = purged_walk_forward_splits(
        clean, folds=folds, min_train=policy.minimum_training_samples,
        embargo_sessions=embargo_sessions,
    )
    oos_index, oos_probability = [], []
    fold_details = []
    for fold_number, (train_idx, validation_idx) in enumerate(splits, 1):
        train_y = clean.iloc[train_idx]["target_before_stop"].astype(int)
        if min(int(train_y.sum()), int((1 - train_y).sum())) < policy.minimum_class_samples:
            continue
        calibrator = PlattCalibrator().fit(clean.iloc[train_idx]["score"], train_y)
        predicted = calibrator.predict(clean.iloc[validation_idx]["score"])
        oos_index.extend(validation_idx.tolist())
        oos_probability.extend(predicted.tolist())
        fold_details.append({
            "fold": fold_number, "training_samples": len(train_idx), "validation_samples": len(validation_idx),
            "validation_start": str(clean.iloc[validation_idx]["as_of_date"].min()),
            "validation_end": str(clean.iloc[validation_idx]["as_of_date"].max()),
        })
    if not oos_index:
        return {"status": "INSUFFICIENT_EVIDENCE", "reason": "No valid purged walk-forward fold",
                "training_samples": len(clean), "oos_samples": 0, "metrics": {}, "folds": []}
    y_oos = clean.iloc[oos_index]["target_before_stop"].astype(int).to_numpy()
    metrics = calibration_metrics(y_oos, oos_probability)
    all_y = clean["target_before_stop"].astype(int)
    final_model = PlattCalibrator().fit(clean["score"], all_y)
    representative_probability = float(final_model.predict([float(clean.iloc[-1]["score"])])[0])
    abstain, reason = decide_abstention(
        representative_probability, metrics, training_samples=len(clean),
        positive_samples=int(all_y.sum()), negative_samples=int((1 - all_y).sum()),
        pit_coverage=float(clean.get("pit_coverage", pd.Series([1.0])).min()), policy=policy,
    )
    maturity = evidence_maturity(clean.iloc[oos_index].reset_index(drop=True), oos_probability, policy)
    if not abstain and not maturity["credible"]:
        abstain = True
        reason = maturity["reasons"][0]
    returns = clean.iloc[oos_index]["excess_return"].astype(float).to_numpy()
    evidence_valid = bool(
        len(oos_index) >= policy.minimum_oos_samples
        and metrics["brier"] < metrics["baseline_brier"]
        and metrics["ece"] <= policy.maximum_ece
        and maturity["credible"]
    )
    return {
        "status": "ABSTAIN" if abstain else "VALIDATED",
        "reason": reason,
        "training_samples": len(clean), "oos_samples": len(oos_index),
        "metrics": metrics, "folds": fold_details,
        "model": {"type": "platt_logistic", "intercept": final_model.intercept, "slope": final_model.slope},
        "latest_probability": representative_probability,
        "return_quantiles": {
            "p10": float(np.quantile(returns, .10)), "p50": float(np.quantile(returns, .50)),
            "p90": float(np.quantile(returns, .90)),
        },
        "policy": asdict(policy), "maturity": maturity,
        "embargo_sessions": int(embargo_sessions),
        "evidence_valid": evidence_valid,
    }


def run_advanced_chronological_validation(
    rows: pd.DataFrame,
    *,
    folds=5,
    embargo_sessions=20,
    holdout_fraction=0.15,
    minimum_holdout_dates=20,
    experiment_trials=1,
    bootstrap_samples=1000,
    bootstrap_block_length=10,
    policy=CalibrationPolicy(),
) -> dict:
    """Development walk-forward validation followed by one untouched holdout.

    The holdout is never passed to model fitting or probability calibration.
    A development result may look acceptable while the final status remains
    ABSTAIN when the untouched period fails calibration or economic tests.
    """
    development, holdout = chronological_holdout_split(
        rows, holdout_fraction=holdout_fraction,
        minimum_holdout_dates=minimum_holdout_dates,
        embargo_sessions=embargo_sessions,
    )
    if development.empty or holdout.empty:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "reason": "Insufficient chronological coverage for an untouched holdout",
            "training_samples": 0,
            "oos_samples": 0,
            "holdout_samples": len(holdout),
            "metrics": {},
            "holdout": {},
        }
    development_result = run_purged_walk_forward_validation(
        development, folds=folds, embargo_sessions=embargo_sessions, policy=policy,
    )
    if development_result["status"] == "INSUFFICIENT_EVIDENCE":
        return {
            **development_result,
            "reason": f"Development validation: {development_result['reason']}",
            "holdout_samples": len(holdout),
            "holdout": {},
        }
    model = development_result["model"]
    holdout_probability = PlattCalibrator._sigmoid(
        float(model["intercept"]) + float(model["slope"]) * holdout["score"].astype(float).to_numpy() / 100.0
    )
    holdout_y = holdout["target_before_stop"].astype(int).to_numpy()
    development_base_rate = float(development["target_before_stop"].astype(int).mean())
    holdout_metrics = calibration_metrics(
        holdout_y, holdout_probability, baseline_probability=development_base_rate,
    )
    holdout_log_loss_improvement = paired_log_loss_improvement(
        holdout_y, holdout_probability, baseline_probability=development_base_rate,
        bootstrap_samples=bootstrap_samples, block_length=bootstrap_block_length,
    )
    holdout_metrics["log_loss_improvement_ci_low"] = (
        holdout_log_loss_improvement.get("lower_one_sided")
        if holdout_log_loss_improvement.get("status") == "PASS" else None
    )
    # Multiple same-day signals are correlated. Aggregate by decision date
    # before bootstrap and Sharpe inference instead of treating them as IID.
    holdout_return_series = holdout.assign(
        _validation_date=pd.to_datetime(holdout["as_of_date"], errors="coerce").dt.normalize(),
        _excess_return=pd.to_numeric(holdout["excess_return"], errors="coerce"),
    ).dropna(subset=["_validation_date", "_excess_return"]).groupby("_validation_date")["_excess_return"].mean()
    holdout_returns = holdout_return_series.to_numpy(dtype=float)
    return_interval = moving_block_bootstrap_interval(
        holdout_returns, statistic="mean", samples=bootstrap_samples,
        block_length=bootstrap_block_length,
    )
    win_interval = wilson_score_interval(int(holdout_y.sum()), len(holdout_y))
    deflated = deflated_sharpe_ratio(holdout_returns, trials=experiment_trials)
    failures = []
    if not development_result.get("evidence_valid", False):
        failures.append("Development walk-forward evidence did not pass")
    if holdout_metrics["brier"] >= holdout_metrics["baseline_brier"]:
        failures.append("Holdout Brier score does not beat the base rate")
    if holdout_metrics["ece"] > policy.maximum_ece:
        failures.append("Holdout calibration error exceeds policy")
    if (
        holdout_metrics.get("log_loss_skill") is None
        or holdout_metrics["log_loss_skill"] < policy.minimum_log_loss_skill
    ):
        failures.append("Holdout log-loss skill is below policy")
    if (
        holdout_log_loss_improvement.get("status") != "PASS"
        or holdout_log_loss_improvement.get("lower_one_sided", -math.inf)
        <= policy.minimum_log_loss_improvement_ci_low
    ):
        failures.append("Holdout paired log-loss improvement is not statistically established")
    if return_interval.get("status") != "PASS" or return_interval["lower"] <= 0:
        failures.append("Holdout net excess-return interval is not strictly positive")
    if deflated.get("status") != "PASS" or deflated["deflated_sharpe_probability"] < 0.95:
        failures.append("Search-adjusted Sharpe evidence is insufficient")
    return {
        "status": "VALIDATED" if not failures else "ABSTAIN",
        "reason": "Untouched holdout passed" if not failures else failures[0],
        "failures": failures,
        "training_samples": len(development),
        "oos_samples": int(development_result.get("oos_samples", 0)),
        "holdout_samples": len(holdout),
        "development": development_result,
        "metrics": development_result.get("metrics", {}),
        "model": model,
        "holdout": {
            "start": str(holdout["as_of_date"].min()),
            "end": str(holdout["as_of_date"].max()),
            "metrics": holdout_metrics,
            "log_loss_improvement": holdout_log_loss_improvement,
            "win_rate": float(np.mean(holdout_y)),
            "win_rate_interval": {"lower": win_interval[0], "upper": win_interval[1]},
            "excess_return_interval": return_interval,
            "deflated_sharpe": deflated,
            "independent_return_periods": int(len(holdout_returns)),
        },
        "holdout_fraction": float(holdout_fraction),
        "embargo_sessions": int(embargo_sessions),
        "experiment_trials": max(int(experiment_trials), 1),
    }


class ValidationStore:
    def __init__(self, connect_fn, db_path):
        self._connect_fn, self._db_path = connect_fn, db_path
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        return self._connect_fn(self._db_path)

    def _ensure_schema(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS prediction_targets (
                        observation_id TEXT NOT NULL,
                        horizon_sessions INTEGER NOT NULL,
                        target_version TEXT NOT NULL,
                        entry_date TEXT NOT NULL,
                        label_end_date TEXT NOT NULL,
                        outcome_date TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        target_before_stop INTEGER NOT NULL,
                        gross_return REAL NOT NULL,
                        net_return REAL NOT NULL,
                        benchmark_return REAL,
                        excess_return REAL,
                        positive_excess INTEGER,
                        cost_bps REAL NOT NULL,
                        PRIMARY KEY (observation_id, horizon_sessions, target_version)
                    );
                    CREATE TABLE IF NOT EXISTS validation_runs (
                        run_id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        strategy_version TEXT NOT NULL,
                        target_version TEXT NOT NULL,
                        horizon_sessions INTEGER NOT NULL,
                        training_samples INTEGER NOT NULL,
                        oos_samples INTEGER NOT NULL,
                        metrics_json TEXT NOT NULL,
                        model_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        status_reason TEXT NOT NULL
                    );
                    CREATE TRIGGER IF NOT EXISTS prediction_targets_no_update
                    BEFORE UPDATE ON prediction_targets
                    BEGIN SELECT RAISE(ABORT, 'prediction targets are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS prediction_targets_no_delete
                    BEFORE DELETE ON prediction_targets
                    BEGIN SELECT RAISE(ABORT, 'prediction targets are immutable'); END;
                """)
                columns = {row[1] for row in conn.execute("PRAGMA table_info(validation_runs)")}
                for name in ("result_json", "dataset_hash", "config_hash"):
                    if name not in columns:
                        conn.execute(f"ALTER TABLE validation_runs ADD COLUMN {name} TEXT")
                conn.commit()
            finally:
                conn.close()

    def save_target(self, observation_id, target):
        values = (
            observation_id, target["horizon_sessions"], target["target_version"], target["entry_date"],
            target["label_end_date"], target["outcome_date"], target["outcome"],
            target["target_before_stop"], target["gross_return"], target["net_return"],
            target["benchmark_return"], target["excess_return"], target["positive_excess"], target["cost_bps"],
        )
        conn = self._connect()
        try:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO prediction_targets(observation_id, horizon_sessions, target_version,
                    entry_date, label_end_date, outcome_date, outcome, target_before_stop, gross_return,
                    net_return, benchmark_return, excess_return, positive_excess, cost_bps)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, values)
            if cursor.rowcount == 0:
                existing = conn.execute("""
                    SELECT observation_id,horizon_sessions,target_version,entry_date,label_end_date,
                           outcome_date,outcome,target_before_stop,gross_return,net_return,
                           benchmark_return,excess_return,positive_excess,cost_bps
                    FROM prediction_targets
                    WHERE observation_id=? AND horizon_sessions=? AND target_version=?
                """, (observation_id, target["horizon_sessions"], target["target_version"])).fetchone()
                if canonical_target(existing) != canonical_target(values):
                    raise ValueError("Matured target is immutable and conflicts with existing evidence")
            conn.commit()
        finally:
            conn.close()

    def pending_observations(self, horizon_sessions: int, limit=25) -> list[dict]:
        """Completed scanner signals that do not yet have this horizon label."""
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT o.observation_id, o.as_of_date, o.instrument_key, o.trading_symbol,
                       o.entry, o.stop, o.target
                FROM scanner_observations o
                LEFT JOIN prediction_targets t ON t.observation_id=o.observation_id
                    AND t.horizon_sessions=? AND t.target_version=?
                WHERE o.stage2_pass=1 AND o.entry IS NOT NULL AND o.stop IS NOT NULL
                    AND o.target IS NOT NULL AND t.observation_id IS NULL
                ORDER BY o.as_of_date, o.instrument_key LIMIT ?
            """, (int(horizon_sessions), TARGET_VERSION, int(limit))).fetchall()
        finally:
            conn.close()
        names = ["observation_id", "as_of_date", "instrument_key", "trading_symbol", "entry", "stop", "target"]
        return [dict(zip(names, row)) for row in rows]

    def evidence_summary(self) -> dict:
        conn = self._connect()
        try:
            observations = conn.execute("SELECT COUNT(*) FROM scanner_observations").fetchone()[0]
            targets = conn.execute("SELECT COUNT(*) FROM prediction_targets").fetchone()[0]
            validated = conn.execute("SELECT COUNT(*) FROM validation_runs WHERE status='VALIDATED'").fetchone()[0]
            latest = conn.execute("SELECT created_at, status, status_reason, metrics_json FROM validation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        return {"observations": int(observations), "targets": int(targets), "validated_runs": int(validated),
                "latest": ({"created_at": latest[0], "status": latest[1], "reason": latest[2],
                            "metrics": json.loads(latest[3])} if latest else None)}

    def validation_dataset(self, horizon_sessions: int) -> pd.DataFrame:
        conn = self._connect()
        try:
            frame = pd.read_sql_query("""
                SELECT o.observation_id, o.as_of_date, o.instrument_key, o.trading_symbol,
                       o.strategy_version, o.score, o.universe_snapshot_date, o.feature_json,
                       t.label_end_date, t.target_before_stop, t.net_return, t.benchmark_return,
                       t.excess_return
                FROM scanner_observations o
                JOIN prediction_targets t ON t.observation_id=o.observation_id
                JOIN pit_universe_snapshots u ON u.snapshot_date=o.universe_snapshot_date
                WHERE o.stage1_pass=1 AND o.stage2_pass=1 AND o.score IS NOT NULL
                  AND t.horizon_sessions=? AND t.target_version=? AND u.is_complete=1
                ORDER BY o.as_of_date, o.instrument_key
            """, conn, params=(int(horizon_sessions), TARGET_VERSION))
        finally:
            conn.close()
        if frame.empty:
            frame["market_regime"] = pd.Series(dtype="object")
            frame.attrs.update({
                "pit_verified": True, "costs_applied": True,
                "strategy_version": STRATEGY_VERSION, "target_version": TARGET_VERSION,
                "horizon_sessions": int(horizon_sessions),
            })
            return frame
        def regime_from_features(value):
            try:
                return (json.loads(value or "{}") or {}).get("market_regime")
            except (TypeError, ValueError, json.JSONDecodeError):
                return None
        frame["market_regime"] = frame["feature_json"].map(regime_from_features)
        frame = frame.drop(columns=["feature_json"])
        frame.attrs.update({
            "pit_verified": True, "costs_applied": True,
            "strategy_version": STRATEGY_VERSION, "target_version": TARGET_VERSION,
            "horizon_sessions": int(horizon_sessions),
        })
        return frame

    def load_validation_run(self, run_id: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT run_id,created_at,strategy_version,target_version,horizon_sessions,status,result_json "
                "FROM validation_runs WHERE run_id=?", (str(run_id),),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "run_id": row[0], "created_at": row[1], "strategy_version": row[2],
            "target_version": row[3], "horizon_sessions": int(row[4]),
            "status": row[5], "result": json.loads(row[6] or "{}"),
        }

    def latest_validated_run(self, *, strategy_version: str, target_version: str,
                             horizon_sessions: int) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT run_id FROM validation_runs WHERE strategy_version=? AND target_version=? "
                "AND horizon_sessions=? AND status='VALIDATED' ORDER BY created_at DESC LIMIT 1",
                (str(strategy_version), str(target_version), int(horizon_sessions)),
            ).fetchone()
        finally:
            conn.close()
        return self.load_validation_run(row[0]) if row else None

    def save_validation_run(self, result, horizon_sessions, strategy_version=STRATEGY_VERSION,
                            dataset: pd.DataFrame | None = None) -> str:
        created_at = dt.datetime.now(dt.timezone.utc).isoformat()
        material = json.dumps({"created_at": created_at, "strategy": strategy_version,
                               "horizon": horizon_sessions}, sort_keys=True)
        run_id = hashlib.sha256(material.encode()).hexdigest()
        result_json = json.dumps(result, sort_keys=True, default=str, allow_nan=False)
        dataset_hash = None
        if isinstance(dataset, pd.DataFrame):
            dataset_hash = hashlib.sha256(
                pd.util.hash_pandas_object(dataset, index=True).values.tobytes()
            ).hexdigest()
        config_hash = hashlib.sha256(json.dumps({
            "policy": result.get("policy") or result.get("development", {}).get("policy"),
            "holdout_fraction": result.get("holdout_fraction"),
            "embargo_sessions": result.get("embargo_sessions"),
            "experiment_trials": result.get("experiment_trials"),
        }, sort_keys=True, default=str).encode()).hexdigest()
        conn = self._connect()
        try:
            conn.execute("""
                INSERT INTO validation_runs(run_id, created_at, strategy_version, target_version,
                    horizon_sessions, training_samples, oos_samples, metrics_json, model_json,
                    status, status_reason, result_json, dataset_hash, config_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, created_at, strategy_version, TARGET_VERSION, int(horizon_sessions),
                  int(result.get("training_samples", 0)), int(result.get("oos_samples", 0)),
                  json.dumps(result.get("metrics", {}), sort_keys=True),
                  json.dumps({"model": result.get("model"), "return_quantiles": result.get("return_quantiles"),
                              "policy": result.get("policy"), "folds": result.get("folds")}, sort_keys=True),
                  result.get("status", "INSUFFICIENT_EVIDENCE"), result.get("reason", "Unknown"),
                  result_json, dataset_hash, config_hash))
            conn.commit()
        finally:
            conn.close()
        return run_id
