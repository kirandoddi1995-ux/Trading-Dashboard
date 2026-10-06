"""Offline failure-path checks for explicit owner NAV maintenance."""
from pathlib import Path
from typing import Any
import getpass
import json
import os
import subprocess
from decimal import Decimal

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
    result = json.loads(capsys.readouterr().out)
    assert result['code'] == 'OWNER_MAINTENANCE_CONFIRMATIONS_REQUIRED'
    assert result['rewrite_outcome'] == 'NOT_ATTEMPTED'
    assert result['network_calls'] == 0


def test_non_autocommit_blocked(tmp_path: Path) -> None:
    conn = Connection()
    conn.autocommit = False
    with pytest.raises(owner.MaintenanceBlocked):
        owner.compact(conn, tmp_path, 1_000_000_000)
    assert not conn.calls


@pytest.mark.parametrize('connection_fails,maintenance_fails', [(False, False), (True, False), (False, True)])
def test_confirmed_cli_uses_one_tls_session_without_secret_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any,
    connection_fails: bool, maintenance_fails: bool,
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
    session.fail_after = maintenance_fails

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
    assert code == (2 if connection_fails or maintenance_fails else 0)
    if connection_fails:
        assert json.loads(output)['rewrite_outcome'] == 'NOT_ATTEMPTED'
        assert json.loads(output)['phase'] == 'CONNECTING'
    if maintenance_fails:
        assert json.loads(output)['rewrite_outcome'] == 'CHECK_PRIVATELY_DO_NOT_RETRY'
        assert json.loads(output)['phase'] == 'MAINTENANCE'
        assert (receipts / 'before.json').is_file()
        assert not (receipts / 'after.json').exists()
    assert len(connections) == 1
    assert connections[0]['sslmode'] == 'verify-full'
    assert connections[0]['autocommit'] is True
    assert connections[0]['options'] == '-c timezone=UTC -c statement_timeout=120000 -c lock_timeout=5000'
    assert session.calls.count(owner.VACUUM_SQL) == (0 if connection_fails else 1)
    assert secret not in json.dumps([p.read_text() for p in receipts.iterdir()])


