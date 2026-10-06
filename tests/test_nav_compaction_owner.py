"""Offline failure-path checks for explicit owner NAV maintenance."""
from pathlib import Path
from typing import Any
import getpass
import json

import psycopg
import pytest

import nav_compaction_owner as owner


class Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    def fetchone(self) -> Any:
        return self.value


class Connection:
    autocommit = True

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.values: dict[str, Any] = {
            owner.DATA_SQL: (9424, 9424, owner.EXPECTED_DATA),
            owner.SCHEMA_SQL: (owner.EXPECTED_SCHEMA,),
            owner.SIZE_SQL: (493951797, 42237952),
            owner.BLOCKERS_SQL: (0, 0, 0, 0, 0),
        }
        self.role = ('postgres', 'off')
        self.fail_after = False

    def execute(self, query: str) -> Result:
        self.calls.append(query)
        if self.fail_after and owner.VACUUM_SQL in self.calls and query == owner.DATA_SQL:
            raise RuntimeError('private driver error')
        if query.startswith('SELECT current_user'):
            return Result(self.role)
        return Result(self.values.get(query))


def test_success_exactly_one_rewrite_with_private_receipts(tmp_path: Path) -> None:
    conn = Connection()
    result = owner.compact(conn, tmp_path, 1_000_000_000)
    assert result['status'] == 'NAV_COMPACTION_VERIFIED'
    assert not result['collector_capacity_floor_met']
    assert not result['approval_authority']
    assert conn.calls.count(owner.VACUUM_SQL) == 1
    assert (tmp_path / 'before.json').is_file()
    assert (tmp_path / 'after.json').is_file()
    assert not any('read_only=off' in query for query in conn.calls)


@pytest.mark.parametrize('query,value', [
    (owner.DATA_SQL, (9423, 9423, owner.EXPECTED_DATA)),
    (owner.DATA_SQL, (9424, 9424, 'changed')),
    (owner.SCHEMA_SQL, ('changed',)),
    (owner.SIZE_SQL, (True, 42237952)),
    (owner.BLOCKERS_SQL, (0, 1, 0, 0, 0)),
    (owner.BLOCKERS_SQL, (False, 0, 0, 0, 0)),
])
def test_invariant_failure_never_rewrites(tmp_path: Path, query: str, value: Any) -> None:
    conn = Connection()
    conn.values[query] = value
    with pytest.raises(owner.MaintenanceBlocked):
        owner.compact(conn, tmp_path, 1_000_000_000)
    assert owner.VACUUM_SQL not in conn.calls


@pytest.mark.parametrize('role', [('postgres', 'on'), ('quant_app_runtime', 'off')])
def test_wrong_session_is_blocked(tmp_path: Path, role: tuple[str, str]) -> None:
    conn = Connection()
    conn.role = role
    with pytest.raises(owner.MaintenanceBlocked):
        owner.compact(conn, tmp_path, 1_000_000_000)
    assert owner.VACUUM_SQL not in conn.calls


@pytest.mark.parametrize('capacity', [0, -1, True, 424951807])
def test_physical_capacity_bound(tmp_path: Path, capacity: int) -> None:
    conn = Connection()
    with pytest.raises(owner.MaintenanceBlocked):
        owner.compact(conn, tmp_path, capacity)
    assert owner.VACUUM_SQL not in conn.calls


def test_existing_receipt_stops_before_rewrite(tmp_path: Path) -> None:
    (tmp_path / 'before.json').touch()
    conn = Connection()
    with pytest.raises(FileExistsError):
        owner.compact(conn, tmp_path, 1_000_000_000)
    assert owner.VACUUM_SQL not in conn.calls


def test_post_failure_preserves_before_and_never_retries(tmp_path: Path) -> None:
    conn = Connection()
    conn.fail_after = True
    with pytest.raises(RuntimeError):
        owner.compact(conn, tmp_path, 1_000_000_000)
    assert conn.calls.count(owner.VACUUM_SQL) == 1
    assert (tmp_path / 'before.json').is_file()
    assert not (tmp_path / 'after.json').exists()


def test_default_preview_never_connects(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail('offline preview accessed credentials/network')
    monkeypatch.setattr(psycopg, 'connect', forbidden)
    monkeypatch.setattr(getpass, 'getpass', forbidden)
    assert owner.main([]) == 0
    assert '"network_calls": 0' in capsys.readouterr().out


def test_missing_confirmations_fail_closed(capsys: Any) -> None:
    assert owner.main(['--compact']) == 2
    assert 'CHECK_PRIVATELY_DO_NOT_RETRY' in capsys.readouterr().out


def test_non_autocommit_blocked(tmp_path: Path) -> None:
    conn = Connection()
    conn.autocommit = False
    with pytest.raises(owner.MaintenanceBlocked):
        owner.compact(conn, tmp_path, 1_000_000_000)
    assert not conn.calls


@pytest.mark.parametrize('connection_fails', [False, True])
def test_confirmed_cli_uses_one_tls_session_without_secret_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any, connection_fails: bool,
) -> None:
    monkeypatch.setattr(owner, 'ROOT', tmp_path / 'repo')
    ca = tmp_path / 'ca.pem'
    ca.touch()
    receipts = tmp_path / 'private-receipts'
    monkeypatch.setattr(owner, 'bounded_read', lambda path: b'{}')
    monkeypatch.setattr(owner, 'rehearse', lambda *args: {'status': 'NAV_OFFLINE_RESTORE_VERIFIED'})
    secret = 'never-print-private-owner-url'
    monkeypatch.setattr(getpass, 'getpass', lambda prompt: secret)
    connections: list[dict[str, Any]] = []

    class Session(Connection):
        def __enter__(self) -> 'Session':
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    session = Session()

    def connect(url: str, **kwargs: Any) -> Session:
        assert url == secret
        assert (receipts / 'restore-proof.json').is_file()
        connections.append(kwargs)
        if connection_fails:
            raise RuntimeError(secret)
        return session

    monkeypatch.setattr(psycopg, 'connect', connect)
    code = owner.main([
        '--compact', '--confirm-writers-quiesced', '--acknowledge-transient-quota-risk',
        '--physical-free-bytes', '1000000000', '--data', str(tmp_path / 'data'),
        '--manifest', str(tmp_path / 'manifest'), '--pglite-module', str(tmp_path / 'pg'),
        '--ca-file', str(ca), '--receipt-dir', str(receipts),
    ])
    output = capsys.readouterr().out
    assert secret not in output
    assert code == (2 if connection_fails else 0)
    assert len(connections) == 1
    assert connections[0]['sslmode'] == 'verify-full'
    assert connections[0]['autocommit'] is True
    assert connections[0]['options'] == '-c timezone=UTC -c statement_timeout=120000 -c lock_timeout=5000'
    assert session.calls.count(owner.VACUUM_SQL) == (0 if connection_fails else 1)
    assert secret not in json.dumps([p.read_text() for p in receipts.iterdir()])
