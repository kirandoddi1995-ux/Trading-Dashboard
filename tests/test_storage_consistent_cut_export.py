"""Deterministic OFFLINE failures; no database, credentials, files or transport."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal, DefaultContext, Inexact, Rounded, ROUND_DOWN, localcontext
import math
import traceback
from typing import TypeVar, cast

import pytest

import storage_consistent_cut_export as export
import storage_daily_volume_reader as reader
from overnight_storage_contracts import digest

KNOWN = datetime(2024, 1, 16, 12, tzinfo=timezone.utc)
REQUEST = export.ExportRequest('cut_a', date(2024, 1, 1), date(2024, 1, 16), lookback=2)
Row = tuple[object, ...]
F = TypeVar('F', bound=Callable[..., object])


def parametrize(names: str, values: Sequence[object]) -> Callable[[F], F]:
    """Keep pytest's decorator typed under the public follow_imports=skip policy."""
    return cast(Callable[[F], F], pytest.mark.parametrize(names, values))


@dataclass
class FakeCursor:
    owner: FakeConnection
    pending: list[Row] = field(default_factory=list)
    position: int = 0
    phase: str = ''

    def execute(self, operation: str, parameters: Sequence[object] = ()) -> object:
        assert operation.lstrip().startswith('SELECT ')
        assert ';' not in operation
        assert self.owner.active
        self.owner.operations.append((operation, tuple(parameters)))
        sources = {
            export.SETTINGS_SQL: ('settings', self.owner.settings),
            export.COUNT_SQL: ('count', self.owner.counts),
            export.ROWS_SQL: ('rows', self.owner.rows),
            export.AGGREGATE_SQL: ('aggregate', self.owner.aggregates),
        }
        self.phase, self.pending = sources[operation]
        self.position = 0
        self.owner.hit(self.phase)
        return None

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        assert 1 <= size <= export.BATCH_ROWS
        self.owner.hit('fetch_' + self.phase)
        if self.owner.oversize_batch:
            return [('x',)] * (size + 1)
        result = self.pending[self.position:self.position + size]
        self.position += len(result)
        return result

    def close(self) -> None:
        self.owner.events.append('cursor_close')
        self.owner.hit('cursor_close')


@dataclass
class FakeConnection:
    rows: list[Row] = field(default_factory=lambda: [
        ('A', date(2024, 1, 2), Decimal('10')),
        ('A', date(2024, 1, 3), Decimal('20')),
        ('A', date(2024, 1, 4), Decimal('30')),
        ('B', date(2024, 1, 3), Decimal('-2')),
    ])
    counts: list[Row] = field(default_factory=lambda: [(4, 2)])
    aggregates: list[Row] = field(default_factory=lambda: [
        ('A', 3, Decimal('60'), 2, 25.0), ('B', 1, Decimal('-2'), 1, -2.0),
    ])
    settings: list[Row] = field(default_factory=lambda: [('repeatable read', 'on', KNOWN)])
    autocommit: bool = False
    active: bool = False
    status: int = 0
    faults: set[str] = field(default_factory=set)
    events: list[str] = field(default_factory=list)
    operations: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    oversize_batch: bool = False

    def hit(self, step: str) -> None:
        if step in self.faults:
            # Even a driver which imitates the public exception must be redacted.
            raise export.ExportError('secret_password private_host private_row')

    def get_transaction_status(self) -> int:
        self.hit('status')
        return self.status

    def set_session(self, *, isolation_level: str, readonly: bool, autocommit: bool) -> None:
        self.events.append('session')
        self.hit('session')
        assert (isolation_level, readonly, autocommit) == ('REPEATABLE READ', True, False)
        self.autocommit = autocommit
        self.active = True

    def cursor(self) -> FakeCursor:
        self.hit('cursor')
        return FakeCursor(self)

    def rollback(self) -> None:
        self.events.append('rollback')
        self.hit('rollback')
        self.active = False

    def close(self) -> None:
        self.events.append('close')
        self.hit('close')


