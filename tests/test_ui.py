"""Widget behaviour: navigation, filtering, fill, and authoring.

Driven through the same key-routing code the real palette uses, so a regression
in ``_handle_grid_key`` shows up here rather than under someone's fingers.
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QWidget

from pcc.model import Tab, Template
from pcc.ui.palette import PAGE_EDITOR

pytestmark = pytest.mark.usefixtures("qapp")


def press(widget, key, modifiers=Qt.KeyboardModifier.NoModifier, text=""):
    """Route a key through the palette exactly as the event filter would."""
    event = QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)
    return widget._handle_grid_key(event)


class TestGridNavigation:
    def _grid(self, library):
        from pcc.ui.grid import TileGrid

        grid = TileGrid(columns=3)
        grid.populate([(library.tabs[0], t) for t in library.tabs[0].templates])
        return grid

    def test_first_item_is_selected_on_populate(self, library):
        assert self._grid(library).current.id == "p1"

    def test_right_advances(self, library):
        grid = self._grid(library)
        grid.move(Qt.Key.Key_Right)
        assert grid.current.id == "p2"

    def test_right_wraps_at_the_end(self, library):
        grid = self._grid(library)
        grid.set_index(4)
        grid.move(Qt.Key.Key_Right)
        assert grid.current.id == "p1"

    def test_left_wraps_at_the_start(self, library):
        grid = self._grid(library)
        grid.move(Qt.Key.Key_Left)
        assert grid.current.id == "p5", "left from the first tile should reach the last"

    def test_down_moves_by_one_row(self, library):
        grid = self._grid(library)
        grid.move(Qt.Key.Key_Down)
        assert grid.current.id == "p4", "index 0 + 3 columns"

    def test_up_from_the_top_row_stays_put(self, library):
        grid = self._grid(library)
        grid.move(Qt.Key.Key_Up)
        assert grid.current.id == "p1"

    def test_down_from_a_short_last_row_clamps_to_the_end(self, library):
        grid = self._grid(library)
        grid.set_index(2)          # row 0, col 2; row 1 only has p4, p5
        grid.move(Qt.Key.Key_Down)
        assert grid.current.id == "p5"

    def test_home_and_end(self, library):
        grid = self._grid(library)
        grid.move(Qt.Key.Key_End)
        assert grid.current.id == "p5"
        grid.move(Qt.Key.Key_Home)
        assert grid.current.id == "p1"

    def test_navigation_on_an_empty_grid_does_not_crash(self, library):
        from pcc.ui.grid import TileGrid

        grid = TileGrid(columns=3)
        grid.populate([])
        grid.move(Qt.Key.Key_Down)
        assert grid.current is None

    def test_tiles_are_pooled_not_recreated(self, library):
        """Re-filtering must reuse widgets; this is the show-latency guarantee."""
        grid = self._grid(library)
        first = grid._pool[0]
        grid.populate([(library.tabs[1], t) for t in library.tabs[1].templates])
        assert grid._pool[0] is first
        assert grid._pool[0].template.id == "p6"

    def test_surplus_tiles_are_hidden_not_left_showing(self, library):
        grid = self._grid(library)                       # 5 entries
        grid.populate([(library.tabs[1], library.tabs[1].templates[0])])  # 1 entry
        assert grid._pool[0].isVisibleTo(grid)
        assert not grid._pool[1].isVisibleTo(grid)

    def test_keep_id_preserves_selection(self, library):
        grid = self._grid(library)
        entries = [(library.tabs[0], t) for t in library.tabs[0].templates]
        grid.populate(entries, keep_id="p4")
        assert grid.current.id == "p4"


class TestTabStrip:
    def _strip(self, library):
        from pcc.ui.tabstrip import TabStrip

        strip = TabStrip()
        strip.set_tabs(library.tabs, 0)
        return strip

    def test_step_forward_wraps(self, library):
        strip = self._strip(library)
        strip.step(1)
        assert strip.index == 1
        strip.step(1)
        assert strip.index == 0, "Ctrl+Tab should never dead-end"

    def test_step_backward_wraps(self, library):
        strip = self._strip(library)
        strip.step(-1)
        assert strip.index == 1

    def test_index_is_clamped(self, library):
        strip = self._strip(library)
        strip.set_index(99)
        assert strip.index == 1

    def test_buttons_are_pooled(self, library):
        strip = self._strip(library)
        first = strip._buttons[0]
        strip.set_tabs(library.tabs + [Tab(name="Extra", id="t3")], 0)
        assert strip._buttons[0] is first
        assert strip._buttons[2].isVisibleTo(strip)


class TestSearchIntegration:
    def test_typing_filters_the_grid(self, palette):
        palette.search.setText("summ")
        assert [t.id for _, t in palette.grid._entries] == ["p6"]

    def test_search_spans_tabs(self, palette):
        """p6 lives in tab 2 while tab 1 is selected."""
        assert palette.tabs.index == 0
        palette.search.setText("translate")
        assert palette.grid.current.id == "p7"

    def test_clearing_search_restores_the_current_tab(self, palette):
        palette.search.setText("summ")
        palette.search.setText("")
        assert [t.id for _, t in palette.grid._entries] == ["p1", "p2", "p3", "p4", "p5"]

    def test_tab_hints_appear_only_while_searching(self, palette):
        assert not palette.grid._show_tab_hints
        palette.search.setText("summ")
        assert palette.grid._show_tab_hints

    def test_switching_tab_changes_the_grid(self, palette):
        palette.tabs.set_index(1)
        assert [t.id for _, t in palette.grid._entries] == ["p6", "p7"]


class TestKeyRouting:
    def test_tab_switches_tabs(self, palette):
        assert press(palette, Qt.Key.Key_Tab)
        assert palette.tabs.index == 1

    def test_alt_digit_jumps_to_tab(self, palette):
        assert press(palette, Qt.Key.Key_2, Qt.KeyboardModifier.AltModifier)
        assert palette.tabs.index == 1

    def test_arrows_move_the_selection(self, palette):
        assert press(palette, Qt.Key.Key_Right)
        assert palette.grid.current.id == "p2"

    def test_escape_clears_search_before_hiding(self, palette):
        palette.search.setText("summ")
        assert press(palette, Qt.Key.Key_Escape)
        assert palette.search.text() == ""

    def test_ctrl_arrow_is_released_to_the_search_box_while_filtering(self, palette):
        # Reordering is meaningless against search ranking, so the key must fall
        # through to the line edit for word-wise navigation.
        palette.search.setText("re")
        assert not press(palette, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)

    def test_printable_keys_fall_through_to_the_search_box(self, palette):
        assert not press(palette, Qt.Key.Key_A, text="a")

    def test_enter_on_a_slotted_template_opens_the_fill_panel(self, palette):
        from pcc.ui.palette import PAGE_FILL

        press(palette, Qt.Key.Key_Return)
        assert palette.stack.currentIndex() == PAGE_FILL
        assert palette.fill.template.id == "p1"

    def test_enter_on_a_slotless_template_pastes_directly(self, palette, monkeypatch):
        pasted: list[str] = []
        monkeypatch.setattr(palette, "paste_text", pasted.append)
        palette.grid.set_index(2)          # p3, "No slots here"
        press(palette, Qt.Key.Key_Return)
        assert pasted == ["No slots here"]

    def test_ctrl_enter_skips_the_fill_panel(self, palette, monkeypatch):
        pasted: list[str] = []
        monkeypatch.setattr(palette, "paste_text", pasted.append)
        press(palette, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        assert pasted == ["Refactor Python"], "defaults applied, no panel"


class TestFillPanel:
    def test_one_field_per_slot(self, palette):
        palette.fill.load(Template(title="T", body="{{a}} {{b|x}} {{a}}"))
        assert [f.slot.name for f in palette.fill._fields] == ["a", "b"]

    def test_rendered_uses_typed_values(self, palette):
        palette.fill.load(Template(title="T", body="{{a}}-{{b|x}}"))
        palette.fill._fields[0].edit.setPlainText("hello")
        assert palette.fill.rendered() == "hello-x"

    def test_rendered_keeps_literal_token_when_empty_and_no_default(self, palette):
        palette.fill.load(Template(title="T", body="{{a}}"))
        assert palette.fill.rendered() == "{{a}}"

    def test_multiline_value_survives(self, palette):
        palette.fill.load(Template(title="T", body="```{{code}}```"))
        palette.fill._fields[0].edit.setPlainText("line1\nline2")
        assert palette.fill.rendered() == "```line1\nline2```"

    def test_reload_replaces_previous_fields(self, palette):
        palette.fill.load(Template(title="A", body="{{a}} {{b}} {{c}}"))
        palette.fill.load(Template(title="B", body="{{z}}"))
        assert [f.slot.name for f in palette.fill._fields] == ["z"]

    def test_escape_returns_to_the_grid(self, palette):
        from pcc.ui.palette import PAGE_FILL, PAGE_GRID

        press(palette, Qt.Key.Key_Return)
        assert palette.stack.currentIndex() == PAGE_FILL
        palette.fill.handle_key(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        )
        assert palette.stack.currentIndex() == PAGE_GRID

    def test_shift_enter_is_left_for_a_newline(self, palette):
        palette.fill.load(Template(title="T", body="{{a}}"))
        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier
        )
        assert not palette.fill.handle_key(event), "Shift+Enter must reach the editor"


class TestMagicSlots:
    """``{{clipboard}}``, ``{{date}}`` etc. -- resolved, never typed."""

    def test_magic_slots_get_no_input_field(self, palette):
        from pcc.context import ResolveEnv, context_items, make_resolver

        env = ResolveEnv(clipboard="copied text")
        tmpl = Template(title="T", body="Explain {{clipboard}} for {{audience}}")
        palette.fill.load(
            tmpl,
            resolve=make_resolver(env),
            context_items=context_items(["clipboard"], env),
        )
        # Only the human slot gets a field; the magic one is resolved for us.
        assert [f.slot.name for f in palette.fill._fields] == ["audience"]

    def test_context_strip_shows_resolved_magic(self, palette):
        from pcc.context import ResolveEnv, context_items, make_resolver

        env = ResolveEnv(clipboard="hi")
        tmpl = Template(title="T", body="Explain {{clipboard}} for {{audience}}")
        palette.fill.load(
            tmpl, resolve=make_resolver(env), context_items=context_items(["clipboard"], env)
        )
        # isVisible() is False whenever the top-level window is hidden, which it
        # always is in these headless tests; isHidden() reflects the widget's own
        # shown/hidden intent instead.
        assert not palette.fill.context.isHidden()
        assert "clipboard · hi" in palette.fill.context.text()

    def test_rendered_fills_magic_and_typed_together(self, palette):
        from pcc.context import ResolveEnv, make_resolver

        env = ResolveEnv(clipboard="CODE")
        tmpl = Template(title="T", body="{{clipboard}} for {{audience}}")
        palette.fill.load(tmpl, resolve=make_resolver(env))
        palette.fill._fields[0].edit.setPlainText("a novice")
        assert palette.fill.rendered() == "CODE for a novice"

    def test_magic_only_template_pastes_without_the_fill_panel(self, palette, monkeypatch):
        from pcc.ui.palette import PAGE_GRID

        pasted = []
        monkeypatch.setattr(palette, "paste_text", pasted.append)
        monkeypatch.setattr(winapi_module(), "clipboard_get_text", lambda: "the code")
        palette._activate(Template(title="T", body="Explain {{clipboard}}"))
        assert pasted == ["Explain the code"]
        assert palette.stack.currentIndex() == PAGE_GRID

    def test_clipboard_prefills_and_preselects_a_code_slot(self, palette):
        big = "x" * 300
        tmpl = Template(title="T", body="Explain\n```\n{{code}}\n```")
        palette.fill.load(tmpl, prefill=big)
        field = palette.fill._fields[0]
        assert field.edit.toPlainText() == big
        palette.fill.focus_first()
        # Pre-selected: the whole guess is highlighted, so one keystroke replaces it.
        assert field.edit.textCursor().hasSelection()

    def test_short_clipboard_does_not_prefill(self, palette):
        tmpl = Template(title="T", body="{{code}}")
        palette.fill.load(tmpl, prefill="tiny")
        assert palette.fill._fields[0].edit.toPlainText() == ""


def winapi_module():
    from pcc import winapi

    return winapi


class TestMemory:
    """Frecency recording, slot recall, and the reload diff toast."""

    def test_activating_a_template_records_a_use(self, palette, monkeypatch):
        monkeypatch.setattr(palette, "paste_text", lambda *_: None)
        monkeypatch.setattr(winapi_module(), "clipboard_get_text", lambda: "")
        template = palette.library.tabs[0].templates[2]  # "Write tests", no slots
        palette._activate(template)
        assert palette.usage.frecency(template.id) == 1.0

    def test_submitting_a_fill_records_use_and_slot(self, palette, monkeypatch):
        monkeypatch.setattr(palette, "paste_text", lambda *_: None)
        template = Template(title="T", body="Say {{greeting}}", id="pX")
        palette._fill_template = template
        palette.fill.load(template)
        palette.fill._fields[0].edit.setPlainText("hi")
        palette._on_fill_submitted("Say hi")
        assert palette.usage.frecency("pX") == 1.0
        assert palette.usage.slot_value("pX", "greeting") == "hi"

    def test_recalled_slot_value_becomes_ghost_text(self, palette):
        template = Template(title="T", body="Say {{greeting}}", id="pY")
        palette.fill.load(template, recall={"greeting": "howdy"})
        field = palette.fill._fields[0]
        assert field.edit.placeholderText() == "howdy"
        # Ghost only: the field is still empty, so tabbing past keeps it unfilled.
        assert field.edit.toPlainText() == ""

    def test_reload_summary_counts_add_change_remove(self, palette):
        from pcc.model import Library, Tab, Template

        before = Library(tabs=[Tab(name="A", id="t", templates=[
            Template(title="keep", body="same", id="k"),
            Template(title="gone", body="x", id="g"),
            Template(title="edit", body="old", id="e"),
        ])])
        after = Library(tabs=[Tab(name="A", id="t", templates=[
            Template(title="keep", body="same", id="k"),
            Template(title="edit", body="NEW", id="e"),
            Template(title="fresh", body="y", id="f"),
        ])])
        assert palette._reload_summary(before, after) == "+1 ~1 -1"

    def test_reload_summary_is_word_when_unchanged(self, palette):
        lib = palette.library
        assert palette._reload_summary(lib, lib) == "RELOADED"


class TestComposition:
    """Ctrl+Space marks; Enter composes marked templates and modifiers."""

    def _add_modifier(self, palette):
        from pcc.model import Template

        mod = Template(title="Concise", body="Be concise.", id="mod1", tags=["modifier"])
        palette.library.tabs[0].templates.append(mod)
        palette.refresh_tabs()
        return mod

    def test_ctrl_space_marks_the_current_tile(self, palette):
        palette._toggle_mark()
        assert len(palette._marked) == 1
        palette._toggle_mark()
        assert palette._marked == []

    def test_marked_base_plus_modifier_composes(self, palette, monkeypatch):
        pasted = []
        monkeypatch.setattr(palette, "paste_text", pasted.append)
        monkeypatch.setattr(winapi_module(), "clipboard_get_text", lambda: "")
        self._add_modifier(palette)
        # Mark the modifier, then activate with a plain base selected.
        palette.grid.set_index(5)  # the appended modifier
        palette._toggle_mark()
        palette.grid.set_index(4)  # "Review", a slotless base
        palette._activate_selection()
        assert pasted == ["Review it\n\nBe concise."]
        assert palette._marked == []  # marks cleared after use

    def test_stacking_two_bases_joins_them(self, palette, monkeypatch):
        pasted = []
        monkeypatch.setattr(palette, "paste_text", pasted.append)
        monkeypatch.setattr(winapi_module(), "clipboard_get_text", lambda: "")
        # "Write tests" (idx 2, slotless) and "Review" (idx 4, slotless).
        palette.grid.set_index(2)
        palette._toggle_mark()
        palette.grid.set_index(4)
        palette._toggle_mark()
        palette._activate_selection()
        assert pasted == ["No slots here\n\nReview it"]

    def test_trigger_clears_stale_marks(self, palette):
        palette._toggle_mark()
        assert palette._marked
        palette.trigger()
        assert palette._marked == []

    def test_include_is_inlined_on_activate(self, palette, monkeypatch):
        from pcc.model import Template

        pasted = []
        monkeypatch.setattr(palette, "paste_text", pasted.append)
        monkeypatch.setattr(winapi_module(), "clipboard_get_text", lambda: "")
        palette.library.tabs[0].templates.append(
            Template(title="Rules", body="ALWAYS TEST", id="rules")
        )
        tmpl = Template(title="Uses", body="Do it. {{>rules}}", id="uses")
        palette._activate(tmpl)
        assert pasted == ["Do it. ALWAYS TEST"]


class TestCare:
    """Undo instead of confirm, and the adaptive hint bar."""

    def test_delete_is_undoable(self, palette):
        tab = palette.library.tabs[0]
        before = [t.id for t in tab.templates]
        palette.grid.set_index(0)
        palette._delete_template()
        assert len(palette.library.tabs[0].templates) == len(before) - 1
        palette._undo()
        assert [t.id for t in palette.library.tabs[0].templates] == before

    def test_undo_with_empty_journal_is_safe(self, palette):
        palette._undo()  # must not raise

    def test_delete_does_not_prompt(self, palette, monkeypatch):
        # If a confirmation dialog were still there, this would hang the test;
        # asserting the template simply vanishes proves there is none.
        called = []
        monkeypatch.setattr(palette, "_confirm", lambda *_: called.append(True) or True)
        palette.grid.set_index(0)
        palette._delete_template()
        assert called == []

    def test_hints_fade_with_familiarity(self, palette):
        from pcc.ui.palette import HINTS, MINIMAL_HINTS, PAGE_FILL, SHORT_HINTS

        assert palette._hint_for(PAGE_FILL) == HINTS[PAGE_FILL]
        for _ in range(30):
            palette.usage.record_page("fill")
        assert palette._hint_for(PAGE_FILL) == SHORT_HINTS[PAGE_FILL]
        for _ in range(100):
            palette.usage.record_page("fill")
        assert palette._hint_for(PAGE_FILL) == MINIMAL_HINTS[PAGE_FILL]

    def test_health_report_summarises_findings(self, palette):
        from pcc.model import Template

        palette.library.tabs[0].templates.append(Template(title="Blank", body="  ", id="blank"))
        summary, detail = palette._health_report()
        assert "empty" in summary
        assert "empty body" in detail

    def test_full_preview_toggle_shows_untruncated_text(self, palette):
        from pcc.model import Template

        body = "X" * 600
        palette.fill.load(Template(title="T", body=body))
        assert "…" in palette.fill.preview.text()          # collapsed by default
        palette.fill.toggle_full_preview()
        assert palette.fill.preview.text() == body          # full, untruncated


class TestChoiceSlots:
    """``{{tone|blunt|warm}}`` -- chips, plus custom input that always wins."""

    BODY = "Be {{tone|blunt|warm|formal}} about {{topic}}"

    def _load(self, palette, body=BODY):
        palette.fill.load(Template(title="T", body=body))
        return palette.fill._fields[0]

    def test_only_choice_slots_get_a_chip_row(self, palette):
        self._load(palette)
        rows = [f.options is not None for f in palette.fill._fields]
        assert rows == [True, False]

    def test_first_option_is_preselected(self, palette):
        assert self._load(palette).value() == "blunt"

    def test_the_field_stays_hidden_until_custom_is_chosen(self, palette):
        field = self._load(palette)
        assert not field.edit.isVisibleTo(field)
        field.options.select(field.options.CUSTOM)
        assert field.edit.isVisibleTo(field)

    def test_stepping_selects_as_it_moves(self, palette):
        field = self._load(palette)
        field.options.step(1)
        assert field.value() == "warm"

    def test_stepping_wraps_through_custom_back_to_the_first(self, palette):
        field = self._load(palette)
        for _ in range(3):                      # blunt -> warm -> formal -> custom
            field.options.step(1)
        assert field.options.is_custom
        field.options.step(1)
        assert field.value() == "blunt"

    def test_stepping_backwards_from_the_first_lands_on_custom(self, palette):
        field = self._load(palette)
        field.options.step(-1)
        assert field.options.is_custom

    def test_custom_text_beats_every_option(self, palette):
        field = self._load(palette)
        field.type_into_custom("wry")
        assert field.value() == "wry"
        assert palette.fill.rendered() == "Be wry about {{topic}}"

    def test_switching_back_to_a_chip_keeps_the_typed_text(self, palette):
        # Coming back to "custom" after a detour must not lose the answer.
        field = self._load(palette)
        field.type_into_custom("wry")
        field.options.select(0)
        assert field.value() == "blunt"
        field.options.select(field.options.CUSTOM)
        assert field.value() == "wry"

    def test_empty_custom_falls_back_to_the_literal_token(self, palette):
        # No preselection: nothing may be chosen on the user's behalf, and an
        # unanswered slot still survives into the paste.
        field = self._load(palette, "Be {{tone||warm|blunt}}")
        assert field.options.is_custom
        assert palette.fill.rendered() == "Be {{tone}}"

    def test_render_uses_the_chosen_option(self, palette):
        field = self._load(palette)
        field.options.select(2)
        assert palette.fill.rendered() == "Be formal about {{topic}}"

    def test_preview_follows_the_selection(self, palette):
        field = self._load(palette)
        field.options.select(1)
        assert "warm" in palette.fill.preview.text()

    def test_clicking_a_chip_selects_it(self, palette):
        field = self._load(palette)
        field.options._chips[2].clicked.emit()
        assert field.value() == "formal"

    def test_a_long_option_list_does_not_inflate_the_minimum_height(self, palette):
        # Qt derives a height-for-width widget's minimum height from its
        # narrowest layout -- for a wrapping row, every chip on a line of its
        # own. A field reporting that as its minimum would push the palette
        # taller than window_height asks for, however wide the window really is.
        body = "{{s|" + "|".join(f"option {i}" for i in range(8)) + "}}"
        field = self._load(palette, body)
        chip = field.options._chips[0].sizeHint().height()
        assert field.minimumSizeHint().height() < 4 * chip


class TestChoiceSlotKeys:
    """The chip row's keys, routed exactly as the palette's event filter does."""

    @pytest.fixture
    def field(self, palette):
        palette.fill.load(Template(title="T", body="Be {{tone|blunt|warm}} now"))
        palette.fill.focus_first()
        return palette.fill._fields[0]

    def _key(self, palette, key, text=""):
        return palette.fill.handle_key(
            QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
        )

    def test_right_moves_to_the_next_option(self, palette, field):
        assert self._key(palette, Qt.Key.Key_Right)
        assert field.value() == "warm"

    def test_end_jumps_to_custom(self, palette, field):
        assert self._key(palette, Qt.Key.Key_End)
        assert field.options.is_custom

    def test_typing_moves_into_the_custom_field(self, palette, field):
        # A printable key on a chip row means "none of these" -- and the
        # keystroke that said so must not be swallowed.
        assert self._key(palette, Qt.Key.Key_W, text="w")
        assert field.value() == "w"

    def test_arrows_are_left_alone_inside_a_text_field(self, palette, field):
        field.options.select(field.options.CUSTOM)
        field.edit.setFocus()
        assert not self._key(palette, Qt.Key.Key_Right), "caret movement, not selection"

    def test_enter_still_submits_from_a_chip_row(self, palette, field):
        submitted: list[str] = []
        palette.fill.submitted.connect(submitted.append)
        assert self._key(palette, Qt.Key.Key_Return)
        assert submitted == ["Be blunt now"]


class TestAuthoring:
    def _saved(self, palette) -> dict:
        from pcc import store

        return json.loads(
            store.library_path(palette.settings).read_text(encoding="utf-8")
        )

    def test_duplicate_inserts_after_the_original(self, palette):
        palette._duplicate_template()
        titles = [t.title for t in palette.library.tabs[0].templates]
        assert titles[1] == "Refactor for readability copy"

    def test_duplicate_persists(self, palette):
        palette._duplicate_template()
        assert len(self._saved(palette)["tabs"][0]["templates"]) == 6

    def test_reorder_moves_the_template(self, palette):
        palette._move_template(1)
        assert [t.id for t in palette.library.tabs[0].templates][:2] == ["p2", "p1"]

    def test_reorder_keeps_the_same_template_selected(self, palette):
        palette._move_template(1)
        assert palette.grid.current.id == "p1"

    def test_reorder_clamps_at_the_edges(self, palette):
        palette._move_template(-1)
        assert [t.id for t in palette.library.tabs[0].templates][0] == "p1"

    def test_move_tab_reorders_and_follows(self, palette):
        palette._move_tab(1)
        assert [t.id for t in palette.library.tabs] == ["t2", "t1"]
        assert palette.tabs.index == 1

    def test_move_tab_is_a_no_op_past_the_edge(self, palette):
        palette._move_tab(-1)
        assert [t.id for t in palette.library.tabs] == ["t1", "t2"]

    def test_editor_save_adds_a_new_template(self, palette):
        new = Template(title="Fresh", body="body {{x}}")
        palette._on_editor_saved(new, "t1")
        assert palette.library.tabs[0].templates[-1].title == "Fresh"
        assert palette.grid.current.id == new.id

    def test_editor_save_moves_between_tabs(self, palette):
        moved = palette.library.tabs[0].templates[0]
        palette._on_editor_saved(moved, "t2")
        assert moved.id not in [t.id for t in palette.library.tabs[0].templates]
        assert moved.id in [t.id for t in palette.library.tabs[1].templates]

    def test_before_save_hook_fires_on_every_write(self, palette):
        """The file watcher hangs off this; if it stops firing we reload our own
        writes in a loop."""
        calls: list[int] = []
        palette.before_save = lambda: calls.append(1)
        palette._duplicate_template()
        palette._move_template(1)
        assert len(calls) == 2

    def test_reload_picks_up_external_edits(self, palette):
        from pcc import store

        path = store.library_path(palette.settings)
        store.save_library(palette.library, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tabs"][0]["templates"][0]["title"] = "Edited Externally"
        path.write_text(json.dumps(data), encoding="utf-8")

        palette.reload_library()
        assert palette.library.tabs[0].templates[0].title == "Edited Externally"


class TestTypographyScaling:
    """Font settings must actually reshape the widgets, not just the QSS text."""

    def _palette(self, qapp, library, settings, **overrides):
        from pcc.ui.palette import PaletteWindow
        from pcc.ui.theme import build_stylesheet

        merged = {**settings, **overrides}
        qapp.setStyleSheet(build_stylesheet(merged))
        window = PaletteWindow(library, merged)
        # Polishing is enough to apply the stylesheet font and fire FontChange;
        # a full prewarm() show/hide is not needed to observe the geometry.
        window.ensurePolished()
        for child in window.findChildren(QWidget):
            child.ensurePolished()
        return window

    def test_font_family_reaches_the_tiles(self, qapp, library, settings, destroy):
        window = self._palette(qapp, library, settings, font_family="Georgia, serif")
        try:
            assert window.grid._pool[0].title.font().family() == "Georgia"
        finally:
            destroy(window)

    def test_preview_font_can_differ_from_the_ui_font(self, qapp, library, settings, destroy):
        window = self._palette(
            qapp, library, settings,
            font_family="Consolas", mono_preview=False, preview_font_family="Georgia",
        )
        try:
            tile = window.grid._pool[0]
            assert tile.title.font().family() == "Consolas"
            assert tile.body.font().family() == "Georgia"
        finally:
            destroy(window)

    def test_tile_height_grows_with_font_size(self, qapp, library, settings, destroy):
        """Regression: heights were computed before the stylesheet font was
        applied and never recomputed, so large fonts clipped instead of growing."""
        heights = []
        for size in (10, 16, 24):
            window = self._palette(qapp, library, settings, font_size=size)
            heights.append(window.grid._pool[0].body.height())
            destroy(window)
        assert heights == sorted(heights) and heights[0] < heights[-1], heights

    def test_window_can_still_be_as_narrow_as_configured(self, qapp, library, settings, destroy):
        """Regression: a non-wrapping hint bar reported its full text width as a
        minimum, so the window could never shrink to window_width."""
        window = self._palette(qapp, library, settings, font_size=22)
        try:
            assert window.minimumSizeHint().width() < 400
        finally:
            destroy(window)

    def test_reload_settings_restyles_in_place(self, qapp, library, settings, tmp_path, destroy):
        from pcc import store

        window = self._palette(qapp, library, settings)
        try:
            before = window.grid._pool[0].body.height()
            store.SETTINGS_PATH_BACKUP = store.SETTINGS_PATH
            path = tmp_path / "settings.json"
            path.write_text(json.dumps({**settings, "font_size": 26}), encoding="utf-8")
            store.SETTINGS_PATH = path
            try:
                window.reload_settings()
            finally:
                store.SETTINGS_PATH = store.SETTINGS_PATH_BACKUP
            assert window.grid._pool[0].body.height() > before
        finally:
            destroy(window)


class TestPaste:
    def test_paste_renders_defaults_and_hides(self, palette, monkeypatch):
        calls = {}
        monkeypatch.setattr("pcc.winapi.clipboard_get_text", lambda: "PRIOR")
        monkeypatch.setattr(
            "pcc.winapi.clipboard_set_text",
            lambda text: calls.setdefault("clipboard", text) or True,
        )
        monkeypatch.setattr(
            "pcc.winapi.send_paste", lambda chord: calls.setdefault("chord", chord) or True
        )
        monkeypatch.setattr("pcc.winapi.restore_focus", lambda hwnd: True)

        palette.paste_text("hello world")

        assert calls["clipboard"] == "hello world"
        assert calls["chord"] == "ctrl+v"
        assert not palette.isVisible()

    def test_empty_text_does_not_touch_the_clipboard(self, palette, monkeypatch):
        touched: list[str] = []
        monkeypatch.setattr("pcc.winapi.clipboard_set_text", lambda t: touched.append(t) or True)
        monkeypatch.setattr("pcc.winapi.restore_focus", lambda hwnd: True)
        palette.paste_text("")
        assert touched == []

    def test_busy_clipboard_keeps_the_palette_open(self, palette, monkeypatch):
        monkeypatch.setattr("pcc.winapi.clipboard_get_text", lambda: None)
        monkeypatch.setattr("pcc.winapi.clipboard_set_text", lambda t: False)
        palette.show()
        palette.paste_text("text")
        assert palette.isVisible(), "a failed copy must not silently swallow the paste"


class TestShutDown:
    """Ctrl+Q quits the process, rather than hiding the window."""

    def _asked(self, palette):
        calls: list[bool] = []
        palette.quit_requested.connect(lambda: calls.append(True))
        return calls

    def test_ctrl_q_requests_the_quit(self, palette):
        calls = self._asked(palette)
        assert press(palette, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier)
        assert calls == [True]

    def test_it_hides_and_hands_focus_back_first(self, palette, monkeypatch):
        restored: list[int] = []
        monkeypatch.setattr("pcc.winapi.restore_focus", lambda hwnd: restored.append(hwnd) or True)
        palette.show()
        palette.shut_down()
        assert not palette.isVisible()
        assert restored, "the foreground must not be left orphaned"

    def test_bare_q_is_left_to_the_search_box(self, palette):
        calls = self._asked(palette)
        assert not press(palette, Qt.Key.Key_Q, text="q")
        assert calls == []

    def test_it_cannot_fire_while_a_template_is_being_edited(self, palette):
        """The editor gets first refusal on every key, so Ctrl+Q never reaches
        the grid handler and cannot discard half-written work."""
        calls = self._asked(palette)
        # eventFilter ignores everything while hidden, so a hidden palette would
        # pass this test without routing anything.
        palette.show()
        palette._edit_template()
        assert palette.stack.currentIndex() == PAGE_EDITOR

        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Q,
                          Qt.KeyboardModifier.ControlModifier, "")
        assert not palette.eventFilter(palette.editor.body_edit, event)
        assert calls == []

    def test_the_same_key_does_quit_from_the_grid_page(self, palette):
        """The counterpart: proof the routing above is what stopped it."""
        calls = self._asked(palette)
        palette.show()
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Q,
                          Qt.KeyboardModifier.ControlModifier, "")
        assert palette.eventFilter(palette.search, event)
        assert calls == [True]



