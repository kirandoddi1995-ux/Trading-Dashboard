"""Runtime-role RLS on quant_app.market_quotes / mf_nav, in an isolated PGlite DB.

Regression for 9 Nov 2026: RLS was switched on for these tables while the only
policies (sql/drive_archive_draft.sql) were for quant_archive_worker, so the
scheduled collector (quant_app_runtime) failed with "new row violates row-level
security policy for table market_quotes". Older SQL tests hand-wrote the runtime
policy into their fixtures, which hid the gap. This test only applies real SQL
files and drives the real ProductionRepository write paths.

No hosted connection, no credentials, synthetic rows only.
"""
import datetime as dt
import json
import os
from pathlib import Path

import pytest

from production_repository import ProductionRepository
from test_archive_maintenance_sql import Pg

ROOT = Path(__file__).resolve().parents[1]
POLICY_SQL = (ROOT / 'sql/runtime_rls_policies.sql').read_text()
GAP_SQL = (ROOT / 'sql/check_rls_policy_gaps.sql').read_text()

pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                                reason='Local SQL harness not configured')

OBSERVED = dt.datetime(2026, 11, 9, 4, 37, tzinfo=dt.timezone.utc)
QUOTE = {'instrument_key': 'NSE_EQ|SYNTHETIC1', 'last_price': 101.5, 'volume': 1200,
         'ohlc': {'open': 100, 'high': 102, 'low': 99, 'close': 101}}


class RuntimePg(Pg):
    """Adapts the shared PGlite harness to ProductionRepository's DB-API use."""

    def commit(self):
        """No-op: `connect()` already wraps BEGIN/COMMIT, but repository code calls commit()."""
        return None

    def execute(self, sql, params=()):
        """Run SQL, turning psycopg Jsonb wrappers into JSON text (as tests/test_universe_storage_sql.py does)."""
        if not isinstance(params, dict):
            params = tuple(json.dumps(p.obj) if hasattr(p, 'obj') else p for p in params)
        return super().execute(sql, params)


@pytest.fixture
def pg():
    """Fresh DB in the live 9 Nov state: live grants, archive SQL applied, RLS on, no runtime policy."""
    db = RuntimePg()
    try:
        db.send({'script': """
          CREATE ROLE quant_app_runtime LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS;
          CREATE ROLE equity_research_collector; CREATE ROLE anon;
          CREATE ROLE authenticated; CREATE ROLE service_role;
          CREATE SCHEMA quant_app;
          GRANT USAGE ON SCHEMA quant_app TO quant_app_runtime;
          CREATE TABLE quant_app.market_quotes (
            observed_at timestamptz NOT NULL,trade_date date NOT NULL,instrument_key text NOT NULL,
            source text NOT NULL,last_price numeric,open numeric,high numeric,low numeric,
            previous_close numeric,volume numeric,open_interest numeric,raw jsonb NOT NULL DEFAULT '{}',
            PRIMARY KEY(observed_at,instrument_key));
          CREATE TABLE quant_app.mf_nav (
            scheme_code text NOT NULL,nav_date date NOT NULL,isin_growth text,isin_reinvestment text,
            scheme_name text NOT NULL,amc text,category text,plan text,option_name text,nav numeric NOT NULL,
            source text NOT NULL,observed_at timestamptz NOT NULL,source_hash text NOT NULL,
            PRIMARY KEY(scheme_code,nav_date));
          CREATE TABLE quant_app.evidence_ledger_events (id integer);
          -- Live grants on 9 Nov 2026: runtime may read/insert/update, never delete.
          GRANT SELECT,INSERT,UPDATE ON quant_app.market_quotes, quant_app.mf_nav TO quant_app_runtime;
        """})
        db.send({'script': (ROOT / 'sql/drive_archive_draft.sql').read_text()})
        # Live state after the 9 Nov advisor fix: RLS on, mf_nav also FORCE.
        db.send({'script': """
          ALTER TABLE quant_app.market_quotes ENABLE ROW LEVEL SECURITY;
          ALTER TABLE quant_app.mf_nav ENABLE ROW LEVEL SECURITY;
          ALTER TABLE quant_app.mf_nav FORCE ROW LEVEL SECURITY;
        """})
        yield db
    finally:
        db.send({'close': True})


