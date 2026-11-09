param([string]$Python = '', [switch]$NoLive)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent
if (-not $Python) { $Python = Join-Path $ProjectRoot '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Python environment missing. Create .venv and install backend/requirements.txt; see docs/app_demo.md.' }
$Python = (Resolve-Path -LiteralPath $Python).Path
$NodePath = (Get-Command node -ErrorAction Stop).Source
$VitePath = Join-Path $ProjectRoot 'frontend/node_modules/vite/bin/vite.js'
if (-not (Test-Path -LiteralPath $VitePath)) { throw 'Frontend dependencies missing. Run npm ci in frontend first.' }
$RuntimePath = Join-Path $ProjectRoot '.local'
New-Item -ItemType Directory -Force -Path $RuntimePath | Out-Null
$PidPath = Join-Path $RuntimePath 'demo-processes.json'
if (Test-Path -LiteralPath $PidPath) { throw 'Existing demo process record found. Run scripts/stop_demo.ps1 first.' }
foreach ($Port in @(8000, 3000)) {
    $Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($Listener) { throw "Port $Port is already in use. Stop its owner before starting the demo." }
}
if ($NoLive) { $env:BIKEFLOW_LIVE = '0' }
$ApiProcess = Start-Process -FilePath $Python -ArgumentList @('-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000','--no-access-log') -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RuntimePath 'api.out.log') -RedirectStandardError (Join-Path $RuntimePath 'api.err.log')
try {
    $WebProcess = Start-Process -FilePath $NodePath -ArgumentList @('node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','3000','--strictPort') -WorkingDirectory (Join-Path $ProjectRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RuntimePath 'web.out.log') -RedirectStandardError (Join-Path $RuntimePath 'web.err.log')
    @($ApiProcess,$WebProcess) | ForEach-Object { @{id=$_.Id;started=$_.StartTime.ToUniversalTime().ToString('o');path=$_.Path} } | ConvertTo-Json | Set-Content -LiteralPath $PidPath
    $Ready = $false
    for ($Attempt=0; $Attempt -lt 25; $Attempt++) {
        if ($ApiProcess.HasExited -or $WebProcess.HasExited) { throw 'Demo process exited. Inspect .local/*.log.' }
        try {
            $ApiStatus = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2
            $WebStatus = Invoke-WebRequest -Uri 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 2
            if ($ApiStatus.StatusCode -eq 200 -and $WebStatus.StatusCode -eq 200) { $Ready=$true; break }
        } catch { Start-Sleep -Milliseconds 400 }
    }
    if (-not $Ready) { throw 'Demo startup timed out. Inspect .local/*.log.' }
    Write-Host 'BikeFlow is ready: http://127.0.0.1:3000'
    $Readiness = $ApiStatus.Content | ConvertFrom-Json
    Write-Host ("Forecast: {0} | Data: {1} | PPO runtime ready: {2}" -f $Readiness.active_method, $Readiness.data_source, $Readiness.rl_ready)
    Write-Host 'API docs: http://127.0.0.1:8000/docs | Stop: ./scripts/stop_demo.ps1'
} catch {
    if (-not $ApiProcess.HasExited) { $ApiProcess.Kill() }
    if ($WebProcess -and -not $WebProcess.HasExited) { $WebProcess.Kill() }
    if (Test-Path -LiteralPath $PidPath) { Remove-Item -LiteralPath $PidPath }
    throw
}
