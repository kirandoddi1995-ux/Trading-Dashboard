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
    assert row['service'] == '' and row['sslmode'] == 'disable'
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
