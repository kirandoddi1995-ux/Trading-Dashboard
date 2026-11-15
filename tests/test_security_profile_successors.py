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
    """A changed record, current file or predecessor fails closed with its own code."""
    root = Path(__file__).resolve().parents[1]
    raw = (root / s.RECORD).read_bytes()
    for name, _, _ in s.LINEAGE:
        (tmp_path / name).write_bytes((root / name).read_bytes())
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
    """Constraints from before the Authlib patch are not accepted as current."""
    root = Path(__file__).resolve().parents[1]
    for name in (s.RECORD, *(n for n, _, _ in s.LINEAGE)):
        (tmp_path / name).write_bytes((root / name).read_bytes())
    previous = json.loads((root / s.PREVIOUS_RECORD).read_bytes())
    current = (root / 'constraints.txt').read_bytes()
    (tmp_path / 'constraints.txt').write_bytes(current.replace(b'Authlib==1.9.1', b'Authlib==1.8.0'))
    original = previous['files']['constraints.txt']['predecessor_raw_sha256']
    with pytest.raises(ValueError, match='SECURITY_TRANSITION_CURRENT_BYTES_DIFFER'):
        s.regression_hash(tmp_path, 'constraints.txt', original)


@pytest.mark.parametrize('changed', [False, True])
def test_previous_record_missing_or_changed_is_rejected(tmp_path, changed):
    """The PRE_AUTHLIB snapshot is required and pinned byte for byte."""
    root = Path(__file__).resolve().parents[1]
    raw = (root / s.RECORD).read_bytes()
    (tmp_path / s.RECORD).write_bytes(raw)
    for name in (s.OTEL_PREVIOUS_RECORD, s.PYASN1_PREVIOUS_RECORD, 'constraints.txt'):
        (tmp_path / name).write_bytes((root / name).read_bytes())
    if changed:
        (tmp_path / s.PREVIOUS_RECORD).write_bytes((root / s.PREVIOUS_RECORD).read_bytes() + b' ')
    code = 'CHANGED' if changed else 'REQUIRED'
    predecessor = json.loads(raw)['files']['constraints.txt']['predecessor_raw_sha256']
    with pytest.raises(ValueError, match='^SECURITY_TRANSITION_PREVIOUS_RECORD_' + code + '$'):
        s.regression_hash(tmp_path, 'constraints.txt', predecessor)


@pytest.fixture
def pyasn1_transition_root(tmp_path):
    """A temp root holding the record, every lineage snapshot and the current constraints."""
    root = Path(__file__).resolve().parents[1]
    for name in (s.RECORD, *(n for n, _, _ in s.LINEAGE), 'constraints.txt'):
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


OTEL_BUMP = ((b'opentelemetry-api==1.45.1', b'opentelemetry-api==1.45.2'),
             (b'opentelemetry-exporter-http-transport==0.66b1', b'opentelemetry-exporter-http-transport==0.66b2'),
             (b'opentelemetry-exporter-otlp-common==0.66b1', b'opentelemetry-exporter-otlp-common==0.66b2'),
             (b'opentelemetry-exporter-otlp-proto-common==1.45.1', b'opentelemetry-exporter-otlp-proto-common==1.45.2'),
             (b'opentelemetry-exporter-otlp-proto-http==1.45.1', b'opentelemetry-exporter-otlp-proto-http==1.45.2'),
             (b'opentelemetry-proto==1.45.1', b'opentelemetry-proto==1.45.2'),
             (b'opentelemetry-sdk==1.45.1', b'opentelemetry-sdk==1.45.2'),
             (b'opentelemetry-semantic-conventions==0.66b1', b'opentelemetry-semantic-conventions==0.66b2'))


def _revert(raw, pairs):
    """Undo each (old, new) pin swap; each new pin must appear exactly once."""
    for old, new in pairs:
        assert raw.splitlines().count(new) == 1
        raw = raw.replace(new, old)
    return raw


def test_otel_and_pyasn1_patches_each_change_only_their_lines_and_one_record_digest():
    """Current constraints minus the OTel bump = the PRE_OTEL successor; minus pyasn1 too = the
    PRE_PYASN1 successor. Each record equals the next with only the constraints digest changed."""
    root = Path(__file__).resolve().parents[1]
    current = (root / 'constraints.txt').read_bytes()
    records = [json.loads((root / s.RECORD).read_bytes())]
    for name, digest, _ in s.LINEAGE:
        snapshot = (root / name).read_bytes()
        assert hashlib.sha256(snapshot).hexdigest() == digest
        records.append(json.loads(snapshot))
    assert s.OTEL_PREVIOUS_RECORD_SHA256 == '84ba96fe008b64b1b7a9a616118217ecc97b07755ce66862a4755cb6ccbb4d52'
    assert s.PYASN1_PREVIOUS_RECORD_SHA256 == '3c207fca4ad1917e093c3b67af5e541194249ae477d24befa7da7dad930b36d1'
    pre_otel = _revert(current, OTEL_BUMP)
    pre_pyasn1 = _revert(pre_otel, [(b'pyasn1==0.6.4', b'pyasn1==0.6.5')])
    for record, raw in zip(records, (current, pre_otel, pre_pyasn1)):
        assert record['files']['constraints.txt']['successor_raw_sha256'] == hashlib.sha256(raw).hexdigest()
    for newer, older in zip(records, records[1:]):
        older = json.loads(json.dumps(older))
        older['files']['constraints.txt']['successor_raw_sha256'] = newer['files']['constraints.txt']['successor_raw_sha256']
        assert older == newer


