"""A single template tile."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QTextLayout, QTextOption
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ..model import Template


class ClampedLabel(QLabel):
    """Label that wraps to at most ``lines`` and elides the overflow.

    ``QLabel`` can wrap or it can elide, never both -- word wrap simply clips
    whatever does not fit, which is what produced half-height rows of text in
    the first build. Laying the text out manually with ``QTextLayout`` gives
    real line breaks plus a trailing ellipsis, and fixes the height to an exact
    multiple of the line spacing so every tile lines up.
    """

    def __init__(self, lines: int) -> None:
        super().__init__()
        self._lines = lines
        self._full_text = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def sizeHint(self) -> QSize:
        return QSize(0, self._fixed_height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self._fixed_height())

    def _fixed_height(self) -> int:
        return int(QFontMetrics(self.font()).lineSpacing() * self._lines)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setFixedHeight(self._fixed_height())
        self._relayout()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._relayout()

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            # Qt applies stylesheet fonts *after* construction, and again on
            # every live restyle. Height is a multiple of the line spacing, so
            # it has to be recomputed here or a bigger font clips instead of
            # growing the tile.
            self.setFixedHeight(self._fixed_height())
            self._relayout()

    def _relayout(self) -> None:
        width = max(1, self.width())
        metrics = QFontMetrics(self.font())

        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

        layout = QTextLayout(self._full_text, self.font())
        layout.setTextOption(option)
        layout.beginLayout()

        parts: list[str] = []
        consumed = 0
        for index in range(self._lines):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            start, length = line.textStart(), line.textLength()
            chunk = self._full_text[start : start + length]
            consumed = start + length
            if index == self._lines - 1 and consumed < len(self._full_text):
                # Last visible line and there is more: elide this line instead.
                chunk = metrics.elidedText(
                    self._full_text[start:], Qt.TextElideMode.ElideRight, width
                )
            parts.append(chunk.rstrip("\n"))
        layout.endLayout()

        super().setText("\n".join(parts))


class Tile(QFrame):
    """One template in the grid.

    Tiles are pooled by :class:`~pcc.ui.grid.TileGrid` and re-bound rather than
    recreated, so this class must be cheap to update and must never assume it
    shows the same template twice in a row.
    """

    #: Every tile is the same height so rows align regardless of title length.
    TITLE_LINES = 2
    BODY_LINES = 3

    activated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Tile")
        self.setProperty("selected", False)
        self.setProperty("marked", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template: Template | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 9)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.title = ClampedLabel(self.TITLE_LINES)
        self.title.setObjectName("TileTitle")
        header.addWidget(self.title, 1)

        self.meta = QLabel()
        self.meta.setObjectName("TileMeta")
        self.meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.meta, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self.body = ClampedLabel(self.BODY_LINES)
        self.body.setObjectName("TileBody")
        layout.addWidget(self.body)

        self.tab_hint = QLabel()
        self.tab_hint.setObjectName("TileTab")
        layout.addWidget(self.tab_hint)
        layout.addStretch(1)

    def bind(self, template: Template, tab_hint: str = "", marked: bool = False) -> None:
        self.template = template
        self.title.set_full_text(template.title)
        self.body.set_full_text(template.preview())

        # A modifier advertises itself so its tile reads as "a fragment to layer
        # on", not a prompt to run alone. Slot count still shows when present.
        parts = []
        if template.is_modifier:
            parts.append("MOD")
        slot_count = len(template.slots)
        if slot_count:
            parts.append(f"{slot_count}⬚")
        self.meta.setText("  ".join(parts))

        self._set_property("marked", marked)

        # The owning tab is only worth showing when results span tabs.
        self.tab_hint.setText(tab_hint.upper())
        self.tab_hint.setVisible(bool(tab_hint))

    def _set_property(self, name: str, value: bool) -> None:
        if self.property(name) == value:
            return
        self.setProperty(name, value)
        # Dynamic properties do not restyle on their own; only a couple of tiles
        # change per keystroke so this stays cheap.
        self.style().unpolish(self)
        self.style().polish(self)

    def set_selected(self, selected: bool) -> None:
        self._set_property("selected", selected)

    def set_marked(self, marked: bool) -> None:
        self._set_property("marked", marked)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
        super().mousePressEvent(event)
