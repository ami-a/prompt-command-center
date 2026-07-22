# PCC installer: venv, dependencies, and AutoHotkey wiring.
# Safe to re-run; every step is idempotent and nothing is overwritten silently.
[CmdletBinding()]
param(
    [string]$BasePython = "D:\Python\Python3116\python.exe",
    [string]$AhkScript  = "E:\Prpjects\2023\ShortCutKeyboard\a001.ahk",
    [switch]$SkipAhk
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv"
$py   = Join-Path $venv "Scripts\python.exe"

Write-Host "PCC setup -- $root" -ForegroundColor Cyan

if (-not (Test-Path $BasePython)) {
    # Fall back to the launcher if the recorded interpreter has moved.
    $BasePython = (& py -3 -c "import sys; print(sys.executable)")
    Write-Host "  base python resolved via py launcher: $BasePython"
}

if (-not (Test-Path $py)) {
    Write-Host "  creating venv..." -ForegroundColor Yellow
    & $BasePython -m venv $venv
} else {
    Write-Host "  venv already present" -ForegroundColor DarkGray
}

Write-Host "  installing dependencies..." -ForegroundColor Yellow
& $py -m pip install --disable-pip-version-check -q -r (Join-Path $root "requirements.txt")

Write-Host "  verifying imports..." -ForegroundColor Yellow
& $py -c "from PySide6 import QtWidgets; import rapidfuzz, watchdog, win32clipboard; print('    dependencies OK')"
if ($LASTEXITCODE -ne 0) { throw "dependency verification failed" }

& $py -m pytest (Join-Path $root "tests") -q
if ($LASTEXITCODE -ne 0) { throw "tests failed" }

# --- AutoHotkey wiring ------------------------------------------------------
if (-not $SkipAhk) {
    $include = "#Include $root\scripts\pcc.ahk"
    if (-not (Test-Path $AhkScript)) {
        Write-Host "  ! AHK script not found at $AhkScript -- add this line yourself:" -ForegroundColor Red
        Write-Host "      $include"
    } elseif ((Get-Content $AhkScript -Raw) -match [regex]::Escape("scripts\pcc.ahk")) {
        Write-Host "  AHK include already present" -ForegroundColor DarkGray
    } else {
        Copy-Item $AhkScript "$AhkScript.bak-$(Get-Date -Format yyyyMMddHHmmss)"
        Add-Content -Path $AhkScript -Value "`r`n; --- PCC Prompt Command Center ---`r`n$include`r`n" -Encoding UTF8
        Write-Host "  added include to $AhkScript (backup kept)" -ForegroundColor Green
        Write-Host "  reload AHK for CapsLock+Space to take effect" -ForegroundColor Yellow
    }
}

# --- Autostart --------------------------------------------------------------
$startup = [Environment]::GetFolderPath("Startup")
$shortcut = Join-Path $startup "PCC.lnk"
if (-not (Test-Path $shortcut)) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $link.TargetPath = Join-Path $venv "Scripts\pythonw.exe"   # pythonw = no console
    $link.Arguments = "-m pcc"
    $link.WorkingDirectory = $root
    $link.Description = "PCC - Prompt Command Center"
    $link.Save()
    Write-Host "  added startup shortcut" -ForegroundColor Green
} else {
    Write-Host "  startup shortcut already present" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "Done. Start now with:" -ForegroundColor Cyan
Write-Host "  $venv\Scripts\pythonw.exe -m pcc" -ForegroundColor White
Write-Host "Then press CapsLock+Space." -ForegroundColor White
