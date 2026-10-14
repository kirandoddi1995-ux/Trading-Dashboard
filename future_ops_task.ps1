param(
    [string]$PythonExecutable,
    [string]$SessionDate,
    [ValidateSet(0,1,2)][int]$SyntheticExit = 0,
    [switch]$AllowRehearsal,
    [switch]$NotifyLocal
)
# Separate FUTURE synthetic launcher. No capture paths or task/service mutations.
$ErrorActionPreference = 'Stop'
if (-not $AllowRehearsal) {
    Write-Output '{"status":"PREVIEW","code":"ZERO_IO_NO_CHECKS_PERFORMED"}'
    exit 0
}
try {
    if ($PythonExecutable -notmatch '^[A-Za-z]:[\\/]' -or
        -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) { throw 'PYTHON_REQUIRED' }
    $script = Join-Path $PSScriptRoot 'future_ops_diagnostics.py'
    $childArguments = @('-B', $script, '--mode', 'rehearsal', '--allow-rehearsal',
        '--session-date', $SessionDate, '--synthetic-exit', [string]$SyntheticExit)
    if ($NotifyLocal) { $childArguments += '--notify-local' }
    # Synchronous native invocation: parent waits, then explicitly propagates child status.
    & $PythonExecutable @childArguments
    $childExit = $LASTEXITCODE
    if ($null -eq $childExit) { throw 'CHILD_EXIT_UNKNOWN' }
    exit $childExit
} catch {
    Write-Output '{"status":"BLOCKED","code":"FUTURE_LAUNCHER_UNAVAILABLE","approval_authority":false}'
    exit 2
}
