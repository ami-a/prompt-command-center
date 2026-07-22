"""Placeholder grammar and rendering — the rules that decide what gets pasted."""

from __future__ import annotations

import pytest

from pcc.model import Library, Tab, Template, parse_slots, readable, render


class TestParseSlots:
    def test_finds_slots_in_order(self):
        slots = parse_slots("{{a}} then {{b}} then {{c}}")
        assert [s.name for s in slots] == ["a", "b", "c"]

    def test_captures_default(self):
        (slot,) = parse_slots("{{language|Python}}")
        assert (slot.name, slot.default) == ("language", "Python")

    def test_no_default_is_none_not_empty(self):
        # None and "" must stay distinguishable: one means "no default was
        # written", the other would mean "default to nothing".
        (slot,) = parse_slots("{{language}}")
        assert slot.default is None

    def test_whitespace_is_trimmed(self):
        (slot,) = parse_slots("{{  language  |  Python  }}")
        assert (slot.name, slot.default) == ("language", "Python")

    def test_repeated_name_collapses_to_one_slot(self):
        slots = parse_slots("{{name}} and {{name}} again")
        assert len(slots) == 1

    def test_first_default_wins_across_repeats(self):
        (slot,) = parse_slots("{{name|Ada}} then {{name|Grace}}")
        assert slot.default == "Ada"

    def test_default_is_adopted_from_later_occurrence(self):
        # Write the default once, refer to the slot bare afterwards.
        (slot,) = parse_slots("{{name}} then {{name|Ada}}")
        assert slot.default == "Ada"

    @pytest.mark.parametrize("body", ["{{}}", "{{   }}", "plain text", "{single}", ""])
    def test_non_slots_are_ignored(self, body):
        assert parse_slots(body) == []

    def test_unbalanced_braces_do_not_match(self):
        assert parse_slots("{{ unclosed") == []


class TestRender:
    def test_user_value_wins(self):
        assert render("{{lang|Python}}", {"lang": "Rust"}) == "Rust"

    def test_default_applies_when_unfilled(self):
        assert render("{{lang|Python}}", {}) == "Python"

    def test_blank_value_falls_back_to_default(self):
        assert render("{{lang|Python}}", {"lang": "   "}) == "Python"

    def test_literal_token_survives_when_no_default(self):
        # The "nothing is silently lost" guarantee: an unfilled slot stays
        # visible in the pasted text so it can be finished in the target app.
        assert render("say {{thing}}", {}) == "say {{thing}}"

    def test_literal_token_drops_the_default_pipe(self):
        assert render("{{a}} {{b|x}}", {"b": ""}) == "{{a}} x"

    def test_repeated_slot_fills_every_occurrence(self):
        assert render("{{n}}-{{n}}-{{n}}", {"n": "7"}) == "7-7-7"

    def test_unicode_round_trips(self):
        assert render("{{greeting}}", {"greeting": "שלום 你好"}) == "שלום 你好"

    def test_multiline_value_is_preserved(self):
        assert render("```\n{{code}}\n```", {"code": "a\nb"}) == "```\na\nb\n```"

    def test_unknown_values_are_ignored(self):
        assert render("{{a|x}}", {"zzz": "y"}) == "x"

    def test_value_is_not_re_expanded(self):
        # A value that looks like a placeholder must not be substituted again.
        assert render("{{a}}", {"a": "{{b}}"}) == "{{b}}"


class TestReadable:
    def test_defaults_become_prose(self):
        assert readable("Refactor {{lang|Python}} code") == "Refactor Python code"

    def test_bare_slot_becomes_its_name(self):
        assert readable("Explain {{code}}") == "Explain code"

    def test_whitespace_collapses(self):
        assert readable("a\n\n  b\tc") == "a b c"


class TestTemplate:
    def test_has_slots(self):
        assert Template(title="t", body="{{a}}").has_slots
        assert not Template(title="t", body="plain").has_slots

    def test_ids_are_unique(self):
        assert Template(title="a", body="").id != Template(title="b", body="").id

    def test_round_trips_through_dict(self):
        original = Template(title="T", body="{{a|1}}", tags=["x"])
        restored = Template.from_dict(original.to_dict())
        assert (restored.id, restored.title, restored.body, restored.tags) == (
            original.id, original.title, original.body, original.tags
        )

    def test_from_dict_tolerates_garbage(self):
        template = Template.from_dict({})
        assert template.title == "Untitled" and template.body == ""


class TestLibrary:
    def _library(self) -> Library:
        return Library(tabs=[
            Tab(name="One", id="t1", templates=[
                Template(title="A", body="", id="p1"),
                Template(title="B", body="", id="p2"),
            ]),
            Tab(name="Two", id="t2", templates=[Template(title="C", body="", id="p3")]),
        ])

    def test_locate_returns_tab_and_index(self):
        tab, index = self._library().locate("p2")
        assert (tab.id, index) == ("t1", 1)

    def test_locate_missing_is_none(self):
        assert self._library().locate("nope") is None

    def test_iter_all_spans_tabs(self):
        assert [t.id for _, t in self._library().iter_all()] == ["p1", "p2", "p3"]

    def test_round_trips_through_dict(self):
        original = self._library()
        restored = Library.from_dict(original.to_dict())
        assert [t.id for _, t in restored.iter_all()] == ["p1", "p2", "p3"]
        assert [t.name for t in restored.tabs] == ["One", "Two"]
