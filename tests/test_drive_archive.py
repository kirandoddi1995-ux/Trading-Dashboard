import datetime as dt
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import textwrap
from unittest.mock import Mock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import archive_maintenance as maintenance
import authorize_drive
from drive_archive import (
    ArchiveError, DriveArchive, SCOPE, TOKEN_URI, batch_identity, credentials,
    digest, exact_json, parquet_bytes, upload_verified, verify_parquet,
)


def nav(code='A', value=Decimal('1.123456789123456789')):
    return dict(scheme_code=code, nav_date='2026-08-01', isin_growth=None,
                isin_reinvestment=None, scheme_name='Fund Ω', amc=None, category='Equity',
                plan='Direct', option_name='Growth', nav=value, source='AMFI',
                observed_at='2026-08-01T10:00:00+00:00', source_hash='captured')


def quote():
    return dict(observed_at='2026-08-01T10:00:00+00:00', trade_date='2026-08-01',
                instrument_key='NSE_EQ|A', source='captured', last_price=Decimal('1.001'),
                open=None, high=2, low=0, previous_close=1, volume=0, open_interest=None,
                raw={'nested': [None, Decimal('0.123456789123456789'), True], 'label': '株'})


@pytest.mark.parametrize('table,row', [('mf_nav', nav()), ('market_quotes', quote())])
def test_parquet_full_precision_nulls_zero_types_and_verification(table, row):
    key, data, texts = parquet_bytes(table, [exact_json(row)])
    assert verify_parquet(data, table, key, 1, digest(data)) == texts
    parsed = pq.read_table(io.BytesIO(data)).to_pydict()
    assert parsed['observed_at'][0].utcoffset() == dt.timedelta(0)
    if table == 'mf_nav':
        assert parsed['nav'] == ['1.123456789123456789']
        assert parsed['isin_growth'] == [None]
    else:
        assert parsed['volume'] == ['0']
        assert parsed['open'] == [None]
        assert '0.123456789123456789' in parsed['raw'][0]
    with pytest.raises(ArchiveError, match='CHECKSUM'):
        verify_parquet(data + b'changed', table, key, 1, digest(data))
    with pytest.raises(ArchiveError, match='METADATA'):
        verify_parquet(data, table, key, 2, digest(data))


def test_wrong_analytical_column_detected_even_when_full_row_copy_unchanged():
    key, data, _ = parquet_bytes('mf_nav', [exact_json(nav())])
    table = pq.read_table(io.BytesIO(data))
    index = table.schema.get_field_index('nav')
    changed = table.set_column(index, table.schema.field(index), pa.array(['999']))
    sink = io.BytesIO()
    pq.write_table(changed, sink)
    bad = sink.getvalue()
    with pytest.raises(ArchiveError, match='COLUMN_MISMATCH'):
        verify_parquet(bad, 'mf_nav', key, 1, digest(bad))


def test_batch_identity_is_stable_and_changes_with_payload():
    a, b = exact_json(nav()), exact_json(nav('B'))
    assert batch_identity('mf_nav', [a, b])[0] == batch_identity('mf_nav', [b, a])[0]
    assert batch_identity('mf_nav', [a])[0] != batch_identity('mf_nav', [exact_json(nav(value=2))])[0]
    with pytest.raises(ArchiveError, match='DUPLICATE'):
        batch_identity('mf_nav', [a, a])
    with pytest.raises(ArchiveError, match='SCHEMA'):
        batch_identity('mf_nav', [exact_json({**nav(), 'new_column': 'unreviewed'})])


class MemoryDrive:
    def __init__(self, corrupt=None):
        self.data, self.identities = {}, {}
        self.corrupt = corrupt

    def put(self, name, data, batch, kind, mime):
        identity = (batch, kind)
        if identity not in self.identities:
            file_id = str(len(self.data))
            self.identities[identity] = file_id
            self.data[file_id] = (data, kind)
        return self.identities[identity]

    def download(self, file_id):
        data, kind = self.data[file_id]
        return data + b'corrupt' if self.corrupt == kind else data


