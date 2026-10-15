"""Parse real PowerShell; execute selected AST blocks with synthetic commands only.

Never run the owner script against Windows identity, Desktop, LOCALAPPDATA,
Task Scheduler, ACLs, services, credentials, capture state, or the network.
"""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'forward_daily_owner.ps1'
SHELL_LABELS = ('windows-powershell-5.1', 'powershell-7')


@pytest.fixture(params=SHELL_LABELS, ids=SHELL_LABELS)
def shell(request: pytest.FixtureRequest) -> str:
    label: str = request.param
    executable = 'powershell' if label == 'windows-powershell-5.1' else 'pwsh'
    value = shutil.which(executable)
    if value is None:
        pytest.skip(f'{label} runtime unavailable; Python/static contracts still run')
    return value


def source() -> str:
    assert SCRIPT.is_file(), 'Main must supply forward_daily_owner.ps1'
    return SCRIPT.read_text(encoding='utf-8-sig')


PARSER = r'''
$ErrorActionPreference = 'Stop'
$PSScriptRoot = Split-Path -Parent $env:DAILY_TEST_SOURCE
# Extracted scriptblocks have no file-owned PSScriptRoot. Resolve only their
# pure-contract resource to the real public source; other joins stay native.
function Join-Path {
    param([AllowEmptyString()][string]$Path,[string]$ChildPath)
    if ($ChildPath -ceq 'forward_daily_contract.py') {
        return [IO.Path]::Combine((Split-Path -Parent $env:DAILY_TEST_SOURCE),$ChildPath)
    }
    return Microsoft.PowerShell.Management\Join-Path -Path $Path -ChildPath $ChildPath
}
$tokens = $null; $parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:DAILY_TEST_SOURCE,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | ForEach-Object { $_.Message } | Out-String) }
$publicCodes=@(); $publicBlockers=@()
$controlPython=$env:DAILY_TEST_PYTHON
foreach ($statement in $ast.EndBlock.Statements) {
    if ($statement -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $statement.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
        $statement.Left.VariablePath.UserPath -in @('publicCodes','publicBlockers','lastNativeExit')) {
        . ([scriptblock]::Create($statement.Extent.Text))
    }
}
function Load-Function([string]$Name) {
    $nodes = @($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $Name},$true))
    if ($nodes.Count -ne 1) { throw 'Missing/duplicate tested function' }
    return $nodes[0].Extent.Text
}
$outer = @($ast.EndBlock.Statements | Where-Object { $_ -is [System.Management.Automation.Language.TryStatementAst] })
if ($outer.Count -ne 1) { throw 'Expected one owner try/catch' }
'''


MOCK_WINDOWS_BOOTSTRAP = r'''
# Metadata-only Windows application fixture; no synthetic executable is run.
$BootstrapPython='C:\Synthetic Runtime\python.exe'
$script:bootstrapApplication=Microsoft.PowerShell.Core\Get-Command -Name $env:DAILY_TEST_PYTHON -CommandType Application | Select-Object -First 1
$script:bootstrapApplication | Add-Member -MemberType NoteProperty -Name Source -Value $BootstrapPython -Force
function Get-Command { return $script:bootstrapApplication }
'''


def run_ps(shell: str, code: str, tmp_path: Path | None = None,
           scenario: str = 'success') -> subprocess.CompletedProcess[str]:
    encoded = base64.b64encode((PARSER + code).encode('utf-16-le')).decode('ascii')
    env = dict(os.environ, DAILY_TEST_SOURCE=str(SCRIPT), DAILY_TEST_SCENARIO=scenario,
               DAILY_TEST_ROOT=str(tmp_path or ROOT), DAILY_TEST_PYTHON=sys.executable)
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            env=env, capture_output=True, text=True, timeout=25, check=False)
    return result


def json_rows(result: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]


@pytest.mark.parametrize('invocation', ['file', 'interactive'])
def test_run_text_exit_status_from_actual_script_file_scope(
        shell: str, tmp_path: Path, invocation: str) -> None:
    code = r'''
Set-StrictMode -Version Latest
$global:LASTEXITCODE=91
$script:LASTEXITCODE=77
try {
        $text=Run-Text $env:DAILY_TEST_PYTHON @('-I','-B','-c','print(12345)')
        @{code='ACCEPTED';output_ok=($text -ceq '12345')} | ConvertTo-Json -Compress
} catch { @{code=$_.Exception.Message;output_ok=$false} | ConvertTo-Json -Compress }
'''
    script = tmp_path / 'Synthetic Native Script Scope.ps1'
    # Definitions must be literal file-owned functions, not scriptblocks created
    # by the AST harness (which have different script-scope ownership).
    definitions = source().split('function Stop-Daily', 1)[1].split('function Run-Json', 1)[0]
    script.write_text("$ErrorActionPreference='Stop'\n$publicCodes=@();$publicBlockers=@()\n"
                      + 'function Stop-Daily' + definitions + code, encoding='utf-8')
    env = dict(os.environ, DAILY_TEST_SOURCE=str(SCRIPT), DAILY_TEST_PYTHON=sys.executable,
               DAILY_FIXTURE_SCRIPT=str(script))
    arguments = (['-File', str(script)] if invocation == 'file' else
                 ['-EncodedCommand', base64.b64encode(
                     '& $env:DAILY_FIXTURE_SCRIPT'.encode('utf-16-le')).decode('ascii')])
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', *arguments],
                            env=env, text=True, capture_output=True, timeout=25, check=False)
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    assert row == {'code': 'ACCEPTED', 'output_ok': True}


@pytest.mark.parametrize('dirty', [False, True], ids=['clean', 'dirty'])
def test_actual_tools_checkout_stage_with_real_git_and_windows_path(
        shell: str, tmp_path: Path, dirty: bool) -> None:
    tools = tmp_path / 'Reviewed Tools Checkout'
    tools.mkdir()
    initialized = subprocess.run(['git', 'init', str(tools)], capture_output=True,
                                 text=True, check=False, timeout=20)
    assert initialized.returncode == 0
    if dirty:
        (tools / 'untracked-public-fixture.txt').write_text('synthetic', encoding='utf-8')
    result = run_ps(shell, r'''
Set-StrictMode -Version Latest
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Run-Text')))
$helper=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-ToolsCheckout'},$true))
if ($helper.Count -eq 1) { . ([scriptblock]::Create($helper[0].Extent.Text)) }
$PSScriptRoot=$env:DAILY_TEST_ROOT
$statements=@($outer[0].Body.Statements)
$begin=@($statements | Where-Object {$_.Extent.Text -ceq "$"+'phase = '+"'REVIEWED_TOOLS_CHECKOUT'"})
$end=@($statements | Where-Object {$_.Extent.Text -match '^\$stateRoot = '})
if ($begin.Count -ne 1 -or $end.Count -ne 1) { throw 'TEST_STAGE_BOUNDARY_INVALID' }
$selected=@($statements | Where-Object {$_.Extent.StartOffset -ge $begin[0].Extent.StartOffset -and $_.Extent.StartOffset -lt $end[0].Extent.StartOffset})
try {
    # Extracted AST blocks have no file-owned PSScriptRoot. Supply only that
    # resource identity; keep the actual Git calls/checks and Run-Text unchanged.
    $stage=($selected.Extent.Text -join "`n").Replace('$PSScriptRoot','$env:DAILY_TEST_ROOT')
    . ([scriptblock]::Create($stage))
    @{code='ACCEPTED';operational_continuation_executed=$false} | ConvertTo-Json -Compress
} catch {
    @{code=$_.Exception.Message;operational_continuation_executed=$false} | ConvertTo-Json -Compress
}
''', tools)
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    assert row['code'] == ('TOOLS_CHECKOUT_NOT_CLEAN' if dirty else 'ACCEPTED')
    assert row['operational_continuation_executed'] is False


