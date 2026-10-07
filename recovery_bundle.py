"""Offline authenticated backup bindings; no export, restore or custody commit.

The independently retained checkpoint and reviewed inventory are caller-owned.
Signing declared metadata does not prove a consistent capture or a durable copy.
Original event signatures and remote acknowledgements need their own adapters.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import datetime as dt
import hashlib
import hmac
import json
import re
import time
from typing import Any, BinaryIO, cast
import uuid

import catalog_receipts as receipts
from local_state_recovery import StateWitness

VERSION = 'recovery-bundle-v1'
MAX_MANIFEST_BYTES = 128 * 1024
MAX_ARTIFACTS = 64
MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * MAX_ARTIFACT_BYTES
READ_BYTES = 1024 * 1024
MAX_MEASURE_SECONDS = 60.0
FORMATS = frozenset({'sqlite-image-v1', 'catalog-roots-v1', 'cold-index-v1',
                     'release-manifest-v1', 'derived-state-v1'})


class BundleError(ValueError):
    """Stable errors, never private paths, payloads, key values or driver text."""


def _name(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', value) is None:
        raise BundleError('BACKUP_IDENTITY_INVALID')
    return value


def _hash(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise BundleError('BACKUP_DIGEST_INVALID')
    return value


def _uuid(value: object) -> str:
    try:
        parsed = uuid.UUID(cast(str, value))
        if not isinstance(value, str) or str(parsed) != value or parsed.int == 0:
            raise ValueError
    except Exception:
        raise BundleError('BACKUP_GENERATION_ID_INVALID') from None
    return value


def _json(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False).encode('utf-8')
    except Exception:
        raise BundleError('BACKUP_METADATA_INVALID') from None


@dataclass(frozen=True)
class Binding:
    """Reviewed logical role/source/format, never a filename or connection URL."""
    name: str
    source_id: str
    format: str


@dataclass(frozen=True)
class BackupContract:
    """Expected inventory retained outside the restored target/backup bundle."""
    scope: str
    bindings: tuple[Binding, ...]


@dataclass(frozen=True)
class ArtifactDigest:
    """One measured artifact; its origin/consistency is not asserted here."""
    name: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _name(self.name)
        _hash(self.sha256)
        if type(self.size_bytes) is not int or not 1 <= self.size_bytes <= MAX_ARTIFACT_BYTES:
            raise BundleError('BACKUP_ARTIFACT_SIZE_INVALID')


@dataclass(frozen=True)
class BundleCheckpoint:
    """Independent previous/current anchors; caller must commit custody safely."""
    previous: receipts.RootAnchor
    current: receipts.RootAnchor


@dataclass(frozen=True)
class SignedBundle:
    """Proposed metadata/checkpoint, NOT a persisted or replicated backup."""
    data: bytes = field(repr=False)
    checkpoint: BundleCheckpoint


@dataclass(frozen=True, repr=False)
class VerifiedBundle:
    """Authenticated declared identities; no whole-application restore claim."""
    witness: StateWitness
    artifacts: tuple[ArtifactDigest, ...]
    checkpoint: BundleCheckpoint

    def __repr__(self) -> str:
        return 'VerifiedBundle(<authenticated identities; no restore approval>)'


def _contract(contract: BackupContract) -> dict[str, Any]:
    if (type(contract) is not BackupContract or not isinstance(contract.scope, str)
            or not contract.scope.startswith('backup:')):
        raise BundleError('BACKUP_CONTRACT_INVALID')
    _name(contract.scope[7:])
    if type(contract.bindings) is not tuple or not 1 <= len(contract.bindings) <= MAX_ARTIFACTS:
        raise BundleError('BACKUP_CONTRACT_INVALID')
    bindings = []
    seen: set[str] = set()
    for binding in contract.bindings:
        if type(binding) is not Binding:
            raise BundleError('BACKUP_CONTRACT_INVALID')
        _name(binding.name)
        _name(binding.source_id)
        if not isinstance(binding.format, str) or binding.format not in FORMATS or binding.name in seen:
            raise BundleError('BACKUP_CONTRACT_INVALID')
        seen.add(binding.name)
        bindings.append({'name': binding.name, 'source_id': binding.source_id, 'format': binding.format})
    if not any(b['name'] == 'primary_state' and b['format'] == 'sqlite-image-v1' for b in bindings):
        raise BundleError('BACKUP_PRIMARY_STATE_REQUIRED')
    return {'scope': contract.scope, 'bindings': sorted(bindings, key=lambda b: b['name'])}


def genesis(contract: BackupContract) -> receipts.RootAnchor:
    """Explicit bootstrap only; never substitute for a lost trusted checkpoint."""
    _contract(contract)
    return receipts.genesis(contract.scope)


def measure(name: str, stream: BinaryIO) -> ArtifactDigest:
    """Hash a caller-opened stream, bounded between reads; never close or rewind it.

    A blocking reader needs its own I/O timeout. This is not path validation,
    an export/snapshot operation, or permission to inspect real private files.
    """
    _name(name)
    digest = hashlib.sha256()
    size = 0
    deadline = time.monotonic() + MAX_MEASURE_SECONDS
    try:
        while True:
            chunk = stream.read(READ_BYTES)
            if time.monotonic() > deadline:
                raise BundleError('BACKUP_MEASURE_TIME_BOUND')
            if type(chunk) is not bytes or len(chunk) > READ_BYTES:
                raise BundleError('BACKUP_STREAM_INVALID')
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise BundleError('BACKUP_ARTIFACT_SIZE_INVALID')
            digest.update(chunk)
    except BundleError:
        raise
    except Exception:
        raise BundleError('BACKUP_STREAM_UNAVAILABLE') from None
    return ArtifactDigest(name, digest.hexdigest(), size)


def _artifacts(contract: BackupContract, values: tuple[ArtifactDigest, ...]) -> list[dict[str, Any]]:
    expected = {b['name'] for b in _contract(contract)['bindings']}
    if type(values) is not tuple or len(values) != len(expected):
        raise BundleError('BACKUP_INVENTORY_MISMATCH')
    seen: set[str] = set()
    result = []
    total = 0
    for value in values:
        if type(value) is not ArtifactDigest:
            raise BundleError('BACKUP_INVENTORY_MISMATCH')
        # Revalidate at the trust boundary, including objects constructed unsafely.
        ArtifactDigest(value.name, value.sha256, value.size_bytes)
        if value.name not in expected or value.name in seen:
            raise BundleError('BACKUP_INVENTORY_MISMATCH')
        seen.add(value.name)
        total += value.size_bytes
        if total > MAX_TOTAL_BYTES:
            raise BundleError('BACKUP_TOTAL_SIZE_INVALID')
        result.append({'name': value.name, 'sha256': value.sha256, 'size_bytes': value.size_bytes})
    return sorted(result, key=lambda a: a['name'])


def _witness(value: StateWitness) -> dict[str, Any]:
    if type(value) is not StateWitness:
        raise BundleError('BACKUP_WITNESS_INVALID')
    try:
        StateWitness(value.version, value.counts, value.schema_sha256, value.state_sha256)
    except Exception:
        raise BundleError('BACKUP_WITNESS_INVALID') from None
    return {'version': value.version, 'counts': list(value.counts),
            'schema_sha256': value.schema_sha256, 'state_sha256': value.state_sha256}


def _instant(at: dt.datetime) -> dt.datetime:
    try:
        if type(at) is not dt.datetime or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError
        return at.astimezone(dt.timezone.utc)
    except Exception:
        raise BundleError('BACKUP_CLOCK_INVALID') from None


def _manifest(contract: BackupContract, witness: StateWitness, artifacts: tuple[ArtifactDigest, ...],
              bundle_id: str, cut_id: str, at: dt.datetime) -> dict[str, Any]:
    return {'version': VERSION, 'contract': _contract(contract), 'bundle_id': _uuid(bundle_id),
            'cut_id': _uuid(cut_id), 'created_at': _instant(at).isoformat(),
            'source_witness': _witness(witness), 'artifacts': _artifacts(contract, artifacts)}


def seal(contract: BackupContract, witness: StateWitness, artifacts: tuple[ArtifactDigest, ...], *,
         bundle_id: str, cut_id: str, at: dt.datetime, previous: receipts.RootAnchor,
         key_id: str, key: bytes) -> SignedBundle:
    """Bind supplied identities using the existing signed-root codec, not event re-signing.

    Source provenance, capture barrier and durable independent publication are
    future adapters. No default key, clock, bootstrap or inventory is inferred.
    """
    manifest = _manifest(contract, witness, artifacts, bundle_id, cut_id, at)
    root = hashlib.sha256(_json(manifest)).hexdigest()
    if type(previous) is not receipts.RootAnchor or previous.scope != contract.scope:
        raise BundleError('BACKUP_PREDECESSOR_INVALID')
    try:
        receipt = receipts.sign(previous, root, hashlib.sha256(_json(_contract(contract))).hexdigest(),
                                _instant(at), key_id, key)
    except Exception:
        raise BundleError('BACKUP_AUTH_UNAVAILABLE') from None
    data = _json({'manifest': manifest, 'receipt': receipt.data.decode('utf-8')})
    if len(data) > MAX_MANIFEST_BYTES:
        raise BundleError('BACKUP_METADATA_SIZE_INVALID')
    return SignedBundle(data, BundleCheckpoint(previous, receipt.anchor))


def _decode(data: bytes) -> dict[str, Any]:
    if type(data) is not bytes or not 1 <= len(data) <= MAX_MANIFEST_BYTES:
        raise BundleError('BACKUP_METADATA_SIZE_INVALID')
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise BundleError('BACKUP_METADATA_INVALID')
            result[key] = value
        return result
    try:
        value = json.loads(data, object_pairs_hook=unique)
        if (type(value) is not dict or set(value) != {'manifest', 'receipt'}
                or _json(value) != data or type(value['manifest']) is not dict
                or type(value['receipt']) is not str):
            raise BundleError('BACKUP_METADATA_INVALID')
        return cast(dict[str, Any], value)
    except BundleError:
        raise
    except Exception:
        raise BundleError('BACKUP_METADATA_INVALID') from None


def verify(data: bytes, *, checkpoint: BundleCheckpoint, contract: BackupContract,
           keyring: Mapping[str, bytes]) -> VerifiedBundle:
    """Authenticate against an independently supplied checkpoint and inventory.

    Do not obtain either expectation from the bundle or restored target. This
    function cannot establish that the caller retained/committed them securely.
    """
    if (type(checkpoint) is not BundleCheckpoint
            or type(checkpoint.previous) is not receipts.RootAnchor
            or type(checkpoint.current) is not receipts.RootAnchor):
        raise BundleError('BACKUP_CHECKPOINT_REQUIRED')
    if (type(checkpoint.current.generation) is not int
            or not 1 <= checkpoint.current.generation <= receipts.MAX_GENERATION
            or type(checkpoint.previous.generation) is not int
            or checkpoint.current.generation != checkpoint.previous.generation + 1):
        raise BundleError('BACKUP_CHECKPOINT_MISMATCH')
    envelope = _decode(data)
    manifest = envelope['manifest']
    try:
        w = manifest['source_witness']
        if (type(w) is not dict or type(w.get('counts')) is not list or len(w['counts']) != 5
                or type(manifest.get('artifacts')) is not list
                or not 1 <= len(manifest['artifacts']) <= MAX_ARTIFACTS):
            raise BundleError('BACKUP_METADATA_INVALID')
        witness = StateWitness(w['version'], tuple(w['counts']), w['schema_sha256'], w['state_sha256'])
        artifacts = tuple(ArtifactDigest(a['name'], a['sha256'], a['size_bytes'])
                          for a in manifest['artifacts'])
        expected = _manifest(contract, witness, artifacts, manifest['bundle_id'], manifest['cut_id'],
                             dt.datetime.fromisoformat(manifest['created_at']))
        if _json(manifest) != _json(expected) or _json(w) != _json(_witness(witness)):
            raise BundleError('BACKUP_CONTRACT_MISMATCH')
    except BundleError:
        raise
    except Exception:
        raise BundleError('BACKUP_METADATA_INVALID') from None
    if (checkpoint.previous.scope != contract.scope or checkpoint.current.scope != contract.scope
            or not hmac.compare_digest(hashlib.sha256(_json(manifest)).hexdigest(),
                                       _hash(checkpoint.current.root))):
        raise BundleError('BACKUP_CHECKPOINT_MISMATCH')
    try:
        raw_receipt = envelope['receipt'].encode('utf-8')
        anchor = receipts.verify(raw_receipt, checkpoint.current.receipt_sha256,
                                 checkpoint.previous, keyring)
        if anchor != checkpoint.current:
            raise BundleError('BACKUP_CHECKPOINT_MISMATCH')
        if json.loads(raw_receipt)['message']['segment'] != hashlib.sha256(_json(_contract(contract))).hexdigest():
            raise BundleError('BACKUP_CONTRACT_MISMATCH')
    except BundleError:
        raise
    except Exception:
        raise BundleError('BACKUP_AUTH_UNVERIFIED') from None
    return VerifiedBundle(witness, tuple(sorted(artifacts, key=lambda a: a.name)), checkpoint)


def verify_restore(data: bytes, *, checkpoint: BundleCheckpoint, contract: BackupContract,
                   keyring: Mapping[str, bytes], observed: tuple[ArtifactDigest, ...],
                   restored_witness: StateWitness) -> dict[str, object]:
    """Require every restored byte identity and five-table witness to match.

    No source/target is opened or overwritten. A five-table witness is not full
    application state. Signing authority, remote proofs and consistency remain
    separate; this result NEVER authorizes deletion, sending, or trade approval.
    """
    verified = verify(data, checkpoint=checkpoint, contract=contract, keyring=keyring)
    if _artifacts(contract, observed) != _artifacts(contract, verified.artifacts):
        raise BundleError('BACKUP_RESTORED_ARTIFACT_MISMATCH')
    if _witness(restored_witness) != _witness(verified.witness):
        raise BundleError('BACKUP_RESTORED_WITNESS_MISMATCH')
    return {'status': 'BACKUP_IDENTITIES_VERIFIED', 'artifact_count': len(observed),
            'metadata_authenticated': True, 'state_witness_equality_verified': True,
            'capture_consistency_verified': False, 'custody_persistence_verified': False,
            'original_signatures_verified': False, 'remote_recovery_verified': False,
            'application_recovery_verified': False, 'approval_authority': False}
