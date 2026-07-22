"""Colour schemes: derivation must stay legible for every scheme."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor

from pcc.ui import schemes

ALL = pytest.mark.parametrize("key", schemes.keys())


def _contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colours."""

    def luminance(name: str) -> float:
        colour = QColor(name)
        channels = []
        for value in (colour.redF(), colour.greenF(), colour.blueF()):
            channels.append(value / 12.92 if value <= 0.03928
                            else ((value + 0.055) / 1.055) ** 2.4)
        r, g, b = channels
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    first, second = luminance(a), luminance(b)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


class TestTokens:
    @ALL
    def test_every_token_is_a_valid_colour(self, key):
        for name, value in schemes.get(key).tokens().items():
            assert QColor(value).isValid(), f"{key}.{name} = {value!r}"

    @ALL
    def test_all_schemes_expose_the_same_tokens(self, key):
        assert set(schemes.get(key).tokens()) == set(
            schemes.get(schemes.DEFAULT_SCHEME).tokens()
        )

    @ALL
    def test_body_text_is_comfortably_readable(self, key):
        t = schemes.get(key).tokens()
        assert _contrast(t["TEXT"], t["BG"]) >= 7.0, "primary text should hit AAA"

    @ALL
    def test_secondary_text_stays_readable(self, key):
        t = schemes.get(key).tokens()
        assert _contrast(t["MUTED"], t["TILE"]) >= 3.0

    @ALL
    def test_accent_reads_against_the_background(self, key):
        t = schemes.get(key).tokens()
        assert _contrast(t["ACCENT"], t["BG"]) >= 4.5

    @ALL
    def test_selection_text_reads_on_the_accent(self, key):
        t = schemes.get(key).tokens()
        assert _contrast(t["ON_ACCENT"], t["ACCENT_DEEP"]) >= 4.5

    @ALL
    def test_surfaces_are_ordered_by_elevation(self, key):
        t = schemes.get(key).tokens()
        levels = [QColor(t[n]).lightnessF()
                  for n in ("BG", "PANEL", "TILE", "TILE_HOVER", "BORDER")]
        assert levels == sorted(levels), f"{key}: surfaces not monotonic: {levels}"

    @ALL
    def test_accent_soft_never_washes_out_to_white(self, key):
        """Ice and Void start light; a fixed lift would push them to near-white
        and lose the hue that identifies the theme."""
        soft = QColor(schemes.get(key).tokens()["ACCENT_SOFT"])
        assert soft.lightnessF() <= 0.85
        # hslSaturationF, not saturationF -- the latter is HSV saturation and is
        # naturally low for light colours, so it would pass regardless.
        assert soft.hslSaturationF() >= 0.50

    @ALL
    def test_the_spelling_mark_carries_further_than_its_source(self, key):
        """Qt's wave underline is one antialiased pixel high, so half of it is
        background. SPELL exists to survive that; it must never come out dimmer
        than the SECONDARY it derives from."""
        t = schemes.get(key).tokens()
        spell, secondary = QColor(t["SPELL"]), QColor(t["SECONDARY"])
        assert spell.lightnessF() >= secondary.lightnessF()
        assert spell.hslSaturationF() >= secondary.hslSaturationF()
        assert _contrast(t["SPELL"], t["PANEL"]) >= _contrast(t["SECONDARY"], t["PANEL"])

    @ALL
    def test_the_spelling_mark_is_visible_on_every_surface(self, key):
        t = schemes.get(key).tokens()
        for surface in ("PANEL", "PANEL_FOCUS", "TILE"):
            # 3.0 is the WCAG bar for non-text UI; a squiggle is exactly that.
            assert _contrast(t["SPELL"], t[surface]) >= 3.0, f"{key} on {surface}"

    @ALL
    def test_the_spelling_mark_keeps_its_hue(self, key):
        """Brightening must not bleach it to white -- the mark still belongs to
        the scheme, and a grey squiggle reads as a rendering artefact."""
        assert QColor(schemes.get(key).tokens()["SPELL"]).hslSaturationF() >= 0.85

    @ALL
    def test_selected_tile_is_distinguishable_from_a_plain_one(self, key):
        t = schemes.get(key).tokens()
        assert t["TILE_SELECTED"] != t["TILE"]

    @ALL
    def test_the_window_edge_is_unmistakable(self, key):
        """The palette appears over an unknown desktop, so its own border has to
        carry far more than the inner ones do."""
        t = schemes.get(key).tokens()
        assert _contrast(t["CARD_BORDER"], t["BG"]) >= 2.0
        assert _contrast(t["CARD_BORDER"], t["BG"]) > _contrast(t["BORDER"], t["BG"])

    @ALL
    def test_the_window_edge_never_outshines_the_accent(self, key):
        # A border brighter than the accent would pull the eye to the frame
        # instead of to the selected tile.
        t = schemes.get(key).tokens()
        assert QColor(t["CARD_BORDER"]).lightnessF() < QColor(t["ACCENT"]).lightnessF()

    @ALL
    def test_the_card_shadow_stays_a_shadow(self, key):
        t = schemes.get(key).tokens()
        assert QColor(t["CARD_SHADOW"]).lightnessF() <= 0.10


class TestLookup:
    def test_unknown_scheme_falls_back_to_default(self):
        assert schemes.get("nonsense").key == schemes.DEFAULT_SCHEME

    @pytest.mark.parametrize("value", [None, "", "  "])
    def test_empty_scheme_falls_back(self, value):
        assert schemes.get(value).key == schemes.DEFAULT_SCHEME

    def test_lookup_is_case_insensitive(self):
        assert schemes.get("CYBER").key == "cyber"

    def test_keys_are_unique(self):
        assert len(schemes.keys()) == len(set(schemes.keys()))


class TestAccentOverride:
    def test_override_replaces_the_accent(self):
        assert schemes.colour_tokens("cyber", "#FF8800")["ACCENT"] == "#ff8800"

    def test_override_propagates_to_derived_tokens(self):
        base = schemes.colour_tokens("cyber")
        custom = schemes.colour_tokens("cyber", "#FF8800")
        assert custom["ACCENT_SOFT"] != base["ACCENT_SOFT"]

    @pytest.mark.parametrize("bad", ["not-a-colour", "#12", "", None])
    def test_invalid_override_is_ignored(self, bad):
        # settings.json is hand-editable; a typo should cost the custom accent,
        # not the whole app.
        assert schemes.colour_tokens("cyber", bad)["ACCENT"] == "#22d3ee"

    def test_named_colours_are_accepted(self):
        assert schemes.colour_tokens("cyber", "orange")["ACCENT"] == "#ffa500"
