<#
.SYNOPSIS
    Decompile The Sims 4 shipped Python into research/ts4/ (PLANO.md §15.7, F0).

.DESCRIPTION
    Reproducible F0 step: locate the game's Python (inside the Data/Simulation
    Gameplay zips and Game/Bin/Python), extract it to a staging folder, verify
    the 3.7 bytecode magic (42 0D 0D 0A) and decompile it with unpyc37 into
    `research/ts4/` (gitignored - never commit EA code).

    unpyc37 is the S4S starter project's `decompile_all.py` or
    https://github.com/andrews4s/unpyc37. Because the exact CLI varies by fork,
    the per-file command is parameterized: pass `-Unpyc37Script` and an
    `-Unpyc37Args` template with `{input}` / `{output}` placeholders.

.EXAMPLE
    # Extract + verify the bytecode magic only (no decompiler needed):
    powershell -File scripts/decompile-scripts.ps1 -VerifyOnly

.EXAMPLE
    # Full run with an unpyc37 checkout under tools/unpyc37:
    powershell -File scripts/decompile-scripts.ps1 `
        -Unpyc37Script tools/unpyc37/unpyc37.py -Unpyc37Args "{input}"

.NOTES
    EA scripts are proprietary: research/ts4/ is in .gitignore. Keep them local.
#>

[CmdletBinding()]
param(
    # The Sims 4 install folder. Auto-detected from the common EA/Origin paths.
    [string]$GameDir = "",

    # Where the decompiled sources go. Defaults to <repo>/research/ts4.
    [string]$OutDir = "",

    # Python interpreter used to run the decompiler. Defaults to the sidecar venv
    # then `python`/`py`.
    [string]$Python = "",

    # Path to the unpyc37 entry script (e.g. tools/unpyc37/unpyc37.py).
    [string]$Unpyc37Script = "",

    # Arguments template passed to the decompiler. {input} = .pyc path,
    # {output} = target .py path. Example: "{input} -o {output}".
    [string]$Unpyc37Args = "{input}",

    # Only extract + verify the 3.7 bytecode magic; skip decompilation.
    [switch]$VerifyOnly,

    # Re-decompile even when the target .py already exists.
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-GameDir([string]$Explicit) {
    if ($Explicit -and (Test-Path -LiteralPath $Explicit)) {
        return (Resolve-Path -LiteralPath $Explicit).Path
    }
    $candidates = @(
        (Join-Path ${env:ProgramFiles} "EA Games\The Sims 4"),
        (Join-Path ${env:ProgramFiles} "Electronic Arts\The Sims 4"),
        (Join-Path ${env:ProgramFiles(x86)} "Origin Games\The Sims 4"),
        (Join-Path ${env:ProgramFiles(x86)} "EA Games\The Sims 4"),
        (Join-Path $env:SystemDrive "Program Files\EA Games\The Sims 4")
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ""
}

function Resolve-Python([string]$Explicit) {
    if ($Explicit -and (Test-Path -LiteralPath $Explicit)) { return $Explicit }
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    $venv = Join-Path $repoRoot "sidecar\.venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv) { return $venv }
    foreach ($name in @("python", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return ""
}

function Expand-GameZip([string]$ZipPath, [string]$Destination) {
    if (-not (Test-Path -LiteralPath $ZipPath)) {
        Write-Host "    skip (missing): $ZipPath" -ForegroundColor DarkGray
        return $false
    }
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $Destination)
    Write-Host "    extracted: $ZipPath -> $Destination" -ForegroundColor DarkGray
    return $true
}

function Get-PycMagic([string]$File) {
    try {
        $stream = [System.IO.File]::OpenRead($File)
        try {
            $buffer = New-Object byte[] 4
            [void]$stream.Read($buffer, 0, 4)
        } finally {
            $stream.Close()
        }
        return (($buffer | ForEach-Object { $_.ToString("X2") }) -join " ")
    } catch {
        return "?? ?? ?? ??"
    }
}

# ── 1. Locate the game ───────────────────────────────────────────────────
$gameDir = Resolve-GameDir $GameDir
if (-not $gameDir) {
    Write-Error "The Sims 4 install not found. Pass -GameDir '<path>'."
    exit 1
}
Write-Step "Game: $gameDir"

$generatedZip = Join-Path $gameDir "Game\Bin\Python\generated.zip"
$gameplayDir = Join-Path $gameDir "Data\Simulation\Gameplay"
$gameplayZips = @(
    (Join-Path $gameplayDir "base.zip"),
    (Join-Path $gameplayDir "core.zip"),
    (Join-Path $gameplayDir "simulation.zip")
)

# ── 2. Stage the bytecode ────────────────────────────────────────────────
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) { $OutDir = Join-Path $repoRoot "research\ts4" }
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("simssense-ts4-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $staging -Force | Out-Null

Write-Step "Staging bytecode in $staging"
[void](Expand-GameZip $generatedZip (Join-Path $staging "generated"))
foreach ($name in @("base", "core", "simulation")) {
    $zip = Join-Path $gameplayDir "$name.zip"
    [void](Expand-GameZip $zip (Join-Path $staging $name))
}

$pycFiles = @(Get-ChildItem -LiteralPath $staging -Recurse -File -Filter *.pyc -ErrorAction SilentlyContinue)
if ($pycFiles.Count -eq 0) {
    Write-Error "No .pyc files staged. Check -GameDir ('$gameDir')."
    exit 1
}
Write-Host "    found $($pycFiles.Count) .pyc files" -ForegroundColor DarkGray

# ── 3. Verify the 3.7 bytecode magic ─────────────────────────────────────
Write-Step "Verifying bytecode magic (Python 3.7 = '42 0D 0D 0A')"
$magicCounts = @{}
foreach ($file in $pycFiles) {
    $magic = Get-PycMagic $file.FullName
    if (-not $magicCounts.ContainsKey($magic)) { $magicCounts[$magic] = 0 }
    $magicCounts[$magic]++
}
$magicCounts.GetEnumerator() | Sort-Object Name | ForEach-Object {
    $tag = if ($_.Name -eq "42 0D 0D 0A") { "OK (3.7)" } else { "unexpected" }
    Write-Host ("    {0}  x{1}  {2}" -f $_.Name, $_.Value, $tag) -ForegroundColor DarkGray
}
if (-not $magicCounts.ContainsKey("42 0D 0D 0A")) {
    Write-Warning "No 3.7 bytecode found - the patch may have changed the runtime. The tooling must be updated."
}

if ($VerifyOnly) {
    Write-Step "Verify-only complete. Staging kept at: $staging"
    Write-Host "Set SIMS_SENSE_TS4_STUBS=$staging to reuse it." -ForegroundColor DarkGray
    exit 0
}

# ── 4. Decompile with unpyc37 ────────────────────────────────────────────
if (-not $Unpyc37Script) {
    Write-Host ""
    Write-Warning "No -Unpyc37Script given; bytecode is staged but not decompiled."
    Write-Host "  Get unpyc37 (S4S starter project's decompile_all.py, or" -ForegroundColor Yellow
    Write-Host "  https://github.com/andrews4s/unpyc37), then re-run with:" -ForegroundColor Yellow
    Write-Host "    -Unpyc37Script tools/unpyc37/unpyc37.py -Unpyc37Args '{input}'" -ForegroundColor Yellow
    Write-Host "  Staging: $staging (set SIMS_SENSE_TS4_STUBS to reuse)." -ForegroundColor DarkGray
    exit 2
}
if (-not (Test-Path -LiteralPath $Unpyc37Script)) {
    Write-Error "Decompiler not found: $Unpyc37Script"
    exit 1
}
$pythonExe = Resolve-Python $Python
if (-not $pythonExe) {
    Write-Error "No Python interpreter found. Pass -Python '<path>'."
    exit 1
}

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
Write-Step "Decompiling into $OutDir (python: $pythonExe)"

$ok = 0; $failed = 0; $skipped = 0
foreach ($file in $pycFiles) {
    $relative = $file.FullName.Substring($staging.Length).TrimStart('\', '/')
    $target = Join-Path $OutDir ($relative -replace '\.pyc$', '.py')
    $targetDir = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
    if ((Test-Path -LiteralPath $target) -and -not $Force) {
        $skipped++
        continue
    }
    $argumentLine = $Unpyc37Args.Replace("{input}", $file.FullName).Replace("{output}", $target)
    $argList = @()
    foreach ($token in ($argumentLine -split '\s+')) {
        $token = $token.Trim('"')
        if ($token) { $argList += $token }
    }
    try {
        $output = & $pythonExe $Unpyc37Script @argList 2>&1
        if (Test-Path -LiteralPath $target) {
            $ok++
        } elseif ($output) {
            # Some forks print the source to stdout instead of writing a file.
            Set-Content -LiteralPath $target -Value $output -Encoding UTF8
            $ok++
        } else {
            $failed++
        }
    } catch {
        $failed++
        Write-Host "    failed: $relative -> $($_.Exception.Message)" -ForegroundColor DarkGray
    }
}

Write-Step "Done. decompiled=$ok skipped=$skipped failed=$failed"
Write-Host "    output: $OutDir" -ForegroundColor DarkGray
Write-Host "    (research/ts4/ is gitignored - never commit EA code)" -ForegroundColor DarkGray
