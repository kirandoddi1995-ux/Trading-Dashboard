[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$SessionDate,
    [ValidateSet('TaskStatus','HostRisk','AlertDrill','AwakeDrill','AwakeLease')][string]$Action='TaskStatus',
    [switch]$ConfirmReadOnly,
    [switch]$ConfirmAfterSession,
    [switch]$ConfirmNoCaptureRunning,
    [switch]$ConfirmAwakeLease
)
$ErrorActionPreference='Stop'

function Task-Time($Value) {
    if ($null -eq $Value -or ($Value -is [string] -and [string]::IsNullOrWhiteSpace($Value))) {
        return @{value=$null;status='NOT_REPORTED'}
    }
    if ($Value -isnot [datetime] -or $Value -eq [datetime]::MinValue) {
        return @{value=$null;status='UNCLASSIFIED_OR_UNSET'}
    }
    return @{value=$Value.ToString('o');status='REPORTED_LOCAL_MACHINE_TIME'}
}

function Task-Summary([string]$Day) {
    $stamp = $Day.Replace('-','')
    $rows = @()
    foreach ($role in @('poll','audit')) {
        $name = 'KiranTrading-Versioned-' + $stamp + '-' + $role
        $task = Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue
        if ($null -eq $task) { $rows += @{role=$role;exists=$null;status='ABSENT_OR_QUERY_UNAVAILABLE'}; continue }
        $info = Get-ScheduledTaskInfo -TaskPath '\' -TaskName $name -ErrorAction Stop
        $state = [string]$task.State
        if ($state -notin @('Disabled','Ready','Running','Queued')) {$state='UNKNOWN'}
        $enabled = $null
        if ($task.Settings.Enabled -is [bool]) {$enabled=$task.Settings.Enabled}
        $last = Task-Time $info.LastRunTime
        $next = Task-Time $info.NextRunTime
        $lastResult=$null
        if ($info.LastTaskResult -is [int32] -or $info.LastTaskResult -is [uint32] -or
            $info.LastTaskResult -is [int64] -or $info.LastTaskResult -is [int16] -or
            $info.LastTaskResult -is [uint16] -or $info.LastTaskResult -is [byte]) {
            $lastResult=[long]$info.LastTaskResult
        }
        $rows += @{role=$role;exists=$true;state=$state;enabled=$enabled;
            last_result=$lastResult;last_run=$last.value;last_run_status=$last.status;
            next_run=$next.value;next_run_status=$next.status;binding_verified=$false}
    }
    return @{status='TASK_STATE_OBSERVED_NOT_EXECUTION_PROOF';tasks=$rows;task_mutations=0;
        command_values_printed=$false;approval_authority=$false}
}

function Drill-Allowed([datetime]$Now,[string]$Day,[bool]$After,[bool]$Idle) {
    return ($After -and $Idle -and $Now.ToString('yyyy-MM-dd') -ceq $Day -and $Now.Hour -ge 16)
}

function Lease-Allowed([datetime]$Now,[string]$Day,[bool]$Confirmed) {
    return ($Confirmed -and $Now.ToString('yyyy-MM-dd') -ceq $Day -and
        $Now.TimeOfDay -ge [timespan]::FromHours(7) -and
        $Now.TimeOfDay -lt [timespan]::FromHours(9.25))
}

function Hold-Lease([datetime]$Finish,[scriptblock]$Acquire,[scriptblock]$Release,
                    [scriptblock]$At,[scriptblock]$Pause,[switch]$Once) {
    $held = $false
    try {
        if (-not (& $Acquire)) {throw 'AWAKE_REQUEST_FAILED'}
        $held = $true
        @{status='PROCESS_AWAKE_LEASE_REQUESTED';automatic_idle_sleep_request=$true;
            update_restart_prevented=$false;manual_sleep_prevented=$false;lid_close_prevented=$false;
            persistent_settings_changed=$false;capture_go=$false} | ConvertTo-Json -Compress
        $timer = [Diagnostics.Stopwatch]::StartNew()
        while (-not $Once -and $timer.Elapsed.TotalHours -lt 9) {
            if ((& $At) -ge $Finish) {break}
            & $Pause
        }
    } finally {
        if ($held) {
            $released = & $Release
            @{status='PROCESS_AWAKE_LEASE_RELEASE_ATTEMPTED';release_acknowledged=($released -eq $true);
                persistent_settings_changed=$false} | ConvertTo-Json -Compress
            if ($released -ne $true) {throw 'AWAKE_RELEASE_UNCONFIRMED'}
        }
    }
}

