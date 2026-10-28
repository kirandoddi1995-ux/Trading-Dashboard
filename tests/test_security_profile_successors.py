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
    (tmp_path / s.PREVIOUS_RECORD).write_bytes((root / s.PREVIOUS_RECORD).read_bytes())
    (tmp_path / s.RECORD).write_bytes(raw + b" " if change == "record" else raw)
    (tmp_path / "constraints.txt").write_bytes(
        b"changed" if change == "current" else (root / "constraints.txt").read_bytes())
    predecessor = json.loads(raw)["files"]["constraints.txt"]["predecessor_raw_sha256"]
    code = {'record': 'RECORD_CHANGED', 'current': 'CURRENT_BYTES_DIFFER',
            'predecessor': 'PREDECESSOR_DIFFERS'}[change]
    with pytest.raises(ValueError, match='^SECURITY_TRANSITION_' + code + '$'):
        s.regression_hash(tmp_path, "constraints.txt", "0" * 64 if change == "predecessor" else predecessor)


def test_record_pin_is_raw_not_line_ending_normalised():
    root = Path(__file__).resolve().parents[1]
    raw = (root / s.RECORD).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == s.RECORD_SHA256


def test_authlib_successor_preserves_prior_record_and_all_predecessors():
    root = Path(__file__).resolve().parents[1]
    raw = (root / s.PREVIOUS_RECORD).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == s.PREVIOUS_RECORD_SHA256
    old = json.loads(raw)
    current = json.loads((root / s.RECORD).read_bytes())
    assert old['files'].keys() == current['files'].keys()
    for name in old['files']:
        if name == 'constraints.txt':
            assert old['files'][name]['predecessor_base64'] == current['files'][name]['predecessor_base64']
            assert old['files'][name]['predecessor_raw_sha256'] == current['files'][name]['predecessor_raw_sha256']
            assert old['files'][name]['successor_raw_sha256'] != current['files'][name]['successor_raw_sha256']
        else:
            assert old['files'][name] == current['files'][name]


def test_pre_authlib_constraints_are_not_an_allowed_fallback(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for name in (s.RECORD, s.PREVIOUS_RECORD):
        (tmp_path / name).write_bytes((root / name).read_bytes())
    previous = json.loads((root / s.PREVIOUS_RECORD).read_bytes())
    current = (root / 'constraints.txt').read_bytes()
    (tmp_path / 'constraints.txt').write_bytes(current.replace(b'Authlib==1.9.1', b'Authlib==1.8.0'))
    original = previous['files']['constraints.txt']['predecessor_raw_sha256']
    with pytest.raises(ValueError, match='SECURITY_TRANSITION_CURRENT_BYTES_DIFFER'):
        s.regression_hash(tmp_path, 'constraints.txt', original)


@pytest.mark.parametrize('changed', [False, True])
def test_previous_record_missing_or_changed_is_rejected(tmp_path, changed):
    root = Path(__file__).resolve().parents[1]
    raw = (root / s.RECORD).read_bytes()
    (tmp_path / s.RECORD).write_bytes(raw)
    (tmp_path / 'constraints.txt').write_bytes((root / 'constraints.txt').read_bytes())
    if changed:
        (tmp_path / s.PREVIOUS_RECORD).write_bytes((root / s.PREVIOUS_RECORD).read_bytes() + b' ')
    code = 'CHANGED' if changed else 'REQUIRED'
    predecessor = json.loads(raw)['files']['constraints.txt']['predecessor_raw_sha256']
    with pytest.raises(ValueError, match='^SECURITY_TRANSITION_PREVIOUS_RECORD_' + code + '$'):
        s.regression_hash(tmp_path, 'constraints.txt', predecessor)
