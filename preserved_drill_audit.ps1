[CmdletBinding()]
param([string]$OldToolsRoot='',[string]$Python='',[switch]$ConfirmReadOnly)
$ErrorActionPreference='Stop'
if (-not $ConfirmReadOnly) {
    @{status='PREVIEW';reads=0;task_queries=0;task_mutations=0;operational_writes=0}|ConvertTo-Json -Compress
    exit 0
}
function Invoke-PreservedAudit([string]$OldToolsRoot,[string]$Python,$Identity,[string]$ToolsRoot,[scriptblock]$RunChild) {
    $id='389daf12415a482eb0231443ddfd8697'
    $argv=@('-I','-B',(Join-Path $ToolsRoot 'preserved_drill_audit.py'),'--drill-id',$id,'--old-tools-root',$OldToolsRoot,'--confirm-read-only')
    $child=& $RunChild -Arguments $argv
    if ($child.exit_code -ne 0) {throw 'SOURCE_OR_RECIPE_REVIEW_BLOCKED'}
    try {$recipe=$child.output|ConvertFrom-Json} catch {throw 'SOURCE_OR_RECIPE_REVIEW_BLOCKED'}
    if ($recipe.status -cne 'PRESERVED_RECIPE_AND_SOURCES_CONSISTENT_NOT_RUN_ADMISSION') {throw 'SOURCE_OR_RECIPE_REVIEW_BLOCKED'}
    foreach ($field in @('source_integrity','recipe_consistency')) {
        if ($recipe.$field -isnot [bool] -or $recipe.$field -ne $true) {throw 'SOURCE_OR_RECIPE_REVIEW_BLOCKED'}
    }
    foreach ($field in @('run_authorised','replacement_id_authorised','recipe_authenticated')) {
        if ($recipe.$field -isnot [bool] -or $recipe.$field -ne $false) {throw 'SOURCE_OR_RECIPE_REVIEW_BLOCKED'}
    }
    if ($recipe.same_ist_day -isnot [bool] -or $recipe.historical_recipe -isnot [bool] -or $recipe.same_ist_day -eq $recipe.historical_recipe) {throw 'SOURCE_OR_RECIPE_REVIEW_BLOCKED'}
    $path=Join-Path $ToolsRoot 'isolated_alert_task_drill.ps1'
    $info=Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if ($info.Length -gt 131072 -or ($info.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {throw 'PINNED_BINDING_SOURCE_REQUIRED'}
    $text=[IO.File]::ReadAllText($path).Replace("`r`n","`n")
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$hash=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))).Replace('-','').ToLowerInvariant()} finally {$sha.Dispose()}
    if ($hash -cne 'd37bbf5d6fb9e5f650adbe35d7b8cff4811da9a29126268e3f8bcd89f7dd3191') {throw 'PINNED_BINDING_SOURCE_REQUIRED'}
    $errors=$null;$tokens=$null
    $ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
    if ($errors.Count -ne 0) {throw 'PINNED_BINDING_SOURCE_REQUIRED'}
    foreach ($name in @('Drill-Arguments','Resolve-DrillAccountSid','Test-DrillCurrentUser','Assert-DrillTask')) {
        $nodes=@($ast.FindAll({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -ceq $name},$true))
        if ($nodes.Count -ne 1) {throw 'PINNED_BINDING_SOURCE_REQUIRED'}
        Invoke-Expression $nodes[0].Extent.Text
    }
    $tasks=@(Get-ScheduledTask -TaskPath '\' -TaskName ('ResearchOps-SyntheticAlert-'+$id) -ErrorAction Stop)
    if ($tasks.Count -ne 1) {throw 'EXACT_TASK_NOT_ESTABLISHED'}
    $task=$tasks[0]
    $argsText=Drill-Arguments (Join-Path $OldToolsRoot 'isolated_alert_drill.py') $id
    Assert-DrillTask $task $Python $argsText $OldToolsRoot $identity.User.Value $identity.Name
    if ($task.Settings.Enabled -isnot [bool] -or $task.Settings.Enabled -ne $false -or [string]$task.State -cne 'Disabled') {throw 'DISABLED_TASK_NOT_PROVEN'}
    @{status='PRESERVED_DRILL_FULL_READ_ONLY_REVIEW_NOT_RUN_ADMISSION';source_integrity=$true;
      task_binding=$true;disabled_verified=$true;recipe_consistency=$true;recipe_authenticated=$false;
      same_ist_day=$recipe.same_ist_day;historical_recipe=$recipe.historical_recipe;
      execution_history_independently_verified=$false;run_authorised=$false;replacement_id_authorised=$false;
      raw_values_printed=$false;task_queries=1;task_mutations=0;operational_writes=0;credential_reads=0}
}
try {
    if ($env:OS -cne 'Windows_NT') {throw 'WINDOWS_REQUIRED'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'NORMAL_WINDOW_REQUIRED'}
    if (-not [IO.Path]::IsPathRooted($OldToolsRoot) -or -not [IO.Path]::IsPathRooted($Python)) {throw 'EXPLICIT_PATHS_REQUIRED'}
    $version=& $Python -I -B -c 'import sys; print(sys.version.split()[0])'
    if ($LASTEXITCODE -ne 0 -or ([string]$version).Trim() -cne '3.13.9') {throw 'PYTHON_3139_REQUIRED'}
    $runner={param([string[]]$Arguments)
        $lines=@(& $Python @Arguments)
        @{exit_code=$LASTEXITCODE;output=($lines -join "`n")}
    }
    Invoke-PreservedAudit $OldToolsRoot $Python $identity $PSScriptRoot $runner|ConvertTo-Json -Compress
    exit 0
} catch {
    $known=@('WINDOWS_REQUIRED','NORMAL_WINDOW_REQUIRED','EXPLICIT_PATHS_REQUIRED','PYTHON_3139_REQUIRED',
      'SOURCE_OR_RECIPE_REVIEW_BLOCKED','PINNED_BINDING_SOURCE_REQUIRED','EXACT_TASK_NOT_ESTABLISHED','DISABLED_TASK_NOT_PROVEN','ISOLATED_TASK_BINDING_REVIEW_REQUIRED')
    $reason=if ($_.Exception.Message -cin $known) {$_.Exception.Message} else {'READ_ONLY_REVIEW_NOT_ESTABLISHED'}
    $fields=if ($reason -ceq 'ISOLATED_TASK_BINDING_REVIEW_REQUIRED') {@($script:bindingFailures)} else {@()}
    @{status='BLOCKED';reason=$reason;binding_failures=$fields;raw_values_printed=$false;
      run_authorised=$false;replacement_id_authorised=$false;task_mutations=0;operational_writes=0}|ConvertTo-Json -Compress
    exit 2
}
