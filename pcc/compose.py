"""Composition: stack templates and layer modifiers into one prompt.

The trick that keeps this tiny and robust is to compose at the *body* level, not
with a new runtime object. Joining a few template bodies with blank lines yields
an ordinary body string, which then flows through the very same
:func:`pcc.model.render`, :func:`pcc.model.parse_slots` and fill panel as any
single template -- including the existing rule that a repeated ``{{name}}``
collapses to one field. So two stacked templates that both use ``{{code}}`` share
one input for free, with no code here to make that happen.

A *modifier* (a template tagged ``modifier``) is a fragment like "Be concise." or
"Answer as a markdown table." Marking a handful and applying them to a base is
what turns N templates into N x M prompts from the same small library.
"""

from __future__ import annotations

from .model import Template

#: Blank line between parts: it reads as paragraph breaks in the destination
#: chat box and never accidentally glues the end of one prompt to the next.
JOIN = "\n\n"


def combined_body(bases: list[Template], modifiers: list[Template]) -> str:
    """Join base bodies then modifier bodies into one prompt body.

    Bases keep their given order (stacking), modifiers follow (so "be concise"
    lands after the instruction it qualifies). Empty bodies are dropped so a
    stray blank template cannot open a paste with whitespace.
    """
    parts = [t.body.strip() for t in bases if t.body.strip()]
    parts += [m.body.strip() for m in modifiers if m.body.strip()]
    return JOIN.join(parts)


def compose(bases: list[Template], modifiers: list[Template]) -> Template | None:
    """A transient :class:`Template` for the joined prompt, or ``None`` if empty.

    Transient by design: it carries a sentinel id and is never stored, so it
    reuses the whole fill/paste path without touching the library.
    """
    body = combined_body(bases, modifiers)
    if not body:
        return None
    if len(bases) == 1 and not modifiers:
        # A single base with no modifiers is just that base -- keep its identity
        # so usage recording and slot recall still key off the real template.
        return bases[0]
    title = bases[0].title if bases else "Composed"
    return Template(title=title, body=body, id="__composed__")
