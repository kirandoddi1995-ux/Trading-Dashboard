"""Cryptographic signing for model artifacts and independent approvals."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
from typing import Any, Mapping

from live_evidence import aware_utc
from resilience_control_plane import canonical_hash


ARTIFACT_ALGORITHM = "HMAC-SHA256"
APPROVAL_SCHEMA = "model-approval-v1"


def _key_bytes(value: str | bytes, *, name: str) -> bytes:
    key = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    if len(key) < 32:
        raise ValueError(f"{name} must contain at least 32 bytes of entropy")
    return key


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _artifact_integrity_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in dict(artifact or {}).items()
        if key not in {"artifact_hash", "signature", "signature_algorithm", "signature_key_id"}
    }


class ArtifactSigner:
    def __init__(self, key: str | bytes, *, key_id: str | None = None):
        self._key = _key_bytes(key, name="artifact signing key")
        self.key_id = str(key_id or hashlib.sha256(self._key).hexdigest()[:16])

    def sign(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        source = dict(artifact or {})
        integrity = _artifact_integrity_payload(source)
        expected_hash = canonical_hash(integrity)
        supplied_hash = str(source.get("artifact_hash") or expected_hash)
        if not hmac.compare_digest(supplied_hash, expected_hash):
            raise ValueError("Artifact hash does not match its content")
        signed = {
            **integrity,
            "artifact_hash": expected_hash,
            "signature_algorithm": ARTIFACT_ALGORITHM,
            "signature_key_id": self.key_id,
        }
        signature = hmac.new(self._key, _canonical_bytes(signed), hashlib.sha256).hexdigest()
        return {**signed, "signature": signature}

    def verify(self, artifact: Mapping[str, Any]) -> bool:
        source = dict(artifact or {})
        if source.get("signature_algorithm") != ARTIFACT_ALGORITHM:
            return False
        if not hmac.compare_digest(str(source.get("signature_key_id") or ""), self.key_id):
            return False
        integrity = _artifact_integrity_payload(source)
        expected_hash = canonical_hash(integrity)
        if not hmac.compare_digest(str(source.get("artifact_hash") or ""), expected_hash):
            return False
        signed = {key: value for key, value in source.items() if key != "signature"}
        expected = hmac.new(self._key, _canonical_bytes(signed), hashlib.sha256).hexdigest()
        return hmac.compare_digest(str(source.get("signature") or ""), expected)


class ApprovalAuthority:
    """Verifies approvals signed by independent, separately keyed identities."""

    def __init__(self, approver_keys: Mapping[str, str | bytes]):
        self._keys = {
            str(identity): _key_bytes(key, name=f"approval key for {identity}")
            for identity, key in dict(approver_keys or {}).items()
        }
        if len(self._keys) < 2:
            raise ValueError("At least two independent approval identities are required")

    def issue(self, *, approver: str, role: str, artifact_hash: str, action: str,
              ttl_minutes: int = 30, issued_at: dt.datetime | None = None) -> dict[str, Any]:
        identity = str(approver)
        if identity not in self._keys:
            raise ValueError("Approver identity is not configured")
        issued = aware_utc(issued_at or dt.datetime.now(dt.timezone.utc), name="issued_at")
        payload = {
            "schema_version": APPROVAL_SCHEMA,
            "approver": identity,
            "role": str(role),
            "artifact_hash": str(artifact_hash),
            "action": str(action).upper(),
            "issued_at": issued.isoformat(),
            "expires_at": (issued + dt.timedelta(minutes=max(int(ttl_minutes), 1))).isoformat(),
            "nonce": secrets.token_hex(16),
        }
        signature = hmac.new(self._keys[identity], _canonical_bytes(payload), hashlib.sha256).hexdigest()
        return {**payload, "signature": signature}

    def verify(self, approval: Mapping[str, Any], *, artifact_hash: str, action: str,
               now: dt.datetime | None = None) -> bool:
        row = dict(approval or {})
        identity = str(row.get("approver") or "")
        key = self._keys.get(identity)
        if key is None or row.get("schema_version") != APPROVAL_SCHEMA:
            return False
        if not hmac.compare_digest(str(row.get("artifact_hash") or ""), str(artifact_hash)):
            return False
        if str(row.get("action") or "").upper() != str(action).upper():
            return False
        try:
            current = aware_utc(now or dt.datetime.now(dt.timezone.utc), name="now")
            issued = aware_utc(row.get("issued_at"), name="issued_at")
            expires = aware_utc(row.get("expires_at"), name="expires_at")
        except ValueError:
            return False
        if issued > current + dt.timedelta(seconds=5) or expires <= current or expires <= issued:
            return False
        payload = {key_name: value for key_name, value in row.items() if key_name != "signature"}
        try:
            expected = hmac.new(key, _canonical_bytes(payload), hashlib.sha256).hexdigest()
        except (TypeError, ValueError):
            return False
        return hmac.compare_digest(str(row.get("signature") or ""), expected)


def validate_independent_approvals(
    approvals,
    *,
    artifact_hash: str,
    action: str,
    authority: ApprovalAuthority,
    required_roles=("model-risk", "deployment"),
) -> list[dict[str, Any]]:
    verified = []
    identities, roles, nonces = set(), set(), set()
    for approval in approvals or ():
        row = dict(approval or {})
        if not authority.verify(row, artifact_hash=artifact_hash, action=action):
            raise ValueError("An approval attestation is invalid or expired")
        identity, role, nonce = str(row.get("approver")), str(row.get("role")), str(row.get("nonce"))
        if identity in identities or nonce in nonces:
            raise ValueError("Approval identities and nonces must be unique")
        identities.add(identity); roles.add(role); nonces.add(nonce); verified.append(row)
    missing_roles = set(required_roles) - roles
    if missing_roles:
        raise ValueError(f"Missing independent approval roles: {', '.join(sorted(missing_roles))}")
    return verified
