"""Restart authenticated offline proposals without inventing committed custody.

No runtime integration, private credentials, network, deletion or restore. The
caller retains the predecessor independently before export and protects files
against concurrent mutation. A local custody database is not an independent copy.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import catalog_receipts as receipts
import recovery_bundle as bundle
import recovery_export as export


class ProposalError(ValueError):
    """Redacted restart failures; never reset custody or remove partial files."""


@dataclass(frozen=True)
class ReloadedProposal:
    """Authenticated files and observed local head, not replica/restore authority."""
    generation: export.PreparedGeneration = field(repr=False)
    observed_head: receipts.RootAnchor
    status: str


def reload(directory: Path, custody: Path, *, trusted_previous: receipts.RootAnchor,
           contract: bundle.BackupContract, keys: Mapping[str, bytes],
           original_keys: Mapping[str, bytes], spool_parent: Path) -> ReloadedProposal:
    """Re-read an existing complete proposal after process death or lost reply.

    Never derive trusted_previous from the backup. Partial export, lost custody,
    changed originals, a competing successor, skipped generation or stale retry
    block. A successful reload is still subject to commit()'s atomic head CAS.
    """
    try:
        if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
            raise ProposalError('PROPOSAL_DIRECTORY_UNVERIFIED')
        manifest = directory / export.MANIFEST
        if manifest.is_symlink() or manifest.is_junction() or not manifest.is_file():
            raise ProposalError('PROPOSAL_INCOMPLETE')
        with manifest.open('rb') as stream:
            data = stream.read(bundle.MAX_MANIFEST_BYTES + 1)
        signed = bundle.admit_proposal(data, previous=trusted_previous,
                                      contract=contract, keyring=keys)
        checked = export.verify_generation(directory, checkpoint=signed.checkpoint,
            contract=contract, keys=keys, original_keys=original_keys, spool_parent=spool_parent)
        if data != checked:
            raise ProposalError('PROPOSAL_CHANGED')
        head = export.read_head(custody, contract=contract)
        if head == signed.checkpoint.previous:
            status = 'PROPOSAL_READY_FOR_LOCAL_CAS'
        elif head == signed.checkpoint.current:
            status = 'PROPOSAL_ALREADY_LOCALLY_COMMITTED'
        else:
            raise ProposalError('PROPOSAL_STALE_OR_CONFLICTING')
        if custody.resolve().is_relative_to(directory.resolve()):
            raise ProposalError('PROPOSAL_CUSTODY_NOT_SEPARATE')
        return ReloadedProposal(export.PreparedGeneration(directory, signed), head, status)
    except ProposalError:
        raise
    except Exception:
        raise ProposalError('PROPOSAL_RELOAD_BLOCKED_RETAIN_FILES') from None


def resume(custody: Path, proposal: ReloadedProposal, *, contract: bundle.BackupContract,
           keys: Mapping[str, bytes], original_keys: Mapping[str, bytes],
           spool_parent: Path) -> dict[str, object]:
    """Reverify every byte and CAS again; reload observations are not a lock."""
    if type(proposal) is not ReloadedProposal:
        raise ProposalError('PROPOSAL_RELOAD_REQUIRED')
    return export.commit(custody, proposal.generation, contract=contract, keys=keys,
                         original_keys=original_keys, spool_parent=spool_parent)
