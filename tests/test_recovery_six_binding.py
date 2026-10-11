"""Synthetic joint binding: neither private files nor owner keys are accessed."""
from __future__ import annotations

from dataclasses import replace
import datetime as dt
import hashlib
import io
import json
from typing import Any

import pytest

from local_state_recovery import StateWitness, VERSION as STATE_VERSION
import recovery_bundle as bundle
import recovery_six_binding as six
from terminal_intent_snapshot import IntentWitness, VERSION as INTENT_VERSION

KEY = b'synthetic-six-table-binding-key-only'
ID = '12345678-1234-4234-8234-123456789abc'
CUT = '23456789-2345-4345-8345-23456789abcd'
AT = dt.datetime(2026, 10, 12, tzinfo=dt.timezone.utc)
PRIMARY = StateWitness(STATE_VERSION, (1, 0, 0, 0, 0), 'a' * 64, 'b' * 64)
INTENTS = IntentWitness(INTENT_VERSION, 0, 'c' * 64)
CONTRACT = bundle.BackupContract('backup:synthetic_six', (
    bundle.Binding('primary_state', 'same_sqlite_cut', 'sqlite-image-v1'),
    bundle.Binding(six.NAME, 'same_sqlite_cut', 'derived-state-v1')))
IMAGE = bundle.measure('primary_state', io.BytesIO(b'SYNTHETIC FULL IMAGE'))


def seal(**changes: Any) -> six.SixBinding:
    args: dict[str, Any] = dict(contract=CONTRACT, witness=PRIMARY, intents=INTENTS,
        artifacts=(IMAGE,), bundle_id=ID, cut_id=CUT, at=AT, previous=bundle.genesis(CONTRACT),
        key_id='fixture', key=KEY)
    args.update(changes)
    return six.seal(**args)


def verify(value: six.SixBinding, **changes: Any) -> dict[str, object]:
    digest = bundle.ArtifactDigest(six.NAME, hashlib.sha256(value.witness_bytes).hexdigest(), len(value.witness_bytes))
    args: dict[str, Any] = dict(checkpoint=value.signed.checkpoint, contract=CONTRACT,
        keyring={'fixture': KEY}, observed=(IMAGE, digest), restored_primary=PRIMARY,
        restored_intents=INTENTS)
    args.update(changes)
    return six.verify_restore(value.signed.data, value.witness_bytes, **args)


def test_joint_signature_deterministic_and_never_custody() -> None:
    value = seal()
    assert seal().signed.data == value.signed.data
    result = verify(value)
    assert result['status'] == 'SIX_TABLE_IMAGE_IDENTITIES_VERIFIED'
    assert result['sixth_witness_authenticated'] is True
    for flag in ('independent_custody_verified', 'capture_consistency_verified',
                 'application_recovery_verified', 'approval_authority', 'deletion_authorised'):
        assert result[flag] is False
    assert KEY.decode() not in value.signed.data.decode()
    assert 'witness_bytes' not in repr(value)


@pytest.mark.parametrize('change', [
    {'restored_intents': replace(INTENTS, count=1)},
    {'restored_intents': replace(INTENTS, sha256='d' * 64)},
    {'restored_primary': replace(PRIMARY, state_sha256='d' * 64)},
    {'keyring': {}}, {'checkpoint': None}, {'observed': (IMAGE,)},
    {'observed': (replace(IMAGE, sha256='d' * 64),)},
])
def test_missing_or_swapped_identity_blocks(change: dict[str, Any]) -> None:
    with pytest.raises(bundle.BundleError):
        verify(seal(), **change)


@pytest.mark.parametrize('metadata', [b'', b'{}', b'[]', b'x' * (six.MAX_BYTES + 1),
                                    b'\xff', b'{"version":1,"version":2}'])
def test_corrupt_metadata_blocks(metadata: bytes) -> None:
    value = seal()
    with pytest.raises(bundle.BundleError):
        verify(replace(value, witness_bytes=metadata))


def test_valid_other_cut_cannot_be_spliced() -> None:
    first = seal()
    second = seal(cut_id='34567890-3456-4456-8456-34567890abcd')
    with pytest.raises(bundle.BundleError):
        verify(replace(first, witness_bytes=second.witness_bytes))


@pytest.mark.parametrize('bindings', [CONTRACT.bindings[:1],
    (CONTRACT.bindings[0], replace(CONTRACT.bindings[1], source_id='other_source')),
    (CONTRACT.bindings[0], replace(CONTRACT.bindings[1], format='sqlite-image-v1'))])
def test_missing_sixth_or_cross_file_contract_blocks(bindings: Any) -> None:
    with pytest.raises(bundle.BundleError):
        seal(contract=replace(CONTRACT, bindings=bindings))


def test_one_signed_root_covers_both_witnesses_and_image() -> None:
    value = seal()
    outer = json.loads(value.signed.data)['manifest']
    body = json.loads(value.witness_bytes)
    assert body['cut_id'] == outer['cut_id']
    assert body['primary'] == outer['source_witness']
    assert body['image']['sha256'] == IMAGE.sha256
    assert {a['name'] for a in outer['artifacts']} == {'primary_state', six.NAME}


@pytest.mark.parametrize('change', [{'contract': None}, {'witness': None}, {'intents': None},
    {'artifacts': None}, {'artifacts': (None,)}, {'cut_id': ''}, {'at': dt.datetime(2026, 10, 12)},
    {'key': b'short'}, {'previous': None}])
def test_invalid_typed_boundary_is_redacted(change: dict[str, Any]) -> None:
    with pytest.raises(bundle.BundleError):
        seal(**change)