def run(connection: FakeConnection, request: export.ExportRequest = REQUEST) -> export.ConsistentCut:
    return export.export_daily_volumes(connection, request, monotonic=lambda: 0.0)


def rejected(connection: FakeConnection, code: str, request: export.ExportRequest = REQUEST) -> None:
    with pytest.raises(export.ExportError, match='^' + code + '$'):
        run(connection, request)
    assert connection.events[-1] == 'close'
    if 'session' in connection.events:
        assert 'rollback' in connection.events


def test_exact_cut_reader_contract_and_native_query() -> None:
    conn = FakeConnection()
    cut = run(conn)
    assert cut.row_count == 4 and cut.key_count == 2
    assert cut.known_at == KNOWN and dict(cut.averages) == {'A': 25.0}
    assert conn.events == ['session', 'rollback', 'cursor_close', 'close']
    assert [sql for sql, _ in conn.operations] == [export.SETTINGS_SQL, export.COUNT_SQL,
                                                 export.ROWS_SQL, export.AGGREGATE_SQL]
    assert conn.operations[-1][1] == (REQUEST.start_date, REQUEST.end_date,
        REQUEST.start_date, REQUEST.end_date, date(2024, 1, 16), 2, reader.MAX_KEYS + 1)
    obj, = cut.objects
    decoded = reader.decode_snapshot(obj.raw)
    assert [(r.instrument_key, r.trade_date, r.max_captured_volume) for r in decoded.rows] == conn.rows
    assert obj.candidate.sha256 == digest(obj.raw)
    assert obj.candidate.size == len(obj.raw)
    assert obj.candidate.witness == reader.restore_witness(obj.raw)
    assert cut.declaration() == reader.cut_declaration(REQUEST.cut_id, KNOWN, (obj.candidate,))
    assert not cut.physical_custody_verified and not cut.deletion_authority and not cut.global_wired
    assert cut.historical_pit_verified is False
    assert cut.snapshot_visibility_timestamp_exact is False
    with pytest.raises(TypeError):
        cut.averages['A'] = 1.0  # type: ignore[index]


def test_known_at_uses_post_acquisition_server_clock_not_transaction_start() -> None:
    # The transaction began before this window ended. A commit may become visible
    # before its first SELECT acquires the snapshot. Start time cannot label it.
    transaction_start = datetime(2024, 1, 15, 12, tzinfo=timezone.utc)
    acquired_at = KNOWN - timedelta(milliseconds=1)
    markers: list[str] = []

    class ServerClockCursor(FakeCursor):
        def execute(self, operation: str, parameters: Sequence[object] = ()) -> object:
            result = super().execute(operation, parameters)
            if operation == export.SETTINGS_SQL:
                markers.append('snapshot_acquired')
                # Independent timestamp-source emulation: substituting the old
                # SQL returns the earlier start and fails the requested window.
                observation = KNOWN if 'clock_timestamp()' in operation else transaction_start
                markers.append('server_clock_evaluated')
                self.pending = [('repeatable read', 'on', observation)]
            return result

    class ServerClockConnection(FakeConnection):
        def cursor(self) -> FakeCursor:
            return ServerClockCursor(self)

    conn = ServerClockConnection()
    cut = run(conn)
    settings_sql = conn.operations[0][0]
    assert settings_sql == export.SETTINGS_SQL
    assert 'clock_timestamp()' in settings_sql
    assert 'transaction_timestamp()' not in settings_sql
    assert 'statement_timestamp()' not in settings_sql
    assert markers == ['snapshot_acquired', 'server_clock_evaluated']
    assert transaction_start < acquired_at <= cut.known_at == KNOWN
    assert cut.known_at != transaction_start
    assert cut.declaration()['known_at'] == KNOWN.isoformat()
    assert all(reader.decode_snapshot(obj.raw).known_at == KNOWN for obj in cut.objects)
    assert cut.historical_pit_verified is False
    assert cut.snapshot_visibility_timestamp_exact is False
    assert conn.events[-3:] == ['rollback', 'cursor_close', 'close']


