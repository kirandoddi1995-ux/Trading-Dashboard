"""No hot-only fallback after archive: real disposable PostgreSQL snapshots."""
import os
from contextlib import contextmanager

import pytest

from ledger_runtime_reader import LedgerReadError
from ledger_storage_access import hot_read
from production_repository import ProductionRepository
from test_archive_maintenance_sql import Pg

pytest_plugins = ('test_ledger_runtime_reader_sql',)
pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                                reason='Local SQL harness not configured')


def legacy_repository(reader):
    repo = ProductionRepository('')
    repo._schema_ready = True
    repo.connect = reader[-1].connect
    return repo


@pytest.mark.parametrize('method', ['events', 'audit', 'training', 'readiness', 'pending'])
def test_every_legacy_ledger_reader_blocks_after_archival(reader, method):
    _, _, _, commit, _ = reader
    commit()
    repo = legacy_repository(reader)
    call = {'events': lambda: repo.events('one'),
            'audit': repo.verify_evidence_ledger_continuity,
            'training': lambda: repo.matured_decision_dataset(strategy_id='fixture',
                target_version='fixture', horizon_sessions=1),
            'readiness': repo.decision_outcome_records,
            'pending': repo.pending_observations}[method]
    with pytest.raises(LedgerReadError, match='COLD_READER_REQUIRED'):
        call()


def test_genesis_hot_reads_and_audit_keep_original_sql_results(reader):
    repo = legacy_repository(reader)
    assert len(repo.events('one')) == 3
    assert repo.verify_evidence_ledger_continuity()['events'] == 3


def test_legacy_writer_cannot_restart_fully_archived_aggregate(reader):
    db, _, _, commit, _ = reader
    commit()
    repo = legacy_repository(reader)
    with pytest.raises(LedgerReadError, match='COLD_READER_REQUIRED'):
        repo.append_evidence_event(aggregate_id='one', event_type='NEXT',
                                   payload={'synthetic': True}, idempotency_key='new')
    assert db.execute('SELECT count(*) FROM quant_app.evidence_ledger_events').fetchone() == (0,)


def test_legacy_shared_writer_failure_rolls_back_before_retry(reader):
    _, _, _, commit, _ = reader
    commit()
    repo = legacy_repository(reader)
    with repo.connect() as conn:
        for key in ('first', 'second'):
            with pytest.raises(LedgerReadError, match='COLD_READER_REQUIRED'):
                repo.append_evidence_event(aggregate_id='one', event_type='NEXT', payload={},
                                           idempotency_key=key, _connection=conn)
            assert conn.execute('SELECT count(*) FROM quant_app.evidence_ledger_events').fetchone() == (0,)


@pytest.mark.parametrize('damage', ['missing', 'malformed'])
def test_partial_or_damaged_storage_control_never_allows_hot_fallback(reader, damage):
    db, _, _, _, _ = reader
    if damage == 'missing':
        db.execute('TRUNCATE quant_storage.catalog_roots')
    else:
        # Explicit operator damage in a disposable fixture only, not an owner step.
        db.execute('ALTER TABLE quant_storage.catalog_roots DISABLE TRIGGER USER')
        db.execute('ALTER TABLE quant_storage.catalog_roots DROP CONSTRAINT storage_root_shape')
        db.execute("UPDATE quant_storage.catalog_roots SET root=repeat('a',64)")
        db.execute('ALTER TABLE quant_storage.catalog_roots ENABLE TRIGGER USER')
    with pytest.raises(LedgerReadError, match='STORAGE_STATE_INVALID'):
        legacy_repository(reader).events('one')


def test_legacy_read_without_storage_namespace_is_still_read_only():
    db = Pg()
    try:
        with hot_read(db.connect) as conn:
            assert conn.execute("SELECT current_setting('transaction_read_only')").fetchone() == ('on',)
            with pytest.raises(RuntimeError, match='read-only'):
                conn.execute('CREATE TABLE forbidden_write(id integer)')
        assert db.execute("SELECT to_regclass('public.forbidden_write')").fetchone() == (None,)
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)


def test_legacy_read_metadata_denial_rolls_back_and_sanitizes(reader):
    db, _, _, _, _ = reader
    db.execute('REVOKE SELECT ON quant_storage.catalog_roots FROM quant_app_runtime')
    with pytest.raises(LedgerReadError, match='^LEDGER_HOT_SNAPSHOT_UNVERIFIED$'):
        legacy_repository(reader).events('one')
    db.execute('GRANT SELECT ON quant_storage.catalog_roots TO quant_app_runtime')
    assert len(legacy_repository(reader).events('one')) == 3


def test_prequeried_writable_connection_cannot_silently_keep_weak_isolation():
    db = Pg()
    try:
        @contextmanager
        def used():
            db.execute('BEGIN')
            db.execute('SELECT 1')
            try:
                yield db
            finally:
                db.execute('ROLLBACK')
        with pytest.raises(LedgerReadError, match='HOT_SNAPSHOT_UNVERIFIED'):
            with hot_read(used):
                pytest.fail('A prequeried weak snapshot must not be accepted')
        assert db.execute('SELECT 1').fetchone() == (1,)
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)
