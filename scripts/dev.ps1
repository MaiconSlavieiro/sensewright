<#
.SYNOPSIS
    Sensewright development script - starts the sidecar in the foreground.

.DESCRIPTION
    Runs the sidecar FastAPI server using the sidecar's virtual environment.
    Note: hot-reload is disabled because the app is created with a factory
    (settings + token), which uvicorn can only reload from an import string.
#>

$ErrorActionPreference = "Stop"

Write-Host "Starting Sensewright sidecar (development mode)..." -ForegroundColor Cyan

$sidecarDir = Join-Path $PSScriptRoot "..\sidecar"
$venvPython = Join-Path $sidecarDir ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found at $venvPython. Run 'make install' or 'cd sidecar && uv sync --extra dev' first."
    exit 1
}

Set-Location $sidecarDir

$sidecarArgs = @("-m", "sensewright_sidecar")

Write-Host "Running: $venvPython $($sidecarArgs -join ' ')" -ForegroundColor Gray
& $venvPython @sidecarArgs
