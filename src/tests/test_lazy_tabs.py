"""The heavy tabs are not built until someone opens them.

The tab is 741 of the window's 1888 widgets -- more than a third of the whole
application -- and every launch paid for them whether or not the tab was ever
opened. Measured on the real library that is about 12 MB and most of a second
of startup.

What is deferred is the contents, not the tab: the bar's order is part of the
design, and a tab that appears late is a tab that moves. Recordings and Compare
Runs first paint lightweight loading rings, then yield between construction
batches so the tab switch itself remains responsive.

Run in a subprocess against the real application, as `test_startup_window_order`
does. A fake tab widget would prove nothing here: the trigger is Qt's own
`showEvent`, which only fires in a real widget hierarchy, and the ordering that
makes the deferral safe -- the page is shown before `currentChanged` reaches the
router -- is Qt's, not ours.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite


PREAMBLE = """
import os
import sys
import time
import traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import src
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget
from app import config
from gui_app import MegabonkApp

unhandled = []
def record_unhandled(exc_type, exc_value, exc_traceback):
    unhandled.append(
        "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    )
sys.excepthook = record_unhandled

config.save_config = lambda *_args, **_kwargs: None
app = MegabonkApp()
qt = QApplication.instance()
app.window.show()
qt.processEvents()

tabs = [
    widget
    for widget in app.window.findChildren(QTabWidget)
    if widget.objectName() == "mainTabs"
][0]
def page_for(caption):
    index = [
        position
        for position in range(tabs.count())
        if tabs.tabText(position) == caption
    ][0]
    return index, tabs.widget(index)


compare_index, page = page_for("Compare Runs")
recordings_index, recordings_page = page_for("Recordings")
"""

EPILOGUE = """
app.on_closing()
qt.processEvents()
assert not unhandled, "\\n".join(unhandled)
"""


class LazyTabsTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = (
            textwrap.dedent(PREAMBLE)
            + textwrap.dedent(body)
            + textwrap.dedent(EPILOGUE)
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_tabs_are_registered_without_heavy_contents(self) -> None:
        """Both tabs exist, but neither pays for its heavy workspace at startup.

        Both heavy tabs keep only their tiny loading shells eager so Qt can give
        them the final viewport before the first click.
        """
        self._run(
            """
            assert page is not None
            assert not page.is_built
            assert page.findChild(QWidget, "CompareRunsLoadingPage") is not None
            assert page.findChild(QWidget, "CompareRunsLoadingSpinner") is not None

            assert recordings_page is not None
            assert not recordings_page.is_built
            assert recordings_page.findChild(QWidget, "RecordingsLoadingPage") is not None
            assert recordings_page.findChild(QWidget, "RecordingsLoadingSpinner") is not None

            # The tab bar is unchanged: same positions, same captions.
            assert tabs.tabText(compare_index) == "Compare Runs"
            assert tabs.tabText(recordings_index) == "Recordings"

            # And the heavy workspace widgets do not exist yet. `__init__`
            # declares them None precisely so this state is representable.
            assert app._compare_runs_view._timeline is None
            assert app._compare_runs_view._detail_tabs is None
            assert app._recordings_view._body_splitter is None
            assert app._recordings_view._scrubber is None

            # Live Stats is built eagerly and must stay that way: the recording
            # path writes into it with no active-tab gate. A future change that
            # defers it would land here first.
            live_page = page_for("Live Stats")[1]
            assert live_page.findChildren(QWidget), "Live Stats stopped building eagerly"
            """
        )

    def test_opening_recordings_paints_before_building_it_in_full(self) -> None:
        """The first frame is cheap, then every workspace section arrives.

        The detail pages are the check rather than a widget count: a count
        would fail on any honest change to the tab's contents, where a missing
        page is the actual failure this guards.
        """
        self._run(
            """
            tabs.setCurrentIndex(recordings_index)
            assert not recordings_page.is_built
            assert recordings_page.findChild(QWidget, "RecordingsLoadingPage") is not None
            assert recordings_page.findChild(QWidget, "RecordingsLoadingSpinner") is not None
            loading_page = recordings_page.findChild(QWidget, "RecordingsLoadingPage")
            assert loading_page.geometry() == recordings_page.rect(), (
                loading_page.geometry(),
                recordings_page.rect(),
            )
            assert loading_page.isVisible()
            workspace = recordings_page.findChild(QWidget, "RecordingsWorkspace")
            assert workspace.geometry() == recordings_page.rect(), (
                workspace.geometry(),
                recordings_page.rect(),
            )
            assert app._recordings_view._scrubber is None

            unexpected_windows = []
            class WindowShowSpy(QObject):
                def eventFilter(self, obj, event):
                    if (
                        event.type() == QEvent.Show
                        and isinstance(obj, QWidget)
                        and obj is not app.window
                        and obj.isWindow()
                    ):
                        unexpected_windows.append(
                            (type(obj).__name__, obj.objectName(), obj.windowTitle())
                        )
                    return False
            window_show_spy = WindowShowSpy()
            qt.installEventFilter(window_show_spy)

            deadline = time.monotonic() + 10.0
            while not recordings_page.is_built and time.monotonic() < deadline:
                qt.processEvents()
                if not recordings_page.is_built:
                    assert loading_page.isVisible()
                    assert loading_page.geometry() == recordings_page.rect()
                    assert workspace.geometry() == recordings_page.rect()
                time.sleep(0.002)

            assert recordings_page.is_built
            assert not loading_page.isVisible()
            assert not unexpected_windows, unexpected_windows
            assert recordings_page.findChildren(QWidget), "Recordings built nothing"
            recordings = app._recordings_view
            assert recordings._body_splitter is not None
            assert recordings._scrubber is not None
            assert recordings._list_frame is not None
            assert [
                recordings._detail_tabs.tabText(index)
                for index in range(recordings._detail_tabs.count())
            ] == ["Stats", "Loot", "Weapons", "Tomes", "Chaos", "Shrines", "Passives", "Damage Sources"]

            tabs.setCurrentIndex(compare_index)
            compare_loading_page = page.findChild(QWidget, "CompareRunsLoadingPage")
            compare_workspace = page.findChild(QWidget, "CompareRunsLoadingWorkspace")
            assert not page.is_built
            assert compare_loading_page.isVisible()
            assert compare_loading_page.geometry() == page.rect()
            assert compare_workspace.geometry() == page.rect()

            deadline = time.monotonic() + 10.0
            while not page.is_built and time.monotonic() < deadline:
                qt.processEvents()
                if not page.is_built:
                    assert compare_loading_page.isVisible()
                    assert compare_loading_page.geometry() == page.rect()
                    assert compare_workspace.geometry() == page.rect()
                time.sleep(0.002)

            assert page.is_built
            assert not compare_loading_page.isVisible()
            qt.removeEventFilter(window_show_spy)
            assert not unexpected_windows, unexpected_windows
            assert page.findChildren(QWidget), "opening the tab built nothing"

            view = app._compare_runs_view
            assert view._timeline is not None
            assert view._detail_tabs is not None
            assert [
                view._detail_tabs.tabText(index)
                for index in range(view._detail_tabs.count())
            ] == ["Overview", "Stats", "Stages", "Items", "Weapons", "Tomes", "Chaos", "Shrines", "Passives"]
            assert view._run_a_list_frame is not None
            assert view._run_b_list_frame is not None
            assert view._swap_btn is not None
            """
        )

    def test_the_router_finds_the_widgets_when_the_switch_reaches_it(self) -> None:
        """The ordering the whole deferral rests on.

        `_refresh_recording_tabs` runs off `currentChanged` while the staged
        workspace is still loading. Its calls must remain safe in that state,
        and the finished build must replay the newest chooser state.
        """
        self._run(
            """
            seen = {}

            def spy(_index):
                seen["built"] = page.is_built

            tabs.currentChanged.connect(spy)
            tabs.setCurrentIndex(compare_index)
            qt.processEvents()

            assert seen.get("built") is False, seen

            # The router's own call is safe while the widgets are still absent.
            app._tab_router._refresh_recording_tabs()
            deadline = time.monotonic() + 10.0
            while not page.is_built and time.monotonic() < deadline:
                qt.processEvents()
                time.sleep(0.002)
            assert page.is_built
            assert app._compare_runs_view._chooser_expanded
            assert app._compare_runs_view._chooser_group.isVisible()
            """
        )


if __name__ == "__main__":
    unittest.main()
