"""Restore proof for the Drive archive: synthetic Drive and the PGlite SQL harness only."""
import datetime as dt
import io
import json
import os
from unittest.mock import Mock

import pyarrow.parquet as pq
import pytest

import archive_maintenance as maintenance
import archive_restore_check as restore_check
from archive_maintenance import ArchiveRepository
from drive_archive import ArchiveError, digest, exact_json, upload_verified
import test_archive_maintenance_sql as sql_harness
from test_drive_archive import MemoryDrive, nav, quote

UTC = dt.timezone.utc


class ListedDrive(MemoryDrive):
    """MemoryDrive plus the folder listing Drive returns (paged, with checksums)."""

    folder_id = 'folder'

    def __init__(self, corrupt=None, page_size=2):
        super().__init__(corrupt)
        self.page_size = page_size
        self.properties = {}
        self.trashed = set()
        self.no_checksum = set()

    def metadata(self, file_id):
        """Drive files.get metadata; a vanished file is a 404."""
        if file_id not in self.data:
            raise ArchiveError('DRIVE_HTTP_404')
        body = self.data[file_id][0]
        return {'id': file_id, 'trashed': file_id in self.trashed,
                'appProperties': self.properties[file_id],
                'sha256Checksum': None if file_id in self.no_checksum else digest(body),
                'size': str(len(body))}

    def put(self, name, data, batch, kind, mime):
        file_id = super().put(name, data, batch, kind, mime)
        self.properties[file_id] = {'batch': batch, 'kind': kind}
        return file_id

    def request(self, method, url, **kwargs):
        assert method == 'GET' and url == restore_check.API
        ids = sorted(i for i in self.data if i not in self.trashed)
        start = int(kwargs['params'].get('pageToken', 0))
        chunk = ids[start:start + self.page_size]
        files = [{'id': i, 'size': str(len(self.data[i][0])), 'sha256Checksum': digest(self.data[i][0]),
                  'appProperties': self.properties[i]} for i in chunk]
        page = {'files': files}
        if start + self.page_size < len(ids):
            page['nextPageToken'] = str(start + self.page_size)
        response = Mock()
        response.json.return_value = page
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response


def archive(drive, table, rows, verified_at):
    manifest, texts = upload_verified(drive, table, [exact_json(row) for row in rows])
    return {'batch_id': manifest['batch_id'], 'source_table': table, 'row_count': manifest['rows'],
            'file_sha256': manifest['sha256'], 'drive_file_id': manifest['drive_file_id'],
            'drive_manifest_id': manifest['drive_manifest_id'], 'verified_at': verified_at}, texts


def fixture_batches(drive):
    old = dt.datetime(2026, 9, 20, tzinfo=UTC)
    return [archive(drive, 'mf_nav', [nav(code)], old)[0] for code in 'ABCDEFGH'] + \
        [archive(drive, 'market_quotes', [quote()], dt.datetime(2026, 11, 3, tzinfo=UTC))[0]]


def test_archived_rows_accepts_intact_batch_and_rejects_every_tamper():
    drive = ListedDrive()
    manifest, texts = archive(drive, 'mf_nav', [nav('A'), nav('B')], None)
    data = drive.download(manifest['drive_file_id'])
    assert restore_check.archived_rows(data, manifest) == texts
    with pytest.raises(ArchiveError, match='ARCHIVE_CHECKSUM_MISMATCH'):
        restore_check.archived_rows(data + b'x', manifest)
    with pytest.raises(ArchiveError, match='ARCHIVE_METADATA_MISMATCH'):
        restore_check.archived_rows(data, {**manifest, 'row_count': 3})
    # Same metadata, different row content, recorded checksum updated: content id catches it.
    table = pq.read_table(io.BytesIO(data))
    changed = table.set_column(table.schema.get_field_index('_row_json'), '_row_json',
                               [[texts[0], texts[1].replace('Fund', 'Fake')]])
    sink = io.BytesIO()
    pq.write_table(changed, sink)
    forged = sink.getvalue()
    with pytest.raises(ArchiveError, match='ARCHIVE_CONTENT_MISMATCH'):
        restore_check.archived_rows(forged, {**manifest, 'file_sha256': digest(forged)})


