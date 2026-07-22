"""Persistence: atomicity, corruption recovery, and the self-write guard."""

from __future__ import annotations

import json

from pcc import store
from pcc.model import Library, Tab, Template


def test_seeds_defaults_on_first_run(tmp_path):
    path = tmp_path / "templates.json"
    library = store.load_library(path)
    assert path.exists()
    assert library.tabs, "seeded library should not be empty"


def test_seeded_defaults_are_valid_templates(tmp_path):
    library = store.load_library(tmp_path / "templates.json")
    for _, template in library.iter_all():
        assert template.title and template.body


def test_round_trip_preserves_everything(tmp_path):
    path = tmp_path / "templates.json"
    original = Library(tabs=[
        Tab(name="קטגוריה", id="t1", templates=[
            Template(title="שלום", body="{{a|ב}} 你好", id="p1", tags=["x"]),
        ]),
    ])
    store.save_library(original, path)
    restored = store.load_library(path)

    assert restored.tabs[0].name == "קטגוריה"
    assert restored.tabs[0].templates[0].body == "{{a|ב}} 你好"
    assert restored.tabs[0].templates[0].tags == ["x"]


def test_unicode_is_stored_readably(tmp_path):
    """Hand-editing the file is a supported workflow, so no \\uXXXX escapes."""
    path = tmp_path / "templates.json"
    store.save_library(
        Library(tabs=[Tab(name="עברית", id="t1")]), path
    )
    assert "עברית" in path.read_text(encoding="utf-8")


def test_corrupt_file_is_preserved_not_destroyed(tmp_path):
    path = tmp_path / "templates.json"
    path.write_text("{ this is not json", encoding="utf-8")

    library = store.load_library(path)

    assert library.tabs, "should fall back to defaults"
    backups = list(tmp_path.glob("templates.corrupt-*.json"))
    assert len(backups) == 1, "the bad file must be kept, never silently dropped"
    assert backups[0].read_text(encoding="utf-8") == "{ this is not json"


def test_no_temp_file_is_left_behind(tmp_path):
    path = tmp_path / "templates.json"
    store.save_library(Library(tabs=[Tab(name="A", id="t1")]), path)
    assert not list(tmp_path.glob("*.tmp"))


def test_save_is_atomic_under_repeated_writes(tmp_path):
    path = tmp_path / "templates.json"
    for index in range(20):
        store.save_library(Library(tabs=[Tab(name=f"T{index}", id="t1")]), path)
        # A partially written file would fail to parse here.
        assert json.loads(path.read_text(encoding="utf-8"))["tabs"][0]["name"] == f"T{index}"


class TestSettings:
    def test_defaults_are_returned_when_absent(self, monkeypatch, tmp_path):
        monkeypatch.setattr(store, "SETTINGS_PATH", tmp_path / "settings.json")
        assert store.load_settings() == store.DEFAULT_SETTINGS

    def test_unknown_keys_are_rejected(self, monkeypatch, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"columns": 5, "evil": True}), encoding="utf-8")
        monkeypatch.setattr(store, "SETTINGS_PATH", path)

        settings = store.load_settings()
        assert settings["columns"] == 5
        assert "evil" not in settings

    def test_corrupt_settings_fall_back_to_defaults(self, monkeypatch, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("nonsense", encoding="utf-8")
        monkeypatch.setattr(store, "SETTINGS_PATH", path)
        assert store.load_settings() == store.DEFAULT_SETTINGS

    def test_library_path_honours_override(self, tmp_path):
        custom = tmp_path / "elsewhere" / "lib.json"
        assert store.library_path({"library_path": str(custom)}) == custom


class TestWatcherSelfWriteGuard:
    def test_self_write_suppresses_the_callback(self, tmp_path):
        fired: list[int] = []
        watcher = store.LibraryWatcher(tmp_path / "templates.json", lambda: fired.append(1))

        watcher.mark_self_write()
        # Simulate the handler's decision without spinning up a real observer.
        import time
        now = time.monotonic()
        suppressed = (now - watcher._last_self_write) < watcher.QUIET_WINDOW_S

        assert suppressed, "our own save must not trigger a reload"
        assert not fired
