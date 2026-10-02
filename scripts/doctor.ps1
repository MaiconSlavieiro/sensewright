<#
.SYNOPSIS
    Diagnostic script for Sensewright v2 mod.

.DESCRIPTION
    Checks environment, dependencies, and build artifacts for common issues.

.EXAMPLE
    .\scripts\doctor.ps1
#>

$ErrorActionPreference = 'Continue'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RootDir = Split-Path -Parent $ScriptDir
$ModDir = Join-Path $RootDir 'mod'
$SidecarDir = Join-Path $RootDir 'sidecar'

Write-Host "Sensewright v2 - Diagnostics" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan
Write-Host ""

$issues = 0
$warnings = 0

function Check($name, $condition, $msgOk, $msgFail, $isWarning=$false) {
    if ($condition) {
        Write-Host "  [OK] ${name}: $msgOk" -ForegroundColor Green
    } else {
        if ($isWarning) {
            Write-Host "  [WARN] ${name}: $msgFail" -ForegroundColor Yellow
            $script:warnings++
        } else {
            Write-Host "  [FAIL] ${name}: $msgFail" -ForegroundColor Red
            $script:issues++
        }
    }
}

# Depth-safe JSON parsing (Windows PowerShell 5.1's ConvertFrom-Json has no
# -Depth parameter and truncates at depth 2).
function ConvertFrom-JsonDeep([string]$content) {
    Add-Type -AssemblyName System.Web.Extensions -ErrorAction SilentlyContinue
    $serializer = New-Object System.Web.Script.Serialization.JavaScriptSerializer
    $serializer.MaxJsonLength = 1073741824
    return $serializer.DeserializeObject($content)
}

# Python versions
Write-Host "Python Versions:" -ForegroundColor White
$py37 = $null
$py310 = $null

try {
    $out = & py -3.7 --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $py37 = $out.Trim()
        Check 'Python 3.7' $true "Found: $py37" 'Not found'
    } else {
        Check 'Python 3.7' $false 'Not found (required for mod compilation)'
    }
} catch {
    Check 'Python 3.7' $false 'Not found (required for mod compilation)'
}

try {
    $out = & python --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $py310 = $out.Trim()
        Check 'Python 3.10+' $true "Found: $py310" 'Not found' $true
    } else {
        Check 'Python 3.10+' $false 'Not found (required for build scripts)' $true
    }
} catch {
    Check 'Python 3.10+' $false 'Not found (required for build scripts)' $true
}

Write-Host ""

# Mod source files
Write-Host "Mod Source Files:" -ForegroundColor White
$modFiles = @(
    'sensewright_mod\__init__.py',
    'sensewright_mod\main.py',
    'sensewright_mod\debug_log.py',
    'sensewright_mod\config.py',
    'sensewright_mod\http_client.py',
    'sensewright_mod\state_collector.py',
    'sensewright_mod\intent_bus.py',
    'sensewright_mod\tool_executor.py',
    'sensewright_mod\native_hooks.py',
    'sensewright_mod\tuning.py',
    'sensewright_mod\chat_ui.py',
    'sensewright_mod\panel_ui.py',
    'sensewright_mod\pie_menu.py',
    'sensewright_mod\interactions.py',
    'sensewright_mod\player_activity.py',
    'sensewright_mod\i18n.py',
    'sensewright_mod\locales\ui\en-US.json',
    'sensewright_mod\locales\ui\pt-BR.json',
    'sensewright_mod\locales\manifest.json'
)

foreach ($f in $modFiles) {
    $path = Join-Path $ModDir $f
    Check "Source: $f" (Test-Path $path) 'Exists' 'Missing'
}

Write-Host ""

# Locale JSON validity
Write-Host "Locale JSON Validity:" -ForegroundColor White
foreach ($lang in 'en-US', 'pt-BR') {
    $path = Join-Path $ModDir "sensewright_mod\locales\ui\$lang.json"
    if (Test-Path $path) {
        try {
            $content = Get-Content $path -Raw -Encoding UTF8
            $json = ConvertFrom-JsonDeep $content
            Check "Locale: $lang" $true 'Valid JSON' 'Invalid JSON'
        } catch {
            Check "Locale: $lang" $false "Invalid JSON: $($_.Exception.Message)"
        }
    } else {
        Check "Locale: $lang" $false 'File not found'
    }
}

# Check key parity between en-US and pt-BR
$enPath = Join-Path $ModDir 'sensewright_mod\locales\ui\en-US.json'
$ptPath = Join-Path $ModDir 'sensewright_mod\locales\ui\pt-BR.json'
if ((Test-Path $enPath) -and (Test-Path $ptPath)) {
    $enJson = ConvertFrom-JsonDeep (Get-Content $enPath -Raw -Encoding UTF8)
    $ptJson = ConvertFrom-JsonDeep (Get-Content $ptPath -Raw -Encoding UTF8)

    function GetAllKeys($obj, $prefix='') {
        $keys = @()
        if ($obj -is [System.Collections.IDictionary]) {
            foreach ($key in $obj.Keys) {
                $newPrefix = if ($prefix) { "$prefix.$key" } else { $key }
                $value = $obj[$key]
                if ($value -is [System.Collections.IDictionary]) {
                    $keys += GetAllKeys $value $newPrefix
                } else {
                    $keys += $newPrefix
                }
            }
        }
        return $keys
    }

    $enKeys = GetAllKeys $enJson | Sort-Object
    $ptKeys = GetAllKeys $ptJson | Sort-Object

    $missingInPt = Compare-Object $enKeys $ptKeys | Where-Object { $_.SideIndicator -eq '<=' } | ForEach-Object { $_.InputObject }
    $extraInPt = Compare-Object $enKeys $ptKeys | Where-Object { $_.SideIndicator -eq '=>' } | ForEach-Object { $_.InputObject }

    if ($missingInPt.Count -eq 0 -and $extraInPt.Count -eq 0) {
        Check 'Locale key parity' $true 'en and pt-BR have identical keys' 'Key mismatch'
    } else {
        if ($missingInPt.Count -gt 0) {
            Check 'Locale key parity' $false "pt-BR missing keys: $($missingInPt -join ', ')"
        }
        if ($extraInPt.Count -gt 0) {
            Check 'Locale key parity' $false "pt-BR has extra keys: $($extraInPt -join ', ')" $true
        }
    }
}

