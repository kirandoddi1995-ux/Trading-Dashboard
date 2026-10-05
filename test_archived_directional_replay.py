"""Synthetic archive recovery, prefix causality and origin boundaries."""
from dataclasses import replace
import base64
import json
import zlib

import pytest

import archived_directional_replay as adapter
import research_input_archive as storage
from research_integrity import DevelopmentManifest, IntegrityError, canonical, hash_value
from research_replay_comparison import ObservationJournal, compare_session
from test_automated_directional_replay import ROOT, pack


def setup_run(tmp_path, mutate=None):
    replay, ledger = pack(tmp_path, mutate=mutate)
    spec = adapter.prepare_spec(replay, ROOT)
    identity = hash_value(spec)
    ledger.append({'kind': 'REGISTERED', 'identity': identity, 'spec_hash': identity})
    archive = storage.InputArchive(tmp_path / 'archive')
    result = adapter.run(spec, source_root=ROOT, data_root=tmp_path, archive=archive, ledger=ledger)
    return spec, ledger, archive, result


def test_archive_roundtrip_deduplicates_and_restarts(tmp_path):
    archive = storage.InputArchive(tmp_path)
    raw = b'precise bytes\r\n' * 100
    reference = archive.put(raw)
    assert archive.put(raw) == reference
    assert len(list(tmp_path.iterdir())) == 1
    assert storage.InputArchive(tmp_path).get(reference['sha256']) == raw
    assert reference['compressed_size'] < reference['size']


@pytest.mark.parametrize('damage', ['hash', 'size', 'truncated', 'trailing', 'base64', 'schema'])
def test_archive_rejects_corruption_not_overwrite(tmp_path, damage):
    archive = storage.InputArchive(tmp_path)
    raw = b'original'
    ref = archive.put(raw)
    path = tmp_path / (ref['sha256'] + '.json')
    record = json.loads(path.read_bytes())
    if damage == 'hash':
        record['sha256'] = 'a' * 64
    elif damage == 'size':
        record['size'] = True
    elif damage in ('truncated', 'trailing'):
        compressed = zlib.compress(raw)
        record['payload'] = base64.b64encode(compressed[:-1] if damage == 'truncated'
                                             else compressed + b'extra').decode()
    elif damage == 'base64':
        record['payload'] = 'not base64!'
    else:
        record['unexpected'] = 1
    damaged = canonical(record)
    path.write_bytes(damaged)
    with pytest.raises(IntegrityError):
        archive.get(ref['sha256'])
    with pytest.raises(IntegrityError):
        archive.put(raw)
    assert path.read_bytes() == damaged


def test_archive_bounds_expansion_and_encoded_size(tmp_path, monkeypatch):
    archive = storage.InputArchive(tmp_path)
    raw = b'x' * 10000
    ref = archive.put(raw)
    path = tmp_path / (ref['sha256'] + '.json')
    record = json.loads(path.read_bytes())
    record['size'] = 10
    path.write_bytes(canonical(record))
    monkeypatch.setattr(storage, 'MAX_INPUT_BYTES', 100)
    with pytest.raises(IntegrityError):
        archive.get(ref['sha256'])
    with pytest.raises(IntegrityError):
        archive.put(raw)
    monkeypatch.setattr(storage, 'MAX_ENVELOPE_BYTES', 10)
    with pytest.raises(IntegrityError, match='ENVELOPE_TOO_LARGE'):
        archive.get(ref['sha256'])


def test_archive_private_path_and_missing_blob(tmp_path):
    with pytest.raises(IntegrityError, match='OUTSIDE_REPOSITORY'):
        storage.InputArchive(ROOT / 'forbidden-private-archive')
    with pytest.raises(FileNotFoundError):
        storage.InputArchive(tmp_path).get('a' * 64)


def test_recovery_uses_only_archive_and_exact_results(tmp_path, monkeypatch):
    spec, ledger, archive, first = setup_run(tmp_path)
    second = adapter.run(spec, source_root=ROOT, data_root=tmp_path, archive=archive, ledger=ledger)
    assert first == second
    def forbidden(*args):
        raise AssertionError('original dataset must not be opened')
    monkeypatch.setattr(DevelopmentManifest, 'read_bytes', forbidden)
    restored = adapter.restore_and_replay(archive, first['manifest_sha256'], ROOT)
    assert restored['report'] == first['report']
    assert restored['references'] == first['references']
    assert len(restored['references']) == 375
    assert restored['approval_authority'] is False and restored['fill_evidence'] is False


@pytest.mark.parametrize('field', ['report_hash', 'references_hash'])
def test_recovery_rejects_result_conflict(tmp_path, field):
    _, _, archive, result = setup_run(tmp_path)
    manifest = json.loads(archive.get(result['manifest_sha256']))
    manifest[field] = 'a' * 64
    altered = archive.put(canonical(manifest))
    with pytest.raises(IntegrityError, match='RESULT_MISMATCH'):
        adapter.restore_and_replay(archive, altered['sha256'], ROOT)


def test_recovery_rejects_environment_drift(tmp_path, monkeypatch):
    _, _, archive, result = setup_run(tmp_path)
    monkeypatch.setattr(adapter, 'prepare_spec', lambda *args: {})
    with pytest.raises(IntegrityError, match='ENVIRONMENT_MISMATCH'):
        adapter.restore_and_replay(archive, result['manifest_sha256'], ROOT)


