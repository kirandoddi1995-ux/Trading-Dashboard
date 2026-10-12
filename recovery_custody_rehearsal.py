"""Inactive two-replica six-table restore rehearsal and authenticated report.

Owner supplies extracted replicas, original keys and independently retained
anchors. No encryption, credentials, network, live restore, custody CAS or delete.
Signed reports authenticate the measured result, NOT physical independence.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import TypedDict

import catalog_receipts as receipts
import recovery_bundle as bundle
import recovery_export as export
import recovery_materialization as restore
import recovery_replica_audit as audit

VERSION = 'two-replica-six-table-rehearsal-v1'
SCOPE = 'custody:six-table-rehearsal'


class RehearsalError(ValueError):
    """Fixed diagnostics; partial restores remain intact for private inspection."""


class _Options(TypedDict):
    checkpoint: bundle.BundleCheckpoint
    contract: bundle.BackupContract
    keys: Mapping[str, bytes]
    original_keys: Mapping[str, bytes]
    spool_parent: Path


@dataclass(frozen=True, repr=False)
class Rehearsal:
    """Proposed evidence only. Caller must retain report/anchor independently."""
    report: bytes = field(repr=False)
    signed: receipts.SignedReceipt = field(repr=False)


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


def _paths(source: Path, copies: tuple[audit.ExtractedCopy, ...],
           targets: Mapping[str, Path]) -> None:
    if (type(copies) is not tuple or len(copies) != 2
            or any(type(c) is not audit.ExtractedCopy for c in copies)
            or {c.name for c in copies} != {'drive', 'external_disk'}
            or set(targets) != {'drive', 'external_disk'}):
        raise RehearsalError('REHEARSAL_TWO_NAMED_REPLICAS_REQUIRED')
    paths = [source, *(c.directory for c in copies), *targets.values()]
    for path in paths:
        if not isinstance(path, Path) or not path.is_absolute():
            raise RehearsalError('REHEARSAL_ABSOLUTE_PATHS_REQUIRED')
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            raise RehearsalError('REHEARSAL_LINK_REJECTED')
    resolved = [p.resolve() for p in paths]
    for index, left in enumerate(resolved):
        if any(left.is_relative_to(right) or right.is_relative_to(left)
               for right in resolved[index + 1:]):
            raise RehearsalError('REHEARSAL_PATH_OVERLAP')
    if any(p.exists() or not p.parent.is_dir() for p in targets.values()):
        raise RehearsalError('REHEARSAL_NEW_TARGETS_REQUIRED')


def rehearse(source: export.PreparedGeneration, copies: tuple[audit.ExtractedCopy, ...], *,
             targets: Mapping[str, Path], checkpoint: bundle.BundleCheckpoint,
             contract: bundle.BackupContract, keys: Mapping[str, bytes],
             original_keys: Mapping[str, bytes], spool_parent: Path,
             previous_report: receipts.RootAnchor, at: datetime,
             key_id: str, key: bytes) -> Rehearsal:
    """Authenticate both copies, materialize each, recheck every cut, sign evidence.

    Targets must be NEW, mutually separate, and outside all source/extraction
    trees. A partial failure issues no report and leaves targets, never retries.
    Caller must exclude concurrent mutation and protect private directory ACLs.
    The report is a six-table/image restore proof, not a full Supabase restore.
    Original remote ACK interpretation and independent custody remain separate.
    """
    stage = 'INPUTS'
    try:
        if (type(at) is not datetime or at.tzinfo is None or at.utcoffset() is None
                or previous_report.scope != SCOPE):
            raise RehearsalError('REHEARSAL_CLOCK_OR_SCOPE_INVALID')
        # Validate signing inputs before creating any restore target.
        receipts.sign(previous_report, '1' * 64, '2' * 64, at, key_id, key)
        if (len(contract.bindings) != 2
                or {b.name for b in contract.bindings} != {'primary_state', 'six_table_witness'}):
            raise RehearsalError('REHEARSAL_SIX_TABLE_CONTRACT_REQUIRED')
        _paths(source.directory, copies, targets)
        options: _Options = dict(checkpoint=checkpoint, contract=contract, keys=keys,
                       original_keys=original_keys, spool_parent=spool_parent)
        stage = 'REPLICA_READBACK'
        audit.verify_copies(source, copies, **options)
        for copy in sorted(copies, key=lambda c: c.name):
            stage = 'RESTORE_' + copy.name.upper()
            detached = export.PreparedGeneration(copy.directory, source.signed)
            restore.materialize(detached, targets[copy.name], **options)
        stage = 'FINAL_READBACK'
        audit.verify_copies(source, copies, **options)
        for target in targets.values():
            if export.verify_generation(target, **options) != source.signed.data:
                raise RehearsalError('REHEARSAL_FINAL_IDENTITY_MISMATCH')
        bundle_hash = hashlib.sha256(source.signed.data).hexdigest()
        body = {'version': VERSION, 'status': 'TWO_REPLICA_SIX_TABLE_RESTORE_VERIFIED',
                'scope': SCOPE, 'at': at.astimezone(timezone.utc).isoformat(),
                'generation': checkpoint.current.generation,
                'bundle_sha256': bundle_hash,
                'bundle_root': checkpoint.current.root,
                'bundle_receipt_sha256': checkpoint.current.receipt_sha256,
                'replicas': ['drive', 'external_disk'], 'restores_verified': 2,
                'original_signatures_verified': True, 'six_table_image_verified': True,
                'encryption_verified': False, 'physical_independence_verified': False,
                'trusted_checkpoint_durability_verified': False,
                'application_recovery_verified': False, 'hot_deletion_authority': False,
                'approval_authority': False}
        report = _json(body)
        stage = 'REPORT_SIGNING'
        signed = receipts.sign(previous_report, hashlib.sha256(report).hexdigest(),
                               bundle_hash, at.astimezone(timezone.utc), key_id, key)
        return Rehearsal(report, signed)
    except RehearsalError:
        raise
    except Exception:
        raise RehearsalError('REHEARSAL_' + stage + '_BLOCKED_RETAIN_TARGETS') from None


def verify_report(evidence: Rehearsal, *, trusted_report: receipts.RootAnchor,
                  previous_report: receipts.RootAnchor, checkpoint: bundle.BundleCheckpoint,
                  trusted_bundle_sha256: str, keyring: Mapping[str, bytes]) -> bytes:
    """Authenticate exact report against external anchors; never accept self-pins."""
    try:
        if (type(evidence) is not Rehearsal or type(evidence.report) is not bytes
                or not 0 < len(evidence.report) <= receipts.MAX_BYTES
                or previous_report.scope != SCOPE or trusted_report.scope != SCOPE):
            raise RehearsalError('REHEARSAL_REPORT_INVALID')
        actual = receipts.verify(evidence.signed.data, trusted_report.receipt_sha256,
                                 previous_report, keyring)
        if (actual != trusted_report or evidence.signed.anchor != trusted_report
                or actual.root != hashlib.sha256(evidence.report).hexdigest()):
            raise RehearsalError('REHEARSAL_REPORT_ANCHOR_MISMATCH')
        body = json.loads(evidence.report)
        envelope = json.loads(evidence.signed.data)['message']
        if (body['version'] != VERSION or body['scope'] != SCOPE
                or body['generation'] != checkpoint.current.generation
                or body['bundle_root'] != checkpoint.current.root
                or body['bundle_receipt_sha256'] != checkpoint.current.receipt_sha256
                or body['bundle_sha256'] != trusted_bundle_sha256
                or envelope['segment'] != body['bundle_sha256']
                or envelope['published_at'] != body['at']
                or _json(body) != evidence.report):
            raise RehearsalError('REHEARSAL_REPORT_BINDING_MISMATCH')
        if (body['status'] != 'TWO_REPLICA_SIX_TABLE_RESTORE_VERIFIED'
                or body['replicas'] != ['drive', 'external_disk']
                or type(body['restores_verified']) is not int or body['restores_verified'] != 2
                or type(body['generation']) is not int
                or any(body[name] is not True for name in
                       ('original_signatures_verified', 'six_table_image_verified'))
                or any(body[name] is not False for name in
                       ('encryption_verified', 'physical_independence_verified',
                        'trusted_checkpoint_durability_verified', 'application_recovery_verified',
                        'hot_deletion_authority', 'approval_authority'))):
            raise RehearsalError('REHEARSAL_REPORT_CLAIM_INVALID')
        return evidence.report
    except RehearsalError:
        raise
    except Exception:
        raise RehearsalError('REHEARSAL_REPORT_AUTHENTICATION_FAILED') from None
