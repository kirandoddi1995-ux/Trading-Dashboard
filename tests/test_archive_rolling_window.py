"""Rolling window (ROLLING_WINDOW_2026-11-07.md): ledger export (never deleted), incremental proof,
and a time-bounded prune scoped to the batches that proof deep-checked.

Synthetic Drive and the PGlite harness only; no hosted connection.
"""
import datetime as dt
import json
import os
from pathlib import Path
import time

import pytest

import archive_maintenance as maintenance
import archive_restore_check as restore_check
from archive_maintenance import ArchiveRepository
from drive_archive import APPEND_ONLY, ArchiveError, SPECS
import test_archive_maintenance_sql as sql_harness
from test_archive_restore_check import ListedDrive

pg = sql_harness.pg
needs_sql = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                               reason='Local SQL harness not configured')
ROOT = Path(__file__).resolve().parents[1]
LEDGER = 'evidence_ledger_events'
CUTOFF = dt.date(2026, 9, 13)
TODAY = CUTOFF + dt.timedelta(days=maintenance.HOT_RETENTION_DAYS)


def _ledger(pg):
    """Replace the harness placeholder with the real ledger shape and its append-only triggers."""
    columns = ','.join(f'{name} {kind}' for name, kind in SPECS[LEDGER].items())
    pg.send({'script': f"""
        DROP TABLE quant_app.evidence_ledger_events;
        CREATE TABLE quant_app.evidence_ledger_events ({columns}, PRIMARY KEY(event_id),
            UNIQUE(aggregate_id,sequence_no), UNIQUE(idempotency_key), UNIQUE(event_hash));
        CREATE FUNCTION quant_app.reject_evidence_ledger_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'append only'; END $$;
        CREATE TRIGGER evidence_ledger_no_delete BEFORE DELETE ON quant_app.evidence_ledger_events
            FOR EACH ROW EXECUTE FUNCTION quant_app.reject_evidence_ledger_mutation();
        CREATE TRIGGER evidence_ledger_no_update BEFORE UPDATE ON quant_app.evidence_ledger_events
            FOR EACH ROW EXECUTE FUNCTION quant_app.reject_evidence_ledger_mutation();
    """})
    pg.send({'script': (ROOT / 'sql/drive_archive_ledger_export_draft.sql').read_text()})


def _event(pg, n, recorded, size=10):
    pg.execute("""INSERT INTO quant_app.evidence_ledger_events VALUES
        (%s::uuid,%s,%s,'DECISION_EVALUATED',%s::timestamptz,%s::timestamptz,'test','actor',%s,
         %s::jsonb,%s,%s,'sha256',1,NULL)""",
               (f'00000000-0000-0000-0000-{n:012d}', 'agg', n, recorded, recorded, f'idem-{n}',
                json.dumps({'n': n, 'pad': 'x' * size, 'price': 1.123456789123456789}),
                f'prev-{n}', f'hash-{n}'))


def _count(pg, sql):
    return pg.execute(sql).fetchone()[0]


def _archived_ledger_rows(pg):
    return _count(pg, f"SELECT coalesce(sum(row_count),0) FROM quant_app.archive_manifests "
                      f"WHERE source_table='{LEDGER}'")


@needs_sql
def test_ledger_exports_closed_days_once_each_and_is_never_deleted(pg):
    _ledger(pg)
    for n, stamp in enumerate(['2026-09-01T08:00:00+00', '2026-09-01T20:00:00+00',
                               '2026-09-02T09:00:00+00', '2026-09-03T09:00:00+00'], 1):
        _event(pg, n, stamp)
    pg.execute('SET ROLE quant_archive_worker')
    repo, drive = ArchiveRepository('postgres://test-only'), ListedDrive()
    repo.check(readable=(LEDGER,))
    # Only 1 Sep is closed: one batch of both its events.
    first = maintenance.export_batches(repo, drive, LEDGER, dt.date(2026, 9, 2), 500, 10)
    assert [r['selected'] for r in first] == [2] and first[0]['custody_probe'] == 'ok'
    # 2 Sep closes later. A page never crosses a UTC day, so the 1 Sep batch is unchanged (passed
    # over) and no event is archived twice.
    second = maintenance.export_batches(repo, drive, LEDGER, dt.date(2026, 9, 3), 500, 10)
    assert [r['selected'] for r in second] == [1]
    assert _archived_ledger_rows(pg) == 3
    assert maintenance.export_batches(repo, drive, LEDGER, dt.date(2026, 9, 3), 500, 10) == []
    assert _count(pg, 'SELECT count(*) FROM quant_app.evidence_ledger_events') == 4
    # Deletion is refused before any proof, custody or connection is consulted.
    texts = repo.select(LEDGER, dt.date(2026, 9, 2), 500)
    manifest = {'batch_id': first[0]['batch_id'], 'source_table': LEDGER, 'rows': 2}
    with pytest.raises(ArchiveError, match='APPEND_ONLY_NEVER_DELETED'):
        repo.acknowledge(manifest, texts, dt.date(2026, 9, 2), True)
    assert _count(pg, 'SELECT count(*) FROM quant_app.evidence_ledger_events') == 4