def test_fixed_rejections_have_redacted_public_codes() -> None:
    text = source()
    codes = text.split('$publicCodes = @(', 1)[1].split('\n\nfunction Stop-Daily', 1)[0]
    fixed = set(re.findall(r"Stop-Daily '([A-Z0-9_]+)'", text))
    assert fixed <= set(re.findall(r"'([A-Z0-9_]+)'", codes))


def test_check_setup_stops_after_shared_prerequisites_before_any_setup_writes(shell: str) -> None:
    text = source()
    assert text.index("if ($Action -eq 'CheckSetup')") > text.index("$phase = 'PRIVATE_OPS_READ_ONLY_CHECK'")
    assert text.index("if ($Action -eq 'CheckSetup')") < text.index("if ($Action -eq 'Setup')")
    result = run_ps(shell, r'''
$Action='CheckSetup'
$branch=@($outer[0].Body.Statements | Where-Object {$_.Extent.Text -match '^if \(\$Action -eq ''CheckSetup''\)'})
if ($branch.Count -ne 1) { throw 'TEST_BRANCH_MISSING' }
function Run-Text { throw 'UNEXPECTED_NATIVE_CALL' }
function Register-ScheduledTask { throw 'UNEXPECTED_TASK_WRITE' }
function Write-NewOpsRecord { throw 'UNEXPECTED_RECORD_WRITE' }
. ([scriptblock]::Create($branch[0].Extent.Text+"`nthrow 'HOST_CONTINUATION_REACHED'"))
''')
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    assert row['status'] == 'SETUP_PREREQUISITES_CHECK_PASSED_NOT_COMMISSIONED'
    assert row['operational_writes'] == row['capture_invocations'] == row['task_mutations'] == 0
    assert row['capsule'] == row['calendar'] == row['clock'] == row['provider_and_drive'] == 'NOT_CHECKED'
    assert row['start_attempt_marker_effect'] == 'NOT_REACHED'


@pytest.mark.parametrize('case', ['success', 'python', 'ops_unknown', 'ops_controlled'])
def test_bootstrap_and_private_ops_have_separate_prewrite_diagnostics(
        shell: str, case: str) -> None:
    segment = source().split("    $phase = 'PINNED_PYTHON_BOOTSTRAP_CHECK'", 1)[1]
    segment = "$phase = 'PINNED_PYTHON_BOOTSTRAP_CHECK'" + segment.split("    if ($Action -eq 'Setup')", 1)[0]
    encoded = base64.b64encode(segment.encode('utf-8')).decode('ascii')
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Assert-BootstrapPython')))
MOCK_BOOTSTRAP
function Run-Text {
    if ($env:DAILY_TEST_SCENARIO -ceq 'python') { throw 'SYNTHETIC_PRIVATE_ERROR_NOT_FOR_OUTPUT' }
    return '3139009'
}
function Assert-PrivateOps {
    if ($env:DAILY_TEST_SCENARIO -ceq 'ops_unknown') { throw 'SYNTHETIC_PRIVATE_ERROR_NOT_FOR_OUTPUT' }
    if ($env:DAILY_TEST_SCENARIO -ceq 'ops_controlled') { Stop-Daily 'OPS_LINK_REJECTED' }
}
$Action='Setup'
try {
    $segment=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('SEGMENT'))
    . ([scriptblock]::Create($segment))
    $code='ACCEPTED'
} catch { $code=$_.Exception.Message }
@{code=$code;stage=$phase} | ConvertTo-Json -Compress
'''.replace('SEGMENT', encoded).replace('MOCK_BOOTSTRAP', MOCK_WINDOWS_BOOTSTRAP), scenario=case)
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    expected = {'success': 'ACCEPTED', 'python': 'PINNED_PYTHON_3139_REQUIRED',
                'ops_unknown': 'PRIVATE_OPS_READ_UNAVAILABLE', 'ops_controlled': 'OPS_LINK_REJECTED'}[case]
    assert row['code'] == expected
    assert row['stage'] == ('PINNED_PYTHON_BOOTSTRAP_CHECK' if case == 'python'
                            else 'PRIVATE_OPS_READ_ONLY_CHECK')
    assert 'SYNTHETIC_PRIVATE_ERROR' not in result.stdout


@pytest.mark.skipif(sys.platform != 'win32' or sys.version_info[:3] != (3, 13, 9),
                    reason='Native Windows Python 3.13.9 integration fixture; mocked contracts still run')
def test_bootstrap_real_explicit_pinned_python_without_launcher(shell: str) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Run-Text')))
. ([scriptblock]::Create((Load-Function 'Assert-BootstrapPython')))
$BootstrapPython=$env:DAILY_TEST_PYTHON
Assert-BootstrapPython
@{status='EXPLICIT_PINNED_PYTHON_VERIFIED';same_executable=($controlPython -ieq $env:DAILY_TEST_PYTHON)} | ConvertTo-Json -Compress
''')
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    assert row == {'status': 'EXPLICIT_PINNED_PYTHON_VERIFIED', 'same_executable': True}
    assert 'Run-Text \'py\'' not in source() and "'-3.13'" not in source()


@pytest.mark.skipif(sys.platform != 'win32' or sys.version_info[:3] != (3, 13, 9),
                    reason='Native Windows Python 3.13.9 environment fixture; mocked contracts still run')
def test_actual_capsule_venv_command_uses_explicit_bootstrap_offline(
        shell: str, tmp_path: Path) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Run-Text')))
. ([scriptblock]::Create((Load-Function 'Assert-BootstrapPython')))
$BootstrapPython=$env:DAILY_TEST_PYTHON
Assert-BootstrapPython
$codeRoot=$env:DAILY_TEST_ROOT
$commands=@($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.CommandAst] -and $n.Extent.Text -match "^Run-Text.*'-m','venv'"},$true))
if ($commands.Count -ne 1) { throw 'TEST_VENV_COMMAND_NOT_UNIQUE' }
. ([scriptblock]::Create($commands[0].Extent.Text))
$created=Join-Path $codeRoot '.venv\Scripts\python.exe'
$proof=Run-Text $created @('-I','-B','-c','import sys; assert sys.version_info[:3] == (3,13,9); print(3139009)')
@{status='SYNTHETIC_CAPSULE_ENVIRONMENT_VERIFIED';pinned=($proof -ceq '3139009')} | ConvertTo-Json -Compress
''', tmp_path)
    assert result.returncode == 0, result.stderr
    rows = json_rows(result)
    assert rows == [{'status': 'SYNTHETIC_CAPSULE_ENVIRONMENT_VERIFIED', 'pinned': True}]
    assert not (tmp_path / '.venv' / 'forward_daily_contract.py').exists()


@pytest.mark.parametrize('case', ['missing', 'relative', 'unc', 'wrong_proof', 'native_failure'])
def test_bootstrap_rejects_missing_or_unproven_executable_without_fallback(
        shell: str, case: str) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Assert-BootstrapPython')))
MOCK_BOOTSTRAP
switch ($env:DAILY_TEST_SCENARIO) {
    'missing' { $BootstrapPython='' }
    'relative' { $BootstrapPython='relative\python.exe' }
    'unc' { $BootstrapPython='\\synthetic.invalid\share\python.exe' }
}
$script:calls=0
function Run-Text {
    $script:calls++
    if ($env:DAILY_TEST_SCENARIO -eq 'native_failure') { throw 'SYNTHETIC_PRIVATE_ERROR' }
    return 'SYNTHETIC_NOT_A_VERSION_PROOF'
}
try { Assert-BootstrapPython; $code='ACCEPTED' } catch { $code=$_.Exception.Message }
@{code=$code;native_calls=$script:calls} | ConvertTo-Json -Compress
'''.replace('MOCK_BOOTSTRAP', MOCK_WINDOWS_BOOTSTRAP), scenario=case)
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    expected = 'BOOTSTRAP_PYTHON_LOCAL_PATH_REQUIRED' if case in {'missing', 'relative', 'unc'} else 'PINNED_PYTHON_3139_REQUIRED'
    assert row['code'] == expected
    assert row['native_calls'] == (0 if case in {'missing', 'relative', 'unc'} else 1)
    assert 'SYNTHETIC_PRIVATE_ERROR' not in result.stdout


