"""Inactive factory switch review contract. Parses source, never imports it.

Public-base bytes/hashes must be supplied by Main's verified package. Local held
drafts cannot establish public coverage. Every callable in each repository is
conservatively inventoried, including read APIs that share its connection.
"""
from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
import json
import re

from overnight_storage_contracts import ContractError, digest, hash_id

MAX_SOURCE_BYTES = 2_000_000
# Source-only entry points observed locally; this is an explicit lower bound,
# not an assertion that external jobs or deployed public source are inventoried.
REQUIRED = {
    'app.py': ('get_production_repository', 'get_equity_scan_repository', 'get_model_registry',
               'get_mutual_fund_archive', 'get_runtime_evidence_store'),
    'production_repository.py': ('ProductionRepository',),
    'equity_scan_repository.py': ('EquityScanRepository',),
    'equity_research_repository.py': ('ResearchRepository',),
    'equity_research_collector.py': ('main',),
    'derivative_repository.py': ('DerivativeRepository', 'main'),
    'derivative_monitor.py': ('main',),
    'prospective_collection.py': ('ProspectiveFeatureWriter',),
    'equity_positions.py': ('PositionRepository',),
    'model_registry.py': ('ModelRegistry',),
    'mf_archive.py': ('MutualFundArchive',),
    'archive_maintenance.py': ('ArchiveRepository', 'main'),
    'ledger_archive_repository.py': ('LedgerArchiveRepository',),
    'scheduled_collector.py': ('run', 'main', 'CollectorLease'),
    'model_training_pipeline.py': ('production_smoke', 'register_shadow_candidate'),
    'evidence_progress.py': ('load_production_progress',),
    'recovery_drill.py': ('verify_isolated_target',),
    'runtime_evidence_store.py': ('RuntimeEvidenceStore',),
}


@dataclass(frozen=True)
class SourceInventory:
    source_sha256: tuple[tuple[str, str], ...]
    callables: tuple[str, ...]
    missing: tuple[str, ...]
    inventory_sha256: str


def inventory(sources: Mapping[str, bytes]) -> SourceInventory:
    if len(sources) > 128 or any(path not in REQUIRED for path in sources):
        raise ContractError('FACTORY_SOURCE_BOUND_OR_SCOPE')
    hashes: list[tuple[str, str]] = []
    callables: list[str] = []
    missing: list[str] = []
    for path, symbols in sorted(REQUIRED.items()):
        raw = sources.get(path)
        if raw is None:
            missing.append(path)
            continue
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES:
            raise ContractError('FACTORY_SOURCE_SIZE_INVALID')
        try:
            tree = ast.parse(raw)
        except (SyntaxError, UnicodeError, ValueError):
            raise ContractError('FACTORY_SOURCE_PARSE_INVALID') from None
        hashes.append((path, digest(raw)))
        nodes = {node.name: node for node in tree.body
                 if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}
        for symbol in symbols:
            node = nodes.get(symbol)
            if node is None:
                missing.append(path + ':' + symbol)
            elif isinstance(node, ast.ClassDef):
                callables.extend(path + ':' + symbol + '.' + member.name for member in node.body
                                 if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)))
            else:
                callables.append(path + ':' + symbol)
    if len(callables) > 512:
        raise ContractError('FACTORY_CALLABLE_BOUND')
    content = json.dumps({'sources': hashes, 'callables': sorted(callables), 'missing': missing},
                         sort_keys=True, separators=(',', ':')).encode()
    return SourceInventory(tuple(hashes), tuple(sorted(callables)), tuple(missing), digest(content))


@dataclass(frozen=True)
class SwitchingEvidence:
    """Independently reviewed engineering refs; no owner attestation authority."""
    public_base_sha: str | None
    public_sources: tuple[tuple[str, str], ...]
    reviewed_callables: tuple[str, ...]
    allocation_bounds_sha256: str | None
    same_connection_transactions_sha256: str | None
    original_receipt_reconciliation_sha256: str | None
    historical_lookup_parity_sha256: str | None
    native_fencing_races_sha256: str | None
    deployment_inventory_sha256: str | None


@dataclass(frozen=True)
class SwitchingPlan:
    inventory_sha256: str
    blockers: tuple[str, ...]
    # No switch callback, enabled flag, connection wrapping or source edit exists.
    active: bool = False
    globally_wired: bool = False


def switching_plan(observed: SourceInventory, evidence: SwitchingEvidence) -> SwitchingPlan:
    blockers: set[str] = set()
    if observed.missing:
        blockers.add('FACTORY_SOURCE_OR_SYMBOL_MISSING')
    if evidence.public_base_sha is None:
        blockers.add('PUBLIC_BASE_UNVERIFIED')
    elif re.fullmatch('[0-9a-f]{40}', evidence.public_base_sha) is None:
        raise ContractError('PUBLIC_BASE_INVALID')
    if (len({path for path, _ in evidence.public_sources}) != len(evidence.public_sources)
            or dict(observed.source_sha256) != dict(evidence.public_sources)):
        blockers.add('PUBLIC_SOURCE_HASH_COVERAGE_UNVERIFIED')
    if (len(set(evidence.reviewed_callables)) != len(evidence.reviewed_callables)
            or set(evidence.reviewed_callables) != set(observed.callables)):
        blockers.add('ALL_FACTORY_CALLABLES_UNVERIFIED')
    for label, reference in (
            ('ALLOCATION_BOUNDS', evidence.allocation_bounds_sha256),
            ('SAME_CONNECTION_TRANSACTION_MIGRATION', evidence.same_connection_transactions_sha256),
            ('ORIGINAL_RECEIPT_RECONCILIATION', evidence.original_receipt_reconciliation_sha256),
            ('HISTORICAL_LOOKUP_PARITY', evidence.historical_lookup_parity_sha256),
            ('NATIVE_FENCING_RACES', evidence.native_fencing_races_sha256),
            ('DEPLOYMENT_WRITER_INVENTORY', evidence.deployment_inventory_sha256)):
        if reference is None:
            blockers.add(label + '_UNVERIFIED')
        else:
            hash_id(reference)
    return SwitchingPlan(observed.inventory_sha256, tuple(sorted(blockers)))
