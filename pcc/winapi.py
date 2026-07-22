"""Win32 glue: foreground capture/restore, clipboard, and synthetic paste.

This is the highest-risk part of PCC. The contract is:

* :func:`get_foreground_window` is called **before** our window is shown, while
  the user's target app still owns the foreground.
* :func:`restore_focus` hands the foreground back using the ``AttachThreadInput``
  sandwich, which is the only recipe Windows honours consistently.
* :func:`send_paste` synthesises the paste chord via ``SendInput``.

Everything degrades gracefully: no function here raises on Win32 failure, they
return ``False`` so the UI can stay alive.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# --- SendInput plumbing -----------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MAPVK_VK_TO_VSC = 0

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12          # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_V = 0x56
VK_C = 0x43
VK_INSERT = 0x2D
VK_RETURN = 0x0D
VK_LEFT = 0x25

SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
SPIF_SENDCHANGE = 0x02


# ULONG_PTR: 8 bytes on x64, 4 on x86. Getting this wrong silently changes
# sizeof(INPUT), and SendInput rejects any cbSize that is not an exact match --
# it returns 0 with no error rather than doing something visibly wrong.
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    """Unused, but it is the largest union member and therefore sets its size."""

    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


assert ctypes.sizeof(INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28), (
    f"unexpected sizeof(INPUT)={ctypes.sizeof(INPUT)}; SendInput would silently fail"
)


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD


def _key_event(vk: int, key_up: bool) -> INPUT:
    """Build a keystroke carrying both the virtual key and its scan code.

    Supplying ``wScan`` alongside ``wVk`` keeps apps happy that read either one
    (Electron and terminal emulators are the usual offenders) without making the
    keystroke layout-dependent.
    """
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_KEYUP if key_up else 0
    event = INPUT(type=INPUT_KEYBOARD)
    event.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return event


def _send(inputs: list[INPUT]) -> bool:
    if not inputs:
        return True
    array = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))
    return sent == len(inputs)


def _release_stray_modifiers() -> None:
    """Drop Shift/Alt/Win if they are physically down.

    The palette is opened from a chord, so a modifier can still be held when the
    user hits Enter. A stray Shift turns Ctrl+V into Ctrl+Shift+V (paste-as-
    plain-text in some apps, nothing at all in others). Ctrl is left alone -- we
    are about to press it anyway.
    """
    stray = [vk for vk in (VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN)
             if user32.GetAsyncKeyState(vk) & 0x8000]
    if stray:
        _send([_key_event(vk, key_up=True) for vk in stray])


# --- Foreground window ------------------------------------------------------


def get_foreground_window() -> int:
    return int(user32.GetForegroundWindow() or 0)


def is_window(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(wintypes.HWND(hwnd)))


def relax_foreground_lock() -> None:
    """Ask Windows to stop rate-limiting foreground changes.

    Without this, ``SetForegroundWindow`` can be downgraded to a taskbar flash
    when the user has been typing in another app.
    """
    try:
        user32.SystemParametersInfoW(
            SPI_SETFOREGROUNDLOCKTIMEOUT, 0, ctypes.c_void_p(0), SPIF_SENDCHANGE
        )
    except Exception:
        pass


def _activate_attached(hwnd: int, borrow_tid: int) -> bool:
    """Activate ``hwnd`` while sharing input state with thread ``borrow_tid``.

    Windows only honours ``SetForegroundWindow`` from the process that already
    owns the foreground. Attaching our input queue to a thread that does own it
    makes the call legitimate; without this the request is silently downgraded
    to a taskbar flash.
    """
    target = wintypes.HWND(hwnd)
    our_tid = kernel32.GetCurrentThreadId()

    attached = False
    if borrow_tid and borrow_tid != our_tid:
        attached = bool(user32.AttachThreadInput(our_tid, borrow_tid, True))
    try:
        user32.SetForegroundWindow(target)
        user32.BringWindowToTop(target)
        user32.SetActiveWindow(target)
        user32.SetFocus(target)
    finally:
        if attached:
            user32.AttachThreadInput(our_tid, borrow_tid, False)

    return int(user32.GetForegroundWindow() or 0) == hwnd


def restore_focus(hwnd: int) -> bool:
    """Give the foreground back to ``hwnd`` after the palette is done.

    Here we are the outgoing foreground process, so we borrow the *target's*
    thread and hand off.
    """
    if not is_window(hwnd):
        return False
    target_tid = user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), None)
    if not target_tid:
        return False
    return _activate_attached(hwnd, target_tid)


def force_foreground(hwnd: int) -> bool:
    """Take the foreground for our own ``hwnd`` when we are *not* foreground.

    This is the harder direction and the one Qt's ``activateWindow()`` cannot
    do: the palette is summoned by AutoHotkey while some other app is focused,
    so we borrow the thread of whatever currently holds the foreground in order
    to be allowed to take it. Without this the palette paints on top but never
    receives a keystroke.
    """
    if not is_window(hwnd):
        return False
    current = int(user32.GetForegroundWindow() or 0)
    if current == hwnd:
        return True
    borrow_tid = (
        user32.GetWindowThreadProcessId(wintypes.HWND(current), None) if current else 0
    )
    return _activate_attached(hwnd, borrow_tid)


# --- Clipboard --------------------------------------------------------------

CF_UNICODETEXT = 13


def _with_clipboard(fn, attempts: int = 8):
    """Run ``fn`` with the clipboard open, retrying while another app holds it."""
    import win32clipboard

    for attempt in range(attempts):
        try:
            win32clipboard.OpenClipboard()
        except Exception:
            time.sleep(0.01 * (attempt + 1))
            continue
        try:
            return fn(win32clipboard)
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
    return None


def clipboard_get_text() -> str | None:
    """Current clipboard text, or ``None`` if it holds something else / nothing.

    ``None`` deliberately means "do not restore": clobbering a copied image with
    an empty string would be worse than leaving our prompt on the clipboard.
    """

    def read(clip):
        if not clip.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        try:
            return clip.GetClipboardData(CF_UNICODETEXT)
        except Exception:
            return None

    return _with_clipboard(read)


def clipboard_set_text(text: str) -> bool:
    def write(clip):
        clip.EmptyClipboard()
        clip.SetClipboardData(CF_UNICODETEXT, text)
        return True

    return bool(_with_clipboard(write))


# --- Paste ------------------------------------------------------------------


def send_chord(modifier_vk: int, key_vk: int) -> bool:
    """Press ``modifier_vk``+``key_vk`` and release both, into the focused window.

    The one primitive behind every synthesised shortcut here (Ctrl+V paste,
    Ctrl+C capture, ...). Modifiers held by the user are dropped first so a stray
    Shift cannot turn the chord into something else.
    """
    _release_stray_modifiers()
    return _send([
        _key_event(modifier_vk, key_up=False),
        _key_event(key_vk, key_up=False),
        _key_event(key_vk, key_up=True),
        _key_event(modifier_vk, key_up=True),
    ])


def send_paste(chord: str = "ctrl+v") -> bool:
    """Synthesise the paste chord into whatever currently has focus."""
    if chord == "shift+insert":
        return send_chord(VK_SHIFT, VK_INSERT)
    return send_chord(VK_CONTROL, VK_V)


def send_copy() -> bool:
    """Ctrl+C into the focused window -- used to capture the selection."""
    return send_chord(VK_CONTROL, VK_C)


def send_enter() -> bool:
    """Tap Enter into the focused window (paste-and-send)."""
    _release_stray_modifiers()
    return _send([_key_event(VK_RETURN, key_up=False), _key_event(VK_RETURN, key_up=True)])


def send_key_taps(key_vk: int, count: int) -> bool:
    """Tap ``key_vk`` ``count`` times -- e.g. Left arrows to park the caret."""
    if count <= 0:
        return True
    inputs: list[INPUT] = []
    for _ in range(count):
        inputs.append(_key_event(key_vk, key_up=False))
        inputs.append(_key_event(key_vk, key_up=True))
    return _send(inputs)


def clipboard_sequence() -> int:
    """``GetClipboardSequenceNumber``: bumps whenever the clipboard changes.

    Lets selection capture tell "the user copied something" from "nothing was
    selected, so Ctrl+C did nothing" without comparing clipboard contents.
    """
    try:
        return int(user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


def send_unicode_text(text: str) -> bool:
    """Type ``text`` directly as Unicode keystrokes.

    Fallback for the rare app that ignores the clipboard. Not the default: it is
    O(n) in the length of the prompt and far slower for multi-line templates.
    """
    inputs: list[INPUT] = []
    for char in text:
        for key_up in (False, True):
            event = INPUT(type=INPUT_KEYBOARD)
            event.ki = KEYBDINPUT(
                wVk=0,
                wScan=ord(char),
                dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0),
                time=0,
                dwExtraInfo=0,
            )
            inputs.append(event)
    return _send(inputs)


def is_elevated() -> bool:
    """Whether we run elevated -- determines if we can paste into admin windows."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# --- Window identity (for context resolvers) --------------------------------

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def window_title(hwnd: int) -> str:
    """Title bar text of ``hwnd``, or ``""``.

    Feeds the ``{{window}}`` magic slot. Never raises: an invalid handle or a
    window that refuses the query just yields an empty string, which resolves to
    the literal token exactly like any other unavailable context.
    """
    if not is_window(hwnd):
        return ""
    try:
        length = int(user32.GetWindowTextLengthW(wintypes.HWND(hwnd)))
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
        return buffer.value or ""
    except Exception:
        return ""


def process_name(hwnd: int) -> str:
    """Executable name that owns ``hwnd`` (e.g. ``Code.exe``), or ``""``.

    ``QueryFullProcessImageNameW`` rather than the older ``GetModuleFileNameEx``:
    it needs only ``PROCESS_QUERY_LIMITED_INFORMATION``, which Windows grants
    across integrity levels, so it still answers for an elevated target when PCC
    is not. The handle is always closed; every failure path returns ``""``.
    """
    if not is_window(hwnd):
        return ""
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(
            wintypes.HANDLE(handle), 0, buffer, ctypes.byref(size)
        )
        if not ok:
            return ""
        full = buffer.value or ""
        return full.rsplit("\\", 1)[-1]
    except Exception:
        return ""
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(handle))
