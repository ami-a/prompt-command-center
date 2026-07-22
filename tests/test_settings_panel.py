"""Settings panel: value cycling, live apply, save and revert."""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from pcc import store
from pcc.ui import schemes
from pcc.ui.palette import PAGE_GRID, PAGE_SETTINGS
from pcc.ui.settings_panel import Setting, build_settings
from pcc.ui.theme import build_stylesheet

pytestmark = pytest.mark.usefixtures("qapp")


def key(panel, code):
    return panel.handle_key(
        QKeyEvent(QEvent.Type.KeyPress, code, Qt.KeyboardModifier.NoModifier)
    )


class TestSettingAdjust:
    def test_choice_cycles_forward(self):
        s = Setting("k", "K", values=["a", "b", "c"])
        assert s.adjust("a", 1) == "b"

    def test_choice_wraps_at_the_end(self):
        s = Setting("k", "K", values=["a", "b", "c"])
        assert s.adjust("c", 1) == "a"

    def test_choice_wraps_backwards(self):
        s = Setting("k", "K", values=["a", "b", "c"])
        assert s.adjust("a", -1) == "c"

    def test_unknown_current_value_starts_from_the_first(self):
        # A hand-edited settings.json can hold anything.
        s = Setting("k", "K", values=["a", "b"])
        assert s.adjust("zzz", 1) == "b"

    def test_numeric_respects_step(self):
        s = Setting("k", "K", bounds=(0, 100, 5))
        assert s.adjust(10, 1) == 15

    def test_numeric_clamps_at_both_ends(self):
        s = Setting("k", "K", bounds=(8, 28, 1))
        assert s.adjust(28, 1) == 28
        assert s.adjust(8, -1) == 8

    def test_numeric_recovers_from_a_non_numeric_value(self):
        s = Setting("k", "K", bounds=(8, 28, 1))
        assert s.adjust("banana", 1) == 8

    def test_empty_choice_list_is_a_no_op(self):
        assert Setting("k", "K").adjust("x", 1) == "x"


class TestPanelNavigation:
    def test_every_row_maps_to_a_real_setting(self, settings):
        for definition in build_settings():
            assert definition.key in store.DEFAULT_SETTINGS, definition.key

    def test_down_moves_and_wraps(self, palette):
        palette.open_settings()
        panel = palette.settings_panel
        assert panel._index == 0
        for _ in range(len(panel._definitions)):
            key(panel, Qt.Key.Key_Down)
        assert panel._index == 0, "should wrap back to the top"

    def test_up_from_the_top_wraps_to_the_end(self, palette):
        palette.open_settings()
        panel = palette.settings_panel
        key(panel, Qt.Key.Key_Up)
        assert panel._index == len(panel._definitions) - 1

    def test_home_and_end(self, palette):
        palette.open_settings()
        panel = palette.settings_panel
        key(panel, Qt.Key.Key_End)
        assert panel._index == len(panel._definitions) - 1
        key(panel, Qt.Key.Key_Home)
        assert panel._index == 0

    def test_rows_are_pooled(self, palette):
        palette.open_settings()
        panel = palette.settings_panel
        first = panel._rows[0]
        panel.load(palette.settings)
        assert panel._rows[0] is first


class TestLiveApply:
    def test_right_changes_the_value(self, palette):
        palette.open_settings()
        panel = palette.settings_panel
        before = palette.settings["scheme"]
        key(panel, Qt.Key.Key_Right)
        assert palette.settings["scheme"] != before

    def test_change_is_applied_to_the_stylesheet_immediately(self, qapp, palette):
        palette.open_settings()
        panel = palette.settings_panel
        # QApplication is session-scoped, so an earlier test may have left a
        # different stylesheet on it. Establish the baseline explicitly rather
        # than comparing against whatever happened to be there.
        qapp.setStyleSheet(build_stylesheet(palette.settings))
        before = qapp.styleSheet()

        key(panel, Qt.Key.Key_Right)          # cycles the colour scheme

        assert qapp.styleSheet() != before, "the panel is its own preview"

    def test_page_up_makes_a_coarse_numeric_jump(self, palette):
        palette.open_settings()
        panel = palette.settings_panel
        panel._index = next(
            i for i, d in enumerate(panel._definitions) if d.key == "font_size"
        )
        palette.settings["font_size"] = 13
        key(panel, Qt.Key.Key_PageDown)
        assert palette.settings["font_size"] == 18

    def test_font_size_change_resizes_the_tiles(self, qapp, palette):
        palette.open_settings()
        panel = palette.settings_panel
        panel._index = next(
            i for i, d in enumerate(panel._definitions) if d.key == "font_size"
        )
        before = palette.grid._pool[0].body.height()
        for _ in range(8):
            key(panel, Qt.Key.Key_Right)
        assert palette.grid._pool[0].body.height() > before

    def test_columns_change_reaches_the_grid(self, palette):
        palette.open_settings()
        panel = palette.settings_panel
        panel._index = next(
            i for i, d in enumerate(panel._definitions) if d.key == "columns"
        )
        key(panel, Qt.Key.Key_Right)
        assert palette.grid.columns == palette.settings["columns"]


