[CmdletBinding()]
param(
    [ValidateSet('Preview','Setup','Run','Inspect','Acknowledge')][string]$Action='Preview',
    [string]$DrillId='', [string]$Python='', [string]$SeenCode='',
    [switch]$ConfirmRun, [switch]$ConfirmNoCaptureRunning,
    [switch]$ConfirmNotificationSeen
)
$ErrorActionPreference='Stop'

function Assert-DrillWindow([datetime]$Now,[bool]$Idle) {
    if (-not $Idle -or ($Now.DayOfWeek -notin @('Saturday','Sunday') -and $Now.Hour -lt 16)) {
        throw 'POSTSESSION_OR_WEEKEND_AND_IDLE_REQUIRED'
    }
}

function Drill-Arguments([string]$Script,[string]$Id) {
    if ($Id -cnotmatch '^[a-f0-9]{32}$' -or $Script.Contains('"') -or $Script.Contains("`n") -or $Script.Contains("`r")) {
        throw 'DRILL_ARGUMENT_INVALID'
    }
    return '-I -B "' + $Script + '" --drill-id ' + $Id + ' --mode worker --confirm-drill-only'
}

function Assert-DrillTools([string]$Root) {
    $application=Get-Command git -CommandType Application -ErrorAction Stop|Select-Object -First 1
    $top=@(& $application.Source -C $Root rev-parse --show-toplevel 2>$null)
    if ($LASTEXITCODE -ne 0 -or ($top -join '').Trim().Replace('\','/').TrimEnd('/') -ine $Root.Replace('\','/').TrimEnd('/')) {
        throw 'REVIEWED_CLEAN_TOOLS_ROOT_REQUIRED'
    }
    $dirty=@(& $application.Source -C $Root status --porcelain --untracked-files=normal 2>$null)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {throw 'REVIEWED_CLEAN_TOOLS_ROOT_REQUIRED'}
    $null=& $application.Source -C $Root ls-files --error-unmatch -- isolated_alert_drill.py isolated_alert_task_drill.ps1 PROGRAMME_NEXT_UPLOAD_2026-10-17.json 2>$null
    if ($LASTEXITCODE -ne 0) {throw 'REVIEWED_TRACKED_DRILL_FILES_REQUIRED'}
}

function Resolve-DrillAccountSid([string]$Account) {
    if ([string]::IsNullOrWhiteSpace($Account) -or $Account.Length -gt 512) {throw 'ACCOUNT_IDENTITY_UNRESOLVED'}
    if ($Account -match '^S-') {
        return ([Security.Principal.SecurityIdentifier]::new($Account)).Value
    }
    return ([Security.Principal.NTAccount]::new($Account)).Translate([Security.Principal.SecurityIdentifier]).Value
}

function Test-DrillCurrentUser([string]$Account,[string]$Sid) {
    $script:identityProof='UNRESOLVED'
    try {
        $actual=Resolve-DrillAccountSid $Account
        $expected=Resolve-DrillAccountSid $Sid
        if ($actual -cne $expected) {$script:identityProof='SID_MISMATCH';return $false}
        $script:identityProof='SID_EQUAL';return $true
    } catch {return $false}
}

function Assert-DrillTask($Task,[string]$Exe,[string]$Arguments,[string]$Directory,[string]$Sid,[string]$User) {
    $actions=@($Task.Actions | Where-Object {$null -ne $_})
    $one=if ($actions.Count -eq 1) {$actions[0]} else {$null}
    $duration=$null
    try {$duration=[Xml.XmlConvert]::ToTimeSpan([string]$Task.Settings.ExecutionTimeLimit)} catch {}
    $restartCount=$Task.Settings.RestartCount
    $checks=[ordered]@{
        task_present=($null -ne $Task)
        action_count=($actions.Count -eq 1)
        trigger_count=(@($Task.Triggers | Where-Object {$null -ne $_}).Count -eq 0)
        command=([string]$one.Execute -ceq $Exe)
        arguments=([string]$one.Arguments -ceq $Arguments)
        working_directory=([string]$one.WorkingDirectory -ceq $Directory)
        run_level=([string]$Task.Principal.RunLevel -ceq 'Limited')
        logon_type=([string]$Task.Principal.LogonType -ceq 'Interactive')
        current_user=(Test-DrillCurrentUser ([string]$Task.Principal.UserId) $Sid)
        multiple_instances=([string]$Task.Settings.MultipleInstances -ceq 'IgnoreNew')
        execution_limit=($duration -eq [timespan]::FromMinutes(2))
        no_restart=(($restartCount -is [int32] -or $restartCount -is [uint32] -or $restartCount -is [int64]) -and $restartCount -eq 0)
        no_catchup=($Task.Settings.StartWhenAvailable -is [bool] -and $Task.Settings.StartWhenAvailable -eq $false)
        no_wake=($Task.Settings.WakeToRun -is [bool] -and $Task.Settings.WakeToRun -eq $false)
    }
    $script:bindingFailures=@($checks.Keys | Where-Object {-not $checks[$_]})
    if ($script:bindingFailures.Count -ne 0) {throw 'ISOLATED_TASK_BINDING_REVIEW_REQUIRED'}
}

function Write-DrillWitness([string]$Path,$Value) {
    $bytes=[Text.Encoding]::UTF8.GetBytes(($Value|ConvertTo-Json -Compress))
    $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)} finally {$stream.Dispose()}
}

