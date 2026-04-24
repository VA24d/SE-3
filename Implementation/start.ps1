# SyncSpace launcher for Windows (PowerShell).
# Usage: .\start.ps1
# Optional: $env:SYNCSPACE_PORT = "9000"; .\start.ps1

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Port = if ($env:SYNCSPACE_PORT) { $env:SYNCSPACE_PORT } else { "8080" }
$Py = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Py)) {
    Write-Host "Missing venv Python at: $Py" -ForegroundColor Red
    Write-Host "From the Implementation folder run:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor Gray
    Write-Host "  .\.venv\Scripts\pip.exe install -r requirements.txt" -ForegroundColor Gray
    Write-Host "Or: make install" -ForegroundColor Gray
    exit 1
}

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  SyncSpace" -ForegroundColor White
Write-Host ""
Write-Host "  On this computer:" -ForegroundColor Gray
Write-Host "    http://127.0.0.1:$Port/" -ForegroundColor Green
Write-Host ""
Write-Host "  Same Wi‑Fi / LAN:" -ForegroundColor Gray
$any = $false
try {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*"
        } |
        ForEach-Object {
            Write-Host ("    http://{0}:{1}/   ({2})" -f $_.IPAddress, $Port, $_.InterfaceAlias) -ForegroundColor Green
            $any = $true
        }
} catch { }
if (-not $any) {
    try {
        foreach ($line in (ipconfig | Out-String) -split "`n") {
            if ($line -match "IPv4.*:\s*(\d+\.\d+\.\d+\.\d+)") {
                $ip = $Matches[1]
                if ($ip -notlike "127.*") {
                    Write-Host "    http://${ip}:$Port/" -ForegroundColor Green
                    $any = $true
                }
            }
        }
    } catch { }
}
if (-not $any) {
    Write-Host "    (could not detect LAN IP — check ipconfig)" -ForegroundColor DarkYellow
}
Write-Host ""
Write-Host "  Listening on 0.0.0.0:$Port — allow TCP $Port in Windows Firewall if needed." -ForegroundColor Gray
Write-Host "  Press Ctrl+C to stop." -ForegroundColor Gray
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

if (-not $env:SYNCSPACE_HOST) { $env:SYNCSPACE_HOST = "0.0.0.0" }
if (-not $env:SYNCSPACE_PORT) { $env:SYNCSPACE_PORT = $Port }

Set-Location -LiteralPath (Join-Path $Root "src\server")
& $Py server.py
