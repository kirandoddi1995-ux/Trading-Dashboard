[CmdletBinding()]
param([string]$OldToolsRoot='',[string]$Python='',
      [switch]$ConfirmNoCaptureRunning,[switch]$ConfirmFirstExecution)
$ErrorActionPreference='Stop'
if (-not $ConfirmFirstExecution) {
    @{status='PREVIEW';reads=0;task_queries=0;task_mutations=0;operational_writes=0}|ConvertTo-Json -Compress
    exit 0
}

function Read-BridgeHash([string]$Path) {
    if ($Path -cnotmatch '^[A-Za-z]:[\\/]') {throw 'EXPLICIT_PATHS_REQUIRED'}
    $item=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or $item.Length -gt 1048576) {throw 'PINNED_REGULAR_FILE_REQUIRED'}
    $cursor=$item
    while ($null -ne $cursor) {
        if (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {throw 'LINKED_PATH_REJECTED'}
        if ($cursor -is [IO.FileInfo]) {$cursor=$cursor.Directory} else {$cursor=$cursor.Parent}
    }
    $text=[IO.File]::ReadAllText($Path).Replace("`r`n","`n")
    $after=Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if ($after.Length -ne $item.Length -or $after.LastWriteTimeUtc -ne $item.LastWriteTimeUtc) {throw 'READ_CHANGED'}
    $sha=[Security.Cryptography.SHA256]::Create()
    try {return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))).Replace('-','').ToLowerInvariant()}
    finally {$sha.Dispose()}
}