@pytest.mark.parametrize('changed', [False, True])
def test_otel_previous_record_missing_or_changed_is_rejected(pyasn1_transition_root, changed):
    """The PRE_OTEL snapshot is required and pinned byte for byte."""
    snapshot = pyasn1_transition_root / s.OTEL_PREVIOUS_RECORD
    if changed:
        snapshot.write_bytes(snapshot.read_bytes() + b' ')
    else:
        snapshot.unlink()
    predecessor = json.loads((pyasn1_transition_root / s.RECORD).read_bytes())['files']['constraints.txt']['predecessor_raw_sha256']
    code = 'CHANGED' if changed else 'REQUIRED'
    with pytest.raises(ValueError, match='^SECURITY_TRANSITION_OTEL_PREVIOUS_RECORD_' + code + '$'):
        s.regression_hash(pyasn1_transition_root, 'constraints.txt', predecessor)


def test_pre_otel_constraints_are_not_a_fallback(pyasn1_transition_root):
    current = (pyasn1_transition_root / 'constraints.txt').read_bytes()
    (pyasn1_transition_root / 'constraints.txt').write_bytes(_revert(current, OTEL_BUMP))
    predecessor = json.loads((pyasn1_transition_root / s.RECORD).read_bytes())['files']['constraints.txt']['predecessor_raw_sha256']
    with pytest.raises(ValueError, match='^SECURITY_TRANSITION_CURRENT_BYTES_DIFFER$'):
        s.regression_hash(pyasn1_transition_root, 'constraints.txt', predecessor)


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


def test_reviewed_supersessions_map_exact_pins_to_exact_current_bytes():
    root = Path(__file__).resolve().parents[1]
    raw = (root / s.SUPERSESSIONS).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == s.SUPERSESSIONS_SHA256
    value = json.loads(raw)
    assert value["files"]
    for name, entries in value["files"].items():
        for entry in entries:
            assert s.regression_hash(root, name, entry["predecessor_legacy_sha256"]) == s._legacy_sha((root / name).read_bytes())
            assert (root / entry["reason"]).is_file()
        # Any other historical pin for the same file stays the historical pin.
        assert s.regression_hash(root, name, "0" * 64) == "0" * 64


@pytest.mark.parametrize("change", ["record", "current"])
def test_supersession_tampering_is_refused(tmp_path, change):
    root = Path(__file__).resolve().parents[1]
    for name in (s.RECORD, s.PREVIOUS_RECORD, s.PYASN1_PREVIOUS_RECORD, "constraints.txt"):
        (tmp_path / name).write_bytes((root / name).read_bytes())
    raw = (root / s.SUPERSESSIONS).read_bytes()
    (tmp_path / s.SUPERSESSIONS).write_bytes(raw + b" " if change == "record" else raw)
    name, entries = next(iter(json.loads(raw)["files"].items()))
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_bytes(b"changed" if change == "current" else (root / name).read_bytes())
    code = {"record": "SOURCE_SUPERSESSIONS_RECORD_CHANGED", "current": "SOURCE_SUPERSESSION_CURRENT_BYTES_DIFFER"}[change]
    with pytest.raises(ValueError, match="^" + code + "$"):
        s.regression_hash(tmp_path, name, entries[0]["predecessor_legacy_sha256"])


@pytest.mark.parametrize('field', ['other_file', 'constraints_predecessor', 'top_level'])
def test_a_lineage_step_changing_more_than_the_constraints_digest_is_rejected(pyasn1_transition_root, monkeypatch, field):
    """Even with a re-pinned snapshot, a step that changes anything but the constraints successor
    digest (another file's entry, the constraints predecessor, a top-level field) breaks the lineage."""
    snapshot = pyasn1_transition_root / s.OTEL_PREVIOUS_RECORD
    value = json.loads(snapshot.read_bytes())
    if field == 'other_file':
        other = next(name for name in value['files'] if name != 'constraints.txt')
        value['files'][other]['successor_raw_sha256'] = '0' * 64
    elif field == 'constraints_predecessor':
        value['files']['constraints.txt']['predecessor_raw_sha256'] = '0' * 64
    else:
        value['purpose'] = 'CHANGED'
    snapshot.write_bytes(json.dumps(value).encode())
    lineage = list(s.LINEAGE)
    lineage[0] = (s.OTEL_PREVIOUS_RECORD, hashlib.sha256(snapshot.read_bytes()).hexdigest(), 'OTEL_PREVIOUS_RECORD')
    monkeypatch.setattr(s, 'LINEAGE', tuple(lineage))
    predecessor = json.loads((pyasn1_transition_root / s.RECORD).read_bytes())['files']['constraints.txt']['predecessor_raw_sha256']
    with pytest.raises(ValueError, match='^SECURITY_TRANSITION_LINEAGE_DIFFERS$'):
        s.regression_hash(pyasn1_transition_root, 'constraints.txt', predecessor)
