"""Container plan/readback mutation tests. Native Docker denial tests are separate."""
import copy
import json
import io
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import outcomes_private_container as c

IMAGE = 'sha256:' + 'a' * 64


def inspected(catalog: Path, bundle: Path) -> dict[str, Any]:
    return dict(Image=IMAGE, Config=dict(Image=IMAGE, User='65534:65534', Volumes=None),
        Mounts=[dict(Destination=target, Source=str(source), RW=False, Type='bind')
                for target, source in [('/inputs/catalog.json', catalog), ('/inputs/bundle.zip', bundle)]],
        HostConfig=dict(NetworkMode='none', ReadonlyRootfs=True, Privileged=False, Init=True, CapDrop=['ALL'], CapAdd=None,
            Devices=[], DeviceRequests=None, Memory=c.MEMORY, MemorySwap=c.MEMORY, NanoCpus=1000000000,
            PidsLimit=16, IpcMode='none', PidMode='', CgroupnsMode='private', Runtime='runc',
            LogConfig=dict(Type='none'), RestartPolicy=dict(Name='no'), SecurityOpt=['no-new-privileges:true'],
            PortBindings={}, VolumesFrom=None, Ulimits=[dict(Name='cpu', Soft=60, Hard=60), dict(Name='nofile', Soft=64, Hard=64), dict(Name='core', Soft=0, Hard=0)],
            Mounts=[dict(Target=target, Source=str(source), ReadOnly=True, Type='bind')
                    for target, source in [('/inputs/catalog.json', catalog), ('/inputs/bundle.zip', bundle)]]))


def test_fixed_plan_no_shell_no_socket_no_whole_directory(tmp_path: Path) -> None:
    args = c.create_arguments(IMAGE, 'researchops-bridge-' + 'b' * 32, tmp_path / 'catalog', tmp_path / 'bundle', ['--selftest'])
    assert '--network=none' in args and '--read-only' in args and '--pull=never' in args
    assert '--user=65534:65534' in args and '--cap-drop=ALL' in args
    assert args.count('--mount') == 2
    assert '--privileged' not in args and '-v' not in args and '--rm' not in args
    assert 'docker.sock' not in ' '.join(args)


def test_expected_readback(tmp_path: Path) -> None:
    c.validate_inspection(inspected(tmp_path / 'catalog', tmp_path / 'bundle'), IMAGE, tmp_path / 'catalog', tmp_path / 'bundle')


@pytest.mark.parametrize('field,value', [('NetworkMode', 'host'), ('ReadonlyRootfs', False), ('Privileged', True),
    ('Init', False),
    ('CapDrop', []), ('Memory', 0), ('MemorySwap', -1), ('NanoCpus', 0), ('PidsLimit', -1),
    ('PidMode', 'host'), ('IpcMode', 'host'), ('CgroupnsMode', 'host'), ('SecurityOpt', ['seccomp=unconfined']),
    ('Devices', [{}]), ('DeviceRequests', [{}]), ('Runtime', 'unknown'), ('VolumesFrom', ['host'])])
def test_every_weakened_host_constraint_rejected(tmp_path: Path, field: str, value: Any) -> None:
    result = inspected(tmp_path / 'catalog', tmp_path / 'bundle')
    result['HostConfig'][field] = value
    with pytest.raises(ValueError):
        c.validate_inspection(result, IMAGE, tmp_path / 'catalog', tmp_path / 'bundle')


@pytest.mark.parametrize('change', ['rw', 'extra', 'wrong-source', 'effective-source', 'wrong-image', 'root', 'logs', 'limits'])
def test_identity_mount_and_limit_mutations(tmp_path: Path, change: str) -> None:
    result = inspected(tmp_path / 'catalog', tmp_path / 'bundle')
    if change == 'rw':
        result['Mounts'][0]['RW'] = True
    elif change == 'extra':
        result['Mounts'].append(copy.deepcopy(result['Mounts'][0]))
    elif change == 'wrong-source':
        result['HostConfig']['Mounts'][0]['Source'] = 'wrong'
    elif change == 'effective-source':
        result['Mounts'][0]['Source'] = 'wrong-effective-path'
    elif change == 'wrong-image':
        result['Image'] = 'sha256:' + 'c' * 64
    elif change == 'root':
        result['Config']['User'] = '0'
    elif change == 'logs':
        result['HostConfig']['LogConfig']['Type'] = 'json-file'
    else:
        result['HostConfig']['Ulimits'][0]['Hard'] = 0
    with pytest.raises(ValueError):
        c.validate_inspection(result, IMAGE, tmp_path / 'catalog', tmp_path / 'bundle')


