"""Wave 5: caret parking, paste-and-send, and guarded selection capture.

The synthetic-keystroke primitives themselves (SendInput) can only be proven on
a real desktop -- scripts/verify.ps1 covers that. Here we test the decisions
around them: caret arithmetic, the post-paste scheduling, and every guard on
selection capture, all headlessly.
"""

from __future__ import annotations

from pcc import winapi
from pcc.model import Template, extract_caret, parse_slots


class TestExtractCaret:
    def test_no_marker_is_unchanged(self):
        assert extract_caret("hello world") == ("hello world", 0)

    def test_marker_is_removed_and_counts_trailing_chars(self):
        clean, left = extract_caret("hello {{^}}world")
        assert clean == "hello world"
        assert left == 5  # "world"

    def test_marker_at_end_parks_at_end(self):
        assert extract_caret("done {{^}}") == ("done ", 0)

    def test_all_markers_are_removed(self):
        clean, _ = extract_caret("a {{^}}b {{^}}c")
        assert "{{^}}" not in clean

    def test_caret_is_not_a_fill_slot(self):
        assert parse_slots("finish here {{^}}") == []


def _mute_paste(monkeypatch, sync_timers=True):
    """Stub the real Win32 paste path so a headless test can drive paste_text."""
    monkeypatch.setattr(winapi, "clipboard_get_text", lambda: "")
    monkeypatch.setattr(winapi, "clipboard_set_text", lambda _t: True)
    monkeypatch.setattr(winapi, "send_paste", lambda *_a: True)
    monkeypatch.setattr(winapi, "restore_focus", lambda *_a: True)
    if sync_timers:
        from pcc.ui import palette as pmod

        # Fire scheduled callbacks immediately so the delayed keystrokes are
        # observable without spinning an event loop.
        monkeypatch.setattr(pmod.QTimer, "singleShot", lambda _ms, cb: cb())


class TestCaretAndSend:
    def test_caret_parking_taps_left(self, palette, monkeypatch):
        _mute_paste(monkeypatch)
        taps = []
        monkeypatch.setattr(winapi, "send_key_taps", lambda vk, n: taps.append((vk, n)))
        palette.paste_text("hello {{^}}world")
        assert taps == [(winapi.VK_LEFT, 5)]

    def test_no_caret_no_taps(self, palette, monkeypatch):
        _mute_paste(monkeypatch)
        taps = []
        monkeypatch.setattr(winapi, "send_key_taps", lambda vk, n: taps.append((vk, n)))
        palette.paste_text("plain text")
        assert taps == []

    def test_paste_and_send_taps_enter(self, palette, monkeypatch):
        _mute_paste(monkeypatch)
        enters = []
        monkeypatch.setattr(winapi, "send_enter", lambda: enters.append(True) or True)
        palette._then_send = True
        palette.paste_text("submit me")
        assert enters == [True]

    def test_then_send_is_consumed_once(self, palette, monkeypatch):
        _mute_paste(monkeypatch)
        enters = []
        monkeypatch.setattr(winapi, "send_enter", lambda: enters.append(True) or True)
        palette._then_send = True
        palette.paste_text("first")
        palette.paste_text("second")   # flag was reset, no second send
        assert enters == [True]


class TestSelectionGuards:
    def test_off_never_captures(self, palette):
        palette.settings["capture_selection"] = "off"
        assert not palette._should_capture_selection()

    def test_console_is_denied_even_when_always(self, palette, monkeypatch):
        palette.settings["capture_selection"] = "always"
        monkeypatch.setattr(palette, "_current_app", lambda: "cmd.exe")
        assert not palette._should_capture_selection()

    def test_smart_needs_a_selection_template(self, palette, monkeypatch):
        palette.settings["capture_selection"] = "smart"
        monkeypatch.setattr(palette, "_current_app", lambda: "Code.exe")
        assert not palette._should_capture_selection()   # fixture uses none
        palette.library.tabs[0].templates.append(
            Template(title="S", body="Explain {{selection}}", id="s")
        )
        assert palette._should_capture_selection()

    def test_always_captures_outside_a_console(self, palette, monkeypatch):
        palette.settings["capture_selection"] = "always"
        monkeypatch.setattr(palette, "_current_app", lambda: "notepad.exe")
        assert palette._should_capture_selection()


class TestSelectionResolution:
    def test_changed_sequence_yields_the_selection_and_restores_clipboard(
        self, palette, monkeypatch
    ):
        palette._sel_pending = True
        palette._sel_seq = 1
        palette._sel_prior = "original clipboard"
        monkeypatch.setattr(winapi, "clipboard_sequence", lambda: 2)  # changed
        monkeypatch.setattr(winapi, "clipboard_get_text", lambda: "the selection")
        restored = []
        monkeypatch.setattr(winapi, "clipboard_set_text", lambda t: restored.append(t) or True)
        assert palette._selection() == "the selection"
        # The user's clipboard is put back, so capture never clobbers it.
        assert restored == ["original clipboard"]

    def test_unchanged_sequence_means_nothing_selected(self, palette, monkeypatch):
        palette._sel_pending = True
        palette._sel_seq = 7
        monkeypatch.setattr(winapi, "clipboard_sequence", lambda: 7)  # no change
        assert palette._selection() is None

    def test_selection_is_resolved_only_once(self, palette, monkeypatch):
        palette._sel_pending = True
        palette._sel_seq = 1
        palette._sel_prior = "orig"
        calls = []
        monkeypatch.setattr(winapi, "clipboard_sequence", lambda: 2)
        monkeypatch.setattr(
            winapi, "clipboard_get_text", lambda: calls.append(1) or "sel"
        )
        monkeypatch.setattr(winapi, "clipboard_set_text", lambda _t: True)
        assert palette._selection() == "sel"
        assert palette._selection() == "sel"   # cached
        assert len(calls) == 1

    def test_no_pending_capture_is_none(self, palette):
        palette._sel_pending = False
        assert palette._selection() is None
