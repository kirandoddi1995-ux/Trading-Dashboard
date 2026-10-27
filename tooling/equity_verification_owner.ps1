# Windows PowerShell 5.1 and PowerShell 7: invoke this file once with -File.
# Default: preview only. Confirmed Preflight requires -Root and -Python.
# Confirmed FullSuite additionally requires -Runner and a NEW external -Receipt.
# Root must be this script's own ordinary checkout. No production test hooks.
# Parse only this fixed data-only option list inside the protected block. A
# parameter binder would emit unredacted errors before a script-level catch.
$Action = 'Preview'
$ConfirmRun = $false
$Root = ''
$Python = ''
$Runner = ''
$Receipt = ''

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$launches = 0
$preflightVerified = $false
$stage = 'binder'
$runnerPin = '404eab045c32e37df3866b1337ab50ccf827eb4bbac56dd0983f55dc3865bc2d'
$expectedProbeSuccess = '{"approval_authority": false, "python_version": "3.13.9", "source_binding_verified": true, "stage": "temp", "status": "NATIVE_PREFLIGHT_VERIFIED", "synthetic_temp_write_read_cleanup": true}'

function Write-Result([string]$Status, [string]$Code) {
    [ordered]@{
        status = $Status
        code = $Code
        stage = $script:stage
        child_invocations = $script:launches
        preflight_verified = $script:preflightVerified
        approval_authority = $false
    } | ConvertTo-Json -Compress
}

function Safe-Path([string]$Value, [string]$Kind) {
    # Local absolute paths only; reject drive-relative, UNC, ADS and traversal.
    if ($Value -notmatch '^[A-Za-z]:[\\/]' -or $Value.Substring(2).Contains(':') -or
        @($Value -split '[\\/]' | Where-Object { $_ -ceq '..' -or $_ -ceq '.' }).Count -ne 0) {
        throw 'INVALID'
    }
    $full = [IO.Path]::GetFullPath($Value).TrimEnd('\', '/')
    $cursor = $full
    $first = $true
    while (-not [string]::IsNullOrEmpty($cursor)) {
        $exists = $true
        try { $attributes = [IO.File]::GetAttributes($cursor) }
        catch [IO.FileNotFoundException] { $exists = $false }
        catch [IO.DirectoryNotFoundException] { $exists = $false }
        if ($exists) {
            if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'INVALID' }
            $isDirectory = ($attributes -band [IO.FileAttributes]::Directory) -ne 0
            if ($first) {
                if ($Kind -ceq 'NewDirectory') { throw 'INVALID' }
                if (($Kind -ceq 'Directory') -ne $isDirectory) { throw 'INVALID' }
            } elseif (-not $isDirectory) { throw 'INVALID' }
        } elseif (-not ($first -and $Kind -ceq 'NewDirectory')) { throw 'INVALID' }
        $first = $false
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -ceq $cursor) { break }
        $cursor = $parent
    }
    return $full
}

