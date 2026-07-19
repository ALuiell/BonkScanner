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

import unittest

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from core.game_state import RuntimeGameMode
from support.player_stats import build_recording_timeline_view


class RecordingTimelineRenderTests(unittest.TestCase):
    def test_idle_shows_live_stats(self) -> None:
        harness = build_recording_timeline_view()
        harness.view.refresh()

        self.assertEqual(harness.timeline_label.text, "Live stats")
        self.assertEqual(harness.slider_time_label.text, "Timeline: live stats")
        self.assertIn("Start Recording", harness.record_btn.text)

    def test_armed_but_not_recording_says_waiting_for_run(self) -> None:
        harness = build_recording_timeline_view(armed=True)
        harness.view.refresh()

        self.assertEqual(harness.record_btn.text, "Stop Recording")
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

        self.assertEqual(harness.record_btn.text, "Stop Recording")
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
