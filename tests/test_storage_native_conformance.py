"""Offline test doubles only; these are NOT native Postgres acceptance."""
from __future__ import annotations

from contextlib import contextmanager
import json
from typing import Any, Iterator

import pytest

import storage_native_conformance as native
from test_storage_write_guard import FakeConnection, FakeCursor, Lock


class DuplicateError(Exception):
    sqlstate = '23505'


def profile(pid: int = 100) -> tuple[object, ...]:
    return (native.DATABASE, native.ROLE, 170006, pid, native.MARKER,
            False, False, False, False, False)


@pytest.mark.parametrize('index,value', [
    (0, 'postgres'), (1, 'postgres'), (2, 160006), (2, 180000),
    (2, True), (3, 0), (3, True), (4, None), (5, True),
    (6, True), (7, True), (8, True), (9, True), (9, None),
])
def test_sandbox_and_native_identity_fail_closed(index: int, value: object) -> None:
    row = list(profile())
    row[index] = value
    with pytest.raises(native.ConformanceError, match='IDENTITY_UNVERIFIED'):
        native.validate_profile(row)


@pytest.mark.parametrize('row', [None, (), profile()[:-1]])
def test_missing_profile_blocks(row: object) -> None:
    with pytest.raises(native.ConformanceError):
        native.validate_profile(row)


def test_valid_profile() -> None:
    assert native.validate_profile(profile()) == 100


