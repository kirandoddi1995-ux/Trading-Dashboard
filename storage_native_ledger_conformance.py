"""Synthetic native ledger/archive acceptance; fixed disposable service only.

Uses the actual reviewed SQL, archive repository, publication and cold reader.
In-memory objects are NOT independent backup custody. Lost COMMIT replies are
explicit fault injection, not a claim to test arbitrary network failures.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import time
from typing import Any
import uuid

from evidence_ledger import canonical_json
from ledger_archive_publication import PublishedLedger, publish
from ledger_archive_repository import ArchiveTransactionError, LedgerArchiveRepository
from ledger_read_contract import Connection, Kind
from ledger_runtime_reader import LedgerRuntimeReader
from ledger_segments import FIELDS
from ledger_source_capture import SourceCapture
import storage_native_conformance as sandbox

RUNTIME = 'quant_app_runtime'
ARCHIVER = 'quant_storage_archiver'
FINGERPRINT = 'f' * 64
EVENT_KEY = b'public-synthetic-event-key-only!!'
SEAL_KEY = b'public-synthetic-segment-key-only'
RECEIPT_KEY = b'public-synthetic-receipt-key-only'
KEYRING = {'fixture': EVENT_KEY}
RECEIPTS = {'fixture': RECEIPT_KEY}
NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)
CASES = (
    'restricted_native_identity_and_empty_fixture',
    'incomplete_archive_rolls_back_source_root_and_head',
    'relations_root_compare_and_swap_serializes',
    'append_before_archive_preserves_new_hot_tail',
    'archive_before_append_rejects_stale_proof',
    'competing_archivers_commit_one_generation',
    'lost_commit_reply_reconciles_without_second_delete',
    'failed_commit_before_acceptance_rolls_back',
)


class LedgerConformanceError(ValueError):
    """Only fixed stage/category/case identifiers may reach the public log."""

    def __init__(self, stage: str, category: str, checks: list[str]) -> None:
        super().__init__('NATIVE_LEDGER_CONFORMANCE_FAILED')
        self.stage = stage if stage in CASES else 'IDENTITY_OR_CLEANUP'
        self.category = category if category in sandbox.CATEGORIES else 'REDACTED_EXCEPTION'
        self.checks = [name for name in checks if name in CASES]


def require(condition: bool) -> None:
    """A failed assertion cannot become an apparent native pass."""
    if condition is not True:
        raise AssertionError('SYNTHETIC_CASE_ASSERTION')


class MemoryObjects:
    """Immutable synthetic objects only; no Drive, credentials or durable custody."""

    def __init__(self) -> None:
        self.data: dict[tuple[Kind, str], bytes] = {}

    def put(self, kind: Kind, digest: str, data: bytes) -> None:
        if (kind, digest) in self.data and self.data[kind, digest] != data:
            raise ValueError('SYNTHETIC_OBJECT_CONFLICT')
        self.data[kind, digest] = data

    def get(self, kind: Kind, digest: str) -> bytes | None:
        return self.data.get((kind, digest))


def synthetic_event(aggregate: str, sequence: int, previous: str) -> dict[str, object]:
    """Deterministic signed synthetic event; never market/research evidence."""
    row: dict[str, object] = dict(zip(FIELDS, (
        str(uuid.uuid5(uuid.NAMESPACE_URL, f'disposable-ledger/{aggregate}/{sequence}')),
        aggregate, sequence, 'SYNTHETIC', NOW.isoformat(), NOW.isoformat(),
        'disposable-conformance', 'fixture', f'{aggregate}/{sequence}',
        {'synthetic': True, 'ordinal': sequence}, previous, '', 'HMAC-SHA256', 2, 'fixture')))
    material = {name: value for name, value in row.items() if name not in ('payload', 'event_hash')}
    material['payload_json'] = canonical_json(row['payload'])  # type: ignore[arg-type]
    row['event_hash'] = hmac.new(EVENT_KEY, canonical_json(material).encode(), hashlib.sha256).hexdigest()
    return row


def insert_event(connection: Connection, row: dict[str, object]) -> None:
    """Insert one synthetic original through the reviewed SQL head trigger."""
    values = [row[name] for name in FIELDS]
    values[9] = json.dumps(values[9])
    connection.execute('INSERT INTO quant_app.evidence_ledger_events (' + ','.join(FIELDS)
                       + ') VALUES (' + ','.join(['%s'] * len(FIELDS)) + ')', values)


def wait_blocked(observer: Any, waiter: int, holder: int, future: Future[Any],
                 *, deadline_seconds: float = 1.5) -> None:
    """Observe a real backend lock dependency, not a timing-only sleep race."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        row = observer.execute('SELECT %s = ANY(pg_blocking_pids(%s))', (holder, waiter)).fetchone()
        observer.rollback()
        if row == (True,):
            return
        require(not future.done())
        time.sleep(0.01)
    raise AssertionError('SYNTHETIC_LOCK_DEPENDENCY_NOT_OBSERVED')


