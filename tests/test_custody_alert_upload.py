"""Exact public package and safe failure paths; no Git writes or hosted calls."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

import custody_alert_upload_check as check
import reviewed_upload_check as base


def test_exact_package_and_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    check.validate(root, set(check.FILES))
    with pytest.raises(ValueError):
        check.validate(root, set(check.FILES) | {'client_secret.json'})


@pytest.mark.parametrize('damage', ['hash', 'extra', 'mapping', 'prerequisite', 'missing'])
def test_broken_package_blocks(tmp_path: Path, damage: str) -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / check.MANIFEST).read_bytes())
    for entry in manifest['files'] + manifest['prerequisites']:
        if entry['destination'] == check.MANIFEST:
            continue
        target = tmp_path / entry['destination']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / entry['destination'], target)
    if damage == 'hash':
        manifest['files'][0]['sha256_lf'] = 'f'*64
    elif damage == 'extra':
        manifest['files'].append({'source': 'private.json', 'destination': 'private.json', 'sha256_lf': None})
    elif damage == 'mapping':
        manifest['files'][0]['source'] = 'staged_replacement.py'
    elif damage == 'prerequisite':
        manifest['prerequisites'].pop()
    else:
        (tmp_path / 'storage_alert_delivery.py').unlink()
    (tmp_path / check.MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        check.validate(tmp_path, set(check.FILES))


def test_cli_exact_base_and_redacted_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    def git(root: Path, *args: str) -> str:
        return {('rev-parse', 'HEAD'): 'a'*40,
                ('rev-parse', '--show-toplevel'): str(tmp_path),
                ('diff', '--name-only', 'a'*40, '--'): '',
                ('ls-files', '--others', '--exclude-standard'): ''}[args]
    monkeypatch.setattr(base, 'git', git)
    called = []
    monkeypatch.setattr(check, 'validate', lambda root, changes: called.append((root, changes)))
    assert check.main(['--base', 'a'*40, '--root', str(tmp_path)]) == 0
    assert len(called) == 1
    assert 'REQUIRES_TESTS_AND_CI' in capsys.readouterr().out
    assert check.main(['--base', 'b'*40, '--root', str(tmp_path)]) == 2
    assert len(called) == 1
    assert 'BLOCKED' in capsys.readouterr().out