def test_empty_window_is_exact_empty_object_not_missing_cut() -> None:
    conn = FakeConnection(rows=[], counts=[(0, 0)], aggregates=[])
    cut = run(conn)
    assert cut.row_count == cut.key_count == 0 and not cut.averages
    assert len(cut.objects) == 1
    assert reader.decode_snapshot(cut.objects[0].raw).rows == ()


@parametrize('phase', ['status', 'session', 'cursor', 'settings', 'count', 'rows',
    'aggregate', 'fetch_settings', 'fetch_count', 'fetch_rows', 'fetch_aggregate'])
def test_driver_failure_every_phase_redacted_and_released(phase: str) -> None:
    conn = FakeConnection(faults={phase})
    with pytest.raises(export.ExportError) as caught:
        run(conn)
    assert str(caught.value) == 'CUT_DRIVER_UNAVAILABLE'
    assert 'secret_password' not in ''.join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert conn.events[-1] == 'close'
    if phase != 'status':
        assert 'rollback' in conn.events


@parametrize('faults', [{'rollback'}, {'cursor_close'}, {'close'},
                                  {'rollback', 'cursor_close', 'close'}, {'rows', 'rollback'}])
def test_cleanup_failure_never_returns_prepared_cut(faults: set[str]) -> None:
    conn = FakeConnection(faults=faults)
    rejected(conn, 'CUT_RELEASE_UNVERIFIED')
    assert conn.events[-3:] == ['rollback', 'cursor_close', 'close']


@parametrize('phase', ['status', 'session', 'cursor', 'settings', 'count', 'rows',
    'aggregate', 'fetch_settings', 'fetch_count', 'fetch_rows', 'fetch_aggregate',
    'rollback', 'cursor_close', 'close'])
def test_keyboard_interrupt_preserved_after_every_possible_release(phase: str) -> None:
    interrupt = KeyboardInterrupt()

    class Interrupted(FakeConnection):
        def hit(self, step: str) -> None:
            if step == phase:
                raise interrupt
            super().hit(step)

    conn = Interrupted()
    with pytest.raises(KeyboardInterrupt) as caught:
        run(conn)
    assert caught.value is interrupt
    assert conn.events[-1] == 'close'
    if phase == 'status':
        assert conn.events == ['close']
    elif phase in {'session', 'cursor'}:
        assert conn.events[-2:] == ['rollback', 'close']
    else:
        assert conn.events[-3:] == ['rollback', 'cursor_close', 'close']
    if phase == 'rollback':
        assert conn.active  # Rollback interrupted: no assertion that it undid work.


def test_body_interrupt_wins_over_cleanup_interrupt_and_exceptions() -> None:
    original = KeyboardInterrupt()
    cleanup_interrupt = SystemExit(7)

    class Interrupted(FakeConnection):
        def hit(self, step: str) -> None:
            if step == 'rows':
                raise original
            if step == 'rollback':
                raise cleanup_interrupt
            super().hit(step)

    conn = Interrupted(faults={'cursor_close', 'close'})
    with pytest.raises(KeyboardInterrupt) as caught:
        run(conn)
    assert caught.value is original
    assert conn.events[-3:] == ['rollback', 'cursor_close', 'close']


def test_first_cleanup_interrupt_wins_and_all_later_releases_are_attempted() -> None:
    first = SystemExit(9)

    class Interrupted(FakeConnection):
        def hit(self, step: str) -> None:
            if step == 'rollback':
                raise first
            if step == 'cursor_close':
                raise KeyboardInterrupt()
            super().hit(step)

    # Ordinary body and later cleanup errors cannot suppress process interruption.
    conn = Interrupted(faults={'rows', 'close'})
    with pytest.raises(SystemExit) as caught:
        run(conn)
    assert caught.value is first and caught.value.code == 9
    assert conn.events[-3:] == ['rollback', 'cursor_close', 'close']


