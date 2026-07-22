"""Typography settings: the stylesheet must always resolve to valid QSS."""

from __future__ import annotations

import pytest

from pcc.store import DEFAULT_SETTINGS
from pcc.ui.theme import (
    MAX_FONT_SIZE,
    MIN_DERIVED_SIZE,
    MIN_FONT_SIZE,
    build_stylesheet,
    font_metrics,
)


def _settings(**overrides):
    return {**DEFAULT_SETTINGS, **overrides}


class TestFontMetrics:
    def test_default_reproduces_the_hand_tuned_scale(self):
        # The ratios exist to generalise the original design, not change it.
        assert font_metrics(_settings(font_size=13)) == {
            "FS_BASE": 13, "FS_SMALL": 12, "FS_BODY": 11, "FS_TINY": 10, "FS_TITLE": 14,
        }

    def test_hierarchy_survives_scaling_up(self):
        m = font_metrics(_settings(font_size=22))
        assert m["FS_TINY"] < m["FS_BODY"] < m["FS_SMALL"] < m["FS_BASE"] < m["FS_TITLE"]

    @pytest.mark.parametrize("size", [1, 4, MIN_FONT_SIZE, 13, MAX_FONT_SIZE, 200])
    def test_sizes_stay_within_sane_bounds(self, size):
        m = font_metrics(_settings(font_size=size))
        assert m["FS_BASE"] <= MAX_FONT_SIZE + 2
        assert all(v >= MIN_DERIVED_SIZE for v in m.values())

    @pytest.mark.parametrize("bogus", ["big", None, [], {}])
    def test_non_numeric_font_size_falls_back_to_the_default(self, bogus):
        # A bad hand-edit must not crash or produce an unreadable palette.
        assert font_metrics(_settings(font_size=bogus))["FS_BASE"] == 13

    @pytest.mark.parametrize(
        "given,expected", [(3.7, MIN_FONT_SIZE), (1, MIN_FONT_SIZE), (500, MAX_FONT_SIZE)]
    )
    def test_out_of_range_font_size_is_clamped(self, given, expected):
        assert font_metrics(_settings(font_size=given))["FS_BASE"] == expected


class TestStylesheet:
    def test_no_placeholder_is_left_unresolved(self):
        assert "$" not in build_stylesheet(DEFAULT_SETTINGS)

    @pytest.mark.parametrize("size", [8, 13, 28])
    def test_requested_size_reaches_the_stylesheet(self, size):
        css = build_stylesheet(_settings(font_size=size))
        assert f"font-size: {size}px" in css

    def test_family_is_applied(self):
        css = build_stylesheet(_settings(font_family="Fira Code, monospace"))
        assert '"Fira Code", monospace' in css

    def test_multiword_families_are_quoted(self):
        """Unquoted multi-word families are silently dropped by Qt."""
        css = build_stylesheet(_settings(font_family="Cascadia Code, Consolas"))
        assert '"Cascadia Code"' in css
        assert '"Consolas"' not in css, "single-word names need no quotes"

    def test_already_quoted_family_is_not_double_quoted(self):
        css = build_stylesheet(_settings(font_family='"Fira Code"'))
        assert '""' not in css

    def test_empty_family_falls_back_to_monospace(self):
        assert "font-family: monospace;" in build_stylesheet(_settings(font_family=""))

    def test_mono_preview_true_uses_the_ui_font_for_body(self):
        css = build_stylesheet(_settings(font_family="Fira Code", mono_preview=True))
        assert "Segoe" not in css

    def test_mono_preview_false_switches_the_body_font(self):
        css = build_stylesheet(
            _settings(mono_preview=False, preview_font_family="Georgia, serif")
        )
        assert "Georgia, serif" in css

    def test_output_is_deterministic(self):
        assert build_stylesheet(DEFAULT_SETTINGS) == build_stylesheet(DEFAULT_SETTINGS)
