"""Pinned existing-repository fixture routes and exhaustive migration dispositions.

Exact statements are derived ONLY from independently pinned source for the named
reviewed methods below, never from arbitrary SQL/callback inputs. Execution stays
synthetic/disposable; public factories, schema admission and measured bounds are
not commissioned. The three native STAGED_METHODS remain a separate registry.
"""
from __future__ import annotations

import ast
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import cast

import derivative_repository
import equity_research_repository
import equity_scan_repository
import production_repository
import storage_write_guard as guard
from overnight_storage_contracts import ContractError, digest
from overnight_storage_factory_adapter import FactoryCoverage
from overnight_storage_staged_factories import (BorrowedConnection, FactoryMethod,
    LegacyDriver, _invoke_profile, validate_result)
from overnight_storage_switching import inventory

FAMILIES = {
    'production': ('production_repository.py', 'ProductionRepository'),
    'equity_scan': ('equity_scan_repository.py', 'EquityScanRepository'),
    'derivative': ('derivative_repository.py', 'DerivativeRepository'),
    'research': ('equity_research_repository.py', 'ResearchRepository'),
}
REVIEWED: Mapping[str, tuple[str, ...]] = {
    'production': ('start_run', 'finish_run', 'acquire_collector_lease', 'renew_collector_lease',
        'release_collector_lease', 'record_resilience_snapshot', 'record_runtime_attestation',
        'record_recovery_drill', 'record_feature_observation', 'archive_corporate_actions',
        'mark_enrichment_checked', 'archive_quotes', 'upsert_scanner_observations',
        'save_prediction_target', 'save_validation_run', 'archive_mf_nav',
        'archive_mf_disclosures', 'record_quality_event', 'prior_average_volumes',
        'enrichment_candidates', 'corporate_action_candidates'),
    'equity_scan': ('create_run', 'heartbeat', 'save_manual_review', 'latest_manual_review',
                   'unresolved_orders', 'latest_recoverable'),
    'derivative': ('mark_pending', 'set_monitor_state', 'save_position', 'alert', 'clear_alert',
        'acknowledge', 'finish_email', 'ingest_master', 'ingest_ban', 'historical', 'reviewed',
        'monitor_state', 'positions', 'alerts', 'load'),
    'research': ('register', 'report', 'sources'),
}
HELPERS = {'_health', '_source'}


@dataclass(frozen=True)
class RepositoryRoute:
    profile: FactoryMethod
    path: str
    symbol: str
    source_sha256: str
    access: str


@dataclass(frozen=True)
class MethodDisposition:
    identity: str
    status: str
    reason: str


@dataclass(frozen=True)
class RouteRegistry:
    routes: tuple[RepositoryRoute, ...]
    dispositions: tuple[MethodDisposition, ...]

    def find(self, family: str, method: str) -> RepositoryRoute:
        for route in self.routes:
            if (route.profile.factory, route.profile.method) == (family, method):
                return route
        raise ContractError('REPOSITORY_METHOD_MIGRATION_BLOCKED')


