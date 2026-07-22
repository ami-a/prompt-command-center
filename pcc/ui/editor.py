"""In-app template editor.

Kept as a panel inside the palette rather than a modal dialog: a dialog would
deactivate the palette window, which is wired to auto-hide on deactivation.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..model import Tab, Template


class EditorPanel(QWidget):
    """Create or edit one template.

    Emits :attr:`saved` with the edited template and the id of the tab it should
    live in, so the caller owns all mutation of the library.
    """

    saved = Signal(object, str)  # Template, tab_id
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.template: Template | None = None
        self._is_new = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        self.heading = QLabel()
        self.heading.setObjectName("PanelTitle")
        layout.addWidget(self.heading)

        layout.addWidget(self._label("TITLE"))
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("Field")
        layout.addWidget(self.title_edit)

        layout.addWidget(self._label("TAB"))
        self.tab_combo = QComboBox()
        self.tab_combo.setObjectName("Field")
        layout.addWidget(self.tab_combo)

        layout.addWidget(self._label("BODY   —   {{name}} or {{name|default}} marks a fill-in slot"))
        self.body_edit = QPlainTextEdit()
        self.body_edit.setObjectName("Field")
        self.body_edit.setTabChangesFocus(True)
        layout.addWidget(self.body_edit, 1)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        # Long field captions must not dictate the window's minimum width.
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def load(self, template: Template | None, tabs: list[Tab], tab_id: str) -> None:
        self._is_new = template is None
        self.template = template or Template(title="", body="")
        self.heading.setText("NEW TEMPLATE" if self._is_new else "EDIT TEMPLATE")

        self.title_edit.setText(self.template.title)
        self.body_edit.setPlainText(self.template.body)

        self.tab_combo.clear()
        for tab in tabs:
            self.tab_combo.addItem(tab.name, tab.id)
        index = self.tab_combo.findData(tab_id)
        self.tab_combo.setCurrentIndex(max(0, index))

    def focus_first(self) -> None:
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _commit(self) -> None:
        title = self.title_edit.text().strip()
        body = self.body_edit.toPlainText()
        if not title and not body.strip():
            self.cancelled.emit()
            return
        assert self.template is not None
        self.template.title = title or "Untitled"
        self.template.body = body
        self.saved.emit(self.template, self.tab_combo.currentData())

    def handle_key(self, event) -> bool:
        key = event.key()
        modifiers = event.modifiers()
        control = modifiers & Qt.KeyboardModifier.ControlModifier

        # Ctrl+S or Ctrl+Enter saves. Bare Enter must stay available for
        # newlines -- prompt bodies are multi-line by nature.
        if (key == Qt.Key.Key_S and control) or (
            key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and control
        ):
            self._commit()
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.title_edit.hasFocus():
            self.body_edit.setFocus()
            return True

        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return True

        return False
