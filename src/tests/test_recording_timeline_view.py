"""Behaviour of the recording timeline strip (step-18 pilot).

Before this file the strip had **no coverage at all**: all nine test references
to `refresh_player_stats_timeline_ui` replaced it with a stub, so its body was
never executed by the suite. Equivalence with the pre-pilot implementation was
established separately by a differential trace over the same scenario matrix
used here; these tests are what keeps it from regressing afterwards.

Every case is built through `build_recording_timeline_view`, which calls the
component's real constructor -- no `object.__new__(MegabonkApp)`.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from core.game_state import RuntimeGameMode
from support.player_stats import FakeRecorder, build_recording_timeline_view
from ui.styles import build_qt_app_stylesheet
from ui.tabs.player_stats.recording_timeline import RecordingTimelineView


class DeferredThrottle:
    """Deterministic trailing-only throttle for stale-selection tests."""

    def __init__(self) -> None:
        self.pending = None

    def request(self, callback) -> bool:
        self.pending = callback
        return False

    @property
    def has_pending(self) -> bool:
        return self.pending is not None

    def cancel(self) -> None:
        self.pending = None

    def fire(self) -> None:
        callback, self.pending = self.pending, None
        if callback is not None:
            callback()


class RecordingTimelineRenderTests(unittest.TestCase):
    def test_idle_shows_live_stats(self) -> None:
        harness = build_recording_timeline_view()
        harness.view.refresh()

        self.assertEqual(harness.timeline_label.text, "Live stats")
        self.assertEqual(harness.slider_time_label.text, "Timeline: live stats")
        self.assertEqual(harness.record_btn.active, ("record", ""))

    def test_armed_but_not_recording_says_waiting_for_run(self) -> None:
        harness = build_recording_timeline_view(armed=True)
        harness.view.refresh()

        # The `armed` variant is the whole point: before it, this state and
        # the recording one below rendered the same red "Stop Recording".
        self.assertEqual(harness.record_btn.active, ("stop", "armed"))
        self.assertEqual(
            harness.timeline_label.text, "Recording armed | waiting for run"
        )
        self.assertEqual(
            harness.slider_time_label.text,
            "Timeline: recording armed | waiting for run",
        )

    def test_recording_without_snapshots_reports_elapsed(self) -> None:
        harness = build_recording_timeline_view(recording=True, elapsed="01:15")
        harness.view.refresh()

        self.assertEqual(harness.record_btn.active, ("stop", ""))
        self.assertEqual(harness.timeline_label.text, "Recording 01:15 | No snapshots")
        self.assertEqual(
            harness.slider_time_label.text,
            "Timeline: recording 01:15 | waiting for first snapshot",
        )

    def test_recording_while_paused_in_game_is_distinguished(self) -> None:
        """The pause state is a separate line, not the generic 'No snapshots'."""
        harness = build_recording_timeline_view(
            recording=True, waiting_mode=RuntimeGameMode.PAUSED_IN_GAME.value
        )
        harness.view.refresh()

        self.assertEqual(harness.timeline_label.text, "Recording 00:42 | Paused in game")

    def test_recording_with_snapshots_shows_range_and_selection(self) -> None:
        harness = build_recording_timeline_view(
            recording=True,
            snapshot_labels=("00:10", "00:20", "00:30"),
            selected_index=1,
        )
        harness.view.refresh()

        self.assertEqual(
            harness.timeline_label.text, "Recording 00:42 | 3 snapshots | 00:20"
        )
        self.assertEqual(
            harness.slider_time_label.text,
            "Timeline: 00:10 - 00:30 | Selected: 00:20",
        )

    def test_unselected_snapshot_renders_a_dash(self) -> None:
        harness = build_recording_timeline_view(
            recording=True, snapshot_labels=("00:10", "00:20"), selected_index=None
        )
        harness.view.refresh()

        self.assertEqual(harness.timeline_label.text, "Recording 00:42 | 2 snapshots | --")
        self.assertEqual(
            harness.slider_time_label.text, "Timeline: 00:10 - 00:20 | Selected: --"
        )

    def test_stale_selected_index_is_clamped_to_the_available_snapshots(self) -> None:
        harness = build_recording_timeline_view(
            recording=True,
            snapshot_labels=("00:10", "00:20", "00:30"),
            selected_index=99,
        )

        harness.view.refresh()

        self.assertEqual(
            harness.timeline_label.text,
            "Recording 00:42 | 3 snapshots | 00:30",
        )
        self.assertIn(("setValue", 2), harness.slider.calls)

    def test_invalid_selected_index_is_treated_as_live(self) -> None:
        harness = build_recording_timeline_view(
            recording=True,
            snapshot_labels=("00:10", "00:20", "00:30"),
        )
        harness.state["selected"] = "not-an-index"

        harness.view.refresh()

        self.assertEqual(
            harness.slider_time_label.text,
            "Timeline: 00:10 - 00:30 | Selected: --",
        )
        self.assertIn(("setValue", 2), harness.slider.calls)


class RecordingTimelineSliderTests(unittest.TestCase):
    def test_slider_enabled_and_bounded_while_recording(self) -> None:
        harness = build_recording_timeline_view(
            recording=True, snapshot_labels=("a", "b", "c"), selected_index=2
        )
        harness.view.refresh()

        self.assertIn(("setEnabled", True), harness.slider.calls)
        self.assertIn(("setMaximum", 2), harness.slider.calls)
        self.assertIn(("setValue", 2), harness.slider.calls)

    def test_single_snapshot_keeps_a_minimum_maximum_of_one(self) -> None:
        """`max(count - 1, 1)` -- a one-snapshot run must not collapse to 0."""
        harness = build_recording_timeline_view(
            recording=True, snapshot_labels=("only",), selected_index=0
        )
        harness.view.refresh()

        self.assertIn(("setMaximum", 1), harness.slider.calls)

    def test_update_slider_false_leaves_the_position_alone(self) -> None:
        harness = build_recording_timeline_view(
            recording=True, snapshot_labels=("a", "b"), selected_index=1
        )
        harness.view.refresh(update_slider=False)

        self.assertNotIn(("setValue", 1), harness.slider.calls)
        self.assertIn(("setEnabled", True), harness.slider.calls)

    def test_slider_disabled_and_reset_when_not_recording(self) -> None:
        harness = build_recording_timeline_view(snapshot_labels=("a", "b"))
        harness.view.refresh()

        self.assertIn(("setEnabled", False), harness.slider.calls)
        self.assertIn(("setMaximum", 1), harness.slider.calls)
        self.assertIn(("setValue", 0), harness.slider.calls)


class RecordingTimelineCommandTests(unittest.TestCase):
    def test_moving_the_slider_selects_and_rerenders(self) -> None:
        harness = build_recording_timeline_view(
            recording=True, snapshot_labels=("00:10", "00:20", "00:30"), selected_index=0
        )
        harness.view.handle_slider_value(2)

        self.assertEqual([2], harness.selections)
        self.assertEqual(
            harness.timeline_label.text, "Recording 00:42 | 3 snapshots | 00:30"
        )

    def test_selecting_the_current_index_is_a_no_op(self) -> None:
        harness = build_recording_timeline_view(
            recording=True, snapshot_labels=("00:10", "00:20"), selected_index=1
        )
        harness.view.handle_slider_value(1)

        self.assertEqual([], harness.selections)
        self.assertEqual([], harness.timeline_label.calls)

    def test_slider_value_is_clamped_to_the_snapshot_range(self) -> None:
        harness = build_recording_timeline_view(
            recording=True, snapshot_labels=("00:10", "00:20"), selected_index=0
        )
        harness.view.handle_slider_value(99)

        self.assertEqual([1], harness.selections)

    def test_slider_ignores_input_when_there_are_no_snapshots(self) -> None:
        harness = build_recording_timeline_view(recording=True)
        harness.view.handle_slider_value(3)

        self.assertEqual([], harness.selections)

    def test_record_button_click_reaches_the_injected_command(self) -> None:
        harness = build_recording_timeline_view()

        harness.view._on_toggle_recording()

        self.assertEqual(1, harness.toggles)

    def test_queued_selection_is_discarded_after_snapshot_store_replacement(self) -> None:
        throttle = DeferredThrottle()
        harness = build_recording_timeline_view(
            recording=True,
            snapshot_labels=("old-a", "old-b"),
            selected_index=0,
            throttle=throttle,
        )
        harness.view.handle_slider_value(1)

        harness.state["snapshots"] = [type(harness.state["snapshots"][0])("new")]
        throttle.fire()

        self.assertEqual([], harness.selections)

    def test_timeline_reset_cancels_a_queued_selection(self) -> None:
        throttle = DeferredThrottle()
        harness = build_recording_timeline_view(
            recording=True,
            snapshot_labels=("00:10", "00:20"),
            selected_index=0,
            throttle=throttle,
        )
        harness.view.handle_slider_value(1)

        harness.state["recorder"].is_recording = False
        harness.state["snapshots"] = []
        harness.view.refresh()
        throttle.fire()

        self.assertEqual([], harness.selections)


class RecordingTimelineInitialPaintTests(unittest.TestCase):
    """`install()` must render the real state, not the caption baked into it.

    Nothing else paints this strip at startup -- every other caller of
    `refresh_player_stats_timeline_ui` is a recording-lifecycle event, a
    capture, a scanner event or a dialog. Without an initial render the button
    claims "Start Recording" while `AUTO_START_RECORDING` has already armed the
    app, so the first click takes the stop branch and only the second arms.
    That was reported as "needs a double click to start" on 2026-07-19.

    Drives the real `install()` against real Qt widgets, because the bug was
    precisely that `install()` did not render -- a test using `attach_widgets`
    would not have caught it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def _install(self, *, armed: bool, recording: bool):
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        holder = QWidget()
        layout = QVBoxLayout(holder)
        view = RecordingTimelineView(
            recorder=lambda: FakeRecorder(is_recording=recording, elapsed="00:07"),
            snapshots=lambda: [],
            selected_index=lambda: None,
            recording_armed=lambda: armed,
            waiting_mode=lambda: None,
            on_toggle_recording=lambda: None,
            on_snapshot_selected=lambda index: None,
        )
        view.install(layout)
        # Keep `holder` alive: Qt deletes child widgets with their parent, and
        # a collected parent turns every later read into a RuntimeError.
        self._holder = holder
        return view

    def test_armed_at_startup_is_shown_immediately(self) -> None:
        view = self._install(armed=True, recording=False)

        self.assertEqual("stop", view._record_btn.active_key())
        self.assertEqual("armed", view._record_btn.variant())
        self.assertEqual(
            "Recording armed | waiting for run", view._timeline_label.text()
        )

    def test_idle_at_startup_still_reads_start_recording(self) -> None:
        view = self._install(armed=False, recording=False)

        self.assertEqual("record", view._record_btn.active_key())
        self.assertEqual("Live stats", view._timeline_label.text())

    def test_already_recording_at_startup_is_shown_immediately(self) -> None:
        view = self._install(armed=False, recording=True)

        self.assertEqual("stop", view._record_btn.active_key())
        self.assertEqual("", view._record_btn.variant())
        self.assertEqual("Recording 00:07 | No snapshots", view._timeline_label.text())

    def test_the_control_is_one_size_in_all_three_states(self) -> None:
        """Under the real stylesheet, which is the only place it can fail.

        The button this replaced measured 290x33 as `Start Recording (F8)` and
        221x37 as `Stop Recording`, with no size floor anywhere. Fixed captions
        are only half of what keeps that from coming back: the QSS must not
        change their typography with state either. The `armed` variant was
        written 700/0 against the plain halt's 800/0.3 and moved the control by
        3px on arming -- caught here, not by eye.
        """
        from PySide6.QtWidgets import QApplication

        QApplication.instance().setStyleSheet(build_qt_app_stylesheet(""))
        sizes = []
        for armed, recording in ((False, False), (True, False), (False, True)):
            view = self._install(armed=armed, recording=recording)
            view._record_btn.ensurePolished()
            sizes.append(view._record_btn.sizeHint())

        self.assertEqual(1, len(set((size.width(), size.height()) for size in sizes)), sizes)

    def test_destroying_the_tab_cancels_a_trailing_slider_callback(self) -> None:
        # DeferredDelete is deliberately isolated. Running it against the one
        # QApplication shared by the full suite would also flush deferred
        # deletion from unrelated Qt tests and can terminate the test process
        # before unittest has a chance to report anything.
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtCore import QCoreApplication, QEvent
            from PySide6.QtTest import QTest
            from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
            from tests.support.player_stats import FakeRecorder
            from ui.tabs.player_stats.recording_timeline import RecordingTimelineView

            app = QApplication([])
            holder = QWidget()
            layout = QVBoxLayout(holder)
            state = {
                "snapshots": [
                    type("Snapshot", (), {"time_label": "00:10"})(),
                    type("Snapshot", (), {"time_label": "00:20"})(),
                ],
                "selected": None,
            }
            selections = []
            def select(index):
                selections.append(index)
                state["selected"] = index

            view = RecordingTimelineView(
                recorder=lambda: FakeRecorder(is_recording=True, elapsed="00:20"),
                snapshots=lambda: state["snapshots"],
                selected_index=lambda: state["selected"],
                recording_armed=lambda: False,
                waiting_mode=lambda: None,
                on_toggle_recording=lambda: None,
                on_snapshot_selected=select,
            )
            view.install(layout)
            selections.clear()
            state["selected"] = 1
            view.handle_slider_value(0)
            assert selections == [], selections

            holder.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            QTest.qWait(60)
            QCoreApplication.processEvents()
            assert selections == [], selections
            print("BLOCK8_QT_CONTEXT_DELETE_OK")
            """
        )
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("BLOCK8_QT_CONTEXT_DELETE_OK", result.stdout)


class RecordingTimelineEncapsulationTests(unittest.TestCase):
    def test_widgets_are_private_to_the_component(self) -> None:
        """The point of the pilot: no public widget attributes to reach through."""
        harness = build_recording_timeline_view()

        public = [
            name
            for name in vars(harness.view)
            if not name.startswith("_")
        ]
        self.assertEqual([], public)

    def test_component_holds_no_reference_to_an_owner(self) -> None:
        """If an ambient owner ever gets injected, this is where it shows up."""
        harness = build_recording_timeline_view()

        for name, value in vars(harness.view).items():
            self.assertFalse(
                hasattr(value, "player_stats_vod_snapshots"),
                f"{name} looks like an ambient app namespace",
            )


if __name__ == "__main__":
    unittest.main()
