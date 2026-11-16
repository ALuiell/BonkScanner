"""The heavy tabs are not built until someone opens them.

The tab is 741 of the window's 1888 widgets -- more than a third of the whole
application -- and every launch paid for them whether or not the tab was ever
opened. Measured on the real library that is about 12 MB and most of a second
of startup.

What is deferred is the contents, not the tab: the bar's order is part of the
design, and a tab that appears late is a tab that moves. Live, Recordings and
Compare first paint lightweight loading rings, then yield between construction
batches so the tab switch itself remains responsive.

Run in a subprocess against the real application, as `test_startup_window_order`
does. A fake tab widget would prove nothing here: the trigger is Qt's own
`showEvent`, which only fires in a real widget hierarchy, and the ordering that
makes the deferral safe -- the page is shown before `currentChanged` reaches the
router -- is Qt's, not ours.
"""

from __future__ import annotations

from importlib.util import find_spec
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
from core.localization import LANGUAGE_CONFIG_KEY
from gui_app import MegabonkApp

unhandled = []
def record_unhandled(exc_type, exc_value, exc_traceback):
    formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    unhandled.append(formatted)
    print(formatted, file=sys.stderr)
sys.excepthook = record_unhandled

config.save_config = lambda _candidate: config.ConfigSaveResult(True)
config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED = True
config.user_config[LANGUAGE_CONFIG_KEY] = "en"
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


compare_index, page = page_for("Compare")
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
        """All three tabs exist without eagerly building their workspaces.

        The tabs keep only their small loading shells eager so Qt can give
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

            validator_tabs = ["Validator"] if app.coordinator.validator is not None else []
            assert [tabs.tabText(index) for index in range(tabs.count())] == [
                "Logs", "Session", "Live", "Recordings", *validator_tabs,
                "Compare", "OBS", "Twitch", "Game Overlay",
            ]

            # And the heavy workspace widgets do not exist yet. `__init__`
            # declares them None precisely so this state is representable.
            assert app._compare_runs_view._timeline is None
            assert app._compare_runs_view._detail_tabs is None
            assert app._recordings_view._body_splitter is None
            assert app._recordings_view._scrubber is None

            live_page = page_for("Live")[1]
            assert not live_page.is_built
            assert live_page.findChild(QWidget, "LiveStatsLoadingSpinner") is not None
            assert app._player_stats_view._detail_tabs is None
            """
        )

    def test_opening_live_reads_stats_and_renders_an_existing_recording(self) -> None:
        self._run(
            """
            from types import SimpleNamespace

            live_index, live_page = page_for("Live")
            view = app._player_stats_view
            recorder = app.player_stats_vod_recorder
            refreshes = []
            app.refresh_live_player_stats_now = lambda: refreshes.append(view.is_ready)
            recorder.is_recording = True
            app.player_stats_vod_snapshots = [
                SimpleNamespace(time_label="00:10"),
                SimpleNamespace(time_label="00:20"),
                SimpleNamespace(time_label="00:30"),
            ]

            try:
                # A recording can change while the Logs tab is selected.
                view.refresh_player_stats_timeline_ui()
                view.set_recording_status_text("Existing recording")
                assert view._recording_timeline is None
                tabs.setCurrentIndex(live_index)
                app._tab_router._refresh_right_tab_after_switch()
                assert not refreshes
                assert not app._is_live_stats_tab_active()
                assert live_page.findChild(QWidget, "LiveStatsLoadingPage").isVisible()

                deadline = time.monotonic() + 10
                while (not live_page.is_built or not refreshes) and time.monotonic() < deadline:
                    qt.processEvents()
                    time.sleep(0.002)
                assert live_page.is_built and view.is_ready
                assert app._is_live_stats_tab_active()
                assert refreshes == [True], refreshes
                assert view._status_label.text() == "Existing recording"
                timeline = view._recording_timeline
                assert timeline._slider.isEnabled()
                assert timeline._slider.maximum() == 2
                assert timeline._slider.value() == 2
                assert app.player_stats_selected_snapshot_index is None
            finally:
                recorder.is_recording = False
            """
        )

    @unittest.skipUnless(find_spec("bonkscanner_validator"), "Validator package is optional")
    def test_validator_strip_stays_inside_the_deferred_live_page(self) -> None:
        self._run(
            """
            from unittest.mock import patch

            validator = app._validator_tab
            assert validator is not None
            validator.stop_polling()
            live_index, live_page = page_for("Live")
            snapshot = {
                "state": "waiting_game", "error": None, "enabled": True,
                "busy": False, "coverage": {}, "delivery": None, "active_run_id": None,
            }
            with patch.object(validator.controller, "try_snapshot", return_value=snapshot):
                validator._poll()
                assert validator._live_strip is None
                assert not any(w.objectName() == "validatorReportStrip" and w.isVisible()
                               for w in qt.topLevelWidgets())

                validator.header_button.click()
                assert tabs.currentWidget() is validator
                tabs.setCurrentIndex(live_index)
                deadline = time.monotonic() + 10
                while not live_page.is_built and time.monotonic() < deadline:
                    qt.processEvents()
                    time.sleep(0.002)
                assert live_page.is_built

                validator._poll()
                strip = validator._live_strip
                assert strip is not None and live_page.isAncestorOf(strip)
                assert strip.isVisible() and not strip.isWindow()
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
