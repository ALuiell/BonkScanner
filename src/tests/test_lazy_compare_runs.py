"""Compare Runs is not built until someone opens it.

The tab is 741 of the window's 1888 widgets -- more than a third of the whole
application -- and every launch paid for them whether or not the tab was ever
opened. Measured on the real library that is about 12 MB and most of a second
of startup.

What is deferred is the contents, not the tab: the bar's order is part of the
design, and a tab that appears late is a tab that moves. So the assertions are
in two halves -- the tab is in the bar and its page is empty, and opening it
fills the page in.

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
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import src
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget
from app import config
from gui_app import MegabonkApp

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
compare_index = [
    index for index in range(tabs.count()) if tabs.tabText(index) == "Compare Runs"
][0]
page = tabs.widget(compare_index)
"""

EPILOGUE = """
# In-process teardown of a real app exits 0xC0000409 often enough to make this
# flaky; see the same note in `test_startup_window_order`.
os._exit(0)
"""


class LazyCompareRunsTests(unittest.TestCase):
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

    def test_the_tab_is_in_the_bar_with_nothing_built_inside_it(self) -> None:
        """Both halves, because either alone is the wrong outcome.

        A page with children would mean the deferral did not happen; a missing
        tab would mean it went too far and moved the bar.
        """
        self._run(
            """
            assert page is not None
            assert not page.is_built, "the page built itself before anyone opened it"
            assert page.findChildren(QWidget) == [], len(page.findChildren(QWidget))

            # The tab bar is unchanged: same position, same caption.
            assert tabs.tabText(compare_index) == "Compare Runs"

            # And the widgets the tab will own do not exist yet. `__init__`
            # declares them None precisely so this state is representable.
            view = app._compare_runs_view
            assert view._timeline is None
            assert view._detail_tabs is None
            """
        )

    def test_opening_the_tab_builds_it_in_full(self) -> None:
        """Deferred, not dropped -- the whole workspace has to arrive.

        The seven detail pages are the check rather than a widget count: a count
        would fail on any honest change to the tab's contents, where a missing
        page is the actual failure this guards.
        """
        self._run(
            """
            tabs.setCurrentIndex(compare_index)
            qt.processEvents()

            assert page.is_built
            assert page.findChildren(QWidget), "opening the tab built nothing"

            view = app._compare_runs_view
            assert view._timeline is not None
            assert view._detail_tabs is not None
            assert [
                view._detail_tabs.tabText(index)
                for index in range(view._detail_tabs.count())
            ] == ["Overview", "Stats", "Stages", "Items", "Weapons", "Tomes", "Chaos"]
            assert view._run_a_list_frame is not None
            assert view._run_b_list_frame is not None
            assert view._swap_btn is not None
            """
        )

    def test_the_router_finds_the_widgets_when_the_switch_reaches_it(self) -> None:
        """The ordering the whole deferral rests on.

        `_refresh_recording_tabs` runs off `currentChanged` and calls straight
        into this tab. Qt shows the incoming page before it emits that signal,
        so the widgets are there by the time the router asks -- but that is Qt's
        ordering, not ours, and this is what would catch it changing.
        """
        self._run(
            """
            seen = {}

            def spy(_index):
                seen["built"] = page.is_built

            tabs.currentChanged.connect(spy)
            tabs.setCurrentIndex(compare_index)
            qt.processEvents()

            assert seen.get("built") is True, seen

            # And the router's own call is safe to make now.
            app._tab_router._refresh_recording_tabs()
            qt.processEvents()
            """
        )


if __name__ == "__main__":
    unittest.main()