@pytest.mark.parametrize('failure', ['data', 'manifest'])
def test_failed_remote_verification_never_acknowledges_or_deletes(failure):
    repo = Mock()
    repo.select.return_value = [exact_json(nav())]
    with pytest.raises(ArchiveError):
        maintenance.run_batch(repo, MemoryDrive(failure), 'mf_nav', dt.date(2026, 9, 13), delete=True)
    repo.acknowledge.assert_not_called()


def test_export_only_and_retry_after_upload_crash_reuse_files():
    drive = MemoryDrive()
    texts = [exact_json(nav())]
    first, _ = upload_verified(drive, 'mf_nav', texts)
    second, _ = upload_verified(drive, 'mf_nav', texts)
    assert first == second and len(drive.data) == 2
    repo = Mock()
    repo.select.return_value = texts
    repo.acknowledge.return_value = 0
    result = maintenance.run_batch(repo, drive, 'mf_nav', dt.date(2026, 9, 13))
    assert result['verified'] == 1 and result['deleted'] == 0
    assert repo.acknowledge.call_args.args[-1] is False


def test_cutoff_bounds_and_14_calendar_day_policy():
    today = dt.date(2026, 9, 20)
    assert maintenance.cutoff_for('market_quotes', today) == dt.date(2026, 9, 6)
    assert maintenance.cutoff_for('mf_nav', today) == dt.date(2026, 9, 6)
    assert maintenance.cutoff_for('mf_nav', today, dt.date(2026, 9, 13)) == dt.date(2026, 9, 13)
    with pytest.raises(ArchiveError):
        maintenance.cutoff_for('market_quotes', today, dt.date(2026, 9, 13))
    with pytest.raises(ArchiveError):
        maintenance.cutoff_for('mf_nav', today, today)
    with pytest.raises(ArchiveError):
        maintenance.predicate('evidence_ledger_events')


def test_delete_switch_is_checked_before_any_connection(monkeypatch, capsys):
    monkeypatch.delenv('ARCHIVE_DELETE_ENABLED', raising=False)
    repo = Mock()
    monkeypatch.setattr(maintenance, 'ArchiveRepository', repo)
    assert maintenance.main(['--mode', 'delete']) == 1
    repo.assert_not_called()
    assert 'DELETION_NOT_ENABLED' in capsys.readouterr().out


@pytest.mark.parametrize('table', ['evidence_ledger_events',
    'prediction_targets', 'market_daily_volumes', 'positions', 'orders',
    'scan_runs', 'outcomes', 'observations'])
def test_protected_tables_never_enter_archive_retention(table):
    with pytest.raises(ArchiveError, match='UNSUPPORTED_TABLE'):
        maintenance.cutoff_for(table, dt.date(2026, 9, 24))
    with pytest.raises(ArchiveError, match='UNSUPPORTED_TABLE'):
        maintenance.predicate(table)


def workflow_script():
    text = (Path(__file__).resolve().parents[1] /
            '.github/workflows/drive-archive.yml').read_text()
    return textwrap.dedent(text.split("python - <<'PY'\n", 1)[1].rsplit('          PY', 1)[0])


def test_schedule_requests_deletion_for_all_four_tables(monkeypatch):
    calls = []
    monkeypatch.setenv('EVENT_NAME', 'schedule')
    monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', 'true')
    monkeypatch.setattr(maintenance, 'main', lambda args: calls.append(args) or 0)
    exec(compile(workflow_script(), '<archive-workflow>', 'exec'), {})
    assert calls == [['--mode', 'delete', '--table', 'mf_nav'],
                     ['--mode', 'delete', '--table', 'market_quotes'],
                     ['--mode', 'delete', '--table', 'universe_membership_versions'],
                     ['--mode', 'delete', '--table', 'scanner_observations']]


