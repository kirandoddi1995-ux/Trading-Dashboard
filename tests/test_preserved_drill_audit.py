from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

import preserved_drill_audit as audit


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    old = tmp_path / 'public-old'
    root = tmp_path / 'isolated-state'
    old.mkdir()
    root.mkdir()
    sources = {name: audit.sha(name.encode()) for name in audit.SOURCE_PINS}
    monkeypatch.setattr(audit, 'SOURCE_PINS', sources)
    monkeypatch.setattr(audit, 'WORKER_HASH', audit.sha(b'worker fixture'))
    monkeypatch.setattr(audit, 'OLD_CONTROLLER_HASH', audit.sha(b'controller fixture'))
    for name in sources:
        (old / name).write_bytes(name.encode())
    (old / 'isolated_alert_drill.py').write_bytes(b'worker fixture')
    (old / 'isolated_alert_task_drill.ps1').write_bytes(b'controller fixture')
    (root / 'recipe.json').write_text(json.dumps(dict(schema='isolated-alert-drill-v1',
        identifier=audit.REVIEWED_ID, session_date='2026-10-17', sources=sources,
        worker_sha256=audit.WORKER_HASH, synthetic=True)))
    return old, root


def test_consistency_is_never_run_or_replacement_admission(prepared: tuple[Path, Path]) -> None:
    old, root = prepared
    before = (root / 'recipe.json').read_bytes()
    result = audit.review(old, root, audit.REVIEWED_ID, datetime(2026, 10, 17, 12, tzinfo=timezone.utc))
    assert result['same_ist_day'] is True
    assert result['run_authorised'] is False
    assert result['replacement_id_authorised'] is False
    assert result['recipe_authenticated'] is False
    assert result['operational_writes'] == 0
    assert (root / 'recipe.json').read_bytes() == before
    assert len(list(root.iterdir())) == 1


def test_ist_midnight_does_not_rebase_recipe(prepared: tuple[Path, Path]) -> None:
    old, root = prepared
    result = audit.review(old, root, audit.REVIEWED_ID, datetime(2026, 10, 17, 18, 30, tzinfo=timezone.utc))
    assert result['historical_recipe'] is True
    assert result['run_authorised'] is False


@pytest.mark.parametrize('file', ['isolated_alert_drill.py', 'isolated_alert_task_drill.ps1', 'forward_ops_host.py'])
def test_old_source_tamper_blocks(prepared: tuple[Path, Path], file: str) -> None:
    old, root = prepared
    (old / file).write_bytes(b'changed')
    with pytest.raises(ValueError, match='OLD_PUBLIC_SOURCE_PIN_MISMATCH'):
        audit.review(old, root, audit.REVIEWED_ID, datetime.now(timezone.utc))


@pytest.mark.parametrize('field,value', [('synthetic', False), ('identifier', 'a' * 32),
    ('worker_sha256', '0' * 64), ('sources', {}), ('schema', 'unknown')])
def test_recipe_tamper_blocks(prepared: tuple[Path, Path], field: str, value: Any) -> None:
    old, root = prepared
    recipe = json.loads((root / 'recipe.json').read_text())
    recipe[field] = value
    (root / 'recipe.json').write_text(json.dumps(recipe))
    with pytest.raises(ValueError, match='RECIPE_CONSISTENCY_FAILED'):
        audit.review(old, root, audit.REVIEWED_ID, datetime.now(timezone.utc))


@pytest.mark.parametrize('extra', ['controller-attempt.json', 'attempt.json', 'task-witness.json',
                                   'owner-ack.json', 'reports', 'unknown'])
def test_any_extra_state_blocks_closure_review(prepared: tuple[Path, Path], extra: str) -> None:
    old, root = prepared
    (root / extra).write_text('synthetic fixture')
    with pytest.raises(ValueError, match='EXTRA_STATE_OR_EXECUTION_WITNESS_REVIEW_REQUIRED'):
        audit.review(old, root, audit.REVIEWED_ID, datetime.now(timezone.utc))


