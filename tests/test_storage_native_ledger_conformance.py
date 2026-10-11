"""Offline runner boundaries and real serial SQL; never native race certification."""
from __future__ import annotations

from concurrent.futures import Future
from contextlib import contextmanager
import json
import os
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

import storage_native_conformance as sandbox
import storage_native_ledger_conformance as native
from ledger_segments import verify_records


@pytest.mark.parametrize('role', [native.RUNTIME, native.ARCHIVER, sandbox.ROLE])
def test_only_fixed_restricted_profiles(role: str) -> None:
    row = (sandbox.DATABASE, role, 170006, 11, sandbox.MARKER, False, False, False, False, False)
    assert sandbox.validate_profile(row, role=role) == 11
    with pytest.raises(sandbox.ConformanceError):
        sandbox.validate_profile(row, role='postgres')
    with pytest.raises(sandbox.ConformanceError):
        sandbox.validate_profile(row, role='invented')


@pytest.mark.parametrize('role,port', [('postgres', 55432), ('invented', 55432),
                                    (native.RUNTIME, True), (native.RUNTIME, 1)])
def test_disallowed_connection_before_driver(role: str, port: int) -> None:
    with pytest.raises(sandbox.ConformanceError):
        sandbox.connect_fixture(port, role=role)


@pytest.mark.parametrize('args,exit_code', [([], 0), (['--execute'], 2),
    (['--execute', '--confirm-disposable', '--port', '1'], 2)])
def test_preview_and_confirmation_offline(args: list[str], exit_code: int,
                                         monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(sandbox, 'connect_fixture', lambda *a, **k: pytest.fail('network'))
    assert native.main(args) == exit_code
    result = json.loads(capsys.readouterr().out)
    if exit_code == 0:
        assert result == {'status': 'PREVIEW', 'network_calls': 0, 'writes': 0}


def test_failure_diagnostics_never_serialize_exception(monkeypatch: pytest.MonkeyPatch,
                                                    capsys: Any) -> None:
    def fail(_: str) -> None:
        raise RuntimeError('private password/connection/raw SQL')
    monkeypatch.setattr(sandbox, 'connect_fixture', lambda *a, **k: fail(''))
    assert native.main(['--execute', '--confirm-disposable']) == 2
    output = capsys.readouterr().out
    assert 'private' not in output and 'password' not in output
    result = json.loads(output)
    assert result['stage'] == native.CASES[0]
    assert result['passed_cases'] == []
    assert result['global_enforcement_commissioned'] is False


def test_case_failure_preserves_only_completed_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native.Harness, 'identity', lambda _: None)
    def fail(_: Any) -> None:
        raise AssertionError('not public')
    monkeypatch.setattr(native.Harness, 'incomplete', fail)
    with pytest.raises(native.LedgerConformanceError) as caught:
        native.run_native(lambda _: None)
    assert caught.value.stage == native.CASES[1]
    assert caught.value.category == 'ASSERTION'
    assert caught.value.checks == [native.CASES[0]]


def test_diagnostic_identifiers_are_allowlisted() -> None:
    error = native.LedgerConformanceError('private stage', 'private category', ['private', native.CASES[0]])
    assert error.stage == 'IDENTITY_OR_CLEANUP'
    assert error.category == 'REDACTED_EXCEPTION'
    assert error.checks == [native.CASES[0]]


def test_synthetic_originals_match_existing_signature_verifier() -> None:
    first = native.synthetic_event('synthetic-only', 1, '0' * 64)
    second = native.synthetic_event('synthetic-only', 2, str(first['event_hash']))
    assert first == native.synthetic_event('synthetic-only', 1, '0' * 64)
    assert verify_records([first, second], {}, native.KEYRING) == {
        'synthetic-only': (2, second['event_hash'])}


def test_memory_objects_cannot_overwrite_different_bytes() -> None:
    objects = native.MemoryObjects()
    objects.put('catalog-page', 'a' * 64, b'first')
    objects.put('catalog-page', 'a' * 64, b'first')
    with pytest.raises(ValueError, match='CONFLICT'):
        objects.put('catalog-page', 'a' * 64, b'different')
    assert objects.get('catalog-page', 'a' * 64) == b'first'
    assert objects.get('catalog-page', 'b' * 64) is None


class Observer:
    def __init__(self, rows: list[tuple[bool]]) -> None:
        self.rows = rows
        self.rollbacks = 0
    def execute(self, query: str, params: Any) -> Observer:
        assert query == 'SELECT %s = ANY(pg_blocking_pids(%s))'
        assert params == (11, 22)
        return self
    def fetchone(self) -> tuple[bool]:
        return self.rows.pop(0)
    def rollback(self) -> None:
        self.rollbacks += 1


def test_lock_observation_requires_actual_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    observer = Observer([(False,), (True,)])
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    native.wait_blocked(observer, 22, 11, Future())
    assert observer.rollbacks == 2
    finished: Future[Any] = Future()
    finished.set_result('already completed')
    with pytest.raises(AssertionError):
        native.wait_blocked(Observer([(False,)]), 22, 11, finished)
    with pytest.raises(AssertionError):
        native.wait_blocked(Observer([]), 22, 11, Future(), deadline_seconds=0)


def test_connection_rejects_identity_and_closes_before_cases() -> None:
    class Wrong:
        closed = False
        rolled_back = False
        def execute(self, query: str) -> Wrong:
            assert query == sandbox.PROFILE_SQL
            return self
        def fetchone(self) -> None:
            return None
        def rollback(self) -> None:
            self.rolled_back = True
        def close(self) -> None:
            self.closed = True
    connection = Wrong()
    harness = native.Harness(lambda _: connection)
    with pytest.raises(sandbox.ConformanceError):
        with harness.connection(native.RUNTIME):
            pytest.fail('unverified database entered')
    assert connection.closed and connection.rolled_back