def test_schedule_fails_closed_instead_of_export_fallback(monkeypatch, capsys):
    monkeypatch.setenv('EVENT_NAME', 'schedule')
    monkeypatch.delenv('ARCHIVE_DELETE_ENABLED', raising=False)
    repo = Mock()
    monkeypatch.setattr(maintenance, 'ArchiveRepository', repo)
    with pytest.raises(SystemExit) as caught:
        exec(compile(workflow_script(), '<archive-workflow>', 'exec'), {})
    assert caught.value.code == 1
    repo.assert_not_called()
    assert 'DELETION_NOT_ENABLED' in capsys.readouterr().out


def test_enabled_delete_verifies_before_acknowledging(monkeypatch):
    repo = Mock()
    repo.preview.return_value = 1
    repo.select.side_effect = [[exact_json(nav())], []]
    repo.acknowledge.return_value = 1
    drive = MemoryDrive()
    drive.check_folder = Mock()
    drive.close = Mock()
    monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', 'true')
    monkeypatch.setattr(maintenance, 'ArchiveRepository', lambda url: repo)
    monkeypatch.setattr(maintenance, 'build_drive_credentials', lambda: None)
    monkeypatch.setattr(maintenance, 'DriveArchive', lambda *args: drive)
    assert maintenance.main(['--mode', 'delete']) == 0
    manifest, texts, cutoff, deleting = repo.acknowledge.call_args.args
    assert deleting is True and len(texts) == manifest['rows'] == 1
    assert cutoff == dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=14)
    assert len(drive.data) == 2


def test_preview_never_constructs_drive(monkeypatch):
    repo, drive = Mock(), Mock()
    repo.preview.return_value = 10
    monkeypatch.setattr(maintenance, 'ArchiveRepository', lambda url: repo)
    monkeypatch.setattr(maintenance, 'DriveArchive', drive)
    assert maintenance.main(['--mode', 'preview']) == 0
    drive.assert_not_called()
    repo.acknowledge.assert_not_called()


def test_errors_do_not_print_token_url_provider_body(monkeypatch, capsys):
    secret = 'postgresql://user:DO_NOT_PRINT@host/db'
    monkeypatch.setattr(maintenance, 'ArchiveRepository', Mock(side_effect=RuntimeError(secret)))
    assert maintenance.main([]) == 1
    assert secret not in capsys.readouterr().out


def test_oauth_only_narrow_scope_and_fixed_token_endpoint():
    token = dict(type='authorized_user', client_id='id', client_secret='secret',
                 refresh_token='refresh', scopes=[SCOPE], token_uri=TOKEN_URI)
    assert credentials(token).refresh_token == 'refresh'
    for override in ({'token_uri': 'https://bad.example'}, {'scopes': ['https://www.googleapis.com/auth/drive']},
                     {'refresh_token': ''}, {'type': 'service_account'}):
        with pytest.raises(ArchiveError):
            credentials({**token, **override})


def test_runtime_credentials_reads_oauth_secret(monkeypatch):
    token = dict(type='authorized_user', client_id='id', client_secret='secret',
                 refresh_token='refresh', scopes=[SCOPE], token_uri=TOKEN_URI)
    monkeypatch.setenv('DRIVE_OAUTH_TOKEN_JSON', json.dumps(token))
    monkeypatch.setenv('DRIVE_SERVICE_ACCOUNT_JSON', 'must-not-be-read')
    builder = Mock(wraps=credentials)
    monkeypatch.setattr(maintenance, 'credentials', builder)
    result = maintenance.build_drive_credentials()
    builder.assert_called_once_with(token)
    assert result.refresh_token == 'refresh'
    assert result.scopes == [SCOPE]
    assert result.token_uri == TOKEN_URI