@needs_sql
def test_ledger_pages_split_at_the_stored_byte_budget_and_stay_stable(pg, monkeypatch):
    _ledger(pg)
    for n in range(1, 6):
        _event(pg, n, f'2026-09-01T0{n}:00:00+00', size=3000)
    pg.execute('SET ROLE quant_archive_worker')
    repo, drive = ArchiveRepository('postgres://test-only'), ListedDrive()
    size = _count(pg, 'SELECT max(pg_column_size(payload)) FROM quant_app.evidence_ledger_events')
    monkeypatch.setattr(maintenance, 'LEDGER_PAGE_STORED_BYTES', 2 * size)
    exported = maintenance.export_batches(repo, drive, LEDGER, dt.date(2026, 9, 2), 500, 10)
    assert [r['selected'] for r in exported] == [2, 2, 1]
    assert maintenance.export_batches(repo, drive, LEDGER, dt.date(2026, 9, 2), 500, 10) == []
    # A single event larger than the budget still forms a page of one.
    monkeypatch.setattr(maintenance, 'LEDGER_PAGE_STORED_BYTES', 1)
    assert len(repo.select(LEDGER, dt.date(2026, 9, 2), 500)) == 1


@needs_sql
def test_ledger_export_needs_the_read_grant_and_no_write_grant(pg):
    _ledger(pg)
    pg.execute('REVOKE SELECT ON quant_app.evidence_ledger_events FROM quant_archive_worker')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    repo.check()  # other modes do not need the ledger
    with pytest.raises(ArchiveError, match='ARCHIVE_LEDGER_SELECT_GRANT_MISSING'):
        repo.check(readable=(LEDGER,))
    pg.execute('RESET ROLE')
    pg.execute('GRANT SELECT,DELETE ON quant_app.evidence_ledger_events TO quant_archive_worker')
    pg.execute('SET ROLE quant_archive_worker')
    with pytest.raises(ArchiveError, match='ARCHIVE_APPEND_ONLY_WRITE_GRANT_FORBIDDEN'):
        repo.check()


@needs_sql
def test_preserved_candidates_never_include_ledger_batches(pg):
    _ledger(pg)
    _event(pg, 1, '2026-09-01T08:00:00+00')
    pg.execute('SET ROLE quant_archive_worker')
    repo, drive = ArchiveRepository('postgres://test-only'), ListedDrive()
    maintenance.export_batches(repo, drive, LEDGER, dt.date(2026, 9, 2), 500, 10)
    before = repo.database_now()
    expected = repo.generation(before)
    assert expected[0] == 1
    assert repo.preserved_candidates(before, 10, expected, (LEDGER, 'mf_nav')) == []


def _nav(pg, dates):
    for day in dates:
        sql_harness.insert_nav(pg, 'A', day)


def _activate(proof):
    maintenance.activate_restore_proof(proof)
    return proof


