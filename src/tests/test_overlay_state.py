from __future__ import annotations

import src

import unittest

import config
from live_run_tracker import LiveRunSnapshot, LiveRunTracker
from overlay_state import build_overlay_state


class _DisplayValue:
    def __init__(self, display_value: str) -> None:
        self.display_value = display_value


class OverlayStateTests(unittest.TestCase):
    def test_overlay_tracked_items_source_defaults_to_custom_for_compatibility(self) -> None:
        overlay = config.normalize_overlay_config(
            {
                "tracked_items": [
                    {
                        "id": "custom_anvils",
                        "label": "Custom Anvils",
                        "item_names": ["Anvil"],
                        "mode": "all_run",
                    }
                ]
            }
        )

        self.assertEqual(overlay["tracked_items_source"], "custom")
        self.assertEqual(overlay["tracked_items"][0]["id"], "custom_anvils")

    def test_tracked_item_rules_normalize_combo_items(self) -> None:
        rules = config.normalize_tracked_item_rules_config(
            [
                {
                    "id": "kevin_plug",
                    "item_names": ["Kevin", "Electric Plug", "Kevin"],
                    "mode": "map_1_only",
                }
            ]
        )

        self.assertEqual(rules[0]["label"], "Kevin + Electric Plug")
        self.assertEqual(rules[0]["item_names"], ["Kevin", "Electric Plug"])

    def test_overlay_state_has_json_friendly_missing_data(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        state = build_overlay_state(
            tracker,
            {
                "template": "compact",
                "poll_ms": 500,
                "widgets": [{"id": "stage_summary", "enabled": True, "order": 10}],
            },
        )

        self.assertEqual(state["status"], "waiting")
        self.assertEqual(state["run_timer_label"], "--")
        self.assertEqual(state["widgets"]["stage_summary"]["enabled"], True)
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
        tracker.update(
            LiveRunSnapshot(
                captured_at=2.0,
                stats={},
                items=("Anvil x1",),
                game_time_seconds=6.0,
                mob_kills=42,
                player_level=7,
                map_seed=1,
                stage_ptr=10,
                chests_per_minute=2.5,
            )
        )
        state = build_overlay_state(tracker, {"widgets": []})

        self.assertEqual(state["status"], "live")
        self.assertEqual(state["run_timer_label"], "00:06")
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

    def test_overlay_state_includes_selected_stats_widget_rows(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        tracker.update(
            LiveRunSnapshot(
                captured_at=1.0,
                stats={
                    "Damage": _DisplayValue("2x"),
                    "Luck": _DisplayValue("15%"),
                    "XP Gain": _DisplayValue("1.2x"),
                },
                game_time_seconds=5.0,
                map_seed=1,
                stage_ptr=10,
            )
        )

        state = build_overlay_state(
            tracker,
            {
                "widgets": [
                    {
                        "id": "stats",
                        "enabled": True,
                        "selected_stats": ["Luck", "Damage"],
                        "max_rows": 2,
                    }
                ],
            },
        )

        self.assertEqual(
            state["stats"],
            [
                {"label": "Luck", "value": "15%"},
                {"label": "Damage", "value": "2x"},
            ],
        )

    def test_overlay_state_includes_banish_widget_rows(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        tracker.update(
            LiveRunSnapshot(
                captured_at=1.0,
                stats={},
                banishes=("Clover", "Golden Tome", "Wrench"),
                game_time_seconds=5.0,
                map_seed=1,
                stage_ptr=10,
            )
        )

        state = build_overlay_state(
            tracker,
            {
                "widgets": [
                    {
                        "id": "banishes",
                        "enabled": True,
                        "max_rows": 2,
                    }
                ],
            },
        )

        self.assertEqual(state["banishes"], ["Clover", "Golden Tome"])

    def test_overlay_state_includes_kps_metrics(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        tracker.track_kills(1.0, 100)
        tracker.track_kills(2.0, 150)
        tracker.track_kills(60.0, 400)
        tracker.track_kills(120.0, 700)

        state = build_overlay_state(
            tracker,
            {
                "widgets": [
                    {
                        "id": "kps",
                        "enabled": True,
                    }
                ],
            },
        )

        self.assertEqual(
            state["kps"],
            {
                "current": 50,
                "minute_avg": 5,
                "five_minute_avg": 5,
                "run_avg": 6,
            },
        )

    def test_overlay_state_includes_selected_kps_widget_metrics(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)

        state = build_overlay_state(
            tracker,
            {
                "widgets": [
                    {
                        "id": "kps",
                        "enabled": True,
                        "selected_kps_metrics": ["minute_avg", "run_avg"],
                    }
                ],
            },
        )

        self.assertEqual(
            state["widgets"]["kps"]["selected_kps_metrics"],
            ("minute_avg", "run_avg"),
        )

    def test_overlay_state_kps_widget_metrics_fallback_to_default_when_empty(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)

        state = build_overlay_state(
            tracker,
            {
                "widgets": [
                    {
                        "id": "kps",
                        "enabled": True,
                        "selected_kps_metrics": [],
                    }
                ],
            },
        )

        self.assertEqual(
            state["widgets"]["kps"]["selected_kps_metrics"],
            ("current", "minute_avg", "five_minute_avg", "run_avg"),
        )


if __name__ == "__main__":
    unittest.main()
