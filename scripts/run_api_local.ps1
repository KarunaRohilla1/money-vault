# Run the Money Vault API for local / lower testing.
# Usage:  .\scripts\run_api_local.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not $env:APP_ENV) {
    $env:APP_ENV = "development"
}

if (-not $env:API_HOST) {
    $env:API_HOST = "0.0.0.0"
}

if (-not $env:API_PORT) {
    $env:API_PORT = "8001"
}

$port = [int]$env:API_PORT
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    $owner = $listener.OwningProcess
    if ($owner) {
        Write-Host "Freeing port $port (PID $owner)" -ForegroundColor Yellow
        Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Starting local API on http://$($env:API_HOST):$port" -ForegroundColor Cyan
python scripts/run_api_local.py
