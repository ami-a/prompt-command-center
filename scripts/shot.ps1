# Capture the PCC palette in a given UI state to a PNG, for the README and docs.
#
#   # PCC must already be running:
#   .venv\Scripts\pythonw.exe -m pcc
#
#   powershell -ExecutionPolicy Bypass -File scripts\shot.ps1 -Out assets\palette.png
#   powershell -ExecutionPolicy Bypass -File scripts\shot.ps1 -Keys "refactor{ENTER}" -Out assets\fill-panel.png
#   powershell -ExecutionPolicy Bypass -File scripts\shot.ps1 -Keys "^," -Out assets\settings.png
#
# Runs entirely in this process on purpose: spawning a child console would steal
# the foreground and the palette would auto-hide on deactivate, capturing nothing.
# Needs an UNLOCKED, interactive desktop session (same constraint as verify.ps1).
param(
    [string]$Out = "$PSScriptRoot\..\assets\shot.png",
    [string]$Keys = "",
    [int]$SettleMs = 650,
    [switch]$KeepOpen
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Shot {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern IntPtr FindWindow(string cls, string title);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
}
"@

# Without this the capture process is DPI-virtualised: GetWindowRect returns
# logical pixels while the framebuffer is physical, and the shot comes out
# cropped and magnified on a scaled display.
[void][Shot]::SetProcessDPIAware()

$hostWin = [Shot]::FindWindow([NullString]::Value, "PCC_IPC_HOST")
if ($hostWin -eq 0) {
    Write-Error "PCC is not running. Start it first:  .venv\Scripts\pythonw.exe -m pcc"
    exit 1
}

# Show the palette fresh (WM_APP = 0x8000, CMD_SHOW = 0), then drive it into the
# requested state with real keystrokes.
[void][Shot]::PostMessage($hostWin, 0x8000, [IntPtr]::Zero, [IntPtr]::Zero)
Start-Sleep -Milliseconds 750
if ($Keys) { [System.Windows.Forms.SendKeys]::SendWait($Keys); Start-Sleep -Milliseconds $SettleMs }

$p = [Shot]::FindWindow([NullString]::Value, "PCC")
if ($p -eq 0 -or -not [Shot]::IsWindowVisible($p)) { Write-Error "palette not visible"; exit 1 }
$r = New-Object Shot+RECT
[void][Shot]::GetWindowRect($p, [ref]$r)
$w = $r.R - $r.L; $h = $r.B - $r.T
if ($w -le 0 -or $h -le 0) { Write-Error "palette has an empty rect"; exit 1 }

$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, (New-Object System.Drawing.Size $w, $h))
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved $Out (${w}x${h} at $($r.L),$($r.T))"

# Dismiss the palette so the next capture starts from a clean state.
if (-not $KeepOpen) { [System.Windows.Forms.SendKeys]::SendWait("{ESC}{ESC}") }