@parametrize('settings', [
    [('read committed', 'on', KNOWN)], [('repeatable read', 'off', KNOWN)],
    [('repeatable read', 'on', datetime(2024, 1, 16))],
    [('repeatable read', 'on', None)], [],
    [('repeatable read', 'on', KNOWN)] * 2,
])
def test_transaction_settings_fail_closed(settings: list[Row]) -> None:
    conn = FakeConnection(settings=settings)
    with pytest.raises(export.ExportError):
        run(conn)
    assert len(conn.operations) == 1
    assert conn.events[-3:] == ['rollback', 'cursor_close', 'close']


def test_no_sql_for_nonidle_or_autocommit_handle() -> None:
    conn = FakeConnection(status=2)
    rejected(conn, 'CUT_IDLE_CONNECTION_REQUIRED')
    assert conn.events == ['close'] and not conn.operations
    conn = FakeConnection(autocommit=True)
    rejected(conn, 'CUT_AUTOCOMMIT_REJECTED')
    assert conn.events == ['close'] and not conn.operations


def test_nonconforming_setter_cannot_enable_autocommit() -> None:
    class BadSetter(FakeConnection):
        def set_session(self, *, isolation_level: str, readonly: bool, autocommit: bool) -> None:
            super().set_session(isolation_level=isolation_level, readonly=readonly, autocommit=autocommit)
            self.autocommit = True

    conn = BadSetter()
    rejected(conn, 'CUT_AUTOCOMMIT_REJECTED')
    assert conn.events == ['session', 'rollback', 'close'] and not conn.operations


@parametrize('changes', [
    {'start_date': date(2024, 1, 16)}, {'end_date': date(2026, 1, 1)},
    {'cut_id': 'SQL; DROP'}, {'cut_id': 'a' * 56}, {'revision': True},
    {'revision': 0}, {'lookback': 0}, {'lookback': 401}, {'max_seconds': float('nan')},
    {'max_seconds': float('inf')}, {'max_seconds': True}, {'max_seconds': 31.0},
])
def test_request_bounds_before_transaction(changes: dict[str, object]) -> None:
    conn = FakeConnection()
    with pytest.raises(export.ExportError):
        run(conn, replace(REQUEST, **changes))  # type: ignore[arg-type]  # Deliberately invalid inputs.
    assert conn.events == ['close'] and not conn.operations


def test_future_window_cannot_be_declared() -> None:
    conn = FakeConnection()
    rejected(conn, 'CUT_FUTURE_WINDOW', replace(REQUEST, end_date=date(2024, 1, 17)))
    assert len(conn.operations) == 1


@parametrize('counts,code', [
    ([(3, 2)], 'CUT_COUNT_MISMATCH'), ([(4, 1)], 'CUT_COUNT_MISMATCH'),
    ([(1601, 2)], 'CUT_COUNT_BOUND'), ([(4, 129)], 'CUT_COUNT_BOUND'),
    ([(True, 2)], 'CUT_COUNT_BOUND'), ([(4, -1)], 'CUT_COUNT_BOUND'),
    ([], 'CUT_SINGLE_RESULT_REQUIRED'), ([(4, 2), (4, 2)], 'CUT_SINGLE_RESULT_REQUIRED'),
])
def test_counts_own_same_window_and_no_prefix_success(counts: list[Row], code: str) -> None:
    rejected(FakeConnection(counts=counts), code)


@parametrize('bad', [None, True, 1.0, Decimal('NaN'), Decimal('Infinity'),
    Decimal('-Infinity'), Decimal('1e19'), Decimal('1e-1000')])
