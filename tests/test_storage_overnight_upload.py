"""The one complete inactive package and all prerequisites must exist exactly."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import reviewed_upload_check as checker


def test_exact_overnight_files_and_prerequisites() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / checker.OVERNIGHT_MANIFEST).read_bytes())
    assert manifest['version'] == 'storage-overnight-upload-v1'
    entries = manifest['groups']['overnight']
    checker.validate_files(root, entries, {entry['destination'] for entry in entries})
    checker.validate_files(root, manifest['prerequisites']['overnight'], set())
    assert all(entry['source'] == entry['destination'] for entry in entries)
    assert not any(entry['destination'].startswith('supabase/migrations/') for entry in entries)


def test_overnight_manifest_is_explicit_not_arbitrary_json() -> None:
    assert checker.relative(checker.OVERNIGHT_MANIFEST) == checker.OVERNIGHT_MANIFEST
    with pytest.raises(ValueError):
        checker.relative('private-credentials.json')


def test_overnight_cli_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                               capsys: pytest.CaptureFixture[str]) -> None:
    manifest = {'version': 'storage-overnight-upload-v1', 'groups': {'overnight': [
        {'destination': checker.OVERNIGHT_MANIFEST, 'sha256_lf': None}]}}
    (tmp_path / checker.OVERNIGHT_MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')

    def git(root: Path, *args: str) -> str:
        return {('rev-parse', 'HEAD'): 'a' * 40,
                ('rev-parse', '--show-toplevel'): str(tmp_path),
                ('diff', '--name-only', 'a' * 40, '--'): '',
                ('ls-files', '--others', '--exclude-standard'): checker.OVERNIGHT_MANIFEST}[args]

    monkeypatch.setattr(checker, 'git', git)
    args = ['--group', 'overnight', '--manifest', checker.OVERNIGHT_MANIFEST,
            '--base', 'a' * 40, '--root', str(tmp_path)]
    assert checker.main(args) == 0
    assert 'REQUIRES_TESTS_AND_CI' in capsys.readouterr().out
    args[1] = 'storage'
    assert checker.main(args) == 2
    assert 'MANIFEST_VERSION_INVALID' in capsys.readouterr().out
