"""Entry point: single-instance guard, tray, IPC wiring, event loop."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import store, winapi
from .ipc import CMD_QUIT, CMD_SHOW, CMD_TOGGLE, HostWindow, TriggerFilter, find_existing_host
from .ui.palette import PaletteWindow, load_stylesheet

MUTEX_NAME = "Global\\PCC_PromptCommandCenter_SingleInstance"
ACCENT = QColor("#22D3EE")
BACKDROP = QColor("#0B0F14")


class ReloadBridge(QObject):
    """Marshals watchdog's worker-thread callback onto the Qt main thread.

    Touching widgets from the watcher thread would be a crash waiting to happen;
    a queued signal is the cheap, correct fix.
    """

    triggered = Signal()


def _acquire_single_instance() -> bool:
    """Claim the named mutex. ``False`` means another PCC already owns it.

    A named mutex rather than a window search: process creation and window
    creation are not atomic, so two near-simultaneous launches could both find
    no window and both start.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True  # cannot tell; assume we are alone rather than refuse to run
    ERROR_ALREADY_EXISTS = 183
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return False
    # Leaked deliberately: the mutex must outlive this function for the whole
    # process lifetime, and Windows releases it on exit.
    _acquire_single_instance._handle = handle  # type: ignore[attr-defined]
    return True


def build_icon() -> QIcon:
    """Draw the tray glyph rather than shipping a .ico file."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    path = QPainterPath()
    path.addRoundedRect(4, 4, 56, 56, 14, 14)
    painter.fillPath(path, BACKDROP)
    painter.setPen(ACCENT)
    painter.drawPath(path)

    font = QFont("Cascadia Code", 26, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(ACCENT)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "›_")
    painter.end()

    return QIcon(pixmap)


def main() -> int:
    if not _acquire_single_instance():
        # Second launch acts as a trigger for the instance already running --
        # this is what makes the AHK hybrid fallback safe to fire twice.
        existing = find_existing_host()
        if existing:
            ctypes.WinDLL("user32", use_last_error=True).PostMessageW(
                ctypes.c_void_p(existing), 0x8000, CMD_SHOW, 0
            )
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("PCC")
    app.setQuitOnLastWindowClosed(False)  # the palette hiding must not end the app

    winapi.relax_foreground_lock()

    settings = store.load_settings()
    app.setStyleSheet(load_stylesheet(settings))
    library = store.load_library(store.library_path(settings))
    palette = PaletteWindow(library, settings)
    palette.quit_requested.connect(app.quit)
    palette.prewarm()

    host = HostWindow()
    trigger_filter = TriggerFilter(
        host.hwnd,
        {
            CMD_SHOW: palette.trigger,
            CMD_TOGGLE: palette.toggle,
            CMD_QUIT: app.quit,
        },
    )
    app.installNativeEventFilter(trigger_filter)
    # Only now is the host discoverable by AHK; see HostWindow.arm().
    host.arm()

    bridge = ReloadBridge()
    bridge.triggered.connect(palette.reload_library)
    watcher = store.LibraryWatcher(store.library_path(settings), bridge.triggered.emit)
    watcher.start()

    # Every internal save must silence the watcher, or we reload our own writes.
    palette.before_save = watcher.mark_self_write

    icon = build_icon()
    app.setWindowIcon(icon)
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("PCC — CapsLock+Space")

    menu = QMenu()
    show_action = QAction("Show palette", menu)
    show_action.triggered.connect(palette.trigger)
    edit_action = QAction("Edit templates.json", menu)
    edit_action.triggered.connect(palette.open_library_file)
    prefs_action = QAction("Settings…\tCtrl+,", menu)
    prefs_action.triggered.connect(lambda: (palette.trigger(), palette.open_settings()))
    settings_action = QAction("Edit settings.json", menu)
    settings_action.triggered.connect(palette.open_settings_file)
    reload_action = QAction("Reload templates", menu)
    reload_action.triggered.connect(palette.reload_library)
    restyle_action = QAction("Reload settings", menu)
    restyle_action.triggered.connect(palette.reload_settings)
    quit_action = QAction("Quit PCC\tCtrl+Q", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(show_action)
    menu.addAction(prefs_action)
    menu.addSeparator()
    menu.addAction(edit_action)
    menu.addAction(settings_action)
    menu.addAction(reload_action)
    menu.addAction(restyle_action)
    menu.addSeparator()
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: palette.toggle()
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    app.aboutToQuit.connect(watcher.stop)

    if "--show" in sys.argv:
        palette.trigger()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
