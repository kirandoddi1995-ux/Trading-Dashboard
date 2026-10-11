"""Synthetic Drive check wiring; no actual vault or network access."""
import json
from typing import Any

import pytest

import forward_drive_probe as probe
from drive_archive import ArchiveError


def test_preview_has_no_credentials_or_transport(monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object) -> Any:
        raise AssertionError('offline preview')

    monkeypatch.setattr(probe, 'read_secret', forbidden)
    monkeypatch.setattr(probe, 'DriveArchive', forbidden)
    assert probe.main([]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['network_calls'] == record['credential_reads'] == record['writes'] == 0


@pytest.mark.parametrize('fail', [False, True])
def test_check_reads_only_drive_credentials(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], fail: bool) -> None:
    reads: list[str] = []
    calls: list[str] = []

    def read(name: str) -> str:
        reads.append(name)
        assert name in ('DRIVE_OAUTH_TOKEN_JSON', 'OPTION_CAPTURE_DRIVE_FOLDER_ID')
        return '{}' if name == 'DRIVE_OAUTH_TOKEN_JSON' else 'SYNTHETIC_PRIVATE_FOLDER'

    class Drive:
        def check_folder(self) -> None:
            calls.append('check')
            if fail:
                raise ArchiveError('DRIVE_HTTP_403')

        def close(self) -> None:
            calls.append('close')

    monkeypatch.setattr(probe, 'read_secret', read)
    monkeypatch.setattr(probe, 'credentials', lambda _: object())
    monkeypatch.setattr(probe, 'DriveArchive', lambda *a: Drive())
    assert probe.main(['--check']) == (2 if fail else 0)
    output = capsys.readouterr()
    assert 'SYNTHETIC_PRIVATE_FOLDER' not in output.out + output.err
    assert reads == ['DRIVE_OAUTH_TOKEN_JSON', 'OPTION_CAPTURE_DRIVE_FOLDER_ID']
    assert calls == ['check', 'close']
    record = json.loads(output.out)
    assert record['writes'] == record['market_network_calls'] == 0
    if fail:
        assert record['stage'] == 'DRIVE_FOLDER_CHECK'
        assert record['category'] == 'DRIVE_HTTP_403'
    else:
        assert record['remote_bundle_verified'] is False


def test_vault_failure_redacted(monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    def read(name: str) -> str:
        raise RuntimeError('SYNTHETIC_SECRET private-path')

    monkeypatch.setattr(probe, 'read_secret', read)
    assert probe.main(['--check']) == 2
    output = capsys.readouterr()
    assert 'SYNTHETIC_SECRET' not in output.out + output.err
    assert json.loads(output.out)['stage'] == 'PRIVATE_CREDENTIAL_READ'
