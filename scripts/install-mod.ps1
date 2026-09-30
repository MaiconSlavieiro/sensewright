<#
.SYNOPSIS
    Sensewright mod installer - copies the built .ts4script and sidecar to Mods.

.DESCRIPTION
    Copies the built mod package and the sidecar folder to:
    Documents\Electronic Arts\The Sims 4\Mods\Sensewright

    Note: until the PyInstaller packaging phase, the sidecar is shipped as
    Python source. This script records the interpreter that has the sidecar
    dependencies in `sidecar/python.txt`, so the mod's autoboot can spawn it
    automatically (no manual start needed on the dev machine).
#>

param(
    # Remove the legacy Mods\SimsSense folder after a successful install.
    [switch]$RemoveLegacy
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "=== Sensewright Mod Installer ===" -ForegroundColor Cyan

$modDist = Join-Path $repoRoot "dist\Sensewright.ts4script"
$packageDist = Join-Path $repoRoot "dist\Sensewright.package"
$sidecarSrc = Join-Path $repoRoot "sidecar"
$sidecarConfig = Join-Path $sidecarSrc "config.toml"
$configExample = Join-Path $repoRoot "config.example.toml"

$docsPath = [Environment]::GetFolderPath("MyDocuments")
$modsRoot = Join-Path $docsPath "Electronic Arts\The Sims 4\Mods"
$modsDest = Join-Path $modsRoot "Sensewright"
$sidecarDest = Join-Path $modsDest "sidecar"
$legacyDir = Join-Path $modsRoot "SimsSense"

if (-not (Test-Path $modDist)) {
    Write-Error "Mod package not found at $modDist. Run 'make build-mod' first."
    exit 1
}
if (-not (Test-Path $packageDist)) {
    Write-Error "Tuning package not found at $packageDist. Run 'make build-mod' first."
    exit 1
}
if (-not (Test-Path $sidecarSrc)) {
    Write-Error "Sidecar folder not found at $sidecarSrc."
    exit 1
}

if (-not (Test-Path $modsDest)) {
    Write-Host "Creating Mods directory: $modsDest" -ForegroundColor Cyan
    New-Item -ItemType Directory -Path $modsDest -Force | Out-Null
}

# Copy .ts4script and the tuning .package
Write-Host "Copying mod package..." -ForegroundColor Cyan
Copy-Item -Path $modDist -Destination $modsDest -Force
Write-Host "  Copied: Sensewright.ts4script" -ForegroundColor Green
Copy-Item -Path $packageDist -Destination $modsDest -Force
Write-Host "  Copied: Sensewright.package" -ForegroundColor Green

# Stack base libraries (S4CL + Lot 51 Core) must be installed by the player at
# the Mods ROOT. Sensewright ships a tuning .package for the custom interactions
# and registers them through S4CL's CommonInteractionRegistry (no XmlInjector).
$requiredLibs = @("sims4communitylib", "lot51_core")
$missingLibs = @()
foreach ($lib in $requiredLibs) {
    $found = Get-ChildItem -Path $modsRoot -Recurse -Depth 1 -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "$lib*.ts4script" } | Select-Object -First 1
    if (-not $found) { $missingLibs += $lib }
}
if ($missingLibs.Count -eq 0) {
    Write-Host "  Libraries present at Mods root: $($requiredLibs -join ', ')" -ForegroundColor Green
} else {
    Write-Host "  [WARN] Missing stack libraries: $($missingLibs -join ', ')" -ForegroundColor Yellow
    Write-Host "         Download Sims 4 Community Library (S4CL) and Lot 51 Core Library" -ForegroundColor Yellow
    Write-Host "         and place both at the Mods root (top level or one folder deep)." -ForegroundColor Yellow
}

# Copy sidecar source (excluding venvs, caches, tests, locks)
Write-Host "Copying sidecar..." -ForegroundColor Cyan
$sidecarFiles = Get-ChildItem -Path $sidecarSrc -Recurse -File | Where-Object {
    $_.FullName -notmatch "\\\.venv\\" -and
    $_.FullName -notmatch "\\__pycache__\\" -and
    $_.FullName -notmatch "\\\.pytest_cache\\" -and
    $_.FullName -notmatch "\\tests\\" -and
    $_.FullName -notmatch "\\data\\" -and
    $_.Name -ne "config.toml" -and
    $_.Extension -notin @(".pyc", ".pyo", ".lock")
}

$sidecarSrcPath = (Resolve-Path -LiteralPath $sidecarSrc).Path
$copiedCount = 0
foreach ($file in $sidecarFiles) {
    $relPath = $file.FullName.Substring($sidecarSrcPath.Length + 1)
    $destFile = Join-Path $sidecarDest $relPath
    $destDir = Split-Path $destFile -Parent
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }
    Copy-Item -Path $file.FullName -Destination $destFile -Force
    $copiedCount++
}
Write-Host "  Copied $copiedCount sidecar files" -ForegroundColor Green

