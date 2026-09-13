import datetime as dt

import numpy as np
import pandas as pd
import pytest

from calibration_artifacts import build_equity_calibration_artifact, infer_equity_probability
from prediction_validation import chronological_holdout_split


def _dataset(rows=240):
    dates = pd.bdate_range("2024-01-01", periods=rows)
    frame = pd.DataFrame({
        "as_of_date": dates,
        "label_end_date": dates + pd.offsets.BDay(5),
        "score": np.tile(np.linspace(30, 90, 40), rows // 40),
        "target_before_stop": np.tile([0, 1], rows // 2),
    })
    frame.attrs.update({
        "pit_verified": True, "costs_applied": True,
        "strategy_version": "equity-v1", "target_version": "target-v1",
        "horizon_sessions": 5,
    })
    return frame


def _validated_result(frame):
    _, holdout = chronological_holdout_split(
        frame, holdout_fraction=0.15, minimum_holdout_dates=20, embargo_sessions=20,
    )
    metrics = {
        "brier": 0.20, "baseline_brier": 0.25, "ece": 0.04,
        "log_loss": 0.60, "baseline_log_loss": 0.69,
        "log_loss_skill": 0.13, "log_loss_improvement_ci_low": 0.01,
    }
    return {
        "status": "VALIDATED", "model": {"intercept": -0.2, "slope": 1.1},
        "holdout_fraction": 0.15, "embargo_sessions": 20,
        "holdout_samples": len(holdout), "metrics": {**metrics, "ece": 0.03},
        "holdout": {"metrics": metrics},
    }


def test_artifact_is_built_only_from_proven_validation_context():
    frame = _dataset()
    artifact = build_equity_calibration_artifact(
        _validated_result(frame), frame, run_id="run-123", strategy_id="equity-v1",
        target_version="target-v1", horizon_sessions=5, feature_schema_hash="schema",
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    assert artifact["deployment_stage"] == "SHADOW"
    assert artifact["untouched_holdout"] is True
    assert artifact["artifact_hash"]
    assert artifact.get("signature") is None


def test_unsigned_artifact_cannot_produce_live_probability():
    frame = _dataset()
    artifact = build_equity_calibration_artifact(
        _validated_result(frame), frame, run_id="run-123", strategy_id="equity-v1",
        target_version="target-v1", horizon_sessions=5, feature_schema_hash="schema",
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    result = infer_equity_probability(
        artifact, score=70, feature_at=dt.datetime.now(dt.timezone.utc),
        inference_at=dt.datetime.now(dt.timezone.utc),
        expected_context={"strategy_id": "equity-v1", "asset_class": "equity"},
        registry_record={"model_id": artifact["model_id"], "role": "champion", "status": "ACTIVE"},
        verify_signature=None,
    )
    assert result["status"] == "UNAVAILABLE"
    assert "Calibration artifact signature is not cryptographically verified" in result["failures"]


def test_artifact_rejects_unverified_pit_dataset():
    frame = _dataset()
    frame.attrs["pit_verified"] = False
    try:
        build_equity_calibration_artifact(
            _validated_result(frame), frame, run_id="run", strategy_id="equity-v1",
            target_version="target-v1", horizon_sessions=5, feature_schema_hash="schema",
        )
    except ValueError as exc:
        assert "point-in-time" in str(exc)
    else:
        raise AssertionError("unverified dataset produced an artifact")


def test_equity_keyless_inference_preserves_integrity_context_and_activation():
    frame = _dataset(800)
    now = dt.datetime.now(dt.timezone.utc)
    artifact = build_equity_calibration_artifact(
        _validated_result(frame), frame, run_id="fixture", strategy_id="equity-v1",
        target_version="target-v1", horizon_sessions=5, feature_schema_hash="schema",
        created_at=now)
    kwargs = dict(score=70, feature_at=now, inference_at=now,
                  expected_context={"asset_class": "equity", "horizon_sessions": 5},
                  registry_record={"model_id": artifact["model_id"], "role": "champion", "status": "ACTIVE"},
                  verify_signature=None, require_signature=False, minimum_bin_samples=1)
    result = infer_equity_probability(artifact, **kwargs)
    assert result["status"] == "PASS"
    assert result["model_prediction"]["artifact_signature_valid"] is False
    assert result["model_prediction"]["artifact_integrity_valid"] is True
    assert result["model_prediction"]["artifact_verification"] == "equity-content-hash"
    tampered = {**artifact, "coefficients": {"intercept": 99, "slope": 1}}
    assert "Calibration artifact hash mismatch" in infer_equity_probability(tampered, **kwargs)["failures"]
    for replacement in (
        {"expected_context": {"asset_class": "options"}},
        {"expected_context": {"asset_class": "equity", "horizon_sessions": 15}},
        {"registry_record": {"model_id": artifact["model_id"], "role": "challenger", "status": "SHADOW"}},
        {"inference_at": now + dt.timedelta(days=1000)},
    ):
        assert infer_equity_probability(artifact, **{**kwargs, **replacement})["status"] == "UNAVAILABLE"
