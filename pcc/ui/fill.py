"""Fill panel: one field per placeholder, with a live preview of the paste.

A slot is either free text (``{{code}}``) or a choice (``{{tone|blunt|warm}}``).
A choice is offered as a strip of chips plus a *custom* chip, because the point
of the options is to save typing without ever forbidding an answer the template
author did not think of. Left/Right moves between chips and selects as it goes,
which is the same "arrows change the value" idiom the settings panel uses --
there is no separate confirm step to forget.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..model import Slot, Template, render
from . import spellcheck
from .flow import FlowLayout
from .textedit import GrowingTextEdit


class SlotEdit(GrowingTextEdit):
    """The text input for one slot."""

    MAX_VISIBLE_LINES = 6

    def __init__(self, slot: Slot) -> None:
        super().__init__(max_visible_lines=self.MAX_VISIBLE_LINES)
        self.slot = slot
        self.setPlaceholderText(slot.placeholder_hint)
        # Slot values are the prose that actually gets pasted, so this is where
        # a typo costs the most.
        spellcheck.attach(self)


class OptionChip(QLabel):
    """One selectable option.

    A QLabel, not a QPushButton: buttons come with focus, click and default
    behaviour that would fight the row's own keyboard model, and a label already
    honours the full box model from the stylesheet.
    """

    clicked = Signal()

    def __init__(self, text: str, custom: bool = False) -> None:
        super().__init__(text)
        self.setObjectName("Chip")
        self.setProperty("chosen", False)
        # `active` is the row's focus, mirrored onto the chip: QSS cannot style a
        # child on an ancestor's pseudo-state, and the filled-in look is what
        # says "Left/Right changes *this* row".
        self.setProperty("active", False)
        self.setProperty("custom", custom)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setTextFormat(Qt.TextFormat.PlainText)

    def set_state(self, chosen: bool, active: bool) -> None:
        if (self.property("chosen"), self.property("active")) == (chosen, active):
            return
        self.setProperty("chosen", chosen)
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class OptionRow(QWidget):
    """The chips for one choice slot, plus the trailing *custom* chip.

    Selection index runs over the options; :attr:`CUSTOM` is the last chip and
    means "use the text field instead".
    """

    #: Sentinel index for the custom chip.
    CUSTOM = -1

    changed = Signal()

    def __init__(self, slot: Slot) -> None:
        super().__init__()
        self.setObjectName("OptionRow")
        self.slot = slot
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Fixed vertically: the row's height is whatever its own size hint says,
        # and that hint is computed from the width it currently has.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._flow = FlowLayout(self, spacing=5)
        self._chips: list[OptionChip] = []
        for index, option in enumerate(slot.options):
            chip = OptionChip(option)
            chip.clicked.connect(lambda i=index: self.select(i))
            self._flow.addWidget(chip)
            self._chips.append(chip)

        # Plain words, no glyph: the dashed outline already sets this chip apart,
        # and the label has to survive whatever font the user picked.
        self._custom_chip = OptionChip("custom…", custom=True)
        self._custom_chip.clicked.connect(lambda: self.select(self.CUSTOM))
        self._flow.addWidget(self._custom_chip)

        # A slot written without a preselection ({{tone||warm|blunt}}) opens on
        # the custom chip, so nothing is chosen on the user's behalf.
        self._index = (
            slot.options.index(slot.default) if slot.default in slot.options else self.CUSTOM
        )
        self._refresh()

    # --- state --------------------------------------------------------------

    @property
    def is_custom(self) -> bool:
        return self._index == self.CUSTOM

    def value(self) -> str | None:
        """The chosen option, or ``None`` when the custom field is in charge."""
        return None if self.is_custom else self.slot.options[self._index]

    def select(self, index: int) -> None:
        count = len(self._chips)
        # Wrap through the custom chip, so Right off the end lands somewhere
        # useful rather than stopping dead.
        if index >= count or index < self.CUSTOM:
            index = self.CUSTOM
        self._index = index
        self._refresh()
        self.changed.emit()

    def step(self, delta: int) -> None:
        order = list(range(len(self._chips))) + [self.CUSTOM]
        position = order.index(self._index)
        self.select(order[(position + delta) % len(order)])

    def _refresh(self) -> None:
        active = self.hasFocus()
        for index, chip in enumerate(self._chips):
            chip.set_state(index == self._index, active)
        self._custom_chip.set_state(self.is_custom, active)

    # --- geometry -----------------------------------------------------------

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        """Tall enough for however many lines the chips wrap into *here*."""
        return QSize(0, self._flow.heightForWidth(max(1, self.width())))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt naming)
        return self.sizeHint()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        # A narrower row may need another line, and the hint above is only
        # re-read if something invalidates it.
        if event.oldSize().width() != event.size().width():
            self.updateGeometry()

    # --- focus --------------------------------------------------------------

    def focusInEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().focusInEvent(event)
        self._refresh()

    def focusOutEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().focusOutEvent(event)
        self._refresh()


class SlotField(QWidget):
    """Label, optional chip row, and the text input for a single slot."""

    changed = Signal()

    def __init__(self, slot: Slot) -> None:
        super().__init__()
        self.slot = slot

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        label = QLabel(slot.name.upper())
        label.setObjectName("FieldLabel")
        layout.addWidget(label)

        self.options: OptionRow | None = None
        if slot.has_options:
            self.options = OptionRow(slot)
            self.options.changed.connect(self._on_option_changed)
            layout.addWidget(self.options)

        self.edit = SlotEdit(slot)
        self.edit.textChanged.connect(self.changed)
        layout.addWidget(self.edit)

        if self.options is not None:
            # The field only earns its space when the answer is not on a chip;
            # keeping it hidden also keeps it out of the Tab chain.
            self.edit.setVisible(self.options.is_custom)

    def _on_option_changed(self) -> None:
        assert self.options is not None
        self.edit.setVisible(self.options.is_custom)
        # Only a mouse click on the custom chip moves the caret for you. Doing
        # it for the keyboard too would end the arrow walk the moment it reached
        # the last chip, with no way back to the options short of Shift+Tab.
        if self.options.is_custom and self.focusWidget() is not self.options:
            self.edit.setFocus()
        self.changed.emit()

    # --- value --------------------------------------------------------------

    def value(self) -> str:
        if self.options is not None and not self.options.is_custom:
            return self.options.value() or ""
        return self.edit.toPlainText()

    def focus_entry(self) -> None:
        """Focus whichever widget the user should land on first."""
        if self.options is not None:
            self.options.setFocus()
        else:
            self.edit.setFocus()
            self.edit.selectAll()

    def type_into_custom(self, text: str) -> None:
        """Switch to custom input and start it with ``text``."""
        if self.options is not None and not self.options.is_custom:
            self.options.select(OptionRow.CUSTOM)
        self.edit.setFocus()
        self.edit.insertPlainText(text)


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
        self._fields: list[SlotField] = []

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
        self._scroll = scroll

        # Named so the stylesheet's transparent-surface rule reaches it: an
        # unnamed host inside a scroll area paints the palette's default base
        # colour, which is a light rectangle in the middle of a dark panel.
        self._fields_host = QWidget()
        self._fields_host.setObjectName("GridHost")
        self._fields_layout = QVBoxLayout(self._fields_host)
        self._fields_layout.setContentsMargins(0, 0, 6, 0)
        self._fields_layout.setSpacing(9)
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

        self._fields.clear()
        while self._fields_layout.count():
            item = self._fields_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        for slot in template.slots:
            field = SlotField(slot)
            field.changed.connect(self._update_preview)
            self._fields_layout.addWidget(field)
            self._fields.append(field)

        self._fields_layout.addStretch(1)
        self._update_preview()

    def focus_first(self) -> None:
        if self._fields:
            self._fields[0].focus_entry()

    def values(self) -> dict[str, str]:
        return {field.slot.name: field.value() for field in self._fields}

    def rendered(self) -> str:
        if self.template is None:
            return ""
        return render(self.template.body, self.values())

    def _update_preview(self) -> None:
        text = " ".join(self.rendered().split())
        self.preview.setText(text[:400] + ("…" if len(text) > 400 else ""))

    # --- keys ---------------------------------------------------------------

    def _focused_row(self) -> tuple[SlotField, int] | None:
        """The chip row holding keyboard focus, and its field's position.

        ``self.focusWidget()`` rather than the application's: it answers for this
        subtree whether or not the window is currently active, which is what the
        palette needs -- it is only asked while the fill page is up -- and what
        lets the key routing be tested headlessly.
        """
        focused = self.focusWidget()
        for index, field in enumerate(self._fields):
            if field.options is not None and field.options is focused:
                return field, index
        return None

    def _focus_neighbour(self, index: int, delta: int) -> None:
        if self._fields:
            neighbour = self._fields[(index + delta) % len(self._fields)]
            neighbour.focus_entry()
            self._scroll.ensureWidgetVisible(neighbour, 0, 12)

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

        # Ctrl+. is the quick-fix binding people already have in their fingers.
        if key == Qt.Key.Key_Period and modifiers & Qt.KeyboardModifier.ControlModifier:
            focused = self.focusWidget()
            return isinstance(focused, SlotEdit) and spellcheck.open_suggestions(focused)

        # Every key below belongs to a chip row. While a text field has focus
        # they all mean what they always mean, so they are left alone.
        located = self._focused_row()
        if located is None:
            return False
        field, index = located
        row = field.options
        assert row is not None

        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            row.step(-1 if key == Qt.Key.Key_Left else 1)
            return True
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            row.select(0 if key == Qt.Key.Key_Home else OptionRow.CUSTOM)
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._focus_neighbour(index, -1 if key == Qt.Key.Key_Up else 1)
            return True

        # Typing on a chip row means "none of these": jump to the custom field
        # and keep the keystroke, rather than dropping it on the floor.
        text = event.text()
        if (
            text
            and text.isprintable()
            and not modifiers & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
            )
        ):
            field.type_into_custom(text)
            return True

        return False