function Invoke-IsolatedDrillRun([string]$TaskName,[string]$Python,[string]$Worker,[string]$Arguments,[string]$Directory,[string]$Sid,[string]$User,[string]$Root,[string]$DrillId) {
        $script:phase='ISOLATED_TASK_ADMISSION'
        $output=& $Python -I -B $worker --drill-id $DrillId --mode check --confirm-drill-only
        if ($LASTEXITCODE -ne 0 -or ($output|ConvertFrom-Json).status -cne 'ISOLATED_DRILL_PREREQUISITES_CHECK_PASSED') {throw 'ISOLATED_RECIPE_PRECHECK_BLOCKED'}
        $task=Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
        Assert-DrillTask $task $Python $arguments $Directory $Sid $User
        if ($task.Settings.Enabled -ne $false -or [string]$task.State -cne 'Disabled' -or
            (Test-Path -LiteralPath (Join-Path $Root 'attempt.json')) -or
            (Test-Path -LiteralPath (Join-Path $Root 'controller-attempt.json')) -or
            (Test-Path -LiteralPath (Join-Path $Root 'task-witness.json'))) {throw 'ONE_NEW_DRILL_ATTEMPT_ONLY'}
        Write-DrillWitness (Join-Path $Root 'controller-attempt.json') @{identifier=$DrillId;retry_allowed=$false;at=[datetime]::UtcNow.ToString('o')}
        $script:phase='SYNTHETIC_ENABLE_START'
        $script:attemptedEnable=$true
        Enable-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop|Out-Null
        Start-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
        $started=$false;$watch=[Diagnostics.Stopwatch]::StartNew()
        do {
            Start-Sleep -Seconds 2
            $info=Get-ScheduledTaskInfo -TaskPath '\' -TaskName $taskName -ErrorAction Stop
            $task=Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
            if (Test-Path -LiteralPath (Join-Path $Root 'attempt.json')) {$started=$true}
            if ($started -and [string]$task.State -notin @('Running','Queued') -and $info.LastTaskResult -eq 2) {break}
        } while ($watch.Elapsed.TotalSeconds -lt 150)
        $script:phase='DISABLE_AND_WITNESS'
        Disable-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop|Out-Null
        $task=Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
        $script:disabledVerified=($task.Settings.Enabled -eq $false -and [string]$task.State -ceq 'Disabled')
        if (-not $script:disabledVerified -or -not $started -or $info.LastTaskResult -ne 2) {throw 'SYNTHETIC_COMPLETION_NOT_PROVEN'}
        Assert-DrillTask $task $Python $arguments $Directory $Sid $User
        Write-DrillWitness (Join-Path $Root 'task-witness.json') @{identifier=$DrillId;binding_verified=$true;disabled_verified=$true;last_result=[long]$info.LastTaskResult;provenance='OWNER_CONTROLLER_NATIVE_TASK_QUERY'}
}

