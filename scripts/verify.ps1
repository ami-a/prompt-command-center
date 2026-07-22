# PCC end-to-end GUI verification.
#
#   powershell -ExecutionPolicy Bypass -File E:\Prpjects\2026\PCC\scripts\verify.ps1
#
# Requires an UNLOCKED, interactive session: nothing can take the foreground,
# read the screen, or receive synthetic keystrokes while Windows is locked.
#
# Everything runs in this process on purpose. Spawning a child console would
# steal the foreground and make the palette auto-hide, silently invalidating
# every result.
[CmdletBinding()]
param([switch]$KeepRunning)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class V {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern IntPtr FindWindow(string cls, string title);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
}
"@
[void][V]::SetProcessDPIAware()

$root = Split-Path -Parent $PSScriptRoot
$py   = Join-Path $root ".venv\Scripts\python.exe"
$recv = Join-Path $root "spike\received.txt"
$err  = Join-Path $root "spike\verify.err"

$script:pass = 0
$script:fail = 0
function Check([string]$name, [bool]$ok, [string]$detail = "") {
    if ($ok) { $script:pass++; Write-Host "  PASS  $name" -ForegroundColor Green }
    else     { $script:fail++; Write-Host "  FAIL  $name  $detail" -ForegroundColor Red }
}

if (Get-Process LogonUI -ErrorAction SilentlyContinue) {
    Write-Host "Session is LOCKED. Unlock Windows and re-run." -ForegroundColor Red
    exit 2
}

