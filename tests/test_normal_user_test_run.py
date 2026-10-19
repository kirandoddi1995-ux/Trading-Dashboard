"""Synthetic launcher mocks only: never execute the project test suite."""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
from types import SimpleNamespace
from typing import NoReturn

import pytest

import normal_user_test_run as runner


def forbidden(*args: object, **kwargs: object) -> NoReturn:
    pytest.fail('Unexpected native operation')


def test_preview_zero_io(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(runner, '_normal_windows', forbidden)
    monkeypatch.setattr(tempfile, 'mkdtemp', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(Path, 'resolve', forbidden)
    assert runner.main(['--python', 'PRIVATE_SENTINEL', '--with-pglite']) == 0
    assert json.loads(capsys.readouterr().out)['input_reads'] == 0


@pytest.mark.parametrize('code', ['WINDOWS_REQUIRED', 'PYTHON_3_13_9_REQUIRED', 'NONADMIN_TOKEN_REQUIRED'])
def test_preflight_blocks_before_allocation(code: str, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    def blocked() -> None:
        raise runner.Blocked(code)
    monkeypatch.setattr(runner, '_normal_windows', blocked)
    monkeypatch.setattr(tempfile, 'mkdtemp', forbidden)
    assert runner.main(['--run-confirmed']) == 2
    assert json.loads(capsys.readouterr().out)['code'] == code


@pytest.mark.parametrize('exit_code', [0, 1, 2, 5])
def test_exact_full_suite_command_and_exit_no_retry(tmp_path: Path, exit_code: int,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(runner, '_normal_windows', lambda: None)
    monkeypatch.setattr(runner, '_clean_checkout', lambda root, env: None)
    monkeypatch.setattr(tempfile, 'gettempdir', lambda: str(tmp_path))
    monkeypatch.setenv('PYTEST_ADDOPTS', '--ignore=tests')
    monkeypatch.setenv('EQUITY_TEST_PGLITE_MODULE', 'PRIVATE_SENTINEL')
    monkeypatch.setenv('PYTEST_DISABLE_PLUGIN_AUTOLOAD', '1')
    for name in ('DATABASE_URL', 'UPSTOX_ACCESS_TOKEN', 'DRIVE_TOKEN', 'EVIDENCE_TOKEN',
                 'PYTHONPATH', 'NODE_OPTIONS', 'HTTP_PROXY', 'GIT_DIR'):
        monkeypatch.setenv(name, 'CREDENTIAL_SENTINEL_NOT_FOR_CHILD')
    calls = 0
    def fake_run(command: list[str], *, cwd: Path, env: dict[str, str], check: bool) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        assert command[:6] == [str(Path(sys.executable).resolve()), '-B', '-m', 'pytest', '-p', 'no:cacheprovider']
        assert command[-1] == 'tests' and command[-3] == '--basetemp'
        base = Path(command[-2])
        assert base.parent.parent == tmp_path and base.parent.is_dir() and not base.exists()
        assert cwd == Path(runner.__file__).resolve().parent and check is False
        assert 'PYTEST_ADDOPTS' not in env and 'EQUITY_TEST_PGLITE_MODULE' not in env
        assert 'PYTEST_DISABLE_PLUGIN_AUTOLOAD' not in env
        assert 'CREDENTIAL_SENTINEL_NOT_FOR_CHILD' not in env.values()
        assert not ({'DATABASE_URL', 'UPSTOX_ACCESS_TOKEN', 'DRIVE_TOKEN', 'EVIDENCE_TOKEN',
                     'PYTHONPATH', 'NODE_OPTIONS', 'HTTP_PROXY', 'GIT_DIR'} & env.keys())
        assert set(env) <= runner.RUNTIME_ENV_NAMES | {'PYTHONDONTWRITEBYTECODE'}
        assert env['TEMP'] == env['TMP'] == env['TMPDIR'] == str(base.parent)
        return subprocess.CompletedProcess(command, exit_code)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    assert runner.main(['--run-confirmed', '--python', sys.executable]) == exit_code
    assert calls == 1 and len(list(tmp_path.iterdir())) == 1
    output = capsys.readouterr().out
    assert 'PRIVATE_SENTINEL' not in output and str(tmp_path) not in output
    assert json.loads(output.splitlines()[-1])['pytest_exit'] == exit_code


@pytest.mark.parametrize('python', [None, 'relative.exe'])
def test_python_required_before_temp(python: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, '_normal_windows', lambda: None)
    monkeypatch.setattr(tempfile, 'mkdtemp', forbidden)
    args = ['--run-confirmed'] + (['--python', python] if python else [])
    assert runner.main(args) == 2


def test_temp_inside_checkout_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, '_normal_windows', lambda: None)
    monkeypatch.setattr(tempfile, 'gettempdir', lambda: str(Path(runner.__file__).parent))
    monkeypatch.setattr(tempfile, 'mkdtemp', forbidden)
    assert runner.main(['--run-confirmed', '--python', sys.executable]) == 2


def test_optional_pglite_failure_never_silently_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, '_normal_windows', lambda: None)
    monkeypatch.setattr(runner, '_clean_checkout', lambda root, env: None)
    monkeypatch.setattr(tempfile, 'gettempdir', lambda: str(tmp_path))
    def blocked(root: Path, env: dict[str, str]) -> None:
        raise runner.Blocked('PGLITE_LOCK_MISMATCH')
    monkeypatch.setattr(runner, '_pglite', blocked)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    assert runner.main(['--run-confirmed', '--python', sys.executable, '--with-pglite']) == 2
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize('node_version,node_exit', [('v24.1.0', 0), ('v22.0.0', 0), ('v24.1.0', 1)])
def test_pglite_synthetic_lock(tmp_path: Path, node_version: str, node_exit: int,
        monkeypatch: pytest.MonkeyPatch) -> None:
    harness = tmp_path/'tests/sql-harness'
    installed = harness/'node_modules/@electric-sql/pglite'
    installed.mkdir(parents=True)
    (harness/'package-lock.json').write_text(json.dumps({'packages': {
        'node_modules/@electric-sql/pglite': {'version': '0.3.14'}}}), encoding='utf-8')
    (installed/'package.json').write_text('{"version":"0.3.14"}', encoding='utf-8')
    monkeypatch.setattr(shutil, 'which', lambda name: str(tmp_path/'node.exe'))
    calls = 0
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert command[-1] == '--version'
            return subprocess.CompletedProcess(command, node_exit, stdout=node_version)
        assert command[1] == '-e' and command[-1] == str(installed)
        assert "db.query('SELECT 1 AS ok')" in command[2]
        assert kwargs['capture_output'] is True and kwargs['check'] is False
        return subprocess.CompletedProcess(command, 0, stdout='PGLITE_SELECT_1_OK')
    monkeypatch.setattr(subprocess, 'run', fake_run)
    env: dict[str, str] = {}
    if node_version.startswith('v24.') and node_exit == 0:
        runner._pglite(tmp_path, env)
        assert env['EQUITY_TEST_PGLITE_MODULE'] == str(installed)
        assert calls == 2
    else:
        with pytest.raises(runner.Blocked, match='NODE_24_REQUIRED'):
            runner._pglite(tmp_path, env)


@pytest.mark.parametrize('platform,version,admin,code', [
    ('linux', (3, 13, 9), 0, 'WINDOWS_REQUIRED'),
    ('win32', (3, 13, 8), 0, 'PYTHON_3_13_9_REQUIRED'),
    ('win32', (3, 13, 9), 1, 'NONADMIN_TOKEN_REQUIRED'),
    ('win32', (3, 13, 9), 0, None),
])
def test_actual_token_and_version_guard_mocked(platform: str, version: tuple[int, int, int],
        admin: int, code: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    def query() -> int:
        nonlocal calls
        calls += 1
        return admin
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(sys, 'version_info', version)
    monkeypatch.setattr(ctypes, 'windll',
        SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=query)), raising=False)
    if code is None:
        runner._normal_windows()
    else:
        with pytest.raises(runner.Blocked, match=code):
            runner._normal_windows()
    assert calls == (1 if platform == 'win32' and version == (3, 13, 9) else 0)


def test_missing_node_blocks_without_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    with pytest.raises(runner.Blocked, match='NODE_24_REQUIRED'):
        runner._pglite(tmp_path, {})


@pytest.mark.parametrize('case', ['clean', 'sql-installed', 'modified', 'untracked', 'ignored-secret',
                                 'wrong-root', 'bare', 'git-failed', 'no-git-directory'])
def test_clean_git_gate_synthetic_metadata(tmp_path: Path, case: str,
        monkeypatch: pytest.MonkeyPatch) -> None:
    if case != 'no-git-directory':
        (tmp_path/'.git').mkdir()
    monkeypatch.setattr(shutil, 'which', lambda name: 'synthetic-git')
    calls = 0
    def fake_run(command: list[str], *, cwd: Path, env: dict[str, str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        assert cwd == tmp_path and 'GIT_DIR' not in env
        assert '--no-optional-locks' in command and 'core.fsmonitor=false' in command
        if '--show-toplevel' in command:
            output = str(tmp_path.parent if case == 'wrong-root' else tmp_path)
        elif '--is-bare-repository' in command:
            output = 'true' if case == 'bare' else 'false'
        elif '--verify' in command:
            output = 'a'*40
        else:
            assert '--ignored=matching' in command and '--untracked-files=all' in command
            output = {'sql-installed': '!! tests/sql-harness/node_modules/',
                      'modified': ' M public.py', 'untracked': '?? unknown.py',
                      'ignored-secret': '!! .streamlit/'}.get(case, '')
        return subprocess.CompletedProcess(command, 1 if case == 'git-failed' else 0, stdout=output)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    if case in ('clean', 'sql-installed'):
        runner._clean_checkout(tmp_path, {'GIT_DIR': 'PRIVATE_SENTINEL'})
        assert calls == 4
    else:
        with pytest.raises(runner.Blocked):
            runner._clean_checkout(tmp_path, {'GIT_DIR': 'PRIVATE_SENTINEL'})


@pytest.mark.parametrize('exit_code,output', [(2, ''), (0, ''), (0, 'PRIVATE_SENTINEL')])
def test_sql_failure_blocks_full_suite(tmp_path: Path, exit_code: int, output: str,
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, 'which', lambda name: 'synthetic-node')
    def metadata(path: Path) -> dict[str, object]:
        if path.name == 'package-lock.json':
            return {'packages': {'node_modules/@electric-sql/pglite': {'version': '0.3.14'}}}
        return {'version': '0.3.14'}
    monkeypatch.setattr(runner, '_json', metadata)
    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[-1] == '--version':
            return subprocess.CompletedProcess(command, 0, stdout='v24.1.0')
        return subprocess.CompletedProcess(command, exit_code, stdout=output)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    with pytest.raises(runner.Blocked, match='PGLITE_SELECT_1_FAILED'):
        runner._pglite(tmp_path, {})
