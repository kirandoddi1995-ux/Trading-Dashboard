"""New upload group cannot silently accept unrelated or stale file sets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import reviewed_upload_check as check
from test_reviewed_upload_check import entry


def test_ledger_manifest_explicit_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                      capsys: Any) -> None:
    (tmp_path / 'sample.py').write_bytes(b'pass')
    manifest = {'version': 'storage-native-ledger-upload-v1', 'groups': {'native_ledger': [
        entry('sample.py', b'pass'), {'destination': check.LEDGER_MANIFEST, 'sha256_lf': None}]}}
    (tmp_path / check.LEDGER_MANIFEST).write_text(json.dumps(manifest), encoding='utf-8')
    def git(root: Path, *args: str) -> str:
        return {('rev-parse', 'HEAD'): 'a' * 40,
                ('rev-parse', '--show-toplevel'): str(tmp_path),
                ('diff', '--name-only', 'a' * 40, '--'): '',
                ('ls-files', '--others', '--exclude-standard'): 'sample.py\n' + check.LEDGER_MANIFEST}[args]
    monkeypatch.setattr(check, 'git', git)
    args = ['--group', 'native_ledger', '--manifest', check.LEDGER_MANIFEST,
            '--base', 'a' * 40, '--root', str(tmp_path)]
    assert check.main(args) == 0
    assert 'REQUIRES_TESTS_AND_CI' in capsys.readouterr().out
    assert check.main(['--group', 'foundation', '--manifest', check.LEDGER_MANIFEST,
                       '--base', 'a' * 40, '--root', str(tmp_path)]) == 2
    assert 'MANIFEST_VERSION_INVALID' in capsys.readouterr().out


def test_delivered_upload_manifest_exact_sources_and_dependencies() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / check.LEDGER_MANIFEST).read_bytes())
    entries = manifest['groups']['native_ledger']
    # Historical package hashes stay immutable. Files superseded by the reviewed
    # next package are checked against that package, not their old release bytes.
    successor = json.loads((root / check.OVERNIGHT_MANIFEST).read_bytes())
    current = successor['groups']['overnight']
    superseded = {item['destination'] for item in current}
    check.validate_files(root, [item for item in entries
                               if item['destination'] not in superseded], set())
    check.validate_files(root, current, set())
    check.validate_files(root, manifest['prerequisites']['native_ledger'], set())
    assert all(item['source'] == item['destination'] for item in entries)
    names = {item['destination'] for item in entries}
    assert 'storage_native_ledger_conformance.py' in names
    assert check.NATIVE_WORKFLOW in names
    assert 'sql/storage_native_ledger_fixture_disposable_only.sql' in names
