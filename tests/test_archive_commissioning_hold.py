"""Production gate is NOT monkeypatched here. No hosted/archive IO allowed.

Since 4 Nov 2026 deletion is possible only with a passing restore proof produced by
archive_restore_check.prove() in the same process (ARCHIVE_DELETION_RECOMMISSIONING_2026-11-04.md).
Flags and environment variables still never unlock it.
"""
import datetime as dt
import os
from pathlib import Path
import textwrap
import urllib.request
from unittest.mock import Mock

import pytest

import archive_maintenance as maintenance
import archive_restore_check as restore_check
from drive_archive import ArchiveError, SPECS


@pytest.fixture(autouse=True)
def no_active_proof(monkeypatch):
    monkeypatch.setattr(maintenance, '_ACTIVE_PROOF', None)


def proof(**changes):
    values = dict(manifests=3, presence_verified=3, deep_batches=1, deep_rows=10, exact_rows=10,
                  added_column_rows=0, failures=(), issuer=restore_check._ISSUER)
    values.update(changes)
    return restore_check.RestoreProof(**values)


@pytest.mark.parametrize('flag', [None, 'false', 'TRUE'])
@pytest.mark.parametrize('table', tuple(SPECS))
def test_cli_delete_without_owner_flag_never_reaches_database_or_credentials(monkeypatch, capsys, flag, table):
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
    assert 'DELETION_NOT_ENABLED' in capsys.readouterr().out
    repository.assert_not_called()
    credentials.assert_not_called()
    drive.assert_not_called()


@pytest.mark.parametrize('failing', [proof(failures=('abc:DATA_FILE_CHECKSUM',)), proof(presence_verified=2)])
def test_cli_delete_with_failing_restore_proof_never_selects_or_deletes(monkeypatch, capsys, failing):
    monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', 'true')
    repo = Mock()
    repo.preview.return_value = 5
    monkeypatch.setattr(maintenance, 'ArchiveRepository', lambda url: repo)
    monkeypatch.setattr(maintenance, 'build_drive_credentials', Mock())
    monkeypatch.setattr(maintenance, 'DriveArchive', Mock())
    monkeypatch.setattr(restore_check, 'prove', lambda *args, **kwargs: failing)
    batch = Mock(side_effect=AssertionError('NO_BATCH'))
    monkeypatch.setattr(maintenance, 'run_batch', batch)
    assert maintenance.main(['--mode', 'delete', '--table', 'growing']) == 1
    assert 'ARCHIVE_RESTORE_PROOF_FAILED' in capsys.readouterr().out
    batch.assert_not_called()
    repo.select.assert_not_called()
    repo.acknowledge.assert_not_called()
    assert maintenance._ACTIVE_PROOF is None


def test_cli_restore_check_is_read_only_and_reports(monkeypatch, capsys):
    repo = Mock()
    repo.preview.return_value = 0
    monkeypatch.setattr(maintenance, 'ArchiveRepository', lambda url: repo)
    monkeypatch.setattr(maintenance, 'build_drive_credentials', Mock())
    drive = Mock()
    monkeypatch.setattr(maintenance, 'DriveArchive', Mock(return_value=drive))
    seen = {}
    monkeypatch.setattr(restore_check, 'prove', lambda *args, **kwargs: seen.update(kwargs) or proof())
    batch = Mock(side_effect=AssertionError('NO_BATCH'))
    monkeypatch.setattr(maintenance, 'run_batch', batch)
    assert maintenance.main(['--mode', 'restore-check', '--table', 'market_quotes']) == 0
    assert seen['everything'] is True
    assert '"restore_proof": "PASSED"' in capsys.readouterr().out
    drive.check_folder.assert_not_called()  # read-only: no write capability required
    batch.assert_not_called()
    repo.acknowledge.assert_not_called()
    assert maintenance._ACTIVE_PROOF is None


def test_hand_built_proof_never_unlocks_deletion():
    # A passing-looking proof not issued by prove() is rejected (CodeAnt finding, PR #71).
    forged = restore_check.RestoreProof(manifests=0, presence_verified=0, deep_batches=0, deep_rows=0,
                                        exact_rows=0, added_column_rows=0, failures=())
    assert not forged.valid_now()
    with pytest.raises(ArchiveError, match='ARCHIVE_RESTORE_PROOF_FAILED'):
        maintenance.activate_restore_proof(forged)
    with pytest.raises(ArchiveError, match='AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED'):
        maintenance.require_commissioned_delete()


