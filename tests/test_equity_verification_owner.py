"""Portable helper tests and real PS 5.1/7 fixture-only owner-wrapper tests.

Synthetic failing helpers exist only in copied fixture checkouts. No production
injection flag, real full suite, network, Git mutation or credential access.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tooling/equity_native_preflight.py'
WRAPPER = ROOT / 'tooling/equity_verification_owner.ps1'
PIN = '404eab045c32e37df3866b1337ab50ccf827eb4bbac56dd0983f55dc3865bc2d'


def helper_module() -> Any:
    spec = importlib.util.spec_from_file_location('equity_native_preflight', HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / 'public clone spaces \u65b0'
    (root / 'tooling').mkdir(parents=True)
    (root / '.git').mkdir()
    (root / '.git/HEAD').write_text('ref: refs/heads/main\n', encoding='ascii')
    (root / 'requirements.txt').write_text('# synthetic\n', encoding='ascii')
    (root / 'tests').mkdir()
    shutil.copyfile(HELPER, root / 'tooling/equity_native_preflight.py')
    script = root / 'tooling/equity_verification_owner.ps1'
    shutil.copyfile(WRAPPER, script)
    return root, script


def test_python_native_temp_success_and_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = helper_module()
    root, _ = fixture_tree(tmp_path)
    monkeypatch.setattr(module, '__file__', str(root / 'tooling/equity_native_preflight.py'))
    monkeypatch.setattr(module.sys, 'version_info', (3, 13, 9))
    temporary = tmp_path / 'native temp \u8bd5'
    temporary.mkdir()
    monkeypatch.setattr(module.tempfile, 'tempdir', str(temporary))
    assert module.main(['--root', str(root)]) == 0
    captured = capsys.readouterr().out
    wire_literal = next(line for line in WRAPPER.read_text(encoding='utf-8').splitlines()
                        if line.startswith('$expectedProbeSuccess = ')).split("'", 2)[1]
    assert captured == wire_literal + '\n'
    value = json.loads(captured)
    assert value == {
        'status': 'NATIVE_PREFLIGHT_VERIFIED', 'python_version': '3.13.9',
        'source_binding_verified': True, 'synthetic_temp_write_read_cleanup': True,
        'approval_authority': False, 'stage': 'temp',
    }
    assert list(temporary.iterdir()) == []


@pytest.mark.parametrize('version', [(3, 13, 9), (3, 13, 8)])
def test_python_version_mode_has_no_path_or_temp_operations(version: tuple[int, int, int], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = helper_module()
    monkeypatch.setattr(module.sys, 'version_info', version)

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError('unexpected path/temp access')

    monkeypatch.setattr(module, 'source_root', forbidden)
    monkeypatch.setattr(module.tempfile, 'TemporaryDirectory', forbidden)
    monkeypatch.setattr(Path, 'open', forbidden)
    monkeypatch.setattr(Path, 'lstat', forbidden)
    assert module.main(['--mode', 'version']) == (0 if version == (3, 13, 9) else 2)
    value = json.loads(capsys.readouterr().out)
    assert value['approval_authority'] is False
    if version == (3, 13, 9):
        assert value['status'] == 'PYTHON_VERSION_VERIFIED'
        assert value['source_binding_verified'] is False
        assert value['temp_probe_performed'] is False
        assert value['stage'] == 'python'
    else:
        assert value['status'] == 'BLOCKED'


@pytest.mark.parametrize('failure', ['python', 'root', 'temp', 'cleanup', 'arguments', 'git_marker'])
def test_python_failures_are_redacted(failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    module = helper_module()
    root, _ = fixture_tree(tmp_path)
    monkeypatch.setattr(module, '__file__', str(root / 'tooling/equity_native_preflight.py'))
    monkeypatch.setattr(module.sys, 'version_info', (3, 13, 9))

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise OSError('PRIVATE_SENTINEL')

    if failure == 'python':
        monkeypatch.setattr(module.sys, 'version_info', (3, 13, 8))
        monkeypatch.setattr(module.tempfile, 'TemporaryDirectory', forbidden)
    elif failure == 'root':
        root = tmp_path
    elif failure == 'temp':
        monkeypatch.setattr(module.tempfile, 'TemporaryDirectory', forbidden)
    elif failure == 'cleanup':
        class FailedCleanup:
            def __enter__(self) -> str:
                path = tmp_path / 'synthetic only'
                path.mkdir()
                return str(path)

            def __exit__(self, *args: object) -> None:
                raise OSError('PRIVATE_SENTINEL')

        monkeypatch.setattr(module.tempfile, 'TemporaryDirectory', lambda **kwargs: FailedCleanup())
    elif failure == 'git_marker':
        (root / '.git/HEAD').unlink()
    arguments = ['--PRIVATE_SENTINEL'] if failure == 'arguments' else ['--root', str(root)]
    assert module.main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.err == ''
    assert json.loads(captured.out) == {
        'status': 'BLOCKED', 'code': 'EQUITY_NATIVE_PREFLIGHT_FAILED', 'approval_authority': False,
        'stage': {'python': 'python', 'arguments': 'python', 'root': 'source',
                  'git_marker': 'source', 'temp': 'temp', 'cleanup': 'temp'}[failure],
    }


def test_helper_rejects_symlink_before_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = helper_module()
    root, _ = fixture_tree(tmp_path)
    monkeypatch.setattr(module, '__file__', str(root / 'tooling/equity_native_preflight.py'))
    info = (root / 'requirements.txt').lstat()

    class Reparse:
        st_mode = info.st_mode
        st_file_attributes = 1024

    original = Path.lstat
    monkeypatch.setattr(Path, 'lstat', lambda path: Reparse() if path == root / 'requirements.txt' else original(path))
    with pytest.raises(ValueError):
        module.source_root(str(root))


def test_static_command_surface_is_file_only_and_pinned() -> None:
    text = WRAPPER.read_text(encoding='utf-8')
    lowered = text.lower()
    for forbidden in ('-encodedcommand', 'invoke-expression', 'invokeexpression', '-command',
                      'remove-item', 'set-acl', 'set-date', 'schtasks', 'start-service',
                      'pip install', 'git ', 'testhook', 'probecommand'):
        assert forbidden not in lowered
    assert ' -c ' not in lowered
    assert 'convertfrom-json' not in lowered
    assert '[StringComparison]::Ordinal)' in text
    assert PIN in text
    assert text.count('& $checkedPython') == 2
    assert '& $checkedPython -I -B $helper --root $checkedRoot' in text
    assert '& $checkedPython -I -B $checkedRunner --root $checkedRoot --output $checkedReceipt' in text
    assert text.index('$probeExit -ne 0') < text.index('& $checkedPython -I -B $checkedRunner')
    assert text.index("if ($Action -ceq 'Preview')") < text.index('$ownScript = Safe-Path')


@pytest.fixture(params=['powershell.exe', 'pwsh.exe'])
def native_shell(request: pytest.FixtureRequest) -> str:
    if os.name != 'nt':
        pytest.skip('Native Windows PowerShell cases require Windows')
    name = str(request.param)
    found = shutil.which(name)
    if not found and name == 'pwsh.exe':
        fallback = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe'
        if fallback.is_file():
            found = str(fallback)
    assert found is not None, f'Required Windows shell unavailable: {name}'
    return found


def native_run(shell: str, script: Path, arguments: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    temporary = tmp_path / 'native temporary \u8bd5'
    temporary.mkdir(exist_ok=True)
    env = dict(os.environ, TEMP=str(temporary), TMP=str(temporary), PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run(
        [shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script), *arguments],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=45, check=False, env=env,
    )


def blocked(result: subprocess.CompletedProcess[str], launches: int, stage: str = 'binder') -> None:
    assert result.returncode != 0, result.stdout
    assert result.stderr == '', result.stderr
    assert result.stdout.startswith('{'), result.stdout
    assert json.loads(result.stdout) == {
        'status': 'BLOCKED', 'code': 'EQUITY_OWNER_VERIFICATION_FAILED',
        'child_invocations': launches, 'preflight_verified': False, 'approval_authority': False,
        'stage': stage,
    }
    assert 'PRIVATE_SENTINEL' not in result.stdout


def test_native_shell_version(native_shell: str, tmp_path: Path) -> None:
    script = tmp_path / 'shell version.ps1'
    script.write_text(
        '@{major=$PSVersionTable.PSVersion.Major;minor=$PSVersionTable.PSVersion.Minor;version=$PSVersionTable.PSVersion.ToString()} | ConvertTo-Json -Compress\n',
        encoding='ascii',
    )
    result = native_run(native_shell, script, [], tmp_path)
    assert result.returncode == 0 and result.stderr == ''
    value = json.loads(result.stdout)
    if Path(native_shell).name.lower() == 'powershell.exe':
        assert value['major'] == 5 and value['minor'] == 1
    else:
        assert value['major'] == 7
    print(f"NATIVE_SHELL_DIAGNOSTIC {Path(native_shell).name} {value['version']}")


def test_native_preview_zero_launches_and_writes(native_shell: str, tmp_path: Path) -> None:
    root, script = fixture_tree(tmp_path)
    before = sorted(str(path.relative_to(root)) for path in root.rglob('*'))
    result = native_run(native_shell, script, [], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    assert json.loads(result.stdout) == {
        'status': 'PREVIEW', 'code': 'NO_ACTION_PERFORMED', 'child_invocations': 0,
        'preflight_verified': False, 'approval_authority': False,
        'stage': 'binder',
    }
    assert before == sorted(str(path.relative_to(root)) for path in root.rglob('*'))
    assert list((tmp_path / 'native temporary \u8bd5').iterdir()) == []


@pytest.mark.parametrize('action', ['Preflight', 'FullSuite'])
def test_native_confirmation_required(native_shell: str, action: str, tmp_path: Path) -> None:
    _, script = fixture_tree(tmp_path)
    blocked(native_run(native_shell, script, ['-Action', action], tmp_path), 0)


def test_native_file_preflight_with_spaces_and_unicode(native_shell: str, tmp_path: Path) -> None:
    root, script = fixture_tree(tmp_path)
    result = native_run(native_shell, script, [
        '-Action', 'Preflight', '-ConfirmRun', '-Root', str(root), '-Python', sys.executable,
    ], tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stderr == ''
    assert json.loads(result.stdout) == {
        'status': 'PREFLIGHT_VERIFIED', 'code': 'NOT_FULL_SUITE_VERIFICATION',
        'child_invocations': 1, 'preflight_verified': True, 'approval_authority': False,
        'stage': 'nativepreflight',
    }
    assert list((tmp_path / 'native temporary \u8bd5').iterdir()) == []


@pytest.mark.parametrize('failure', [
    'nonzero', 'malformed', 'false_flag', 'wrong_python', 'version_only', 'array_status',
    'numeric_flag', 'extra_property', 'wrong_stage', 'duplicate_blocked_then_success',
    'duplicate_success_then_blocked', 'top_level_array', 'numeric_false',
    'leading_whitespace', 'trailing_whitespace', 'compact_json', 'multiline_json',
    'extra_line', 'reordered_json',
])
def test_native_failing_preflight_has_no_downstream_marker(native_shell: str, failure: str, tmp_path: Path) -> None:
    root, script = fixture_tree(tmp_path)
    marker = tmp_path / 'DOWNSTREAM_MARKER'
    synthetic: dict[str, object] = {
        'status': 'NATIVE_PREFLIGHT_VERIFIED', 'python_version': '3.13.9',
        'source_binding_verified': True, 'synthetic_temp_write_read_cleanup': True,
        'approval_authority': False,
        'stage': 'temp',
    }
    if failure == 'false_flag':
        synthetic['synthetic_temp_write_read_cleanup'] = False
    if failure == 'wrong_python':
        synthetic['python_version'] = '3.13.8'
    if failure == 'version_only':
        synthetic['status'] = 'PYTHON_VERSION_VERIFIED'
    if failure == 'array_status':
        synthetic['status'] = ['NATIVE_PREFLIGHT_VERIFIED']
    if failure == 'numeric_flag':
        synthetic['source_binding_verified'] = 1
    if failure == 'extra_property':
        synthetic['PRIVATE_SENTINEL'] = True
    if failure == 'wrong_stage':
        synthetic['stage'] = 'python'
    output = 'PRIVATE_SENTINEL' if failure == 'malformed' else json.dumps(synthetic, sort_keys=True)
    if failure == 'duplicate_blocked_then_success':
        output = output.replace('"status": "NATIVE_PREFLIGHT_VERIFIED"',
                                '"status": "BLOCKED", "status": "NATIVE_PREFLIGHT_VERIFIED"')
    elif failure == 'duplicate_success_then_blocked':
        output = output.replace('"status": "NATIVE_PREFLIGHT_VERIFIED"',
                                '"status": "NATIVE_PREFLIGHT_VERIFIED", "status": "BLOCKED"')
    elif failure == 'top_level_array':
        output = '[' + output + ']'
    elif failure == 'numeric_false':
        output = output.replace('"approval_authority": false', '"approval_authority": 0')
    elif failure == 'leading_whitespace':
        output = ' ' + output
    elif failure == 'trailing_whitespace':
        output += ' '
    elif failure == 'compact_json':
        output = json.dumps(synthetic, sort_keys=True, separators=(',', ':'))
    elif failure == 'multiline_json':
        output = json.dumps(synthetic, sort_keys=True, indent=2)
    elif failure == 'extra_line':
        output += '\nPRIVATE_SENTINEL'
    elif failure == 'reordered_json':
        output = json.dumps(synthetic, sort_keys=False)
    (root / 'tooling/equity_native_preflight.py').write_text(
        'import sys\nprint(' + repr(output) + ')\nsys.exit(' + ('2' if failure == 'nonzero' else '0') + ')\n',
        encoding='utf-8',
    )
    # Test fixture only: substitute the pinned runner body and its matching digest
    # in the copied wrapper. The production pin and source are never changed.
    runner = tmp_path / 'synthetic runner \u65b0.py'
    runner.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("BAD")\n', encoding='utf-8')
    script.write_text(script.read_text(encoding='utf-8').replace(PIN, hashlib.sha256(runner.read_bytes()).hexdigest()), encoding='utf-8')
    receipt = tmp_path / 'NEW external receipt \u65b0'
    result = native_run(native_shell, script, [
        '-Action', 'FullSuite', '-ConfirmRun', '-Root', str(root), '-Python', sys.executable,
        '-Runner', str(runner), '-Receipt', str(receipt),
    ], tmp_path)
    blocked(result, 1, 'nativepreflight')
    assert not marker.exists()
    assert not receipt.exists()


def test_native_read_only_version_helper(native_shell: str, tmp_path: Path) -> None:
    root, _ = fixture_tree(tmp_path)
    script = tmp_path / 'version file call.ps1'
    # Fixed file call with variable arguments: no inline Python or shell text.
    script.write_text('& $args[0] -I -B $args[1] --mode version\nexit $LASTEXITCODE\n', encoding='ascii')
    result = native_run(native_shell, script, [sys.executable, str(root / 'tooling/equity_native_preflight.py')], tmp_path)
    assert result.returncode == 0 and result.stderr == ''
    value = json.loads(result.stdout)
    assert value['status'] == 'PYTHON_VERSION_VERIFIED'
    assert value['temp_probe_performed'] is False
    assert value['stage'] == 'python'
    assert list((tmp_path / 'native temporary \u8bd5').iterdir()) == []


@pytest.mark.parametrize('arguments', [
    ['-Action'], ['-Root'], ['-Action', 'Preflight', '-ConfirmRun', '-Root'],
    ['-PRIVATE_SENTINEL'], ['-Action', 'Preview', '-Action', 'Preflight'],
    ['-ConfirmRun:$false'], ['PRIVATE_SENTINEL'],
])
def test_native_malformed_options_have_only_redacted_json(native_shell: str, arguments: list[str], tmp_path: Path) -> None:
    _, script = fixture_tree(tmp_path)
    blocked(native_run(native_shell, script, arguments, tmp_path), 0)


@pytest.mark.parametrize('exit_code', [0, 2])
def test_native_synthetic_runner_only_after_real_preflight(native_shell: str, exit_code: int, tmp_path: Path) -> None:
    root, script = fixture_tree(tmp_path)
    runner = tmp_path / 'synthetic runner \u65b0.py'
    marker = tmp_path / 'downstream verified args.json'
    runner.write_text(
        'import json, sys\nfrom pathlib import Path\n'
        'Path(' + repr(str(marker)) + ').write_text(json.dumps(sys.argv[1:]))\n'
        'print("PRIVATE_SENTINEL")\nsys.exit(' + str(exit_code) + ')\n', encoding='utf-8',
    )
    script.write_text(script.read_text(encoding='utf-8').replace(PIN, hashlib.sha256(runner.read_bytes()).hexdigest()), encoding='utf-8')
    receipt = tmp_path / 'NEW external receipt \u65b0'
    result = native_run(native_shell, script, [
        '-Action', 'FullSuite', '-ConfirmRun', '-Root', str(root), '-Python', sys.executable,
        '-Runner', str(runner), '-Receipt', str(receipt),
    ], tmp_path)
    assert result.stderr == ''
    assert 'PRIVATE_SENTINEL' not in result.stdout
    value = json.loads(result.stdout)
    assert value['child_invocations'] == 2 and value['preflight_verified'] is True
    assert value['approval_authority'] is False
    assert value['stage'] == 'fullsuite'
    assert (result.returncode == 0) == (exit_code == 0)
    assert value['status'] == ('FULL_SUITE_RUNNER_EXIT_ZERO_REVIEW_RECEIPT' if exit_code == 0 else 'BLOCKED')
    assert json.loads(marker.read_text()) == ['--root', str(root), '--output', str(receipt)]
    assert not receipt.exists()  # Wrapper never creates receipts; fixture runner doesn't either.


@pytest.mark.parametrize('failure', ['root', 'pin', 'existing_receipt', 'internal_receipt', 'relative_python', 'unknown_action'])
def test_native_rejects_bad_bindings_before_launch(native_shell: str, failure: str, tmp_path: Path) -> None:
    root, script = fixture_tree(tmp_path)
    runner = tmp_path / 'untrusted runner.py'
    runner.write_text('raise RuntimeError("PRIVATE_SENTINEL")\n', encoding='utf-8')
    receipt = tmp_path / 'new receipt'
    arguments = ['-Action', 'FullSuite', '-ConfirmRun', '-Root', str(root),
                 '-Python', sys.executable, '-Runner', str(runner), '-Receipt', str(receipt)]
    if failure == 'root':
        arguments[arguments.index('-Root') + 1] = str(tmp_path)
    elif failure == 'existing_receipt':
        receipt.mkdir()
    elif failure == 'internal_receipt':
        arguments[-1] = str(root / 'receipt')
    elif failure == 'relative_python':
        arguments[arguments.index('-Python') + 1] = 'python.exe'
    elif failure == 'unknown_action':
        arguments[1] = 'PRIVATE_SENTINEL'
    stage = {
        'root': 'sourcebinding', 'pin': 'runnerbinding', 'existing_receipt': 'runnerbinding',
        'internal_receipt': 'runnerbinding', 'relative_python': 'sourcebinding',
        'unknown_action': 'binder',
    }[failure]
    blocked(native_run(native_shell, script, arguments, tmp_path), 0, stage)
    assert not (root / 'receipt').exists()


@pytest.mark.parametrize('failure', ['source_reparse', 'helper_reparse', 'source_permission'])
def test_native_path_attributes_fail_closed_without_launch(native_shell: str, failure: str, tmp_path: Path) -> None:
    root, script = fixture_tree(tmp_path)
    # Fixture-local attribute injection avoids requiring junction/ACL privileges.
    # No production hook, filesystem link or real permission change is created.
    original = '$attributes = [IO.File]::GetAttributes($cursor)'
    if failure == 'source_permission':
        injected = "if ($cursor -ceq $Root) { throw [UnauthorizedAccessException]::new('PRIVATE_SENTINEL') } else { " + original + ' }'
    else:
        target = '$PSCommandPath' if failure == 'source_reparse' else "(Join-Path $Root 'tooling/equity_native_preflight.py')"
        injected = 'if ($cursor -ceq ' + target + ') { $attributes = [IO.FileAttributes]::ReparsePoint } else { ' + original + ' }'
    script.write_text(script.read_text(encoding='utf-8').replace(original, injected), encoding='utf-8')
    blocked(native_run(native_shell, script, [
        '-Action', 'Preflight', '-ConfirmRun', '-Root', str(root), '-Python', sys.executable,
    ], tmp_path), 0, 'sourcebinding')
