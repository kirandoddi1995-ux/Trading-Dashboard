"""Synthetic ephemeral key bytes only; never read the preservation key or files."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib

import pytest

import archive_preservation_witness as w
import archive_recovery_binding as b


@pytest.fixture(scope='module')
def chain() -> tuple[bytes, bytes, bytes, str]:
    unlock = b'Synthetic-only-binding-test-1234'
    key = w.generate_encrypted_pkcs8(unlock)
    public = w.public_key_from_encrypted_pkcs8(key, unlock)
    parent = w.sign_observation(key, unlock, {'purpose': 'SYNTHETIC_PARENT'},
        generation=1, predecessor_generation=None, predecessor_digest=None,
        enroll_first_generation=True)
    return key, public, parent, hashlib.sha256(public).hexdigest()


def artifacts() -> tuple[b.Artifact, ...]:
    return tuple(b.Artifact(role, hashlib.sha256(role.encode()).hexdigest(), 123)
                 for role in sorted(b.ROLES))


def proposal(chain: tuple[bytes, bytes, bytes, str], refs: tuple[b.Artifact, ...]) -> w.JsonObject:
    _, public, parent, fingerprint = chain
    return b.observation(parent_witness=parent, public_key=public,
        parent_generation=1, parent_digest=w.witness_digest(parent),
        public_sha256=fingerprint, artifacts=refs)


def signed(chain: tuple[bytes, bytes, bytes, str], obs: w.JsonObject) -> bytes:
    return w.sign_observation(chain[0], b'Synthetic-only-binding-test-1234', obs,
        generation=2, predecessor_generation=1, predecessor_digest=w.witness_digest(chain[2]))


def verify(chain: tuple[bytes, bytes, bytes, str], raw: bytes,
           refs: tuple[b.Artifact, ...]) -> b.BindingReview:
    return b.verify_binding(signed=raw, public_key=chain[1], latest_generation=2,
        latest_digest=w.witness_digest(raw), public_sha256=chain[3],
        parent_witness=chain[2], parent_generation=1,
        parent_digest=w.witness_digest(chain[2]), measured_artifacts=refs)


def test_signed_exact_references_not_custody_restore_or_receipt_authentication(chain: tuple[bytes, bytes, bytes, str]) -> None:
    refs = artifacts()
    obs = proposal(chain, refs)
    assert obs == proposal(chain, tuple(reversed(refs)))
    result = verify(chain, signed(chain, obs), refs)
    assert result.signature_verified is True
    assert all(value is False for key, value in asdict(result).items()
               if type(value) is bool and key != 'signature_verified')


@pytest.mark.parametrize('role', sorted(b.ROLES))
def test_each_changed_artifact_breaks_binding(chain: tuple[bytes, bytes, bytes, str], role: str) -> None:
    refs = artifacts()
    raw = signed(chain, proposal(chain, refs))
    changed = tuple(replace(item, sha256='f' * 64) if item.role == role else item for item in refs)
    with pytest.raises(ValueError, match='EXACT_EVIDENCE_BINDING_REQUIRED'):
        verify(chain, raw, changed)


@pytest.mark.parametrize('field,value', [('purpose', 'custody'), ('custody_verified', True),
    ('deletion_authorised', True), ('receipt_claims_authenticated', True),
    ('training_eligible', True), ('extra', 'unreviewed')])
def test_signed_unreviewed_semantics_rejected(chain: tuple[bytes, bytes, bytes, str], field: str, value: w.JsonValue) -> None:
    obs = proposal(chain, artifacts())
    obs[field] = value
    with pytest.raises(ValueError, match='EXACT_EVIDENCE_BINDING_REQUIRED'):
        verify(chain, signed(chain, obs), artifacts())


def test_wrong_external_parent_or_key_anchor_rejected(chain: tuple[bytes, bytes, bytes, str]) -> None:
    for bad in ('parent_digest', 'public_sha256'):
        args = dict(parent_witness=chain[2], public_key=chain[1], parent_generation=1,
            parent_digest=w.witness_digest(chain[2]), public_sha256=chain[3], artifacts=artifacts())
        args[bad] = 'f' * 64
        with pytest.raises(w.WitnessError):
            b.observation(**args)  # type: ignore[arg-type]


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'list', 'wrong_type'])
def test_exact_role_set_required(chain: tuple[bytes, bytes, bytes, str], change: str) -> None:
    refs = artifacts()
    changed = refs[:-1] if change == 'missing' else refs[:-1] + (refs[0],)
    if change == 'list':
        changed = list(refs)  # type: ignore[assignment]
    if change == 'wrong_type':
        changed = refs[:-1] + (None,)  # type: ignore[assignment]
    with pytest.raises(ValueError, match='EXACT_ARTIFACT_SET_REQUIRED'):
        proposal(chain, changed)


@pytest.mark.parametrize('size', [True, 0, -1, 4 * 1024**3 + 1, 1.0])
def test_artifact_size_bound(size: int) -> None:
    with pytest.raises(ValueError, match='ARTIFACT_SIZE_BOUND'):
        b.Artifact('catalog', 'a' * 64, size)


def test_rollback_and_wrong_signature_rejected(chain: tuple[bytes, bytes, bytes, str]) -> None:
    with pytest.raises(ValueError):
        verify(chain, chain[2], artifacts())
    raw = signed(chain, proposal(chain, artifacts()))
    tampered = raw.replace(b'"signature":"', b'"signature":"f', 1)
    with pytest.raises(ValueError):
        verify(chain, tampered, artifacts())


def test_size_change_and_validly_signed_wrong_parent_rejected(chain: tuple[bytes, bytes, bytes, str]) -> None:
    refs = artifacts()
    obs = proposal(chain, refs)
    raw = signed(chain, obs)
    with pytest.raises(ValueError, match='EXACT_EVIDENCE_BINDING_REQUIRED'):
        verify(chain, raw, (replace(refs[0], size_bytes=124), *refs[1:]))
    wrong_parent = w.sign_observation(chain[0], b'Synthetic-only-binding-test-1234', obs,
        generation=2, predecessor_generation=1, predecessor_digest='f' * 64)
    with pytest.raises(ValueError, match='EXACT_EVIDENCE_BINDING_REQUIRED'):
        verify(chain, wrong_parent, refs)


@pytest.mark.parametrize('role,digest', [('unknown', 'a' * 64), ('catalog', 'A' * 64),
    ('catalog', 'private text'), ('catalog', None)])
def test_invalid_role_and_hash_do_not_leak_received_values(role: str, digest: str) -> None:
    with pytest.raises(ValueError) as captured:
        b.Artifact(role, digest, 1)
    assert str(captured.value) in ('EXACT_ARTIFACT_ROLE_REQUIRED', 'EXACT_DIGEST_REQUIRED')
