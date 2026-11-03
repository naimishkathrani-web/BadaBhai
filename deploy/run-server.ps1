# Run under the SAME Windows user who ran setup.ps1 (model cache belongs to that user).
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Set-Location $projectPath
$env:PREWARM_VOICES = '1'
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run deploy/setup.ps1 first.' }
if (-not (Test-Path -LiteralPath '.env')) { throw 'Create the private .env first.' }
while ($true) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $serverProcess = Start-Process -FilePath $pythonPath -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--no-access-log','--log-level','warning' -WorkingDirectory $projectPath -WindowStyle Hidden -PassThru -Wait -RedirectStandardOutput (Join-Path $projectPath "server-$stamp.log") -RedirectStandardError (Join-Path $projectPath "server-error-$stamp.log")
    Write-Host "Server exited with $($serverProcess.ExitCode). Restarting in 10 seconds."
    Start-Sleep -Seconds 10
}
