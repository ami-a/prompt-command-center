"""In-app settings.

Two decisions shape this panel:

* **Left/Right edits, Up/Down moves.** Every setting is a value on a row, so one
  pair of keys changes anything without tabbing between heterogeneous widgets.
  It matches how the tile grid already behaves.
* **Changes apply live.** Colour and font settings are judged by eye, so the
  palette restyles on every keypress and the panel you are editing *is* the
  preview. Escape restores the snapshot taken on entry, so experimenting is
  free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import schemes

#: Offered when the font database is unavailable (e.g. the offscreen platform
#: used by the tests, which reports no families at all).
FALLBACK_FONTS = ("Cascadia Code", "Cascadia Mono", "Consolas", "Courier New")
PROPORTIONAL_FONTS = ("Segoe UI", "Segoe UI Variable", "Inter", "Arial", "Georgia")


def available_mono_fonts() -> list[str]:
    """Installed fixed-pitch families, best-first.

    Bitmap and CJK-only faces are filtered out: they are technically fixed
    pitch but nobody wants them in a prompt palette, and a long list makes the
    row tedious to cycle through.
    """
    skip = ("8514oem", "Fixedsys", "Terminal", "Courier", "OCR", "SimSun",
            "NSimSun", "MS Gothic", "Guttman", "Miriam", "Rod")
    try:
        families = [
            name for name in QFontDatabase.families()
            if QFontDatabase.isFixedPitch(name)
            and not any(name.startswith(prefix) for prefix in skip)
        ]
    except Exception:
        families = []
    return families or list(FALLBACK_FONTS)


@dataclass
class Setting:
    """One editable row.

    ``values`` holds the choices for a cycling row; ``bounds`` the (min, max,
    step) for a numeric one. ``fmt`` renders the stored value for display.
    """

    key: str
    label: str
    hint: str = ""
    values: list[Any] = field(default_factory=list)
    bounds: tuple[int, int, int] | None = None
    fmt: Callable[[Any], str] = str
    swatch: bool = False

    def adjust(self, current: Any, delta: int) -> Any:
        if self.bounds is not None:
            low, high, step = self.bounds
            try:
                value = int(current)
            except (TypeError, ValueError):
                # Garbage from a hand-edited file: snap to a known-good value
                # rather than stepping away from it in whichever direction the
                # user happened to press.
                return low
            return max(low, min(high, value + delta * step))
        if not self.values:
            return current
        try:
            index = self.values.index(current)
        except ValueError:
            index = 0
        return self.values[(index + delta) % len(self.values)]


def build_settings() -> list[Setting]:
    """The rows, in display order."""
    mono = available_mono_fonts()
    return [
        Setting("scheme", "Colour scheme", "the whole palette",
                values=schemes.keys(),
                fmt=lambda v: schemes.get(v).name, swatch=True),
        Setting("font_family", "Font", "UI and tile titles",
                values=mono, fmt=lambda v: str(v).split(",")[0]),
        Setting("font_size", "Font size", "everything scales from this",
                bounds=(8, 28, 1), fmt=lambda v: f"{v} px"),
        Setting("mono_preview", "Body text", "prompt previews",
                values=[True, False],
                fmt=lambda v: "monospace" if v else "proportional"),
        Setting("preview_font_family", "Body font", "when proportional",
                values=list(PROPORTIONAL_FONTS),
                fmt=lambda v: str(v).split(",")[0]),
        Setting("columns", "Columns", "tiles per row", bounds=(1, 6, 1)),
        Setting("window_width", "Width", bounds=(420, 1600, 20),
                fmt=lambda v: f"{v} px"),
        Setting("window_height", "Height", bounds=(280, 1200, 20),
                fmt=lambda v: f"{v} px"),
        Setting("margin", "Screen margin", "inset from the corner",
                bounds=(0, 200, 5), fmt=lambda v: f"{v} px"),
        Setting("restore_clipboard", "Restore clipboard", "after pasting",
                values=[True, False], fmt=lambda v: "yes" if v else "no"),
        Setting("paste_key", "Paste with", "shift+insert for terminals",
                values=["ctrl+v", "shift+insert"],
                fmt=lambda v: str(v).replace("+", " + ")),
        # The language it checks in is deliberately not a row: Windows reports
        # twenty-odd locale tags, and cycling those with Left/Right would be
        # miserable. It stays a hand-editable key in settings.json.
        Setting("spellcheck", "Spell check", "marks typos as you write",
                values=[True, False], fmt=lambda v: "on" if v else "off"),
    ]


class SettingRow(QFrame):
    """Label, hint, and current value; pooled like tiles.

    QFrame rather than QWidget on purpose: a plain QWidget ignores
    ``background-color`` and ``border`` from a stylesheet unless it also sets
    WA_StyledBackground, so the rows and the selection highlight would render
    completely invisible.
    """

    SWATCH = 13

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SettingRow")
        self.setProperty("selected", False)
        self.setting: Setting | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(1)
        self.label = QLabel()
        self.label.setObjectName("SettingLabel")
        left.addWidget(self.label)
        self.hint = QLabel()
        self.hint.setObjectName("SettingHint")
        left.addWidget(self.hint)
        layout.addLayout(left, 1)

        self.swatches = QLabel()
        self.swatches.setObjectName("SettingSwatch")
        self.swatches.setVisible(False)
        layout.addWidget(self.swatches, 0, Qt.AlignmentFlag.AlignVCenter)

        self.value = QLabel()
        self.value.setObjectName("SettingValue")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.value, 0)

    def bind(self, setting: Setting, value: Any) -> None:
        self.setting = setting
        self.label.setText(setting.label)
        self.hint.setText(setting.hint)
        self.hint.setVisible(bool(setting.hint))
        self.value.setText(f"‹ {setting.fmt(value)} ›")

        if setting.swatch:
            self.swatches.setPixmap(self._swatch_strip(str(value)))
            self.swatches.setVisible(True)
        else:
            self.swatches.setVisible(False)

    def _swatch_strip(self, scheme_key: str) -> QPixmap:
        """Three dots showing the scheme's actual accent, secondary and surface.

        Reading a colour scheme's name tells you nothing; this makes cycling
        through them a visual choice rather than a guess.
        """
        tokens = schemes.get(scheme_key).tokens()
        # Accent, secondary, and the scheme's own background -- the third dot is
        # what distinguishes, say, Matrix from Void at a glance.
        colours = [tokens["ACCENT"], tokens["SECONDARY"], tokens["BG"]]
        size, gap = self.SWATCH, 4
        pixmap = QPixmap(len(colours) * size + (len(colours) - 1) * gap, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Outline every dot, otherwise the dark background swatch is invisible
        # against the row it sits on.
        painter.setPen(QColor(tokens["BORDER_HOVER"]))
        for index, colour in enumerate(colours):
            painter.setBrush(QColor(colour))
            painter.drawEllipse(index * (size + gap), 0, size - 1, size - 1)
        painter.end()
        return pixmap

    def set_selected(self, selected: bool) -> None:
        if self.property("selected") == selected:
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)


class SettingsPanel(QWidget):
    """Live-editing settings page.

    Emits :attr:`changed` on every edit so the caller can restyle immediately,
    :attr:`saved` to persist, and :attr:`cancelled` to roll back.
    """

    changed = Signal(str, object)   # key, value
    saved = Signal()
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._settings: dict[str, Any] = {}
        self._rows: list[SettingRow] = []
        self._definitions: list[Setting] = []
        self._index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.title = QLabel("SETTINGS")
        self.title.setObjectName("PanelTitle")
        layout.addWidget(self.title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll = scroll

        host = QWidget()
        host.setObjectName("GridHost")
        self._list = QVBoxLayout(host)
        self._list.setContentsMargins(0, 0, 6, 0)
        self._list.setSpacing(4)
        self._list.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

    # --- lifecycle ----------------------------------------------------------

    def load(self, settings: dict[str, Any]) -> None:
        """Show ``settings``. The caller keeps ownership of the snapshot."""
        self._settings = settings
        self._definitions = build_settings()

        while len(self._rows) < len(self._definitions):
            row = SettingRow()
            self._list.insertWidget(self._list.count() - 1, row)
            self._rows.append(row)

        for index, definition in enumerate(self._definitions):
            row = self._rows[index]
            row.bind(definition, settings.get(definition.key))
            row.setVisible(True)
        for index in range(len(self._definitions), len(self._rows)):
            self._rows[index].setVisible(False)

        self._index = min(self._index, len(self._definitions) - 1)
        self._refresh_selection()

    def _refresh_selection(self) -> None:
        for index, row in enumerate(self._rows):
            row.set_selected(index == self._index and index < len(self._definitions))
        if 0 <= self._index < len(self._definitions):
            self._scroll.ensureWidgetVisible(self._rows[self._index], 0, 10)

    def _rebind_current(self) -> None:
        definition = self._definitions[self._index]
        self._rows[self._index].bind(definition, self._settings.get(definition.key))

    def _move(self, delta: int) -> None:
        if not self._definitions:
            return
        self._index = (self._index + delta) % len(self._definitions)
        self._refresh_selection()

    def _adjust(self, delta: int) -> None:
        if not self._definitions:
            return
        definition = self._definitions[self._index]
        value = definition.adjust(self._settings.get(definition.key), delta)
        if value == self._settings.get(definition.key):
            return
        self._settings[definition.key] = value
        self._rebind_current()
        self.changed.emit(definition.key, value)

    # --- keys ---------------------------------------------------------------

    def handle_key(self, event) -> bool:
        key = event.key()

        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._move(-1 if key == Qt.Key.Key_Up else 1)
            return True
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._adjust(-1 if key == Qt.Key.Key_Left else 1)
            return True
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            # Coarse adjustment for the numeric rows.
            self._adjust(-5 if key == Qt.Key.Key_PageUp else 5)
            return True
        if key == Qt.Key.Key_Home:
            self._index = 0
            self._refresh_selection()
            return True
        if key == Qt.Key.Key_End:
            self._index = len(self._definitions) - 1
            self._refresh_selection()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.saved.emit()
            return True
        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return True
        return False