def _repository(pg):
    """Real ProductionRepository wired to the PGlite connection (schema bootstrap skipped)."""
    repository = ProductionRepository('postgres://test-only')
    repository.ensure_schema = lambda: None
    repository.connect = pg.connect
    return repository


def _nav(value):
    """One synthetic NAV row in the shape the collector passes to archive_mf_nav."""
    return [{'scheme_code': 'SYN001', 'nav_date': dt.date(2026, 11, 6), 'scheme_name': 'Synthetic Fund',
             'nav': value, 'option': 'Growth'}]


def _gaps(pg, table):
    """Gap-check rows for one table as {(role, privileges)}, run as the superuser."""
    pg.execute('RESET ROLE')
    return {(role, privileges) for role, _schema, name, privileges in pg.execute(GAP_SQL).fetchall()
            if name == table}


def test_without_runtime_policy_the_collector_write_fails_like_9_nov(pg):
    """Control: the fixture reproduces the exact production error before the fix."""
    repository = _repository(pg)
    pg.execute('SET ROLE quant_app_runtime')
    with pytest.raises(RuntimeError, match='row-level security'):
        repository.archive_quotes([QUOTE], observed_at=OBSERVED, source='Upstox Full Market Quote V3')
    with pytest.raises(RuntimeError, match='row-level security'):
        repository.archive_mf_nav(_nav(10.5), source_hash='synthetic')


def test_policy_file_restores_runtime_quote_and_nav_writes(pg):
    """After the policy file, the real quote and NAV write paths succeed as the runtime role."""
    pg.send({'script': POLICY_SQL})
    repository = _repository(pg)
    pg.execute('SET ROLE quant_app_runtime')
    assert repository.archive_quotes([QUOTE], observed_at=OBSERVED, source='Upstox Full Market Quote V3') == 1
    # Same snapshot again: ON CONFLICT DO NOTHING path still allowed.
    repository.archive_quotes([QUOTE], observed_at=OBSERVED, source='Upstox Full Market Quote V3')
    assert pg.execute('SELECT count(*) FROM quant_app.market_quotes').fetchone()[0] == 1
    # The reviewed daily-volume trigger (SECURITY INVOKER) still runs as runtime.
    assert float(pg.execute('SELECT max_captured_volume FROM quant_app.market_daily_volumes '
                            "WHERE instrument_key='NSE_EQ|SYNTHETIC1'").fetchone()[0]) == 1200
    # NAV insert, then ON CONFLICT DO UPDATE (needs SELECT + UPDATE policy too).
    assert repository.archive_mf_nav(_nav(10.5), source_hash='synthetic') == 1
    assert repository.archive_mf_nav(_nav(10.75), source_hash='synthetic') == 1
    assert float(pg.execute('SELECT nav FROM quant_app.mf_nav').fetchone()[0]) == 10.75


def test_policy_does_not_widen_runtime_privileges(pg):
    """The policies add no privilege: runtime still has no DELETE grant on either table."""
    pg.send({'script': POLICY_SQL})
    _repository(pg).archive_quotes([QUOTE], observed_at=OBSERVED)
    pg.execute('SET ROLE quant_app_runtime')
    for table in ('market_quotes', 'mf_nav'):
        with pytest.raises(RuntimeError, match='permission denied'):
            pg.execute(f'DELETE FROM quant_app.{table}')


