<#
.SYNOPSIS
    Install Sensewright v2 mod + sidecar to The Sims 4 Mods folder.

.DESCRIPTION
    Installs the built .ts4script + .package and the sidecar into the
    `Mods\Sensewright\` folder (matching the autoboot path convention and the
    prior v1 layout). Supports OneDrive-redirected Documents folders.

.EXAMPLE
    .\scripts\install-mod.ps1
#>

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir = Split-Path -Parent $ScriptDir
$ModDir = Join-Path $RootDir 'mod'
$SidecarDir = Join-Path $RootDir 'sidecar'
$DistDir = Join-Path $ModDir 'dist'

$ModsDir = "$env:USERPROFILE\Documents\Electronic Arts\The Sims 4\Mods"
# Support OneDrive-redirected Documents folders.
$oneDriveModsDir = "$env:USERPROFILE\OneDrive\Documents\Electronic Arts\The Sims 4\Mods"
if ((Test-Path $oneDriveModsDir) -and -not (Test-Path $ModsDir)) {
    $ModsDir = $oneDriveModsDir
}

$InstallDir = Join-Path $ModsDir 'Sensewright'
$InstallSidecarDir = Join-Path $InstallDir 'sidecar'

Write-Host "Sensewright v2 - Mod Installer" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host "Target: $InstallDir" -ForegroundColor Gray

if (-not (Test-Path $DistDir)) {
    Write-Error "Build directory not found: $DistDir"
    Write-Host "Run .\scripts\dev.ps1 build first" -ForegroundColor Yellow
    exit 1
}

$ts4script = Get-ChildItem $DistDir -Filter '*.ts4script' | Select-Object -First 1
$package = Get-ChildItem $DistDir -Filter '*.package' | Select-Object -First 1

if (-not $ts4script -and -not $package) {
    Write-Error "No build artifacts found in $DistDir"
    exit 1
}

# Ensure install directories exist
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path $InstallSidecarDir -Force | Out-Null

# Copy mod artifacts
if ($ts4script) {
    Write-Host "Installing $($ts4script.Name)..." -ForegroundColor Green
    Copy-Item $ts4script.FullName -Destination $InstallDir -Force
}

if ($package) {
    Write-Host "Installing $($package.Name)..." -ForegroundColor Green
    Copy-Item $package.FullName -Destination $InstallDir -Force
}

# Copy sidecar (runtime files + package + locales + config + python.txt)
Write-Host "Installing sidecar..." -ForegroundColor Green
foreach ($f in @('main.py', 'pyproject.toml', 'requirements.txt', 'README.md')) {
    $src = Join-Path $SidecarDir $f
    if (Test-Path $src) { Copy-Item $src -Destination $InstallSidecarDir -Force }
}

# config.toml is optional (only copied when present; it contains API keys)
$configSrc = Join-Path $SidecarDir 'config.toml'
if (Test-Path $configSrc) {
    Copy-Item $configSrc -Destination $InstallSidecarDir -Force
} else {
    Write-Host "  (no sidecar/config.toml - sidecar will run in 0-key fallback mode)" -ForegroundColor Yellow
}

# python.txt enables autoboot; optional
$pythonTxt = Join-Path $SidecarDir 'python.txt'
if (Test-Path $pythonTxt) {
    Copy-Item $pythonTxt -Destination $InstallSidecarDir -Force
}

# Sidecar package + locale bundle
$pkgSrc = Join-Path $SidecarDir 'sensewright_sidecar'
if (Test-Path $pkgSrc) {
    Copy-Item $pkgSrc -Destination $InstallSidecarDir -Recurse -Force
}
$localesSrc = Join-Path $SidecarDir 'locales'
if (Test-Path $localesSrc) {
    Copy-Item $localesSrc -Destination $InstallSidecarDir -Recurse -Force
}

# Clean compiled caches from the installed sidecar copy
Get-ChildItem $InstallSidecarDir -Recurse -Directory -Filter '__pycache__' |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Cyan
Write-Host "Mod + sidecar installed to: $InstallDir" -ForegroundColor Gray
Write-Host ""
Write-Host "Remember to enable 'Script Mods Allowed' in Game Options > Other" -ForegroundColor Yellow
