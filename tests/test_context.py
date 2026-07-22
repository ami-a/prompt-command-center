"""Magic-slot resolvers and the render-time injection they feed."""

from __future__ import annotations

import datetime as dt

from pcc import context
from pcc.context import ResolveEnv, context_items, is_magic, make_resolver
from pcc.model import render

FIXED = dt.datetime(2026, 7, 22, 14, 5)


class TestRegistry:
    def test_known_names_are_magic(self):
        for name in ("clipboard", "date", "time", "datetime", "app", "window"):
            assert is_magic(name)

    def test_unknown_names_are_not_magic(self):
        assert not is_magic("code")
        assert not is_magic("language")

    def test_names_are_trimmed(self):
        assert is_magic("  clipboard  ")


class TestResolve:
    def test_clipboard_uses_the_snapshot(self):
        env = ResolveEnv(clipboard="hello world")
        assert context.resolve("clipboard", env).value == "hello world"

    def test_empty_clipboard_is_unavailable(self):
        # Unavailable, not "" -- so it falls through to the literal token rather
        # than pasting an empty string where the user expected content.
        env = ResolveEnv(clipboard="")
        result = context.resolve("clipboard", env)
        assert result.value is None
        assert not result.available

    def test_date_and_time_use_the_fixed_now(self):
        env = ResolveEnv(now=FIXED)
        assert context.resolve("date", env).value == "2026-07-22"
        assert context.resolve("time", env).value == "14:05"
        assert context.resolve("datetime", env).value == "2026-07-22 14:05"

    def test_selection_defaults_to_unavailable(self):
        assert context.resolve("selection", ResolveEnv()).value is None

    def test_unknown_name_resolves_to_none(self):
        assert context.resolve("nonsense", ResolveEnv()).value is None

    def test_app_and_window_are_empty_without_a_target(self):
        env = ResolveEnv(target_hwnd=0)
        assert context.resolve("app", env).value is None
        assert context.resolve("window", env).value is None


class TestRenderInjection:
    def test_magic_slot_is_filled_by_the_resolver(self):
        env = ResolveEnv(clipboard="def f(): pass", now=FIXED)
        out = render("Explain {{clipboard}}", resolve=make_resolver(env))
        assert out == "Explain def f(): pass"

    def test_user_value_beats_the_resolver(self):
        env = ResolveEnv(clipboard="from clipboard")
        out = render("{{clipboard}}", {"clipboard": "typed"}, resolve=make_resolver(env))
        assert out == "typed"

    def test_explicit_default_beats_the_resolver(self):
        # A hand-written default must keep winning, so nothing anyone already
        # wrote changes meaning once magic slots exist.
        env = ResolveEnv(now=FIXED)
        out = render("{{date|yesterday}}", resolve=make_resolver(env))
        assert out == "yesterday"

    def test_unavailable_magic_falls_back_to_literal_token(self):
        env = ResolveEnv(clipboard="")
        out = render("Explain {{clipboard}}", resolve=make_resolver(env))
        assert out == "Explain {{clipboard}}"

    def test_no_resolver_is_unchanged_behaviour(self):
        assert render("Explain {{clipboard}}") == "Explain {{clipboard}}"


class TestContextItems:
    def test_summary_of_short_value(self):
        (item,) = context_items(["app"], ResolveEnv(clipboard=None))
        # No target, so app is unavailable -> the em dash form.
        assert item.summary() == "app · —"

    def test_summary_of_a_long_clipboard_is_sized_not_dumped(self):
        big = "x" * 2000
        (item,) = context_items(["clipboard"], ResolveEnv(clipboard=big))
        assert item.summary() == "clipboard · 2.0k chars"

    def test_summary_of_a_short_clipboard_shows_it(self):
        (item,) = context_items(["clipboard"], ResolveEnv(clipboard="hi"))
        assert item.summary() == "clipboard · hi"

    def test_date_item_uses_a_friendly_label(self):
        (item,) = context_items(["date"], ResolveEnv(now=FIXED))
        assert item.summary() == "today · 2026-07-22"
