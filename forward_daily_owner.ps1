param(
    [Parameter(Mandatory=$true)][string]$SessionDate,
    [ValidateSet('Preview','Setup','Prepare','Start','Audit')][string]$Action = 'Preview',
    [string]$CloseFile = '',
    [string]$DownloadedAt = '',
    [switch]$AttestNseSource,
    [switch]$ConfirmNotificationSeen,
    [switch]$ConfirmEnableAfterTwoPolls,
    [switch]$ConfirmRun
)
# Owner-run coordinator OUTSIDE the frozen capsule. No automatic service/ACL repair.
# No prompt consumes pasted input. Producer and all existing safety gates unchanged.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$phase = 'INPUT'
$pollEnableAttemptedByThisRun = $false
$pollEnableCommitted = $false
$rollbackAttempted = $false
$rollback = 'NOT_REQUIRED'
$base = '1251530731cce5b75fad8601567b9320d07b710d'
$publicBlockers = @()
$publicCodes = @('CLOCK_UNVERIFIED','CLOCK_MEASUREMENT_UNAVAILABLE','CLOCK_MEASUREMENT_STALE',
    'CLOCK_MEASUREMENT_INVALID','CLOCK_OFFSET_OR_UNCERTAINTY_EXCESSIVE',
    'WINDOWS_TIME_SERVICE_NOT_RUNNING','WINDOWS_TIME_SERVICE_NOT_AUTOMATIC',
    'WINDOWS_DIAGNOSTICS_UNAVAILABLE','LOCAL_DISK_RESERVE_NOT_MET','CAPTURE_DISK_RESERVE_NOT_MET',
    'LOCAL_DISK_CHECK_UNAVAILABLE','POLL_TASK_ACTION_MISMATCH','AUDIT_TASK_ACTION_MISMATCH',
    'AUTH_REQUIRED','LICENSE_ACK_REQUIRED','SESSION_ALREADY_PREPARED','SESSION_NOT_PREPARED',
    'OWNER_CLOSE_TIMING_INVALID','NORMAL_NON_ADMIN_WINDOW_REQUIRED',
    'FRESH_SESSION_MORNING_DOWNLOAD_REQUIRED','SETUP_REQUIRED','PRIVATE_OPS_PERMISSIONS_REQUIRE_REVIEW',
    'FIRST_START_DEADLINE_MISSED_NO_RETRY','PREOPEN_DEADLINE_MISSED','SESSION_DATE_MISMATCH',
    'REVIEWED_REGULAR_SESSION_REQUIRED','SETUP_DATE_OUTSIDE_REVIEW_WINDOW','APPROVED_POLICY_BYTES_INVALID',
    'ACTUAL_DOWNLOAD_TIMESTAMP_REQUIRED','AWARE_TIME_REQUIRED','POSTSESSION_AUDIT_ONLY',
    'TASK_EXACT_BINDING_MISMATCH','TASK_TRIGGER_DATE_MISMATCH','TASK_REPETITION_MISMATCH',
    'TASK_STATE_NOT_EXPECTED','OTHER_CAPTURE_TASK_NOT_DISABLED','ENABLE_DEADLINE_MISSED',
    'TARGET_PASSED_OR_WAIT_TOO_LONG_NO_CATCHUP','WAIT_CLOCK_CHANGED','INTERRUPTED_WAIT_NO_CATCHUP',
    'NEXT_TRIGGER_NOT_PROVEN_BEFORE_DEADLINE','ADMISSION_HEALTH_NOT_VERIFIED')

