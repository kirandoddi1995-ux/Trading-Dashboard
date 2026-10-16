from datetime import date, datetime
from pathlib import Path
import json
import shutil
import subprocess

import pytest

from forward_operations_runner import ACTIONS, plan

NOW = datetime.fromisoformat('2026-10-16T17:00:00+05:30')


@pytest.mark.parametrize('action', ACTIONS)
def test_plans_do_not_execute_or_attest(action: str) -> None:
    result = plan(date(2026, 10, 19), action, NOW, 'REGULAR')
    assert result['status'] == 'PLAN_ONLY_NOT_OPERATIONAL_GO'
    assert result['command_execution'] is False and result['task_enable_operations'] == 0
    assert result['actual_task_state'] == 'NOT_OBSERVED'
    assert result['automatic_attestation'] is False


@pytest.mark.parametrize('kind', ['CLOSED', 'UNKNOWN'])
def test_closed_or_unknown_calendar_never_go(kind: str) -> None:
    assert plan(date(2026, 10, 20), 'Setup', NOW, kind)['status'] == 'BLOCKED'


@pytest.mark.parametrize('expiry,expected', [('2026-10-15T12:00:00+05:30','EXPIRED'),
    ('2026-11-01T12:00:00+05:30','RENEWAL_DUE_WITHIN_30_DAYS'),
    ('2027-01-01T12:00:00+05:30','NOT_DUE')])
def test_owner_date_expiry_reminder_no_token_reads(expiry: str, expected: str) -> None:
    result = plan(date(2026, 10, 19), 'Prepare', NOW, 'REGULAR', datetime.fromisoformat(expiry))
    assert result['token_expiry_status'] == expected


def test_arbitrary_command_and_naive_expiry_rejected() -> None:
    with pytest.raises(ValueError):
        plan(date(2026, 10, 19), 'powershell -Command anything', NOW, 'REGULAR')
    with pytest.raises(ValueError):
        plan(date(2026, 10, 19), 'Start', NOW, 'REGULAR', datetime(2027, 1, 1))


@pytest.fixture(params=['powershell', 'pwsh'])
def shell(request: pytest.FixtureRequest) -> str:
    found = shutil.which(str(request.param))
    if not found:
        pytest.skip('This PowerShell implementation is not present')
    return found


