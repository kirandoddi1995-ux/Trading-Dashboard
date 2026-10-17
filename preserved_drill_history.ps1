[CmdletBinding()]
param([switch]$ConfirmReadOnly)
$ErrorActionPreference='Stop'

function Convert-DrillEvent([string]$Text) {
    if ($Text.Length -gt 65536) {throw 'EVENT_XML_BOUND'}
    $settings=[Xml.XmlReaderSettings]::new()
    $settings.DtdProcessing=[Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver=$null
    $settings.MaxCharactersInDocument=65536
    $inputReader=[IO.StringReader]::new($Text)
    $reader=[Xml.XmlReader]::Create($inputReader,$settings)
    try {$doc=[Xml.XmlDocument]::new();$doc.XmlResolver=$null;$doc.Load($reader)}
    finally {$reader.Dispose();$inputReader.Dispose()}
    $ns=[Xml.XmlNamespaceManager]::new($doc.NameTable)
    $ns.AddNamespace('e','http://schemas.microsoft.com/win/2004/08/events/event')
    $provider=$doc.SelectNodes('/e:Event/e:System/e:Provider',$ns)
    $task=$doc.SelectNodes('/e:Event/e:EventData/e:Data[@Name="TaskName"]',$ns)
    $times=$doc.SelectNodes('/e:Event/e:System/e:TimeCreated',$ns)
    $ids=$doc.SelectNodes('/e:Event/e:System/e:EventID',$ns)
    if ($provider.Count -ne 1 -or $provider[0].GetAttribute('Name') -cne 'Microsoft-Windows-TaskScheduler' -or
        $task.Count -ne 1 -or $task[0].InnerText -cne '\ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697' -or
        $times.Count -ne 1 -or $ids.Count -ne 1) {throw 'EXACT_EVENT_SHAPE_REQUIRED'}
    $timeText=$times[0].GetAttribute('SystemTime')
    if ($timeText -cnotmatch '^2026-10-17T[0-9:.]+Z$') {throw 'EXACT_EVENT_WINDOW_REQUIRED'}
    $at=[datetimeoffset]::Parse($timeText,[Globalization.CultureInfo]::InvariantCulture)
    if ($at -lt [datetimeoffset]::Parse('2026-10-17T14:54:00Z') -or
        $at -gt [datetimeoffset]::Parse('2026-10-17T15:03:00Z')) {throw 'EXACT_EVENT_WINDOW_REQUIRED'}
    if ($ids[0].InnerText -cnotmatch '^[0-9]{1,5}$') {throw 'EVENT_ID_REQUIRED'}
    $id=[int]$ids[0].InnerText
    $kind=switch ($id) {
        100 {'TASK_START_RECORDED'};101 {'TASK_START_FAILURE_RECORDED'};102 {'TASK_COMPLETION_RECORDED'}
        104 {'LOGON_FAILURE_RECORDED'};110 {'DEMAND_REQUEST_RECORDED'};129 {'PROCESS_CREATION_RECORDED'}
        200 {'ACTION_START_RECORDED'};201 {'ACTION_COMPLETION_RECORDED'};202 {'ACTION_FAILURE_RECORDED'}
        203 {'ACTION_LAUNCH_FAILURE_RECORDED'};311 {'PROCESS_START_FAILURE_RECORDED'}
        default {'OTHER_EVENT_RECORDED_NOT_INTERPRETED'}
    }
    $results=$doc.SelectNodes('/e:Event/e:EventData/e:Data[@Name="ResultCode"]',$ns)
    if ($results.Count -gt 1) {throw 'DUPLICATE_RESULT_FIELD'}
    $result=$null
    if ($results.Count -eq 1) {
        $value=$results[0].InnerText
        if ($value -cmatch '^[0-9]{1,10}$') {$number=[uint64]::Parse($value,[Globalization.CultureInfo]::InvariantCulture)}
        elseif ($value -cmatch '^0[xX][0-9a-fA-F]{1,8}$') {$number=[Convert]::ToUInt64($value.Substring(2),16)}
        else {throw 'NUMERIC_RESULT_REQUIRED'}
        if ($number -gt 4294967295) {throw 'NUMERIC_RESULT_REQUIRED'}
        $result=@{decimal=[long]$number;hex=('0x{0:X8}' -f $number)}
    }
    return @{at_utc=$at.ToUniversalTime().ToString('o');event_id=$id;kind=$kind;result=$result}
}

function Invoke-DrillHistory([scriptblock]$LogQuery,[scriptblock]$EventQuery) {
    $log=& $LogQuery
    if ($log.IsEnabled -isnot [bool]) {throw 'TYPED_LOG_STATE_REQUIRED'}
    if (-not $log.IsEnabled) {
        return @{status='HISTORY_DISABLED_NO_CAUSE_ESTABLISHED';log_queries=1;event_queries=0;events=@();log_enabled=$false;
            task_mutations=0;operational_writes=0;credential_reads=0;capture_invocations=0;
            retry_authorised=$false;replacement_id_authorised=$false;popup_delivery_verified=$false;raw_values_printed=$false}
    }
    $events=@(& $EventQuery)
    if ($events.Count -gt 64) {throw 'EVENT_COUNT_BOUND'}
    $summary=@(foreach ($event in $events) {Convert-DrillEvent $event.ToXml()})
    return @{status='HISTORICAL_EVENT_SUMMARY_NOT_RUN_ADMISSION';log_queries=1;event_queries=1;events=$summary;
        log_enabled=$true;history_complete=$false;worker_cause='NOT_ESTABLISHED';
        task_mutations=0;operational_writes=0;credential_reads=0;capture_invocations=0;
        retry_authorised=$false;replacement_id_authorised=$false;popup_delivery_verified=$false;raw_values_printed=$false}
}

if (-not $ConfirmReadOnly) {
    @{status='PREVIEW';log_queries=0;event_queries=0;task_mutations=0;operational_writes=0;credential_reads=0;capture_invocations=0}|ConvertTo-Json -Compress
    exit 0
}
try {
    if ($env:OS -cne 'Windows_NT') {throw 'WINDOWS_REQUIRED'}
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    if (([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'NORMAL_WINDOW_REQUIRED'}
    $logQuery={Get-WinEvent -ListLog 'Microsoft-Windows-TaskScheduler/Operational' -ErrorAction Stop}
    $eventQuery={
        $xpath="*[System[Provider[@Name='Microsoft-Windows-TaskScheduler'] and TimeCreated[@SystemTime>='2026-10-17T14:54:00Z' and @SystemTime<='2026-10-17T15:03:00Z']] and EventData[Data[@Name='TaskName']='\ResearchOps-SyntheticAlert-389daf12415a482eb0231443ddfd8697']]"
        try {Get-WinEvent -LogName 'Microsoft-Windows-TaskScheduler/Operational' -FilterXPath $xpath -MaxEvents 65 -ErrorAction Stop}
        catch {
            if ($_.FullyQualifiedErrorId -cne 'NoMatchingEventsFound,Microsoft.PowerShell.Commands.GetWinEventCommand') {throw}
            # No matching retained records is not proof that nothing ran.
        }
    }
    Invoke-DrillHistory $logQuery $eventQuery|ConvertTo-Json -Compress -Depth 6
    exit 0
} catch {
    $known=@('WINDOWS_REQUIRED','NORMAL_WINDOW_REQUIRED','EVENT_XML_BOUND','EXACT_EVENT_SHAPE_REQUIRED',
        'EXACT_EVENT_WINDOW_REQUIRED','EVENT_ID_REQUIRED','DUPLICATE_RESULT_FIELD','NUMERIC_RESULT_REQUIRED',
        'TYPED_LOG_STATE_REQUIRED','EVENT_COUNT_BOUND')
    $reason=if ($_.Exception.Message -cin $known) {$_.Exception.Message} else {'HISTORY_QUERY_OR_PARSE_NOT_ESTABLISHED'}
    @{status='BLOCKED';reason=$reason;task_mutations=0;operational_writes=0;credential_reads=0;capture_invocations=0;
        raw_values_printed=$false;retry_authorised=$false;replacement_id_authorised=$false}|ConvertTo-Json -Compress
    exit 2
}
