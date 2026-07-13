from __future__ import annotations

import src

import unittest
from types import SimpleNamespace

from gui_in_game_overlay_render import (
    build_event_timer_overlay_html,
    build_stats_overlay_html,
)


class InGameOverlayRenderTests(unittest.TestCase):
    def test_stats_overlay_uses_shared_stat_abbreviations(self) -> None:
        snapshot = SimpleNamespace(
            stats={
                "Damage": SimpleNamespace(value=1.5, display_value="150%"),
                "Powerup Drop Chance": SimpleNamespace(value=0.2, display_value="+20%"),
            },
        )

        html = build_stats_overlay_html(
            snapshot,
            ["Damage", "Powerup Drop Chance"],
            0,
            0.0,
            600.0,
            False,
        )

        self.assertIn("DMG:", html)
        self.assertIn("PDC:", html)
        self.assertIn("<table", html)
        self.assertNotIn("Damage:", html)
        self.assertNotIn("Powerup Drop Chance:", html)

    def test_stats_overlay_aligns_values_by_longest_displayed_label(self) -> None:
        snapshot = SimpleNamespace(
            stats={
                "Damage": SimpleNamespace(value=1.5, display_value="150%"),
                "Projectile Speed": SimpleNamespace(value=1.2, display_value="1.2x"),
            },
        )

        html = build_stats_overlay_html(
            snapshot,
            ["Damage", "Projectile Speed"],
            0,
            0.0,
            600.0,
            False,
        )

        self.assertIn("width='90'", html)
        self.assertIn("DMG:", html)
        self.assertIn("ProjSpeed:", html)

    def test_stats_overlay_uses_post_two_minute_difficulty_cap(self) -> None:
        snapshot = SimpleNamespace(
            stats={
                "Difficulty": SimpleNamespace(value=5.0, display_value="500%"),
            },
        )

        early_html = build_stats_overlay_html(
            snapshot,
            ["Difficulty"],
            0,
            719.0,
            600.0,
            False,
        )
        late_html = build_stats_overlay_html(
            snapshot,
            ["Difficulty"],
            0,
            720.0,
            600.0,
            False,
        )

        self.assertIn("500% / 571%", early_html)
        self.assertIn("#16e7ff", early_html)
        self.assertIn("500% / 495%", late_html)
        self.assertIn("#ff4d4d", late_html)

    def test_stats_overlay_clamps_xp_gain_to_cap(self) -> None:
        snapshot = SimpleNamespace(
            stats={
                "XP Gain": SimpleNamespace(value=12.5, display_value="12.5x"),
            },
        )

        html = build_stats_overlay_html(
            snapshot,
            ["XP Gain"],
            0,
            0.0,
            600.0,
            False,
        )

        self.assertIn("10x / 10x", html)
        self.assertIn("#ff4d4d", html)
        self.assertNotIn("12.5x", html)

    def test_event_timer_uses_stage_timestamp_for_boss_warning(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            170.0,
            600.0,
            False,
            warning_seconds=15,
        )

        self.assertIn("Boss at 7:00", html)

    def test_event_timer_uses_minimum_thirty_second_window_for_waves(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            220.0,
            600.0,
            False,
            warning_seconds=15,
        )

        self.assertIn("Wave at 6:00", html)

    def test_event_timer_formats_active_wave_countdown(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            250.0,
            600.0,
            False,
            warning_seconds=15,
        )

        self.assertIn("Wave Active: 30s", html)

    def test_event_timer_does_not_use_timeline_marker_as_map_duration_at_game_start(self) -> None:
        # stage_time_seconds is a live timeline marker. At game start it may
        # contain a small/current marker, but the stage still has its full
        # 600-second event schedule ahead of it.
        html = build_event_timer_overlay_html(
            0,
            0.0,
            30.0,
            False,
            warning_seconds=15,
        )

        self.assertNotIn("Wave Active", html)
        self.assertNotIn("Boss at", html)

    def test_event_timer_graveyard_behavior(self) -> None:
        # 1. When graveyard events are not active: should hide/return empty string
        html = build_event_timer_overlay_html(
            0,
            170.0,
            960.0,
            is_graveyard=True,
            warning_seconds=15,
            graveyard_main_map_events_active=False,
        )
        self.assertEqual(html, "")

        # 2. When graveyard events are active and not in crypt:
        # Test warning at 175s elapsed (remaining time 785s, boss event at 780s remaining / 13:00)
        # Warning seconds = 15. remaining_time is 785s, which is 5s before 780s boss event.
        html_warning = build_event_timer_overlay_html(
            0,
            175.0,
            960.0,
            is_graveyard=True,
            warning_seconds=15,
            graveyard_main_map_events_active=True,
        )
        self.assertIn("Boss at 13:00", html_warning)

        # Test active wave countdown at 250s elapsed (remaining time 710s, wave event at 720s remaining / 12:00 with 30s duration)
        # Wave is active from 720s remaining to 690s remaining.
        # The overlay intentionally shows the static wave duration so it does
        # not drift relative to the game's own wave UI.
        html_active = build_event_timer_overlay_html(
            0,
            250.0,
            960.0,
            is_graveyard=True,
            warning_seconds=15,
            graveyard_main_map_events_active=True,
        )
        self.assertIn("Wave Active: 30s", html_active)

    def test_event_timer_returns_preview_in_edit_mode_when_inactive(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            0.0,
            0.0,
            False,
            warning_seconds=15,
            edit_mode=True,
        )

        self.assertIn("Event Timer (preview)", html)

    def test_event_timer_formats_boss_warning_with_static_timestamp_for_fractional_seconds(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            170.6,
            600.0,
            False,
            warning_seconds=15,
        )

        self.assertIn("Boss at 7:00", html)

    def test_event_timer_keeps_active_wave_duration_static_for_fractional_seconds(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            250.4,
            600.0,
            False,
            warning_seconds=15,
        )

        self.assertIn("Wave Active: 30s", html)


if __name__ == "__main__":
    unittest.main()