def test_preview_never_connects(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(native, 'connect_fixture', lambda _: pytest.fail('connection opened'))
    assert native.main([]) == 0
    assert json.loads(capsys.readouterr().out) == dict(status='PREVIEW', network_calls=0, writes=0)


@pytest.mark.parametrize('args', [
    ['--execute'], ['--execute', '--confirm-disposable', '--port', '0'],
    ['--execute', '--confirm-disposable', '--port', '65536'],
])
def test_confirmation_and_port_before_network(args: list[str], monkeypatch: pytest.MonkeyPatch,
                                            capsys: Any) -> None:
    monkeypatch.setattr(native, 'connect_fixture', lambda _: pytest.fail('connection opened'))
    assert native.main(args) == 2
    assert json.loads(capsys.readouterr().out)['code'] == 'DISPOSABLE_CONFIRMATION_REQUIRED'


def test_connect_failure_redacted(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    def fail(_: int) -> None:
        raise RuntimeError('private connection text')
    monkeypatch.setattr(native, 'connect_fixture', fail)
    assert native.main(['--execute', '--confirm-disposable']) == 2
    output = capsys.readouterr().out
    assert 'private' not in output and 'NATIVE_CONFORMANCE_FAILED' in output


def test_fixture_explicit_connection_parameters_no_environment_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg
    for name in ('PGSERVICE', 'PGSERVICEFILE', 'PGSYSCONFDIR'):
        monkeypatch.delenv(name, raising=False)
    seen: list[dict[str, Any]] = []
    sentinel = object()
    def connect(**kwargs: Any) -> object:
        seen.append(kwargs)
        return sentinel
    monkeypatch.setattr(psycopg, 'connect', connect)
    monkeypatch.setenv('DATABASE_URL', 'synthetic-forbidden-environment')
    assert native.connect_fixture(55432) is sentinel
    row = seen[0]
    assert row['host'] == row['hostaddr'] == '127.0.0.1'
    assert row['dbname'] == native.DATABASE and row['user'] == native.ROLE
    assert 'service' not in row and row['sslmode'] == 'disable'
    assert row['password'] == native.FIXTURE_PASSWORD and row['port'] == 55432


class Connection(FakeConnection):
    def __init__(self, shared: set[int], lock: Lock, pid: int) -> None:
        super().__init__(size=30_000_000, growth=0, lock=lock)
        self.shared, self.pid = shared, pid
        self.pending_rows: set[int] = set()
        self.closed = False

    @contextmanager
    def cursor(self) -> Iterator[Cursor]:
        yield Cursor(self)

    def commit(self) -> None:
        self.shared.update(self.pending_rows)
        self.pending_rows.clear()
        super().commit()

    def rollback(self) -> None:
        self.pending_rows.clear()
        super().rollback()

    def close(self) -> None:
        self.closed = True


class Cursor(FakeCursor):
    def execute(self, query: str) -> None:
        conn = self.connection
        assert isinstance(conn, Connection)
        if query == native.PROFILE_SQL:
            self.result = profile(conn.pid)
        elif query.startswith('INSERT INTO public.guard_probe VALUES('):
            number = int(query.split('VALUES(')[1].split(')')[0])
            if number in conn.shared:
                raise DuplicateError('synthetic duplicate SQL exception')
            conn.pending_rows.add(number)
            self.result = (number,)
        elif query == 'SELECT count(*) FROM public.guard_probe':
            self.result = (len(conn.shared),)
        elif query.startswith('SELECT count(*) FROM public.guard_probe WHERE id='):
            number = int(query.split('id=')[1])
            self.result = (int(number in conn.shared),)
        elif query.startswith('SELECT id FROM public.guard_probe WHERE id='):
            number = int(query.split('id=')[1])
            self.result = (number,) if number in conn.shared else None
        else:
            super().execute(query)


def test_runner_control_flow_on_fake_not_native(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native, '_clock', lambda: __import__('test_storage_write_guard').NOW)
    shared: set[int] = set()
    lock = Lock()
    connections = [Connection(shared, lock, 100), Connection(shared, lock, 101)]
    iterator = iter(connections)
    report = native.run_native(lambda: next(iterator))
    assert report['native_cases_executed'] == 6
    assert report['global_enforcement_commissioned'] is False
    assert report['ledger_archive_races_verified'] is False
    assert shared == {1, 2, 3, 5, 6}
    assert all(conn.closed for conn in connections)


def test_nonempty_fixture_refused_and_connections_closed() -> None:
    lock = Lock()
    connections = [Connection({1}, lock, 100), Connection({1}, lock, 101)]
    iterator = iter(connections)
    with pytest.raises(native.ConformanceError, match='NATIVE_CONFORMANCE_FAILED'):
        native.run_native(lambda: next(iterator))
    assert all(conn.closed for conn in connections)


def test_workflow_no_secrets_no_schedule_no_production_trigger() -> None:
    from pathlib import Path
    body = (Path(__file__).resolve().parents[1] / '.github/workflows/storage-native-conformance.yml').read_text()
    assert 'secrets.' not in body and 'DATABASE_URL' not in body
    assert 'schedule:' not in body and 'push:' not in body and 'pull_request:' not in body
    assert 'inputs.confirm_disposable == true' in body
    assert 'contents: read' in body and 'storage_conformance_sandbox' in body


def test_shared_database_comment_catalog() -> None:
    from pathlib import Path
    assert 'shobj_description(' in native.PROFILE_SQL
    assert '\n    obj_description(' not in native.PROFILE_SQL
    fixture = (Path(__file__).resolve().parents[1] /
               'sql/storage_native_fixture_disposable_only.sql').read_text()
    assert f"COMMENT ON DATABASE {native.DATABASE} IS '{native.MARKER}'" in fixture


def test_actual_shared_comment_lookup_in_offline_sql_engine() -> None:
    """Actual catalog semantics, NOT native backend/lock acceptance."""
    import os
    import subprocess
    module = os.environ.get('EQUITY_TEST_PGLITE_MODULE')
    if not module:
        pytest.skip('Local SQL harness not configured')
    script = """
const {PGlite}=require(process.argv[1]);
(async()=>{const db=new PGlite(); await db.waitReady;
 await db.exec("COMMENT ON DATABASE template1 IS 'disposable-storage-guard-v1'");
 const old=await db.query("SELECT obj_description(oid,'pg_database') AS marker FROM pg_database WHERE datname=current_database()");
 const corrected=await db.query(process.argv[2],[],{rowMode:'array'});
 console.log(JSON.stringify({old:old.rows[0].marker,corrected:corrected.rows[0][4]}));
 await db.close();})().catch(()=>{process.exitCode=1;});
"""
    result = subprocess.run(['node', '-e', script, module, native.PROFILE_SQL],
                            capture_output=True, text=True, timeout=35, check=False)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {'old': None, 'corrected': native.MARKER}


@pytest.mark.parametrize('name', ['PGSERVICE', 'PGSERVICEFILE', 'PGSYSCONFDIR'])
@pytest.mark.parametrize('value', ['', 'synthetic-private-service'])
def test_service_environment_refused_before_driver(name: str, value: str,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    import psycopg
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(psycopg, 'connect', lambda **_: pytest.fail('driver called'))
    with pytest.raises(native.ConformanceError) as caught:
        native.connect_fixture(55432)
    assert caught.value.category == 'SERVICE_ENVIRONMENT'


@pytest.mark.parametrize('state,category', [
    ('28P01', 'AUTHENTICATION'), ('42501', 'PERMISSION'),
    ('42P01', 'FIXTURE_TABLE_MISSING'), ('42883', 'DATABASE_FUNCTION_MISSING'),
    ('23505', 'UNIQUE_CONSTRAINT'), ('57014', 'QUERY_CANCELLED'),
    ('08001', 'CONNECTION'), ('08006', 'CONNECTION'),
    ('private-token', 'REDACTED_EXCEPTION'), (None, 'REDACTED_EXCEPTION'),
])
def test_allowlisted_error_categories(state: object, category: str) -> None:
    error = RuntimeError('private-message')
    error.sqlstate = state  # type: ignore[attr-defined]
    assert native._category(error) == category


@pytest.mark.parametrize('connection_number', [1, 2])
def test_connection_stage_and_cleanup(connection_number: int,
                                      monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    first = Connection(set(), Lock(), 100)
    calls = 0
    def connect(_: int) -> Connection:
        nonlocal calls
        calls += 1
        if calls == connection_number:
            raise RuntimeError('private connection string')
        return first
    monkeypatch.setattr(native, 'connect_fixture', connect)
    assert native.main(['--execute', '--confirm-disposable']) == 2
    output = capsys.readouterr().out
    assert 'private' not in output
    report = json.loads(output)
    assert report['stage'] == ('CONNECT_FIRST' if connection_number == 1 else 'CONNECT_SECOND')
    assert report['passed_cases'] == []
    assert report['error_category'] == 'REDACTED_EXCEPTION'
    assert calls == connection_number
    assert first.closed is (connection_number == 2)


@pytest.mark.parametrize('failure_stage', [
    'VERIFY_FIRST_PROFILE', 'VERIFY_SECOND_PROFILE', 'VERIFY_EMPTY_FIXTURE',
    'COMMITTED_APPEND', 'CONCURRENT_WRITER', 'BODY_ROLLBACK', 'CALLER_COMMIT',
    'CONSTRAINT_ROLLBACK',
])
def test_case_diagnostics_and_no_false_pass(failure_stage: str,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native, '_clock', lambda: __import__('test_storage_write_guard').NOW)
    shared: set[int] = set()
    lock = Lock()
    connections = [Connection(shared, lock, 100), Connection(shared, lock, 101)]
    original = native._query
    profiles = 0
    targets = {'VERIFY_EMPTY_FIXTURE': 'SELECT count(*) FROM public.guard_probe',
               'COMMITTED_APPEND': 'INSERT INTO public.guard_probe VALUES(1)',
               'CONCURRENT_WRITER': 'INSERT INTO public.guard_probe VALUES(2)',
               'BODY_ROLLBACK': 'INSERT INTO public.guard_probe VALUES(4)',
               'CALLER_COMMIT': 'INSERT INTO public.guard_probe VALUES(6)',
               'CONSTRAINT_ROLLBACK': 'SELECT count(*) FROM public.guard_probe WHERE id=1'}
    def query(connection: Any, sql: str) -> Any:
        nonlocal profiles
        if sql == native.PROFILE_SQL:
            profiles += 1
            if failure_stage == ('VERIFY_FIRST_PROFILE' if profiles == 1 else 'VERIFY_SECOND_PROFILE'):
                raise DuplicateError('private query text')
        if failure_stage in targets and sql.startswith(targets[failure_stage]):
            raise DuplicateError('private query text')
        return original(connection, sql)
    monkeypatch.setattr(native, '_query', query)
    iterator = iter(connections)
    with pytest.raises(native.ConformanceError) as caught:
        native.run_native(lambda: next(iterator))
    assert caught.value.stage == failure_stage
    assert caught.value.category == 'UNIQUE_CONSTRAINT'
    assert all(connection.closed for connection in connections)


def test_diagnostic_payload_does_not_accept_free_text() -> None:
    error = native.ConformanceError('private-message', stage='private-stage',
                                    category='private-category', checks=('private-query',))
    assert error.stage == 'UNEXPECTED'
    assert native._category(error) == 'REDACTED_EXCEPTION'
    assert error.checks == ()


@pytest.mark.parametrize('number', [0, 1])
def test_cleanup_failure_is_blocked_not_passed(number: int,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native, '_clock', lambda: __import__('test_storage_write_guard').NOW)
    shared: set[int] = set()
    lock = Lock()
    connections = [Connection(shared, lock, 100), Connection(shared, lock, 101)]
    def close() -> None:
        connections[number].closed = True
        raise RuntimeError('private cleanup text')
    monkeypatch.setattr(connections[number], 'close', close)
    iterator = iter(connections)
    with pytest.raises(native.ConformanceError) as caught:
        native.run_native(lambda: next(iterator))
    assert caught.value.stage == ('CLOSE_FIRST' if number == 0 else 'CLOSE_SECOND')
    assert len(caught.value.checks) == 6
    assert all(connection.closed for connection in connections)
