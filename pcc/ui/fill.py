"""Fill panel: one input per placeholder, with a live preview of the paste."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..model import Slot, Template, render


class SlotEdit(QPlainTextEdit):
    """One-line-by-default input that grows with its content.

    ``QPlainTextEdit`` rather than ``QLineEdit`` because slots such as
    ``{{code}}`` routinely receive multi-line text, and a line edit silently
    flattens newlines out of a paste.
    """

    MAX_VISIBLE_LINES = 6

    def __init__(self, slot: Slot) -> None:
        super().__init__()
        self.slot = slot
        self.setObjectName("Field")
        self.setPlaceholderText(slot.placeholder_hint)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Tab must move between slots, not insert a tab character.
        self.setTabChangesFocus(True)
        self.document().documentLayout().documentSizeChanged.connect(self._resize_to_fit)
        self._resize_to_fit()

    def _resize_to_fit(self) -> None:
        metrics = self.fontMetrics()
        lines = max(1, min(int(self.document().size().height()), self.MAX_VISIBLE_LINES))
        chrome = self.contentsMargins().top() + self.contentsMargins().bottom() + 18
        self.setFixedHeight(int(lines * metrics.lineSpacing() + chrome))
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if self.document().size().height() > self.MAX_VISIBLE_LINES
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )


class FillPanel(QWidget):
    """Collects slot values for one template.

    Emits :attr:`submitted` with the fully rendered text; unfilled slots resolve
    to their default, or to the literal ``{{token}}`` when they have none.
    """

    submitted = Signal(str)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.template: Template | None = None
        self._edits: list[SlotEdit] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.title = QLabel()
        self.title.setObjectName("PanelTitle")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._fields_host = QWidget()
        self._fields = QVBoxLayout(self._fields_host)
        self._fields.setContentsMargins(0, 0, 6, 0)
        self._fields.setSpacing(7)
        scroll.setWidget(self._fields_host)
        layout.addWidget(scroll, 1)

        preview_label = QLabel("PREVIEW")
        preview_label.setObjectName("PreviewLabel")
        layout.addWidget(preview_label)

        self.preview = QLabel()
        self.preview.setObjectName("Preview")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.preview.setMaximumHeight(96)
        layout.addWidget(self.preview)

    # --- lifecycle ----------------------------------------------------------

    def load(self, template: Template) -> None:
        self.template = template
        self.title.setText(template.title)

        for edit in self._edits:
            edit.setParent(None)
            edit.deleteLater()
        self._edits.clear()
        while self._fields.count():
            item = self._fields.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        for slot in template.slots:
            label = QLabel(slot.name.upper())
            label.setObjectName("FieldLabel")
            self._fields.addWidget(label)

            edit = SlotEdit(slot)
            edit.textChanged.connect(self._update_preview)
            self._fields.addWidget(edit)
            self._edits.append(edit)

        self._fields.addStretch(1)
        self._update_preview()

    def focus_first(self) -> None:
        if self._edits:
            self._edits[0].setFocus()
            self._edits[0].selectAll()

    def values(self) -> dict[str, str]:
        return {edit.slot.name: edit.toPlainText() for edit in self._edits}

    def rendered(self) -> str:
        if self.template is None:
            return ""
        return render(self.template.body, self.values())

    def _update_preview(self) -> None:
        text = " ".join(self.rendered().split())
        self.preview.setText(text[:400] + ("…" if len(text) > 400 else ""))

    # --- keys ---------------------------------------------------------------

    def handle_key(self, event) -> bool:
        """Panel-specific keys. Returns whether the event was consumed."""
        key = event.key()
        modifiers = event.modifiers()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Shift+Enter inserts a newline; bare Enter submits. This is the
            # chat-box idiom, which is exactly where these prompts are headed.
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                return False
            self.submitted.emit(self.rendered())
            return True

        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return True

        return False
