"""Synthetic identity representations only; never inspect native tasks/state."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
@pytest.mark.parametrize('case,proof,accepted', [
    ('sid', 'SID_EQUAL', True), ('qualified_alias', 'SID_EQUAL', True),
    ('other_user', 'SID_MISMATCH', False), ('unresolved', 'UNRESOLVED', False),
    ('empty', 'UNRESOLVED', False),
])
def test_sid_comparison_requires_resolved_exact_identity(shell: str, case: str, proof: str, accepted: bool) -> None:
    executable = shutil.which(shell)
    if not executable:
        pytest.skip('Windows PowerShell runtime unavailable')
    script = r'''
$ErrorActionPreference='Stop';$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'isolated_alert_task_drill.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count -ne 0) {throw 'PARSE'}
$node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Test-DrillCurrentUser'},$true)
Invoke-Expression $node.Extent.Text
function Resolve-DrillAccountSid {param($Account)
 switch -CaseSensitive ($Account) {
  'EXPECTED' {return 'SYNTHETIC_CURRENT_SID'}
  'sid' {return 'SYNTHETIC_CURRENT_SID'}
  'qualified_alias' {return 'SYNTHETIC_CURRENT_SID'}
  'other_user' {return 'SYNTHETIC_OTHER_SID'}
  default {throw 'PRIVATE_EXCEPTION_MUST_NOT_ESCAPE'}
 }
}
$account=if ('CASE' -ceq 'empty') {''} else {'CASE'}
$ok=Test-DrillCurrentUser $account 'EXPECTED'
@{accepted=$ok;proof=$script:identityProof}|ConvertTo-Json -Compress
'''.replace('CASE', case)
    output = subprocess.run([executable, '-NoProfile', '-Command', script], capture_output=True, text=True, check=True)
    assert json.loads(output.stdout) == {'accepted': accepted, 'proof': proof}
    assert 'PRIVATE_EXCEPTION' not in output.stdout


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
def test_reconciliation_preview_has_no_side_effects(shell: str) -> None:
    executable = shutil.which(shell)
    if not executable:
        pytest.skip('Windows PowerShell runtime unavailable')
    output = subprocess.run([executable, '-NoProfile', '-File', 'isolated_alert_reconcile.ps1'],
                            capture_output=True, text=True, check=True)
    assert json.loads(output.stdout) == dict(status='PREVIEW', task_queries=0, operational_writes=0,
                                           credential_reads=0, task_mutations=0)


def test_reconciliation_is_exact_bounded_metadata_only() -> None:
    source = Path('isolated_alert_reconcile.ps1').read_text()
    assert "-TaskName ('ResearchOps-SyntheticAlert-'+$DrillId)" in source
    assert source.count('Get-ScheduledTask ') == 1
    for forbidden in ('Get-Content', 'Export-ScheduledTask', 'Enable-ScheduledTask',
                      'Register-ScheduledTask', 'Remove-Item', 'Set-Content', 'forward_daily_owner'):
        assert forbidden not in source
    assert 'retry_authorised=$false' in source
    assert 'LINKED_STATE_REQUIRES_REVIEW' in source


@pytest.mark.parametrize('shell', ['powershell', 'pwsh'])
@pytest.mark.parametrize('case', ['present', 'query_failure', 'denied', 'linked_ancestor', 'linked_file'])
def test_confirmed_reconciliation_with_fake_native_metadata(shell: str, case: str) -> None:
    executable = shutil.which(shell)
    if not executable:
        pytest.skip('Windows PowerShell runtime unavailable')
    script = r'''
$ErrorActionPreference='Stop';$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'isolated_alert_reconcile.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count -ne 0) {throw 'PARSE'}
$node=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq 'Invoke-IsolatedReadOnlyReconciliation'},$true)
Invoke-Expression $node.Extent.Text
$script:queries=0
function Get-ScheduledTask {param($TaskPath,$TaskName,$ErrorAction)
 $script:queries++
 if ($TaskPath -cne '\' -or $TaskName -cne ('ResearchOps-SyntheticAlert-'+('a'*32))) {throw 'WRONG_QUERY'}
 if ('CASE' -ceq 'query_failure') {throw 'PRIVATE_QUERY_EXCEPTION'}
 [pscustomobject]@{Settings=[pscustomobject]@{Enabled=$false};State='Disabled';Triggers=$null;
 Principal=[pscustomobject]@{UserId='S-1-5-21-1-2-3-1001'}}
}
function Test-Path {param($LiteralPath,$PathType) return ($LiteralPath -notlike '*attempt.json' -and $LiteralPath -notlike '*witness.json' -and $LiteralPath -notlike '*ack.json')}
function Get-Item {param($LiteralPath,[switch]$Force,$ErrorAction)
 if ('CASE' -ceq 'denied') {throw 'PRIVATE_DENIED_EXCEPTION'}
 $link=('CASE' -ceq 'linked_ancestor' -and $LiteralPath -notlike '*.json') -or ('CASE' -ceq 'linked_file' -and $LiteralPath -like '*recipe.json')
 [pscustomobject]@{Attributes=$(if($link){[IO.FileAttributes]::ReparsePoint}else{[IO.FileAttributes]::Normal});PSIsContainer=$false}
}
$identity=[pscustomobject]@{User=[pscustomobject]@{Value='S-1-5-21-1-2-3-1001'};Name='SYNTHETIC'}
$blocked=$false;$result=$null
try {$result=Invoke-IsolatedReadOnlyReconciliation ('a'*32) $identity (Join-Path ([IO.Path]::GetTempPath()) 'SyntheticLocal') $PWD.ProviderPath}
catch {$blocked=$true}
@{blocked=$blocked;queries=$script:queries;result=$result;sid_api_available=([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT)}|ConvertTo-Json -Compress -Depth 6
'''.replace('CASE', case)
    output = subprocess.run([executable, '-NoProfile', '-Command', script], capture_output=True, text=True, check=True)
    result = json.loads(output.stdout)
    assert result['queries'] == 1
    assert result['blocked'] is (case != 'present')
    if case == 'present':
        assert result['result']['current_user_sid_equal'] is result['sid_api_available']
        assert result['result']['identity_proof'] == ('SID_EQUAL' if result['sid_api_available'] else 'UNRESOLVED')
        assert result['result']['task_disabled'] is True
        assert result['result']['files']['recipe.json'] is True
        assert result['result']['files']['attempt.json'] is False
        assert result['result']['retry_authorised'] is False
    assert 'PRIVATE_' not in output.stdout
