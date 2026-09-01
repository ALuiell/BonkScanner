from __future__ import annotations

import src

import unittest
from types import SimpleNamespace

from projections.in_game_html import (
    build_event_timer_overlay_html,
    build_stats_overlay_html,
    build_weapon_tracker_overlay_html,
)
from core.stats.weapon_tracker import WeaponTrackerMetric, WeaponTrackerRow


class InGameOverlayRenderTests(unittest.TestCase):
    def _weapon_rows(self):
        return (
            WeaponTrackerRow(
                weapon_id=23,
                name="Katana",
                level=4,
                metrics=(
                    WeaponTrackerMetric("damage", 12, "DMG", 100.0),
                    WeaponTrackerMetric("projectile_count", 16, "PROJ", 2.0),
                    WeaponTrackerMetric("size", 9, "SIZE", 1.4),
                ),
            ),
        )

    def test_weapon_tracker_compact_is_one_row_without_level_or_heading(self) -> None:
        html = build_weapon_tracker_overlay_html(
            self._weapon_rows(), layout="compact"
        )

        self.assertIn("Katana", html)
        self.assertIn("DMG", html)
        self.assertIn("100", html)
        self.assertIn("PROJ", html)
        self.assertIn("×1.4", html)
        self.assertNotIn("Lv.4", html)
        self.assertNotIn("Weapons", html)
        self.assertEqual(html.count("<tr>"), 1)

    def test_weapon_tracker_detailed_shows_level_and_metric_rows(self) -> None:
        html = build_weapon_tracker_overlay_html(
            self._weapon_rows(), layout="detailed"
        )

        self.assertIn("Katana", html)
        self.assertIn("Lv.4", html)
        self.assertEqual(html.count("<tr>"), 4)
        self.assertNotIn("Weapons", html)

    def test_weapon_tracker_escapes_weapon_names(self) -> None:
        rows = (
            WeaponTrackerRow(
                weapon_id=1,
                name="A&B <Bow>",
                level=1,
                metrics=(WeaponTrackerMetric("damage", 12, "DMG", 10.0),),
            ),
        )

        html = build_weapon_tracker_overlay_html(rows)

        self.assertIn("A&amp;B &lt;Bow&gt;", html)
        self.assertNotIn("A&B <Bow>", html)

    def test_weapon_tracker_edit_mode_status_messages_are_exact(self) -> None:
        for message in (
            "No Weapon Stats Selected",
            "Waiting for Weapon Data",
            "No Matching Weapon Stats",
        ):
            with self.subTest(message=message):
                html = build_weapon_tracker_overlay_html(
                    (), edit_mode=True, status_message=message
                )
                self.assertIn("Weapons", html)
                self.assertIn(message, html)

    def test_weapon_tracker_normal_empty_state_is_hidden_without_heading(self) -> None:
        html = build_weapon_tracker_overlay_html((), edit_mode=False)

        self.assertEqual(html, "")
        self.assertNotIn("Weapons", html)

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

    def test_stats_overlay_caps_graveyard_difficulty_like_tier_one_stage_zero(self) -> None:
        snapshot = SimpleNamespace(
            stats={
                "Difficulty": SimpleNamespace(value=5.0, display_value="500%"),
            },
        )

        # The Graveyard boundary is the fixed 960 s main-map duration plus the
        # two ghost minutes, regardless of the duration the snapshot carries.
        early_html = build_stats_overlay_html(
            snapshot,
            ["Difficulty"],
            2,
            1079.0,
            480.0,
            True,
        )
        late_html = build_stats_overlay_html(
            snapshot,
            ["Difficulty"],
            2,
            1080.0,
            480.0,
            True,
        )

        self.assertIn("500% / 571%", early_html)
        self.assertIn("#16e7ff", early_html)
        self.assertIn("500% / 495%", late_html)
        self.assertIn("#ff4d4d", late_html)

    def test_stats_overlay_ignores_stage_index_tiers_on_graveyard(self) -> None:
        snapshot = SimpleNamespace(
            stats={
                "Difficulty": SimpleNamespace(value=5.0, display_value="500%"),
            },
        )

        for stage_index in (0, 1, 2):
            with self.subTest(stage_index=stage_index):
                html = build_stats_overlay_html(
                    snapshot,
                    ["Difficulty"],
                    stage_index,
                    0.0,
                    960.0,
                    True,
                )
                self.assertIn("500% / 571%", html)

    def test_stats_overlay_clamps_xp_gain_to_cap_on_graveyard(self) -> None:
        snapshot = SimpleNamespace(
            stats={
                "XP Gain": SimpleNamespace(value=12.5, display_value="12.5x"),
            },
        )

        html = build_stats_overlay_html(
            snapshot,
            ["XP Gain"],
            2,
            0.0,
            960.0,
            True,
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

    def test_event_timer_uses_configured_warning_window_for_waves(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            225.0,
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

        self.assertIn("Wave Active", html)
        self.assertNotIn("Wave Active:", html)

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
        self.assertIn("Wave Active", html_active)
        self.assertNotIn("Wave Active:", html_active)

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

        self.assertIn("Wave Active", html)
        self.assertNotIn("Wave Active:", html)


if __name__ == "__main__":
    unittest.main()
