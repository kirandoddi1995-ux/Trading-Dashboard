"""Real bridge/function/finally logic with synthetic callbacks; zero native changes."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
def test_bridge_preview_is_inert(shell: str) -> None:
    executable = shutil.which(shell)
    if not executable:
        pytest.skip('PowerShell executable unavailable')
    result = subprocess.run([executable, '-NoProfile', '-File', 'preserved_drill_first_run.ps1'],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == dict(status='PREVIEW', reads=0, task_queries=0,
                                           task_mutations=0, operational_writes=0)


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
@pytest.mark.parametrize('case', ['success', 'past_day', 'no_idle', 'bad_audit', 'untyped_audit',
    'collision', 'admission_partial', 'start_unknown', 'disable_unknown', 'interrupted', 'bad_inspection',
    'audit_midnight', 'admission_midnight'])
def test_first_execution_order_consumption_and_cleanup(shell: str, case: str) -> None:
    executable = shutil.which(shell)
    if not executable:
        pytest.skip('PowerShell executable unavailable')
    script = r'''
$ErrorActionPreference='Stop';$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'preserved_drill_first_run.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count -ne 0) {throw 'PARSE_FAILED'}
foreach($name in @('Invoke-PreservedFirstRun','Assert-FirstRunDate')) {
 $node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 Invoke-Expression $node.Extent.Text
}
$outer=@($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.TryStatementAst]})[0]
$finallyText=$outer.Finally.Extent.Text
$cleanup=[scriptblock]::Create($finallyText.Substring(1,$finallyText.Length-2))
$script:events=[Collections.Generic.List[string]]::new();$script:attemptedEnable=$false;$script:disabledVerified=$false
$script:taskName='ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697'
function Assert-DrillWindow {param($Now,$Idle) if (-not $Idle) {throw 'IDLE_REQUIRED'}}
function Test-Path {param($LiteralPath) return ('CASE' -ceq 'collision')}
function Write-DrillWitness {param($Path,$Value)
 if ($Path -notlike '*recovery-admission.json') {throw 'WRONG_MARKER'}
 $script:events.Add('admission')
 if ('CASE' -ceq 'admission_midnight') {$script:mockNow=$script:mockNow.AddDays(1)}
 if ('CASE' -ceq 'admission_partial') {throw 'UNKNOWN_WRITE'}
}
function Disable-ScheduledTask {param($TaskPath,$TaskName,$ErrorAction)
 if ($TaskPath -cne '\' -or $TaskName -cne $script:taskName) {throw 'WRONG_CLEANUP_TARGET'}
 $script:events.Add('cleanup_disable')
}
$audit={
 $script:events.Add('audit')
 if ('CASE' -ceq 'audit_midnight') {$script:mockNow=$script:mockNow.AddDays(1)}
 $r=@{status='PRESERVED_DRILL_FULL_READ_ONLY_REVIEW_NOT_RUN_ADMISSION';source_integrity=$true;task_binding=$true;
 disabled_verified=$true;recipe_consistency=$true;same_ist_day=$true;historical_recipe=$false;run_authorised=$false;replacement_id_authorised=$false}
 if ('CASE' -ceq 'bad_audit') {$r.same_ist_day=$false}
 if ('CASE' -ceq 'untyped_audit') {$r.task_binding='true'}
 return $r
}
$run={
 $script:events.Add('enable');$script:attemptedEnable=$true;$script:events.Add('start')
 if ('CASE' -in @('start_unknown','interrupted')) {throw 'UNKNOWN_START_OR_INTERRUPTION'}
 $script:events.Add('disable')
 if ('CASE' -ceq 'disable_unknown') {throw 'UNKNOWN_DISABLE'}
 $script:disabledVerified=$true
}
$inspect={
 $script:events.Add('inspect')
 if ('CASE' -ceq 'bad_inspection') {return @{status='WRONG'}}
 return @{status='ISOLATED_FAILURE_ROUTE_RECORDED_AWAITING_OWNER_ACK';synthetic=$true;launch_acknowledged=$true;
 task_disabled_owner_witness=$true;production_failure_verified=$false;independent_delivery_verified=$false;owner_acknowledged=$false;scheduler_result=2}
}
$script:mockNow=[datetime]::Parse('2026-10-17T20:00:00');if ('CASE' -ceq 'past_day') {$script:mockNow=$script:mockNow.AddDays(1)}
$clock={$script:mockNow}
$blocked=$false
try {$null=Invoke-PreservedFirstRun (Join-Path ([IO.Path]::GetTempPath()) 'SyntheticDrill') $clock ('CASE' -cne 'no_idle') $audit $run $inspect @{retry_allowed=$false}}
catch {$blocked=$true}
finally {& $cleanup}
@{events=@($script:events.ToArray());blocked=$blocked;disabled_verified=$script:disabledVerified}|ConvertTo-Json -Compress
'''.replace('CASE', case)
    output = subprocess.run([executable, '-NoProfile', '-Command', script],
                            capture_output=True, text=True, check=True)
    result = json.loads(output.stdout)
    assert result['blocked'] is (case != 'success')
    if case in ('past_day', 'no_idle'):
        assert result['events'] == []
    elif case in ('bad_audit', 'untyped_audit', 'collision', 'audit_midnight'):
        assert result['events'] == ['audit']
    elif case in ('admission_partial', 'admission_midnight'):
        assert result['events'] == ['audit', 'admission']
    elif case in ('start_unknown', 'interrupted'):
        assert result['events'] == ['audit', 'admission', 'enable', 'start', 'cleanup_disable']
        assert result['disabled_verified'] is False
    elif case == 'disable_unknown':
        assert result['events'] == ['audit', 'admission', 'enable', 'start', 'disable', 'cleanup_disable']
        assert result['disabled_verified'] is False
    else:
        assert result['events'] == ['audit', 'admission', 'enable', 'start', 'disable', 'inspect']


def test_bridge_has_no_setup_delete_register_or_date_override() -> None:
    source = Path('preserved_drill_first_run.ps1').read_text()
    for forbidden in ('Register-ScheduledTask', 'Unregister-ScheduledTask', 'Remove-Item',
                      'Set-ScheduledTask', '--mode setup', 'Set-Date'):
        assert forbidden not in source
    assert '2026-10-17' in source
    assert 'recovery-admission.json' in source
    assert 'Invoke-IsolatedDrillRun' in source
    assert "Get-ScheduledTask -TaskPath" not in source  # delegated pinned exact query


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
def test_bridge_rejects_unc_and_drive_relative_before_metadata_reads(shell: str) -> None:
    executable = shutil.which(shell)
    if not executable:
        pytest.skip('PowerShell executable unavailable')
    script = r'''
$ErrorActionPreference='Stop';$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'preserved_drill_first_run.ps1'),[ref]$tokens,[ref]$errors)
$node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Read-BridgeHash'},$true)
Invoke-Expression $node.Extent.Text
$script:reads=0;$rejected=0
function Get-Item {param($LiteralPath,[switch]$Force,$ErrorAction) $script:reads++;throw 'NO_METADATA_ALLOWED'}
foreach($path in @('C:relative','\\synthetic-server\share\recipe.json','/tmp/not-windows')) {
 try {$null=Read-BridgeHash $path} catch {if ($_.Exception.Message -ceq 'EXPLICIT_PATHS_REQUIRED') {$rejected++} else {throw}}
}
@{rejected=$rejected;reads=$script:reads}|ConvertTo-Json -Compress
'''
    output = subprocess.run([executable, '-NoProfile', '-Command', script], capture_output=True, text=True, check=True)
    assert json.loads(output.stdout) == dict(rejected=3, reads=0)


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
@pytest.mark.parametrize('case', ['success', 'binding_midnight', 'start_midnight'])
def test_actual_bridge_composed_with_pinned_run_helper(shell: str, case: str) -> None:
    executable = shutil.which(shell)
    if not executable:
        pytest.skip('PowerShell executable unavailable')
    script = r'''
$ErrorActionPreference='Stop';$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'preserved_drill_first_run.ps1'),[ref]$tokens,[ref]$errors)
foreach($name in @('Invoke-PreservedFirstRun','Assert-FirstRunDate','Enable-ScheduledTask','Start-ScheduledTask')) {
 $node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 Invoke-Expression $node.Extent.Text
}
$outer=@($ast.EndBlock.Statements|Where-Object {$_ -is [Management.Automation.Language.TryStatementAst]})[0]
$text=$outer.Finally.Extent.Text;$cleanup=[scriptblock]::Create($text.Substring(1,$text.Length-2))
$controller=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'isolated_alert_task_drill.ps1'),[ref]$tokens,[ref]$errors)
foreach($name in @('Invoke-IsolatedDrillRun','Assert-DrillTask','Test-DrillCurrentUser','Assert-DrillWindow')) {
 $node=$controller.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 Invoke-Expression $node.Extent.Text
}
function Resolve-DrillAccountSid {param($Account) return 'SYNTHETIC_SAME_SID'}
$script:events=[Collections.Generic.List[string]]::new();$script:enabled=$false;$script:worker=$false
$script:mockNow=[datetime]::Parse('2026-10-17T20:00:00');$script:attemptedEnable=$false;$script:disabledVerified=$false
$script:taskName='ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697'
$script:bridgeClock={$script:mockNow};$script:controllerAttempt=$false
$script:bridgeNativeEnable={param($TaskPath,$TaskName,$ErrorAction)
 $script:events.Add('enable');$script:enabled=$true
 if ('CASE' -ceq 'start_midnight') {$script:mockNow=$script:mockNow.AddDays(1)}
}
$script:bridgeNativeStart={param($TaskPath,$TaskName,$ErrorAction) $script:events.Add('start');$script:worker=$true}
function SyntheticPython {$global:LASTEXITCODE=0;return '{"status":"ISOLATED_DRILL_PREREQUISITES_CHECK_PASSED"}'}
function Get-ScheduledTask {param($TaskPath,$TaskName,$ErrorAction)
 if ('CASE' -ceq 'binding_midnight') {$script:mockNow=[datetime]::Parse('2026-10-18T00:00:00')}
 [pscustomobject]@{State=$(if($script:enabled){'Ready'}else{'Disabled'});Triggers=@();
 Actions=@([pscustomobject]@{Execute='SyntheticPython';Arguments='ARGS';WorkingDirectory='DIR'});
 Principal=[pscustomobject]@{UserId='SID';RunLevel='Limited';LogonType='Interactive'};
 Settings=[pscustomobject]@{Enabled=$script:enabled;RestartCount=0;MultipleInstances='IgnoreNew';ExecutionTimeLimit='PT120S';WakeToRun=$false;StartWhenAvailable=$false}}
}
function Test-Path {param($LiteralPath)
 if ($LiteralPath -like '*controller-attempt.json') {return $script:controllerAttempt}
 if ($LiteralPath -like '*attempt.json') {return $script:worker}
 return $false
}
function Write-DrillWitness {param($Path,$Value)
 if ($Path -like '*recovery-admission.json') {$script:events.Add('admission')}
 elseif ($Path -like '*controller-attempt.json') {$script:events.Add('controller');$script:controllerAttempt=$true}
 else {$script:events.Add('witness')}
}
function Get-ScheduledTaskInfo {param($TaskPath,$TaskName,$ErrorAction) [pscustomobject]@{LastTaskResult=2}}
function Start-Sleep {param($Seconds)}
function Disable-ScheduledTask {param($TaskPath,$TaskName,$ErrorAction)
 if ($TaskName -cne $script:taskName -or $TaskPath -cne '\') {throw 'WRONG_CLEANUP'}
 $script:events.Add('disable');$script:enabled=$false
}
$root=Join-Path ([IO.Path]::GetTempPath()) 'SyntheticOnly'
$audit={@{status='PRESERVED_DRILL_FULL_READ_ONLY_REVIEW_NOT_RUN_ADMISSION';source_integrity=$true;task_binding=$true;disabled_verified=$true;recipe_consistency=$true;same_ist_day=$true;historical_recipe=$false;run_authorised=$false;replacement_id_authorised=$false}}
$run={Invoke-IsolatedDrillRun $script:taskName 'SyntheticPython' 'WORKER' 'ARGS' 'DIR' 'SID' 'USER' $root '389daf12415a482eb0231443ddfd8697'}
$inspect={@{status='ISOLATED_FAILURE_ROUTE_RECORDED_AWAITING_OWNER_ACK';synthetic=$true;launch_acknowledged=$true;task_disabled_owner_witness=$true;production_failure_verified=$false;independent_delivery_verified=$false;owner_acknowledged=$false;scheduler_result=[long]2}}
$blocked=$false
try {$null=Invoke-PreservedFirstRun $root $script:bridgeClock $true $audit $run $inspect @{retry_allowed=$false}}
catch {$blocked=$true}
finally {& $cleanup}
@{events=@($script:events.ToArray());blocked=$blocked;enabled=$script:enabled}|ConvertTo-Json -Compress
'''.replace('CASE', case)
    output = subprocess.run([executable, '-NoProfile', '-Command', script],
                            capture_output=True, text=True, check=True)
    result = json.loads(output.stdout)
    assert result['enabled'] is False
    assert result['blocked'] is (case != 'success')
    assert result['events'] == {
        'success': ['admission', 'controller', 'enable', 'start', 'disable', 'witness'],
        'binding_midnight': ['admission', 'controller', 'disable'],
        'start_midnight': ['admission', 'controller', 'enable', 'disable'],
    }[case]