class Harness:
    """Fresh restricted connections; no owner identity or connection discovery."""

    def __init__(self, connect: Callable[[str], Any]) -> None:
        self.connect = connect
        self.objects = MemoryObjects()
        self.reader = LedgerRuntimeReader(lambda: self.connection(RUNTIME), self.objects,
                                          KEYRING, SEAL_KEY, RECEIPTS)

    @contextmanager
    def connection(self, role: str) -> Iterator[Any]:
        connection = self.connect(role)
        try:
            sandbox.validate_profile(connection.execute(sandbox.PROFILE_SQL).fetchone(), role=role)
            connection.rollback()
            yield connection
        finally:
            try:
                connection.rollback()
            finally:
                connection.close()

    def seed(self, aggregate: str) -> list[dict[str, object]]:
        """Two original events with independently verified signatures and heads."""
        rows = [synthetic_event(aggregate, 1, '0' * 64)]
        rows.append(synthetic_event(aggregate, 2, str(rows[0]['event_hash'])))
        for row in rows:
            prepared = self.reader.prepare_append(aggregate, str(row['idempotency_key']))
            with self.connection(RUNTIME) as connection:
                self.reader.lock_append(connection, prepared, FINGERPRINT)
                insert_event(connection, row)
                connection.commit()
        require(self.reader.events(aggregate) == rows)
        return rows

    def proposal(self, aggregate: str) -> tuple[SourceCapture, PublishedLedger]:
        """Publish verified originals outside every archive SQL transaction."""
        snapshot = self.reader.snapshot(aggregate)
        source = SourceCapture(snapshot.native_rows)
        publication = publish(source.records(), snapshot.anchor, self.objects,
                              KEYRING, SEAL_KEY, RECEIPTS, 'fixture', NOW)
        return source, publication

    def commit(self, source: SourceCapture, publication: PublishedLedger) -> str:
        return LedgerArchiveRepository(lambda: self.connection(ARCHIVER)).commit(
            source, publication, self.objects, KEYRING, SEAL_KEY, RECEIPTS, FINGERPRINT)

    def archive_locked(self, connection: Any, source: SourceCapture,
                       publication: PublishedLedger) -> None:
        """Hold the real repository transaction at its pre-COMMIT boundary."""
        connection.execute('BEGIN')
        require(LedgerArchiveRepository._commit(connection, source, source.records(),
                                                publication, FINGERPRINT) == 'COMMITTED')

    def race(self, holder: Any, peer: Any, operation: Callable[[], Any]) -> Any:
        """Bound the waiter, observe PostgreSQL blocking, then commit the holder.

        On failure the holder rolls back before joining. The actual repository's
        two-second lock timeout bounds the peer even if a dependency is missed.
        """
        with self.connection(RUNTIME) as observer:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(operation)
                try:
                    wait_blocked(observer, peer.info.backend_pid, holder.info.backend_pid, future)
                    holder.commit()
                    return future.result(timeout=5)
                finally:
                    holder.rollback()
                    # Driver cancellation is bounded by the SQL statement/lock limits.
                    if not future.done():
                        peer.cancel()

    def identity(self) -> None:
        with self.connection(RUNTIME) as runtime, self.connection(ARCHIVER) as archiver:
            require(runtime.info.backend_pid != archiver.info.backend_pid)
            require(runtime.execute('SELECT count(*) FROM quant_app.evidence_ledger_events').fetchone() == (0,))
            require(runtime.execute('SELECT count(*) FROM quant_storage.ledger_hot_heads').fetchone() == (0,))
            require(runtime.execute('SELECT array_agg(generation ORDER BY scope) FROM quant_storage.catalog_roots').fetchone() == ([0, 0],))
            require(runtime.execute("SELECT heads_enabled,pruning_enabled,reader_fingerprint FROM quant_storage.ledger_control").fetchone() == (True, True, FINGERPRINT))
            for connection, role in ((runtime, RUNTIME), (archiver, ARCHIVER)):
                privileges = connection.execute("SELECT has_table_privilege(%s,'quant_storage.ledger_hot_heads','UPDATE'),has_table_privilege(%s,'quant_app.evidence_ledger_events','UPDATE')", (role, role)).fetchone()
                require(privileges == (False, False))

    def incomplete(self) -> None:
        rows = self.seed('incomplete')
        source, publication = self.proposal('incomplete')
        with self.connection(ARCHIVER) as connection:
            connection.execute("SET LOCAL TimeZone='UTC'")
            LedgerArchiveRepository._stage(connection, source.records(), source, publication, FINGERPRINT)
            connection.execute('DELETE FROM quant_app.evidence_ledger_events WHERE event_id=%s', (rows[0]['event_id'],))
            try:
                connection.execute('SET CONSTRAINTS ALL IMMEDIATE')
            except Exception as error:
                require(getattr(error, 'sqlstate', None) == 'P0001')
                connection.rollback()
            else:
                raise AssertionError('INCOMPLETE_ARCHIVE_ACCEPTED')
        require(self.reader.snapshot('incomplete').anchor == publication.previous)
        require(self.reader.events('incomplete') == rows)

    def root_cas(self) -> None:
        sql = """UPDATE quant_storage.catalog_roots SET generation=1,root=repeat('a',64),
          receipt_sha256=repeat('b',64),previous_root=root,previous_receipt=receipt_sha256,
          segment=repeat('c',64),key_id='fixture',published_at=%s
          WHERE scope='relations' AND generation=0 RETURNING generation"""
        with self.connection(ARCHIVER) as holder, self.connection(ARCHIVER) as peer:
            require(holder.execute(sql, (NOW,)).fetchone() == (1,))
            peer.execute("SET LOCAL statement_timeout='5s'")
            result = self.race(holder, peer, lambda: peer.execute(sql, (NOW,)).fetchone())
            require(result is None)
            peer.rollback()

    def append_first(self) -> None:
        rows = self.seed('append-first')
        source, publication = self.proposal('append-first')
        third = synthetic_event('append-first', 3, str(rows[-1]['event_hash']))
        prepared = self.reader.prepare_append('append-first', str(third['idempotency_key']))
        with self.connection(RUNTIME) as holder, self.connection(ARCHIVER) as peer:
            self.reader.lock_append(holder, prepared, FINGERPRINT)
            insert_event(holder, third)
            @contextmanager
            def borrowed() -> Iterator[Any]:
                yield peer
            repository = LedgerArchiveRepository(borrowed)
            result = self.race(holder, peer, lambda: repository.commit(source, publication,
                self.objects, KEYRING, SEAL_KEY, RECEIPTS, FINGERPRINT))
            require(result == 'COMMITTED')
        require(self.reader.events('append-first') == rows + [third])
        require(self.reader.snapshot('append-first').terminal == (3, third['event_hash']))

    def archive_first(self) -> None:
        rows = self.seed('archive-first')
        source, publication = self.proposal('archive-first')
        third = synthetic_event('archive-first', 3, str(rows[-1]['event_hash']))
        prepared = self.reader.prepare_append('archive-first', str(third['idempotency_key']))
        with self.connection(ARCHIVER) as holder, self.connection(RUNTIME) as peer:
            self.archive_locked(holder, source, publication)
            def stale_append() -> str:
                try:
                    self.reader.lock_append(peer, prepared, FINGERPRINT)
                except Exception as error:
                    from ledger_runtime_reader import append_error
                    code = str(append_error(error))
                    peer.rollback()
                    return code
                raise AssertionError('STALE_APPEND_ACCEPTED')
            require(self.race(holder, peer, stale_append) == 'STORAGE_APPEND_ROOT_CHANGED')
        require(self.reader.events('archive-first') == rows)
        require(self.reader.snapshot('archive-first').terminal is None)
        refreshed = self.reader.prepare_append('archive-first', str(third['idempotency_key']))
        with self.connection(RUNTIME) as connection:
            self.reader.lock_append(connection, refreshed, FINGERPRINT)
            insert_event(connection, third)
            connection.commit()
        require(self.reader.events('archive-first') == rows + [third])

    def competing_archivers(self) -> None:
        rows = self.seed('competing')
        source, publication = self.proposal('competing')
        with self.connection(ARCHIVER) as holder, self.connection(ARCHIVER) as peer:
            self.archive_locked(holder, source, publication)
            @contextmanager
            def borrowed() -> Iterator[Any]:
                yield peer
            repository = LedgerArchiveRepository(borrowed)
            result = self.race(holder, peer, lambda: repository.commit(source, publication,
                self.objects, KEYRING, SEAL_KEY, RECEIPTS, FINGERPRINT))
            require(result == 'ALREADY_COMMITTED')
        require(self.reader.snapshot('competing').anchor == publication.receipt.anchor)
        require(self.reader.events('competing') == rows)

    def commit_fault(self, *, accepted: bool) -> None:
        aggregate = 'lost-reply' if accepted else 'pre-commit-failure'
        rows = self.seed(aggregate)
        source, publication = self.proposal(aggregate)
        @contextmanager
        def fault_connection() -> Iterator[Any]:
            with self.connection(ARCHIVER) as connection:
                class Fault:
                    def execute(self, query: str, params: Any = ()) -> Any:
                        return connection.execute(query, params)
                    def rollback(self) -> None:
                        connection.rollback()
                    def commit(self) -> None:
                        if accepted:
                            connection.commit()
                        raise RuntimeError('SYNTHETIC_LOST_REPLY')
                yield Fault()
        try:
            LedgerArchiveRepository(fault_connection).commit(source, publication,
                self.objects, KEYRING, SEAL_KEY, RECEIPTS, FINGERPRINT)
        except ArchiveTransactionError as error:
            require(str(error) == 'ARCHIVE_TRANSACTION_FAILED')
        else:
            raise AssertionError('FAULT_REPORTED_AS_SUCCESS')
        actual = self.reader.snapshot(aggregate)
        require(actual.anchor == (publication.receipt.anchor if accepted else publication.previous))
        require(len(actual.native_rows) == (0 if accepted else 2))
        require(self.reader.events(aggregate) == rows)
        require(self.commit(source, publication) == ('ALREADY_COMMITTED' if accepted else 'COMMITTED'))
        require(self.reader.events(aggregate) == rows)


