# Trigger the palette and photograph it. Runs entirely in-process: spawning a
# child console would steal the foreground and the palette would auto-hide.
param(
    [string]$Out = "snap.png",
    [string]$Keys = "",
    [int]$SettleMs = 500
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class S {
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
[void][S]::SetProcessDPIAware()

$root = Split-Path -Parent $PSScriptRoot
$hostWin = [S]::FindWindow([NullString]::Value, "PCC_IPC_HOST")
if ($hostWin -eq 0) { Write-Output "PCC is not running"; exit 1 }

[void][S]::PostMessage($hostWin, 0x8000, [IntPtr]::Zero, [IntPtr]::Zero)
Start-Sleep -Milliseconds 700
if ($Keys) { [System.Windows.Forms.SendKeys]::SendWait($Keys); Start-Sleep -Milliseconds $SettleMs }

$p = [S]::FindWindow([NullString]::Value, "PCC")
if (-not [S]::IsWindowVisible($p)) { Write-Output "palette not visible"; exit 1 }
$r = New-Object S+RECT
[void][S]::GetWindowRect($p, [ref]$r)
$w = $r.R - $r.L; $h = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, (New-Object System.Drawing.Size $w, $h))
$bmp.Save("$root\spike\$Out", [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved $Out (${w}x${h} at $($r.L),$($r.T))"

[System.Windows.Forms.SendKeys]::SendWait("{ESC}")
