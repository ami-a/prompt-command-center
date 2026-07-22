"""Data model: tabs, templates, and the ``{{name|default}}`` placeholder grammar.

This module is deliberately free of Qt and Win32 imports so it can be unit
tested in isolation and reused headlessly.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Iterator

# {{ name | default }} -- name may not contain '|' or '}'; default may not
# contain '}'. Both sides are whitespace-trimmed. A missing '|' yields None for
# the default, which is what distinguishes "no default" from "empty default".
PLACEHOLDER_RE = re.compile(r"\{\{\s*([^}|]+?)\s*(?:\|\s*([^}]*?)\s*)?\}\}")

MAX_TITLE_LEN = 120


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass(frozen=True)
class Slot:
    """One distinct fill-in position in a template body.

    Repeated occurrences of the same ``name`` collapse into a single Slot, so
    the fill panel shows one input that drives every occurrence.
    """

    name: str
    default: str | None = None

    @property
    def token(self) -> str:
        """The literal text to emit when the slot is left empty and has no default."""
        return "{{" + self.name + "}}"

    @property
    def placeholder_hint(self) -> str:
        return self.default if self.default else self.name


def parse_slots(body: str) -> list[Slot]:
    """Return the distinct slots of ``body`` in first-appearance order.

    When the same name appears more than once, the first occurrence that
    carries a default wins; this lets you write the default once and refer to
    the slot bare afterwards.
    """
    slots: dict[str, Slot] = {}
    for match in PLACEHOLDER_RE.finditer(body):
        name = match.group(1).strip()
        if not name:
            continue
        default = match.group(2)
        existing = slots.get(name)
        if existing is None:
            slots[name] = Slot(name, default)
        elif existing.default is None and default is not None:
            slots[name] = Slot(name, default)
    return list(slots.values())


def readable(body: str) -> str:
    """Collapse a body to flowing prose for display.

    Placeholders become their default, or their bare name when they have none,
    so a tile reads like the sentence it will produce instead of a wall of
    ``{{braces}}``. Never use this for pasting -- see :func:`render`.
    """

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        default = match.group(2)
        return default if default else name

    return " ".join(PLACEHOLDER_RE.sub(substitute, body).split())


def render(body: str, values: dict[str, str] | None = None) -> str:
    """Substitute ``values`` into ``body``.

    Resolution order per placeholder:

    1. a non-empty user value,
    2. the placeholder's own default,
    3. the literal ``{{name}}`` token.

    Step 3 is the deliberate "nothing is silently lost" behaviour: an unfilled
    slot with no default stays visible in the pasted text so it can be finished
    in the destination app.
    """
    values = values or {}

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if not name:
            return match.group(0)
        value = values.get(name, "").strip()
        if value:
            return value
        default = match.group(2)
        if default:
            return default
        return "{{" + name + "}}"

    return PLACEHOLDER_RE.sub(substitute, body)


@dataclass
class Template:
    title: str
    body: str
    id: str = field(default_factory=lambda: new_id("p"))
    tags: list[str] = field(default_factory=list)

    @property
    def slots(self) -> list[Slot]:
        return parse_slots(self.body)

    @property
    def has_slots(self) -> bool:
        return bool(PLACEHOLDER_RE.search(self.body))

    def preview(self) -> str:
        """Body as readable prose for the tile subtitle.

        Returned unclipped: the tile elides it to whole lines at paint time,
        which a character count cannot do correctly in a proportional layout.
        """
        return readable(self.body)

    def to_dict(self) -> dict:
        data = {"id": self.id, "title": self.title, "body": self.body}
        if self.tags:
            data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Template":
        return cls(
            id=str(data.get("id") or new_id("p")),
            title=str(data.get("title", "")).strip()[:MAX_TITLE_LEN] or "Untitled",
            body=str(data.get("body", "")),
            tags=[str(t) for t in data.get("tags", []) if str(t).strip()],
        )


@dataclass
class Tab:
    name: str
    id: str = field(default_factory=lambda: new_id("t"))
    templates: list[Template] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "templates": [t.to_dict() for t in self.templates],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Tab":
        return cls(
            id=str(data.get("id") or new_id("t")),
            name=str(data.get("name", "")).strip() or "Untitled",
            templates=[Template.from_dict(t) for t in data.get("templates", [])],
        )


@dataclass
class Library:
    """The whole template collection: an ordered list of tabs."""

    tabs: list[Tab] = field(default_factory=list)
    version: int = 1

    def iter_all(self) -> Iterator[tuple[Tab, Template]]:
        for tab in self.tabs:
            for template in tab.templates:
                yield tab, template

    def find_tab(self, tab_id: str) -> Tab | None:
        return next((t for t in self.tabs if t.id == tab_id), None)

    def locate(self, template_id: str) -> tuple[Tab, int] | None:
        """Return the owning tab and the template's index within it."""
        for tab in self.tabs:
            for index, template in enumerate(tab.templates):
                if template.id == template_id:
                    return tab, index
        return None

    def to_dict(self) -> dict:
        return {"version": self.version, "tabs": [t.to_dict() for t in self.tabs]}

    @classmethod
    def from_dict(cls, data: dict) -> "Library":
        return cls(
            version=int(data.get("version", 1)),
            tabs=[Tab.from_dict(t) for t in data.get("tabs", [])],
        )
