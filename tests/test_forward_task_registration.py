"""Execute the real registration helper with mocked cmdlets, never real tasks."""
from datetime import date
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from forward_nifty_schedule import task_xml


ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which('powershell') or shutil.which('pwsh')


@pytest.mark.parametrize('scenario,success,calls', [
    ('success', True, 3), ('fail', False, 1), ('fail_second', False, 2),
    ('missing', False, 1), ('enabled', False, 1), ('existing', False, 0),
    ('invalid_plan', False, 0), ('bad_declaration', False, 0),
    ('malformed_xml', False, 0), ('missing_disabled', False, 0),
])
def test_real_helper_encoding_and_fail_closed(scenario, success, calls, tmp_path):
    if SHELL is None:
        pytest.skip('PowerShell runtime required for mocked installer execution')
    plans = tmp_path / 'plans'
    plans.mkdir()
    before = {}
    for mode in ('prepare', 'poll', 'audit'):
        xml = task_xml(mode, tmp_path / 'private', date(2026, 10, 6), 'S-1-5-21-1001')
        if scenario == 'invalid_plan' and mode == 'audit':
            xml = xml.replace('<Enabled>false</Enabled>', '<Enabled>true</Enabled>')
        if scenario == 'bad_declaration' and mode == 'audit':
            xml = xml.replace('encoding="UTF-8"', 'encoding="UTF-16"')
        if scenario == 'malformed_xml' and mode == 'audit':
            xml = xml.replace('</Task>', '')
        if scenario == 'missing_disabled' and mode == 'audit':
            xml = xml.replace('<Enabled>false</Enabled>', '')
        path = plans / (mode + '.xml')
        path.write_text(xml, encoding='utf-8')
        before[path] = path.read_bytes()
    wrapper = tmp_path / 'mock-install.ps1'
    wrapper.write_text(r'''
$ErrorActionPreference = 'Stop'
$script:calls = 0
$script:registered = @{}
function Get-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName)
    if ($env:TEST_SCENARIO -eq 'existing') { return [pscustomobject]@{ State = 'Disabled' } }
    if ($script:registered.ContainsKey($TaskName)) {
        if ($env:TEST_SCENARIO -eq 'missing') { return }
        $state = if ($env:TEST_SCENARIO -eq 'enabled') { 'Ready' } else { 'Disabled' }
        return [pscustomobject]@{ State = $state }
    }
}
function Register-ScheduledTask {
    [CmdletBinding()] param([string]$TaskName, [string]$Xml)
    $script:calls++
    if ($Xml -match 'encoding=') { throw 'Encoding declaration reached COM' }
    $document = New-Object System.Xml.XmlDocument
    $document.LoadXml($Xml)
    if ($env:TEST_SCENARIO -eq 'fail' -or
        ($env:TEST_SCENARIO -eq 'fail_second' -and $script:calls -eq 2)) {
        Write-Error 'Synthetic registration error'
        return
    }
    $script:registered[$TaskName] = $true
}
. $env:TEST_HELPER
try {
    Register-ForwardTaskPlans -PlansDirectory $env:TEST_PLANS
    Write-Output 'TEST_SUCCESS'
} catch {
    Write-Output 'TEST_BLOCKED'
}
Write-Output "CALLS=$script:calls"
''', encoding='utf-8')
    env = dict(os.environ, TEST_HELPER=str(ROOT / 'scripts' / 'forward_task_registration.ps1'),
               TEST_PLANS=str(plans), TEST_SCENARIO=scenario)
    result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-File', str(wrapper)],
                            env=env, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert ('TEST_SUCCESS' in result.stdout) is success
    assert ('Three tasks registered DISABLED' in result.stdout) is success
    assert f'CALLS={calls}' in result.stdout
    assert all(path.read_bytes() == original for path, original in before.items())


def test_installer_calls_verified_helper_without_enabling_or_overwriting():
    source = (ROOT / 'scripts' / 'install_forward_tasks.ps1').read_text(encoding='utf-8')
    assert source.index('--verify-task-plans') < source.index('Register-ForwardTaskPlans')
    assert "'forward_task_registration.ps1'" in source
    assert 'Enable-ScheduledTask' not in source and '-Force' not in source
