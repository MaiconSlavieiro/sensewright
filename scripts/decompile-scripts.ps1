<#
.SYNOPSIS
    Decompile The Sims 4 Python scripts for reference (modern zip layout).

.DESCRIPTION
    Thin wrapper around scripts/decompile_ts4.py. Modern TS4 ships its server
    scripts as .pyc archives under Data\Simulation\Gameplay\{base,core,
    simulation}.zip; the Python script extracts a curated list and decompiles
    them with decompyle3 into research/ts4/ (gitignored — proprietary EA code).

.EXAMPLE
    .\scripts\decompile-scripts.ps1
    .\scripts\decompile-scripts.ps1 -All     # extract + decompile every module
#>

param(
    [string]$OutputDir = "$PSScriptRoot\..\research\ts4",
    [switch]$All
)

$ErrorActionPreference = 'Stop'

$pyArgs = @((Join-Path $PSScriptRoot 'decompile_ts4.py'), '--output', $OutputDir)
if ($All) {
    $pyArgs += '--all'
}

& python @pyArgs
exit $LASTEXITCODE
