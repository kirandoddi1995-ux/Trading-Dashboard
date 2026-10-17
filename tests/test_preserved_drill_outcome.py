"""Synthetic metadata and Scheduler doubles only; never queries native tasks."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ID = '389daf12415a482eb0231443ddfd8697'


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
def test_preview_has_zero_reads(shell: str) -> None:
    exe = shutil.which(shell)
    if not exe:
        pytest.skip('PowerShell unavailable')
    result = subprocess.run([exe, '-NoProfile', '-File', 'preserved_drill_outcome.ps1'],
                            check=True, capture_output=True, text=True)
    value = json.loads(result.stdout)
    assert value == dict(status='PREVIEW', task_queries=0, task_mutations=0,
                         operational_writes=0, credential_reads=0, capture_invocations=0)


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
@pytest.mark.parametrize('case', ['no_controller', 'no_worker', 'no_report', 'no_launch',
    'no_witness', 'witness', 'null_result', 'string_result', 'bad_state', 'query_failure',
    'too_many', 'directory_marker', 'oversized', 'native_running', 'native_never',
    'native_terminated', 'native_other', 'enabled', 'linked_marker', 'linked_ancestor', 'denied_metadata'])
def test_fixed_attempt_metadata_and_fail_closed(shell: str, case: str, tmp_path: Path) -> None:
    exe = shutil.which(shell)
    if not exe:
        pytest.skip('PowerShell unavailable')
    root = tmp_path / 'KiranTrading' / 'AlertDrills' / ID
    root.mkdir(parents=True)
    names = ['recipe.json', 'recovery-admission.json', 'controller-attempt.json',
             'attempt.json', 'task-witness.json']
    if case == 'no_controller':
        names = names[:2]
    elif case == 'no_worker':
        names = names[:3]
    elif case != 'witness':
        names.remove('task-witness.json')
    for name in names:
        (root / name).write_text('PRIVATE_SENTINEL_NOT_JSON')
    if case == 'directory_marker':
        (root / 'owner-ack.json').mkdir()
    if case == 'oversized':
        (root / 'owner-ack.json').write_bytes(b'x' * 1048577)
    reports = root / 'reports'
    reports.mkdir()
    if case not in ('no_controller', 'no_worker', 'no_report'):
        (reports / ('2026-10-17-' + 'a' * 32 + '.json')).write_text('PRIVATE_SENTINEL')
    identity = __import__('hashlib').sha256(
        json.dumps(['CLOCK_UNVERIFIED', 'CLOCK_CHECK', 'SYNTHETIC_FAILURE_ONLY']).encode()).hexdigest()[:16]
    if case not in ('no_controller', 'no_worker', 'no_report', 'no_launch'):
        (reports / f'2026-10-17-v2-CLOCK_REVIEW_REQUIRED-{identity}-1.launch').write_text('PRIVATE_SENTINEL')
    if case == 'too_many':
        for i in range(17):
            (reports / str(i)).write_text('PRIVATE_SENTINEL')
    script = r'''
$ErrorActionPreference='Stop';$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'preserved_drill_outcome.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count -ne 0) {throw 'PARSE'}
foreach($node in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)) {Invoke-Expression $node.Extent.Text}
$script:taskQueries=0;$script:outcomeStage='TEST';$script:targets=[Collections.Generic.List[string]]::new()
$script:originalGetItem=Get-Command Get-Item -CommandType Cmdlet
function Get-Item {param($LiteralPath,[switch]$Force,$ErrorAction)
 if ('CASE' -ceq 'denied_metadata' -and [IO.Path]::GetFileName($LiteralPath) -ceq 'recipe.json') {throw 'SECRET_NATIVE_MESSAGE'}
 if (('CASE' -ceq 'linked_marker' -and [IO.Path]::GetFileName($LiteralPath) -ceq 'recipe.json') -or
     ('CASE' -ceq 'linked_ancestor' -and [IO.Path]::GetFileName($LiteralPath) -ceq 'AlertDrills')) {
   return [pscustomobject]@{Attributes=[IO.FileAttributes]::ReparsePoint}
 }
 return & $script:originalGetItem -LiteralPath $LiteralPath -Force -ErrorAction Stop
}
function Get-ScheduledTask {param($TaskPath,$TaskName,$ErrorAction)
 if ($TaskPath -cne '\' -or $TaskName -cne 'ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697') {throw 'TARGET'}
 $script:targets.Add('task')
 if ('CASE' -ceq 'query_failure') {throw 'SECRET_NATIVE_MESSAGE'}
 return [pscustomobject]@{Settings=[pscustomobject]@{Enabled=('CASE' -ceq 'enabled')};State=$(if ('CASE' -ceq 'bad_state') {'PRIVATE_SENTINEL'} else {'Disabled'})}
}
function Get-ScheduledTaskInfo {param($TaskPath,$TaskName,$ErrorAction)
 if ($TaskPath -cne '\' -or $TaskName -cne 'ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697') {throw 'TARGET'}
 $script:targets.Add('info')
 $value=switch ('CASE') {'null_result' {$null};'string_result' {'2'};'native_running' {267009};'native_never' {267011};'native_terminated' {267014};'native_other' {2147942402};default {2}}
 return [pscustomobject]@{LastTaskResult=$value}
}
$result=$null;$blocked=$false
try {$result=Invoke-PreservedOutcome 'ROOT'} catch {$blocked=$true}
@{blocked=$blocked;result=$result;queries=$script:taskQueries;targets=@($script:targets.ToArray())}|ConvertTo-Json -Compress -Depth 9
'''.replace('CASE', case).replace('ROOT', str(tmp_path).replace("'", "''"))
    result = subprocess.run([exe, '-NoProfile', '-Command', script],
                            capture_output=True, text=True, check=True)
    assert 'PRIVATE_SENTINEL' not in result.stdout
    assert 'SECRET_NATIVE_MESSAGE' not in result.stdout
    value = json.loads(result.stdout)
    blocked = case in ('null_result', 'string_result', 'bad_state', 'query_failure',
                       'too_many', 'directory_marker', 'oversized', 'linked_marker',
                       'linked_ancestor', 'denied_metadata')
    assert value['blocked'] is blocked
    if blocked:
        return
    report = value['result']
    assert report['task_queries'] == 2
    assert report['task_mutations'] == report['operational_writes'] == report['credential_reads'] == 0
    assert report['retry_authorised'] is report['replacement_id_authorised'] is False
    assert report['metadata_authenticated'] is report['popup_delivery_verified'] is False
    assert report['worker_cause'] == 'NOT_ESTABLISHED'
    expected = dict(no_controller='CONTROLLER_MARKER_ABSENT',
        no_worker='WORKER_CLAIM_MARKER_ABSENT_CAUSE_UNKNOWN',
        no_report='WORKER_CLAIM_PRESENT_REPORT_ABSENT',
        no_launch='REPORT_PRESENT_LAUNCH_MARKER_ABSENT',
        witness='WITNESS_METADATA_PRESENT_NOT_VALIDATED')
    assert report['phase'] == expected.get(case, 'LAUNCH_MARKER_PRESENT_NATIVE_WITNESS_ABSENT')
    assert report['task_disabled'] is (case != 'enabled')
    if case == 'native_other':
        assert report['last_result']['hex'] == '0x80070002'
        assert report['last_result']['category'] == 'OTHER_NATIVE_RESULT_REVIEW_REQUIRED'


def test_source_has_no_execution_or_content_reader() -> None:
    source = Path('preserved_drill_outcome.ps1').read_text()
    for forbidden in ('Start-ScheduledTask', 'Enable-ScheduledTask', 'Disable-ScheduledTask',
        'Register-ScheduledTask', 'Remove-Item', 'Set-Content', 'ReadAllText', 'Get-Content',
        'ConvertFrom-Json', 'Invoke-Expression', 'python', 'Get-WinEvent'):
        assert forbidden not in source
    assert source.count('Get-ScheduledTask -TaskPath') == 1
    assert source.count('Get-ScheduledTaskInfo -TaskPath') == 1
