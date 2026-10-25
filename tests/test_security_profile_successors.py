import hashlib
import json
from pathlib import Path

import pytest

import security_profile_successors as s


def test_enrolled_originals_and_current_bytes_are_both_pinned():
    root = Path(__file__).resolve().parents[1]
    value = json.loads((root / s.RECORD).read_bytes())
    assert len(value["files"]) == 12
    for name, entry in value["files"].items():
        assert s.regression_hash(root, name, entry["predecessor_raw_sha256"]) == s._legacy_sha((root / name).read_bytes())
    assert s.regression_hash(root, "not-enrolled.py", "original") == "original"


@pytest.mark.parametrize("change", ["record", "current", "predecessor"])
def test_transition_tampering_never_becomes_a_fallback(tmp_path, change):
    root = Path(__file__).resolve().parents[1]
    raw = (root / s.RECORD).read_bytes()
    (tmp_path / s.RECORD).write_bytes(raw + b" " if change == "record" else raw)
    (tmp_path / "constraints.txt").write_bytes(
        b"changed" if change == "current" else (root / "constraints.txt").read_bytes())
    predecessor = json.loads(raw)["files"]["constraints.txt"]["predecessor_raw_sha256"]
    with pytest.raises(ValueError, match="SECURITY_TRANSITION_"):
        s.regression_hash(tmp_path, "constraints.txt", "0" * 64 if change == "predecessor" else predecessor)


def test_record_pin_is_raw_not_line_ending_normalised():
    root = Path(__file__).resolve().parents[1]
    raw = (root / s.RECORD).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == s.RECORD_SHA256
