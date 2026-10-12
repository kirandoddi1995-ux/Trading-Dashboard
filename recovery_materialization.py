"""Inactive restore rehearsal for authenticated, detached six-table generations.

Only caller-supplied private paths/keys/proof adapters. No CLI, credentials,
runtime factories, sending, ACK mutation, overwrite, pruning or custody advance.
Extracting on one PC does not prove encrypted or independent-device recovery.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import io
import os
from pathlib import Path
import sqlite3
import time
from typing import TypedDict

import local_state_recovery as state
import recovery_bundle as bundle
import recovery_export as export
import recovery_six_binding as binding
import terminal_intent_snapshot as intents

MAX_COPY_SECONDS = 30.0
COPY_BYTES = 1024 * 1024


class MaterializationError(ValueError):
    """Stable redacted errors; partial targets remain for private inspection."""


class _VerifyOptions(TypedDict):
    checkpoint: bundle.BundleCheckpoint
    contract: bundle.BackupContract
    keys: Mapping[str, bytes]
    original_keys: Mapping[str, bytes]
    spool_parent: Path


@dataclass(frozen=True, repr=False)
class RemoteLookups:
    """Injected contract adapters; their actual authentication is not proved here."""
    evidence: Callable[[str], state.RemoteProof] = field(repr=False)
    checkpoint: Callable[[str, str, int], state.RemoteProof] = field(repr=False)
    run: Callable[[str, int], state.RemoteProof] = field(repr=False)


def _directory(path: Path) -> Path:
    if not path.is_absolute():
        raise MaterializationError('RESTORE_EXPLICIT_ABSOLUTE_PATH_REQUIRED')
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise MaterializationError('RESTORE_LINK_REJECTED')
    if not path.is_dir():
        raise MaterializationError('RESTORE_PRIVATE_PARENT_REQUIRED')
    return path.resolve(strict=True)


def _six(contract: bundle.BackupContract) -> None:
    # Exporter performs full contract validation. Do not silently restore five.
    if len(contract.bindings) != 2 or {b.name for b in contract.bindings} != {
            'primary_state', binding.NAME}:
        raise MaterializationError('RESTORE_SIX_TABLE_CONTRACT_REQUIRED')


def _copy(source: Path, target: Path, limit: int, deadline: float) -> None:
    if source.is_symlink() or source.is_junction() or not source.is_file():
        raise MaterializationError('RESTORE_SOURCE_FILE_UNVERIFIED')
    if not 0 < source.stat().st_size <= limit:
        raise MaterializationError('RESTORE_COPY_SIZE_BOUND')
    size = 0
    with source.open('rb') as before, target.open('xb') as after:
        while True:
            if time.monotonic() > deadline:
                raise MaterializationError('RESTORE_COPY_TIME_BOUND')
            block = before.read(COPY_BYTES)
            if not block:
                break
            size += len(block)
            if size > limit:
                raise MaterializationError('RESTORE_COPY_SIZE_BOUND')
            after.write(block)
        after.flush()
        os.fsync(after.fileno())


def materialize(source: export.PreparedGeneration, target: Path, *,
                checkpoint: bundle.BundleCheckpoint, contract: bundle.BackupContract,
                keys: Mapping[str, bytes], original_keys: Mapping[str, bytes],
                spool_parent: Path) -> export.PreparedGeneration:
    """Authenticate first, copy to NEW target, re-read target AND source.

    No selection of an installed/default state path, rename, cleanup or retry in
    place. Caller owns directory ACLs, free space and concurrent-mutation exclusion.
    A failed new target is retained, never mistaken for a completed generation.
    """
    try:
        _six(contract)
        if source.signed.checkpoint != checkpoint:
            raise MaterializationError('RESTORE_INDEPENDENT_CHECKPOINT_MISMATCH')
        origin = _directory(source.directory)
        parent = _directory(target.parent)
        if not target.is_absolute() or target.name in ('', '.', '..'):
            raise MaterializationError('RESTORE_NEW_TARGET_REQUIRED')
        target = parent / target.name
        if target.is_symlink() or target.is_junction() or target.exists():
            raise MaterializationError('RESTORE_NEW_TARGET_REQUIRED')
        if target.is_relative_to(origin) or origin.is_relative_to(target):
            raise MaterializationError('RESTORE_SOURCE_TARGET_OVERLAP')
        options: _VerifyOptions = dict(checkpoint=checkpoint, contract=contract, keys=keys,
                       original_keys=original_keys, spool_parent=spool_parent)
        authenticated = export.verify_generation(origin, **options)
        if authenticated != source.signed.data:
            raise MaterializationError('RESTORE_SOURCE_CHANGED')
        target.mkdir()  # Exclusive creation; never replace an installed file.
        deadline = time.monotonic() + MAX_COPY_SECONDS
        for name, limit in ((export.IMAGE, bundle.MAX_ARTIFACT_BYTES),
                            (export.MANIFEST, bundle.MAX_MANIFEST_BYTES),
                            (export.SIX_WITNESS, binding.MAX_BYTES)):
            _copy(origin / name, target / name, limit, deadline)
        if (export.verify_generation(target, **options) != authenticated
                or export.verify_generation(origin, **options) != authenticated):
            raise MaterializationError('RESTORE_GENERATION_CHANGED')
        return export.PreparedGeneration(target, source.signed)
    except MaterializationError:
        raise
    except Exception:
        raise MaterializationError('RESTORE_STOP_RETAIN_PARTIAL_TARGET') from None


def review_remote_contract(generation: export.PreparedGeneration, *,
                           checkpoint: bundle.BundleCheckpoint, contract: bundle.BackupContract,
                           keys: Mapping[str, bytes], original_keys: Mapping[str, bytes],
                           spool_parent: Path, lookups: RemoteLookups) -> dict[str, object]:
    """Review exact original requests/ACKs and fences on the restored six-table cut.

    Lookups cannot send/acknowledge through this API. Unknown COMMIT remains
    pending even when remote presence is found. Callbacks need separately reviewed
    authentication/absence proofs; passing this contract does not commission them.
    """
    try:
        _six(contract)
        if type(lookups) is not RemoteLookups or not all(callable(f) for f in (
                lookups.evidence, lookups.checkpoint, lookups.run)):
            raise MaterializationError('RESTORE_EXPLICIT_REMOTE_ADAPTERS_REQUIRED')
        if generation.signed.checkpoint != checkpoint:
            raise MaterializationError('RESTORE_INDEPENDENT_CHECKPOINT_MISMATCH')
        directory = _directory(generation.directory)
        options: _VerifyOptions = dict(checkpoint=checkpoint, contract=contract, keys=keys,
                       original_keys=original_keys, spool_parent=spool_parent)
        data = export.verify_generation(directory, **options)
        if data != generation.signed.data:
            raise MaterializationError('RESTORE_SOURCE_CHANGED')
        bundle.verify(data, checkpoint=checkpoint, contract=contract, keyring=keys)
        # Joint identity was authenticated above. The detached cut is rechecked
        # against its own signed image before callbacks can influence a result.
        connect = lambda: sqlite3.connect((directory / export.IMAGE).resolve().as_uri()
                                         + '?mode=ro', uri=True, timeout=export.SQLITE_TIMEOUT)
        with (directory / export.IMAGE).open('rb') as stream:
            image_identity = bundle.measure('primary_state', stream)
        with intents.capture_six(connect, original_keys, spool_parent=spool_parent) as snapshot:
            with (directory / export.SIX_WITNESS).open('rb') as stream:
                witness = stream.read(binding.MAX_BYTES + 1)
            binding.verify_restore(data, witness, checkpoint=checkpoint, contract=contract,
                keyring=keys, observed=(image_identity, bundle.measure(binding.NAME, io.BytesIO(witness))),
                restored_primary=snapshot.primary.witness, restored_intents=snapshot.intents)
            result = intents.verify_six(snapshot, snapshot.primary.witness, snapshot.intents,
                evidence_lookup=lookups.evidence, checkpoint_lookup=lookups.checkpoint,
                run_lookup=lookups.run)
        if result['status'] != 'PASS':
            raise MaterializationError('RESTORE_REMOTE_CONTRACT_UNVERIFIED')
        if export.verify_generation(directory, **options) != data:
            raise MaterializationError('RESTORE_GENERATION_CHANGED')
        return {**result, 'status': 'RESTORED_SIX_TABLE_REMOTE_CONTRACT_REVIEWED',
                'remote_adapter_authentication_verified': False,
                'independent_custody_verified': False, 'encryption_verified': False,
                'application_recovery_verified': False, 'hot_deletion_authority': False,
                'approval_authority': False}
    except MaterializationError:
        raise
    except Exception:
        raise MaterializationError('RESTORE_REVIEW_FAILED_RETAIN_TARGET') from None
