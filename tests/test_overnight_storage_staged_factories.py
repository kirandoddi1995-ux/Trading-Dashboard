"""Actual existing repository methods, isolated injected driver acceptance."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol, cast

import pytest

import derivative_repository
import equity_scan_repository
import production_repository
import storage_write_guard as guard
from overnight_storage_contracts import ContractError, digest
from overnight_storage_factory_adapter import FactoryCoverage
from overnight_storage_harness import START, SyntheticConnection
from overnight_storage_staged_factories import BorrowedConnection, STAGED_METHODS, invoke_staged


class AcceptanceDriver(SyntheticConnection):
    synthetic_fixture = True
    def __init__(self, fault: str = '') -> None:
        super().__init__(START, fault=fault)
        self.legacy_writes: list[str] = []

    @contextmanager
    def cursor(self) -> Iterator[AcceptanceDriver]:
        yield self

    def execute(self, query: str, parameters: Sequence[object] | Mapping[str, object] | None = None) -> None:
        if parameters is None:
            super().execute(query)
        elif query.lstrip().startswith(('INSERT', 'UPDATE')):
            self.legacy_writes.append(query)
            self.append()
        return None

    def executemany(self, query: str, parameters: Sequence[Sequence[object]]) -> object:
        for values in parameters:
            self.execute(query, values)
        return None

    def fetchall(self) -> object:
        return []


class Scan(Protocol):
    def create_run(self, run: Mapping[str, object], items: Sequence[object]) -> object: ...


class Derivative(Protocol):
    def mark_pending(self, kind: str, trading_date: object, now: object) -> object: ...


class Production(Protocol):
    def start_run(self, mode: str) -> str: ...


@pytest.mark.parametrize('family', ['production', 'equity_scan', 'derivative'])
@pytest.mark.parametrize('fault', ['', 'fencing', 'full_disk', 'commit_reply_lost'])
def test_existing_public_style_method_with_staged_session(family: str, fault: str) -> None:
    driver = AcceptanceDriver(fault)
    method = next(m for m in STAGED_METHODS if m.factory == family)
    def construct(session: Callable[[], AbstractContextManager[BorrowedConnection]]) -> object:
        if family == 'equity_scan':
            constructor = cast(Callable[[object], object], equity_scan_repository.EquityScanRepository)
            return constructor(session)
        if family == 'derivative':
            constructor = cast(Callable[[object], object], derivative_repository.DerivativeRepository)
            return constructor(session)
        constructor = cast(Callable[..., object], production_repository.ProductionRepository)
        repo = constructor('postgresql://inactive.invalid/synthetic', evidence_signing_key=b'', schema_mode='validate')
        # Only this NEW synthetic instance: fake acceptance assumes a prevalidated
        # schema and never executes production role discovery/migration.
        setattr(repo, '_schema_ready', True)
        setattr(repo, 'connect', session)
        return repo
    def invoke(repo: object) -> object:
        if family == 'equity_scan':
            return cast(Scan, repo).create_run({'id': 'synthetic', 'owner': 'synthetic',
                'signature': 'synthetic', 'started_at': START.timestamp()}, [])
        if family == 'derivative':
            return cast(Derivative, repo).mark_pending('MASTER_NSE', START.date(), START)
        return cast(Production, repo).start_run('synthetic')
    coverage = FactoryCoverage((family,), (family,), digest(b'synthetic inventory'), digest(b'synthetic migration'))
    if fault:
        expected = {'fencing': 'STORAGE_TRANSACTION_OWNERSHIP_LOST',
                    'full_disk': 'synthetic full disk',
                    'commit_reply_lost': 'STORAGE_COMMIT_UNCONFIRMED_RECONCILE_DO_NOT_RETRY'}[fault]
        with pytest.raises((guard.GuardError, OSError), match=expected):
            invoke_staged(driver, method, construct, invoke, coverage=coverage, clock=lambda: START)
        assert driver.commits == int(fault == 'commit_reply_lost')
    else:
        _, receipt = invoke_staged(driver, method, construct, invoke, coverage=coverage, clock=lambda: START)
        assert driver.legacy_writes and driver.commits == 1 and receipt.status == 'COMMITTED'
        assert not receipt.global_enforcement_commissioned


@pytest.mark.parametrize('sql', ['DELETE FROM quant_app.collection_runs', 'BEGIN',
    'INSERT INTO quant_app.collection_runs VALUES (1); COMMIT',
    'SELECT pg_advisory_xact_lock(1) FROM quant_app.collection_runs',
    'INSERT INTO unknown.table VALUES (1)',
    'SELECT dangerous_function() FROM quant_app.collection_runs',
    'INSERT/**/INTO quant_app.collection_runs VALUES(1)',
    'INSERT INTO collection_runs VALUES(1)'])
def test_unsupported_semantics_block_before_driver(sql: str) -> None:
    from overnight_storage_staged_factories import BorrowedCursor, Lease
    driver = AcceptanceDriver()
    driver.info.transaction_status = 2
    lease = Lease(driver, STAGED_METHODS[0])
    lease.session_active = True
    cursor = BorrowedCursor(driver, lease)
    with pytest.raises(ContractError):
        cursor.execute(sql, (1,))
    assert not driver.legacy_writes


def test_session_handles_expire_and_nested_handles_cannot_escape() -> None:
    from overnight_storage_staged_factories import BorrowedConnection, validate_result
    driver = AcceptanceDriver()
    driver.info.transaction_status = 2
    borrowed = BorrowedConnection(driver, STAGED_METHODS[0])
    with pytest.raises(ContractError, match='LEASE_CLOSED'):
        with borrowed.cursor():
            pytest.fail('cursor available outside session')
    with borrowed.session():
        with borrowed.cursor() as cursor:
            with pytest.raises(ContractError, match='HANDLE_ESCAPE'):
                validate_result({'nested': [cursor]})
        with pytest.raises(ContractError, match='CURSOR_CLOSED'):
            cursor.fetchone()
    with pytest.raises(ContractError, match='LEASE_CLOSED'):
        cursor.execute(STAGED_METHODS[0].sql[0], ())


def test_nonfixture_driver_blocked_before_callback() -> None:
    driver = AcceptanceDriver()
    driver.synthetic_fixture = False
    coverage = FactoryCoverage(('production',), ('production',), digest(b'inventory'), digest(b'migration'))
    with pytest.raises(ContractError, match='SYNTHETIC_ONLY'):
        invoke_staged(driver, STAGED_METHODS[0], lambda _: None, lambda _: None,
                      coverage=coverage, clock=lambda: START)
    assert driver.info.transaction_status == 0


def test_parameter_fixture_bounds_and_statement_bounds() -> None:
    from overnight_storage_staged_factories import BorrowedCursor, Lease, parameter_bound
    driver = AcceptanceDriver()
    driver.info.transaction_status = 2
    lease = Lease(driver, STAGED_METHODS[0])
    lease.session_active = True
    cursor = BorrowedCursor(driver, lease)
    with pytest.raises(ContractError, match='PARAMETER_BOUND'):
        cursor.execute(STAGED_METHODS[0].sql[0], ('x' * 8193,))
    assert not driver.legacy_writes
    with pytest.raises(ContractError, match='PARAMETER_TYPE'):
        parameter_bound((object(),))
    # A rejected oversized request consumes its attempt budget; never silently retry.
    with pytest.raises(ContractError, match='STATEMENT_BOUND'):
        cursor.execute(STAGED_METHODS[0].sql[0], ())
