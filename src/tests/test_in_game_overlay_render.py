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

    def test_event_timer_uses_remaining_stage_time_for_warning(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            170.0,
            600.0,
            False,
            warning_seconds=15,
        )

        self.assertIn("Boss in 10s", html)

    def test_event_timer_formats_active_wave_countdown(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            250.0,
            600.0,
            False,
            warning_seconds=15,
        )

        self.assertIn("Wave active: 20s", html)

    def test_event_timer_hides_for_graveyard(self) -> None:
        html = build_event_timer_overlay_html(
            0,
            170.0,
            600.0,
            True,
            warning_seconds=15,
        )

        self.assertEqual(html, "")


if __name__ == "__main__":
    unittest.main()
