"""Real universe writer SQL in disposable PostgreSQL; no hosted data or secrets."""
import ast
import json
from contextlib import contextmanager
import datetime as dt
import os
from pathlib import Path

import pytest

from drive_archive import SPECS
from production_repository import ProductionRepository
from test_archive_maintenance_sql import Pg

pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'), reason='SQL engine not configured')


@pytest.fixture
def repository(monkeypatch):
    monkeypatch.setattr('production_repository._utcnow', lambda: dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc))
    db = Pg()
    db.send({'script': '''CREATE SCHEMA quant_app;
      CREATE TABLE quant_app.universe_snapshots(snapshot_date date PRIMARY KEY,
      observed_at timestamptz,source text,instrument_count integer,payload_hash text,
      is_complete boolean,schema_version integer);
      CREATE TABLE quant_app.universe_snapshot_versions(snapshot_id text PRIMARY KEY,
      snapshot_date date,observed_at timestamptz,source text,instrument_count integer,
      payload_hash text,is_complete boolean,schema_version integer);'''})
    for table, key in [('universe_membership','snapshot_date'), ('universe_membership_versions','snapshot_id')]:
        columns = ','.join(f'{name} {kind}' for name, kind in SPECS[table].items())
        db.execute(f'CREATE TABLE quant_app.{table} ({columns}, PRIMARY KEY({key},instrument_key))')
    repo = ProductionRepository('')
    repo.ensure_schema = lambda: None
    @contextmanager
    def connect():
        class Connection:
            def execute(self, sql, params=()):
                return db.execute(sql, tuple(json.dumps(p.obj) if hasattr(p, 'obj') else p for p in params))
            def cursor(self):
                return self
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def executemany(self, sql, rows):
                for row in rows:
                    self.execute(sql, row)
            def commit(self):
                pass
        with db.connect():
            yield Connection()
    repo.connect = connect
    try:
        yield repo, db
    finally:
        db.send({'close': True})
        db.process.stdin.close()
        db.process.wait(timeout=10)


def records(count=2):
    return [{'instrument_key': f'NSE_EQ|{i}', 'trading_symbol': f'S{i}', 'name': 'fixture'} for i in range(count)]


def test_repeat_is_storage_noop_preserves_receipt(repository, monkeypatch):
    repo, db = repository
    first = repo.archive_universe(records(), '2026-10-05', minimum_complete=2)
    monkeypatch.setattr('production_repository._utcnow', lambda: dt.datetime(2026, 10, 5, 1, tzinfo=dt.timezone.utc))
    before = db.execute('SELECT to_jsonb(s) FROM quant_app.universe_snapshots s').fetchall()
    # A trigger proves the writer does not attempt canonical UPDATE/DELETE/INSERT.
    db.send({'script': '''CREATE FUNCTION quant_app.reject_write() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Unexpected unchanged write'; END $$;
    CREATE TRIGGER block_header BEFORE UPDATE ON quant_app.universe_snapshots FOR EACH ROW EXECUTE FUNCTION quant_app.reject_write();
    CREATE TRIGGER block_members BEFORE INSERT OR DELETE ON quant_app.universe_membership FOR EACH ROW EXECUTE FUNCTION quant_app.reject_write();
    CREATE TRIGGER block_versions BEFORE INSERT ON quant_app.universe_membership_versions FOR EACH ROW EXECUTE FUNCTION quant_app.reject_write();'''})
    repeated = repo.archive_universe(list(reversed(records())), '2026-10-05', minimum_complete=2)
    assert not repeated['canonical_changed'] and not repeated['version_created']
    assert repeated['observed_at'] == first['observed_at']
    assert db.execute('SELECT to_jsonb(s) FROM quant_app.universe_snapshots s').fetchall() == before


def test_change_and_incomplete_preserve_history(repository):
    repo, db = repository
    first = repo.archive_universe(records(), '2026-10-05', minimum_complete=2)
    partial = repo.archive_universe(records(1), '2026-10-05', minimum_complete=2)
    assert partial['canonical_preserved'] and partial['version_created']
    assert not partial['canonical_changed']
    assert db.execute('SELECT count(*) FROM quant_app.universe_membership').fetchone()[0] == 2
    revised = records()
    revised[0]['name'] = 'real revision fixture'
    result = repo.archive_universe(revised, '2026-10-05', minimum_complete=2)
    assert result['canonical_changed'] and result['version_created']
    assert first['snapshot_id'] != result['snapshot_id']
    assert db.execute('SELECT count(*) FROM quant_app.universe_snapshot_versions').fetchone()[0] == 3
    assert db.execute('SELECT count(*) FROM quant_app.universe_membership_versions').fetchone()[0] == 5


def test_new_date_same_content_retains_calendar_identity(repository):
    repo, db = repository
    repo.archive_universe(records(), '2026-10-05', minimum_complete=2)
    assert repo.archive_universe(records(), '2026-10-06', minimum_complete=2)['version_created']
    assert db.execute('SELECT count(*) FROM quant_app.universe_membership').fetchone()[0] == 4


def test_missing_canonical_members_cannot_be_certified_as_unchanged(repository):
    repo, db = repository
    repo.archive_universe(records(), '2026-10-05', minimum_complete=2)
    db.execute("DELETE FROM quant_app.universe_membership WHERE instrument_key='NSE_EQ|0'")
    with pytest.raises(RuntimeError, match='UNIVERSE_CANONICAL_MEMBERSHIP_COUNT_MISMATCH'):
        repo.archive_universe(records(), '2026-10-05', minimum_complete=2)


def test_first_quick_scan_requires_explicit_button():
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / 'app.py').read_text(encoding='utf-8'))
    branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                  and ast.unparse(n.test) == 'not already_scanned_this_session')
    assignment = next(n for n in branch.body if isinstance(n, ast.Assign))
    assert isinstance(assignment.value, ast.Call)
    assert ast.unparse(assignment.value.func) == 'st.button'
