"""Spelling marks and the fix menu.

Two ideas carry the whole feature:

* **Tokenise before asking.** A prompt body is not prose -- it is prose threaded
  with ``{{slots}}``, ``` `code` ```, ``snake_case`` and ``pcc/ui/palette.py``.
  Handing the raw text to the system checker underlines all of it. So the text
  is filtered down to things that are actually words first, which both removes
  the false marks and removes almost all of the work.
* **Let QSyntaxHighlighter do the scheduling.** Qt re-runs
  :meth:`SpellHighlighter.highlightBlock` only for the paragraph that changed,
  and stops there while the block state holds. Combined with the word cache in
  :mod:`pcc.spell`, a keystroke costs two regex passes over one paragraph and a
  dict lookup. That is why there is no worker thread and no debounce timer here
  -- both would be machinery bolted onto something already incremental, and both
  would race a window that hides itself the moment it loses focus.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import nullcontext
from weakref import WeakSet

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QMenu

from .. import spell

#: Regions that are never prose, and that may contain spaces.
#:
#: The placeholder rule deliberately swallows only ``{{name`` and not the whole
#: token: the *options* of ``{{tone|professional|friendly}}`` are prose the user
#: wrote and can misspell, while the slot name is an identifier.
_REGION_RE = re.compile(r"\{\{\s*[^}|]*|`[^`]*`")

#: A run of non-space characters -- the unit that is judged opaque or not.
_CHUNK_RE = re.compile(r"\S+")

#: What makes a whole chunk not-a-word: ``pcc/ui/palette.py``,
#: ``store.load_settings``, ``C:\dir``, ``snake_case``, ``v2``, ``a@b.com``.
#:
#: Written to be searched *within* an already-isolated chunk. The obvious
#: spelling -- ``\S*[\d_]\S*`` as one big alternation over the whole text -- is
#: quadratic: the leading ``\S*`` backtracks character by character at every
#: position in the block, which cost ~0.7 ms per keystroke on a long line. This
#: form is linear, and measured 25x faster.
#:
#: Note the trailing ``[A-Za-z0-9]`` in the punctuation rule: without it, the
#: full stop ending a sentence would make an identifier of the word before it.
_OPAQUE_RE = re.compile(r"[\d_]|[A-Za-z0-9][._/\\][A-Za-z0-9]|https?://|www\.|@")

#: Letters only, with internal apostrophes so ``don't`` stays one word.
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")

#: Latin script, accents included. Anything else -- the Hebrew in the seeded
#: templates, Cyrillic, CJK -- is not for an English checker to judge.
_LATIN_RE = re.compile(r"[A-Za-zÀ-ɏ'’]+")

#: Below this, a "misspelling" is almost always a deliberate abbreviation.
MIN_WORD_LEN = 3

#: Blocks longer than this are skipped whole. A 9 000-character paste into a
#: ``{{code}}`` slot would cost ~50 ms to check and would be nonsense anyway.
MAX_BLOCK_LEN = 2000

_IN_FENCE = 1

#: Opacity of the wash behind a misspelled word.
#:
#: The wash is what makes the mark *visible*; the wave is what makes it mean
#: "spelling" rather than "selected". Qt draws the wave a single antialiased
#: pixel high, so roughly half of it is background bleeding through -- against
#: these near-black surfaces that alone is easy to miss, and no amount of
#: brightening fixes it, because the limit is the geometry rather than the
#: colour. Tuned by eye against 0.14 (too timid) and 0.24 (reads as a selection
#: highlight).
WASH_ALPHA = 0.18

_enabled = True
_format = QTextCharFormat()
# WaveUnderline, not SpellCheckUnderline: the latter defers to QPlatformTheme,
# which is free to render it as nothing at all. This one always draws.
_format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)

_highlighters: WeakSet[SpellHighlighter] = WeakSet()


# --- tokenising (pure; no Qt, no COM) ---------------------------------------


def _skip_spans(text: str) -> list[tuple[int, int]]:
    """The stretches of ``text`` that are not prose, merged and in order.

    Three linear passes -- regions, chunks, words -- rather than one regex doing
    all of it, because the one-regex version has to backtrack.
    """
    spans = [match.span() for match in _REGION_RE.finditer(text)]
    spans += [
        match.span() for match in _CHUNK_RE.finditer(text)
        if _OPAQUE_RE.search(match.group())
    ]
    spans.sort()

    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def candidates(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(offset, word)`` for every token worth asking the checker about.

    The skip spans and the word matches both arrive in increasing order, so they
    are consumed with a single moving index rather than re-scanned per word.
    """
    spans = _skip_spans(text)
    index = 0
    for match in _WORD_RE.finditer(text):
        start, end = match.span()
        while index < len(spans) and spans[index][1] <= start:
            index += 1
        if index < len(spans) and spans[index][0] < end:
            continue

        word = match.group()
        if len(word) < MIN_WORD_LEN:
            continue
        if word.isupper():                          # API, JSON, SQL
            continue
        if word[1:] != word[1:].lower():            # camelCase, PascalCase
            continue
        if not _LATIN_RE.fullmatch(word):
            continue
        yield start, word


