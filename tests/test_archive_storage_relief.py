"""Offline regression coverage for reviewed seven/fourteen-day storage relief."""
import datetime as dt
import os
from pathlib import Path

import pytest

from archive_maintenance import ArchiveRepository, batch_size_for, cutoff_for, run_batch
from drive_archive import SPECS, upload_verified, verify_parquet, digest
import test_archive_maintenance_sql as sql_harness
from test_archive_maintenance_sql import scanner, research_snapshot
from test_drive_archive import MemoryDrive

ROOT = Path(__file__).resolve().parents[1]
pg = sql_harness.pg
pytestmark = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                                reason='Local SQL harness not configured')


def canonical(db, day, *, complete=True, observed=None):
    observed = observed or day + 'T00:00:00Z'
    db.execute('INSERT INTO quant_app.universe_snapshots VALUES (%s,%s,%s)',
               (day, observed, complete))
    db.execute("""INSERT INTO quant_app.universe_membership
        (snapshot_date,instrument_key,trading_symbol,observed_at,source,raw)
        VALUES (%s,'K','SYMBOL',%s,'original','{"precision":1.123456789123456789}')""",
               (day, observed))


def test_only_outcomes_get_seven_days():
    today = dt.date(2026, 9, 30)
    for table in SPECS:
        assert cutoff_for(table, today) == today - dt.timedelta(
            days=7 if table == 'equity_research.outcomes' else 14)


def test_per_source_batch_defaults_and_bounds():
    from drive_archive import ArchiveError
    assert batch_size_for('equity_research.outcomes') == 100
    assert batch_size_for('universe_membership') == 500
    assert batch_size_for('market_quotes') == 1000
    for size in (1, 50, 2000):
        assert batch_size_for('equity_research.outcomes', size) == size
    for size in (-1, 0, 2001):
        with pytest.raises(ArchiveError, match='INVALID_BATCH_LIMIT'):
            batch_size_for('equity_research.outcomes', size)


def test_migration_stops_for_other_effective_reader(pg):
    pg.execute('CREATE ROLE extra_reader')
    pg.execute('GRANT USAGE ON SCHEMA quant_app TO extra_reader')
    pg.execute('GRANT SELECT(instrument_key) ON quant_app.universe_membership TO extra_reader')
    pg.execute('ALTER TABLE quant_app.universe_membership DISABLE ROW LEVEL SECURITY')
    with pytest.raises(RuntimeError, match='Unreviewed canonical reader'):
        pg.send({'script': (ROOT / 'sql/drive_archive_storage_relief_draft.sql').read_text()})
    pg.execute('ROLLBACK')
    assert pg.execute("SELECT relrowsecurity FROM pg_class WHERE oid='quant_app.universe_membership'::regclass").fetchone()[0] is False


def test_scanner_dependency_index_is_narrow_and_valid(pg):
    row = pg.execute("""SELECT i.indisvalid,i.indisready,i.indnkeyatts,a.attname
        FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=i.indkey[0]
        WHERE i.indexrelid='quant_app.scanner_universe_snapshot_date_idx'::regclass""").fetchone()
    assert row == (True, True, 1, 'universe_snapshot_date')


def test_relief_diagnostics_execute_read_only(pg):
    sql = (ROOT / 'sql/storage_relief_checks_read_only.sql').read_text()
    pg.send({'script': 'BEGIN READ ONLY;\n' + sql + '\nROLLBACK;'})
    extra = (ROOT / 'sql/storage_relief_access_checks_read_only.sql').read_text()
    pg.send({'script': "BEGIN READ ONLY; SET LOCAL statement_timeout='5s';\n" + extra + '\nROLLBACK;'})


def test_new_seven_day_policy_archives_eight_day_incomplete_not_latest(pg):
    old = pg.execute("SELECT clock_timestamp()-interval '8 days'").fetchone()[0]
    research_snapshot(pg, 'old', 'a', old)
    research_snapshot(pg, 'latest', 'a', '2099-01-01Z')
    research_snapshot(pg, 'only', 'b', old)
    pg.execute('SET ROLE quant_archive_worker')
    result = run_batch(ArchiveRepository('postgres://test'), MemoryDrive(),
                       'equity_research.outcomes', cutoff_for('equity_research.outcomes',
                       dt.datetime.now(dt.timezone.utc).date()), delete=True)
    assert result['deleted'] == 1
    assert pg.execute('SELECT snapshot_id FROM equity_research.outcomes ORDER BY 1').fetchall() == [('latest',), ('only',)]


def test_canonical_export_restore_dependencies_latest_and_complete(pg):
    for day, complete in [('2020-01-01', True), ('2020-01-02', True),
                          ('2020-01-03', True), ('2020-01-04', False)]:
        canonical(pg, day, complete=complete)
    scanner(pg, 'dependent', day='2020-01-02', passed=True)
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test')
    repo.check()
    cutoff = dt.date(2026, 9, 16)
    assert repo.preview('universe_membership', cutoff) == 1
    drive = MemoryDrive()
    result = run_batch(repo, drive, 'universe_membership', cutoff, delete=True)
    assert result['verified'] == result['deleted'] == 1
    assert run_batch(repo, drive, 'universe_membership', cutoff, delete=True)['selected'] == 0
    assert pg.execute('SELECT count(*) FROM quant_app.universe_snapshots').fetchone()[0] == 4
    data = next(data for data, kind in drive.data.values() if kind == 'data')
    texts = verify_parquet(data, 'universe_membership', result['batch_id'], 1, digest(data))
    pg.execute('RESET ROLE')
    pg.execute('CREATE TEMP TABLE restored (LIKE quant_app.universe_membership)')
    pg.execute('INSERT INTO restored SELECT * FROM jsonb_populate_record('
               'NULL::quant_app.universe_membership,%s::jsonb)', (texts[0],))
    assert pg.execute("SELECT raw->>'precision' FROM restored").fetchone()[0] == '1.123456789123456789'