def test_preview_no_files_or_engine(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr('sys.argv', ['bridge'])
    monkeypatch.setattr(c, 'docker_prefix', lambda: pytest.fail('Engine contacted'))
    assert c.main() == 0
    assert json.loads(capsys.readouterr().out)['process_launches'] == 0


def test_blocked_run_is_redacted(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr('sys.argv', ['bridge', '--mode', 'private', '--confirm-run', '--run-root', 'PRIVATE_SENTINEL'])
    assert c.main() == 2
    output = capsys.readouterr().out
    assert 'PRIVATE_SENTINEL' not in output and json.loads(output)['retry_authorised'] is False


@pytest.mark.parametrize('change', ['missing', 'extra', 'integer', 'empty'])
def test_synthetic_admission_requires_closed_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str) -> None:
    checks = dict.fromkeys(c.CHECKS, True)
    if change == 'missing':
        checks.pop('codec')
    elif change == 'extra':
        checks['unreviewed'] = True
    elif change == 'integer':
        checks['codec'] = 1
    else:
        checks = {}
    monkeypatch.setattr(c, 'run_container', lambda *a, **kw: dict(status='SYNTHETIC_CONTAINER_CHECK_PASSED', checks=checks, private_decode_authorised=False))
    with pytest.raises(ValueError, match='SYNTHETIC_CONTAINER_PROOF_MISSING'):
        c.synthetic(IMAGE, tmp_path / 'synthetic')


def test_output_flood_is_bounded() -> None:
    with pytest.raises(ValueError):
        c.execute([sys.executable, '-c', "print('SYNTHETIC_' * 10000)"], maximum=1024)


def test_reader_failure_after_valid_prefix_cannot_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            if self.tell():
                raise OSError('SYNTHETIC_PRIVATE_SENTINEL')
            return super().read(size)
    class Process:
        stdout = Broken(b'{"status":"ok"}')
        returncode = 0
        def wait(self, timeout: int) -> int:
            return 0
        def poll(self) -> int:
            return 0
        def kill(self) -> None:
            pass
    monkeypatch.setattr(c.subprocess, 'Popen', lambda *a, **kw: Process())
    with pytest.raises(ValueError, match='LOCAL_CONTAINER_COMMAND_FAILED'):
        c.execute(['synthetic-not-started'])


def test_watchdog_proof_has_no_attached_start_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    catalog, bundle = tmp_path / 'catalog', tmp_path / 'bundle'
    before = inspected(catalog, bundle)
    before['State'] = dict(Running=False, Pid=0, ExitCode=0, OOMKilled=False)
    before['Config'].update(Entrypoint=['python', '-B', '/app/outcomes_private_worker.py'], Cmd=['--watchdog-probe'])
    calls: list[list[str]] = []
    inspections = 0
    def execute(command: list[str], **kwargs: Any) -> bytes:
        nonlocal inspections
        calls.append(command)
        if 'create' in command:
            return b'b' * 64
        if 'inspect' in command:
            inspections += 1
            value = copy.deepcopy(before)
            if inspections > 1:
                value['State']['ExitCode'] = 142
            return json.dumps([value]).encode()
        return b'synthetic'
    monkeypatch.setattr(c, 'docker_prefix', lambda _: ['synthetic-docker'])
    monkeypatch.setattr(c, 'execute', execute)
    assert c.run_container(IMAGE, catalog, bundle, ['--watchdog-probe'], tmp_path / 'intent.json', watchdog=True)['status'] == 'AUTONOMOUS_WATCHDOG_VERIFIED'
    assert any(command[1:] == ['start', command[-1]] for command in calls if 'start' in command)
    assert not any('--attach' in command for command in calls)


def test_owner_host_enforces_normal_windows_before_private_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    def elevated() -> None:
        raise c.Blocked('NONADMIN_TOKEN_REQUIRED')
    monkeypatch.setattr(c, '_normal_windows', elevated)
    with pytest.raises(ValueError, match='NONADMIN_TOKEN_REQUIRED'):
        c.owner_host('private', 'nt')
    with pytest.raises(ValueError, match='WINDOWS_OWNER_PRIVATE_HOST_REQUIRED'):
        c.owner_host('private', 'posix')
    c.owner_host('selftest', 'posix')


def test_public_recipe_and_inactive_workflow_are_bounded() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / 'docker/outcomes-private.Dockerfile').read_text()
    assert 'python:3.13.9-slim-bookworm@sha256:8cdd496996889eef0a8a7921c152c0a4a9f18a26c7a5e7257d3c90b431891894' in dockerfile
    assert '--require-hashes' in dockerfile and 'USER 65534:65534' in dockerfile
    assert 'COPY .' not in dockerfile and 'VOLUME' not in dockerfile
    requirements = (root / 'docker/outcomes-private.requirements.txt').read_text()
    assert requirements.strip() == 'pyarrow==24.0.0 --hash=sha256:6f066b179d68c413374294bc1735f68475457c933258df594443bb9d88ddc2a0'
    workflow = (root / '.github/workflows/outcomes-private-conformance.yml').read_text()
    assert "inputs.confirm_disposable && vars.OUTCOMES_PRIVATE_CONFORMANCE_ENABLED == 'true'" in workflow
    assert 'default: false' in workflow and 'contents: read' in workflow
    assert 'schedule:' not in workflow and 'secrets.' not in workflow
    assert 'docker push' not in workflow and 'upload-artifact' not in workflow


