"""Inactive byte API: authenticate evidence references, NEVER physical custody.

No file reads, key discovery, prompts, signing, transport or publication. A future
native-handle adapter must measure these artifacts at their REAL destinations.
This typed observation uses the existing preservation-v1 signature envelope and
explicit purpose; no new cryptography or production key/mode is introduced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import cast

import archive_preservation_witness as witness

PURPOSE = 'recovery-evidence-binding-v1'
ROLES = frozenset({'catalog', 'bundle', 'ciphertext', 'structural_intent',
                   'structural_binding', 'structural_result'})


def _digest(value: object) -> str:
    if type(value) is not str or re.fullmatch('[a-f0-9]{64}', value) is None:
        raise ValueError('EXACT_DIGEST_REQUIRED')
    return value


@dataclass(frozen=True, repr=False)
class Artifact:
    role: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if type(self.role) is not str or self.role not in ROLES:
            raise ValueError('EXACT_ARTIFACT_ROLE_REQUIRED')
        _digest(self.sha256)
        if type(self.size_bytes) is not int or not 1 <= self.size_bytes <= 4 * 1024**3:
            raise ValueError('ARTIFACT_SIZE_BOUND')


def observation(*, parent_witness: bytes, public_key: bytes,
                parent_generation: int, parent_digest: str, public_sha256: str,
                artifacts: tuple[Artifact, ...]) -> witness.JsonObject:
    """Verify externally anchored parent; produce a purpose-limited proposal.

    References bind exact opaque bytes only. They do not assert that the B result
    is true, that its image ran, or that original Drive receipts were signed.
    A valid parent may itself be a prior evidence binding; append, never reset.
    """
    parent = witness.verify_observation(parent_witness, public_key,
        latest_generation=parent_generation, latest_digest=parent_digest,
        trusted_public_key_sha256=public_sha256)
    if type(artifacts) is not tuple or len(artifacts) != len(ROLES):
        raise ValueError('EXACT_ARTIFACT_SET_REQUIRED')
    if any(type(item) is not Artifact for item in artifacts):
        raise ValueError('EXACT_ARTIFACT_SET_REQUIRED')
    for item in artifacts:
        item.__post_init__()
    if {item.role for item in artifacts} != ROLES:
        raise ValueError('EXACT_ARTIFACT_SET_REQUIRED')
    references: list[witness.JsonValue] = [cast(witness.JsonValue, {
        'role': item.role, 'sha256': item.sha256, 'size_bytes': item.size_bytes})
        for item in sorted(artifacts, key=lambda item: item.role)]
    return dict(purpose=PURPOSE,
        parent=dict(generation=parent.generation, digest=parent.digest),
        artifacts=references, custody_verified=False, restore_verified=False,
        receipt_claims_authenticated=False, deletion_authorised=False, training_eligible=False)


@dataclass(frozen=True)
class BindingReview:
    status: str = field(default='SIGNED_REFERENCES_VERIFIED_NOT_CUSTODY', init=False)
    signature_verified: bool = field(default=True, init=False)
    custody_verified: bool = field(default=False, init=False)
    restore_verified: bool = field(default=False, init=False)
    receipt_claims_authenticated: bool = field(default=False, init=False)
    deletion_authorised: bool = field(default=False, init=False)
    training_eligible: bool = field(default=False, init=False)


def verify_binding(*, signed: bytes, public_key: bytes, latest_generation: int,
                   latest_digest: str, public_sha256: str, parent_witness: bytes,
                   parent_generation: int, parent_digest: str,
                   measured_artifacts: tuple[Artifact, ...]) -> BindingReview:
    """Externally anchored signed head AND parent AND remeasured exact references.

    This is not an IO adapter. Passing copied manifest digests as 'measured'
    would authenticate only those assertions, not custody. Never use this result
    alone for archive deletion or same-generation restore admission.
    """
    expected = observation(parent_witness=parent_witness, public_key=public_key,
        parent_generation=parent_generation, parent_digest=parent_digest,
        public_sha256=public_sha256, artifacts=measured_artifacts)
    checked = witness.verify_observation(signed, public_key,
        latest_generation=latest_generation, latest_digest=latest_digest,
        trusted_public_key_sha256=public_sha256)
    if (checked.generation != parent_generation + 1
            or checked.predecessor_generation != parent_generation
            or checked.predecessor_digest != parent_digest
            or checked.observation_json != witness.canonical_json(expected)):
        raise ValueError('EXACT_EVIDENCE_BINDING_REQUIRED')
    return BindingReview()
