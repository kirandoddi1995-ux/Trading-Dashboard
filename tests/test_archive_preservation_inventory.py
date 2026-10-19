"""Synthetic opaque bytes only. No recovery archive, keys or provider access."""
import hashlib
import json
from pathlib import Path
from typing import Any
from types import SimpleNamespace

import pytest

import archive_preservation_inventory as p


def test_raw_byte_measurement_and_native_handle(tmp_path: Path) -> None:
    file = tmp_path / 'opaque.bin'
    raw = b'\x00\xffa\r\nb\n'
    file.write_bytes(raw)
    result = p.measure(file)
    assert result['sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['bytes'] == len(raw)
    assert result['binding']['file_id'] == file.stat().st_ino
    if p.os.name == 'nt':
        assert result['binding']['volume'].startswith('\\\\?\\volume{')
        assert result['binding']['final_path'].endswith('opaque.bin')


@pytest.mark.parametrize('raw', [b'', b'abcd'])
def test_bounds(tmp_path: Path, raw: bytes) -> None:
    file = tmp_path / 'data'
    file.write_bytes(raw)
    with pytest.raises(ValueError, match='FILE_SIZE_BOUND'):
        p.measure(file, 3)


def test_relative_rejected() -> None:
    with pytest.raises(ValueError, match='PATH_REQUIRED'):
        p.measure(Path('relative'))


def test_replace_during_hash_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file = tmp_path / 'data'
    file.write_bytes(b'old')
    original = p.os.read
    changed = False
    def mutate(fd: int, size: int) -> bytes:
        nonlocal changed
        result = original(fd, size)
        if not changed:
            changed = True
            file.write_bytes(b'changed')
        return result
    monkeypatch.setattr(p.os, 'read', mutate)
    with pytest.raises((ValueError, OSError)):
        p.measure(file)


def test_preview_no_reads(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr('sys.argv', ['inventory', '--selection', 'not-read'])
    monkeypatch.setattr(p, 'read_json', lambda _: pytest.fail('private read'))
    assert p.main() == 0
    assert json.loads(capsys.readouterr().out)['private_reads'] == 0


@pytest.mark.parametrize('text', ['{"a":1,"a":2}', '{"a":NaN}', '[]'])
def test_strict_selection_json(tmp_path: Path, text: str) -> None:
    file = tmp_path / 'selection'
    file.write_text(text)
    with pytest.raises(ValueError):
        p.read_json(file)


def selection() -> dict[str, Any]:
    return {'version': 'preservation-selection-v1', 'originals': [
        {'role': role, 'path': '/' + role, 'bytes': 4, 'sha256': 'a' * 64,
         'anchor_kind': 'ORIGINAL_RETAINED_PIN' if role in {'catalog', 'bundle'} else 'FIRST_OBSERVED',
         'observed_at': '2026-10-19T18:15:00+05:30'} for role in sorted(p.ROLES)],
        'source_cipher': '/local', 'destination_cipher': '/external',
        'expected_destination_volume': 'external-enrolled',
        'owner_reports': {key: True for key in ('external_disk', 'disconnected_storage',
            'extraction_rehearsal', 'drive_readback', 'superseded_stale_attempt')}}


def fake_measure(path: Path, max_bytes: int = p.MAX_FILE_BYTES) -> dict[str, Any]:
    cipher = path.name in {'local', 'external'}
    return {'bytes': p.CIPHER_BYTES if cipher else 4, 'sha256': p.CIPHER_SHA256 if cipher else 'a' * 64,
            'binding': {'device': 1 if path.name != 'external' else 2,
                        'file_id': sorted(p.ROLES | {'local', 'external'}).index(path.name),
                        'volume': 'external-enrolled' if path.name == 'external' else 'source'}}


def test_collection_does_not_infer_custody(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(p, 'measure', fake_measure)
    monkeypatch.setattr(p, 'private_path', lambda _: None)
    report = p.collect(selection(), 'b' * 64)
    assert report['custody_verified'] is False
    assert report['physical_disk_independence'] == 'NOT_VERIFIED'
    assert report['remote_provider_identity'] == 'NOT_VERIFIED'
    assert report['deletion_authorised'] is False
    assert len(report['originals']) == 7


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'nullhash', 'boolsize', 'history', 'volume', 'same-volume', 'cipher', 'anchor', 'claim'])
def test_fail_closed_contract(monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    value = selection()
    if change == 'missing':
        value['originals'].pop()
    elif change == 'duplicate':
        value['originals'][1] = value['originals'][0]
    elif change == 'nullhash':
        value['originals'][0]['sha256'] = None
    elif change == 'boolsize':
        value['originals'][0]['bytes'] = True
    elif change == 'history':
        value['originals'][0]['anchor_kind'] = 'HISTORIC_AUTHENTIC'
    elif change == 'volume':
        value['expected_destination_volume'] = 'stale-local-volume'
    elif change == 'same-volume':
        value['expected_destination_volume'] = 'source'
    elif change == 'anchor':
        value['originals'][0]['sha256'] = 'c' * 64
    elif change == 'claim':
        value['owner_reports']['external_disk'] = 'true'
    def measured(path: Path, max_bytes: int = p.MAX_FILE_BYTES) -> dict[str, Any]:
        result = fake_measure(path)
        if change == 'cipher' and path.name == 'external':
            result['sha256'] = 'd' * 64
        if change == 'same-volume' and path.name == 'external':
            result['binding']['volume'] = 'source'
        return result
    monkeypatch.setattr(p, 'measure', measured)
    monkeypatch.setattr(p, 'private_path', lambda _: None)
    with pytest.raises(ValueError):
        p.collect(value, 'b' * 64)


def test_exclusive_publish_preserves_existing(tmp_path: Path) -> None:
    output = tmp_path / 'report'
    p.publish(output, b'first')
    with pytest.raises(FileExistsError):
        p.publish(output, b'second')
    assert output.read_bytes() == b'first'


def test_disk_full_preserves_partial_and_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = tmp_path / 'original'
    original.write_bytes(b'untouched')
    output = tmp_path / 'partial'
    def fail(fd: int, data: Any) -> int:
        raise OSError('SYNTHETIC_SECRET_PATH_NOT_PRINTED')
    monkeypatch.setattr(p.os, 'write', fail)
    with pytest.raises(OSError):
        p.publish(output, b'new')
    assert output.exists() and output.read_bytes() == b''
    assert original.read_bytes() == b'untouched'


def test_cli_failure_redacted(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr('sys.argv', ['inventory', '--confirm-measure'])
    assert p.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result['raw_error_printed'] is False and result['retry_authorised'] is False


def test_private_output_rejects_tools_tree() -> None:
    with pytest.raises(ValueError, match='PRIVATE_PATH_OUTSIDE_TOOLS_REQUIRED'):
        p.private_path(Path(p.__file__).resolve().parent / 'should-not-exist.json')


def test_probe_is_not_enrollment_or_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                        capsys: pytest.CaptureFixture[str]) -> None:
    artifact = tmp_path / 'synthetic'
    artifact.write_bytes(b'not-decoded')
    output = tmp_path / 'probe'
    monkeypatch.setattr('sys.argv', ['inventory', '--probe-destination', str(artifact),
        '--output', str(output), '--confirm-probe'])
    monkeypatch.setattr(p, 'measure', lambda *a: pytest.fail('Content hash not requested'))
    assert p.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result['file_content_reads'] == 0
    report = json.loads(output.read_bytes())
    assert report['identity_enrolled'] is False and report['custody_verified'] is False


def test_short_writes_are_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = p.os.write
    def short(fd: int, data: Any) -> int:
        return original(fd, data[:1])
    monkeypatch.setattr(p.os, 'write', short)
    path = tmp_path / 'short'
    p.publish(path, b'complete')
    assert path.read_bytes() == b'complete'


def test_unc_rejected_before_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, 'is_symlink', lambda _: pytest.fail('Network filesystem query'))
    with pytest.raises(ValueError, match='LOCAL_NATIVE_PATH_REQUIRED'):
        p.check_path(Path('//untrusted/share/private'))


def test_config_size_bounded(tmp_path: Path) -> None:
    path = tmp_path / 'large-config'
    path.write_bytes(b'x' * (p.MAX_SELECTION_BYTES + 1))
    with pytest.raises(ValueError, match='CONFIG_SIZE_BOUND'):
        p.read_json(path)


def test_bad_cli_args_never_echo_private_values(monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr('sys.argv', ['inventory', '--private-sentinel', 'SECRET_PATH'])
    assert p.main() == 2
    output = capsys.readouterr()
    assert not output.err and 'SECRET_PATH' not in output.out
    assert json.loads(output.out)['reason'] == 'INVALID_ARGUMENTS'


def test_multilink_identity_rejected_without_permission_changes(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / 'single'
    path.write_bytes(b'synthetic')
    fd = p.open_read(path)
    original = p.os.fstat
    def linked(number: int) -> p.os.stat_result:
        fields = list(original(number))
        fields[3] = 2
        return p.os.stat_result(fields)
    try:
        monkeypatch.setattr(p.os, 'fstat', linked)
        with pytest.raises(ValueError, match='SINGLE_LINK_REGULAR_FILE_REQUIRED'):
            p.identity(fd)
    finally:
        p.os.close(fd)


def test_handle_vs_path_ctime_semantics_are_compared_within_api(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / 'native-ctime-regression'
    path.write_bytes(b'unchanged opaque bytes')
    original = p.os.fstat
    def native(fd: int) -> Any:
        info = original(fd)
        values = {name: getattr(info, name) for name in ('st_mode', 'st_nlink', 'st_dev', 'st_ino',
            'st_size', 'st_mtime_ns', 'st_ctime_ns')}
        values['st_ctime_ns'] += 100
        return SimpleNamespace(**values)
    monkeypatch.setattr(p.os, 'fstat', native)
    assert p.measure(path)['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
