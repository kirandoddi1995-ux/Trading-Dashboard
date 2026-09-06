"""Build and use real chronological calibration artifacts.

Artifacts are created only from a validation run whose final untouched holdout
passed.  Creation does not promote or sign a model.  Runtime inference also
requires an injected cryptographic verifier and an ACTIVE champion record.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from live_evidence import aware_utc
from prediction_validation import chronological_holdout_split, wilson_score_interval
from resilience_control_plane import canonical_hash


CALIBRATION_ARTIFACT_SCHEMA = "calibration-artifact-v1"


def _finite(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _dataset_hash(frame: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest()


def _psi(reference, current, bins=10) -> float | None:
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    ref, cur = ref[np.isfinite(ref)], cur[np.isfinite(cur)]
    if len(ref) < 20 or len(cur) < 20:
        return None
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    rp = np.clip(np.histogram(ref, edges)[0] / len(ref), 1e-6, None)
    cp = np.clip(np.histogram(cur, edges)[0] / len(cur), 1e-6, None)
    return float(np.sum((cp - rp) * np.log(cp / rp)))


def build_calibration_artifact(
    result: Mapping[str, Any],
    dataset: pd.DataFrame,
    *,
    run_id: str,
    strategy_id: str,
    target_version: str,
    horizon_sessions: int,
    feature_schema_hash: str,
    asset_class: str,
    score_feature: str,
    valid_days: int = 30,
    created_at: dt.datetime | None = None,
) -> dict[str, Any]:
    """Create an unsigned candidate artifact from a passed untouched holdout."""
    if str(result.get("status") or "").upper() != "VALIDATED":
        raise ValueError("Only a VALIDATED chronological run can create an artifact")
    if not isinstance(dataset, pd.DataFrame) or dataset.empty:
        raise ValueError("The exact validation dataset is required")
    if dataset.attrs.get("pit_verified") is not True:
        raise ValueError("Dataset point-in-time provenance is not verified")
    if dataset.attrs.get("costs_applied") is not True:
        raise ValueError("Dataset executable-cost provenance is not verified")
    if str(dataset.attrs.get("strategy_version")) != str(strategy_id):
        raise ValueError("Dataset strategy context mismatch")
    if str(dataset.attrs.get("target_version")) != str(target_version):
        raise ValueError("Dataset target context mismatch")
    if int(dataset.attrs.get("horizon_sessions", -1)) != int(horizon_sessions):
        raise ValueError("Dataset horizon context mismatch")
    required = {"as_of_date", "label_end_date", "score", "target_before_stop"}
    if not required.issubset(dataset.columns):
        raise ValueError(f"Validation dataset is missing: {sorted(required - set(dataset.columns))}")

    model = dict(result.get("model") or {})
    intercept = _finite(model.get("intercept"), "model intercept")
    slope = _finite(model.get("slope"), "model slope")
    development, holdout = chronological_holdout_split(
        dataset,
        holdout_fraction=float(result.get("holdout_fraction", 0.15)),
        minimum_holdout_dates=20,
        embargo_sessions=int(result.get("embargo_sessions", 20)),
    )
    if development.empty or holdout.empty or len(holdout) != int(result.get("holdout_samples", -1)):
        raise ValueError("Untouched holdout cannot be reproduced from the archived dataset")
    scores = pd.to_numeric(holdout["score"], errors="coerce").to_numpy(dtype=float)
    outcomes = pd.to_numeric(holdout["target_before_stop"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(scores).all() or not np.isin(outcomes, [0.0, 1.0]).all():
        raise ValueError("Holdout scores and outcomes must be finite and binary")
    probabilities = 1.0 / (1.0 + np.exp(-np.clip(intercept + slope * scores / 100.0, -35, 35)))
    bins = []
    edges = np.linspace(0, 1, 11)
    for index in range(10):
        mask = (probabilities >= edges[index]) & (
            probabilities <= edges[index + 1] if index == 9 else probabilities < edges[index + 1]
        )
        count = int(mask.sum())
        if not count:
            continue
        successes = int(outcomes[mask].sum())
        low, high = wilson_score_interval(successes, count)
        bins.append({
            "lower_edge": float(edges[index]), "upper_edge": float(edges[index + 1]),
            "count": count, "successes": successes,
            "predicted": float(probabilities[mask].mean()),
            "actual": float(outcomes[mask].mean()),
            "wilson_low": float(low), "wilson_high": float(high),
        })
    feature_psi = _psi(development["score"], holdout["score"])
    if feature_psi is None:
        raise ValueError("Score-drift evidence needs at least 20 development and holdout samples")
    holdout_metrics = dict((result.get("holdout") or {}).get("metrics") or {})
    development_metrics = dict(result.get("metrics") or {})
    for name in (
        "brier", "baseline_brier", "ece", "log_loss", "baseline_log_loss",
        "log_loss_skill", "log_loss_improvement_ci_low",
    ):
        _finite(holdout_metrics.get(name), f"holdout {name}")
    calibration_decay = max(
        0.0,
        _finite(holdout_metrics.get("ece"), "holdout ece")
        - _finite(development_metrics.get("ece"), "development ece"),
    )
    created = aware_utc(created_at or dt.datetime.now(dt.timezone.utc), name="created_at")
    valid_until = created + dt.timedelta(days=max(int(valid_days), 1))
    model_id = f"{asset_class}-{strategy_id}-{horizon_sessions}-{str(run_id)[:12]}"
    payload = {
        "schema_version": CALIBRATION_ARTIFACT_SCHEMA,
        "model_id": model_id,
        "model_type": "platt_logistic",
        "model_family": "interpretable_baseline",
        "version": str(run_id),
        "strategy_id": str(strategy_id),
        "asset_class": str(asset_class),
        "target_version": str(target_version),
        "horizon_sessions": int(horizon_sessions),
        "feature_schema_hash": str(feature_schema_hash),
        "score_feature": str(score_feature),
        "coefficients": {"intercept": intercept, "slope": slope},
        "dataset_hash": _dataset_hash(dataset),
        "validation_run_id": str(run_id),
        "validated_at": created.isoformat(),
        "valid_until": valid_until.isoformat(),
        "training_end": str(development["as_of_date"].max()),
        "holdout_start": str(holdout["as_of_date"].min()),
        "holdout_end": str(holdout["as_of_date"].max()),
        "oos_samples": int(len(holdout)),
        "positive_samples": int(outcomes.sum()),
        "negative_samples": int(len(outcomes) - outcomes.sum()),
        "observation_days": int(pd.to_datetime(holdout["as_of_date"]).dt.normalize().nunique()),
        "metrics": holdout_metrics,
        "reliability": bins,
        "feature_psi": float(feature_psi),
        "calibration_decay": float(calibration_decay),
        "nested_chronological": True,
        "untouched_holdout": True,
        "pit_verified": True,
        "costs_applied": True,
        "deployment_stage": "SHADOW",
    }
    return {**payload, "artifact_hash": canonical_hash(payload)}


def build_equity_calibration_artifact(
    result: Mapping[str, Any],
    dataset: pd.DataFrame,
    *,
    run_id: str,
    strategy_id: str,
    target_version: str,
    horizon_sessions: int,
    feature_schema_hash: str,
    valid_days: int = 30,
    created_at: dt.datetime | None = None,
) -> dict[str, Any]:
    """Backward-compatible equity builder with an equity-only context."""
    return build_calibration_artifact(
        result, dataset, run_id=run_id, strategy_id=strategy_id,
        target_version=target_version, horizon_sessions=horizon_sessions,
        feature_schema_hash=feature_schema_hash, asset_class="equity",
        score_feature="scanner_composite_score", valid_days=valid_days,
        created_at=created_at,
    )


def infer_equity_probability(
    artifact: Mapping[str, Any],
    *,
    score: float,
    feature_at: Any,
    inference_at: Any,
    expected_context: Mapping[str, Any],
    registry_record: Mapping[str, Any] | None,
    verify_signature: Callable[[Mapping[str, Any]], bool] | None,
    minimum_bin_samples: int = 30,
) -> dict[str, Any]:
    """Compute a candidate probability only from a verified ACTIVE champion."""
    package = dict(artifact or {})
    failures = []
    if package.get("schema_version") != CALIBRATION_ARTIFACT_SCHEMA:
        failures.append("Unsupported calibration artifact schema")
    artifact_hash = str(package.get("artifact_hash") or "")
    unsigned = {
        key: value for key, value in package.items()
        if key not in {"artifact_hash", "signature", "signature_algorithm", "signature_key_id"}
    }
    if not artifact_hash or canonical_hash(unsigned) != artifact_hash:
        failures.append("Calibration artifact hash mismatch")
    if verify_signature is None or not verify_signature(package):
        failures.append("Calibration artifact signature is not cryptographically verified")
    record = dict(registry_record or {})
    if record.get("role") != "champion" or record.get("status") != "ACTIVE":
        failures.append("Model is not the ACTIVE champion")
    if str(record.get("model_id") or "") != str(package.get("model_id") or ""):
        failures.append("Registry model identity mismatch")
    for key, expected in dict(expected_context or {}).items():
        if str(package.get(key, "")) != str(expected):
            failures.append(f"Artifact context mismatch: {key}")
    try:
        now = aware_utc(inference_at, name="inference_at")
        feature_time = aware_utc(feature_at, name="feature_at")
        if feature_time > now:
            failures.append("Feature timestamp is after inference")
        if aware_utc(package.get("valid_until"), name="valid_until") < now:
            failures.append("Calibration artifact has expired")
        score_value = _finite(score, "score")
        intercept = _finite((package.get("coefficients") or {}).get("intercept"), "intercept")
        slope = _finite((package.get("coefficients") or {}).get("slope"), "slope")
    except ValueError as exc:
        failures.append(str(exc))
        score_value = intercept = slope = 0.0
    if failures:
        return {"status": "UNAVAILABLE", "failures": sorted(set(failures)), "probability": None}
    probability = float(1.0 / (1.0 + math.exp(-max(min(intercept + slope * score_value / 100.0, 35), -35))))
    bin_row = next((row for row in package.get("reliability", ())
                    if float(row["lower_edge"]) <= probability <= float(row["upper_edge"])), None)
    if not bin_row or int(bin_row.get("count", 0)) < int(minimum_bin_samples):
        return {"status": "UNAVAILABLE", "failures": ["Candidate reliability bin lacks evidence"], "probability": None}
    metrics = dict(package["metrics"])
    calibration = {
        "status": "VALIDATED",
        "probability": probability,
        "probability_interval_low": float(bin_row["wilson_low"]),
        "probability_interval_high": float(bin_row["wilson_high"]),
        "oos_samples": int(package["oos_samples"]),
        "positive_samples": int(package["positive_samples"]),
        "negative_samples": int(package["negative_samples"]),
        "observation_days": int(package["observation_days"]),
        "ece": float(metrics["ece"]), "brier": float(metrics["brier"]),
        "baseline_brier": float(metrics["baseline_brier"]),
        "log_loss": float(metrics["log_loss"]),
        "baseline_log_loss": float(metrics["baseline_log_loss"]),
        "log_loss_skill": float(metrics["log_loss_skill"]),
        "log_loss_improvement_ci_low": float(metrics["log_loss_improvement_ci_low"]),
        "model_version": str(package["version"]),
        "validated_at": package["validated_at"], "valid_until": package["valid_until"],
        "feature_psi": float(package["feature_psi"]),
        "calibration_decay": float(package["calibration_decay"]),
        "nested_chronological": True, "untouched_holdout": True,
        "pit_verified": True, "costs_applied": True,
        "reliability": list(package["reliability"]),
        **{key: package[key] for key in (
            "strategy_id", "asset_class", "target_version", "horizon_sessions", "feature_schema_hash"
        )},
    }
    prediction = {
        "model_id": package["model_id"], "model_family": package["model_family"],
        "version": package["version"], "role": "CHAMPION", "status": "ACTIVE",
        "deployment_mode": "PRODUCTION", "promotion_attested": True,
        "artifact_signature_valid": True, "calibrated": True,
        "feature_schema_hash": package["feature_schema_hash"], "regime": "GLOBAL",
        "probability": probability, "inference_at": now.isoformat(),
        "feature_at": feature_time.isoformat(), "maximum_feature_age_seconds": 120,
        "artifact_hash": artifact_hash,
    }
    return {"status": "PASS", "failures": [], "probability": probability,
            "calibration_evidence": calibration, "model_prediction": prediction}
