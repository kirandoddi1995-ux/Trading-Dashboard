"""Synthetic authenticated backup bindings; no real files, keys, data or network."""
from __future__ import annotations

from dataclasses import replace
import datetime as dt
import hashlib
import io
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

import catalog_receipts
from local_state_recovery import StateWitness, VERSION as STATE_VERSION
import recovery_bundle as bundle

KEY = b'synthetic-backup-authentication-key-only'
KEYRING = {'backup_key': KEY}
AT = dt.datetime(2026, 10, 7, 9, 15, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
ID = '12345678-1234-4234-8234-123456789abc'
CUT = '23456789-2345-4345-8345-23456789abcd'


def contract() -> bundle.BackupContract:
    """An explicit example inventory, not the app's commissioned inventory."""
    return bundle.BackupContract('backup:synthetic_app', (
        bundle.Binding('primary_state', 'sqlite_source', 'sqlite-image-v1'),
        bundle.Binding('roots', 'catalog_source', 'catalog-roots-v1'),
        bundle.Binding('release', 'code_source', 'release-manifest-v1')))


def witness() -> StateWitness:
    return StateWitness(STATE_VERSION, (1, 1, 0, 0, 0), 'a' * 64, 'b' * 64)


def artifacts() -> tuple[bundle.ArtifactDigest, ...]:
    return tuple(bundle.measure(name, io.BytesIO(value)) for name, value in (
        ('primary_state', b'SYNTHETIC STATE'), ('roots', b'SYNTHETIC ROOTS'),
        ('release', b'SYNTHETIC CODE MANIFEST')))


def seal(**changes: Any) -> bundle.SignedBundle:
    args: dict[str, Any] = dict(contract=contract(), witness=witness(), artifacts=artifacts(),
        bundle_id=ID, cut_id=CUT, at=AT, previous=bundle.genesis(contract()),
        key_id='backup_key', key=KEY)
    args.update(changes)
    return bundle.seal(**args)


def verify(signed: bundle.SignedBundle, **changes: Any) -> bundle.VerifiedBundle:
    args: dict[str, Any] = dict(checkpoint=signed.checkpoint, contract=contract(), keyring=KEYRING)
    args.update(changes)
    return bundle.verify(signed.data, **args)


def encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def test_deterministic_ist_utc_receipt_and_read_only_measurement() -> None:
    stream = io.BytesIO(b'SYNTHETIC')
    assert bundle.measure('primary_state', stream).sha256 == hashlib.sha256(b'SYNTHETIC').hexdigest()
    assert not stream.closed
    assert stream.tell() == len(b'SYNTHETIC')
    first = seal()
    second = seal(at=AT.astimezone(dt.timezone.utc), artifacts=tuple(reversed(artifacts())))
    assert first == second
    assert KEY.decode() not in first.data.decode()
    assert 'manifest' not in repr(first)
    actual = verify(first)
    assert actual.witness == witness()
    assert actual.artifacts == tuple(sorted(artifacts(), key=lambda a: a.name))
    assert repr(actual) == 'VerifiedBundle(<authenticated identities; no restore approval>)'


def test_restored_identity_pass_never_claims_capture_custody_or_application() -> None:
    signed = seal()
    result = bundle.verify_restore(signed.data, checkpoint=signed.checkpoint, contract=contract(),
        keyring=KEYRING, observed=tuple(reversed(artifacts())), restored_witness=witness())
    assert result['status'] == 'BACKUP_IDENTITIES_VERIFIED'
    assert result['artifact_count'] == 3
    assert result['metadata_authenticated'] is True
    assert result['state_witness_equality_verified'] is True
    for flag in ('capture_consistency_verified', 'custody_persistence_verified',
                 'original_signatures_verified', 'remote_recovery_verified',
                 'application_recovery_verified', 'approval_authority'):
        assert result[flag] is False


@pytest.mark.parametrize('change', [
    {'scope': 'cold:synthetic_app'}, {'scope': 'backup:'}, {'scope': 'backup:../private'},
    {'bindings': ()}, {'bindings': []},
    {'bindings': (bundle.Binding('roots', 'catalog_source', 'catalog-roots-v1'),)},
    {'bindings': (bundle.Binding('primary_state', 'sqlite_source', 'unknown'),)},
    {'bindings': (bundle.Binding('primary_state', 'sqlite_source', 'sqlite-image-v1'),) * 2},
    {'bindings': (bundle.Binding('primary_state', '../source', 'sqlite-image-v1'),)},
])
def test_invalid_or_incomplete_contract_cannot_seal(change: dict[str, Any]) -> None:
    with pytest.raises(bundle.BundleError):
        seal(contract=replace(contract(), **change))


@pytest.mark.parametrize('args', [
    {'bundle_id': ''}, {'cut_id': '../generation'}, {'bundle_id': ID.upper()},
    {'cut_id': '00000000-0000-0000-0000-000000000000'},
    {'at': dt.datetime(2026, 10, 7)}, {'at': None},
    {'previous': catalog_receipts.genesis('cold:synthetic_app')},
    {'previous': None}, {'key': b'short'}, {'key': None}, {'key_id': '../key'},
])
def test_bad_clock_generation_or_auth_is_blocked(args: dict[str, Any]) -> None:
    with pytest.raises(bundle.BundleError):
        seal(**args)


@pytest.mark.parametrize('size', [0, -1, True, 1.0, 1024 * 1024 * 1024 + 1])
def test_artifact_size_is_strict(size: Any) -> None:
    with pytest.raises(bundle.BundleError, match='BACKUP_ARTIFACT_SIZE_INVALID'):
        bundle.ArtifactDigest('primary_state', 'a' * 64, size)


@pytest.mark.parametrize('values', [
    (), artifacts()[:-1], artifacts() + (artifacts()[0],),
    (artifacts()[0], artifacts()[1], artifacts()[1]),
    (artifacts()[0], artifacts()[1], bundle.ArtifactDigest('unknown', 'a' * 64, 1)),
])
def test_missing_duplicate_extra_artifact_cannot_seal(values: tuple[bundle.ArtifactDigest, ...]) -> None:
    with pytest.raises(bundle.BundleError, match='BACKUP_INVENTORY_MISMATCH'):
        seal(artifacts=values)


def test_contract_and_manifest_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundle, 'MAX_ARTIFACTS', 2)
    with pytest.raises(bundle.BundleError, match='BACKUP_CONTRACT_INVALID'):
        seal()
    monkeypatch.setattr(bundle, 'MAX_ARTIFACTS', 64)
    monkeypatch.setattr(bundle, 'MAX_TOTAL_BYTES', 2)
    with pytest.raises(bundle.BundleError, match='BACKUP_TOTAL_SIZE_INVALID'):
        seal()
    monkeypatch.setattr(bundle, 'MAX_TOTAL_BYTES', 2 * 1024 * 1024 * 1024)
    monkeypatch.setattr(bundle, 'MAX_MANIFEST_BYTES', 10)
    with pytest.raises(bundle.BundleError, match='BACKUP_METADATA_SIZE_INVALID'):
        seal()