def test_invalid_native_numeric(bad: object) -> None:
    conn = FakeConnection()
    conn.rows[0] = ('A', date(2024, 1, 2), bad)
    with pytest.raises(export.ExportError):
        run(conn)
    assert conn.events[-3:] == ['rollback', 'cursor_close', 'close']


@parametrize('rows,code', [
    ([('A', date(2024, 1, 2), Decimal(1))] * 2, 'CUT_ROW_ORDER_OR_DUPLICATE'),
    ([('B', date(2024, 1, 2), Decimal(1)), ('A', date(2024, 1, 2), Decimal(1))],
     'CUT_ROW_ORDER_OR_DUPLICATE'),
    ([('A', date(2023, 12, 31), Decimal(1))], 'CUT_ROW_INVALID'),
    ([('A', date(2024, 1, 16), Decimal(1))], 'CUT_ROW_INVALID'),
    ([('A', None, Decimal(1))], 'CUT_ROW_INVALID'),
    ([('A', datetime(2024, 1, 2), Decimal(1))], 'CUT_ROW_INVALID'),
    ([(None, date(2024, 1, 2), Decimal(1))], 'CUT_ROW_INVALID'),
    ([(' A', date(2024, 1, 2), Decimal(1))], 'CUT_SNAPSHOT_INVALID'),
    ([('A', date(2024, 1, 2))], 'CUT_ROW_SCHEMA_INVALID'),
])
def test_missing_duplicate_ordered_and_invalid_keys(rows: list[Row], code: str) -> None:
    rejected(FakeConnection(rows=rows, counts=[(len(rows), len({r[0] for r in rows}))]), code)


@parametrize('aggregates,code', [
    ([('A', 3, Decimal(60), 2, 24.0), ('B', 1, Decimal(-2), 1, -2.0)],
     'CUT_NATIVE_AVERAGE_MISMATCH'),
    ([('A', 3, Decimal(61), 2, 25.0), ('B', 1, Decimal(-2), 1, -2.0)], 'CUT_AGGREGATE_MISMATCH'),
    ([('A', 2, Decimal(60), 2, 25.0), ('B', 1, Decimal(-2), 1, -2.0)], 'CUT_AGGREGATE_MISMATCH'),
    ([('A', 3, Decimal(60), 1, 25.0), ('B', 1, Decimal(-2), 1, -2.0)], 'CUT_AGGREGATE_MISMATCH'),
    ([('A', 3, Decimal(60), 2, float('nan')), ('B', 1, Decimal(-2), 1, -2.0)],
     'CUT_NATIVE_AVERAGE_MISMATCH'),
    ([('A', 3, Decimal('NaN'), 2, 25.0), ('B', 1, Decimal(-2), 1, -2.0)], 'CUT_AGGREGATE_MISMATCH'),
    ([('A', 3, Decimal(60), 2, None), ('B', 1, Decimal(-2), 1, -2.0)], 'CUT_NATIVE_AVERAGE_MISMATCH'),
    ([('A', 3, Decimal(60), 2, 25.0)], 'CUT_AGGREGATE_KEYS_MISMATCH'),
    ([('B', 1, Decimal(-2), 1, -2.0), ('A', 3, Decimal(60), 2, 25.0)], 'CUT_AGGREGATE_KEYS_MISMATCH'),
    ([('A', 3, Decimal(60), 2, 25.0)] * 2, 'CUT_AGGREGATE_KEYS_MISMATCH'),
])
def test_native_aggregate_failure_injection(aggregates: list[Row], code: str) -> None:
    rejected(FakeConnection(aggregates=aggregates), code)


def test_row_missing_but_count_forged_still_fails_key_coverage() -> None:
    conn = FakeConnection()
    conn.rows.pop()
    conn.counts = [(3, 1)]
    rejected(conn, 'CUT_AGGREGATE_KEYS_MISMATCH')


def test_decimal_context_does_not_round_exact_sum() -> None:
    with localcontext() as context:
        context.prec = 2
        assert run(FakeConnection()).averages['A'] == 25.0