@pytest.mark.parametrize('stage', ['TOOLS_CLEAN_QUERY', 'PUBLIC_CAPSULE_SETUP'])
@pytest.mark.parametrize('code', ['CHILD_BLOCKED_NO_RETRY', 'PUBLIC_NATIVE_TOOL_REQUIRED'])
def test_actual_catch_never_calls_late_native_failure_prewrite(
        shell: str, stage: str, code: str) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
$phase='STAGE'; $pollEnableAttemptedByThisRun=$false; $pollEnableCommitted=$false
$rollbackAttempted=$false; $rollback='NOT_REQUIRED'
$handler=$outer[0].CatchClauses[0].Body.Extent.Text
. ([scriptblock]::Create("try { Stop-Daily 'CODE' } catch " + $handler))
'''.replace('STAGE', stage).replace('CODE', code))
    assert result.returncode == 2, result.stderr
    row, = json_rows(result)
    expected = 'NOT_REACHED' if stage == 'TOOLS_CLEAN_QUERY' else 'NOT_ESTABLISHED'
    assert row['operational_state_effect'] == row['start_attempt_marker_effect'] == expected
    assert row['code'] == code and row['blockers'] == [code]
    assert 'precedes operational writes' not in row['owner_step']
    assert row['raw_error_printed'] is False


@pytest.mark.parametrize('case', ['clean', 'dirty', 'subdirectory', 'not_repo'])
def test_check_tools_entire_script_read_only_in_real_repository(
        shell: str, tmp_path: Path, case: str) -> None:
    tools = tmp_path / 'Synthetic Reviewed Tools'
    tools.mkdir()
    initialized = subprocess.run(['git', 'init', str(tools)], capture_output=True,
                                 text=True, check=False, timeout=20)
    assert initialized.returncode == 0
    script_root = tools / 'nested' if case == 'subdirectory' else tools
    if case == 'not_repo':
        script_root = tmp_path / 'Synthetic Not Repository'
    script_root.mkdir(exist_ok=True)
    script = script_root / 'forward_daily_owner.ps1'
    script.write_text(source(), encoding='utf-8')
    # Keep a genuinely clean public fixture without committing or user identity.
    # .git/info/exclude is disposable fixture metadata, not an owner permission.
    (tools / '.git/info/exclude').write_text('forward_daily_owner.ps1\n', encoding='utf-8')
    if case == 'dirty':
        (tools / 'untracked-public-fixture.txt').write_text('synthetic', encoding='utf-8')
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path / 'UNTOUCHED_PRIVATE_SENTINEL'))
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(script),
                             '-SessionDate', '2026-10-16', '-Action', 'CheckTools', '-ConfirmRun'],
                            env=env, capture_output=True, text=True, timeout=25, check=False)
    row, = json_rows(result)
    if case == 'clean':
        assert result.returncode == 0
        assert row['status'] == 'REVIEWED_TOOLS_CHECK_PASSED'
        assert row['operational_writes'] == row['capture_invocations'] == row['task_mutations'] == 0
    else:
        expected = {'dirty': 'TOOLS_CHECKOUT_NOT_CLEAN',
                    'subdirectory': 'TOOLS_CHECKOUT_ROOT_REQUIRED',
                    'not_repo': 'TOOLS_GIT_QUERY_FAILED'}[case]
        assert result.returncode == 2
        assert row['code'] == expected and row['blockers'] == [expected]
        assert row['stage'].startswith('TOOLS_')
        assert row['operational_state_effect'] == row['start_attempt_marker_effect'] == 'NOT_REACHED'
        assert row['raw_error_printed'] is row['same_slot_retry_allowed'] is False
    assert str(tmp_path) not in result.stdout
    assert not (tmp_path / 'UNTOUCHED_PRIVATE_SENTINEL').exists()


def test_static_public_interface_and_no_prompt_or_repairs() -> None:
    text = source()
    assert re.search(r"ValidateSet\('Preview','CheckTools','CheckSetup','Setup','Prepare','Start','Audit'\)", text)
    assert re.search(r'\[string\]\$SessionDate', text)
    assert re.search(r'\[switch\]\$ConfirmRun', text)
    assert 'Read-Host' not in text
    for forbidden in ('Set-Acl', 'Start-Service', 'Restart-Service', 'Stop-Service',
                      'Start-ScheduledTask', 'Unregister-ScheduledTask', 'Remove-Item'):
        assert not re.search(r'^\s*' + forbidden + r'\b', text, re.MULTILINE)
    assert '[IO.FileMode]::CreateNew' in text
    assert "1251530731cce5b75fad8601567b9320d07b710d" in text
    assert "'checkout','--detach',$base" in text
    assert 'same_slot_retry_allowed=$false' in text


def test_diagnostics_actual_success_status_is_checked() -> None:
    # Read public source as syntax only; do not import or execute host diagnostics.
    import ast
    tree = ast.parse((ROOT / 'future_ops_diagnostics.py').read_text(encoding='utf-8-sig'))
    for name in ('package_check', 'dependencies'):
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Name) and n.func.id == 'Result']
        assert any(isinstance(n.args[0], ast.IfExp)
                   and isinstance(n.args[0].orelse, ast.Constant)
                   and n.args[0].orelse.value == 'CHECKED' for n in returns)
    for mode in ('package', 'dependencies'):
        assert re.search(r"'future_ops_diagnostics.py'.*'" + mode + r"'.*@\('CHECKED'\)", source())


def test_windows_syntax_parser_and_declared_parameters(shell: str) -> None:
    result = run_ps(shell, r'''
@{parameters=@($ast.ParamBlock.Parameters | ForEach-Object {$_.Name.VariablePath.UserPath});errors=$parseErrors.Count} | ConvertTo-Json -Compress
''')
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    assert row['errors'] == 0
    assert {'SessionDate', 'Action', 'ConfirmRun'} <= set(row['parameters'])


@pytest.mark.parametrize('action,confirmed', [(a, c) for a in ('Preview', 'CheckTools', 'CheckSetup', 'Setup', 'Prepare', 'Start', 'Audit') for c in (False, True) if a == 'Preview' or not c])
def test_preview_ast_block_never_reaches_host_commands(shell: str, action: str, confirmed: bool) -> None:
    # Execute only the actual initial parameter/date/preview statements, followed
    # by a sentinel. No source function or host continuation can be reached.
    code = r'''
