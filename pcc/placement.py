"""Where to put the palette.

This machine runs a 175 % scaled primary (3440x1440 physical reported as
1966x823 logical) plus a second monitor at a vertical offset, so every
computation here stays in Qt's *logical* coordinate space and is driven by
``QScreen.availableGeometry()``. Raw pixel arithmetic would land the window off
-screen or under the taskbar.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication, QScreen

user32 = ctypes.WinDLL("user32", use_last_error=True)


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def window_center(hwnd: int) -> QPoint | None:
    """Centre of ``hwnd`` in physical screen pixels, or ``None``."""
    if not hwnd:
        return None
    rect = _RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None
    return QPoint((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)


def physical_geometry(screen: QScreen) -> QRect:
    """``screen``'s rect in the same physical pixels ``GetWindowRect`` reports.

    Qt on Windows is inconsistent here and it is worth being explicit: screen
    *origins* already come back in physical desktop coordinates, while screen
    *sizes* are device-independent. Measured on this machine at 175 %::

        SE790C        geo=(0, 0, 1966, 823)      dpr=1.75 -> (0, 0, 3440, 1440)
        TL156VDXP0101 geo=(3440, 358, 1097, 617) dpr=1.75 -> (3440, 358, 1919, 1079)

    Note the second origin is 3440, i.e. already physical -- scaling it too
    would put the screen at x=6020 and every hit test would miss.
    """
    geo = screen.geometry()
    ratio = screen.devicePixelRatio()
    return QRect(
        geo.x(),
        geo.y(),
        int(round(geo.width() * ratio)),
        int(round(geo.height() * ratio)),
    )


def screen_for_window(hwnd: int) -> QScreen:
    """The screen showing ``hwnd``, falling back to nearest, then primary."""
    center = window_center(hwnd)
    screens = QGuiApplication.screens()
    if center is not None and screens:
        for screen in screens:
            if physical_geometry(screen).contains(center):
                return screen
        # Off-screen or straddling: pick the nearest by centre distance rather
        # than silently defaulting to primary.
        def distance(screen: QScreen) -> int:
            c = physical_geometry(screen).center()
            return (c.x() - center.x()) ** 2 + (c.y() - center.y()) ** 2

        return min(screens, key=distance)

    return QGuiApplication.primaryScreen()


def top_left_position(screen: QScreen, size, margin: int = 40) -> QPoint:
    """Top-left anchor inside ``screen``'s work area, clamped to stay on-screen."""
    area = screen.availableGeometry()
    x = area.x() + margin
    y = area.y() + margin

    # Clamp so an oversized palette on a small monitor still fits.
    max_x = area.right() - size.width() + 1
    max_y = area.bottom() - size.height() + 1
    x = max(area.x(), min(x, max_x))
    y = max(area.y(), min(y, max_y))
    return QPoint(x, y)


def fit_size(screen: QScreen, width: int, height: int, margin: int = 40):
    """Shrink the requested size to what the target monitor can actually show."""
    area = screen.availableGeometry()
    return (
        min(width, area.width() - 2 * margin),
        min(height, area.height() - 2 * margin),
    )
