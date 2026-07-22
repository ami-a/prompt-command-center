"""Trigger channel: AutoHotkey -> PCC.

AHK posts ``WM_APP`` to a well-known, never-shown top-level window. That is
roughly a millisecond of work and needs no sockets, no ports, and no polling.

Two details matter and are easy to get wrong:

* The host must be a genuine **top-level** window, not a ``HWND_MESSAGE``-only
  one -- message-only windows are invisible to AHK's ``WinExist``/``FindWindow``.
* ``winId()`` must be touched so Qt actually creates the HWND for a widget that
  is never shown.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtWidgets import QWidget

#: Window title AHK looks for. Must stay in sync with ``scripts/pcc.ahk``.
HOST_TITLE = "PCC_IPC_HOST"

WM_APP = 0x8000
#: wParam values, so one message type can carry several commands.
CMD_SHOW = 0
CMD_TOGGLE = 1
CMD_QUIT = 2


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt_x", wintypes.LONG),
        ("pt_y", wintypes.LONG),
    ]


class HostWindow(QWidget):
    """Invisible window whose only job is to own a findable HWND.

    Created *unarmed*: the window exists (so its HWND can be handed to the event
    filter) but carries a placeholder title, so AHK's ``WinWait`` cannot find it
    yet. Call :meth:`arm` once the filter is installed. Without this, a trigger
    arriving in the gap between window creation and filter installation is
    dispatched to a window that is not yet listening and silently vanishes.
    """

    UNARMED_TITLE = HOST_TITLE + "_STARTING"

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Tool)
        self.setWindowTitle(self.UNARMED_TITLE)
        self.setObjectName(HOST_TITLE)
        self.setFixedSize(1, 1)
        # Force native window creation without ever showing it.
        self.hwnd = int(self.winId())

    def arm(self) -> None:
        """Publish the well-known title; from here on AHK can reach us."""
        self.setWindowTitle(HOST_TITLE)


class TriggerFilter(QAbstractNativeEventFilter):
    """Routes ``WM_APP`` posted at the host window to Python callbacks.

    Runs on Qt's main thread inside the event loop, so handlers may touch the
    UI directly. Keep them fast -- this sits on the message pump.
    """

    def __init__(self, hwnd: int, handlers: dict[int, Callable[[], None]]) -> None:
        super().__init__()
        self._hwnd = hwnd
        self._handlers = handlers

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt naming)
        if event_type != b"windows_generic_MSG":
            return False, 0
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        except (TypeError, ValueError):
            return False, 0

        if msg.message != WM_APP or int(msg.hwnd or 0) != self._hwnd:
            return False, 0

        handler = self._handlers.get(int(msg.wParam))
        if handler is not None:
            handler()
        # Swallow it: nothing else has any business seeing this message.
        return True, 0


def find_existing_host() -> int:
    """HWND of an already-running PCC, or 0.

    Used only for diagnostics; the real single-instance guard is a named mutex,
    which is race-free where a window search is not.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    return int(user32.FindWindowW(None, HOST_TITLE) or 0)
