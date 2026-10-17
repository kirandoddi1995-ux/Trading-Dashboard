"""Production denial is NOT monkeypatched here. No hosted/archive IO allowed."""
import datetime as dt
import os
from pathlib import Path
import textwrap
from unittest.mock import Mock

import pytest

import archive_maintenance as maintenance
from drive_archive import ArchiveError, SPECS


@pytest.mark.parametrize('flag', [None, 'false', 'true', 'TRUE'])
@pytest.mark.parametrize('table', tuple(SPECS))
def test_cli_delete_never_reaches_database_or_credentials(monkeypatch, capsys, flag, table):
    if flag is None:
        monkeypatch.delenv('ARCHIVE_DELETE_ENABLED', raising=False)
    else:
        monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', flag)
    repository = Mock(side_effect=AssertionError('NO_DATABASE'))
    credentials = Mock(side_effect=AssertionError('NO_CREDENTIALS'))
    drive = Mock(side_effect=AssertionError('NO_DRIVE'))
    monkeypatch.setattr(maintenance, 'ArchiveRepository', repository)
    monkeypatch.setattr(maintenance, 'build_drive_credentials', credentials)
    monkeypatch.setattr(maintenance, 'DriveArchive', drive)
    args = ['--mode', 'delete', '--table', table]
    if table == 'mf_nav':
        args += ['--nav-cutoff', '2026-10-04']
    assert maintenance.main(args) == 1
    output = capsys.readouterr().out
    assert ('AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED' if flag == 'true' else 'DELETION_NOT_ENABLED') in output
    repository.assert_not_called()
    credentials.assert_not_called()
    drive.assert_not_called()


@pytest.mark.parametrize('table', tuple(SPECS))
def test_batch_denial_precedes_select_and_upload(monkeypatch, table):
    repo = Mock()
    upload = Mock(side_effect=AssertionError('NO_UPLOAD'))
    monkeypatch.setattr(maintenance, 'upload_verified', upload)
    monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', 'true')
    monkeypatch.setenv('CUSTODY_VERIFIED', 'true')
    monkeypatch.setenv('RESTORE_VERIFIED', 'true')
    with pytest.raises(ArchiveError, match='AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED'):
        maintenance.run_batch(repo, object(), table, dt.date(2026, 10, 1), delete=True)
    repo.select.assert_not_called()
    repo.acknowledge.assert_not_called()
    upload.assert_not_called()


def test_repository_denial_precedes_transaction_or_manifest(monkeypatch):
    repo = maintenance.ArchiveRepository('postgresql://synthetic')
    connection = Mock(side_effect=AssertionError('NO_CONNECTION'))
    monkeypatch.setattr(repo, 'connection', connection)
    with pytest.raises(ArchiveError, match='AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED'):
        repo.acknowledge({}, [], dt.date(2026, 10, 1), True)
    connection.assert_not_called()


def test_actual_scheduled_launcher_is_hold_without_archive_import(monkeypatch, capsys):
    source = (Path(__file__).resolve().parents[1] / '.github/workflows/drive-archive.yml').read_text()
    script = textwrap.dedent(source.split("python - <<'PY'\n", 1)[1].rsplit('          PY', 1)[0])
    monkeypatch.setenv('EVENT_NAME', 'schedule')
    monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', 'true')
    main = Mock(side_effect=AssertionError('NO_ARCHIVE_MAIN'))
    monkeypatch.setattr(maintenance, 'main', main)
    with pytest.raises(SystemExit) as caught:
        exec(compile(script, '<synthetic-workflow>', 'exec'), {})
    assert caught.value.code == 0
    main.assert_not_called()
    assert 'ARCHIVE_SCHEDULE_HELD_NO_IO' in capsys.readouterr().out
    hold = source.split('  scheduled-hold:', 1)[1].split('  archive:', 1)[0]
    assert 'secrets.' not in hold
    assert 'checkout' not in hold
    assert 'options: [preview, export]' in source


def test_no_boolean_is_a_commissioning_receipt(monkeypatch):
    for name in ('ARCHIVE_DELETE_ENABLED', 'CUSTODY_VERIFIED', 'RESTORE_VERIFIED', 'ARCHIVE_COMMISSIONED'):
        monkeypatch.setenv(name, 'true')
    with pytest.raises(ArchiveError, match='AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED'):
        maintenance.require_commissioned_delete()
    assert os.environ['ARCHIVE_DELETE_ENABLED'] == 'true'