def test_presence_is_rechecked_before_every_deleting_batch(monkeypatch, capsys):
    monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', 'true')
    repo = Mock()
    repo.preview.return_value = 5
    monkeypatch.setattr(maintenance, 'ArchiveRepository', lambda url: repo)
    monkeypatch.setattr(maintenance, 'build_drive_credentials', Mock())
    monkeypatch.setattr(maintenance, 'DriveArchive', Mock())
    monkeypatch.setattr(restore_check, 'prove', lambda *args, **kwargs: proof())
    calls = []

    def recheck(repo, drive, proof):
        calls.append('recheck')
        if calls.count('recheck') == 2:
            raise ArchiveError('ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF')
        return 3
    monkeypatch.setattr(restore_check, 'recheck_presence', recheck)
    batch = Mock(side_effect=lambda *args: calls.append('batch') or
                 {'selected': 1, 'verified': 1, 'deleted': 1, 'retained': 0})
    monkeypatch.setattr(maintenance, 'run_batch', batch)
    assert maintenance.main(['--mode', 'delete', '--table', 'market_quotes', '--max-batches', '5']) == 1
    assert calls == ['recheck', 'batch', 'recheck']
    assert 'ARCHIVE_PRESENCE_CHANGED_SINCE_PROOF' in capsys.readouterr().out


def test_proof_activation_rules(monkeypatch):
    with pytest.raises(ArchiveError, match='ARCHIVE_RESTORE_PROOF_FAILED'):
        maintenance.activate_restore_proof(proof(failures=('x:DATA_FILE_MISSING',)))
    with pytest.raises(ArchiveError, match='ARCHIVE_RESTORE_PROOF_FAILED'):
        maintenance.activate_restore_proof({'manifests': 3, 'failures': []})
    stale = proof()
    monkeypatch.setattr(restore_check.time, 'monotonic', lambda: stale.created + restore_check.PROOF_MAX_AGE_SECONDS + 1)
    with pytest.raises(ArchiveError, match='ARCHIVE_RESTORE_PROOF_FAILED'):
        maintenance.activate_restore_proof(stale)
    monkeypatch.undo()
    monkeypatch.setattr(maintenance, '_ACTIVE_PROOF', None)
    maintenance.activate_restore_proof(proof())
    maintenance.require_commissioned_delete()


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


def _launcher():
    source = (Path(__file__).resolve().parents[1] / '.github/workflows/drive-archive.yml').read_text()
    script = textwrap.dedent(source.split("python - <<'PY'\n", 1)[1].rsplit('          PY', 1)[0])
    return source, script


def test_actual_scheduled_launcher_holds_without_nightly_owner_variable(monkeypatch, capsys):
    """The real launcher holds the schedule (no IO, no secrets) until nightly delete is on."""
    source, script = _launcher()
    monkeypatch.setenv('EVENT_NAME', 'schedule')
    monkeypatch.setenv('ARCHIVE_DELETE_ENABLED', 'true')
    monkeypatch.delenv('NIGHTLY_DELETE', raising=False)
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
    assert "vars.ARCHIVE_NIGHTLY_DELETE != 'true'" in hold
    assert 'options: [preview, export, restore-check, delete, prune-preserved, nightly]' in source


def test_actual_scheduled_launcher_runs_restore_proven_growing_retention(monkeypatch):
    """With the owner variable on and no Actions token, the schedule runs the retention (no API call)."""
    _, script = _launcher()
    monkeypatch.setenv('EVENT_NAME', 'schedule')
    monkeypatch.setenv('NIGHTLY_DELETE', 'true')
    monkeypatch.delenv('ACTIONS_READ_TOKEN', raising=False)
    requests = []
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *args, **kwargs: requests.append(args))
    main = Mock(return_value=0)
    monkeypatch.setattr(maintenance, 'main', main)
    with pytest.raises(SystemExit) as caught:
        exec(compile(script, '<synthetic-workflow>', 'exec'), {})
    assert caught.value.code == 0
    assert requests == []
    main.assert_called_once_with(['--mode', 'delete', '--table', 'growing', '--max-batches', '100'])


def test_no_boolean_is_a_commissioning_receipt(monkeypatch):
    for name in ('ARCHIVE_DELETE_ENABLED', 'CUSTODY_VERIFIED', 'RESTORE_VERIFIED', 'ARCHIVE_COMMISSIONED',
                 'ARCHIVE_NIGHTLY_DELETE', 'NIGHTLY_DELETE'):
        monkeypatch.setenv(name, 'true')
    with pytest.raises(ArchiveError, match='AUTHENTICATED_CUSTODY_AND_RESTORE_NOT_COMMISSIONED'):
        maintenance.require_commissioned_delete()
    assert os.environ['ARCHIVE_DELETE_ENABLED'] == 'true'
