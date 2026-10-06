"""Legacy startup cannot overwrite protected ledger archive triggers."""
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock
import os

import pytest

from production_repository import ProductionRepository, RepositoryUnavailable

pytest_plugins = ('test_ledger_archive_guards_sql',)


@pytest.mark.parametrize('answer', [(True,), None, (), (None,), ('false',), (0,)])
def test_protected_or_unverified_namespace_blocks_before_any_ddl(answer):
    connection = Mock()
    connection.execute.return_value.fetchone.return_value = answer
    repository = ProductionRepository('postgresql://fixture.invalid/test')

    @contextmanager
    def connect():
        yield connection

    repository.connect = connect
    with pytest.raises(RepositoryUnavailable, match='legacy schema setup refused'):
        repository.ensure_schema()
    assert connection.execute.call_count == 2
    assert connection.execute.call_args_list[0].args[1] == ('quant-storage-schema-v1',)
    assert 'pg_namespace' in connection.execute.call_args.args[0]
    connection.cursor.assert_not_called()
    connection.commit.assert_not_called()
    assert repository._schema_ready is False


def test_no_protected_namespace_preserves_legacy_migration_path():
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (False,)
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = RuntimeError('FIRST_LEGACY_DDL_REACHED')
    repository = ProductionRepository('postgresql://fixture.invalid/test')

    @contextmanager
    def connect():
        yield connection

    repository.connect = connect
    with pytest.raises(RuntimeError, match='FIRST_LEGACY_DDL_REACHED'):
        repository.ensure_schema()
    assert cursor.execute.call_args.args[0] == 'CREATE SCHEMA IF NOT EXISTS quant_app'


def test_already_ready_does_not_open_connection():
    repository = ProductionRepository('postgresql://fixture.invalid/test')
    repository._schema_ready = True
    repository.connect = Mock(side_effect=AssertionError('Unexpected connection'))
    repository.ensure_schema()
    repository.connect.assert_not_called()


@pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                    reason='Local SQL harness not configured')
def test_actual_protected_sql_guards_survive_legacy_setup_attempt(ledger_db):
    query = """SELECT tgname, tgfoid::text FROM pg_trigger
        WHERE tgrelid='quant_app.evidence_ledger_events'::regclass
          AND NOT tgisinternal ORDER BY tgname"""
    before = ledger_db.execute(query).fetchall()
    repository = ProductionRepository('postgresql://fixture.invalid/test')
    repository.connect = ledger_db.connect
    with pytest.raises(RepositoryUnavailable, match='legacy schema setup refused'):
        repository.ensure_schema()
    assert ledger_db.execute(query).fetchall() == before
    assert 'storage_ledger_delete_statement' in {row[0] for row in before}
