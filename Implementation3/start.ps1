# SyncSpace — Implementation 3 (Pub-Sub + SSE, port 8082)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Write-Host "Run: make install   (or python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt)"
  exit 1
}
$env:SYNCSPACE_PUBSUB_HOST = "0.0.0.0"
$env:SYNCSPACE_PUBSUB_PORT = "8082"
& .\.venv\Scripts\uvicorn.exe server:app --host 0.0.0.0 --port 8082 --reload --app-dir src\server
