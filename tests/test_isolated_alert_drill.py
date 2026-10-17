from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pytest

import isolated_alert_drill as drill

ID = 'a'*32
NOW = datetime.fromisoformat('2026-10-17T10:30:00+00:00')


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    drill.setup(ID, NOW)
    root = drill.root_for(ID)
    drill.write_new(root / 'controller-attempt.json', dict(identifier=ID, retry_allowed=False, at=NOW.isoformat()))
    return root


def witness(root: Path, **changes: Any) -> None:
    item = dict(identifier=ID, binding_verified=True, disabled_verified=True, last_result=2)
    item.update(changes)
    drill.write_new(root / 'task-witness.json', item)


def test_preview_no_io(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fail(*args: object) -> Path:
        raise AssertionError('IO forbidden')
    monkeypatch.setattr(drill, 'root_for', fail)
    assert drill.main(['--drill-id', 'notvalidatedyet']) == 0
    assert json.loads(capsys.readouterr().out)['reads'] == 0


def test_real_pinned_failure_route_marker_launch_inspection_and_human_ack(state: Path) -> None:
    categories: list[str] = []
    def fake_notify(category: str) -> bool:
        categories.append(category); return True
    result = drill.worker(ID, NOW, fake_notify)
    assert result['status'] == 'SYNTHETIC_FAILURE_ROUTED_EXPECTED_EXIT_2'
    assert categories == ['SYNTHETIC_KKKKKKKK_CLOCK_REVIEW_REQUIRED']
    witness(state)
    checked = drill.inspect(ID, NOW)
    assert checked['popup_seen'] is None and checked['production_failure_verified'] is False
    ack = drill.acknowledge(ID, NOW, 'kkkkkkkk')
    assert ack['status'] == 'ISOLATED_FAILURE_ROUTE_OWNER_ACKNOWLEDGED'
    assert ack['independent_delivery_verified'] is ack['training_eligible'] is False
    assert drill.inspect(ID, NOW)['status'] == 'ISOLATED_FAILURE_ROUTE_ACK_RECORDED'
    with pytest.raises(FileExistsError): drill.acknowledge(ID, NOW, 'kkkkkkkk')


def test_wrong_popup_code_cannot_create_owner_ack(state: Path) -> None:
    drill.worker(ID, NOW, lambda category: True)
    witness(state)
    with pytest.raises(ValueError, match='HUMAN_SYNTHETIC_CODE_MISMATCH'):
        drill.acknowledge(ID, NOW, 'aaaaaaaa')
    assert not (state / 'owner-ack.json').exists()


def test_worker_no_retry_and_no_existing_state_overwrite(state: Path) -> None:
    drill.worker(ID, NOW, lambda category: True)
    before = (state / 'attempt.json').read_bytes()
    with pytest.raises(FileExistsError): drill.worker(ID, NOW, lambda category: True)
    assert (state / 'attempt.json').read_bytes() == before
    with pytest.raises(FileExistsError): drill.setup(ID, NOW)


def test_production_dedup_function_does_not_repeat_launched_notification(state: Path) -> None:
    functions = drill.load_functions()
    calls: list[str] = []
    def fake(category: str) -> bool:
        calls.append(category); return True
    functions['notify'] = fake
    for _ in range(2):
        functions['save'](state / 'isolated-extra', NOW.date(),
                          {'status': 'BLOCKED', 'code': 'CLOCK_UNVERIFIED'}, visible=True)
    assert calls == ['CLOCK_REVIEW_REQUIRED']


@pytest.mark.parametrize('changes', [dict(last_result=0), dict(last_result=True),
    dict(disabled_verified=False), dict(binding_verified=False), dict(identifier='b'*32)])
def test_bad_task_witness_cannot_acknowledge(state: Path, changes: dict[str, Any]) -> None:
    drill.worker(ID, NOW, lambda category: True)
    witness(state, **changes)
    with pytest.raises(ValueError): drill.inspect(ID, NOW)
    assert not (state / 'owner-ack.json').exists()


def test_launch_failure_or_absent_task_witness_never_seen(state: Path) -> None:
    drill.worker(ID, NOW, lambda category: False)
    witness(state)
    with pytest.raises(ValueError): drill.inspect(ID, NOW)


@pytest.mark.parametrize('artifact', ['controller-attempt.json', 'attempt.json', 'alert'])
def test_attempt_and_alert_records_cannot_be_absent_or_corrupt(state: Path, artifact: str) -> None:
    drill.worker(ID, NOW, lambda category: True)
    witness(state)
    path = next((state / 'reports').glob('*.alert')) if artifact == 'alert' else state / artifact
    path.write_bytes(b'{}')
    with pytest.raises(ValueError): drill.inspect(ID, NOW)


def test_naive_time_not_interpreted_in_host_timezone() -> None:
    with pytest.raises(ValueError, match='AWARE_TIME_REQUIRED'):
        drill.allowed(datetime(2026, 10, 17))


def test_source_pin_is_checked_before_function_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(drill.SOURCES, 'forward_ops_host.py', '0'*64)
    with pytest.raises(ValueError, match='REVIEWED_SOURCE_PIN_MISMATCH'): drill.load_functions()


@pytest.mark.parametrize('at,accepted', [('2026-10-19T03:00:00Z', False),
    ('2026-10-19T10:30:00Z', True), ('2026-10-17T01:00:00Z', True)])
def test_no_weekday_market_hours_drill(at: str, accepted: bool) -> None:
    assert drill.allowed(datetime.fromisoformat(at)) is accepted


def test_invalid_id_never_selects_capture_root() -> None:
    for value in ('..', 'Forward', 'a'*31, 'A'*32, 'a'*32+'/state'):
        with pytest.raises(ValueError): drill.root_for(value)


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
@pytest.mark.parametrize('scenario', ['success', 'start_unknown', 'bad_binding', 'already_attempted'])
def test_real_controller_block_and_finally_with_fake_native_commands(shell: str, scenario: str) -> None:
    executable = shutil.which(shell)
    if not executable: pytest.skip('PowerShell runtime absent on this platform')
    script = r'''
$ErrorActionPreference='Stop';$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'isolated_alert_task_drill.ps1'),[ref]$tokens,[ref]$errors)
foreach ($name in @('Invoke-IsolatedDrillRun','Assert-DrillTask','Test-DrillCurrentUser')) {
 $node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
 Invoke-Expression $node.Extent.Text
}
$outer=@($ast.EndBlock.Statements | Where-Object {$_ -is [Management.Automation.Language.TryStatementAst]})[0]
$cleanupText=$outer.Finally.Extent.Text
$cleanup=[scriptblock]::Create($cleanupText.Substring(1,$cleanupText.Length-2))
$script:events=[Collections.Generic.List[string]]::new();$script:enabled=$false;$script:worker=$false
$script:controller=('SCENARIO' -ceq 'already_attempted');$script:attemptedEnable=$false;$script:disabledVerified=$false
$script:taskName='SYNTHETIC';$script:blocked=$false
function Resolve-DrillAccountSid {param($Account) if ($Account -ceq 'SID') {return 'SYNTHETIC_SID'};throw 'UNRESOLVED'}
function SyntheticPython {$global:LASTEXITCODE=0;return '{"status":"ISOLATED_DRILL_PREREQUISITES_CHECK_PASSED"}'}
function Get-ScheduledTask {
 param($TaskPath,$TaskName,$ErrorAction)
 $level=if ('SCENARIO' -ceq 'bad_binding') {'Highest'} else {'Limited'}
 [pscustomobject]@{State=$(if($script:enabled){'Ready'}else{'Disabled'});
  Actions=@([pscustomobject]@{Execute='SyntheticPython';Arguments='ARGS';WorkingDirectory='DIR'});Triggers=$null;
  Principal=[pscustomobject]@{RunLevel=$level;LogonType='Interactive';UserId='SID'};
  Settings=[pscustomobject]@{RestartCount=0;Enabled=$script:enabled;MultipleInstances='IgnoreNew';ExecutionTimeLimit='PT120S';StartWhenAvailable=$false;WakeToRun=$false}}
}
function Test-Path {param($LiteralPath)
 if ($LiteralPath -like '*controller-attempt.json') {return $script:controller}
 if ($LiteralPath -like '*attempt.json') {return $script:worker}; return $false
}
function Write-DrillWitness {param($Path,$Value)
 if ($Path -like '*controller-attempt.json') {$script:events.Add('marker');$script:controller=$true}
 else {$script:events.Add('witness')}
}
function Enable-ScheduledTask {param($TaskPath,$TaskName,$ErrorAction) $script:events.Add('enable');$script:enabled=$true}
function Start-ScheduledTask {param($TaskPath,$TaskName,$ErrorAction)
 $script:events.Add('start');if ('SCENARIO' -ceq 'start_unknown') {throw 'SIMULATED_UNKNOWN'};$script:worker=$true
}
function Get-ScheduledTaskInfo {param($TaskPath,$TaskName,$ErrorAction) [pscustomobject]@{LastTaskResult=2}}
function Disable-ScheduledTask {param($TaskPath,$TaskName,$ErrorAction) $script:events.Add('disable');$script:enabled=$false}
function Start-Sleep {param($Seconds)}
try {Invoke-IsolatedDrillRun 'SYNTHETIC' 'SyntheticPython' 'WORKER' 'ARGS' 'DIR' 'SID' 'USER' 'ROOT' ('a'*32)}
catch {$script:blocked=$true}
finally {& $cleanup}
@{events=@($script:events.ToArray());blocked=$script:blocked;enabled=$script:enabled;disabled_proven=$script:disabledVerified}|ConvertTo-Json -Compress
'''.replace('SCENARIO', scenario)
    output = subprocess.run([executable, '-NoProfile', '-Command', script], capture_output=True, text=True, check=True)
    result = json.loads(output.stdout)
    expected = {'success': ['marker', 'enable', 'start', 'disable', 'witness'],
                'start_unknown': ['marker', 'enable', 'start', 'disable'],
                'bad_binding': [], 'already_attempted': []}
    assert result['events'] == expected[scenario]
    assert result['enabled'] is False
    assert result['blocked'] is (scenario != 'success')


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
def test_ps_preview_and_real_ast_binding_contract(shell: str) -> None:
    executable = shutil.which(shell)
    if not executable: pytest.skip('PowerShell runtime absent on this platform')
    output = subprocess.run([executable, '-NoProfile', '-File', 'isolated_alert_task_drill.ps1',
                             '-Action', 'Setup'], capture_output=True, text=True, check=True)
    assert json.loads(output.stdout)['task_mutations'] == 0
    script = r'''
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'isolated_alert_task_drill.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count -ne 0) {throw 'PARSE_FAILED'}
foreach ($name in @('Drill-Arguments','Assert-DrillTask','Assert-DrillWindow','Test-DrillCurrentUser')) {
  $node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true)
  Invoke-Expression $node.Extent.Text
}
function Resolve-DrillAccountSid {param($Account) if ($Account -ceq 'SID') {return 'SYNTHETIC_SID'};throw 'UNRESOLVED'}
$argsText=Drill-Arguments 'C:\Reviewed Tools\isolated_alert_drill.py' ('a'*32)
$task=[pscustomobject]@{Actions=@([pscustomobject]@{Execute='PYTHON';Arguments=$argsText;WorkingDirectory='DIR'});
 Triggers=@();Principal=[pscustomobject]@{RunLevel='Limited';LogonType='Interactive';UserId='SID'};
 Settings=[pscustomobject]@{RestartCount=0;MultipleInstances='IgnoreNew';ExecutionTimeLimit='PT2M';StartWhenAvailable=$false;WakeToRun=$false}}
Assert-DrillTask $task 'PYTHON' $argsText 'DIR' 'SID' 'USER'
$task.Principal.RunLevel='Highest';$blocked=$false
try {Assert-DrillTask $task 'PYTHON' $argsText 'DIR' 'SID' 'USER'} catch {$blocked=$true}
if (-not $blocked) {throw 'PRIVILEGE_GATE_FAILED'}
if ('run_level' -notin $script:bindingFailures) {throw 'REDACTED_FIELD_DIAGNOSTIC_MISSING'}
$task.Principal.RunLevel='Limited';$task.Settings.RestartCount=1;$blocked=$false
try {Assert-DrillTask $task 'PYTHON' $argsText 'DIR' 'SID' 'USER'} catch {$blocked=$true}
if (-not $blocked) {throw 'RESTART_GATE_FAILED'}
if ('no_restart' -notin $script:bindingFailures) {throw 'RESTART_FIELD_DIAGNOSTIC_MISSING'}
@{status='SYNTHETIC_AST_BINDING_TEST_PASSED';native_tasks_touched=0}|ConvertTo-Json -Compress
'''
    output = subprocess.run([executable, '-NoProfile', '-Command', script], capture_output=True, text=True, check=True)
    assert json.loads(output.stdout)['native_tasks_touched'] == 0


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
def test_clean_tools_guard_uses_real_synthetic_git_not_owner_checkout(tmp_path: Path, shell: str) -> None:
    executable = shutil.which(shell)
    if not executable or not shutil.which('git'):
        pytest.skip('Required shell/Git runtime absent on this platform')
    def git(*args: str) -> None:
        subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True)
    git('init'); git('config', 'user.name', 'Synthetic fixture')
    git('config', 'user.email', 'synthetic@example.invalid')
    for name in ('isolated_alert_drill.py', 'isolated_alert_task_drill.ps1', 'PROGRAMME_NEXT_UPLOAD_2026-10-17.json'):
        (tmp_path / name).write_bytes(b'synthetic only')
    git('add', '.'); git('commit', '-m', 'Synthetic clean fixture')
    escaped = str(tmp_path).replace("'", "''")
    script = r'''
$ErrorActionPreference='Stop';$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'isolated_alert_task_drill.ps1'),[ref]$tokens,[ref]$errors)
$node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Assert-DrillTools'},$true)
Invoke-Expression $node.Extent.Text
Assert-DrillTools 'SYNTHETIC_ROOT'
[IO.File]::WriteAllText((Join-Path 'SYNTHETIC_ROOT' 'isolated_alert_drill.py'),'changed synthetic fixture')
$blocked=$false
try {Assert-DrillTools 'SYNTHETIC_ROOT'} catch {$blocked=($_.Exception.Message -ceq 'REVIEWED_CLEAN_TOOLS_ROOT_REQUIRED')}
@{clean_passed=$true;dirty_blocked=$blocked;native_tasks_touched=0}|ConvertTo-Json -Compress
'''.replace('SYNTHETIC_ROOT', escaped)
    output = subprocess.run([executable, '-NoProfile', '-Command', script], capture_output=True, text=True, check=True)
    assert json.loads(output.stdout) == dict(clean_passed=True, dirty_blocked=True, native_tasks_touched=0)
