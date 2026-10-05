# Owner-run only. Creates disabled tasks; never enables collection or stores passwords.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PrivateRoot,
    [Parameter(Mandatory = $true)][string]$StartDate,
    [switch]$RegisterTasks
)
$ErrorActionPreference = 'Stop'
if ([TimeZoneInfo]::Local.Id -ne 'India Standard Time') {
    throw 'Use an India Standard Time PC for this supervised task plan; no timezone was changed.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runner = Join-Path $projectRoot 'forward_nifty_schedule.py'
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Project Python environment is missing.' }
$names = @('KiranTrading-Forward-prepare', 'KiranTrading-Forward-poll', 'KiranTrading-Forward-audit')
foreach ($name in $names) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        throw "Existing task will not be replaced: $name"
    }
}
# Arguments are passed as data to Python, never assembled into a shell script.
if ($RegisterTasks) {
    & $python $runner --root $PrivateRoot --verify-task-plans --start-date $StartDate --owner-sid $ownerSid
} else {
    & $python $runner --root $PrivateRoot --write-task-plans --start-date $StartDate --owner-sid $ownerSid
}
if ($LASTEXITCODE -ne 0) { throw 'Task plan generation failed; nothing was registered.' }
if (-not $RegisterTasks) {
    Write-Output 'Disabled XML plans written privately. Review before explicitly registering.'
    return
}
. (Join-Path $PSScriptRoot 'forward_task_registration.ps1')
Register-ForwardTaskPlans -PlansDirectory (Join-Path $PrivateRoot 'task-plans')