def test_staged_context_has_default_deny_and_only_public_inputs(tmp_path: Path) -> None:
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'docker').mkdir()
    for name in c.BUILD_FILES:
        (source / name).write_bytes(b'SYNTHETIC_PUBLIC_CODE')
    for name in ('outcomes-private.Dockerfile', 'outcomes-private.requirements.txt'):
        (source / 'docker' / name).write_bytes(b'SYNTHETIC_PUBLIC_RECIPE')
    (source / 'secret-do-not-copy.txt').write_bytes(b'SYNTHETIC_PRIVATE_SENTINEL')
    destination = tmp_path / 'context'
    c.stage_context(source, destination)
    assert set(p.name for p in destination.iterdir()) == set(c.BUILD_FILES) | {'Dockerfile', 'requirements.txt', '.dockerignore'}
    ignore = (destination / '.dockerignore').read_text()
    assert ignore.startswith('**\n') and 'secret-do-not-copy' not in ignore


def test_successful_synthetic_summary_has_no_stale_review_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr('sys.argv', ['bridge', '--mode', 'selftest', '--confirm-run', '--image-id', IMAGE,
                                   '--run-root', str(tmp_path / 'synthetic')])
    monkeypatch.setattr(c, 'owner_host', lambda _: None)
    monkeypatch.setattr(c, 'synthetic', lambda *a: dict(status='SYNTHETIC_CONTAINER_CHECK_PASSED',
        checks=dict.fromkeys(c.CHECKS, True), autonomous_watchdog_verified=True))
    assert c.main() == 0
    value = json.loads(capsys.readouterr().out)
    assert value['autonomous_watchdog_verified'] is True and 'code' not in value and 'reason' not in value


@pytest.mark.parametrize('shell_name', ['powershell', 'pwsh'])
def test_owner_blocks_parse_without_execution(shell_name: str) -> None:
    shell = shutil.which(shell_name)
    if shell is None:
        pytest.skip('PowerShell parser unavailable on this platform; no installation or bypass')
    root = Path(__file__).resolve().parents[1]
    files = [root / 'PRESERVATION_COMMISSION_2026-10-20.md', root / 'OUTCOMES_PRIVATE_RUNBOOK.md']
    literals = ','.join("'" + str(file).replace("'", "''") + "'" for file in files)
    script = ("$ErrorActionPreference='Stop';$fence=[string]::new([char]96,3);"
        "$pattern='(?s)'+$fence+'powershell\\r?\\n(.*?)'+$fence;$count=0;$failures=0;"
        "foreach($file in @(" + literals + ")){foreach($match in [regex]::Matches([IO.File]::ReadAllText($file),$pattern)){"
        "$tokens=$null;$parseErrors=$null;[Management.Automation.Language.Parser]::ParseInput($match.Groups[1].Value,[ref]$tokens,[ref]$parseErrors)|Out-Null;"
        "$count++;$failures+=@($parseErrors).Count}};"
        "[pscustomobject]@{blocks=$count;errors=$failures;executed=0}|ConvertTo-Json -Compress")
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed['blocks'] > 20 and parsed['errors'] == 0 and parsed['executed'] == 0