def test_81_digit_native_sum_ignores_caller_and_default_decimal_context(
        monkeypatch: pytest.MonkeyPatch) -> None:
    largest = Decimal('1000000000000000000')
    smallest = Decimal('0.000001' + '0' * 55 + '1')
    native_total = Decimal('1000000000000000000.000001' + '0' * 55 + '1')
    assert len(str(smallest)) == 64 and len(native_total.as_tuple().digits) == 81
    conn = FakeConnection(rows=[('A', date(2024, 1, 2), largest),
        ('A', date(2024, 1, 3), smallest)], counts=[(2, 1)],
        aggregates=[('A', 2, native_total, 2, 5e17)])
    # Mutating DefaultContext also must not change the fully specified context.
    monkeypatch.setattr(DefaultContext, 'prec', 1)
    monkeypatch.setattr(DefaultContext, 'Emax', 1)
    monkeypatch.setattr(DefaultContext, 'Emin', -1)
    monkeypatch.setattr(DefaultContext, 'rounding', ROUND_DOWN)
    monkeypatch.setitem(DefaultContext.traps, Rounded, True)
    monkeypatch.setitem(DefaultContext.traps, Inexact, True)
    with localcontext() as caller:
        caller.prec = 2
        caller.Emax = 2
        caller.Emin = -2
        caller.rounding = ROUND_DOWN
        caller.clamp = 1
        caller.capitals = 0
        for signal in caller.traps:
            caller.traps[signal] = True
        caller.flags[Inexact] = True
        original_flags, original_traps = dict(caller.flags), dict(caller.traps)
        cut = run(conn)
        assert dict(cut.averages) == {'A': 5e17}
        assert (caller.prec, caller.Emax, caller.Emin, caller.rounding, caller.clamp,
                caller.capitals) == (2, 2, -2, ROUND_DOWN, 1, 0)
        assert dict(caller.flags) == original_flags and dict(caller.traps) == original_traps


@parametrize('number', [Decimal('0e-16384'), Decimal('1e-16384'),
                       Decimal('0e-999999999'), Decimal('1e-999999999')])
def test_native_impossible_fractional_scale_rejected_before_codec(number: Decimal) -> None:
    conn = FakeConnection(rows=[('A', date(2024, 1, 2), number)], counts=[(1, 1)])
    rejected(conn, 'CUT_ROW_INVALID')
    assert all(sql != export.AGGREGATE_SQL for sql, _ in conn.operations)


def test_postgres_fractional_boundary_and_native_total_scale() -> None:
    assert export._numeric_scale_valid(Decimal('1e-16383'))
    assert not export._numeric_scale_valid(Decimal('1e-16384'))
    conn = FakeConnection(rows=[('A', date(2024, 1, 2), Decimal(0))], counts=[(1, 1)],
                          aggregates=[('A', 1, Decimal('0e-16384'), 1, 0.0)])
    rejected(conn, 'CUT_AGGREGATE_MISMATCH')


@parametrize('first,second,native', [
    ('1', '-0.999999999999999', 0.0),
    ('1', '-0.999999999999999', -1e-16),
    ('-1', '0.999999999999999', 1e-16),
    ('1', '-1', 1e-16),
])
def test_average_positivity_must_match_even_inside_absolute_tolerance(
        first: str, second: str, native: float) -> None:
    a, b = Decimal(first), Decimal(second)
    with localcontext() as context:
        context.prec = 100
        total = a + b
    expected = math.fsum((float(a), float(b))) / 2
    assert math.isclose(native, expected, rel_tol=1e-12, abs_tol=1e-12)
    assert (native > 0) != (expected > 0)
    conn = FakeConnection(rows=[('A', date(2024, 1, 2), a),
        ('A', date(2024, 1, 3), b)], counts=[(2, 1)], aggregates=[('A', 2, total, 2, native)])
    rejected(conn, 'CUT_NATIVE_AVERAGE_MISMATCH')


