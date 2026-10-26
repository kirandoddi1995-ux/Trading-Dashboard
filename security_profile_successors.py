"""Regression-only source transitions; historical upload admissions stay frozen.

The record includes actual predecessor Git blob bytes from the reviewed base.
Unknown paths are not transitioned. Known paths require the exact predecessor,
the fixed record digest and the exact raw current bytes. This is not an uploader.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

BASE = "563665a32e5454633b0c27256072a7249503c520"
RECORD = "APP_SECURITY_SOURCE_TRANSITIONS.json"
RECORD_SHA256 = "fad604b72c6b3cddec40fc397a5ebbd4d9d22869529b3ba23c9c036d0b35f5a2"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _legacy_sha(raw: bytes) -> str:
    return _sha(raw.replace(b"\r\n", b"\n"))


def regression_hash(root: Path, name: str, predecessor: str) -> str:
    """Return a narrowly enrolled current digest; never infer a successor."""
    raw = (root / RECORD).read_bytes()
    if _sha(raw) != RECORD_SHA256:
        raise ValueError("SECURITY_TRANSITION_RECORD_CHANGED")
    value = json.loads(raw)
    if (set(value) != {"format", "base", "purpose", "files"}
            or value["format"] != "app-security-source-transitions-v1"
            or value["base"] != BASE or value["purpose"] != "REGRESSION_ONLY_NOT_UPLOAD_ADMISSION"):
        raise ValueError("SECURITY_TRANSITION_CONTRACT_INVALID")
    if name not in value["files"]:
        return predecessor
    entry = value["files"][name]
    original = base64.b64decode(entry["predecessor_base64"], validate=True)
    if (_sha(original) != entry["predecessor_raw_sha256"]
            or _legacy_sha(original) != predecessor):
        raise ValueError("SECURITY_TRANSITION_PREDECESSOR_DIFFERS")
    current = (root / name).read_bytes()
    if _sha(current) != entry["successor_raw_sha256"]:
        raise ValueError("SECURITY_TRANSITION_CURRENT_BYTES_DIFFER")
    return _legacy_sha(current)
