"""A left-to-right layout that wraps.

Qt ships no wrapping box layout, and a choice slot's chips are exactly the case
that needs one: their number and width come from the template, so any fixed
column count is wrong for some template. Wrapping keeps a long option list
inside the panel instead of pushing the fill panel wider than the window.

:meth:`FlowLayout.heightForWidth` is the interesting part -- the height of a
wrapping row is a function of the width it is given. Note that the *widget*
using this layout should report that height through its size hint rather than
by declaring ``QSizePolicy.setHeightForWidth``: Qt derives a height-for-width
widget's minimum height by asking for its height at its narrowest, which for a
wrapping row means every chip on a line of its own -- a minimum tall enough to
push the whole window past the size the user asked for.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    # --- QLayout plumbing ---------------------------------------------------

    def addItem(self, item) -> None:  # noqa: N802 (Qt naming)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 (Qt naming)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 (Qt naming)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 (Qt naming)
        return Qt.Orientation(0)

    # --- sizing -------------------------------------------------------------

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt naming)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt naming)
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt naming)
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt naming)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, apply: bool) -> int:
        """Place (or just measure) the items; returns the height used."""
        x, y, line_height = rect.x(), rect.y(), 0
        space = self.spacing()

        for item in self._items:
            hint = item.sizeHint()
            # line_height > 0 means something is already on this line, so there
            # is a line to wrap out of; the first item never wraps.
            if line_height and x + hint.width() > rect.right() + 1:
                x = rect.x()
                y += line_height + space
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + space
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y()
