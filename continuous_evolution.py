"""Unified model, calibration, execution and governance decision contracts.

The module deliberately contains no provider or UI code.  It turns immutable
evidence packages into deterministic, fail-closed decisions that can be used by
the Streamlit application, scheduled jobs and CI acceptance tests.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

import trade_contracts
from prediction_validation import wilson_score_interval
from quant_foundation import calibration_evidence_status
from resilience_control_plane import SafetyFinding, SafetyState, canonical_hash


UTC = dt.timezone.utc


@dataclass(frozen=True)
class ContinuousEvolutionPolicy:
    minimum_production_models: int = 1
    maximum_model_probability_range: float = 0.15
    maximum_single_model_weight: float = 0.80
    minimum_conformal_samples: int = 500
    conformal_alpha: float = 0.10
    maximum_conformal_width: float = 0.35
    minimum_conformal_coverage: float = 0.88
    minimum_reliability_bin_samples: int = 30
    minimum_log_loss_skill: float = 0.01
    minimum_log_loss_improvement_ci_low: float = 0.0
    minimum_fill_oos_samples: int = 500
    maximum_fill_brier: float = 0.25
    maximum_fill_ece: float = 0.08
    minimum_fill_probability: float = 0.50
    minimum_claim_samples: int = 1000
    minimum_candidate_coverage: float = 0.05
    minimum_claim_wilson_lower: float = 0.99
    minimum_regime_samples: int = 100
    minimum_claim_regimes: int = 3


PRODUCTION_EVOLUTION_POLICY = ContinuousEvolutionPolicy()


def _finite(value, *, name: str, minimum=None, maximum=None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return result


def _aware(value, *, name: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a timezone-aware datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def evaluate_model_ensemble(
    predictions: Sequence[Mapping] | None,
    *,
    weights: Mapping[str, float] | None = None,
    selected_regime: str,
    expected_feature_schema_hash: str,
    decision_at=None,
    policy: ContinuousEvolutionPolicy = PRODUCTION_EVOLUTION_POLICY,
) -> dict:
    """Validate and combine only promoted production models.

    Deep, order-book, options-surface and order-flow specialists are retained in
    the returned shadow list until their individual promotion attestation is
    present.  This prevents an experimental specialist from influencing a live
    probability through an accidental configuration change.
    """
    now = _aware(decision_at or dt.datetime.now(UTC), name="decision_at")
    expected_hash = str(expected_feature_schema_hash or "").strip()
    failures, shadow, eligible = [], [], []
    if not expected_hash:
        failures.append("Expected feature-schema hash is missing")
    for raw in predictions or ():
        row = dict(raw)
        model_id = str(row.get("model_id") or "").strip()
        family = str(row.get("model_family") or "").strip().lower()
        role = str(row.get("role") or "").strip().upper()
        status = str(row.get("status") or "").strip().upper()
        mode = str(row.get("deployment_mode") or "SHADOW").strip().upper()
        specialist = family in {"deep_order_book", "deep_temporal", "options_surface", "order_flow"}
        production_candidate = role == "CHAMPION" and status == "ACTIVE" and mode == "PRODUCTION"
        if specialist and not bool(row.get("promotion_attested")):
            production_candidate = False
        if not production_candidate:
            shadow.append(model_id or family or "unidentified-model")
            continue
        try:
            probability = _finite(row.get("probability"), name=f"{model_id}.probability", minimum=0, maximum=1)
            inference_at = _aware(row.get("inference_at"), name=f"{model_id}.inference_at")
            feature_at = _aware(row.get("feature_at"), name=f"{model_id}.feature_at")
            max_age = _finite(row.get("maximum_feature_age_seconds", 5), name=f"{model_id}.maximum_feature_age_seconds", minimum=0)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if not model_id:
            failures.append("Production model id is missing")
        if not bool(row.get("artifact_signature_valid")):
            failures.append(f"{model_id} artifact signature is invalid")
        if not bool(row.get("calibrated")):
            failures.append(f"{model_id} output is not calibrated")
        if str(row.get("feature_schema_hash") or "") != expected_hash:
            failures.append(f"{model_id} feature schema mismatch")
        model_regime = str(row.get("regime") or "GLOBAL").strip().upper()
        if model_regime not in {"GLOBAL", str(selected_regime).strip().upper()}:
            failures.append(f"{model_id} is not approved for the selected regime")
        if feature_at > inference_at or inference_at > now:
            failures.append(f"{model_id} has invalid inference chronology")
        if (inference_at - feature_at).total_seconds() > max_age:
            failures.append(f"{model_id} used stale features")
        eligible.append({**row, "model_id": model_id, "model_family": family, "probability": probability})

    if len(eligible) < policy.minimum_production_models:
        failures.append("No sufficient promoted production models are available")
    if not any(row["model_family"] in {"logistic", "gam", "interpretable_baseline"} for row in eligible):
        failures.append("An interpretable production baseline is required")
    model_weights = dict(weights or {})
    parsed_weights = []
    for row in eligible:
        try:
            weight = _finite(model_weights.get(row["model_id"]), name=f"{row['model_id']}.weight", minimum=0)
        except ValueError as exc:
            failures.append(str(exc))
            weight = 0.0
        if weight > policy.maximum_single_model_weight and len(eligible) > 1:
            failures.append(f"{row['model_id']} weight exceeds concentration policy")
        parsed_weights.append(weight)
    total_weight = sum(parsed_weights)
    if eligible and total_weight <= 0:
        failures.append("Production model weights are missing or zero")
    probability_range = (
        max(row["probability"] for row in eligible) - min(row["probability"] for row in eligible)
        if eligible else None
    )
    if probability_range is not None and probability_range > policy.maximum_model_probability_range:
        failures.append("Production model disagreement exceeds policy")
    probability = (
        sum(row["probability"] * weight for row, weight in zip(eligible, parsed_weights)) / total_weight
        if eligible and total_weight > 0 else None
    )
    lineage = [{
        "model_id": row["model_id"], "model_family": row["model_family"],
        "version": str(row.get("version") or ""), "regime": str(row.get("regime") or "GLOBAL"),
        "artifact_hash": str(row.get("artifact_hash") or ""), "weight": parsed_weights[index],
    } for index, row in enumerate(eligible)]
    return {
        "status": "PASS" if not failures else "ABSTAIN",
        "probability": probability if not failures else None,
        "failures": sorted(set(failures)), "production_models": lineage,
        "shadow_models": shadow, "selected_regime": str(selected_regime),
        "probability_range": probability_range,
        "ensemble_hash": canonical_hash({"lineage": lineage, "schema": expected_hash, "regime": selected_regime}),
    }


def adaptive_conformal_interval(
    point_estimate,
    calibration_residuals,
    *,
    training_end,
    calibration_start,
    calibration_end,
    observed_coverage,
    alpha=None,
    policy: ContinuousEvolutionPolicy = PRODUCTION_EVOLUTION_POLICY,
) -> dict:
    """Build a chronological split-conformal interval with coverage gating."""
    failures = []
    try:
        point = _finite(point_estimate, name="point_estimate")
        train_end = _aware(training_end, name="training_end")
        cal_start = _aware(calibration_start, name="calibration_start")
        cal_end = _aware(calibration_end, name="calibration_end")
        coverage = _finite(observed_coverage, name="observed_coverage", minimum=0, maximum=1)
        alpha_value = _finite(policy.conformal_alpha if alpha is None else alpha, name="alpha", minimum=1e-6, maximum=0.5)
    except ValueError as exc:
        return {"status": "ABSTAIN", "failures": [str(exc)], "lower": None, "upper": None}
    residuals = np.asarray(calibration_residuals, dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    if len(residuals) < policy.minimum_conformal_samples:
        failures.append("Insufficient conformal calibration samples")
    if not train_end < cal_start <= cal_end:
        failures.append("Conformal calibration window overlaps training or is reversed")
    if coverage < policy.minimum_conformal_coverage:
        failures.append("Observed conformal coverage is below policy")
    if not len(residuals):
        return {"status": "ABSTAIN", "failures": failures or ["No finite residuals"], "lower": None, "upper": None}
    level = min(math.ceil((len(residuals) + 1) * (1 - alpha_value)) / len(residuals), 1.0)
    radius = float(np.quantile(np.abs(residuals), level, method="higher"))
    lower, upper = point - radius, point + radius
    if upper - lower > policy.maximum_conformal_width:
        failures.append("Conformal interval is wider than policy")
    return {
        "status": "PASS" if not failures else "ABSTAIN", "failures": failures,
        "lower": lower, "upper": upper, "width": upper - lower, "radius": radius,
        "samples": int(len(residuals)), "alpha": alpha_value, "observed_coverage": coverage,
        "window": {"training_end": train_end.isoformat(), "calibration_start": cal_start.isoformat(),
                   "calibration_end": cal_end.isoformat()},
    }


def validate_calibration_package(
    evidence: Mapping | None,
    *,
    expected_model_version: str | None = None,
    expected_ensemble_hash: str | None = None,
    policy: ContinuousEvolutionPolicy = PRODUCTION_EVOLUTION_POLICY,
) -> dict:
    """Require nested chronology, untouched holdout and reliable finite metrics."""
    context = {}
    if expected_model_version:
        context["model_version"] = expected_model_version
    if expected_ensemble_hash:
        context["ensemble_hash"] = expected_ensemble_hash
    base = calibration_evidence_status(evidence, expected_context=context or None)
    failures = [] if base.get("usable") else [str(base.get("reason") or "Calibration unavailable")]
    package = dict(evidence or {})
    for flag, reason in (
        ("nested_chronological", "Nested chronological calibration was not verified"),
        ("untouched_holdout", "Untouched chronological holdout was not verified"),
        ("pit_verified", "Point-in-time inputs were not verified"),
        ("costs_applied", "Executable costs were not applied"),
    ):
        if not package.get(flag):
            failures.append(reason)
    try:
        log_loss = _finite(package.get("log_loss"), name="log_loss", minimum=0)
        baseline_log_loss = _finite(
            package.get("baseline_log_loss"), name="baseline_log_loss", minimum=0,
        )
        log_loss_skill = _finite(package.get("log_loss_skill"), name="log_loss_skill")
        improvement_low = _finite(
            package.get("log_loss_improvement_ci_low"),
            name="log_loss_improvement_ci_low",
        )
        if log_loss >= baseline_log_loss:
            failures.append("Log loss does not beat the chronological base-rate model")
        if log_loss_skill < policy.minimum_log_loss_skill:
            failures.append("Log-loss skill is below policy")
        if improvement_low <= policy.minimum_log_loss_improvement_ci_low:
            failures.append("Paired log-loss improvement is not statistically established")
    except ValueError as exc:
        failures.append(str(exc))
    reliability = package.get("reliability")
    if not isinstance(reliability, Sequence) or isinstance(reliability, (str, bytes)) or not reliability:
        failures.append("Reliability-curve evidence is missing")
    else:
        for index, row in enumerate(reliability):
            try:
                count = int(_finite(row.get("count"), name=f"reliability[{index}].count", minimum=0))
                _finite(row.get("predicted"), name=f"reliability[{index}].predicted", minimum=0, maximum=1)
                _finite(row.get("actual"), name=f"reliability[{index}].actual", minimum=0, maximum=1)
            except (AttributeError, ValueError) as exc:
                failures.append(str(exc))
                continue
            if count < policy.minimum_reliability_bin_samples:
                failures.append("Reliability bin sample count is below policy")
    return {**base, "usable": not failures, "status": "PASS" if not failures else "ABSTAIN",
            "failures": sorted(set(failures))}


def validate_fill_model(evidence: Mapping | None,
                        policy: ContinuousEvolutionPolicy = PRODUCTION_EVOLUTION_POLICY) -> dict:
    """Validate a chronological fill/partial-fill model before EV can use it."""
    failures = []
    package = dict(evidence or {})
    try:
        probability = _finite(package.get("fill_probability"), name="fill_probability", minimum=0, maximum=1)
        low = _finite(package.get("fill_probability_low"), name="fill_probability_low", minimum=0, maximum=1)
        samples = int(_finite(package.get("oos_samples"), name="fill oos_samples", minimum=0))
        brier = _finite(package.get("brier"), name="fill brier", minimum=0)
        ece = _finite(package.get("ece"), name="fill ece", minimum=0)
    except ValueError as exc:
        return {"status": "ABSTAIN", "usable": False, "failures": [str(exc)], "fill_probability": None}
    if not package.get("chronological_oos"): failures.append("Fill model lacks chronological OOS evidence")
    if not package.get("partial_fills_modelled"): failures.append("Partial fills are not modelled")
    if samples < policy.minimum_fill_oos_samples: failures.append("Insufficient fill-model OOS samples")
    if brier > policy.maximum_fill_brier: failures.append("Fill-model Brier score exceeds policy")
    if ece > policy.maximum_fill_ece: failures.append("Fill-model ECE exceeds policy")
    if not 0 <= low <= probability <= 1: failures.append("Fill-probability interval is invalid")
    if low < policy.minimum_fill_probability: failures.append("Conservative fill probability is below policy")
    return {"status": "PASS" if not failures else "ABSTAIN", "usable": not failures,
            "failures": failures, "fill_probability": probability,
            "conservative_fill_probability": low, "model_version": str(package.get("model_version") or "")}


def executable_fill_adjusted_ev(
    *, entry, stop, target, direction, quantity, round_trip_cost_bps,
    target_probability, stop_probability, time_exit_probability,
    time_exit_return_per_unit, fill_evidence: Mapping | None,
    adverse_selection_bps=0.0,
    policy: ContinuousEvolutionPolicy = PRODUCTION_EVOLUTION_POLICY,
) -> dict:
    """Expected value over target, stop, time-exit and non-fill outcomes."""
    fill = validate_fill_model(fill_evidence, policy)
    if not fill["usable"]:
        return {"status": "ABSTAIN", "expected_value_per_order": None, "failures": fill["failures"]}
    try:
        trade = trade_contracts.calculate_trade_math(
            entry, stop, target, direction=direction, round_trip_cost_bps=round_trip_cost_bps,
        )
        probabilities = np.asarray([
            _finite(target_probability, name="target_probability", minimum=0, maximum=1),
            _finite(stop_probability, name="stop_probability", minimum=0, maximum=1),
            _finite(time_exit_probability, name="time_exit_probability", minimum=0, maximum=1),
        ])
        time_return = _finite(time_exit_return_per_unit, name="time_exit_return_per_unit")
        qty = int(_finite(quantity, name="quantity", minimum=1))
        adverse = _finite(adverse_selection_bps, name="adverse_selection_bps", minimum=0)
        entry_value = _finite(entry, name="entry", minimum=1e-12)
    except (ValueError, TypeError) as exc:
        return {"status": "ABSTAIN", "expected_value_per_order": None, "failures": [str(exc)]}
    if not math.isclose(float(probabilities.sum()), 1.0, rel_tol=0, abs_tol=1e-6):
        return {"status": "ABSTAIN", "expected_value_per_order": None,
                "failures": ["Conditional target/stop/time-exit probabilities must sum to one"]}
    conditional = (
        probabilities[0] * float(trade["net_reward"])
        - probabilities[1] * float(trade["net_risk"])
        + probabilities[2] * time_return
        - entry_value * adverse / 10_000.0
    )
    fill_probability = float(fill["conservative_fill_probability"])
    per_order = fill_probability * conditional * qty
    return {
        "status": "PASS" if per_order > 0 and trade["passes_gate"] else "NO_TRADE",
        "expected_value_per_filled_unit": conditional,
        "expected_value_per_order": per_order,
        "expected_value_bps_per_order": per_order / (entry_value * qty) * 10_000,
        "conservative_fill_probability": fill_probability,
        "non_fill_probability": 1.0 - fill_probability,
        "outcome_probabilities": {"target": probabilities[0], "stop": probabilities[1],
                                  "time_exit": probabilities[2]},
        "trade_math": trade,
        "failures": [] if per_order > 0 and trade["passes_gate"] else ["Fill-adjusted executable EV is not positive"],
    }


def predictive_correctness_claim(evidence: Mapping | None,
                                 policy: ContinuousEvolutionPolicy = PRODUCTION_EVOLUTION_POLICY) -> dict:
    """Prevent an unsupported 99% claim, including accuracy-by-abstention."""
    package = dict(evidence or {})
    failures = []
    try:
        samples = int(_finite(package.get("matured_actionable"), name="matured_actionable", minimum=0))
        successes = int(_finite(package.get("correct_predictions"), name="correct_predictions", minimum=0))
        candidates = int(_finite(package.get("candidate_count"), name="candidate_count", minimum=0))
        evaluated = int(_finite(package.get("evaluated_count"), name="evaluated_count", minimum=1))
    except ValueError as exc:
        return {"established": False, "claim": "99% not established", "failures": [str(exc)]}
    if successes > samples: failures.append("Correct predictions exceed matured actionable samples")
    coverage = candidates / evaluated
    lower, upper = wilson_score_interval(successes, samples)
    regimes = {str(k): int(v) for k, v in dict(package.get("regime_samples") or {}).items()}
    qualified_regimes = [name for name, count in regimes.items() if count >= policy.minimum_regime_samples]
    if samples < policy.minimum_claim_samples: failures.append("Fewer than 1,000 matured actionable observations")
    if coverage < policy.minimum_candidate_coverage: failures.append("Candidate coverage is below 5%")
    if not math.isfinite(lower) or lower < policy.minimum_claim_wilson_lower:
        failures.append("95% Wilson lower bound is below 0.99")
    if len(qualified_regimes) < policy.minimum_claim_regimes: failures.append("Major-regime evidence is insufficient")
    for flag, reason in (
        ("untouched_chronological_holdout", "Untouched chronological holdout is not verified"),
        ("pit_verified", "Point-in-time evidence is not verified"),
        ("executable_prices", "Executable prices are not verified"),
        ("full_costs_applied", "Full costs are not applied"),
        ("ledger_verified", "Decision ledger is not verified"),
    ):
        if not package.get(flag): failures.append(reason)
    established = not failures
    return {
        "established": established,
        "claim": "At least 99% predictive correctness independently established" if established else "99% not established",
        "failures": failures, "matured_actionable": samples,
        "observed_correctness": successes / samples if samples else None,
        "wilson_95": {"lower": lower, "upper": upper}, "candidate_coverage": coverage,
        "qualified_regimes": qualified_regimes,
    }


def unified_control_findings(*, pit, model, calibration, conformal, execution,
                             expected_value, portfolio, allocation, kill_switch,
                             ledger_status: Mapping | None = None) -> list[SafetyFinding]:
    """Map every quantitative control into the shared operational state machine."""
    findings: list[SafetyFinding] = []
    controls = (
        ("pit", pit, "PASS"), ("model", model, "PASS"),
        ("calibration", calibration, "PASS"), ("conformal", conformal, "PASS"),
        ("execution", execution, "PASS"), ("expected_value", expected_value, "PASS"),
        ("portfolio", portfolio, "PASS"), ("allocation", allocation, "PASS"),
        ("kill_switch", kill_switch, "PASS"),
    )
    for name, result, expected in controls:
        status = str((result or {}).get("status") or "UNAVAILABLE").upper()
        if status != expected:
            details = ((result or {}).get("failures") or (result or {}).get("reasons")
                       or [(result or {}).get("reason") or f"{name} evidence unavailable"])
            if not isinstance(details, Sequence) or isinstance(details, (str, bytes)):
                details = [str(details)]
            findings.append(SafetyFinding(name, f"{name.upper()}_{status}", "; ".join(map(str, details)), SafetyState.NO_TRADE))
    if ledger_status is not None:
        if ledger_status.get("signature_valid") is False:
            findings.append(SafetyFinding("ledger", "LEDGER_SIGNATURE_INVALID",
                                          "Ledger signing verification failed", SafetyState.EMERGENCY_STOP))
        elif ledger_status.get("chain_valid") is not True or ledger_status.get("append_durable") is not True:
            findings.append(SafetyFinding("ledger", "LEDGER_DURABILITY",
                                          "Ledger chain or durable append is not verified", SafetyState.READ_ONLY))
    return findings


def decision_evidence_bundle(*, instrument, decision_at, pit, model, calibration, conformal,
                             execution, expected_value, portfolio, allocation, kill_switch,
                             safety, claim) -> dict:
    """Small immutable summary; raw features and credentials are intentionally excluded."""
    payload = {
        "schema_version": 1, "instrument": str(instrument),
        "decision_at": _aware(decision_at, name="decision_at").isoformat(),
        "statuses": {
            "pit": pit.get("status"), "model": model.get("status"),
            "calibration": calibration.get("status"),
            "conformal": conformal.get("status"), "execution": execution.get("status"),
            "expected_value": expected_value.get("status"), "portfolio": portfolio.get("status"),
            "allocation": allocation.get("status"), "kill_switch": kill_switch.get("status"),
            "safety": safety.get("state"),
        },
        "lineage": {"ensemble_hash": model.get("ensemble_hash"),
                    "model_version": calibration.get("model_version")},
        "claim": claim.get("claim", "99% not established"),
        "correlation_id": safety.get("correlation_id"),
    }
    return {**payload, "decision_hash": canonical_hash(payload)}
