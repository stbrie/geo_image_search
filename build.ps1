# Build script for geo_image_search.exe.
#
# Creates a venv, installs requirements.txt (which includes Nuitka), and
# compiles the GUI into a single .exe with Nuitka. The C compiler is NOT
# installed — you need Microsoft Visual Studio (or Build Tools) on the
# machine. Nuitka picks it up automatically via vswhere.
#
# Usage:
#   .\build.ps1                  # build (incremental — reuses venv if present)
#   .\build.ps1 -Clean           # wipe venv + Nuitka build dirs, then build
#   .\build.ps1 -SetupOnly       # create venv + install deps, skip build
#   .\build.ps1 -PyVersion 3.13  # use a different Python (default: 3.14)
#
# Requires: PyManager (`py` launcher) with the chosen Python version installed.
#   py install 3.14    # one-time

[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$SetupOnly,
    [string]$PyVersion = "3.14"
)

# Note: we deliberately do NOT set $ErrorActionPreference = 'Stop' here.
# PowerShell 5.1 wraps each stderr line from native commands (py, pip,
# nuitka) as a NativeCommandError; with 'Stop' that aborts the script
# even when the exe returned 0. We check $LASTEXITCODE after each native
# call instead.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $here 'venv'
$py = Join-Path $venv 'Scripts\python.exe'
$artifacts = @(
    'venv',
    'geo_image_search_gui.build',
    'geo_image_search_gui.dist',
    'geo_image_search_gui.onefile-build',
    'geo_image_search.exe'
)

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

if ($Clean) {
    Write-Step "Cleaning venv and build artifacts"
    foreach ($name in $artifacts) {
        $p = Join-Path $here $name
        if (Test-Path $p) { Remove-Item -Recurse -Force $p; Write-Host "  removed $name" }
    }
}

function Assert-Exit($name) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "$name failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if (-not (Test-Path $py)) {
    Write-Step "Creating venv with Python $PyVersion"
    # Fail fast with a helpful message if the chosen Python isn't installed.
    $available = & py -0 | Out-String
    if ($available -notmatch "-V:$([regex]::Escape($PyVersion))\b") {
        Write-Host "Python $PyVersion not found via py launcher. Install it with:" -ForegroundColor Red
        Write-Host "  py install $PyVersion" -ForegroundColor Red
        exit 1
    }
    & py -V:$PyVersion -m venv $venv
    Assert-Exit "venv creation"
}

Write-Step "Installing dependencies"
& $py -m pip install --upgrade --quiet pip
Assert-Exit "pip upgrade"
& $py -m pip install --quiet -r (Join-Path $here 'requirements.txt')
Assert-Exit "pip install"

if ($SetupOnly) {
    Write-Step "Setup complete (skipping build because of -SetupOnly)"
    exit 0
}

Write-Step "Compiling geo_image_search.exe with Nuitka"
$existingExe = Join-Path $here 'geo_image_search.exe'
if (Test-Path $existingExe) {
    # Nuitka will fail with PermissionError if the prior exe is still
    # locked (e.g. you ran it and Windows hasn't released the handle).
    # Remove it now and let Nuitka write a fresh one.
    try { Remove-Item -Force $existingExe -ErrorAction Stop }
    catch {
        Write-Host "Could not remove $existingExe (probably still running)." -ForegroundColor Red
        Write-Host "Close any open instance and rerun." -ForegroundColor Red
        exit 1
    }
}
Push-Location $here
try {
    & $py -m nuitka `
        --standalone --onefile `
        --enable-plugin=tk-inter `
        --windows-console-mode=disable `
        --include-data-files=HELP.md=HELP.md `
        --assume-yes-for-downloads `
        --output-filename=geo_image_search.exe `
        geo_image_search_gui.py
    Assert-Exit "Nuitka"
}
finally {
    Pop-Location
}

$exe = Join-Path $here 'geo_image_search.exe'
if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Built $exe ($size MB)" -ForegroundColor Green
} else {
    Write-Host "Expected $exe but it's not there." -ForegroundColor Red
    exit 1
}
