import datetime as dt
import sqlite3

import pandas as pd
import pytest

from artifact_security import ArtifactSigner
from resilience_control_plane import canonical_hash
from runtime_evidence_store import RuntimeEvidenceStore


def _connect(path):
    return sqlite3.connect(path)


def _signed(signer, kind="FILL", *, expired=False):
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "strategy_id": "equity-v1", "asset_class": "equity",
        "target_version": "target-v1", "horizon_sessions": 5,
        "feature_schema_hash": "schema", "created_at": now.isoformat(),
        "valid_until": (now + dt.timedelta(days=-1 if expired else 1)).isoformat(),
        "status": "VALIDATED", "kind": kind,
    }
    return signer.sign({**payload, "artifact_hash": canonical_hash(payload)})


def _context():
    return {
        "strategy_id": "equity-v1", "asset_class": "equity",
        "target_version": "target-v1", "horizon_sessions": 5,
        "feature_schema_hash": "schema",
    }


def test_runtime_store_accepts_only_signed_exact_evidence(tmp_path):
    store = RuntimeEvidenceStore(_connect, str(tmp_path / "runtime.sqlite3"))
    signer = ArtifactSigner(b"z" * 32)
    artifact = _signed(signer)
    store.save("FILL", artifact, verify_signature=signer.verify)
    assert store.latest("FILL", _context(), verify_signature=signer.verify)["artifact_hash"] == artifact["artifact_hash"]
    assert store.latest("FILL", {**_context(), "horizon_sessions": 10}, verify_signature=signer.verify) is None
    with pytest.raises(ValueError, match="signature"):
        store.save("FILL", {**artifact, "status": "changed"}, verify_signature=signer.verify)


def test_expired_runtime_evidence_is_not_loaded(tmp_path):
    store = RuntimeEvidenceStore(_connect, str(tmp_path / "runtime.sqlite3"))
    signer = ArtifactSigner(b"z" * 32)
    with pytest.raises(ValueError, match="validity window"):
        store.save("FILL", _signed(signer, expired=True), verify_signature=signer.verify)


def test_portfolio_snapshot_requires_aligned_history(tmp_path):
    store = RuntimeEvidenceStore(_connect, str(tmp_path / "runtime.sqlite3"))
    signer = ArtifactSigner(b"z" * 32)
    index = pd.bdate_range("2026-01-01", periods=65)
    payload = {
        **_signed(signer, kind="PORTFOLIO"),
    }
    # Re-sign after adding the exact portfolio payload.
    unsigned = {key: value for key, value in payload.items()
                if key not in {"artifact_hash", "signature", "signature_algorithm", "signature_key_id"}}
    unsigned.update({
        "returns": {"index": [item.isoformat() for item in index], "columns": ["NSE:ABC"],
                    "data": [[0.001] for _ in index]},
        "weights": {"NSE:ABC": 0.1},
        "stress_scenarios": {"market_down": {"NSE:ABC": -0.1}},
    })
    artifact = signer.sign({**unsigned, "artifact_hash": canonical_hash(unsigned)})
    store.save("PORTFOLIO", artifact, verify_signature=signer.verify)
    loaded = store.portfolio(_context(), verify_signature=signer.verify)
    assert loaded["returns"].shape == (65, 1)
    assert loaded["weights"] == {"NSE:ABC": 0.1}
