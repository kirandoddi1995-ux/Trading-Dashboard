import datetime as dt
import sqlite3

import pytest

from artifact_security import ApprovalAuthority, ArtifactSigner, validate_independent_approvals
from model_registry import ModelRegistry
from resilience_control_plane import ModelPromotionGate, canonical_hash


def _signed(signer, model_id):
    payload = {"model_id": model_id, "version": "1", "feature_schema_hash": "schema"}
    return signer.sign({**payload, "artifact_hash": canonical_hash(payload)})


def _approvals(authority, artifact_hash, action):
    return [
        authority.issue(approver="risk", role="model-risk", artifact_hash=artifact_hash, action=action),
        authority.issue(approver="deploy", role="deployment", artifact_hash=artifact_hash, action=action),
    ]


def _gate():
    return ModelPromotionGate().evaluate({
        "point_in_time_verified": True, "untouched_holdout": True,
        "costs_applied": True, "rollback_model_available": True,
        "oos_samples": 800, "regimes_tested": 4,
    })


def test_artifact_signature_fails_after_content_tampering():
    signer = ArtifactSigner(b"x" * 32, key_id="k1")
    signed = _signed(signer, "m1")
    assert signer.verify(signed)
    assert not signer.verify({**signed, "version": "changed"})


def test_approval_requires_two_independent_signed_roles():
    authority = ApprovalAuthority({"risk": b"r" * 32, "deploy": b"d" * 32})
    one = authority.issue(approver="risk", role="model-risk", artifact_hash="hash", action="PROMOTE")
    with pytest.raises(ValueError, match="Missing independent approval roles"):
        validate_independent_approvals(
            [one], artifact_hash="hash", action="PROMOTE", authority=authority,
        )
    expired = authority.issue(
        approver="deploy", role="deployment", artifact_hash="hash", action="PROMOTE",
        issued_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1), ttl_minutes=1,
    )
    assert not authority.verify(expired, artifact_hash="hash", action="PROMOTE")


def test_signed_lifecycle_and_rollback_are_audited(tmp_path):
    registry = ModelRegistry(sqlite3.connect, str(tmp_path / "registry.sqlite3"))
    signer = ArtifactSigner(b"x" * 32)
    authority = ApprovalAuthority({"risk": b"r" * 32, "deploy": b"d" * 32})
    old_artifact = _signed(signer, "old")
    registry.bootstrap_champion(
        "old", "logistic", "GLOBAL", "1", old_artifact, {},
        approvals=_approvals(authority, old_artifact["artifact_hash"], "BOOTSTRAP"),
        artifact_authority=signer, approval_authority=authority,
    )
    registry.register("new", "logistic", "GLOBAL", "2", "challenger", _signed(signer, "new"), {})
    registry.transition("new", "PAPER", approved_by="validator", reason="paper checks",
                        verify_artifact=signer.verify, expected_registry_version=0)
    registry.transition("new", "CANARY", approved_by="operator", reason="canary checks",
                        verify_artifact=signer.verify, expected_registry_version=1)
    new_hash = registry.get_model("new")["artifact"]["artifact_hash"]
    promotion = registry.promote(
        "new", _gate(), approvals=_approvals(authority, new_hash, "PROMOTE"),
        artifact_authority=signer, approval_authority=authority,
    )
    old_hash = registry.get_model("old")["artifact"]["artifact_hash"]
    rollback = registry.rollback(
        promotion["promotion_id"], approvals=_approvals(authority, old_hash, "ROLLBACK"),
        artifact_authority=signer, approval_authority=authority,
    )
    assert rollback["model_id"] == "old"
    assert registry.get_model("old")["status"] == "ACTIVE"
    conn = sqlite3.connect(registry.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM model_stage_transitions").fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM model_promotions WHERE action IN ('PROMOTE','ROLLBACK')"
        ).fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM model_stage_transitions")
    finally:
        conn.close()


def test_active_bootstrap_escape_hatch_is_rejected(tmp_path):
    registry = ModelRegistry(sqlite3.connect, str(tmp_path / "registry.sqlite3"))
    signer = ArtifactSigner(b"x" * 32)
    with pytest.raises(ValueError, match="bootstrap_champion"):
        registry.register(
            "unsafe", "logistic", "GLOBAL", "1", "champion", _signed(signer, "unsafe"), {},
            status="ACTIVE", bootstrap_active=True,
        )