def test_duplicate_json_and_future_recipe_block(prepared: tuple[Path, Path]) -> None:
    old, root = prepared
    raw = (root / 'recipe.json').read_text()
    (root / 'recipe.json').write_text(raw[:-1] + ',"synthetic": true}')
    with pytest.raises(ValueError, match='DUPLICATE_RECIPE_KEY'):
        audit.review(old, root, audit.REVIEWED_ID, datetime.now(timezone.utc))
    (root / 'recipe.json').write_text(raw.replace('2026-10-17', '2099-10-17'))
    with pytest.raises(ValueError, match='RECIPE_DATE_REVIEW_REQUIRED'):
        audit.review(old, root, audit.REVIEWED_ID, datetime.now(timezone.utc))


def test_bounded_read_and_permission_uncertainty_fail_closed(prepared: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    old, root = prepared
    (root / 'recipe.json').write_bytes(b' ' * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match='BOUNDED_REGULAR_FILE_REQUIRED'):
        audit.review(old, root, audit.REVIEWED_ID, datetime.now(timezone.utc))
    def denied(path: Path) -> bytes:
        raise PermissionError('PRIVATE_PATH_NOT_PRINTED')
    monkeypatch.setattr(audit, 'read', denied)
    with pytest.raises(PermissionError):
        audit.review(old, root, audit.REVIEWED_ID, datetime.now(timezone.utc))


def test_link_rejected_before_recipe_read(prepared: tuple[Path, Path]) -> None:
    old, root = prepared
    alias = root.parent / 'alias'
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip('Windows symlink privilege unavailable; Linux covers link rejection')
    with pytest.raises(ValueError, match='LINK_REJECTED'):
        audit.review(old, alias, audit.REVIEWED_ID, datetime.now(timezone.utc))


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
def test_ps_preview_and_parse_never_query_or_write(shell: str) -> None:
    executable = shutil.which(shell)
    if not executable:
        pytest.skip('PowerShell executable unavailable')
    result = subprocess.run([executable, '-NoProfile', '-File', 'preserved_drill_audit.ps1'],
                            check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == dict(status='PREVIEW', reads=0, task_queries=0,
                                           task_mutations=0, operational_writes=0)


def test_controller_cannot_start_register_enable_or_read_capture() -> None:
    source = Path('preserved_drill_audit.ps1').read_text()
    for forbidden in ('Start-ScheduledTask', 'Enable-ScheduledTask', 'Register-ScheduledTask',
                      'Set-Content', 'WriteAllText', 'forward_daily_owner', '--mode worker'):
        assert forbidden not in source
    assert r"Get-ScheduledTask -TaskPath '\' -TaskName ('ResearchOps-SyntheticAlert-'+$id)" in source
    assert audit.REVIEWED_ID in source
    assert 'run_authorised=$false' in source


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
@pytest.mark.parametrize('case', ['historical', 'child_failure', 'malformed_child', 'missing_flags',
    'zero_tasks', 'two_tasks', 'wrong_command', 'wrong_arguments', 'wrong_directory',
    'wrong_user', 'highest', 'service_logon', 'trigger', 'restart', 'wake', 'catchup',
    'wrong_limit', 'wrong_instances', 'enabled', 'untyped_enabled'])
def test_real_confirmed_controller_with_fake_child_and_scheduler(shell: str, case: str) -> None:
    executable = shutil.which(shell)
    if not executable:
        pytest.skip('PowerShell executable unavailable')
    script = r'''
$ErrorActionPreference='Stop';$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'preserved_drill_audit.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count -ne 0) {throw 'PARSE_FAILED'}
$node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Invoke-PreservedAudit'},$true)
Invoke-Expression $node.Extent.Text
$script:queries=0;$script:bindingFailures=@()
$old=Join-Path ([IO.Path]::GetTempPath()) 'SyntheticOld';$python='SyntheticPython'
$runner={param([string[]]$Arguments)
 if ('CASE' -ceq 'child_failure') {return @{exit_code=2;output='PRIVATE_CHILD_EXCEPTION'}}
 if ('CASE' -ceq 'malformed_child') {return @{exit_code=0;output='not json'}}
 if ('CASE' -ceq 'missing_flags') {return @{exit_code=0;output='{"status":"PRESERVED_RECIPE_AND_SOURCES_CONSISTENT_NOT_RUN_ADMISSION"}'}}
 @{exit_code=0;output='{"status":"PRESERVED_RECIPE_AND_SOURCES_CONSISTENT_NOT_RUN_ADMISSION","source_integrity":true,"recipe_consistency":true,"run_authorised":false,"replacement_id_authorised":false,"recipe_authenticated":false,"same_ist_day":false,"historical_recipe":true}'}
}
function Get-ScheduledTask {param($TaskPath,$TaskName,$ErrorAction)
 $script:queries++
 if ($TaskPath -cne '\' -or $TaskName -cne 'ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697') {throw 'PRIVATE_WRONG_QUERY'}
 if ('CASE' -ceq 'zero_tasks') {return}
 $a=Drill-Arguments (Join-Path $old 'isolated_alert_drill.py') '389daf12415a482eb0231443ddfd8697'
 $task=[pscustomobject]@{State='Disabled';Actions=@([pscustomobject]@{Execute=$python;Arguments=$a;WorkingDirectory=$old});Triggers=@();
 Principal=[pscustomobject]@{UserId='S-1-5-21-1-2-3-1001';RunLevel='Limited';LogonType='Interactive'};
 Settings=[pscustomobject]@{Enabled=$false;RestartCount=0;ExecutionTimeLimit='PT2M';MultipleInstances='IgnoreNew';WakeToRun=$false;StartWhenAvailable=$false}}
 switch ('CASE') {
 'wrong_command' {$task.Actions[0].Execute='WRONG'}
 'wrong_arguments' {$task.Actions[0].Arguments='WRONG'}
 'wrong_directory' {$task.Actions[0].WorkingDirectory='WRONG'}
 'wrong_user' {$task.Principal.UserId='S-1-5-21-1-2-3-1002'}
 'highest' {$task.Principal.RunLevel='Highest'}
 'service_logon' {$task.Principal.LogonType='ServiceAccount'}
 'trigger' {$task.Triggers=@([pscustomobject]@{Enabled=$false})}
 'restart' {$task.Settings.RestartCount=1}
 'wake' {$task.Settings.WakeToRun=$true}
 'catchup' {$task.Settings.StartWhenAvailable=$true}
 'wrong_limit' {$task.Settings.ExecutionTimeLimit='PT3M'}
 'wrong_instances' {$task.Settings.MultipleInstances='Parallel'}
 'enabled' {$task.Settings.Enabled=$true;$task.State='Ready'}
 'untyped_enabled' {$task.Settings.Enabled='false'}
 }
 if ('CASE' -ceq 'two_tasks') {return @($task,$task)}
 return $task
}
$identity=[pscustomobject]@{User=[pscustomobject]@{Value='S-1-5-21-1-2-3-1001'};Name='SYNTHETIC'}
$blocked=$false;$result=$null;$reason=$null
try {$result=Invoke-PreservedAudit $old $python $identity $PWD.ProviderPath $runner}
catch {$blocked=$true;$reason=if ($_.Exception.Message -in @('SOURCE_OR_RECIPE_REVIEW_BLOCKED','EXACT_TASK_NOT_ESTABLISHED','DISABLED_TASK_NOT_PROVEN','ISOLATED_TASK_BINDING_REVIEW_REQUIRED')) {$_.Exception.Message} else {'REDACTED'}}
@{blocked=$blocked;reason=$reason;fields=@($script:bindingFailures);result=$result;windows=([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT);queries=$script:queries}|ConvertTo-Json -Compress -Depth 6
'''.replace('CASE', case)
    output = subprocess.run([executable, '-NoProfile', '-Command', script],
                            check=True, capture_output=True, text=True)
    result = json.loads(output.stdout)
    assert result['queries'] == (0 if case in ('child_failure', 'malformed_child', 'missing_flags') else 1)
    assert result['blocked'] is (case != 'historical' or not result['windows'])
    expected_fields = {'wrong_command': 'command', 'wrong_arguments': 'arguments', 'wrong_directory': 'working_directory',
        'wrong_user': 'current_user', 'highest': 'run_level', 'service_logon': 'logon_type', 'trigger': 'trigger_count',
        'restart': 'no_restart', 'wake': 'no_wake', 'catchup': 'no_catchup', 'wrong_limit': 'execution_limit',
        'wrong_instances': 'multiple_instances'}
    if case in expected_fields:
        assert expected_fields[case] in result['fields']
    if not result['blocked']:
        assert result['result']['historical_recipe'] is True
        assert result['result']['run_authorised'] is False
    assert 'PRIVATE_' not in output.stdout
