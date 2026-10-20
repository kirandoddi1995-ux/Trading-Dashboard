"""Synthetic Windows-width identities. No real keys, files or archive contents."""
from __future__ import annotations

import hashlib
import json
import ast
import base64
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives import serialization

import archive_preservation_inventory as inventory
import archive_preservation_witness as w
import outcomes_private_container as bridge

PASSWORD = b'SYNTHETIC-ONLY-dedicated-unlock'
DEVICE = 12977725834036290552  # Reported width reproducer; no identity/trust anchor.
FILE_ID = 2**63 - 123


@pytest.fixture(scope='module')
def keys() -> tuple[bytes, bytes]:
    key = w.generate_encrypted_pkcs8(PASSWORD)
    return key, w.public_key_from_encrypted_pkcs8(key, PASSWORD)


def observation(device: int = DEVICE, file_id: int = FILE_ID) -> w.JsonObject:
    return cast(w.JsonObject, {'version': 'preservation-inventory-v1',
        'originals': [{'role': role, 'measured': {'sha256': 'a' * 64 if role != 'bundle'
            else bridge.PRESERVED_BUNDLE_SHA256}} for role in sorted(inventory.ROLES)],
        'cipher_copies': [{'binding': {'device': 1, 'file_id': 1}},
            {'binding': {'device': device, 'file_id': file_id}}],
        'owner_reports': {'extraction_rehearsal': False}, 'custody_verified': False})


@pytest.mark.parametrize('number', [2**53 + 1, 2**63, DEVICE, 2**64 - 1, 2**127, 2**128 - 1])
def test_exact_large_identity_sign_verify(keys: tuple[bytes, bytes], number: int) -> None:
    obs = observation(file_id=number)
    raw = w.sign_observation(keys[0], PASSWORD, obs, generation=1,
        predecessor_generation=None, predecessor_digest=None, enroll_first_generation=True)
    checked = w.verify_observation(raw, keys[1], latest_generation=1,
        latest_digest=hashlib.sha256(raw).hexdigest(), trusted_public_key_sha256=hashlib.sha256(keys[1]).hexdigest())
    assert checked.observation_json == w.canonical_json(obs)
    assert json.loads(checked.observation_json)['cipher_copies'][1]['binding']['file_id'] == number
    assert not checked.custody_verified and not checked.training_eligible


@pytest.mark.parametrize('number', [2**128, -(2**128)])
def test_json_integer_overflow_still_rejected(number: int) -> None:
    with pytest.raises(w.WitnessError, match='JSON_INTEGER_BOUND'):
        w.canonical_json({'synthetic': number})


@pytest.mark.parametrize('device,file_id,accepted', [
    (DEVICE, FILE_ID, True), (2**64 - 1, 2**128 - 1, True),
    (2**64, 1, False), (-1, 1, False), (True, 1, False),
    (1, 2**128, False), (1, -1, False), (1, 1.0, False), (1, True, False)])
def test_producer_native_id_contract(monkeypatch: pytest.MonkeyPatch,
        device: Any, file_id: Any, accepted: bool) -> None:
    # This stops at the native metadata boundary: do not pretend a Windows handle
    # was obtained on Linux. Real handle tests remain in the inventory suite.
    monkeypatch.setattr(inventory.os, 'fstat', lambda _: SimpleNamespace(
        st_mode=stat.S_IFREG, st_nlink=1, st_dev=device, st_ino=file_id))
    if accepted:
        if inventory.os.name == 'nt':
            # exercise the pure validation preceding Windows API construction
            def stop(*_: Any, **__: Any) -> Any:
                raise RuntimeError('SYNTHETIC_NATIVE_API_BOUNDARY')
            monkeypatch.setattr(inventory.ctypes, 'WinDLL', stop)
            with pytest.raises(RuntimeError, match='SYNTHETIC_NATIVE_API_BOUNDARY'):
                inventory.identity(42)
        else:
            result = inventory.identity(42)
            assert result['device'] == device and result['file_id'] == file_id
    else:
        with pytest.raises(ValueError, match='NATIVE_ID_INTEGER_BOUND'):
            inventory.identity(42)


def test_preexisting_v1_signature_bytes_unchanged(keys: tuple[bytes, bytes]) -> None:
    obs: w.JsonObject = {'claim': 'SYNTHETIC-OLD-V1', 'bytes': 123}
    payload = dict(scope='preservation-v1', generation=1, predecessor=None, observation=obs)
    # Independent copy of the original encoder, not the newly extended function.
    def old_encode(value: object) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    key = serialization.load_der_private_key(keys[0], password=PASSWORD)
    expected = old_encode(dict(payload=payload, signature=key.sign(w.DOMAIN + old_encode(payload)).hex()))  # type: ignore[union-attr,call-arg]
    actual = w.sign_observation(keys[0], PASSWORD, obs, generation=1,
        predecessor_generation=None, predecessor_digest=None, enroll_first_generation=True)
    assert actual == expected