# config.toml holds the model/API keys, so it is handled explicitly and is
# NEVER overwritten by the sidecar source copy. Precedence:
#   1. keep an existing install config (keys preserved on re-install);
#   2. migrate the legacy Mods\SimsSense config (the user's keys);
#   3. the repo sidecar\config.toml (dev keys);
#   4. the example (empty keys).
$destConfig = Join-Path $sidecarDest "config.toml"
if (Test-Path $destConfig) {
    Write-Host "  Keeping existing config.toml (model keys preserved)" -ForegroundColor Green
} elseif (Test-Path (Join-Path $legacyDir "sidecar\config.toml")) {
    Copy-Item -Path (Join-Path $legacyDir "sidecar\config.toml") -Destination $destConfig -Force
    Write-Host "  Migrated config.toml (model keys) from Mods\SimsSense" -ForegroundColor Green
} elseif (Test-Path $sidecarConfig) {
    Copy-Item -Path $sidecarConfig -Destination $destConfig -Force
    Write-Host "  Copied config.toml (model keys) from sidecar\" -ForegroundColor Green
} elseif (Test-Path $configExample) {
    Copy-Item -Path $configExample -Destination $destConfig -Force
    Write-Host "  Seeded config.toml from config.example.toml (no keys)" -ForegroundColor Gray
}

# The sidecar data folder (memory DB / token / runtime) is NEVER overwritten by
# the source copy. Precedence mirrors config.toml: keep an existing install,
# else migrate the legacy Mods\SimsSense data, else copy the repo sidecar\data
# (dev convenience). The sidecar creates whatever is still missing on start.
$legacyData = Join-Path $legacyDir "sidecar\data"
$repoData = Join-Path $sidecarSrc "data"
$destData = Join-Path $sidecarDest "data"
if (Test-Path $destData) {
    Write-Host "  Keeping existing sidecar data (memory/token)" -ForegroundColor Green
} elseif (Test-Path $legacyData) {
    Copy-Item -Path $legacyData -Destination $destData -Recurse -Force
    Write-Host "  Migrated sidecar data (memory/token) from Mods\SimsSense" -ForegroundColor Green
} elseif (Test-Path $repoData) {
    Copy-Item -Path $repoData -Destination $destData -Recurse -Force
    Write-Host "  Copied sidecar data (memory/token) from sidecar\data" -ForegroundColor Green
}

# Record the interpreter that has the sidecar dependencies so the mod's autoboot
# can spawn it without a manual start. Prefer the dev venv, then PATH python.
Write-Host "Recording sidecar interpreter..." -ForegroundColor Cyan
$venvPython = Join-Path $sidecarSrc ".venv\Scripts\python.exe"
$interpreter = $null
if (Test-Path -LiteralPath $venvPython) {
    $interpreter = (Resolve-Path -LiteralPath $venvPython).Path
} else {
    foreach ($name in @("python", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $interpreter = $cmd.Source; break }
    }
}
$hintFile = Join-Path $sidecarDest "python.txt"
if ($interpreter) {
    # Write WITHOUT a BOM: Set-Content -Encoding UTF8 prepends one on PS 5.1,
    # which the mod would read as part of the path and reject.
    [System.IO.File]::WriteAllText($hintFile, $interpreter, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "  Autoboot interpreter: $interpreter" -ForegroundColor Green
} else {
    Write-Host "  [WARN] No interpreter found; start the sidecar manually (sw.start)" -ForegroundColor Yellow
}

# Verify critical files
Write-Host "Verifying critical files..." -ForegroundColor Cyan
$criticalFiles = @(
    (Join-Path $modsDest "Sensewright.ts4script"),
    (Join-Path $modsDest "Sensewright.package"),
    (Join-Path $sidecarDest "sensewright_sidecar\__main__.py"),
    (Join-Path $sidecarDest "sensewright_sidecar\server.py"),
    $destConfig
)
foreach ($file in $criticalFiles) {
    if (Test-Path $file) {
        Write-Host "  [OK] $file" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] Missing: $file" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Install complete!" -ForegroundColor Green
Write-Host "Mod installed to: $modsDest" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Enable 'Script Mods Allowed' in Game Options > Other"
Write-Host "  2. Restart The Sims 4"
Write-Host "  3. Open the cheat console (Ctrl+Shift+C) and type: sw.help"
Write-Host ""
if ($RemoveLegacy) {
    if (Test-Path $legacyDir) {
        Remove-Item -Path $legacyDir -Recurse -Force
        Write-Host "Removed legacy install: $legacyDir" -ForegroundColor Yellow
    } else {
        Write-Host "No legacy install found at $legacyDir" -ForegroundColor Gray
    }
}

Write-Host "Note: if Documents is inside OneDrive, script mods may not load." -ForegroundColor Yellow