$SessionDate='2026-10-15'; $Action='ACTION'; $ConfirmRun=CONFIRMED
function Read-Host { throw 'FORBIDDEN_PROMPT' }
function Get-ScheduledTask { throw 'FORBIDDEN_TASK' }
function Run-Text { throw 'FORBIDDEN_PROCESS' }
function Test-Path { throw 'FORBIDDEN_FILE' }
$statements = @($outer[0].Body.Statements)
$preview = @($statements | Where-Object { $_.Extent.Text -match '^if \(-not \$ConfirmRun' })
if ($preview.Count -ne 1) { throw 'Preview guard missing' }
$selected = @($statements | Where-Object {$_.Extent.StartOffset -le $preview[0].Extent.StartOffset})
& ([scriptblock]::Create(($selected.Extent.Text -join "`n") + "`nthrow 'HOST_CONTINUATION_REACHED'"))
'''.replace('ACTION', action).replace('CONFIRMED', '$true' if confirmed else '$false')
    result = run_ps(shell, code)
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    assert row['status'] == 'PREVIEW' and row['session_date'] == '2026-10-15'
    assert row['writes'] == row['network_calls'] == row['credential_reads'] == 0
    assert row['approval_authority'] is False


START_MOCKS = r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Accept-Poll')))
. ([scriptblock]::Create((Load-Function 'Undo-PollEnable')))
. ([scriptblock]::Create((Load-Function 'Report-Digest')))
. ([scriptblock]::Create((Load-Function 'Write-NewOpsRecord')))
$SessionDate='2026-10-15'; $day=[datetime]'2026-10-15'; $phase='TEST'
$ConfirmNotificationSeen=$true; $ConfirmEnableAfterTwoPolls=$true
$pollEnableAttemptedByThisRun=$false; $pollName='synthetic-poll'; $auditName='synthetic-audit'
$pollEnableCommitted=$false; $rollbackAttempted=$false; $rollback='NOT_REQUIRED'
$script:pollEnabled=$false
$base='1251530731cce5b75fad8601567b9320d07b710d'
$taskPlans=[pscustomobject]@{plans=[pscustomobject]@{'synthetic-poll'='SYNTHETIC_REVIEWED_PLAN'}}
$opsRoot=$env:DAILY_TEST_ROOT; $codeRoot='SYNTHETIC_CODE'; $codePython='SYNTHETIC_PYTHON'; $stateRoot='SYNTHETIC_STATE'
$common=@('--session-date',$SessionDate); $script:polls=0; $script:accepts=0
function Log([string]$text) { [Console]::WriteLine('EVENT:'+$text) }
function Gate([string]$mode) { Log ('gate:'+$mode) }
function Assert-PrivateOps {}
function Assert-Capsule {}
function Run-Json {
    param($exe,$Arguments,$Statuses)
    if ($script:pollEnabled) { throw 'Post-commit blocking validation is forbidden' }
    Log 'admission-preflight'
    if ($env:DAILY_TEST_SCENARIO -eq 'readiness_fail') { throw 'PRIVATE_SYNTHETIC_ERROR' }
    return [pscustomobject]@{status='PREOPEN_HOST_CHECK_PASSED';facts=[pscustomobject]@{clock_check='PASS'}}
}
function Run-Text([string]$exe,[string[]]$Arguments,[int[]]$Allowed=@(0)) {
    if ($Arguments -contains '--evaluate') { throw 'Unexpected process' }
    if ($Arguments -contains '-c' -and ($Arguments -join ' ') -match 'accepted_poll') {
        $script:accepts++
        $expected=$Arguments[-1]; $r=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Arguments[-2])) | ConvertFrom-Json
        Log ('accept:'+$expected)
        if ($r.clock_problem -cne 'PASS' -or $r.recorded_decisions -ne [int]$expected -or $r.missing_decisions -ne (75-[int]$expected)) { throw 'Receipt mismatch' }
        if ($env:DAILY_TEST_SCENARIO -eq ('accept_fail_'+$expected)) { throw 'PRIVATE_SYNTHETIC_ERROR' }
        return ''
    }
    Log 'prepared-validator'
    return ''
}
function Now-Ist {
    if ($env:DAILY_TEST_SCENARIO -eq 'late_enable') { return [datetime]'2026-10-15T09:30:00' }
    if ($script:pollEnabled -and $env:DAILY_TEST_SCENARIO -in @('rollback_noop','rollback_error')) { return [datetime]'2026-10-15T09:30:00' }
    return [datetime]'2026-10-15T09:26:00'
}
function Wait-Slot([string]$time) { Log ('wait:'+$time) }
function Assert-Task([string]$Name,[bool]$Enabled) {
    Log ('verify:'+$Name+':'+$Enabled)
    if ($env:DAILY_TEST_SCENARIO -eq 'audit_verify_fail' -and $Name -eq $auditName -and $Enabled) { throw 'PRIVATE_SYNTHETIC_ERROR' }
    if ($env:DAILY_TEST_SCENARIO -in @('poll_verify_fail','wrong_next_trigger') -and $Name -eq $pollName -and -not $Enabled) { throw 'PRIVATE_SYNTHETIC_ERROR' }
}
function Invoke-Capsule([string]$File,[string[]]$Arguments,[string[]]$Statuses) {
    if ($File -cne 'forward_session_ops.py' -or $Arguments -notcontains 'poll') { throw 'Unexpected capsule' }
    $script:polls++; Log ('poll:'+$script:polls)
    if ($env:DAILY_TEST_SCENARIO -eq ('poll_fail_'+$script:polls)) { throw 'PRIVATE_SYNTHETIC_ERROR' }
    return [pscustomobject]@{status='POLL_REMOTE_VERIFIED';clock_problem='PASS';recorded_decisions=$script:polls;missing_decisions=(75-$script:polls)}
}
function Enable-ScheduledTask {
    param($TaskPath,$TaskName,$ErrorAction)
    Log ('enable:'+$TaskName)
    if ($TaskName -eq $pollName) {
        $script:pollEnabled=$true
        if ($env:DAILY_TEST_SCENARIO -eq 'poll_enable_unknown') { throw 'PRIVATE_SYNTHETIC_ERROR' }
    }
}
function Disable-ScheduledTask {
    param($TaskPath,$TaskName,$ErrorAction)
    Log ('disable:'+$TaskName)
    if ($env:DAILY_TEST_SCENARIO -eq 'rollback_error') { throw 'PRIVATE_SYNTHETIC_ERROR' }
    if ($env:DAILY_TEST_SCENARIO -ne 'rollback_noop') { $script:pollEnabled=$false }
}
function Get-ScheduledTask {
    param($TaskPath,$TaskName,$ErrorAction)
    return [pscustomobject]@{TaskName=$TaskName;Settings=[pscustomobject]@{Enabled=$script:pollEnabled}}
}
function Get-ScheduledTaskInfo { throw 'Post-commit query is forbidden' }
'''


def start_code() -> str:
    return START_MOCKS + r'''
$statements=@($outer[0].Body.Statements)
$begin=@($statements | Where-Object {$_.Extent.Text -eq "$"+"phase = 'SUPERVISED_ADMISSION'"})
if ($begin.Count -ne 1) { throw 'Start admission boundary missing' }
$selected=@($statements | Where-Object {$_.Extent.StartOffset -ge $begin[0].Extent.StartOffset})
$body=$selected.Extent.Text -join "`n"
$handler=$outer[0].CatchClauses[0].Body.Extent.Text
$cleanup=$outer[0].Finally.Extent.Text
& ([scriptblock]::Create("try {`n"+$body+"`n} catch "+$handler+" finally "+$cleanup))
'''


def events(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line[6:] for line in result.stdout.splitlines() if line.startswith('EVENT:')]


