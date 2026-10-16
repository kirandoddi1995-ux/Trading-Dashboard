"""Real PowerShell parsing and delegated synthetic stages, never actual coordinator."""
from pathlib import Path
import json
import shutil
import subprocess

import pytest


@pytest.fixture(params=['powershell','pwsh'])
def shell(request: pytest.FixtureRequest) -> str:
    found=shutil.which(str(request.param))
    if not found:
        pytest.skip('This PowerShell implementation is unavailable')
    return found


def functions() -> str:
    return r"""
    $tokens=$null;$errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'forward_guided_owner.ps1'),[ref]$tokens,[ref]$errors)
    if ($errors.Count -ne 0) {throw 'SYNTAX'}
    foreach ($name in @('Invoke-GuidedChain','Read-ChildResult','Child-Arguments','Assert-GuidedWindow')) {
      $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
      Invoke-Expression $node.Extent.Text
    }
    """


def run(shell: str, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([shell,'-NoProfile','-Command',code],capture_output=True,text=True,check=True)


@pytest.mark.parametrize('action',['Preview','SetupAhead','Morning'])
def test_actual_preview_no_host_or_path_access(shell: str,action: str) -> None:
    result=subprocess.run([shell,'-NoProfile','-File','forward_guided_owner.ps1','-SessionDate','2026-10-19',
        '-Action',action,'-ToolsRoot','NONEXISTENT'],capture_output=True,text=True,check=True)
    value=json.loads(result.stdout)
    assert value['status']=='PREVIEW' and value['source_reads']==value['child_invocations']==0
    assert value['session_date']=='2026-10-19'


@pytest.mark.parametrize('mode,expected',[('Morning',['Prepare','Start']),('SetupAhead',['CheckSetup','Setup','CheckTasks'])])
def test_real_chain_exact_order_once(shell: str,mode: str,expected: list[str]) -> None:
    code=functions()+r"""
    $script:events=[Collections.Generic.List[string]]::new()
    $reports=@{Prepare='MORNING_GO_SUPERVISED_START_REQUIRED';Start='POLL_ENABLE_ACKNOWLEDGED_AFTER_VERIFIED_ADMISSION';
      CheckSetup='SETUP_PREREQUISITES_CHECK_PASSED_NOT_COMMISSIONED';CheckTasks='EXISTING_TASK_BINDINGS_CHECKED_NOT_SETUP_ACCEPTANCE';Setup='SETUP_VERIFIED_TASKS_DISABLED'}
    Invoke-GuidedChain 'MODE' {param($stage) $script:events.Add($stage); return @{status=$reports[$stage]}}|Out-Null
    ConvertTo-Json -InputObject @($script:events.ToArray()) -Compress
    """.replace('MODE',mode)
    assert json.loads(run(shell,code).stdout)==expected


@pytest.mark.parametrize('failure',['BLOCKED','UNKNOWN','NULL'])
def test_prepare_failure_never_reaches_start(shell: str,failure: str) -> None:
    code=functions()+r"""
    $script:events=[Collections.Generic.List[string]]::new()
    try {Invoke-GuidedChain 'Morning' {param($stage) $script:events.Add($stage); if ('FAILURE' -ceq 'NULL') {return $null}; return @{status='FAILURE'}}|Out-Null}
    catch {$script:events.Add('stopped')}
    ConvertTo-Json -InputObject @($script:events.ToArray()) -Compress
    """.replace('FAILURE',failure)
    assert json.loads(run(shell,code).stdout)==['Prepare','stopped']


@pytest.mark.parametrize('text,exit_code,accepted', [('{"status":"OK"}',0,True),
    ('{"status":"OK"}',2,False), ('{"status":"BLOCKED"}\n{"status":"OK"}',0,False),
    ('PRIVATE_ERROR',0,False), ('[]',0,False), ('',0,False)])
def test_child_unknowns_and_errors_redacted(shell: str,text: str,exit_code: int,accepted: bool) -> None:
    payload=text.encode().hex()
    code=functions()+f"""
    $bytes=[byte[]]@(for($i=0;$i -lt '{payload}'.Length;$i+=2){{[Convert]::ToByte('{payload}'.Substring($i,2),16)}})
    $text=[Text.Encoding]::UTF8.GetString($bytes)
    try {{$null=Read-ChildResult $text {exit_code} 'Prepare'; @{{accepted=$true}}|ConvertTo-Json -Compress}}
    catch {{@{{accepted=$false;raw_error_printed=$false}}|ConvertTo-Json -Compress}}
    """
    result=run(shell,code)
    assert json.loads(result.stdout)['accepted'] is accepted
    assert 'PRIVATE_ERROR' not in result.stdout


def test_no_generic_shell_or_auto_attestation_in_public_interface() -> None:
    source=Path('forward_guided_owner.ps1').read_text(encoding='utf8')
    assert '[ValidateSet(\'Preview\',\'SetupAhead\',\'Morning\')]' in source
    assert 'Read-Host' not in source and 'Enable-ScheduledTask' not in source
    assert '4ee910bc266fe87b7dd768f4037c4a126896ff1f3d3b5ea7fdab0214b51ce8db' in source
    coordinator=Path('forward_daily_owner.ps1').read_text(encoding='utf8')
    capsule=coordinator.index("    Assert-Capsule\n    $phase = 'REVIEWED_CALENDAR'")
    assert capsule < coordinator.index("    if ($Action -eq 'CheckTasks') {",capsule)
    # Fresh dated capsule must be created by Setup before CheckTasks can inspect it.


@pytest.mark.parametrize('stage',['CheckSetup','CheckTasks','Setup','Prepare','Start'])
def test_actual_child_arguments_confirm_every_stage(shell: str,stage: str) -> None:
    code=functions()+f"""
    ConvertTo-Json -InputObject @(Child-Arguments 'C:/Synthetic tools/coordinator.ps1' '2026-10-19' '{stage}' 'C:/Synthetic Python/python.exe' 'C:/Private Close/source.csv' '2026-10-19T07:30:00+05:30') -Compress
    """
    args=json.loads(run(shell,code).stdout)
    assert args.count('-ConfirmRun')==1
    assert args[args.index('-Action')+1]==stage
    assert ('-AttestNseSource' in args) is (stage=='Prepare')
    assert ('-ConfirmNotificationSeen' in args) is (stage=='Start')


def test_native_synthetic_child_progress_and_confirmation_contract(shell: str,tmp_path: Path) -> None:
    child=tmp_path/'synthetic coordinator.ps1'
    child.write_text('''param([string]$SessionDate,[string]$Action,[string]$BootstrapPython,[switch]$ConfirmRun,[switch]$ConfirmNotificationSeen,[switch]$ConfirmEnableAfterTwoPolls)
if (-not $ConfirmRun) { @{status='PREVIEW'}|ConvertTo-Json -Compress; exit 0 }
Write-Host 'Waiting for ONE future supervised slot 09:20:30 IST. Do not close this window.'
@{status='POLL_REMOTE_VERIFIED';recorded_decisions=1;missing_decisions=74;clock_problem='PASS'}|ConvertTo-Json -Compress
Write-Host 'Waiting for ONE future supervised slot 09:25:30 IST. Do not close this window.'
@{status='POLL_REMOTE_VERIFIED';recorded_decisions=2;missing_decisions=73;clock_problem='PASS'}|ConvertTo-Json -Compress
@{status='POLL_ENABLE_ACKNOWLEDGED_AFTER_VERIFIED_ADMISSION'}|ConvertTo-Json -Compress
''',encoding='utf8')
    escaped=str(child).replace("'","''")
    exe=shell.replace("'","''")
    code=functions()+f"""
    $arguments=Child-Arguments '{escaped}' '2026-10-19' 'Start' 'NEVER_EXECUTE_PYTHON' '' ''
    $raw=@(& '{exe}' @arguments)
    $exit=$LASTEXITCODE
    $result=Read-ChildResult ($raw -join "`n") $exit 'Start'
    $result|ConvertTo-Json -Depth 5 -Compress
    """
    value=json.loads(run(shell,code).stdout)
    assert value['status']=='POLL_ENABLE_ACKNOWLEDGED_AFTER_VERIFIED_ADMISSION'
    assert [(r['recorded_decisions'],r['missing_decisions']) for r in value['guided_poll_summaries']]==[(1,74),(2,73)]


def test_child_failure_effects_preserved_and_private_code_redacted(shell: str) -> None:
    code=functions()+r"""
    $script:guidedChildCode='NOT_ESTABLISHED';$script:guidedChildRollback='NOT_ESTABLISHED'
    $script:guidedChildEffect='NOT_ESTABLISHED';$script:guidedChildMarker='NOT_ESTABLISHED'
    try {Read-ChildResult '{"status":"BLOCKED","stage":"PREOPEN_HEALTH","code":"CLOCK_UNVERIFIED","rollback":"NOT_REQUIRED","operational_state_effect":"NOT_REACHED","start_attempt_marker_effect":"NOT_REACHED"}' 2 'Prepare'|Out-Null}
    catch {@{stage=$script:guidedChildStage;controller_stage=$script:guidedControllerStage;exit=$script:guidedChildExit;code=$script:guidedChildCode;rollback=$script:guidedChildRollback;effect=$script:guidedChildEffect;marker=$script:guidedChildMarker}|ConvertTo-Json -Compress}
    """
    assert json.loads(run(shell,code).stdout)==dict(stage='Prepare',controller_stage='PREOPEN_HEALTH',exit=2,code='CLOCK_UNVERIFIED',
        rollback='NOT_REQUIRED',effect='NOT_REACHED',marker='NOT_REACHED')


@pytest.mark.parametrize('at,day,mode,accepted', [
    ('2026-10-19T07:49:59','2026-10-19','Morning',False),
    ('2026-10-19T07:50:30','2026-10-19','Morning',True),
    ('2026-10-19T08:00:00','2026-10-19','Morning',True),
    ('2026-10-19T09:15:00','2026-10-19','Morning',False),
    ('2026-10-18T08:00:00','2026-10-19','Morning',False),
    ('2026-10-17T10:00:00','2026-10-19','SetupAhead',True),
    ('2026-10-17T10:00:00','2026-10-21','SetupAhead',True),
    ('2026-10-17T10:00:00','2026-10-25','SetupAhead',False)])
def test_early_morning_rejected_before_any_child_marker(shell: str,at: str,day: str,mode: str,accepted: bool) -> None:
    code=functions()+f"""
    try {{Assert-GuidedWindow ([datetime]'{at}') '{day}' '{mode}'; @{{accepted=$true}}|ConvertTo-Json -Compress}}
    catch {{@{{accepted=$false}}|ConvertTo-Json -Compress}}
    """
    assert json.loads(run(shell,code).stdout)['accepted'] is accepted