def test_future_prices_do_not_change_consumed_prefix(tmp_path):
    left, right = tmp_path / 'left', tmp_path / 'right'
    left.mkdir()
    right.mkdir()
    _, _, _, original = setup_run(left)
    def mutate(records, sessions):
        for record in records[70:75]:
            for key in ('Open', 'High', 'Low', 'Close'):
                record[key] += 300
    _, _, _, changed = setup_run(right, mutate)
    assert original['spec_hash'] != changed['spec_hash']
    assert original['comparison_spec_hash'] == changed['comparison_spec_hash']
    assert original['references'][:70] == changed['references'][:70]
    assert original['references'][70]['input_hash'] != changed['references'][70]['input_hash']


def test_replay_cannot_become_captured_observation(tmp_path):
    _, _, _, result = setup_run(tmp_path)
    row = adapter.ReplayReference(result['references'][0]).for_comparison('2022-01-10T00:00:00+00:00')
    assert row.normalized()['record_type'] == 'REPLAY_REFERENCE'
    with pytest.raises(IntegrityError, match='REPLAY_CANNOT'):
        ObservationJournal(tmp_path / 'observations.sqlite').record(row)
    with pytest.raises(IntegrityError):
        adapter.ReplayReference(result['references'][0]).for_comparison('2022-01-03T00:00:00+00:00')
    with pytest.raises(IntegrityError):
        compare_session(observed=[row], replayed=[row], spec_hash=row.spec_hash,
                        session_open=row.session_open, session_close=row.session_close)
    with pytest.raises(IntegrityError):
        replace(row, origin='false').normalized()


def test_warmup_reset_requires_real_boolean(tmp_path):
    def mutate(records, sessions):
        sessions[0]['reset_warmup'] = 'false'
    replay, _ = pack(tmp_path, mutate=mutate)
    manifests = replay['manifests']
    with pytest.raises(IntegrityError, match='BOOLEAN_WARMUP'):
        adapter.parse_inputs((tmp_path / 'bars.csv').read_bytes(),
                             (tmp_path / 'sessions.json').read_bytes(), manifests)


def test_failed_archive_never_acknowledges_success(tmp_path, monkeypatch):
    replay, ledger = pack(tmp_path)
    spec = adapter.prepare_spec(replay, ROOT)
    identity = hash_value(spec)
    ledger.append({'kind': 'REGISTERED', 'identity': identity, 'spec_hash': identity})
    archive = storage.InputArchive(tmp_path / 'archive')
    def fail(*args):
        raise OSError('synthetic failure')
    monkeypatch.setattr(archive, 'put', fail)
    with pytest.raises(OSError):
        adapter.run(spec, source_root=ROOT, data_root=tmp_path, archive=archive, ledger=ledger)
    events = ledger.events()
    assert events[-1]['kind'] == 'FAILED'


def test_cli_sanitizes_errors_and_private_paths(tmp_path, capsys):
    path = tmp_path / 'secret.json'
    path.write_text('{credential-value-not-json')
    assert adapter.main(['prepare', '--replay-spec', str(path), '--spec', str(tmp_path / 'new.json')]) == 2
    assert 'credential-value' not in capsys.readouterr().out
    assert adapter.main(['prepare', '--spec', str(ROOT / 'private.json')]) == 2
    assert 'BLOCKED' in capsys.readouterr().out


def test_cli_prepare_register_run_restore(tmp_path, capsys):
    replay, _ = pack(tmp_path)
    old, spec, ledger = tmp_path / 'old.json', tmp_path / 'new.json', tmp_path / 'cli.sqlite'
    archive, output, restored = tmp_path / 'archive', tmp_path / 'output.json', tmp_path / 'restored.json'
    old.write_bytes(canonical(replay))
    assert adapter.main(['prepare', '--replay-spec', str(old), '--spec', str(spec)]) == 0
    assert adapter.main(['register', '--spec', str(spec), '--ledger', str(ledger)]) == 0
    args = ['run', '--spec', str(spec), '--ledger', str(ledger), '--data-root', str(tmp_path),
            '--archive', str(archive), '--output', str(output)]
    assert adapter.main(args) == 0
    result = json.loads(output.read_bytes())
    assert adapter.main(['restore', '--archive', str(archive), '--manifest-sha256',
                         result['manifest_sha256'], '--output', str(restored)]) == 0
    assert json.loads(restored.read_bytes())['report'] == result['report']
    assert adapter.main(args) == 2  # Never overwrite published results.
    assert 'SYNTHETIC_ONLY' not in capsys.readouterr().out


@pytest.mark.parametrize('damage', ['inventory', 'size', 'authority', 'identity'])
def test_manifest_failures(tmp_path, damage):
    _, _, archive, result = setup_run(tmp_path)
    manifest = json.loads(archive.get(result['manifest_sha256']))
    if damage == 'inventory':
        manifest['inputs']['bars'] = None
    elif damage == 'size':
        manifest['inputs']['bars']['size'] += 1
    elif damage == 'authority':
        manifest['approval_authority'] = True
    else:
        manifest['inputs']['bars']['sha256'] = manifest['inputs']['sessions']['sha256']
    altered = archive.put(canonical(manifest))
    with pytest.raises(IntegrityError):
        adapter.restore_and_replay(archive, altered['sha256'], ROOT)


def test_archive_publication_failure_has_no_ack(tmp_path, monkeypatch):
    archive = storage.InputArchive(tmp_path)
    def fail(*args):
        raise OSError('write failed')
    monkeypatch.setattr(storage, 'write_once', fail)
    with pytest.raises(OSError):
        archive.put(b'exact')
    assert list(tmp_path.iterdir()) == []
