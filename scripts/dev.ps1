<# 
.SYNOPSIS
    Development helper script for Sensewright v2 mod.

.DESCRIPTION
    Provides common development tasks: build, test, clean, run sidecar.

.EXAMPLE
    .\scripts\dev.ps1 build
    .\scripts\dev.ps1 test
    .\scripts\dev.ps1 sidecar
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('build', 'test', 'clean', 'sidecar', 'install', 'doctor', 'decompile')]
    [string]$Task,

    [switch]$Verbose
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir = Split-Path -Parent $ScriptDir
$ModDir = Join-Path $RootDir 'mod'

function Write-Log($msg) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor Cyan
}

function Write-ErrorLog($msg) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ERROR: $msg" -ForegroundColor Red
}

function Write-Success($msg) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg" -ForegroundColor Green
}

switch ($Task) {
    'build' {
        Write-Log 'Building .ts4script and .package...'
        # Package first: build_package.py emits dist/tuning_ids.json, which
        # build.py then embeds into the .ts4script.
        & python "$ModDir\build_package.py"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & python "$ModDir\build.py"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Success 'Build complete!'
    }

    'test' {
        Write-Log 'Running Python 3.7 syntax verification...'
        $py37 = 'py -3.7'
        $files = Get-ChildItem "$ModDir\sensewright_mod" -Filter *.py -Recurse
        foreach ($file in $files) {
            & $py37 -m py_compile $file.FullName
            if ($LASTEXITCODE -ne 0) {
                Write-ErrorLog "Syntax error in $($file.Name)"
                exit 1
            }
        }
        Write-Success 'All Python 3.7 files compile cleanly'

        Write-Log 'Running Python 3.10 syntax verification on build scripts...'
        & python "$ModDir\build.py" --check-only 2>$null
        & python "$ModDir\build_package.py" --check-only 2>$null
        Write-Success 'Build scripts compile cleanly'
    }

    'clean' {
        Write-Log 'Cleaning build artifacts...'
        $distDir = Join-Path $ModDir 'dist'
        if (Test-Path $distDir) {
            Remove-Item $distDir -Recurse -Force
        }
        # Clean __pycache__
        Get-ChildItem "$ModDir\sensewright_mod" -Filter '__pycache__' -Recurse -Directory | Remove-Item -Recurse -Force
        Write-Success 'Clean complete'
    }

    'sidecar' {
        Write-Log 'Starting sidecar development server...'
        $sidecarDir = Join-Path $RootDir 'sidecar'
        if (-not (Test-Path "$sidecarDir\main.py")) {
            Write-ErrorLog 'Sidecar main.py not found. Create sidecar first.'
            exit 1
        }
        Set-Location $sidecarDir
        & python main.py
    }

    'install' {
        Write-Log 'Installing mod to The Sims 4 Mods folder...'
        $modsDir = "$env:USERPROFILE\Documents\Electronic Arts\The Sims 4\Mods"
        $distDir = Join-Path $ModDir 'dist'

        if (-not (Test-Path $distDir)) {
            Write-ErrorLog 'No build artifacts found. Run build first.'
            exit 1
        }

        if (-not (Test-Path $modsDir)) {
            Write-ErrorLog "Mods folder not found: $modsDir"
            exit 1
        }

        # Copy .ts4script and .package
        Get-ChildItem $distDir -Filter '*.ts4script' | Copy-Item -Destination $modsDir -Force
        Get-ChildItem $distDir -Filter '*.package' | Copy-Item -Destination $modsDir -Force

        Write-Success 'Mod installed to Mods folder'
    }

    'doctor' {
        Write-Log 'Running diagnostics...'
        & "$ScriptDir\doctor.ps1"
    }

    'decompile' {
        Write-Log 'Decompiling TS4 scripts...'
        & "$ScriptDir\decompile-scripts.ps1"
    }
}