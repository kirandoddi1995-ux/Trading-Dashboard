"""Verify owner-extracted copies against independently retained backup identity.

No encryption/decryption, copy creation, network, key discovery or hot deletion.
Physical separation and encryption custody need owner commissioning, not a flag.
The installed application never imports this offline audit module.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import recovery_bundle as bundle
import recovery_export as export


class ReplicaError(ValueError):
    """Redacted proof failures; missing replicas never mean delayed permission."""


@dataclass(frozen=True)
class ExtractedCopy:
    """Reviewed logical replica name and explicit private extraction directory."""
    name: str
    directory: Path = field(repr=False)


def verify_copies(source: export.PreparedGeneration, copies: tuple[ExtractedCopy, ...], *,
                  checkpoint: bundle.BundleCheckpoint, contract: bundle.BackupContract,
                  keys: Mapping[str, bytes], original_keys: Mapping[str, bytes],
                  spool_parent: Path) -> dict[str, object]:
    """Re-read two separately extracted copies and source, including all originals.

    checkpoint/inventory must be independently retained, not loaded from a copy.
    Names are fixed to Drive and external disk to prevent silently relabelling
    an uncommissioned third destination. Distinct paths are necessary, NOT proof
    of distinct physical failure domains. No receipt here authorizes hot pruning.
    """
    try:
        if type(copies) is not tuple or len(copies) != 2:
            raise ReplicaError('REPLICA_TWO_COPIES_REQUIRED')
        if any(type(copy) is not ExtractedCopy for copy in copies):
            raise ReplicaError('REPLICA_BINDING_INVALID')
        if {copy.name for copy in copies} != {'drive', 'external_disk'}:
            raise ReplicaError('REPLICA_INDEPENDENT_BINDINGS_REQUIRED')
        if source.signed.checkpoint != checkpoint:
            raise ReplicaError('REPLICA_INDEPENDENT_CHECKPOINT_MISMATCH')
        paths = [source.directory, *(copy.directory for copy in copies)]
        for path in paths:
            # Inspect ancestors as well: a differently named junction is not a copy.
            for ancestor in (path, *path.parents):
                if ancestor.is_symlink() or ancestor.is_junction():
                    raise ReplicaError('REPLICA_LINK_REJECTED')
        resolved = [path.resolve(strict=True) for path in paths]
        for index, left in enumerate(resolved):
            for right in resolved[index + 1:]:
                if left.is_relative_to(right) or right.is_relative_to(left):
                    raise ReplicaError('REPLICA_PATHS_NOT_SEPARATE')
        expected = export.verify_generation(source.directory, checkpoint=checkpoint,
            contract=contract, keys=keys, original_keys=original_keys, spool_parent=spool_parent)
        if expected != source.signed.data:
            raise ReplicaError('REPLICA_SOURCE_CHANGED')
        for copy in copies:
            actual = export.verify_generation(copy.directory, checkpoint=checkpoint,
                contract=contract, keys=keys, original_keys=original_keys, spool_parent=spool_parent)
            if actual != expected:
                raise ReplicaError('REPLICA_GENERATION_MISMATCH')
        # Re-read source after replica audits; no mutable cached proof is reused.
        if export.verify_generation(source.directory, checkpoint=checkpoint,
                contract=contract, keys=keys, original_keys=original_keys,
                spool_parent=spool_parent) != expected:
            raise ReplicaError('REPLICA_SOURCE_CHANGED')
        return {'status': 'EXTRACTED_REPLICA_IDENTITIES_VERIFIED', 'copies_checked': 2,
                'generation': checkpoint.current.generation,
                'original_signatures_verified': True, 'byte_identities_verified': True,
                'encryption_verified': False, 'physical_independence_verified': False,
                'trusted_checkpoint_durability_verified': False,
                'application_recovery_verified': False, 'hot_deletion_authority': False,
                'approval_authority': False}
    except ReplicaError:
        raise
    except Exception:
        raise ReplicaError('REPLICA_AUDIT_BLOCKED_RETAIN_COPIES') from None
