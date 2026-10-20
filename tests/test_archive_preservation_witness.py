"""Disposable synthetic keys/observations only; no operational key/data reads."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
from typing import Iterator, NoReturn, cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

import archive_preservation_witness as witness

PASSWORD = b'Synthetic-only-passphrase-123'
OBS: witness.JsonObject = {'claim': 'SYNTHETIC_OWNER_OBSERVATION', 'bytes': 123, 'nested': [True, None]}


@pytest.fixture(scope='module')
def keys() -> tuple[bytes, bytes]:
    encrypted = witness.generate_encrypted_pkcs8(PASSWORD)
    return encrypted, witness.public_key_from_encrypted_pkcs8(encrypted, PASSWORD)


def first(keys: tuple[bytes, bytes]) -> bytes:
    return witness.sign_observation(keys[0], PASSWORD, OBS, generation=1,
        predecessor_generation=None, predecessor_digest=None, enroll_first_generation=True)


def verify(raw: bytes, public: bytes, generation: int = 1) -> witness.VerifiedObservation:
    return witness.verify_observation(raw, public, latest_generation=generation,
                                      latest_digest=hashlib.sha256(raw).hexdigest())


def test_encrypted_dedicated_key_roundtrip_and_immutable_no_authority(keys: tuple[bytes, bytes]) -> None:
    raw = first(keys)
    result = verify(raw, keys[1])
    assert result.signature_verified and result.scope == 'preservation-v1'
    assert result.observation_json == witness.canonical_json(OBS)
    assert result.digest == witness.witness_digest(raw)
    assert result.predecessor_generation is None and result.predecessor_digest is None
    for flag in (result.custody_verified, result.logical_restore_verified,
                 result.delete_authorised, result.training_eligible, result.approval_authority):
        assert flag is False
    with pytest.raises(FrozenInstanceError):
        setattr(result, 'custody_verified', True)
    with pytest.raises(TypeError):
        serialization.load_der_private_key(keys[0], password=None)


def test_explicit_enrollment_and_sequential_predecessor(keys: tuple[bytes, bytes]) -> None:
    with pytest.raises(witness.WitnessError, match='EXPLICIT_FIRST'):
        witness.sign_observation(keys[0], PASSWORD, OBS, generation=1,
            predecessor_generation=None, predecessor_digest=None)
    older = first(keys)
    current = witness.sign_observation(keys[0], PASSWORD, OBS, generation=2,
        predecessor_generation=1, predecessor_digest=witness.witness_digest(older))
    result = verify(current, keys[1], 2)
    assert result.predecessor_generation == 1
    assert result.predecessor_digest == witness.witness_digest(older)
    for generation, previous in ((3, 1), (2, 2), (2, None)):
        with pytest.raises(witness.WitnessError):
            witness.sign_observation(keys[0], PASSWORD, OBS, generation=generation,
                predecessor_generation=previous, predecessor_digest='a'*64)


def test_rollback_and_same_generation_fork_require_external_latest_digest(keys: tuple[bytes, bytes]) -> None:
    old = first(keys)
    new = witness.sign_observation(keys[0], PASSWORD, {'claim': 'synthetic revised claim'},
        generation=1, predecessor_generation=None, predecessor_digest=None, enroll_first_generation=True)
    with pytest.raises(witness.WitnessError, match='ANCHOR_MISMATCH'):
        witness.verify_observation(old, keys[1], latest_generation=1, latest_digest=witness.witness_digest(new))
    with pytest.raises(witness.WitnessError, match='ANCHOR_MISMATCH'):
        witness.verify_observation(old, keys[1], latest_generation=2, latest_digest=witness.witness_digest(old))


@pytest.mark.parametrize('change', ['observation', 'scope', 'generation', 'signature', 'embedded_key', 'predecessor'])
def test_tampering_never_verifies_even_with_recomputed_content_digest(keys: tuple[bytes, bytes], change: str) -> None:
    value = json.loads(first(keys))
    if change == 'observation':
        value['payload']['observation']['bytes'] = 456
    elif change == 'scope':
        value['payload']['scope'] = 'custody-v1'
    elif change == 'generation':
        value['payload']['generation'] = 2
    elif change == 'signature':
        value['signature'] = '0'*128
    elif change == 'embedded_key':
        value['public_key'] = keys[1].hex()
    else:
        value['payload']['predecessor'] = {'generation': 0, 'digest': 'a'*64}
    with pytest.raises(witness.WitnessError):
        verify(witness.canonical_json(value), keys[1])


def test_wrong_external_key_cannot_self_enroll(keys: tuple[bytes, bytes]) -> None:
    other = witness.generate_encrypted_pkcs8(PASSWORD)
    with pytest.raises(witness.WitnessError, match='SIGNATURE_NOT_VERIFIED'):
        verify(first(keys), witness.public_key_from_encrypted_pkcs8(other, PASSWORD))


@pytest.mark.parametrize('raw', [
    b'{"payload":{},"payload":{},"signature":"x"}',
    b'{"payload":{"observation":{"a":1,"a":2}},"signature":"x"}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'[]', b'{', b'\xff',
])
def test_recursive_duplicates_nonfinite_and_malformed_json_rejected(raw: bytes) -> None:
    with pytest.raises(witness.WitnessError):
        witness.witness_digest(raw)


def test_canonical_bytes_required_not_whitespace_equivalence(keys: tuple[bytes, bytes]) -> None:
    raw = first(keys)
    assert first(keys) == raw  # Ed25519 is deterministic for the same key/message.
    with pytest.raises(witness.WitnessError, match='CANONICAL_JSON_REQUIRED'):
        verify(b' '+raw, keys[1])
    assert witness.canonical_json({'z': 1, 'a': 'é'}) == witness.canonical_json({'a': 'é', 'z': 1})


@pytest.mark.parametrize('bad', [True, 0, -1, 2**63, '1', None])
def test_strict_external_generation_types(keys: tuple[bytes, bytes], bad: object) -> None:
    with pytest.raises(witness.WitnessError, match='GENERATION_REQUIRED'):
        witness.verify_observation(first(keys), keys[1], latest_generation=cast(int, bad), latest_digest='a'*64)


def test_json_structure_bounds_and_no_nonjson_coercion() -> None:
    for bad in (float('nan'), float('inf'), 2**128, (1, 2), {1: 'not string'}, '\ud800'):
        with pytest.raises(witness.WitnessError):
            witness.canonical_json(cast(witness.JsonValue, bad))
    value: witness.JsonValue = None
    for _ in range(18):
        value = [value]
    with pytest.raises(witness.WitnessError, match='STRUCTURE_BOUND'):
        witness.canonical_json(value)
    with pytest.raises(witness.WitnessError, match='SIZE_BOUND'):
        witness.canonical_json({'large': 'x'*65536})


def test_wrong_password_plaintext_and_unsupported_key_refused(keys: tuple[bytes, bytes]) -> None:
    with pytest.raises(witness.WitnessError, match='ENCRYPTED_KEY_UNAVAILABLE'):
        witness.public_key_from_encrypted_pkcs8(keys[0], b'Wrong-synthetic-password')
    plaintext = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    with pytest.raises(witness.WitnessError, match='ENCRYPTED_KEY_UNAVAILABLE'):
        witness.public_key_from_encrypted_pkcs8(plaintext, PASSWORD)
    with pytest.raises(witness.WitnessError, match='PASSPHRASE_BYTES_BOUND'):
        witness.generate_encrypted_pkcs8(b'short')


def test_cli_preview_zero_io_and_redacted_errors(monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail('Preview performed IO/key generation/password access')
    monkeypatch.setattr(witness, '_read', forbidden)
    monkeypatch.setattr(witness, '_publish', forbidden)
    monkeypatch.setattr(witness, '_hidden_password', forbidden)
    monkeypatch.setattr(Ed25519PrivateKey, 'generate', forbidden)
    assert witness.main(['--mode', 'keygen', '--key-output', 'PRIVATE_SENTINEL']) == 0
    assert json.loads(capsys.readouterr().out)['input_reads'] == 0
    assert witness.main(['--PRIVATE_SENTINEL']) == 2
    assert 'PRIVATE_SENTINEL' not in capsys.readouterr().out


def test_cli_explicit_enrollment_chain_and_verification(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(witness, '_hidden_password', lambda **_: PASSWORD)
    key, public, observation = tmp_path/'owner.pk8', tmp_path/'trusted.pub', tmp_path/'claim.json'
    head, second = tmp_path/'first.json', tmp_path/'second.json'
    assert witness.main(['--mode','keygen','--confirm-run','--key-output',str(key),
                         '--public-output',str(public)]) == 0
    observation.write_bytes(witness.canonical_json(OBS))
    common = ['--mode','sign','--confirm-run','--key',str(key),'--trusted-public-key',str(public),
              '--trusted-public-key-sha256',hashlib.sha256(public.read_bytes()).hexdigest(),
              '--observation',str(observation)]
    assert witness.main(common+['--generation','1','--output',str(head)]) == 2
    assert not head.exists()
    assert witness.main(common+['--generation','1','--output',str(head),
                               '--confirm-first-generation-enrollment']) == 0
    digest = witness.witness_digest(head.read_bytes())
    assert witness.main(common+['--generation','2','--output',str(second)]) == 2
    assert witness.main(common+['--generation','2','--output',str(second),
        '--previous-witness',str(head),'--latest-generation','1','--latest-digest',digest]) == 0
    latest = witness.witness_digest(second.read_bytes())
    command = ['--mode','verify','--confirm-run','--witness',str(second),
               '--trusted-public-key',str(public),'--trusted-public-key-sha256',
               hashlib.sha256(public.read_bytes()).hexdigest(),
               '--latest-generation','2','--latest-digest',latest]
    assert witness.main(command) == 0
    output = capsys.readouterr().out
    assert PASSWORD.decode() not in output and str(tmp_path) not in output
    result = json.loads(output.splitlines()[-1])
    assert result['custody_verified'] is result['delete_authorised'] is result['training_eligible'] is False
    assert witness.main(command[:-2]) == 2  # Missing latest digest cannot use envelope's digest.
    assert witness.main(common+['--generation','1','--output',str(head),
                               '--confirm-first-generation-enrollment']) == 2
    assert witness.witness_digest(head.read_bytes()) == digest


def test_private_paths_source_links_and_exclusive_partial_retention(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(witness.WitnessError, match='OUTSIDE_SOURCE'):
        witness._publish(witness.PROJECT_ROOT/'never-created.pk8', b'synthetic')
    target = tmp_path/'existing'
    witness._publish(target, b'synthetic')
    with pytest.raises(witness.WitnessError, match='OUTPUT_ALREADY_EXISTS'):
        witness._publish(target, b'replacement')
    assert target.read_bytes() == b'synthetic'
    def failed_sync(fd: int) -> None:
        raise OSError('PRIVATE_SENTINEL')
    monkeypatch.setattr(os, 'fsync', failed_sync)
    partial = tmp_path/'retained'
    with pytest.raises(OSError):
        witness._publish(partial, b'synthetic retained')
    assert partial.read_bytes() == b'synthetic retained'


def test_link_rejected_if_platform_permits(tmp_path: Path) -> None:
    target, link = tmp_path/'source', tmp_path/'linked'
    target.write_bytes(b'synthetic')
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('Symlink privilege absent; no permission changes')
    with pytest.raises(witness.WitnessError, match='LOCAL_NATIVE_PRIVATE_PATH_REQUIRED'):
        witness._read(link, 100)


def test_external_public_fingerprint_gate_and_no_revocation_claim(keys: tuple[bytes, bytes]) -> None:
    raw = first(keys)
    result = witness.verify_observation(raw, keys[1], latest_generation=1,
        latest_digest=witness.witness_digest(raw), trusted_public_key_sha256=hashlib.sha256(keys[1]).hexdigest())
    assert result.revocation_checked is False
    with pytest.raises(witness.WitnessError, match='PUBLIC_KEY_FINGERPRINT_MISMATCH'):
        witness.verify_observation(raw, keys[1], latest_generation=1,
            latest_digest=witness.witness_digest(raw), trusted_public_key_sha256='0'*64)


def test_mapped_remote_gate_precedes_filesystem_metadata(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    def remote(path: Path) -> None:
        raise ValueError('LOCAL_NATIVE_PATH_REQUIRED')
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail('Metadata was queried after the remote-drive rejection')
    monkeypatch.setattr(witness, 'check_local_path', remote)
    monkeypatch.setattr(Path, 'lstat', forbidden)
    with pytest.raises(witness.WitnessError, match='LOCAL_NATIVE_PRIVATE_PATH_REQUIRED'):
        witness._read(tmp_path/'never-opened', 100)


def test_aggregate_encoding_is_stream_bounded_before_materialization(monkeypatch: pytest.MonkeyPatch) -> None:
    original = json.JSONEncoder.iterencode
    chunks = 0
    def streaming(self: json.JSONEncoder, value: object, _one_shot: bool = False) -> Iterator[str]:
        nonlocal chunks
        for chunk in original(self, value, _one_shot):
            chunks += 1
            assert chunks < 6  # Do not build the potential 300 MB aggregate.
            yield chunk
    def eager(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail('Unbounded eager JSON encoding invoked')
    monkeypatch.setattr(json.JSONEncoder, 'iterencode', streaming)
    monkeypatch.setattr(json, 'dumps', eager)
    with pytest.raises(witness.WitnessError, match='JSON_SIZE_BOUND'):
        witness.canonical_json(['x'*60000]*5000)
    assert 1 <= chunks < 6


@pytest.mark.parametrize('mode', ['sign', 'verify', 'check-key'])
def test_cli_fingerprint_is_mandatory_before_input_reads(mode: str,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail('Input read before mandatory fingerprint')
    monkeypatch.setattr(witness, '_read', forbidden)
    args = ['--mode',mode,'--confirm-run','--generation','1','--latest-generation','1',
            '--latest-digest','a'*64]
    assert witness.main(args) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'EXTERNAL_DIGEST_REQUIRED'


@pytest.mark.parametrize('case', ['success', 'wrong-password', 'wrong-key', 'wrong-fingerprint', 'preview'])
def test_cli_restored_key_check_only(tmp_path: Path, keys: tuple[bytes, bytes], case: str,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    restored, trusted = tmp_path/'restored.pk8', tmp_path/'trusted.pub'
    restored.write_bytes(keys[0])
    public = keys[1]
    if case == 'wrong-key':
        public = witness.public_key_from_encrypted_pkcs8(witness.generate_encrypted_pkcs8(PASSWORD), PASSWORD)
    trusted.write_bytes(public)
    fingerprint = hashlib.sha256(public).hexdigest() if case != 'wrong-fingerprint' else '0'*64
    unlocks = 0
    def unlock(*, confirmation: bool) -> bytes:
        nonlocal unlocks
        assert confirmation is False
        unlocks += 1
        return b'Incorrect-synthetic-password' if case == 'wrong-password' else PASSWORD
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail('Key recovery check attempted a write, signing or key generation')
    monkeypatch.setattr(witness, '_hidden_password', unlock)
    monkeypatch.setattr(witness, '_publish', forbidden)
    monkeypatch.setattr(witness, 'generate_encrypted_pkcs8', forbidden)
    monkeypatch.setattr(witness, 'sign_observation', forbidden)
    args = ['--mode','check-key','--key',str(restored),'--trusted-public-key',str(trusted),
            '--trusted-public-key-sha256',fingerprint]
    if case == 'preview':
        monkeypatch.setattr(witness, '_read', forbidden)
    else:
        args.append('--confirm-run')
    assert witness.main(args) == (0 if case in ('success', 'preview') else 2)
    output = capsys.readouterr().out
    assert str(tmp_path) not in output and PASSWORD.decode() not in output
    result = json.loads(output)
    if case == 'success':
        assert result['status'] == 'KEY_RECOVERY_VERIFIED_NOT_ARCHIVE'
        assert result['key_recovery_verified'] is True
        assert result['archive_recovery_verified'] is False
        assert result['writes'] == 0
        assert result['custody_verified'] is result['logical_restore_verified'] is False
    elif case == 'preview':
        assert result['input_reads'] == result['writes'] == 0
    else:
        expected = {'wrong-password': 'ENCRYPTED_KEY_UNAVAILABLE',
                    'wrong-key': 'RECOVERED_KEY_NOT_EXTERNALLY_TRUSTED',
                    'wrong-fingerprint': 'TRUSTED_PUBLIC_KEY_FINGERPRINT_MISMATCH'}
        assert result['code'] == expected[case]
    assert unlocks == (0 if case in ('preview', 'wrong-fingerprint') else 1)
    assert restored.read_bytes() == keys[0] and trusted.read_bytes() == public


def test_predecessor_digest_is_signed_and_domain_separated(keys: tuple[bytes, bytes]) -> None:
    old = first(keys)
    raw = witness.sign_observation(keys[0], PASSWORD, OBS, generation=2,
        predecessor_generation=1, predecessor_digest=witness.witness_digest(old))
    value = json.loads(raw)
    value['payload']['predecessor']['digest'] = 'f'*64
    with pytest.raises(witness.WitnessError, match='SIGNATURE_NOT_VERIFIED'):
        verify(witness.canonical_json(value), keys[1], 2)
    value = json.loads(old)
    private = serialization.load_der_private_key(keys[0], password=PASSWORD)
    assert isinstance(private, Ed25519PrivateKey)
    value['signature'] = private.sign(witness.canonical_json(value['payload'])).hex()
    with pytest.raises(witness.WitnessError, match='SIGNATURE_NOT_VERIFIED'):
        verify(witness.canonical_json(value), keys[1])
