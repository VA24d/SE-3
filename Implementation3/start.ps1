# SyncSpace — Implementation 3 (Pub-Sub + SSE, port 8082)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "Run: make install   (or python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt)"
  exit 1
}
$env:SYNCSPACE_PUBSUB_HOST = "0.0.0.0"
$env:SYNCSPACE_PUBSUB_PORT = "8082"

Write-Host ""
Write-Host "Starting SyncSpace (Pub-Sub + SSE) on http://0.0.0.0:8082"
Write-Host "Open http://127.0.0.1:8082/ in your browser."
Write-Host ""

& .\.venv\Scripts\uvicorn.exe server:app --host 0.0.0.0 --port 8082 --reload --app-dir src\server
