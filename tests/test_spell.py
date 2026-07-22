"""Spelling: what gets asked about, what gets marked, and what gets offered.

The system checker is faked by default -- a set of misspelled words -- so the
suite says the same thing on every machine and never pays for COM. One test at
the bottom is marked ``live_spell`` and talks to the real thing when there is
one, which is what keeps the ctypes binding honest.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMenu, QPlainTextEdit

from pcc import spell, store
from pcc.ui import spellcheck
from pcc.ui.editor import EditorPanel

pytestmark = pytest.mark.usefixtures("qapp")

MISSPELLED = {"sentance", "mispelled", "paragrph", "teh", "proffesional", "freindly"}
SUGGESTIONS = {"sentance": ["sentence", "sentience"], "mispelled": ["misspelled"]}


@pytest.fixture(autouse=True)
def fake_backend(request, monkeypatch):
    """Swap the checker for a set, unless the test asked for the real module."""
    if "real_spell" in request.keywords:
        spell.reset()
        yield
        spell.reset()
        return
    monkeypatch.setattr(spell, "available", lambda: True)
    monkeypatch.setattr(spell, "is_correct", lambda word: word not in MISSPELLED)
    monkeypatch.setattr(spell, "suggest", lambda word: list(SUGGESTIONS.get(word, [])))
    monkeypatch.setattr(spell, "ignore", lambda word: MISSPELLED.discard(word) or True)
    monkeypatch.setattr(spell, "add", lambda word: MISSPELLED.discard(word) or True)
    spellcheck.set_enabled(True)
    yield
    spellcheck.set_enabled(True)


def build(text: str) -> QPlainTextEdit:
    edit = QPlainTextEdit()
    spellcheck.attach(edit)
    edit.setPlainText(text)
    return edit


def marked(edit: QPlainTextEdit) -> list[str]:
    """Every word currently wearing a squiggle, in document order."""
    text = edit.toPlainText()
    words: list[str] = []
    block = edit.document().begin()
    while block.isValid():
        for span in block.layout().formats():
            start = block.position() + span.start
            words.append(text[start:start + span.length])
        block = block.next()
    return words


def caret(edit: QPlainTextEdit, position: int) -> QTextCursor:
    cursor = edit.textCursor()
    cursor.setPosition(position)
    edit.setTextCursor(cursor)
    return cursor


@pytest.fixture
def menus(monkeypatch) -> list[QMenu]:
    """Catch fix menus instead of entering their modal loop."""
    caught: list[QMenu] = []
    monkeypatch.setattr(spellcheck, "_show_menu",
                        lambda menu, origin: caught.append(menu))
    return caught


def entries(menu: QMenu) -> dict[str, object]:
    return {action.text(): action for action in menu.actions()}


class TestTokenising:
    """The filter that runs before the checker is ever asked."""

    @pytest.mark.parametrize("text,expected", [
        ("This sentance has a mispelled word.",
         ["This", "sentance", "has", "mispelled", "word"]),
        # A sentence-ending full stop must not turn its word into an identifier.
        ("end. Next sentance begins.", ["end", "Next", "sentance", "begins"]),
        # The slot *name* is an identifier; its options are prose the user wrote.
        ("Keep the tone {{tone|proffesional|freindly}} now.",
         ["Keep", "the", "tone", "proffesional", "freindly", "now"]),
        ("Refactor {{language|Python|Go}} for {{goal}} today.",
         ["Refactor", "Python", "for", "today"]),
        ("See `foo_bar()` and more.", ["See", "and", "more"]),
        # A placeholder whose *name* is an identifier makes the whole token
        # opaque -- the skip regions overlap, and must merge rather than
        # shadow one another.
        ("Set {{slot_name|proffesional}} and go.", ["Set", "and"]),
        ("Backticks `may hold sentance words` too.", ["Backticks", "too"]),
        (r"Open store.load_settings in pcc/ui/palette.py at C:\Users\x now.",
         ["Open", "now"]),
        ("Visit https://example.com/sentance or mail teh@b.com today.",
         ["Visit", "mail", "today"]),
        ("The API returns JSON via setPlainText and snake_case_thing v2.",
         ["The", "returns", "via", "and"]),
        ("I don't think it's teh cat.", ["don't", "think", "it's", "teh", "cat"]),
        ("The naïve café résumé.", ["The", "naïve", "café", "résumé"]),
        # An en-US checker has no business judging Hebrew.
        ("תרגם את הטקסט hello", ["hello"]),
        # Two letters is an abbreviation far more often than a typo.
        ("a an it to teh", ["teh"]),
    ])
    def test_candidates(self, text, expected):
        assert [word for _, word in spellcheck.candidates(text)] == expected

    def test_offsets_point_at_the_word(self):
        text = "This sentance has a mispelled word."
        assert list(spellcheck.candidates(text))[1] == (5, "sentance")
        assert text[5:13] == "sentance"


class TestMarks:
    def test_marks_only_the_misspellings(self):
        edit = build("This sentance has a mispelled word.")
        assert marked(edit) == ["sentance", "mispelled"]

    def test_skipped_regions_are_never_marked(self):
        edit = build("A `sentance` and {{mispelled}} and https://x.com/paragrph ok")
        assert marked(edit) == []

    def test_each_paragraph_is_marked_independently(self):
        edit = build("A sentance here.\nNothing wrong.\nA paragrph there.")
        assert marked(edit) == ["sentance", "paragrph"]

    def test_fenced_code_is_left_alone(self):
        edit = build("A sentance.\n```\nteh mispelled code\n```\nA paragrph.")
        assert marked(edit) == ["sentance", "paragrph"]

    def test_a_huge_block_is_skipped_whole(self):
        # A code paste, not prose. Checking it would cost ~50 ms and tell the
        # user nothing they want to hear.
        edit = build("sentance " + "word " * spellcheck.MAX_BLOCK_LEN)
        assert marked(edit) == []

    def test_editing_one_line_remarks_it(self):
        edit = build("All fine here.")
        assert marked(edit) == []
        caret(edit, len("All fine"))
        edit.insertPlainText(" sentance")
        assert marked(edit) == ["sentance"]

    def test_disabling_clears_the_marks_and_enabling_restores_them(self):
        edit = build("This sentance.")
        assert marked(edit) == ["sentance"]
        spellcheck.set_enabled(False)
        assert marked(edit) == []
        spellcheck.set_enabled(True)
        assert marked(edit) == ["sentance"]

    @pytest.mark.real_spell
    def test_no_checker_means_no_marks_not_a_crash(self, monkeypatch):
        """Driven through the real is_correct, with the COM side dead."""
        monkeypatch.setattr(spell, "_ensure", lambda: False)
        assert marked(build("This sentance.")) == []

    def test_marking_an_empty_document_never_builds_a_checker(self, monkeypatch):
        """COM setup belongs in prewarm, not in a widget constructor."""
        monkeypatch.setattr(spell, "_ensure", lambda: pytest.fail("built a checker"))
        build("")

    def test_colour_follows_the_scheme(self):
        spellcheck.set_colour("#F472B6")
        edit = build("This sentance.")
        span = edit.document().begin().layout().formats()[0]
        assert span.format.underlineColor().name() == "#f472b6"
        assert span.format.underlineStyle().name == "WaveUnderline"

    def test_the_mark_is_washed_as_well_as_underlined(self):
        """A 1 px wave alone is nearly invisible on these surfaces."""
        spellcheck.set_colour("#F472B6")
        edit = build("This sentance.")
        # Each of these has to be held: chaining off the temporary format frees
        # it underneath the brush, and shiboken raises.
        spans = edit.document().begin().layout().formats()
        style = spans[0].format
        wash = style.background().color()
        assert wash.name() == "#f472b6"
        assert 0 < wash.alphaF() < 0.5, "a wash, not a highlight"

    def test_correct_words_are_left_completely_alone(self):
        """The wash must not leak onto text that is fine."""
        edit = build("Every word here is spelled correctly.")
        assert edit.document().begin().layout().formats() == []

    def test_attach_is_idempotent(self):
        edit = QPlainTextEdit()
        assert spellcheck.attach(edit) is spellcheck.attach(edit)


class TestFixing:
    def test_word_at_the_caret(self):
        edit = build("This sentance has a mispelled word.")
        assert spellcheck.word_at(edit, caret(edit, 7)) == (5, "sentance")
        # Just after the word you finished typing still counts as on it.
        assert spellcheck.word_at(edit, caret(edit, 13)) == (5, "sentance")

    def test_no_word_inside_a_skipped_region(self):
        edit = build("A `sentance` here.")
        assert spellcheck.word_at(edit, caret(edit, 6)) is None

    def test_menu_replaces_the_word_in_one_undo_step(self, menus):
        edit = build("This sentance has a mispelled word.")
        caret(edit, 7)
        assert spellcheck.open_suggestions(edit) is True

        actions = entries(menus[0])
        assert "sentence" in actions and "Add to dictionary" in actions
        actions["sentence"].trigger()
        assert edit.toPlainText() == "This sentence has a mispelled word."
        assert marked(edit) == ["mispelled"]

        edit.undo()
        assert edit.toPlainText() == "This sentance has a mispelled word."

    def test_best_suggestion_is_preselected(self, menus):
        edit = build("This sentance.")
        caret(edit, 7)
        spellcheck.open_suggestions(edit)
        assert menus[0].activeAction().text() == "sentence"

    def test_a_word_with_no_suggestions_still_offers_the_dictionary(self, menus):
        edit = build("This paragrph.")
        caret(edit, 7)
        assert spellcheck.open_suggestions(edit) is True
        assert "no suggestions" in entries(menus[0])
        assert "Add to dictionary" in entries(menus[0])

    def test_ignoring_clears_the_mark(self, menus):
        edit = build("This sentance.")
        caret(edit, 7)
        spellcheck.open_suggestions(edit)
        try:
            entries(menus[0])["Ignore"].trigger()
            assert marked(edit) == []
        finally:
            MISSPELLED.add("sentance")

    def test_nothing_offered_for_a_correct_word(self, menus):
        edit = build("This sentance.")
        caret(edit, 2)   # inside "This"
        assert spellcheck.open_suggestions(edit) is False
        assert menus == []

    def test_right_click_keeps_the_standard_menu(self, menus):
        """Switching to a custom context menu must not cost Cut/Copy/Paste."""
        edit = build("This sentance has words.")
        edit.resize(400, 80)
        point = edit.cursorRect(caret(edit, 7)).center()

        spellcheck.context_menu(edit, point)
        labels = [action.text() for action in menus[0].actions()]
        assert "sentence" in labels                      # the fix, on top
        assert labels.index("sentence") < labels.index("Ignore")
        assert any("Paste" in label for label in labels)  # ...and the usual menu

    def test_right_click_on_clean_text_is_just_the_standard_menu(self, menus):
        edit = build("This sentance has words.")
        edit.resize(400, 80)
        point = edit.cursorRect(caret(edit, 2)).center()

        spellcheck.context_menu(edit, point)
        labels = [action.text() for action in menus[0].actions()]
        assert "Ignore" not in labels
        assert any("Paste" in label for label in labels)

    def test_nothing_offered_when_disabled(self):
        edit = build("This sentance.")
        caret(edit, 7)
        spellcheck.set_enabled(False)
        assert spellcheck.open_suggestions(edit) is False


class TestPaletteIntegration:
    def test_menu_suppresses_the_auto_hide(self, palette, monkeypatch):
        """The palette hides on deactivation; the menu must not trip that."""
        seen: list[bool] = []
        monkeypatch.setattr(spellcheck, "_show_menu", lambda menu, origin: seen.append(
            palette._suppress_deactivate))

        edit = palette.editor.body_edit
        edit.setPlainText("This sentance.")
        caret(edit, 7)
        assert spellcheck.open_suggestions(edit) is True
        assert seen == [True]
        # ...and hands the auto-hide back afterwards.
        assert palette._suppress_deactivate is False

    def test_modal_guard_restores_the_flag_after_an_error(self, palette):
        with pytest.raises(ValueError):
            with palette.modal_guard():
                raise ValueError
        assert palette._suppress_deactivate is False

    def test_the_setting_drives_the_marks(self, palette):
        palette.settings["spellcheck"] = False
        palette._apply_spellcheck()
        edit = palette.editor.body_edit
        edit.setPlainText("This sentance.")
        assert marked(edit) == []

        palette.settings["spellcheck"] = True
        palette._apply_spellcheck()
        assert marked(edit) == ["sentance"]

    def test_slot_fields_are_checked(self, palette, library):
        palette.fill.load(library.tabs[0].templates[1])   # "Explain {{code}}"
        field = palette.fill._fields[0]
        field.edit.setPlainText("Explain this mispelled thing")
        assert marked(field.edit) == ["mispelled"]

    def test_settings_offers_the_toggle(self):
        from pcc.ui.settings_panel import build_settings

        row = next(s for s in build_settings() if s.key == "spellcheck")
        assert row.adjust(True, 1) is False
        assert row.fmt(True) == "on"

    def test_defaults_carry_the_keys(self):
        # load_settings drops anything not in DEFAULT_SETTINGS, so a missing key
        # here would silently disable the whole feature.
        assert store.DEFAULT_SETTINGS["spellcheck"] is True
        assert store.DEFAULT_SETTINGS["spellcheck_language"] is None


class TestEditorTitle:
    """The title field became a QPlainTextEdit so it could carry marks."""

    def test_round_trips_the_title(self, library):
        panel = EditorPanel()
        panel.load(library.tabs[0].templates[0], library.tabs, "t1")
        assert panel.title_edit.toPlainText() == "Refactor for readability"

    def test_a_pasted_newline_cannot_survive_into_a_title(self, library):
        panel = EditorPanel()
        panel.load(library.tabs[0].templates[0], library.tabs, "t1")
        saved: list[str] = []
        panel.saved.connect(lambda template, _tab: saved.append(template.title))
        panel.title_edit.setPlainText("  Two\nline   title  ")
        panel._commit()
        assert saved == ["Two line title"]

    def test_the_title_is_marked(self, library):
        panel = EditorPanel()
        panel.load(library.tabs[0].templates[0], library.tabs, "t1")
        panel.title_edit.setPlainText("Refactor a sentance")
        assert marked(panel.title_edit) == ["sentance"]


@pytest.mark.real_spell
class TestBackend:
    """The real module: caching, and -- if the machine has one -- a real checker."""

    def test_a_word_is_only_ever_checked_once(self, monkeypatch):
        asked: list[str] = []
        monkeypatch.setattr(spell, "_ensure", lambda: True)
        monkeypatch.setattr(spell, "_has_error",
                            lambda word: bool(asked.append(word)) or word in MISSPELLED)

        assert spell.is_correct("sentance") is False
        assert spell.is_correct("sentance") is False
        assert spell.is_correct("word") is True
        assert asked == ["sentance", "word"]

    def test_teaching_a_word_updates_the_cache(self, monkeypatch):
        monkeypatch.setattr(spell, "_ensure", lambda: True)
        monkeypatch.setattr(spell, "_has_error", lambda word: word in MISSPELLED)
        monkeypatch.setattr(spell, "_method",
                            lambda *args: (lambda *call_args: 0))

        assert spell.is_correct("sentance") is False
        assert spell.ignore("sentance") is True
        assert spell.is_correct("sentance") is True

    def test_the_cache_is_bounded(self, monkeypatch):
        monkeypatch.setattr(spell, "_ensure", lambda: True)
        monkeypatch.setattr(spell, "_has_error", lambda word: False)
        monkeypatch.setattr(spell, "MAX_CACHE", 8)
        for index in range(20):
            spell.is_correct(f"word{index}")
        assert len(spell._cache) <= 8

    def test_a_broken_checker_never_underlines(self, monkeypatch):
        monkeypatch.setattr(spell, "_ensure", lambda: False)
        assert spell.is_correct("sentance") is True
        assert spell.suggest("sentance") == []
        assert spell.add("sentance") is False

    @pytest.mark.skipif(not spell.available(), reason="no Windows spell checker here")
    def test_the_real_checker_agrees(self):
        assert spell.is_correct("readability") is True
        assert spell.is_correct("mispelled") is False
        assert "misspelled" in spell.suggest("mispelled")
        assert spell.language()
