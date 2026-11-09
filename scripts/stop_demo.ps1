$ErrorActionPreference = 'Stop'
$PidPath = Join-Path (Split-Path $PSScriptRoot -Parent) '.local/demo-processes.json'
if (-not (Test-Path -LiteralPath $PidPath)) { Write-Host 'No managed demo processes.'; return }
$Records = Get-Content -LiteralPath $PidPath -Raw | ConvertFrom-Json
foreach ($Record in $Records) {
    $Process = Get-Process -Id $Record.id -ErrorAction SilentlyContinue
    if ($Process -and $Process.StartTime.ToUniversalTime().ToString('o') -eq $Record.started -and $Process.Path -eq $Record.path) {
        Stop-Process -Id $Process.Id
    }
}
Remove-Item -LiteralPath $PidPath
Write-Host 'Stopped managed BikeFlow demo processes.'