def test_start_two_verified_polls_audit_first_poll_last(shell: str, tmp_path: Path) -> None:
    result = run_ps(shell, start_code(), tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert events(result) == ['prepared-validator', 'gate:Start', 'wait:09:20:30',
        'poll:1', 'accept:1', 'wait:09:25:30', 'poll:2', 'accept:2',
        'prepared-validator', 'admission-preflight',
        'verify:synthetic-audit:False', 'verify:synthetic-poll:False',
        'enable:synthetic-audit', 'verify:synthetic-audit:True',
        'enable:synthetic-poll']
    rows = json_rows(result)
    assert rows[-1]['status'] == 'POLL_ENABLE_ACKNOWLEDGED_AFTER_VERIFIED_ADMISSION'
    assert rows[-1]['poll_enabled_readback_verified'] is rows[-1]['next_trigger_readback_verified'] is False
    assert rows[-1]['first_trigger_execution_verified'] is False
    assert rows[-1]['training_eligible'] is rows[-1]['remote_custody_verified'] is False
    claims = list(tmp_path.iterdir())
    assert len(claims) == 2
    claim = tmp_path / '2026-10-15-guided-morning-v1.attempt'
    assert claim.read_text() == 'STARTED_OUTCOME_UNKNOWN_UNTIL_VERIFIED_RECEIPTS'
    witness = json.loads((tmp_path / '2026-10-15-guided-activation-v1.json').read_text())
    assert witness['status'] == 'ADMISSION_VERIFIED_ENABLE_SUBMISSION_AUTHORISED'
    assert witness['enable_result'] == 'NOT_ESTABLISHED'
    assert len(witness['poll_report_sha256']) == 2
    assert witness['approval_authority'] is witness['training_eligible'] is False


def test_second_start_cannot_repeat_slot_or_replace_claim(shell: str, tmp_path: Path) -> None:
    claim = tmp_path / '2026-10-15-guided-morning-v1.attempt'
    claim.write_bytes(b'SYNTHETIC_PREEXISTING_UNKNOWN_OUTCOME')
    result = run_ps(shell, start_code(), tmp_path)
    assert result.returncode == 2, result.stderr
    assert events(result) == ['prepared-validator', 'gate:Start']
    assert json_rows(result)[-1]['same_slot_retry_allowed'] is False
    assert claim.read_bytes() == b'SYNTHETIC_PREEXISTING_UNKNOWN_OUTCOME'


def test_existing_activation_witness_blocks_submission_without_overwrite(shell: str,
                                                                       tmp_path: Path) -> None:
    witness = tmp_path / '2026-10-15-guided-activation-v1.json'
    witness.write_bytes(b'SYNTHETIC_PRIOR_UNKNOWN_ACTIVATION')
    result = run_ps(shell, start_code(), tmp_path)
    assert result.returncode == 2, result.stderr
    assert 'enable:synthetic-poll' not in events(result)
    assert witness.read_bytes() == b'SYNTHETIC_PRIOR_UNKNOWN_ACTIVATION'
    assert json_rows(result)[-1]['rollback'] == 'NOT_REQUIRED'
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.parametrize('scenario,polls,armed', [
    ('poll_fail_1', 1, False), ('accept_fail_1', 1, False),
    ('poll_fail_2', 2, False), ('accept_fail_2', 2, False),
    ('late_enable', 2, False), ('audit_verify_fail', 2, False),
    ('poll_verify_fail', 2, False), ('readiness_fail', 2, False),
    ('poll_enable_unknown', 2, True), ('rollback_noop', 2, True), ('rollback_error', 2, True),
    ('wrong_next_trigger', 2, False)])
def test_start_failure_stops_without_retry_and_rolls_back_armed_poll(shell: str, tmp_path: Path,
        scenario: str, polls: int, armed: bool) -> None:
    result = run_ps(shell, start_code(), tmp_path, scenario)
    assert result.returncode == 2, result.stderr
    observed = events(result)
    assert sum(e.startswith('poll:') for e in observed) == polls
    assert observed.count('disable:synthetic-poll') == (1 if armed else 0)
    assert len(set(e for e in observed if e.startswith('poll:'))) == polls
    if scenario in ('poll_fail_1', 'accept_fail_1', 'poll_fail_2', 'accept_fail_2', 'late_enable'):
        assert not any(e.startswith('enable:') for e in observed)
    row = json_rows(result)[-1]
    assert row['status'] == 'BLOCKED'
    assert row['raw_error_printed'] is row['catchup_allowed'] is row['same_slot_retry_allowed'] is False
    if scenario in ('rollback_noop', 'rollback_error'):
        assert row['rollback'] == 'FUTURE_POLL_DISABLE_UNCONFIRMED_OWNER_CHECK_REQUIRED'
    elif armed:
        assert row['rollback'] == 'FUTURE_POLL_DISABLED_NO_PROCESS_TERMINATED'
    assert 'PRIVATE_SYNTHETIC_ERROR' not in result.stdout + result.stderr
    assert len(list(tmp_path.iterdir())) == (2 if armed else 1), 'Preserve the exclusive claim and any precommit witness'


@pytest.mark.parametrize('scenario,accepted', [('valid', True), ('wrong_status', False),
    ('missing', False), ('oversize', False), ('malformed', False)])
def test_run_json_actual_parser_requires_bounded_accepted_report(shell: str, scenario: str,
                                                               accepted: bool) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Run-Json')))
function Run-Text {
    switch ($env:DAILY_TEST_SCENARIO) {
        'valid' { return "synthetic log`n{`"status`":`"CHECKED`"}" }
        'wrong_status' { return '{"status":"BLOCKED"}' }
        'missing' { return 'synthetic log only' }
        'oversize' { return ('x'*131073) }
        'malformed' { return '{invalid-private-payload' }
        default { throw 'Unexpected scenario' }
    }
}
try { $null=Run-Json 'SYNTHETIC' @() @('CHECKED'); @{accepted=$true} | ConvertTo-Json -Compress }
catch { @{accepted=$false} | ConvertTo-Json -Compress }
''', scenario=scenario)
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    assert row['accepted'] is accepted


NATIVE_PY_STUB = r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Run-Text')))
. ([scriptblock]::Create((Load-Function 'Run-Json')))
function Run-Text {
    param([string]$exe,[object[]]$Arguments,[int[]]$Allowed=@(0))
    # Unit-test argument construction separately from application resolution.
    # The native process boundary has its own real-process regression tests.
    $nativeArgs=@($Arguments | Where-Object {$_ -cne '-3.13'})
    [Console]::WriteLine('ARGV:'+($nativeArgs | ConvertTo-Json -Compress))
    $output=& $env:DAILY_TEST_PYTHON @nativeArgs
    if ($LASTEXITCODE -notin $Allowed) { throw 'SYNTHETIC_CHILD_REJECTED' }
    return ($output -join "`n")
}
'''


@pytest.mark.parametrize('scenario', ['valid', 'missing_clock', 'low_reserve', 'repair'])
def test_health_adapter_real_inline_python_uses_only_synthetic_host_module(shell: str,
        tmp_path: Path, scenario: str) -> None:
    task = dict(exists=True, action_matches=True, enabled=False, disabled=True,
                running=False, state='Disabled')
    report: dict[str, Any] = dict(status='PREOPEN_HOST_CHECK_PASSED', blockers=[],
        approval_authority=False, training_eligible=False, repairs_performed=0,
        credentials_checked=False, provider_and_drive_health='NOT_CHECKED',
        facts=dict(time_service_running=True, time_service_automatic=True, clock_check='PASS',
            free_bytes=1024**3, capture_volume_free_bytes=1024**3,
            **{'KiranTrading-Versioned-20261015-poll': dict(task),
               'KiranTrading-Versioned-20261015-audit': dict(task)}))
    if scenario == 'missing_clock':
        del report['facts']['clock_check']
    elif scenario == 'low_reserve':
        report['facts']['free_bytes'] = 1024**3-1
    elif scenario == 'repair':
        report['repairs_performed'] = 1
    module_root = tmp_path / 'Synthetic host module'
    module_root.mkdir()
    (module_root / 'forward_ops_host.py').write_text(
        'MIN_FREE_BYTES=1024**3\ndef preflight(*args, **kwargs):\n    return '+repr(report)+'\n',
        encoding='utf-8')
    result = run_ps(shell, NATIVE_PY_STUB + r'''
$node=@($outer[0].Body.Statements | Where-Object {
    $_ -is [Management.Automation.Language.AssignmentStatementAst] -and
    $_.Left.VariablePath.UserPath -eq 'healthCode'
})
if ($node.Count -ne 1) { throw 'One reviewed health adapter required' }
. ([scriptblock]::Create($node[0].Extent.Text))
try {
    $null=Run-Json $env:DAILY_TEST_PYTHON @('-I','-B','-c',$healthCode,$env:DAILY_TEST_ROOT,'2026-10-15','KiranTrading-Versioned-20261015-poll','KiranTrading-Versioned-20261015-audit','SYNTHETIC_STATE','SYNTHETIC_OPS',(Join-Path $PSScriptRoot 'forward_daily_contract.py')) @('PREOPEN_HOST_CHECK_PASSED')
    $accepted=$true
} catch { $accepted=$false }
@{accepted=$accepted} | ConvertTo-Json -Compress
''', module_root)
    assert result.returncode == 0, result.stderr
    assert json_rows(result) == [dict(accepted=scenario == 'valid')]
    argv, = [json.loads(line[5:]) for line in result.stdout.splitlines() if line.startswith('ARGV:')]
    assert '"' not in argv[argv.index('-c')+1]


@pytest.mark.parametrize('mode', ['Setup', 'Prepare', 'Start', 'Audit'])
def test_gate_actual_arguments_have_one_aware_timestamp(shell: str, mode: str) -> None:
    code = NATIVE_PY_STUB + r'''
. ([scriptblock]::Create((Load-Function 'Gate')))
$SessionDate='2026-10-15'; $calendar=[pscustomobject]@{kind='REGULAR'}
$DownloadedAt='2026-10-15T08:00:00+05:30'
function Now-Ist { return [datetime]'2026-10-15TCLOCK' }
try { Gate 'MODE'; @{accepted=$true} | ConvertTo-Json -Compress }
catch { @{accepted=$false} | ConvertTo-Json -Compress }
'''.replace('CLOCK', '15:40:00' if mode == 'Audit' else '08:30:00').replace('MODE', mode)
    result = run_ps(shell, code)
    assert result.returncode == 0, result.stderr
    argv, = [json.loads(line[5:]) for line in result.stdout.splitlines() if line.startswith('ARGV:')]
    timestamp = argv[argv.index('--at') + 1]
    from datetime import datetime, timedelta
    assert datetime.fromisoformat(timestamp).utcoffset() == timedelta(hours=5, minutes=30)
    assert '+05:30' not in argv, 'Timezone must not become a separate native argument'
    assert argv[argv.index('--calendar-kind') + 1] == 'REGULAR'
    assert len(argv) == (13 if mode == 'Prepare' else 11)
    row, = json_rows(result)
    assert row['accepted'] is True, result.stdout + result.stderr


@pytest.mark.parametrize('expected,change,accepted', [
    (1, {}, True), (2, {}, True),
    (1, {'clock_problem': 'FAIL'}, False),
    (1, {'clock_check': 'PASS', 'clock_problem': None}, False),
    (1, {'decision_recorded_this_poll': False, 'capture_status': 'RAW_INPUT_BLOCKED'}, False),
    (1, {'recorded_decisions': True}, False),
    (2, {'recorded_decisions': 1, 'missing_decisions': 74}, False),
    (2, {'receipt_written': 1}, False)])
def test_accept_poll_base64_argument_through_real_python(shell: str, expected: int,
        change: dict[str, Any], accepted: bool) -> None:
    report: dict[str, Any] = dict(status='POLL_REMOTE_VERIFIED', exit_code=0,
        code='REMOTE_VERIFICATION_COMPLETE', capture_status='VERSIONED_OBSERVATION_RECORDED',
        decision_recorded_this_poll=True, local_poll_committed=True, remote_verified=True,
        receipt_written=True, recorded_decisions=expected, missing_decisions=75-expected,
        clock_problem='PASS', retries=0, approval_authority=False, training_eligible=False)
    report.update(change)
    encoded = base64.b64encode(json.dumps(report).encode()).decode()
    code = NATIVE_PY_STUB + r'''
. ([scriptblock]::Create((Load-Function 'Accept-Poll')))
$report=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('REPORT')) | ConvertFrom-Json
try { Accept-Poll $report EXPECTED; @{accepted=$true} | ConvertTo-Json -Compress }
catch { @{accepted=$false} | ConvertTo-Json -Compress }
'''.replace('REPORT', encoded).replace('EXPECTED', str(expected))
    result = run_ps(shell, code)
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    assert row['accepted'] is accepted, result.stdout + result.stderr
    argv, = [json.loads(line[5:]) for line in result.stdout.splitlines() if line.startswith('ARGV:')]
    assert json.loads(base64.b64decode(argv[-2], validate=True)) == report
    assert argv[-1] == str(expected)
    assert '"' not in argv[argv.index('-c')+1], 'Inline Python must survive PS 5.1 native quoting'


def test_child_failure_public_causes_preserved_private_details_filtered(shell: str) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Run-Text')))
foreach ($case in @(
    @('{"status":"BLOCKED","code":"PREOPEN_DEADLINE_MISSED","raw":"PRIVATE_PATH_TOKEN"}', 'PREOPEN_DEADLINE_MISSED'),
    @('{"status":"BLOCKED","code":"private-error","blockers":["PRIVATE_PATH_TOKEN","CLOCK_UNVERIFIED"]}', 'CLOCK_UNVERIFIED'),
    @('{"status":"BLOCKED","code":"private-error","blockers":["PRIVATE_PATH_TOKEN"]}', 'CHILD_BLOCKED_NO_RETRY'),
    @('PRIVATE_PATH_TOKEN', 'CHILD_BLOCKED_NO_RETRY')
)) {
    $publicBlockers=@(); $script:publicBlockers=@(); $script:payload=$case[0]
    $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($script:payload))
    $child="import base64,sys; print(base64.b64decode(sys.argv[1]).decode()); sys.exit(2)"
    try { $null=Run-Text $env:DAILY_TEST_PYTHON @('-I','-B','-c',$child,$encoded); throw 'Unexpected acceptance' }
    catch { @{code=$_.Exception.Message;expected=$case[1];blockers=@($publicBlockers)} | ConvertTo-Json -Compress }
}
''')
    assert result.returncode == 0, result.stderr
    rows = json_rows(result)
    assert len(rows) == 4
    assert all(row['code'] == row['expected'] for row in rows)
    assert 'PRIVATE_PATH_TOKEN' not in result.stdout


@pytest.mark.parametrize('scenario,expected', [
    ('stderr_exit_zero', 'PASS'),
    ('stderr_safe_json_exit_two', 'CLOCK_UNVERIFIED'),
    ('stderr_unknown_exit_two', 'CHILD_BLOCKED_NO_RETRY')])
def test_run_text_real_native_python_stderr_and_exit_code(shell: str, scenario: str,
                                                        expected: str) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Run-Text')))
$child = switch ($env:DAILY_TEST_SCENARIO) {
    'stderr_exit_zero' { "import json,sys; print('BENIGN_NATIVE_PROGRESS',file=sys.stderr); print(json.dumps(dict(status='CHECKED'))); sys.exit(0)" }
    'stderr_safe_json_exit_two' { "import json,sys; print('PRIVATE_NATIVE_STDERR',file=sys.stderr); print(json.dumps(dict(status='BLOCKED',code='CLOCK_UNVERIFIED',blockers=['PRIVATE_NATIVE_DETAIL','CLOCK_UNVERIFIED']))); sys.exit(2)" }
    'stderr_unknown_exit_two' { "import sys; print('PRIVATE_NATIVE_STDERR',file=sys.stderr); sys.exit(2)" }
    default { throw 'Unexpected scenario' }
}
$progressCaptured=$false; $reportCaptured=$false
try {
    $text=Run-Text $env:DAILY_TEST_PYTHON @('-I','-B','-c',$child)
    $progressCaptured=$text.Contains('BENIGN_NATIVE_PROGRESS')
    $reportCaptured=$text.Contains('CHECKED')
    $code='PASS'
} catch { $code=$_.Exception.Message }
@{code=$code;preference=[string]$ErrorActionPreference;progress_captured=$progressCaptured;report_captured=$reportCaptured;major=$PSVersionTable.PSVersion.Major;minor=$PSVersionTable.PSVersion.Minor;blockers=@($publicBlockers)} | ConvertTo-Json -Compress
''', scenario=scenario)
    assert result.returncode == 0, result.stderr
    row, = json_rows(result)
    assert row['code'] == expected, result.stdout + result.stderr
    assert row['preference'] == 'Stop', 'Native invocation must restore the caller preference'
    if scenario == 'stderr_exit_zero':
        assert row['progress_captured'] is row['report_captured'] is True
    elif scenario == 'stderr_safe_json_exit_two':
        assert row['blockers'] == ['CLOCK_UNVERIFIED']
    else:
        assert row['blockers'] == []
    assert 'PRIVATE_NATIVE_' not in result.stdout + result.stderr
    if Path(shell).name.lower() == 'powershell.exe':
        assert (row['major'], row['minor']) == (5, 1)


