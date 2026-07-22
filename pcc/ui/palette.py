"""The palette window: everything the user actually sees."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

#: Set PCC_TIMING=1 to print show latency to stderr. Off by default so the hot
#: path stays free of even a perf_counter call.
TIMING = bool(os.environ.get("PCC_TIMING"))

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import compose, context, lint, placement, spell, store, winapi
from ..context import is_magic
from ..journal import UndoJournal
from ..model import Library, Tab, Template, expand_includes, new_id, render
from ..usage import UsageStore
from ..search import search as run_search
from . import spellcheck
from .editor import EditorPanel
from .fill import PREFILL_SLOTS, FillPanel
from .grid import TileGrid
from .schemes import colour_tokens
from .settings_panel import SettingsPanel
from .tabstrip import TabStrip
from .theme import build_stylesheet

PAGE_GRID, PAGE_FILL, PAGE_EDITOR, PAGE_SETTINGS = 0, 1, 2, 3

HINTS = {
    PAGE_GRID: (
        "<b>↑↓←→</b> move · <b>type</b> filter · <b>⏎</b> paste · <b>^Space</b> mark · "
        "<b>^N</b> new · <b>F2</b> edit · <b>^Z</b> undo · <b>^H</b> health · "
        "<b>Esc</b> hide"
    ),
    PAGE_FILL: (
        "<b>⇥/⇧⇥</b> next slot · <b>←→</b> option · <b>type</b> your own · "
        "<b>^P</b> full preview · <b>⇧⏎</b> newline · <b>⏎</b> paste · <b>Esc</b> back"
    ),
    PAGE_EDITOR: (
        "<b>⇥</b> next field · <b>^S</b> save · <b>^.</b> fix spelling · "
        "<b>Esc</b> cancel"
    ),
    PAGE_SETTINGS: (
        "<b>↑↓</b> setting · <b>←→</b> change · <b>PgUp/PgDn</b> ×5 · "
        "<b>⏎</b> save · <b>Esc</b> revert"
    ),
}

#: Scaffolding decay: once you have used a page enough, the full hint bar is a
#: reminder you stopped reading in week one and are now paying screen space for.
#: So it shrinks to the essentials, then to almost nothing, as competence grows.
SHORT_HINTS = {
    PAGE_GRID: "<b>type</b> filter · <b>⏎</b> paste · <b>^Space</b> mark · <b>Esc</b> hide",
    PAGE_FILL: "<b>⇥</b> slot · <b>⏎</b> paste · <b>Esc</b> back",
    PAGE_EDITOR: "<b>^S</b> save · <b>Esc</b> cancel",
    PAGE_SETTINGS: "<b>↑↓←→</b> edit · <b>⏎</b> save · <b>Esc</b> revert",
}
MINIMAL_HINTS = {
    PAGE_GRID: "<b>Esc</b>",
    PAGE_FILL: "<b>⏎</b> · <b>Esc</b>",
    PAGE_EDITOR: "<b>^S</b> · <b>Esc</b>",
    PAGE_SETTINGS: "<b>⏎</b> · <b>Esc</b>",
}
PAGE_NAMES = {PAGE_GRID: "grid", PAGE_FILL: "fill", PAGE_EDITOR: "editor", PAGE_SETTINGS: "settings"}

#: Use counts at which a page's hint bar steps down a tier.
HINT_FAMILIAR = 30
HINT_EXPERT = 100


class PaletteWindow(QWidget):
    """Frameless always-on-top palette.

    Built **once** at startup and shown/hidden thereafter. Nothing in the show
    path allocates widgets, which is what keeps the trigger under ~30 ms.
    """

    quit_requested = Signal()

    SHADOW_BLUR = 38
    SHADOW_OFFSET_Y = 6
    #: Opacity of the card's drop shadow. Its *colour* comes from the scheme, so
    #: the halo is hue-matched, but it stays dark enough to lift the palette off
    #: a bright desktop rather than reading as a glow.
    SHADOW_ALPHA = 205
    #: The window must be large enough to contain the card *plus* its shadow.
    #:
    #: A QGraphicsDropShadowEffect paints outside the widget it is attached to,
    #: which makes Qt compute a damaged region larger than the window. On a
    #: translucent (layered) window that region is handed to
    #: UpdateLayeredWindowIndirect, which rejects anything outside the window
    #: bounds -- it failed with "the parameter is incorrect" for a 1316x966
    #: window and a 1340x1001 dirty rect at (-12,-5). A rejected update leaves
    #: the previous frame on screen, which showed up as the search box and tab
    #: strip staying painted over the fill panel. Keeping the margin wider than
    #: the shadow's reach keeps every damaged rect inside the window.
    SHADOW_MARGIN = 30

    def __init__(
        self, library: Library, settings: dict, usage: "UsageStore | None" = None
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.library = library
        self.settings = settings
        # Frecency / slot-memory. Injected so tests keep it in a tmp dir; in
        # production it lives beside settings in %APPDATA%\PCC, never in the
        # (possibly git-tracked) library folder.
        self.usage = usage if usage is not None else UsageStore(store.APP_DIR / "usage.json")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("PCC")

        self._target_hwnd = 0
        self._suppress_deactivate = False
        self._filtering = False
        self._editing: Template | None = None
        self._settings_snapshot: dict | None = None
        #: Called immediately before each save. The file watcher installs itself
        #: here so our own writes do not come back as an external change.
        self.before_save: Callable[[], None] = lambda: None

        self._fill_template: Template | None = None
        #: Template ids marked with Ctrl+Space, in mark order, for composition.
        #: Reset on every summon so a stale mark never rides into a new session.
        self._marked: list[str] = []
        #: In-session undo for destructive edits, so delete need not ask first.
        self.journal = UndoJournal()
        self._build_ui()
        self._wire()
        self._apply_spellcheck()
        self.refresh_tabs()
        self._resize_for(QApplication.primaryScreen())

        # Usage is flushed off a debounce, never on the keystroke that dirtied
        # it: a paste must not wait on a disk write. aboutToQuit flushes the
        # tail (wired in __main__).
        self._usage_timer = QTimer(self)
        self._usage_timer.setSingleShot(True)
        self._usage_timer.timeout.connect(self.usage.flush)

    # --- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*([self.SHADOW_MARGIN] * 4))

        card = QFrame()
        card.setObjectName("Card")
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(self.SHADOW_BLUR)
        self._shadow.setOffset(0, self.SHADOW_OFFSET_Y)
        card.setGraphicsEffect(self._shadow)
        self._apply_shadow_colour()
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(9)

        header = QHBoxLayout()
        header.setSpacing(10)
        brand = QLabel("PCC")
        brand.setObjectName("Brand")
        header.addWidget(brand)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("type to filter…")
        self.search.setClearButtonEnabled(False)
        header.addWidget(self.search, 1)
        root.addLayout(header)

        self.tabs = TabStrip()
        root.addWidget(self.tabs)

        self.stack = QStackedWidget()
        self.grid = TileGrid(columns=int(self.settings.get("columns", 3)))
        self.fill = FillPanel()
        self.editor = EditorPanel()
        self.settings_panel = SettingsPanel()
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.fill)
        self.stack.addWidget(self.editor)
        self.stack.addWidget(self.settings_panel)
        root.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        self.hints = QLabel()
        self.hints.setObjectName("Hints")
        self.hints.setTextFormat(Qt.TextFormat.RichText)
        # A non-wrapping QLabel reports its entire text width as its minimum,
        # which propagates up and stops the window ever being as narrow as
        # window_width asks for -- badly so at large font sizes. Wrapping plus
        # an ignored width policy lets the hint bar shrink instead.
        self.hints.setWordWrap(True)
        self.hints.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer.addWidget(self.hints, 1)
        self.toast = QLabel()
        self.toast.setObjectName("Toast")
        footer.addWidget(self.toast, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(footer)

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: self.toast.setText(""))

        # No fade-in animation, deliberately. setWindowOpacity drives a layered
        # window through SetLayeredWindowAttributes (constant alpha) while
        # WA_TranslucentBackground uses UpdateLayeredWindow (per-pixel alpha);
        # the two paths conflict on Windows and the failure mode is an
        # invisible window. Not worth the risk for 90 ms of polish on a tool
        # whose entire value proposition is appearing instantly.

    def _wire(self) -> None:
        self.search.textChanged.connect(self._on_search_changed)
        self.tabs.changed.connect(lambda _: self.refresh_grid())
        self.grid.activated.connect(self._activate)
        self.fill.submitted.connect(self._on_fill_submitted)
        self.fill.cancelled.connect(lambda: self._go_to_grid())
        self.editor.saved.connect(self._on_editor_saved)
        self.editor.cancelled.connect(lambda: self._go_to_grid())
        self.settings_panel.changed.connect(self._on_setting_changed)
        self.settings_panel.saved.connect(self._save_settings)
        self.settings_panel.cancelled.connect(self._revert_settings)

    def _apply_shadow_colour(self) -> None:
        """Re-tint the drop shadow for the current scheme."""
        tokens = colour_tokens(self.settings.get("scheme"), self.settings.get("accent"))
        colour = QColor(tokens["CARD_SHADOW"])
        colour.setAlpha(self.SHADOW_ALPHA)
        self._shadow.setColor(colour)

    def _apply_spellcheck(self) -> None:
        """Push the spelling settings into the checker and the marks.

        The squiggle wears SPELL -- the scheme's secondary colour pushed
        brighter, pink on Cyber, lime on Matrix -- so it stays inside the rule
        that every colour in the app derives from a scheme's three source
        colours, and reads as "not the accent" in all seven. Both setters no-op
        when nothing changed, which is what makes this safe to call on every
        keystroke of the live preview.
        """
        tokens = colour_tokens(self.settings.get("scheme"), self.settings.get("accent"))
        spell.set_language(self.settings.get("spellcheck_language"))
        spellcheck.set_colour(tokens["SPELL"])
        spellcheck.set_enabled(bool(self.settings.get("spellcheck", True)))

    def _resize_for(self, screen) -> None:
        width, height = placement.fit_size(
            screen,
            int(self.settings.get("window_width", 720)),
            int(self.settings.get("window_height", 520)),
            int(self.settings.get("margin", 40)),
        )
        chrome = 2 * self.SHADOW_MARGIN
        size = QSize(width + chrome, height + chrome)
        # Resizing a translucent frameless window forces Windows to rebuild its
        # layered surface -- measurable on the hot path, and the source of
        # spurious "UpdateLayeredWindowIndirect failed" warnings. Both monitors
        # usually yield the same size, so skip the no-op.
        if size != self.size():
            self.resize(size)

    # --- data ---------------------------------------------------------------

    def refresh_tabs(self, keep_index: int | None = None) -> None:
        index = self.tabs.index if keep_index is None else keep_index
        self.tabs.set_tabs(self.library.tabs, index)
        self.refresh_grid()

    def refresh_grid(self, keep_id: str | None = None) -> None:
        query = self.search.text().strip()
        if query:
            # Frecency nudges the ranking so the template you keep reaching for
            # floats up among equally-good matches -- capped, so it never beats a
            # title-prefix hit. Keyed to the app you summoned PCC over.
            bonus = self.usage.bonus_fn(self._current_app())
            hits = run_search(query, self.library.tabs, bonus=bonus)
            entries = [(hit.tab, hit.template) for hit in hits]
            self.grid.populate(
                entries, show_tab_hints=True, keep_id=keep_id, marked_ids=set(self._marked)
            )
        else:
            tab = self.tabs.current
            entries = [(tab, t) for t in tab.templates] if tab else []
            self.grid.populate(
                entries, show_tab_hints=False, keep_id=keep_id, marked_ids=set(self._marked)
            )

    def _on_search_changed(self, _text: str) -> None:
        self.refresh_grid()

    def reload_library(self) -> None:
        """Re-read templates.json after an external edit."""
        before = self.library
        try:
            self.library = store.load_library(store.library_path(self.settings))
        except Exception:
            return
        self.refresh_tabs(keep_index=min(self.tabs.index, max(0, len(self.library.tabs) - 1)))
        self._show_toast(self._reload_summary(before, self.library))

    @staticmethod
    def _reload_summary(before: Library, after: Library) -> str:
        """``+3 ~1 -0`` -- what a hand-edit actually changed, so the file-watcher
        toast confirms the edit landed without opening anything."""
        old = {t.id: t for _tab, t in before.iter_all()}
        new = {t.id: t for _tab, t in after.iter_all()}
        added = len(new.keys() - old.keys())
        removed = len(old.keys() - new.keys())
        changed = sum(
            1
            for tid in old.keys() & new.keys()
            if (old[tid].title, old[tid].body) != (new[tid].title, new[tid].body)
        )
        if not (added or removed or changed):
            return "RELOADED"
        return f"+{added} ~{changed} -{removed}"

    def reload_settings(self) -> None:
        """Re-read settings.json and restyle in place.

        Font changes take effect immediately: the stylesheet is rebuilt and the
        tiles re-measure their own text, so nothing needs a restart.
        """
        try:
            self.settings = store.load_settings()
        except Exception:
            return
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(self.settings))
        self._apply_shadow_colour()
        self._apply_spellcheck()
        self.grid.set_columns(int(self.settings.get("columns", 3)))
        # Re-binding forces the clamped labels to recompute their line heights
        # against the new font metrics.
        self.refresh_grid(keep_id=self.grid.current.id if self.grid.current else None)
        self._resize_for(placement.screen_for_window(self._target_hwnd))
        self._show_toast("SETTINGS RELOADED")

    def open_settings_file(self) -> None:
        self._open_in_editor(store.SETTINGS_PATH)

    # --- settings panel -----------------------------------------------------

    def open_settings(self) -> None:
        # Snapshot so Escape can undo an entire editing session, not just the
        # last keypress. Experimenting with colours has to be risk-free or
        # nobody will.
        self._settings_snapshot = dict(self.settings)
        self.settings_panel.load(self.settings)
        self._set_page(PAGE_SETTINGS)

    def _on_setting_changed(self, key: str, _value: object) -> None:
        """Apply an edit immediately -- the panel is its own preview."""
        self._apply_appearance()
        if key in ("window_width", "window_height", "margin"):
            self._reposition()

    def _apply_appearance(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(self.settings))
        self._apply_shadow_colour()
        self._apply_spellcheck()
        self.grid.set_columns(int(self.settings.get("columns", 3)))
        current = self.grid.current
        self.refresh_grid(keep_id=current.id if current else None)

    def _reposition(self) -> None:
        screen = placement.screen_for_window(self._target_hwnd)
        self._resize_for(screen)
        self.move(placement.top_left_position(
            screen, self.size(), int(self.settings.get("margin", 40))
        ))

    def _save_settings(self) -> None:
        try:
            store.save_settings(self.settings)
        except OSError:
            self._show_toast("COULD NOT SAVE")
            return
        self._settings_snapshot = dict(self.settings)
        self._go_to_grid()
        self._show_toast("SETTINGS SAVED")

    def _revert_settings(self) -> None:
        if self._settings_snapshot is not None:
            # Mutate in place: the panel and everything else hold this same dict.
            self.settings.clear()
            self.settings.update(self._settings_snapshot)
            self._apply_appearance()
            self._reposition()
        self._go_to_grid()

    def _save(self, snapshot: bool = False) -> None:
        self.before_save()
        store.save_library(
            self.library, store.library_path(self.settings), snapshot=snapshot
        )

    # --- show / hide --------------------------------------------------------

    def trigger(self) -> None:
        """Handle the AHK trigger: capture the target, then appear."""
        marks: list[tuple[str, float]] = []
        started = time.perf_counter() if TIMING else 0.0

        def mark(label: str) -> None:
            if TIMING:
                marks.append((label, (time.perf_counter() - started) * 1000))

        foreground = winapi.get_foreground_window()
        # Ignore our own windows so a double trigger cannot make us the target.
        if foreground and foreground != int(self.winId()):
            self._target_hwnd = foreground
        mark("capture")

        # A new summon starts with a clean slate -- a mark left over from last
        # time would silently join the next prompt.
        self._marked.clear()
        self._go_to_grid(clear_search=True)
        mark("repopulate")

        screen = placement.screen_for_window(self._target_hwnd)
        self._resize_for(screen)
        self.move(placement.top_left_position(
            screen, self.size(), int(self.settings.get("margin", 40))
        ))
        mark("place")

        self.show()
        self.raise_()
        mark("show")

        # We are summoned while another app is foreground, so Qt's
        # activateWindow() alone gets refused and the palette would appear
        # without keyboard focus. Take the foreground explicitly first.
        winapi.force_foreground(int(self.winId()))
        self.activateWindow()
        self.search.setFocus()
        mark("focus")

        if TIMING:
            focused = winapi.get_foreground_window() == int(self.winId())
            phases = " ".join(f"{label}={ms:.1f}" for label, ms in marks)
            print(
                f"[pcc] show {marks[-1][1]:.1f} ms  [{phases}] "
                f"tiles={self.grid.count} focused={focused}",
                file=sys.stderr,
                flush=True,
            )

    #: Far outside the virtual desktop, so the prewarm show cannot flash.
    _PREWARM_POS = QPoint(-32000, -32000)

    def prewarm(self) -> None:
        """Pay the first-show cost at startup rather than on the first trigger.

        Measured breakdown of a cold trigger was ``show`` 21 ms and ``focus``
        15 ms, against 4-5 ms each once warm. Polishing widgets alone did not
        help much: the expensive part is Windows creating the layered surface
        for a translucent window and compositing the first frame, which only
        happens on a real ``show()``.

        So we genuinely show it, parked off-screen and non-activating, then hide
        it again. PCC starts at boot and lives in the tray, so this cost lands
        where nobody is waiting on it.
        """
        self.ensurePolished()
        for child in self.findChildren(QWidget):
            child.ensurePolished()

        self._suppress_deactivate = True
        # Do not steal focus from whatever the user is doing at login.
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        try:
            self.move(self._PREWARM_POS)
            self.show()
            QApplication.processEvents()
            self.hide()
            QApplication.processEvents()
        finally:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
            self._suppress_deactivate = False

        # Same bargain, for the spell checker: building the COM object costs
        # ~70 ms once. Paid here it is free; paid on the first Ctrl+N it would
        # be a visible stutter on the way into the editor.
        try:
            spell.warm()
        except Exception:
            pass

    def toggle(self) -> None:
        if self.isVisible():
            self.dismiss()
        else:
            self.trigger()

    def dismiss(self, restore_focus: bool = True) -> None:
        """Hide without pasting."""
        self._suppress_deactivate = True
        self.hide()
        if restore_focus:
            winapi.restore_focus(self._target_hwnd)
        self._suppress_deactivate = False

    def shut_down(self) -> None:
        """Quit PCC entirely, not just hide it.

        Focus goes back to the window you came from first: the palette is about
        to vanish along with the process, and an orphaned foreground leaves the
        caret nowhere.

        It does not ask. AHK relaunches PCC on the next CapsLock+Space -- so the
        worst an accidental Ctrl+Q costs is the ~1 s cold start on the next
        trigger -- and the tray's own *Quit PCC* has never asked either.
        """
        self.dismiss(restore_focus=True)
        self.quit_requested.emit()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # The key filter is application-wide, so it is attached only while the
        # palette is up: nothing to filter when hidden, and -- more importantly
        # -- no filter left dangling on the QApplication for the lifetime of the
        # process once this window goes away.
        super().showEvent(event)
        if not self._filtering:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
                self._filtering = True

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._filtering:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._filtering = False
        super().hideEvent(event)

    def event(self, event) -> bool:
        if (
            event.type() == QEvent.Type.WindowDeactivate
            and self.isVisible()
            and not self._suppress_deactivate
        ):
            # Clicking away should dismiss, but focus has already moved, so do
            # not fight the user for it.
            self.dismiss(restore_focus=False)
        return super().event(event)

    # --- paste --------------------------------------------------------------

    def paste_text(self, text: str) -> None:
        """Put ``text`` on the clipboard and paste it into the captured window."""
        if not text:
            self.dismiss()
            return

        restore = bool(self.settings.get("restore_clipboard", True))
        prior = winapi.clipboard_get_text() if restore else None

        if not winapi.clipboard_set_text(text):
            self._show_toast("CLIPBOARD BUSY")
            return

        self.dismiss(restore_focus=True)
        winapi.send_paste(str(self.settings.get("paste_key", "ctrl+v")))

        if prior is not None:
            # Give the target app time to read the clipboard before we put the
            # old contents back; restoring immediately races the paste.
            QTimer.singleShot(
                int(self.settings.get("restore_clipboard_delay_ms", 300)),
                lambda: winapi.clipboard_set_text(prior),
            )

    def _resolver_for(self, template: Template) -> "tuple[object, list, str | None]":
        """Build the magic-slot resolver, CONTEXT items and prefill for ``template``.

        The clipboard is read at most once, and only when a magic slot or a
        prefill-worthy input actually wants it -- this runs after the user has
        already chosen, never on the trigger hot path.
        """
        input_slots = [s for s in template.slots if not is_magic(s.name)]
        magic_names = [s.name for s in template.slots if is_magic(s.name)]
        prefill_candidate = any(
            not s.has_options and s.name.lower() in PREFILL_SLOTS for s in input_slots
        )
        clip = (
            (winapi.clipboard_get_text() or "")
            if (magic_names or prefill_candidate)
            else None
        )
        env = context.ResolveEnv(target_hwnd=self._target_hwnd, clipboard=clip)
        resolve = context.make_resolver(env)
        items = context.context_items(magic_names, env)
        prefill = clip if prefill_candidate else None
        return resolve, items, prefill, input_slots

    def _current_app(self) -> str | None:
        try:
            return winapi.process_name(self._target_hwnd) or None
        except Exception:
            return None

    def _record_use(self, template: Template) -> None:
        self.usage.record_use(template.id, self._current_app())
        self._usage_timer.start(5000)

    def _make_lookup(self) -> "Callable[[str], str | None]":
        """Resolve a ``{{>ref}}`` include to another template's body, by id or title."""
        def lookup(ref: str) -> str | None:
            key = ref.strip().lower()
            for _tab, template in self.library.iter_all():
                if template.id == ref or template.title.strip().lower() == key:
                    return template.body
            return None
        return lookup

    def _expanded(self, template: Template) -> Template:
        """``template`` with its ``{{>includes}}`` inlined, keeping id/title/tags.

        Same id, so usage recording and slot recall still key off the real
        template even after its body has been composed from others.
        """
        expanded = expand_includes(template.body, self._make_lookup())
        if expanded == template.body:
            return template
        return Template(
            title=template.title, body=expanded, id=template.id, tags=list(template.tags)
        )

    def _activate(self, template: Template) -> None:
        template = self._expanded(template)
        resolve, items, prefill, input_slots = self._resolver_for(template)
        # A template whose only slots are magic ({{clipboard}}, {{date}}...) has
        # nothing to type, so skip the fill panel entirely -- copy, summon, done.
        if not input_slots:
            self._record_use(template)
            self.paste_text(render(template.body, resolve=resolve))
            return
        recall = {s.name: self.usage.slot_value(template.id, s.name) for s in input_slots}
        self._fill_template = template
        self.fill.load(
            template, resolve=resolve, context_items=items, prefill=prefill, recall=recall
        )
        self._set_page(PAGE_FILL)
        self.fill.focus_first()

    def _on_fill_submitted(self, text: str) -> None:
        """A filled template was accepted: bank the use and remember the slots."""
        template = self._fill_template
        if template is not None:
            self._record_use(template)
            for name, value in self.fill.values().items():
                self.usage.record_slot(template.id, name, value)
        self.paste_text(text)

    def _paste_raw(self) -> None:
        template = self.grid.current
        if template is not None:
            template = self._expanded(template)
            resolve, _items, _prefill, _inputs = self._resolver_for(template)
            self._record_use(template)
            self.paste_text(render(template.body, resolve=resolve))

    # --- composition (mark with Ctrl+Space, apply on Enter) ------------------

    def _toggle_mark(self) -> None:
        template = self.grid.current
        if template is None:
            return
        if template.id in self._marked:
            self._marked.remove(template.id)
        else:
            self._marked.append(template.id)
        self.grid.apply_marks(set(self._marked))
        count = len(self._marked)
        self._show_toast(f"{count} MARKED" if count else "CLEARED")

    def _clear_marks(self) -> None:
        if self._marked:
            self._marked.clear()
            self.grid.apply_marks(set())

    def _template_by_id(self, template_id: str) -> Template | None:
        located = self.library.locate(template_id)
        return located[0].templates[located[1]] if located else None

    def _activate_selection(self) -> None:
        """Enter: compose the marked templates if any, else the current one.

        Predictable rule -- **marks are the selection**. If any non-modifier
        (base) templates are marked, those are the bases and the hovered tile is
        ignored; otherwise the hovered tile is the base. Marked modifiers always
        layer on. Choosing anything clears the marks.
        """
        if not self._marked:
            self.grid.activate()
            return
        marked = [t for t in (self._template_by_id(i) for i in self._marked) if t is not None]
        modifiers = [t for t in marked if t.is_modifier]
        bases = [t for t in marked if not t.is_modifier]
        if not bases:
            current = self.grid.current
            if current is not None and not current.is_modifier:
                bases = [current]
        composed = compose.compose(bases, modifiers)
        self._clear_marks()
        if composed is not None:
            self._activate(composed)

    # --- pages --------------------------------------------------------------

    def _hint_for(self, page: int) -> str:
        """The hint bar for ``page``, faded to match how well it is known."""
        count = self.usage.page_count(PAGE_NAMES.get(page, str(page)))
        if count >= HINT_EXPERT:
            return MINIMAL_HINTS[page]
        if count >= HINT_FAMILIAR:
            return SHORT_HINTS[page]
        return HINTS[page]

    def _set_page(self, page: int) -> None:
        # Record a page as "used" only on a real transition into it, so the many
        # internal _set_page(GRID) calls per summon do not inflate the count.
        if page != self.stack.currentIndex():
            self.usage.record_page(PAGE_NAMES.get(page, str(page)))
            self._usage_timer.start(5000)
        self.stack.setCurrentIndex(page)
        self.hints.setText(self._hint_for(page))
        self.search.setVisible(page == PAGE_GRID)
        self.tabs.setVisible(page == PAGE_GRID)
        # Hiding widgets on a translucent frameless window leaves their pixels
        # behind: the damaged region is not always propagated to the layered
        # surface, so the search box and tab strip stayed painted over the fill
        # panel. Invalidating the whole window is cheap here and reliable.
        self.update()

    def _go_to_grid(self, clear_search: bool = False) -> None:
        if clear_search:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.refresh_grid()
        self._set_page(PAGE_GRID)
        self.search.setFocus()

    def _show_toast(self, message: str) -> None:
        self.toast.setText(message)
        self._toast_timer.start(1600)

    # --- authoring ----------------------------------------------------------

    def _current_tab(self) -> Tab | None:
        return self.tabs.current

    def _new_template(self) -> None:
        tab = self._current_tab()
        if tab is None:
            self._show_toast("CREATE A TAB FIRST")
            return
        self._editing = None
        self.editor.load(None, self.library.tabs, tab.id)
        self._set_page(PAGE_EDITOR)
        self.editor.focus_first()

    def _edit_template(self) -> None:
        template = self.grid.current
        if template is None:
            return
        located = self.library.locate(template.id)
        if located is None:
            return
        self._editing = template
        self.editor.load(template, self.library.tabs, located[0].id)
        self._set_page(PAGE_EDITOR)
        self.editor.focus_first()

    def _on_editor_saved(self, template: Template, tab_id: str) -> None:
        target_tab = self.library.find_tab(tab_id) or (
            self.library.tabs[0] if self.library.tabs else None
        )
        if target_tab is None:
            return

        located = self.library.locate(template.id)
        if located is None:
            target_tab.templates.append(template)
        elif located[0] is not target_tab:
            # Moved between tabs: detach from the old one, append to the new.
            located[0].templates.pop(located[1])
            target_tab.templates.append(template)

        self._save()
        self._editing = None
        index = next(
            (i for i, tab in enumerate(self.library.tabs) if tab is target_tab),
            self.tabs.index,
        )
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.tabs.set_tabs(self.library.tabs, index)
        self.refresh_grid(keep_id=template.id)
        self._set_page(PAGE_GRID)
        self.search.setFocus()
        self._show_toast("SAVED")

    def _duplicate_template(self) -> None:
        template = self.grid.current
        located = self.library.locate(template.id) if template else None
        if template is None or located is None:
            return
        tab, index = located
        clone = Template(title=f"{template.title} copy", body=template.body,
                         tags=list(template.tags))
        tab.templates.insert(index + 1, clone)
        self._save()
        self.refresh_grid(keep_id=clone.id)
        self._show_toast("DUPLICATED")

    def _snapshot(self, label: str) -> None:
        """Bank the current library so the next destructive edit is undoable."""
        self.journal.record(self.library.to_dict(), label)

    def _undo(self) -> None:
        entry = self.journal.undo()
        if entry is None:
            self._show_toast("NOTHING TO UNDO")
            return
        snapshot, label = entry
        self.library = Library.from_dict(snapshot)
        self._save()
        self.refresh_tabs(keep_index=min(self.tabs.index, max(0, len(self.library.tabs) - 1)))
        self._show_toast(f"UNDID {label}")

    def _health_report(self) -> tuple[str, str]:
        """(summary, detail) for the library health check."""
        findings = lint.lint(self.library, self.usage.frecency)
        summary = lint.summary(findings)
        if not findings:
            return summary, "Nothing to clean up. 🎉"
        by_tab: dict[str, list[str]] = {}
        for finding in findings:
            by_tab.setdefault(finding.tab_name, []).append(finding.message)
        detail_lines = []
        for tab_name, messages in by_tab.items():
            detail_lines.append(f"[{tab_name}]")
            detail_lines.extend(f"  • {m}" for m in messages)
        return summary, "\n".join(detail_lines)

    def _show_health(self) -> None:
        summary, detail = self._health_report()
        self._show_toast(summary.upper())
        with self.modal_guard():
            box = QMessageBox(self)
            box.setWindowTitle("Library health")
            box.setText(summary)
            box.setInformativeText(detail)
            box.setIcon(QMessageBox.Icon.Information)
            box.exec()

    def _delete_template(self) -> None:
        template = self.grid.current
        located = self.library.locate(template.id) if template else None
        if template is None or located is None:
            return
        tab, index = located
        # No confirmation dialog: delete now, keep an undo. A prompt on every
        # delete trains click-through; undo catches the mistake without one.
        self._snapshot("delete")
        tab.templates.pop(index)
        self._save(snapshot=True)
        self.refresh_grid()
        self._show_toast("DELETED · ^Z undo")

    def _move_template(self, delta: int) -> None:
        template = self.grid.current
        located = self.library.locate(template.id) if template else None
        if template is None or located is None:
            return
        # Reordering is meaningless while search reshuffles the grid.
        if self.search.text().strip():
            self._show_toast("CLEAR SEARCH TO REORDER")
            return
        tab, index = located
        new_index = max(0, min(index + delta, len(tab.templates) - 1))
        if new_index == index:
            return
        tab.templates.insert(new_index, tab.templates.pop(index))
        self._save()
        self.refresh_grid(keep_id=template.id)

    def _new_tab(self) -> None:
        name = self._prompt("New tab", "Name:")
        if not name:
            return
        self.library.tabs.append(Tab(name=name, id=new_id("t")))
        self._save()
        self.refresh_tabs(keep_index=len(self.library.tabs) - 1)
        self._show_toast("TAB ADDED")

    def _rename_tab(self) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        name = self._prompt("Rename tab", "Name:", tab.name)
        if not name:
            return
        tab.name = name
        self._save()
        self.refresh_tabs()
        self._show_toast("RENAMED")

    def _delete_tab(self) -> None:
        tab = self._current_tab()
        if tab is None:
            return
        if len(self.library.tabs) == 1:
            self._show_toast("LAST TAB")
            return
        count = len(tab.templates)
        # A tab can destroy many templates at once, so this one keeps a
        # confirmation -- but still banks an undo as a second safety net.
        if not self._confirm(
            f"Delete tab “{tab.name}”" + (f" and its {count} templates?" if count else "?")
        ):
            return
        self._snapshot("delete tab")
        index = self.tabs.index
        self.library.tabs.remove(tab)
        self._save(snapshot=True)
        self.refresh_tabs(keep_index=max(0, index - 1))
        self._show_toast("TAB DELETED · ^Z undo")

    def _move_tab(self, delta: int) -> None:
        index = self.tabs.index
        new_index = index + delta
        if not (0 <= new_index < len(self.library.tabs)):
            return
        self.library.tabs.insert(new_index, self.library.tabs.pop(index))
        self._save()
        self.refresh_tabs(keep_index=new_index)

    def open_library_file(self) -> None:
        self._open_in_editor(store.library_path(self.settings))

    def _open_in_editor(self, path: Path) -> None:
        self.dismiss(restore_focus=False)
        try:
            subprocess.Popen(["cmd", "/c", "start", "", str(path)], shell=False)
        except Exception:
            pass

    # --- modal helpers ------------------------------------------------------

    @contextmanager
    def modal_guard(self):
        """Run something that takes focus without the palette hiding itself.

        Public because the spelling menu needs it too, and it finds it by name
        on :meth:`QWidget.window` -- which keeps ``ui.spellcheck`` free of any
        import back into this module.
        """
        self._suppress_deactivate = True
        try:
            yield
        finally:
            self._suppress_deactivate = False
            self.activateWindow()

    def _prompt(self, title: str, label: str, initial: str = "") -> str | None:
        """Modal text prompt that does not trip the auto-hide-on-deactivate rule."""
        with self.modal_guard():
            text, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Normal, initial)
        return text.strip() if ok and text.strip() else None

    def _confirm(self, question: str) -> bool:
        with self.modal_guard():
            answer = QMessageBox.question(
                self,
                "PCC",
                question,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
        return answer == QMessageBox.StandardButton.Yes

    # --- keyboard -----------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        """Single funnel for every key press while the palette is up.

        Filtering at the application level -- rather than on each input widget --
        means dynamically created slot editors are covered automatically and
        Ctrl+Tab is intercepted before Qt turns it into focus navigation.
        """
        if event.type() != QEvent.Type.KeyPress or not self.isVisible():
            return False
        # Our prompts are parented to this window, so their widgets pass the
        # ancestry test below. Without this guard, Enter in a "New tab" dialog
        # would be read as "paste the selected template", and Escape in an open
        # combo box would cancel the editor instead of closing the popup.
        if (
            QApplication.activeModalWidget() is not None
            or QApplication.activePopupWidget() is not None
        ):
            return False
        if not (obj is self or (isinstance(obj, QWidget) and self.isAncestorOf(obj))):
            return False

        page = self.stack.currentIndex()
        if page == PAGE_FILL:
            return self.fill.handle_key(event)
        if page == PAGE_EDITOR:
            return self.editor.handle_key(event)
        if page == PAGE_SETTINGS:
            return self.settings_panel.handle_key(event)
        return self._handle_grid_key(event)

    def _handle_grid_key(self, event) -> bool:
        key = event.key()
        modifiers = event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)

        if key == Qt.Key.Key_Escape:
            # Esc peels one layer at a time: search first, then the window.
            if self.search.text():
                self.search.clear()
            else:
                self.dismiss()
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if control:
                self._paste_raw()
            else:
                self._activate_selection()
            return True

        # Ctrl+Space marks the current tile for composition. Ctrl-, not bare
        # Space, because the search box owns Space for multi-word queries.
        if control and key == Qt.Key.Key_Space:
            self._toggle_mark()
            return True

        # Tab reordering must be checked before plain tab switching.
        if control and shift and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self._move_tab(-1 if key == Qt.Key.Key_Left else 1)
            return True

        if control and key in (
            Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down
        ):
            # While filtering, the grid order is the search ranking rather than
            # the stored order, so reordering is meaningless -- hand Ctrl+Arrow
            # back to the search box for word-wise navigation instead.
            if self.search.text().strip():
                return False
            columns = self.grid.columns
            delta = {
                Qt.Key.Key_Left: -1,
                Qt.Key.Key_Right: 1,
                Qt.Key.Key_Up: -columns,
                Qt.Key.Key_Down: columns,
            }[key]
            self._move_template(delta)
            return True

        # Ctrl+Tab is the documented binding, but bare Tab does the same: the
        # search box is the only focusable widget on this page, so Qt's focus
        # chain has nowhere useful to go and the key would otherwise be wasted.
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.tabs.step(-1 if (shift or key == Qt.Key.Key_Backtab) else 1)
            return True

        if alt and Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            self.tabs.set_index(key - Qt.Key.Key_1)
            return True

        if key in (
            Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
            Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
        ):
            # Home/End belong to the search box once there is text to move within.
            if key in (Qt.Key.Key_Home, Qt.Key.Key_End) and self.search.text():
                return False
            return self.grid.move(key)

        if control and key == Qt.Key.Key_N:
            self._new_tab() if shift else self._new_template()
            return True
        if key == Qt.Key.Key_F2:
            self._rename_tab() if shift else self._edit_template()
            return True
        if control and key == Qt.Key.Key_D:
            self._duplicate_template()
            return True
        if control and key == Qt.Key.Key_Delete:
            self._delete_tab() if shift else self._delete_template()
            return True
        if control and key == Qt.Key.Key_Z:
            self._undo()
            return True
        # Ctrl+H opens the library health check.
        if control and key == Qt.Key.Key_H:
            self._show_health()
            return True
        # Ctrl+, is the near-universal "open preferences" binding.
        if key == Qt.Key.Key_Comma and control:
            self.open_settings()
            return True
        if control and key == Qt.Key.Key_E:
            self.open_settings_file() if shift else self.open_library_file()
            return True
        if control and key == Qt.Key.Key_R:
            self.reload_settings() if shift else self.reload_library()
            return True
        # Only reachable from the grid page -- the editor, fill and settings
        # pages get first refusal on every key, so Ctrl+Q can never discard a
        # template you are halfway through writing.
        if control and key == Qt.Key.Key_Q:
            self.shut_down()
            return True

        return False


# Re-exported so callers have one obvious import site for the stylesheet.
load_stylesheet = build_stylesheet
