"""Inactive, injected transaction guard for bounded cooperating append writers.

No connection discovery, credentials, automatic runtime wiring or hosted changes.
The advisory lock is transaction-held, not a time-expiring reservation. It cannot
protect against non-cooperating writers or enforce PostgreSQL's allocator bounds.
Rollback does not necessarily shrink files allocated during a failed attempt.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Protocol

from collector_storage_preflight import QUOTA_BYTES, RESERVE_BYTES, RUN_ALLOWANCE_BYTES, assess

FLOOR_BYTES = RESERVE_BYTES + RUN_ALLOWANCE_BYTES
# Namespace must be used by EVERY cooperating writer in the same database.
LOCK_SQL = 'SELECT pg_catalog.pg_try_advisory_xact_lock(77261008, 1)'
MEASURE_SQL = """SELECT pg_catalog.clock_timestamp(),
    (SELECT pg_catalog.sum(pg_catalog.pg_database_size(oid))::pg_catalog.int8 FROM pg_catalog.pg_database),
    r.rolsuper,r.rolbypassrls
    FROM pg_catalog.pg_roles r WHERE r.rolname=current_user"""
FENCE_SQL = """SELECT pg_catalog.pg_current_xact_id()::pg_catalog.text, EXISTS (
    SELECT 1 FROM pg_catalog.pg_locks WHERE locktype='advisory' AND pid=pg_catalog.pg_backend_pid()
    AND mode='ExclusiveLock' AND granted AND classid=77261008::pg_catalog.oid
    AND objid=1::pg_catalog.oid AND objsubid=2)"""


class GuardError(ValueError):
    """Stable failure codes; never expose driver errors or retry unknown commits."""


class Cursor(Protocol):
    """Minimal positional SQL driver; no query or credential logging required."""

    def execute(self, query: str) -> object: ...
    def fetchone(self) -> object: ...


class ConnectionInfo(Protocol):
    """DBAPI/psycopg transaction status: zero means an idle connection."""

    @property
    def transaction_status(self) -> int: ...


class Connection(Protocol):
    """Caller-supplied dedicated connection; the guard owns exactly one TX."""

    @property
    def autocommit(self) -> bool: ...
    @property
    def info(self) -> ConnectionInfo: ...
    def cursor(self) -> AbstractContextManager[Cursor]: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True)
class AppendBound:
    """Reviewed TOTAL allocation bound, not payload length or eventual savings.

    Includes heap, indexes, TOAST and incidental database allocation during this
    append. Normal writers only: no compaction, migration, partition conversion
    or reclamation. Bounds over the current collector's 4 MB allowance need a
    separately reviewed transition, not an increased constant here.
    """

    writer: str
    additional_database_bytes: int


@dataclass
class GuardReceipt:
    """Mutable completion receipt; only a successful commit sets COMMITTED.

    This is local transaction evidence, not signed custody or global enforcement.
    A caller must not publish READY as successful collection. No trade authority.
    """

    writer: str
    before_bytes: int
    declared_bound_bytes: int
    status: str = 'READY_IN_TRANSACTION'
    after_bytes: int | None = None
    global_enforcement_commissioned: bool = False
    approval_authority: bool = False


def _bound(bound: AppendBound) -> None:
    if (not isinstance(bound, AppendBound) or not isinstance(bound.writer, str)
            or re.fullmatch('[a-z][a-z0-9_]{0,62}', bound.writer) is None
            or type(bound.additional_database_bytes) is not int
            or not 0 < bound.additional_database_bytes <= RUN_ALLOWANCE_BYTES):
        raise GuardError('STORAGE_APPEND_BOUND_INVALID')


def _measure(cursor: Cursor, clock: Callable[[], datetime]) -> int:
    cursor.execute(MEASURE_SQL)
    try:
        result = assess(cursor.fetchone(), clock())
        size = result['cluster_bytes']
        if type(size) is not int:
            raise ValueError
        return size
    except Exception:
        raise GuardError('STORAGE_GUARD_MEASUREMENT_UNUSABLE') from None


def _rollback(connection: Connection) -> None:
    try:
        connection.rollback()
    except Exception:
        raise GuardError('STORAGE_ROLLBACK_UNCONFIRMED_DISCARD_CONNECTION') from None


def _fence(cursor: Cursor) -> str:
    """Original transaction identity plus its still-held two-int advisory lock."""
    cursor.execute(FENCE_SQL)
    result = cursor.fetchone()
    if (not isinstance(result, (tuple, list)) or len(result) != 2
            or not isinstance(result[0], str) or re.fullmatch('[1-9][0-9]{0,19}', result[0]) is None
            or int(result[0]) > (1 << 64) - 1 or result[1] is not True):
        raise GuardError('STORAGE_TRANSACTION_FENCE_UNVERIFIED')
    return result[0]


@contextmanager
def append_transaction(connection: Connection, bound: AppendBound, *,
                       clock: Callable[[], datetime]) -> Iterator[GuardReceipt]:
    """One transaction: try lock -> fresh size -> append -> fresh size -> commit.

    Caller MUST use this SAME connection and must NOT commit/rollback, reconnect,
    take another advisory lock, execute DDL or write outside the yielded block.
    Connection must initially be idle, autocommit false and restricted. PostgreSQL
    17+ is required for a 30-second transaction timeout. No network/object-storage
    work inside this transaction; only bounded SQL appends. No leases
    are reclaimed by time; a live writer keeps its transaction lock. Busy rejects
    immediately. Connection establishment timeouts are the owner's responsibility.

    Before: keep the entire 24 MB floor AFTER the declared allocation bound.
    After: keep that floor and reject a bound overrun. An overrun can consume file
    space even after rollback: investigate, remeasure, revise the verified bound;
    NEVER blindly retry. On an uncertain COMMIT, reconcile run/event identities
    independently; no automatic second append. Global enforcement stays false.
    """
    _bound(bound)
    try:
        state = connection.info.transaction_status
        if (connection.autocommit is not False or not isinstance(state, int)
                or isinstance(state, bool) or state != 0):
            raise GuardError('STORAGE_DEDICATED_IDLE_CONNECTION_REQUIRED')
    except GuardError:
        raise
    except Exception:
        raise GuardError('STORAGE_CONNECTION_STATE_UNAVAILABLE') from None
    receipt: GuardReceipt | None = None
    body_error: BaseException | None = None
    phase = 'SETUP'
    try:
        with connection.cursor() as cursor:
            cursor.execute('BEGIN')
            cursor.execute("SET LOCAL statement_timeout='10s'")
            cursor.execute("SET LOCAL lock_timeout='2s'")
            cursor.execute("SET LOCAL transaction_timeout='30s'")
            cursor.execute(LOCK_SQL)
            locked = cursor.fetchone()
            if not isinstance(locked, (tuple, list)) or len(locked) != 1 or locked[0] is not True:
                raise GuardError('STORAGE_WRITER_BUSY_OR_LOCK_UNVERIFIED')
            before = _measure(cursor, clock)
            if before + bound.additional_database_bytes > QUOTA_BYTES - FLOOR_BYTES:
                raise GuardError('STORAGE_APPEND_MARGIN_NOT_MET')
            transaction_id = _fence(cursor)
            receipt = GuardReceipt(bound.writer, before, bound.additional_database_bytes)
            phase = 'BODY'
            try:
                yield receipt
            except BaseException as error:
                body_error = error
                raise
            phase = 'CHECK'
            if connection.info.transaction_status != 2:
                # psycopg TransactionStatus.INTRANS is 2. A caller that commits
                # inside the block has broken the guard; never report success.
                raise GuardError('STORAGE_TRANSACTION_OWNERSHIP_LOST')
            if _fence(cursor) != transaction_id:
                raise GuardError('STORAGE_TRANSACTION_OWNERSHIP_LOST')
            after = _measure(cursor, clock)
            receipt.after_bytes = after
            if after > QUOTA_BYTES - FLOOR_BYTES:
                raise GuardError('STORAGE_POSTWRITE_MARGIN_NOT_MET_DO_NOT_RETRY')
            if after - before > bound.additional_database_bytes:
                raise GuardError('STORAGE_ALLOCATION_BOUND_EXCEEDED_DO_NOT_RETRY')
            phase = 'COMMIT'
            connection.commit()
            receipt.status = 'COMMITTED'
            phase = 'COMPLETE'
        # A faulty injected cursor context must not suppress an acquisition,
        # body, post-check or commit failure and turn it into apparent success.
        if phase != 'COMPLETE':
            if body_error is not None:
                raise body_error
            raise GuardError('STORAGE_TRANSACTION_EXIT_UNCONFIRMED')
    except BaseException as error:
        if receipt is not None:
            receipt.status = ('COMMIT_UNCONFIRMED' if phase == 'COMMIT' else
                              'COMMITTED_CLEANUP_FAILED' if phase == 'COMPLETE' else 'FAILED')
        if phase == 'COMMIT':
            # Rollback cannot establish whether the server already committed.
            try:
                connection.rollback()
            except Exception:
                pass
            raise GuardError('STORAGE_COMMIT_UNCONFIRMED_RECONCILE_DO_NOT_RETRY') from None
        if phase != 'COMPLETE':
            _rollback(connection)
        if body_error is not None:
            raise body_error from None
        if isinstance(error, GuardError) or not isinstance(error, Exception):
            raise
        # Even a cursor exit failure after a successful COMMIT is not retryable.
        if phase == 'COMPLETE':
            raise GuardError('STORAGE_COMMITTED_CONNECTION_CLEANUP_FAILED_DO_NOT_RETRY') from None
        raise GuardError('STORAGE_GUARD_UNAVAILABLE') from None
