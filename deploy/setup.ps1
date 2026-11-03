$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Set-Location $projectPath
& py -3.11 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Install 64-bit Python 3.11, including the Python launcher, first.' }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements-lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) {
    $randomBytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $generator.GetBytes($randomBytes)
    $generator.Dispose()
    $appSecret = [Convert]::ToBase64String($randomBytes).TrimEnd('=').Replace('+','-').Replace('/','_')
    $template = Get-Content -LiteralPath '.env.example' -Raw
    $template.Replace('APP_TOKEN=replace-with-a-long-random-token', "APP_TOKEN=$appSecret") | Set-Content -LiteralPath '.env' -Encoding utf8
}
& '.\.venv\Scripts\python.exe' -m scripts.warmup
if ($LASTEXITCODE -ne 0) { throw 'Model download/warm-up failed.' }
Write-Host 'Setup finished. Add MODEL_API_KEY to the private .env file before starting.'
