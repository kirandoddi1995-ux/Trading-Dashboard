"""Offline synthetic public trees; no private files or hosted changes."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
from typing import Any

import pytest

import continuity_upload_check as check
import daily_volume_upload_check as guarded


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    root = tmp_path.resolve()
    for name in set(check.FILES) | set(check.SEEDS) | set(check.EXTRA) | {'dependency.py'}:
        if name == check.MANIFEST:
            continue
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'# public\r\n')
    (root/'forward_morning_route.py').write_text('import dependency\n', encoding='utf-8')
    policy = b'{"synthetic_policy":1}\n'
    (root/'resilience_policy.json').write_bytes(policy)
    (root/'resilience_policy.sha256').write_text(hashlib.sha256(policy).hexdigest()+'\n', encoding='ascii')
    prior = (guarded.guarded_members(root, list(check.SEEDS)) | set(check.EXTRA)) - set(check.FILES)
    def pin(name: str) -> dict[str, object]:
        return {'destination':name, 'sha256_lf':None if name == check.MANIFEST
                else guarded.digest((root/name).read_bytes())}
    plan: dict[str, Any] = {'version':'oct15-continuity-v1', 'base':check.BASE,
        'files':[pin(n) for n in check.FILES], 'prerequisites':[pin(n) for n in sorted(prior)],
        'seeds':list(check.SEEDS), 'extra_pins':list(check.EXTRA)}
    (root/check.MANIFEST).write_text(json.dumps(plan), encoding='utf-8')
    return root, plan


def test_exact_paths(tree: tuple[Path, dict[str, Any]]) -> None:
    root, _ = tree
    assert len(check.FILES) == 20
    assert 'AUTOMATION_PROGRESS.md' not in check.FILES
    assert check.BASE == '1251530731cce5b75fad8601567b9320d07b710d'
    assert check.verify(root, set(check.FILES)) == []


def test_changed_pin_reports_path_expected_actual(tree: tuple[Path, dict[str, Any]]) -> None:
    root, _ = tree
    old = guarded.digest((root/'dependency.py').read_bytes())
    (root/'dependency.py').write_bytes(b'# changed\n')
    assert check.verify(root, set(check.FILES)) == [
        {'path':'dependency.py','expected':old,'actual':guarded.digest(b'# changed\n')}]


@pytest.mark.parametrize('mutation', ['base','version','extra','missing','files','duplicate',
    'self-hash','null-pin','no-prereq','seeds','extras','private-path'])
def test_bad_controls_block(tree: tuple[Path, dict[str, Any]], mutation: str) -> None:
    root, plan = tree
    if mutation in {'base','version'}:
        plan[mutation] = True
    elif mutation == 'extra':
        plan['extra'] = False
    elif mutation == 'missing':
        del plan['base']
    elif mutation == 'files':
        plan['files'] = {}
    elif mutation == 'duplicate':
        plan['files'][0] = plan['files'][1]
    elif mutation == 'self-hash':
        plan['files'][-1]['sha256_lf'] = 'a'*64
    elif mutation == 'null-pin':
        plan['prerequisites'][0]['sha256_lf'] = None
    elif mutation == 'no-prereq':
        plan['prerequisites'].pop()
    elif mutation == 'seeds':
        plan['seeds'].reverse()
    elif mutation == 'extras':
        plan['extra_pins'].reverse()
    else:
        plan['files'][0]['destination'] = '../secrets.toml'
    (root/check.MANIFEST).write_text(json.dumps(plan), encoding='utf-8')
    with pytest.raises(ValueError):
        check.verify(root, set(check.FILES))


def test_control_size_and_duplicate_key(tree: tuple[Path, dict[str, Any]]) -> None:
    root, _ = tree
    (root/check.MANIFEST).write_bytes(b' ' * check.LIMIT)
    with pytest.raises(ValueError, match='CONTROL_TOO_LARGE'):
        check.verify(root, set(check.FILES))
    (root/check.MANIFEST).write_bytes(b'{"base":1,"base":2}')
    with pytest.raises(ValueError, match='MANIFEST_DUPLICATE_KEY'):
        check.verify(root, set(check.FILES))


def test_different_changed_paths_block(tree: tuple[Path, dict[str, Any]]) -> None:
    root, _ = tree
    with pytest.raises(ValueError, match='EXACT_PACKAGE_REQUIRED'):
        check.verify(root, set(check.FILES) - {'MORNING_2026-10-15.md'})


def stage_fixture(monkeypatch: pytest.MonkeyPatch, raw: bytes, *, mode: str = '100644',
                  size: str | None = None) -> None:
    def fake_git(root: Path, *args: str) -> str:
        if args[:2] == ('ls-files','--stage'):
            return mode + ' ' + 'a'*40 + ' 0\t' + args[-1]
        assert args[:2] == ('cat-file','-s')
        return str(len(raw)) if size is None else size
    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert args[-3:] == ['cat-file','blob','a'*40]
        return subprocess.CompletedProcess(args, 0, stdout=raw)
    monkeypatch.setattr(check, 'git', fake_git)
    monkeypatch.setattr(subprocess, 'run', fake_run)


@pytest.mark.parametrize('change', ['crlf','sidecar'])
def test_exact_policy_bytes_are_not_normalized_to_pass(tree: tuple[Path, dict[str, Any]], change: str) -> None:
    root, _ = tree
    if change == 'crlf':
        target = root/'resilience_policy.json'
        target.write_bytes(target.read_bytes().replace(b'\n',b'\r\n'))
    else:
        (root/'resilience_policy.sha256').write_bytes(b'not-approved\n')
    with pytest.raises(ValueError, match='APPROVED_POLICY_BYTES_INVALID'):
        check.verify(root, set(check.FILES))


def test_control_index_mismatch_detected(tree: tuple[Path, dict[str, Any]],
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = tree
    working = (root/check.MANIFEST).read_bytes()
    stage_fixture(monkeypatch, b'{}')
    assert check.index_matches(root, {check.MANIFEST}) == [{
        'path':check.MANIFEST, 'expected':guarded.digest(working), 'actual':guarded.digest(b'{}')}]


@pytest.mark.parametrize('mode,size,code', [
    ('120000', None, 'INDEX_ENTRY_INVALID'),
    ('100644', 'garbage', 'INDEX_BLOB_INVALID'),
    ('100644', str(check.LIMIT), 'INDEX_BLOB_TOO_LARGE'),
    ('100644', '1', 'INDEX_BLOB_INVALID'),
])
def test_control_index_mode_and_size(tree: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
                                     mode: str, size: str | None, code: str) -> None:
    root, _ = tree
    stage_fixture(monkeypatch, b'{}', mode=mode, size=size)
    with pytest.raises(ValueError, match=code):
        check.index_matches(root, {check.MANIFEST})


@pytest.mark.parametrize('problem', ['argument-base','head-base','unstaged','untracked','wrong-root','unknown'])
def test_main_guards_and_redaction(tree: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str], problem: str) -> None:
    root, _ = tree
    monkeypatch.chdir(root)
    def fake_git(where: Path, *args: str) -> str:
        if problem == 'unknown':
            raise RuntimeError('private-password-connection-string')
        if args == ('rev-parse','HEAD'):
            return 'b'*40 if problem == 'head-base' else check.BASE
        if args == ('rev-parse','--show-toplevel'):
            return str(root.parent if problem == 'wrong-root' else root)
        if args == ('diff','--name-only','--'):
            return 'source.py' if problem == 'unstaged' else ''
        if args == ('ls-files','--others','--exclude-standard'):
            return 'untracked.py' if problem == 'untracked' else ''
        raise AssertionError('Cannot reach validation after guard failure')
    monkeypatch.setattr(check, 'git', fake_git)
    assert check.main(['--base','c'*40 if problem == 'argument-base' else check.BASE]) == 2
    output = capsys.readouterr().out
    assert 'private-password' not in output and str(root) not in output
    assert json.loads(output)['status'] == 'BLOCKED'


def test_main_requires_index_binding(tree: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
                                    capsys: pytest.CaptureFixture[str]) -> None:
    root, _ = tree
    monkeypatch.chdir(root)
    def fake_git(where: Path, *args: str) -> str:
        if args == ('rev-parse','HEAD'):
            return check.BASE
        if args == ('rev-parse','--show-toplevel'):
            return str(root)
        if args == ('diff','--name-only','--') or args == ('ls-files','--others','--exclude-standard'):
            return ''
        if args[:3] == ('diff','--cached','--name-only'):
            return '\n'.join(check.FILES)
        raise AssertionError('Unexpected Git operation')
    monkeypatch.setattr(check, 'git', fake_git)
    monkeypatch.setattr(check, 'index_matches', lambda root, names: [
        {'path':check.MANIFEST,'expected':'a'*64,'actual':'b'*64}])
    assert check.main(['--base',check.BASE]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['failures'][0]['path'] == check.MANIFEST
