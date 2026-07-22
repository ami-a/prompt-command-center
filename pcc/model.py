"""Data model: tabs, templates, and the ``{{name|default}}`` placeholder grammar.

This module is deliberately free of Qt and Win32 imports so it can be unit
tested in isolation and reused headlessly.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Callable, Iterator

# {{ name | tail }} -- name may not contain '|' or '}'; the tail may not contain
# '}'. Both sides are whitespace-trimmed. A missing '|' yields None for the
# tail, which is what distinguishes "no default" from "empty default".
PLACEHOLDER_RE = re.compile(r"\{\{\s*([^}|]+?)\s*(?:\|\s*([^}]*?)\s*)?\}\}")

#: The tail splits into options on every *unescaped* pipe, so a default that
#: genuinely contains one can still be written as ``\|``.
_OPTION_SPLIT_RE = re.compile(r"(?<!\\)\|")

MAX_TITLE_LEN = 120

#: ``{{>name}}`` inlines another template's body. Guarded so a template that
#: includes itself (directly or in a ring) produces a visible marker instead of
#: recursing forever -- the same "fail loudly, never hang" stance the store
#: takes on a corrupt file.
INCLUDE_PREFIX = ">"
MAX_INCLUDE_DEPTH = 4

#: Templates carrying this tag are *modifiers*: short fragments ("Be concise.")
#: meant to be appended to a base prompt rather than used alone. See
#: :mod:`pcc.compose`.
MODIFIER_TAG = "modifier"

#: ``{{^}}`` marks where the caret should land after pasting, so a template can
#: end with a scaffold you finish typing in place. It is not a fill-in slot.
CARET_NAME = "^"
CARET_TOKEN = "{{^}}"


def _split_tail(tail: str | None) -> tuple[str | None, tuple[str, ...]]:
    """Split a placeholder's tail into ``(default, options)``.

    One part is a plain default (``{{lang|Python}}``); two or more make the slot
    a choice (``{{lang|Python|Go|Rust}}``) whose first option is also its
    default. Writing the first part empty (``{{lang||Go|Rust}}``) offers the
    options without preselecting one.
    """
    if tail is None:
        return None, ()
    parts = [part.strip().replace("\\|", "|") for part in _OPTION_SPLIT_RE.split(tail)]
    if len(parts) == 1:
        # "" stays "" rather than becoming None: an explicitly empty default is
        # a different statement from no default at all.
        return parts[0], ()
    return parts[0] or None, tuple(part for part in parts if part)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass(frozen=True)
class Slot:
    """One distinct fill-in position in a template body.

    Repeated occurrences of the same ``name`` collapse into a single Slot, so
    the fill panel shows one input that drives every occurrence.

    ``options`` is non-empty only for a choice slot, and never removes the
    ability to type something else: the offered values are shortcuts, not a
    closed set.
    """

    name: str
    default: str | None = None
    options: tuple[str, ...] = ()

    @property
    def token(self) -> str:
        """The literal text to emit when the slot is left empty and has no default."""
        return "{{" + self.name + "}}"

    @property
    def has_options(self) -> bool:
        return bool(self.options)

    @property
    def placeholder_hint(self) -> str:
        # A choice slot's field is the *custom* answer, so hinting it with the
        # default would suggest typing what a chip already offers.
        if self.options:
            return "something else…"
        return self.default if self.default else self.name


def parse_slots(body: str) -> list[Slot]:
    """Return the distinct slots of ``body`` in first-appearance order.

    When the same name appears more than once, the first occurrence that
    carries a default or options wins; this lets you write the choices once and
    refer to the slot bare afterwards.
    """
    def specified(slot: Slot) -> bool:
        return slot.default is not None or bool(slot.options)

    slots: dict[str, Slot] = {}
    for match in PLACEHOLDER_RE.finditer(body):
        name = match.group(1).strip()
        if not name or name.startswith(INCLUDE_PREFIX) or name == CARET_NAME:
            # Neither an include nor the caret marker is a fill-in: the include
            # contributes its own slots once expanded (render handles that), and
            # {{^}} is a paste-time cursor hint, not a field.
            continue
        candidate = Slot(name, *_split_tail(match.group(2)))
        existing = slots.get(name)
        if existing is None or (not specified(existing) and specified(candidate)):
            slots[name] = candidate
    return list(slots.values())


def readable(body: str) -> str:
    """Collapse a body to flowing prose for display.

    Placeholders become their default -- the first option, for a choice slot --
    or their bare name when they have none, so a tile reads like the sentence it
    will produce instead of a wall of ``{{braces}}``. Never use this for
    pasting -- see :func:`render`.
    """

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if name.startswith(INCLUDE_PREFIX):
            # No library to resolve against here; show the referenced name as a
            # word so the tile reads sensibly.
            return name[len(INCLUDE_PREFIX):].strip()
        default, _ = _split_tail(match.group(2))
        return default if default else name

    return " ".join(PLACEHOLDER_RE.sub(substitute, body).split())


def _expand_include(
    name: str,
    values: dict[str, str],
    resolve: "Callable[[str], str | None] | None",
    lookup: "Callable[[str], str | None] | None",
    seen: tuple[str, ...],
) -> str:
    """Resolve a ``{{>ref}}`` include, or a visible marker if it can't be.

    Every failure is surfaced rather than swallowed: an unknown ref, a cycle, or
    too-deep nesting each leave a ``{{>marker}}`` in the output so the author can
    see exactly what went wrong instead of getting silently truncated text.
    """
    ref = name[len(INCLUDE_PREFIX):].strip()
    if not ref or lookup is None:
        return "{{" + name + "}}"
    if ref in seen:
        return "{{>cycle: " + ref + "}}"
    if len(seen) >= MAX_INCLUDE_DEPTH:
        return "{{>too deep: " + ref + "}}"
    included = lookup(ref)
    if included is None:
        return "{{>missing: " + ref + "}}"
    return render(included, values, resolve, lookup, _seen=seen + (ref,))


def expand_includes(
    body: str,
    lookup: "Callable[[str], str | None] | None",
    _seen: tuple[str, ...] = (),
) -> str:
    """Inline ``{{>ref}}`` includes, leaving every other placeholder untouched.

    A *structural* pass, run before slot parsing: it resolves the composition of
    templates (which needs the library) while keeping ``{{slot}}`` and magic
    tokens byte-identical, so the fill panel still sees and collects the slots
    that live inside an included body. Value rendering happens afterwards.
    """

    def sub(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if not name.startswith(INCLUDE_PREFIX):
            return match.group(0)
        ref = name[len(INCLUDE_PREFIX):].strip()
        if not ref or lookup is None:
            return match.group(0)
        if ref in _seen:
            return "{{>cycle: " + ref + "}}"
        if len(_seen) >= MAX_INCLUDE_DEPTH:
            return "{{>too deep: " + ref + "}}"
        included = lookup(ref)
        if included is None:
            return "{{>missing: " + ref + "}}"
        return expand_includes(included, lookup, _seen + (ref,))

    return PLACEHOLDER_RE.sub(sub, body)


def render(
    body: str,
    values: dict[str, str] | None = None,
    resolve: "Callable[[str], str | None] | None" = None,
    lookup: "Callable[[str], str | None] | None" = None,
    _seen: tuple[str, ...] = (),
) -> str:
    """Substitute ``values`` into ``body``.

    Resolution order per placeholder:

    1. a non-empty user value,
    2. the placeholder's own default -- the first option, for a choice slot,
    3. an injected ``resolve(name)`` (magic slots: clipboard, date, app, ...),
    4. the literal ``{{name}}`` token.

    ``resolve`` is optional and injected rather than imported, so this module
    stays free of Qt and Win32 (see :mod:`pcc.context`). It comes *after* the
    default deliberately: a hand-written ``{{date|2024-01}}`` keeps its default,
    and nothing anyone already wrote changes meaning.

    Step 4 is the deliberate "nothing is silently lost" behaviour: an unfilled
    slot with no default -- or a magic slot whose source is empty -- stays
    visible in the pasted text so it can be finished in the destination app.
    """
    values = values or {}

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if not name:
            return match.group(0)
        if name.startswith(INCLUDE_PREFIX):
            return _expand_include(name, values, resolve, lookup, _seen)
        value = values.get(name, "").strip()
        if value:
            return value
        default, _ = _split_tail(match.group(2))
        if default:
            return default
        if resolve is not None:
            resolved = resolve(name)
            if resolved:
                return resolved
        return "{{" + name + "}}"

    return PLACEHOLDER_RE.sub(substitute, body)


def extract_caret(text: str) -> tuple[str, int]:
    """Split a ``{{^}}`` marker out of rendered text.

    Returns ``(clean_text, left_moves)`` where ``left_moves`` is how many
    characters sit after the marker -- i.e. how many Left arrows to tap after
    pasting so the caret lands where ``{{^}}`` was. Only the first marker counts;
    any others are removed too so they never paste literally. No marker yields
    ``(text, 0)``.
    """
    index = text.find(CARET_TOKEN)
    if index < 0:
        return text, 0
    clean = text.replace(CARET_TOKEN, "")
    left_moves = len(clean) - index
    return clean, left_moves


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

    @property
    def is_modifier(self) -> bool:
        """A short fragment meant to be appended to a base prompt, not used alone."""
        return any(tag.lower() == MODIFIER_TAG for tag in self.tags)

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
