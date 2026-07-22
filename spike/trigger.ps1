# Spike driver: focus the paste target, then post WM_APP at the PCC host
# window exactly the way AutoHotkey will.
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern IntPtr FindWindow(string cls, string title);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
}
"@

# [NullString]::Value, not $null -- PowerShell marshals $null to "" for string
# parameters, and FindWindowW("" , title) matches a class named "", i.e. nothing.
$target = [W]::FindWindow([NullString]::Value, "PCC_SPIKE_TARGET")
$hostWin = [W]::FindWindow([NullString]::Value, "PCC_IPC_HOST")
Write-Output "target hwnd = $target"
Write-Output "host   hwnd = $hostWin"
if ($target -eq 0 -or $hostWin -eq 0) { Write-Output "MISSING WINDOW"; exit 1 }

[void][W]::SetForegroundWindow($target)
Start-Sleep -Milliseconds 600
Write-Output "foreground before post = $([W]::GetForegroundWindow())"
[void][W]::PostMessage($hostWin, 0x8000, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Output "posted WM_APP"
