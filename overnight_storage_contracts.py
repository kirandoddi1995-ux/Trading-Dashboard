"""Inactive bounded storage orchestration. No transport, deletion or authority.

Caller pins roots independently. Synthetic proofs describe exact bytes and cuts;
they do not establish hardware custody, encryption or whole-application recovery.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import re
from typing import Protocol

import catalog_receipts as receipts
import cold_catalog as catalog
import recovery_bundle as bundle
import recovery_custody_rehearsal as custody
import storage_capacity_watch as watch
import storage_transition as transition

# Absolute in-memory object ceiling. Source limits below are fixture admission
# limits, NOT measured production allocation/maximum-payload evidence.
MAX_BYTES = 8 * 1024 * 1024
SOURCE_OBJECT_LIMITS = {
    'quant_app__evidence_ledger_events': MAX_BYTES,
    'equity_research__outcomes': MAX_BYTES,
    'six_table_image': MAX_BYTES,
    'six_table_witness': 1024 * 1024,
}


def object_limit(source: str) -> int:
    return SOURCE_OBJECT_LIMITS.get(source, 64 * 1024)
MAX_CANDIDATES = 128
MAX_TIERS = 4


class ContractError(ValueError):
    """Allowlisted errors; no underlying transport details."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def instant(at: datetime) -> datetime:
    if type(at) is not datetime or at.tzinfo is None or at.utcoffset() is None:
        raise ContractError('CLOCK_INVALID')
    return at.astimezone(timezone.utc)


