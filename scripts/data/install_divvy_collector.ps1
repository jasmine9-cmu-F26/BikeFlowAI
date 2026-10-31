param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [Parameter(Mandatory=$true)][string]$DataRoot,
    [int]$IntervalMinutes = 2,
    [string]$StopAtUtc = '2026-12-13T07:59:00+00:00'
)
$ErrorActionPreference = 'Stop'
if ($IntervalMinutes -lt 1 -or $IntervalMinutes -gt 5) { throw 'Choose a 1-5 minute interval' }
$collectorPath = Join-Path $PSScriptRoot 'collect_divvy_gbfs.py'
if (-not (Test-Path -LiteralPath $PythonExe) -or -not (Test-Path -LiteralPath $collectorPath)) { throw 'Missing interpreter or collector script' }
$windowlessPython = Join-Path (Split-Path $PythonExe -Parent) 'pythonw.exe'
if (Test-Path -LiteralPath $windowlessPython) { $PythonExe = $windowlessPython }
$taskName = 'BikeFlowAI-Divvy-Full-GBFS-Collector'
$arguments = '"{0}" --data-root "{1}" --once --stop-at "{2}"' -f $collectorPath,$DataRoot,$StopAtUtc
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Actions.Arguments -notlike '*collect_divvy_gbfs.py*') { throw 'Existing task name belongs to another command' }
$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $arguments -WorkingDirectory (Split-Path $collectorPath -Parent)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(15) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$trigger.EndBoundary = ([DateTimeOffset]::Parse($StopAtUtc)).UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ss'Z'")
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 90) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Capture complete official Divvy station status every two minutes; retain success/error heartbeats; stop after final project.'
Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object LastRunTime,LastTaskResult,NextRunTime
Write-Output 'Runs while this Windows user is logged in and the computer is awake/online; no passwords or wake/power settings are changed.'
