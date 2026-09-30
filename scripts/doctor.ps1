<#
.SYNOPSIS
    Sensewright doctor script - checks environment health.

.DESCRIPTION
    Validates the Python interpreters, uv, the sidecar virtual environment,
    the API port and the Sims 4 Mods path (including OneDrive pitfalls).
#>

$ErrorActionPreference = "Continue"

Write-Host "=== Sensewright Environment Doctor ===" -ForegroundColor Cyan
Write-Host ""

$allOk = $true
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

function Test-Interpreter {
    param(
        [string]$Label,
        [string]$Exe,
        [string[]]$ExtraArgs
    )
    try {
        $output = & $Exe @ExtraArgs 2>&1
        if ($LASTEXITCODE -eq 0) {
            $first = ($output | Select-Object -First 1)
            Write-Host "[OK] ${Label}: $first" -ForegroundColor Green
            return $true
        }
        Write-Host "[FAIL] ${Label}: command failed" -ForegroundColor Red
        return $false
    } catch {
        Write-Host "[FAIL] ${Label}: not found ($($_.Exception.Message))" -ForegroundColor Red
        return $false
    }
}

function Get-PythonVersion {
    param([string]$Exe, [string[]]$ExtraArgs)
    try {
        $output = & $Exe @ExtraArgs 2>&1
        if ($LASTEXITCODE -eq 0) {
            return ($output | Select-Object -First 1)
        }
    } catch {
    }
    return $null
}

function Test-Port {
    param([int]$Port, [string]$Name)
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        $listener.Stop()
        Write-Host "[OK] Port $Port ($Name): available" -ForegroundColor Green
    } catch {
        Write-Host "[WARN] Port $Port ($Name): in use or blocked" -ForegroundColor Yellow
    }
}

# 1. Python interpreters
Write-Host "--- Python Interpreters ---" -ForegroundColor Cyan
$py37 = Test-Interpreter "Python 3.7 (mod build)" "py" @("-3.7", "-c", "import sys; print(sys.version)")
if (-not $py37) {
    $allOk = $false
    Write-Host "  Python 3.7 is REQUIRED to build the .ts4script bytecode." -ForegroundColor Yellow
    Write-Host "  Install with: winget install --id Python.Python.3.7 --exact" -ForegroundColor Yellow
}

$sidecarPy = $false
foreach ($v in @("3.13", "3.12", "3.11", "3.10")) {
    $version = Get-PythonVersion "py" @("-$v", "-c", "import sys; print(sys.version)")
    if ($version) {
        Write-Host "[OK] Python $v (sidecar): $version" -ForegroundColor Green
        $sidecarPy = $true
        break
    }
}
if (-not $sidecarPy) {
    $version = Get-PythonVersion "python" @("-c", "import sys; print(sys.version)")
    if ($version) {
        Write-Host "[OK] Python (default, sidecar): $version" -ForegroundColor Green
        $sidecarPy = $true
    }
}
if (-not $sidecarPy) { $allOk = $false; Write-Host "  Python 3.10+ is required for the sidecar." -ForegroundColor Yellow }

# 2. uv
Write-Host ""
Write-Host "--- Package Manager ---" -ForegroundColor Cyan
if (-not (Test-Interpreter "uv" "uv" @("--version"))) { $allOk = $false }

# 3. Sidecar virtual environment
Write-Host ""
Write-Host "--- Sidecar Virtual Environment ---" -ForegroundColor Cyan
$sidecarDir = Join-Path $repoRoot "sidecar"
$venvPython = Join-Path $sidecarDir ".venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    Write-Host "[OK] Sidecar venv exists at $venvPython" -ForegroundColor Green
    try {
        $deps = & $venvPython -c "import fastapi, pydantic, httpx, uvicorn; print('FastAPI', fastapi.__version__, '| Pydantic', pydantic.VERSION, '| httpx', httpx.__version__)" 2>&1
        Write-Host "  Dependencies: $deps" -ForegroundColor Gray
    } catch {
        Write-Host "[WARN] Sidecar venv exists but dependencies may be missing. Run: uv sync --extra dev" -ForegroundColor Yellow
    }
} else {
    Write-Host "[FAIL] Sidecar venv not found. Run 'make install' (uv sync --extra dev)." -ForegroundColor Red
    $allOk = $false
}

# 4. Port check
Write-Host ""
Write-Host "--- Port Availability ---" -ForegroundColor Cyan
Test-Port 8765 "Sidecar API"

# 5. OneDrive detection
Write-Host ""
Write-Host "--- OneDrive Detection ---" -ForegroundColor Cyan
$docsPath = [Environment]::GetFolderPath("MyDocuments")
$sims4ModsPath = Join-Path $docsPath "Electronic Arts\The Sims 4\Mods"

if ($sims4ModsPath -match "OneDrive") {
    Write-Host "[WARN] Documents folder is inside OneDrive: $sims4ModsPath" -ForegroundColor Yellow
    Write-Host "  Script mods can fail silently here. Consider moving Documents out of OneDrive." -ForegroundColor Yellow
} elseif (Test-Path $sims4ModsPath) {
    Write-Host "[OK] Sims 4 Mods folder is not in OneDrive: $sims4ModsPath" -ForegroundColor Green
} else {
    Write-Host "[INFO] Sims 4 Mods folder not found at the default location: $sims4ModsPath" -ForegroundColor Gray
}

# 6. Built mod artifact
Write-Host ""
Write-Host "--- Mod Build ---" -ForegroundColor Cyan
$modDist = Join-Path $repoRoot "dist\Sensewright.ts4script"
$packageDist = Join-Path $repoRoot "dist\Sensewright.package"
if (Test-Path $modDist) {
    $size = (Get-Item $modDist).Length
    Write-Host "[OK] Mod package exists: $modDist" -ForegroundColor Green
    Write-Host "  Size: $([math]::Round($size / 1KB, 1)) KB" -ForegroundColor Gray
} else {
    Write-Host "[INFO] Mod package not built yet. Run 'make build-mod'." -ForegroundColor Gray
}
if (Test-Path $packageDist) {
    Write-Host "[OK] Tuning package exists: $packageDist" -ForegroundColor Green
} else {
    Write-Host "[INFO] Tuning package not built yet. Run 'make build-mod'." -ForegroundColor Gray
}

# 7. Stack libraries (S4CL + Lot 51 Core) at the Mods root
Write-Host ""
Write-Host "--- Modding Stack Libraries ---" -ForegroundColor Cyan
if (Test-Path $sims4ModsPath) {
    foreach ($lib in @("sims4communitylib", "lot51_core")) {
        $found = Get-ChildItem -Path $sims4ModsPath -Recurse -Depth 1 -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "$lib*.ts4script" } | Select-Object -First 1
        if ($found) {
            Write-Host "[OK] $lib present: $($found.Name)" -ForegroundColor Green
        } else {
            Write-Host "[WARN] $lib not found at the Mods root (required stack base)." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "[INFO] Mods folder not found; skipping stack library check." -ForegroundColor Gray
}

# Summary
Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
if ($allOk) {
    Write-Host "All critical checks passed!" -ForegroundColor Green
    exit 0
} else {
    Write-Host "Some critical checks failed. See above." -ForegroundColor Red
    exit 1
}