def test_row_bound_and_byte_partitioning() -> None:
    start = date(2023, 1, 1)
    rows: list[Row] = []
    # Long but legal keys force splitting below the 400-row codec ceiling.
    for index in range(4):
        key = chr(65 + index) * 160
        rows.extend((key, date.fromordinal(start.toordinal() + i), Decimal('1')) for i in range(400))
    settings: list[Row] = [('repeatable read', 'on', datetime(2024, 6, 1, tzinfo=timezone.utc))]
    conn = FakeConnection(rows=rows, counts=[(1600, 4)], settings=settings, aggregates=[
        (chr(65 + index) * 160, 400, Decimal(400), 20, 1.0) for index in range(4)])
    request = export.ExportRequest('large_cut', start, date.fromordinal(start.toordinal() + 400))
    cut = run(conn, request)
    assert 4 < len(cut.objects) <= reader.MAX_OBJECTS
    restored = tuple(row for obj in cut.objects for row in reader.decode_snapshot(obj.raw).rows)
    assert len(restored) == 1600
    assert all(len(obj.raw) <= reader.MAX_BYTES for obj in cut.objects)
    assert len({obj.candidate.identity for obj in cut.objects}) == len(cut.objects)
    assert run(FakeConnection(rows=rows, counts=[(1600, 4)], settings=settings,
                              aggregates=conn.aggregates), request).objects == cut.objects
    rows.append(('Z', date(2023, 1, 1), Decimal(1)))
    rejected(FakeConnection(rows=rows, counts=[(1600, 4)], settings=settings), 'CUT_ROWS_BOUND', request)


def test_driver_overlong_batch_rejected() -> None:
    rejected(FakeConnection(oversize_batch=True), 'CUT_DRIVER_BATCH_INVALID')


@parametrize('ticks,code', [
    ([0.0, 30.0], 'CUT_TIME_BOUND'), ([0.0, -1.0], 'CUT_CLOCK_INVALID'),
    ([float('inf')], 'CUT_CLOCK_INVALID'), ([0.0, float('nan')], 'CUT_CLOCK_INVALID'),
])
def test_deadline_without_sleep(ticks: list[float], code: str) -> None:
    conn = FakeConnection()
    values = iter(ticks)
    with pytest.raises(export.ExportError, match='^' + code + '$'):
        export.export_daily_volumes(conn, REQUEST, monotonic=lambda: next(values))
    assert conn.events[-1] == 'close'


def test_injected_clock_error_redacted() -> None:
    def bad_clock() -> float:
        raise export.ExportError('private_clock')
    with pytest.raises(export.ExportError, match='^CUT_CLOCK_UNAVAILABLE$'):
        export.export_daily_volumes(FakeConnection(), REQUEST, monotonic=bad_clock)


def test_native_rounding_tolerance_is_narrow() -> None:
    conn = FakeConnection()
    conn.aggregates[0] = ('A', 3, Decimal(60), 2, math.nextafter(25.0, math.inf))
    assert run(conn).averages['A'] == 25.0


def test_conflicting_duplicate_across_fetch_boundaries() -> None:
    start = date(2023, 1, 1)
    rows: list[Row] = [('A', date.fromordinal(start.toordinal() + i), Decimal(1))
                       for i in range(128)]
    rows.append(('A', date.fromordinal(start.toordinal() + 127), Decimal(2)))
    conn = FakeConnection(rows=rows, counts=[(129, 1)])
    rejected(conn, 'CUT_ROW_ORDER_OR_DUPLICATE', replace(REQUEST, start_date=start))


def test_key_and_aggregate_bounds_independent_of_claimed_count() -> None:
    rows: list[Row] = [(f'K{i:03}', date(2024, 1, 2), Decimal(1)) for i in range(129)]
    rejected(FakeConnection(rows=rows, counts=[(129, 128)]), 'CUT_ROWS_BOUND')
    conn = FakeConnection(aggregates=[('A', 1, Decimal(1), 1, 1.0)] * 129)
    rejected(conn, 'CUT_AGGREGATE_BOUND')