class TestSaveAndRevert:
    def _open_and_change(self, palette):
        palette.open_settings()
        panel = palette.settings_panel
        original = palette.settings["scheme"]
        key(panel, Qt.Key.Key_Right)
        return panel, original

    def test_enter_persists_to_disk(self, palette, monkeypatch, tmp_path):
        path = tmp_path / "settings.json"
        monkeypatch.setattr(store, "SETTINGS_PATH", path)
        panel, original = self._open_and_change(palette)

        key(panel, Qt.Key.Key_Return)

        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["scheme"] == palette.settings["scheme"] != original

    def test_enter_returns_to_the_grid(self, palette, monkeypatch, tmp_path):
        monkeypatch.setattr(store, "SETTINGS_PATH", tmp_path / "settings.json")
        panel, _ = self._open_and_change(palette)
        key(panel, Qt.Key.Key_Return)
        assert palette.stack.currentIndex() == PAGE_GRID

    def test_escape_reverts_the_whole_session(self, palette):
        """Escape undoes every edit made since the panel opened, not just the
        last one -- experimenting with colours has to be free."""
        palette.open_settings()
        panel = palette.settings_panel
        original = dict(palette.settings)

        key(panel, Qt.Key.Key_Right)                 # scheme
        key(panel, Qt.Key.Key_Down)
        key(panel, Qt.Key.Key_Right)                 # font family
        key(panel, Qt.Key.Key_Escape)

        assert palette.settings == original

    def test_escape_restores_the_stylesheet(self, qapp, palette):
        palette.open_settings()
        panel = palette.settings_panel
        qapp.setStyleSheet(build_stylesheet(palette.settings))
        before = qapp.styleSheet()
        key(panel, Qt.Key.Key_Right)
        key(panel, Qt.Key.Key_Escape)
        assert qapp.styleSheet() == before

    def test_settings_object_identity_is_preserved_on_revert(self, palette):
        """The panel and the palette share one dict; revert must mutate it in
        place rather than rebind, or the panel would edit a detached copy."""
        palette.open_settings()
        shared = palette.settings
        key(palette.settings_panel, Qt.Key.Key_Right)
        key(palette.settings_panel, Qt.Key.Key_Escape)
        assert palette.settings is shared

    def test_escape_returns_to_the_grid(self, palette):
        palette.open_settings()
        key(palette.settings_panel, Qt.Key.Key_Escape)
        assert palette.stack.currentIndex() == PAGE_GRID


class TestPaletteIntegration:
    def test_ctrl_comma_opens_settings(self, palette):
        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier
        )
        assert palette._handle_grid_key(event)
        assert palette.stack.currentIndex() == PAGE_SETTINGS

    def test_search_and_tabs_are_hidden_on_the_settings_page(self, palette):
        palette.open_settings()
        assert not palette.search.isVisible()
        assert not palette.tabs.isVisible()

    def test_every_scheme_can_be_selected_without_error(self, qapp, palette):
        palette.open_settings()
        panel = palette.settings_panel
        seen = set()
        for _ in range(len(schemes.keys())):
            key(panel, Qt.Key.Key_Right)
            seen.add(palette.settings["scheme"])
            assert "$" not in qapp.styleSheet()
        assert seen == set(schemes.keys())
