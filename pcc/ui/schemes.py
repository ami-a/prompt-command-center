"""Colour schemes.

A scheme is defined by three colours -- background, accent, secondary -- and
everything else is *derived*. Hand-picking eighteen colours per scheme would be
six times the work and would drift out of tune; deriving them means every scheme
shares the same contrast relationships, so a new one is three hex codes rather
than an afternoon of nudging.

Surfaces are lifted toward a desaturated tint of the accent rather than toward
neutral grey, which is what makes panels read as part of the theme instead of as
grey boxes sitting on a coloured background.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def _hsl(hue: float, saturation: float, lightness: float) -> QColor:
    colour = QColor()
    colour.setHslF(max(0.0, min(1.0, hue)), max(0.0, min(1.0, saturation)),
                   max(0.0, min(1.0, lightness)))
    return colour


def _hue_of(colour: QColor) -> float:
    """Hue in 0..1, with grey (-1) normalised to 0."""
    hue = colour.hueF()
    return hue if hue >= 0 else 0.0


def _shift_lightness(colour: QColor, delta: float) -> QColor:
    # hslSaturationF, not saturationF: the latter is HSV saturation, and feeding
    # it back into setHslF quietly desaturates every light colour.
    return _hsl(_hue_of(colour), colour.hslSaturationF(), colour.lightnessF() + delta)


@dataclass(frozen=True)
class Scheme:
    """Three source colours plus a display name."""

    key: str
    name: str
    background: str
    accent: str
    secondary: str

    def tokens(self) -> dict[str, str]:
        """Expand into the colour tokens ``theme.qss`` expects."""
        bg = QColor(self.background)
        accent = QColor(self.accent)
        secondary = QColor(self.secondary)

        hue = _hue_of(accent)
        # Desaturated, light version of the accent. Surfaces lifted toward this
        # inherit a trace of the theme's hue instead of going flat grey.
        tint = _hsl(hue, 0.30, 0.72)

        def surface(amount: float) -> QColor:
            return _mix(bg, tint, amount)

        tile = surface(0.07)
        text = _hsl(hue, 0.22, 0.87)

        return {
            "BG": bg.name(),
            "PREVIEW_BG": surface(0.02).name(),
            "PANEL": surface(0.04).name(),
            "PANEL_FOCUS": surface(0.055).name(),
            "TILE": tile.name(),
            "TILE_HOVER": surface(0.12).name(),
            # Selected rows carry the accent itself, not just more lift.
            "TILE_SELECTED": _mix(tile, accent, 0.06).name(),
            "BORDER": surface(0.155).name(),
            "BORDER_HOVER": surface(0.28).name(),
            # The window's own edge, not an inner one: mixed most of the way to
            # the accent so the palette reads as a distinct object over whatever
            # desktop it was summoned onto, while still being darker than the
            # accent itself and so never competing with the selected tile.
            "CARD_BORDER": _mix(bg, accent, 0.62).name(),
            # The drop shadow behind that edge. Kept dark -- it is a shadow, not
            # a glow -- but carrying the accent's hue, so the halo around the
            # window belongs to the scheme instead of being neutral black.
            "CARD_SHADOW": _hsl(hue, 0.85, 0.04).name(),
            "SCROLL": surface(0.19).name(),
            "SCROLL_HOVER": surface(0.28).name(),
            "ACCENT": accent.name(),
            # Lift toward a *ceiling* rather than by a fixed delta. An accent
            # that is already light (Ice, Void) would otherwise land on
            # near-white and lose the hue that identifies the theme, while
            # saturation is floored so it stays a colour rather than a grey.
            "ACCENT_SOFT": _hsl(
                hue,
                max(0.55, accent.hslSaturationF()),
                min(0.80, accent.lightnessF() + 0.18),
            ).name(),
            "ACCENT_DEEP": _shift_lightness(accent, -0.08).name(),
            # Text drawn *on* the accent (selection highlight) must be dark
            # enough to stay legible whatever the accent's own lightness is.
            "ON_ACCENT": _hsl(hue, 0.80, 0.06).name(),
            "SECONDARY": secondary.name(),
            "TEXT": text.name(),
            # Specified in HSL, not mixed toward the background: mixing drains
            # the chroma and secondary text ends up muddy grey in every theme.
            "MUTED": _hsl(hue, 0.13, 0.55).name(),
            "FAINT": _hsl(hue, 0.12, 0.36).name(),
        }


#: Ordered; the settings panel cycles through these.
SCHEMES: tuple[Scheme, ...] = (
    Scheme("cyber", "Cyber", "#0B0F14", "#22D3EE", "#F472B6"),
    Scheme("synthwave", "Synthwave", "#120B1F", "#FF4D9D", "#7C5CFF"),
    Scheme("matrix", "Matrix", "#060B08", "#3DFF88", "#A6FF4D"),
    Scheme("amber", "Amber", "#120E08", "#FFB020", "#FF6B4A"),
    Scheme("ice", "Ice", "#0A0F16", "#7DD3FC", "#C4B5FD"),
    Scheme("void", "Void", "#0A0A0F", "#A78BFA", "#22D3EE"),
    Scheme("blood", "Blood", "#120809", "#FF4D5E", "#FFB020"),
)

DEFAULT_SCHEME = "cyber"

_BY_KEY = {scheme.key: scheme for scheme in SCHEMES}


def get(key: str | None) -> Scheme:
    """Look up a scheme, falling back to the default rather than failing."""
    return _BY_KEY.get(str(key or "").lower(), _BY_KEY[DEFAULT_SCHEME])


def keys() -> list[str]:
    return [scheme.key for scheme in SCHEMES]


def colour_tokens(key: str | None, accent_override: str | None = None) -> dict[str, str]:
    """Tokens for ``key``, optionally with a custom accent colour.

    An invalid override is ignored rather than raising: settings.json is
    hand-editable, and a typo should cost you the custom accent, not the app.
    """
    scheme = get(key)
    if accent_override:
        candidate = QColor(str(accent_override))
        if candidate.isValid():
            scheme = Scheme(
                scheme.key, scheme.name, scheme.background,
                candidate.name(), scheme.secondary,
            )
    return scheme.tokens()