@pytest.mark.parametrize('keys', [{}, {'backup_key': b'wrong synthetic key material long enough'}])
def test_unknown_or_wrong_key_cannot_verify(keys: dict[str, bytes]) -> None:
    with pytest.raises(bundle.BundleError, match='BACKUP_AUTH_UNVERIFIED'):
        verify(seal(), keyring=keys)


@pytest.mark.parametrize('change', ['byte', 'receipt', 'witness', 'inventory', 'extra', 'duplicates', 'spacing'])
def test_modified_metadata_cannot_verify(change: str) -> None:
    signed = seal()
    value = json.loads(signed.data)
    if change == 'byte':
        data = signed.data[:-1] + b'!'
    elif change == 'spacing':
        data = json.dumps(value).encode()
    elif change == 'duplicates':
        data = b'{"manifest":{},"manifest":{},"receipt":""}'
    else:
        if change == 'receipt':
            value['receipt'] = value['receipt'].replace('backup_key', 'other_key')
        elif change == 'witness':
            value['manifest']['source_witness']['state_sha256'] = 'c' * 64
        elif change == 'inventory':
            value['manifest']['artifacts'].pop()
        else:
            value['manifest']['unexpected'] = True
        data = encode(value)
    with pytest.raises(bundle.BundleError):
        bundle.verify(data, checkpoint=signed.checkpoint, contract=contract(), keyring=KEYRING)


