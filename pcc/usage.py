"""Derived usage state: frecency, per-app affinity, and slot memory.

Deliberately a *separate* file from ``templates.json``. That file is hand-edited
and often git-tracked; usage counts churn on every paste and would poison its
diffs. This one lives beside the settings in ``%APPDATA%\\PCC`` and is disposable
-- losing it costs a little ranking quality and nothing else, so every read and
write degrades to "empty" rather than raising.

The clock is injected (``now``) so the decay maths can be tested without waiting
fourteen days, and so nothing here calls ``datetime.now`` on the hot path more
than once per event.

**Frecency in O(1), no event log.** Each use folds into a single decayed float::

    score := score * 0.5 ** (Δt / HALF_LIFE) + 1

which is exactly the sum over every past use weighted by age -- the whole history
in one number, no list to grow or trim.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

#: A use is worth half as much after this long. Two weeks makes "what I've been
#: doing lately" win without erasing a tool I reach for monthly.
HALF_LIFE_S = 14 * 24 * 3600

#: The ranking bonus is capped here so frecency can only ever break ties, never
#: overturn a title-prefix match (100) -- see :mod:`pcc.search`.
MAX_BONUS = 6.0
#: Of that budget, at most this much may come from same-app affinity.
MAX_APP_BONUS = 2.0

#: Slot values never remembered: they carry pasted code, errors, secrets. The
#: first time someone fills ``{{code}}`` with an API key, it must not land in a
#: JSON file on disk forever. Mirrors ``ui.fill.PREFILL_SLOTS`` by intent, kept
#: independent so core does not import UI.
NO_MEMORY_SLOTS = frozenset(
    {"code", "text", "error", "input", "content", "snippet", "log", "body", "diff",
     "password", "secret", "token", "key", "apikey"}
)
#: A remembered value longer than this is almost certainly prose or a paste, not
#: the short "Python"/"formal" answer slot memory is for.
MAX_MEMORY_LEN = 80


def _parse(iso: str | None) -> _dt.datetime | None:
    if not iso:
        return None
    try:
        return _dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


@dataclass
class UsageStore:
    """Frecency, per-app affinity and slot memory, persisted as one small JSON."""

    path: Path
    now: Callable[[], _dt.datetime] = field(default_factory=lambda: _dt.datetime.now)
    _templates: dict = field(default_factory=dict)
    _pages: dict = field(default_factory=dict)
    _slots: dict = field(default_factory=dict)
    _dirty: bool = False

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._load()

    # --- persistence --------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # Missing or corrupt: start empty, and do NOT preserve a `.corrupt`
            # copy the way the library does. This data is throwaway.
            return
        if not isinstance(raw, dict):
            return
        self._templates = raw.get("templates", {}) if isinstance(raw.get("templates"), dict) else {}
        self._pages = raw.get("pages", {}) if isinstance(raw.get("pages"), dict) else {}
        self._slots = raw.get("slots", {}) if isinstance(raw.get("slots"), dict) else {}

    def flush(self) -> None:
        """Write if anything changed. Silent on failure -- usage is not precious."""
        if not self._dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(
                    {"templates": self._templates, "pages": self._pages, "slots": self._slots}
                ),
                encoding="utf-8",
            )
            tmp.replace(self.path)
            self._dirty = False
        except OSError:
            pass

    # --- decay --------------------------------------------------------------

    def _decayed(self, score: float, last: str | None, now: _dt.datetime) -> float:
        when = _parse(last)
        if when is None:
            return 0.0
        elapsed = (now - when).total_seconds()
        if elapsed <= 0:
            return float(score)
        return float(score) * 0.5 ** (elapsed / HALF_LIFE_S)

    # --- recording ----------------------------------------------------------

    def record_use(self, template_id: str, app: str | None = None) -> None:
        if not template_id:
            return
        now = self.now()
        stamp = now.isoformat()
        entry = self._templates.setdefault(template_id, {"score": 0.0, "last": None, "apps": {}})
        entry["score"] = self._decayed(entry.get("score", 0.0), entry.get("last"), now) + 1.0
        entry["last"] = stamp
        if app:
            apps = entry.setdefault("apps", {})
            prior = apps.get(app, {})
            apps[app] = {
                "score": self._decayed(prior.get("score", 0.0), prior.get("last"), now) + 1.0,
                "last": stamp,
            }
        self._dirty = True

    def record_page(self, name: str) -> None:
        self._pages[name] = int(self._pages.get(name, 0)) + 1
        self._dirty = True

    def record_slot(self, template_id: str, slot: str, value: str) -> None:
        """Remember a short, non-sensitive slot answer for next time."""
        value = (value or "").strip()
        if not template_id or not value:
            return
        if slot.lower() in NO_MEMORY_SLOTS or len(value) > MAX_MEMORY_LEN or "\n" in value:
            return
        self._slots[f"{template_id}\x00{slot}"] = value
        self._dirty = True

    # --- reading ------------------------------------------------------------

    def frecency(self, template_id: str) -> float:
        entry = self._templates.get(template_id)
        if not entry:
            return 0.0
        return self._decayed(entry.get("score", 0.0), entry.get("last"), self.now())

    def page_count(self, name: str) -> int:
        return int(self._pages.get(name, 0))

    def slot_value(self, template_id: str, slot: str) -> str | None:
        return self._slots.get(f"{template_id}\x00{slot}")

    def bonus(self, template_id: str, app: str | None = None) -> float:
        """Ranking bonus in ``[0, MAX_BONUS]``: frecency, plus same-app affinity.

        Capped hard, because a launcher whose ranking can be overturned by
        habit stops being predictable. This only ever breaks ties.
        """
        now = self.now()
        entry = self._templates.get(template_id)
        if not entry:
            return 0.0
        base = min(MAX_BONUS, self._decayed(entry.get("score", 0.0), entry.get("last"), now))
        if app:
            app_entry = entry.get("apps", {}).get(app)
            if app_entry:
                affinity = self._decayed(app_entry.get("score", 0.0), app_entry.get("last"), now)
                base = min(MAX_BONUS, base + min(MAX_APP_BONUS, affinity))
        return base

    def bonus_fn(self, app: str | None = None) -> Callable[[str], float]:
        """A ``template_id -> bonus`` closure for :func:`pcc.search.search`."""
        return lambda template_id: self.bonus(template_id, app)

    def most_frecent(self, template_ids: list[str]) -> str | None:
        """The id with the highest current frecency, or ``None`` if all cold.

        Stable: ties keep the given order, so a screen of never-used templates
        pre-selects the first exactly as before.
        """
        best_id, best_score = None, 0.0
        for template_id in template_ids:
            score = self.frecency(template_id)
            if score > best_score:
                best_id, best_score = template_id, score
        return best_id
