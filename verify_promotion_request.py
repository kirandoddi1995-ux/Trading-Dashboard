"""Verify a signed model promotion/rollback request in a protected CI environment."""
from __future__ import annotations

import argparse
import json
import os
import pathlib

from artifact_security import ApprovalAuthority, ArtifactSigner, validate_independent_approvals


def verify_request(path, environ=None):
    environ = environ or os.environ
    request = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    artifact = dict(request.get("artifact") or {})
    action = str(request.get("action") or "").upper()
    if action not in {"PROMOTE", "ROLLBACK"}:
        raise ValueError("Action must be PROMOTE or ROLLBACK")
    signer = ArtifactSigner(
        str(environ.get("MODEL_ARTIFACT_SIGNING_KEY") or "").encode(),
        key_id=str(environ.get("MODEL_ARTIFACT_SIGNING_KEY_ID") or "production"),
    )
    approver_keys = json.loads(str(environ.get("MODEL_APPROVER_KEYS_JSON") or "{}"))
    authority = ApprovalAuthority({name: str(key).encode() for name, key in approver_keys.items()})
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
    args = parser.parse_args(argv)
    result = verify_request(args.request)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
