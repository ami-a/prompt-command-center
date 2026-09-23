"""The shortcuts page: one place that lists every key, so the footer needn't.

The palette used to carry a hint bar that spelled out the current page's keys.
That is scaffolding: useful on day one, visual noise once the keys are in your
fingers. So the footer now shows only how to open *this* page, and everything
lives here, grouped by where it applies. Press F1 (or Esc) to return.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

#: (section, [(keys, description), ...]). Kept declarative so the page is just a
#: render of this table -- and so it is the single source of truth to update when
#: a binding changes.
SHORTCUTS: list[tuple[str, list[tuple[str, str]]]] = [
    ("The palette", [
        ("CapsLock+Space", "Show or hide the palette"),
        ("type", "Fuzzy-filter across every tab"),
        ("↑ ↓ ← →", "Move between tiles"),
        ("Enter", "Paste — or open the fill panel if the template has slots"),
        ("Ctrl+Enter", "Paste immediately, skipping the fill panel"),
        ("Alt+Enter", "Paste and press Enter — sends the chat"),
        ("Ctrl+Space", "Mark this tile to compose (stack it, or layer a modifier)"),
        ("Esc", "Clear the search, then hide"),
        ("F1", "Show this list of shortcuts"),
    ]),
    ("Tabs", [
        ("Ctrl+Tab / Ctrl+Shift+Tab", "Next / previous tab"),
        ("Alt+1…9", "Jump to tab N"),
        ("Ctrl+Shift+N", "New tab"),
        ("Shift+F2", "Rename the current tab"),
        ("Ctrl+Shift+Del", "Delete the current tab (Ctrl+Z to undo)"),
        ("Ctrl+Shift+← →", "Move the current tab"),
    ]),
    ("Templates", [
        ("Ctrl+N", "New template"),
        ("F2", "Edit the selected template"),
        ("Ctrl+D", "Duplicate the selected template"),
        ("Ctrl+Del", "Delete the selected template (Ctrl+Z to undo)"),
        ("Ctrl+← → ↑ ↓", "Reorder the selected tile"),
        ("Ctrl+Z", "Undo the last delete"),
        ("Ctrl+H", "Library health — empty, duplicate, broken, never-used"),
    ]),
    ("Fill panel", [
        ("Tab / Shift+Tab", "Next / previous slot"),
        ("← →", "Pick an option on a choice slot"),
        ("type", "Use your own value instead of an option"),
        ("Ctrl+P", "Toggle the full, untruncated preview"),
        ("Shift+Enter", "Newline inside a slot"),
        ("Ctrl+.", "Fix the misspelled word at the caret"),
        ("Enter / Alt+Enter", "Paste / paste and send"),
        ("Esc", "Back to the grid"),
    ]),
    ("Editor", [
        ("Tab", "Next field"),
        ("Ctrl+S / Ctrl+Enter", "Save"),
        ("Ctrl+.", "Fix the misspelled word at the caret"),
        ("Esc", "Cancel"),
    ]),
    ("Settings", [
        ("↑ ↓", "Choose a setting"),
        ("← →", "Change its value"),
        ("PgUp / PgDn", "Change a number by five"),
        ("Enter / Esc", "Save / revert the whole session"),
    ]),
    ("Files & app", [
        ("Ctrl+,", "Settings — colours, fonts, layout, live preview"),
        ("Ctrl+E / Ctrl+R", "Open / reload templates.json"),
        ("Ctrl+Shift+E / Ctrl+Shift+R", "Open / reload settings.json"),
        ("Ctrl+Q", "Quit — the next CapsLock+Space starts PCC again"),
    ]),
]


class ShortcutsPage(QWidget):
    """A scrollable, read-only cheat sheet. Esc or F1 closes it."""

    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        # Accept focus so arrow/page keys land here to scroll; the app-wide
        # filter routes them regardless, but focus keeps the scrollbar live.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("SHORTCUTS")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scroll = scroll

        host = QWidget()
        host.setObjectName("GridHost")
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(12)

        for section, rows in SHORTCUTS:
            header = QLabel(section.upper())
            header.setObjectName("FieldLabel")
            column.addWidget(header)

            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(3)
            # Keys column hugs its content; description takes the rest.
            grid.setColumnStretch(0, 0)
            grid.setColumnStretch(1, 1)
            for row, (keys, description) in enumerate(rows):
                key_label = QLabel(keys)
                key_label.setObjectName("ShortcutKey")
                key_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
                desc_label = QLabel(description)
                desc_label.setObjectName("ShortcutDesc")
                desc_label.setWordWrap(True)
                grid.addWidget(key_label, row, 0)
                grid.addWidget(desc_label, row, 1)
            column.addLayout(grid)

        column.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

    def handle_key(self, event) -> bool:
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_F1):
            self.closed.emit()
            return True
        # Let the arrows and page keys scroll the list.
        bar = self._scroll.verticalScrollBar()
        step = bar.singleStep()
        if key == Qt.Key.Key_Down:
            bar.setValue(bar.value() + step)
            return True
        if key == Qt.Key.Key_Up:
            bar.setValue(bar.value() - step)
            return True
        if key in (Qt.Key.Key_PageDown, Qt.Key.Key_End):
            page_down = key == Qt.Key.Key_PageDown
            bar.setValue(bar.value() + bar.pageStep() if page_down else bar.maximum())
            return True
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_Home):
            bar.setValue(bar.value() - bar.pageStep() if key == Qt.Key.Key_PageUp else 0)
            return True
        return True  # swallow everything else: this page has no other actions
