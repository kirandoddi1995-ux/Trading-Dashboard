"""Execute the real migration and repository SQL in an isolated PostgreSQL WASM DB.

No hosted connection or credentials. Advisory-lock serialization itself must also
be checked on hosted PostgreSQL; this harness exercises data/transaction safety.
"""
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from archive_maintenance import ArchiveRepository, cutoff_for, run_batch
from production_repository import ProductionRepository
from test_drive_archive import MemoryDrive

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                                reason='Local SQL harness not configured')

NODE = r"""
const {PGlite}=require(process.argv[1]);
const readline=require('readline');
(async()=>{
 const db=new PGlite();await db.waitReady;
 for await (const line of readline.createInterface({input:process.stdin})){
  try {const m=JSON.parse(line);
   if(m.close){await db.close();process.stdout.write('{}\n');break;}
   if(m.script){await db.exec(m.script);process.stdout.write('{}\n');continue;}
   const r=await db.query(m.sql,m.params||[]);
   process.stdout.write(JSON.stringify({rows:r.rows.map(row=>r.fields.map(f=>row[f.name]))})+'\n');
  }catch(e){process.stdout.write(JSON.stringify({error:e.message})+'\n');}
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
"""


class Pg:
    def __init__(self):
        self.process = subprocess.Popen(['node', '-e', NODE, os.environ['EQUITY_TEST_PGLITE_MODULE']],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding='utf-8')

    def send(self, message):
        self.process.stdin.write(json.dumps(message, default=str) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('Local SQL process stopped')
        reply = json.loads(line)
        if reply.get('error'):
            raise RuntimeError(reply['error'])
        return reply.get('rows', [])

    def execute(self, sql, params=()):
        values = []
        if isinstance(params, dict):
            def replace(match):
                values.append(params[match.group(1)])
                return '$' + str(len(values))
            sql = re.sub(r'%\((\w+)\)s', replace, sql)
        else:
            values = list(params)
            for index in range(len(values)):
                sql = sql.replace('%s', '$' + str(index + 1), 1)
        return Result(self.send({'sql': sql, 'params': values}))

    def cursor(self):
        return self

    def executemany(self, sql, rows):
        for row in rows:
            self.execute(sql, row)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    @contextmanager
    def connect(self, *_args, **_kwargs):
        self.execute('BEGIN')
        try:
            yield self
            self.execute('COMMIT')
        except Exception:
            self.execute('ROLLBACK')
            raise


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return tuple(self.rows[0]) if self.rows else None

    def fetchall(self):
        return [tuple(row) for row in self.rows]


@pytest.fixture
def pg(monkeypatch):
    db = Pg()
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
          GRANT SELECT,INSERT ON quant_app.market_quotes TO quant_app_runtime;
          ALTER TABLE quant_app.market_quotes ENABLE ROW LEVEL SECURITY;
          CREATE POLICY runtime_quotes ON quant_app.market_quotes TO quant_app_runtime USING(true) WITH CHECK(true);
          ALTER TABLE quant_app.mf_nav ENABLE ROW LEVEL SECURITY;
        """})
        migration = (ROOT / 'sql/drive_archive_draft.sql').read_text()
        db.send({'script': migration})
        from drive_archive import SPECS
        for table in ('universe_membership_versions', 'scanner_observations'):
            columns = ','.join(f'{name} {kind}' for name, kind in SPECS[table].items())
            key = 'snapshot_id,instrument_key' if table.startswith('universe') else 'observation_id'
            db.execute(f'CREATE TABLE quant_app.{table} ({columns}, PRIMARY KEY({key}))')
        db.send({'script': """
            CREATE TABLE quant_app.universe_snapshot_versions (
                snapshot_id text PRIMARY KEY,snapshot_date date,observed_at timestamptz,
                is_complete boolean,payload_hash text);
            CREATE TABLE quant_app.prediction_targets (
                observation_id text PRIMARY KEY REFERENCES quant_app.scanner_observations(observation_id)
                    ON DELETE CASCADE, outcome text);
            GRANT SELECT,INSERT,UPDATE ON quant_app.scanner_observations,
                quant_app.universe_membership_versions,quant_app.universe_snapshot_versions,
                quant_app.prediction_targets TO quant_app_runtime;
        """})
        db.send({'script': (ROOT / 'sql/drive_archive_scanner_universe_draft.sql').read_text()})
        db.send({'script': """
            CREATE SCHEMA equity_research;
            CREATE TABLE equity_research.source_decisions(decision_id text PRIMARY KEY);
            CREATE TABLE equity_research.observations(decision_id text PRIMARY KEY
                REFERENCES equity_research.source_decisions(decision_id));
            CREATE TABLE equity_research.outcomes(snapshot_id text PRIMARY KEY,
                decision_id text NOT NULL REFERENCES equity_research.observations(decision_id),
                payload jsonb NOT NULL, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp());
            GRANT USAGE ON SCHEMA equity_research TO equity_research_collector;
            GRANT SELECT,INSERT ON equity_research.outcomes TO equity_research_collector;
            CREATE POLICY research_read ON equity_research.outcomes FOR SELECT
                TO equity_research_collector USING(true);
            CREATE POLICY research_insert ON equity_research.outcomes FOR INSERT
                TO equity_research_collector WITH CHECK(true);
        """})
        original_research = (ROOT / 'sql/equity_research_observations.sql').read_text()
        protection = original_research.split('CREATE FUNCTION equity_research.reject_mutation()', 1)[1]
        protection = protection.split('REVOKE ALL ON ALL TABLES', 1)[0]
        db.send({'script': 'CREATE FUNCTION equity_research.reject_mutation()' + protection})
        db.send({'script': (ROOT / 'sql/drive_archive_research_outcomes_draft.sql').read_text()})
        # PGlite has no shared processes; replace ONLY this lock in the harness.
        original = db.execute
        def execute(sql, params=()):
            if sql == 'SELECT pg_advisory_xact_lock(71429051)':
                return Result([[None]])
            return original(sql, params)
        db.execute = execute
        monkeypatch.setattr('archive_maintenance.psycopg.connect', db.connect)
        yield db
    finally:
        db.send({'close': True})
        db.process.communicate(timeout=15)


def insert_nav(db, code, date, nav='1.123456789123456789'):
    db.execute("""INSERT INTO quant_app.mf_nav
        (scheme_code,nav_date,scheme_name,nav,source,observed_at,source_hash)
        VALUES (%s,%s,'Fund',%s,'AMFI','2026-08-01Z','hash')""", (code, date, nav))


def test_real_sql_nav_latest_retained_changed_row_not_deleted_and_retry(pg):
    insert_nav(pg, 'A', '2026-08-01')
    insert_nav(pg, 'A', '2026-08-02')
    insert_nav(pg, 'B', '2020-01-01')  # Old but latest: must survive.
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    repo.check()
    cutoff = dt.date(2026, 9, 13)
    assert repo.preview('mf_nav', cutoff) == 1
    drive = MemoryDrive()
    exported = run_batch(repo, drive, 'mf_nav', cutoff)
    assert exported['verified'] == 1 and exported['deleted'] == 0
    deleted = run_batch(repo, drive, 'mf_nav', cutoff, delete=True)
    assert deleted['deleted'] == 1
    assert run_batch(repo, drive, 'mf_nav', cutoff, delete=True)['selected'] == 0
    assert pg.execute('SELECT count(*) FROM quant_app.mf_nav').fetchone()[0] == 2
    pg.execute('RESET ROLE')
    insert_nav(pg, 'A', '2026-08-01')
    pg.execute('SET ROLE quant_archive_worker')
    from drive_archive import upload_verified
    manifest, texts = upload_verified(drive, 'mf_nav', repo.select('mf_nav', cutoff, 100))
    # A downloaded archive can restore every column, including exact NUMERIC,
    # into an isolated table without fetching replacement data.
    pg.execute('RESET ROLE')
    pg.execute('CREATE TEMP TABLE restore_check (LIKE quant_app.mf_nav)')
    pg.execute('INSERT INTO restore_check SELECT * FROM '
               'jsonb_populate_record(NULL::quant_app.mf_nav,%s::jsonb)', (texts[0],))
    assert pg.execute("SELECT nav::text FROM restore_check").fetchone()[0] == '1.123456789123456789'
    pg.execute("UPDATE quant_app.mf_nav SET nav=99 WHERE nav_date='2026-08-01'")
    pg.execute('SET ROLE quant_archive_worker')
    assert repo.acknowledge(manifest, texts, cutoff, True) == 0
    assert repo.preview('mf_nav', cutoff) == 1
    with pytest.raises(RuntimeError):
        pg.execute('SELECT * FROM quant_app.evidence_ledger_events')
    with pytest.raises(RuntimeError):
        pg.execute('TRUNCATE quant_app.mf_nav')


def test_manifest_conflict_never_deletes_source_and_ack_retry_is_idempotent(pg):
    from drive_archive import upload_verified
    insert_nav(pg, 'A', '2026-08-01')
    insert_nav(pg, 'A', '2026-08-02')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    cutoff = dt.date(2026, 9, 13)
    manifest, texts = upload_verified(MemoryDrive(), 'mf_nav', repo.select('mf_nav', cutoff, 100))
    repo.acknowledge(manifest, texts, cutoff, False)
    with pytest.raises(Exception, match='MANIFEST_CONFLICT'):
        repo.acknowledge({**manifest, 'sha256': 'a' * 64}, texts, cutoff, True)
    assert repo.preview('mf_nav', cutoff) == 1
    assert repo.acknowledge(manifest, texts, cutoff, True) == 1
    assert repo.acknowledge(manifest, texts, cutoff, True) == 0
    assert pg.execute('SELECT deleted_count FROM quant_app.archive_manifests').fetchone()[0] == 1


def test_daily_maxima_reader_equal_old_query_before_and_after_archival(pg):
    # Backfill existing rows, duplicate snapshots, missing volumes, zero volume,
    # >20 dates, and current-date exclusion. Use actual repository reader SQL.
    for day in range(1, 26):
        for hour, volume in ((9, day), (10, day * 3), (11, None)):
            pg.execute("""INSERT INTO quant_app.market_quotes
                (observed_at,trade_date,instrument_key,source,volume)
                VALUES (%s,%s,'A','test',%s)""",
                       (f'2026-08-{day:02d}T{hour}:00:00Z', f'2026-08-{day:02d}', volume))
    pg.execute("INSERT INTO quant_app.market_quotes VALUES "
               "('2026-09-20T09:00Z','2026-09-20','A','test',NULL,NULL,NULL,NULL,NULL,9999,NULL,'{}')")
    pg.execute("INSERT INTO quant_app.market_quotes VALUES "
               "('2026-08-01T09:00Z','2026-08-01','ZERO','test',NULL,NULL,NULL,NULL,NULL,0,NULL,'{}')")
    pg.send({'script': (ROOT / 'sql/drive_archive_draft.sql').read_text()})  # Idempotent backfill.
    old = pg.execute("""WITH daily AS (
        SELECT instrument_key,trade_date,MAX(volume)::double precision v
        FROM quant_app.market_quotes WHERE trade_date<'2026-09-20' AND volume IS NOT NULL
        GROUP BY instrument_key,trade_date), ranked AS (
        SELECT *,row_number() OVER(PARTITION BY instrument_key ORDER BY trade_date DESC) n FROM daily)
        SELECT instrument_key,AVG(v) FROM ranked WHERE n<=20 GROUP BY instrument_key""").fetchall()
    expected = {key: float(value) for key, value in old if value > 0}
    repository = ProductionRepository('postgres://test-only')
    repository.ensure_schema = lambda: None
    repository.connect = pg.connect
    pg.execute('SET ROLE quant_app_runtime')
    assert repository.prior_average_volumes(['A', 'ZERO'], as_of_date='2026-09-20') == expected
    # Runtime insert trigger updates maxima; rollback must undo BOTH tables.
    pg.execute('BEGIN')
    pg.execute("INSERT INTO quant_app.market_quotes VALUES "
               "('2026-08-25T12:00Z','2026-08-25','A','test',NULL,NULL,NULL,NULL,NULL,999,NULL,'{}')")
    pg.execute('ROLLBACK')
    assert repository.prior_average_volumes(['A'], as_of_date='2026-09-20') == expected
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    result = run_batch(repo, MemoryDrive(), 'market_quotes', dt.date(2026, 8, 26), delete=True)
    assert result['deleted'] == 76
    pg.execute('SET ROLE quant_app_runtime')
    assert repository.prior_average_volumes(['A', 'ZERO'], as_of_date='2026-09-20') == expected
    pg.execute('SET ROLE equity_research_collector')
    for table in ('market_daily_volumes', 'archive_manifests'):
        with pytest.raises(RuntimeError):
            pg.execute('SELECT * FROM quant_app.' + table)


def test_missing_rollup_blocks_deletion_and_rolls_back_manifest(pg):
    pg.execute("INSERT INTO quant_app.market_quotes VALUES "
               "('2026-08-01T09:00Z','2026-08-01','A','test',NULL,NULL,NULL,NULL,NULL,123,NULL,'{}')")
    pg.execute('DELETE FROM quant_app.market_daily_volumes')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    with pytest.raises(Exception, match='DAILY_VOLUME_COVERAGE_MISSING'):
        run_batch(repo, MemoryDrive(), 'market_quotes', dt.date(2026, 8, 21), delete=True)
    assert pg.execute('SELECT count(*) FROM quant_app.market_quotes').fetchone()[0] == 1
    assert pg.execute('SELECT count(*) FROM quant_app.archive_manifests').fetchone()[0] == 0


def test_fourteen_day_boundary_latest_nav_and_recent_capture_survive(pg):
    cutoff = cutoff_for('market_quotes', dt.date(2026, 9, 24))
    assert cutoff == dt.date(2026, 9, 10)
    insert_nav(pg, 'A', '2026-09-09')
    insert_nav(pg, 'A', '2026-09-10')
    insert_nav(pg, 'B', '2020-01-01')
    for instrument, trade_date, observed_at in (
        ('OLD', '2026-09-09', '2026-09-09T10:00Z'),
        ('BOUNDARY', '2026-09-10', '2026-09-10T00:00Z'),
        ('RECENT_CAPTURE', '2026-09-09', '2026-09-10T00:00Z'),
        ('RECENT_TRADE', '2026-09-10', '2026-09-09T10:00Z'),
    ):
        pg.execute('INSERT INTO quant_app.market_quotes '
                   '(instrument_key,trade_date,observed_at,source,volume) '
                   "VALUES (%s,%s,%s,'test',100)", (instrument, trade_date, observed_at))
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    for table in ('mf_nav', 'market_quotes'):
        assert repo.preview(table, cutoff) == 1
        assert run_batch(repo, MemoryDrive(), table, cutoff, delete=True)['deleted'] == 1
    assert pg.execute('SELECT count(*) FROM quant_app.market_quotes').fetchone()[0] == 3
    assert pg.execute('SELECT count(*) FROM quant_app.mf_nav').fetchone()[0] == 2
    assert pg.execute('SELECT count(*) FROM quant_app.market_daily_volumes').fetchone()[0] == 4


def scanner(db, identifier, *, passed=False, day='2026-08-01', observed=None):
    db.execute("""INSERT INTO quant_app.scanner_observations
        (observation_id,as_of_date,observed_at,instrument_key,trading_symbol,strategy_version,
         universe_snapshot_date,stage1_pass,stage2_pass,feature_json)
        VALUES (%s,%s,%s,'KEY','SYMBOL','test',%s,true,%s,'{"x":1.234567890123456789}')""",
               (identifier, day, observed or day+'T10:00Z', day, passed))


def test_scanner_retains_passed_target_parents_boundary_and_recent_capture(pg):
    scanner(pg, 'archive')
    scanner(pg, 'passed', passed=True)
    scanner(pg, 'target')
    scanner(pg, 'boundary', day='2026-09-10')
    scanner(pg, 'recent_capture', observed='2026-09-10T00:00Z')
    pg.execute("INSERT INTO quant_app.prediction_targets VALUES ('target','label')")
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    repo.check()
    cutoff = dt.date(2026, 9, 10)
    assert repo.preview('scanner_observations', cutoff) == 1
    result = run_batch(repo, MemoryDrive(), 'scanner_observations', cutoff, delete=True)
    assert result['verified'] == result['deleted'] == 1
    assert {r[0] for r in pg.execute('SELECT observation_id FROM quant_app.scanner_observations').fetchall()} == {
        'passed', 'target', 'boundary', 'recent_capture'}
    assert pg.execute('SELECT observation_id FROM quant_app.prediction_targets').fetchall() == [('target',)]
    with pytest.raises(RuntimeError):
        pg.execute('SELECT outcome FROM quant_app.prediction_targets')
    with pytest.raises(RuntimeError):
        pg.execute('DELETE FROM quant_app.prediction_targets')


def test_scanner_rechecks_payload_status_and_new_target_after_export(pg):
    from drive_archive import upload_verified
    for identifier in ('changed', 'promoted', 'target_added'):
        scanner(pg, identifier)
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    cutoff = dt.date(2026, 9, 10)
    manifest, texts = upload_verified(MemoryDrive(), 'scanner_observations',
                                      repo.select('scanner_observations', cutoff, 100))
    pg.execute('RESET ROLE')
    pg.execute("UPDATE quant_app.scanner_observations SET score=99 WHERE observation_id='changed'")
    pg.execute("UPDATE quant_app.scanner_observations SET stage2_pass=true WHERE observation_id='promoted'")
    pg.execute("INSERT INTO quant_app.prediction_targets VALUES ('target_added','label')")
    pg.execute('SET ROLE quant_archive_worker')
    assert repo.acknowledge(manifest, texts, cutoff, True) == 0
    pg.execute('RESET ROLE')
    # Even an owner bypassing RLS cannot cascade away an existing target.
    with pytest.raises(RuntimeError, match='foreign key'):
        pg.execute("DELETE FROM quant_app.scanner_observations WHERE observation_id='target_added'")
    assert pg.execute('SELECT count(*) FROM quant_app.prediction_targets').fetchone()[0] == 1


def test_membership_versions_keep_latest_complete_and_recent_capture(pg):
    for identifier, date, complete in [('old','2026-08-01',True),
                                       ('latest','2026-08-02',True),
                                       ('incomplete','2026-08-03',False)]:
        pg.execute('INSERT INTO quant_app.universe_snapshot_versions VALUES (%s,%s,%s,%s,\'hash\')',
                   (identifier,date,date+'T10:00Z',complete))
        pg.execute("""INSERT INTO quant_app.universe_membership_versions
            (snapshot_id,instrument_key,trading_symbol,observed_at,source,raw)
            VALUES (%s,'KEY','SYMBOL',%s,'provider','{"original":true}')""",
                   (identifier,date+'T10:00Z'))
    pg.execute("""INSERT INTO quant_app.universe_membership_versions
        (snapshot_id,instrument_key,observed_at) VALUES ('old','RECENT','2026-09-10T00:00Z')""")
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    result = run_batch(repo, MemoryDrive(), 'universe_membership_versions', dt.date(2026,9,10), delete=True)
    assert result['deleted'] == result['verified'] == 1
    assert pg.execute('SELECT count(*) FROM quant_app.universe_membership_versions').fetchone()[0] == 3
    assert pg.execute('SELECT count(snapshot_id) FROM quant_app.universe_snapshot_versions').fetchone()[0] == 3
    with pytest.raises(RuntimeError):
        pg.execute('SELECT payload_hash FROM quant_app.universe_snapshot_versions')


def test_new_migration_rerunnable_and_missing_restrict_guard_blocks(pg):
    pg.send({'script': (ROOT / 'sql/drive_archive_scanner_universe_draft.sql').read_text()})
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    repo.check()
    pg.execute('RESET ROLE')
    pg.execute('ALTER TABLE quant_app.prediction_targets DROP CONSTRAINT prediction_targets_observation_id_fkey')
    pg.execute('SET ROLE quant_archive_worker')
    with pytest.raises(Exception, match='RESTRICT_FK_REQUIRED'):
        repo.check()


def test_migration_preserves_runtime_and_does_not_widen_existing_rls(pg):
    pg.execute('SET ROLE quant_app_runtime')
    scanner(pg, 'runtime', passed=True)
    assert pg.execute('SELECT observation_id FROM quant_app.scanner_observations').fetchone() == ('runtime',)
    pg.execute('RESET ROLE')
    pg.execute('ALTER POLICY archive_preserve_runtime ON quant_app.scanner_observations '
               'USING (false) WITH CHECK (false)')
    pg.send({'script': (ROOT / 'sql/drive_archive_scanner_universe_draft.sql').read_text()})
    pg.execute('SET ROLE quant_app_runtime')
    assert pg.execute('SELECT observation_id FROM quant_app.scanner_observations').fetchall() == []


def research_snapshot(db, snapshot, subject, stamp):
    db.execute('INSERT INTO equity_research.source_decisions VALUES (%s) ON CONFLICT DO NOTHING', (subject,))
    db.execute('INSERT INTO equity_research.observations VALUES (%s) ON CONFLICT DO NOTHING', (subject,))
    db.execute("""INSERT INTO equity_research.outcomes VALUES (%s,%s,
        '{"source_candles":[["original",1.123456789123456789,0]],"approved":false}',%s)""",
               (snapshot, subject, stamp))


def test_research_archive_preserves_latest_per_entity_and_timestamp_ties(pg):
    for snapshot, subject, stamp in [('a1','a','2020-01-01Z'), ('a2','a','2020-01-02Z'),
                                     ('a3','a','2020-01-03Z'), ('b1','b','2020-01-01Z'),
                                     ('c1','c','2020-01-01Z'), ('c2','c','2020-01-01Z')]:
        research_snapshot(pg, snapshot, subject, stamp)
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    repo.check()
    cutoff = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=14)
    assert repo.preview('equity_research.outcomes', cutoff) == 3
    drive = MemoryDrive()
    result = run_batch(repo, drive, 'equity_research.outcomes', cutoff, delete=True)
    assert result['verified'] == result['deleted'] == 3
    assert pg.execute('SELECT snapshot_id FROM equity_research.outcomes ORDER BY snapshot_id').fetchall() == [
        ('a3',), ('b1',), ('c2',)]
    assert run_batch(repo, drive, 'equity_research.outcomes', cutoff, delete=True)['selected'] == 0
    with pytest.raises(RuntimeError):
        pg.execute('SELECT * FROM equity_research.observations')
    # Exact archived full-row JSON restores raw candle precision, not estimates.
    from drive_archive import verify_parquet, digest
    data = next(data for data, kind in drive.data.values() if kind == 'data')
    texts = verify_parquet(data, 'equity_research.outcomes', result['batch_id'], 3, digest(data))
    assert '1.123456789123456789' in texts[0]
    pg.execute('RESET ROLE')
    pg.execute('CREATE TEMP TABLE research_restore (LIKE equity_research.outcomes)')
    pg.execute('INSERT INTO research_restore SELECT * FROM '
               'jsonb_populate_record(NULL::equity_research.outcomes,%s::jsonb)', (texts[0],))
    assert pg.execute('SELECT count(*) FROM research_restore').fetchone()[0] == 1


def test_research_age_boundary_and_latest_are_enforced_by_trigger(pg):
    cutoff = pg.execute("SELECT (((statement_timestamp() AT TIME ZONE 'UTC')::date - 14)"
                        "::timestamp AT TIME ZONE 'UTC')").fetchone()[0]
    research_snapshot(pg, 'boundary', 'a', cutoff)
    research_snapshot(pg, 'newer', 'a', '2099-01-01Z')
    research_snapshot(pg, 'only-old', 'b', '2020-01-01Z')
    pg.execute('SET ROLE quant_archive_worker')
    for snapshot, message in [('boundary','retention window'), ('newer','retention window'),
                              ('only-old','Latest research outcome')]:
        with pytest.raises(RuntimeError, match=message):
            pg.execute('DELETE FROM equity_research.outcomes WHERE snapshot_id=%s', (snapshot,))
    assert pg.execute('SELECT count(*) FROM equity_research.outcomes').fetchone()[0] == 3


@pytest.mark.parametrize('role', ['equity_research_collector', 'quant_app_runtime'])
def test_research_trigger_blocks_other_callers_even_with_accidental_grants(pg, role):
    research_snapshot(pg, 'old', 'a', '2020-01-01Z')
    research_snapshot(pg, 'latest', 'a', '2020-01-02Z')
    pg.execute(f'GRANT USAGE ON SCHEMA equity_research TO {role}')
    pg.execute(f'GRANT SELECT,DELETE,UPDATE,TRUNCATE ON equity_research.outcomes TO {role}')
    pg.execute(f'CREATE POLICY accidental_access ON equity_research.outcomes TO {role} '
               'USING(true) WITH CHECK(true)')
    pg.execute(f'SET ROLE {role}')
    for sql in ["DELETE FROM equity_research.outcomes WHERE snapshot_id='old'",
                "UPDATE equity_research.outcomes SET payload='{}'", 'TRUNCATE equity_research.outcomes']:
        with pytest.raises(RuntimeError, match='append-only'):
            pg.execute(sql)


def test_archive_worker_cannot_mutate_other_research_tables_or_update_truncate(pg):
    research_snapshot(pg, 'old', 'a', '2020-01-01Z')
    # Accidental grants must still not bypass append-only triggers.
    for table in ('outcomes', 'observations', 'source_decisions'):
        pg.execute(f'GRANT SELECT,DELETE,UPDATE,TRUNCATE ON equity_research.{table} TO quant_archive_worker')
    pg.execute('SET ROLE quant_archive_worker')
    for sql in ['TRUNCATE equity_research.outcomes',
                "UPDATE equity_research.outcomes SET payload='{}'",
                'DELETE FROM equity_research.observations',
                'DELETE FROM equity_research.source_decisions']:
        with pytest.raises(RuntimeError, match='append-only'):
            pg.execute(sql)


def test_research_failed_verification_never_deletes_and_export_retry_is_safe(pg):
    research_snapshot(pg, 'old', 'a', '2020-01-01Z')
    research_snapshot(pg, 'latest', 'a', '2020-01-02Z')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    cutoff = dt.date(2026, 9, 10)
    for corrupt in ('data','manifest'):
        with pytest.raises(Exception):
            run_batch(repo, MemoryDrive(corrupt), 'equity_research.outcomes', cutoff, delete=True)
        assert pg.execute('SELECT count(*) FROM equity_research.outcomes').fetchone()[0] == 2
        assert pg.execute('SELECT count(*) FROM quant_app.archive_manifests').fetchone()[0] == 0
    from drive_archive import upload_verified
    manifest, texts = upload_verified(MemoryDrive(), 'equity_research.outcomes',
                                      repo.select('equity_research.outcomes', cutoff, 100))
    assert repo.acknowledge(manifest, texts, cutoff, False) == 0
    assert repo.acknowledge(manifest, texts, cutoff, True) == 1
    assert repo.acknowledge(manifest, texts, cutoff, True) == 0


def test_research_migration_rerunnable_and_disabled_guard_fails_check(pg):
    pg.send({'script': (ROOT / 'sql/drive_archive_research_outcomes_draft.sql').read_text()})
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    repo.check()
    pg.execute('RESET ROLE')
    pg.execute('ALTER TABLE equity_research.outcomes DISABLE TRIGGER outcome_archive_row_guard')
    pg.execute('SET ROLE quant_archive_worker')
    with pytest.raises(Exception, match='RESEARCH_ARCHIVE_GUARDS_REQUIRED'):
        repo.check()


def test_bulk_research_delete_cannot_remove_last_snapshot_or_partially_commit(pg):
    research_snapshot(pg, 'old', 'a', '2020-01-01Z')
    research_snapshot(pg, 'latest', 'a', '2020-01-02Z')
    pg.execute('SET ROLE quant_archive_worker')
    with pytest.raises(RuntimeError, match='Latest research outcome'):
        pg.execute('DELETE FROM equity_research.outcomes')
    assert pg.execute('SELECT count(*) FROM equity_research.outcomes').fetchone()[0] == 2


def test_forged_cutoff_cannot_shorten_db_retention_and_manifest_rolls_back(pg):
    now = pg.execute('SELECT clock_timestamp()').fetchone()[0]
    research_snapshot(pg, 'recent', 'a', now)
    research_snapshot(pg, 'future', 'a', '2099-01-01Z')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    with pytest.raises(RuntimeError, match='retention window'):
        run_batch(repo, MemoryDrive(), 'equity_research.outcomes', dt.date(2090,1,1), delete=True)
    assert pg.execute('SELECT count(*) FROM equity_research.outcomes').fetchone()[0] == 2
    assert pg.execute('SELECT count(*) FROM quant_app.archive_manifests').fetchone()[0] == 0


def test_collector_remains_append_only_and_archive_cannot_append(pg):
    research_snapshot(pg, 'old', 'a', '2020-01-01Z')
    pg.execute('SET ROLE equity_research_collector')
    pg.execute("INSERT INTO equity_research.outcomes VALUES ('new','a','{}',clock_timestamp())")
    assert pg.execute('SELECT count(*) FROM equity_research.outcomes').fetchone()[0] == 2
    pg.execute('SET ROLE quant_archive_worker')
    with pytest.raises(RuntimeError, match='permission denied'):
        pg.execute("INSERT INTO equity_research.outcomes VALUES ('forbidden','a','{}',clock_timestamp())")
