"""Context resolvers: the magic behind ``{{clipboard}}``, ``{{date}}`` and kin.

A *magic slot* is a placeholder whose name is a known context source rather than
a fill-in the user types. ``{{clipboard}}`` becomes whatever you last copied,
``{{app}}`` the executable you summoned PCC over, ``{{date}}`` today.

The whole feature is one function injected into :func:`pcc.model.render`: a
``resolve(name) -> str | None`` closure. ``model`` stays free of Qt and Win32 --
the promise that keeps it headlessly testable -- because the closure is built
*here* and passed in, and this module is the one place allowed to touch
:mod:`pcc.winapi`.

The slow-path contract is deliberately built in from day one, even though every
resolver today is instant. A :class:`Resolved` may report ``pending``; a
pending value renders to the literal token, exactly like an unavailable one, and
the paste path never blocks. An LLM-backed slot later is just a resolver that
stays pending for 900 ms -- no structural change needed then.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Callable

from . import winapi


@dataclass
class ResolveEnv:
    """Everything a resolver may read, captured at trigger time.

    Captured rather than read live so a resolver is a pure function of this
    snapshot: the target window has moved on by the time the user picks a
    template, and tests can supply the whole world without a real desktop.
    """

    target_hwnd: int = 0
    #: Clipboard text at trigger time. ``None`` means "read it live"; a string
    #: (including "") means "use exactly this", which is what lets tests and the
    #: selection-capture path (wave 5) override it.
    clipboard: str | None = None
    #: Selection captured from the target app. Reserved for wave 5; until then it
    #: stays ``None`` and ``{{selection}}`` resolves to the literal token.
    selection: str | None = None
    now: _dt.datetime | None = None

    def _clipboard(self) -> str:
        if self.clipboard is not None:
            return self.clipboard
        return winapi.clipboard_get_text() or ""

    def _now(self) -> _dt.datetime:
        return self.now or _dt.datetime.now()


@dataclass(frozen=True)
class Resolved:
    """A resolver's answer.

    ``value`` is ``None`` when the source has nothing (empty clipboard, unknown
    window); ``pending`` marks a slow source still working. Both render to the
    literal token, so an unresolved magic slot degrades to precisely what an
    unfilled ordinary slot does today.
    """

    value: str | None
    pending: bool = False

    @property
    def available(self) -> bool:
        return self.value is not None and not self.pending


# --- The registry -----------------------------------------------------------
#
# Each entry maps a magic name to a pure function of the env. Adding a source is
# one line here; nothing else in the app needs to know the name exists.

Resolver = Callable[[ResolveEnv], Resolved]


def _some(text: str | None) -> Resolved:
    """Wrap a plain string: empty or ``None`` becomes an unavailable Resolved."""
    return Resolved(text if text else None)


RESOLVERS: dict[str, Resolver] = {
    "clipboard": lambda env: _some(env._clipboard()),
    "selection": lambda env: _some(env.selection),
    "date": lambda env: _some(env._now().strftime("%Y-%m-%d")),
    "time": lambda env: _some(env._now().strftime("%H:%M")),
    "datetime": lambda env: _some(env._now().strftime("%Y-%m-%d %H:%M")),
    "app": lambda env: _some(winapi.process_name(env.target_hwnd)),
    "window": lambda env: _some(winapi.window_title(env.target_hwnd)),
}

#: Human labels for the fill panel's CONTEXT strip. A magic slot injects text the
#: user did not type, so it must be *shown*; silent injection is how this feature
#: would lose trust the first time it guessed wrong.
LABELS: dict[str, str] = {
    "clipboard": "clipboard",
    "selection": "selection",
    "date": "today",
    "time": "now",
    "datetime": "now",
    "app": "app",
    "window": "window",
}


def is_magic(name: str) -> bool:
    return name.strip() in RESOLVERS


def resolve(name: str, env: ResolveEnv) -> Resolved:
    """Resolve one magic name against ``env``; unknown names are unavailable."""
    resolver = RESOLVERS.get(name.strip())
    if resolver is None:
        return Resolved(None)
    try:
        return resolver(env)
    except Exception:
        # A resolver must never take down a paste. Treat any failure as "nothing
        # here" and fall through to the literal token.
        return Resolved(None)


def make_resolver(env: ResolveEnv) -> Callable[[str], str | None]:
    """Build the closure :func:`pcc.model.render` calls for each placeholder.

    Returns the resolved text, or ``None`` to mean "not a magic slot / nothing
    available", on which render keeps its literal-token fallback.
    """

    def _resolve(name: str) -> str | None:
        result = resolve(name, env)
        return result.value if result.available else None

    return _resolve


@dataclass
class ContextItem:
    """One resolved magic slot, ready to show in the CONTEXT strip."""

    name: str
    label: str
    value: str | None
    pending: bool = False

    @property
    def available(self) -> bool:
        return self.value is not None and not self.pending

    def summary(self) -> str:
        """A compact, safe one-liner: ``clipboard · 1.2k chars`` / ``app · Code.exe``."""
        if self.pending:
            return f"{self.label} · …"
        if self.value is None:
            return f"{self.label} · —"
        text = self.value
        # Long values (a pasted file, a whole selection) are summarised by size
        # rather than dumped into the strip.
        if len(text) > 42 or "\n" in text:
            chars = len(text)
            size = f"{chars / 1000:.1f}k" if chars >= 1000 else str(chars)
            return f"{self.label} · {size} chars"
        return f"{self.label} · {text}"


def context_items(names: list[str], env: ResolveEnv) -> list[ContextItem]:
    """Resolve ``names`` (already known magic) into display items, order kept."""
    items: list[ContextItem] = []
    for name in names:
        result = resolve(name, env)
        items.append(
            ContextItem(
                name=name,
                label=LABELS.get(name.strip(), name.strip()),
                value=result.value,
                pending=result.pending,
            )
        )
    return items