def test_two_generations_and_rotated_custody_key_reject_rollback_and_skip() -> None:
    first = seal()
    key2 = b'next-synthetic-backup-key-not-an-original-ledger-key'
    second = seal(bundle_id='34567890-3456-4456-8456-34567890abcd',
                  previous=first.checkpoint.current, key_id='next_key', key=key2)
    assert verify(second, keyring={'next_key': key2}).checkpoint.current.generation == 2
    with pytest.raises(bundle.BundleError):
        verify(first, checkpoint=second.checkpoint)
    with pytest.raises(bundle.BundleError):
        verify(second, checkpoint=first.checkpoint, keyring={'next_key': key2})
    with pytest.raises(bundle.BundleError):
        verify(second, checkpoint=replace(second.checkpoint, previous=first.checkpoint.previous),
               keyring={'next_key': key2})
    assert verify(first).checkpoint.current.generation == 1


@pytest.mark.parametrize('field,value', [('generation', True), ('generation', 0), ('generation', 5),
                                      ('root', 'bad'), ('receipt_sha256', 'bad')])
def test_bad_current_checkpoint_fails(field: str, value: Any) -> None:
    signed = seal()
    current = replace(signed.checkpoint.current, **{field: value})
    with pytest.raises(bundle.BundleError):
        verify(signed, checkpoint=replace(signed.checkpoint, current=current))


def test_no_checkpoint_or_target_derived_contract_fallback() -> None:
    signed = seal()
    with pytest.raises(bundle.BundleError, match='BACKUP_CHECKPOINT_REQUIRED'):
        verify(signed, checkpoint=None)
    changed = replace(contract(), bindings=(replace(contract().bindings[0], source_id='other_source'),
                                           *contract().bindings[1:]))
    with pytest.raises(bundle.BundleError, match='BACKUP_CONTRACT_MISMATCH'):
        verify(signed, contract=changed)


@pytest.mark.parametrize('role', ['primary_state', 'roots', 'release'])
def test_mixed_generation_artifact_is_not_a_valid_restore(role: str) -> None:
    signed = seal()
    observed = tuple(replace(a, sha256='c' * 64) if a.name == role else a for a in artifacts())
    with pytest.raises(bundle.BundleError, match='BACKUP_RESTORED_ARTIFACT_MISMATCH'):
        bundle.verify_restore(signed.data, checkpoint=signed.checkpoint, contract=contract(),
            keyring=KEYRING, observed=observed, restored_witness=witness())


@pytest.mark.parametrize('field,value', [('counts', (2, 1, 0, 0, 0)),
                                      ('schema_sha256', 'c' * 64), ('state_sha256', 'c' * 64)])
def test_restored_witness_must_equal_signed_source(field: str, value: Any) -> None:
    signed = seal()
    with pytest.raises(bundle.BundleError, match='BACKUP_RESTORED_WITNESS_MISMATCH'):
        bundle.verify_restore(signed.data, checkpoint=signed.checkpoint, contract=contract(),
            keyring=KEYRING, observed=artifacts(), restored_witness=replace(witness(), **{field: value}))


