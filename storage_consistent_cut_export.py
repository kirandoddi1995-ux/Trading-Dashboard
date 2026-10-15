"""Bounded OFFLINE daily-volume export from one injected PostgreSQL transaction.

No connection creation, credentials, CLI, network, production wiring or file I/O.
The caller supplies an exclusive, idle DB-API connection through the
``set_session``/``get_transaction_status`` adapter seam documented below. Driver
statement, socket and cleanup timeouts must be provisioned by the caller: the
cooperative deadline here cannot interrupt a blocked driver. Only SELECT SQL is
issued. The connection is consumed, rolled back and closed, never committed.

Completeness and native aggregate parity cover ONLY the half-open IST date window
in ExportRequest, not all table history. Missing calendar dates are not inferred.
Existing reader codecs/candidate/declaration contracts are reused. Exact objects
are prepared in memory, not published: the public local publisher accepts ledger
kinds, not daily-volume objects. No custody, signed catalog, deletion authority,
historical PIT, exchange-final volume or global application acceptance is implied.

``known_at`` is the server clock observation evaluated in the first SELECT after
PostgreSQL acquires that statement's repeatable-read snapshot. It is not the
transaction start, a proven MVCC wall-clock instant, or a historical availability
boundary for individual rows. Server wall-clock adjustments are not measured.
Opaque cut_id/revision and exact object bytes identify the declared cut; reader
as_of_at == known_at selects that cut, not historical database state at that time.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Context, Decimal, MAX_EMAX, MIN_EMIN, ROUND_HALF_EVEN, localcontext
import math
import time as clock_time
from types import MappingProxyType
from typing import Protocol

from overnight_storage_contracts import Candidate, ContractError, digest, instant, name
import storage_daily_volume_reader as reader

MAX_SECONDS = 30.0
BATCH_ROWS = 128
MAX_TOTAL_BYTES = reader.MAX_OBJECTS * reader.MAX_BYTES
MIN_NUMERIC_EXPONENT = -16383  # PostgreSQL unconstrained NUMERIC fractional bound.
SUM_PRECISION = 20000
ERROR_CODES = frozenset({
    'CUT_AGGREGATE_BOUND', 'CUT_AGGREGATE_KEYS_MISMATCH', 'CUT_AGGREGATE_MISMATCH',
    'CUT_AUTOCOMMIT_REJECTED', 'CUT_CLOCK_INVALID', 'CUT_CLOCK_UNAVAILABLE',
    'CUT_COUNT_BOUND', 'CUT_COUNT_MISMATCH', 'CUT_DRIVER_BATCH_INVALID',
    'CUT_DRIVER_ROW_INVALID', 'CUT_DRIVER_UNAVAILABLE', 'CUT_EXPORT_UNAVAILABLE',
    'CUT_FUTURE_WINDOW', 'CUT_IDLE_CONNECTION_REQUIRED', 'CUT_NATIVE_AVERAGE_MISMATCH',
    'CUT_OBJECT_BOUND', 'CUT_RELEASE_UNVERIFIED', 'CUT_REQUEST_BOUND', 'CUT_REQUEST_INVALID',
    'CUT_ROW_INVALID', 'CUT_ROW_ORDER_OR_DUPLICATE', 'CUT_ROW_SCHEMA_INVALID', 'CUT_ROWS_BOUND',
    'CUT_SINGLE_RESULT_REQUIRED', 'CUT_SNAPSHOT_INVALID', 'CUT_TIME_BOUND',
    'CUT_TRANSACTION_CLOCK_INVALID', 'CUT_TRANSACTION_SETTINGS_MISMATCH',
})

# All predicates use date parameters, never interpolated names or caller SQL.
# PostgreSQL acquires the statement snapshot before evaluating clock_timestamp().
# A transaction/statement-start timestamp can precede visible concurrent commits.
SETTINGS_SQL = """SELECT current_setting('transaction_isolation'),
    current_setting('transaction_read_only'), clock_timestamp()"""
COUNT_SQL = """SELECT COUNT(*), COUNT(DISTINCT instrument_key)
    FROM quant_app.market_daily_volumes WHERE trade_date >= %s AND trade_date < %s"""
ROWS_SQL = """SELECT instrument_key, trade_date, max_captured_volume
    FROM quant_app.market_daily_volumes WHERE trade_date >= %s AND trade_date < %s
    ORDER BY instrument_key COLLATE "C", trade_date LIMIT %s"""
AGGREGATE_SQL = """SELECT totals.instrument_key, totals.n, totals.total,
    COALESCE(prior.n, 0), prior.average
    FROM (
        SELECT instrument_key, COUNT(*) AS n, SUM(max_captured_volume) AS total
        FROM quant_app.market_daily_volumes
        WHERE trade_date >= %s AND trade_date < %s GROUP BY instrument_key
    ) AS totals LEFT JOIN (
        SELECT instrument_key, COUNT(*) AS n, AVG(day_volume) AS average
        FROM (
            SELECT instrument_key, max_captured_volume::double precision AS day_volume,
                ROW_NUMBER() OVER (PARTITION BY instrument_key ORDER BY trade_date DESC) AS rn
            FROM quant_app.market_daily_volumes
            WHERE trade_date >= %s AND trade_date < %s AND trade_date < %s
        ) AS ranked WHERE rn <= %s GROUP BY instrument_key
    ) AS prior ON totals.instrument_key = prior.instrument_key
    ORDER BY totals.instrument_key COLLATE "C" LIMIT %s"""


class ExportError(ValueError):
    """Stable path/data-free errors; caller exceptions are never propagated."""


class Cursor(Protocol):
    def execute(self, operation: str, parameters: Sequence[object] = ()) -> object: ...
    def fetchmany(self, size: int) -> Sequence[Sequence[object]]: ...
    def close(self) -> None: ...


class Connection(Protocol):
    """Dedicated DB-API adapter; status is a plain int and 0 means idle.

    A psycopg3 adapter returns int(connection.info.transaction_status) and maps
    set_session to isolation_level=IsolationLevel.REPEATABLE_READ, read_only=True
    and autocommit=False while idle. A psycopg2 handle exposes these methods
    directly. No driver import or production adapter is provided here. Both must
    keep the first SELECT's snapshot throughout all counts, rows and aggregates.
    """

    @property
    def autocommit(self) -> bool: ...
    def get_transaction_status(self) -> int: ...
    def set_session(self, *, isolation_level: str, readonly: bool,
                    autocommit: bool) -> None: ...
    def cursor(self) -> Cursor: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ExportRequest:
    cut_id: str
    start_date: date
    end_date: date
    revision: int = 1
    lookback: int = 20
    max_seconds: float = MAX_SECONDS


@dataclass(frozen=True)
class ExportObject:
    candidate: Candidate
    raw: bytes = field(repr=False)


@dataclass(frozen=True)
class ConsistentCut:
    """Prepared bytes with a server observation timestamp, not historical PIT.

    known_at is observed after snapshot acquisition, not the snapshot's exact
    visibility instant. declaration() retains the reader's unsigned declared-cut
    schema: its time labels this opaque cut and does not attest temporal MVCC
    equivalence or database availability at that wall-clock instant.
    """

    request: ExportRequest
    known_at: datetime
    objects: tuple[ExportObject, ...]
    row_count: int
    key_count: int
    averages: Mapping[str, float]
    complete_window_export_verified: bool = True
    native_window_aggregate_verified: bool = True
    physical_custody_verified: bool = False
    deletion_authority: bool = False
    global_wired: bool = False
    historical_pit_verified: bool = False
    snapshot_visibility_timestamp_exact: bool = False

    def declaration(self) -> dict[str, object]:
        return reader.cut_declaration(
            self.request.cut_id, self.known_at, tuple(obj.candidate for obj in self.objects))


def _request(request: ExportRequest) -> None:
    if type(request) is not ExportRequest:
        raise ExportError('CUT_REQUEST_INVALID')
    name(request.cut_id)
    if (len(request.cut_id) > 55 or type(request.start_date) is not date
            or type(request.end_date) is not date
            or not 1 <= (request.end_date - request.start_date).days <= reader.MAX_LOOKBACK
            or type(request.revision) is not int or not 1 <= request.revision <= 2**31 - 1
            or type(request.lookback) is not int or not 1 <= request.lookback <= reader.MAX_LOOKBACK
            or type(request.max_seconds) not in (int, float)
            or not math.isfinite(request.max_seconds)
            or not 0 < request.max_seconds <= MAX_SECONDS):
        raise ExportError('CUT_REQUEST_BOUND')


def _batch(cursor: Cursor, size: int) -> Sequence[Sequence[object]]:
    batch = cursor.fetchmany(size)
    if type(batch) not in (list, tuple) or len(batch) > size:
        raise ExportError('CUT_DRIVER_BATCH_INVALID')
    if any(type(row) not in (tuple, list) for row in batch):
        raise ExportError('CUT_DRIVER_ROW_INVALID')
    return batch


def _single(cursor: Cursor, columns: int) -> Sequence[object]:
    rows = _batch(cursor, 2)
    if len(rows) != 1 or len(rows[0]) != columns:
        raise ExportError('CUT_SINGLE_RESULT_REQUIRED')
    if _batch(cursor, 1):
        raise ExportError('CUT_SINGLE_RESULT_REQUIRED')
    return rows[0]


def _count(value: object, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ExportError('CUT_COUNT_BOUND')
    return value


def _numeric_scale_valid(value: Decimal) -> bool:
    """Reject nonfinite/native-impossible scale without caller-context arithmetic."""
    exponent = value.as_tuple().exponent
    return value.is_finite() and type(exponent) is int and exponent >= MIN_NUMERIC_EXPONENT


def _objects(request: ExportRequest, known: datetime,
             rows: tuple[reader.DailyVolumeRow, ...]) -> tuple[ExportObject, ...]:
    lower = datetime.combine(request.start_date, time(), reader.IST).astimezone(timezone.utc)
    upper = datetime.combine(request.end_date, time(), reader.IST).astimezone(timezone.utc)
    pending = [rows[i:i + reader.MAX_ROWS] for i in range(0, len(rows), reader.MAX_ROWS)] or [()]
    result: list[ExportObject] = []
    total_bytes = 0
    while pending:
        part = pending.pop(0)
        snapshot = reader.DailyVolumeSnapshot(f'{request.cut_id}_p{len(result):02d}',
                                             request.revision, lower, upper, known, part)
        try:
            raw = reader.encode_snapshot(snapshot)
        except ContractError as error:
            if str(error) != 'DAILY_VOLUME_BYTES_BOUND' or len(part) <= 1:
                raise ExportError('CUT_SNAPSHOT_INVALID') from None
            midpoint = len(part) // 2
            pending[0:0] = [part[:midpoint], part[midpoint:]]
            continue
        total_bytes += len(raw)
        if len(result) >= reader.MAX_OBJECTS or total_bytes > MAX_TOTAL_BYTES:
            raise ExportError('CUT_OBJECT_BOUND')
        candidate = Candidate(reader.SOURCE, snapshot.snapshot, request.revision,
                              lower, upper, digest(raw), len(raw), reader.restore_witness(raw))
        result.append(ExportObject(candidate, raw))
    return tuple(result)


def _aggregate(cursor: Cursor, request: ExportRequest, known: datetime,
               rows: tuple[reader.DailyVolumeRow, ...], check_time: Callable[[], None]) -> Mapping[str, float]:
    grouped: dict[str, list[reader.DailyVolumeRow]] = {}
    for row in rows:
        grouped.setdefault(row.instrument_key, []).append(row)
    cutoff = known.astimezone(reader.IST).date()
    cursor.execute(AGGREGATE_SQL, (request.start_date, request.end_date,
        request.start_date, request.end_date, cutoff, request.lookback, reader.MAX_KEYS + 1))
    aggregates: list[Sequence[object]] = []
    while True:
        check_time()
        batch = _batch(cursor, min(BATCH_ROWS, reader.MAX_KEYS + 1 - len(aggregates)))
        if not batch:
            break
        aggregates.extend(batch)
        if len(aggregates) > reader.MAX_KEYS:
            raise ExportError('CUT_AGGREGATE_BOUND')
    if len(aggregates) != len(grouped):
        raise ExportError('CUT_AGGREGATE_KEYS_MISMATCH')
    averages: dict[str, float] = {}
    for key, aggregate in zip(sorted(grouped), aggregates, strict=True):
        if len(aggregate) != 5 or type(aggregate[0]) is not str or aggregate[0] != key:
            raise ExportError('CUT_AGGREGATE_KEYS_MISMATCH')
        _, count, total, prior_count, average = aggregate
        items = grouped[key]
        selected = [item for item in reversed(items) if item.trade_date < cutoff][:request.lookback]
        # Mixed scales can yield an 81+ digit sum even with 64-character rows.
        # 20000 digits cover the PostgreSQL fractional bound plus the 1e18 row
        # magnitude and 1600-row carry. Specify EVERY context setting, flags and
        # traps: neither caller context nor mutable DefaultContext is inherited.
        with localcontext(Context(prec=SUM_PRECISION, rounding=ROUND_HALF_EVEN,
                Emin=MIN_EMIN, Emax=MAX_EMAX, capitals=1, clamp=0, flags=[], traps=[])):
            expected_total = sum((item.max_captured_volume for item in items), Decimal(0))
        if (_count(count, reader.MAX_TOTAL_ROWS) != len(items)
                or type(total) is not Decimal or not _numeric_scale_valid(total) or total != expected_total
                or _count(prior_count, reader.MAX_LOOKBACK) != len(selected)):
            raise ExportError('CUT_AGGREGATE_MISMATCH')
        if not selected:
            if average is not None:
                raise ExportError('CUT_AGGREGATE_MISMATCH')
            continue
        expected = math.fsum(float(item.max_captured_volume) for item in selected) / len(selected)
        # Native PostgreSQL float8 AVG may sum in a different order from fsum.
        # Permit only rounding at 1e-12 relative/absolute; no NULL/NaN fallback.
        if (type(average) is not float or not math.isfinite(average)
                or (average > 0) != (expected > 0)
                or not math.isclose(average, expected, rel_tol=1e-12, abs_tol=1e-12)):
            raise ExportError('CUT_NATIVE_AVERAGE_MISMATCH')
        if expected > 0:
            averages[key] = expected
    return MappingProxyType(averages)


def export_daily_volumes(connection: Connection, request: ExportRequest, *,
                         monotonic: Callable[[], float] = clock_time.monotonic) -> ConsistentCut:
    """Consume an injected handle; return only after rollback and both closes succeed.

    Invalid/nonidle/initially-autocommit handles are closed without issuing SQL
    or claiming ownership of a transaction. Cleanup attempts rollback and both
    closes even when a callback raises BaseException. Interrupts are re-raised
    after all release attempts (the original body interrupt takes precedence).
    These attempts do not claim an interrupted rollback undid anything. Unknown
    Exception errors, including driver-raised ExportError, are redacted. No
    callback runs after verification to reread source rows.
    """
    cursor: Cursor | None = None
    transaction_owned = False
    outcome: ConsistentCut | None = None
    failure: str | None = None
    interruption: BaseException | None = None
    # Separate driver exceptions from our own stable validation errors.
    def driver(callback: Callable[[], object]) -> object:
        try:
            return callback()
        except Exception:
            raise ExportError('CUT_DRIVER_UNAVAILABLE') from None

    try:
        _request(request)
        def tick() -> float:
            try:
                return monotonic()
            except Exception:
                raise ExportError('CUT_CLOCK_UNAVAILABLE') from None
        started = tick()
        if type(started) not in (int, float) or not math.isfinite(started):
            raise ExportError('CUT_CLOCK_INVALID')
        def check_time() -> None:
            now = tick()
            if (type(now) not in (int, float) or not math.isfinite(now) or now < started):
                raise ExportError('CUT_CLOCK_INVALID')
            if now - started >= request.max_seconds:
                raise ExportError('CUT_TIME_BOUND')
        status = driver(connection.get_transaction_status)
        if type(status) is not int or status != 0:
            raise ExportError('CUT_IDLE_CONNECTION_REQUIRED')
        if driver(lambda: connection.autocommit) is not False:
            raise ExportError('CUT_AUTOCOMMIT_REJECTED')
        transaction_owned = True
        driver(lambda: connection.set_session(isolation_level='REPEATABLE READ',
                                              readonly=True, autocommit=False))
        if driver(lambda: connection.autocommit) is not False:
            raise ExportError('CUT_AUTOCOMMIT_REJECTED')
        try:
            cursor = _SafeCursor(connection.cursor())
        except Exception:
            raise ExportError('CUT_DRIVER_UNAVAILABLE') from None
        check_time()
        cursor.execute(SETTINGS_SQL)
        isolation, readonly, observed_at = _single(cursor, 3)
        if (type(isolation) is not str or type(readonly) is not str
                or isolation != 'repeatable read' or readonly != 'on'):
            raise ExportError('CUT_TRANSACTION_SETTINGS_MISMATCH')
        if type(observed_at) is not datetime:
            raise ExportError('CUT_TRANSACTION_CLOCK_INVALID')
        known = instant(observed_at)
        upper = datetime.combine(request.end_date, time(), reader.IST).astimezone(timezone.utc)
        if upper > known:
            raise ExportError('CUT_FUTURE_WINDOW')
        check_time()
        cursor.execute(COUNT_SQL, (request.start_date, request.end_date))
        row_count, key_count = _single(cursor, 2)
        expected_count = _count(row_count, reader.MAX_TOTAL_ROWS)
        expected_keys = _count(key_count, reader.MAX_KEYS)
        check_time()
        cursor.execute(ROWS_SQL, (request.start_date, request.end_date, reader.MAX_TOTAL_ROWS + 1))
        rows: list[reader.DailyVolumeRow] = []
        identities: set[str] = set()
        previous: tuple[str, date] | None = None
        while True:
            check_time()
            batch = _batch(cursor, min(BATCH_ROWS, reader.MAX_TOTAL_ROWS + 1 - len(rows)))
            if not batch:
                break
            for values in batch:
                if len(values) != 3:
                    raise ExportError('CUT_ROW_SCHEMA_INVALID')
                key, day, volume = values
                if (type(key) is not str or not 1 <= len(key) <= 160
                        or type(day) is not date or type(volume) is not Decimal
                        or not _numeric_scale_valid(volume) or len(str(volume)) > 64
                        or volume.copy_abs() > reader.MAX_VOLUME
                        or not request.start_date <= day < request.end_date):
                    raise ExportError('CUT_ROW_INVALID')
                identity = (key, day)
                if previous is not None and identity <= previous:
                    raise ExportError('CUT_ROW_ORDER_OR_DUPLICATE')
                previous = identity
                identities.add(key)
                rows.append(reader.DailyVolumeRow(key, day, volume))
                if len(rows) > reader.MAX_TOTAL_ROWS or len(identities) > reader.MAX_KEYS:
                    raise ExportError('CUT_ROWS_BOUND')
        if len(rows) != expected_count or len(identities) != expected_keys:
            raise ExportError('CUT_COUNT_MISMATCH')
        objects = _objects(request, known, tuple(rows))
        check_time()
        averages = _aggregate(cursor, request, known, tuple(rows), check_time)
        check_time()
        outcome = ConsistentCut(request, known, objects, expected_count, expected_keys, averages)
    except ExportError as error:
        failure = str(error)
    except Exception:
        failure = 'CUT_EXPORT_UNAVAILABLE'
    except BaseException as error:
        interruption = error
    finally:
        releases: list[Callable[[], None]] = []
        if transaction_owned:
            releases.append(lambda: connection.rollback())
        if cursor is not None:
            releases.append(cursor.close)
        releases.append(lambda: connection.close())
        release_errors: list[Exception] = []
        release_interrupts: list[BaseException] = []
        for release in releases:
            try:
                release()
            except Exception as error:
                release_errors.append(error)
            except BaseException as error:
                release_interrupts.append(error)
        if interruption is None and release_interrupts:
            interruption = release_interrupts[0]
        if release_errors or release_interrupts:
            failure = 'CUT_RELEASE_UNVERIFIED'
        elif outcome is not None and failure is None and interruption is None:
            try:
                check_time()
            except ExportError as error:
                failure = str(error)
            except Exception:
                failure = 'CUT_CLOCK_UNAVAILABLE'
    if interruption is not None:
        raise interruption from None
    if failure is not None:
        # A hostile adapter value can execute Python during validation. Never
        # trust arbitrary ExportError text, even outside the driver wrappers.
        raise ExportError(failure if failure in ERROR_CODES else 'CUT_EXPORT_UNAVAILABLE') from None
    if outcome is None:
        raise ExportError('CUT_EXPORT_UNAVAILABLE')
    return outcome


@dataclass
class _SafeCursor:
    """Redact injected driver errors even if they imitate our exception classes."""

    wrapped: Cursor

    def execute(self, operation: str, parameters: Sequence[object] = ()) -> object:
        try:
            return self.wrapped.execute(operation, parameters)
        except Exception:
            raise ExportError('CUT_DRIVER_UNAVAILABLE') from None

    def fetchmany(self, size: int) -> Sequence[Sequence[object]]:
        try:
            return self.wrapped.fetchmany(size)
        except Exception:
            raise ExportError('CUT_DRIVER_UNAVAILABLE') from None

    def close(self) -> None:
        self.wrapped.close()
