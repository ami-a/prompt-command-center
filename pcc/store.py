"""Persistence: atomic JSON writes, defaults seeding, and external hot-reload.

Data lives in ``%APPDATA%\\PCC`` by default. ``settings.json`` may point
``library_path`` elsewhere (e.g. a git-tracked folder).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .model import Library, Tab, Template

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "PCC"
SETTINGS_PATH = APP_DIR / "settings.json"
DEFAULT_LIBRARY_PATH = APP_DIR / "templates.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "library_path": None,          # None -> DEFAULT_LIBRARY_PATH
    "margin": 40,                  # px inset from the active monitor's work area
    "window_width": 720,
    "window_height": 520,
    "columns": 3,
    "restore_clipboard": True,
    "restore_clipboard_delay_ms": 300,
    "paste_key": "ctrl+v",         # or "shift+insert" for stubborn terminals

    # Selection capture for {{selection}}. OFF by default: it synthesises Ctrl+C
    # into the app you summoned PCC over, and in a console Ctrl+C is SIGINT, so
    # this must be opt-in. "smart" fires only when a template actually uses
    # {{selection}}; "always" every summon. Consoles are skipped either way.
    "capture_selection": "off",    # off | smart | always

    # Spelling. The checker is the one built into Windows, so there is no
    # dictionary to ship and words you add here are known to every other app.
    "spellcheck": True,
    "spellcheck_language": None,   # None -> your Windows locale, then en-US

    # Appearance. All of this is editable in-app with Ctrl+, -- the panel
    # applies changes live and writes back here on save.
    #
    # Every other size in the theme derives from font_size, and every colour
    # derives from the scheme's three source colours, so these few keys control
    # the entire look.
    "scheme": "cyber",             # see ui/schemes.py: cyber, synthwave, matrix,
                                   # amber, ice, void, blood
    "accent": None,                # optional hex override, e.g. "#FF8800"
    "font_family": "Cascadia Code, JetBrains Mono, Consolas, monospace",
    "font_size": 13,               # px, used for the search box and tile titles
    "mono_preview": True,          # False -> proportional font for body/preview
    "preview_font_family": "Segoe UI, Inter, sans-serif",
}


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a crash can never truncate the real one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_settings(seed: bool = True) -> dict[str, Any]:
    """Load settings, ignoring unknown keys so a typo cannot inject anything.

    On first run the defaults are written out, so the file is discoverable and
    editable instead of being an undocumented secret.
    """
    settings = dict(DEFAULT_SETTINGS)
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            settings.update({k: v for k, v in raw.items() if k in DEFAULT_SETTINGS})
    except FileNotFoundError:
        if seed:
            try:
                save_settings(settings)
            except OSError:
                pass
    except (OSError, json.JSONDecodeError):
        pass
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    _atomic_write(SETTINGS_PATH, json.dumps(settings, indent=2))


def library_path(settings: dict[str, Any] | None = None) -> Path:
    settings = settings or load_settings()
    custom = settings.get("library_path")
    return Path(custom).expanduser() if custom else DEFAULT_LIBRARY_PATH


def default_library() -> Library:
    """Seed content -- also serves as living documentation of the syntax."""
    return Library(
        tabs=[
            Tab(
                name="Coding",
                templates=[
                    Template(
                        title="Refactor for readability",
                        body=(
                            "Refactor the following {{language|Python|TypeScript|Go|Rust|SQL}} "
                            "code for {{goal|readability|performance|testability}}.\n\n"
                            "Keep the public API unchanged, preserve behaviour exactly, "
                            "and explain each change in one line.\n\n"
                            "```\n{{code}}\n```"
                        ),
                    ),
                    Template(
                        title="Explain this code",
                        body=(
                            "Explain what this code does, step by step, for a "
                            "{{audience|senior engineer|junior developer|"
                            "non-programmer}}.\n\n"
                            "Call out any bug, race condition, or edge case you notice.\n\n"
                            "```\n{{code}}\n```"
                        ),
                    ),
                    Template(
                        title="Write tests",
                        body=(
                            "Write {{framework|pytest|unittest|vitest|jest|go test}} "
                            "tests for the code below.\n\n"
                            "Cover the happy path, boundary values, and failure modes. "
                            "No mocks unless a real dependency makes the test slow or "
                            "non-deterministic.\n\n"
                            "```\n{{code}}\n```"
                        ),
                    ),
                    Template(
                        title="Debug this error",
                        body=(
                            "I am getting this error:\n\n```\n{{error}}\n```\n\n"
                            "Relevant code:\n\n```\n{{code}}\n```\n\n"
                            "Identify the root cause before proposing a fix. "
                            "If you need more information, ask instead of guessing."
                        ),
                    ),
                ],
            ),
            Tab(
                name="Writing",
                templates=[
                    Template(
                        title="Tighten this text",
                        body=(
                            "Rewrite the text below to be clearer and shorter without "
                            "losing meaning. Keep the tone "
                            "{{tone|professional|friendly|blunt|academic}}.\n\n"
                            "{{text}}"
                        ),
                    ),
                    Template(
                        title="Summarise",
                        body=(
                            "Summarise the following in "
                            "{{length|five bullet points|one sentence|a short "
                            "paragraph}}. "
                            "Lead with the single most important takeaway.\n\n{{text}}"
                        ),
                    ),
                    Template(
                        title="Translate",
                        body=(
                            "Translate the text below into "
                            "{{target|Hebrew|English|Spanish|French|German}}. "
                            "Preserve formatting and keep proper nouns untranslated.\n\n"
                            "{{text}}"
                        ),
                    ),
                ],
            ),
            Tab(
                name="Thinking",
                templates=[
                    Template(
                        title="Critique my reasoning",
                        body=(
                            "Here is my reasoning:\n\n{{argument}}\n\n"
                            "Attack it. Find the weakest assumption, the missing "
                            "evidence, and the conclusion that does not follow. "
                            "Be specific, not polite."
                        ),
                    ),
                    Template(
                        title="Compare options",
                        body=(
                            "Compare {{option_a}} and {{option_b}} for "
                            "{{use_case}}.\n\n"
                            "Give a table of real trade-offs, then a single "
                            "recommendation with the reason it wins."
                        ),
                    ),
                    Template(
                        title="Ask me questions first",
                        body=(
                            "Before answering, ask me the {{count|three}} questions "
                            "whose answers would most change your response.\n\n"
                            "My request: {{request}}"
                        ),
                    ),
                ],
            ),
        ]
    )


def load_library(path: Path | None = None) -> Library:
    """Load the library, seeding defaults on first run.

    A corrupt file is preserved as ``.corrupt-<ts>`` rather than overwritten, so
    a bad hand-edit never destroys the collection.
    """
    path = path or library_path()
    if not path.exists():
        library = default_library()
        save_library(library, path)
        return library
    try:
        return Library.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        try:
            path.replace(path.with_suffix(f".corrupt-{int(time.time())}.json"))
        except OSError:
            pass
        library = default_library()
        save_library(library, path)
        return library


#: How many rotating on-disk copies of the library to keep. Cheap insurance --
#: they are small -- so a bad hand-edit or a runaway script is always one file
#: away from recovery even across sessions, where the in-memory undo ring cannot
#: reach.
SNAPSHOT_KEEP = 10


def snapshot_dir(path: Path | None = None) -> Path:
    return (path or library_path()).parent / "snapshots"


def write_snapshot(library: Library, path: Path | None = None) -> None:
    """Drop a timestamped copy of the library and prune to the newest few.

    Best-effort and silent: a failed snapshot must never block or break a save.
    """
    try:
        target = path or library_path()
        folder = snapshot_dir(target)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        _atomic_write(
            folder / f"{target.stem}-{stamp}.json",
            json.dumps(library.to_dict(), indent=2, ensure_ascii=False),
        )
        snaps = sorted(folder.glob(f"{target.stem}-*.json"))
        for stale in snaps[:-SNAPSHOT_KEEP]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass


def save_library(library: Library, path: Path | None = None, snapshot: bool = False) -> None:
    path = path or library_path()
    if snapshot:
        write_snapshot(library, path)
    _atomic_write(path, json.dumps(library.to_dict(), indent=2, ensure_ascii=False))


class LibraryWatcher:
    """Notifies when ``templates.json`` changes underneath us.

    Self-inflicted writes are suppressed: :meth:`mark_self_write` records the
    moment we wrote, and events inside the quiet window are ignored. Callbacks
    are delivered on watchdog's thread, so the Qt side must marshal them.
    """

    QUIET_WINDOW_S = 1.0
    DEBOUNCE_S = 0.35

    def __init__(self, path: Path, on_change: Callable[[], None]) -> None:
        self._path = path.resolve()
        self._on_change = on_change
        self._last_self_write = 0.0
        self._last_emit = 0.0
        self._observer = None

    def mark_self_write(self) -> None:
        self._last_self_write = time.monotonic()

    def start(self) -> None:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:  # hot-reload is a nicety, not a requirement
            return

        watcher = self

        class _Handler(FileSystemEventHandler):
            def on_any_event(self, event) -> None:
                if event.is_directory:
                    return
                paths = [getattr(event, "src_path", ""), getattr(event, "dest_path", "")]
                if not any(p and Path(p).name == watcher._path.name for p in paths):
                    return
                now = time.monotonic()
                if now - watcher._last_self_write < watcher.QUIET_WINDOW_S:
                    return
                if now - watcher._last_emit < watcher.DEBOUNCE_S:
                    return
                watcher._last_emit = now
                watcher._on_change()

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._observer = Observer()
            self._observer.schedule(_Handler(), str(self._path.parent), recursive=False)
            self._observer.daemon = True
            self._observer.start()
        except Exception:
            self._observer = None

    def stop(self) -> None:
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=1.0)
            except Exception:
                pass
            self._observer = None
