<#
.SYNOPSIS
    Decompile The Sims 4 Python scripts for reference.

.DESCRIPTION
    Uses unpyc3 or similar to decompile TS4 game scripts for API reference.
    Requires unpyc3 to be installed (pip install unpyc3).

.EXAMPLE
    .\scripts\decompile-scripts.ps1
    .\scripts\decompile-scripts.ps1 -OutputDir "C:\TS4_Decompiled"
#>

param(
    [string]$OutputDir = "$env:USERPROFILE\Documents\TS4_Decompiled",
    [string[]]$Packages = @('base', 'core', 'simulation', 'generated')
)

$ErrorActionPreference = 'Stop'

Write-Host "TS4 Script Decompiler" -ForegroundColor Cyan
Write-Host "=====================" -ForegroundColor Cyan
Write-Host ""

# Find TS4 installation
$ts4Paths = @(
    "C:\Program Files (x86)\Origin Games\The Sims 4",
    "C:\Program Files\EA Games\The Sims 4",
    "$env:PROGRAMFILES\EA Games\The Sims 4",
    "$env:PROGRAMFILES(X86)\Origin Games\The Sims 4"
)

$ts4Root = $null
foreach ($p in $ts4Paths) {
    if (Test-Path (Join-Path $p 'Game\Bin\Python')) {
        $ts4Root = $p
        break
    }
}

if (-not $ts4Root) {
    Write-Error "Could not find The Sims 4 installation."
    Write-Host "Please install TS4 or set the path manually." -ForegroundColor Yellow
    exit 1
}

Write-Host "Found TS4 at: $ts4Root" -ForegroundColor Green

$pythonDir = Join-Path $ts4Root 'Game\Bin\Python'
$scriptsDir = Join-Path $pythonDir 'Scripts'

if (-not (Test-Path $scriptsDir)) {
    Write-Error "TS4 Python scripts directory not found: $scriptsDir"
    exit 1
}

# Check for unpyc3
try {
    & python -c "import unpyc3" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "unpyc3 not found. Installing..." -ForegroundColor Yellow
        & pip install unpyc3
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to install unpyc3"
            exit 1
        }
    }
} catch {
    Write-Host "unpyc3 not found. Installing..." -ForegroundColor Yellow
    & pip install unpyc3
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install unpyc3"
        exit 1
    }
}

# Create output directory
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

Write-Host "Decompiling to: $OutputDir" -ForegroundColor Green
Write-Host ""

foreach ($pkg in $Packages) {
    $srcDir = Join-Path $scriptsDir $pkg
    $dstDir = Join-Path $OutputDir $pkg

    if (-not (Test-Path $srcDir)) {
        Write-Host "Package '$pkg' not found at $srcDir, skipping..." -ForegroundColor Yellow
        continue
    }

    Write-Host "Decompiling $pkg..." -ForegroundColor White
    New-Item -ItemType Directory -Path $dstDir -Force | Out-Null

    & python -m unpyc3 "$srcDir" "$dstDir"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Done: $pkg" -ForegroundColor Green
    } else {
        Write-Host "  Failed: $pkg" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Decompilation complete!" -ForegroundColor Cyan
Write-Host "Output: $OutputDir" -ForegroundColor Gray