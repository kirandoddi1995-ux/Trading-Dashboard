param(
    [Parameter(Mandatory=$true)][string]$SessionDate,
    [switch]$ConfirmReadOnly
)
# Owner-only narrow read: no capture/config/state/ACL reads, task mutation or XML output.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-BindingSelectors {
    return [ordered]@{
        command='/t:Task/t:Actions/t:Exec/t:Command'
        arguments='/t:Task/t:Actions/t:Exec/t:Arguments'
        working_directory='/t:Task/t:Actions/t:Exec/t:WorkingDirectory'
        user_id='/t:Task/t:Principals/t:Principal/t:UserId'
        logon_type='/t:Task/t:Principals/t:Principal/t:LogonType'
        run_level='/t:Task/t:Principals/t:Principal/t:RunLevel'
        trigger_enabled='/t:Task/t:Triggers/t:TimeTrigger/t:Enabled'
        multiple_instances='/t:Task/t:Settings/t:MultipleInstancesPolicy'
        start_when_available='/t:Task/t:Settings/t:StartWhenAvailable'
        execution_time_limit='/t:Task/t:Settings/t:ExecutionTimeLimit'
        wake_to_run='/t:Task/t:Settings/t:WakeToRun'
        disallow_battery_start='/t:Task/t:Settings/t:DisallowStartIfOnBatteries'
        stop_on_battery='/t:Task/t:Settings/t:StopIfGoingOnBatteries'
        start_boundary='/t:Task/t:Triggers/t:TimeTrigger/t:StartBoundary'
        end_boundary='/t:Task/t:Triggers/t:TimeTrigger/t:EndBoundary'
        repeat_interval='/t:Task/t:Triggers/t:TimeTrigger/t:Repetition/t:Interval'
        repeat_duration='/t:Task/t:Triggers/t:TimeTrigger/t:Repetition/t:Duration'
        repeat_stop='/t:Task/t:Triggers/t:TimeTrigger/t:Repetition/t:StopAtDurationEnd'
        settings_enabled='/t:Task/t:Settings/t:Enabled'
        idle_condition='/t:Task/t:Settings/t:RunOnlyIfIdle'
        network_condition='/t:Task/t:Settings/t:RunOnlyIfNetworkAvailable'
        random_delay='/t:Task/t:Triggers/t:TimeTrigger/t:RandomDelay'
        restart='/t:Task/t:Settings/t:RestartOnFailure'
    }
}

function Read-BindingShape([string]$Text) {
    if ($Text.Length -gt 65536 -or $Text -match '<!') { throw [InvalidOperationException]::new('TASK_XML_STRUCTURE_UNAVAILABLE') }
    $xml = [xml]::new(); $xml.XmlResolver = $null; $xml.LoadXml($Text)
    $ns = [Xml.XmlNamespaceManager]::new($xml.NameTable)
    $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
    if ($xml.SelectNodes('/t:Task',$ns).Count -ne 1) { throw [InvalidOperationException]::new('TASK_XML_STRUCTURE_UNAVAILABLE') }
    $rows = @()
    foreach ($entry in (Get-BindingSelectors).GetEnumerator()) {
        $count = $xml.SelectNodes($entry.Value,$ns).Count
        $rows += @{field=$entry.Key;count=$count}
    }
    return @{status='FIELD_COUNTS_ONLY_NOT_BINDING_ACCEPTANCE';fields=$rows}
}

function Read-DatedTask([string]$Name,[string]$Role) {
    # Exact literal names only; no task-tree enumeration or inspection of legacy tasks.
    try {
        $queryError = @()
        $task = Get-ScheduledTask -TaskPath '\' -TaskName $Name -ErrorAction SilentlyContinue -ErrorVariable queryError
        if (-not $task) {
            $unavailable = @($queryError | Where-Object { $_.CategoryInfo.Category -ne [Management.Automation.ErrorCategory]::ObjectNotFound }).Count -gt 0
            return @{role=$Role;exists=$(if ($unavailable) {$null} else {$false});status=$(if ($unavailable) {'TASK_QUERY_UNAVAILABLE'} else {'NOT_FOUND'})}
        }
        $state = if ([string]$task.State -cin @('Disabled','Ready','Running','Queued','Unknown')) {[string]$task.State} else {'UNCLASSIFIED'}
        $enabled = if ($task.Settings.Enabled -is [bool]) {[bool]$task.Settings.Enabled} else {$null}
        $shape = Read-BindingShape ([string](Export-ScheduledTask -TaskPath '\' -TaskName $Name -ErrorAction Stop))
        return @{role=$Role;exists=$true;status=$shape.status;enabled=$enabled;state=$state;
            actions=@($task.Actions).Count;triggers=@($task.Triggers).Count;fields=$shape.fields}
    } catch {
        return @{role=$Role;exists=$null;status='TASK_QUERY_OR_XML_UNAVAILABLE';raw_error_printed=$false}
    }
}

try {
    if ($SessionDate -cnotmatch '^\d{4}-\d{2}-\d{2}$') { throw [InvalidOperationException]::new('SESSION_DATE_INVALID') }
    $day = [DateTime]::ParseExact($SessionDate,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture)
    if (-not $ConfirmReadOnly) {
        @{status='PREVIEW';task_queries=0;task_exports=0;task_mutations=0;operational_writes=0;credential_reads=0;approval_authority=$false} | ConvertTo-Json -Compress
        exit 0
    }
    if ($env:OS -cne 'Windows_NT') { throw [InvalidOperationException]::new('WINDOWS_OWNER_READ_ONLY_REQUIRED') }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw [InvalidOperationException]::new('NORMAL_WINDOW_REQUIRED') }
    $prefix = 'KiranTrading-Versioned-' + $day.ToString('yyyyMMdd')
    $rows = @((Read-DatedTask ($prefix+'-poll') 'poll'),(Read-DatedTask ($prefix+'-audit') 'audit'))
    @{status='READ_ONLY_TASK_BINDING_SHAPES';tasks=$rows;task_mutations=0;operational_writes=0;credential_reads=0;
        capture_invocations=0;binding_acceptance=$false;raw_values_printed=$false;approval_authority=$false} | ConvertTo-Json -Depth 7 -Compress
    exit 0
} catch {
    @{status='BLOCKED';code='READ_ONLY_TASK_DIAGNOSTIC_UNAVAILABLE';task_mutations=0;operational_writes=0;
        credential_reads=0;raw_error_printed=$false;approval_authority=$false} | ConvertTo-Json -Compress
    exit 2
}
