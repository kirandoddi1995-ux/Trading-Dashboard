"""Per-factory isolated integration candidate; never installs factory switches.

Runs legacy repository methods with an injected borrowed connection inside the
existing guard. Commit requests are deferred; transaction controls/DDL/delete
are rejected. Multi-transaction/locking methods need a dedicated migration,
and are blocked rather than silently changing their semantics.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from datetime import date
from decimal import Decimal
import math
import json
from typing import Protocol, TypeVar

import storage_write_guard as guard
from overnight_storage_contracts import ContractError, digest
from overnight_storage_factory_adapter import FactoryCoverage, guarded_candidate

T = TypeVar('T')


class LegacyCursor(Protocol):
    def execute(self, sql: str, parameters: Sequence[object] | Mapping[str, object] | None = None) -> object: ...
    def executemany(self, sql: str, parameters: Sequence[Sequence[object]]) -> object: ...
    def fetchone(self) -> object: ...
    def fetchall(self) -> object: ...


class LegacyDriver(guard.Connection, Protocol):
    @property
    def synthetic_fixture(self) -> bool: ...
    def cursor(self) -> AbstractContextManager[LegacyCursor]: ...


@dataclass(frozen=True)
class FactoryMethod:
    factory: str
    method: str
    allocation_bound: int
    tables: tuple[str, ...]
    sql: tuple[str, ...]
    max_statements: int


def sql_fingerprint(sql: str) -> str:
    # Trusted fixed statements only. No comment stripping or SQL parsing claim.
    return digest(' '.join(sql.split()).encode())


PRODUCTION_RUN_SQL = 'INSERT INTO quant_app.collection_runs(run_id,mode,scheduled_for,started_at,status,provider,metadata) VALUES (%s,%s,%s,%s,%s,%s,%s)'
SCAN_SQL = (
    'SELECT checkpoint_fencing_token FROM equity_operations.scan_candidates LIMIT 0',
    "INSERT INTO equity_operations.scan_runs (run_id,owner_id,signature,scan_mode,horizon_sessions,status, fencing_token,started_at,heartbeat_at,metadata) VALUES (%s,%s,%s,%s,%s,'RUNNING',%s,to_timestamp(%s),clock_timestamp(),%s::jsonb) ON CONFLICT (run_id) DO NOTHING",
    "INSERT INTO equity_operations.scan_candidates (run_id,instrument,item,status,attempt_no,updated_at) VALUES (%s,%s,%s::jsonb,'PENDING',0,clock_timestamp()) ON CONFLICT (run_id,instrument) DO NOTHING",
)
DERIVATIVE_HEALTH_SQL = ('INSERT INTO derivatives_reference.source_health(kind,trading_date,status,updated_at,source_hash) '
    'VALUES(%s,%s,%s,%s,%s) ON CONFLICT(kind,trading_date) DO UPDATE '
    'SET status=excluded.status,updated_at=excluded.updated_at,source_hash=excluded.source_hash '
    'WHERE derivatives_reference.source_health.updated_at<=excluded.updated_at')


# Concrete first methods; every other callable remains an explicit migration gap.
STAGED_METHODS = (
    FactoryMethod('production', 'start_run', 500_000, ('quant_app.collection_runs',), (PRODUCTION_RUN_SQL,), 1),
    FactoryMethod('equity_scan', 'create_run', 1_000_000, ('equity_operations.scan_runs', 'equity_operations.scan_candidates'), SCAN_SQL, 130),
    FactoryMethod('derivative', 'mark_pending', 500_000, ('derivatives_reference.source_health',), (DERIVATIVE_HEALTH_SQL,), 1),
)


class Lease:
    def __init__(self, connection: LegacyDriver, method: FactoryMethod) -> None:
        self.connection, self.method = connection, method
        self.active = True
        self.session_active = False
        self.statements = 0

    def check(self) -> None:
        if not self.active or not self.session_active or self.connection.info.transaction_status != 2:
            raise ContractError('STAGED_BORROWED_LEASE_CLOSED')


class BorrowedCursor:
    def __init__(self, raw: LegacyCursor, lease: Lease) -> None:
        self.raw, self.lease = raw, lease
        self.closed = False

    def _check(self) -> None:
        self.lease.check()
        if self.closed:
            raise ContractError('STAGED_CURSOR_CLOSED')

    def _sql(self, sql: str) -> None:
        self._check()
        if sql_fingerprint(sql) not in {sql_fingerprint(s) for s in self.lease.method.sql}:
            raise ContractError('STAGED_SQL_FINGERPRINT_UNREVIEWED')
        self.lease.statements += 1
        if self.lease.statements > self.lease.method.max_statements:
            raise ContractError('STAGED_STATEMENT_BOUND')

    def execute(self, sql: str, parameters: Sequence[object] | Mapping[str, object] | None = None) -> object:
        self._sql(sql)
        parameter_bound(parameters)
        return self.raw.execute(sql, parameters)

    def executemany(self, sql: str, parameters: Sequence[Sequence[object]]) -> object:
        self._sql(sql)
        if len(parameters) > 128:
            raise ContractError('STAGED_METHOD_BATCH_BOUND')
        for row in parameters:
            parameter_bound(row)
        self.lease.statements += len(parameters) - 1
        if self.lease.statements > self.lease.method.max_statements:
            raise ContractError('STAGED_STATEMENT_BOUND')
        return self.raw.executemany(sql, parameters)

    def fetchone(self) -> object:
        self._check()
        return self.raw.fetchone()

    @property
    def rowcount(self) -> int:
        self._check()
        value: object = getattr(self.raw, 'rowcount', None)
        if type(value) is not int or not -1 <= value <= 128:
            raise ContractError('STAGED_ROWCOUNT_UNVERIFIED')
        return value

    def fetchall(self) -> object:
        self._check()
        return self.raw.fetchall()


class BorrowedConnection:
    def __init__(self, connection: LegacyDriver, method: FactoryMethod) -> None:
        self.connection, self.method = connection, method
        self.commit_requests = 0
        self.aborted = False
        self.entered = False
        self.stack: ExitStack | None = None
        self.lease = Lease(connection, method)

    @contextmanager
    def session(self) -> Iterator[BorrowedConnection]:
        if self.entered:
            raise ContractError('STAGED_MULTI_SESSION_MIGRATION_REQUIRED')
        self.entered = True
        self.lease.session_active = True
        with ExitStack() as stack:
            self.stack = stack
            try:
                yield self
            finally:
                self.stack = None
                self.lease.session_active = False

    @contextmanager
    def cursor(self) -> Iterator[BorrowedCursor]:
        self.lease.check()
        with self.connection.cursor() as cursor:
            borrowed = BorrowedCursor(cursor, self.lease)
            try:
                yield borrowed
            finally:
                borrowed.closed = True

    def execute(self, sql: str, parameters: Sequence[object] | Mapping[str, object] | None = None) -> object:
        if self.stack is None:
            raise ContractError('STAGED_EXECUTE_OUTSIDE_SESSION')
        raw = self.stack.enter_context(self.connection.cursor())
        cursor = BorrowedCursor(raw, self.lease)
        cursor.execute(sql, parameters)
        return cursor

    def commit(self) -> None:
        self.lease.check()
        self.commit_requests += 1
        if self.commit_requests > 1:
            raise ContractError('STAGED_MULTI_COMMIT_MIGRATION_REQUIRED')

    def rollback(self) -> None:
        self.lease.check()
        self.aborted = True
        raise ContractError('STAGED_ROLLBACK_REQUESTED')


def invoke_staged(connection: LegacyDriver, method: FactoryMethod,
                  construct: Callable[[Callable[[], AbstractContextManager[BorrowedConnection]]], T],
                  invoke: Callable[[T], object], *, coverage: FactoryCoverage,
                  clock: Callable[[], datetime]) -> tuple[object, guard.GuardReceipt]:
    """Construct one isolated real legacy repository and invoke one bounded method.

    A construction callback must inject only the supplied session. No factory
    discovery, credentials or runtime replacement. Results escape after commit.
    """
    if connection.synthetic_fixture is not True:
        raise ContractError('STAGED_UNMEASURED_BOUNDS_SYNTHETIC_ONLY')
    if method not in STAGED_METHODS:
        raise ContractError('STAGED_METHOD_UNREVIEWED')
    return _invoke_profile(connection, method, construct, invoke, coverage=coverage, clock=clock)


def _invoke_profile(connection: LegacyDriver, method: FactoryMethod,
                  construct: Callable[[Callable[[], AbstractContextManager[BorrowedConnection]]], T],
                  invoke: Callable[[T], object], *, coverage: FactoryCoverage,
                  clock: Callable[[], datetime]) -> tuple[object, guard.GuardReceipt]:
    """Internal executor for independently pinned, separately reviewed registries."""
    if connection.synthetic_fixture is not True:
        raise ContractError('STAGED_UNMEASURED_BOUNDS_SYNTHETIC_ONLY')
    def append(supplied: guard.Connection) -> object:
        if supplied is not connection:
            raise ContractError('STAGED_CONNECTION_MISMATCH')
        borrowed = BorrowedConnection(connection, method)
        try:
            repository = construct(borrowed.session)
            result = invoke(repository)
            validate_result(result)
            if borrowed.aborted or not borrowed.entered:
                raise ContractError('STAGED_FACTORY_SESSION_UNVERIFIED')
            return result
        finally:
            borrowed.lease.active = False
    return guarded_candidate(connection, guard.AppendBound(method.factory, method.allocation_bound),
                             append, clock=clock, coverage=coverage)


def validate_result(value: object, depth: int = 0) -> None:
    """Only bounded plain return data may escape, never opaque handles/objects."""
    if depth > 8:
        raise ContractError('STAGED_RESULT_BOUND')
    if value is None or type(value) in (bool, int, float, str, bytes, datetime, date, Decimal):
        if isinstance(value, Decimal) and not value.is_finite():
            raise ContractError('STAGED_RESULT_BOUND')
        if isinstance(value, (str, bytes)) and len(value) > 8192:
            raise ContractError('STAGED_RESULT_BOUND')
        return
    if type(value) in (list, tuple):
        assert isinstance(value, (list, tuple))
        if len(value) > 128:
            raise ContractError('STAGED_RESULT_BOUND')
        for item in value:
            validate_result(item, depth + 1)
        return
    if type(value) is dict:
        assert isinstance(value, dict)
        if len(value) > 128:
            raise ContractError('STAGED_RESULT_BOUND')
        for key, item in value.items():
            if type(key) is not str:
                raise ContractError('STAGED_HANDLE_ESCAPE')
            validate_result(item, depth + 1)
        return
    raise ContractError('STAGED_HANDLE_ESCAPE')


def parameter_bound(parameters: Sequence[object] | Mapping[str, object] | None) -> None:
    from psycopg.types.json import Jsonb
    if parameters is None:
        return
    if not isinstance(parameters, (tuple, list, dict)) or len(parameters) > 32:
        raise ContractError('STAGED_PARAMETER_BOUND')
    values = parameters.values() if isinstance(parameters, Mapping) else parameters
    total = 0
    for value in values:
        if type(value) in (str, bytes):
            assert isinstance(value, (str, bytes))
            total += len(value.encode() if isinstance(value, str) else value)
        elif value is None or type(value) in (bool, int, float, datetime, date, Decimal):
            if isinstance(value, float) and not math.isfinite(value):
                raise ContractError('STAGED_PARAMETER_BOUND')
            total += 64
            if isinstance(value, Decimal) and (not value.is_finite() or len(str(value)) > 128):
                raise ContractError('STAGED_PARAMETER_BOUND')
        elif type(value) is Jsonb:
            assert isinstance(value, Jsonb)
            if value.dumps is not None:
                raise ContractError('STAGED_PARAMETER_TYPE_UNREVIEWED')
            try:
                total += len(json.dumps(value.obj, sort_keys=True, allow_nan=False).encode())
            except (TypeError, ValueError):
                raise ContractError('STAGED_PARAMETER_BOUND') from None
        else:
            raise ContractError('STAGED_PARAMETER_TYPE_UNREVIEWED')
    if total > 8192:
        raise ContractError('STAGED_PARAMETER_BOUND')
