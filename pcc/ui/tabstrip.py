"""Keyboard-first tab strip."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ..model import Tab


class TabStrip(QWidget):
    """Row of tabs driven by Ctrl+Tab and Alt+1..9.

    Buttons are pooled like tiles, because tabs get added, renamed and reordered
    from the keyboard and rebuilding the row each time would drop styling state.
    """

    changed = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("TabStrip")
        self._buttons: list[QPushButton] = []
        self._tabs: list[Tab] = []
        self._index = 0

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._layout.addStretch(1)

    def set_tabs(self, tabs: list[Tab], index: int = 0) -> None:
        self._tabs = tabs

        while len(self._buttons) < len(tabs):
            button = QPushButton()
            button.setObjectName("Tab")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            position = len(self._buttons)
            button.clicked.connect(lambda _=False, i=position: self.set_index(i))
            # Insert before the trailing stretch so tabs stay left-aligned.
            self._layout.insertWidget(self._layout.count() - 1, button)
            self._buttons.append(button)

        for position, button in enumerate(self._buttons):
            if position < len(tabs):
                label = tabs[position].name
                # Alt+1..9 are only advertised where they actually work.
                button.setText(f"{label}  {position + 1}" if position < 9 else label)
                button.setVisible(True)
            else:
                button.setVisible(False)

        self._index = max(0, min(index, len(tabs) - 1)) if tabs else 0
        self._restyle()

    def _restyle(self) -> None:
        for position, button in enumerate(self._buttons):
            active = position == self._index
            if button.property("active") == active:
                continue
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    @property
    def index(self) -> int:
        return self._index

    @property
    def current(self) -> Tab | None:
        if 0 <= self._index < len(self._tabs):
            return self._tabs[self._index]
        return None

    def set_index(self, index: int, emit: bool = True) -> None:
        if not self._tabs:
            return
        index = max(0, min(index, len(self._tabs) - 1))
        if index == self._index:
            return
        self._index = index
        self._restyle()
        if emit:
            self.changed.emit(index)

    def step(self, delta: int) -> None:
        """Cycle by ``delta``, wrapping -- Ctrl+Tab should never dead-end."""
        if not self._tabs:
            return
        self.set_index((self._index + delta) % len(self._tabs))
