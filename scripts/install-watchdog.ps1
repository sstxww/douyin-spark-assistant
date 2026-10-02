# Register a visible, reversible, least-privilege task. No passwords/tokens stored.
param([string]$Python = '', [switch]$Remove)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$name = 'Spark-Assistant-Recovery'
$homeDir = Join-Path $root '.local\web-local'
if ($Remove) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task) {
        if ($task.Actions.WorkingDirectory -ne $root) { throw 'Task belongs to another installation.' }
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
    Write-Output 'Local recovery task removed. GitHub schedule and private data are unchanged.'
    exit 0
}
if (-not $Python) { $Python = (Get-Command python -ErrorAction Stop).Source }
$gh = (Get-Command gh -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { throw 'pythonw.exe not found beside the specified Python.' }
if (-not (Test-Path (Join-Path $homeDir 'workspace.json'))) { throw 'Publish the local configuration first.' }
Push-Location $root
try {
    & $Python -X utf8 -m spark.watchdog --home $homeDir --export-plan
    if ($LASTEXITCODE -ne 0) { throw 'Cannot export the already-published plan. No task installed.' }
} finally { Pop-Location }
$old = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($old -and $old.Actions.WorkingDirectory -ne $root) { throw 'Existing task belongs to another installation.' }
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $pythonw -WorkingDirectory $root -Argument ('-X utf8 -m spark.watchdog --home "{0}" --gh-path "{1}"' -f $homeDir, $gh)
# 02/07/12/17/... includes both :17 slots, independent of the computer's timezone.
$start = (Get-Date).AddMinutes(1)
$start = $start.AddSeconds(-$start.Second).AddMilliseconds(-$start.Millisecond)
while (($start.Minute % 5) -ne 2) { $start = $start.AddMinutes(1) }
$interval = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes 5)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)
# No self-hosted Actions runner, no always-on browser, no public port, no power changes.
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($interval,$logon) -Principal $principal -Settings $settings -Description 'Checks the published Spark plan every 5 minutes; triggers missed GitHub runs with per-slot deduplication. Requires this Windows user to remain logged in. Does not store account tokens.' -Force | Out-Null
Start-ScheduledTask -TaskName $name
Get-ScheduledTask -TaskName $name | Select-Object TaskName,State,@{N='LogonType';E={$_.Principal.LogonType}},@{N='RunLevel';E={$_.Principal.RunLevel}}
Get-ScheduledTaskInfo -TaskName $name | Select-Object LastRunTime,NextRunTime,LastTaskResult
