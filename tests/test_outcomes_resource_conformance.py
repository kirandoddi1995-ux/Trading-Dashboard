"""No private inputs. Native synthetic stress cases are explicitly opt-in."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from typing import Any

import pytest

import outcomes_resource_conformance as runner


def test_preview_and_argument_rejection_have_no_process_io(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: Any) -> Any:
        raise AssertionError('NO_PROCESS')
    monkeypatch.setattr(runner, 'run_case', forbidden)
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)['child_processes'] == 0
    assert runner.main(['--PRIVATE_SOURCE_PATH']) == 2
    assert 'PRIVATE_SOURCE_PATH' not in capsys.readouterr().out


def test_only_fixed_synthetic_cases_and_reviewed_runtime() -> None:
    with pytest.raises(ValueError, match='FIXED_SYNTHETIC_CASE_REQUIRED'):
        runner.run_case('PRIVATE_FILE_OR_COMMAND')


def test_child_environment_drops_all_credential_and_python_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ('DATABASE_URL','GOOGLE_APPLICATION_CREDENTIALS','HOME','PYTHONPATH','HTTP_PROXY'):
        monkeypatch.setenv(name, 'SECRET_TEST_VALUE')
    result = runner.child_environment()
    assert set(result) <= {'SYSTEMROOT','WINDIR','TEMP','TMP','OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','ARROW_NUM_THREADS','NUMEXPR_NUM_THREADS'}
    assert 'SECRET_TEST_VALUE' not in json.dumps(result)


def test_native_setup_failure_never_releases_workload(monkeypatch: pytest.MonkeyPatch) -> None:
    actions: list[str] = []
    class Fake:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.pid = 123
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.returncode: int | None = None
        def poll(self) -> int | None: return self.returncode
        def kill(self) -> None:
            actions.append('kill')
            self.returncode = 2
        def wait(self, timeout: float) -> int:
            self.returncode = 2
            return 2
        def resume(self) -> None: actions.append('RESUME_FORBIDDEN')
        def close(self) -> None: actions.append('close')
    def reject(*args: Any) -> Any:
        raise ValueError('SYNTHETIC_SETUP_FAILURE')
    monkeypatch.setattr(runner, '_reviewed_python', lambda: True)
    if os.name == 'nt':
        monkeypatch.setattr(runner, '_WindowsChild', Fake)
        monkeypatch.setattr(runner, '_WindowsJob', reject)
    else:
        monkeypatch.setattr(runner.subprocess, 'Popen', Fake)
        monkeypatch.setattr(runner, '_linux_limits', reject)
    result = runner.run_case('large')
    assert result['status'] == 'BLOCKED'
    assert result['synthetic_workload_released'] is False
    assert result['native_limits_read_back'] is False
    assert result['child_reaped'] is True
    assert 'RESUME_FORBIDDEN' not in actions


def test_linux_prlimit_enforcement_and_readback_without_targeting_real_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: dict[int, tuple[int,int]] = {}
    def prlimit(pid: int, kind: int, limits: Any = None) -> tuple[int,int]:
        assert pid == 12345
        if limits is not None:
            saved[kind] = limits
        return saved.get(kind, (-1,-1))
    fake = SimpleNamespace(RLIMIT_AS=1, RLIMIT_CPU=2, RLIMIT_CORE=3, RLIMIT_FSIZE=4, RLIM_INFINITY=-1, prlimit=prlimit)
    original = runner.importlib.import_module
    monkeypatch.setattr(runner.importlib, 'import_module', lambda name: fake if name == 'resource' else original(name))
    runner._linux_limits(12345)
    assert saved == {1:(runner.LINUX_ADDRESS_SPACE,)*2,2:(15,15),3:(0,0),4:(0,0)}


def test_second_pipe_creation_failure_closes_first_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    closed: list[int] = []
    def pipe() -> tuple[int, int]:
        calls.append('pipe')
        if len(calls) == 2:
            raise OSError('SYNTHETIC_PIPE_FAILURE')
        return (101, 102)
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace())
    monkeypatch.setattr(runner, '_kernel', lambda: SimpleNamespace())
    monkeypatch.setattr(runner.os, 'pipe', pipe)
    monkeypatch.setattr(runner.os, 'close', closed.append)
    with pytest.raises(OSError, match='SYNTHETIC_PIPE_FAILURE'):
        runner._WindowsChild(['synthetic'])
    assert set(closed) == {101, 102}


@pytest.mark.parametrize('read_fails', [True, False])
def test_hang_timeout_requires_successful_pipe_completion_without_native_launch(
        monkeypatch: pytest.MonkeyPatch, read_fails: bool) -> None:
    """A reader exception is not EOF, even when timeout and cleanup succeed."""
    actions: list[str] = []

    class Pipe(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            if read_fails:
                raise OSError('SYNTHETIC_PIPE_READ_FAILURE')
            return super().read(size)

    class FakeChild:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.pid = 123
            self.stdin = io.BytesIO()
            self.stdout = Pipe()
            self.returncode: int | None = None
            self.waits = 0

        def resume(self) -> None:
            actions.append('resume')

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired('synthetic-only', timeout)
            assert self.returncode is not None
            return self.returncode

        def kill(self) -> None:
            actions.append('kill')
            self.returncode = 2

        def close(self) -> None:
            actions.append('child_handles_closed')

    class FakeJob:
        name = 'SYNTHETIC_ONLY'

        def __init__(self, pid: int) -> None:
            assert pid == 123

        def stop_and_verify_empty(self) -> bool:
            actions.append('job_empty')
            return True

        def close(self) -> None:
            actions.append('job_closed')

    def fake_linux_limits(pid: int) -> None:
        assert pid == 123

    monkeypatch.setattr(runner, '_reviewed_python', lambda: True)
    monkeypatch.setattr(runner, '_WindowsChild', FakeChild)
    monkeypatch.setattr(runner, '_WindowsJob', FakeJob)
    monkeypatch.setattr(subprocess, 'Popen', FakeChild)
    monkeypatch.setattr(runner, '_linux_limits', fake_linux_limits)
    result = runner.run_case('hang')
    assert result['status'] == ('BLOCKED' if read_fails else 'PASS')
    assert result['code'] == 'WALL_TIMEOUT_ENFORCED'
    assert result['wall_timeout_hit'] and result['child_reaped']
    assert result['native_limits_read_back'] and result['synthetic_workload_released']
    assert result['output_limit_hit'] is False
    assert result['private_decode_authorised'] is False
    assert 'kill' in actions and 'child_handles_closed' in actions
    if os.name == 'nt':
        assert result['windows_job_empty_verified'] is True
        assert 'job_empty' in actions and 'job_closed' in actions


@pytest.mark.skipif(os.environ.get('OUTCOMES_RUN_NATIVE_CONFORMANCE') != '1', reason='Explicit disposable native resource commissioning required')
@pytest.mark.parametrize('case', runner.CASES)
def test_native_synthetic_case(case: str) -> None:
    result = runner.run_case(case)
    assert result['status'] == 'PASS', result
    assert result['native_limits_read_back'] and result['child_reaped']
    assert result['private_decode_authorised'] is False
