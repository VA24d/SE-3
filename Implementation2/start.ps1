# SyncSpace OT — Implementation 2 startup script (PowerShell)
# Starts the OT sequencer server on port 8081.

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Create venv if needed
$venv = Join-Path $ROOT ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "Creating virtual environment..."
    python -m venv $venv
    & "$venv\Scripts\pip" install --upgrade pip
    & "$venv\Scripts\pip" install -r "$ROOT\requirements.txt"
}

$env:SYNCSPACE_OT_HOST = "0.0.0.0"
$env:SYNCSPACE_OT_PORT = "8081"

Write-Host ""
Write-Host "Starting SyncSpace-OT (OT + Central Sequencer) on http://0.0.0.0:8081"
Write-Host "Open http://127.0.0.1:8081/ in your browser."
Write-Host ""

& "$venv\Scripts\uvicorn" server:app `
    --host 0.0.0.0 --port 8081 `
    --app-dir "$ROOT\src\server"