function Stop-Daily([string]$code) { throw [InvalidOperationException]::new($code) }
function Now-Ist { [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, [TimeZoneInfo]::FindSystemTimeZoneById('India Standard Time')) }
function Run-Text([string]$exe, [string[]]$Arguments, [int[]]$Allowed = @(0)) {
    # PS5.1 turns redirected native stderr into ErrorRecords. Capture progress
    # without treating stderr as failure; use the actual exit code instead.
    # Resolve an actual executable, never a profile function/alias/wrapper that
    # could leave a stale LASTEXITCODE behind after a nonterminating failure.
    $native = Get-Command -Name $exe -CommandType Application -ErrorAction Stop | Select-Object -First 1
    if ($native -isnot [Management.Automation.ApplicationInfo]) { Stop-Daily 'PUBLIC_NATIVE_TOOL_REQUIRED' }
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = $null
        $output = & $native.Source @Arguments 2>&1
        $exitValue = $global:LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    $text = (($output | ForEach-Object { [string]$_ }) -join "`n")
    if ($exitValue -isnot [int] -or $exitValue -notin $Allowed) {
        # Only fixed public enums leave the child. Never print a raw exception.
        if ($text.Length -le 131072) {
            try {
                $line = $text -split "`n" | Where-Object { $_.TrimStart().StartsWith('{') } | Select-Object -Last 1
                $data = $line | ConvertFrom-Json
                $found = @()
                if ($data.PSObject.Properties['code'] -and $data.code -cin $publicCodes) { $found += [string]$data.code }
                if ($data.PSObject.Properties['blockers']) { $found += @($data.blockers | Where-Object { $_ -cin $publicCodes } | Select-Object -First 8) }
                $script:publicBlockers = @($found | Select-Object -Unique)
            } catch { $script:publicBlockers = @() }
        }
        if ($publicBlockers.Count -gt 0) { Stop-Daily ([string]$publicBlockers[0]) }
        Stop-Daily 'CHILD_BLOCKED_NO_RETRY'
    }
    return $text
}
function Run-Json([string]$exe, [string[]]$Arguments, [string[]]$Statuses) {
    $text = Run-Text $exe $Arguments
    if ($text.Length -gt 131072) { Stop-Daily 'CHILD_REPORT_TOO_LARGE' }
    $last = ($text -split "`n" | Where-Object { $_.TrimStart().StartsWith('{') } | Select-Object -Last 1)
    if (-not $last) { Stop-Daily 'CHILD_REPORT_MISSING' }
    $value = $last | ConvertFrom-Json
    if ($value.status -notin $Statuses) { Stop-Daily 'CHILD_STATUS_NOT_ACCEPTED' }
    return $value
}
function Assert-Capsule {
    if (-not (Test-Path -LiteralPath $codeRoot -PathType Container)) { Stop-Daily 'SETUP_REQUIRED' }
    if ((Run-Text 'git' @('-C',$codeRoot,'rev-parse','HEAD')).Trim() -cne $base) { Stop-Daily 'CAPSULE_COMMIT_MISMATCH' }
    if ((Run-Text 'git' @('-C',$codeRoot,'status','--porcelain')).Trim()) { Stop-Daily 'CAPSULE_SOURCE_NOT_CLEAN' }
    $policy = Join-Path $codeRoot 'resilience_policy.json'
    $approved = [IO.File]::ReadAllText((Join-Path $codeRoot 'resilience_policy.sha256')).Trim()
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $actual = ([BitConverter]::ToString($hasher.ComputeHash([IO.File]::ReadAllBytes($policy)))).Replace('-','').ToLowerInvariant() }
    finally { $hasher.Dispose() }
    if ($approved -cnotmatch '^[0-9a-f]{64}$' -or $actual -cne $approved) { Stop-Daily 'APPROVED_POLICY_BYTES_INVALID' }
}
function Invoke-Capsule([string]$File, [string[]]$Arguments, [string[]]$Statuses) {
    Assert-Capsule
    Push-Location -LiteralPath $codeRoot
    try { return Run-Json $codePython (@('-B',(Join-Path $codeRoot $File)) + $Arguments) $Statuses }
    finally { Pop-Location }
}
function Gate([string]$mode) {
    $argsCore = @('-3.13','-I','-B',(Join-Path $PSScriptRoot 'forward_daily_contract.py'),
        '--session-date',$SessionDate,'--evaluate',$mode,'--at',((Now-Ist).ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff")+'+05:30'),
        '--calendar-kind',[string]$calendar.kind)
    if ($mode -eq 'Prepare') { $argsCore += @('--download-at',$DownloadedAt) }
    $null = Run-Json 'py' $argsCore @('PURE_INPUT_GATE_PASSED_NOT_HOST_ACCEPTANCE')
}
function Assert-PrivateOps {
    # Read-only allow-list, never Set-Acl or inheritance repair. Owner/SYSTEM/Admins.
    if (-not (Test-Path -LiteralPath $opsRoot -PathType Container)) { Stop-Daily 'EXISTING_PRIVATE_OPS_ROOT_REQUIRED' }
    $item = Get-Item -LiteralPath $opsRoot -Force
    for ($ancestor = $item; $null -ne $ancestor; $ancestor = $ancestor.Parent) {
        if (($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { Stop-Daily 'OPS_LINK_REJECTED' }
    }
    $trusted = @($ownerSid,'S-1-5-18','S-1-5-32-544')
    foreach ($rule in (Get-Acl -LiteralPath $opsRoot).Access) {
        if ([string]$rule.AccessControlType -eq 'Allow') {
            $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            if ($sid -notin $trusted) { Stop-Daily 'PRIVATE_OPS_PERMISSIONS_REQUIRE_REVIEW' }
        }
    }
}
function Field([xml]$Xml, [string]$Path) {
    $ns = [Xml.XmlNamespaceManager]::new($Xml.NameTable)
    $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    $nodes = $Xml.SelectNodes($Path,$ns)
    if ($nodes.Count -ne 1) { Stop-Daily 'TASK_BINDING_FIELD_MISSING_OR_DUPLICATE' }
    return $nodes[0].InnerText
}
function Assert-Task([string]$Name, [bool]$Enabled) {
    $task = Get-ScheduledTask -TaskPath '\' -TaskName $Name -ErrorAction Stop
    $export = [string](Export-ScheduledTask -TaskPath '\' -TaskName $Name -ErrorAction Stop)
    if ($export.Length -gt 65536 -or $export -match '<!') { Stop-Daily 'TASK_XML_REQUIRES_REVIEW' }
    $xml = [xml]::new(); $xml.XmlResolver = $null; $xml.LoadXml($export)
    $expected = [xml]$taskPlans.plans.$Name
    foreach ($path in @('/t:Task/t:Actions/t:Exec/t:Command','/t:Task/t:Actions/t:Exec/t:Arguments',
        '/t:Task/t:Actions/t:Exec/t:WorkingDirectory','/t:Task/t:Principals/t:Principal/t:UserId',
        '/t:Task/t:Principals/t:Principal/t:LogonType','/t:Task/t:Principals/t:Principal/t:RunLevel',
        '/t:Task/t:Triggers/t:TimeTrigger/t:Enabled',
        '/t:Task/t:Settings/t:MultipleInstancesPolicy','/t:Task/t:Settings/t:StartWhenAvailable',
        '/t:Task/t:Settings/t:ExecutionTimeLimit','/t:Task/t:Settings/t:WakeToRun',
        '/t:Task/t:Settings/t:DisallowStartIfOnBatteries','/t:Task/t:Settings/t:StopIfGoingOnBatteries')) {
        if ((Field $xml $path) -cne (Field $expected $path)) { Stop-Daily 'TASK_EXACT_BINDING_MISMATCH' }
    }
    # These plan-omitted schema defaults are false. Windows may export explicit
    # false elements, but true/unknown/duplicate conditions must not delay a slot.
    foreach ($condition in @('RunOnlyIfIdle','RunOnlyIfNetworkAvailable')) {
        $ns = [Xml.XmlNamespaceManager]::new($xml.NameTable)
        $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
        $nodes = $xml.SelectNodes('/t:Task/t:Settings/t:' + $condition,$ns)
        if ($nodes.Count -gt 1 -or ($nodes.Count -eq 1 -and $nodes[0].InnerText -cne 'false')) { Stop-Daily 'TASK_EXACT_BINDING_MISMATCH' }
    }
    $delayNodes = $xml.SelectNodes('/t:Task/t:Triggers/t:TimeTrigger/t:RandomDelay',$ns)
    if ($delayNodes.Count -gt 1 -or ($delayNodes.Count -eq 1 -and $delayNodes[0].InnerText -cne 'PT0S')) { Stop-Daily 'TASK_EXACT_BINDING_MISMATCH' }
    foreach ($field in @('StartBoundary','EndBoundary')) {
        $path = '/t:Task/t:Triggers/t:TimeTrigger/t:' + $field
        if ([DateTimeOffset]::Parse((Field $xml $path)) -ne [DateTimeOffset]::Parse((Field $expected $path))) { Stop-Daily 'TASK_TRIGGER_DATE_MISMATCH' }
    }
    if ($Name -eq $pollName) {
        foreach ($field in @('Interval','Duration','StopAtDurationEnd')) {
            $path = '/t:Task/t:Triggers/t:TimeTrigger/t:Repetition/t:' + $field
            if ((Field $xml $path) -cne (Field $expected $path)) { Stop-Daily 'TASK_REPETITION_MISMATCH' }
        }
    }
    if ($task.Actions.Count -ne 1 -or $task.Triggers.Count -ne 1 -or $export -match '<RestartOnFailure') { Stop-Daily 'TASK_EXTRA_ACTION_OR_RETRY_REJECTED' }
    if ([bool]$task.Settings.Enabled -ne $Enabled -or [string]$task.State -cne $(if ($Enabled) {'Ready'} else {'Disabled'})) { Stop-Daily 'TASK_STATE_NOT_EXPECTED' }
}
function Wait-Slot([string]$time) {
    $target = [DateTime]::ParseExact("$SessionDate $time",'yyyy-MM-dd HH:mm:ss',[Globalization.CultureInfo]::InvariantCulture)
    $prior = Now-Ist
    if ($prior -ge $target -or ($target-$prior).TotalSeconds -gt 5400) { Stop-Daily 'TARGET_PASSED_OR_WAIT_TOO_LONG_NO_CATCHUP' }
    Write-Host ('Waiting for ONE future supervised slot ' + $time + ' IST. Do not close this window.')
    do {
        Start-Sleep -Milliseconds 200
        $fresh = Now-Ist
        if ($fresh -lt $prior -or $fresh.Date -ne $day.Date) { Stop-Daily 'WAIT_CLOCK_CHANGED' }
        $prior = $fresh
    } while ($fresh -lt $target)
    if (($fresh-$target).TotalSeconds -gt 1) { Stop-Daily 'INTERRUPTED_WAIT_NO_CATCHUP' }
}
function Accept-Poll($Report, [int]$Expected) {
    # Pure contract runs in an isolated interpreter, not a second producer.
    $check = "import base64,json,runpy,sys; m=runpy.run_path(sys.argv[1]); assert m['accepted_poll'](json.loads(base64.b64decode(sys.argv[2],validate=True)),int(sys.argv[3]))"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($Report | ConvertTo-Json -Compress)))
    $null = Run-Text 'py' @('-3.13','-I','-B','-c',$check,(Join-Path $PSScriptRoot 'forward_daily_contract.py'),$encoded,[string]$Expected)
}
function Undo-PollEnable {
    $script:rollbackAttempted = $true
    try {
        Disable-ScheduledTask -TaskPath '\' -TaskName $pollName -ErrorAction Stop | Out-Null
        $remaining = Get-ScheduledTask -TaskPath '\' -TaskName $pollName -ErrorAction Stop
        if ($remaining.Settings.Enabled -isnot [bool] -or $remaining.Settings.Enabled) { Stop-Daily 'FUTURE_POLL_DISABLE_NOT_PROVEN' }
        $script:rollback = 'FUTURE_POLL_DISABLED_NO_PROCESS_TERMINATED'
    } catch { $script:rollback = 'FUTURE_POLL_DISABLE_UNCONFIRMED_OWNER_CHECK_REQUIRED' }
}
function Report-Digest([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text.Replace("`r`n","`n"))))).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
function Write-NewOpsRecord([string]$Name, [string]$Text) {
    if ($Name -cnotmatch '^\d{4}-\d{2}-\d{2}-guided-(morning-v1\.attempt|activation-v1\.json)$' -or $Text.Length -gt 131072) { Stop-Daily 'OPS_RECORD_IDENTITY_INVALID' }
    Assert-PrivateOps
    $handle = [IO.File]::Open((Join-Path $opsRoot $Name),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $bytes = [Text.Encoding]::UTF8.GetBytes($Text); $handle.Write($bytes,0,$bytes.Length); $handle.Flush($true) }
    finally { $handle.Dispose() }
}

