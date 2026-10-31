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
RECORD_SHA256 = '84ba96fe008b64b1b7a9a616118217ecc97b07755ce66862a4755cb6ccbb4d52'


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
    if name == 'constraints.txt':
        # The pyasn1 patch extends the exact approved chain; no old-byte fallback.
        try:
            pyasn1_previous_raw = (root / PYASN1_PREVIOUS_RECORD).read_bytes()
        except OSError:
            raise ValueError('SECURITY_TRANSITION_PYASN1_PREVIOUS_RECORD_REQUIRED') from None
        if _sha(pyasn1_previous_raw) != PYASN1_PREVIOUS_RECORD_SHA256:
            raise ValueError('SECURITY_TRANSITION_PYASN1_PREVIOUS_RECORD_CHANGED')
        expected = json.loads(pyasn1_previous_raw)
        expected['files']['constraints.txt']['successor_raw_sha256'] = value['files']['constraints.txt']['successor_raw_sha256']
        if expected != value:
            raise ValueError('SECURITY_TRANSITION_LINEAGE_DIFFERS')
        # Preserve the prior approved record verbatim; enrol exactly one new
        # constraints digest, not an ignore/fallback for historical admissions.
        try:
            previous_raw = (root / PREVIOUS_RECORD).read_bytes()
        except OSError:
            raise ValueError('SECURITY_TRANSITION_PREVIOUS_RECORD_REQUIRED') from None
        if _sha(previous_raw) != PREVIOUS_RECORD_SHA256:
            raise ValueError('SECURITY_TRANSITION_PREVIOUS_RECORD_CHANGED')
        previous = json.loads(previous_raw)
        if set(previous['files']) != set(value['files']):
            raise ValueError('SECURITY_TRANSITION_LINEAGE_DIFFERS')
        for path, old in previous['files'].items():
            new = value['files'][path]
            if path == 'constraints.txt':
                if ({k: v for k, v in old.items() if k != 'successor_raw_sha256'} !=
                        {k: v for k, v in new.items() if k != 'successor_raw_sha256'}):
                    raise ValueError('SECURITY_TRANSITION_LINEAGE_DIFFERS')
            elif new != old:
                raise ValueError('SECURITY_TRANSITION_LINEAGE_DIFFERS')
    entry = value["files"][name]
    original = base64.b64decode(entry["predecessor_base64"], validate=True)
    if (_sha(original) != entry["predecessor_raw_sha256"]
            or _legacy_sha(original) != predecessor):
        raise ValueError("SECURITY_TRANSITION_PREDECESSOR_DIFFERS")
    current = (root / name).read_bytes()
    if _sha(current) != entry["successor_raw_sha256"]:
        raise ValueError("SECURITY_TRANSITION_CURRENT_BYTES_DIFFER")
    return _legacy_sha(current)
