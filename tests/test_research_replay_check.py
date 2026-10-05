"""Synthetic end-to-end evidence checks, never real forward observations."""
from dataclasses import replace
from contextlib import closing
import json
import sqlite3

import pytest

from archived_directional_replay import ReplayReference
import research_replay_check as runner
from research_integrity import IntegrityError
from research_replay_comparison import ObservationJournal
from test_archived_directional_replay import ROOT, setup_run


def invoke(archive, result, path):
    return runner.check(archive=archive, manifest_sha256=result['manifest_sha256'], journal_path=path,
                        source_root=ROOT, computed_at='2022-01-10T00:00:00+00:00')


def observed_fixture(path, result, omit=None):
    # Intentional synthetic fixture, not a real captured observation or producer.
    journal = ObservationJournal(path)
    for index, payload in enumerate(result['references']):
        if index != omit:
            replay = ReplayReference(payload).for_comparison('2022-01-10T00:00:00+00:00')
            journal.record(replace(replay, origin='OBSERVED'))
    return journal


def test_absent_journal_remains_missing_and_not_created(tmp_path):
    _, _, archive, result = setup_run(tmp_path)
    path = tmp_path / 'absent.sqlite'
    check = invoke(archive, result, path)
    assert check['status'] == 'ATTENTION_REQUIRED'
    assert check['journal_present'] is False and not path.exists()
    assert check['accepted_sessions'] == 5
    assert all(row['counts']['MISSING_OBSERVATION'] == 75 for row in check['sessions'])


def test_synthetic_full_comparison_is_not_live_or_fill_evidence(tmp_path):
    _, _, archive, result = setup_run(tmp_path)
    path = tmp_path / 'observations.sqlite'
    observed_fixture(path, result)
    check = invoke(archive, result, path)
    assert check['status'] == 'CHECKS_PASS'
    assert check['available_decision_matches'] + check['unavailable_decision_matches'] == 375
    assert check['approval_authority'] is False and check['fill_evidence'] is False
    assert check['live_capture_verified'] is False and check['automatic_actions'] == []


def test_one_missing_decision_blocks_whole_check(tmp_path):
    _, _, archive, result = setup_run(tmp_path)
    path = tmp_path / 'observations.sqlite'
    observed_fixture(path, result, omit=74)
    check = invoke(archive, result, path)
    assert check['status'] == 'ATTENTION_REQUIRED'
    assert check['sessions'][0]['counts']['MISSING_OBSERVATION'] == 1
    assert check['sessions'][0]['expected'] == 75


def test_excluded_session_prevents_complete_claim(tmp_path):
    def mutate(records, sessions):
        sessions[-1]['replay_eligible'] = False
        sessions[-1]['exclusion_reason'] = 'SYNTHETIC_CALENDAR_EXCLUSION'
    _, _, archive, result = setup_run(tmp_path, mutate)
    path = tmp_path / 'observations.sqlite'
    observed_fixture(path, result)
    check = invoke(archive, result, path)
    assert check['status'] == 'ATTENTION_REQUIRED'
    assert check['accepted_sessions'] == 4 and len(check['excluded_sessions']) == 1


def test_repository_journal_is_rejected(tmp_path):
    _, _, archive, result = setup_run(tmp_path)
    with pytest.raises(IntegrityError):
        invoke(archive, result, ROOT / 'forbidden-journal.sqlite')


def test_cli_missing_evidence_nonzero_without_secret_output(tmp_path, capsys):
    _, _, archive, result = setup_run(tmp_path)
    output = tmp_path / 'check.json'
    args = ['--archive', str(archive.root), '--manifest-sha256', result['manifest_sha256'],
            '--journal', str(tmp_path / 'absent.sqlite'), '--output', str(output)]
    assert runner.main(args) == 1
    assert json.loads(output.read_bytes())['status'] == 'ATTENTION_REQUIRED'
    assert str(tmp_path) not in capsys.readouterr().out
    assert runner.main(args) == 2
    assert 'BLOCKED' in capsys.readouterr().out


def test_checker_reads_journal_without_changing_it(tmp_path):
    _, _, archive, result = setup_run(tmp_path)
    path = tmp_path / 'observations.sqlite'
    observed_fixture(path, result)
    before = path.read_bytes()
    assert invoke(archive, result, path)['status'] == 'CHECKS_PASS'
    assert path.read_bytes() == before
    readonly = ObservationJournal(path, read_only=True)
    replay = ReplayReference(result['references'][0]).for_comparison('2022-01-10T00:00:00+00:00')
    with pytest.raises(IntegrityError, match='READ_ONLY'):
        readonly.record(replace(replay, origin='OBSERVED'))
    with closing(readonly.connect()) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute('CREATE TABLE forbidden (id INTEGER)')


def test_empty_existing_file_is_not_initialized_by_check(tmp_path):
    _, _, archive, result = setup_run(tmp_path)
    path = tmp_path / 'empty.sqlite'
    path.write_bytes(b'')
    with pytest.raises(sqlite3.OperationalError):
        invoke(archive, result, path)
    assert path.read_bytes() == b''


def test_cli_complete_synthetic_check_exit_zero(tmp_path, capsys):
    _, _, archive, result = setup_run(tmp_path)
    journal = tmp_path / 'observations.sqlite'
    observed_fixture(journal, result)
    output = tmp_path / 'complete.json'
    assert runner.main(['--archive', str(archive.root), '--manifest-sha256', result['manifest_sha256'],
                        '--journal', str(journal), '--output', str(output)]) == 0
    assert json.loads(output.read_bytes())['live_capture_verified'] is False
    assert json.loads(capsys.readouterr().out)['status'] == 'CHECKS_PASS'
