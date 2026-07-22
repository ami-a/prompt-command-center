# Capture a window by title to a PNG so the UI can be inspected.
param([string]$Title = "PCC", [string]$Out = "E:\Prpjects\2026\PCC\spike\shot.png")

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Cap {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern IntPtr FindWindow(string cls, string title);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@

# Without this the capture process is DPI-virtualised: GetWindowRect returns
# logical pixels while the framebuffer is physical, and the shot comes out
# cropped and magnified on this 175 % display.
[void][Cap]::SetProcessDPIAware()

$h = [Cap]::FindWindow([NullString]::Value, $Title)
if ($h -eq 0) { Write-Output "window '$Title' not found"; exit 1 }
$r = New-Object Cap+RECT
[void][Cap]::GetWindowRect($h, [ref]$r)
$w = $r.R - $r.L; $ht = $r.B - $r.T
Write-Output "rect = $($r.L),$($r.T) ${w}x${ht}"
if ($w -le 0 -or $ht -le 0) { Write-Output "window not visible"; exit 1 }

$bmp = New-Object System.Drawing.Bitmap $w, $ht
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, (New-Object System.Drawing.Size $w, $ht))
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved $Out"