def test_stream_size_time_empty_and_private_error_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(bundle.BundleError, match='BACKUP_ARTIFACT_SIZE_INVALID'):
        bundle.measure('primary_state', io.BytesIO())
    monkeypatch.setattr(bundle, 'MAX_ARTIFACT_BYTES', 2)
    with pytest.raises(bundle.BundleError, match='BACKUP_ARTIFACT_SIZE_INVALID'):
        bundle.measure('primary_state', io.BytesIO(b'123'))
    monkeypatch.setattr(bundle, 'MAX_ARTIFACT_BYTES', 1024 * 1024 * 1024)
    clock = iter([0.0, 61.0])
    monkeypatch.setattr(bundle, 'time', SimpleNamespace(monotonic=lambda: next(clock)))
    with pytest.raises(bundle.BundleError, match='BACKUP_MEASURE_TIME_BOUND'):
        bundle.measure('primary_state', io.BytesIO(b'123'))
    monkeypatch.setattr(bundle, 'time', SimpleNamespace(monotonic=lambda: 0.0))
    class BrokenStream:
        def read(self, size: int) -> bytes:
            raise OSError('PRIVATE_PATH_AND_SECRET_NEVER_PRINT')
    with pytest.raises(bundle.BundleError, match='BACKUP_STREAM_UNAVAILABLE') as error:
        bundle.measure('primary_state', cast(io.BytesIO, BrokenStream()))
    assert 'PRIVATE' not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize('returned', ['text', None, b'x' * (1024 * 1024 + 1)],
                         ids=['text', 'none', 'oversized'])
def test_malformed_reader_cannot_supply_a_passing_prefix(returned: Any) -> None:
    class BadStream:
        def read(self, size: int) -> Any:
            return returned
    with pytest.raises(bundle.BundleError, match='BACKUP_STREAM_INVALID'):
        bundle.measure('primary_state', cast(io.BytesIO, BadStream()))


def test_even_signed_receipt_cannot_bind_wrong_contract_digest() -> None:
    signed = seal()
    value = json.loads(signed.data)
    receipt = catalog_receipts.sign(signed.checkpoint.previous, signed.checkpoint.current.root,
                                   '0' * 64, AT, 'backup_key', KEY)
    value['receipt'] = receipt.data.decode()
    checkpoint = bundle.BundleCheckpoint(signed.checkpoint.previous, receipt.anchor)
    with pytest.raises(bundle.BundleError, match='BACKUP_CONTRACT_MISMATCH'):
        bundle.verify(encode(value), checkpoint=checkpoint, contract=contract(), keyring=KEYRING)


@pytest.mark.parametrize('changed', ['missing', 'extra', 'oversized_list', 'bad_counts', 'bad_version'])
def test_structural_metadata_rejected_before_authentication(changed: str) -> None:
    signed = seal()
    value = json.loads(signed.data)
    if changed == 'missing':
        del value['manifest']['source_witness']
    elif changed == 'extra':
        value['manifest']['source_witness']['secret'] = 'synthetic-only'
    elif changed == 'oversized_list':
        value['manifest']['artifacts'] = value['manifest']['artifacts'] * 30
    elif changed == 'bad_counts':
        value['manifest']['source_witness']['counts'] = '11111'
    else:
        value['manifest']['source_witness']['version'] = 'invented'
    with pytest.raises(bundle.BundleError):
        bundle.verify(encode(value), checkpoint=signed.checkpoint, contract=contract(), keyring=KEYRING)


def test_metadata_limits_empty_malformed_utf8_and_key_adapter_error(monkeypatch: pytest.MonkeyPatch) -> None:
    signed = seal()
    for data in (b'', b'\xff', b'[]', b'{}', b'x' * (bundle.MAX_MANIFEST_BYTES + 1)):
        with pytest.raises(bundle.BundleError):
            bundle.verify(data, checkpoint=signed.checkpoint, contract=contract(), keyring=KEYRING)
    def fail(*args: Any) -> Any:
        raise OSError('PRIVATE_KEY_ADAPTER_DETAIL')
    monkeypatch.setattr(catalog_receipts, 'verify', fail)
    with pytest.raises(bundle.BundleError, match='BACKUP_AUTH_UNVERIFIED') as error:
        verify(signed)
    assert 'PRIVATE' not in str(error.value)
    assert error.value.__suppress_context__