def test_presence_checks_identity_and_drive_checksum():
    drive = ListedDrive()
    manifest, _ = archive(drive, 'mf_nav', [nav()], None)
    listing = restore_check.list_folder(drive)
    assert restore_check.presence_failures(manifest, listing) == []
    wrong = {**manifest, 'file_sha256': '0' * 64}
    assert restore_check.presence_failures(wrong, listing)[0].endswith('DATA_FILE_CHECKSUM')
    del listing[manifest['drive_manifest_id']]
    assert restore_check.presence_failures(manifest, listing)[0].endswith('MANIFEST_FILE_MISSING')
    listing[manifest['drive_file_id']]['appProperties'] = {'batch': 'other', 'kind': 'data'}
    assert 'DATA_FILE_IDENTITY' in ' '.join(restore_check.presence_failures(manifest, listing))


def test_listing_follows_every_page():
    drive = ListedDrive(page_size=3)
    fixture_batches(drive)
    assert len(restore_check.list_folder(drive)) == len(drive.data) == 18


def test_rotation_covers_every_batch_within_a_week_and_always_recent():
    manifests = [{'batch_id': str(i), 'verified_at': dt.datetime(2026, 9, 1, tzinfo=UTC)} for i in range(50)]
    manifests.append({'batch_id': 'new', 'verified_at': dt.datetime(2026, 11, 1, tzinfo=UTC)})
    covered = set()
    for offset in range(7):
        chosen = restore_check.select_deep(manifests, dt.date(2026, 11, 4) + dt.timedelta(days=offset), False)
        assert len(chosen) < len(manifests)
        covered |= {m['batch_id'] for m in chosen}
        if offset < 5:
            assert 'new' in {m['batch_id'] for m in chosen}
    assert covered == {m['batch_id'] for m in manifests}
    assert len(restore_check.select_deep(manifests, dt.date(2026, 11, 4), True)) == len(manifests)


def _prove(monkeypatch, drive, manifests, counts=None, everything=True):
    monkeypatch.setattr(restore_check, 'load_manifests', lambda repo: manifests)
    monkeypatch.setattr(restore_check, 'restore_counts',
                        counts or (lambda repo, table, texts: (len(texts), 0, len(texts))))
    monkeypatch.setattr(restore_check, 'rehearse_insert', lambda repo, table, texts: len(texts))
    return restore_check.prove(object(), drive, today=dt.date(2026, 11, 4), everything=everything)


def test_prove_passes_on_intact_archive(monkeypatch):
    drive = ListedDrive()
    manifests = fixture_batches(drive)
    proof = _prove(monkeypatch, drive, manifests)
    assert proof.valid_now() and proof.manifests == proof.presence_verified == proof.deep_batches == 9
    assert proof.deep_rows == proof.exact_rows == 9
    maintenance.activate_restore_proof(proof)
    maintenance.require_commissioned_delete()
    monkeypatch.setattr(maintenance, '_ACTIVE_PROOF', None)


@pytest.mark.parametrize('damage', ['corrupt_data', 'missing_manifest', 'unrestorable', 'schema_drift_only'])
def test_prove_fails_closed_on_any_damage(monkeypatch, damage):
    drive = ListedDrive()
    manifests = fixture_batches(drive)
    counts = None
    if damage == 'corrupt_data':
        file_id = manifests[0]['drive_file_id']
        drive.data[file_id] = (drive.data[file_id][0] + b'!', 'data')
    elif damage == 'missing_manifest':
        del drive.data[manifests[-1]['drive_manifest_id']]
    elif damage == 'unrestorable':
        counts = lambda repo, table, texts: (0, 0, len(texts))  # noqa: E731
    else:
        counts = lambda repo, table, texts: (0, len(texts), len(texts))  # noqa: E731
    proof = _prove(monkeypatch, drive, manifests, counts)
    if damage == 'schema_drift_only':
        assert proof.valid_now() and proof.added_column_rows == 9
        return
    assert not proof.valid_now() and proof.failures
    with pytest.raises(ArchiveError, match='ARCHIVE_RESTORE_PROOF_FAILED'):
        maintenance.activate_restore_proof(proof)


def test_prove_reports_driver_errors_as_safe_codes(monkeypatch):
    drive = ListedDrive()
    manifests = fixture_batches(drive)

    def boom(repo, table, texts):
        raise RuntimeError('postgresql://user:secret@host/db')
    proof = _prove(monkeypatch, drive, manifests, boom)
    assert not proof.valid_now()
    assert all(item.endswith(':RuntimeError') for item in proof.failures)
    assert 'secret' not in json.dumps(proof.summary())


