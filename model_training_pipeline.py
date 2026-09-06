"""Evidence-gated Step 3+ training, calibration and shadow-artifact pipeline.

Algorithms can be exercised with structurally marked synthetic fixtures, but a
signed artifact can only be created from immutable production evidence that
passes PIT, cost, ledger, chronology, sample, class and calibration gates.
Registration is SHADOW-only; existing independent approvals remain mandatory
for every later stage transition.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import io
import json
import math
import os
import pathlib
import sqlite3
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler

from artifact_security import ArtifactSigner
from decision_evidence import ExperimentTracker
from prediction_validation import (
    calibration_metrics, chronological_holdout_split, purged_walk_forward_splits,
)
from production_repository import ProductionRepository
from resilience_control_plane import ModelPromotionGate, canonical_hash


UTC = dt.timezone.utc
ARTIFACT_SCHEMA = "step3-model-artifact-v1"


@dataclass(frozen=True)
class ModelTrainingPolicy:
    minimum_total_samples: int = 1000
    minimum_class_samples: int = 100
    minimum_observation_days: int = 120
    minimum_oof_samples: int = 500
    minimum_holdout_samples: int = 500
    minimum_holdout_dates: int = 20
    holdout_fraction: float = 0.15
    folds: int = 5
    minimum_fold_training_samples: int = 200
    embargo_sessions: int = 20
    maximum_missing_fraction: float = 0.05
    maximum_ece: float = 0.08
    maximum_log_loss: float = 0.69
    minimum_regimes: int = 3
    random_state: int = 1729


PRODUCTION_TRAINING_POLICY = ModelTrainingPolicy()


def _dataset_hash(frame: pd.DataFrame, features: Sequence[str]) -> str:
    columns = ["decision_id", "as_of_date", "label_end_date", "target_before_stop", *features]
    available = [name for name in columns if name in frame]
    return hashlib.sha256(
        pd.util.hash_pandas_object(frame[available], index=False).values.tobytes()
    ).hexdigest()


def _model_logit(probabilities):
    values = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(values / (1 - values)).reshape(-1, 1)


def _sample_weights(labels):
    labels = np.asarray(labels, dtype=int)
    counts = np.bincount(labels, minlength=2)
    if not counts[0] or not counts[1]:
        raise ValueError("Both outcome classes are required")
    return np.asarray([len(labels) / (2 * counts[value]) for value in labels], dtype=float)


def _logistic(random_state=1729):
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(
            C=1.0, class_weight="balanced", max_iter=2000, random_state=random_state,
        )),
    ])


def _gam(random_state=1729):
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("spline", SplineTransformer(n_knots=5, degree=2, include_bias=False)),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(
            C=0.5, class_weight="balanced", max_iter=2500, random_state=random_state,
        )),
    ])


def _boosted(monotonic_constraints: Sequence[int], random_state=1729):
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=False)),
        ("model", HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=250, max_leaf_nodes=15,
            min_samples_leaf=30, l2_regularization=1.0,
            monotonic_cst=list(monotonic_constraints), random_state=random_state,
        )),
    ])


def validate_training_dataset(frame: pd.DataFrame, *, features: Sequence[str],
                              policy=PRODUCTION_TRAINING_POLICY) -> dict:
    required = {"decision_id", "as_of_date", "label_end_date", "target_before_stop", *features}
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {"status": "INSUFFICIENT_EVIDENCE", "failures": ["No matured observations"]}
    missing = sorted(required - set(frame.columns))
    if missing:
        return {"status": "INVALID_EVIDENCE", "failures": [f"Missing columns: {missing}"]}
    failures = []
    attrs = dict(frame.attrs)
    synthetic = attrs.get("synthetic_fixture") is True
    if synthetic and attrs.get("production_evidence"):
        failures.append("Synthetic fixtures cannot be production evidence")
    if not synthetic:
        for name, message in (
            ("pit_verified", "PIT lineage is not verified"),
            ("costs_applied", "Executable costs are not verified"),
            ("executable_quotes_verified", "Executable bid/ask quotes are not verified"),
            ("ledger_verified", "Evidence ledger continuity is not verified"),
            ("production_evidence", "Dataset is not production evidence"),
        ):
            if attrs.get(name) is not True:
                failures.append(message)
        if attrs.get("evidence_source") != "immutable-decision-spine":
            failures.append("Dataset did not come from the immutable decision spine")
    normalized = frame.copy()
    normalized["as_of_date"] = pd.to_datetime(normalized["as_of_date"], utc=True, errors="coerce")
    normalized["label_end_date"] = pd.to_datetime(
        normalized["label_end_date"], utc=True, errors="coerce"
    )
    if normalized[["as_of_date", "label_end_date"]].isna().any().any():
        failures.append("Decision or label timestamps are invalid")
    elif (normalized["label_end_date"] <= normalized["as_of_date"]).any():
        failures.append("Label chronology is reversed or zero length")
    if normalized["decision_id"].astype(str).duplicated().any():
        failures.append("Duplicate decision ids are forbidden")
    labels = pd.to_numeric(normalized["target_before_stop"], errors="coerce")
    if not labels.isin([0, 1]).all():
        failures.append("Outcomes must be binary")
    else:
        counts = labels.astype(int).value_counts()
        if len(normalized) < policy.minimum_total_samples:
            failures.append("Insufficient total matured observations")
        if min(int(counts.get(0, 0)), int(counts.get(1, 0))) < policy.minimum_class_samples:
            failures.append("Insufficient observations in one outcome class")
    if not synthetic:
        returns = pd.to_numeric(normalized.get("excess_return"), errors="coerce")
        if returns is None or returns.isna().any() or not np.isfinite(returns.to_numpy(dtype=float)).all():
            failures.append("Production outcomes require finite realized excess returns")
    days = normalized["as_of_date"].dt.normalize().nunique()
    if days < policy.minimum_observation_days:
        failures.append("Insufficient chronological observation days")
    for feature in features:
        values = pd.to_numeric(normalized[feature], errors="coerce")
        missing_fraction = float(values.isna().mean())
        if missing_fraction > policy.maximum_missing_fraction or values.notna().sum() == 0:
            failures.append(f"Feature {feature} exceeds missing-data policy")
        finite = values.dropna().to_numpy(dtype=float)
        if finite.size and not np.isfinite(finite).all():
            failures.append(f"Feature {feature} contains infinity")
        normalized[feature] = values
    status = "PASS" if not failures else (
        "INSUFFICIENT_EVIDENCE" if all("Insufficient" in item for item in failures) else "INVALID_EVIDENCE"
    )
    normalized.attrs.update(attrs)
    return {"status": status, "failures": sorted(set(failures)), "dataset": normalized}


def _oof_predictions(estimator, rows, features, splits):
    predictions = np.full(len(rows), np.nan)
    labels = rows["target_before_stop"].astype(int).to_numpy()
    for train_idx, validation_idx in splits:
        candidate = clone(estimator)
        kwargs = {}
        if isinstance(candidate.named_steps.get("model"), HistGradientBoostingClassifier):
            kwargs["model__sample_weight"] = _sample_weights(labels[train_idx])
        candidate.fit(rows.iloc[train_idx][list(features)], labels[train_idx], **kwargs)
        predictions[validation_idx] = candidate.predict_proba(
            rows.iloc[validation_idx][list(features)]
        )[:, 1]
    return predictions


def _fit_platt(raw_probabilities, labels):
    calibrator = LogisticRegression(C=1.0, max_iter=2000, random_state=1729)
    calibrator.fit(_model_logit(raw_probabilities), np.asarray(labels, dtype=int))
    return calibrator


def _calibrate(calibrator, raw_probabilities):
    return calibrator.predict_proba(_model_logit(raw_probabilities))[:, 1]


def train_step3_candidates(frame: pd.DataFrame, *, features: Sequence[str],
                           monotonic_constraints: Mapping[str, int] | None = None,
                           policy=PRODUCTION_TRAINING_POLICY, experiment_tracker=None,
                           code_hash="uncommitted") -> dict:
    feature_names = tuple(dict.fromkeys(str(name) for name in features))
    if not feature_names:
        return {"status": "INVALID_EVIDENCE", "failures": ["Feature list is empty"],
                "promotable": False, "artifact": None}
    check = validate_training_dataset(frame, features=feature_names, policy=policy)
    if check["status"] != "PASS":
        return {**check, "promotable": False, "artifact": None}
    rows = check["dataset"].sort_values("as_of_date").reset_index(drop=True)
    trial = None
    if experiment_tracker is not None:
        trial = experiment_tracker.start(
            hypothesis="Step3 interpretable baseline plus constrained boosted stack",
            data_window={"from": rows.as_of_date.min().isoformat(),
                         "to": rows.as_of_date.max().isoformat(), "samples": len(rows)},
            config_hash=canonical_hash(asdict(policy)),
            feature_versions={name: "registry-resolved" for name in feature_names},
            code_hash=str(code_hash),
        )
    development, holdout = chronological_holdout_split(
        rows, holdout_fraction=policy.holdout_fraction,
        minimum_holdout_dates=policy.minimum_holdout_dates,
        embargo_sessions=policy.embargo_sessions,
    )
    development, holdout = development.reset_index(drop=True), holdout.reset_index(drop=True)
    failures = []
    if len(holdout) < policy.minimum_holdout_samples:
        failures.append("Untouched holdout is below sample policy")
    splits = purged_walk_forward_splits(
        development, folds=policy.folds,
        min_train=policy.minimum_fold_training_samples,
        embargo_sessions=policy.embargo_sessions,
    )
    if not splits:
        failures.append("Purged walk-forward produced no valid folds")
    if failures:
        result = {"status": "INSUFFICIENT_EVIDENCE", "failures": failures,
                  "promotable": False, "artifact": None,
                  "training_samples": len(development), "holdout_samples": len(holdout)}
        if trial is not None:
            experiment_tracker.finish(
                trial, status="ABSTAIN", metrics={}, result_summary="; ".join(failures),
            )
        return result

    labels = development["target_before_stop"].astype(int).to_numpy()
    logistic = _logistic(policy.random_state)
    gam = _gam(policy.random_state)
    constraints = [int(dict(monotonic_constraints or {}).get(name, 0)) for name in feature_names]
    if any(value not in {-1, 0, 1} for value in constraints):
        raise ValueError("Monotonic constraints must be -1, 0, or 1")
    boosted = _boosted(constraints, policy.random_state)
    baseline_oof = _oof_predictions(logistic, development, feature_names, splits)
    gam_oof = _oof_predictions(gam, development, feature_names, splits)
    boosted_oof = _oof_predictions(boosted, development, feature_names, splits)
    valid = np.isfinite(baseline_oof) & np.isfinite(gam_oof) & np.isfinite(boosted_oof)
    if int(valid.sum()) < policy.minimum_oof_samples or len(np.unique(labels[valid])) < 2:
        failures.append("Nested OOF predictions are insufficient or single-class")
    if failures:
        result = {"status": "INSUFFICIENT_EVIDENCE", "failures": failures,
                  "promotable": False, "artifact": None, "oof_samples": int(valid.sum())}
        if trial is not None:
            experiment_tracker.finish(
                trial, status="ABSTAIN", metrics={}, result_summary="; ".join(failures),
            )
        return result

    oof_indices = np.flatnonzero(valid)
    split_point = max(int(len(oof_indices) * 0.70), 1)
    meta_indices, calibration_indices = oof_indices[:split_point], oof_indices[split_point:]
    if len(calibration_indices) < max(20, policy.minimum_class_samples * 2):
        failures.append("Chronological Platt calibration window is insufficient")
    if len(np.unique(labels[meta_indices])) < 2 or len(np.unique(labels[calibration_indices])) < 2:
        failures.append("Meta-training or calibration window is single-class")
    if failures:
        result = {"status": "INSUFFICIENT_EVIDENCE", "failures": failures,
                  "promotable": False, "artifact": None, "oof_samples": int(valid.sum())}
        if trial is not None:
            experiment_tracker.finish(
                trial, status="ABSTAIN", metrics={}, result_summary="; ".join(failures),
            )
        return result

    stacker = LogisticRegression(C=0.5, max_iter=2000, random_state=policy.random_state)
    stack_features = np.column_stack([
        _model_logit(baseline_oof[meta_indices]).ravel(),
        _model_logit(boosted_oof[meta_indices]).ravel(),
    ])
    stacker.fit(stack_features, labels[meta_indices])
    calibration_stack = np.column_stack([
        _model_logit(baseline_oof[calibration_indices]).ravel(),
        _model_logit(boosted_oof[calibration_indices]).ravel(),
    ])
    raw_calibration = stacker.predict_proba(calibration_stack)[:, 1]
    platt = _fit_platt(raw_calibration, labels[calibration_indices])

    logistic.fit(development[list(feature_names)], labels)
    gam.fit(development[list(feature_names)], labels)
    boosted.fit(
        development[list(feature_names)], labels,
        model__sample_weight=_sample_weights(labels),
    )
    holdout_labels = holdout["target_before_stop"].astype(int).to_numpy()
    baseline_holdout = logistic.predict_proba(holdout[list(feature_names)])[:, 1]
    gam_holdout = gam.predict_proba(holdout[list(feature_names)])[:, 1]
    boosted_holdout = boosted.predict_proba(holdout[list(feature_names)])[:, 1]
    raw_holdout = stacker.predict_proba(np.column_stack([
        _model_logit(baseline_holdout).ravel(), _model_logit(boosted_holdout).ravel(),
    ]))[:, 1]
    probabilities = _calibrate(platt, raw_holdout)
    metrics = calibration_metrics(holdout_labels, probabilities)
    metrics["accuracy"] = float(accuracy_score(holdout_labels, probabilities >= 0.5))
    baseline_metrics = calibration_metrics(holdout_labels, baseline_holdout)
    gam_metrics = calibration_metrics(holdout_labels, gam_holdout)
    boosted_metrics = calibration_metrics(holdout_labels, boosted_holdout)
    if metrics["brier"] >= metrics["baseline_brier"]:
        failures.append("Calibrated stack does not beat holdout base-rate Brier")
    if metrics["ece"] > policy.maximum_ece:
        failures.append("Holdout ECE exceeds policy")
    if metrics["log_loss"] > policy.maximum_log_loss:
        failures.append("Holdout log loss exceeds policy")
    regimes = int(holdout.get("market_regime", pd.Series(dtype=str)).dropna().astype(str).nunique())
    if not frame.attrs.get("synthetic_fixture") and regimes < policy.minimum_regimes:
        failures.append("Untouched holdout lacks required regime coverage")
    status = "VALIDATED" if not failures else "NEGATIVE"
    bundle = {
        "logistic": logistic, "gam": gam, "boosted": boosted,
        "stacker": stacker, "platt": platt,
    }
    result = {
        "status": status, "failures": failures, "promotable": False, "artifact": None,
        "features": list(feature_names), "monotonic_constraints": constraints,
        "training_samples": len(development), "oof_samples": int(valid.sum()),
        "holdout_samples": len(holdout), "holdout_dates": int(holdout.as_of_date.dt.normalize().nunique()),
        "metrics": metrics,
        "candidate_metrics": {"logistic": baseline_metrics, "gam": gam_metrics,
                              "monotonic_boosted": boosted_metrics},
        "nested_chronological": True, "untouched_holdout": True,
        "dataset_hash": _dataset_hash(rows, feature_names),
        "evidence_class": "TEST_ONLY" if frame.attrs.get("synthetic_fixture") else "PRODUCTION",
        "_bundle": bundle,
    }
    if trial is not None:
        experiment_tracker.finish(
            trial, status="VALIDATED" if status == "VALIDATED" else "NEGATIVE",
            metrics=metrics, result_summary="Validated" if status == "VALIDATED" else "; ".join(failures),
        )
    return result


def _signed_artifact(result: Mapping, *, signer: ArtifactSigner, strategy_id: str,
                     target_version: str, horizon_sessions: int, deployment_stage: str,
                     evidence_class: str, promotion_gate: Mapping) -> dict:
    buffer = io.BytesIO()
    joblib.dump(result["_bundle"], buffer, compress=3)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    payload = {
        "schema_version": ARTIFACT_SCHEMA,
        "model_id": f"equity-step3-{result['dataset_hash'][:16]}",
        "model_family": "interpretable-plus-monotonic-stack",
        "deployment_stage": str(deployment_stage),
        "role": "challenger" if deployment_stage == "SHADOW" else "test-only",
        "evidence_class": str(evidence_class),
        "strategy_id": str(strategy_id), "target_version": str(target_version),
        "horizon_sessions": int(horizon_sessions), "features": list(result["features"]),
        "monotonic_constraints": list(result["monotonic_constraints"]),
        "dataset_hash": result["dataset_hash"], "metrics": dict(result["metrics"]),
        "nested_chronological": True, "untouched_holdout": True,
        "pit_verified": evidence_class == "PRODUCTION",
        "costs_applied": evidence_class == "PRODUCTION",
        "executable_quotes_verified": evidence_class == "PRODUCTION",
        "ledger_verified": evidence_class == "PRODUCTION",
        "model_bundle_encoding": "joblib-base64-signed-before-load",
        "model_bundle": encoded, "created_at": dt.datetime.now(UTC).isoformat(),
        "promotion_gate": dict(promotion_gate),
    }
    return signer.sign(payload)


def create_signed_test_artifact(result: Mapping, frame: pd.DataFrame, *, signer: ArtifactSigner,
                                strategy_id="synthetic-test", target_version="synthetic-test",
                                horizon_sessions=1) -> dict:
    """Exercise serialization/signature code without creating a registry-eligible artifact."""
    if result.get("status") != "VALIDATED" or frame.attrs.get("synthetic_fixture") is not True:
        raise ValueError("A validated, explicitly synthetic fixture is required")
    return _signed_artifact(
        result, signer=signer, strategy_id=strategy_id, target_version=target_version,
        horizon_sessions=horizon_sessions, deployment_stage="TEST_ONLY",
        evidence_class="TEST_ONLY",
        promotion_gate={"status": "NOT_APPLICABLE", "promotion_allowed": False},
    )


def create_signed_shadow_artifact(result: Mapping, frame: pd.DataFrame, *, signer: ArtifactSigner,
                                  strategy_id: str, target_version: str,
                                  horizon_sessions: int,
                                  promotion_evidence: Mapping) -> dict:
    if result.get("status") != "VALIDATED":
        raise ValueError("Only a validated training result may create an artifact")
    required_attrs = {
        "production_evidence": True, "synthetic_fixture": False,
        "pit_verified": True, "costs_applied": True,
        "executable_quotes_verified": True, "ledger_verified": True,
    }
    if any(frame.attrs.get(name) is not expected for name, expected in required_attrs.items()):
        raise ValueError("Artifact creation requires genuine immutable production evidence")
    supplied = dict(promotion_evidence or {})
    derived = {
        "point_in_time_verified": frame.attrs.get("pit_verified") is True,
        "untouched_holdout": result.get("untouched_holdout") is True,
        "costs_applied": frame.attrs.get("costs_applied") is True,
        "oos_samples": int(result["holdout_samples"]),
        "regimes_tested": int(frame.get("market_regime", pd.Series(dtype=str)).dropna().nunique()),
    }
    mismatches = [name for name, expected in derived.items() if supplied.get(name) != expected]
    if mismatches:
        raise ValueError(
            "Promotion evidence disagrees with derived training evidence: " + ", ".join(mismatches)
        )
    if supplied.get("rollback_model_available") is not True:
        raise ValueError("Independent registry proof of a rollback model is required")
    promotion_package = {**supplied, **derived}
    gate = ModelPromotionGate().evaluate(promotion_package)
    if not gate["promotion_allowed"]:
        raise ValueError("Promotion evidence gate rejected the candidate: " + ", ".join(gate["failures"]))
    return _signed_artifact(
        result, signer=signer, strategy_id=strategy_id, target_version=target_version,
        horizon_sessions=horizon_sessions, deployment_stage="SHADOW",
        evidence_class="PRODUCTION", promotion_gate=gate,
    )


def load_verified_model_bundle(artifact: Mapping, *, signer: ArtifactSigner,
                               registry_record: Mapping | None = None,
                               require_active=False):
    package = dict(artifact or {})
    if not signer.verify(package):
        raise ValueError("Model artifact signature verification failed")
    if package.get("schema_version") != ARTIFACT_SCHEMA:
        raise ValueError("Unsupported model artifact schema")
    if require_active:
        record = dict(registry_record or {})
        if record.get("role") != "champion" or record.get("status") != "ACTIVE":
            raise ValueError("Live inference requires an ACTIVE champion registry record")
        if str(record.get("model_id")) != str(package.get("model_id")):
            raise ValueError("Registry and artifact identities differ")
    try:
        raw = base64.b64decode(str(package["model_bundle"]), validate=True)
    except (KeyError, ValueError) as exc:
        raise ValueError("Signed model bundle encoding is invalid") from exc
    return joblib.load(io.BytesIO(raw))


def register_shadow_candidate(registry, artifact: Mapping, *, signer: ArtifactSigner) -> dict:
    if (not signer.verify(artifact) or artifact.get("deployment_stage") != "SHADOW"
            or artifact.get("evidence_class") != "PRODUCTION"):
        raise ValueError("A verified SHADOW artifact is required")
    registry.register(
        artifact["model_id"], artifact["model_family"], "GLOBAL",
        artifact["dataset_hash"][:12], "challenger", dict(artifact),
        dict(artifact["metrics"]), status="SHADOW",
    )
    return registry.get_model(artifact["model_id"])


def production_smoke(*, database_url=None, features=(), strategy_id="equity-scanner-v19.0",
                     target_version="net-excess-execution-v2", horizon_sessions=5) -> dict:
    url = str(database_url or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        local = pathlib.Path(__file__).resolve().parent / "market_cache.sqlite3"
        counts = {"scanner_observations": 0, "prediction_targets": 0}
        if local.is_file():
            conn = sqlite3.connect(str(local))
            try:
                for table in counts:
                    try:
                        counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    except sqlite3.Error:
                        pass
            finally:
                conn.close()
        return {
            "status": "UNAVAILABLE", "promotable": False, "artifact": None,
            "reason": "Restricted production DATABASE_URL is not configured in this process",
            "local_cache_counts": counts,
        }
    repository = ProductionRepository(url, schema_mode="validate", enforce_restricted_role=True)
    frame = repository.matured_decision_dataset(
        strategy_id=strategy_id, target_version=target_version,
        horizon_sessions=horizon_sessions,
    )
    tracker = ExperimentTracker(repository.append_evidence_event, repository)
    return train_step3_candidates(frame, features=features, experiment_tracker=tracker)


def _public_result(result):
    return {key: value for key, value in dict(result).items() if key not in {"_bundle", "dataset"}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--features", default="scanner_composite_score")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument(
        "--expect-no-artifact", action="store_true",
        help="Pass only when real evidence safely refuses training/artifact creation",
    )
    args = parser.parse_args(argv)
    if not args.smoke:
        parser.error("Only the evidence-gated --smoke entry point is exposed")
    result = production_smoke(
        features=[name.strip() for name in args.features.split(",") if name.strip()],
        horizon_sessions=args.horizon,
    )
    print(json.dumps(_public_result(result), indent=2, default=str))
    if args.expect_no_artifact:
        safe_refusal = (
            result.get("artifact") is None and result.get("promotable") is False
            and result.get("status") in {
                "UNAVAILABLE", "INSUFFICIENT_EVIDENCE", "INVALID_EVIDENCE", "NEGATIVE",
            }
        )
        return 0 if safe_refusal else 3
    return 0 if result.get("status") == "VALIDATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
