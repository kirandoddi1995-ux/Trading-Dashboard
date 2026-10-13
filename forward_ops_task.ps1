param(
    [Parameter(Mandatory=$true)][string]$PythonExecutable,
    [Parameter(Mandatory=$true)][string]$CodeDirectory,
    [Parameter(Mandatory=$true)][string]$StateRoot,
    [Parameter(Mandatory=$true)][string]$OpsRoot,
    [Parameter(Mandatory=$true)][string]$SessionDate,
    [Parameter(Mandatory=$true)][ValidateSet('poll','audit','preflight')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$PollTask,
    [Parameter(Mandatory=$true)][string]$AuditTask
)
# Owner-installed future date only. Never changes Windows time or task state.
$ErrorActionPreference = 'Stop'
try {
    foreach ($value in @($PythonExecutable,$CodeDirectory,$StateRoot,$OpsRoot,$SessionDate,$PollTask,$AuditTask)) {
        if ($value.Contains('"') -or $value.Contains("`r") -or $value.Contains("`n")) { throw 'INVALID_ARGUMENT' }
    }
    if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'EXECUTABLE_MISSING' }
    $launcher = Join-Path $CodeDirectory 'forward_session_ops.py'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw 'LAUNCHER_MISSING' }
    $arguments = '"' + $launcher + '" --root "' + $StateRoot + '" --ops-root "' + $OpsRoot +
        '" --session-date ' + $SessionDate + ' --mode ' + $Mode + ' --poll-task "' + $PollTask +
        '" --audit-task "' + $AuditTask + '" --confirm-ops --notify-local'
    $process = Start-Process -FilePath $PythonExecutable -ArgumentList $arguments -WorkingDirectory $CodeDirectory -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -notin @(0,1,2)) {
        Write-Output '{"status":"BLOCKED","code":"PROCESS_TERMINATED_COMMIT_UNKNOWN","local_poll_committed":null,"approval_authority":false}'
        try {
            Add-Type -AssemblyName System.Windows.Forms
            [void][System.Windows.Forms.MessageBox]::Show('Capture process terminated unexpectedly. Commit is UNKNOWN. Do not retry the slot or reset the journal; inspect read-only.', 'NIFTY capture alert')
        } catch { }
    }
    exit $process.ExitCode
} catch {
    # No raw paths/exception data. This notification is independent of Python starting.
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [void][System.Windows.Forms.MessageBox]::Show('Capture launcher could not start. Check reviewed task paths. No slot retried.', 'NIFTY capture alert')
    } catch { }
    Write-Output '{"status":"BLOCKED","code":"TASK_LAUNCHER_UNAVAILABLE","approval_authority":false}'
    exit 2
}
