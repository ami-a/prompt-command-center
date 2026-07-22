"""Spike fixture: a stand-in for the app you paste into.

Runs as its own process with a focused text box and mirrors every change to
``spike/received.txt`` so the harness can assert what actually arrived. Using a
window we control -- rather than Notepad -- makes the assertion exact and keeps
the test independent of Windows 11 Notepad internals.
"""

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QMainWindow

OUT = Path(__file__).with_name("received.txt")

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
user32.FindWindowW.restype = wintypes.HWND


def self_trigger() -> None:
    """Post WM_APP at the host while *this* window owns the foreground.

    The driver cannot do this from PowerShell: Windows refuses
    ``SetForegroundWindow`` to a process that is not already foreground, so the
    host would capture the wrong target. Triggering from here reproduces the
    real situation, where AHK posts while the user's app is focused.
    """
    host = user32.FindWindowW(None, "PCC_IPC_HOST")
    fg = user32.GetForegroundWindow()
    print(f"[target] host={host} foreground={fg} self={int(win.winId())}", flush=True)
    if host:
        user32.PostMessageW(wintypes.HWND(host), 0x8000, 0, 0)


class Target(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PCC_SPIKE_TARGET")
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("paste target")
        self.edit.textChanged.connect(self._dump)
        self.setCentralWidget(self.edit)
        self.resize(560, 320)

    def _dump(self) -> None:
        OUT.write_text(self.edit.toPlainText(), encoding="utf-8")


if __name__ == "__main__":
    OUT.write_text("", encoding="utf-8")
    app = QApplication(sys.argv)
    win = Target()
    win.show()
    win.raise_()
    win.activateWindow()
    win.edit.setFocus()
    if "--self-trigger" in sys.argv:
        QTimer.singleShot(2500, self_trigger)
    sys.exit(app.exec())
