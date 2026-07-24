# End-to-end driver.
#
# Starts a paste target, has it trigger PCC while it owns the foreground (the
# only way to reproduce what AHK does), then sends real keystrokes to the
# palette and reports what landed in the target.
#
# Everything runs in THIS process: spawning a child powershell pops a console
# that steals the foreground, which makes the palette auto-hide on deactivate
# and silently invalidates the test.
param(
    [string]$Keys = "",
    [int]$SettleMs = 900,
    [switch]$Shot,
    [string]$ShotName = "drive.png"
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class D {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern IntPtr FindWindow(string cls, string title);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
}
"@
[void][D]::SetProcessDPIAware()

$root = Split-Path -Parent $PSScriptRoot
$py = "$root\.venv\Scripts\python.exe"
$received = "$root\spike\received.txt"

function Capture([string]$title, [string]$out) {
    $h = [D]::FindWindow([NullString]::Value, $title)
    if ($h -eq 0) { Write-Output "  capture: '$title' not found"; return }
    if (-not [D]::IsWindowVisible($h)) { Write-Output "  capture: '$title' hidden"; return }
    $r = New-Object D+RECT
    [void][D]::GetWindowRect($h, [ref]$r)
    $w = $r.R - $r.L; $ht = $r.B - $r.T
    if ($w -le 0 -or $ht -le 0) { Write-Output "  capture: empty rect"; return }
    $bmp = New-Object System.Drawing.Bitmap $w, $ht
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($r.L, $r.T, 0, 0, (New-Object System.Drawing.Size $w, $ht))
    $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "  captured $out (${w}x${ht})"
}

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*spike\target.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item $received -ErrorAction SilentlyContinue

Start-Process -FilePath $py -ArgumentList "$root\spike\target.py","--self-trigger"
Start-Sleep -Milliseconds 4200   # 2500 ms self-trigger delay + startup + fade

$palette = [D]::FindWindow([NullString]::Value, "PCC")
$fg = [D]::GetForegroundWindow()
$focused = if ($fg -eq $palette) { "YES" } else { "NO (fg=$fg)" }
$pr = New-Object D+RECT
[void][D]::GetWindowRect($palette, [ref]$pr)
Write-Output "palette hwnd = $palette ; visible = $([D]::IsWindowVisible($palette)) ; has focus = $focused"
Write-Output "palette rect = $($pr.L),$($pr.T) $($pr.R - $pr.L)x$($pr.B - $pr.T)"

if ($Shot) {
    # Whole virtual desktop: a window-rect crop cannot tell "not painted" apart
    # from "painted somewhere else".
    $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
    Write-Output "  virtual screen = $($vs.X),$($vs.Y) $($vs.Width)x$($vs.Height)"
    $bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($vs.X, $vs.Y, 0, 0, (New-Object System.Drawing.Size $vs.Width, $vs.Height))
    $bmp.Save("$root\spike\$ShotName", [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "  captured full desktop -> $ShotName"
}

if ($Keys) {
    Write-Output "sending: $Keys"
    [System.Windows.Forms.SendKeys]::SendWait($Keys)
    Start-Sleep -Milliseconds $SettleMs
}

Write-Output "--- target received ---"
if (Test-Path $received) {
    Write-Output "[[$(Get-Content $received -Raw -Encoding UTF8)]]"
} else {
    Write-Output "<no file>"
}
