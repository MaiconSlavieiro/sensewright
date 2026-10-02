<#
.SYNOPSIS
    Install Sensewright v2 mod to The Sims 4 Mods folder.

.DESCRIPTION
    Copies the built .ts4script and .package files to the user's Mods folder.
    Creates the Mods folder if it doesn't exist.

.EXAMPLE
    .\scripts\install-mod.ps1
#>

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir = Split-Path -Parent $ScriptDir
$ModDir = Join-Path $RootDir 'mod'
$DistDir = Join-Path $ModDir 'dist'

$ModsDir = "$env:USERPROFILE\Documents\Electronic Arts\The Sims 4\Mods"

Write-Host "Sensewright v2 - Mod Installer" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan

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

# Ensure Mods directory exists
if (-not (Test-Path $ModsDir)) {
    Write-Host "Creating Mods directory: $ModsDir" -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $ModsDir -Force | Out-Null
}

# Copy files
if ($ts4script) {
    Write-Host "Installing $($ts4script.Name)..." -ForegroundColor Green
    Copy-Item $ts4script.FullName -Destination $ModsDir -Force
}

if ($package) {
    Write-Host "Installing $($package.Name)..." -ForegroundColor Green
    Copy-Item $package.FullName -Destination $ModsDir -Force
}

Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Cyan
Write-Host "Mod files copied to: $ModsDir" -ForegroundColor Gray
Write-Host ""
Write-Host "Remember to enable 'Script Mods Allowed' in Game Options > Other" -ForegroundColor Yellow