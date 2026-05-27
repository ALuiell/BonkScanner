from __future__ import annotations

import unittest

from live_run_tracker import LiveRunSnapshot, LiveRunTracker
from overlay_state import build_overlay_state


class OverlayStateTests(unittest.TestCase):
    def test_overlay_state_has_json_friendly_missing_data(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        state = build_overlay_state(
            tracker,
            {
                "template": "compact",
                "poll_ms": 500,
                "widgets": [{"id": "run_timer", "enabled": True, "order": 10}],
            },
        )

        self.assertEqual(state["status"], "waiting")
        self.assertEqual(state["run_timer_label"], "--")
        self.assertEqual(state["widgets"]["run_timer"]["enabled"], True)
        self.assertEqual(state["stage_summary"][0]["stage"], "1")

    def test_overlay_state_includes_tracker_counters_and_live_fields(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        tracker.update(
            LiveRunSnapshot(
                captured_at=1.0,
                stats={},
                items=("Anvil x1",),
                game_time_seconds=5.0,
                mob_kills=42,
                player_level=7,
                map_seed=1,
                stage_ptr=10,
                chests_per_minute=2.5,
            )
        )
        state = build_overlay_state(tracker, {"widgets": []})

        self.assertEqual(state["status"], "live")
        self.assertEqual(state["run_timer_label"], "00:05")
        self.assertEqual(state["mob_kills"], 42)
        self.assertEqual(state["player_level"], 7)
        self.assertEqual(state["tracked_items"][0]["count"], 1)

    def test_overlay_stage_summary_uses_structured_rarity_counts(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        tracker.update(
            LiveRunSnapshot(
                captured_at=1.0,
                stats={},
                items=(),
                game_time_seconds=1.0,
                map_seed=1,
                stage_ptr=10,
            )
        )
        tracker.update(
            LiveRunSnapshot(
                captured_at=2.0,
                stats={},
                items=("Anvil x1",),
                game_time_seconds=2.0,
                map_seed=1,
                stage_ptr=10,
            )
        )

        state = build_overlay_state(tracker, {"widgets": []})

        self.assertEqual(state["stage_summary"][0]["items"][0]["rarity"], "LEGENDARY")
        self.assertEqual(state["stage_summary"][0]["items"][0]["count"], 1)


if __name__ == "__main__":
    unittest.main()