"""Adversarial exact-tree packaging checks without network or private files."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import overnight_programme_upload_check as check


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    files = ('example.py', check.MANIFESTS['future_ops'])
    monkeypatch.setattr(check, 'GROUP_FILES', {'future_ops': files})
    monkeypatch.setattr(check, 'GROUP_SEEDS', {'future_ops': ('example.py',)})
    monkeypatch.setattr(check, 'EXTRA_PINS', ('constraints.txt',))
    monkeypatch.setattr(check, 'guarded_members', lambda root, seeds: {'example.py', 'dependency.py'})
    for name in ('example.py', 'dependency.py', 'constraints.txt'):
        (tmp_path / name).write_bytes(b'# public\r\n')
    digest = hashlib.sha256(b'# public\n').hexdigest()
    manifest: dict[str, Any] = {
        'version': 'overnight-programme-v1', 'group': 'future_ops',
        'files': [{'destination': 'example.py', 'sha256_lf': digest},
                  {'destination': check.MANIFESTS['future_ops'], 'sha256_lf': None}],
        'seeds': ['example.py'], 'extra_pins': ['constraints.txt'],
        'prerequisites': [{'destination': name, 'sha256_lf': digest}
                          for name in ('dependency.py', 'constraints.txt')],
    }
    return tmp_path, manifest


def save(tree: tuple[Path, dict[str, Any]]) -> Path:
    root, manifest = tree
    (root / check.MANIFESTS['future_ops']).write_text(json.dumps(manifest), encoding='utf-8')
    return root


def test_exact_tree_and_lf_normalization(tree: tuple[Path, dict[str, Any]]) -> None:
    assert check.verify(save(tree), 'future_ops', set(check.GROUP_FILES['future_ops'])) == []


def test_changed_prerequisite_diagnostic(tree: tuple[Path, dict[str, Any]]) -> None:
    root = save(tree)
    (root / 'dependency.py').write_bytes(b'# new\n')
    failures = check.verify(root, 'future_ops', set(check.GROUP_FILES['future_ops']))
    assert failures == [{'path': 'dependency.py', 'expected': hashlib.sha256(b'# public\n').hexdigest(),
                         'actual': hashlib.sha256(b'# new\n').hexdigest()}]


@pytest.mark.parametrize('mutation', ['omitted_pin', 'duplicate_pin', 'extra_file', 'seed', 'hash', 'extra_pin'])
def test_controls_cannot_be_loosened(tree: tuple[Path, dict[str, Any]], mutation: str) -> None:
    _, plan = tree
    if mutation == 'omitted_pin':
        plan['prerequisites'].pop()
    elif mutation == 'duplicate_pin':
        plan['prerequisites'].append(plan['prerequisites'][0])
    elif mutation == 'extra_file':
        plan['files'].append({'destination': 'extra.py', 'sha256_lf': 'a' * 64})
    elif mutation == 'seed':
        plan['seeds'] = ['dependency.py']
    elif mutation == 'hash':
        plan['files'][0]['sha256_lf'] = None
    else:
        plan['extra_pins'] = ['dependency.py']
    with pytest.raises(ValueError):
        check.verify(save(tree), 'future_ops', set(check.GROUP_FILES['future_ops']))


@pytest.mark.parametrize('name', ['../private.py', '/absolute.py', 'x\\private.py', 'secrets.toml',
                                  'client_secret.json', 'unknown.json', 'tests/../private.py'])
def test_private_or_non_public_paths_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match='PUBLIC_SOURCE_PATH_REQUIRED'):
        check.public_path(tmp_path, name)


def test_hyphenated_requirements_allowed(tmp_path: Path) -> None:
    path = tmp_path / 'requirements-forward-operations.txt'
    path.write_bytes(b'# public')
    assert check.public_path(tmp_path, path.name) == path


def test_duplicate_json_keys_rejected(tree: tuple[Path, dict[str, Any]]) -> None:
    root = save(tree)
    (root / check.MANIFESTS['future_ops']).write_text('{"group":"future_ops","group":"application"}')
    with pytest.raises(ValueError):
        check.verify(root, 'future_ops', set(check.GROUP_FILES['future_ops']))


@pytest.mark.parametrize('condition', ['stale_head', 'unstaged', 'not_root'])
def test_git_baseline_and_index_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                     capsys: pytest.CaptureFixture[str], condition: str) -> None:
    monkeypatch.chdir(tmp_path)
    def fake_git(root: Path, *args: str) -> str:
        if args == ('rev-parse', 'HEAD'):
            return 'b' * 40 if condition == 'stale_head' else 'a' * 40
        if args == ('rev-parse', '--show-toplevel'):
            return str(root / 'other') if condition == 'not_root' else str(root)
        if args == ('diff', '--name-only', '--'):
            return 'example.py' if condition == 'unstaged' else ''
        raise AssertionError('unexpected Git operation')
    monkeypatch.setattr(check, 'git', fake_git)
    assert check.main(['--base', 'a' * 40, '--group', 'future_ops']) == 2
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'BLOCKED' and output['hosted_changes'] == 0


@pytest.mark.parametrize('dependency', ['token_state.py', 'huge.py'])
def test_discovery_guards_before_source_read(tmp_path: Path, dependency: str) -> None:
    (tmp_path / 'entry.py').write_text('import ' + dependency[:-3])
    (tmp_path / dependency).write_bytes(b'x' * (check.MAX_BYTES + 1) if dependency == 'huge.py' else b'not valid python')
    with pytest.raises(ValueError, match='PUBLIC_SOURCE_PATH_REQUIRED|SOURCE_MISSING_OR_TOO_LARGE'):
        check.guarded_members(tmp_path, ['entry.py'])


def test_discovery_follows_static_and_literal_imports(tmp_path: Path) -> None:
    (tmp_path / 'entry.py').write_text("import first\n__import__('second')\n")
    for name in ('first.py', 'second.py'):
        (tmp_path / name).write_text('# public')
    assert check.guarded_members(tmp_path, ['entry.py']) == {'entry.py', 'first.py', 'second.py'}


def test_untracked_package_is_not_staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    def fake_git(root: Path, *args: str) -> str:
        if args == ('rev-parse', 'HEAD'):
            return 'a' * 40
        if args == ('rev-parse', '--show-toplevel'):
            return str(root)
        if args[0] == 'diff':
            return ''
        return '\n'.join(check.GROUP_FILES['future_ops'])
    monkeypatch.setattr(check, 'git', fake_git)
    assert check.main(['--base', 'a' * 40, '--group', 'future_ops']) == 2
    assert json.loads(capsys.readouterr().out)['rule'] == 'STAGE_THEN_RECHECK'


def test_index_bytes_cannot_diverge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'entry.py').write_bytes(b'# reviewed\n')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, b'# other\n'))
    failures = check.index_matches(tmp_path, {'entry.py'})
    assert failures[0]['path'] == 'entry.py'
    assert failures[0]['expected'] != failures[0]['actual']


def test_relative_dynamic_import_is_rejected(tmp_path: Path) -> None:
    (tmp_path / 'entry.py').write_text("importlib.import_module('.child', package='localpkg')")
    with pytest.raises(ValueError, match='PUBLIC_SOURCE_PATH_REQUIRED'):
        check.guarded_members(tmp_path, ['entry.py'])


def test_main_binds_prerequisite_index_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    queried: list[set[str]] = []
    def fake_git(root: Path, *args: str) -> str:
        if args == ('rev-parse', 'HEAD'):
            return 'a' * 40
        if args == ('rev-parse', '--show-toplevel'):
            return str(root)
        if args[:2] == ('diff', '--cached'):
            return '\n'.join(check.GROUP_FILES['future_ops'])
        return ''
    monkeypatch.setattr(check, 'git', fake_git)
    monkeypatch.setattr(check, 'verify', lambda *a: [])
    monkeypatch.setattr(check, 'guarded_members', lambda *a: {'dependency.py'})
    def capture(root: Path, names: set[str]) -> list[dict[str, str]]:
        queried.append(names)
        return []
    monkeypatch.setattr(check, 'index_matches', capture)
    assert check.main(['--base', 'a' * 40, '--group', 'future_ops']) == 0
    assert {'dependency.py', 'constraints.txt'} <= queried[0]