@pytest.mark.parametrize('wrapper', ['function', 'alias'])
def test_run_text_rejects_non_application_despite_stale_success(shell: str,
                                                              wrapper: str) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Run-Text')))
function Invoke-SyntheticPrivateWrapper { throw 'PRIVATE_WRAPPER_WAS_EXECUTED' }
if ($env:DAILY_TEST_SCENARIO -eq 'function') {
    function synthetic-private-native { Invoke-SyntheticPrivateWrapper }
} else { Set-Alias synthetic-private-native Invoke-SyntheticPrivateWrapper }
$global:LASTEXITCODE=0
try { $null=Run-Text 'synthetic-private-native' @(); $accepted=$true }
catch { $accepted=$false }
@{accepted=$accepted} | ConvertTo-Json -Compress
''', scenario=wrapper)
    assert result.returncode == 0, result.stderr
    assert json_rows(result) == [{'accepted': False}]
    assert 'PRIVATE_WRAPPER_WAS_EXECUTED' not in result.stdout + result.stderr


def test_actual_wait_slot_deadlines_clock_changes_and_no_catchup(shell: str) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Wait-Slot')))
$SessionDate='2026-10-15'; $day=[datetime]'2026-10-15'
$script:ticks=0; $script:clock=@(); $script:sleeps=0
function Now-Ist {
    $value=$script:clock[[Math]::Min($script:ticks,$script:clock.Count-1)]
    $script:ticks++
    return [datetime]$value
}
function Start-Sleep { param($Milliseconds) $script:sleeps++ }
foreach ($case in @(
    @('exact',@('2026-10-15T09:20:30'),'TARGET_PASSED_OR_WAIT_TOO_LONG_NO_CATCHUP'),
    @('past',@('2026-10-15T09:20:31'),'TARGET_PASSED_OR_WAIT_TOO_LONG_NO_CATCHUP'),
    @('early',@('2026-10-15T07:50:29'),'TARGET_PASSED_OR_WAIT_TOO_LONG_NO_CATCHUP'),
    @('maxwait',@('2026-10-15T07:50:30','2026-10-15T09:20:30'),'PASS'),
    @('normal',@('2026-10-15T09:20:29','2026-10-15T09:20:30'),'PASS'),
    @('late',@('2026-10-15T09:20:29','2026-10-15T09:20:31.001'),'INTERRUPTED_WAIT_NO_CATCHUP'),
    @('backward',@('2026-10-15T09:20:29','2026-10-15T09:20:28'),'WAIT_CLOCK_CHANGED'),
    @('nextday',@('2026-10-15T09:20:29','2026-10-16T09:20:30'),'WAIT_CLOCK_CHANGED')
)) {
    $script:clock=$case[1]; $script:ticks=0; $script:sleeps=0
    try { Wait-Slot '09:20:30'; $code='PASS' } catch { $code=$_.Exception.Message }
    @{scenario=$case[0];code=$code;expected=$case[2];sleeps=$script:sleeps} | ConvertTo-Json -Compress
}
''')
    assert result.returncode == 0, result.stderr
    rows = json_rows(result)
    assert len(rows) == 8
    assert all(row['code'] == row['expected'] for row in rows), rows
    assert all(row['sleeps'] == 0 for row in rows[:3])


