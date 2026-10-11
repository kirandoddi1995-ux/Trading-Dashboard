"""Offline folder identity/access checks with synthetic hidden inputs only."""
import json
import getpass
from pathlib import Path
import re
import sys
from typing import Any

import pytest

import forward_drive_folder_check as tool
from drive_archive import ArchiveError


def interactive(monkeypatch: pytest.MonkeyPatch, values: list[str]) -> None:
    class Terminal:
        def isatty(self) -> bool:
            return True

    answers = iter(values)
    monkeypatch.setattr(sys, 'stdin', Terminal())
    monkeypatch.setattr(getpass, 'getpass', lambda _: next(answers))


@pytest.mark.parametrize('stored,label', [('ID_ALPHA', 'A'), ('ID_BETA', 'B'),
                                        ('ID_GAMMA', 'C'), ('ID_OTHER', 'NONE')])
def test_compare_hidden_no_network(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], stored: str, label: str) -> None:
    interactive(monkeypatch, ['ID_ALPHA', 'ID_BETA', 'ID_GAMMA'])
    reads: list[str] = []

    def read(name: str) -> str:
        reads.append(name)
        return stored

    def forbidden(*args: object) -> Any:
        raise AssertionError('no network')

    monkeypatch.setattr(tool, 'read_secret', read)
    monkeypatch.setattr(tool, 'DriveArchive', forbidden)
    assert tool.main(['--compare']) == 0
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert record['stored_folder_match'] == label
    assert record['network_calls'] == record['writes'] == 0
    assert reads == ['OPTION_CAPTURE_DRIVE_FOLDER_ID']
    assert 'ID_' not in output.out + output.err


@pytest.mark.parametrize('values', [['SAME', 'SAME', 'OTHER'], ['https://private', 'B', 'C'],
                                  [' ', 'B', 'C'], ['X' * 201, 'B', 'C'], ['é', 'B', 'C']])
def test_invalid_inputs_before_vault(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], values: list[str]) -> None:
    interactive(monkeypatch, values)

    def forbidden(*args: object) -> str:
        raise AssertionError('must not read credential')

    monkeypatch.setattr(tool, 'read_secret', forbidden)
    assert tool.main(['--compare']) == 2
    assert json.loads(capsys.readouterr().out)['category'] == 'FOLDER_COMPARISON_INPUT_INVALID'


@pytest.mark.parametrize('status', [None, 404, 403])
def test_candidate_check_uses_existing_oauth_only(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], status: int | None) -> None:
    interactive(monkeypatch, ['ID_CANDIDATE'])
    reads: list[str] = []
    calls: list[str] = []

    def read(name: str) -> str:
        reads.append(name)
        return '{}'

    class Drive:
        def check_folder(self) -> None:
            calls.append('check')
            if status is not None:
                raise ArchiveError('DRIVE_HTTP_' + str(status))

        def close(self) -> None:
            calls.append('close')

    def create(oauth: object, folder: str) -> Drive:
        assert folder == 'ID_CANDIDATE'
        return Drive()

    monkeypatch.setattr(tool, 'read_secret', read)
    monkeypatch.setattr(tool, 'credentials', lambda _: object())
    monkeypatch.setattr(tool, 'DriveArchive', create)
    assert tool.main(['--check-candidate', 'B']) == (0 if status is None else 2)
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert reads == ['DRIVE_OAUTH_TOKEN_JSON']
    assert calls == ['check', 'close']
    assert record['candidate'] == 'B' and record['writes'] == 0
    assert 'ID_CANDIDATE' not in output.out + output.err
    if status is not None:
        assert record['category'] == 'DRIVE_HTTP_' + str(status)


def test_preview_and_noninteractive_read_nothing(monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    class Terminal:
        def isatty(self) -> bool:
            return False

    def forbidden(*args: object) -> Any:
        raise AssertionError('no secrets')

    monkeypatch.setattr(sys, 'stdin', Terminal())
    monkeypatch.setattr(tool, 'read_secret', forbidden)
    monkeypatch.setattr(getpass, 'getpass', forbidden)
    assert tool.main([]) == 0
    assert json.loads(capsys.readouterr().out)['credential_reads'] == 0
    assert tool.main(['--compare']) == 2
    assert json.loads(capsys.readouterr().out)['category'] == 'INTERACTIVE_PRIVATE_PROMPT_REQUIRED'


def test_unexpected_error_redacted(monkeypatch: pytest.MonkeyPatch,
                                 capsys: pytest.CaptureFixture[str]) -> None:
    interactive(monkeypatch, ['ID_ALPHA', 'ID_BETA', 'ID_GAMMA'])

    def read(name: str) -> str:
        raise RuntimeError('SECRET_PRIVATE_VALUE')

    monkeypatch.setattr(tool, 'read_secret', read)
    assert tool.main(['--compare']) == 2
    output = capsys.readouterr()
    assert 'SECRET_PRIVATE_VALUE' not in output.out + output.err
    assert json.loads(output.out)['stage'] == 'PRIVATE_FOLDER_READ'


@pytest.mark.parametrize('failure', [None, 'folder', 'readback'])
def test_owner_update_wrapper_only_changes_verified_folder(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], failure: str | None) -> None:
    """Execute reviewed owner instructions with wholly mocked credential/transport APIs."""
    import drive_archive
    import forward_windows_credentials as vault
    text = (Path(__file__).resolve().parents[1] / 'FORWARD_DRIVE_FOLDER_SELECTION.md').read_text(encoding='utf-8')
    match = re.search(r"@'\n(.*?)\n'@", text, re.DOTALL)
    assert match is not None
    writes: list[tuple[str, str]] = []
    reads: list[str] = []

    def read(name: str) -> str:
        reads.append(name)
        return '{}' if name == 'DRIVE_OAUTH_TOKEN_JSON' else ('WRONG' if failure == 'readback' else 'ID_SELECTED')

    class Drive:
        def check_folder(self) -> None:
            if failure == 'folder':
                raise ArchiveError('DRIVE_HTTP_404')

        def close(self) -> None:
            pass

    monkeypatch.setattr(getpass, 'getpass', lambda _: 'ID_SELECTED')
    monkeypatch.setattr(vault, 'read_secret', read)
    monkeypatch.setattr(vault, 'write_secret', lambda name, value: writes.append((name, value)))
    monkeypatch.setattr(drive_archive, 'credentials', lambda _: object())
    monkeypatch.setattr(drive_archive, 'DriveArchive', lambda *a: Drive())
    with pytest.raises(SystemExit) as exit_result:
        exec(compile(match.group(1), '<reviewed-owner-wrapper>', 'exec'), {})
    assert exit_result.value.code == (0 if failure is None else 2)
    assert writes == ([] if failure == 'folder' else [('OPTION_CAPTURE_DRIVE_FOLDER_ID', 'ID_SELECTED')])
    assert reads == (['DRIVE_OAUTH_TOKEN_JSON'] if failure == 'folder' else
                     ['DRIVE_OAUTH_TOKEN_JSON', 'OPTION_CAPTURE_DRIVE_FOLDER_ID'])
    output = capsys.readouterr()
    assert 'ID_SELECTED' not in output.out + output.err