function Stop-Pcc {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*-m pcc*" -or $_.CommandLine -like "*spike\target.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Start-Target {
    # The target self-triggers PCC 2.5 s after it starts, while IT owns the
    # foreground -- the only faithful reproduction of the AHK path.
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*spike\target.py*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Remove-Item $recv -ErrorAction SilentlyContinue
    Start-Process -FilePath $py -ArgumentList "$root\spike\target.py","--self-trigger"
    Start-Sleep -Milliseconds 4200
}

function Get-Received {
    if (Test-Path $recv) { (Get-Content $recv -Raw -Encoding UTF8) } else { "" }
}

function Send([string]$keys, [int]$settle = 700) {
    [System.Windows.Forms.SendKeys]::SendWait($keys)
    Start-Sleep -Milliseconds $settle
}

Write-Host "`nPCC end-to-end verification" -ForegroundColor Cyan
Write-Host ("-" * 52)

Stop-Pcc
Start-Sleep -Milliseconds 500
$env:PCC_TIMING = "1"
Remove-Item $err -ErrorAction SilentlyContinue
Start-Process -FilePath $py -ArgumentList "-m","pcc" -WorkingDirectory $root -RedirectStandardError $err
Start-Sleep -Seconds 4

# --- 1. IPC host exists -----------------------------------------------------
$hostWin = [V]::FindWindow([NullString]::Value, "PCC_IPC_HOST")
Check "IPC host window exists (AHK can find it)" ($hostWin -ne 0) "FindWindow returned 0"

# --- 2. trigger, focus, placement ------------------------------------------
Write-Host "`nTrigger and focus" -ForegroundColor Cyan
Start-Target
$palette = [V]::FindWindow([NullString]::Value, "PCC")
$fg = [V]::GetForegroundWindow()
Check "palette is visible after trigger" ([V]::IsWindowVisible($palette))
Check "palette holds keyboard focus" ($fg -eq $palette) "foreground=$fg palette=$palette"

$r = New-Object V+RECT
[void][V]::GetWindowRect($palette, [ref]$r)
$onScreen = ($r.R -gt $r.L) -and ($r.B -gt $r.T) -and ($r.L -ge 0) -and ($r.T -ge 0)
Check "palette placed on-screen" $onScreen "rect=$($r.L),$($r.T),$($r.R),$($r.B)"

# --- 3. search + fill + paste ----------------------------------------------
Write-Host "`nSearch, fill panel, paste" -ForegroundColor Cyan
Send "refactor" 500          # fuzzy-filter to "Refactor for readability"
Send "{ENTER}" 500           # has slots -> opens the fill panel
Send "Rust" 300              # fills {{language}}, which has default Python
Send "{ENTER}" 1200          # paste

$got = Get-Received
Check "paste landed in the target window" ($got.Length -gt 0) "target still empty"
Check "typed slot value was used" ($got -like "*Rust*") "got: $got"
Check "unfilled slot fell back to its default" ($got -like "*readability*") "got: $got"
Check "no raw tokens leaked for slots with defaults" (-not ($got -like "*{{goal*")) "got: $got"
Check "literal token kept for slot without a default" ($got -like "*{{code}}*") "got: $got"
Check "palette hid itself after pasting" (-not [V]::IsWindowVisible($palette))

# --- 4. Esc dismisses without pasting --------------------------------------
Write-Host "`nEsc dismisses without pasting" -ForegroundColor Cyan
Start-Target
$before = Get-Received      # after Start-Target: it recreates the capture file
Send "{ESC}" 500
$palette = [V]::FindWindow([NullString]::Value, "PCC")
Check "palette hidden by Esc" (-not [V]::IsWindowVisible($palette))
Check "Esc pasted nothing" ((Get-Received) -eq $before)

# --- 5. show latency --------------------------------------------------------
Write-Host "`nPerformance" -ForegroundColor Cyan
$timings = @()
if (Test-Path $err) {
    Get-Content $err | Where-Object { $_ -match "show ([\d.]+) ms" } |
        ForEach-Object { $timings += [double]$Matches[1] }
}
if ($timings.Count) {
    Write-Host ("  show latency: " + (($timings | ForEach-Object { "{0:N1}" -f $_ }) -join ", ") + " ms")
    # Two budgets, because they measure two different things.
    #
    # The first trigger of a session pays Windows' cross-process focus handoff
    # (AttachThreadInput + SetForegroundWindow) against whatever app happened to
    # be foreground. That is required for correctness, cannot be pre-warmed
    # away, and its cost depends on how promptly the other process's thread
    # responds -- measured across runs at 30.4 / 32.4 / 36.1 / 37.2 / 45.0 ms.
    # A single-sample threshold set at the observed maximum is flaky by
    # construction, so this is set above the spread rather than at its edge; it
    # is a regression guard, not a target. Still well under the ~100 ms where a
    # delay becomes perceptible.
    Check "first trigger under 60 ms" ($timings[0] -lt 60) "first=$($timings[0])ms"
    if ($timings.Count -gt 1) {
        $warm = ($timings[1..($timings.Count - 1)] | Measure-Object -Maximum).Maximum
        Check "subsequent triggers under 20 ms" ($warm -lt 20) "worst warm=${warm}ms"
    }
} else {
    Check "show latency captured" $false "no timing lines in $err"
}

# A venv launcher and the interpreter it re-execs both match "-m pcc"; the real
# one is whichever actually holds the Qt heap, so take the largest.
$proc = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*-m pcc*" } |
        ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } |
        Sort-Object WorkingSet64 -Descending | Select-Object -First 1
if ($proc) {
    $mb = [math]::Round($proc.WorkingSet64 / 1MB, 1)
    Write-Host "  resident memory: $mb MB"
    Check "resident memory under 150 MB" ($mb -lt 150) "${mb}MB"
}

# --- crash check ------------------------------------------------------------
$traceback = if (Test-Path $err) { Get-Content $err | Where-Object { $_ -match "Traceback|Error" } } else { @() }
Check "no exceptions logged" ($traceback.Count -eq 0) ($traceback -join " | ")

Write-Host ("-" * 52)
Write-Host "  $script:pass passed, $script:fail failed" -ForegroundColor $(if ($script:fail) { "Red" } else { "Green" })

if (-not $KeepRunning) { Stop-Pcc; Write-Host "  (PCC stopped; pass -KeepRunning to leave it up)" -ForegroundColor DarkGray }
exit $(if ($script:fail) { 1 } else { 0 })
