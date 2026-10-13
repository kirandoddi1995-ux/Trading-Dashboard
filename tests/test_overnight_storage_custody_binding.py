"""Codec-level exact report/cut binding; never claims measured replica custody."""
from __future__ import annotations

from dataclasses import replace
import json

import pytest

import catalog_receipts as receipts
import cold_catalog as catalog
import recovery_bundle as bundle
import recovery_custody_rehearsal as custody
from overnight_storage_contracts import (Candidate, CatalogCut, ContractError,
    bind_six_table_recovery, digest)
from overnight_storage_harness import START, SYNTHETIC_KEY


@pytest.mark.parametrize('damage', ['', 'report', 'missing_binding', 'bundle_generation', 'source', 'key'])
def test_existing_custody_verifier_bound_to_exact_catalog_cut(damage: str) -> None:
    previous_bundle = receipts.genesis('backup:synthetic')
    signed_bundle = receipts.sign(previous_bundle, digest(b'bundle root'), digest(b'segment'),
                                  START, 'synthetic', SYNTHETIC_KEY)
    checkpoint = bundle.BundleCheckpoint(previous_bundle, signed_bundle.anchor)
    bundle_hash = digest(b'synthetic bundle bytes')
    report_body: dict[str, object] = {'version': custody.VERSION,
        'status': 'TWO_REPLICA_SIX_TABLE_RESTORE_VERIFIED', 'scope': custody.SCOPE,
        'at': START.isoformat(), 'generation': 1, 'bundle_sha256': bundle_hash,
        'bundle_root': checkpoint.current.root, 'bundle_receipt_sha256': checkpoint.current.receipt_sha256,
        'replicas': ['drive', 'external_disk'], 'restores_verified': 2,
        'original_signatures_verified': True, 'six_table_image_verified': True,
        'encryption_verified': False, 'physical_independence_verified': False,
        'trusted_checkpoint_durability_verified': False, 'application_recovery_verified': False,
        'hot_deletion_authority': False, 'approval_authority': False}
    report = json.dumps(report_body, sort_keys=True, separators=(',', ':')).encode()
    previous_report = receipts.genesis(custody.SCOPE)
    signed_report = receipts.sign(previous_report, digest(report), bundle_hash, START, 'synthetic', SYNTHETIC_KEY)
    evidence = custody.Rehearsal(report, signed_report)
    candidate = Candidate('synthetic', 'snapshot', 1, START.replace(year=2025), START,
                          digest(b'bytes'), 5, digest(b'witness'))
    binding: dict[str, object] = {'candidate': candidate.metadata(), 'catalog_generation': 1,
        'report_sha256': digest(report), 'bundle_generation': 1,
        'bundle_root': checkpoint.current.root, 'bundle_sha256': bundle_hash,
        'bundle_receipt_sha256': checkpoint.current.receipt_sha256}
    updates = {candidate.identity: candidate.metadata(), 'recovery:' + candidate.identity: binding}
    if damage == 'missing_binding':
        updates.pop('recovery:' + candidate.identity)
    if damage == 'bundle_generation':
        binding['bundle_generation'] = 2
    patch = catalog.Catalog(catalog.EMPTY_ROOT, lambda _: None).patch(updates)
    previous = receipts.genesis('overnight:synthetic')
    signed = receipts.sign(previous, patch.root, digest(b'content'), START, 'synthetic', SYNTHETIC_KEY)
    cut = CatalogCut(previous, signed.anchor, signed.data)
    if damage == 'report':
        evidence = replace(evidence, report=report + b' ')
    if damage == 'source':
        candidate = replace(candidate, source='wrong_source')
    keys = {} if damage == 'key' else {'synthetic': SYNTHETIC_KEY}
    def invoke() -> object:
        return bind_six_table_recovery(candidate, cut, catalog_keys={'synthetic': SYNTHETIC_KEY},
            fetch=patch.pages.get, evidence=evidence, trusted_report=signed_report.anchor,
            previous_report=previous_report, checkpoint=checkpoint,
            trusted_bundle_sha256=bundle_hash, recovery_keys=keys)
    if damage:
        with pytest.raises((ContractError, custody.RehearsalError)):
            invoke()
    else:
        result = bind_six_table_recovery(candidate, cut, catalog_keys={'synthetic': SYNTHETIC_KEY},
            fetch=patch.pages.get, evidence=evidence, trusted_report=signed_report.anchor,
            previous_report=previous_report, checkpoint=checkpoint,
            trusted_bundle_sha256=bundle_hash, recovery_keys=keys)
        assert result.catalog_generation == result.bundle_generation == 1
        assert not result.physical_custody_verified and not result.application_recovery_verified
        assert not result.deletion_authority
