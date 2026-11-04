"""Custody hardening after the independent review of PR #71 (cb03cd4).

Each test reproduces one reviewed gap. Synthetic Drive and the PGlite harness only.
"""
import datetime as dt
import os
from decimal import Decimal

import pytest

import archive_maintenance as maintenance
import archive_restore_check as restore_check
from archive_maintenance import ArchiveRepository
from drive_archive import ArchiveError, exact_json, upload_verified
import test_archive_maintenance_sql as sql_harness
from test_archive_restore_check import ListedDrive, UTC, _prove, archive, fixture_batches
from test_drive_archive import nav

pg = sql_harness.pg
needs_sql = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                               reason='Local SQL harness not configured')


def _no_checksum(monkeypatch, drive, file_ids):
    """Drive sometimes omits sha256Checksum: serve listings without it for these files."""
    original = restore_check.list_folder

    def listing(d):
        files = original(d)
        for file_id in file_ids:
            files[file_id].pop('sha256Checksum', None)
        return files
    monkeypatch.setattr(restore_check, 'list_folder', listing)


# Finding 2: a recheck must not accept bytes it cannot verify.
def test_recheck_downloads_data_files_that_drive_gives_no_checksum_for(monkeypatch):
    drive = ListedDrive()
    manifests = fixture_batches(drive)
    proof = _prove(monkeypatch, drive, manifests)
    target = manifests[2]['drive_file_id']
    _no_checksum(monkeypatch, drive, [target])
    assert restore_check.recheck_presence(object(), drive, proof) == len(manifests)
    drive.data[target] = (drive.data[target][0] + b'tampered', 'data')
    with pytest.raises(ArchiveError, match='ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF'):
        restore_check.recheck_presence(object(), drive, proof)


def test_recheck_compares_the_manifest_file_checksum_not_only_its_identity(monkeypatch):
    drive = ListedDrive()
    manifests = fixture_batches(drive)
    proof = _prove(monkeypatch, drive, manifests)
    target = manifests[4]['drive_manifest_id']
    drive.data[target] = (drive.data[target][0].replace(b'mf_nav', b'xx_nav'), 'manifest')
    with pytest.raises(ArchiveError, match='ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF'):
        restore_check.recheck_presence(object(), drive, proof)


def test_manifest_file_without_drive_checksum_is_downloaded_and_compared(monkeypatch):
    drive = ListedDrive()
    manifests = fixture_batches(drive)
    proof = _prove(monkeypatch, drive, manifests)
    target = manifests[1]['drive_manifest_id']
    _no_checksum(monkeypatch, drive, [target])
    assert restore_check.recheck_presence(object(), drive, proof) == len(manifests)
    drive.data[target] = (b'{}', 'manifest')
    with pytest.raises(ArchiveError, match='ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF'):
        restore_check.recheck_presence(object(), drive, proof)


# Finding 1: a batch uploaded in this run needs its own custody check right before deletion.
def test_confirm_custody_passes_then_fails_when_a_copy_vanishes_or_changes():
    drive = ListedDrive()
    manifest, _ = upload_verified(drive, 'mf_nav', [exact_json(nav())])
    restore_check.confirm_custody(drive, manifest)
    original = drive.data[manifest['drive_manifest_id']]
    drive.data[manifest['drive_manifest_id']] = (original[0] + b' ', 'manifest')
    with pytest.raises(ArchiveError, match='ARCHIVE_CUSTODY_LOST'):
        restore_check.confirm_custody(drive, manifest)
    drive.data[manifest['drive_manifest_id']] = original
    restore_check.confirm_custody(drive, manifest)
    del drive.data[manifest['drive_file_id']]
    with pytest.raises(ArchiveError, match='ARCHIVE_CUSTODY_LOST'):
        restore_check.confirm_custody(drive, manifest)


def test_confirm_custody_rejects_a_trashed_file_even_though_its_bytes_still_download():
    drive = ListedDrive()
    manifest, _ = upload_verified(drive, 'mf_nav', [exact_json(nav())])
    drive.trashed.add(manifest['drive_file_id'])
    with pytest.raises(ArchiveError, match='ARCHIVE_CUSTODY_LOST'):
        restore_check.confirm_custody(drive, manifest)


def test_run_batch_hands_a_custody_check_to_the_deleting_transaction(monkeypatch):
    seen = {}

    class Repo:
        url = 'postgres://x'

        def select(self, table, cutoff, limit):
            return [exact_json(nav())]

        def acknowledge(self, manifest, texts, cutoff, delete, custody=None):
            seen['custody'] = custody
            return len(texts)
    drive = ListedDrive()
    monkeypatch.setattr(maintenance, 'require_commissioned_delete', lambda context=None: None)
    result = maintenance.run_batch(Repo(), drive, 'mf_nav', dt.date(2026, 9, 13), delete=True)
    assert result['deleted'] == 1 and callable(seen['custody'])
    seen['custody']()  # intact copy: passes
    drive.trashed.update(drive.data)
    with pytest.raises(ArchiveError, match='ARCHIVE_CUSTODY_LOST'):
        seen['custody']()


