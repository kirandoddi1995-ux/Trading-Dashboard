"""Actual existing six-table decoder, large synthetic payloads, no private data."""
from __future__ import annotations

from pathlib import Path

import pytest
import catalog_receipts as receipts
import cold_catalog as catalog
import recovery_export as export
import recovery_materialization as materialization
from overnight_storage_contracts import Candidate, CatalogCut, ContractError, digest, object_limit, readback
from overnight_storage_harness import START, SYNTHETIC_KEY, SyntheticTier
from overnight_storage_materialization import restore_six_table
from tests.test_local_state_recovery import source as source_fixture, KEY, KEY_ID
from tests.test_recovery_export import AUTH
from tests.test_recovery_six_export import contract, initialize, prepare

source = source_fixture  # Register the existing synthetic pytest fixture explicitly.


def signed_cut(candidate: Candidate) -> tuple[CatalogCut, dict[str, bytes]]:
    patch = catalog.Catalog(catalog.EMPTY_ROOT, lambda _: None).patch({candidate.identity: candidate.metadata()})
    previous = receipts.genesis('overnight:synthetic')
    signed = receipts.sign(previous, patch.root, candidate.sha256, START, 'synthetic', SYNTHETIC_KEY)
    return CatalogCut(previous, signed.anchor, signed.data), dict(patch.pages)


@pytest.mark.parametrize('source_name', ['equity_research__outcomes', 'quant_app__evidence_ledger_events'])
def test_344_kib_payload_exact_restore_and_parity(source_name: str) -> None:
    # Representative user-reported size, deterministic bytes, not an original
    # private outcome or a claim to have measured production payload maxima.
    raw = b'synthetic:' + b'x' * (344 * 1024 - 10)
    candidate = Candidate(source_name, 'fixture', 1, START.replace(year=2025), START,
                          digest(raw), len(raw), digest(raw))
    cut, pages = signed_cut(candidate)
    tiers = (SyntheticTier('disk', {digest(raw): raw}), SyntheticTier('online', {digest(raw): raw}))
    from overnight_storage_sources import SourceRouter
    proof = SourceRouter({source_name: digest}).recover(candidate, cut, {'synthetic': SYNTHETIC_KEY},
        pages.get, tiers, hot=raw)
    assert proof.candidate.size == 344 * 1024 and len(proof.restore_witnesses) == 2
    with pytest.raises(ContractError, match='CANDIDATE_INVALID'):
        Candidate(source_name, 'fixture', 1, candidate.lower, candidate.upper,
                  digest(raw), object_limit(source_name) + 1, digest(raw))
    oversized = SyntheticTier('oversize', {digest(raw): raw}, 'oversize')
    with pytest.raises(ContractError, match='OVERSIZE'):
        readback(candidate, cut, {'synthetic': SYNTHETIC_KEY}, pages.get, (oversized,), restore=digest)


@pytest.mark.parametrize('fault', ['', 'partial', 'original_key', 'existing_target'])
def test_existing_six_table_materialization_routed_from_catalog(source: Path, tmp_path: Path, fault: str) -> None:
    initialize(source)
    generation = prepare(source, tmp_path / 'generation')
    raw = (generation.directory / export.IMAGE).read_bytes()
    witness = (generation.directory / export.SIX_WITNESS).read_bytes()
    candidate = Candidate('six_table_image', 'fixture', 1, START.replace(year=2025), START,
                          digest(raw), len(raw), digest(witness))
    cut, pages = signed_cut(candidate)
    tier = SyntheticTier('disk', {digest(raw): raw}, 'partial' if fault == 'partial' else '')
    target = tmp_path / 'overnight_storage_restored'
    if fault == 'existing_target':
        target.mkdir()
    def invoke() -> object:
        return restore_six_table(candidate, cut, catalog_keys={'synthetic': SYNTHETIC_KEY},
            pages=pages.get, tiers=(tier,), source=generation, target=target,
            checkpoint=generation.signed.checkpoint, contract=contract(), recovery_keys={'auth': AUTH},
            original_keys={} if fault == 'original_key' else {KEY_ID: KEY}, spool_parent=tmp_path)
    if fault:
        with pytest.raises((ContractError, export.ExportError, materialization.MaterializationError)):
            invoke()
        if fault != 'existing_target':
            assert not target.exists()
    else:
        result = restore_six_table(candidate, cut, catalog_keys={'synthetic': SYNTHETIC_KEY},
            pages=pages.get, tiers=(tier,), source=generation, target=target,
            checkpoint=generation.signed.checkpoint, contract=contract(), recovery_keys={'auth': AUTH},
            original_keys={KEY_ID: KEY}, spool_parent=tmp_path)
        assert result.witness_bytes == witness
        assert (target / export.IMAGE).read_bytes() == raw
        assert not result.application_recovery_verified and not result.deletion_authority
