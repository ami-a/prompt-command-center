"""Spike harness: proves the three risky mechanisms before any UI is built.

1. AHK/PowerShell ``PostMessage`` reaches a never-shown Qt window.
2. Foreground capture -> show a real window -> restore focus -> paste lands in
   the original app.
3. Window placement is correct on both monitors under 175 % DPI scaling.

Writes a verdict to ``spike/result.txt`` and exits, so it can be asserted on.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout  # noqa: E402

from pcc import placement, winapi  # noqa: E402
from pcc.ipc import CMD_SHOW, HostWindow, TriggerFilter  # noqa: E402

RESULT = Path(__file__).with_name("result.txt")
PAYLOAD = "PCC-SPIKE ✔ shalom שלום 你好"

log: list[str] = []


def note(line: str) -> None:
    log.append(line)
    print(line, flush=True)


class Palette(QWidget):
    """Minimal stand-in for the real palette: frameless, on top, takes focus."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("PCC spike palette\npasting in 500 ms…"))
        self.resize(360, 140)
        self.target_hwnd = 0

    def trigger(self) -> None:
        self.target_hwnd = winapi.get_foreground_window()
        note(f"[1] WM_APP received. foreground hwnd={self.target_hwnd}")

        screen = placement.screen_for_window(self.target_hwnd)
        pos = placement.top_left_position(screen, self.size(), margin=40)
        note(f"[3] screen={screen.name()} dpr={screen.devicePixelRatio()} "
             f"avail={screen.availableGeometry()} -> pos=({pos.x()},{pos.y()})")

        self.move(pos)
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(500, self.paste)

    def paste(self) -> None:
        prior = winapi.clipboard_get_text()
        winapi.clipboard_set_text(PAYLOAD)
        self.hide()
        restored = winapi.restore_focus(self.target_hwnd)
        note(f"[2a] restore_focus -> {restored} "
             f"(now fg={winapi.get_foreground_window()})")
        sent = winapi.send_paste("ctrl+v")
        note(f"[2b] send_paste -> {sent}")
        QTimer.singleShot(400, lambda: self.finish(prior, restored, sent))

    def finish(self, prior, restored: bool, sent: bool) -> None:
        if prior is not None:
            winapi.clipboard_set_text(prior)
            note(f"[2c] clipboard restored to {prior[:40]!r}")
        else:
            note("[2c] prior clipboard was not text -> left as is")

        received = Path(__file__).with_name("received.txt")
        got = received.read_text(encoding="utf-8") if received.exists() else "<missing>"
        ok = got.strip() == PAYLOAD
        note(f"[2d] target received {got!r} -> {'PASS' if ok else 'FAIL'}")
        note(f"VERDICT: {'PASS' if (ok and restored and sent) else 'FAIL'}")
        RESULT.write_text("\n".join(log), encoding="utf-8")
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    winapi.relax_foreground_lock()

    host = HostWindow()
    palette = Palette()
    trigger_filter = TriggerFilter(host.hwnd, {CMD_SHOW: palette.trigger})
    app.installNativeEventFilter(trigger_filter)

    note(f"[0] host hwnd={host.hwnd} title={host.windowTitle()!r} ready")
    for s in app.screens():
        note(f"[0] screen {s.name()} geo={s.geometry()} avail={s.availableGeometry()} "
             f"dpr={s.devicePixelRatio()}")

    # Safety net so a failed trigger cannot leave the process wedged.
    QTimer.singleShot(30000, lambda: (RESULT.write_text(
        "\n".join(log + ["VERDICT: TIMEOUT"]), encoding="utf-8"), app.quit()))
    sys.exit(app.exec())