def test_race_failure_rolls_back_holder_before_join(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        class Info:
            backend_pid = 11
        info = Info()
        commits = 0
        rollbacks = 0
        cancelled = False
        def commit(self) -> None:
            self.commits += 1
        def rollback(self) -> None:
            self.rollbacks += 1
        def cancel(self) -> None:
            self.cancelled = True
    harness = native.Harness(lambda _: None)
    @contextmanager
    def observer(self: native.Harness, role: str) -> Iterator[Any]:
        yield None
    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError('lock not observed')
    monkeypatch.setattr(native.Harness, 'connection', observer)
    monkeypatch.setattr(native, 'wait_blocked', fail)
    holder, peer = Connection(), Connection()
    with pytest.raises(AssertionError):
        harness.race(holder, peer, lambda: 'finished')
    assert holder.commits == 0 and holder.rollbacks == 1


def test_workflow_uses_actual_migrations_and_no_hosted_inputs() -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = (root / 'sql/storage_native_ledger_fixture_disposable_only.sql').read_text()
    migrations = [line.split('../', 1)[1] for line in fixture.splitlines() if line.startswith('\\ir ')]
    assert len(migrations) == 3
    assert all((root / path).is_file() for path in migrations)
    assert 'shobj_description' in fixture and "current_user <> 'postgres'" in fixture
    workflow = (root / '.github/workflows/storage-native-conformance.yml').read_text()
    assert 'storage_native_ledger_conformance.py --execute --confirm-disposable' in workflow
    assert 'secrets.' not in workflow and 'DATABASE_URL' not in workflow
    assert 'pull_request:' not in workflow and 'push:' not in workflow


@pytest.fixture
def serial_harness(monkeypatch: pytest.MonkeyPatch) -> Iterator[native.Harness]:
    """Run the exact fixture/migrations in WASM, deliberately NOT native identity."""
    if not os.environ.get('EQUITY_TEST_PGLITE_MODULE'):
        pytest.skip('Local SQL harness not configured')
    from test_archive_maintenance_sql import Pg
    factory: Any = Pg
    db: Any = factory()
    root = Path(__file__).resolve().parents[1]
    fixture = (root / 'sql/storage_native_ledger_fixture_disposable_only.sql').read_text()
    # Only the native DB/owner precheck and psql commands are excluded here.
    # This harness cannot certify native identity, locks or concurrency.
    fixture = fixture.split('END $$;', 1)[1]
    scripts: list[str] = []
    pending: list[str] = []
    for line in fixture.splitlines():
        if line.startswith('\\ir '):
            scripts.append('\n'.join(pending))
            pending = []
            scripts.append((root / line.split('../', 1)[1]).read_text())
        else:
            pending.append(line)
    scripts.append('\n'.join(pending))
    try:
        for script in scripts:
            if script.strip():
                db.send({'script': script})
        @contextmanager
        def connection(self: native.Harness, role: str) -> Iterator[Any]:
            class Driver:
                def execute(self, query: str, params: Any = ()) -> Any:
                    return db.execute(query, params)
                def commit(self) -> None:
                    db.execute('COMMIT')
                def rollback(self) -> None:
                    db.execute('ROLLBACK')
            db.execute('SET ROLE ' + role)
            db.execute('BEGIN')  # Match psycopg implicit transaction ownership.
            try:
                yield Driver()
            finally:
                db.execute('ROLLBACK')
                db.execute('RESET ROLE')
        monkeypatch.setattr(native.Harness, 'connection', connection)
        yield native.Harness(lambda _: pytest.fail('native connector called'))
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)


@pytest.mark.parametrize('accepted', [False, True])
def test_real_repository_commit_fault_serial_sql(serial_harness: native.Harness,
                                               accepted: bool) -> None:
    serial_harness.commit_fault(accepted=accepted)


def test_real_signed_archive_and_cold_reader_serial_sql(serial_harness: native.Harness) -> None:
    rows = serial_harness.seed('serial-originals')
    source, publication = serial_harness.proposal('serial-originals')
    assert serial_harness.commit(source, publication) == 'COMMITTED'
    assert serial_harness.commit(source, publication) == 'ALREADY_COMMITTED'
    assert serial_harness.reader.events('serial-originals') == rows
    assert serial_harness.reader.snapshot('serial-originals').terminal is None
    assert serial_harness.reader.audit()['events'] == 2


def test_cold_frontier_append_keeps_original_chain_serial_sql(serial_harness: native.Harness) -> None:
    rows = serial_harness.seed('cold-append')
    source, publication = serial_harness.proposal('cold-append')
    assert serial_harness.commit(source, publication) == 'COMMITTED'
    third = native.synthetic_event('cold-append', 3, str(rows[-1]['event_hash']))
    prepared = serial_harness.reader.prepare_append('cold-append', str(third['idempotency_key']))
    with serial_harness.connection(native.RUNTIME) as connection:
        serial_harness.reader.lock_append(connection, prepared, native.FINGERPRINT)
        native.insert_event(connection, third)
        connection.commit()
    assert serial_harness.reader.events('cold-append') == rows + [third]


def test_missing_cold_object_blocks_before_delete_serial_sql(serial_harness: native.Harness) -> None:
    from ledger_archive_publication import PublicationError
    rows = serial_harness.seed('missing-object')
    source, publication = serial_harness.proposal('missing-object')
    serial_harness.objects.data.pop(('ledger-segment', publication.prepared.segment.sha256))
    with pytest.raises(PublicationError):
        serial_harness.commit(source, publication)
    assert serial_harness.reader.snapshot('missing-object').anchor == publication.previous
    assert serial_harness.reader.events('missing-object') == rows
