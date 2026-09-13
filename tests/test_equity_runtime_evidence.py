import datetime as dt
import sqlite3

import numpy as np
import pandas as pd
import pytest

from artifact_security import ApprovalAuthority, ArtifactSigner
from calibration_artifacts import build_equity_calibration_artifact
from equity_runtime_evidence import build_equity_live_evidence
from live_evidence import EvidenceTier, LiveEvidenceContext, feature_schema_digest, timestamped_feature_lineage
from model_registry import ModelRegistry
from prediction_validation import chronological_holdout_split
from runtime_evidence_store import RuntimeEvidenceStore


def _connect(path):
    return sqlite3.connect(path)


def test_equity_runtime_requests_only_new_outcomes_not_legacy_fill_or_conformal(monkeypatch):
    import equity_runtime_evidence
    now = dt.datetime.now(dt.timezone.utc)
    context = LiveEvidenceContext("s", "equity", "t", 15, "ABC", now, "hash")
    monkeypatch.setattr(equity_runtime_evidence, "infer_equity_probability", lambda *a, **k: {
        "status": "PASS", "model_prediction": {"model_id": "fixture"}, "calibration_evidence": {}})
    monkeypatch.setattr(equity_runtime_evidence, "evaluate_model_ensemble", lambda *a, **k: {"ensemble_hash": "fixture"})
    class Registry:
        def active_champion(self, **kwargs): return {"artifact": {}}
    class Store:
        def __init__(self): self.calls = []
        def latest(self, kind, exact, **kwargs):
            self.calls.append((kind, exact))
            return None
        def portfolio(self, *a, **k): return None
    store = Store()
    bundle = build_equity_live_evidence(
        context=context, score=70, feature_lineage={"score": {"available_at": now}},
        quote_observed_at=now, quote_received_at=now, quote_source="fixture",
        universe_observed_at=now, universe_effective_at=now,
        registry=Registry(), runtime_store=store)
    assert [kind for kind, _ in store.calls] == ["EQUITY_EXECUTION_OUTCOMES"]
    assert store.calls[0][1]["instrument"] == "ABC"
    assert bundle.equity_execution_evidence is None
    assert bundle.fill_evidence is None and bundle.conformal_evidence is None


@pytest.mark.parametrize("runtime_keys_present", [True, False])
def test_equity_runtime_loads_real_signed_model_but_keeps_missing_controls_unavailable(tmp_path, runtime_keys_present):
    rows = 800
    dates = pd.bdate_range("2022-01-03", periods=rows)
    frame = pd.DataFrame({
        "as_of_date": dates, "label_end_date": dates + pd.offsets.BDay(5),
        "score": np.full(rows, 80.0), "target_before_stop": np.tile([0, 1], rows // 2),
    })
    frame.attrs.update({
        "pit_verified": True, "costs_applied": True,
        "strategy_version": "equity-v1", "target_version": "target-v1",
        "horizon_sessions": 5,
    })
    _, holdout = chronological_holdout_split(
        frame, holdout_fraction=0.15, minimum_holdout_dates=20, embargo_sessions=20,
    )
    metrics = {
        "brier": 0.20, "baseline_brier": 0.25, "ece": 0.03,
        "log_loss": 0.60, "baseline_log_loss": 0.69,
        "log_loss_skill": 0.13, "log_loss_improvement_ci_low": 0.01,
    }
    result = {
        "status": "VALIDATED", "model": {"intercept": 0.2, "slope": 1.0},
        "holdout_fraction": 0.15, "embargo_sessions": 20,
        "holdout_samples": len(holdout), "metrics": metrics,
        "holdout": {"metrics": metrics},
    }
    now = dt.datetime.now(dt.timezone.utc)
    lineage = timestamped_feature_lineage(
        {"scanner_composite_score": 80.0}, source="Upstox",
        available_at=now - dt.timedelta(seconds=1),
        definition_version="equity-v1:scanner-components-v1", maximum_age_seconds=120,
    )
    schema_hash = feature_schema_digest(lineage)
    artifact = build_equity_calibration_artifact(
        result, frame, run_id="run-live", strategy_id="equity-v1",
        target_version="target-v1", horizon_sessions=5,
        feature_schema_hash=schema_hash, created_at=now,
    )
    signer = ArtifactSigner(b"m" * 32)
    artifact = signer.sign(artifact)
    registry = ModelRegistry(_connect, str(tmp_path / "registry.sqlite3"))
    authority = ApprovalAuthority({"risk": b"r" * 32, "deploy": b"d" * 32})
    approvals = [
        authority.issue(approver="risk", role="model-risk",
                        artifact_hash=artifact["artifact_hash"], action="BOOTSTRAP"),
        authority.issue(approver="deploy", role="deployment",
                        artifact_hash=artifact["artifact_hash"], action="BOOTSTRAP"),
    ]
    registry.bootstrap_champion(
        artifact["model_id"], artifact["model_type"], "GLOBAL", artifact["version"],
        artifact, artifact["metrics"], approvals=approvals, artifact_authority=signer,
        approval_authority=authority,
    )
    evidence_store = RuntimeEvidenceStore(_connect, str(tmp_path / "evidence.sqlite3"))
    context = LiveEvidenceContext(
        "equity-v1", "equity", "target-v1", 5, "NSE:ABC", now, schema_hash,
    )
    bundle = build_equity_live_evidence(
        context=context, score=80, feature_lineage=lineage,
        quote_observed_at=now - dt.timedelta(seconds=1), quote_received_at=now,
        quote_source="Upstox", universe_observed_at=now - dt.timedelta(minutes=1),
        universe_effective_at=now - dt.timedelta(days=1), registry=registry,
        runtime_store=evidence_store, model_artifact_signer=signer if runtime_keys_present else None,
    )
    assert bundle.tier is EvidenceTier.VALIDATED
    assert bundle.calibration_evidence["ensemble_hash"]
    assert bundle.conformal_evidence is None
    assert "Execution outcome evidence is unavailable" in bundle.compatibility_failures()
    assert "Conformal evidence is unavailable" not in bundle.compatibility_failures()
    assert bundle.equity_execution_evidence is None
    assert bundle.model_predictions[0]["artifact_signature_valid"] is False
    assert bundle.model_predictions[0]["artifact_integrity_valid"] is True

    # The existing store verifies actual content through the supplied callback.
    # No signing key is needed for equity runtime evidence retrieval.
    from artifact_security import verify_equity_artifact_integrity
    from resilience_control_plane import canonical_hash
    package = {**context.compatibility_fields(), "created_at": now.isoformat(),
               "valid_until": (now + dt.timedelta(days=1)).isoformat(), "status": "VALIDATED",
               "point_estimate": .1, "calibration_residuals": [.01]}
    package["artifact_hash"] = canonical_hash(package)
    evidence_store.save("CONFORMAL", package, verify_signature=verify_equity_artifact_integrity)
    assert evidence_store.latest("CONFORMAL", context.compatibility_fields(),
                                 verify_signature=verify_equity_artifact_integrity, now=now) == package
    assert not verify_equity_artifact_integrity({**package, "point_estimate": .9})
    assert not verify_equity_artifact_integrity({**package, "asset_class": "options"})
