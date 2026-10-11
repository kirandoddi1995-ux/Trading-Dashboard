"""Offline exact-codec and serial SQL checks. Not native concurrency proof."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterator

import pytest

import operational_receipt_writer as writer
from operational_receipt_history import FORMAT, receipt_history
import storage_native_operational_conformance as native
import storage_native_conformance as sandbox


@pytest.mark.parametrize('kind', ['checkpoint', 'run'])
def test_original_codec_interoperability(kind: str) -> None:
    prepared = native.intent('synthetic', kind=kind)
    data = json.dumps({'format': FORMAT, 'receipts': [json.loads(prepared.receipt)]}).encode()
    with receipt_history(data, independently_expected_sha256=hashlib.sha256(data).hexdigest(),
                         keyring={'fixture': native.KEY}) as proof:
        method = proof.checkpoint if kind == 'checkpoint' else proof.run
        args = ('synthetic', 'SYNTHETIC', 1) if kind == 'checkpoint' else ('synthetic', 1)
        assert method(*args).request == json.loads(prepared.request)


class NoConnection:
    def execute(self, *args: Any) -> Any:
        pytest.fail('invalid input reached SQL')


@pytest.mark.parametrize('fence,seconds', [(True, 60), (-1, 60), (2**63, 60),
                                        (0, True), (0, 0), (0, 301)])
def test_invalid_claim_before_sql(fence: int, seconds: int) -> None:
    with pytest.raises(ValueError):
        writer.claim(NoConnection(), 'run', 'owner', expected_fence=fence, lease_seconds=seconds)


@pytest.mark.parametrize('owner', ['', 'a' * 901, None])
def test_invalid_owner_before_sql(owner: Any) -> None:
    with pytest.raises(ValueError):
        writer.apply(NoConnection(), owner, native.intent('run'))


def test_forged_prepared_identity_rejected() -> None:
    with pytest.raises(ValueError):
        writer.apply(NoConnection(), 'owner', replace(native.intent('run'), fence=2))


@pytest.fixture
def sql_db() -> Iterator[Any]:
    if not os.environ.get('EQUITY_TEST_PGLITE_MODULE'):
        pytest.skip('Local SQL harness not configured')
    from test_archive_maintenance_sql import Pg
    factory: Any = Pg
    db: Any = factory()
    root = Path(__file__).resolve().parents[1]
    try:
        db.send({'script': 'CREATE ROLE quant_app_runtime NOINHERIT NOSUPERUSER NOBYPASSRLS;'})
        db.send({'script': (root / 'sql/operational_receipts_review_only.sql').read_text()})
        yield db
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)


@contextmanager
def restricted(db: Any) -> Iterator[Any]:
    db.execute('SET ROLE quant_app_runtime')
    db.execute('BEGIN')
    try:
        yield db
    finally:
        db.execute('ROLLBACK')
        db.execute('RESET ROLE')


def enable(db: Any) -> None:
    db.execute('UPDATE quant_operational_receipts.control SET enabled=true')


def test_sql_default_disabled(sql_db: Any) -> None:
    with restricted(sql_db) as connection, pytest.raises(Exception, match='NOT_COMMISSIONED'):
        writer.claim(connection, 'run', 'owner', expected_fence=0)


@pytest.mark.parametrize('method', ['claim', 'apply'])
def test_sql_missing_control_fails_closed(sql_db: Any, method: str) -> None:
    sql_db.execute('DELETE FROM quant_operational_receipts.control')
    with restricted(sql_db) as connection, pytest.raises(Exception, match='NOT_COMMISSIONED'):
        if method == 'claim':
            writer.claim(connection, 'run', 'owner', expected_fence=0)
        else:
            writer.apply(connection, 'owner', native.intent('run'))


def test_sql_atomic_original_and_conflict(sql_db: Any) -> None:
    enable(sql_db)
    prepared = native.intent('run')
    with restricted(sql_db) as connection:
        assert writer.claim(connection, 'run', 'owner', expected_fence=0) == 1
        assert writer.apply(connection, 'owner', prepared) == 'NEW'
        assert writer.apply(connection, 'owner', prepared) == 'IDEMPOTENT'
        connection.execute('COMMIT')
    with restricted(sql_db) as connection:
        assert writer.original(connection, prepared) == prepared.receipt
        with pytest.raises(Exception, match='CONFLICT'):
            writer.apply(connection, 'owner', native.intent('run', value=2))
    assert sql_db.execute('SELECT count(*) FROM quant_operational_receipts.current_operations').fetchone() == (1,)


def test_sql_rollback_both(sql_db: Any) -> None:
    enable(sql_db)
    with restricted(sql_db) as connection:
        writer.claim(connection, 'run', 'owner', expected_fence=0)
        writer.apply(connection, 'owner', native.intent('run'))
    for name in ('leases', 'receipts', 'current_operations'):
        assert sql_db.execute('SELECT count(*) FROM quant_operational_receipts.' + name).fetchone() == (0,)


@pytest.mark.parametrize('kind', ['checkpoint', 'run'])
def test_sql_takeover_preserves_old_receipt(sql_db: Any, kind: str) -> None:
    enable(sql_db)
    first = native.intent('run', kind=kind)
    with restricted(sql_db) as connection:
        writer.claim(connection, 'run', 'old', expected_fence=0)
        writer.apply(connection, 'old', first)
        connection.execute('COMMIT')
    sql_db.execute("UPDATE quant_operational_receipts.leases SET expires_at='2000-01-01Z'")
    with restricted(sql_db) as connection:
        assert writer.claim(connection, 'run', 'new', expected_fence=1) == 2
        writer.apply(connection, 'new', native.intent('run', 2, kind=kind))
        connection.execute('COMMIT')
    with restricted(sql_db) as connection:
        assert writer.original(connection, first) == first.receipt
        with pytest.raises(Exception, match='STALE_OR_EXPIRED'):
            writer.apply(connection, 'old', first)


def test_sql_unexpired_takeover_blocked(sql_db: Any) -> None:
    enable(sql_db)
    with restricted(sql_db) as connection:
        writer.claim(connection, 'run', 'old', expected_fence=0)
        connection.execute('COMMIT')
    with restricted(sql_db) as connection, pytest.raises(Exception, match='TAKEOVER_BLOCKED'):
        writer.claim(connection, 'run', 'new', expected_fence=1)


@pytest.mark.parametrize('statement', ['UPDATE quant_operational_receipts.receipts SET request_text=\'{}\'',
    'DELETE FROM quant_operational_receipts.receipts', 'TRUNCATE quant_operational_receipts.receipts',
    'UPDATE quant_operational_receipts.control SET enabled=true',
    'UPDATE quant_operational_receipts.leases SET fence=2'])
def test_sql_direct_runtime_writes_denied(sql_db: Any, statement: str) -> None:
    with restricted(sql_db) as connection, pytest.raises(Exception, match='permission denied'):
        connection.execute(statement)


def test_sql_owner_cannot_accidentally_mutate_original(sql_db: Any) -> None:
    enable(sql_db)
    with restricted(sql_db) as connection:
        writer.claim(connection, 'run', 'owner', expected_fence=0)
        writer.apply(connection, 'owner', native.intent('run'))
        connection.execute('COMMIT')
    with pytest.raises(Exception, match='IMMUTABLE'):
        sql_db.execute("UPDATE quant_operational_receipts.receipts SET request_text='{}'")


@pytest.mark.parametrize('args,exit_code', [([], 0), (['--execute'], 2),
    (['--execute', '--confirm-disposable', '--port', '1'], 2)])
def test_preview_never_connects(args: list[str], exit_code: int,
                               monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    monkeypatch.setattr(sandbox, 'connect_fixture', lambda *a, **k: pytest.fail('network'))
    assert native.main(args) == exit_code
    assert 'password' not in capsys.readouterr().out


def test_native_failure_redacted(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError('private credential and connection string')
    monkeypatch.setattr(sandbox, 'connect_fixture', fail)
    assert native.main(['--execute', '--confirm-disposable']) == 2
    output = capsys.readouterr().out
    assert 'private' not in output and 'credential' not in output
    result = json.loads(output)
    assert result['case'] == native.CASES[0] and result['passed_cases'] == []


def test_workflow_inactive_review_sql_and_manual_only() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / '.github/workflows/storage-native-conformance.yml').read_text()
    assert 'storage_native_operational_conformance.py --execute --confirm-disposable' in workflow
    assert 'secrets.' not in workflow and 'push:' not in workflow and 'pull_request:' not in workflow
    fixture = (root / 'sql/storage_native_operational_fixture_disposable_only.sql').read_text()
    assert 'shobj_description' in fixture and '\\ir operational_receipts_review_only.sql' in fixture


@pytest.mark.parametrize('fence', [0, -1, 2**63, True])
def test_invalid_intent_fence(fence: int) -> None:
    with pytest.raises(ValueError):
        native.intent('run', fence)


@pytest.mark.parametrize('field,value', [('signature', 'not-a-signature'), ('kind', 'run'),
    ('format', 'unknown'), ('key_id', None), ('request', {})])
def test_sql_receipt_binding_rejects_malformed(sql_db: Any, field: str, value: Any) -> None:
    enable(sql_db)
    prepared = native.intent('run')
    row = json.loads(prepared.receipt)
    row[field] = value
    bad = replace(prepared, receipt=json.dumps(row))
    with restricted(sql_db) as connection:
        writer.claim(connection, 'run', 'owner', expected_fence=0)
        with pytest.raises(Exception, match='BINDING_INVALID'):
            writer.apply(connection, 'owner', bad)
    assert sql_db.execute('SELECT count(*) FROM quant_operational_receipts.receipts').fetchone() == (0,)


def test_expired_owner_cannot_retry_even_same_receipt(sql_db: Any) -> None:
    enable(sql_db)
    prepared = native.intent('run')
    with restricted(sql_db) as connection:
        writer.claim(connection, 'run', 'owner', expected_fence=0)
        writer.apply(connection, 'owner', prepared)
        connection.execute('COMMIT')
    sql_db.execute("UPDATE quant_operational_receipts.leases SET expires_at='2000-01-01Z'")
    with restricted(sql_db) as connection:
        assert writer.original(connection, prepared) == prepared.receipt
        with pytest.raises(Exception, match='STALE_OR_EXPIRED'):
            writer.apply(connection, 'owner', prepared)


def test_native_claims_remain_narrow(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ('identity_operational', 'idempotency', 'conflict', 'rollback_pair',
                 'mutation_denied', 'takeover', 'takeover_cas', 'old_writer', 'unknown_commit'):
        monkeypatch.setattr(native.OperationalHarness, name, lambda _: None)
    result = native.run_native(lambda _: pytest.fail('network'))
    assert result['passed_cases'] == list(native.CASES)
    assert result['immutable_operational_receipts_verified'] is False
    assert result['fencing_takeover_verified'] is False
    assert result['global_enforcement_commissioned'] is False
