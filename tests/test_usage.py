"""Frecency decay, the bounded ranking bonus, and slot memory."""

from __future__ import annotations

import datetime as dt

from pcc.usage import MAX_BONUS, UsageStore


def clock(start=dt.datetime(2026, 1, 1, 12, 0)):
    """A mutable fake clock: returns ``now()`` and a ``tick(days)`` to advance it."""
    state = {"t": start}

    def now():
        return state["t"]

    def tick(days=0, seconds=0):
        state["t"] = state["t"] + dt.timedelta(days=days, seconds=seconds)

    return now, tick


class TestFrecency:
    def test_a_use_registers(self, tmp_path):
        now, _ = clock()
        u = UsageStore(tmp_path / "u.json", now=now)
        assert u.frecency("p1") == 0.0
        u.record_use("p1")
        assert u.frecency("p1") == 1.0

    def test_repeated_uses_accumulate(self, tmp_path):
        now, _ = clock()
        u = UsageStore(tmp_path / "u.json", now=now)
        for _ in range(3):
            u.record_use("p1")
        assert u.frecency("p1") == 3.0

    def test_score_halves_over_one_half_life(self, tmp_path):
        now, tick = clock()
        u = UsageStore(tmp_path / "u.json", now=now)
        u.record_use("p1")
        tick(days=14)
        assert abs(u.frecency("p1") - 0.5) < 1e-6

    def test_recent_use_outweighs_old_use(self, tmp_path):
        now, tick = clock()
        u = UsageStore(tmp_path / "u.json", now=now)
        u.record_use("old")
        tick(days=28)
        u.record_use("new")
        assert u.frecency("new") > u.frecency("old")


class TestBonus:
    def test_bonus_is_capped(self, tmp_path):
        now, _ = clock()
        u = UsageStore(tmp_path / "u.json", now=now)
        for _ in range(50):
            u.record_use("p1")
        assert u.bonus("p1") == MAX_BONUS

    def test_unused_template_gets_no_bonus(self, tmp_path):
        u = UsageStore(tmp_path / "u.json")
        assert u.bonus("never") == 0.0

    def test_same_app_affinity_adds_within_the_cap(self, tmp_path):
        now, _ = clock()
        u = UsageStore(tmp_path / "u.json", now=now)
        u.record_use("p1", app="Code.exe")
        u.record_use("p1", app="Code.exe")
        # Same app the template was used in should rank at least as high as the
        # app-agnostic figure, and never exceed the cap.
        assert u.bonus("p1", app="Code.exe") >= u.bonus("p1")
        assert u.bonus("p1", app="Code.exe") <= MAX_BONUS


class TestMostFrecent:
    def test_picks_the_hottest_id(self, tmp_path):
        now, _ = clock()
        u = UsageStore(tmp_path / "u.json", now=now)
        u.record_use("a")
        u.record_use("b")
        u.record_use("b")
        assert u.most_frecent(["a", "b", "c"]) == "b"

    def test_all_cold_returns_none(self, tmp_path):
        u = UsageStore(tmp_path / "u.json")
        assert u.most_frecent(["a", "b"]) is None


class TestSlotMemory:
    def test_remembers_a_short_value(self, tmp_path):
        u = UsageStore(tmp_path / "u.json")
        u.record_slot("p1", "language", "Python")
        assert u.slot_value("p1", "language") == "Python"

    def test_does_not_remember_sensitive_slot_names(self, tmp_path):
        # {{code}} and friends carry pastes and secrets; never persist them.
        u = UsageStore(tmp_path / "u.json")
        u.record_slot("p1", "code", "sk-secret-value")
        assert u.slot_value("p1", "code") is None

    def test_does_not_remember_long_values(self, tmp_path):
        u = UsageStore(tmp_path / "u.json")
        u.record_slot("p1", "topic", "x" * 200)
        assert u.slot_value("p1", "topic") is None

    def test_does_not_remember_multiline_values(self, tmp_path):
        u = UsageStore(tmp_path / "u.json")
        u.record_slot("p1", "topic", "line1\nline2")
        assert u.slot_value("p1", "topic") is None


class TestPersistence:
    def test_survives_a_reload(self, tmp_path):
        # Fixed clock on both stores, so no real time elapses between write and
        # read to decay the score off its exact value.
        now, _ = clock()
        path = tmp_path / "u.json"
        u = UsageStore(path, now=now)
        u.record_use("p1")
        u.record_slot("p1", "language", "Go")
        u.flush()
        again = UsageStore(path, now=now)
        assert again.frecency("p1") == 1.0
        assert again.slot_value("p1", "language") == "Go"

    def test_corrupt_file_degrades_to_empty(self, tmp_path):
        path = tmp_path / "u.json"
        path.write_text("{ not json", encoding="utf-8")
        u = UsageStore(path)  # must not raise
        assert u.frecency("p1") == 0.0

    def test_missing_file_is_fine(self, tmp_path):
        u = UsageStore(tmp_path / "nope.json")
        assert u.frecency("p1") == 0.0

    def test_flush_without_changes_writes_nothing(self, tmp_path):
        path = tmp_path / "u.json"
        UsageStore(path).flush()
        assert not path.exists()
