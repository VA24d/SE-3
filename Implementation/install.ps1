$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$VenvDir = Join-Path $Root ".venv"
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$Req = Join-Path $Root "requirements.txt"

function Invoke-CheckedCommand {
    param(
        [ScriptBlock]$Command,
        [string]$FailureMessage
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Resolve-SystemPython {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return "python"
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return "py -3"
    }
    throw "Python 3 was not found. Install Python 3.11+ and try again."
}

if (-not (Test-Path -LiteralPath $Req)) {
    throw "requirements.txt not found at: $Req"
}

if (-not (Test-Path -LiteralPath $VenvPy)) {
    Write-Host "Creating virtual environment in .venv ..." -ForegroundColor Cyan
    $pyCmd = Resolve-SystemPython
    if ($pyCmd -eq "python") {
        Invoke-CheckedCommand { python -m venv $VenvDir } "Failed to create virtual environment with python."
    } else {
        Invoke-CheckedCommand { py -3 -m venv $VenvDir } "Failed to create virtual environment with py -3."
    }
}

Write-Host "Installing dependencies from requirements.txt ..." -ForegroundColor Cyan
Invoke-CheckedCommand { & $VenvPy -m pip install --upgrade pip } "Failed to upgrade pip in the virtual environment."
Invoke-CheckedCommand { & $VenvPy -m pip install -r $Req } "Failed to install dependencies from requirements.txt."

Write-Host "" 
Write-Host "Install complete." -ForegroundColor Green
Write-Host "Start the app with:" -ForegroundColor Gray
Write-Host "  .\start.ps1" -ForegroundColor White