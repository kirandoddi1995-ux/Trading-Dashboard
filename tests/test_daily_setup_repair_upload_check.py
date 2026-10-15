"""Disposable synthetic Git trees only; no workspace manifests or external data."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import TypedDict

import pytest

import daily_setup_repair_upload_check as check


class Pin(TypedDict):
    path: str
    sha256_lf: str | None


class Control(TypedDict):
    version: str
    base: str
    files: list[Pin]
    prerequisites: list[Pin]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


@dataclass
class Tree:
    root: Path
    base: str
    control: Control
    baseline: dict[str, bytes]

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ['git', '-C', str(self.root), '-c', 'user.name=Synthetic',
             '-c', 'user.email=synthetic@example.invalid',
             '-c', 'commit.gpgsign=false', *args],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return result.stdout.decode('utf-8').strip()

    def write(self, name: str, raw: bytes) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def write_control(self) -> None:
        self.write(check.CONTROL, json.dumps(self.control).encode('utf-8'))
        self.git('add', '--', check.CONTROL)

    def replace(self, name: str, raw: bytes, *, repin: bool = False) -> None:
        self.write(name, raw)
        self.git('add', '--', name)
        if repin:
            for pin in self.control['files'] + self.control['prerequisites']:
                if pin['path'] == name:
                    pin['sha256_lf'] = sha(raw)
            self.write_control()

    def verify(self) -> list[dict[str, str]]:
        return check.verify(self.root, self.base)


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tree:
    # Ignore inherited Git repositories, configuration, signing and attributes.
    for key in list(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_CONFIG_SYSTEM', os.devnull)
    monkeypatch.setenv('GIT_ATTR_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_TERMINAL_PROMPT', '0')
    root = tmp_path / 'synthetic-repo'
    root.mkdir()
    template = tmp_path / 'empty-template'
    template.mkdir()
    control: Control = {
        'version': 'daily-setup-diagnostics-v1', 'base': '',
        'files': [], 'prerequisites': [],
    }
    result = Tree(root, '', control, {})
    result.git('init', '--object-format=sha1', '--template=' + str(template))
    for key, value in (
        ('core.autocrlf', 'false'), ('core.filemode', 'false'),
        ('core.attributesfile', os.devnull),
        ('core.hooksPath', str(template)),
    ):
        result.git('config', '--local', key, value)
    for name in check.PRIOR + check.MODIFIED:
        raw = f'synthetic baseline: {name}\n'.encode('ascii')
        if name == 'resilience_policy.json':
            raw = b'{"synthetic_policy":true}\n'
        elif name == 'resilience_policy.sha256':
            raw = hashlib.sha256(result.baseline['resilience_policy.json']).hexdigest().encode('ascii') + b'\n'
        result.baseline[name] = raw
        result.write(name, raw)
    result.git('add', '--all')
    result.git('commit', '-m', 'Synthetic immutable baseline')
    result.base = result.git('rev-parse', 'HEAD')
    monkeypatch.setattr(check, 'BASE', result.base)
    control['base'] = result.base
    for name in check.MODIFIED + check.ADDED:
        if name != check.CONTROL:
            raw = f'synthetic candidate: {name}\n'.encode('ascii')
            result.write(name, raw)
            control['files'].append({'path': name, 'sha256_lf': sha(raw)})
        else:
            control['files'].append({'path': name, 'sha256_lf': None})
    control['prerequisites'] = [
        {'path': name, 'sha256_lf': sha(result.baseline[name])} for name in check.PRIOR]
    result.write_control()
    result.git('add', '--', *check.MODIFIED, *check.ADDED)
    return result


def test_exact_seven_file_package_and_cli(
    tree: Tree, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {f'M\t{name}' for name in check.MODIFIED} | {f'A\t{name}' for name in check.ADDED}
    assert len(expected) == 7
    assert set(tree.git('diff', '--cached', '--name-status', '--no-renames').splitlines()) == expected
    assert tree.verify() == []
    monkeypatch.chdir(tree.root)
    assert check.main(['--base', tree.base]) == 0
    output = capsys.readouterr()
    assert output.err == ''
    assert json.loads(output.out) == {
        'status': 'SETUP_DIAGNOSTICS_PACKAGE_VERIFIED_REQUIRES_EXACT_COMMIT_CI',
        'failures': [], 'hosted_changes': 0,
    }


@pytest.mark.parametrize('base', ['', 'HEAD', '0' * 40, 'd5cd80f41a52de902d23cb81d761e7bb720e710c'])
def test_wrong_base_rejected(tree: Tree, base: str) -> None:
    with pytest.raises(ValueError, match='^EXACT_GREEN_BASE_REQUIRED$'):
        check.verify(tree.root, base)


def test_head_must_still_equal_baseline(tree: Tree) -> None:
    tree.git('commit', '--allow-empty', '--only', '-m', 'Different synthetic HEAD')
    with pytest.raises(ValueError, match='^EXACT_GREEN_BASE_REQUIRED$'):
        tree.verify()


def test_nested_directory_is_not_clone_root(tree: Tree) -> None:
    with pytest.raises(ValueError, match='^CLONE_ROOT_REQUIRED$'):
        check.verify(tree.root / 'tests', tree.base)


@pytest.mark.parametrize('name', check.MODIFIED + check.ADDED)
def test_missing_candidate_path_rejected(tree: Tree, name: str) -> None:
    if name in check.MODIFIED:
        tree.git('restore', '--source=HEAD', '--staged', '--worktree', '--', name)
    else:
        tree.git('rm', '--force', '--', name)
    with pytest.raises(ValueError, match='^EXACT_SEVEN_PATHS_REQUIRED$'):
        tree.verify()


@pytest.mark.parametrize('mutation', ['extra-staged', 'untracked', 'unstaged', 'deleted-staged', 'prior-staged'])
def test_dirty_or_wrong_staged_paths_rejected(tree: Tree, mutation: str) -> None:
    rule = 'EXACT_SEVEN_PATHS_REQUIRED'
    if mutation in {'extra-staged', 'untracked'}:
        tree.write('synthetic-extra.txt', b'extra\n')
        if mutation == 'extra-staged':
            tree.git('add', '--', 'synthetic-extra.txt')
        else:
            rule = 'STAGE_EXACT_PACKAGE_THEN_CHECK'
    elif mutation == 'unstaged':
        tree.write(check.MODIFIED[0], b'unstaged synthetic content\n')
        rule = 'STAGE_EXACT_PACKAGE_THEN_CHECK'
    elif mutation == 'deleted-staged':
        tree.git('rm', '--force', '--', check.MODIFIED[0])
    else:
        tree.replace(check.PRIOR[0], b'changed synthetic prerequisite\n')
    with pytest.raises(ValueError, match=f'^{rule}$'):
        tree.verify()


@pytest.mark.parametrize('name', check.MODIFIED + tuple(n for n in check.ADDED if n != check.CONTROL))
def test_bad_hash_reports_path_expected_actual_and_cli(
    tree: Tree, name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    old = (tree.root / name).read_bytes()
    changed = b'synthetic changed candidate\n'
    tree.replace(name, changed)
    failures = [{'path': name, 'expected': sha(old), 'actual': sha(changed)}]
    assert tree.verify() == failures
    monkeypatch.chdir(tree.root)
    assert check.main(['--base', tree.base]) == 2
    output = capsys.readouterr()
    assert output.err == ''
    assert json.loads(output.out) == {'status': 'BLOCKED', 'failures': failures, 'hosted_changes': 0}


@pytest.mark.parametrize('name', check.PRIOR)
def test_prerequisite_pin_cannot_be_rebound(tree: Tree, name: str) -> None:
    for pin in tree.control['prerequisites']:
        if pin['path'] == name:
            pin['sha256_lf'] = '0' * 64
    tree.write_control()
    with pytest.raises(ValueError, match='^PREREQUISITE_REBINDING_REJECTED$'):
        tree.verify()


@pytest.mark.parametrize('mutation,rule', [
    ('version', 'CONTROL_INVALID'), ('base', 'CONTROL_INVALID'),
    ('extra-field', 'CONTROL_INVALID'), ('missing-field', 'CONTROL_INVALID'),
    ('missing-pin', 'EXACT_PACKAGE_REQUIRED'), ('missing-prior', 'EXACT_PACKAGE_REQUIRED'),
    ('duplicate-pin', 'CONTROL_PINS_INVALID'), ('unknown-path', 'CONTROL_PINS_INVALID'),
    ('bad-hash', 'CONTROL_PINS_INVALID'), ('null-prior', 'CONTROL_PINS_INVALID'),
    ('pins-not-list', 'CONTROL_PINS_INVALID'), ('self-hash', 'CONTROL_SELF_PIN_INVALID'),
])
def test_malformed_control_rejected(tree: Tree, mutation: str, rule: str) -> None:
    plan: dict[str, object] = dict(tree.control)
    if mutation in {'version', 'base'}:
        plan[mutation] = 'synthetic-invalid'
    elif mutation == 'extra-field':
        plan['unexpected'] = True
    elif mutation == 'missing-field':
        del plan['version']
    elif mutation == 'missing-pin':
        tree.control['files'].pop(0)
    elif mutation == 'missing-prior':
        tree.control['prerequisites'].pop()
    elif mutation == 'duplicate-pin':
        tree.control['files'].append(tree.control['files'][0].copy())
    elif mutation == 'unknown-path':
        tree.control['files'][0]['path'] = 'synthetic-unknown.txt'
    elif mutation == 'bad-hash':
        tree.control['files'][0]['sha256_lf'] = 'not-a-sha256'
    elif mutation == 'null-prior':
        tree.control['prerequisites'][0]['sha256_lf'] = None
    elif mutation == 'pins-not-list':
        plan['files'] = {}
    else:
        for pin in tree.control['files']:
            if pin['path'] == check.CONTROL:
                pin['sha256_lf'] = '0' * 64
    tree.replace(check.CONTROL, json.dumps(plan).encode('utf-8'))
    with pytest.raises(ValueError, match=f'^{rule}$'):
        tree.verify()


@pytest.mark.parametrize('raw,rule', [
    (b'{"base":1,"base":2}', 'DUPLICATE_CONTROL_FIELD'),
    (b'{"files":[{"path":"a","path":"b"}]}', 'DUPLICATE_CONTROL_FIELD'),
    (b'{synthetic invalid json', 'PUBLIC_PACKAGE_REVIEW_REQUIRED'),
    (b'\xff', 'PUBLIC_PACKAGE_REVIEW_REQUIRED'),
    (b'[]', 'CONTROL_INVALID'),
])
def test_invalid_json_cli_redacts_errors(
    tree: Tree, raw: bytes, rule: str, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tree.replace(check.CONTROL, raw)
    monkeypatch.chdir(tree.root)
    assert check.main(['--base', tree.base]) == 2
    output = capsys.readouterr()
    assert output.err == ''
    assert json.loads(output.out) == {
        'status': 'BLOCKED', 'rule': rule, 'raw_error_printed': False, 'hosted_changes': 0,
    }


def test_historical_manifests_and_prerequisites_remain_byte_identical(tree: Tree) -> None:
    before_status = tree.git('status', '--porcelain=v1')
    before_control = (tree.root / check.CONTROL).read_bytes()
    assert tree.verify() == []
    assert tree.git('status', '--porcelain=v1') == before_status
    assert (tree.root / check.CONTROL).read_bytes() == before_control
    for name in check.PRIOR:
        assert (tree.root / name).read_bytes() == tree.baseline[name]
        assert check.blob(tree.root, f'{tree.base}:{name}') == tree.baseline[name]
        assert check.blob(tree.root, ':' + name) == tree.baseline[name]
    assert tree.git('diff', '--cached', '--name-only', '--', *check.PRIOR) == ''


@pytest.mark.parametrize('name', [check.MODIFIED[0], check.ADDED[0]])
def test_executable_index_mode_rejected_without_filesystem_permissions(tree: Tree, name: str) -> None:
    tree.git('update-index', '--chmod=+x', '--', name)
    with pytest.raises(ValueError, match='^REGULAR_STAGE_ZERO_BLOB_REQUIRED$'):
        tree.verify()


@pytest.mark.parametrize('length', [0, 512 * 1024])
def test_binary_candidate_within_source_bounds(tree: Tree, length: int) -> None:
    tree.replace(check.ADDED[0], b'\x00' * length, repin=True)
    assert tree.verify() == []


def test_source_bound_rejects_oversize_binary_candidate(tree: Tree) -> None:
    tree.replace(check.ADDED[0], b'\x00' * (512 * 1024 + 1), repin=True)
    with pytest.raises(ValueError, match='^PUBLIC_SOURCE_MISSING_OR_TOO_LARGE$'):
        tree.verify()


@pytest.mark.parametrize('length', [2 * 1024 * 1024, 2 * 1024 * 1024 + 1])
def test_actual_git_blob_binary_bound(tree: Tree, length: int) -> None:
    name = check.ADDED[0]
    raw = b'\x00' * length
    tree.replace(name, raw)
    if length == 2 * 1024 * 1024:
        assert check.blob(tree.root, ':' + name) == raw
    else:
        with pytest.raises(ValueError, match='^PUBLIC_BLOB_INVALID$'):
            check.blob(tree.root, ':' + name)


def test_policy_sidecar_uses_raw_bytes_even_when_lf_pin_matches(tree: Tree) -> None:
    name = 'resilience_policy.json'
    # Both normalized prerequisite pin and unchanged index still match, but the
    # independently approved raw-byte sidecar must reject CRLF conversion.
    tree.write(name, tree.baseline[name].replace(b'\n', b'\r\n'))
    tree.git('update-index', '--assume-unchanged', '--', name)
    with pytest.raises(ValueError, match='^APPROVED_POLICY_BYTES_INVALID$'):
        tree.verify()


def test_hidden_worktree_change_reports_staged_hash(tree: Tree) -> None:
    name = check.CONTROL
    staged = (tree.root / name).read_bytes()
    changed = staged + b'\n'
    tree.write(name, changed)
    tree.git('update-index', '--assume-unchanged', '--', name)
    assert tree.verify() == [{'path': name, 'expected': sha(staged), 'actual': sha(changed)}]
