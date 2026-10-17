"""Fixed historical XML fixtures and log doubles; no real event log access."""
import base64
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
def test_history_preview_has_no_io(shell: str) -> None:
    exe = shutil.which(shell)
    if not exe:
        pytest.skip('PowerShell unavailable')
    output = subprocess.run([exe, '-NoProfile', '-File', 'preserved_drill_history.ps1'],
                            check=True, capture_output=True, text=True)
    result = json.loads(output.stdout)
    assert result == dict(status='PREVIEW', log_queries=0, event_queries=0,
                         task_mutations=0, operational_writes=0, credential_reads=0, capture_invocations=0)


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
@pytest.mark.parametrize('case', ['good', 'disabled', 'empty', 'other_task', 'wrong_provider',
    'old_time', 'future_time', 'duplicate_result', 'missing_task', 'duplicate_task',
    'oversized_xml', 'dtd', 'too_many', 'untyped_log', 'bad_id', 'non_numeric', 'out_of_range',
    'hex_result', 'no_result', 'query_failure'])
def test_bounded_history_filtering_and_redaction(shell: str, case: str) -> None:
    exe = shutil.which(shell)
    if not exe:
        pytest.skip('PowerShell unavailable')
    task = r'\ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697'
    provider = 'Microsoft-Windows-TaskScheduler'
    at = '2026-10-17T14:55:20.0000000Z'
    event_id = '201'
    result = '2'
    if case == 'other_task':
        task = r'\PRIVATE_SENTINEL'
    if case == 'wrong_provider':
        provider = 'PRIVATE_SENTINEL'
    if case == 'old_time':
        at = '2026-10-17T14:53:59Z'
    if case == 'future_time':
        at = '2026-10-17T15:03:00.001Z'
    if case == 'bad_id':
        event_id = 'PRIVATE_SENTINEL'
    if case == 'non_numeric':
        result = 'PRIVATE_SENTINEL'
    if case == 'out_of_range':
        result = '4294967296'
    if case == 'hex_result':
        result = '0x80070002'
    task_node = '' if case == 'missing_task' else f'<Data Name="TaskName">{task}</Data>'
    if case == 'duplicate_task':
        task_node *= 2
    result_node = '' if case == 'no_result' else f'<Data Name="ResultCode">{result}</Data>'
    if case == 'duplicate_result':
        result_node *= 2
    xml = (f'<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">'
           f'<System><Provider Name="{provider}"/><EventID>{event_id}</EventID>'
           f'<TimeCreated SystemTime="{at}"/></System><EventData>{task_node}{result_node}'
           '<Data Name="UserContext">PRIVATE_SENTINEL</Data>'
           '<Data Name="ActionName">PRIVATE_SENTINEL</Data></EventData></Event>')
    if case == 'dtd':
        xml = '<!DOCTYPE Event [<!ENTITY xxe SYSTEM "file:///PRIVATE_SENTINEL">]>' + xml
    encoded = base64.b64encode(xml.encode()).decode()
    script = r'''
$ErrorActionPreference='Stop';$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'preserved_drill_history.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count -ne 0) {throw 'PARSE'}
foreach($node in $ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]},$true)) {Invoke-Expression $node.Extent.Text}
$xml=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('ENCODED'))
if ('CASE' -ceq 'oversized_xml') {$xml=$xml+('x'*65537)}
$event=[pscustomobject]@{Xml=$xml};$event|Add-Member -MemberType ScriptMethod -Name ToXml -Value {$this.Xml}
$log={return [pscustomobject]@{IsEnabled=$(if ('CASE' -ceq 'untyped_log') {'true'} else {'CASE' -cne 'disabled'})}}
$script:eventCalls=0
$query={
 $script:eventCalls++
 if ('CASE' -ceq 'query_failure') {throw 'PRIVATE_SENTINEL'}
 if ('CASE' -ceq 'disabled') {throw 'QUERY_MUST_NOT_RUN'}
 if ('CASE' -ceq 'empty') {return}
 if ('CASE' -ceq 'too_many') {return (1..65|ForEach-Object {$event})}
 return $event
}
$result=$null;$blocked=$false
try {$result=Invoke-DrillHistory $log $query} catch {$blocked=$true}
@{blocked=$blocked;result=$result;event_calls=$script:eventCalls}|ConvertTo-Json -Compress -Depth 8
'''.replace('ENCODED', encoded).replace('CASE', case)
    output = subprocess.run([exe, '-NoProfile', '-Command', script],
                            capture_output=True, text=True, check=True)
    assert 'PRIVATE_SENTINEL' not in output.stdout
    value = json.loads(output.stdout)
    success = case in ('good', 'disabled', 'empty', 'hex_result', 'no_result')
    assert value['blocked'] is (not success)
    if not success:
        return
    report = value['result']
    assert report['retry_authorised'] is report['replacement_id_authorised'] is False
    assert report['popup_delivery_verified'] is False
    assert report['task_mutations'] == report['operational_writes'] == report['credential_reads'] == 0
    if case == 'disabled':
        assert value['event_calls'] == 0
    elif case == 'empty':
        assert report['events'] == []
        assert report['history_complete'] is False
    elif case == 'no_result':
        assert report['events'][0]['result'] is None
    else:
        assert report['events'][0]['result']['decimal'] == (2147942402 if case == 'hex_result' else 2)


def test_live_query_is_fixed_and_has_no_execution_path() -> None:
    source = Path('preserved_drill_history.ps1').read_text()
    for forbidden in ('Start-ScheduledTask', 'Enable-ScheduledTask', 'Set-ScheduledTask',
                      'Remove-Item', 'Set-Content', 'WriteAllText', 'Get-Content', 'wevtutil'):
        assert forbidden not in source
    assert "-MaxEvents 65" in source
    assert "2026-10-17T14:54:00Z" in source
    assert "2026-10-17T15:03:00Z" in source
    assert "Data[@Name='TaskName']='\\ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697'" in source