try {
    $null = [datetime]::ParseExact($SessionDate,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture)
    $confirmed = ($Action -in @('TaskStatus','HostRisk') -and $ConfirmReadOnly) -or
        ($Action -in @('AlertDrill','AwakeDrill') -and $ConfirmAfterSession -and $ConfirmNoCaptureRunning) -or
        ($Action -ceq 'AwakeLease' -and $ConfirmAwakeLease)
    if (-not $confirmed) {
        @{status='PREVIEW';action=$Action;task_queries=0;task_mutations=0;capture_reads=0;
            notification_calls=0;power_requests=0;writes=0} | ConvertTo-Json -Compress
        exit 0
    }
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {throw 'WINDOWS_REQUIRED'}
    $admin = ([Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if ($admin) {throw 'NORMAL_NON_ADMIN_WINDOW_REQUIRED'}
    # Do not assume the Windows configured timezone is IST.
    $now = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([datetime]::UtcNow,'India Standard Time')
    if ($Action -ceq 'TaskStatus') {
        Task-Summary $SessionDate | ConvertTo-Json -Depth 5 -Compress
    } elseif ($Action -ceq 'HostRisk') {
        $keys = @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending',
            'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')
        $pending=$false
        foreach ($key in $keys) {if (Test-Path -LiteralPath $key -ErrorAction Stop) {$pending=$true}}
        @{status='READ_ONLY_RESTART_RISK_SIGNALS';known_pending_reboot_signal=$pending;
            no_restart_guaranteed=$false;active_hours_verified=$false;power_policy_verified=$false;
            setting_mutations=0;capture_reads=0;task_mutations=0} | ConvertTo-Json -Compress
    } elseif ($Action -ceq 'AlertDrill') {
        if (-not (Drill-Allowed $now $SessionDate $ConfirmAfterSession.IsPresent $ConfirmNoCaptureRunning.IsPresent)) {throw 'POSTSESSION_IDLE_ATTESTATION_REQUIRED'}
        Add-Type -AssemblyName System.Windows.Forms
        $answer = [System.Windows.Forms.MessageBox]::Show(
            'SYNTHETIC DELIVERY TEST ONLY. Capture is not failing. Choose Yes only if you can see and read this test.',
            'Synthetic capture alert rehearsal',[System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Information)
        @{status='SYNTHETIC_ALERT_DRILL_COMPLETED';owner_clicked_yes=([string]$answer -ceq 'Yes');
            production_blocked_poll_delivery_verified=$false;dedup_and_failure_routing_verified=$false;
            capture_reads=0;task_mutations=0;writes=0;approval_authority=$false} | ConvertTo-Json -Compress
    } else {
        if ($Action -ceq 'AwakeDrill') {
            if (-not (Drill-Allowed $now $SessionDate $ConfirmAfterSession.IsPresent $ConfirmNoCaptureRunning.IsPresent)) {throw 'POSTSESSION_IDLE_ATTESTATION_REQUIRED'}
        } elseif (-not (Lease-Allowed $now $SessionDate $ConfirmAwakeLease.IsPresent)) {throw 'PREOPEN_AWAKE_LEASE_ONLY'}
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ForwardObserverPower {
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern uint SetThreadExecutionState(uint flags);
}
'@
        $finish = [datetime]::ParseExact($SessionDate + ' 15:50','yyyy-MM-dd HH:mm',[Globalization.CultureInfo]::InvariantCulture)
        if ($Action -ceq 'AwakeDrill') {$finish=$now}
        Hold-Lease $finish { $script:priorPowerFlags=[ForwardObserverPower]::SetThreadExecutionState([uint32]2147483649); $script:priorPowerFlags -ne 0 } `
            { [ForwardObserverPower]::SetThreadExecutionState([uint32]($script:priorPowerFlags -bor [uint32]2147483648)) -ne 0 } `
            { [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([datetime]::UtcNow,'India Standard Time') } `
            { Start-Sleep -Seconds 10 } -Once:($Action -ceq 'AwakeDrill')
    }
} catch {
    $allowed = @('WINDOWS_REQUIRED','NORMAL_NON_ADMIN_WINDOW_REQUIRED','POSTSESSION_IDLE_ATTESTATION_REQUIRED',
        'PREOPEN_AWAKE_LEASE_ONLY','AWAKE_REQUEST_FAILED','AWAKE_RELEASE_UNCONFIRMED')
    $code = 'OBSERVER_TOOL_UNAVAILABLE'
    if ($_.Exception.Message -cin $allowed) {$code=$_.Exception.Message}
    @{status='BLOCKED';code=$code;raw_error_printed=$false;task_mutations=0;capture_writes=0} | ConvertTo-Json -Compress
    exit 2
}
