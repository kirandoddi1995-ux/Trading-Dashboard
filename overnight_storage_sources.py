"""Exact source routing/retention and content maps for every budgeted table.

No universal cutoff or decoder is invented. Caller supplies a reviewed per-source
policy and a bounded decoder. Immutable/control sources stay protected always.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

import cold_catalog as catalog
import storage_policy
from overnight_storage_contracts import (Candidate, CatalogCut, ContractError, Readback,
    RetentionPlan, ReviewGates, SourcePolicy, Tier, dedup_shadow, digest, readback, retention_plan)
from datetime import datetime


@dataclass(frozen=True)
class SourceSpec:
    source: str
    table: str
    retention_contract: str
    never_retire: bool


KNOWN_SOURCES: Mapping[str, SourceSpec] = MappingProxyType({
    budget.name.replace('.', '__'): SourceSpec(budget.name.replace('.', '__'), budget.name,
        budget.retention, budget.name in {'quant_app.schema_migrations', 'quant_app.collector_leases',
            'quant_storage.catalog_roots', 'quant_storage.ledger_control', 'quant_storage.ledger_hot_heads',
            'derivatives_reference.source_health', 'derivatives_monitor.state'})
    for budget in storage_policy.BUDGETS
})


@dataclass(frozen=True)
class ShadowEntry:
    source: str
    snapshot: str
    revision: int
    content_sha256: str
    size: int


class SourceRouter:
    """All known tables have explicit identity; absent decoder is blocked."""
    def __init__(self, decoders: Mapping[str, Callable[[bytes], str]]) -> None:
        if set(decoders) - set(KNOWN_SOURCES):
            raise ContractError('UNKNOWN_SOURCE_DECODER')
        self.decoders = MappingProxyType(dict(decoders))

    def recover(self, candidate: Candidate, cut: CatalogCut, keys: Mapping[str, bytes],
                pages: Callable[[str], bytes | None], tiers: Sequence[Tier], *,
                hot: bytes | None = None) -> Readback:
        decoder = self.decoders.get(candidate.source)
        if candidate.source not in KNOWN_SOURCES or decoder is None:
            raise ContractError('SOURCE_RECOVERY_DECODER_UNCOMMISSIONED')
        proof = readback(candidate, cut, keys, pages, tiers, restore=decoder)
        if hot is not None and (type(hot) is not bytes or len(hot) != candidate.size
                or digest(hot) != candidate.sha256 or decoder(hot) != candidate.witness):
            raise ContractError('HOT_COLD_EXACT_PARITY_MISMATCH')
        return proof

    def shadow(self, index: catalog.Catalog, candidate: Candidate, raw: bytes) -> tuple[catalog.CatalogPatch, ShadowEntry]:
        decoder = self.decoders.get(candidate.source)
        if decoder is None or decoder(raw) != candidate.witness:
            raise ContractError('SOURCE_SHADOW_DECODER_OR_WITNESS_UNVERIFIED')
        patch = dedup_shadow(index, candidate, raw)
        return patch, ShadowEntry(candidate.source, candidate.snapshot, candidate.revision,
                                  candidate.sha256, candidate.size)

    def retention(self, policy: SourcePolicy, candidates: Sequence[Candidate],
                  proofs: Sequence[Readback], gates: ReviewGates, *, cut: CatalogCut,
                  now: datetime, protected_latest: bool | None,
                  source_dependency_closure: str | None) -> RetentionPlan:
        spec = KNOWN_SOURCES.get(policy.source)
        if spec is None:
            raise ContractError('UNKNOWN_RETENTION_SOURCE')
        plan = retention_plan(policy, candidates, proofs, gates, cut=cut, now=now)
        blockers = set(plan.blockers)
        if policy.source not in self.decoders:
            blockers.add('SOURCE_DECODER_UNCOMMISSIONED')
        if spec.never_retire:
            blockers.add('SOURCE_CONTROL_OR_FRONTIER_ALWAYS_PROTECTED')
        if protected_latest is not False:
            blockers.add('SOURCE_LATEST_ACTIVE_OR_UNKNOWN')
        if source_dependency_closure is None:
            blockers.add('SOURCE_DEPENDENCY_CLOSURE_UNPROVEN')
        elif source_dependency_closure != digest((spec.table + ':' + spec.retention_contract).encode()):
            blockers.add('SOURCE_DEPENDENCY_CONTRACT_MISMATCH')
        return replace(plan, blockers=tuple(sorted(blockers)))
