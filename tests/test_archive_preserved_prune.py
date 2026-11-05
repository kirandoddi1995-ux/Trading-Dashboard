"""Bulk export (keyset paging, no deletion) and pruning of an independently preserved generation.

The prune deletes only batches that (1) were recorded at or before a generation timestamp T,
(2) whose catalog prefix at T still has the exact count and fingerprint the owner verified on an
independent copy, (3) are not yet pruned, and (4) whose rows are rebuilt from the archive file
itself. Synthetic Drive and the PGlite harness only.
"""
import datetime as dt
import os

import pytest

import archive_maintenance as maintenance
import archive_restore_check as restore_check
import verify_local_archive_copy as verify
from archive_maintenance import ArchiveRepository
from drive_archive import ArchiveError
import test_archive_maintenance_sql as sql_harness
from test_archive_restore_check import ListedDrive

pg = sql_harness.pg
# Only the SQL tests need the harness; argument and workflow-launcher tests always run.
needs_sql = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                               reason='Local SQL harness not configured')
CUTOFF = dt.date(2026, 9, 13)
TODAY = CUTOFF + dt.timedelta(days=maintenance.HOT_RETENTION_DAYS)


def _setup(pg, dates=('2026-08-01', '2026-08-02', '2026-08-03', '2026-08-04')):
    for day in dates:
        sql_harness.insert_nav(pg, 'A', day)
    pg.execute('SET ROLE quant_archive_worker')
    return ArchiveRepository('postgres://test-only'), ListedDrive()


def _count(pg, sql):
    return pg.execute(sql).fetchone()[0]


def _proof(repo, drive):
    proof = restore_check.RestoreProof(manifests=0, presence_verified=0, deep_batches=0, deep_rows=0,
                                       exact_rows=0, added_column_rows=0, failures=(),
                                       issuer=restore_check._ISSUER,
                                       context=restore_check.context_key(repo, drive))
    maintenance.activate_restore_proof(proof)
    return proof


def _export(repo, drive, max_batches=10):
    return maintenance.export_batches(repo, drive, 'mf_nav', CUTOFF, 1, max_batches)


@needs_sql
def test_bulk_export_pages_through_eligible_rows_without_deleting_and_is_idempotent(pg):
    repo, drive = _setup(pg)
    first = _export(repo, drive)
    # 08-04 is the latest NAV for scheme A and is never eligible.
    assert [r['selected'] for r in first] == [1, 1, 1] and all(r['deleted'] == 0 for r in first)
    assert len({r['batch_id'] for r in first}) == 3
    assert all(r['custody_probe'] == 'ok' for r in first)
    assert _count(pg, 'SELECT count(*) FROM quant_app.mf_nav') == 4
    assert _count(pg, 'SELECT count(*) FROM quant_app.archive_manifests') == 3
    # Same rows, same content-addressed batches: already in the catalog, so nothing new.
    assert _export(repo, drive) == []
    assert _count(pg, 'SELECT count(*) FROM quant_app.archive_manifests') == 3


@needs_sql
def test_generation_fingerprint_equals_the_copy_verifier_fingerprint(pg):
    repo, drive = _setup(pg)
    _export(repo, drive)
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    rows = pg.execute('SELECT batch_id,source_table,row_count,file_sha256,drive_file_id '
                      'FROM quant_app.archive_manifests').fetchall()
    entries = [dict(zip(('batch_id', 'source_table', 'row_count', 'file_sha256', 'drive_file_id'), r))
               for r in rows]
    assert count == 3 and fingerprint == verify.inventory_set_sha256(entries)


@needs_sql
def test_prune_deletes_exactly_the_preserved_generation_and_nothing_recorded_later(pg):
    repo, drive = _setup(pg)
    _export(repo, drive)
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    # A later row makes 08-04 eligible; its batch is recorded after T and is not preserved.
    pg.execute('RESET ROLE')
    sql_harness.insert_nav(pg, 'A', '2026-08-05')
    pg.execute('SET ROLE quant_archive_worker')
    later = _export(repo, drive)
    assert len(later) == 1  # only the newly eligible 08-04 batch; earlier pages are already recorded
    proof = _proof(repo, drive)
    try:
        pruned = maintenance.prune_preserved(repo, drive, proof, before=before, expected_batches=count,
                                             expected_sha256=fingerprint, today=TODAY, limit=50)
    finally:
        maintenance._ACTIVE_PROOF = None
    assert [r['deleted'] for r in pruned] == [1, 1, 1]
    remaining = [r[0] for r in pg.execute('SELECT nav_date::text FROM quant_app.mf_nav ORDER BY 1').fetchall()]
    assert remaining == ['2026-08-04', '2026-08-05']
    assert _count(pg, 'SELECT count(*) FROM quant_app.archive_manifests WHERE completed_at IS NOT NULL') == 3
    assert _count(pg, 'SELECT count(*) FROM quant_app.archive_manifests WHERE completed_at IS NULL') == 1
    # A second run finds nothing left to prune in that generation.
    proof = _proof(repo, drive)
    try:
        assert maintenance.prune_preserved(repo, drive, proof, before=before, expected_batches=count,
                                           expected_sha256=fingerprint, today=TODAY, limit=50) == []
    finally:
        maintenance._ACTIVE_PROOF = None


