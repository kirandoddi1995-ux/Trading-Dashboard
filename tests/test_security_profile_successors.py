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
    (tmp_path / s.PYASN1_PREVIOUS_RECORD).write_bytes((root / s.PYASN1_PREVIOUS_RECORD).read_bytes())
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
    for name in (s.RECORD, s.PREVIOUS_RECORD, s.PYASN1_PREVIOUS_RECORD):
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
    (tmp_path / s.PYASN1_PREVIOUS_RECORD).write_bytes((root / s.PYASN1_PREVIOUS_RECORD).read_bytes())
    (tmp_path / 'constraints.txt').write_bytes((root / 'constraints.txt').read_bytes())
    if changed:
        (tmp_path / s.PREVIOUS_RECORD).write_bytes((root / s.PREVIOUS_RECORD).read_bytes() + b' ')
    code = 'CHANGED' if changed else 'REQUIRED'
    predecessor = json.loads(raw)['files']['constraints.txt']['predecessor_raw_sha256']
    with pytest.raises(ValueError, match='^SECURITY_TRANSITION_PREVIOUS_RECORD_' + code + '$'):
        s.regression_hash(tmp_path, 'constraints.txt', predecessor)


@pytest.fixture
def pyasn1_transition_root(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for name in (s.RECORD, s.PREVIOUS_RECORD, s.PYASN1_PREVIOUS_RECORD, 'constraints.txt'):
        (tmp_path / name).write_bytes((root / name).read_bytes())
    return tmp_path


@pytest.mark.parametrize('changed', [False, True])
def test_pyasn1_previous_record_missing_or_changed_is_rejected(pyasn1_transition_root, changed):
    root = pyasn1_transition_root
    snapshot = root / s.PYASN1_PREVIOUS_RECORD
    if changed:
        snapshot.write_bytes(snapshot.read_bytes() + b' ')
    else:
        snapshot.unlink()
    predecessor = json.loads((root / s.RECORD).read_bytes())['files']['constraints.txt']['predecessor_raw_sha256']
    code = 'CHANGED' if changed else 'REQUIRED'
    with pytest.raises(ValueError, match='^SECURITY_TRANSITION_PYASN1_PREVIOUS_RECORD_' + code + '$'):
        s.regression_hash(root, 'constraints.txt', predecessor)


def test_pyasn1_patch_preserves_exact_previous_record_and_changes_only_one_line():
    root = Path(__file__).resolve().parents[1]
    snapshot = (root / s.PYASN1_PREVIOUS_RECORD).read_bytes()
    assert hashlib.sha256(snapshot).hexdigest() == '3c207fca4ad1917e093c3b67af5e541194249ae477d24befa7da7dad930b36d1'
    assert s.PYASN1_PREVIOUS_RECORD_SHA256 == hashlib.sha256(snapshot).hexdigest()
    previous = json.loads(snapshot)
    current_record = json.loads((root / s.RECORD).read_bytes())
    current = (root / 'constraints.txt').read_bytes()
    assert current.splitlines().count(b'pyasn1==0.6.5') == 1
    reverted = current.replace(b'pyasn1==0.6.5', b'pyasn1==0.6.4')
    assert reverted.splitlines().count(b'pyasn1==0.6.4') == 1
    assert hashlib.sha256(reverted).hexdigest() == previous['files']['constraints.txt']['successor_raw_sha256']
    assert reverted.replace(b'pyasn1==0.6.4', b'pyasn1==0.6.5') == current
    previous['files']['constraints.txt']['successor_raw_sha256'] = hashlib.sha256(current).hexdigest()
    assert previous == current_record


@pytest.mark.parametrize('revert,extra_drift', [(True, False), (True, True), (False, True)])
def test_pyasn1_previous_constraints_and_extra_drift_are_not_fallbacks(pyasn1_transition_root, revert, extra_drift):
    root = pyasn1_transition_root
    current = (root / 'constraints.txt').read_bytes()
    changed = current.replace(b'pyasn1==0.6.5', b'pyasn1==0.6.4') if revert else current
    if extra_drift:
        assert changed.splitlines().count(b'pyasn1_modules==0.4.2') == 1
        changed = changed.replace(b'pyasn1_modules==0.4.2', b'pyasn1_modules==0.4.3')
    assert changed != current
    (root / 'constraints.txt').write_bytes(changed)
    predecessor = json.loads((root / s.RECORD).read_bytes())['files']['constraints.txt']['predecessor_raw_sha256']
    with pytest.raises(ValueError, match='^SECURITY_TRANSITION_CURRENT_BYTES_DIFFER$'):
        s.regression_hash(root, 'constraints.txt', predecessor)
