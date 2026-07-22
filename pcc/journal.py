"""An in-session undo ring for destructive library edits.

Confirmation dialogs are a poor guard: they interrupt every delete to catch the
rare mistake, and people learn to dismiss them without reading. Undo is both
faster (no prompt on the common, correct case) and safer (it also recovers the
delete you *meant*, then regretted). So the palette deletes immediately and
banks a snapshot here.

Snapshots are whole-library ``to_dict`` dicts. That is coarse, but a library is
small and correctness beats cleverness: restoring a snapshot cannot leave a
half-applied edit the way replaying an inverse operation might.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field


@dataclass
class UndoJournal:
    """A bounded stack of ``(library_dict, label)`` snapshots, newest last."""

    limit: int = 20
    _stack: list[tuple[dict, str]] = field(default_factory=list)

    def record(self, library_dict: dict, label: str) -> None:
        """Snapshot the library *before* a destructive change, tagged ``label``."""
        self._stack.append((copy.deepcopy(library_dict), label))
        if len(self._stack) > self.limit:
            # Drop the oldest; the deep past is not worth unbounded memory.
            del self._stack[0 : len(self._stack) - self.limit]

    @property
    def can_undo(self) -> bool:
        return bool(self._stack)

    @property
    def next_label(self) -> str | None:
        return self._stack[-1][1] if self._stack else None

    def undo(self) -> tuple[dict, str] | None:
        """Pop and return the most recent ``(library_dict, label)``, or ``None``."""
        if not self._stack:
            return None
        return self._stack.pop()

    def __len__(self) -> int:
        return len(self._stack)