def misspellings(text: str) -> Iterator[tuple[int, str]]:
    """The candidates the checker rejects."""
    for start, word in candidates(text):
        if not spell.is_correct(word):
            yield start, word


# --- marks ------------------------------------------------------------------


class SpellHighlighter(QSyntaxHighlighter):
    """Wavy underlines under misspelled words, one paragraph at a time."""

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt naming)
        # A ``` fence spans blocks, which is exactly what the block state
        # mechanism is for -- and the one place a change here legitimately
        # propagates rehighlighting to the blocks below.
        inside = self.previousBlockState() == _IN_FENCE
        if text.lstrip().startswith("```"):
            self.setCurrentBlockState(0 if inside else _IN_FENCE)
            return
        self.setCurrentBlockState(_IN_FENCE if inside else 0)

        if inside or not _enabled or len(text) > MAX_BLOCK_LEN:
            return
        # No ``spell.available()`` guard on purpose. It would build the COM
        # checker here -- during widget construction, for a document that is
        # still empty -- instead of during the palette's prewarm where the cost
        # was budgeted for. ``is_correct`` answers True without one, so a
        # machine with no checker simply gets no marks.
        for start, word in misspellings(text):
            self.setFormat(start, len(word), _format)


def attach(edit) -> SpellHighlighter:
    """Give ``edit`` spelling marks, and a right-click menu to fix them.

    The highlighter is kept on the widget so its Python wrapper lives exactly as
    long as the C++ object does -- slot fields are rebuilt on every fill, and a
    dangling wrapper would blow up the next :func:`refresh_all`.
    """
    existing = getattr(edit, "spell_highlighter", None)
    if existing is not None:
        return existing

    highlighter = SpellHighlighter(edit.document())
    edit.spell_highlighter = highlighter
    _highlighters.add(highlighter)

    edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    edit.customContextMenuRequested.connect(
        lambda point, widget=edit: context_menu(widget, point)
    )
    return highlighter


def set_enabled(on: bool) -> None:
    global _enabled
    if bool(on) == _enabled:
        return
    _enabled = bool(on)
    refresh_all()


def set_colour(colour: str) -> None:
    """Tint the mark. Called whenever the scheme changes."""
    value = QColor(colour)
    if not value.isValid() or value == _format.underlineColor():
        return
    _format.setUnderlineColor(value)
    wash = QColor(value)
    wash.setAlphaF(WASH_ALPHA)
    _format.setBackground(wash)
    refresh_all()


def refresh_all() -> None:
    """Re-mark every live editor. Cheap: there are at most a handful."""
    for highlighter in list(_highlighters):
        try:
            highlighter.rehighlight()
        except RuntimeError:
            # The underlying document went away between the WeakSet snapshot and
            # here; the wrapper will be collected on its own.
            pass


# --- fixing -----------------------------------------------------------------


def word_at(edit, cursor: QTextCursor) -> tuple[int, str] | None:
    """The checkable word under ``cursor``, as ``(document position, word)``.

    Uses the same tokeniser as the marks rather than Qt's ``WordUnderCursor``,
    so what the menu offers to fix is exactly what got underlined -- Qt would
    split ``don't`` in two.
    """
    block = cursor.block()
    offset = cursor.position() - block.position()
    for start, word in candidates(block.text()):
        # Inclusive at both ends: the caret sits *after* the word you just typed.
        if start <= offset <= start + len(word):
            return block.position() + start, word
    return None