@needs_sql
def test_incremental_proof_deep_checks_new_and_unpruned_batches_only(pg):
    _nav(pg, ('2026-08-01', '2026-08-02', '2026-08-03', '2026-08-04', '2026-08-05'))
    pg.execute('SET ROLE quant_archive_worker')
    repo, drive = ArchiveRepository('postgres://test-only'), ListedDrive()
    # An earlier cycle: two batches, of which a time-bounded prune pruned only the first.
    maintenance.export_batches(repo, drive, 'mf_nav', CUTOFF, 1, 2)
    previous = repo.database_now()
    count, fingerprint = repo.generation(previous)
    proof = restore_check.prove(repo, drive, today=TODAY, everything=True)
    try:
        _activate(proof)
        assert len(maintenance.prune_preserved(repo, drive, proof, before=previous, expected_batches=count,
                                               expected_sha256=fingerprint, today=TODAY, limit=1)) == 1
    finally:
        maintenance._ACTIVE_PROOF = None
    # This cycle: two new batches, proven after the previous generation.
    maintenance.export_batches(repo, drive, 'mf_nav', CUTOFF, 1, 10)
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    proof = restore_check.prove(repo, drive, today=TODAY, everything=True, deep_after=previous)
    assert proof.valid_now() and proof.manifests == 4 and proof.presence_verified == 4
    # The pruned batch is not deep-checked again; the stranded pending one is.
    assert proof.deep_batches == 3 and len(proof.deep_ids) == 3
    assert proof.summary()['deep_after'] == previous.isoformat()
    try:
        _activate(proof)
        pruned = maintenance.prune_preserved(repo, drive, proof, before=before, expected_batches=count,
                                             expected_sha256=fingerprint, today=TODAY, limit=50)
    finally:
        maintenance._ACTIVE_PROOF = None
    assert [r['deleted'] for r in pruned] == [1, 1, 1]
    assert _count(pg, 'SELECT count(*) FROM quant_app.archive_manifests WHERE completed_at IS NULL') == 0
    assert [r[0] for r in pg.execute('SELECT nav_date::text FROM quant_app.mf_nav').fetchall()] == ['2026-08-05']


@needs_sql
def test_prune_refuses_a_candidate_the_proof_did_not_deep_check(pg):
    _nav(pg, ('2026-08-01', '2026-08-02'))
    pg.execute('SET ROLE quant_archive_worker')
    repo, drive = ArchiveRepository('postgres://test-only'), ListedDrive()
    maintenance.export_batches(repo, drive, 'mf_nav', CUTOFF, 1, 10)
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    proof = restore_check.RestoreProof(manifests=0, presence_verified=0, deep_batches=0, deep_rows=0,
                                       exact_rows=0, added_column_rows=0, failures=(),
                                       issuer=restore_check._ISSUER,
                                       context=restore_check.context_key(repo, drive), deep_ids=frozenset())
    try:
        _activate(proof)
        with pytest.raises(ArchiveError, match='BATCH_NOT_DEEP_PROVEN'):
            maintenance.prune_preserved(repo, drive, proof, before=before, expected_batches=count,
                                        expected_sha256=fingerprint, today=TODAY, limit=50)
    finally:
        maintenance._ACTIVE_PROOF = None
    assert _count(pg, 'SELECT count(*) FROM quant_app.mf_nav') == 2


@needs_sql
def test_prune_starts_no_batch_after_its_deadline(pg):
    _nav(pg, ('2026-08-01', '2026-08-02', '2026-08-03'))
    pg.execute('SET ROLE quant_archive_worker')
    repo, drive = ArchiveRepository('postgres://test-only'), ListedDrive()
    maintenance.export_batches(repo, drive, 'mf_nav', CUTOFF, 1, 10)
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    proof = restore_check.prove(repo, drive, today=TODAY, everything=True)
    reports = []
    try:
        _activate(proof)
        pruned = maintenance.prune_preserved(repo, drive, proof, before=before, expected_batches=count,
                                             expected_sha256=fingerprint, today=TODAY, limit=50,
                                             deadline=time.monotonic() - 1, report=reports.append)
    finally:
        maintenance._ACTIVE_PROOF = None
    assert pruned == [] and reports == [{'stopped': 'TIME_BOUND', 'pruned_batches': 0}]
    assert _count(pg, 'SELECT count(*) FROM quant_app.mf_nav') == 3