@needs_sql
def test_sql_acknowledge_refuses_to_delete_without_or_after_a_failing_custody_check(pg):
    sql_harness.insert_nav(pg, 'A', '2026-08-01')
    sql_harness.insert_nav(pg, 'A', '2026-08-02')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    cutoff = dt.date(2026, 9, 13)
    drive = ListedDrive()
    manifest, texts = upload_verified(drive, 'mf_nav', repo.select('mf_nav', cutoff, 10))
    context = restore_check.context_key(repo, drive)
    proof = restore_check.RestoreProof(manifests=0, presence_verified=0, deep_batches=0, deep_rows=0,
                                       exact_rows=0, added_column_rows=0, failures=(),
                                       issuer=restore_check._ISSUER, context=context)
    maintenance.activate_restore_proof(proof)
    try:
        # Neither nothing nor an arbitrary callable is custody evidence.
        with pytest.raises(ArchiveError, match='CUSTODY_CHECK_REQUIRED'):
            repo.acknowledge(manifest, texts, cutoff, True)
        with pytest.raises(ArchiveError, match='CUSTODY_CHECK_REQUIRED'):
            repo.acknowledge(manifest, texts, cutoff, True, custody=lambda: None)
        # A genuine check for another batch is refused.
        other, _ = upload_verified(drive, 'mf_nav', [exact_json(nav('Z'))])
        with pytest.raises(ArchiveError, match='CUSTODY_CHECK_REQUIRED'):
            repo.acknowledge(manifest, texts, cutoff, True,
                             custody=restore_check.CustodyCheck(repo, drive, other))
        # A check made for another database or folder cannot use this proof.
        elsewhere = ListedDrive()
        elsewhere.folder_id = 'other-folder'
        with pytest.raises(ArchiveError, match='AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED'):
            repo.acknowledge(manifest, texts, cutoff, True,
                             custody=restore_check.CustodyCheck(repo, elsewhere, manifest))
        # A copy trashed before the DELETE stops it and rolls back the manifest record too.
        drive.trashed.add(manifest['drive_file_id'])
        with pytest.raises(ArchiveError, match='ARCHIVE_CUSTODY_LOST'):
            repo.acknowledge(manifest, texts, cutoff, True,
                             custody=restore_check.CustodyCheck(repo, drive, manifest))
        assert pg.execute('SELECT count(*) FROM quant_app.mf_nav').fetchone()[0] == 2
        assert pg.execute('SELECT count(*) FROM quant_app.archive_manifests').fetchone()[0] == 0
        drive.trashed.clear()
        assert repo.acknowledge(manifest, texts, cutoff, True,
                                custody=restore_check.CustodyCheck(repo, drive, manifest)) == 1
    finally:
        maintenance._ACTIVE_PROOF = None


def test_run_batch_checks_bytes_before_locks_and_only_the_quick_form_runs_under_locks(monkeypatch):
    drive = ListedDrive()
    manifest, _ = upload_verified(drive, 'mf_nav', [exact_json(nav())])
    changed = drive.data[manifest['drive_manifest_id']]
    drive.data[manifest['drive_manifest_id']] = (changed[0] + b' ', 'manifest')
    with pytest.raises(ArchiveError, match='ARCHIVE_CUSTODY_LOST'):
        restore_check.confirm_custody(drive, manifest)  # full form, used before any lock
    restore_check.confirm_custody(drive, manifest, check_bytes=False)  # quick form: identity and trash only
    drive.trashed.add(manifest['drive_file_id'])
    with pytest.raises(ArchiveError, match='ARCHIVE_CUSTODY_LOST'):
        restore_check.confirm_custody(drive, manifest, check_bytes=False)


def test_a_corrupt_unsampled_manifest_cannot_become_the_pinned_baseline(monkeypatch):
    drive = ListedDrive()
    manifests = fixture_batches(drive)
    today = dt.date(2026, 11, 4)
    chosen = {m['batch_id'] for m in restore_check.select_deep(manifests, today, False)}
    victim = next(m for m in manifests if m['batch_id'] not in chosen)
    drive.data[victim['drive_manifest_id']] = (b'{}', 'manifest')
    proof = _prove(monkeypatch, drive, manifests, everything=False)
    assert not proof.valid_now()
    assert any(item.endswith('ARCHIVE_MANIFEST_FILE_MISMATCH') for item in proof.failures)