def test_generation_limit_separate_from_observation_width(keys: tuple[bytes, bytes]) -> None:
    assert w._generation(2**63 - 1) == 2**63 - 1
    for bad in [2**63, 2**128 - 1, True, 0, -1]:
        with pytest.raises(w.WitnessError, match='GENERATION_REQUIRED'):
            w.sign_observation(keys[0], PASSWORD, observation(), generation=bad,
                predecessor_generation=None, predecessor_digest=None, enroll_first_generation=True)


def test_preflight_unchanged_measured_bytes_no_key_or_prompt(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    measured = tmp_path / 'synthetic-measured.json'
    # Noncanonical producer formatting and exact native numbers are both retained.
    raw = json.dumps(observation(), indent=2).encode()
    measured.write_bytes(raw)
    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail('Observation preflight attempted credentials/publication')
    monkeypatch.setattr(w, '_hidden_password', forbidden)
    monkeypatch.setattr(w, '_publish', forbidden)
    assert w.main(['--mode', 'check-observation', '--observation', str(measured),
        '--generation', '1', '--confirm-first-generation-enrollment', '--confirm-run']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'OBSERVATION_SIGNING_PREFLIGHT_PASSED_NOT_SIGNATURE'
    assert result['writes'] == result['credential_reads'] == 0
    assert result['signature_verified'] is result['custody_verified'] is False
    assert measured.read_bytes() == raw


def test_full_envelope_bound_precedes_secret_prompt(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], keys: tuple[bytes, bytes]) -> None:
    measured, public = tmp_path / 'observation.json', tmp_path / 'public.bin'
    measured.write_bytes(w.canonical_json({'synthetic': 'x' * (w.MAX_BYTES - 100)}))
    public.write_bytes(keys[1])
    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail('Invalid envelope reached secret/publication')
    monkeypatch.setattr(w, '_hidden_password', forbidden)
    monkeypatch.setattr(w, '_publish', forbidden)
    original_read = w._read
    def public_or_observation_only(path: Path, maximum: int) -> bytes:
        if path not in (measured, public):
            pytest.fail('Invalid envelope reached encrypted-key read')
        return original_read(path, maximum)
    monkeypatch.setattr(w, '_read', public_or_observation_only)
    assert w.main(['--mode', 'sign', '--generation', '1', '--confirm-first-generation-enrollment',
        '--observation', str(measured), '--trusted-public-key', str(public),
        '--trusted-public-key-sha256', hashlib.sha256(keys[1]).hexdigest(),
        '--key', str(tmp_path / 'must-not-read.pk8'), '--output', str(tmp_path / 'never.json'), '--confirm-run']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'JSON_SIZE_BOUND'


def test_bridge_reaches_synthetic_admission_with_exact_native_ids(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], keys: tuple[bytes, bytes]) -> None:
    public, head = tmp_path / 'public.bin', tmp_path / 'signed.json'
    obs = observation(file_id=2**128 - 1)
    raw = w.sign_observation(keys[0], PASSWORD, obs, generation=1,
        predecessor_generation=None, predecessor_digest=None, enroll_first_generation=True)
    public.write_bytes(keys[1]); head.write_bytes(raw)
    monkeypatch.setattr(bridge, 'owner_host', lambda _: None)
    monkeypatch.setattr(bridge, 'private_path', lambda _: None)
    monkeypatch.setattr(bridge, 'measure', lambda path, maximum: {'sha256':
        'a' * 64 if path.name == 'catalog' else bridge.PRESERVED_BUNDLE_SHA256})
    reached = False
    def synthetic(*_: Any) -> Any:
        nonlocal reached
        reached = True
        raise ValueError('SYNTHETIC_CONTAINER_PROOF_MISSING')
    monkeypatch.setattr(bridge, 'synthetic', synthetic)
    monkeypatch.setattr(sys, 'argv', ['bridge', '--mode', 'private', '--confirm-run', '--confirm-private-decode',
        '--run-root', str(tmp_path / 'new-run'), '--witness', str(head), '--trusted-public-key', str(public),
        '--public-sha256', hashlib.sha256(keys[1]).hexdigest(), '--latest-generation', '1',
        '--latest-digest', hashlib.sha256(raw).hexdigest(), '--catalog', str(tmp_path / 'catalog'),
        '--catalog-sha256', 'a' * 64, '--bundle', str(tmp_path / 'bundle'), '--image-id', 'sha256:' + 'a' * 64])
    assert bridge.main() == 2 and reached
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result['stage'] == 'LOCAL_SYNTHETIC_ADMISSION'
    assert result['reason'] == 'SYNTHETIC_CONTAINER_PROOF_MISSING'
    assert result['deletion_authorised'] is False
    assert str(DEVICE) not in output


@pytest.mark.parametrize('size,ok', [(15, False), (16, True), (1024, True), (1025, False)])
def test_passphrase_byte_bounds(size: int, ok: bool) -> None:
    if ok:
        w._password(b'x' * size)
    else:
        with pytest.raises(w.WitnessError, match='PASSPHRASE_BYTES_BOUND'):
            w._password(b'x' * size)


def test_preview_reports_utf8_bounds_with_zero_io(capsys: pytest.CaptureFixture[str]) -> None:
    assert w.main(['--mode', 'keygen']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['unlock_input_policy'] == dict(minimum_utf8_bytes=w.MIN_PASSPHRASE_BYTES,
        maximum_utf8_bytes=w.MAX_PASSPHRASE_BYTES, encoding='UTF-8', single_command_only=True)
    assert result['input_reads'] == result['writes'] == result['credential_reads'] == 0


@pytest.mark.parametrize('previous', [0, 2, 2**63, True])
def test_second_generation_preflight_rejects_wrong_predecessor_without_key(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, previous: Any) -> None:
    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail('Pure preflight accessed a key or prompt')
    monkeypatch.setattr(w, '_read', forbidden)
    monkeypatch.setattr(w, '_hidden_password', forbidden)
    with pytest.raises(w.WitnessError):
        w.signing_payload(observation(), 2, previous, 'a' * 64, False)


def test_utf8_bound_is_bytes_not_characters() -> None:
    w._password(('é' * 8).encode('utf-8'))  # 8 characters, 16 bytes.
    with pytest.raises(w.WitnessError, match='PASSPHRASE_BYTES_BOUND'):
        w._password(('é' * 7).encode('utf-8'))


def test_preview_is_literal_public_projection_not_credential_flow(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    sentinel = 'SYNTHETIC-PRIVATE-MATERIAL-NOT-POLICY'
    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail('Preview accessed private data or a process')
    for name in ('_read', '_publish', '_hidden_password', 'generate_encrypted_pkcs8'):
        monkeypatch.setattr(w, name, forbidden)
    # Even mutation of similarly named globals cannot become preview output.
    monkeypatch.setattr(w, 'MIN_PASSPHRASE_BYTES', sentinel)
    monkeypatch.setattr(w, 'MAX_PASSPHRASE_BYTES', sentinel)
    assert w.main(['--mode', 'keygen', '--key-output', sentinel]) == 0
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err and captured.err == ''
    source = ast.parse(Path(w.__file__).read_text(encoding='utf-8'))
    emitter = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == '_emit_public_preview')
    assert not emitter.args.args and len(emitter.body) == 2  # docstring + one literal print
    call = emitter.body[-1].value  # type: ignore[attr-defined]
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'print'
    assert len(call.args) == 1 and isinstance(call.args[0], ast.Constant) and type(call.args[0].value) is str
    assert json.loads(call.args[0].value) == json.loads(captured.out)
    assert set(json.loads(captured.out)) == {'status', 'input_reads', 'writes', 'credential_reads',
        'unlock_input_policy', 'custody_verified', 'delete_authorised', 'training_eligible'}


def test_every_raised_literal_witness_code_has_a_public_projection() -> None:
    source = ast.parse(Path(w.__file__).read_text(encoding='utf-8'))
    codes = {node.args[0].value for node in ast.walk(source)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'WitnessError'
        and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}
    assert codes == set(w.PUBLIC_ERROR_CODES)
    for code in codes:
        assert w._public_error_code(w.WitnessError(code)) == code


@pytest.mark.parametrize('mode', ['keygen', 'check-key', 'check-observation', 'sign', 'verify'])
@pytest.mark.parametrize('error_type', [w.WitnessError, OSError, ValueError])
def test_all_witness_failure_reports_do_not_echo_errors_or_arguments(mode: str, error_type: Any,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    marker = 'SYNTHETIC-PRIVATE-PATH-TOKEN-OBSERVATION'
    def reject(*_: Any, **__: Any) -> Any:
        raise error_type(marker)
    monkeypatch.setattr(w, '_required', reject)
    args = ['--mode', mode, '--confirm-run', '--key-output', marker, '--public-output', marker,
        '--key', marker, '--trusted-public-key', marker, '--observation', marker, '--output', marker,
        '--witness', marker, '--trusted-public-key-sha256', 'a' * 64, '--generation', '1']
    if mode == 'sign':
        args += ['--confirm-first-generation-enrollment']
    if mode == 'verify':
        args += ['--latest-generation', '1', '--latest-digest', 'a' * 64]
    assert w.main(args) == 2
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err and captured.err == ''
    report = json.loads(captured.out)
    assert report['code'] == 'LOCAL_WITNESS_OPERATION_NOT_ESTABLISHED'
    assert report['custody_verified'] is report['delete_authorised'] is report['training_eligible'] is False


def test_all_success_modes_emit_only_public_schema(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    key, public, obs, head = (tmp_path / name for name in ('PRIVATE-key.pk8', 'PRIVATE-public', 'PRIVATE-obs.json', 'PRIVATE-head.json'))
    marker = 'SYNTHETIC-PRIVATE-OBSERVATION-NOT-A-STATUS'
    monkeypatch.setattr(w, '_hidden_password', lambda **_: PASSWORD)
    common_fields = {'custody_verified', 'logical_restore_verified', 'delete_authorised', 'training_eligible',
        'approval_authority', 'network_requests', 'revocation_checked', 'status', 'writes'}
    blocked_values = [PASSWORD.decode(), marker, str(tmp_path)]
    def output(extra: set[str]) -> dict[str, Any]:
        captured = capsys.readouterr()
        assert captured.err == ''
        assert all(value not in captured.out + captured.err for value in blocked_values)
        result = json.loads(captured.out)
        assert set(result) == common_fields | extra
        assert result['custody_verified'] is result['delete_authorised'] is result['training_eligible'] is False
        return cast(dict[str, Any], result)
    assert w.main(['--mode', 'keygen', '--key-output', str(key), '--public-output', str(public), '--confirm-run']) == 0
    output(set())
    blocked_values += [key.read_bytes().hex(), base64.b64encode(key.read_bytes()).decode(), public.read_bytes().hex()]
    obs.write_bytes(w.canonical_json({'private-observation': marker, 'device': DEVICE}))
    trusted = ['--trusted-public-key', str(public), '--trusted-public-key-sha256', hashlib.sha256(public.read_bytes()).hexdigest()]
    assert w.main(['--mode', 'check-key', '--key', str(key), '--confirm-run'] + trusted) == 0
    output({'key_recovery_verified', 'archive_recovery_verified'})
    first = ['--generation', '1', '--confirm-first-generation-enrollment', '--observation', str(obs)]
    assert w.main(['--mode', 'check-observation', '--confirm-run'] + first) == 0
    output({'input_reads', 'credential_reads', 'signature_verified'})
    assert w.main(['--mode', 'sign', '--key', str(key), '--output', str(head), '--confirm-run'] + first + trusted) == 0
    signed = output({'generation', 'digest'})
    assert w.main(['--mode', 'verify', '--witness', str(head), '--latest-generation', '1',
        '--latest-digest', signed['digest'], '--confirm-run'] + trusted) == 0
    output({'generation', 'digest'})


@pytest.mark.parametrize('error_type', [OSError, ValueError])
def test_private_container_admission_failure_hides_private_input_errors(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error_type: Any) -> None:
    marker = 'SYNTHETIC-PRIVATE-BRIDGE-ERROR-PATH'
    def reject(*_: Any, **__: Any) -> Any:
        raise error_type(marker)
    monkeypatch.setattr(bridge, 'owner_host', lambda _: None)
    monkeypatch.setattr(bridge, 'private_path', lambda _: None)
    monkeypatch.setattr(w, '_read', reject)
    monkeypatch.setattr(sys, 'argv', ['bridge', '--mode', 'private', '--confirm-run', '--confirm-private-decode',
        '--run-root', str(tmp_path / marker), '--public-sha256', 'a' * 64, '--witness', marker, '--trusted-public-key', marker])
    assert bridge.main() == 2
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err and captured.err == ''
    report = json.loads(captured.out)
    assert report['stage'] == 'PRESERVATION_WITNESS' and report['reason'] == 'PRIVATE_ADMISSION_OR_IO_UNVERIFIED'
    assert not (tmp_path / marker).exists()


def test_inventory_error_hides_unknown_private_text(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    marker = 'SYNTHETIC-PRIVATE-INVENTORY-ERROR'
    monkeypatch.setattr(inventory, 'private_path', lambda _: None)
    def reject(*_: Any) -> Any:
        raise ValueError(marker)
    monkeypatch.setattr(inventory, 'read_json', reject)
    monkeypatch.setattr(sys, 'argv', ['inventory', '--selection', marker,
        '--output', str(tmp_path / marker), '--confirm-measure'])
    assert inventory.main() == 2
    captured = capsys.readouterr()
    assert marker not in captured.out + captured.err and captured.err == ''
    assert json.loads(captured.out)['reason'] == 'PRESERVATION_IO_OR_FORMAT_REVIEW_REQUIRED'
