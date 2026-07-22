# Fires the real CapsLock+Space chord and reports what happened.
#
# Exercises the cold path specifically: PCC is killed first, so AHK must launch
# it, wait for the host window, and then trigger -- the exact sequence that was
# reporting "failed to start".
param([int]$WaitSeconds = 12, [switch]$ColdStart)

Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class K {
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern IntPtr FindWindow(string cls, string title);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[void][K]::SetProcessDPIAware()

$root = "E:\Prpjects\2026\PCC"
$py = "$root\.venv\Scripts\python.exe"
$KEYUP = 0x2
$VK_CAPITAL = 0x14
$VK_SPACE = 0x20

function Pcc-Processes {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*-m pcc*" }
}

if ($ColdStart) {
    Pcc-Processes | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 700
    Write-Output "cold start: PCC processes killed ($((Pcc-Processes | Measure-Object).Count) left)"
}

# A real window to be the paste target and the foreground app.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*spike\target.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item "$root\spike\received.txt" -ErrorAction SilentlyContinue
Start-Process -FilePath $py -ArgumentList "$root\spike\target.py"
Start-Sleep -Seconds 3
Write-Output "foreground before chord = $([K]::GetForegroundWindow())"

Write-Output "sending CapsLock+Space ..."
[K]::keybd_event($VK_CAPITAL, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 40
[K]::keybd_event($VK_SPACE, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 40
[K]::keybd_event($VK_SPACE, 0, $KEYUP, [IntPtr]::Zero)
Start-Sleep -Milliseconds 40
[K]::keybd_event($VK_CAPITAL, 0, $KEYUP, [IntPtr]::Zero)

# Poll rather than sleeping blind: a cold start includes venv python + Qt init.
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$palette = [IntPtr]::Zero
while ((Get-Date) -lt $deadline) {
    $palette = [K]::FindWindow([NullString]::Value, "PCC")
    if ($palette -ne 0 -and [K]::IsWindowVisible($palette)) { break }
    Start-Sleep -Milliseconds 250
}

$procs = @(Pcc-Processes)
Write-Output "PCC processes  = $($procs.Count)"
$hostWin = [K]::FindWindow([NullString]::Value, "PCC_IPC_HOST")
Write-Output "PCC_IPC_HOST   = $hostWin"
Write-Output "palette hwnd   = $palette"
Write-Output "palette visible= $(if ($palette -ne 0) { [K]::IsWindowVisible($palette) } else { $false })"
$fg = [K]::GetForegroundWindow()
Write-Output "has focus      = $(if ($fg -eq $palette) { 'YES' } else { "NO (fg=$fg)" })"

# Leave CapsLock off regardless of how the chord was interpreted.
if ([System.Windows.Forms.Control]::IsKeyLocked([System.Windows.Forms.Keys]::CapsLock)) {
    [K]::keybd_event($VK_CAPITAL, 0, 0, [IntPtr]::Zero)
    [K]::keybd_event($VK_CAPITAL, 0, $KEYUP, [IntPtr]::Zero)
    Write-Output "(reset CapsLock)"
}
