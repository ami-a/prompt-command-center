"""Shared fixtures.

Qt widget logic is tested on the ``offscreen`` platform plugin: it exercises the
real layout, focus and key-routing code without needing a visible desktop, which
also means these tests run on a locked or headless machine.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def library():
    from pcc.model import Library, Tab, Template

    return Library(tabs=[
        Tab(name="Coding", id="t1", templates=[
            Template(title="Refactor for readability", body="Refactor {{lang|Python}}", id="p1"),
            Template(title="Explain this code", body="Explain {{code}}", id="p2"),
            Template(title="Write tests", body="No slots here", id="p3"),
            Template(title="Debug", body="Debug {{err}}", id="p4"),
            Template(title="Review", body="Review it", id="p5"),
        ]),
        Tab(name="Writing", id="t2", templates=[
            Template(title="Summarise", body="Summarise {{text}}", id="p6"),
            Template(title="Translate", body="Translate to {{lang|Hebrew}}", id="p7"),
        ]),
    ])


@pytest.fixture
def settings(tmp_path):
    from pcc.store import DEFAULT_SETTINGS

    return {**DEFAULT_SETTINGS, "library_path": str(tmp_path / "templates.json"), "columns": 3}


def _destroy(qapp, window) -> None:
    """Tear a palette down for real.

    ``close()`` alone only hides it. A surviving window still receives every
    ``QApplication.setStyleSheet`` re-polish, so leaked windows turn the suite
    quadratic -- which is how the app-wide event-filter leak was found.
    """
    window.close()
    window.deleteLater()
    qapp.processEvents()


@pytest.fixture
def destroy(qapp):
    """Callable used by tests that build their own palettes."""
    return lambda window: _destroy(qapp, window)


@pytest.fixture
def usage(tmp_path):
    """A UsageStore rooted in the test's tmp dir, never the real %APPDATA%."""
    from pcc.usage import UsageStore

    return UsageStore(tmp_path / "usage.json")


@pytest.fixture
def palette(qapp, library, settings, usage):
    from pcc.ui.palette import PaletteWindow

    window = PaletteWindow(library, settings, usage=usage)
    yield window
    _destroy(qapp, window)
