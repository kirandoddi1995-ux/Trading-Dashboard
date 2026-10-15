"""AST-only synthetic task mocks; actual sidecar execution is preview-only."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import cast
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'forward_task_binding_diagnostic.ps1'
SECRET = 'SYNTHETIC_SECRET_NEVER_PRINT_9137'
NAMESPACE = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
SELECTORS = {
    'command': 'Actions/Exec/Command',
    'arguments': 'Actions/Exec/Arguments',
    'working_directory': 'Actions/Exec/WorkingDirectory',
    'user_id': 'Principals/Principal/UserId',
    'logon_type': 'Principals/Principal/LogonType',
    'run_level': 'Principals/Principal/RunLevel',
    'trigger_enabled': 'Triggers/TimeTrigger/Enabled',
    'multiple_instances': 'Settings/MultipleInstancesPolicy',
    'start_when_available': 'Settings/StartWhenAvailable',
    'execution_time_limit': 'Settings/ExecutionTimeLimit',
    'wake_to_run': 'Settings/WakeToRun',
    'disallow_battery_start': 'Settings/DisallowStartIfOnBatteries',
    'stop_on_battery': 'Settings/StopIfGoingOnBatteries',
    'start_boundary': 'Triggers/TimeTrigger/StartBoundary',
    'end_boundary': 'Triggers/TimeTrigger/EndBoundary',
    'repeat_interval': 'Triggers/TimeTrigger/Repetition/Interval',
    'repeat_duration': 'Triggers/TimeTrigger/Repetition/Duration',
    'repeat_stop': 'Triggers/TimeTrigger/Repetition/StopAtDurationEnd',
    'settings_enabled': 'Settings/Enabled',
    'idle_condition': 'Settings/RunOnlyIfIdle',
    'network_condition': 'Settings/RunOnlyIfNetworkAvailable',
    'random_delay': 'Triggers/TimeTrigger/RandomDelay',
    'restart': 'Settings/RestartOnFailure',
}
STATUS = 'FIELD_COUNTS_ONLY_NOT_BINDING_ACCEPTANCE'


PARSER = r'''
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Set-StrictMode -Version Latest
$tokens=$null; $parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($env:BINDING_SOURCE,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) { throw 'SIDECAR_PARSE_FAILED' }
foreach ($name in @('Get-BindingSelectors','Read-BindingShape','Read-DatedTask')) {
    $nodes=@($ast.FindAll({param($n)
        $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name
    },$true))
    if ($nodes.Count -ne 1) { throw 'FUNCTION_MISSING_OR_DUPLICATE' }
    . ([scriptblock]::Create($nodes[0].Extent.Text))
}
# These names never resolve to a real scheduler or private filesystem command.
function Get-ScheduledTask { throw 'UNMOCKED_TASK_QUERY_FORBIDDEN' }
function Export-ScheduledTask { throw 'UNMOCKED_TASK_EXPORT_FORBIDDEN' }
function Get-Acl { throw 'ACL_READ_FORBIDDEN' }
function Get-Credential { throw 'CREDENTIAL_READ_FORBIDDEN' }
'''


@pytest.fixture(params=['windows-powershell-5.1', 'powershell-7'])
def shell(request: pytest.FixtureRequest) -> str:
    label = cast(str, request.param)
    executable = shutil.which('powershell' if label == 'windows-powershell-5.1' else 'pwsh')
    if executable is None:
        pytest.skip(f'{label} is absent; synthetic runtime tests explicitly skipped')
    version = subprocess.run(
        [executable, '-NoProfile', '-NonInteractive', '-Command',
         '$PSVersionTable.PSVersion.ToString()'],
        capture_output=True, text=True, timeout=25, check=True,
    ).stdout.strip()
    assert version.startswith('5.1.' if label == 'windows-powershell-5.1' else '7.'), version
    return executable


def run_ps(shell: str, code: str, payload: object = None) -> dict[str, object]:
    encoded = base64.b64encode((PARSER + code).encode('utf-16-le')).decode('ascii')
    result = subprocess.run(
        [shell, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        env=dict(os.environ, BINDING_SOURCE=str(SCRIPT),
                 BINDING_CONTROLLER=str(ROOT / 'forward_daily_owner.ps1'),
                 BINDING_PAYLOAD=json.dumps(payload), BINDING_SECRET=SECRET),
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ''
    assert SECRET not in result.stdout + result.stderr
    value: object = json.loads(result.stdout)
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def task_xml(field: str | None = None, count: int = 1) -> str:
    root = ET.Element('Task', xmlns=NAMESPACE)
    for key, path in SELECTORS.items():
        parts = path.split('/')
        parent = root
        for part in parts[:-1]:
            child = parent.find(part)
            if child is None:
                child = ET.SubElement(parent, part)
            parent = child
        for _ in range(count if key == field else 1):
            ET.SubElement(parent, parts[-1]).text = SECRET
    return ET.tostring(root, encoding='unicode')


def counts(shape: dict[str, object]) -> dict[str, int]:
    assert shape['status'] == STATUS
    assert set(shape) == {'status', 'fields'}
    rows = cast(list[dict[str, object]], shape['fields'])
    assert len(rows) == 23
    assert all(set(row) == {'field', 'count'} and type(row['count']) is int for row in rows)
    return {cast(str, row['field']): cast(int, row['count']) for row in rows}


def test_binding_shape_smoke(shell: str) -> None:
    shape = run_ps(shell, r'''
Read-BindingShape ($env:BINDING_PAYLOAD | ConvertFrom-Json) | ConvertTo-Json -Depth 6 -Compress
''', task_xml())
    assert counts(shape) == dict.fromkeys(SELECTORS, 1)


TASK_MOCKS = r'''
$script:input=$env:BINDING_PAYLOAD | ConvertFrom-Json
$script:queries=0; $script:exports=0
function Get-ScheduledTask {
    [CmdletBinding()]param([string]$TaskPath,[string]$TaskName)
    if ($TaskPath -cne '\' -or $TaskName -cne 'Synthetic-Dated-poll') { throw 'UNEXPECTED_TASK_TARGET' }
    $script:queries++
    switch ($script:input.scenario) {
        'missing' { return }
        'not-found' { Write-Error -Message $env:BINDING_SECRET -Category ObjectNotFound; return }
        'query-error' { Write-Error -Message $env:BINDING_SECRET -Category PermissionDenied; return }
        'query-throw' { throw $env:BINDING_SECRET }
    }
    [pscustomobject]@{
        State=$script:input.state
        Settings=[pscustomobject]@{Enabled=$script:input.enabled;Private=$env:BINDING_SECRET}
        Actions=@($env:BINDING_SECRET,$env:BINDING_SECRET)
        Triggers=@($env:BINDING_SECRET,$env:BINDING_SECRET,$env:BINDING_SECRET)
        Private=$env:BINDING_SECRET
    }
}
function Export-ScheduledTask {
    [CmdletBinding()]param([string]$TaskPath,[string]$TaskName)
    if ($TaskPath -cne '\' -or $TaskName -cne 'Synthetic-Dated-poll') { throw 'UNEXPECTED_EXPORT_TARGET' }
    $script:exports++
    if ($script:input.scenario -ceq 'export-throw') { throw $env:BINDING_SECRET }
    if ($script:input.scenario -ceq 'bad-xml') { return '<broken' }
    return $script:input.xml
}
$row=Read-DatedTask 'Synthetic-Dated-poll' 'poll'
@{row=$row;queries=$script:queries;exports=$script:exports} | ConvertTo-Json -Depth 8 -Compress
'''


def task_result(shell: str, scenario: str = 'present', state: str = 'Ready',
                enabled: object = True) -> dict[str, object]:
    return run_ps(shell, TASK_MOCKS, {
        'scenario': scenario, 'state': state, 'enabled': enabled, 'xml': task_xml(),
    })


def test_dated_task_smoke(shell: str) -> None:
    result = task_result(shell)
    assert result['queries'] == result['exports'] == 1
    row = cast(dict[str, object], result['row'])
    assert set(row) == {'role', 'exists', 'status', 'enabled', 'state', 'actions', 'triggers', 'fields'}
    assert {key: value for key, value in row.items() if key != 'fields'} == {
        'role': 'poll', 'exists': True, 'status': STATUS, 'enabled': True,
        'state': 'Ready', 'actions': 2, 'triggers': 3,
    }
    assert counts({'status': row['status'], 'fields': row['fields']}) == dict.fromkeys(SELECTORS, 1)


def test_actual_script_preview_without_confirmation(shell: str) -> None:
    assert run_ps(shell, r'''
& $env:BINDING_SOURCE -SessionDate '2026-10-16'
''') == {
        'status': 'PREVIEW', 'task_queries': 0, 'task_exports': 0,
        'task_mutations': 0, 'operational_writes': 0, 'credential_reads': 0,
        'approval_authority': False,
    }


def test_selectors_exactly_cover_controller_fields(shell: str) -> None:
    result = run_ps(shell, r'''
$t=$null; $e=$null
$controller=[Management.Automation.Language.Parser]::ParseFile($env:BINDING_CONTROLLER,[ref]$t,[ref]$e)
if ($e.Count) { throw 'CONTROLLER_PARSE_FAILED' }
$nodes=@($controller.FindAll({param($n)
    $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Assert-Task'
},$true))
if ($nodes.Count -ne 1) { throw 'CONTROLLER_FUNCTION_MISSING' }
@{selectors=(Get-BindingSelectors);controller=$nodes[0].Extent.Text} | ConvertTo-Json -Depth 5 -Compress
''')
    selectors = cast(dict[str, str], result['selectors'])
    expected = {key: '/t:Task/' + '/'.join('t:' + part for part in path.split('/'))
                for key, path in SELECTORS.items()}
    assert selectors == expected
    controller = cast(str, result['controller'])
    # Leaf counts are diagnostic observations, not binding acceptance. The
    # controller ALSO checks these explicit ancestor/container cardinalities.
    import re

    literal = set(re.findall(r"'(/t:Task/[^']+)'", controller))
    containers = {'/t:Task/t:Actions', '/t:Task/t:Actions/t:Exec', '/t:Task/t:Principals',
                  '/t:Task/t:Principals/t:Principal', '/t:Task/t:Settings', '/t:Task/t:Triggers',
                  '/t:Task/t:Triggers/t:TimeTrigger', '/t:Task/t:Triggers/t:TimeTrigger/t:Repetition'}
    assert {path for path in literal if not path.endswith('t:')} <= set(selectors.values()) | containers
    assert containers <= literal
    for field in ('StartBoundary', 'EndBoundary', 'Interval', 'Duration', 'StopAtDurationEnd',
                  'RunOnlyIfIdle', 'RunOnlyIfNetworkAvailable', 'Enabled', 'RestartOnFailure'):
        assert field in controller
        assert any(path.endswith('/t:' + field) for path in selectors.values())


@pytest.mark.parametrize('count', [0, 2], ids=['omitted', 'duplicate'])
def test_all_23_fields_count_omissions_and_duplicates(shell: str, count: int) -> None:
    result = run_ps(shell, r'''
$payload=$env:BINDING_PAYLOAD | ConvertFrom-Json
$rows=@(foreach ($entry in (Get-BindingSelectors).GetEnumerator()) {
    $xml=[xml]$payload.xml
    $ns=[Xml.XmlNamespaceManager]::new($xml.NameTable)
    $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    $node=$xml.SelectSingleNode($entry.Value,$ns)
    if ($payload.count -eq 0) { $null=$node.ParentNode.RemoveChild($node) }
    else { $null=$node.ParentNode.AppendChild($node.CloneNode($true)) }
    @{field=$entry.Key;shape=(Read-BindingShape $xml.OuterXml)}
})
@{rows=$rows} | ConvertTo-Json -Depth 9 -Compress
''', {'xml': task_xml(), 'count': count})
    rows = cast(list[dict[str, object]], result['rows'])
    assert len(rows) == 23
    for row in rows:
        expected = dict.fromkeys(SELECTORS, 1)
        expected[cast(str, row['field'])] = count
        assert counts(cast(dict[str, object], row['shape'])) == expected


@pytest.mark.parametrize('scenario', ['malformed', 'oversize', 'dtd', 'comment', 'wrong-root', 'wrong-namespace'])
def test_unsafe_xml_rejected_without_values(shell: str, scenario: str) -> None:
    result = run_ps(shell, r'''
$text=switch ($env:BINDING_PAYLOAD | ConvertFrom-Json) {
    'malformed' { '<Task>'+$env:BINDING_SECRET }
    'oversize' { '<Task>'+('x'*65537)+'</Task>' }
    'dtd' { '<!DOCTYPE Task [<!ENTITY synthetic "'+$env:BINDING_SECRET+'">]><Task>&synthetic;</Task>' }
    'comment' { '<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><!--'+$env:BINDING_SECRET+'--></Task>' }
    'wrong-root' { '<Other />' }
    'wrong-namespace' { '<Task xmlns="urn:synthetic" />' }
}
try { $null=Read-BindingShape $text; @{rejected=$false} | ConvertTo-Json -Compress }
catch { @{rejected=$true} | ConvertTo-Json -Compress }
''', scenario)
    assert result == {'rejected': True}


@pytest.mark.parametrize('scenario,status,exists', [
    ('missing', 'NOT_FOUND', False), ('not-found', 'NOT_FOUND', False),
    ('query-error', 'TASK_QUERY_UNAVAILABLE', None),
    ('query-throw', 'TASK_QUERY_OR_XML_UNAVAILABLE', None),
    ('export-throw', 'TASK_QUERY_OR_XML_UNAVAILABLE', None),
    ('bad-xml', 'TASK_QUERY_OR_XML_UNAVAILABLE', None),
])
def test_missing_and_failed_task_queries_are_distinct_and_redacted(
    shell: str, scenario: str, status: str, exists: bool | None,
) -> None:
    result = task_result(shell, scenario)
    expected: dict[str, object] = {'role': 'poll', 'exists': exists, 'status': status}
    if status == 'TASK_QUERY_OR_XML_UNAVAILABLE':
        expected['raw_error_printed'] = False
    assert result['row'] == expected
    assert result['queries'] == 1
    assert result['exports'] == (1 if scenario in {'export-throw', 'bad-xml'} else 0)


@pytest.mark.parametrize('state,enabled,expected_state,expected_enabled', [
    ('Disabled', False, 'Disabled', False), ('Ready', True, 'Ready', True),
    ('Running', True, 'Running', True), ('Queued', True, 'Queued', True),
    ('Unknown', True, 'Unknown', True), ('ready', 'true', 'UNCLASSIFIED', None),
    (SECRET, 1, 'UNCLASSIFIED', None),
])
def test_state_and_enabled_are_allowlisted_without_raw_task_fields(
    shell: str, state: str, enabled: object, expected_state: str,
    expected_enabled: bool | None,
) -> None:
    result = task_result(shell, state=state, enabled=enabled)
    row = cast(dict[str, object], result['row'])
    assert row['state'] == expected_state
    assert row['enabled'] is expected_enabled
    assert row['actions'] == 2 and row['triggers'] == 3
    assert set(row) == {'role', 'exists', 'status', 'enabled', 'state', 'actions', 'triggers', 'fields'}
