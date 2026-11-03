$ErrorActionPreference = 'Stop'
$env:PREWARM_VOICES = '1'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    throw 'Install the local environment first; see README.md.'
}
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log --log-level warning
