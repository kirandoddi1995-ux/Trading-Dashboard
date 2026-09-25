"""Execute the review-only migration in disposable local PostgreSQL WASM only."""
from contextlib import contextmanager
import json
import os
from pathlib import Path

import pytest

from derivative_contracts import digest
from derivative_repository import DerivativeRepository
from derivative_restrictions import ban_url
from test_archive_maintenance_sql import Pg
import test_derivative_foundations as fixtures

NOW = fixtures.NOW


@pytest.fixture
def inputs():
    return fixtures.inputs.__wrapped__()

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'), reason='SQL engine not configured')


@pytest.fixture
def db():
    pg = Pg()
    pg.send({'script':'CREATE ROLE quant_app_runtime; CREATE ROLE equity_research_collector; CREATE ROLE anon; CREATE ROLE authenticated;'})
    script = (ROOT/'sql/derivative_foundations_review_only.sql').read_text()
    pg.send({'script':script})
    pg.send({'script':script})  # Idempotent draft.
    try:
        yield pg
    finally:
        pg.send({'close':True})
        pg.process.stdin.close()
        pg.process.wait(timeout=10)


class Cursor:
    def __init__(self, pg):
        self.pg = pg
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, sql, params=()):
        parts = sql.split('%s')
        converted = parts[0]
        for value, tail in zip(params, parts[1:]):
            converted += ("decode(%s,'hex')" if isinstance(value,bytes) else '%s') + tail
        self.result = self.pg.execute(converted, tuple(v.hex() if isinstance(v,bytes) else v for v in params))
    def fetchone(self):
        row = self.result.fetchone()
        if row and isinstance(row[0], dict) and row[0].get('type') == 'Buffer':
            row = (bytes(row[0]['data']), *row[1:])
        elif row and isinstance(row[0], dict) and row[0] and all(k.isdigit() for k in row[0]):
            row = (bytes(row[0][str(i)] for i in range(len(row[0]))), *row[1:])
        return row
    def fetchall(self):
        return self.result.fetchall()


@contextmanager
def connection(pg):
    class Conn:
        def cursor(self):
            return Cursor(pg)
    with pg.connect():
        yield Conn()


def test_permissions_and_no_research_access(db):
    for table in ('contract_versions','source_snapshots','exchange_rules','decision_snapshots'):
        assert db.execute("SELECT has_table_privilege('equity_research_collector',%s,'SELECT')",('derivatives_reference.'+table,)).fetchone()[0] is False
        assert db.execute("SELECT has_table_privilege('quant_app_runtime',%s,'DELETE')",('derivatives_reference.'+table,)).fetchone()[0] is False
    assert not db.execute("SELECT has_table_privilege('quant_derivative_ingestor','derivatives_reference.exchange_rules','INSERT')").fetchone()[0]
    db.execute('SET ROLE equity_research_collector')
    with pytest.raises(RuntimeError, match='permission denied'):
        db.execute('SELECT * FROM derivatives_reference.source_snapshots')
    db.execute('RESET ROLE')


def test_real_master_sql_versions_and_latest_removal(db, inputs):
    repo = DerivativeRepository(lambda:connection(db))
    m = inputs['master']
    raw = json.dumps([m]).encode()
    db.execute('SET ROLE quant_derivative_ingestor')
    for _ in range(2):
        repo.ingest_master([m],venue='NSE',trading_date=NOW.date(),raw=raw,received_at=NOW)
    repo.ingest_ban(b'SYMBOL\n',trading_date=NOW.date(),source=ban_url(NOW.date()),received_at=NOW)
    db.execute('RESET ROLE')
    assert db.execute('SELECT count(*) FROM derivatives_reference.contract_versions').fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM derivatives_reference.source_snapshots').fetchone()[0] == 2
    rules = inputs['rules']
    db.execute('INSERT INTO derivatives_reference.exchange_rules VALUES(%s,%s,%s,%s::jsonb)',
               (digest(rules),m['instrument_key'],NOW,json.dumps(rules)))
    db.execute('SET ROLE quant_app_runtime')
    master, loaded_rules, ban = repo.load(m['instrument_key'],venue='NSE',trading_date=NOW.date(),now=NOW)
    assert master == m and loaded_rules == rules and not ban.symbols
    db.execute('RESET ROLE')
    # The latest master excludes this key. Never resurrect it from an earlier snapshot.
    db.execute("INSERT INTO derivatives_reference.source_snapshots VALUES('MASTER_NSE',%s,%s,'{}','x',%s)",
               (NOW.date(),'a'*64,NOW.replace(second=1)))
    db.execute("UPDATE derivatives_reference.source_health SET source_hash=%s WHERE kind='MASTER_NSE'", ('a'*64,))
    db.execute('SET ROLE quant_app_runtime')
    assert repo.load(m['instrument_key'],venue='NSE',trading_date=NOW.date(),now=NOW.replace(second=2))[0] is None
    db.execute('RESET ROLE')
    # Re-observing the original version must make A current again after A -> B -> A.
    db.execute('SET ROLE quant_derivative_ingestor')
    repo.ingest_master([m],venue='NSE',trading_date=NOW.date(),raw=raw,received_at=NOW.replace(second=3))
    db.execute('RESET ROLE')
    db.execute('SET ROLE quant_app_runtime')
    assert repo.load(m['instrument_key'],venue='NSE',trading_date=NOW.date(),now=NOW.replace(second=4))[0] == m
    db.execute('RESET ROLE')
    db.execute('SET ROLE quant_derivative_ingestor')
    repo.mark_pending('MASTER_NSE',NOW.date(),NOW.replace(second=5))
    db.execute('RESET ROLE')
    db.execute('SET ROLE quant_app_runtime')
    assert repo.load(m['instrument_key'],venue='NSE',trading_date=NOW.date(),now=NOW.replace(second=6)) == (None,None,None)
    db.execute('RESET ROLE')