def test_archive_worker_access_is_unchanged(pg):
    """The archive worker can still read and delete quotes, and still cannot insert."""
    pg.send({'script': POLICY_SQL})
    _repository(pg).archive_quotes([QUOTE], observed_at=OBSERVED)
    pg.execute('SET ROLE quant_archive_worker')
    assert pg.execute('SELECT count(*) FROM quant_app.market_quotes').fetchone()[0] == 1
    with pytest.raises(RuntimeError, match='permission denied'):
        pg.execute("INSERT INTO quant_app.market_quotes(observed_at,trade_date,instrument_key,source) "
                   "VALUES (now(),current_date,'X','worker')")
    pg.execute('DELETE FROM quant_app.market_quotes')
    pg.execute('RESET ROLE')
    assert pg.execute('SELECT count(*) FROM quant_app.market_quotes').fetchone()[0] == 0


def test_policy_file_is_rerunnable_and_leaves_rls_on(pg):
    """Running the file twice leaves one policy per table, RLS on, and mf_nav's FORCE untouched."""
    pg.send({'script': POLICY_SQL})
    pg.send({'script': POLICY_SQL})
    rows = pg.execute("""
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               (SELECT count(*) FROM pg_policy p WHERE p.polrelid=c.oid AND p.polname LIKE 'runtime_%')
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='quant_app' AND c.relname IN ('market_quotes','mf_nav') ORDER BY 1""").fetchall()
    assert rows == [('market_quotes', True, False, 1), ('mf_nav', True, True, 1)]


def test_gap_check_flags_the_lockout_and_clears_after_policy_file(pg):
    """The gap check reports the 9 Nov lockout, and reports nothing once the policies exist."""
    assert _gaps(pg, 'market_quotes') == {('quant_app_runtime', 'INSERT,SELECT,UPDATE')}
    assert _gaps(pg, 'mf_nav') == {('quant_app_runtime', 'INSERT,SELECT,UPDATE')}
    pg.send({'script': POLICY_SQL})
    assert _gaps(pg, 'market_quotes') == set()
    assert _gaps(pg, 'mf_nav') == set()
    # Worker grants (SELECT/DELETE) are fully covered by drive_archive_draft.sql policies.
    worker = [row for row in pg.execute(GAP_SQL).fetchall() if row[0] == 'quant_archive_worker']
    assert worker == []


def test_gap_check_reports_public_grants_until_a_public_policy_exists(pg):
    """A PUBLIC grant on an RLS table with no PUBLIC policy is a lockout for every role relying on it."""
    pg.send({'script': """
        CREATE TABLE quant_app.public_probe (id integer);
        ALTER TABLE quant_app.public_probe ENABLE ROW LEVEL SECURITY;
        GRANT SELECT ON quant_app.public_probe TO PUBLIC;
    """})
    assert _gaps(pg, 'public_probe') == {('PUBLIC', 'SELECT')}
    pg.send({'script': 'CREATE POLICY probe_read ON quant_app.public_probe FOR SELECT USING (true);'})
    assert _gaps(pg, 'public_probe') == set()


def test_gap_check_reports_a_forced_owner_but_not_an_unforced_one(pg):
    """RLS skips the owner unless FORCE is set; a forced, non-bypass owner with no policy is locked out."""
    pg.send({'script': """
        CREATE ROLE probe_owner NOSUPERUSER NOBYPASSRLS;
        CREATE TABLE quant_app.owner_probe (id integer);
        ALTER TABLE quant_app.owner_probe OWNER TO probe_owner;
        ALTER TABLE quant_app.owner_probe ENABLE ROW LEVEL SECURITY;
    """})
    # Default ACL (relacl NULL): owner rows come from acldefault(); unforced owner is exempt.
    assert _gaps(pg, 'owner_probe') == set()
    pg.send({'script': 'ALTER TABLE quant_app.owner_probe FORCE ROW LEVEL SECURITY;'})
    assert _gaps(pg, 'owner_probe') == {('probe_owner', 'DELETE,INSERT,SELECT,UPDATE')}