function Read-FirstRunIst {
    return [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([datetime]::UtcNow,'India Standard Time')
}

function Assert-FirstRunDate([datetime]$Now) {
    if ($Now.ToString('yyyy-MM-dd') -cne '2026-10-17') {throw 'ORIGINAL_IST_DAY_ONLY_NO_REBASE'}
}

function Enable-ScheduledTask {
    param($TaskPath,$TaskName,$ErrorAction)
    if ($TaskPath -cne '\' -or $TaskName -cne 'ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697') {throw 'EXACT_SYNTHETIC_MUTATION_TARGET_REQUIRED'}
    Assert-FirstRunDate (& $script:bridgeClock)
    & $script:bridgeNativeEnable -TaskPath $TaskPath -TaskName $TaskName -ErrorAction $ErrorAction
}

function Start-ScheduledTask {
    param($TaskPath,$TaskName,$ErrorAction)
    if ($TaskPath -cne '\' -or $TaskName -cne 'ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697') {throw 'EXACT_SYNTHETIC_MUTATION_TARGET_REQUIRED'}
    Assert-FirstRunDate (& $script:bridgeClock)
    & $script:bridgeNativeStart -TaskPath $TaskPath -TaskName $TaskName -ErrorAction $ErrorAction
}

function Invoke-PreservedFirstRun([string]$Root,[scriptblock]$Clock,[bool]$Idle,
        [scriptblock]$Audit,[scriptblock]$Run,[scriptblock]$Inspect,$Admission) {
    $Now=& $Clock
    Assert-DrillWindow $Now $Idle
    Assert-FirstRunDate $Now
    $script:phase='FRESH_FULL_READ_ONLY_AUDIT'
    $review=& $Audit
    if ($review.status -cne 'PRESERVED_DRILL_FULL_READ_ONLY_REVIEW_NOT_RUN_ADMISSION') {throw 'FULL_REVIEW_REQUIRED'}
    foreach ($field in @('source_integrity','task_binding','disabled_verified','recipe_consistency','same_ist_day')) {
        if ($review.$field -isnot [bool] -or $review.$field -ne $true) {throw 'FULL_REVIEW_REQUIRED'}
    }
    foreach ($field in @('historical_recipe','run_authorised','replacement_id_authorised')) {
        if ($review.$field -isnot [bool] -or $review.$field -ne $false) {throw 'FULL_REVIEW_REQUIRED'}
    }
    foreach ($name in @('recovery-admission.json','controller-attempt.json','attempt.json','task-witness.json','owner-ack.json')) {
        if (Test-Path -LiteralPath (Join-Path $Root $name)) {throw 'PRESERVED_ATTEMPT_ALREADY_CONSUMED'}
    }
    $fresh=& $Clock
    Assert-DrillWindow $fresh $Idle
    Assert-FirstRunDate $fresh
    $script:phase='EXCLUSIVE_FIRST_EXECUTION_ADMISSION'
    $Admission.admission_clock_ist=$fresh.ToString('o')
    Write-DrillWitness (Join-Path $Root 'recovery-admission.json') $Admission
    # A write error/uncertain outcome is never retried, even without Enable.
    Assert-FirstRunDate (& $Clock)
    $null=& $Run
    $script:phase='READ_ROUTE_WITNESS'
    $result=& $Inspect
    if ($result.status -cne 'ISOLATED_FAILURE_ROUTE_RECORDED_AWAITING_OWNER_ACK') {throw 'ROUTE_WITNESS_REQUIRED'}
    foreach ($field in @('synthetic','launch_acknowledged','task_disabled_owner_witness')) {
        if ($result.$field -isnot [bool] -or $result.$field -ne $true) {throw 'ROUTE_WITNESS_REQUIRED'}
    }
    foreach ($field in @('production_failure_verified','independent_delivery_verified','owner_acknowledged')) {
        if ($result.$field -isnot [bool] -or $result.$field -ne $false) {throw 'ROUTE_WITNESS_REQUIRED'}
    }
    if (($result.scheduler_result -isnot [int] -and $result.scheduler_result -isnot [long]) -or $result.scheduler_result -ne 2) {throw 'ROUTE_WITNESS_REQUIRED'}
    return $result
}

$script:phase='PINNED_BRIDGE_PREREQUISITES';$script:attemptedEnable=$false;$script:disabledVerified=$false
$script:bindingFailures=@();$taskName='ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697'
try {
    if ($env:OS -cne 'Windows_NT') {throw 'WINDOWS_REQUIRED'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'NORMAL_WINDOW_REQUIRED'}
    if ($OldToolsRoot -cnotmatch '^[A-Za-z]:[\\/]' -or $Python -cnotmatch '^[A-Za-z]:[\\/]') {throw 'EXPLICIT_PATHS_REQUIRED'}
    $version=& $Python -I -B -c 'import sys; print(sys.version.split()[0])'
    if ($LASTEXITCODE -ne 0 -or ([string]$version).Trim() -cne '3.13.9') {throw 'PYTHON_3139_REQUIRED'}
    $pins=@{
        'isolated_alert_task_drill.ps1'='d37bbf5d6fb9e5f650adbe35d7b8cff4811da9a29126268e3f8bcd89f7dd3191';
        'preserved_drill_audit.ps1'='5a64a23d700c9d228592ed7bb3f459a7943a9a7a8ad03cb77baa012a46309ae6';
        'preserved_drill_audit.py'='546c7e2936ba22278f84410b998f59add20ed72fc706dbdd10ebbf0fee5347f6'
    }
    foreach ($name in $pins.Keys) {
        if ((Read-BridgeHash (Join-Path $PSScriptRoot $name)) -cne $pins[$name]) {throw 'REVIEWED_BRIDGE_SOURCE_PIN_REQUIRED'}
    }
    foreach ($source in @('isolated_alert_task_drill.ps1','preserved_drill_audit.ps1')) {
        $errors=$null;$tokens=$null
        $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $source),[ref]$tokens,[ref]$errors)
        if ($errors.Count -ne 0) {throw 'REVIEWED_BRIDGE_SOURCE_PIN_REQUIRED'}
        $names=if ($source -ceq 'isolated_alert_task_drill.ps1') {
            @('Assert-DrillWindow','Drill-Arguments','Assert-DrillTools','Resolve-DrillAccountSid','Test-DrillCurrentUser','Assert-DrillTask','Write-DrillWitness','Invoke-IsolatedDrillRun')
        } else {@('Invoke-PreservedAudit')}
        foreach ($name in $names) {
            $nodes=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
            if ($nodes.Count -ne 1) {throw 'REVIEWED_BRIDGE_SOURCE_PIN_REQUIRED'}
            Invoke-Expression $nodes[0].Extent.Text
        }
    }
    Assert-DrillTools $PSScriptRoot
    $id='389daf12415a482eb0231443ddfd8697'
    $root=Join-Path $env:LOCALAPPDATA ('KiranTrading\AlertDrills\'+$id)
    $worker=Join-Path $OldToolsRoot 'isolated_alert_drill.py'
    $arguments=Drill-Arguments $worker $id
    $script:bridgeClock={Read-FirstRunIst}
    $script:bridgeNativeEnable=Get-Command 'ScheduledTasks\Enable-ScheduledTask' -ErrorAction Stop
    $script:bridgeNativeStart=Get-Command 'ScheduledTasks\Start-ScheduledTask' -ErrorAction Stop
    $now=& $script:bridgeClock
    Assert-DrillWindow $now $ConfirmNoCaptureRunning.IsPresent
    if ($now.ToString('yyyy-MM-dd') -cne '2026-10-17') {throw 'ORIGINAL_IST_DAY_ONLY_NO_REBASE'}
    $child={param([string[]]$Arguments)
        $lines=@(& $Python @Arguments)
        @{exit_code=$LASTEXITCODE;output=($lines -join "`n")}
    }
    $audit={Invoke-PreservedAudit $OldToolsRoot $Python $identity $PSScriptRoot $child}
    $run={Invoke-IsolatedDrillRun $taskName $Python $worker $arguments $OldToolsRoot $identity.User.Value $identity.Name $root $id}
    $inspect={
        $raw=& $Python -I -B $worker --drill-id $id --mode inspect --confirm-drill-only
        if ($LASTEXITCODE -ne 0) {throw 'ROUTE_WITNESS_REQUIRED'}
        $raw|ConvertFrom-Json
    }
    $admission=@{identifier=$id;at=[datetime]::UtcNow.ToString('o');retry_allowed=$false;
        consent='OWNER_CONFIRMED_FIRST_WORKER_EXECUTION_AFTER_READ_ONLY_REVIEW';
        source_set=$pins;recipe_lf_sha256=(Read-BridgeHash (Join-Path $root 'recipe.json'));
        python=$Python;arguments=$arguments;working_directory=$OldToolsRoot;
        authenticated_signature=$false;approval_authority=$false}
    Invoke-PreservedFirstRun $root $script:bridgeClock $ConfirmNoCaptureRunning.IsPresent $audit $run $inspect $admission|ConvertTo-Json -Compress -Depth 5
    exit 0
} catch {
    $known=@('WINDOWS_REQUIRED','NORMAL_WINDOW_REQUIRED','EXPLICIT_PATHS_REQUIRED','PYTHON_3139_REQUIRED',
        'PINNED_REGULAR_FILE_REQUIRED','LINKED_PATH_REJECTED','READ_CHANGED','REVIEWED_BRIDGE_SOURCE_PIN_REQUIRED',
        'POSTSESSION_OR_WEEKEND_AND_IDLE_REQUIRED','ORIGINAL_IST_DAY_ONLY_NO_REBASE','FULL_REVIEW_REQUIRED',
        'PRESERVED_ATTEMPT_ALREADY_CONSUMED','ROUTE_WITNESS_REQUIRED','ISOLATED_RECIPE_PRECHECK_BLOCKED',
        'ISOLATED_TASK_BINDING_REVIEW_REQUIRED','ONE_NEW_DRILL_ATTEMPT_ONLY','SYNTHETIC_COMPLETION_NOT_PROVEN',
        'REVIEWED_CLEAN_TOOLS_ROOT_REQUIRED','REVIEWED_TRACKED_DRILL_FILES_REQUIRED','EXACT_SYNTHETIC_MUTATION_TARGET_REQUIRED')
    $reason=if ($_.Exception.Message -cin $known) {$_.Exception.Message} else {'FIRST_EXECUTION_OUTCOME_NOT_ESTABLISHED'}
    @{status='BLOCKED';stage=$script:phase;reason=$reason;binding_failures=@($script:bindingFailures);
      task_enable_attempted=$script:attemptedEnable;task_disabled_verified=$script:disabledVerified;
      raw_error_printed=$false;retry_authorised=$false;replacement_id_authorised=$false;approval_authority=$false}|ConvertTo-Json -Compress
    exit 2
} finally {
    if ($script:attemptedEnable -and -not $script:disabledVerified) {
        try {Disable-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction Stop|Out-Null} catch {}
    }
}