def _replace(edit, position: int, word: str, replacement: str) -> None:
    """Swap one word, as a single undo step."""
    cursor = edit.textCursor()
    cursor.setPosition(position)
    cursor.setPosition(position + len(word), QTextCursor.MoveMode.KeepAnchor)
    if cursor.selectedText() != word:
        return  # the text moved under us; better to do nothing than to corrupt it
    cursor.beginEditBlock()
    cursor.insertText(replacement)
    cursor.endEditBlock()
    edit.setTextCursor(cursor)


def _show_menu(menu: QMenu, origin) -> None:
    """Enter the menu's modal loop.

    A function of its own so the tests can drive a real, fully built menu
    without blocking on it -- ``QMenu.exec`` itself cannot be patched, PySide6
    types being closed.
    """
    menu.exec(origin)


def _show_guarded(edit, menu: QMenu, origin) -> None:
    """Show ``menu`` without the palette hiding itself underneath it.

    The guard is the same one the rename and delete prompts use, found by name
    rather than imported -- which keeps this module free of any dependency back
    on the palette. ``nullcontext`` covers a widget tested on its own.
    """
    guard = getattr(edit.window(), "modal_guard", None)
    with (guard() if guard is not None else nullcontext()):
        _show_menu(menu, origin)


def _misspelling_at(edit, cursor: QTextCursor) -> tuple[int, str] | None:
    """The *wrong* word at ``cursor``, or ``None`` if there is nothing to fix."""
    if not _enabled or not spell.available():
        return None
    located = word_at(edit, cursor)
    if located is None or spell.is_correct(located[1]):
        return None
    return located


def populate_fixes(menu: QMenu, edit, position: int, word: str, before=None):
    """Add the entries that fix ``word`` to ``menu``.

    ``before`` inserts them ahead of an existing action instead of appending,
    which is how they reach the top of a standard context menu. Returns the
    best suggestion's action, or ``None`` when the checker had none.
    """
    def place(action: QAction) -> QAction:
        if before is None:
            menu.addAction(action)
        else:
            menu.insertAction(before, action)
        return action

    def separator() -> None:
        place(QAction(menu)).setSeparator(True)

    place(QAction(word, menu)).setEnabled(False)
    separator()

    best = None
    for option in spell.suggest(word):
        action = place(QAction(option, menu))
        action.triggered.connect(
            lambda _checked=False, o=option: _replace(edit, position, word, o)
        )
        best = best or action
    if best is None:
        place(QAction("no suggestions", menu)).setEnabled(False)

    separator()
    place(QAction("Ignore", menu)).triggered.connect(
        lambda: (spell.ignore(word), refresh_all())
    )
    place(QAction("Add to dictionary", menu)).triggered.connect(
        lambda: (spell.add(word), refresh_all())
    )
    if before is not None:
        separator()
    return best


def open_suggestions(edit, point=None) -> bool:
    """Offer fixes for the misspelled word at ``point`` (or at the caret).

    Returns whether a menu was shown, so a key handler can fall through when
    there is nothing to fix.
    """
    cursor = edit.cursorForPosition(point) if point is not None else edit.textCursor()
    located = _misspelling_at(edit, cursor)
    if located is None:
        return False
    position, word = located

    if point is not None:
        origin = edit.viewport().mapToGlobal(point)
    else:
        # Under the word, where a fix menu belongs.
        anchor = edit.textCursor()
        anchor.setPosition(position)
        origin = edit.viewport().mapToGlobal(edit.cursorRect(anchor).bottomLeft())

    menu = QMenu(edit)
    best = populate_fixes(menu, edit, position, word)
    if best is not None:
        # Ctrl+. then Enter takes the best fix without moving a finger further.
        menu.setActiveAction(best)
    _show_guarded(edit, menu, origin)
    return True


def context_menu(edit, point) -> None:
    """The right-click menu: the usual one, with any fixes on top.

    Prepending rather than replacing matters -- a right-click on correctly
    spelled text must still offer Cut, Copy, Paste and Undo, which is what
    switching the widget to a custom context menu policy would otherwise cost.
    """
    menu = edit.createStandardContextMenu()
    located = _misspelling_at(edit, edit.cursorForPosition(point))
    if located is not None:
        existing = menu.actions()
        populate_fixes(menu, edit, *located, before=existing[0] if existing else None)
    _show_guarded(edit, menu, edit.viewport().mapToGlobal(point))