@pytest.mark.parametrize('location', ['existing_empty', 'existing_nonempty', 'inside_repo'])
def test_receipt_directory_block_is_local_and_specific(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any, location: str,
) -> None:
    root = tmp_path / 'repo'
    monkeypatch.setattr(owner, 'ROOT', root)
    ca = tmp_path / 'ca.pem'
    ca.touch()
    receipts = root / 'receipts' if location == 'inside_repo' else tmp_path / 'private-receipts'
    if location != 'inside_repo':
        receipts.mkdir()
    if location == 'existing_nonempty':
        (receipts / 'before.json').write_text('preserve me')

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail('local directory failure reached backup, credentials or network')

    monkeypatch.setattr(owner, 'rehearse', forbidden)
    monkeypatch.setattr(owner, 'bounded_read', forbidden)
    monkeypatch.setattr(getpass, 'getpass', forbidden)
    monkeypatch.setattr(psycopg, 'connect', forbidden)
    assert owner.main([
        '--compact', '--confirm-writers-quiesced', '--acknowledge-transient-quota-risk',
        '--physical-free-bytes', '1000000000', '--data', str(tmp_path / 'data'),
        '--manifest', str(tmp_path / 'manifest'), '--pglite-module', str(tmp_path / 'pg'),
        '--ca-file', str(ca), '--receipt-dir', str(receipts),
    ]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['code'] == 'NEW_PRIVATE_RECEIPT_DIRECTORY_REQUIRED'
    assert result['phase'] == 'LOCAL_PREFLIGHT'
    assert result['rewrite_outcome'] == 'NOT_ATTEMPTED'
    assert result['network_calls'] == result['hosted_changes'] == 0
    if location == 'existing_nonempty':
        assert (receipts / 'before.json').read_text() == 'preserve me'


def test_numeric_driver_value_reproduces_old_size_rejection(tmp_path: Path) -> None:
    conn = Connection()
    conn.values[owner.SIZE_SQL] = (Decimal('493951797'), 42237952)
    with pytest.raises(owner.MaintenanceBlocked, match='NAV_SIZE_INVARIANT_FAILED'):
        owner.compact(conn, tmp_path, 1_000_000_000)
    assert owner.VACUUM_SQL not in conn.calls
    assert not (tmp_path / 'before.json').exists()


@pytest.mark.parametrize('broken', [None, 'data', 'schema', 'size', 'blockers'])
def test_connected_check_rolls_back_and_never_rewrites(broken: str | None) -> None:
    conn = Connection()
    if broken:
        query = {'data': owner.DATA_SQL, 'schema': owner.SCHEMA_SQL,
                 'size': owner.SIZE_SQL, 'blockers': owner.BLOCKERS_SQL}[broken]
        conn.values[query] = None
        with pytest.raises(owner.MaintenanceBlocked):
            owner.check_only(conn)
    else:
        result = owner.check_only(conn)
        assert result['status'] == 'NAV_CONNECTED_CHECK_PASSED'
        assert result['hosted_changes'] == 0
        assert result['rewrite_outcome'] == 'NOT_ATTEMPTED'
    assert conn.calls[0] == 'BEGIN READ ONLY'
    assert conn.calls[-1] == 'ROLLBACK'
    assert owner.VACUUM_SQL not in conn.calls


@pytest.mark.parametrize('broken', [None, 'owner', 'data', 'schema', 'size', 'blockers'])
def test_check_only_cli_needs_no_backup_or_receipt_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any, broken: str | None,
) -> None:
    ca = tmp_path / 'ca.pem'
    ca.touch()

    class Session(Connection):
        def __enter__(self) -> 'Session':
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    conn = Session()
    if broken == 'owner':
        conn.role = ('quant_app_runtime', 'off')
    elif broken:
        query = {'data': owner.DATA_SQL, 'schema': owner.SCHEMA_SQL,
                 'size': owner.SIZE_SQL, 'blockers': owner.BLOCKERS_SQL}[broken]
        conn.values[query] = None
    monkeypatch.setattr(getpass, 'getpass', lambda prompt: 'private-owner-url')
    monkeypatch.setattr(psycopg, 'connect', lambda *args, **kwargs: conn)
    assert owner.main(['--check-only', '--ca-file', str(ca)]) == (2 if broken else 0)
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == ('BLOCKED' if broken else 'NAV_CONNECTED_CHECK_PASSED')
    assert result['rewrite_outcome'] == 'NOT_ATTEMPTED'
    if broken:
        assert result['phase'] == 'CONNECTED_CHECK'
        assert result['code'] != 'NAV_MAINTENANCE_STOP_INSPECT_RECEIPTS'
    assert owner.VACUUM_SQL not in conn.calls
    assert conn.calls[0] == 'BEGIN READ ONLY'
    assert conn.calls[-1] == 'ROLLBACK'
    assert list(tmp_path.iterdir()) == [ca]


@pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'), reason='Local SQL harness not configured')
def test_actual_postgres_size_query_and_psycopg_loaders() -> None:
    from psycopg.types.numeric import IntLoader, NumericLoader
    module = os.environ['EQUITY_TEST_PGLITE_MODULE']
    script = r"""
    const {PGlite}=require(process.argv[1]);
    (async()=>{const db=new PGlite();try{
      await db.exec('CREATE SCHEMA quant_app; CREATE TABLE quant_app.mf_nav(x text)');
      const types=await db.query('SELECT pg_typeof(sum(n))::text AS old_type, pg_typeof(sum(n)::bigint)::text AS new_type FROM (VALUES(493951797::bigint))t(n)');
      const size=await db.query(JSON.parse(process.argv[2]));
      process.stdout.write(JSON.stringify({types:types.rows[0],fields:size.fields,rows:size.rows}));
    }finally{await db.close();}})().catch(()=>{process.exitCode=1;});
    """
    process = subprocess.run(['node', '-e', script, module, json.dumps(owner.SIZE_SQL)],
                             capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(process.stdout)
    assert result['types'] == {'old_type': 'numeric', 'new_type': 'bigint'}
    assert [field['dataTypeID'] for field in result['fields']] == [20, 20]
    assert type(NumericLoader(1700).load(b'493951797')) is Decimal
    for field in result['fields']:
        value = IntLoader(20).load(str(result['rows'][0][field['name']]).encode())
        assert type(value) is int
