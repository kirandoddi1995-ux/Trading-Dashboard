[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$SessionDate,
    [ValidateSet('Preview','SetupAhead','Morning')][string]$Action='Preview',
    [string]$ToolsRoot='',
    [string]$BootstrapPython='',
    [string]$CloseFile='',
    [string]$DownloadedAt='',
    [switch]$AttestNseSource,
    [switch]$ConfirmNotificationSeen,
    [switch]$ConfirmEnableAfterTwoPolls,
    [switch]$ConfirmRun
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$script:guidedChildStage='NOT_REACHED'
$script:guidedChildExit=$null
$script:guidedChildCode='NOT_ESTABLISHED'
$script:guidedChildEffect='NOT_ESTABLISHED'
$script:guidedChildMarker='NOT_ESTABLISHED'
$script:guidedChildRollback='NOT_ESTABLISHED'
$script:guidedControllerStage='NOT_ESTABLISHED'

function Assert-GuidedWindow([datetime]$Now,[string]$Day,[string]$Mode) {
    $dayValue=[datetime]::ParseExact($Day,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture)
    if ($Mode -ceq 'Morning') {
        if ($Now.Date -ne $dayValue.Date -or $Now.TimeOfDay -lt ([timespan]::new(7,50,30)) -or
            $Now.TimeOfDay -ge ([timespan]::new(9,15,0))) {throw 'GUIDED_MORNING_WINDOW_REQUIRED'}
    } elseif ($Mode -ceq 'SetupAhead') {
        $days=($dayValue.Date-$Now.Date).Days
        if ($days -lt 0 -or $days -gt 7 -or ($days -eq 0 -and $Now.Hour -ge 9 -and $Now.TimeOfDay -ge ([timespan]::new(9,15,0)))) {
            throw 'GUIDED_SETUP_WINDOW_REQUIRED'
        }
    } else {throw 'GUIDED_STAGE_UNKNOWN_NO_RETRY'}
}

function Child-Arguments([string]$Coordinator,[string]$Day,[string]$Stage,[string]$Python,
                         [string]$File,[string]$Downloaded) {
    if ($Stage -cnotin @('CheckSetup','CheckTasks','Setup','Prepare','Start')) {throw 'GUIDED_STAGE_UNKNOWN_NO_RETRY'}
    $items=@('-NoProfile','-File',$Coordinator,'-SessionDate',$Day,'-Action',$Stage,
        '-BootstrapPython',$Python,'-ConfirmRun')
    if ($Stage -ceq 'Prepare') {$items+=@('-CloseFile',$File,'-DownloadedAt',$Downloaded,'-AttestNseSource')}
    if ($Stage -ceq 'Start') {$items+=@('-ConfirmNotificationSeen','-ConfirmEnableAfterTwoPolls')}
    return $items
}

function Invoke-GuidedChain([string]$Mode,[scriptblock]$Invoke,[string]$Day='') {
    $stages = if ($Mode -ceq 'SetupAhead') {@('CheckSetup','Setup','CheckTasks')} else {@('Prepare','Start')}
    foreach ($stage in $stages) {
        $result = & $Invoke $stage
        if ($null -eq $result -or $result.status -ceq 'BLOCKED') {throw 'GUIDED_STAGE_BLOCKED_NO_RETRY'}
        $expected = switch ($stage) {
            'CheckSetup' {'SETUP_PREREQUISITES_CHECK_PASSED_NOT_COMMISSIONED'}
            'CheckTasks' {'EXISTING_TASK_BINDINGS_CHECKED_NOT_SETUP_ACCEPTANCE'}
            'Setup' {'SETUP_VERIFIED_TASKS_DISABLED'}
            'Prepare' {'MORNING_GO_SUPERVISED_START_REQUIRED'}
            'Start' {'POLL_ENABLE_ACKNOWLEDGED_AFTER_VERIFIED_ADMISSION'}
        }
        if ($result.status -cne $expected) {throw 'GUIDED_STAGE_UNKNOWN_NO_RETRY'}
        $summaries=$null
        if ($null -ne $result.PSObject.Properties['guided_poll_summaries']) {$summaries=$result.guided_poll_summaries}
        @{status='GUIDED_STAGE_ACCEPTED';session_date=$Day;stage=$stage;child_status=$result.status;
            supervised_polls=$summaries;execution_proof=$false;approval_authority=$false} | ConvertTo-Json -Depth 5 -Compress
    }
}

function Read-ChildResult([string]$Text,[int]$ExitCode,[string]$Stage) {
    $script:guidedChildStage=$Stage
    $script:guidedChildExit=$ExitCode
    if ($Text.Length -gt 262144) {throw 'GUIDED_STAGE_BLOCKED_NO_RETRY'}
    $rows = @()
    foreach ($line in ($Text -split "`r?`n")) {
        if ([string]::IsNullOrWhiteSpace($line)) {continue}
        if ($Stage -ceq 'Start' -and $line -cmatch '^Waiting for ONE future supervised slot (09:20:30|09:25:30) IST\. Do not close this window\.$') {continue}
        try {$item = ConvertFrom-Json -InputObject $line -ErrorAction Stop}
        catch {throw 'GUIDED_STAGE_UNKNOWN_NO_RETRY'}
        if ($null -eq $item -or $item -is [array] -or $item -is [string]) {throw 'GUIDED_STAGE_UNKNOWN_NO_RETRY'}
        if ($null -ne $item.PSObject.Properties['status'] -and $item.status -is [string]) {$rows += $item}
    }
    if ($rows.Count -eq 0) {throw 'GUIDED_STAGE_UNKNOWN_NO_RETRY'}
    $blocked=@($rows | Where-Object {$_.status -ceq 'BLOCKED'})
    if ($blocked.Count -gt 0) {
        $public=@('CLOCK_UNVERIFIED','AUTH_REQUIRED','PREOPEN_DEADLINE_MISSED','SESSION_ALREADY_PREPARED',
            'FRESH_SESSION_MORNING_DOWNLOAD_REQUIRED','SETUP_REQUIRED','REVIEWED_REGULAR_SESSION_REQUIRED',
            'FIRST_START_DEADLINE_MISSED_NO_RETRY','TASK_STATE_NOT_EXPECTED','TASK_EXACT_BINDING_MISMATCH',
            'OTHER_CAPTURE_TASK_NOT_DISABLED','WINDOWS_TIME_SERVICE_NOT_RUNNING','DAILY_OWNER_REVIEW_REQUIRED_NO_RETRY')
        if ($null -ne $blocked[0].PSObject.Properties['code'] -and $blocked[0].code -is [string] -and $blocked[0].code -cin $public) {
            $script:guidedChildCode=$blocked[0].code
        }
        $phases=@('INPUT','NORMAL_WINDOW_CHECK','REVIEWED_TOOLS_CHECKOUT','OWNER_PATH_CONTEXT',
            'PINNED_PYTHON_BOOTSTRAP_CHECK','PRIVATE_OPS_READ_ONLY_CHECK','PUBLIC_CAPSULE_SETUP',
            'REVIEWED_CALENDAR','DATE_AND_OWNER_CONTEXT','DISABLED_TASK_READ_ONLY_CHECK','DISABLED_TASK_SETUP',
            'DISABLED_TASK_REGISTRATION','DISABLED_TASK_READBACK','PREOPEN_HEALTH','OWNER_FILE_PREPARATION',
            'POLICY_FREEZE','SUPERVISED_ADMISSION','WAIT_09:20:30','WAIT_09:25:30','ONE_POLL_09:20:30',
            'ONE_POLL_09:25:30','AUDIT_FIRST_POLL_LAST_ENABLE','FRESH_ADMISSION_HEALTH',
            'AUDIT_TASK_ENABLE_AND_VERIFY','OWNER_AUTHORISED_COMMIT_ATTEMPT','POLL_ENABLE_COMMIT_ATTEMPT')
        if ($null -ne $blocked[0].PSObject.Properties['stage'] -and $blocked[0].stage -is [string] -and $blocked[0].stage -cin $phases) {
            $script:guidedControllerStage=$blocked[0].stage
        }
        foreach ($field in @('operational_state_effect','start_attempt_marker_effect')) {
            if ($null -ne $blocked[0].PSObject.Properties[$field] -and $blocked[0].$field -cin @('NOT_REACHED','NOT_ESTABLISHED')) {
                if ($field -ceq 'operational_state_effect') {$script:guidedChildEffect=$blocked[0].$field}
                else {$script:guidedChildMarker=$blocked[0].$field}
            }
        }
        if ($null -ne $blocked[0].PSObject.Properties['rollback'] -and $blocked[0].rollback -cin @(
            'NOT_REQUIRED','FUTURE_POLL_DISABLE_UNCONFIRMED_OWNER_CHECK_REQUIRED','FUTURE_POLL_DISABLED_NO_PROCESS_TERMINATED')) {
            $script:guidedChildRollback=$blocked[0].rollback
        }
        throw 'GUIDED_STAGE_BLOCKED_NO_RETRY'
    }
    if ($ExitCode -ne 0) {throw 'GUIDED_STAGE_BLOCKED_NO_RETRY'}
    $summaries=@()
    foreach ($row in @($rows | Where-Object {$_.status -ceq 'POLL_REMOTE_VERIFIED'})) {
        $count=$null;$missing=$null;$clock='NOT_ESTABLISHED'
        foreach ($key in @('recorded_decisions','missing_decisions')) {
            if ($null -ne $row.PSObject.Properties[$key] -and ($row.$key -is [int] -or $row.$key -is [long]) -and $row.$key -ge 0 -and $row.$key -le 75) {
                if ($key -ceq 'recorded_decisions') {$count=$row.$key} else {$missing=$row.$key}
            }
        }
        if ($null -ne $row.PSObject.Properties['clock_problem'] -and $row.clock_problem -ceq 'PASS') {$clock='PASS'}
        $summaries+=@{status='POLL_REMOTE_VERIFIED';recorded_decisions=$count;missing_decisions=$missing;
            clock_problem=$clock;proof='PINNED_CHILD_REPORT_NOT_INDEPENDENT_CUSTODY'}
    }
    Add-Member -InputObject $rows[-1] -NotePropertyName 'guided_poll_summaries' -NotePropertyValue $summaries
    return $rows[-1]
}

try {
    if (-not $ConfirmRun -or $Action -ceq 'Preview') {
        @{status='PREVIEW';session_date=$SessionDate;action=$Action;source_reads=0;child_invocations=0;task_mutations=0;
            credential_reads=0;automatic_attestations=$false;approval_authority=$false} | ConvertTo-Json -Compress
        exit 0
    }
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {throw 'WINDOWS_REQUIRED'}
    $admin=([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($admin) {throw 'NORMAL_NON_ADMIN_WINDOW_REQUIRED'}
    $now=[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([datetime]::UtcNow,'India Standard Time')
    Assert-GuidedWindow $now $SessionDate $Action
    if ($Action -ceq 'Morning' -and (-not $AttestNseSource -or -not $ConfirmNotificationSeen -or
        -not $ConfirmEnableAfterTwoPolls -or [string]::IsNullOrWhiteSpace($CloseFile) -or
        [string]::IsNullOrWhiteSpace($DownloadedAt))) {throw 'OWNER_ATTESTATIONS_REQUIRED'}
    if (-not [IO.Path]::IsPathRooted($ToolsRoot) -or -not [IO.Path]::IsPathRooted($BootstrapPython)) {throw 'EXPLICIT_REVIEWED_PATHS_REQUIRED'}
    foreach ($path in @($ToolsRoot,$BootstrapPython)) {
        $item=Get-Item -LiteralPath $path -ErrorAction Stop
        while ($null -ne $item) {
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {throw 'LINK_PATH_REJECTED'}
            if ($item -is [IO.FileInfo]) {$item=$item.Directory} else {$item=$item.Parent}
        }
    }
    $pins=@{
        'forward_daily_owner.ps1'='4ee910bc266fe87b7dd768f4037c4a126896ff1f3d3b5ea7fdab0214b51ce8db';
        'forward_daily_contract.py'='9f72b8e0431fc1d484d0bbdfb4bfe0a8a30a5f64fc17ca4ae6b60b47cafa4a0c'
    }
    foreach ($name in $pins.Keys) {
        $text=[IO.File]::ReadAllText((Join-Path $ToolsRoot $name)).Replace("`r`n","`n")
        $sha=[Security.Cryptography.SHA256]::Create()
        try {$actual=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))).Replace('-','').ToLowerInvariant()}
        finally {$sha.Dispose()}
        if ($actual -cne $pins[$name]) {throw 'REVIEWED_COORDINATOR_HASH_MISMATCH'}
    }
    $git=(Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $head=@(& $git -C $ToolsRoot rev-parse HEAD 2>$null)
    if ($LASTEXITCODE -ne 0 -or ($head -join '').Trim() -cne '0b0aad4efa102643cc5dc4073dc7fc915281c1bf') {throw 'REVIEWED_TOOLS_HEAD_REQUIRED'}
    $dirty=@(& $git -C $ToolsRoot status --porcelain 2>$null)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0) {throw 'CLEAN_TOOLS_CHECKOUT_REQUIRED'}
    $script:guidedShell=Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
    $script:guidedCoordinator=Join-Path $ToolsRoot 'forward_daily_owner.ps1'
    Invoke-GuidedChain $Action {
        param($stage)
        $arguments=Child-Arguments $script:guidedCoordinator $SessionDate $stage $BootstrapPython $CloseFile $DownloadedAt
        if ($stage -ceq 'Start') {Write-Host 'Reviewed Start is running and may wait until09:20:30/09:25:30. Leave this window and PC awake; do not retry.'}
        $raw=@(& $script:guidedShell @arguments 2>$null)
        $exit=$LASTEXITCODE
        Read-ChildResult ($raw -join "`n") $exit $stage
    } $SessionDate
    @{status='GUIDED_CHAIN_COMPLETED_NOT_FULL_DAY_PROOF';session_date=$SessionDate;action=$Action;
        disabled_setup_child_reported=($Action -ceq 'SetupAhead');actual_task_state='NOT_QUERIED_BY_WRAPPER';
        enable_acknowledgement_only=($Action -ceq 'Morning');automatic_attestations=$false;
        remote_custody_verified=$false;training_eligible=$false;approval_authority=$false} | ConvertTo-Json -Compress
} catch {
    $allowed=@('WINDOWS_REQUIRED','NORMAL_NON_ADMIN_WINDOW_REQUIRED','OWNER_ATTESTATIONS_REQUIRED',
        'EXPLICIT_REVIEWED_PATHS_REQUIRED','LINK_PATH_REJECTED','REVIEWED_COORDINATOR_HASH_MISMATCH',
        'GUIDED_MORNING_WINDOW_REQUIRED','GUIDED_SETUP_WINDOW_REQUIRED',
        'REVIEWED_TOOLS_HEAD_REQUIRED','CLEAN_TOOLS_CHECKOUT_REQUIRED','GUIDED_STAGE_BLOCKED_NO_RETRY','GUIDED_STAGE_UNKNOWN_NO_RETRY')
    $code='GUIDED_OWNER_REVIEW_REQUIRED_NO_RETRY'
    if ($_.Exception.Message -cin $allowed) {$code=$_.Exception.Message}
    @{status='BLOCKED';session_date=$SessionDate;code=$code;raw_error_printed=$false;operational_state_effect='INSPECT_ORIGINAL_COORDINATOR_REPORTS';
        child_stage=$script:guidedChildStage;child_exit_code=$script:guidedChildExit;child_public_code=$script:guidedChildCode;
        child_controller_stage=$script:guidedControllerStage;
        child_operational_state_effect=$script:guidedChildEffect;child_start_attempt_marker_effect=$script:guidedChildMarker;
        child_rollback=$script:guidedChildRollback;
        marker_reset_allowed=$false;retry_allowed=$false;approval_authority=$false} | ConvertTo-Json -Compress
    exit 2
}
