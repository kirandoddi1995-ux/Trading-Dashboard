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
PREVIOUS_RECORD = "APP_SECURITY_SOURCE_TRANSITIONS_PRE_AUTHLIB.json"
PREVIOUS_RECORD_SHA256 = "fad604b72c6b3cddec40fc397a5ebbd4d9d22869529b3ba23c9c036d0b35f5a2"
PYASN1_PREVIOUS_RECORD = "APP_SECURITY_SOURCE_TRANSITIONS_PRE_PYASN1.json"
PYASN1_PREVIOUS_RECORD_SHA256 = "3c207fca4ad1917e093c3b67af5e541194249ae477d24befa7da7dad930b36d1"
OTEL_PREVIOUS_RECORD = "APP_SECURITY_SOURCE_TRANSITIONS_PRE_OTEL.json"
OTEL_PREVIOUS_RECORD_SHA256 = "84ba96fe008b64b1b7a9a616118217ecc97b07755ce66862a4755cb6ccbb4d52"
RECORD_SHA256 = '6c127bd1fbdc5cf58f22adc9e7c3474b0ee008872e954e0f9a0fac29ef4f008e'
# Constraints-only security patches, newest first: each prior approved record is kept
# verbatim and differs from the next only in the constraints successor digest. A new
# patch adds one entry here; there is no old-byte fallback for historical admissions.
LINEAGE = ((OTEL_PREVIOUS_RECORD, OTEL_PREVIOUS_RECORD_SHA256, "OTEL_PREVIOUS_RECORD"),
           (PYASN1_PREVIOUS_RECORD, PYASN1_PREVIOUS_RECORD_SHA256, "PYASN1_PREVIOUS_RECORD"),
           (PREVIOUS_RECORD, PREVIOUS_RECORD_SHA256, "PREVIOUS_RECORD"))
# Reviewed source changes after historical upload packages (not security patches).
# Each entry maps one exact pinned predecessor to one exact current file; the record
# itself is pinned here, so editing it requires a reviewed code change too.
SUPERSESSIONS = "SOURCE_SUPERSESSIONS.json"
SUPERSESSIONS_SHA256 = "ca257c532dd08588091c13fbbd0e71b49c823c32d900f4588131cc99af3cb6b6"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _legacy_sha(raw: bytes) -> str:
    return _sha(raw.replace(b"\r\n", b"\n"))


def _without_constraints_successor(value: dict) -> dict:
    """A record with only the constraints successor digest removed (the one field a patch may change)."""
    files = dict(value["files"])
    files["constraints.txt"] = {k: v for k, v in files["constraints.txt"].items() if k != "successor_raw_sha256"}
    return {**value, "files": files}


def _check_constraints_lineage(value: dict, root: Path) -> None:
    """Walk LINEAGE back from the current record; every step changes only the constraints digest."""
    newer = value
    for path, digest, code in LINEAGE:
        try:
            raw = (root / path).read_bytes()
        except OSError:
            raise ValueError(f"SECURITY_TRANSITION_{code}_REQUIRED") from None
        if _sha(raw) != digest:
            raise ValueError(f"SECURITY_TRANSITION_{code}_CHANGED")
        older = json.loads(raw)
        if _without_constraints_successor(older) != _without_constraints_successor(newer):
            raise ValueError("SECURITY_TRANSITION_LINEAGE_DIFFERS")
        newer = older


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
        return _superseded(root, name, predecessor)
    if name == 'constraints.txt':
        _check_constraints_lineage(value, root)
    entry = value["files"][name]
    original = base64.b64decode(entry["predecessor_base64"], validate=True)
    if (_sha(original) != entry["predecessor_raw_sha256"]
            or _legacy_sha(original) != predecessor):
        raise ValueError("SECURITY_TRANSITION_PREDECESSOR_DIFFERS")
    current = (root / name).read_bytes()
    if _sha(current) != entry["successor_raw_sha256"]:
        raise ValueError("SECURITY_TRANSITION_CURRENT_BYTES_DIFFER")
    return _legacy_sha(current)


def _superseded(root: Path, name: str, predecessor: str) -> str:
    """Current digest for an exact reviewed supersession, else the historical pin."""
    try:
        raw = (root / SUPERSESSIONS).read_bytes()
    except OSError:
        return predecessor
    if _sha(raw) != SUPERSESSIONS_SHA256:
        raise ValueError("SOURCE_SUPERSESSIONS_RECORD_CHANGED")
    value = json.loads(raw)
    if (set(value) != {"format", "purpose", "files"} or value["format"] != "source-supersessions-v1"
            or value["purpose"] != "REGRESSION_ONLY_NOT_UPLOAD_ADMISSION"):
        raise ValueError("SOURCE_SUPERSESSIONS_CONTRACT_INVALID")
    for entry in value["files"].get(name, []):
        if entry["predecessor_legacy_sha256"] == predecessor:
            current = (root / name).read_bytes()
            if _sha(current) != entry["successor_raw_sha256"]:
                raise ValueError("SOURCE_SUPERSESSION_CURRENT_BYTES_DIFFER")
            return _legacy_sha(current)
    return predecessor