def _text(node: ast.expr, constants: Mapping[str, str]) -> str:
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.Name) and node.id in constants:
        return constants[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _text(node.left, constants) + _text(node.right, constants)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for item in node.values:
            if isinstance(item, ast.FormattedValue):
                if item.conversion != -1 or item.format_spec is not None:
                    raise ContractError('REPOSITORY_DYNAMIC_SQL_REQUIRES_PORT')
                parts.append(_text(item.value, constants))
            else:
                parts.append(_text(item, constants))
        return ''.join(parts)
    raise ContractError('REPOSITORY_DYNAMIC_SQL_REQUIRES_PORT')


def _statements(method: ast.FunctionDef | ast.AsyncFunctionDef,
                members: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
                constants: Mapping[str, str], seen: set[str]) -> tuple[str, ...]:
    if method.name in seen:
        raise ContractError('REPOSITORY_HELPER_CYCLE')
    seen = seen | {method.name}
    statements: list[str] = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            action = node.func.attr
            if action in {'rollback', 'executescript', 'close'}:
                raise ContractError('REPOSITORY_TRANSACTION_OR_LIFECYCLE_PORT_REQUIRED')
            if action in {'execute', 'executemany'} and node.args:
                statements.append(_text(node.args[0], constants))
            if action in HELPERS:
                statements.extend(_statements(members[action], members, constants, seen))
        elif isinstance(node.func, ast.Name) and node.func.id == '_executemany':
            if len(node.args) < 2:
                raise ContractError('REPOSITORY_DYNAMIC_SQL_REQUIRES_PORT')
            statements.append(_text(node.args[1], constants))
    for sql in statements:
        normalized = ' '.join(sql.split()).upper()
        if (not normalized.startswith(('SELECT ', 'INSERT ', 'UPDATE ', 'WITH '))
                or ';' in sql or '--' in sql or '/*' in sql
                or re.search(r'\b(DELETE|DROP|TRUNCATE|ALTER|CREATE|BEGIN|COMMIT|SAVEPOINT)\b', normalized)
                or 'PG_ADVISORY_' in normalized or 'PG_TRY_ADVISORY_' in normalized):
            raise ContractError('REPOSITORY_SPECIAL_SQL_PORT_REQUIRED')
    return tuple(dict.fromkeys(statements))


def compile_registry(sources: Mapping[str, bytes], trusted_hashes: Mapping[str, str]) -> RouteRegistry:
    """Every observed callable gets a disposition; absent public files are missing.

    Source pins must originate in Main's public candidate. Self-pinning local held
    drafts proves only synthetic fixture compatibility, not public coverage.
    """
    observed = inventory(sources)
    routes: list[RepositoryRoute] = []
    supported: set[str] = set()
    failures: dict[str, str] = {}
    for family, (path, symbol) in FAMILIES.items():
        raw = sources.get(path)
        if raw is None:
            continue
        if trusted_hashes.get(path) != digest(raw):
            raise ContractError('REPOSITORY_PUBLIC_SOURCE_PIN_MISMATCH')
        tree = ast.parse(raw)
        constants = {node.targets[0].id: node.value.value for node in tree.body
                     if isinstance(node, ast.Assign) and len(node.targets) == 1
                     and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)
                     and type(node.value.value) is str}
        owner = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == symbol), None)
        if owner is None:
            continue
        members = {node.name: node for node in owner.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for method_name in REVIEWED[family]:
            method = members.get(method_name)
            identity = path + ':' + symbol + '.' + method_name
            if method is None:
                failures[identity] = 'METHOD_ABSENT_FROM_PINNED_PUBLIC_SOURCE'
                continue
            try:
                statements = _statements(method, members, constants, set())
                if not statements:
                    raise ContractError('REPOSITORY_NO_DIRECT_SQL_DELEGATE_PORT_REQUIRED')
            except ContractError as error:
                failures[identity] = str(error)
                continue
            tables = sorted({table.lower() for sql in statements for table in re.findall(
                r'\b(?:FROM|INTO|UPDATE|JOIN)\s+([a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*)', sql, re.IGNORECASE)})
            write = any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'WITH')) for sql in statements)
            profile = FactoryMethod(family, method_name, 4_000_000 if write else 1,
                                    tuple(tables), statements, 256)
            routes.append(RepositoryRoute(profile, path, symbol, digest(raw), 'WRITE' if write else 'READ'))
            supported.add(identity)
    dispositions: list[MethodDisposition] = []
    for identity in observed.callables:
        if identity in supported:
            dispositions.append(MethodDisposition(identity, 'FIXTURE_ROUTE', 'PINNED_SQL_ACTUAL_METHOD'))
            continue
        path, symbol = identity.split(':', 1)
        method_name = symbol.rsplit('.', 1)[-1]
        if identity in failures:
            reason = failures[identity]
        elif path in {'model_registry.py', 'mf_archive.py', 'runtime_evidence_store.py'}:
            reason = 'SQLITE_SCHEMA_FACTORY_NEEDS_SEPARATE_LOCAL_ALLOCATION_GUARD'
        elif method_name == 'commit' and path == 'ledger_archive_repository.py':
            reason = 'DESTRUCTIVE_ARCHIVE_COMMIT_EXCLUDED_NO_DELETE_PRIMITIVE'
        elif method_name.startswith('_') or method_name in {'configured', 'ensure_schema', 'connect'}:
            reason = 'CONSTRUCTOR_SCHEMA_DRIVER_OR_INTERNAL_HELPER_NOT_INVOKABLE'
        elif any(token in method_name for token in ('checkpoint', 'delivery', 'evidence_event', 'recovery')):
            reason = 'ORIGINAL_RECEIPT_OR_MULTI_TRANSACTION_FENCE_PORT_REQUIRED'
        elif method_name in {'historical', 'events', 'pending_observations', 'matured_decision_dataset', 'decision_outcome_records'}:
            reason = 'FULL_HISTORY_CONSUMER_CUT_AND_ORIGINAL_SIGNATURE_ROUTE_REQUIRED'
        else:
            reason = 'EXPLICIT_METHOD_SEMANTICS_AND_FIXTURE_ACCEPTANCE_REQUIRED'
        dispositions.append(MethodDisposition(identity, 'BLOCKED_ENGINEERING', reason))
    dispositions.extend(MethodDisposition(path, 'PUBLIC_SOURCE_MISSING', 'MAIN_PUBLIC_BYTES_REQUIRED')
                        for path in observed.missing)
    for identity, reason in failures.items():
        if identity not in observed.callables:
            dispositions.append(MethodDisposition(identity, 'PUBLIC_METHOD_MISSING', reason))
    return RouteRegistry(tuple(routes), tuple(sorted(dispositions, key=lambda value: value.identity)))


