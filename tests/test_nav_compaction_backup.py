"""Offline source, transport, identity and disposable PostgreSQL recovery tests."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import nav_compaction_backup as backup
from drive_archive import SPECS


@pytest.fixture
def sample(monkeypatch):
    text = json.dumps(dict(scheme_code='A', nav_date='2026-10-01', isin_growth=None,
        isin_reinvestment=None, scheme_name='Fund Ω', amc=None, category='Equity',
        plan='Direct', option_name='Growth', nav=1, source='AMFI',
        observed_at='2026-10-01T10:00:00+00:00', source_hash='captured'))
    raw = text.encode('utf-8')
    md5 = hashlib.md5(raw).hexdigest()
    monkeypatch.setattr(backup, 'EXPECTED_ROWS', 1)
    monkeypatch.setattr(backup, 'EXPECTED_MD5', md5)
    receipt = dict(format=backup.FORMAT, table='quant_app.mf_nav', rows=1,
        fingerprint=md5, sha256=backup.sha(raw), postgres_types=SPECS['mf_nav'],
        source_sql_read_only=True, deleted=0, approval_authority=False)
    return raw, receipt


class MemoryDrive:
    def __init__(self, corrupt=None):
        self.files = {}
        self.corrupt = corrupt
    def check_folder(self): pass
    def put(self, name, data, batch_id, kind, mime):
        self.files[kind] = data
        return kind
    def download(self, file_id):
        return b'changed' if file_id == self.corrupt else self.files[file_id]


def test_snapshot_is_only_select_in_readonly_connection(sample):
    raw, receipt = sample
    class Repository:
        @contextmanager
        def connection(self, readonly=False):
            assert readonly is True
            def execute(sql):
                assert sql == backup.SQL and 'LIMIT 10001' in sql
                return SimpleNamespace(fetchone=lambda: (1, 1, receipt['fingerprint'], [raw.decode()]))
            yield SimpleNamespace(execute=execute)
    assert backup.snapshot(Repository()) == (raw, receipt)


@pytest.mark.parametrize('result', [None, (0, 0, '', []), (1, 0, '', []),
    (10001, 10001, '', []), (1, 1, 'changed', []), (1, 1, None, []),
    (1, 1, 'placeholder', ['x']), (1, 1, 'placeholder', ()), (True, True, '', [])])
def test_changed_or_empty_source_blocks(sample, result):
    class Repository:
        @contextmanager
        def connection(self, readonly=False):
            yield SimpleNamespace(execute=lambda sql: SimpleNamespace(fetchone=lambda: result))
    with pytest.raises(backup.BackupBlocked):
        backup.snapshot(Repository())


@pytest.mark.parametrize('key,value', [('format', 'other'), ('table', 'quant_app.market_quotes'),
    ('rows', True), ('rows', 2), ('fingerprint', 'changed'), ('sha256', 'changed'),
    ('postgres_types', {}), ('source_sql_read_only', False), ('deleted', 1),
    ('deleted', False), ('approval_authority', True)])
def test_receipt_identity_is_not_self_approval(sample, key, value):
    raw, receipt = sample
    receipt[key] = value
    with pytest.raises(backup.BackupBlocked):
        backup.verify(raw, receipt)


@pytest.mark.parametrize('raw', [b'', b'changed', b'{invalid json}'])
def test_corruption_blocks(sample, raw):
    _, receipt = sample
    with pytest.raises(backup.BackupBlocked):
        backup.verify(raw, receipt)


def test_oversize_blocks_before_decoding(sample, monkeypatch):
    raw, receipt = sample
    monkeypatch.setattr(backup, 'MAX_BYTES', 1)
    with pytest.raises(backup.BackupBlocked):
        backup.verify(raw, receipt)


@pytest.mark.parametrize('corrupt', ['data', 'manifest'])
def test_remote_mismatch_never_acknowledged(sample, corrupt):
    raw, receipt = sample
    with pytest.raises(backup.BackupBlocked, match='MISMATCH'):
        backup.publish(MemoryDrive(corrupt), raw, receipt)


def test_private_remote_success_preserves_original_bytes(sample):
    raw, receipt = sample
    drive = MemoryDrive()
    result = backup.publish(drive, raw, receipt)
    assert result['status'] == 'NAV_LIVE_BACKUP_REMOTE_VERIFIED'
    assert result['deleted'] == 0 and drive.files['data'] == raw
    assert json.loads(drive.files['manifest'])['sha256'] == backup.sha(raw)


@pytest.mark.parametrize('confirmation', ['', 'false', 'False', 'TRUE', '1'])
def test_export_requires_exact_confirmation(monkeypatch, capsys, confirmation):
    monkeypatch.setenv('NAV_BACKUP_AUTHORISED', confirmation)
    monkeypatch.setattr(backup, 'ArchiveRepository', lambda *args: pytest.fail('Database access'))
    assert backup.main(['--export']) == 2
    assert 'NAV_BACKUP_CONFIRMATION_REQUIRED' in capsys.readouterr().out


def test_default_preview_touches_no_network_or_secrets(monkeypatch, capsys):
    monkeypatch.setattr(backup, 'ArchiveRepository', lambda *args: pytest.fail('Database access'))
    monkeypatch.setattr(backup, 'DriveArchive', lambda *args: pytest.fail('Drive access'))
    assert backup.main([]) == 0
    assert json.loads(capsys.readouterr().out)['network_calls'] == 0


def test_export_true_uses_existing_secrets_without_printing_values(sample, monkeypatch, capsys):
    raw, receipt = sample
    monkeypatch.setenv('NAV_BACKUP_AUTHORISED', 'true')
    monkeypatch.setenv('ARCHIVE_DATABASE_URL', 'PRIVATE_URL')
    monkeypatch.setenv('DRIVE_OAUTH_TOKEN_JSON', '{"private":"PRIVATE_TOKEN"}')
    monkeypatch.setenv('DRIVE_ARCHIVE_FOLDER_ID', 'PRIVATE_FOLDER')
    monkeypatch.setattr(backup, 'ArchiveRepository', lambda url: object())
    monkeypatch.setattr(backup, 'snapshot', lambda repository: (raw, receipt))
    monkeypatch.setattr(backup, 'credentials', lambda value: object())
    drive = MemoryDrive()
    closed = []
    drive.close = lambda: closed.append(True)
    monkeypatch.setattr(backup, 'DriveArchive', lambda *args: drive)
    assert backup.main(['--export']) == 0
    assert closed == [True]
    assert 'PRIVATE_' not in capsys.readouterr().out


def test_raw_transport_errors_redacted(sample, monkeypatch, capsys):
    monkeypatch.setenv('NAV_BACKUP_AUTHORISED', 'true')
    def fail(*args): raise RuntimeError('PRIVATE_PASSWORD')
    monkeypatch.setattr(backup, 'ArchiveRepository', fail)
    assert backup.main(['--export']) == 2
    assert 'PRIVATE_PASSWORD' not in capsys.readouterr().out


def test_bounded_read(tmp_path, monkeypatch):
    path = tmp_path / 'private'
    path.write_bytes(b'1234')
    monkeypatch.setattr(backup, 'MAX_BYTES', 3)
    with pytest.raises(backup.BackupBlocked, match='TOO_LARGE'):
        backup.bounded_read(path)


@pytest.mark.parametrize('result', [SimpleNamespace(returncode=2, stdout='PRIVATE_PASSWORD'),
    SimpleNamespace(returncode=0, stdout='{"rows":2,"fingerprint":"other"}')])
def test_rehearsal_failure_blocks(sample, tmp_path, monkeypatch, result):
    raw, receipt = sample
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: result)
    with pytest.raises(backup.BackupBlocked):
        backup.rehearse(raw, receipt, tmp_path)


def test_missing_harness_blocks(sample, tmp_path):
    raw, receipt = sample
    with pytest.raises(backup.BackupBlocked, match='HARNESS_REQUIRED'):
        backup.rehearse(raw, receipt, tmp_path / 'absent')


def test_missing_rehearsal_inputs_blocks(capsys):
    assert backup.main(['--rehearse']) == 2
    assert 'NAV_REHEARSAL_INPUTS_REQUIRED' in capsys.readouterr().out


@pytest.mark.skipif(not os.environ.get('EQUITY_TEST_PGLITE_MODULE'), reason='Local SQL harness not configured')
def test_actual_lossless_postgres_restore(monkeypatch):
    module = Path(os.environ['EQUITY_TEST_PGLITE_MODULE'])
    # Obtain a genuine PostgreSQL jsonb representation and expected MD5 from a
    # fresh synthetic table, rather than pretend Python formatting matches PG.
    fixture = backup.REHEARSAL.replace('process.stdout.write(JSON.stringify(r.rows[0]));',
        'const s=await db.query(' + json.dumps(backup.SQL) + ');'
        "process.stdout.write(JSON.stringify({...r.rows[0],original:s.rows[0].array_agg[0],"
        "snapshot:s.fields.map(f=>s.rows[0][f.name])}));")
    row = dict(scheme_code='A', nav_date='2026-10-01', isin_growth=None,
        isin_reinvestment=None, scheme_name='Fund Ω', amc=None, category='Equity',
        plan='Direct', option_name='Growth', source='AMFI',
        observed_at='2026-10-01T15:30:00+05:30', source_hash='captured')
    original = json.dumps(row).rstrip('}') + ',"nav":1.123456789123456789}'
    process = subprocess.run(['node', '-e', fixture, str(module)], input='[' + original + ']',
        capture_output=True, text=True, encoding='utf-8', timeout=60, check=True)
    result = json.loads(process.stdout)
    raw = result['original'].encode()
    monkeypatch.setattr(backup, 'EXPECTED_ROWS', 1)
    monkeypatch.setattr(backup, 'EXPECTED_MD5', result['fingerprint'])
    receipt = dict(format=backup.FORMAT, table='quant_app.mf_nav', rows=1,
        fingerprint=result['fingerprint'], sha256=backup.sha(raw), postgres_types=SPECS['mf_nav'],
        source_sql_read_only=True, deleted=0, approval_authority=False)
    class Repository:
        @contextmanager
        def connection(self, readonly=False):
            assert readonly is True
            actual = result['snapshot']
            actual[:2] = [int(value) for value in actual[:2]]
            yield SimpleNamespace(execute=lambda sql: SimpleNamespace(fetchone=lambda: actual))
    assert backup.snapshot(Repository()) == (raw, receipt)
    assert backup.rehearse(raw, receipt, module)['status'] == 'NAV_OFFLINE_RESTORE_VERIFIED'


def test_workflow_has_no_schedule_writes_or_public_data_artifacts():
    path = Path(__file__).resolve().parents[1] / '.github/workflows/nav-live-backup.yml'
    text = path.read_text()
    assert 'workflow_dispatch:' in text and 'default: false' in text
    assert 'inputs.confirm_export == true' in text and 'inputs.confirm_export != true' in text
    assert 'group: verified-drive-archive' in text and 'contents: read' in text
    for forbidden in ('schedule:', 'push:', 'pull_request:', 'upload-artifact', 'contents: write'):
        assert forbidden not in text