def name(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch('[a-z][a-z0-9_]{0,62}', value) is None:
        raise ContractError('IDENTITY_INVALID')
    return value


def hash_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ContractError('DIGEST_INVALID')
    return value


@dataclass(frozen=True)
class Candidate:
    source: str
    snapshot: str
    revision: int
    lower: datetime
    upper: datetime
    sha256: str
    size: int
    witness: str

    def __post_init__(self) -> None:
        name(self.source)
        name(self.snapshot)
        hash_id(self.sha256)
        hash_id(self.witness)
        if (type(self.revision) is not int or self.revision < 1
                or type(self.size) is not int or not 0 < self.size <= object_limit(self.source)
                or instant(self.lower) >= instant(self.upper)):
            raise ContractError('CANDIDATE_INVALID')

    @property
    def identity(self) -> str:
        return f'{self.source}:{self.snapshot}:{self.revision}'

    def metadata(self) -> dict[str, object]:
        return {'source': self.source, 'snapshot': self.snapshot, 'revision': self.revision,
                'lower': instant(self.lower).isoformat(), 'upper': instant(self.upper).isoformat(),
                'sha256': self.sha256, 'size': self.size, 'witness': self.witness}


class Tier(Protocol):
    """Adapter must bound I/O duration and read size; no credential discovery."""
    @property
    def domain(self) -> str: ...
    def read(self, sha256: str, limit: int) -> bytes | None: ...


@dataclass(frozen=True)
class CatalogCut:
    previous: receipts.RootAnchor
    trusted: receipts.RootAnchor
    signed: bytes


def authenticated_catalog(cut: CatalogCut, keys: Mapping[str, bytes],
                          fetch: Callable[[str], bytes | None]) -> catalog.Catalog:
    actual = receipts.verify(cut.signed, cut.trusted.receipt_sha256, cut.previous, keys)
    if actual != cut.trusted:
        raise ContractError('CATALOG_ANCHOR_MISMATCH')
    return catalog.Catalog(actual.root, fetch)


@dataclass(frozen=True)
class RecoveryBinding:
    candidate: Candidate
    catalog_generation: int
    catalog_root: str
    report_sha256: str
    bundle_generation: int
    # An authenticated six-table report still explicitly denies these claims.
    physical_custody_verified: bool = False
    application_recovery_verified: bool = False
    deletion_authority: bool = False


def bind_six_table_recovery(candidate: Candidate, cut: CatalogCut, *,
        catalog_keys: Mapping[str, bytes], fetch: Callable[[str], bytes | None],
        evidence: custody.Rehearsal, trusted_report: receipts.RootAnchor,
        previous_report: receipts.RootAnchor, checkpoint: bundle.BundleCheckpoint,
        trusted_bundle_sha256: str, recovery_keys: Mapping[str, bytes]) -> RecoveryBinding:
    """Authenticate existing custody verifier AND signed exact-source cut binding.

    The catalog entry must be independently published after report verification.
    Bundle generation and catalog generation are different namespaces: neither
    is inferred from the other. Reports never authorize retention/deletion.
    """
    hash_id(trusted_bundle_sha256)
    report = custody.verify_report(evidence, trusted_report=trusted_report,
        previous_report=previous_report, checkpoint=checkpoint,
        trusted_bundle_sha256=trusted_bundle_sha256, keyring=recovery_keys)
    index = authenticated_catalog(cut, catalog_keys, fetch)
    if index.lookup(candidate.identity) != candidate.metadata():
        raise ContractError('RECOVERY_SOURCE_LOOKUP_MISMATCH')
    expected: dict[str, object] = {'candidate': candidate.metadata(),
        'catalog_generation': cut.trusted.generation, 'report_sha256': digest(report),
        'bundle_generation': checkpoint.current.generation, 'bundle_root': checkpoint.current.root,
        'bundle_sha256': trusted_bundle_sha256,
        'bundle_receipt_sha256': checkpoint.current.receipt_sha256}
    if index.lookup('recovery:' + candidate.identity) != expected:
        raise ContractError('RECOVERY_EXACT_CUT_BINDING_MISSING')
    return RecoveryBinding(candidate, cut.trusted.generation, cut.trusted.root,
                           digest(report), checkpoint.current.generation)


@dataclass(frozen=True)
class Readback:
    candidate: Candidate
    generation: int
    root: str
    domains: tuple[str, ...]
    restore_witnesses: tuple[str, ...]


def readback(candidate: Candidate, cut: CatalogCut, keys: Mapping[str, bytes],
             fetch: Callable[[str], bytes | None], tiers: Sequence[Tier], *,
             restore: Callable[[bytes], str]) -> Readback:
    """Exact source lookup, authenticated bytes and decoder witness per tier.

    Exhausts requested tiers; missing/corrupt/partial data never means absence.
    Independent domain names are contract inputs, NOT physical independence proof.
    """
    if not 1 <= len(tiers) <= MAX_TIERS:
        raise ContractError('TIER_BOUND_INVALID')
    index = authenticated_catalog(cut, keys, fetch)
    if index.lookup(candidate.identity) != candidate.metadata():
        raise ContractError('EXACT_LOOKUP_MISMATCH')
    domains: list[str] = []
    witnesses: list[str] = []
    for tier in tiers:
        domain = name(tier.domain)
        if domain in domains:
            raise ContractError('REPLICA_DOMAIN_DUPLICATE')
        try:
            raw = tier.read(candidate.sha256, candidate.size + 1)
            if type(raw) is not bytes or len(raw) != candidate.size or len(raw) > object_limit(candidate.source):
                raise ContractError('READBACK_MISSING_PARTIAL_OR_OVERSIZE')
            measured = bundle.measure('synthetic_payload', io.BytesIO(raw))
            if measured.sha256 != candidate.sha256:
                raise ContractError('READBACK_HASH_MISMATCH')
            witness = restore(raw)
            if witness != candidate.witness:
                raise ContractError('RESTORE_WITNESS_MISMATCH')
        except ContractError:
            raise
        except Exception:
            raise ContractError('READBACK_OR_RESTORE_UNAVAILABLE') from None
        domains.append(domain)
        witnesses.append(witness)
    return Readback(candidate, cut.trusted.generation, cut.trusted.root,
                    tuple(domains), tuple(witnesses))


def dedup_shadow(index: catalog.Catalog, candidate: Candidate, raw: bytes) -> catalog.CatalogPatch:
    """Exact raw hash shared only within source; snapshot/revision stays distinct."""
    if type(raw) is not bytes or len(raw) != candidate.size or digest(raw) != candidate.sha256:
        raise ContractError('SHADOW_CONTENT_MISMATCH')
    content_key = f'content:{candidate.source}:{candidate.sha256}'
    value: dict[str, object] = {'sha256': candidate.sha256, 'size': candidate.size,
                               'source': candidate.source}
    old = index.lookup(content_key)
    if old is not None and old != value:
        raise ContractError('SHADOW_CONTENT_CONFLICT')
    return index.patch({content_key: value, candidate.identity: candidate.metadata()})


@dataclass(frozen=True)
class SourcePolicy:
    source: str
    retain_from: datetime
    policy_sha256: str
    max_candidates: int
    max_bytes: int

    def __post_init__(self) -> None:
        name(self.source)
        instant(self.retain_from)
        hash_id(self.policy_sha256)
        if (type(self.max_candidates) is not int or not 1 <= self.max_candidates <= MAX_CANDIDATES
                or type(self.max_bytes) is not int or not 0 < self.max_bytes <= MAX_CANDIDATES * MAX_BYTES):
            raise ContractError('POLICY_BOUND_INVALID')


@dataclass(frozen=True)
class ReviewGates:
    """Exact engineering review references, never an owner deletion attestation."""
    source_revision: int
    observed_at: datetime
    active_references: int | None
    unresolved_delivery: int | None
    expected_writers: tuple[str, ...]
    verified_writers: tuple[str, ...]
    inventory_sha256: str | None
    factory_migration_sha256: str | None
    lookup_parity_sha256: str | None
    custody_restore_sha256: str | None


@dataclass(frozen=True)
class RetentionPlan:
    staged: tuple[Candidate, ...]
    blockers: tuple[str, ...]
    generation: int
    root: str
    deletion_authority: bool = False
    globally_wired: bool = False


def retention_plan(policy: SourcePolicy, candidates: Sequence[Candidate],
                   proofs: Sequence[Readback], gates: ReviewGates, *,
                   cut: CatalogCut, now: datetime) -> RetentionPlan:
    """Bounded staged review only. No SQL, delete callback or active primitive.

    Readback values are evidence produced offline, not unforgeable capabilities.
    Even all satisfied engineering references NEVER grant deletion authority.
    """
    current = instant(now)
    if not 0 <= (current - instant(gates.observed_at)).total_seconds() <= 60:
        raise ContractError('REVIEW_CLOCK_STALE_OR_FUTURE')
    if instant(policy.retain_from) > current:
        raise ContractError('RETENTION_CLOCK_INVALID')
    if (not 1 <= len(candidates) <= policy.max_candidates
            or sum(c.size for c in candidates) > policy.max_bytes
            or len(proofs) > policy.max_candidates
            or len({c.identity for c in candidates}) != len(candidates)):
        raise ContractError('STAGING_BOUND_OR_DUPLICATE')
    if len({p.candidate.identity for p in proofs}) != len(proofs):
        raise ContractError('PROOF_DUPLICATE')
    blockers: set[str] = set()
    if (not gates.expected_writers or len(set(gates.expected_writers)) != len(gates.expected_writers)
            or len(set(gates.verified_writers)) != len(gates.verified_writers)
            or set(gates.expected_writers) != set(gates.verified_writers)):
        blockers.add('ALL_WRITER_INVENTORY_UNPROVEN')
    for writer in (*gates.expected_writers, *gates.verified_writers):
        name(writer)
    for label, reference in (('WRITER_INVENTORY', gates.inventory_sha256),
                             ('FACTORY_MIGRATION', gates.factory_migration_sha256),
                             ('EXACT_LOOKUP_PARITY', gates.lookup_parity_sha256),
                             ('INDEPENDENT_CUSTODY_RESTORE', gates.custody_restore_sha256)):
        if reference is None:
            blockers.add(label + '_UNPROVEN')
        else:
            hash_id(reference)
    for label, count in (('DEPENDENCIES', gates.active_references),
                          ('DELIVERY', gates.unresolved_delivery)):
        if type(count) is not int or count != 0:
            blockers.add(label + '_PROTECTED_OR_UNKNOWN')
    by_identity = {p.candidate.identity: p for p in proofs}
    staged: list[Candidate] = []
    for candidate in candidates:
        if candidate.source != policy.source:
            raise ContractError('RETENTION_SOURCE_MISMATCH')
        if candidate.revision != gates.source_revision:
            blockers.add('SOURCE_REVISION_CHANGED')
        if instant(candidate.upper) > instant(policy.retain_from) or instant(candidate.upper) > current:
            blockers.add('PROTECTED_INTERVAL')
        proof = by_identity.get(candidate.identity)
        if (proof is None or proof.candidate != candidate or proof.generation != cut.trusted.generation
                or proof.root != cut.trusted.root or len(proof.domains) < 2
                or len(set(proof.domains)) != len(proof.domains)
                or len(proof.restore_witnesses) != len(proof.domains)
                or any(w != candidate.witness for w in proof.restore_witnesses)):
            blockers.add('SAME_GENERATION_CUSTODY_RESTORE_WITNESSES_MISSING')
        staged.append(candidate)
    return RetentionPlan(tuple(staged), tuple(sorted(blockers)),
                         cut.trusted.generation, cut.trusted.root)


@dataclass(frozen=True)
class Runway:
    watch_report: watch.WatchReport
    peak_plan: transition.CapacityPlan
    bounded_runs_remaining: int | None


def capacity_runway(current: watch.Observation | None, previous: watch.Observation | None,
                    runs: Sequence[watch.ExpectedRun], *, schedule_sha256: str | None,
                    capacity: transition.Capacity, allocation: transition.Allocation,
                    per_run_upper_bound: int | None, owner_delay_days: int,
                    runs_per_day: int, now: datetime) -> Runway:
    """500M planning/24M floor; peak includes unreplicated backlog and scratch.

    Two-point trend remains diagnostic. No dedup/reclamation credit, reservation,
    measured alert delivery, all-writer enforcement or operation-journal claim.
    """
    if (type(owner_delay_days) is not int or not 0 <= owner_delay_days <= 90
            or type(runs_per_day) is not int or not 1 <= runs_per_day <= 1440):
        raise ContractError('RUNWAY_SCHEDULE_BOUND_INVALID')
    if per_run_upper_bound is not None and (type(per_run_upper_bound) is not int
                                           or not 0 < per_run_upper_bound <= 4_000_000):
        raise ContractError('RUNWAY_APPEND_BOUND_INVALID')
    report = watch.evaluate(current, previous, runs, schedule_sha256=schedule_sha256, now=now)
    backlog = None if per_run_upper_bound is None else per_run_upper_bound * owner_delay_days * runs_per_day
    bounded = transition.Allocation(allocation.operation,
        None if backlog is None or allocation.additional_database_bytes is None
        else allocation.additional_database_bytes + backlog,
        None if backlog is None or allocation.additional_disk_bytes is None
        else allocation.additional_disk_bytes + backlog)
    peak = transition.capacity_plan(capacity, bounded, now=now)
    remaining: int | None = None
    if (not peak['blockers'] and report['status'] != 'UNKNOWN' and per_run_upper_bound is not None
            and current is not None and current.at == capacity.at
            and current.cluster_bytes == capacity.cluster_bytes):
        db_peak = peak['projected_database_peak_bytes']
        disk = peak['projected_physical_remaining_bytes']
        if db_peak is not None and disk is not None:
            remaining = max(0, min(transition.QUOTA - transition.ADMISSION_FLOOR - db_peak,
                                   disk) // per_run_upper_bound)
    return Runway(report, peak, remaining)
