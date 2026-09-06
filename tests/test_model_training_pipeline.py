import datetime as dt
import inspect
import sqlite3

import numpy as np
import pandas as pd
import pytest

from artifact_security import ArtifactSigner
from model_registry import ModelRegistry
from model_training_pipeline import (
    ModelTrainingPolicy, create_signed_shadow_artifact, create_signed_test_artifact,
    load_verified_model_bundle,
    main, production_smoke, register_shadow_candidate, train_step3_candidates,
    validate_training_dataset,
)


UTC = dt.timezone.utc


def synthetic_fixture(samples=420, *, seed=7, shift=False, missing=False):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=samples, freq="B", tz="UTC")
    x1, x2 = rng.normal(size=samples), rng.normal(size=samples)
    if shift:
        x1[int(samples * .8):] += 1.5
    logits = 1.2 * x1 - .8 * x2
    p = 1 / (1 + np.exp(-logits))
    y = rng.binomial(1, p)
    frame = pd.DataFrame({
        "decision_id": [f"synthetic-{index}" for index in range(samples)],
        "as_of_date": dates,
        "label_end_date": dates + pd.offsets.BDay(5),
        "target_before_stop": y,
        "f1": x1, "f2": x2,
        "market_regime": np.where(np.arange(samples) % 3 == 0, "TREND", "RANGE"),
    })
    if missing:
        frame.loc[::20, "f2"] = np.nan
    frame.attrs.update({
        "synthetic_fixture": True, "production_evidence": False,
        "pit_verified": False, "costs_applied": False, "ledger_verified": False,
        "executable_quotes_verified": False,
        "evidence_source": "unit-test-fixture",
    })
    return frame


POLICY = ModelTrainingPolicy(
    minimum_total_samples=250, minimum_class_samples=20, minimum_observation_days=100,
    minimum_oof_samples=60, minimum_holdout_samples=50, minimum_holdout_dates=50,
    holdout_fraction=.15, folds=4, minimum_fold_training_samples=50,
    embargo_sessions=5, maximum_missing_fraction=.10, maximum_ece=.30,
    minimum_log_loss_skill=.001, log_loss_bootstrap_samples=200,
    log_loss_block_length=5, minimum_regimes=1,
)


def test_pipeline_trains_nested_candidates_on_separated_synthetic_fixture_but_cannot_promote():
    # A larger untouched holdout is intentional: the strengthened acceptance
    # gate requires a positive one-sided block-bootstrap improvement bound.
    frame = synthetic_fixture(800, missing=True)
    result = train_step3_candidates(
        frame, features=["f1", "f2"], monotonic_constraints={"f1": 1, "f2": -1},
        policy=POLICY,
    )
    assert result["status"] == "VALIDATED"
    assert result["nested_chronological"] and result["untouched_holdout"]
    assert result["evidence_class"] == "TEST_ONLY"
    assert result["promotable"] is False and result["artifact"] is None
    with pytest.raises(ValueError, match="genuine immutable production evidence"):
        create_signed_shadow_artifact(
            result, frame, signer=ArtifactSigner(b"s" * 32),
            strategy_id="test", target_version="test", horizon_sessions=5,
            promotion_evidence={},
        )


def test_too_few_single_class_or_missing_features_fail_before_fitting():
    small = synthetic_fixture(40)
    result = train_step3_candidates(small, features=["f1", "f2"], policy=POLICY)
    assert result["status"] == "INSUFFICIENT_EVIDENCE" and result["artifact"] is None
    one_class = synthetic_fixture()
    one_class["target_before_stop"] = 1
    result = train_step3_candidates(one_class, features=["f1", "f2"], policy=POLICY)
    assert result["status"] == "INSUFFICIENT_EVIDENCE" and result["artifact"] is None
    missing = synthetic_fixture()
    missing["f2"] = np.nan
    assert validate_training_dataset(missing, features=["f1", "f2"], policy=POLICY)["status"] == "INVALID_EVIDENCE"


def test_regime_shift_is_evaluated_only_on_untouched_holdout():
    result = train_step3_candidates(
        synthetic_fixture(shift=True), features=["f1", "f2"], policy=POLICY,
    )
    assert result["holdout_samples"] >= POLICY.minimum_holdout_samples
    assert result["candidate_metrics"]["logistic"]["samples"] == result["holdout_samples"]


def test_synthetic_fixture_cannot_be_relabelled_for_production_artifact(tmp_path):
    frame = synthetic_fixture(800)
    result = train_step3_candidates(frame, features=["f1", "f2"], policy=POLICY)
    with pytest.raises(ValueError, match="genuine immutable production evidence"):
        create_signed_shadow_artifact(
            result, frame, signer=ArtifactSigner(b"s" * 32),
            strategy_id="equity", target_version="v1", horizon_sessions=5,
            promotion_evidence={
                "point_in_time_verified": True, "untouched_holdout": True,
                "costs_applied": True, "rollback_model_available": True,
                "oos_samples": result["holdout_samples"], "regimes_tested": 2,
            },
        )


def test_signed_test_bundle_is_verified_before_deserialization_but_cannot_register(tmp_path):
    frame = synthetic_fixture(800)
    result = train_step3_candidates(frame, features=["f1", "f2"], policy=POLICY)
    signer = ArtifactSigner(b"s" * 32)
    artifact = create_signed_test_artifact(result, frame, signer=signer)
    assert set(load_verified_model_bundle(artifact, signer=signer)) == {
        "logistic", "gam", "boosted", "stacker", "platt",
    }
    with pytest.raises(ValueError, match="signature"):
        load_verified_model_bundle({**artifact, "strategy_id": "tampered"}, signer=signer)
    registry = ModelRegistry(sqlite3.connect, str(tmp_path / "registry.sqlite3"))
    with pytest.raises(ValueError, match="SHADOW"):
        register_shadow_candidate(registry, artifact, signer=signer)


def test_today_smoke_without_production_database_returns_no_artifact(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = production_smoke(features=["scanner_composite_score"])
    assert result["status"] == "UNAVAILABLE"
    assert result["promotable"] is False and result["artifact"] is None


def test_shadow_artifact_api_requires_independent_promotion_evidence():
    parameter = inspect.signature(create_signed_shadow_artifact).parameters["promotion_evidence"]
    assert parameter.default is inspect.Parameter.empty


def test_scheduled_check_treats_insufficient_as_healthy_fail_closed(monkeypatch):
    monkeypatch.setattr(
        "model_training_pipeline.production_smoke",
        lambda **kwargs: {
            "status": "INSUFFICIENT_EVIDENCE", "promotable": False, "artifact": None,
        },
    )
    assert main(["--scheduled-check"]) == 0


def test_scheduled_check_fails_when_production_evidence_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "model_training_pipeline.production_smoke",
        lambda **kwargs: {"status": "UNAVAILABLE", "promotable": False, "artifact": None},
    )
    assert main(["--scheduled-check"]) == 2
