"""Builds the stylesheet from user settings.

``theme.qss`` is a :class:`string.Template`: colours stay fixed, but every font
family and size is a ``$placeholder`` resolved here. ``string.Template`` is used
rather than ``str.format`` because QSS is full of literal ``{`` and ``}``, which
``format`` would try to interpret.

Sizes derive from a single ``font_size`` so the palette rescales coherently
instead of needing a dozen numbers kept in sync by hand.
"""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from . import schemes

QSS_PATH = Path(__file__).with_name("theme.qss")

#: Clamped so a typo in settings.json cannot produce an unusable window.
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 28


def _quote_families(families: str) -> str:
    """Turn ``Cascadia Code, Consolas`` into a QSS-safe quoted list.

    Family names containing spaces must be quoted in QSS or the declaration is
    dropped silently and Qt falls back to the default font.
    """
    names = [name.strip().strip("'\"") for name in str(families).split(",")]
    quoted = [f'"{name}"' if " " in name else name for name in names if name]
    return ", ".join(quoted) or "monospace"


#: Ratios rather than fixed offsets. At the default base of 13 these reproduce
#: the hand-tuned 12/11/10/14 scale exactly, but they keep the hierarchy
#: readable when scaled up -- base-3 would collapse 20px into a flat 20/19/18/17.
_SCALE = {
    "FS_BASE": 1.00,    # search box, tile titles
    "FS_SMALL": 0.92,   # tabs, fields, buttons, menus
    "FS_BODY": 0.85,    # tile body, preview
    "FS_TINY": 0.77,    # hints, badges, labels
    "FS_TITLE": 1.08,   # panel headings
}

#: Anything smaller stops being legible regardless of what the ratio produces.
MIN_DERIVED_SIZE = 7


def font_metrics(settings: dict[str, Any]) -> dict[str, int]:
    """The derived size scale, exposed separately so tests can assert on it."""
    try:
        base = int(settings.get("font_size", 13))
    except (TypeError, ValueError):
        base = 13
    base = max(MIN_FONT_SIZE, min(base, MAX_FONT_SIZE))

    return {
        name: max(MIN_DERIVED_SIZE, round(base * ratio))
        for name, ratio in _SCALE.items()
    }


def build_stylesheet(settings: dict[str, Any]) -> str:
    """Resolve ``theme.qss`` against ``settings``."""
    ui_family = _quote_families(
        settings.get("font_family", "Cascadia Code, Consolas, monospace")
    )
    # The body/preview font can go proportional: prompt text is prose, and prose
    # is easier to skim in a proportional face than in a monospace one.
    if settings.get("mono_preview", True):
        body_family = ui_family
    else:
        body_family = _quote_families(
            settings.get("preview_font_family", "Segoe UI, sans-serif")
        )

    values: dict[str, Any] = {
        "FONT_FAMILY": ui_family,
        "BODY_FONT_FAMILY": body_family,
        **font_metrics(settings),
        **schemes.colour_tokens(settings.get("scheme"), settings.get("accent")),
    }
    return Template(QSS_PATH.read_text(encoding="utf-8")).substitute(values)
