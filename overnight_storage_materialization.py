"""Exact catalog image routing through the existing original-signature six restore.

Private synthetic paths only; caller supplies keys/checkpoints. Existing verifier
recaptures all six tables and checks both witnesses, rather than trusting a hash
callback. No installed path selection, acknowledgement, replacement or deletion.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import recovery_bundle as bundle
import recovery_export as export
import recovery_materialization as materialization
import recovery_six_binding as binding
from overnight_storage_contracts import (Candidate, CatalogCut, ContractError,
    Readback, Tier, digest, readback)


@dataclass(frozen=True)
class SixTableRestore:
    generation: export.PreparedGeneration
    readback: Readback
    witness_bytes: bytes
    application_recovery_verified: bool = False
    deletion_authority: bool = False


def restore_six_table(candidate: Candidate, cut: CatalogCut, *,
        catalog_keys: Mapping[str, bytes], pages: Callable[[str], bytes | None],
        tiers: Sequence[Tier], source: export.PreparedGeneration, target: Path,
        checkpoint: bundle.BundleCheckpoint, contract: bundle.BackupContract,
        recovery_keys: Mapping[str, bytes], original_keys: Mapping[str, bytes],
        spool_parent: Path) -> SixTableRestore:
    if candidate.source != 'six_table_image':
        raise ContractError('SIX_IMAGE_SOURCE_REQUIRED')
    # Existing verification opens only authenticated images and captures all six
    # original tables/signatures. Its limits are streaming, not this object cap.
    verified = export.verify_generation(source.directory, checkpoint=checkpoint,
        contract=contract, keys=recovery_keys, original_keys=original_keys,
        spool_parent=spool_parent)
    if verified != source.signed.data or source.signed.checkpoint != checkpoint:
        raise ContractError('SIX_GENERATION_IDENTITY_MISMATCH')
    with (source.directory / export.SIX_WITNESS).open('rb') as stream:
        witness = stream.read(binding.MAX_BYTES + 1)
    with (source.directory / export.IMAGE).open('rb') as stream:
        image = bundle.measure('primary_state', stream)
    if (candidate.sha256 != image.sha256 or candidate.size != image.size_bytes
            or candidate.witness != digest(witness) or len(witness) > binding.MAX_BYTES):
        raise ContractError('SIX_EXACT_IMAGE_WITNESS_MISMATCH')
    def decoder(raw: bytes) -> str:
        if digest(raw) != image.sha256 or len(raw) != image.size_bytes:
            raise ContractError('SIX_IMAGE_CHANGED')
        # This is the existing semantically verified six-table witness, including
        # pending terminal intents, not an invented opaque business witness.
        return digest(witness)
    proof = readback(candidate, cut, catalog_keys, pages, tiers, restore=decoder)
    restored = materialization.materialize(source, target, checkpoint=checkpoint,
        contract=contract, keys=recovery_keys, original_keys=original_keys,
        spool_parent=spool_parent)
    return SixTableRestore(restored, proof, witness)
