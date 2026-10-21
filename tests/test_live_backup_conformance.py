import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import live_backup_conformance as c


def test_pinned_isolated_synthetic_recipe() -> None:
    args = c.docker_args('live-backup-synthetic-' + 'a' * 32)
    assert args[args.index('--network') + 1] == 'none'
    assert '--pull=never' in args and '--read-only' in args
    assert args[args.index('--cap-drop') + 1] == 'ALL'
    assert args[args.index('--user') + 1] == 'postgres'
    assert 'no-new-privileges' in args and c.IMAGE in args
    assert not any(x in args for x in ('-p', '--publish', '--privileged', '-v', '--mount', '--rm'))
    assert len(c.CASES) == 10


@pytest.mark.parametrize('bad', ['existing-task', 'live-backup-synthetic-' + 'a' * 31, 'a/b'])
def test_only_unique_synthetic_names(bad: str) -> None:
    with pytest.raises(ValueError, match='SYNTHETIC_NAME_REQUIRED'):
        c.docker_args(bad)


def test_script_has_two_fresh_clusters_and_tests_real_typed_restore() -> None:
    assert 'initdb -D /tmp/source' in c.SCRIPT and 'initdb -D /tmp/target' in c.SCRIPT
    assert 'listen_addresses=' in c.SCRIPT
    assert '--roles-only --no-role-passwords' in c.SCRIPT
    assert 'pg_restore --exit-on-error --create' in c.SCRIPT
    assert 'SET ROLE fixture_reader' in c.SCRIPT
    assert 'relrowsecurity AND relforcerowsecurity' in c.SCRIPT
    assert 'rolpassword IS NULL' in c.SCRIPT
    assert 'SYNTHETIC_NATIVE_BACKUP_CASES_PASSED' in c.SCRIPT
    assert 'supabase' not in c.SCRIPT and 'PGPASSWORD' not in c.SCRIPT


def test_default_preview_zero_process_or_io(monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError('forbidden native invocation')
    monkeypatch.setattr(c, 'stream_process', forbidden)
    monkeypatch.setattr(c.shutil, 'which', forbidden)
    assert c.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'PREVIEW' and result['native_invocations'] == 0


def test_manual_workflow_inactive_no_private_data_or_schedules() -> None:
    text = (Path(__file__).resolve().parents[1] / '.github/workflows/live-backup-conformance.yml').read_text()
    assert "vars.LIVE_BACKUP_CONFORMANCE_ENABLED == 'true'" in text
    assert 'default: false' in text and 'workflow_dispatch:' in text
    assert 'runs-on: ubuntu-24.04' in text and "python-version: '3.13'" in text
    assert 'schedule:' not in text and 'secrets.' not in text
    assert c.IMAGE in text and 'upload-artifact' not in text


@pytest.mark.skipif(os.name == 'nt', reason='POSIX shell syntax gate belongs to Linux CI, not Windows MSYS')
def test_shell_recipe_parses_without_execution() -> None:
    shell = shutil.which('bash')
    if not shell or not Path(shell).is_file():
        pytest.skip('Static shell parser unavailable; native acceptance still required')
    result = subprocess.run((shell, '--noprofile', '--norc', '-n'), input=c.SCRIPT.encode(),
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10, check=False)
    assert result.returncode == 0


@pytest.mark.parametrize('failure', ['', 'fixture', 'stop'])
def test_native_harness_projects_only_fixed_cases_and_checks_stop(tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str) -> None:
    monkeypatch.setattr(c.shutil, 'which', lambda value: str(tmp_path / 'docker.exe'))
    config = tmp_path / 'empty-docker-config'
    config.mkdir()
    monkeypatch.setattr(c.tempfile, 'mkdtemp', lambda **kwargs: str(config))
    monkeypatch.setenv('DOCKER_HOST', 'private-remote-sentinel')
    monkeypatch.setenv('PGPASSWORD', 'private-source-sentinel')
    seen: list[tuple[str, ...]] = []
    def run(argv: tuple[str, ...], *, env: dict[str, str], sink: object, **kwargs: object) -> dict[str, object]:
        seen.append(argv)
        assert '--config' in argv and '--host' in argv
        assert 'private-source-sentinel' not in repr(env)
        assert 'private-remote-sentinel' not in repr(env)
        if 'create' in argv:
            data = b'a' * 64 + b'\n'
        elif 'start' in argv:
            data = b'CASE:native_17_11\n'
            if failure == 'fixture':
                sink.write(data)  # type: ignore[attr-defined]
                raise ValueError('NATIVE_EXIT_REVIEW')
            data = (''.join('CASE:' + case + '\n' for case in c.CASES) +
                    'SYNTHETIC_NATIVE_BACKUP_CASES_PASSED\n').encode()
        else:
            data = b'true\n' if failure == 'stop' else b'false\n'
        sink.write(data)  # type: ignore[attr-defined]
        return {}
    monkeypatch.setattr(c, 'stream_process', run)
    monkeypatch.setattr(c.subprocess, 'run', lambda *args, **kwargs: None)
    assert c.main(['--execute', '--confirm-disposable']) == (2 if failure else 0)
    result = json.loads(capsys.readouterr().out)
    assert result['hosted_changes'] == 0 and result['private_restore_verified'] is False
    assert len(result['synthetic_run_id']) == 32
    if failure == 'fixture':
        assert result['last_completed_case'] == 'native_17_11'
    elif failure == 'stop':
        assert result['code'] == 'SYNTHETIC_STOP_UNVERIFIED'
    else:
        assert all(result['cases'].values()) and result['synthetic_container_stopped_verified']