@pytest.mark.parametrize('change', ['payload', 'dependency', 'new_header_time'])
def test_canonical_rechecks_after_remote_export(pg, change):
    canonical(pg, '2020-01-01')
    canonical(pg, '2020-01-02')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test')
    cutoff = dt.date(2026, 9, 16)
    manifest, texts = upload_verified(MemoryDrive(), 'universe_membership',
                                      repo.select('universe_membership', cutoff, 10))
    pg.execute('RESET ROLE')
    if change == 'payload':
        pg.execute("UPDATE quant_app.universe_membership SET raw='{}' WHERE snapshot_date='2020-01-01'")
    elif change == 'dependency':
        scanner(pg, 'late', day='2020-01-01')
    else:
        pg.execute("UPDATE quant_app.universe_snapshots SET observed_at=clock_timestamp() WHERE snapshot_date='2020-01-01'")
    pg.execute('SET ROLE quant_archive_worker')
    assert repo.acknowledge(manifest, texts, cutoff, True) == 0
    assert pg.execute('SELECT count(*) FROM quant_app.universe_membership').fetchone()[0] == 2


@pytest.mark.parametrize('failure', ['data', 'manifest'])
def test_canonical_verification_failure_never_deletes(pg, failure):
    canonical(pg, '2020-01-01')
    canonical(pg, '2020-01-02')
    pg.execute('SET ROLE quant_archive_worker')
    with pytest.raises(Exception):
        run_batch(ArchiveRepository('postgres://test'), MemoryDrive(failure),
                  'universe_membership', dt.date(2026, 9, 16), delete=True)
    assert pg.execute('SELECT count(*) FROM quant_app.universe_membership').fetchone()[0] == 2


def test_canonical_trigger_boundary_and_no_complete_snapshot_fail_closed(pg):
    day = pg.execute("SELECT ((clock_timestamp() AT TIME ZONE 'UTC')::date-14)::text").fetchone()[0]
    canonical(pg, day)
    canonical(pg, '2099-01-01')
    canonical(pg, '2020-01-01')
    pg.execute('SET ROLE quant_archive_worker')
    with pytest.raises(RuntimeError, match='protected'):
        pg.execute('DELETE FROM quant_app.universe_membership WHERE snapshot_date=%s', (day,))
    pg.execute('RESET ROLE')
    pg.execute('UPDATE quant_app.universe_snapshots SET is_complete=false')
    pg.execute('SET ROLE quant_archive_worker')
    with pytest.raises(RuntimeError, match='protected'):
        pg.execute("DELETE FROM quant_app.universe_membership WHERE snapshot_date='2020-01-01'")


def test_canonical_privileges_guard_and_runtime_replacement(pg):
    canonical(pg, '2020-01-01')
    pg.execute('SET ROLE equity_research_collector')
    with pytest.raises(RuntimeError):
        pg.execute('SELECT * FROM quant_app.universe_membership')
    with pytest.raises(RuntimeError):
        pg.execute('SELECT quant_app.lock_canonical_archive_dependencies()')
    pg.execute('SET ROLE quant_archive_worker')
    for sql in ['DELETE FROM quant_app.universe_snapshots',
                'TRUNCATE quant_app.universe_membership',
                "UPDATE quant_app.universe_membership SET raw='{}'"]:
        with pytest.raises(RuntimeError):
            pg.execute(sql)
    pg.execute('SET ROLE quant_app_runtime')
    pg.execute("DELETE FROM quant_app.universe_membership WHERE snapshot_date='2020-01-01'")
    pg.execute('RESET ROLE')
    pg.execute('ALTER TABLE quant_app.universe_membership DISABLE TRIGGER canonical_archive_row_guard')
    pg.execute('SET ROLE quant_archive_worker')
    with pytest.raises(Exception, match='CANONICAL_ARCHIVE_GUARDS_REQUIRED'):
        ArchiveRepository('postgres://test').check()


@pytest.mark.parametrize('staging_failure', [False, True])
def test_canonical_staging_precedes_locks(pg, monkeypatch, staging_failure):
    canonical(pg, '2020-01-01')
    canonical(pg, '2020-01-02')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test')
    cutoff = dt.date(2026, 9, 16)
    manifest, texts = upload_verified(MemoryDrive(), 'universe_membership',
                                      repo.select('universe_membership', cutoff, 10))
    statements = []
    original = pg.execute

    def execute(sql, params=()):
        statements.append(sql)
        if staging_failure and sql.startswith('INSERT INTO verified_archive_rows'):
            raise RuntimeError('staging failure')
        return original(sql, params)

    monkeypatch.setattr(pg, 'execute', execute)
    if staging_failure:
        with pytest.raises(RuntimeError, match='staging failure'):
            repo.acknowledge(manifest, texts, cutoff, True)
        assert not any('lock_canonical_archive_dependencies' in sql for sql in statements)
        assert pg.execute('SELECT count(*) FROM quant_app.universe_membership').fetchone()[0] == 2
    else:
        assert repo.acknowledge(manifest, texts, cutoff, True) == 1
        stage = next(i for i, sql in enumerate(statements) if sql.startswith('INSERT INTO verified_archive_rows'))
        lock = next(i for i, sql in enumerate(statements) if 'lock_canonical_archive_dependencies' in sql)
        delete = next(i for i, sql in enumerate(statements) if 'WITH removed AS' in sql)
        assert stage < lock < delete