function Is-Within([string]$Path, [string]$Directory) {
    return $Path.Equals($Directory, [StringComparison]::OrdinalIgnoreCase) -or
        $Path.StartsWith($Directory.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Runner-Hash([string]$Path) {
    # Use .NET directly: PS 5.1 module autoload need not expose Get-FileHash.
    $stream = [IO.File]::OpenRead($Path)
    $hasher = $null
    try {
        if ($stream.Length -gt 1048576) { throw 'INVALID' }
        $hasher = [Security.Cryptography.SHA256]::Create()
        return [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        if ($null -ne $hasher) { $hasher.Dispose() }
        $stream.Dispose()
    }
}

try {
    $options = @{}
    for ($i = 0; $i -lt $args.Count; $i++) {
        $option = [string]$args[$i]
        if ($options.ContainsKey($option)) { throw 'INVALID' }
        if ($option -ceq '-ConfirmRun') {
            $options[$option] = $true
        } elseif ($option -cin @('-Action', '-Root', '-Python', '-Runner', '-Receipt')) {
            $i++
            if ($i -ge $args.Count -or [string]::IsNullOrEmpty([string]$args[$i]) -or
                ([string]$args[$i]).StartsWith('-')) { throw 'INVALID' }
            $options[$option] = [string]$args[$i]
        } else { throw 'INVALID' }
    }
    if ($options.ContainsKey('-Action')) { $Action = $options['-Action'] }
    if ($options.ContainsKey('-ConfirmRun')) { $ConfirmRun = $true }
    if ($options.ContainsKey('-Root')) { $Root = $options['-Root'] }
    if ($options.ContainsKey('-Python')) { $Python = $options['-Python'] }
    if ($options.ContainsKey('-Runner')) { $Runner = $options['-Runner'] }
    if ($options.ContainsKey('-Receipt')) { $Receipt = $options['-Receipt'] }
    if ($Action -cnotin @('Preview', 'Preflight', 'FullSuite')) { throw 'INVALID' }
    if ($Action -ceq 'Preview') {
        Write-Result 'PREVIEW' 'NO_ACTION_PERFORMED'
        exit 0
    }
    if (-not $ConfirmRun) { throw 'INVALID' }
    $stage = 'sourcebinding'
    $ownScript = Safe-Path $PSCommandPath 'File'
    $ownRoot = Safe-Path ([IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($ownScript))) 'Directory'
    $checkedRoot = Safe-Path $Root 'Directory'
    if (-not $checkedRoot.Equals($ownRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'INVALID' }
    $checkedPython = Safe-Path $Python 'File'
    if ([IO.Path]::GetFileName($checkedPython) -ine 'python.exe') { throw 'INVALID' }
    $helper = Safe-Path (Join-Path $ownRoot 'tooling/equity_native_preflight.py') 'File'

    if ($Action -ceq 'FullSuite') {
        $stage = 'runnerbinding'
        $checkedRunner = Safe-Path $Runner 'File'
        $checkedReceipt = Safe-Path $Receipt 'NewDirectory'
        $pythonEnvironment = [IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($checkedPython))
        if ((Is-Within $checkedRunner $ownRoot) -or (Is-Within $checkedReceipt $ownRoot) -or
            (Is-Within $checkedReceipt $pythonEnvironment) -or
            [IO.Path]::GetExtension($checkedRunner) -ine '.py') { throw 'INVALID' }
        if ((Runner-Hash $checkedRunner) -cne $runnerPin) { throw 'INVALID' }
    } elseif ($Runner -cne '' -or $Receipt -cne '') { throw 'INVALID' }

    $stage = 'nativepreflight'
    $launches++
    $probeOutput = @(& $checkedPython -I -B $helper --root $checkedRoot 2>&1)
    $probeExit = $LASTEXITCODE
    if ($probeExit -ne 0 -or $probeOutput.Count -ne 1) { throw 'INVALID' }
    # Fixed wire protocol from our helper's json.dumps(sort_keys=True). Never
    # parse or trim it: duplicates, arrays and alternate representations fail.
    if (-not [string]::Equals([string]$probeOutput[0], $expectedProbeSuccess, [StringComparison]::Ordinal)) { throw 'INVALID' }
    $preflightVerified = $true

    if ($Action -ceq 'FullSuite') {
        # Recheck immediately before dispatch; do not create the receipt ourselves.
        $stage = 'runnerbinding'
        $checkedRunner = Safe-Path $checkedRunner 'File'
        $checkedReceipt = Safe-Path $checkedReceipt 'NewDirectory'
        if ((Runner-Hash $checkedRunner) -cne $runnerPin) { throw 'INVALID' }
        $stage = 'fullsuite'
        $launches++
        $runnerOutput = @(& $checkedPython -I -B $checkedRunner --root $checkedRoot --output $checkedReceipt 2>&1)
        if ($LASTEXITCODE -ne 0) { throw 'INVALID' }
        Write-Result 'FULL_SUITE_RUNNER_EXIT_ZERO_REVIEW_RECEIPT' 'RECEIPT_REVIEW_REQUIRED'
    } else {
        Write-Result 'PREFLIGHT_VERIFIED' 'NOT_FULL_SUITE_VERIFICATION'
    }
    exit 0
} catch {
    Write-Result 'BLOCKED' 'EQUITY_OWNER_VERIFICATION_FAILED'
    exit 2
}
