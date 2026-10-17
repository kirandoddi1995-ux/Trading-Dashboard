[CmdletBinding()]
param([switch]$ConfirmReadOnly)
$ErrorActionPreference='Stop'

# Fixed historical attempt only. No controller import, worker invocation or JSON
# contents are read. Presence is unsigned evidence, not a validated route.
function Assert-OutcomePath([string]$Path) {
    if (-not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\') -or $Path.StartsWith('//')) {throw 'LOCAL_ABSOLUTE_ROOT_REQUIRED'}
    $cursor=$Path
    while (-not [string]::IsNullOrEmpty($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item=Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {throw 'LINKED_STATE_REJECTED'}
        }
        $cursor=[IO.Path]::GetDirectoryName($cursor)
    }
}

function Read-OutcomeMetadata([string]$Path) {
    Assert-OutcomePath $Path
    if (-not (Test-Path -LiteralPath $Path)) {return @{present=$false;bytes=$null}}
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or $item.Length -gt 1048576) {throw 'BOUNDED_REGULAR_MARKER_REQUIRED'}
    return @{present=$true;bytes=[long]$item.Length}
}

function Get-OutcomeResult($Value) {
    if (($Value -isnot [int32] -and $Value -isnot [uint32] -and $Value -isnot [int64]) -or
        [long]$Value -lt 0 -or [long]$Value -gt 4294967295) {throw 'NATIVE_RESULT_NOT_ESTABLISHED'}
    $number=[long]$Value
    $category=switch ($number) {
        0 {'ZERO_NOT_SYNTHETIC_COMPLETION'}
        2 {'TWO_AMBIGUOUS_WITHOUT_WORKER_WITNESS'}
        267009 {'SCHEDULER_REPORTS_RUNNING'}
        267011 {'SCHEDULER_REPORTS_NOT_YET_RUN'}
        267014 {'SCHEDULER_REPORTS_TERMINATED'}
        default {'OTHER_NATIVE_RESULT_REVIEW_REQUIRED'}
    }
    return @{decimal=$number;hex=('0x{0:X8}' -f $number);category=$category}
}