if (-not $ConfirmRun -or $Action -ceq 'Preview') {
    @{status='PREVIEW';reads=0;writes=0;task_queries=0;task_mutations=0;capture_invocations=0}|ConvertTo-Json -Compress
    exit 0
}
$phase='PREREQUISITES';$attemptedEnable=$false;$disabledVerified=$false;$taskName=$null;$bindingFailures=@();$script:identityProof='NOT_CHECKED'
try {
    if ($env:OS -cne 'Windows_NT') {throw 'WINDOWS_REQUIRED'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'NORMAL_WINDOW_REQUIRED'}
    $now=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([datetime]::UtcNow,'India Standard Time')
    Assert-DrillWindow $now $ConfirmNoCaptureRunning.IsPresent
    Assert-DrillTools $PSScriptRoot
    if ($DrillId -cnotmatch '^[a-f0-9]{32}$' -or -not [IO.Path]::IsPathRooted($Python)) {throw 'EXPLICIT_DRILL_ID_AND_PYTHON_REQUIRED'}
    $version=& $Python -I -B -c 'import sys; print(sys.version.split()[0])'
    if ($LASTEXITCODE -ne 0 -or ([string]$version).Trim() -cne '3.13.9') {throw 'PYTHON_3139_REQUIRED'}
    $worker=Join-Path $PSScriptRoot 'isolated_alert_drill.py'
    $arguments=Drill-Arguments $worker $DrillId
    $taskName='ResearchOps-SyntheticAlert-'+$DrillId
    $root=Join-Path $env:LOCALAPPDATA ('KiranTrading\AlertDrills\'+$DrillId)
    # Setup enumerates existing task metadata to reject a duplicate name. Only
    # the exact new synthetic task can be changed; nothing from capture is run.
    if ($Action -ceq 'Setup') {
        $phase='NEW_ISOLATED_STATE'
        $existing=@(Get-ScheduledTask -TaskPath '\' -ErrorAction Stop | Where-Object {$_.TaskName -ceq $taskName})
        if ($existing.Count -ne 0) {throw 'EXISTING_DRILL_REVIEW_NO_RETRY'}
        $output=& $Python -I -B $worker --drill-id $DrillId --mode setup --confirm-drill-only
        if ($LASTEXITCODE -ne 0 -or ($output|ConvertFrom-Json).status -cne 'ISOLATED_DRILL_STATE_PREPARED_NOT_TASK_REGISTRATION') {throw 'ISOLATED_STATE_SETUP_BLOCKED'}
        $correlationCode=[string]($output|ConvertFrom-Json).correlation_code
        if ($correlationCode -cnotmatch '^[a-p]{8}$') {throw 'ISOLATED_STATE_SETUP_BLOCKED'}
        $phase='DISABLED_DRILL_REGISTRATION'
        $actionDefinition=New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $PSScriptRoot
        $principal=New-ScheduledTaskPrincipal -UserId $identity.User.Value -LogonType Interactive -RunLevel Limited
        $settings=New-ScheduledTaskSettingsSet -Disable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
        $definition=New-ScheduledTask -Action $actionDefinition -Principal $principal -Settings $settings
        Register-ScheduledTask -TaskPath '\' -TaskName $taskName -InputObject $definition -ErrorAction Stop|Out-Null
        $task=Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop
        Assert-DrillTask $task $Python $arguments $PSScriptRoot $identity.User.Value $identity.Name
        if ($task.Settings.Enabled -ne $false -or [string]$task.State -cne 'Disabled') {throw 'DRILL_DISABLED_PROOF_REQUIRED'}
        @{status='ISOLATED_DUMMY_TASK_REGISTERED_DISABLED';correlation_code=$correlationCode;synthetic=$true;capture_invocations=0;tasks_enabled=0;approval_authority=$false}|ConvertTo-Json -Compress
        exit 0
    }
    if ($Action -ceq 'Run') {
        Invoke-IsolatedDrillRun $taskName $Python $worker $arguments $PSScriptRoot $identity.User.Value $identity.Name $root $DrillId
    }
    $mode=if ($Action -ceq 'Acknowledge') {'acknowledge'} else {'inspect'}
    $phase=if ($mode -ceq 'acknowledge') {'ISOLATED_OWNER_ACKNOWLEDGEMENT'} else {'ISOLATED_READ_ONLY_INSPECTION'}
    $extra=@()
    if ($Action -ceq 'Acknowledge') {
        if (-not $ConfirmNotificationSeen) {throw 'PERSONAL_SYNTHETIC_POPUP_ACK_REQUIRED'}
        if ($SeenCode -cnotmatch '^[a-p]{8}$') {throw 'PERSONAL_SYNTHETIC_POPUP_CODE_REQUIRED'}
        $extra=@('--confirm-notification-seen','--seen-code',$SeenCode)
    }
    $output=& $Python -I -B $worker --drill-id $DrillId --mode $mode --confirm-drill-only @extra
    if ($LASTEXITCODE -ne 0) {
        $child=$null
        try {$child=$output|ConvertFrom-Json} catch {}
        if ($null -ne $child -and $child.reason -ceq 'HUMAN_SYNTHETIC_CODE_MISMATCH') {throw 'PERSONAL_SYNTHETIC_POPUP_CODE_MISMATCH'}
        throw 'SYNTHETIC_ROUTE_REVIEW_REQUIRED'
    }
    $output|ConvertFrom-Json|ConvertTo-Json -Compress -Depth 8
    exit 0
} catch {
    $publicReasons=@('WINDOWS_REQUIRED','NORMAL_WINDOW_REQUIRED','POSTSESSION_OR_WEEKEND_AND_IDLE_REQUIRED',
      'EXPLICIT_DRILL_ID_AND_PYTHON_REQUIRED','PYTHON_3139_REQUIRED','EXISTING_DRILL_REVIEW_NO_RETRY',
      'ISOLATED_STATE_SETUP_BLOCKED','DRILL_DISABLED_PROOF_REQUIRED','ISOLATED_TASK_BINDING_REVIEW_REQUIRED',
      'NO_RESTART_POLICY_REQUIRED','ISOLATED_RECIPE_PRECHECK_BLOCKED','ONE_NEW_DRILL_ATTEMPT_ONLY',
      'REVIEWED_CLEAN_TOOLS_ROOT_REQUIRED','REVIEWED_TRACKED_DRILL_FILES_REQUIRED',
      'SYNTHETIC_COMPLETION_NOT_PROVEN','PERSONAL_SYNTHETIC_POPUP_ACK_REQUIRED','PERSONAL_SYNTHETIC_POPUP_CODE_REQUIRED','PERSONAL_SYNTHETIC_POPUP_CODE_MISMATCH','SYNTHETIC_ROUTE_REVIEW_REQUIRED','DRILL_ARGUMENT_INVALID')
    $reason=if ($_.Exception.Message -cin $publicReasons) {$_.Exception.Message} else {'UNCLASSIFIED_NATIVE_OR_IO_FAILURE'}
    @{status='BLOCKED';code='ISOLATED_TASK_DRILL_STOP_REVIEW_NO_RETRY';stage=$phase;raw_error_printed=$false;
      reason=$reason;binding_failures=@($bindingFailures);identity_proof=$script:identityProof;task_enable_attempted=$attemptedEnable;task_disabled_verified=$disabledVerified;capture_invocations=0;approval_authority=$false}|ConvertTo-Json -Compress
    exit 2
} finally {
    if ($attemptedEnable -and -not $disabledVerified) {
        # Best-effort disable of only the prevalidated synthetic task. Never delete.
        try {Disable-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop|Out-Null} catch {}
    }
}