def test_assert_task_actual_xml_binding_with_synthetic_cmdlets(shell: str) -> None:
    result = run_ps(shell, r'''
. ([scriptblock]::Create((Load-Function 'Stop-Daily')))
. ([scriptblock]::Create((Load-Function 'Field')))
. ([scriptblock]::Create((Load-Function 'Assert-Task')))
$pollName='synthetic-poll'
$baseline=@'
<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Actions><Exec><Command>SYNTHETIC_PYTHON</Command><Arguments>synthetic --poll</Arguments><WorkingDirectory>SYNTHETIC_CODE</WorkingDirectory></Exec></Actions>
<Principals><Principal><UserId>S-1-5-21-1001</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><StartWhenAvailable>false</StartWhenAvailable><ExecutionTimeLimit>PT4M</ExecutionTimeLimit><WakeToRun>false</WakeToRun><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries></Settings>
<Triggers><TimeTrigger><Enabled>true</Enabled><StartBoundary>2026-10-15T09:30:30+05:30</StartBoundary><EndBoundary>2026-10-15T15:30:31+05:30</EndBoundary><Repetition><Interval>PT5M</Interval><Duration>PT6H</Duration><StopAtDurationEnd>true</StopAtDurationEnd></Repetition></TimeTrigger></Triggers>
</Task>
'@
$taskPlans=[pscustomobject]@{plans=[pscustomobject]@{'synthetic-poll'=$baseline}}
function Get-ScheduledTask {
    param($TaskPath,$TaskName,$ErrorAction)
    $actions=if ($script:scenario -eq 'extra_action') {@(1,2)} else {@(1)}
    $triggers=if ($script:scenario -eq 'extra_trigger') {@(1,2)} else {@(1)}
    $enabled=($script:scenario -eq 'enabled')
    $state=if ($script:scenario -eq 'ready') {'Ready'} else {'Disabled'}
    return [pscustomobject]@{Actions=@($actions);Triggers=@($triggers);Settings=[pscustomobject]@{Enabled=$enabled};State=$state}
}
function Export-ScheduledTask { param($TaskPath,$TaskName,$ErrorAction) return $script:export }
foreach ($case in @(
    @('valid','','','PASS'),
    @('command','SYNTHETIC_PYTHON','OTHER_PYTHON','TASK_EXACT_BINDING_MISMATCH'),
    @('arguments','synthetic --poll','synthetic --other','TASK_EXACT_BINDING_MISMATCH'),
    @('directory','SYNTHETIC_CODE','OTHER_CODE','TASK_EXACT_BINDING_MISMATCH'),
    @('sid','S-1-5-21-1001','S-1-5-21-1002','TASK_EXACT_BINDING_MISMATCH'),
    @('principal','LeastPrivilege','HighestAvailable','TASK_EXACT_BINDING_MISMATCH'),
    @('catchup','<StartWhenAvailable>false','<StartWhenAvailable>true','TASK_EXACT_BINDING_MISMATCH'),
    @('trigger_disabled','<Enabled>true</Enabled>','<Enabled>false</Enabled>','TASK_EXACT_BINDING_MISMATCH'),
    @('battery_start','<DisallowStartIfOnBatteries>false','<DisallowStartIfOnBatteries>true','TASK_EXACT_BINDING_MISMATCH'),
    @('battery_stop','<StopIfGoingOnBatteries>false','<StopIfGoingOnBatteries>true','TASK_EXACT_BINDING_MISMATCH'),
    @('idle_true','<Settings>','<Settings><RunOnlyIfIdle>true</RunOnlyIfIdle>','TASK_EXACT_BINDING_MISMATCH'),
    @('network_true','<Settings>','<Settings><RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>','TASK_EXACT_BINDING_MISMATCH'),
    @('idle_false','<Settings>','<Settings><RunOnlyIfIdle>false</RunOnlyIfIdle>','PASS'),
    @('network_false','<Settings>','<Settings><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>','PASS'),
    @('idle_invalid','<Settings>','<Settings><RunOnlyIfIdle>unknown</RunOnlyIfIdle>','TASK_EXACT_BINDING_MISMATCH'),
    @('network_duplicate','<Settings>','<Settings><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>','TASK_EXACT_BINDING_MISMATCH'),
    @('delay_nonzero','<TimeTrigger>','<TimeTrigger><RandomDelay>PT1M</RandomDelay>','TASK_EXACT_BINDING_MISMATCH'),
    @('delay_zero','<TimeTrigger>','<TimeTrigger><RandomDelay>PT0S</RandomDelay>','PASS'),
    @('delay_invalid','<TimeTrigger>','<TimeTrigger><RandomDelay>unknown</RandomDelay>','TASK_EXACT_BINDING_MISMATCH'),
    @('delay_duplicate','<TimeTrigger>','<TimeTrigger><RandomDelay>PT0S</RandomDelay><RandomDelay>PT0S</RandomDelay>','TASK_EXACT_BINDING_MISMATCH'),
    @('wrong_date','2026-10-15T09:30:30','2026-10-16T09:30:30','TASK_TRIGGER_DATE_MISMATCH'),
    @('wrong_first_slot','2026-10-15T09:30:30','2026-10-15T09:35:30','TASK_TRIGGER_DATE_MISMATCH'),
    @('repeat','PT5M','PT1M','TASK_REPETITION_MISMATCH'),
    @('duplicate','<Command>SYNTHETIC_PYTHON</Command>','<Command>SYNTHETIC_PYTHON</Command><Command>OTHER</Command>','TASK_BINDING_FIELD_MISSING_OR_DUPLICATE'),
    @('missing','<WorkingDirectory>SYNTHETIC_CODE</WorkingDirectory>','','TASK_BINDING_FIELD_MISSING_OR_DUPLICATE'),
    @('xml_declaration','<Settings>','<Settings><!-- synthetic -->','TASK_XML_REQUIRES_REVIEW'),
    @('restart','<Settings>','<Settings><RestartOnFailure/>','TASK_EXTRA_ACTION_OR_RETRY_REJECTED'),
    @('extra_action','','','TASK_EXTRA_ACTION_OR_RETRY_REJECTED'),
    @('extra_trigger','','','TASK_EXTRA_ACTION_OR_RETRY_REJECTED'),
    @('enabled','','','TASK_STATE_NOT_EXPECTED'),
    @('ready','','','TASK_STATE_NOT_EXPECTED')
)) {
    $script:scenario=$case[0]; $script:export=$baseline
    if ($case[1]) { $script:export=$baseline.Replace($case[1],$case[2]) }
    try { Assert-Task 'synthetic-poll' $false; $code='PASS' } catch {$code=$_.Exception.Message}
    @{scenario=$case[0];code=$code;expected=$case[3]} | ConvertTo-Json -Compress
}
''')
    assert result.returncode == 0, result.stderr
    rows = json_rows(result)
    assert len(rows) == 31
    assert all(row['code'] == row['expected'] for row in rows), rows


