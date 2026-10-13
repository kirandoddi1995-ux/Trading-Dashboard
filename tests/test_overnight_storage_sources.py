"""All known source identities, exact maps and protected source retention."""
from __future__ import annotations

from datetime import timedelta

import pytest

import catalog_receipts as receipts
import cold_catalog as catalog
import storage_policy
from overnight_storage_contracts import Candidate, CatalogCut, ContractError, ReviewGates, SourcePolicy, digest
from overnight_storage_harness import START, SYNTHETIC_KEY, SyntheticTier
from overnight_storage_sources import KNOWN_SOURCES, SourceRouter


@pytest.mark.parametrize('source', list(KNOWN_SOURCES))
def test_each_source_exact_dedup_restore_retention(source: str) -> None:
    router = SourceRouter({source: digest})
    raw = (source + ':synthetic exact bytes').encode()
    candidate = Candidate(source, 'snapshot_a', 1, START - timedelta(days=1), START,
                          digest(raw), len(raw), digest(raw))
    pages: dict[str, bytes] = {}
    patch, entry = router.shadow(catalog.Catalog(catalog.EMPTY_ROOT, pages.get), candidate, raw)
    pages.update(patch.pages)
    assert entry.source == source and entry.content_sha256 == digest(raw)
    second = Candidate(source, 'snapshot_b', 2, candidate.lower, candidate.upper,
                       candidate.sha256, candidate.size, candidate.witness)
    patch2, entry2 = router.shadow(catalog.Catalog(patch.root, pages.get), second, raw)
    pages.update(patch2.pages)
    index = catalog.Catalog(patch2.root, pages.get)
    assert index.audit() == 3
    assert entry.content_sha256 == entry2.content_sha256 and entry.snapshot != entry2.snapshot
    previous = receipts.genesis('overnight:synthetic')
    signed = receipts.sign(previous, patch2.root, digest(raw), START, 'synthetic', SYNTHETIC_KEY)
    cut = CatalogCut(previous, signed.anchor, signed.data)
    tiers = (SyntheticTier('online', {digest(raw): raw}), SyntheticTier('disk', {digest(raw): raw}))
    proof = router.recover(candidate, cut, {'synthetic': SYNTHETIC_KEY}, pages.get, tiers, hot=raw)
    reference = digest(b'synthetic review')
    gates = ReviewGates(1, START, 0, 0, ('writer',), ('writer',), reference, reference, reference, reference)
    spec = KNOWN_SOURCES[source]
    plan = router.retention(SourcePolicy(source, START, reference, 4, 65536), (candidate,), (proof,),
        gates, cut=cut, now=START, protected_latest=False,
        source_dependency_closure=digest((spec.table + ':' + spec.retention_contract).encode()))
    assert bool(plan.blockers) == spec.never_retire
    assert not plan.deletion_authority and not plan.globally_wired
    protected = router.retention(SourcePolicy(source, START, reference, 4, 65536), (candidate,), (proof,),
        gates, cut=cut, now=START, protected_latest=None, source_dependency_closure=None)
    assert 'SOURCE_LATEST_ACTIVE_OR_UNKNOWN' in protected.blockers
    assert 'SOURCE_DEPENDENCY_CLOSURE_UNPROVEN' in protected.blockers
    with pytest.raises(ContractError, match='PARITY'):
        router.recover(candidate, cut, {'synthetic': SYNTHETIC_KEY}, pages.get, tiers, hot=raw + b' ')
    with pytest.raises(ContractError, match='UNCOMMISSIONED'):
        SourceRouter({}).recover(candidate, cut, {'synthetic': SYNTHETIC_KEY}, pages.get, tiers)


def test_all_budgeted_tables_have_unique_exact_source() -> None:
    assert {s.table for s in KNOWN_SOURCES.values()} == {budget.name for budget in storage_policy.BUDGETS}
    assert len(KNOWN_SOURCES) == len(storage_policy.BUDGETS)
    with pytest.raises(ContractError, match='UNKNOWN'):
        SourceRouter({'made_up': digest})
