<#
.SYNOPSIS
    SimsSense mod installer - copies the built .ts4script and sidecar to Mods.

.DESCRIPTION
    Copies the built mod package and the sidecar folder to:
    Documents\Electronic Arts\The Sims 4\Mods\SimsSense

    Note: until the PyInstaller packaging phase, the sidecar is shipped as
    Python source. This script records the interpreter that has the sidecar
    dependencies in `sidecar/python.txt`, so the mod's autoboot can spawn it
    automatically (no manual start needed on the dev machine).
#>

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

Write-Host "=== SimsSense Mod Installer ===" -ForegroundColor Cyan

$modDist = Join-Path $repoRoot "dist\SimsSense.ts4script"
$sidecarSrc = Join-Path $repoRoot "sidecar"
$configExample = Join-Path $repoRoot "config.example.toml"

$docsPath = [Environment]::GetFolderPath("MyDocuments")
$modsDest = Join-Path $docsPath "Electronic Arts\The Sims 4\Mods\SimsSense"
$sidecarDest = Join-Path $modsDest "sidecar"

if (-not (Test-Path $modDist)) {
    Write-Error "Mod package not found at $modDist. Run 'make build-mod' first."
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

# Copy .ts4script
Write-Host "Copying mod package..." -ForegroundColor Cyan
Copy-Item -Path $modDist -Destination $modsDest -Force
Write-Host "  Copied: SimsSense.ts4script" -ForegroundColor Green

# Copy sidecar source (excluding venvs, caches, tests, locks)
Write-Host "Copying sidecar..." -ForegroundColor Cyan
$sidecarFiles = Get-ChildItem -Path $sidecarSrc -Recurse -File | Where-Object {
    $_.FullName -notmatch "\\\.venv\\" -and
    $_.FullName -notmatch "\\__pycache__\\" -and
    $_.FullName -notmatch "\\\.pytest_cache\\" -and
    $_.FullName -notmatch "\\tests\\" -and
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

# Seed config.toml from the example if the user has none
$destConfig = Join-Path $sidecarDest "config.toml"
if (-not (Test-Path $destConfig) -and (Test-Path $configExample)) {
    Copy-Item -Path $configExample -Destination $destConfig -Force
    Write-Host "  Seeded config.toml from config.example.toml" -ForegroundColor Gray
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
    Write-Host "  [WARN] No interpreter found; start the sidecar manually (ai.start)" -ForegroundColor Yellow
}

# Verify critical files
Write-Host "Verifying critical files..." -ForegroundColor Cyan
$criticalFiles = @(
    (Join-Path $modsDest "SimsSense.ts4script"),
    (Join-Path $sidecarDest "sims_sense_sidecar\__main__.py"),
    (Join-Path $sidecarDest "sims_sense_sidecar\server.py"),
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
Write-Host "  3. Open the cheat console (Ctrl+Shift+C) and type: ai.help"
Write-Host ""
Write-Host "Note: if Documents is inside OneDrive, script mods may not load." -ForegroundColor Yellow