@needs_sql
@pytest.mark.parametrize('wrong', ['count', 'fingerprint', 'later_time'])
def test_prune_refuses_any_generation_mismatch_before_touching_anything(pg, wrong):
    repo, drive = _setup(pg)
    _export(repo, drive, max_batches=2)
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    if wrong == 'later_time':
        _export(repo, drive)  # a third batch recorded after T ...
        before = repo.database_now()  # ... is inside a later T, so the verified pair no longer matches
    kwargs = {'before': before, 'expected_batches': count + (wrong == 'count'),
              'expected_sha256': ('0' * 64) if wrong == 'fingerprint' else fingerprint}
    proof = _proof(repo, drive)
    try:
        with pytest.raises(ArchiveError, match='PRESERVED_GENERATION_MISMATCH'):
            maintenance.prune_preserved(repo, drive, proof, today=TODAY, limit=50, **kwargs)
    finally:
        maintenance._ACTIVE_PROOF = None
    assert _count(pg, 'SELECT count(*) FROM quant_app.mf_nav') == 4
    assert _count(pg, 'SELECT count(*) FROM quant_app.archive_manifests WHERE completed_at IS NOT NULL') == 0


@needs_sql
def test_prune_without_an_active_restore_proof_deletes_nothing(pg):
    repo, drive = _setup(pg)
    _export(repo, drive)
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    proof = restore_check.RestoreProof(manifests=0, presence_verified=0, deep_batches=0, deep_rows=0,
                                       exact_rows=0, added_column_rows=0, failures=(),
                                       issuer=restore_check._ISSUER,
                                       context=restore_check.context_key(repo, drive))
    with pytest.raises(ArchiveError, match='AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED'):
        maintenance.prune_preserved(repo, drive, proof, before=before, expected_batches=count,
                                    expected_sha256=fingerprint, today=TODAY, limit=50)
    assert _count(pg, 'SELECT count(*) FROM quant_app.mf_nav') == 4


@needs_sql
def test_prune_rebuilds_rows_from_the_archive_and_stops_on_a_damaged_file(pg):
    repo, drive = _setup(pg)
    batches = _export(repo, drive)
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    first = pg.execute('SELECT drive_file_id FROM quant_app.archive_manifests '
                       'ORDER BY verified_at, batch_id LIMIT 1').fetchone()[0]
    body, kind = drive.data[first]
    drive.data[first] = (body[:-9] + bytes([body[-9] ^ 1]) + body[-8:], kind)
    proof = _proof(repo, drive)
    try:
        with pytest.raises(ArchiveError):
            maintenance.prune_preserved(repo, drive, proof, before=before, expected_batches=count,
                                        expected_sha256=fingerprint, today=TODAY, limit=50)
    finally:
        maintenance._ACTIVE_PROOF = None
    assert len(batches) == 3 and _count(pg, 'SELECT count(*) FROM quant_app.mf_nav') == 4


@needs_sql
def test_prune_stops_for_review_when_a_source_row_changed_since_export(pg):
    repo, drive = _setup(pg)
    maintenance.export_batches(repo, drive, 'mf_nav', CUTOFF, 2, 10)
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    pg.execute('RESET ROLE')
    pg.execute("UPDATE quant_app.mf_nav SET nav = 2 WHERE nav_date = '2026-08-01'")
    pg.execute('SET ROLE quant_archive_worker')
    proof = _proof(repo, drive)
    try:
        with pytest.raises(ArchiveError, match='SOURCE_CHANGED_OR_ALREADY_REMOVED_REVIEW_REQUIRED'):
            maintenance.prune_preserved(repo, drive, proof, before=before, expected_batches=count,
                                        expected_sha256=fingerprint, today=TODAY, limit=50)
    finally:
        maintenance._ACTIVE_PROOF = None
    # Both rows in the failing batch survive, including the unchanged row.
    assert _count(pg, 'SELECT count(*) FROM quant_app.mf_nav') == 4
    assert _count(pg, 'SELECT count(*) FROM quant_app.archive_manifests WHERE completed_at IS NOT NULL') == 0


