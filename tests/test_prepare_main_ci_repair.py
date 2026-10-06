"""Deterministic offline repair-plan safety checks; no remote git or real cache."""
import json
import hashlib
from pathlib import Path
import subprocess

import pytest

import prepare_main_ci_repair as repair


@pytest.fixture
def checkout(tmp_path):
    policy = b'{}\n'
    (tmp_path / 'resilience_policy.json').write_bytes(policy)
    (tmp_path / 'resilience_policy.sha256').write_text(hashlib.sha256(policy).hexdigest())
    for name in repair.RESTORE + repair.REMOVE_CODE + (repair.CACHE,):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic fixture\n')
    return tmp_path


def runner(root, *, head=repair.AUDITED_MAIN, dirty='', missing=None, wrong_diff=False):
    calls = []
    paths = set(repair.RESTORE + repair.REMOVE_CODE + (repair.CACHE,))
    def run(where, args):
        assert where == root
        calls.append(args)
        if args == ['rev-parse', '--show-toplevel']: return str(root)
        if args == ['rev-parse', 'HEAD']: return head
        if args == ['status', '--porcelain']: return dirty
        if args == ['ls-files', '-z']: return '\0'.join(paths - {missing}) + '\0'
        if args[:3] == ['diff', '--cached', '--name-only']:
            return '\0'.join(paths - ({repair.CACHE} if wrong_diff else set())) + '\0'
        return ''
    return run, calls


def test_preview_never_mutates_or_publishes(checkout):
    run, calls = runner(checkout)
    result = repair.prepare(checkout, run=run)
    assert result['status'] == 'REPAIR_PREVIEW' and result['hosted_changes'] == 0
    assert not any(args[0] in {'restore', 'rm', 'commit', 'push', 'fetch'} for args in calls)
    assert len(result['restore']) == 8 and len(result['withdraw']) == 30


def test_application_restores_exact_base_preserves_cache_and_never_publishes(checkout):
    run, calls = runner(checkout)
    assert repair.prepare(checkout, apply=True, run=run)['status'] == 'LOCAL_REPAIR_STAGED_NOT_COMMITTED'
    assert ['rm', '--cached', '--', repair.CACHE] in calls
    assert calls[5][:6] == ['restore', '--source', repair.GOOD_RELEASE, '--staged', '--worktree', '--']
    assert (checkout / repair.CACHE).is_file()
    assert not any(args[0] in {'commit', 'push', 'fetch', 'reset'} for args in calls)


@pytest.mark.parametrize('kwargs,code', [
    ({'head': 'changed'}, 'MAIN_CHANGED_REVIEW_REQUIRED'),
    ({'dirty': ' M user.py'}, 'CLEAN_CHECKOUT_REQUIRED'),
    ({'missing': repair.CACHE}, 'REPAIR_PATHS_UNVERIFIED'),
])
def test_unverified_checkout_blocks_before_mutation(checkout, kwargs, code):
    run, calls = runner(checkout, **kwargs)
    with pytest.raises(repair.RepairBlocked, match=code):
        repair.prepare(checkout, apply=True, run=run)
    assert not any(args[0] in {'restore', 'rm'} for args in calls)


def test_active_workspace_and_missing_directory_are_rejected(tmp_path):
    for root in (Path(repair.__file__).resolve().parent, tmp_path / 'absent'):
        with pytest.raises(repair.RepairBlocked, match='SEPARATE_CHECKOUT_REQUIRED'):
            repair.prepare(root, run=lambda *_: pytest.fail('git invoked'))


def test_subdirectory_is_not_a_checkout_root(checkout):
    with pytest.raises(repair.RepairBlocked, match='CHECKOUT_ROOT_REQUIRED'):
        repair.prepare(checkout, run=lambda *_: str(checkout.parent))


def test_missing_local_source_path_is_not_silently_ignored(checkout):
    (checkout / repair.RESTORE[0]).unlink()
    run, calls = runner(checkout)
    with pytest.raises(repair.RepairBlocked, match='REPAIR_PATH_UNSAFE'):
        repair.prepare(checkout, apply=True, run=run)
    assert not any(args[0] in {'restore', 'rm'} for args in calls)


def test_postcondition_failure_never_creates_commit(checkout):
    run, calls = runner(checkout, wrong_diff=True)
    with pytest.raises(repair.RepairBlocked, match='REPAIR_POSTCONDITION_FAILED_NO_COMMIT'):
        repair.prepare(checkout, apply=True, run=run)
    assert not any(args[0] in {'commit', 'push'} for args in calls)


def test_windows_line_ending_conversion_blocks_before_mutation(checkout):
    (checkout / 'resilience_policy.json').write_bytes(b'{}\r\n')
    run, calls = runner(checkout)
    with pytest.raises(repair.RepairBlocked, match='POLICY_CHECKOUT_BYTES_INVALID_RECLONE_LF'):
        repair.prepare(checkout, apply=True, run=run)
    assert not any(args[0] in {'restore', 'rm'} for args in calls)


@pytest.mark.parametrize('name', ['resilience_policy.json', 'resilience_policy.sha256'])
def test_policy_symlink_blocks_before_read_or_mutation(checkout, monkeypatch, name):
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path.name == name)
    run, calls = runner(checkout)
    with pytest.raises(repair.RepairBlocked, match='POLICY_CHECKOUT_BYTES_INVALID_RECLONE_LF'):
        repair.prepare(checkout, apply=True, run=run)
    assert not any(args[0] in {'restore', 'rm'} for args in calls)


def test_raw_git_error_is_redacted(checkout, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, 'git', stderr='PRIVATE_PASSWORD')
    monkeypatch.setattr(repair.subprocess, 'run', fail)
    assert repair.main(['--checkout', str(checkout)]) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_PASSWORD' not in output
    assert json.loads(output)['code'] == 'LOCAL_GIT_FAILED'


@pytest.mark.parametrize('error_type', [RuntimeError, repair.RepairBlocked])
def test_unexpected_error_is_redacted(checkout, monkeypatch, capsys, error_type):
    def fail(*args, **kwargs): raise error_type('PRIVATE_TOKEN')
    monkeypatch.setattr(repair, 'prepare', fail)
    assert repair.main(['--checkout', str(checkout)]) == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_TOKEN' not in output and 'LOCAL_REPAIR_UNAVAILABLE' in output


def test_git_is_local_bounded_and_not_shell(checkout, monkeypatch):
    def run(command, **kwargs):
        assert command == ['git', '-C', str(checkout), 'status', '--porcelain']
        assert kwargs == dict(check=True, capture_output=True, text=True, timeout=30)
        return subprocess.CompletedProcess(command, 0, stdout='')
    monkeypatch.setattr(repair.subprocess, 'run', run)
    assert repair.git(checkout, ['status', '--porcelain']) == ''
