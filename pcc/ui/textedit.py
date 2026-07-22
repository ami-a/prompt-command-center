"""A text input that looks like a line edit until it needs not to.

``QPlainTextEdit`` rather than ``QLineEdit`` everywhere text is authored, for
two reasons. Slots such as ``{{code}}`` routinely receive multi-line text and a
line edit silently flattens newlines out of a paste; and a line edit has no
``QTextDocument``, so it cannot carry a ``QSyntaxHighlighter`` and therefore
cannot show spelling marks. Fixing the height to the content is what keeps it
*reading* as a single-line field in the meantime.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit


class GrowingTextEdit(QPlainTextEdit):
    """One line tall by default, growing with its content up to a ceiling."""

    def __init__(self, max_visible_lines: int = 6, wrap: bool = True) -> None:
        super().__init__()
        self.max_visible_lines = max_visible_lines
        self.setObjectName("Field")
        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if wrap
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Tab must move between fields, not insert a tab character.
        self.setTabChangesFocus(True)
        self.document().documentLayout().documentSizeChanged.connect(self._resize_to_fit)
        self._resize_to_fit()

    def _resize_to_fit(self) -> None:
        metrics = self.fontMetrics()
        lines = max(1, min(int(self.document().size().height()), self.max_visible_lines))
        chrome = self.contentsMargins().top() + self.contentsMargins().bottom() + 18
        self.setFixedHeight(int(lines * metrics.lineSpacing() + chrome))
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if self.document().size().height() > self.max_visible_lines
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