Write-Host ""

# Tuning files
Write-Host "Tuning Files:" -ForegroundColor White
$tuningFiles = Get-ChildItem (Join-Path $ModDir 'tuning') -Filter '*.xml' -Recurse
foreach ($f in $tuningFiles) {
    $rel = $f.FullName.Substring($ModDir.Length + 1)
    Check "Tuning: $rel" $true 'Exists' 'Missing'
}

if (-not (Test-Path (Join-Path $ModDir 'dist\stbl_keys.json'))) {
    Check 'STBL keys' $false 'dist\stbl_keys.json not found (run build_package.py)' $true
} else {
    Check 'STBL keys' $true 'dist\stbl_keys.json exists'
}

if (-not (Test-Path (Join-Path $ModDir 'dist\tuning_ids.json'))) {
    Check 'Tuning IDs' $false 'dist\tuning_ids.json not found (run build_package.py)' $true
} else {
    Check 'Tuning IDs' $true 'dist\tuning_ids.json exists'
}

Write-Host ""

# Build artifacts
Write-Host "Build Artifacts:" -ForegroundColor White
$distDir = Join-Path $ModDir 'dist'
$ts4script = Get-ChildItem $distDir -Filter '*.ts4script' -ErrorAction SilentlyContinue | Select-Object -First 1
$package = Get-ChildItem $distDir -Filter '*.package' -ErrorAction SilentlyContinue | Select-Object -First 1

Check '.ts4script' ($ts4script -ne $null) ("Found: $($ts4script.Name)") 'Not built' $true
Check '.package' ($package -ne $null) ("Found: $($package.Name)") 'Not built' $true

if ($ts4script) {
    # Verify magic number
    try {
        $bytes = [System.IO.File]::ReadAllBytes($ts4script.FullName)
        # Check for PK header (zip)
        if ($bytes[0] -eq 0x50 -and $bytes[1] -eq 0x4B) {
            Check 'TS4Script zip format' $true 'Valid ZIP' 'Not a ZIP file'
        } else {
            Check 'TS4Script zip format' $false 'Not a valid ZIP file'
        }
    } catch {
        Check 'TS4Script zip format' $false 'Cannot read file'
    }
}

Write-Host ""

# Sidecar
Write-Host "Sidecar:" -ForegroundColor White
Check 'Sidecar directory' (Test-Path $SidecarDir) 'Exists' 'Not found' $true
Check 'sidecar/python.txt' (Test-Path (Join-Path $SidecarDir 'python.txt')) 'Exists' 'Missing (needed for autoboot)' $true
Check 'sidecar/main.py' (Test-Path (Join-Path $SidecarDir 'main.py')) 'Exists' 'Not found' $true

Write-Host ""

# TS4 Mods folder
Write-Host "The Sims 4 Environment:" -ForegroundColor White
$modsDir = "$env:USERPROFILE\Documents\Electronic Arts\The Sims 4\Mods"
# Support OneDrive-redirected Documents folders.
$oneDriveModsDir = "$env:USERPROFILE\OneDrive\Documents\Electronic Arts\The Sims 4\Mods"
if ((Test-Path $oneDriveModsDir) -and -not (Test-Path $modsDir)) {
    $modsDir = $oneDriveModsDir
}
Check 'Mods folder' (Test-Path $modsDir) 'Exists' 'Not found' $true

if (Test-Path $modsDir) {
    # Installed under Mods\Sensewright\ (or directly in Mods).
    $installedTs4script = Get-ChildItem $modsDir -Filter 'Sensewright*.ts4script' -Recurse -ErrorAction SilentlyContinue
    $installedPackage = Get-ChildItem $modsDir -Filter 'Sensewright*.package' -Recurse -ErrorAction SilentlyContinue

    Check 'Installed .ts4script' ($installedTs4script.Count -gt 0) ("Found: $($installedTs4script.Name)") 'Not installed' $true
    Check 'Installed .package' ($installedPackage.Count -gt 0) ("Found: $($installedPackage.Name)") 'Not installed' $true
}

Write-Host ""

# Summary
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  Issues: $issues" -ForegroundColor $(if ($issues -gt 0) { 'Red' } else { 'Green' })
Write-Host "  Warnings: $warnings" -ForegroundColor $(if ($warnings -gt 0) { 'Yellow' } else { 'Green' })

if ($issues -gt 0) {
    Write-Host ""
    Write-Host "Fix the issues above before building/installing." -ForegroundColor Red
    exit 1
} elseif ($warnings -gt 0) {
    Write-Host ""
    Write-Host "Warnings found but build should work." -ForegroundColor Yellow
    exit 0
} else {
    Write-Host ""
    Write-Host "All checks passed!" -ForegroundColor Green
    exit 0
}