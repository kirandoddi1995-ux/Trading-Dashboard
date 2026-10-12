"""Exact inactive recovery successor package, including negative CLI paths."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import reviewed_upload_check as check


def test_exact_files_and_prerequisites() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / check.RECOVERY_MANIFEST).read_bytes())
    assert manifest['version'] == 'storage-six-export-upload-v1'
    entries = manifest['groups']['six_export']
    assert len(entries) == 15
    check.validate_files(root, entries, {item['destination'] for item in entries})
    check.validate_files(root, manifest['prerequisites']['six_export'], set())
    assert all(item['source'] == item['destination'] for item in entries)
    names = {item['destination'] for item in entries}
    assert 'recovery_export.py' in names
    assert {'recovery_materialization.py', 'tests/test_recovery_materialization.py'} <= names
    assert not ({'recovery_materialization.py', 'tests/test_recovery_materialization.py'}
                & {item['destination'] for item in manifest['prerequisites']['six_export']})
    assert not any(name.startswith(('supabase/', 'staged_', '.github/')) for name in names)


def test_manifest_allowlist_and_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    assert check.relative(check.RECOVERY_MANIFEST) == check.RECOVERY_MANIFEST
    with pytest.raises(ValueError):
        check.relative('private-backup.json')
    manifest = {'version': 'storage-six-export-upload-v1', 'groups': {'six_export': [
        {'destination': check.RECOVERY_MANIFEST, 'sha256_lf': None}]}}
    (tmp_path / check.RECOVERY_MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
    def git(root: Path, *args: str) -> str:
        return {('rev-parse', 'HEAD'): 'a' * 40,
                ('rev-parse', '--show-toplevel'): str(tmp_path),
                ('diff', '--name-only', 'a' * 40, '--'): '',
                ('ls-files', '--others', '--exclude-standard'): check.RECOVERY_MANIFEST}[args]
    monkeypatch.setattr(check, 'git', git)
    args = ['--group', 'six_export', '--manifest', check.RECOVERY_MANIFEST,
            '--base', 'a' * 40, '--root', str(tmp_path)]
    assert check.main(args) == 0
    assert 'REQUIRES_TESTS_AND_CI' in capsys.readouterr().out
    args[1] = 'overnight'
    assert check.main(args) == 2
    assert 'MANIFEST_VERSION_INVALID' in capsys.readouterr().out