try {
    if ($SessionDate -cnotmatch '^\d{4}-\d{2}-\d{2}$') { Stop-Daily 'SESSION_DATE_INVALID' }
    $day = [DateTime]::ParseExact($SessionDate,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture)
    $stamp = $day.ToString('yyyyMMdd')
    $pollName = 'KiranTrading-Versioned-' + $stamp + '-poll'
    $auditName = 'KiranTrading-Versioned-' + $stamp + '-audit'
    if (-not $ConfirmRun -or $Action -eq 'Preview') {
        @{status='PREVIEW';session_date=$SessionDate;poll_task=$pollName;audit_task=$auditName;writes=0;network_calls=0;credential_reads=0;approval_authority=$false} | ConvertTo-Json -Compress
        exit 0
    }
    $phase = 'NORMAL_WINDOW_CHECK'
    if ($env:OS -cne 'Windows_NT') { Stop-Daily 'WINDOWS_OWNER_RUN_ONLY' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Stop-Daily 'NORMAL_NON_ADMIN_WINDOW_REQUIRED' }
    $ownerSid = $identity.User.Value
    $phase = 'REVIEWED_TOOLS_CHECKOUT'
    if ((Run-Text 'git' @('-C',$PSScriptRoot,'rev-parse','--show-toplevel')).Trim().Replace('\','/').TrimEnd('/') -ine $PSScriptRoot.Replace('\','/').TrimEnd('/')) { Stop-Daily 'TOOLS_CHECKOUT_ROOT_REQUIRED' }
    if ((Run-Text 'git' @('-C',$PSScriptRoot,'status','--porcelain')).Trim()) { Stop-Daily 'TOOLS_CHECKOUT_NOT_CLEAN' }
    $stateRoot = Join-Path $env:LOCALAPPDATA 'KiranTrading\Forward'
    $opsRoot = Join-Path $env:LOCALAPPDATA 'KiranTrading\ForwardOps'
    $codeRoot = Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) ('kiran_forward_' + $stamp)
    $codePython = Join-Path $codeRoot '.venv\Scripts\python.exe'
    $null = Run-Text 'py' @('-3.13','-I','-B','-c','import sys; assert sys.version_info[:3] == (3,13,9)')
    Assert-PrivateOps
    if ($Action -eq 'Setup') {
        $phase = 'PUBLIC_CAPSULE_SETUP'
        if (($day.Date-(Now-Ist).Date).TotalDays -lt 0 -or ($day.Date-(Now-Ist).Date).TotalDays -gt 7) { Stop-Daily 'SETUP_DATE_OUTSIDE_REVIEW_WINDOW' }
        if ((Now-Ist).Date -gt $day.Date -or ((Now-Ist).Date -eq $day.Date -and (Now-Ist).TimeOfDay -ge [TimeSpan]::FromMinutes(555))) { Stop-Daily 'SETUP_DEADLINE_MISSED' }
        if (-not (Test-Path -LiteralPath $codeRoot)) {
            $null = Run-Text 'git' @('-c','credential.helper=','clone','--config','core.autocrlf=false','--no-checkout','--branch','main','--single-branch','https://github.com/kirandoddi1995-ux/Trading-Dashboard.git',$codeRoot)
            $null = Run-Text 'git' @('-C',$codeRoot,'checkout','--detach',$base)
        }
        Assert-Capsule
        if (-not (Test-Path -LiteralPath $codePython -PathType Leaf)) {
            $null = Run-Text 'py' @('-3.13','-I','-m','venv',(Join-Path $codeRoot '.venv'))
            $null = Run-Text $codePython @('-I','-m','pip','--isolated','install','--index-url','https://pypi.org/simple','-r',(Join-Path $codeRoot 'requirements-forward-operations.txt'))
        }
        $null = Run-Text $codePython @('-I','-m','pip','--isolated','check')
    }
    Assert-Capsule
    $phase = 'REVIEWED_CALENDAR'
    $calendarCode = "import json,sys; from datetime import date; sys.path.insert(0,sys.argv[1]); from nifty_session_calendar import cash_session; from nifty_previous_close import previous_session; d=date.fromisoformat(sys.argv[2]); p=previous_session(d); print(json.dumps(dict(kind=cash_session(d)['kind'],previous=p.isoformat(),filename='ind_close_all_'+p.strftime('%d%m%Y')+'.csv')))"
    $calendar = (Run-Text $codePython @('-I','-B','-c',$calendarCode,$codeRoot,$SessionDate)) | ConvertFrom-Json
    $phase = 'DATE_AND_OWNER_CONTEXT'
    Gate $Action
    $taskPlans = Invoke-Capsule 'forward_ops_plan.py' @('--session-date',$SessionDate,'--owner-sid',$ownerSid,'--code-directory',$codeRoot,'--python-executable',$codePython,'--state-root',$stateRoot,'--ops-root',$opsRoot) @('REVIEW_ONLY_DISABLED')
    $common = @('--root',$stateRoot,'--ops-root',$opsRoot,'--session-date',$SessionDate,'--poll-task',$pollName,'--audit-task',$auditName)
    if ($Action -eq 'Setup') {
        $phase = 'DISABLED_TASK_SETUP'
        foreach ($old in (Get-ScheduledTask -TaskPath '\' | Where-Object { $_.TaskName -like 'KiranTrading-*' })) {
            if ([string]$old.State -cne 'Disabled') { Stop-Daily 'OTHER_CAPTURE_TASK_NOT_DISABLED' }
        }
        $null = Invoke-Capsule 'future_ops_diagnostics.py' @('--mode','package','--allow-read-only') @('CHECKED')
        $null = Invoke-Capsule 'future_ops_diagnostics.py' @('--mode','dependencies','--allow-read-only') @('CHECKED')
        foreach ($name in @($pollName,$auditName)) {
            if (-not (Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue)) {
                Register-ScheduledTask -TaskPath '\' -TaskName $name -Xml ([string]$taskPlans.plans.$name) -ErrorAction Stop | Out-Null
            }
            Assert-Task $name $false
        }
        Add-Type -AssemblyName System.Windows.Forms
        [void][System.Windows.Forms.MessageBox]::Show('REHEARSAL ONLY. No capture ran. Both new tasks remain disabled.','NIFTY notification rehearsal')
        @{status='SETUP_VERIFIED_TASKS_DISABLED';session_date=$SessionDate;previous_close_date=$calendar.previous;nse_filename=$calendar.filename;producer_clock_verified=$false;notification_delivery='OWNER_MUST_CONFIRM_SEEN';custody_verified=$false;approval_authority=$false} | ConvertTo-Json -Compress
        exit 0
    }
    if ($Action -eq 'Audit') {
        $phase = 'READ_ONLY_POSTSESSION_AUDIT'
        Push-Location -LiteralPath $codeRoot
        try { $text = Run-Text $codePython (@('-B',(Join-Path $codeRoot 'forward_session_ops.py')) + $common + @('--mode','audit','--confirm-ops','--read-only-audit')) @(0,1); Write-Output $text }
        finally { Pop-Location }
        exit 0
    }
    Assert-Task $pollName $false; Assert-Task $auditName $false
    if ($Action -eq 'Prepare') {
        $phase = 'PREOPEN_HEALTH'
        if (-not $AttestNseSource -or -not $CloseFile -or -not $DownloadedAt) { Stop-Daily 'ACTUAL_OWNER_FILE_AND_ATTESTATION_REQUIRED' }
        $null = Invoke-Capsule 'forward_session_ops.py' ($common + @('--mode','preflight','--confirm-ops')) @('PREOPEN_HOST_CHECK_PASSED')
        Gate 'Prepare'
        $phase = 'OWNER_FILE_PREPARATION'
        $config = Invoke-Capsule 'forward_nifty_schedule.py' @('--root',$stateRoot,'--mode','prepare','--owner-close-file',$CloseFile,'--owner-download-at',$DownloadedAt,'--attest-nse-source','--confirm-run') @('CONFIG_PREPARED_OWNER_FILE')
        if ($config.previous_close_date -cne $calendar.previous -or $config.clock_check -cne 'PASS') { Stop-Daily 'PREPARATION_REPORT_NOT_ACCEPTED' }
        Gate 'Prepare'
        $phase = 'POLICY_FREEZE'
        $null = Invoke-Capsule 'forward_versioned_capture.py' @('--root',$stateRoot,'--session-date',$SessionDate,'--mode','prepare-policy','--confirm-versioned-research') @('VERSION_POLICY_PREPARED')
        Gate 'Prepare'
        @{status='MORNING_GO_SUPERVISED_START_REQUIRED';session_date=$SessionDate;preparation_verified=$true;tasks_enabled=$false;next_action='Start before09:20:30; leave this interactive PC awake';approval_authority=$false} | ConvertTo-Json -Compress
        exit 0
    }
    $phase = 'SUPERVISED_ADMISSION'
    if (-not $ConfirmNotificationSeen -or -not $ConfirmEnableAfterTwoPolls) { Stop-Daily 'OWNER_VISIBLE_NOTIFICATION_AND_CONDITIONAL_ENABLE_CONFIRMATION_REQUIRED' }
    # Verify frozen recipe/config using existing SELECT/read-only validators, no Producer.
    $preparedCode = "import sys; sys.path.insert(0,sys.argv[1]); from datetime import date; from forward_morning_readiness import ReadinessSpec,_prepared; s=ReadinessSpec(date.fromisoformat(sys.argv[2]),sys.argv[1],sys.argv[3],sys.argv[4],sys.argv[5]); assert _prepared(s)=='VERIFIED'"
    $null = Run-Text $codePython @('-I','-B','-c',$preparedCode,$codeRoot,$SessionDate,$codePython,$stateRoot,$opsRoot)
    Gate 'Start'
    # Exclusive, persistent no-retry claim OUTSIDE capture state. Never deleted/reset.
    Write-NewOpsRecord ($SessionDate + '-guided-morning-v1.attempt') 'STARTED_OUTCOME_UNKNOWN_UNTIL_VERIFIED_RECEIPTS'
    $pollProofs = @()
    foreach ($point in @(@('09:20:30',1),@('09:25:30',2))) {
        $phase = 'WAIT_' + [string]$point[0]
        Wait-Slot ([string]$point[0])
        $phase = 'ONE_POLL_' + [string]$point[0]
        $report = Invoke-Capsule 'forward_session_ops.py' ($common + @('--mode','poll','--confirm-ops','--notify-local')) @('POLL_REMOTE_VERIFIED')
        Accept-Poll $report ([int]$point[1])
        $pollProofs += (Report-Digest ($report | ConvertTo-Json -Compress))
        Write-Output ($report | ConvertTo-Json -Compress)
    }
    $phase = 'AUDIT_FIRST_POLL_LAST_ENABLE'
    $enableEnd = [DateTime]::ParseExact("$SessionDate 09:30",'yyyy-MM-dd HH:mm',[Globalization.CultureInfo]::InvariantCulture)
    if ((Now-Ist) -ge $enableEnd) { Stop-Daily 'ENABLE_DEADLINE_MISSED' }
    # All potentially slow admission reads precede polling's final commit attempt.
    # The frozen preflight CLI stops at09:15; call its unchanged host function,
    # with this controller's explicit date/deadline and literal-fact validator.
    $phase = 'FRESH_ADMISSION_HEALTH'
    $null = Run-Text $codePython @('-I','-B','-c',$preparedCode,$codeRoot,$SessionDate,$codePython,$stateRoot,$opsRoot)
    Assert-Capsule
    $healthCode = "import json,runpy,sys; from pathlib import Path; from datetime import date; sys.path.insert(0,sys.argv[1]); from forward_ops_host import preflight,MIN_FREE_BYTES; r=preflight(date.fromisoformat(sys.argv[2]),sys.argv[3],sys.argv[4],Path(sys.argv[6]),root=Path(sys.argv[5]),ops=Path(sys.argv[6])); m=runpy.run_path(sys.argv[7]); ok=m['accepted_admission_health'](r,sys.argv[3],sys.argv[4],MIN_FREE_BYTES); r.update(dict(status='BLOCKED',code='ADMISSION_HEALTH_NOT_VERIFIED')) if not ok and r.get('status')=='PREOPEN_HOST_CHECK_PASSED' else None; print(json.dumps(r)); sys.exit(0 if ok else 2)"
    $health = Run-Json $codePython @('-I','-B','-c',$healthCode,$codeRoot,$SessionDate,$pollName,$auditName,$stateRoot,$opsRoot,(Join-Path $PSScriptRoot 'forward_daily_contract.py')) @('PREOPEN_HOST_CHECK_PASSED')
    if ((Now-Ist) -ge $enableEnd) { Stop-Daily 'ENABLE_DEADLINE_MISSED' }
    $phase = 'AUDIT_TASK_ENABLE_AND_VERIFY'
    Assert-Task $auditName $false; Assert-Task $pollName $false
    Enable-ScheduledTask -TaskPath '\' -TaskName $auditName -ErrorAction Stop | Out-Null
    Assert-Task $auditName $true
    if ((Now-Ist) -ge $enableEnd) { Stop-Daily 'ENABLE_DEADLINE_MISSED' }
    $phase = 'OWNER_AUTHORISED_COMMIT_ATTEMPT'
    $witness = @{status='ADMISSION_VERIFIED_ENABLE_SUBMISSION_AUTHORISED';session_date=$SessionDate;reviewed_producer_commit=$base;poll_task=$pollName;audit_task=$auditName;poll_report_sha256=$pollProofs;health_report_sha256=(Report-Digest ($health | ConvertTo-Json -Depth 8 -Compress));task_plan_sha256=(Report-Digest ([string]$taskPlans.plans.$pollName));proof_scope='LOCAL_PROCESS_REPORTS_NOT_CUSTODY_OR_EXECUTION';enable_result='NOT_ESTABLISHED';approval_authority=$false;training_eligible=$false}
    Write-NewOpsRecord ($SessionDate + '-guided-activation-v1.json') ($witness | ConvertTo-Json -Depth 8 -Compress)
    if ((Now-Ist) -ge $enableEnd) { Stop-Daily 'ENABLE_DEADLINE_MISSED' }
    $phase = 'POLL_ENABLE_COMMIT_ATTEMPT'
    # A service call can take effect before its acknowledgement fails. Claim the
    # possible effect BEFORE calling it, so unknown outcomes also require rollback.
    $pollEnableAttemptedByThisRun = $true
    Enable-ScheduledTask -TaskPath '\' -TaskName $pollName -ErrorAction Stop | Out-Null
    # No child process, task query or filesystem read may block after submission.
    # Missing/late acknowledgement is UNKNOWN, not proof of automatic disarming.
    if ((Now-Ist) -ge $enableEnd) { Stop-Daily 'ENABLE_DEADLINE_MISSED' }
    $pollEnableCommitted = $true
    @{status='POLL_ENABLE_ACKNOWLEDGED_AFTER_VERIFIED_ADMISSION';session_date=$SessionDate;expected_first_automatic_trigger='09:30:30';audit_trigger='15:40';enable_proof='TASK_SCHEDULER_ACKNOWLEDGEMENT_ONLY';poll_enabled_readback_verified=$false;next_trigger_readback_verified=$false;first_trigger_execution_verified=$false;remote_custody_verified=$false;training_eligible=$false;approval_authority=$false} | ConvertTo-Json -Compress
    exit 0
} catch {
    if ($pollEnableAttemptedByThisRun -and -not $pollEnableCommitted -and -not $rollbackAttempted) { Undo-PollEnable }
    $code = if ($_.Exception.Message -cin $publicCodes) { $_.Exception.Message } else { 'DAILY_OWNER_REVIEW_REQUIRED_NO_RETRY' }
    $fix = switch -Regex ($code) {
        '^NORMAL_NON_ADMIN' { 'Close the elevated shell. Open NORMAL PowerShell; do not change permissions.'; break }
        'CLOCK|WINDOWS_TIME' { 'Keep capture off. Inspect/resync Windows Time as owner, then require the unchanged fresh NTP gate. No blind poll retry.'; break }
        'DOWNLOAD|OWNER_CLOSE' { 'Download the official prior-session CSV on this session morning; supply its ACTUAL completion timestamp. Never relabel an evening download.'; break }
        'DISK|PERMISSIONS' { 'Keep capture off. Review storage/permissions privately; this tool does not repair ACLs or delete data.'; break }
        'DEADLINE|CATCHUP' { 'Keep future polling disabled. Preserve any partial evidence; no catch-up or same-slot retry.'; break }
        default { 'Keep tasks disabled or check rollback status. Inspect this stage and redacted operations reports; do not reset a marker, recipe or journal.' }
    }
    if ($rollback -eq 'FUTURE_POLL_DISABLE_UNCONFIRMED_OWNER_CHECK_REQUIRED') {
        $fix = 'Task state is UNKNOWN: inspect actual polling state as owner. Do not assume disabled, retry Start, remove markers or catch up.'
    }
    @{status='BLOCKED';code=$code;blockers=$publicBlockers;stage=$phase;owner_step=$fix;rollback=$rollback;raw_error_printed=$false;catchup_allowed=$false;same_slot_retry_allowed=$false;approval_authority=$false} | ConvertTo-Json -Compress
    exit 2
} finally {
    # Pipeline cancellation bypasses catch. This also covers cooperative Ctrl+C;
    # hard process termination/power loss still require an owner state check.
    if ($pollEnableAttemptedByThisRun -and -not $pollEnableCommitted -and -not $rollbackAttempted) { Undo-PollEnable }
}
