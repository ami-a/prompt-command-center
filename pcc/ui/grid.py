"""The tile grid: pooled widgets, arrow navigation, reordering."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..model import Tab, Template
from .tile import Tile


class TileGrid(QScrollArea):
    """Scrollable grid of :class:`Tile` widgets.

    Widgets are **pooled**: filtering re-binds existing tiles instead of
    building new ones, so a keystroke costs a few label updates rather than a
    round of widget construction and style resolution.
    """

    activated = Signal(object)          # Template
    selection_changed = Signal(object)  # Template | None

    def __init__(self, columns: int = 3) -> None:
        super().__init__()
        self.columns = max(1, columns)
        self._pool: list[Tile] = []
        self._entries: list[tuple[Tab, Template]] = []
        self._index = 0
        self._show_tab_hints = False

        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        host = QWidget()
        host.setObjectName("GridHost")
        outer = QVBoxLayout(host)
        outer.setContentsMargins(0, 0, 6, 0)
        outer.setSpacing(0)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(9)
        self._apply_column_stretch()
        outer.addLayout(self._grid)

        self._empty = QLabel("no matches")
        self._empty.setObjectName("Empty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setVisible(False)
        outer.addWidget(self._empty)
        outer.addStretch(1)

        self.setWidget(host)

    # --- population ---------------------------------------------------------

    def _tile_at(self, index: int) -> Tile:
        """Fetch pooled tile ``index``, growing the pool only when necessary."""
        while len(self._pool) <= index:
            tile = Tile()
            # Fixed vertical policy + the tile's own clamped labels means every
            # row resolves to the same height, so the grid never looks ragged.
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            position = len(self._pool)
            tile.activated.connect(lambda i=position: self._activate_pool_index(i))
            self._grid.addWidget(tile, position // self.columns, position % self.columns)
            self._pool.append(tile)
        return self._pool[index]

    def _activate_pool_index(self, pool_index: int) -> None:
        if pool_index < len(self._entries):
            self.set_index(pool_index)
            self.activate()

    def populate(
        self,
        entries: list[tuple[Tab, Template]],
        show_tab_hints: bool = False,
        keep_id: str | None = None,
    ) -> None:
        """Show ``entries``, optionally preserving the selection by template id."""
        self._entries = entries
        self._show_tab_hints = show_tab_hints

        for index, (tab, template) in enumerate(entries):
            tile = self._tile_at(index)
            tile.bind(template, tab.name if show_tab_hints else "")
            tile.setVisible(True)

        for index in range(len(entries), len(self._pool)):
            self._pool[index].setVisible(False)

        self._empty.setVisible(not entries)

        new_index = 0
        if keep_id is not None:
            new_index = next(
                (i for i, (_, t) in enumerate(entries) if t.id == keep_id), 0
            )
        self._index = 0 if not entries else min(new_index, len(entries) - 1)
        self._refresh_selection()

    def _apply_column_stretch(self) -> None:
        """Give every column equal stretch, occupied or not.

        A QGridLayout collapses columns that hold no widget, so a search
        matching one template would stretch that single tile across the whole
        window. Equal stretch keeps the column grid fixed, so tiles stay the
        same width no matter how many results there are.
        """
        for column in range(max(self.columns, self._grid.columnCount())):
            self._grid.setColumnStretch(column, 1 if column < self.columns else 0)

    def set_columns(self, columns: int) -> None:
        columns = max(1, columns)
        if columns == self.columns:
            return
        self.columns = columns
        for position, tile in enumerate(self._pool):
            self._grid.addWidget(tile, position // columns, position % columns)
        self._apply_column_stretch()

    # --- selection ----------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def current(self) -> Template | None:
        if 0 <= self._index < len(self._entries):
            return self._entries[self._index][1]
        return None

    @property
    def current_tab(self) -> Tab | None:
        if 0 <= self._index < len(self._entries):
            return self._entries[self._index][0]
        return None

    def _refresh_selection(self) -> None:
        for position, tile in enumerate(self._pool):
            tile.set_selected(position == self._index and position < len(self._entries))
        if 0 <= self._index < len(self._pool) and self._entries:
            self.ensureWidgetVisible(self._pool[self._index], 0, 12)
        self.selection_changed.emit(self.current)

    def set_index(self, index: int) -> None:
        if not self._entries:
            return
        self._index = max(0, min(index, len(self._entries) - 1))
        self._refresh_selection()

    def move(self, key: Qt.Key) -> bool:
        """Arrow-key navigation. Returns whether the key was consumed."""
        if not self._entries:
            return key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right)

        columns = self.columns
        index = self._index
        last = len(self._entries) - 1

        if key == Qt.Key.Key_Left:
            # Wrap backwards through the whole grid rather than stopping at the
            # row edge -- it makes a 3-wide grid navigable with one key.
            index = index - 1 if index > 0 else last
        elif key == Qt.Key.Key_Right:
            index = index + 1 if index < last else 0
        elif key == Qt.Key.Key_Up:
            index = index - columns if index - columns >= 0 else index
        elif key == Qt.Key.Key_Down:
            if index + columns <= last:
                index += columns
            elif index != last and (last // columns) > (index // columns):
                index = last
        elif key == Qt.Key.Key_Home:
            index = 0
        elif key == Qt.Key.Key_End:
            index = last
        elif key == Qt.Key.Key_PageUp:
            index = max(0, index - columns * 2)
        elif key == Qt.Key.Key_PageDown:
            index = min(last, index + columns * 2)
        else:
            return False

        self.set_index(index)
        return True

    def activate(self) -> None:
        template = self.current
        if template is not None:
            self.activated.emit(template)