@pytest.mark.parametrize('argv,code', [
    (['--mode', 'prune-preserved', '--table', LEDGER, '--preserved-before', '2026-11-09T01:00:00+00:00',
      '--preserved-batches', '3', '--preserved-sha256', 'a' * 64], 'APPEND_ONLY_NEVER_DELETED'),
    (['--mode', 'delete', '--table', LEDGER], 'APPEND_ONLY_NEVER_DELETED'),
    (['--mode', 'export', '--table', 'growing', '--proven-after', '2026-11-05T00:00:00+00:00'],
     'PROVEN_AFTER_RESTORE_CHECK_OR_PRUNE_ONLY'),
    (['--mode', 'restore-check', '--proven-after', '2026-11-05T00:00:00'], 'PRESERVED_GENERATION_REQUIRED'),
    (['--mode', 'export', '--table', 'growing', '--max-minutes', '30'], 'INVALID_MAX_MINUTES'),
    (['--mode', 'prune-preserved', '--table', 'growing', '--max-minutes', '0'], 'INVALID_MAX_MINUTES'),
    (['--mode', 'prune-preserved', '--table', 'growing', '--max-minutes', '171'], 'INVALID_MAX_MINUTES'),
])
def test_rolling_inputs_are_refused_before_any_connection(argv, code, capsys, monkeypatch):
    monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', 'true')
    monkeypatch.delenv('ARCHIVE_DATABASE_URL', raising=False)
    assert maintenance.main(argv) == 1
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {
        'status': 'FAILED', 'error_category': code}


def test_the_ledger_is_append_only_and_not_in_the_growing_prune_set():
    assert APPEND_ONLY == {LEDGER} and LEDGER not in maintenance.GROWING_TABLES
    assert maintenance.export_cutoff(LEDGER, TODAY) == TODAY - dt.timedelta(days=1)
    assert maintenance.ORDER_COLUMNS[LEDGER] == ('recorded_at', 'event_id')
    # No deletion retention exists for it at all.
    for policy in (lambda: maintenance.cutoff_for(LEDGER, TODAY), lambda: maintenance.predicate(LEDGER)):
        with pytest.raises(ArchiveError, match='UNSUPPORTED_TABLE'):
            policy()


def test_recovery_review_mirrors_every_deletable_archive_table():
    import archive_recovery_review as review
    assert review.SPECS == {table: spec for table, spec in SPECS.items() if table not in APPEND_ONLY}


def test_dispatched_rolling_prune_passes_the_scope_and_time_bound(monkeypatch):
    from unittest.mock import Mock
    from test_archive_commissioning_hold import _launcher
    _, script = _launcher()
    monkeypatch.setenv('EVENT_NAME', 'workflow_dispatch')
    for name, value in {'REQUESTED_MODE': 'prune-preserved', 'REQUESTED_TABLE': 'growing',
                        'REQUESTED_MAX_BATCHES': '200', 'PRESERVED_BEFORE': '2026-11-09T01:02:03.456789+00:00',
                        'PRESERVED_BATCHES': '1100', 'PRESERVED_SHA256': 'b' * 64,
                        'PROVEN_AFTER': '2026-11-05T00:00:00+00:00', 'MAX_MINUTES': '150'}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv('NAV_CUTOFF', raising=False)
    monkeypatch.delenv('REQUESTED_BATCH_SIZE', raising=False)
    main = Mock(return_value=0)
    monkeypatch.setattr(maintenance, 'main', main)
    with pytest.raises(SystemExit):
        exec(compile(script, '<synthetic-workflow>', 'exec'), {})
    main.assert_called_once_with(['--mode', 'prune-preserved', '--table', 'growing', '--max-batches', '200',
                                  '--preserved-before', '2026-11-09T01:02:03.456789+00:00',
                                  '--preserved-batches', '1100', '--preserved-sha256', 'b' * 64,
                                  '--max-minutes', '150', '--proven-after', '2026-11-05T00:00:00+00:00'])


@needs_sql
def test_ledger_batches_pass_the_restore_proof_exactly(pg):
    _ledger(pg)
    for n in range(1, 4):
        _event(pg, n, f'2026-09-01T0{n}:00:00.123456+00', size=50)
    pg.execute('SET ROLE quant_archive_worker')
    repo, drive = ArchiveRepository('postgres://test-only'), ListedDrive()
    maintenance.export_batches(repo, drive, LEDGER, dt.date(2026, 9, 2), 500, 10)
    proof = restore_check.prove(repo, drive, today=TODAY, everything=True)
    assert proof.valid_now(), proof.summary()
    assert proof.deep_rows == proof.exact_rows == 3