@pytest.mark.parametrize('raw', [None, '', '{private-secret', 'null', '[]', '{}'])
def test_runtime_credentials_invalid_config_is_sanitized(monkeypatch, raw):
    monkeypatch.setenv('DRIVE_SERVICE_ACCOUNT_JSON', '{"type":"service_account"}')
    if raw is None:
        monkeypatch.delenv('DRIVE_OAUTH_TOKEN_JSON', raising=False)
    else:
        monkeypatch.setenv('DRIVE_OAUTH_TOKEN_JSON', raw)
    with pytest.raises(ArchiveError, match='^INVALID_OAUTH_CONFIGURATION$'):
        maintenance.build_drive_credentials()


@pytest.mark.parametrize('key,value', [
    ('client_id', ''), ('client_secret', None), ('refresh_token', ' '),
    ('client_id', 123), ('token_uri', None), ('scopes', SCOPE),
    ('scopes', [SCOPE, 'https://www.googleapis.com/auth/drive']),
])
def test_credentials_rejects_incomplete_or_broad_configuration(key, value):
    token = dict(type='authorized_user', client_id='id', client_secret='secret',
                 refresh_token='refresh', scopes=[SCOPE], token_uri=TOKEN_URI)
    with pytest.raises(ArchiveError, match='^INVALID_OAUTH_CONFIGURATION$'):
        credentials({**token, key: value})


def test_token_file_refuses_overwrite(tmp_path):
    path = tmp_path / 'token.json'
    authorize_drive.save_private_token(path, {'refresh_token': 'test-not-a-secret'})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        authorize_drive.save_private_token(path, {'refresh_token': 'replacement'})
    assert path.read_bytes() == before


def test_oauth_pkce_offline_loopback_rejects_wrong_state_and_does_not_log_code(monkeypatch, capsys):
    import threading
    import urllib.parse
    import requests
    seen = {}
    threads = []
    code = 'DO_NOT_LOG_AUTHORIZATION_CODE'
    def browser(url, new):
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        seen.update(params)
        def callbacks():
            base = params['redirect_uri'][0]
            requests.get(base, params={'state': 'wrong-state', 'code': 'wrong'}, timeout=10)
            requests.get(base, params={'state': params['state'][0], 'code': code}, timeout=10)
        worker = threading.Thread(target=callbacks)
        worker.start()
        threads.append(worker)
        return True
    monkeypatch.setattr(authorize_drive.webbrowser, 'open', browser)
    actual, redirect = authorize_drive.get_authorization_code('client', 'correct-state', 'v' * 64)
    for thread in threads:
        thread.join(timeout=10)
    assert actual == code and redirect.startswith('http://127.0.0.1:')
    assert seen['access_type'] == ['offline'] and seen['code_challenge_method'] == ['S256']
    assert seen['scope'] == [SCOPE] and 'consent' in seen['prompt'][0]
    assert code not in capsys.readouterr().out


def test_manifest_and_source_scope_in_workflow_and_gitignore():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / '.github/workflows/drive-archive.yml').read_text()
    assert 'ARCHIVE_DATABASE_URL' in workflow and 'DRIVE_OAUTH_TOKEN_JSON' in workflow
    assert 'vars.ARCHIVE_ENABLED' in workflow and 'vars.ARCHIVE_DELETE_ENABLED' in workflow
    assert 'upload-artifact' not in workflow
    ignored = (root / '.gitignore').read_text()
    assert 'token.json' in ignored and 'client_secret*.json' in ignored


def test_drive_upload_reuses_existing_batch_and_rejects_duplicates():
    drive = object.__new__(DriveArchive)
    drive.folder_id = 'folder'
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.json.return_value = {'files': [{'id': 'existing'}]}
    drive.request = Mock(return_value=response)
    batch = hashlib.sha256(b'batch').hexdigest()
    assert drive.put('name', b'data', batch, 'data', 'application/octet-stream') == 'existing'
    assert drive.request.call_count == 1
    response.json.return_value = {'files': [{'id': 'a'}, {'id': 'b'}]}
    with pytest.raises(ArchiveError, match='DUPLICATE'):
        drive.put('name', b'data', batch, 'data', 'application/octet-stream')