function Invoke-PreservedOutcome([string]$LocalRoot) {
    $taskName='ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697'
    $root=Join-Path $LocalRoot 'KiranTrading/AlertDrills/389daf12415a482eb0231443ddfd8697'
    Assert-OutcomePath $root
    $script:outcomeStage='EXACT_TASK_QUERY'
    $script:taskQueries++
    $tasks=@(Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop)
    if ($tasks.Count -ne 1) {throw 'EXACT_TASK_QUERY_NOT_ESTABLISHED'}
    $task=$tasks[0]
    if ($task.Settings.Enabled -isnot [bool]) {throw 'TYPED_TASK_STATE_REQUIRED'}
    $state=[string]$task.State
    if ($state -cnotin @('Disabled','Ready','Running','Queued','Unknown')) {throw 'TYPED_TASK_STATE_REQUIRED'}
    $script:outcomeStage='EXACT_TASK_RESULT_QUERY'
    $script:taskQueries++
    $info=Get-ScheduledTaskInfo -TaskPath '\' -TaskName $taskName -ErrorAction Stop
    $result=Get-OutcomeResult $info.LastTaskResult
    $lastRun=if ($info.LastRunTime -is [datetime]) {$info.LastRunTime.ToString('o')} else {$null}
    $script:outcomeStage='FIXED_MARKER_METADATA'
    $files=[ordered]@{}
    foreach ($name in @('recipe.json','recovery-admission.json','controller-attempt.json','attempt.json','task-witness.json','owner-ack.json')) {
        $files[$name]=Read-OutcomeMetadata (Join-Path $root $name)
    }
    $reports=Join-Path $root 'reports'
    Assert-OutcomePath $reports
    $reportCount=0;$unrecognised=0
    if (Test-Path -LiteralPath $reports) {
        if (-not (Get-Item -LiteralPath $reports -Force -ErrorAction Stop).PSIsContainer) {throw 'REPORT_DIRECTORY_REQUIRED'}
        $enumerator=[IO.Directory]::EnumerateFileSystemEntries($reports).GetEnumerator()
        try {
            $seen=0
            while ($enumerator.MoveNext()) {
                $seen++
                if ($seen -gt 16) {throw 'REPORT_ENTRY_BOUND_EXCEEDED'}
                $entry=[string]$enumerator.Current
                $null=Read-OutcomeMetadata $entry
                if ([IO.Path]::GetFileName($entry) -cmatch '^2026-10-17-[a-f0-9]{32}\.json$') {$reportCount++}
                elseif ([IO.Path]::GetFileName($entry) -cnotmatch '^2026-10-17-v2-CLOCK_REVIEW_REQUIRED-[a-f0-9]{16}-1\.(alert|launch)$') {$unrecognised++}
            }
        } finally {if ($enumerator -is [IDisposable]) {$enumerator.Dispose()}}
    }
    # The original worker uses these exact names. Read metadata, never contents.
    $tokens='["CLOCK_UNVERIFIED", "CLOCK_CHECK", "SYNTHETIC_FAILURE_ONLY"]'
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$identity=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($tokens)))).Replace('-','').ToLowerInvariant().Substring(0,16)}
    finally {$sha.Dispose()}
    $stem='2026-10-17-v2-CLOCK_REVIEW_REQUIRED-'+$identity+'-1'
    $alert=Read-OutcomeMetadata (Join-Path $reports ($stem+'.alert'))
    $launch=Read-OutcomeMetadata (Join-Path $reports ($stem+'.launch'))
    $phase=if (-not $files['controller-attempt.json'].present) {'CONTROLLER_MARKER_ABSENT'}
        elseif (-not $files['attempt.json'].present) {'WORKER_CLAIM_MARKER_ABSENT_CAUSE_UNKNOWN'}
        elseif ($reportCount -eq 0) {'WORKER_CLAIM_PRESENT_REPORT_ABSENT'}
        elseif (-not $launch.present) {'REPORT_PRESENT_LAUNCH_MARKER_ABSENT'}
        elseif (-not $files['task-witness.json'].present) {'LAUNCH_MARKER_PRESENT_NATIVE_WITNESS_ABSENT'}
        else {'WITNESS_METADATA_PRESENT_NOT_VALIDATED'}
    return @{status='PRESERVED_OUTCOME_READ_ONLY_NOT_RUN_ADMISSION';phase=$phase;
        task_exists=$true;task_disabled=($task.Settings.Enabled -eq $false -and $state -ceq 'Disabled');
        task_state=$state;last_result=$result;last_run_local=$lastRun;files=$files;report_count=$reportCount;
        unrecognised_report_entries=$unrecognised;alert_marker=$alert;launch_marker=$launch;
        snapshot_atomic=$false;metadata_authenticated=$false;worker_cause='NOT_ESTABLISHED';
        task_queries=$script:taskQueries;task_mutations=0;operational_writes=0;credential_reads=0;capture_invocations=0;
        retry_authorised=$false;replacement_id_authorised=$false;production_failure_verified=$false;
        popup_delivery_verified=$false;raw_values_printed=$false;approval_authority=$false}
}

if (-not $ConfirmReadOnly) {
    @{status='PREVIEW';task_queries=0;task_mutations=0;operational_writes=0;credential_reads=0;capture_invocations=0}|ConvertTo-Json -Compress
    exit 0
}
$script:outcomeStage='HOST_CHECK';$script:taskQueries=0
try {
    if ($env:OS -cne 'Windows_NT') {throw 'WINDOWS_REQUIRED'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'NORMAL_WINDOW_REQUIRED'}
    if ($env:LOCALAPPDATA -cnotmatch '^[A-Za-z]:[\\/]') {throw 'LOCAL_ABSOLUTE_ROOT_REQUIRED'}
    Invoke-PreservedOutcome $env:LOCALAPPDATA|ConvertTo-Json -Compress -Depth 7
    exit 0
} catch {
    $known=@('WINDOWS_REQUIRED','NORMAL_WINDOW_REQUIRED','LOCAL_ABSOLUTE_ROOT_REQUIRED','LINKED_STATE_REJECTED',
        'BOUNDED_REGULAR_MARKER_REQUIRED','NATIVE_RESULT_NOT_ESTABLISHED','EXACT_TASK_QUERY_NOT_ESTABLISHED',
        'TYPED_TASK_STATE_REQUIRED','REPORT_DIRECTORY_REQUIRED','REPORT_ENTRY_BOUND_EXCEEDED')
    $reason=if ($_.Exception.Message -cin $known) {$_.Exception.Message} else {'READ_ONLY_QUERY_NOT_ESTABLISHED'}
    @{status='BLOCKED';stage=$script:outcomeStage;reason=$reason;task_queries=$script:taskQueries;
        task_mutations=0;operational_writes=0;credential_reads=0;capture_invocations=0;raw_values_printed=$false;
        retry_authorised=$false;replacement_id_authorised=$false;approval_authority=$false}|ConvertTo-Json -Compress
    exit 2
}