@needs_sql
def test_prune_binds_generation_and_candidates_in_one_statement(pg, monkeypatch):
    repo, drive = _setup(pg)
    _export(repo, drive)
    before = repo.database_now()
    expected = repo.generation(before)
    statements = []
    original = pg.execute

    def record(sql, params=()):
        if 'archive_manifests' in sql:
            statements.append(sql)
        return original(sql, params)

    monkeypatch.setattr(pg, 'execute', record)
    candidates = repo.preserved_candidates(before, 2, expected, ('mf_nav',))
    assert len(candidates) == 2
    assert len(statements) == 1
    assert 'string_agg' in statements[0] and 'completed_at IS NULL' in statements[0]
    assert repo.preserved_candidates(before, 2, expected, ('market_quotes',)) == []


@pytest.mark.parametrize('argv', [
    ['--mode', 'prune-preserved'],
    ['--mode', 'prune-preserved', '--preserved-before', '2026-11-05T10:00:00',
     '--preserved-batches', '3', '--preserved-sha256', 'a' * 64],  # naive time
    ['--mode', 'prune-preserved', '--preserved-before', '2026-11-05T10:00:00+05:30',
     '--preserved-batches', '0', '--preserved-sha256', 'a' * 64],
    ['--mode', 'prune-preserved', '--preserved-before', '2026-11-05T10:00:00+05:30',
     '--preserved-batches', '3', '--preserved-sha256', 'xyz'],
])
def test_prune_mode_requires_the_full_generation_inputs(argv, capsys, monkeypatch):
    import json
    monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', 'true')
    assert maintenance.main(argv) == 1
    # Refused for the missing generation, before any database or Drive connection.
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {
        'status': 'FAILED', 'error_category': 'PRESERVED_GENERATION_REQUIRED'}


def test_the_nightly_schedule_cannot_reach_prune_mode():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/drive-archive.yml').read_text()
    scheduled = workflow[workflow.index("if os.environ['EVENT_NAME'] == 'schedule':"):
                         workflow.index("if os.environ['EVENT_NAME'] != 'workflow_dispatch':")]
    assert "'--mode', 'delete'" in scheduled and 'prune' not in scheduled
    assert 'preserved' not in scheduled


def test_dispatched_prune_passes_exactly_the_owner_inputs(monkeypatch):
    from unittest.mock import Mock
    from test_archive_commissioning_hold import _launcher
    _, script = _launcher()
    monkeypatch.setenv('EVENT_NAME', 'workflow_dispatch')
    for name, value in {'REQUESTED_MODE': 'prune-preserved', 'REQUESTED_TABLE': 'growing',
                        'REQUESTED_MAX_BATCHES': '50', 'PRESERVED_BEFORE': '2026-11-05 10:32:17.265431+00',
                        'PRESERVED_BATCHES': '1146', 'PRESERVED_SHA256': 'a' * 64}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv('NAV_CUTOFF', raising=False)
    monkeypatch.delenv('REQUESTED_BATCH_SIZE', raising=False)
    main = Mock(return_value=0)
    monkeypatch.setattr(maintenance, 'main', main)
    with pytest.raises(SystemExit):
        exec(compile(script, '<synthetic-workflow>', 'exec'), {})
    main.assert_called_once_with(['--mode', 'prune-preserved', '--table', 'growing', '--max-batches', '50',
                                  '--preserved-before', '2026-11-05 10:32:17.265431+00',
                                  '--preserved-batches', '1146', '--preserved-sha256', 'a' * 64])



@needs_sql
def test_a_repeated_bounded_export_continues_past_batches_already_exported(pg):
    repo, drive = _setup(pg)
    first = _export(repo, drive, max_batches=2)
    second = maintenance.export_batches(repo, drive, 'mf_nav', CUTOFF, 1, 2)
    assert len(first) == 2 and len(second) == 1  # only the one not yet exported
    assert {r['batch_id'] for r in second}.isdisjoint({r['batch_id'] for r in first})
    assert _count(pg, 'SELECT count(*) FROM quant_app.archive_manifests') == 3
    assert maintenance.export_batches(repo, drive, 'mf_nav', CUTOFF, 1, 2) == []  # all done


@needs_sql
def test_prune_honours_the_one_time_nav_cutoff_used_at_export(pg):
    repo, drive = _setup(pg, dates=('2026-09-20', '2026-09-21', '2026-09-22'))
    one_time = dt.date(2026, 9, 25)  # newer than the 14-day default at TODAY
    exported = maintenance.export_batches(repo, drive, 'mf_nav', one_time, 1, 10)
    assert len(exported) == 2
    before = repo.database_now()
    count, fingerprint = repo.generation(before)
    proof = _proof(repo, drive)
    try:
        pruned = maintenance.prune_preserved(repo, drive, proof, before=before, expected_batches=count,
                                             expected_sha256=fingerprint, today=TODAY, limit=50,
                                             nav_cutoff=one_time)
    finally:
        maintenance._ACTIVE_PROOF = None
    assert [r['deleted'] for r in pruned] == [1, 1]
