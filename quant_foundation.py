"""Advanced quantitative governance, execution, uncertainty and risk controls.

This module contains deterministic, testable contracts.  It does not claim
predictive skill: probability-dependent outputs remain unavailable until the
supplied calibration evidence passes the configured production policy.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

import trade_contracts


@dataclass(frozen=True)
class EvidencePolicy:
    minimum_oos_samples: int = 500
    minimum_class_samples: int = 75
    minimum_observation_days: int = 60
    maximum_ece: float = 0.08
    minimum_brier_skill: float = 0.02
    minimum_probability: float = 0.60
    maximum_feature_age_seconds: int = 120
    maximum_clock_skew_seconds: int = 2
    minimum_pit_coverage: float = 0.90


@dataclass(frozen=True)
class ExecutionPolicy:
    minimum_net_reward_risk: float = 2.0
    minimum_conservative_ev_bps: float = 5.0
    maximum_spread_bps: float = 80.0
    maximum_participation_rate: float = 0.02
    maximum_quote_age_seconds: int = 5
    residual_uncertainty_cost_bps: float = 5.0


@dataclass(frozen=True)
class PortfolioRiskPolicy:
    maximum_position_weight: float = 0.20
    maximum_sector_weight: float = 0.30
    maximum_daily_expected_shortfall: float = 0.03
    maximum_annualized_volatility: float = 0.25
    maximum_drawdown: float = 0.15
    maximum_marginal_risk_share: float = 0.35
    maximum_expiry_weight: float = 0.35
    maximum_absolute_net_delta: float = 0.50
    maximum_gamma_one_percent_loss: float = 0.05
    maximum_vega_one_point_loss: float = 0.05
    maximum_daily_loss: float = 0.03
    maximum_weekly_loss: float = 0.06
    covariance_shrinkage: float = 0.25
    kelly_fraction: float = 0.25
    maximum_fractional_kelly_weight: float = 0.10


@dataclass(frozen=True)
class ValidationPolicy:
    folds: int = 5
    embargo_sessions: int = 20
    final_holdout_fraction: float = 0.15
    bootstrap_samples: int = 1000
    bootstrap_block_length: int = 10
    confidence_level: float = 0.95
    minimum_history_sessions: int = 500
    maximum_feature_psi: float = 0.20
    maximum_calibration_decay: float = 0.05


@dataclass(frozen=True)
class AdvancedQuantConfig:
    version: str = "advanced-governance-v1"
    evidence: EvidencePolicy = field(default_factory=EvidencePolicy)
    execution: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    portfolio: PortfolioRiskPolicy = field(default_factory=PortfolioRiskPolicy)
    validation: ValidationPolicy = field(default_factory=ValidationPolicy)

    def public_dict(self) -> dict:
        return asdict(self)


PRODUCTION_QUANT_CONFIG = AdvancedQuantConfig()


def _timestamp(value) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def validate_point_in_time_features(
    decision_at,
    features: Mapping[str, Mapping],
    *,
    universe_observed_at=None,
    universe_effective_at=None,
    pit_coverage=1.0,
    policy: EvidencePolicy = EvidencePolicy(),
) -> dict:
    """Fail closed when any feature was unavailable at the decision timestamp."""
    decision = _timestamp(decision_at)
    failures, warnings, checked = [], [], 0
    skew = pd.Timedelta(seconds=max(int(policy.maximum_clock_skew_seconds), 0))
    default_age = pd.Timedelta(seconds=max(int(policy.maximum_feature_age_seconds), 0))

    if float(pit_coverage) < policy.minimum_pit_coverage:
        failures.append({"code": "PIT_COVERAGE", "detail": f"coverage={float(pit_coverage):.3f}"})
    for label, value in (("universe observed", universe_observed_at), ("universe effective", universe_effective_at)):
        if value is not None and _timestamp(value) > decision + skew:
            failures.append({"code": "FUTURE_UNIVERSE", "detail": f"{label} timestamp is after decision"})

    for name, observation in features.items():
        checked += 1
        if not isinstance(observation, Mapping):
            failures.append({"feature": name, "code": "MISSING_LINEAGE", "detail": "feature metadata is not a mapping"})
            continue
        available_at = observation.get("available_at") or observation.get("observed_at")
        source = str(observation.get("source") or "").strip()
        if available_at is None or not source:
            failures.append({"feature": name, "code": "MISSING_LINEAGE", "detail": "source and available_at are required"})
            continue
        available = _timestamp(available_at)
        if available > decision + skew:
            failures.append({"feature": name, "code": "LOOKAHEAD", "detail": "feature was not available at decision time"})
            continue
        maximum_age = observation.get("maximum_age_seconds")
        allowed_age = pd.Timedelta(seconds=float(maximum_age)) if maximum_age is not None else default_age
        age = decision - available
        if age > allowed_age:
            failures.append({"feature": name, "code": "STALE", "detail": f"age_seconds={age.total_seconds():.1f}"})
        effective_at = observation.get("effective_at")
        if effective_at is not None and _timestamp(effective_at) > decision + skew:
            failures.append({"feature": name, "code": "FUTURE_EFFECTIVE_DATE", "detail": "effective timestamp is after decision"})
        if observation.get("revised") and not observation.get("original_release_at"):
            warnings.append({"feature": name, "code": "REVISION_LINEAGE", "detail": "revised value lacks original release timestamp"})
    return {
        "status": "PASS" if not failures else "NO_TRADE",
        "decision_at": decision.isoformat(),
        "features_checked": checked,
        "pit_coverage": float(pit_coverage),
        "failures": failures,
        "warnings": warnings,
    }


def calibration_evidence_status(evidence: Mapping | None, policy: EvidencePolicy = EvidencePolicy()) -> dict:
    """Validate evidence without converting rule confidence into probability."""
    if not evidence:
        return {"usable": False, "reason": "Calibrated probability is unavailable"}
    required = {"probability", "oos_samples", "positive_samples", "negative_samples", "ece", "brier", "baseline_brier", "model_version"}
    missing = sorted(required - set(evidence))
    if missing:
        return {"usable": False, "reason": f"Calibration evidence is incomplete: {', '.join(missing)}"}
    probability = float(evidence["probability"])
    brier = float(evidence["brier"])
    baseline = float(evidence["baseline_brier"])
    brier_skill = 1.0 - brier / baseline if baseline > 0 else -math.inf
    checks = [
        (str(evidence.get("status", "")).upper() not in {"VALIDATED", "PASS"}, "Model has not passed validation"),
        (int(evidence["oos_samples"]) < policy.minimum_oos_samples, "Insufficient out-of-sample samples"),
        (min(int(evidence["positive_samples"]), int(evidence["negative_samples"])) < policy.minimum_class_samples, "Insufficient class samples"),
        (int(evidence.get("observation_days", 0)) < policy.minimum_observation_days, "Insufficient observation days"),
        (float(evidence["ece"]) > policy.maximum_ece, "Calibration error exceeds policy"),
        (brier_skill < policy.minimum_brier_skill, "Brier skill does not beat policy"),
        (not 0.0 < probability < 1.0, "Probability must be strictly between zero and one"),
        (probability < policy.minimum_probability, "Probability is below the production threshold"),
    ]
    for failed, reason in checks:
        if failed:
            return {"usable": False, "reason": reason, "brier_skill": brier_skill}
    lower = float(evidence.get("probability_interval_low", probability))
    upper = float(evidence.get("probability_interval_high", probability))
    if not 0.0 <= lower <= probability <= upper <= 1.0:
        return {"usable": False, "reason": "Probability interval is invalid", "brier_skill": brier_skill}
    return {
        "usable": True,
        "reason": "Calibration evidence passed",
        "probability": probability,
        "conservative_probability": lower,
        "probability_interval": [lower, upper],
        "brier_skill": brier_skill,
        "model_version": str(evidence["model_version"]),
    }


def executable_expected_value(
    *,
    entry,
    stop,
    target,
    direction="long",
    quantity=1,
    round_trip_cost_bps=0.0,
    calibration_evidence: Mapping | None = None,
    residual_cost_bps=None,
    config: AdvancedQuantConfig = PRODUCTION_QUANT_CONFIG,
) -> dict:
    """Cost-adjusted conservative EV; unavailable until calibration passes."""
    trade_math = trade_contracts.calculate_trade_math(
        entry, stop, target, direction=direction,
        round_trip_cost_bps=round_trip_cost_bps,
        minimum_ratio=config.execution.minimum_net_reward_risk,
    )
    status = calibration_evidence_status(calibration_evidence, config.evidence)
    base = {
        "status": "UNAVAILABLE",
        "action": "NO_TRADE",
        "reason": status["reason"],
        "trade_math": trade_math,
        "probability": None,
        "conservative_probability": None,
        "expected_value_per_unit": None,
        "expected_value_total": None,
        "expected_value_bps": None,
    }
    if not status["usable"]:
        return base
    probability = float(status["probability"])
    conservative_probability = float(status["conservative_probability"])
    residual_bps = (
        config.execution.residual_uncertainty_cost_bps
        if residual_cost_bps is None else max(float(residual_cost_bps), 0.0)
    )
    residual_cost = float(entry) * residual_bps / 10_000.0
    net_win = float(trade_math["net_reward"])
    net_loss = float(trade_math["net_risk"])
    ev = conservative_probability * net_win - (1.0 - conservative_probability) * net_loss - residual_cost
    ev_bps = ev / float(entry) * 10_000.0
    gate_failures = []
    if not trade_math["passes_gate"]:
        gate_failures.append("Net reward/risk is below policy")
    if ev_bps < config.execution.minimum_conservative_ev_bps:
        gate_failures.append("Conservative expected value is below policy")
    return {
        **base,
        "status": "PASS" if not gate_failures else "NO_TRADE",
        "action": "TRADE" if not gate_failures else "NO_TRADE",
        "reason": "All executable-value gates passed" if not gate_failures else "; ".join(gate_failures),
        "probability": probability,
        "conservative_probability": conservative_probability,
        "probability_interval": status["probability_interval"],
        "model_version": status["model_version"],
        "brier_skill": status["brier_skill"],
        "expected_value_per_unit": ev,
        "expected_value_total": ev * max(int(quantity), 0),
        "expected_value_bps": ev_bps,
        "residual_cost_per_unit": residual_cost,
    }


def order_book_features(bids: Sequence[Mapping], asks: Sequence[Mapping], *, reference_price=None) -> dict:
    """Deterministic level-2 liquidity features; returns no values for invalid books."""
    def levels(source):
        parsed = []
        for row in source or ():
            price = row.get("price", row.get("bidP", row.get("askP")))
            quantity = row.get("quantity", row.get("bidQ", row.get("askQ")))
            try:
                price, quantity = float(price), float(quantity)
            except (TypeError, ValueError):
                continue
            if price > 0 and quantity >= 0 and np.isfinite(price) and np.isfinite(quantity):
                parsed.append((price, quantity))
        return parsed

    bid_levels, ask_levels = levels(bids), levels(asks)
    if not bid_levels or not ask_levels:
        return {"status": "UNAVAILABLE", "reason": "Both bid and ask depth are required"}
    bid_levels.sort(key=lambda item: item[0], reverse=True)
    ask_levels.sort(key=lambda item: item[0])
    best_bid, bid_q = bid_levels[0]
    best_ask, ask_q = ask_levels[0]
    if best_ask <= best_bid:
        return {"status": "INVALID", "reason": "Crossed or locked order book"}
    mid = (best_bid + best_ask) / 2.0
    denominator = bid_q + ask_q
    microprice = (best_ask * bid_q + best_bid * ask_q) / denominator if denominator > 0 else mid
    bid_depth = sum(quantity for _, quantity in bid_levels)
    ask_depth = sum(quantity for _, quantity in ask_levels)
    total_depth = bid_depth + ask_depth
    depth_imbalance = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0.0
    queue_imbalance = (bid_q - ask_q) / denominator if denominator > 0 else 0.0
    reference = float(reference_price or mid)
    return {
        "status": "PASS",
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread": best_ask - best_bid,
        "spread_bps": (best_ask - best_bid) / max(reference, 1e-12) * 10_000.0,
        "microprice": microprice,
        "microprice_edge_bps": (microprice - mid) / max(mid, 1e-12) * 10_000.0,
        "queue_imbalance": queue_imbalance,
        "depth_imbalance": depth_imbalance,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "levels_used": min(len(bid_levels), len(ask_levels)),
    }


def options_surface_features(chain: pd.DataFrame, *, spot, minimum_points=7) -> dict:
    """Summarise IV skew/curvature/term structure on normalized coordinates.

    Expected columns are ``strike``, ``iv`` and ``dte``; ``delta`` and
    ``option_type`` are optional.  Outputs are descriptive evidence only until
    their incremental out-of-sample value has been validated.
    """
    required = {"strike", "iv", "dte"}
    if not required.issubset(chain.columns):
        return {"status": "UNAVAILABLE", "reason": f"Required columns: {sorted(required)}"}
    frame = chain.copy()
    for column in required | ({"delta"} if "delta" in frame else set()):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(required))
    frame = frame[(frame["strike"] > 0) & (frame["dte"] > 0) & (frame["iv"] > 0)]
    if frame["iv"].median() > 3.0:
        frame["iv"] = frame["iv"] / 100.0
    frame = frame[(frame["iv"] > 0.001) & (frame["iv"] < 5.0)]
    if len(frame) < int(minimum_points) or float(spot) <= 0:
        return {"status": "UNAVAILABLE", "reason": "Insufficient valid option-surface points"}
    frame["log_moneyness"] = np.log(frame["strike"] / float(spot))
    nearest_dte = float(frame.loc[frame["dte"].idxmin(), "dte"])
    near = frame[frame["dte"] == nearest_dte].sort_values("log_moneyness")
    if len(near) < 3:
        return {"status": "UNAVAILABLE", "reason": "Nearest expiry lacks enough strikes"}
    polynomial = np.polyfit(near["log_moneyness"], near["iv"], deg=2)
    atm_index = near["log_moneyness"].abs().idxmin()
    atm_iv = float(near.loc[atm_index, "iv"])
    atm_by_dte = []
    for dte, group in frame.groupby("dte"):
        idx = group["log_moneyness"].abs().idxmin()
        atm_by_dte.append((float(dte), float(group.loc[idx, "iv"])))
    term_slope = None
    if len(atm_by_dte) >= 2:
        x = np.sqrt(np.asarray([item[0] for item in atm_by_dte]) / 365.0)
        y = np.asarray([item[1] for item in atm_by_dte])
        term_slope = float(np.polyfit(x, y, deg=1)[0])
    risk_reversal = None
    if "delta" in frame and "option_type" in frame:
        calls = frame[frame["option_type"].astype(str).str.upper().str.startswith("C")]
        puts = frame[frame["option_type"].astype(str).str.upper().str.startswith("P")]
        if not calls.empty and not puts.empty:
            call_idx = (calls["delta"].abs() - 0.25).abs().idxmin()
            put_idx = (puts["delta"].abs() - 0.25).abs().idxmin()
            risk_reversal = float(calls.loc[call_idx, "iv"] - puts.loc[put_idx, "iv"])
    return {
        "status": "PASS",
        "points": int(len(frame)),
        "nearest_dte": nearest_dte,
        "atm_iv": atm_iv,
        "skew_slope": float(polynomial[1]),
        "smile_curvature": float(polynomial[0]),
        "term_structure_slope": term_slope,
        "risk_reversal_25d": risk_reversal,
        "units": "decimal volatility",
        "production_score_eligible": False,
    }


def market_breadth_features(frame: pd.DataFrame) -> dict:
    """Cross-sectional breadth with explicit denominator and missingness."""
    required = {"close", "previous_close"}
    if not required.issubset(frame.columns):
        return {"status": "UNAVAILABLE", "reason": f"Required columns: {sorted(required)}"}
    data = frame.copy()
    numeric = [column for column in ("close", "previous_close", "sma20", "sma50", "sma200") if column in data]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    eligible = data.dropna(subset=["close", "previous_close"])
    eligible = eligible[(eligible["close"] > 0) & (eligible["previous_close"] > 0)]
    if eligible.empty:
        return {"status": "UNAVAILABLE", "reason": "No valid breadth constituents"}
    change = eligible["close"] - eligible["previous_close"]
    advancing, declining, unchanged = int((change > 0).sum()), int((change < 0).sum()), int((change == 0).sum())
    result = {
        "status": "PASS",
        "eligible": int(len(eligible)),
        "input_rows": int(len(frame)),
        "coverage": float(len(eligible) / max(len(frame), 1)),
        "advancing": advancing,
        "declining": declining,
        "unchanged": unchanged,
        "advance_decline_ratio": float(advancing / max(declining, 1)),
        "advance_decline_net_pct": float((advancing - declining) / len(eligible)),
    }
    for window in (20, 50, 200):
        column = f"sma{window}"
        if column in eligible:
            valid = eligible.dropna(subset=[column])
            result[f"pct_above_sma{window}"] = (
                float((valid["close"] > valid[column]).mean()) if len(valid) else None
            )
    return result


def execution_quality_gate(
    *,
    spread_bps,
    order_value,
    average_daily_value,
    quote_age_seconds,
    market_depth_value=None,
    policy: ExecutionPolicy = ExecutionPolicy(),
) -> dict:
    """Liquidity gate; intentionally reports no fill probability without a fitted model."""
    participation = max(float(order_value or 0.0), 0.0) / max(float(average_daily_value or 0.0), 1.0)
    depth_participation = None
    if market_depth_value is not None:
        depth_participation = max(float(order_value or 0.0), 0.0) / max(float(market_depth_value), 1.0)
    failures = []
    if float(spread_bps) > policy.maximum_spread_bps:
        failures.append("Spread exceeds policy")
    if participation > policy.maximum_participation_rate:
        failures.append("Order participation exceeds policy")
    if float(quote_age_seconds) > policy.maximum_quote_age_seconds:
        failures.append("Quote is stale")
    if depth_participation is not None and depth_participation > 1.0:
        failures.append("Visible market depth cannot absorb the order")
    return {
        "status": "PASS" if not failures else "NO_TRADE",
        "failures": failures,
        "participation_rate": participation,
        "visible_depth_participation": depth_participation,
        "fill_probability": None,
        "fill_probability_reason": "A calibrated fill model has not been validated",
    }


def historical_expected_shortfall(returns, confidence=0.975) -> dict:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 30:
        return {"status": "UNAVAILABLE", "reason": "At least 30 returns are required"}
    confidence = float(np.clip(confidence, 0.5, 0.999))
    cutoff = float(np.quantile(values, 1.0 - confidence))
    tail = values[values <= cutoff]
    return {
        "status": "PASS",
        "confidence": confidence,
        "var_loss": max(-cutoff, 0.0),
        "expected_shortfall_loss": max(-float(tail.mean()), 0.0),
        "tail_observations": int(len(tail)),
        "samples": int(len(values)),
    }


def shrinkage_covariance(returns: pd.DataFrame, shrinkage=0.25) -> pd.DataFrame:
    clean = returns.apply(pd.to_numeric, errors="coerce").dropna(how="all")
    if clean.shape[0] < 20 or clean.shape[1] == 0:
        raise ValueError("At least 20 observations and one asset are required")
    sample = clean.cov(min_periods=20).fillna(0.0)
    diagonal = pd.DataFrame(np.diag(np.diag(sample)), index=sample.index, columns=sample.columns)
    strength = float(np.clip(shrinkage, 0.0, 1.0))
    return (1.0 - strength) * sample + strength * diagonal


def portfolio_risk_report(
    returns: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    sectors: Mapping[str, str] | None = None,
    expiries: Mapping[str, str] | None = None,
    greek_exposures: Mapping[str, Mapping[str, float]] | None = None,
    stress_scenarios: Mapping[str, Mapping[str, float]] | None = None,
    policy: PortfolioRiskPolicy = PortfolioRiskPolicy(),
) -> dict:
    names = [name for name in returns.columns if name in weights]
    if not names:
        return {"status": "UNAVAILABLE", "reason": "No weighted return series are available"}
    vector = np.asarray([float(weights[name]) for name in names], dtype=float)
    if not np.all(np.isfinite(vector)) or np.abs(vector).sum() <= 0:
        return {"status": "UNAVAILABLE", "reason": "Portfolio weights are invalid"}
    covariance = shrinkage_covariance(returns[names], policy.covariance_shrinkage)
    covariance_values = covariance.to_numpy(dtype=float)
    variance = max(float(vector @ covariance_values @ vector), 0.0)
    daily_volatility = math.sqrt(variance)
    annualized_volatility = daily_volatility * math.sqrt(252.0)
    component = covariance_values @ vector
    marginal_risk = vector * component / variance if variance > 1e-16 else np.zeros_like(vector)
    portfolio_returns = returns[names].fillna(0.0).to_numpy(dtype=float) @ vector
    es = historical_expected_shortfall(portfolio_returns)
    curve = np.cumprod(1.0 + portfolio_returns)
    running_max = np.maximum.accumulate(curve)
    drawdowns = curve / np.maximum(running_max, 1e-12) - 1.0
    maximum_drawdown = max(-float(np.min(drawdowns)), 0.0)
    sector_weights = {}
    expiry_weights = {}
    for name, weight in zip(names, vector):
        sector = (sectors or {}).get(name, "Unclassified")
        sector_weights[sector] = sector_weights.get(sector, 0.0) + abs(float(weight))
        expiry = (expiries or {}).get(name)
        if expiry:
            expiry_weights[str(expiry)] = expiry_weights.get(str(expiry), 0.0) + abs(float(weight))
    aggregate_greeks = {"delta": 0.0, "gamma_1pct": 0.0, "vega_1point": 0.0}
    for name, weight in zip(names, vector):
        exposure = (greek_exposures or {}).get(name, {})
        for greek in aggregate_greeks:
            aggregate_greeks[greek] += float(weight) * float(exposure.get(greek, 0.0))
    stresses = {}
    for scenario, shocks in (stress_scenarios or {}).items():
        pnl = sum(float(weights.get(name, 0.0)) * float(shocks.get(name, 0.0)) for name in names)
        stresses[str(scenario)] = pnl
    failures = []
    if np.max(np.abs(vector)) > policy.maximum_position_weight + 1e-12:
        failures.append("Position-weight limit exceeded")
    if sector_weights and max(sector_weights.values()) > policy.maximum_sector_weight + 1e-12:
        failures.append("Sector-weight limit exceeded")
    if expiry_weights and max(expiry_weights.values()) > policy.maximum_expiry_weight + 1e-12:
        failures.append("Expiry-weight limit exceeded")
    if abs(aggregate_greeks["delta"]) > policy.maximum_absolute_net_delta:
        failures.append("Net-delta limit exceeded")
    if abs(aggregate_greeks["gamma_1pct"]) > policy.maximum_gamma_one_percent_loss:
        failures.append("Gamma stress limit exceeded")
    if abs(aggregate_greeks["vega_1point"]) > policy.maximum_vega_one_point_loss:
        failures.append("Vega stress limit exceeded")
    if annualized_volatility > policy.maximum_annualized_volatility:
        failures.append("Annualized volatility limit exceeded")
    if es.get("status") == "PASS" and es["expected_shortfall_loss"] > policy.maximum_daily_expected_shortfall:
        failures.append("Expected-shortfall limit exceeded")
    if maximum_drawdown > policy.maximum_drawdown:
        failures.append("Drawdown limit exceeded")
    if len(marginal_risk) and float(np.max(marginal_risk)) > policy.maximum_marginal_risk_share:
        failures.append("Marginal-risk concentration exceeded")
    return {
        "status": "PASS" if not failures else "NO_TRADE",
        "failures": failures,
        "weights": dict(zip(names, vector.tolist())),
        "sector_weights": sector_weights,
        "expiry_weights": expiry_weights,
        "greek_exposures": aggregate_greeks,
        "daily_volatility": daily_volatility,
        "annualized_volatility": annualized_volatility,
        "expected_shortfall": es,
        "maximum_drawdown": maximum_drawdown,
        "marginal_risk_share": dict(zip(names, marginal_risk.tolist())),
        "stress_returns": stresses,
        "covariance": covariance.to_dict(),
    }


def system_kill_switch(
    *,
    feed_age_seconds,
    broker_position_mismatch=False,
    daily_pnl_fraction=0.0,
    weekly_pnl_fraction=0.0,
    provider_available=True,
    exchange_open=True,
    event_restriction=False,
    policy: PortfolioRiskPolicy = PortfolioRiskPolicy(),
    maximum_feed_age_seconds=5,
) -> dict:
    """Central fail-closed operational gate used before any new order."""
    reasons = []
    if float(feed_age_seconds) > float(maximum_feed_age_seconds):
        reasons.append("Market data is stale")
    if bool(broker_position_mismatch):
        reasons.append("Broker position reconciliation failed")
    if float(daily_pnl_fraction) <= -abs(policy.maximum_daily_loss):
        reasons.append("Daily loss limit reached")
    if float(weekly_pnl_fraction) <= -abs(policy.maximum_weekly_loss):
        reasons.append("Weekly loss limit reached")
    if not provider_available:
        reasons.append("Required provider is unavailable")
    if not exchange_open:
        reasons.append("Exchange is not open for new entries")
    if event_restriction:
        reasons.append("Event-risk restriction is active")
    return {
        "status": "HALT" if reasons else "PASS",
        "allow_new_entries": not reasons,
        "reasons": reasons,
        "exit_management_remains_enabled": True,
    }


def fractional_kelly_weight(
    probability,
    net_reward_risk,
    *,
    calibration_evidence: Mapping | None,
    policy: PortfolioRiskPolicy = PortfolioRiskPolicy(),
    evidence_policy: EvidencePolicy = EvidencePolicy(),
) -> dict:
    status = calibration_evidence_status(calibration_evidence, evidence_policy)
    if not status["usable"]:
        return {"status": "UNAVAILABLE", "weight": 0.0, "reason": status["reason"]}
    p = min(float(probability), float(status["conservative_probability"]))
    payoff = float(net_reward_risk)
    if payoff <= 0:
        return {"status": "UNAVAILABLE", "weight": 0.0, "reason": "Payoff ratio must be positive"}
    full_kelly = max((payoff * p - (1.0 - p)) / payoff, 0.0)
    weight = min(full_kelly * policy.kelly_fraction, policy.maximum_fractional_kelly_weight)
    return {
        "status": "PASS" if weight > 0 else "NO_TRADE",
        "weight": weight,
        "full_kelly": full_kelly,
        "fraction": policy.kelly_fraction,
        "probability_used": p,
        "reason": "Calibration-gated fractional Kelly" if weight > 0 else "Kelly edge is non-positive",
    }


def decision_transparency_report(
    *,
    decision_id,
    generated_at,
    instrument,
    model_version,
    supporting_factors: Sequence[Mapping],
    opposing_risks: Sequence[Mapping],
    gates: Sequence[Mapping],
    market_data: Mapping,
    uncertainty: Mapping | None = None,
    sensitivity: Mapping | None = None,
) -> dict:
    """Stable UI/report contract shared by every asset class."""
    normalized_gates = []
    for gate in gates:
        item = dict(gate)
        item["passed"] = bool(item.get("passed"))
        normalized_gates.append(item)
    return {
        "schema_version": 1,
        "decision_id": str(decision_id),
        "generated_at": _timestamp(generated_at).isoformat(),
        "instrument": str(instrument),
        "model_version": str(model_version),
        "actionable": bool(normalized_gates) and all(item["passed"] for item in normalized_gates),
        "supporting_factors": sorted(
            [dict(item) for item in supporting_factors],
            key=lambda item: abs(float(item.get("contribution", 0.0))), reverse=True,
        )[:3],
        "opposing_risks": sorted(
            [dict(item) for item in opposing_risks],
            key=lambda item: abs(float(item.get("contribution", 0.0))), reverse=True,
        )[:3],
        "gates": normalized_gates,
        "market_data": dict(market_data),
        "uncertainty": dict(uncertainty or {}),
        "sensitivity": dict(sensitivity or {}),
    }
