[CmdletBinding()]
param([string]$DrillId='',[switch]$ConfirmReadOnly)
$ErrorActionPreference='Stop'
function Invoke-IsolatedReadOnlyReconciliation([string]$DrillId,$Identity,[string]$LocalRoot,[string]$ToolsRoot) {
    if ($DrillId -cnotmatch '^[a-f0-9]{32}$') {throw 'EXACT_SYNTHETIC_ID_REQUIRED'}
    # Parse only these reviewed definitions. Never execute the controller body.
    $errors=$null;$tokens=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $ToolsRoot 'isolated_alert_task_drill.ps1'),[ref]$tokens,[ref]$errors)
    if ($errors.Count -ne 0) {throw 'REVIEWED_HELPER_PARSE_REQUIRED'}
    foreach ($name in @('Resolve-DrillAccountSid','Test-DrillCurrentUser')) {
        $nodes=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
        if ($nodes.Count -ne 1) {throw 'REVIEWED_HELPER_PARSE_REQUIRED'}
        Invoke-Expression $nodes[0].Extent.Text
    }
    $tasks=@(Get-ScheduledTask -TaskPath '\' -TaskName ('ResearchOps-SyntheticAlert-'+$DrillId) -ErrorAction Stop)
    if ($tasks.Count -ne 1) {throw 'TASK_QUERY_NOT_ESTABLISHED'}
    $task=$tasks[0]
    $equal=Test-DrillCurrentUser ([string]$task.Principal.UserId) $identity.User.Value
    $root=Join-Path $LocalRoot ('KiranTrading\AlertDrills\'+$DrillId)
    $cursor=$root
    while (-not [string]::IsNullOrEmpty($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item=Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {throw 'LINKED_STATE_REQUIRES_REVIEW'}
        }
        $cursor=[IO.Path]::GetDirectoryName($cursor)
    }
    $files=[ordered]@{}
    foreach ($name in @('recipe.json','controller-attempt.json','attempt.json','task-witness.json','owner-ack.json')) {
        $file=Join-Path $root $name
        $present=Test-Path -LiteralPath $file
        if ($present) {
            $item=Get-Item -LiteralPath $file -Force -ErrorAction Stop
            if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {throw 'LINKED_STATE_REQUIRES_REVIEW'}
        }
        $files[$name]=$present
    }
    @{status='ISOLATED_READ_ONLY_RECONCILIATION_NOT_RUN_ADMISSION';task_exists=$true;
      task_disabled=($task.Settings.Enabled -eq $false -and [string]$task.State -ceq 'Disabled');
      current_user_sid_equal=$equal;identity_proof=$script:identityProof;
      raw_identity_equal=([string]$task.Principal.UserId -in @($identity.User.Value,$identity.Name));
      trigger_count=@($task.Triggers|Where-Object {$null -ne $_}).Count;
      isolated_root_exists=(Test-Path -LiteralPath $root -PathType Container);files=$files;
      task_queries=1;task_mutations=0;operational_writes=0;credential_reads=0;
      raw_values_printed=$false;retry_authorised=$false;approval_authority=$false}
}
if (-not $ConfirmReadOnly) {
    @{status='PREVIEW';task_queries=0;operational_writes=0;credential_reads=0;task_mutations=0}|ConvertTo-Json -Compress
    exit 0
}
try {
    if ($env:OS -cne 'Windows_NT') {throw 'WINDOWS_REQUIRED'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'NORMAL_WINDOW_REQUIRED'}
    Invoke-IsolatedReadOnlyReconciliation $DrillId $identity $env:LOCALAPPDATA $PSScriptRoot|ConvertTo-Json -Compress -Depth 5
    exit 0
} catch {
    # A query error is NOT evidence of absence. Never enumerate other tasks.
    $known=@('WINDOWS_REQUIRED','NORMAL_WINDOW_REQUIRED','EXACT_SYNTHETIC_ID_REQUIRED','REVIEWED_HELPER_PARSE_REQUIRED','LINKED_STATE_REQUIRES_REVIEW')
    $reason=if ($_.Exception.Message -cin $known) {$_.Exception.Message} else {'READ_ONLY_QUERY_OR_IDENTITY_NOT_ESTABLISHED'}
    @{status='BLOCKED';reason=$reason;raw_values_printed=$false;task_mutations=0;operational_writes=0;retry_authorised=$false}|ConvertTo-Json -Compress
    exit 2
}