def test_object_bound_and_single_object_byte_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force the boundaries without creating large fixture data or filesystem I/O.
    monkeypatch.setattr(reader, 'MAX_ROWS', 1)
    monkeypatch.setattr(reader, 'MAX_OBJECTS', 2)
    rejected(FakeConnection(), 'CUT_OBJECT_BOUND')
    monkeypatch.setattr(reader, 'MAX_BYTES', 1)
    rejected(FakeConnection(), 'CUT_SNAPSHOT_INVALID')


def test_release_time_is_included_in_cooperative_deadline() -> None:
    class SlowRelease(FakeConnection):
        released: bool = False

        def close(self) -> None:
            super().close()
            self.released = True

    conn = SlowRelease()
    with pytest.raises(export.ExportError, match='^CUT_TIME_BOUND$'):
        export.export_daily_volumes(conn, REQUEST,
                                    monotonic=lambda: 30.0 if conn.released else 0.0)
    assert conn.events[-3:] == ['rollback', 'cursor_close', 'close']


def test_repeatable_read_adapter_pins_cut_despite_concurrent_writer() -> None:
    class ConcurrentWriter(FakeConnection):
        original_rows: list[Row] = []
        original_counts: list[Row] = []
        original_aggregates: list[Row] = []
        writer_ran: bool = False

        def set_session(self, *, isolation_level: str, readonly: bool, autocommit: bool) -> None:
            super().set_session(isolation_level=isolation_level, readonly=readonly, autocommit=autocommit)
            self.original_rows = list(self.rows)
            self.original_counts = list(self.counts)
            self.original_aggregates = list(self.aggregates)

        def cursor(self) -> FakeCursor:
            return SnapshotCursor(self)

    class SnapshotCursor(FakeCursor):
        def execute(self, operation: str, parameters: Sequence[object] = ()) -> object:
            assert isinstance(self.owner, ConcurrentWriter)
            result = super().execute(operation, parameters)
            # A writer changes the live source after the count. The adapter's
            # transaction snapshot serves the original rows AND aggregates.
            if operation == export.COUNT_SQL:
                self.owner.rows = [('NEW', date(2024, 1, 2), Decimal(999))]
                self.owner.counts = [(1, 1)]
                self.owner.aggregates = [('NEW', 1, Decimal(999), 1, 999.0)]
                self.owner.writer_ran = True
            elif operation == export.ROWS_SQL:
                self.pending = self.owner.original_rows
            elif operation == export.AGGREGATE_SQL:
                self.pending = self.owner.original_aggregates
            return result

    conn = ConcurrentWriter()
    cut = run(conn)
    assert conn.writer_ran and cut.row_count == 4 and cut.key_count == 2
    assert dict(cut.averages) == {'A': 25.0}
    assert all(row.instrument_key != 'NEW' for obj in cut.objects
               for row in reader.decode_snapshot(obj.raw).rows)


def test_unknown_error_from_driver_value_is_allowlist_redacted() -> None:
    class HostileTimezone(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta | None:
            raise export.ExportError('private_timezone_detail')

        def dst(self, dt: datetime | None) -> timedelta | None:
            return None

        def tzname(self, dt: datetime | None) -> str | None:
            return None

    conn = FakeConnection(settings=[('repeatable read', 'on',
        datetime(2024, 1, 16, tzinfo=HostileTimezone()))])
    with pytest.raises(export.ExportError, match='^CUT_EXPORT_UNAVAILABLE$') as caught:
        run(conn)
    assert 'private_timezone_detail' not in ''.join(traceback.format_exception(caught.value))
    assert conn.events[-3:] == ['rollback', 'cursor_close', 'close']
