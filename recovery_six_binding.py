"""Inactive six-table/full-image identity binding using existing signed bundles.

No new cryptography, key discovery, export, replica write, restore or deletion.
Both witnesses, image and cut identity are covered by ONE existing signed root.
Equality is not proof of capture consistency or independent physical custody.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import datetime as dt
import hashlib
import json
from typing import Any

import catalog_receipts
from local_state_recovery import StateWitness
from operational_receipt_history import decode_object
import recovery_bundle as bundle
from terminal_intent_snapshot import IntentWitness

VERSION = 'six-table-image-binding-v1'
NAME = 'six_table_witness'
MAX_BYTES = 16 * 1024


@dataclass(frozen=True, repr=False)
class SixBinding:
    """Proposed signed bundle plus its mandatory measured witness artifact."""
    signed: bundle.SignedBundle = field(repr=False)
    witness_bytes: bytes = field(repr=False)


def _contract(contract: bundle.BackupContract) -> None:
    bundle.genesis(contract)  # Validation only; never used as the expected checkpoint.
    primary = [b for b in contract.bindings if b.name == 'primary_state']
    sixth = [b for b in contract.bindings if b.name == NAME]
    if (len(primary) != 1 or len(sixth) != 1 or primary[0].format != 'sqlite-image-v1'
            or sixth[0].format != 'derived-state-v1' or primary[0].source_id != sixth[0].source_id):
        raise bundle.BundleError('SIX_SAME_SOURCE_CONTRACT_REQUIRED')


def _body(witness: StateWitness, intents: IntentWitness, image: bundle.ArtifactDigest,
          cut_id: str) -> dict[str, Any]:
    if (type(witness) is not StateWitness or type(intents) is not IntentWitness
            or type(image) is not bundle.ArtifactDigest):
        raise bundle.BundleError('SIX_WITNESS_INVALID')
    StateWitness(witness.version, witness.counts, witness.schema_sha256, witness.state_sha256)
    IntentWitness(intents.version, intents.count, intents.sha256)
    bundle.ArtifactDigest(image.name, image.sha256, image.size_bytes)
    if image.name != 'primary_state':
        raise bundle.BundleError('SIX_PRIMARY_IMAGE_REQUIRED')
    return {'version': VERSION, 'cut_id': cut_id,
            'primary': {'version': witness.version, 'counts': list(witness.counts),
                        'schema_sha256': witness.schema_sha256, 'state_sha256': witness.state_sha256},
            'intents': {'version': intents.version, 'count': intents.count, 'sha256': intents.sha256},
            'image': {'name': image.name, 'sha256': image.sha256, 'size_bytes': image.size_bytes}}


def _encode(body: dict[str, Any]) -> bytes:
    data = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()
    if len(data) > MAX_BYTES:
        raise bundle.BundleError('SIX_METADATA_LIMIT')
    return data


def seal(contract: bundle.BackupContract, witness: StateWitness, intents: IntentWitness,
         artifacts: tuple[bundle.ArtifactDigest, ...], *, bundle_id: str, cut_id: str,
         at: dt.datetime, previous: catalog_receipts.RootAnchor, key_id: str, key: bytes) -> SixBinding:
    """Bind both independently measured witnesses and full image in one proposal."""
    _contract(contract)
    if type(artifacts) is not tuple or any(type(a) is not bundle.ArtifactDigest for a in artifacts):
        raise bundle.BundleError('SIX_ARTIFACTS_INVALID')
    images = [a for a in artifacts if a.name == 'primary_state']
    if len(images) != 1 or any(a.name == NAME for a in artifacts):
        raise bundle.BundleError('SIX_PRIMARY_IMAGE_REQUIRED')
    encoded = _encode(_body(witness, intents, images[0], cut_id))
    digest = bundle.ArtifactDigest(NAME, hashlib.sha256(encoded).hexdigest(), len(encoded))
    signed = bundle.seal(contract, witness, artifacts + (digest,), bundle_id=bundle_id,
                         cut_id=cut_id, at=at, previous=previous, key_id=key_id, key=key)
    return SixBinding(signed, encoded)


def verify_restore(data: bytes, witness_bytes: bytes, *, checkpoint: bundle.BundleCheckpoint,
                   contract: bundle.BackupContract, keyring: Mapping[str, bytes],
                   observed: tuple[bundle.ArtifactDigest, ...], restored_primary: StateWitness,
                   restored_intents: IntentWitness) -> dict[str, object]:
    """Exact joint identity check against independent checkpoint; never activation."""
    _contract(contract)
    verified = bundle.verify(data, checkpoint=checkpoint, contract=contract, keyring=keyring)
    try:
        if type(witness_bytes) is not bytes or not 1 <= len(witness_bytes) <= MAX_BYTES:
            raise bundle.BundleError('SIX_METADATA_LIMIT')
        body = decode_object(witness_bytes.decode('utf-8'), max_bytes=MAX_BYTES)
        # Outer data has already passed bounded canonical signature verification.
        manifest = json.loads(data)['manifest']
        image = next(a for a in verified.artifacts if a.name == 'primary_state')
        expected = _body(restored_primary, restored_intents, image, manifest['cut_id'])
        if body != expected or witness_bytes != _encode(expected):
            raise bundle.BundleError('SIX_WITNESS_OR_CUT_MISMATCH')
        digest = bundle.ArtifactDigest(NAME, hashlib.sha256(witness_bytes).hexdigest(), len(witness_bytes))
        if digest not in verified.artifacts:
            raise bundle.BundleError('SIX_METADATA_DIGEST_MISMATCH')
        result = bundle.verify_restore(data, checkpoint=checkpoint, contract=contract,
            keyring=keyring, observed=observed, restored_witness=restored_primary)
    except bundle.BundleError:
        raise
    except Exception:
        raise bundle.BundleError('SIX_BINDING_UNVERIFIED') from None
    result.update(status='SIX_TABLE_IMAGE_IDENTITIES_VERIFIED', sixth_witness_authenticated=True,
                  independent_custody_verified=False, deletion_authorised=False)
    return result
