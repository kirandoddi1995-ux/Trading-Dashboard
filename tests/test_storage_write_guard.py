"""Offline transaction ordering/failure tests; no database, secrets or fixtures."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest

import storage_write_guard as guard

NOW = datetime(2026, 10, 8, 4, tzinfo=timezone.utc)
BOUND = guard.AppendBound('synthetic_scan', 4_000_000)


@dataclass
class Lock:
    owner: FakeConnection | None = None


@dataclass
class Info:
    transaction_status: int = 0


class FakeConnection:
    """Deterministic same-connection lock and transaction model, not Postgres."""

    def __init__(self, *, size: int = 450_000_000, growth: int = 700_000,
                 lock: Lock | None = None) -> None:
        self.autocommit = False
        self.info = Info()
        self.lock = lock or Lock()
        self.size = size
        self.growth = growth
        self.queries: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.measures = 0
        self.bad_measure: object | None = None
        self.at = NOW
        self.superuser = False
        self.bypass = False
        self.fail_query: str | None = None
        self.fail_commit = False
        self.fail_rollback = False
        self.fail_exit = False
        self.lock_result: object | None = None
        self.transaction_id = 10
        self.bad_fence: object | None = None
        self.exit_mode: str | None = None

    @contextmanager
    def cursor(self) -> Iterator[FakeCursor]:
        try:
            yield FakeCursor(self)
        except BaseException:
            if self.exit_mode == 'replace':
                raise OSError('private wrapper detail must not escape') from None
            if self.exit_mode != 'suppress':
                raise
        if self.fail_exit:
            raise OSError('private connection detail must not escape')

    def commit(self) -> None:
        self.commits += 1
        self.info.transaction_status = 0
        self.lock.owner = None
        if self.fail_commit:
            raise OSError('private connection detail must not escape')

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.fail_rollback:
            raise OSError('private connection detail must not escape')
        self.info.transaction_status = 0
        if self.lock.owner is self:
            self.lock.owner = None


class FakeCursor:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.result: object = None

    def execute(self, query: str) -> None:
        connection = self.connection
        connection.queries.append(query)
        if query == connection.fail_query:
            raise OSError('private connection detail must not escape')
        if query == 'BEGIN':
            connection.info.transaction_status = 2
            connection.transaction_id += 1
        elif query == guard.LOCK_SQL:
            if connection.lock_result is not None:
                self.result = connection.lock_result
            elif connection.lock.owner is None:
                connection.lock.owner = connection
                self.result = (True,)
            else:
                self.result = (False,)
        elif query == guard.FENCE_SQL:
            self.result = (connection.bad_fence if connection.bad_fence is not None else
                           (str(connection.transaction_id), connection.lock.owner is connection))
        elif query == guard.MEASURE_SQL:
            connection.measures += 1
            size = connection.size + (connection.growth if connection.measures > 1 else 0)
            self.result = (connection.bad_measure if connection.bad_measure is not None
                           else (connection.at, size, connection.superuser, connection.bypass))

    def fetchone(self) -> object:
        return self.result


def test_order_same_transaction_lock_measure_body_postmeasure_commit() -> None:
    connection = FakeConnection()
    with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
        assert receipt.status == 'READY_IN_TRANSACTION'
        assert connection.measures == 1 and connection.commits == 0
        assert connection.lock.owner is connection
        assert connection.info.transaction_status == 2
    assert receipt.status == 'COMMITTED' and receipt.after_bytes == 450_700_000
    assert receipt.before_bytes == 450_000_000 and receipt.declared_bound_bytes == 4_000_000
    assert receipt.global_enforcement_commissioned is False and receipt.approval_authority is False
    assert connection.commits == 1 and connection.rollbacks == 0
    assert connection.info.transaction_status == 0 and connection.lock.owner is None
    assert connection.queries == ['BEGIN', "SET LOCAL statement_timeout='10s'",
                                  "SET LOCAL lock_timeout='2s'", "SET LOCAL transaction_timeout='30s'", guard.LOCK_SQL,
                                  guard.MEASURE_SQL, guard.FENCE_SQL, guard.FENCE_SQL, guard.MEASURE_SQL]


def test_two_writers_cannot_both_spend_same_observed_headroom() -> None:
    lock = Lock()
    first, second = FakeConnection(lock=lock), FakeConnection(lock=lock)
    with guard.append_transaction(first, BOUND, clock=lambda: NOW):
        with pytest.raises(guard.GuardError, match='WRITER_BUSY'):
            with guard.append_transaction(second, BOUND, clock=lambda: NOW):
                pytest.fail('second writer entered')
        assert second.measures == 0 and second.rollbacks == 1
        assert lock.owner is first
    with guard.append_transaction(second, BOUND, clock=lambda: NOW):
        assert lock.owner is second
    assert first.commits == second.commits == 1


@pytest.mark.parametrize('extra', [0, 1])
def test_before_margin_boundary_preserves_floor_after_bound(extra: int) -> None:
    connection = FakeConnection(size=472_000_000 + extra, growth=4_000_000)
    if extra:
        with pytest.raises(guard.GuardError, match='APPEND_MARGIN'):
            with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
                pytest.fail('insufficient margin')
        assert connection.commits == 0 and connection.rollbacks == 1
    else:
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            pass
        assert receipt.status == 'COMMITTED' and receipt.after_bytes == 476_000_000


@pytest.mark.parametrize('amount', [0, -1, True, 1.0, '4000000', 4_000_001, None])
def test_missing_unverified_or_oversized_bounds_never_start(amount: Any) -> None:
    connection = FakeConnection()
    with pytest.raises(guard.GuardError, match='APPEND_BOUND_INVALID'):
        with guard.append_transaction(connection, replace(BOUND, additional_database_bytes=amount), clock=lambda: NOW):
            pytest.fail('invalid bound')
    assert connection.queries == [] and connection.commits == connection.rollbacks == 0


@pytest.mark.parametrize('name', ['', 'scan/secret', 'Scan', '../scan', 'x'*64, None])
def test_writer_identifier_allowlist(name: Any) -> None:
    with pytest.raises(guard.GuardError, match='APPEND_BOUND_INVALID'):
        with guard.append_transaction(FakeConnection(), replace(BOUND, writer=name), clock=lambda: NOW):
            pytest.fail('invalid writer')


@pytest.mark.parametrize('value', [None, {}, False])
def test_missing_request_is_a_stable_block_before_any_sql(value: Any) -> None:
    connection = FakeConnection()
    with pytest.raises(guard.GuardError, match='APPEND_BOUND_INVALID'):
        with guard.append_transaction(connection, value, clock=lambda: NOW):
            pytest.fail('missing request')
    assert connection.queries == []


@pytest.mark.parametrize('status', [1, 2, 3, 4, False])
def test_existing_transaction_rejected_without_rolling_back_callers_work(status: int) -> None:
    connection = FakeConnection()
    connection.info.transaction_status = status
    with pytest.raises(guard.GuardError, match='DEDICATED_IDLE'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('existing transaction')
    assert connection.queries == [] and connection.rollbacks == 0


def test_autocommit_rejected_before_sql() -> None:
    connection = FakeConnection()
    connection.autocommit = True
    with pytest.raises(guard.GuardError, match='DEDICATED_IDLE'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('autocommit')
    assert connection.queries == []


@pytest.mark.parametrize('result', [(False,), ('true',), ('false',), (1,), (), (True, True), None])
def test_lock_evidence_requires_boolean_true(result: object) -> None:
    connection = FakeConnection()
    connection.lock_result = result if result is not None else []
    with pytest.raises(guard.GuardError, match='WRITER_BUSY'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('invalid lock evidence')
    assert connection.measures == connection.commits == 0


@pytest.mark.parametrize('age', [-1, 61])
def test_future_or_stale_measurement_blocks(age: int) -> None:
    connection = FakeConnection()
    connection.at = NOW - timedelta(seconds=age)
    with pytest.raises(guard.GuardError, match='MEASUREMENT_UNUSABLE'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('stale/future')
    assert connection.rollbacks == 1 and connection.commits == 0


def test_equivalent_ist_measurement_and_exact_max_age() -> None:
    connection = FakeConnection()
    connection.at = (NOW - timedelta(seconds=60)).astimezone(timezone(timedelta(hours=5, minutes=30)))
    with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
        pass
    assert connection.commits == 1


@pytest.mark.parametrize('flag', ['superuser', 'bypass'])
def test_privileged_owner_connection_cannot_be_normal_writer(flag: str) -> None:
    connection = FakeConnection()
    setattr(connection, flag, True)
    with pytest.raises(guard.GuardError, match='MEASUREMENT_UNUSABLE'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('owner writer')


@pytest.mark.parametrize('row', [(), (NOW, True, False, False), (NOW, -1, False, False),
                                 (NOW.replace(tzinfo=None), 1, False, False),
                                 (NOW, 1, 'false', False), (NOW, 1, False, 0)])
def test_invalid_measurements_redacted(row: object) -> None:
    connection = FakeConnection()
    connection.bad_measure = row
    with pytest.raises(guard.GuardError, match='MEASUREMENT_UNUSABLE'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('invalid measurement')


def test_body_error_propagates_after_rollback_without_committing() -> None:
    connection = FakeConnection()
    original = RuntimeError('synthetic body failure')
    with pytest.raises(RuntimeError) as caught:
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            raise original
    assert caught.value is original and receipt.status == 'FAILED'
    assert connection.commits == 0 and connection.rollbacks == 1
    assert connection.lock.owner is None


def test_allocation_bound_overrun_blocks_commit_and_is_not_retry_authority() -> None:
    connection = FakeConnection(growth=4_000_001)
    with pytest.raises(guard.GuardError, match='BOUND_EXCEEDED_DO_NOT_RETRY'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            pass
    assert receipt.status == 'FAILED' and receipt.after_bytes == 454_000_001
    assert connection.commits == 0 and connection.rollbacks == 1


def test_decrease_does_not_create_extra_pre_admission_credit() -> None:
    connection = FakeConnection(size=472_000_001, growth=-10_000_000)
    with pytest.raises(guard.GuardError, match='APPEND_MARGIN'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('future savings were credited')
    assert connection.measures == 1


def test_actual_floor_breach_is_an_emergency_even_if_bound_was_declared() -> None:
    connection = FakeConnection(size=472_000_000, growth=10_000_000)
    with pytest.raises(guard.GuardError, match='POSTWRITE_MARGIN_NOT_MET_DO_NOT_RETRY'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            pass
    assert receipt.status == 'FAILED' and receipt.after_bytes == 482_000_000
    assert connection.commits == 0 and connection.rollbacks == 1


def test_stale_second_measurement_blocks_commit() -> None:
    connection = FakeConnection()
    with pytest.raises(guard.GuardError, match='MEASUREMENT_UNUSABLE'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            connection.at = NOW - timedelta(seconds=61)
    assert receipt.status == 'FAILED' and connection.commits == 0


def test_caller_committing_inside_block_is_contract_breach_not_success() -> None:
    connection = FakeConnection()
    with pytest.raises(guard.GuardError, match='OWNERSHIP_LOST'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            connection.commit()
    assert receipt.status == 'FAILED' and connection.measures == 1


def test_commit_then_new_transaction_cannot_hide_ownership_loss() -> None:
    connection = FakeConnection()
    with pytest.raises(guard.GuardError, match='OWNERSHIP_LOST'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute('BEGIN')
                cursor.execute(guard.LOCK_SQL)
    assert connection.measures == 1 and connection.commits == 1


def test_released_advisory_lock_blocks_even_unchanged_transaction_id() -> None:
    connection = FakeConnection()
    with pytest.raises(guard.GuardError, match='TRANSACTION_FENCE_UNVERIFIED'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            connection.lock.owner = None
    assert connection.commits == 0 and connection.rollbacks == 1


@pytest.mark.parametrize('fence', [('0', True), ('01', True), ('x', True),
                                    (str(1 << 64), True), ('10', 'true'), ('10', 1), (10, True), ()])
def test_bad_transaction_fence_never_enters_writer(fence: object) -> None:
    connection = FakeConnection()
    connection.bad_fence = fence
    with pytest.raises(guard.GuardError, match='TRANSACTION_FENCE_UNVERIFIED'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('invalid fence')
    assert connection.commits == 0 and connection.rollbacks == 1


def test_uncertain_commit_must_reconcile_not_repeat() -> None:
    connection = FakeConnection()
    connection.fail_commit = True
    connection.fail_rollback = True
    with pytest.raises(guard.GuardError, match='COMMIT_UNCONFIRMED_RECONCILE_DO_NOT_RETRY') as caught:
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            pass
    assert receipt.status == 'COMMIT_UNCONFIRMED' and connection.commits == 1
    assert 'private' not in str(caught.value)


def test_unconfirmed_rollback_is_not_silently_reusable_connection() -> None:
    connection = FakeConnection()
    connection.fail_rollback = True
    with pytest.raises(guard.GuardError, match='ROLLBACK_UNCONFIRMED_DISCARD_CONNECTION'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            raise RuntimeError('body')


def test_post_commit_cursor_cleanup_failure_never_authorises_retry() -> None:
    connection = FakeConnection()
    connection.fail_exit = True
    with pytest.raises(guard.GuardError, match='COMMITTED_CONNECTION_CLEANUP_FAILED_DO_NOT_RETRY'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            pass
    assert connection.commits == 1 and connection.rollbacks == 0
    assert receipt.status == 'COMMITTED_CLEANUP_FAILED'  # committed, NEVER safe to append again


def test_setup_transport_error_redacted_and_rolled_back() -> None:
    connection = FakeConnection()
    connection.fail_query = guard.MEASURE_SQL
    with pytest.raises(guard.GuardError, match='GUARD_UNAVAILABLE') as caught:
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('failed SQL entered body')
    assert 'private' not in str(caught.value) and connection.rollbacks == 1


@pytest.mark.parametrize('mode', ['suppress', 'replace'])
def test_cursor_cannot_suppress_or_replace_callers_body_error(mode: str) -> None:
    connection = FakeConnection()
    connection.exit_mode = mode
    original = RuntimeError('synthetic body error')
    with pytest.raises(RuntimeError) as caught:
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            raise original
    assert caught.value is original and receipt.status == 'FAILED'
    assert connection.commits == 0 and connection.rollbacks == 1


def test_suppressed_acquisition_failure_still_cannot_enter_writer() -> None:
    connection = FakeConnection()
    connection.exit_mode = 'suppress'
    connection.fail_query = guard.MEASURE_SQL
    with pytest.raises(guard.GuardError, match='TRANSACTION_EXIT_UNCONFIRMED'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW):
            pytest.fail('suppressed acquisition failure yielded')
    assert connection.commits == 0 and connection.rollbacks == 1


def test_suppressed_commit_failure_remains_uncertain_not_success() -> None:
    connection = FakeConnection()
    connection.exit_mode = 'suppress'
    connection.fail_commit = True
    with pytest.raises(guard.GuardError, match='COMMIT_UNCONFIRMED_RECONCILE_DO_NOT_RETRY'):
        with guard.append_transaction(connection, BOUND, clock=lambda: NOW) as receipt:
            pass
    assert receipt.status == 'COMMIT_UNCONFIRMED' and connection.commits == 1