@pytest.mark.parametrize('action', ['TaskStatus','HostRisk','AlertDrill','AwakeDrill','AwakeLease'])
def test_actual_observer_preview_inert(shell: str, action: str) -> None:
    result = subprocess.run([shell,'-NoProfile','-File','forward_observer_tools.ps1',
        '-SessionDate','2026-10-19','-Action',action], capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    assert value['status'] == 'PREVIEW'
    assert value['task_queries'] == value['notification_calls'] == value['power_requests'] == 0


def test_actual_policy_functions_and_lease_cleanup(shell: str) -> None:
    # Parse/extract only pure functions, never execute the real confirmed script.
    script = """
    $tokens=$null;$errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'forward_observer_tools.ps1'),[ref]$tokens,[ref]$errors)
    if ($errors.Count -ne 0) {throw 'SYNTAX'}
    foreach ($name in @('Drill-Allowed','Lease-Allowed')) {
      $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
      Invoke-Expression $node.Extent.Text
    }
    @{
      early_drill=(Drill-Allowed ([datetime]'2026-10-19T15:59:59') '2026-10-19' $true $true)
      drill=(Drill-Allowed ([datetime]'2026-10-19T16:00:00') '2026-10-19' $true $true)
      unattested=(Drill-Allowed ([datetime]'2026-10-19T16:00:00') '2026-10-19' $true $false)
      preopen=(Lease-Allowed ([datetime]'2026-10-19T07:30:00') '2026-10-19' $true)
      late=(Lease-Allowed ([datetime]'2026-10-19T09:15:00') '2026-10-19' $true)
    }|ConvertTo-Json -Compress
    """
    result = subprocess.run([shell,'-NoProfile','-Command',script], capture_output=True,text=True,check=True)
    assert json.loads(result.stdout) == dict(early_drill=False,drill=True,unattested=False,preopen=True,late=False)
    source = Path('forward_observer_tools.ps1').read_text(encoding='utf8')
    assert 'finally' in source and '2147483648' in source
    assert 'Set-ScheduledTask' not in source and 'powercfg' not in source


@pytest.mark.parametrize('scenario', ['finish', 'interrupted', 'acquire_failed', 'release_failed','once_clock_backwards'])
def test_real_lease_function_releases_on_exception_without_native_calls(shell: str, scenario: str) -> None:
    script = r"""
    $tokens=$null;$errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'forward_observer_tools.ps1'),[ref]$tokens,[ref]$errors)
    $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Hold-Lease'},$true)
    Invoke-Expression $node.Extent.Text
    $script:events=[Collections.Generic.List[string]]::new()
    $acquire={ $script:events.Add('acquire'); return SCENARIO -cne 'acquire_failed' }
    $release={ $script:events.Add('release'); return SCENARIO -cne 'release_failed' }
    $at={ if (SCENARIO -ceq 'once_clock_backwards') {throw 'NO_CLOCK_READ_ALLOWED'}; if (SCENARIO -ceq 'interrupted') {return [datetime]'2026-10-19T15:40:00'}; return [datetime]'2026-10-19T16:00:00' }
    try { Hold-Lease ([datetime]'2026-10-19T15:50:00') $acquire $release $at {throw 'SYNTHETIC_CANCEL'} -Once:(SCENARIO -ceq 'once_clock_backwards') | Out-Null }
    catch { $script:events.Add('caught') }
    ConvertTo-Json -InputObject @($script:events.ToArray()) -Compress
    """.replace('SCENARIO', "'"+scenario+"'")
    result = subprocess.run([shell,'-NoProfile','-Command',script],capture_output=True,text=True,check=True)
    expected = {'finish':['acquire','release'], 'interrupted':['acquire','release','caught'],
                'acquire_failed':['acquire','caught'], 'release_failed':['acquire','release','caught'],
                'once_clock_backwards':['acquire','release']}[scenario]
    assert json.loads(result.stdout) == expected


def test_actual_task_projection_preserves_unknown_enabled(shell: str) -> None:
    script = r"""
    $tokens=$null;$errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'forward_observer_tools.ps1'),[ref]$tokens,[ref]$errors)
    foreach ($function in @('Task-Time','Task-Summary')) {
      $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $function},$true)
      Invoke-Expression $node.Extent.Text
    }
    function Get-ScheduledTask {return [pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$null}}}
    function Get-ScheduledTaskInfo {return [pscustomobject]@{LastTaskResult=0;LastRunTime=[datetime]'2026-10-19T09:30:30';NextRunTime=[datetime]'2026-10-19T09:35:30'}}
    Task-Summary '2026-10-19'|ConvertTo-Json -Depth 5 -Compress
    """
    result = subprocess.run([shell,'-NoProfile','-Command',script],capture_output=True,text=True,check=True)
    assert all(row['enabled'] is None for row in json.loads(result.stdout)['tasks'])


@pytest.mark.parametrize('next_expression,status', [('$null','NOT_REPORTED'),("''",'NOT_REPORTED'),
    ('[datetime]::MinValue','UNCLASSIFIED_OR_UNSET'),("'not a date'",'UNCLASSIFIED_OR_UNSET'),
    ("[datetime]'2026-10-19T09:35:30'",'REPORTED_LOCAL_MACHINE_TIME')])
def test_task_summary_empty_next_trigger_is_not_blocked(shell: str, next_expression: str, status: str) -> None:
    script = r"""
    $tokens=$null;$errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'forward_observer_tools.ps1'),[ref]$tokens,[ref]$errors)
    foreach ($function in @('Task-Time','Task-Summary')) {
      $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $function},$true)
      Invoke-Expression $node.Extent.Text
    }
    function Get-ScheduledTask {return [pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$true}}}
    function Get-ScheduledTaskInfo {return [pscustomobject]@{LastTaskResult=0;LastRunTime=[datetime]'2026-10-16T15:40:00';NextRunTime=NEXT}}
    Task-Summary '2026-10-16'|ConvertTo-Json -Depth 5 -Compress
    """.replace('NEXT',next_expression)
    result=subprocess.run([shell,'-NoProfile','-Command',script],capture_output=True,text=True,check=True)
    rows=json.loads(result.stdout)['tasks']
    assert all(row['next_run_status']==status and row['last_result']==0 for row in rows)
    if status != 'REPORTED_LOCAL_MACHINE_TIME':
        assert all(row['next_run'] is None for row in rows)


@pytest.mark.parametrize('shape',['null_both','missing_both'])
def test_task_summary_null_last_next_and_result_preserve_unknown(shell: str,shape: str) -> None:
    properties='LastRunTime=$null;NextRunTime=$null;' if shape=='null_both' else ''
    script = r"""
    $tokens=$null;$errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'forward_observer_tools.ps1'),[ref]$tokens,[ref]$errors)
    foreach ($function in @('Task-Time','Task-Summary')) {
      $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $function},$true)
      Invoke-Expression $node.Extent.Text
    }
    function Get-ScheduledTask {return [pscustomobject]@{State='Ready';Settings=[pscustomobject]@{Enabled=$null}}}
    function Get-ScheduledTaskInfo {return [pscustomobject]@{PROPERTIES LastTaskResult=$null}}
    Task-Summary '2026-10-16'|ConvertTo-Json -Depth 5 -Compress
    """.replace('PROPERTIES',properties)
    result=subprocess.run([shell,'-NoProfile','-Command',script],capture_output=True,text=True,check=True)
    assert all(row['last_run'] is row['next_run'] is row['last_result'] is row['enabled'] is None
               for row in json.loads(result.stdout)['tasks'])
