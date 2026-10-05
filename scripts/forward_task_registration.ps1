# Importable helper: no installation or credential access when dot-sourced.
function Register-ForwardTaskPlans {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$PlansDirectory)
    $ErrorActionPreference = 'Stop'
    $plans = @()
    # Validate all plans before the first registration. The caller has already
    # verified their exact content against the generator and current owner SID.
    foreach ($mode in @('prepare', 'poll', 'audit')) {
        $name = "KiranTrading-Forward-$mode"
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            throw "Existing task will not be replaced: $name"
        }
        $xml = Get-Content -LiteralPath (Join-Path $PlansDirectory "$mode.xml") -Raw -Encoding UTF8 -ErrorAction Stop
        # -Xml receives a Unicode string, not UTF-8 bytes. Leave the private file
        # byte-for-byte intact; omit its byte-encoding declaration for COM only.
        $declaration = '<?xml version="1.0" encoding="UTF-8"?>'
        if (-not $xml.StartsWith($declaration)) { throw 'Unexpected task XML declaration.' }
        $xml = '<?xml version="1.0"?>' + $xml.Substring($declaration.Length)
        $document = New-Object System.Xml.XmlDocument
        $document.XmlResolver = $null
        $document.LoadXml($xml)
        $namespace = New-Object System.Xml.XmlNamespaceManager($document.NameTable)
        $namespace.AddNamespace('t', 'http://schemas.microsoft.com/windows/2004/02/mit/task')
        $enabled = $document.SelectSingleNode('/t:Task/t:Settings/t:Enabled', $namespace)
        if ($null -eq $enabled -or $enabled.InnerText -cne 'false') {
            throw "Task plan is not explicitly disabled: $name"
        }
        $plans += [pscustomobject]@{ Name = $name; Xml = $xml }
    }
    foreach ($plan in $plans) {
        try {
            Register-ScheduledTask -TaskName $plan.Name -Xml $plan.Xml -ErrorAction Stop | Out-Null
            $task = Get-ScheduledTask -TaskName $plan.Name -ErrorAction Stop
            if ($null -eq $task -or [string]$task.State -ne 'Disabled') {
                throw 'Registered task was not confirmed disabled.'
            }
        } catch {
            # Do not echo native exception text or remove partially created tasks.
            throw "Registration not verified for $($plan.Name). Inspect any existing tasks; do not enable a partial installation."
        }
    }
    Write-Output 'Three tasks registered DISABLED, normal user, interactive login, no stored Windows password.'
    Write-Output 'No collector has been enabled. Complete supervised preparation and polls first.'
}