def run_native(connect: Callable[[str], Any]) -> dict[str, object]:
    """Report only completed cases; no raw SQL/exception/payload in output."""
    harness = Harness(connect)
    checks: list[str] = []
    operations = (harness.identity, harness.incomplete, harness.root_cas,
                  harness.append_first, harness.archive_first, harness.competing_archivers,
                  lambda: harness.commit_fault(accepted=True),
                  lambda: harness.commit_fault(accepted=False))
    for name, operation in zip(CASES, operations):
        try:
            operation()
        except Exception as error:
            category = 'ASSERTION' if isinstance(error, AssertionError) else sandbox._category(error)
            raise LedgerConformanceError(name, category, checks) from None
        checks.append(name)
    return {'status': 'NATIVE_LEDGER_CASES_PASSED', 'checks': checks,
            'native_cases_executed': len(checks), 'hosted_changes': 0,
            'tested_archive_transactions_verified': True,
            'ledger_archive_races_verified': False, 'global_enforcement_commissioned': False,
            'independent_custody_verified': False, 'immutable_operational_receipts_verified': False,
            'fencing_takeover_verified': False, 'approval_authority': False}


def main(argv: list[str] | None = None) -> int:
    """No driver import/connection in default preview or unconfirmed execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--confirm-disposable', action='store_true')
    parser.add_argument('--port', type=int, default=55432)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({'status': 'PREVIEW', 'network_calls': 0, 'writes': 0}))
        return 0
    if args.confirm_disposable is not True or not 1024 <= args.port <= 65535:
        print(json.dumps({'status': 'BLOCKED', 'code': 'DISPOSABLE_CONFIRMATION_REQUIRED'}))
        return 2
    try:
        result = run_native(lambda role: sandbox.connect_fixture(args.port, role=role))
    except Exception as error:
        failure = error if isinstance(error, LedgerConformanceError) else None
        print(json.dumps({'status': 'BLOCKED', 'code': 'NATIVE_LEDGER_CONFORMANCE_FAILED',
            'stage': failure.stage if failure else 'IDENTITY_OR_CLEANUP',
            'error_category': failure.category if failure else 'REDACTED_EXCEPTION',
            'passed_cases': failure.checks if failure else [], 'hosted_changes': 0,
            'global_enforcement_commissioned': False, 'approval_authority': False}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
