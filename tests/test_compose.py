"""Includes ({{>ref}}) and modifier/stack composition."""

from __future__ import annotations

from pcc import compose
from pcc.model import Template, expand_includes, parse_slots, render


def _lookup(mapping):
    return lambda ref: mapping.get(ref)


class TestExpandIncludes:
    def test_inlines_a_referenced_body(self):
        out = expand_includes("Start {{>rules}} end", _lookup({"rules": "BE NICE"}))
        assert out == "Start BE NICE end"

    def test_leaves_ordinary_slots_untouched(self):
        # The structural pass must not touch {{slot}} or its default -- the fill
        # panel still needs to see them.
        out = expand_includes("{{>r}} {{name|Ada}}", _lookup({"r": "hi {{x}}"}))
        assert out == "hi {{x}} {{name|Ada}}"

    def test_nested_includes_expand(self):
        out = expand_includes("{{>a}}", _lookup({"a": "A {{>b}}", "b": "B"}))
        assert out == "A B"

    def test_missing_ref_is_a_visible_marker(self):
        out = expand_includes("{{>nope}}", _lookup({}))
        assert out == "{{>missing: nope}}"

    def test_direct_cycle_is_broken_with_a_marker(self):
        out = expand_includes("{{>a}}", _lookup({"a": "loop {{>a}}"}))
        assert out == "loop {{>cycle: a}}"

    def test_indirect_cycle_is_broken(self):
        out = expand_includes("{{>a}}", _lookup({"a": "{{>b}}", "b": "{{>a}}"}))
        assert "{{>cycle: a}}" in out

    def test_no_lookup_leaves_the_token(self):
        assert expand_includes("{{>a}}", None) == "{{>a}}"


class TestIncludesInSlots:
    def test_include_is_not_a_fill_slot(self):
        # {{>rules}} contributes no field of its own.
        assert parse_slots("{{>rules}} {{name}}") == parse_slots("{{name}}")

    def test_slots_inside_an_include_appear_after_expansion(self):
        expanded = expand_includes("{{>r}}", _lookup({"r": "translate {{lang}}"}))
        assert [s.name for s in parse_slots(expanded)] == ["lang"]


class TestRenderIncludes:
    def test_render_expands_and_fills(self):
        out = render(
            "{{>greet}}",
            {"name": "Ada"},
            lookup=_lookup({"greet": "Hello {{name}}"}),
        )
        assert out == "Hello Ada"


class TestCompose:
    def test_combined_body_joins_bases_then_modifiers(self):
        base = Template(title="B", body="Do the thing.")
        mod = Template(title="M", body="Be concise.", tags=["modifier"])
        assert compose.combined_body([base], [mod]) == "Do the thing.\n\nBe concise."

    def test_shared_slot_collapses_across_a_stack(self):
        a = Template(title="A", body="Review {{code}}")
        b = Template(title="B", body="Test {{code}}")
        body = compose.combined_body([a, b], [])
        # One shared field, exactly the single-template collapse rule.
        assert [s.name for s in parse_slots(body)] == ["code"]

    def test_single_base_no_modifiers_keeps_identity(self):
        base = Template(title="B", body="x", id="real")
        assert compose.compose([base], []) is base

    def test_compose_of_base_plus_modifier_is_transient(self):
        base = Template(title="B", body="x", id="real")
        mod = Template(title="M", body="concise", tags=["modifier"])
        composed = compose.compose([base], [mod])
        assert composed is not None and composed.id == "__composed__"
        assert composed.body == "x\n\nconcise"

    def test_empty_inputs_compose_to_none(self):
        assert compose.compose([], []) is None

    def test_blank_bodies_are_dropped(self):
        base = Template(title="B", body="   ")
        mod = Template(title="M", body="concise", tags=["modifier"])
        assert compose.combined_body([base], [mod]) == "concise"


class TestIsModifier:
    def test_tagged_template_is_a_modifier(self):
        assert Template(title="M", body="x", tags=["modifier"]).is_modifier

    def test_case_insensitive_tag(self):
        assert Template(title="M", body="x", tags=["Modifier"]).is_modifier

    def test_untagged_is_not(self):
        assert not Template(title="T", body="x").is_modifier
