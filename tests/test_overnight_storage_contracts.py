"""Synthetic contract failures, never real payloads or hosted resources."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

import catalog_receipts as receipts
import cold_catalog as catalog
import storage_capacity_watch as watch
import storage_transition as transition
import storage_write_guard as guard
from overnight_storage_contracts import (Candidate, CatalogCut, ContractError, Readback, ReviewGates,
    SourcePolicy, authenticated_catalog, capacity_runway, dedup_shadow, digest, readback, retention_plan)
from overnight_storage_harness import (START, SYNTHETIC_KEY, SyntheticTier,
    restore_synthetic, run_synthetic)
from overnight_storage_journal import Journal, metadata_bytes


def fixture() -> tuple[Candidate, CatalogCut, dict[str, bytes], tuple[SyntheticTier, SyntheticTier]]:
    raw = metadata_bytes({'source': 'synthetic_universe', 'rows': [1, 2, 3]})
    candidate = Candidate('synthetic_universe', 'snapshot', 1, START - timedelta(days=1),
                          START, digest(raw), len(raw), restore_synthetic(raw))
    patch = dedup_shadow(catalog.Catalog(catalog.EMPTY_ROOT, lambda _: None), candidate, raw)
    previous = receipts.genesis('overnight:synthetic')
    signed = receipts.sign(previous, patch.root, candidate.sha256, START, 'synthetic', SYNTHETIC_KEY)
    tiers = (SyntheticTier('synthetic_online', {candidate.sha256: raw}),
             SyntheticTier('synthetic_disk', {candidate.sha256: raw}))
    return candidate, CatalogCut(previous, signed.anchor, signed.data), dict(patch.pages), tiers


def gates() -> ReviewGates:
    return ReviewGates(1, START, 0, 0, ('writer',), ('writer',),
                       digest(b'inventory'), digest(b'migration'), digest(b'parity'), digest(b'custody'))


def policy() -> SourcePolicy:
    return SourcePolicy('synthetic_universe', START, digest(b'policy'), 2, 65536)


@pytest.mark.parametrize('days', [21, 28, 42, 84])
def test_multiweek(tmp_path: Path, days: int) -> None:
    result = run_synthetic(tmp_path / 'overnight_storage_harness.sqlite', days=days)
    assert result.snapshots == result.staged == result.blocked_plans == result.journal_reviewed == days
    assert result.adapter_commits == days
    assert result.content_versions == (days + 6) // 7
    assert not result.deletion_authority and not result.globally_wired and not result.physical_custody_verified


@pytest.mark.parametrize('fault', ['corrupt', 'partial', 'clock', 'revision', 'full_disk', 'fencing', 'commit_reply_lost'])
def test_multiweek_interrupted_cut_retains_candidates(tmp_path: Path, fault: str) -> None:
    path = tmp_path / 'overnight_storage_interrupted.sqlite'
    with pytest.raises((ContractError, guard.GuardError, OSError)):
        run_synthetic(path, days=21, fault=fault, fault_day=14)
    journal = Journal(path)
    for day in range(14):
        row = journal.lookup(f'day_{day}')
        assert row is not None and row[1:] == ('REVIEWED', 2)
    interrupted = journal.lookup('day_14')
    assert interrupted is not None and interrupted[1] in {'STAGED', 'VERIFIED'}
    assert journal.lookup('day_15') is None


@pytest.mark.parametrize('fault', ['missing', 'partial', 'corrupt', 'oversize', 'unavailable'])
@pytest.mark.parametrize('tier', [0, 1])
def test_tier_failure_no_proof(fault: str, tier: int) -> None:
    candidate, cut, pages, tiers = fixture()
    tiers[tier].fault = fault
    with pytest.raises(ContractError):
        readback(candidate, cut, {'synthetic': SYNTHETIC_KEY}, pages.get, tiers, restore=restore_synthetic)


@pytest.mark.parametrize('mutation', ['missing_page', 'corrupt_page', 'wrong_pin', 'missing_key', 'wrong_key', 'wrong_generation', 'wrong_source', 'wrong_revision', 'wrong_witness', 'duplicate_domain'])
def test_auth_lookup_fail_closed(mutation: str) -> None:
    candidate, cut, pages, tiers = fixture()
    keys = {'synthetic': SYNTHETIC_KEY}
    if mutation == 'missing_page':
        pages.clear()
    elif mutation == 'corrupt_page':
        pages[cut.trusted.root] = b'corrupt'
    elif mutation == 'wrong_pin':
        cut = replace(cut, trusted=replace(cut.trusted, receipt_sha256=digest(b'wrong')))
    elif mutation == 'missing_key':
        keys = {}
    elif mutation == 'wrong_key':
        keys = {'synthetic': b'x' * 32}
    elif mutation == 'wrong_generation':
        cut = replace(cut, trusted=replace(cut.trusted, generation=2))
    elif mutation == 'wrong_source':
        candidate = replace(candidate, source='different_source')
    elif mutation == 'wrong_revision':
        candidate = replace(candidate, revision=2)
    elif mutation == 'wrong_witness':
        candidate = replace(candidate, witness=digest(b'bad'))
    else:
        tiers[1].domain = tiers[0].domain
    with pytest.raises((ContractError, receipts.ReceiptError, catalog.CatalogError)):
        readback(candidate, cut, keys, pages.get, tiers, restore=restore_synthetic)


def test_shadow_exact_history_and_old_root() -> None:
    candidate, cut, pages, tiers = fixture()
    old = authenticated_catalog(cut, {'synthetic': SYNTHETIC_KEY}, pages.get)
    raw = tiers[0].objects[candidate.sha256]
    successor = replace(candidate, snapshot='next_snapshot')
    patch = dedup_shadow(old, successor, raw)
    pages.update(patch.pages)
    new = catalog.Catalog(patch.root, pages.get)
    assert old.lookup(successor.identity) is None
    assert new.lookup(candidate.identity) == candidate.metadata()
    assert new.lookup(successor.identity) == successor.metadata()
    assert new.audit() == 3  # two snapshot identities, one source content object
    with pytest.raises(ContractError):
        dedup_shadow(new, candidate, raw + b' ')


def test_even_all_gates_never_deletion_authority() -> None:
    candidate, cut, pages, tiers = fixture()
    proof = readback(candidate, cut, {'synthetic': SYNTHETIC_KEY}, pages.get, tiers, restore=restore_synthetic)
    plan = retention_plan(policy(), (candidate,), (proof,), gates(), cut=cut, now=START)
    assert plan.blockers == () and plan.staged == (candidate,)
    assert not plan.deletion_authority and not plan.globally_wired


@pytest.mark.parametrize('failure', ['generation', 'root', 'single_copy', 'restore', 'revision', 'interval', 'dependency', 'delivery', 'inventory', 'migration', 'parity', 'custody', 'writer_missing', 'writer_extra'])
def test_retention_gates(failure: str) -> None:
    candidate, cut, pages, tiers = fixture()
    proof = readback(candidate, cut, {'synthetic': SYNTHETIC_KEY}, pages.get, tiers, restore=restore_synthetic)
    review = gates()
    source_policy = policy()
    if failure == 'generation':
        proof = replace(proof, generation=2)
    elif failure == 'root':
        proof = replace(proof, root=digest(b'other'))
    elif failure == 'single_copy':
        proof = replace(proof, domains=proof.domains[:1], restore_witnesses=proof.restore_witnesses[:1])
    elif failure == 'restore':
        proof = replace(proof, restore_witnesses=(digest(b'bad'),) * 2)
    elif failure == 'revision':
        review = replace(review, source_revision=2)
    elif failure == 'interval':
        source_policy = replace(source_policy, retain_from=START - timedelta(hours=1))
    elif failure == 'dependency':
        review = replace(review, active_references=1)
    elif failure == 'delivery':
        review = replace(review, unresolved_delivery=None)
    elif failure == 'inventory':
        review = replace(review, inventory_sha256=None)
    elif failure == 'migration':
        review = replace(review, factory_migration_sha256=None)
    elif failure == 'parity':
        review = replace(review, lookup_parity_sha256=None)
    elif failure == 'custody':
        review = replace(review, custody_restore_sha256=None)
    elif failure == 'writer_missing':
        review = replace(review, verified_writers=())
    else:
        review = replace(review, verified_writers=('writer', 'unexpected'))
    result = retention_plan(source_policy, (candidate,), (proof,), review, cut=cut, now=START)
    assert result.blockers and not result.deletion_authority


@pytest.mark.parametrize('case', ['stale', 'future', 'source', 'count', 'bytes', 'duplicate', 'proof_duplicate'])
def test_retention_rejects_invalid_staging(case: str) -> None:
    candidate, cut, pages, tiers = fixture()
    proof = readback(candidate, cut, {'synthetic': SYNTHETIC_KEY}, pages.get, tiers, restore=restore_synthetic)
    review, source_policy = gates(), policy()
    candidates: tuple[Candidate, ...] = (candidate,)
    proofs: tuple[Readback, ...] = (proof,)
    if case == 'stale':
        review = replace(review, observed_at=START - timedelta(seconds=61))
    elif case == 'future':
        review = replace(review, observed_at=START + timedelta(seconds=1))
    elif case == 'source':
        source_policy = replace(source_policy, source='other')
    elif case == 'count':
        candidates = ()
    elif case == 'bytes':
        source_policy = replace(source_policy, max_bytes=1)
    elif case == 'duplicate':
        candidates = (candidate, candidate)
    else:
        proofs = (proof, proof)
    with pytest.raises(ContractError):
        retention_plan(source_policy, candidates, proofs, review, cut=cut, now=START)


@pytest.mark.parametrize('case', ['fits', 'full_disk', 'quota', 'delay', 'unknown', 'stale', 'mismatched', 'no_trend'])
def test_runway_preserves_floor_and_peak(case: str) -> None:
    capacity = transition.Capacity(START, 450_000_000, 100_000_000, 0, 24_000_000)
    current = watch.Observation(START, capacity.cluster_bytes)
    previous: watch.Observation | None = watch.Observation(START - timedelta(days=1), 449_500_000)
    bound: int | None = 500_000
    delay = 14
    if case == 'full_disk':
        capacity = replace(capacity, physical_free_bytes=25_000_000)
    elif case == 'quota':
        capacity = replace(capacity, cluster_bytes=475_000_000)
        current = replace(current, cluster_bytes=capacity.cluster_bytes)
    elif case == 'delay':
        delay = 90
    elif case == 'unknown':
        bound = None
    elif case == 'stale':
        capacity = replace(capacity, at=START - timedelta(seconds=61))
    elif case == 'mismatched':
        current = replace(current, cluster_bytes=400_000_000)
    elif case == 'no_trend':
        previous = None
    result = capacity_runway(current, previous, (), schedule_sha256=digest(b'schedule'),
        capacity=capacity, allocation=transition.Allocation('archive', 1_000_000, 2_000_000),
        per_run_upper_bound=bound, owner_delay_days=delay, runs_per_day=1, now=START)
    assert result.peak_plan['required_database_headroom_bytes'] == 24_000_000
    assert not result.peak_plan['hosted_write_authority']
    assert not result.watch_report['all_writers_enforced']
    assert (result.bounded_runs_remaining is not None) == (case == 'fits')
