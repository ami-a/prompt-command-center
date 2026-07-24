; PCC — Prompt Command Center trigger.  AutoHotkey v1.1 syntax.
;
;     #Include <path-to-repo>\scripts\pcc.ahk
;
; Include this ANYWHERE, including at the very bottom of a script after the last
; hotkey. Everything lives inside PCC_Show() on purpose: top-level assignments
; in an included file only run if the #Include lands in the auto-execute section
; (above the script's first Return). Appended to the end of another script they
; are unreachable, the variables stay empty, and `Run` is handed an empty
; command — which surfaces as "failed to start PCC". Locals inside a function
; have no such dependency on where the file is pasted.
;
; The repo root is derived from this file's own location (A_LineFile), so the
; trigger works from any clone path — nothing here is machine-specific.

Capslock & Space::
    KeyWait, CapsLock             ; matches the style of the other Capslock hotkeys
    PCC_Show()
Return

PCC_Show() {
    ; Derive the repo root from this file's own path: <root>\scripts\pcc.ahk.
    ; A_LineFile is the full path of the file holding this line, so the include
    ; is portable no matter where the repo is cloned or how it is #Included.
    SplitPath, A_LineFile, , scriptDir     ; scriptDir = <root>\scripts
    SplitPath, scriptDir,  , root          ; root      = <root>
    exe  := root . "\.venv\Scripts\pythonw.exe"   ; pythonw = no console flash
    host := "PCC_IPC_HOST"
    WM_APP := 0x8000
    CMD_SHOW := 0

    DetectHiddenWindows, On       ; the host window is never shown
    SetTitleMatchMode, 3          ; exact, so we cannot hit an unrelated window

    ; Already resident: this is the fast path, roughly a millisecond, and it
    ; needs no foreground rights so PCC can still see which window you were in.
    IfWinExist, %host%
    {
        PostMessage, %WM_APP%, %CMD_SHOW%, 0,, %host%
        return
    }

    if !FileExist(exe)
    {
        MsgBox, 16, PCC, % "PCC is not installed here:`n" exe "`n`nRun scripts\setup.ps1 first."
        return
    }

    ; Self-healing: start it, wait for the window, then trigger as usual.
    Run, "%exe%" -m pcc, %root%, Hide, pid
    if ErrorLevel
    {
        MsgBox, 16, PCC, % "Could not launch:`n" exe
        return
    }

    WinWait, %host%,, 15
    if ErrorLevel
    {
        MsgBox, 16, PCC, % "PCC started (pid " pid ") but never created its window.`n`n"
            . "Run this to see the error:`n  """ root "\.venv\Scripts\python.exe"" -m pcc"
        return
    }

    PostMessage, %WM_APP%, %CMD_SHOW%, 0,, %host%
}