# Finding 3: "rows convert back" is not "rows insert back".
@needs_sql
def test_sql_insert_rehearsal_catches_what_the_conversion_check_accepts(pg):
    sql_harness.insert_nav(pg, 'A', '2026-08-01')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    texts = [r[0] for r in pg.execute('SELECT to_jsonb(s)::text FROM quant_app.mf_nav s').fetchall()]
    assert restore_check.rehearse_insert(repo, 'mf_nav', texts) == 1
    pg.execute('RESET ROLE')
    pg.execute('ALTER TABLE quant_app.mf_nav ADD CONSTRAINT nav_nonneg CHECK (nav >= 0)')
    pg.execute('SET ROLE quant_archive_worker')
    bad_text = texts[0].replace('1.123456789123456789', '-1')
    assert bad_text != texts[0]
    # The old check still calls this row exactly restorable ...
    assert restore_check.restore_counts(repo, 'mf_nav', [bad_text]) == (1, 0, 1)
    # ... but a real insert is refused.
    with pytest.raises(ArchiveError, match='ARCHIVE_ROWS_NOT_INSERTABLE'):
        restore_check.rehearse_insert(repo, 'mf_nav', [bad_text])
    # Two versions of one key cannot both come back.
    other = texts[0].replace('1.123456789123456789', '2')
    with pytest.raises(ArchiveError, match='ARCHIVE_ROWS_NOT_INSERTABLE'):
        restore_check.rehearse_insert(repo, 'mf_nav', [texts[0], other])
    # Nothing was written to the real table by any rehearsal.
    assert pg.execute('SELECT count(*) FROM quant_app.mf_nav').fetchone()[0] == 1


@needs_sql
def test_sql_rehearsal_checks_deferred_constraints_before_rolling_back(pg):
    sql_harness.insert_nav(pg, 'A', '2026-08-01')
    pg.execute('ALTER TABLE quant_app.mf_nav ADD CONSTRAINT one_name UNIQUE (scheme_name) '
               'DEFERRABLE INITIALLY DEFERRED')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    first = pg.execute('SELECT to_jsonb(s)::text FROM quant_app.mf_nav s').fetchone()[0]
    # Distinct primary key, same value in the deferred-unique column: only a forced check sees it.
    second = first.replace('"scheme_code": "A"', '"scheme_code": "B"')
    assert second != first
    assert restore_check.rehearse_insert(repo, 'mf_nav', [first]) == 1
    with pytest.raises(ArchiveError, match='ARCHIVE_ROWS_NOT_INSERTABLE'):
        restore_check.rehearse_insert(repo, 'mf_nav', [first, second])


def test_prove_runs_the_insert_rehearsal_and_fails_closed(monkeypatch):
    drive = ListedDrive()
    manifests = fixture_batches(drive)
    monkeypatch.setattr(restore_check, 'load_manifests', lambda repo: manifests)
    monkeypatch.setattr(restore_check, 'restore_counts', lambda repo, table, texts: (len(texts), 0, len(texts)))

    def refuse(repo, table, texts):
        raise ArchiveError('ARCHIVE_ROWS_NOT_INSERTABLE')
    monkeypatch.setattr(restore_check, 'rehearse_insert', refuse)
    proof = restore_check.prove(object(), drive, today=dt.date(2026, 11, 4), everything=True)
    assert not proof.valid_now()
    assert all(item.endswith('ARCHIVE_ROWS_NOT_INSERTABLE') for item in proof.failures)


def test_full_check_reports_one_key_archived_twice_with_different_content(monkeypatch):
    drive = ListedDrive()
    old = dt.datetime(2026, 9, 20, tzinfo=UTC)
    manifests = [archive(drive, 'mf_nav', [nav('A', Decimal('1'))], old)[0],
                 archive(drive, 'mf_nav', [nav('A', Decimal('2'))], old)[0]]
    monkeypatch.setattr(restore_check, 'load_manifests', lambda repo: manifests)
    monkeypatch.setattr(restore_check, 'restore_counts', lambda repo, table, texts: (len(texts), 0, len(texts)))
    monkeypatch.setattr(restore_check, 'rehearse_insert', lambda repo, table, texts: len(texts))
    proof = restore_check.prove(object(), drive, today=dt.date(2026, 11, 4), everything=True)
    assert not proof.valid_now()
    assert any(item.endswith('CROSS_BATCH_KEY_CONFLICT') for item in proof.failures)


# Finding 4: a proof belongs to one database and one folder.
def test_a_proof_cannot_authorize_deletion_for_another_database_or_folder():
    class Repo:
        def __init__(self, url):
            self.url = url
    drive_a, drive_b = ListedDrive(), ListedDrive()
    drive_b.folder_id = 'other-folder'
    repo = Repo('postgres://one')
    context = restore_check.context_key(repo, drive_a)
    assert context != restore_check.context_key(repo, drive_b)
    assert context != restore_check.context_key(Repo('postgres://two'), drive_a)
    proof = restore_check.RestoreProof(manifests=1, presence_verified=1, deep_batches=1, deep_rows=1,
                                       exact_rows=1, added_column_rows=0, failures=(),
                                       issuer=restore_check._ISSUER, context=context)
    maintenance.activate_restore_proof(proof)
    try:
        maintenance.require_commissioned_delete(context)
        with pytest.raises(ArchiveError, match='AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED'):
            maintenance.require_commissioned_delete(restore_check.context_key(repo, drive_b))
    finally:
        maintenance._ACTIVE_PROOF = None