def test_pipeline_cancellation_rolls_back_uncommitted_enable_once(shell: str) -> None:
    result = run_ps(shell, r'''
$statements=@($outer[0].Body.Statements)
$begin=@($statements | Where-Object {$_.Extent.Text -eq "$"+"phase = 'AUDIT_FIRST_POLL_LAST_ENABLE'"})
if ($begin.Count -ne 1) { throw 'Enable boundary missing' }
$body=(@($statements | Where-Object {$_.Extent.StartOffset -ge $begin[0].Extent.StartOffset}).Extent.Text) -join "`n"
$definitions=(Load-Function 'Stop-Daily')+"`n"+(Load-Function 'Undo-PollEnable')
$mocks=@'
param($shared)
$ErrorActionPreference='Stop'
$SessionDate='2026-10-16'; $pollName='synthetic-poll'; $auditName='synthetic-audit'
$script:pollEnableAttemptedByThisRun=$false; $script:pollEnableCommitted=$false
$script:rollbackAttempted=$false; $script:rollback='NOT_REQUIRED'
$publicCodes=@(); $publicBlockers=@()
$preparedCode='SYNTHETIC_VALIDATOR'; $base='1251530731cce5b75fad8601567b9320d07b710d'
$pollProofs=@(('a'*64),('b'*64))
$taskPlans=[pscustomobject]@{plans=[pscustomobject]@{'synthetic-poll'='SYNTHETIC_PLAN'}}
$codeRoot='SYNTHETIC'; $codePython='SYNTHETIC'; $stateRoot='SYNTHETIC'; $opsRoot='SYNTHETIC'
$PSScriptRoot='SYNTHETIC_CODE'
function Now-Ist { [datetime]'2026-10-16T09:26:00' }
function Assert-Task {}
function Assert-Capsule {}
function Run-Text {}
function Run-Json {
    if ($shared.Enabled) { throw 'Post-enable child is forbidden' }
    [pscustomobject]@{status='PREOPEN_HOST_CHECK_PASSED'}
}
function Report-Digest { return ('a'*64) }
function Write-NewOpsRecord { $shared.WitnessCreated=$true }
function Enable-ScheduledTask {
    param($TaskPath,$TaskName,$ErrorAction)
    if ($TaskName -eq $pollName) {
        $shared.Enabled=$true; $shared.AtEnable=$true
        while ($true) { Start-Sleep -Milliseconds 100 }
    }
}
function Disable-ScheduledTask {
    param($TaskPath,$TaskName,$ErrorAction)
    $shared.DisableCalls++; $shared.Enabled=$false
}
function Get-ScheduledTask {
    param($TaskPath,$TaskName,$ErrorAction)
    [pscustomobject]@{Settings=[pscustomobject]@{Enabled=$shared.Enabled}}
}
function Invoke-Capsule { throw 'Post-enable child is forbidden' }
function Get-ScheduledTaskInfo { throw 'Unexpected continuation' }
'@
if ($null -eq $outer[0].Finally) { throw 'Cancellation cleanup is required' }
$code=$mocks+"`n"+$definitions+"`ntry {`n"+$body+"`n} catch "+$outer[0].CatchClauses[0].Body.Extent.Text+" finally "+$outer[0].Finally.Extent.Text
$shared=[hashtable]::Synchronized(@{Enabled=$false;DisableCalls=0;AtEnable=$false;WitnessCreated=$false})
$pipeline=[PowerShell]::Create()
try {
    [void]$pipeline.AddScript($code).AddArgument($shared)
    $pending=$pipeline.BeginInvoke(); $timer=[Diagnostics.Stopwatch]::StartNew()
    while (-not $shared.AtEnable -and -not $pending.IsCompleted -and $timer.ElapsedMilliseconds -lt 5000) { Start-Sleep -Milliseconds 20 }
    if (-not $shared.AtEnable) { throw ('Synthetic commit attempt was not reached: '+($pipeline.Streams.Error | Out-String)) }
    $pipeline.Stop()
    try { $null=$pipeline.EndInvoke($pending) } catch {}
    @{enabled=$shared.Enabled;disable_calls=$shared.DisableCalls;commit_attempted=$shared.AtEnable;witness_created=$shared.WitnessCreated} | ConvertTo-Json -Compress
} finally { $pipeline.Stop(); $pipeline.Dispose() }
''')
    assert result.returncode == 0, result.stderr
    assert json_rows(result) == [dict(enabled=False, disable_calls=1, commit_attempted=True, witness_created=True)]