def invoke_repository(connection: LegacyDriver, route: RepositoryRoute,
        args: Sequence[object], kwargs: Mapping[str, object], *,
        coverage: FactoryCoverage, clock: Callable[[], datetime]) -> tuple[object, guard.GuardReceipt]:
    """Actual methods/SQL only. Injected fixture constructors never discover a DSN."""
    modules = {'production': production_repository, 'equity_scan': equity_scan_repository,
               'derivative': derivative_repository, 'research': equity_research_repository}
    family = route.profile.factory
    module = modules.get(family)
    if module is None or module.__file__ is None:
        raise ContractError('REPOSITORY_FACTORY_UNKNOWN')
    loaded = Path(module.__file__).read_bytes()
    if digest(loaded) != route.source_sha256:
        raise ContractError('REPOSITORY_LOADED_SOURCE_DIFFERS_FROM_PUBLIC_PIN')
    rebuilt = compile_registry({route.path: loaded}, {route.path: route.source_sha256}).find(family, route.profile.method)
    if route != rebuilt:
        raise ContractError('REPOSITORY_ROUTE_FINGERPRINT_TAMPERED')
    validate_result(list(args))
    validate_result(dict(kwargs))
    if len(args) > 16 or len(kwargs) > 32 or any(key.startswith('_') for key in kwargs):
        raise ContractError('REPOSITORY_ARGUMENT_SCOPE_INVALID')
    constructor = cast(Callable[..., object], getattr(module, route.symbol))
    def build(session: Callable[[], AbstractContextManager[BorrowedConnection]]) -> object:
        if family == 'production':
            repo = constructor('postgresql://inactive.invalid/synthetic', evidence_signing_key=b'', schema_mode='validate')
            setattr(repo, '_schema_ready', True)  # Only the explicit prevalidated fixture instance.
            setattr(repo, 'connect', session)
            return repo
        return constructor(session)
    def call(repo: object) -> object:
        method = cast(Callable[..., object], getattr(repo, route.profile.method))
        return method(*args, **kwargs)
    if family == 'research':
        def direct(session: Callable[[], AbstractContextManager[BorrowedConnection]]) -> object:
            with session() as borrowed:
                return call(constructor(borrowed))
        return _invoke_profile(connection, route.profile, lambda session: session, direct,
                               coverage=coverage, clock=clock)
    return _invoke_profile(connection, route.profile, build, call, coverage=coverage, clock=clock)
