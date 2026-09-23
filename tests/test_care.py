"""Undo journal, on-disk snapshots, and library lint."""

from __future__ import annotations

from pcc import lint, store
from pcc.journal import UndoJournal
from pcc.model import Library, Tab, Template


class TestUndoJournal:
    def test_undo_returns_the_last_snapshot(self):
        j = UndoJournal()
        j.record({"v": 1}, "delete")
        snapshot, label = j.undo()
        assert snapshot == {"v": 1} and label == "delete"

    def test_snapshots_are_deep_copied(self):
        j = UndoJournal()
        data = {"tabs": [{"name": "A"}]}
        j.record(data, "x")
        data["tabs"][0]["name"] = "MUTATED"
        snapshot, _ = j.undo()
        assert snapshot["tabs"][0]["name"] == "A"

    def test_empty_undo_is_none(self):
        assert UndoJournal().undo() is None

    def test_ring_is_bounded(self):
        j = UndoJournal(limit=3)
        for i in range(10):
            j.record({"i": i}, str(i))
        assert len(j) == 3
        # The three most recent survive, newest last.
        assert j.undo()[0] == {"i": 9}


class TestSnapshots:
    def test_save_with_snapshot_writes_a_rotating_copy(self, tmp_path):
        path = tmp_path / "templates.json"
        lib = Library(tabs=[Tab(name="A", templates=[Template(title="t", body="b")])])
        store.save_library(lib, path, snapshot=True)
        snaps = list(store.snapshot_dir(path).glob("templates-*.json"))
        assert len(snaps) == 1

    def test_snapshots_are_pruned_to_the_keep_limit(self, tmp_path, monkeypatch):
        # Force distinct timestamps so each snapshot is a separate file.
        ticks = iter(f"2026010{i:02d}-000000" for i in range(1, 40))
        monkeypatch.setattr(store.time, "strftime", lambda _f: next(ticks))
        path = tmp_path / "templates.json"
        lib = Library(tabs=[Tab(name="A", templates=[])])
        for _ in range(store.SNAPSHOT_KEEP + 5):
            store.write_snapshot(lib, path)
        snaps = list(store.snapshot_dir(path).glob("templates-*.json"))
        assert len(snaps) == store.SNAPSHOT_KEEP


class TestLint:
    def _lib(self):
        return Library(tabs=[
            Tab(name="Coding", templates=[
                Template(title="Good", body="Do {{x}}", id="g"),
                Template(title="Empty", body="   ", id="e"),
                Template(title="Dup", body="a", id="d1"),
                Template(title="Dup", body="b", id="d2"),
                Template(title="Broken", body="see {{>ghost}}", id="b"),
            ]),
        ])

    def test_flags_empty_body(self):
        findings = lint.lint(self._lib())
        assert any(f.kind == "empty" and f.template_id == "e" for f in findings)

    def test_flags_duplicate_titles(self):
        findings = lint.lint(self._lib())
        dups = [f for f in findings if f.kind == "duplicate-title"]
        assert {f.template_id for f in dups} == {"d1", "d2"}

    def test_flags_broken_include(self):
        findings = lint.lint(self._lib())
        assert any(f.kind == "broken-include" and f.template_id == "b" for f in findings)

    def test_valid_include_is_not_flagged(self):
        lib = Library(tabs=[Tab(name="A", templates=[
            Template(title="Rules", body="R", id="rules"),
            Template(title="Uses", body="{{>Rules}}", id="u"),
        ])])
        assert not [f for f in lint.lint(lib) if f.kind == "broken-include"]

    def test_unused_needs_frecency_data(self):
        lib = self._lib()
        # Without a frecency source, "never used" is not asserted on a fresh lib.
        assert not [f for f in lint.lint(lib) if f.kind == "unused"]
        # With one that reports everything cold, every template is flagged.
        flagged = [f for f in lint.lint(lib, frecency=lambda _id: 0.0) if f.kind == "unused"]
        assert len(flagged) == 5

    def test_summary_of_clean_library(self):
        clean = Library(tabs=[Tab(name="A", templates=[Template(title="T", body="x")])])
        assert lint.summary(lint.lint(clean)) == "library looks healthy"

    def test_findings_are_sorted_most_severe_first(self):
        findings = lint.lint(self._lib())
        severities = [f.severity for f in findings]
        assert severities == sorted(severities)