def test_manifest_file_must_match_database_record():
    drive = ListedDrive()
    manifest, _ = archive(drive, 'mf_nav', [nav()], None)
    raw = drive.download(manifest['drive_manifest_id'])
    assert restore_check.manifest_matches(raw, manifest)
    assert not restore_check.manifest_matches(raw, {**manifest, 'row_count': 2})
    assert not restore_check.manifest_matches(b'not json', manifest)


# Real SQL: the restore statement and the per-row DELETE predicate on PGlite.
pg = sql_harness.pg
needs_sql = pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'),
                               reason='Local SQL harness not configured')


@needs_sql
def test_sql_restore_counts_exact_then_added_column_then_cast_failure(pg):
    sql_harness.insert_nav(pg, 'A', '2026-08-01')
    sql_harness.insert_nav(pg, 'B', '2026-08-02')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    texts = [r[0] for r in pg.execute('SELECT to_jsonb(s)::text FROM quant_app.mf_nav s ORDER BY 1').fetchall()]
    assert restore_check.restore_counts(repo, 'mf_nav', texts) == (2, 0, 2)
    pg.execute('RESET ROLE')
    pg.execute('ALTER TABLE quant_app.mf_nav ADD COLUMN later_note text')
    pg.execute('SET ROLE quant_archive_worker')
    assert restore_check.restore_counts(repo, 'mf_nav', texts) == (0, 2, 2)
    pg.execute('RESET ROLE')
    pg.execute('ALTER TABLE quant_app.mf_nav DROP COLUMN amc')
    pg.execute('SET ROLE quant_archive_worker')
    exact, later, total = restore_check.restore_counts(repo, 'mf_nav', texts)
    assert total == 2 and exact + later == 0  # a lost column is never "restorable"


@needs_sql
def test_sql_delete_keeps_rows_that_would_not_restore_exactly(pg):
    sql_harness.insert_nav(pg, 'A', '2026-08-01')
    sql_harness.insert_nav(pg, 'A', '2026-08-02')
    pg.execute('SET ROLE quant_archive_worker')
    repo = ArchiveRepository('postgres://test-only')
    cutoff = dt.date(2026, 9, 13)
    drive = ListedDrive()
    manifest, texts = upload_verified(drive, 'mf_nav', repo.select('mf_nav', cutoff, 10))
    pg.execute('RESET ROLE')
    pg.execute('ALTER TABLE quant_app.mf_nav ADD COLUMN later_note text DEFAULT \'x\'')
    pg.execute('SET ROLE quant_archive_worker')
    # to_jsonb(s) now differs from the archive, and so would the restore: nothing is deleted.
    custody = maintenance.restore_check.CustodyCheck(repo, drive, manifest)
    proof = restore_check.RestoreProof(manifests=0, presence_verified=0, deep_batches=0, deep_rows=0,
                                       exact_rows=0, added_column_rows=0, failures=(),
                                       issuer=restore_check._ISSUER, context=custody.context)
    maintenance.activate_restore_proof(proof)
    try:
        assert repo.acknowledge(manifest, texts, cutoff, True, custody=custody) == 0
    finally:
        maintenance._ACTIVE_PROOF = None
    assert pg.execute('SELECT count(*) FROM quant_app.mf_nav').fetchone()[0] == 2


def test_batch_without_drive_checksum_is_deep_checked_tonight(monkeypatch):
    drive = ListedDrive()
    manifests = fixture_batches(drive)
    listing = restore_check.list_folder(drive)
    target = manifests[1]
    listing[target['drive_file_id']].pop('sha256Checksum')
    monkeypatch.setattr(restore_check, 'list_folder', lambda d: listing)
    checked = []
    original = restore_check.archived_rows
    monkeypatch.setattr(restore_check, 'archived_rows',
                        lambda data, manifest: checked.append(manifest['batch_id']) or original(data, manifest))
    proof = _prove(monkeypatch, drive, manifests, everything=False)
    assert proof.valid_now()
    assert target['batch_id'] in checked
    assert restore_check.presence_failures(target, listing) == []


def test_recheck_presence_catches_a_file_trashed_after_the_proof(monkeypatch):
    drive = ListedDrive()
    manifests = fixture_batches(drive)
    proof = _prove(monkeypatch, drive, manifests)
    assert restore_check.recheck_presence(object(), drive, proof) == len(manifests)
    del drive.data[manifests[3]['drive_file_id']]  # trashed files leave the untrashed listing
    with pytest.raises(ArchiveError, match='ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF'):
        restore_check.recheck_presence(object(), drive, proof)
