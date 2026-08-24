from __future__ import annotations

import src

import unittest

from app import config
from core.tracker.live_run import LiveRunSnapshot, LiveRunTracker
from projections.obs import build_overlay_state


class _DisplayValue:
    def __init__(self, display_value: str) -> None:
        self.display_value = display_value


class OverlayStateTests(unittest.TestCase):
    def test_build_progression_recovers_from_the_editor_resize_artifact(self) -> None:
        overlay = config.normalize_overlay_config(
            {
                "widgets": [
                    {
                        "id": "build_progression",
                        "width": 60,
                        "height": 40,
                    }
                ]
            }
        )

        build = next(
            widget for widget in overlay["widgets"]
            if widget["id"] == "build_progression"
        )
        self.assertNotIn("width", build)
        self.assertNotIn("height", build)

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

    def test_overlay_state_treats_non_finite_runtime_values_as_unknown(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        tracker.update(
            LiveRunSnapshot(
                captured_at=1.0,
                stats={},
                game_time_seconds=5.0,
                map_seed=1,
                stage_ptr=10,
                chests_per_minute=float("inf"),
            )
        )

        state = build_overlay_state(tracker, {"widgets": []})

        self.assertIsNone(state["chests_per_minute"])

    def test_overlay_uses_the_same_fast_kill_total_as_stage_summary(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        tracker.update(
            LiveRunSnapshot(
                captured_at=1.0,
                stats={},
                game_time_seconds=10.0,
                mob_kills=1_000,
                map_seed=1,
                stage_ptr=10,
            )
        )
        tracker.update_fast_run_timer(11.0)
        tracker.track_kills(11.0, 1_250)

        state = build_overlay_state(tracker, {"widgets": []})

        self.assertEqual(state["mob_kills"], 1_250)
        self.assertEqual(state["stage_summary"][0]["kills"], "1,250")

    def test_overlay_widget_float_settings_reject_non_finite_values(self) -> None:
        state = build_overlay_state(
            LiveRunTracker(clock=lambda: 123.0),
            {
                "widgets": [
                    {
                        "id": "stats",
                        "scale": float("nan"),
                        "background_opacity": float("inf"),
                    }
                ]
            },
        )

        self.assertEqual(state["widgets"]["stats"]["scale"], 1.0)
        self.assertEqual(state["widgets"]["stats"]["background_opacity"], 0.0)

    def test_overlay_state_ships_the_rarity_colours_the_model_owns(self) -> None:
        """The page must not hold a second copy of the tier colours.

        `overlay.css` used to carry its own table on `.stage-item-count`, two of
        whose four entries disagreed with `ITEM_RARITY_COLOR_MAP` -- so a "rare"
        count in the stage table and a "rare" figure in the Luck widget, one
        overlay apart, were different colours. Compared against the map itself
        rather than against literals, because a test that restates the hexes
        would pass a fresh divergence straight through.
        """
        from core.item_metadata import ITEM_RARITY_COLOR_MAP
        from core.luck_rarity import LUCK_RARITY_ORDER

        tracker = LiveRunTracker(clock=lambda: 123.0)
        state = build_overlay_state(tracker, {})

        self.assertEqual(
            state["rarity_colors"],
            {rarity: ITEM_RARITY_COLOR_MAP[rarity] for rarity in LUCK_RARITY_ORDER},
        )
        self.assertEqual(
            state["rarity_labels"],
            {
                "LEGENDARY": "Legendary",
                "RARE": "Epic",
                "UNCOMMON": "Rare",
                "COMMON": "Common",
            },
        )

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
        self.assertEqual(state["stage_summary"][0]["items"][0]["label"], "Legendary")
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
                {"label": "Luck", "display_label": "Luck", "value": "15%"},
                {"label": "Damage", "display_label": "DMG", "value": "2x"},
            ],
        )

    def test_overlay_state_stats_use_short_labels(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        tracker.update(
            LiveRunSnapshot(
                captured_at=1.0,
                stats={
                    "Attack Speed": _DisplayValue("1.4x"),
                    "Crit Damage": _DisplayValue("2.5x"),
                    "Powerup Drop Chance": _DisplayValue("12%"),
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
                        "selected_stats": [
                            "Attack Speed",
                            "Crit Damage",
                            "Powerup Drop Chance",
                        ],
                    }
                ],
            },
        )

        self.assertEqual(
            [row["display_label"] for row in state["stats"]],
            ["AS", "CritDMG", "PDC"],
        )
        # The canonical label stays intact so selectors and templates that key
        # off it keep working.
        self.assertEqual(
            [row["label"] for row in state["stats"]],
            ["Attack Speed", "Crit Damage", "Powerup Drop Chance"],
        )

    def test_overlay_state_stats_keep_full_labels_when_opted_out(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 123.0)
        tracker.update(
            LiveRunSnapshot(
                captured_at=1.0,
                stats={
                    "Attack Speed": _DisplayValue("1.4x"),
                    "Powerup Drop Chance": _DisplayValue("12%"),
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
                        "selected_stats": ["Attack Speed", "Powerup Drop Chance"],
                        "short_stat_labels": False,
                    }
                ],
            },
        )

        self.assertEqual(
            [row["display_label"] for row in state["stats"]],
            ["Attack Speed", "Powerup Drop Chance"],
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
        # Instant KPS is measured over the last ~1 game second of history, so
        # this sample is what makes `current` differ from the averages; without
        # it the nearest baseline is 60 s back and all four readings converge.
        tracker.track_kills(119.0, 640)
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
                "current": 60,
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

    def test_status_card_is_off_by_default_and_reaches_the_payload(self) -> None:
        # `overlay.js` reads this flag; if the normalization ever drops it the
        # card silently comes back and starts shoving widgets around again.
        overlay = config.normalize_overlay_config({})
        self.assertIs(overlay["style"]["show_status"], False)

        # An older saved config has a `style` block without the key at all.
        migrated = config.normalize_overlay_config(
            {"style": {"scale": 1.0, "accent_color": "#FFFFFF"}}
        )
        self.assertIs(migrated["style"]["show_status"], False)
        self.assertEqual(migrated["style"]["accent_color"], "#FFFFFF")

        state = build_overlay_state(LiveRunTracker(clock=lambda: 1.0), overlay)
        self.assertIs(state["style"]["show_status"], False)

    def test_status_card_opt_in_survives_normalization(self) -> None:
        overlay = config.normalize_overlay_config({"style": {"show_status": True}})
        self.assertIs(overlay["style"]["show_status"], True)


class OverlayStatusLoggingTests(unittest.TestCase):
    """The overlay is deliberately silent through a restart, so the app log is
    the only place a genuinely stuck feed becomes visible."""

    def _overlay(self):
        from gui_overlay import Overlay

        overlay = Overlay.__new__(Overlay)
        overlay._last_logged_overlay_status = None
        overlay.logged = []
        overlay._log_port = lambda message, tag=None: overlay.logged.append((message, tag))
        return overlay

    def test_restart_grace_window_logs_nothing(self) -> None:
        overlay = self._overlay()

        overlay._log_overlay_status_transition("waiting")
        overlay._log_overlay_status_transition("live")
        overlay._log_overlay_status_transition("reconnecting")
        overlay._log_overlay_status_transition("live")

        self.assertEqual(overlay.logged, [])

    def test_stale_feed_logs_once_and_recovery_logs_once(self) -> None:
        overlay = self._overlay()

        overlay._log_overlay_status_transition("live")
        overlay._log_overlay_status_transition("reconnecting")
        for _repeat in range(5):
            overlay._log_overlay_status_transition("stale")

        self.assertEqual(len(overlay.logged), 1)
        self.assertEqual(overlay.logged[0][1], "warning")
        self.assertIn("holding the last known values", overlay.logged[0][0])

        overlay._log_overlay_status_transition("live")
        self.assertEqual(len(overlay.logged), 2)
        self.assertEqual(overlay.logged[1][1], "success")

    def test_lost_game_process_is_logged(self) -> None:
        overlay = self._overlay()

        overlay._log_overlay_status_transition("live")
        overlay._log_overlay_status_transition("no_game")

        self.assertEqual(len(overlay.logged), 1)
        self.assertIn("game process is gone", overlay.logged[0][0])

    def test_a_failing_log_port_never_reaches_the_caller(self) -> None:
        from gui_overlay import Overlay

        overlay = Overlay.__new__(Overlay)
        overlay._last_logged_overlay_status = None

        def explode(_message, tag=None):
            raise RuntimeError("log sink is gone")

        overlay._log_port = explode
        overlay._log_overlay_status_transition("stale")


if __name__ == "__main__":
    unittest.main()
