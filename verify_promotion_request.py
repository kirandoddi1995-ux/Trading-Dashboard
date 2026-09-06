"""Verify a signed model promotion/rollback request in a protected CI environment."""
from __future__ import annotations

import argparse
import json
import os
import pathlib

from artifact_security import ApprovalAuthority, ArtifactSigner, validate_independent_approvals
from managed_secrets import (
    GoogleSecretManagerProvider, load_independent_approver_keys, parse_reference_map,
)


def _promotion_authorities(environ, secret_provider=None):
    project = str(environ.get("GCP_SECRET_MANAGER_PROJECT") or "").strip()
    signing_ref = str(environ.get("MODEL_ARTIFACT_SIGNING_SECRET_REF") or "").strip()
    approver_refs_raw = str(environ.get("MODEL_APPROVER_SECRET_REFS_JSON") or "").strip()
    managed_required = str(environ.get("REQUIRE_MANAGED_PROMOTION_KEYS") or "").casefold() == "true"
    managed_selected = bool(project or signing_ref or approver_refs_raw or managed_required)
    if managed_selected:
        if not project or not signing_ref or not approver_refs_raw:
            raise ValueError("Managed promotion-key configuration is incomplete")
        provider = secret_provider or GoogleSecretManagerProvider(project)
        signing_key = provider.access(signing_ref).reveal_bytes()
        approver_keys = load_independent_approver_keys(
            provider, parse_reference_map(approver_refs_raw),
        )
        return signing_key, approver_keys
    signing_key = str(environ.get("MODEL_ARTIFACT_SIGNING_KEY") or "").encode()
    approver_values = json.loads(str(environ.get("MODEL_APPROVER_KEYS_JSON") or "{}"))
    return signing_key, {name: str(key).encode() for name, key in approver_values.items()}


def verify_request(path, environ=None, *, require_action=None, secret_provider=None):
    environ = environ or os.environ
    request = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    artifact = dict(request.get("artifact") or {})
    action = str(request.get("action") or "").upper()
    if action not in {"PROMOTE", "ROLLBACK"}:
        raise ValueError("Action must be PROMOTE or ROLLBACK")
    if require_action and action != str(require_action).upper():
        raise ValueError(f"Request action must be {str(require_action).upper()}")
    signing_key, approver_keys = _promotion_authorities(environ, secret_provider)
    signer = ArtifactSigner(
        signing_key,
        key_id=str(environ.get("MODEL_ARTIFACT_SIGNING_KEY_ID") or "production"),
    )
    authority = ApprovalAuthority(approver_keys)
    if not signer.verify(artifact):
        raise ValueError("Artifact signature verification failed")
    approvals = validate_independent_approvals(
        request.get("approvals") or [], artifact_hash=artifact["artifact_hash"],
        action=action, authority=authority,
    )
    return {"authorized": True, "action": action, "artifact_hash": artifact["artifact_hash"],
            "approvers": [approval["approver"] for approval in approvals]}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("request")
    parser.add_argument("--require-action", choices=("PROMOTE", "ROLLBACK"))
    args = parser.parse_args(argv)
    result = verify_request(args.request, require_action=args.require_action)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
