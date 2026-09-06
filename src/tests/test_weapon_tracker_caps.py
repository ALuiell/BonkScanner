from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

import src
from core.stats.weapon_caps import projectile_cap
from core.stats.weapon_tracker import WEAPON_TRACKER_METRIC_ORDER, calculate_weapon_tracker_row
from projections.in_game_html import build_weapon_tracker_overlay_html
from projections.obs import weapon_tracker_payload
from projections.twitch import format_effective_weapons
from test_weapon_tracker_projection import _weapon, _globals


class WeaponCapsTests(unittest.TestCase):
    def test_complete_registry_and_reached_boundaries(self):
        expected = {
            0: 6, 1: 10, 2: 5, 3: 55, 5: 80, 6: 80, 9: 7, 10: 10,
            11: 10, 12: 9, 13: 10, 14: 20, 15: 3, 19: 49, 20: 4,
            21: 5, 22: 3, 23: 25, 24: 1, 25: 55, 26: 6, 27: 5,
            28: 5, 29: 18, 30: 15,
        }
        for weapon_id, cap in expected.items():
            for value in (cap - 1, cap, cap + 1):
                with self.subTest(weapon=weapon_id, value=value):
                    result = projectile_cap(weapon_id, value, 1.0)
                    self.assertEqual(result.value, cap)
                    self.assertEqual(result.reached, value >= cap)
        for weapon_id in (4, 8, 16, 17, 18, 999):
            self.assertEqual(projectile_cap(weapon_id, 10, 1).kind, "unavailable")

    def test_dynamic_caps_follow_global_attack_speed(self):
        for weapon_id, limits in ((23, (25, 16, 12, 8)), (3, (55, 36, 27, 18)), (25, (55, 36, 27, 18))):
            for speed, cap in zip((1, 1.5, 2, 3), limits):
                self.assertEqual(projectile_cap(weapon_id, 25, speed).value, cap)
        self.assertEqual(projectile_cap(0, 6, 7.5).value, 6)
        self.assertEqual(projectile_cap(0, 6, 10).value, 5)
        self.assertEqual(projectile_cap(23, 1, 1e300).value, 1)

    def test_underlying_projectiles_are_not_spawn_or_pellet_counts(self):
        for weapon_id, kind, cap in ((23, "dynamic_soft", 12), (29, "special_soft", 18),
                                     (5, "hard", 80), (6, "hard", 80), (19, "hard", 49),
                                     (7, "none", None)):
            weapon = _weapon(weapon_id=weapon_id, upgrade_stat_ids=(16,), values={16: 100})
            metric = calculate_weapon_tracker_row(weapon, _globals(**{"Attack Speed": 2}), ("projectile_count",)).metrics[0]
            self.assertEqual(metric.value, 101)
            self.assertEqual((metric.cap.kind, metric.cap.value), (kind, cap))
            if cap:
                self.assertTrue(metric.cap.reached)

    def test_corrupt_sword_has_its_own_dynamic_burst_budget(self):
        # Both sword variants have cap 5 at AS=1, masking a copied registry row.
        # The documented 0.8-second Corrupt burst still fits 5 shots at AS=8;
        # Hero's 0.75-second burst fits only 4. At AS=20 the caps are 2 vs 1.
        for speed, expected in ((1, 5), (7, 5), (8, 5), (10, 4), (20, 2)):
            with self.subTest(attack_speed=speed):
                self.assertEqual(projectile_cap(28, 20, speed).value, expected)
        for weapon_id, expected in ((27, 4), (28, 5)):
            metric = calculate_weapon_tracker_row(
                _weapon(weapon_id=weapon_id, upgrade_stat_ids=(16,), values={16: 3}),
                _globals(**{"Attack Speed": 8}), ("projectile_count",),
            ).metrics[0]
            self.assertEqual(metric.value, 4)
            self.assertEqual(metric.cap.value, expected)
            self.assertEqual(metric.cap.reached, weapon_id == 27)

    def test_missing_attack_speed_does_not_invent_cap_or_hide_known_stat(self):
        for speed in (None, float("nan"), float("inf"), 0, -1):
            metric = calculate_weapon_tracker_row(_weapon(), _globals(**{"Attack Speed": speed}), ("projectile_count",)).metrics[0]
            self.assertEqual(metric.value, 2)
            self.assertIsNone(metric.cap.value)
            self.assertFalse(metric.cap.reached)
            self.assertEqual(metric.overlay_value(True), metric.display_value)

    def test_duration_and_size_use_existing_clamp_and_visibility(self):
        weapon = _weapon(max_duration=3, max_size_multiplier=2)
        row = calculate_weapon_tracker_row(weapon, _globals(), ("duration", "size"))
        self.assertEqual([(m.value, m.cap.value, m.cap.kind) for m in row.metrics], [(2, 2, "hard"), (3, 3, "hard")])
        self.assertTrue(all(m.cap.reached for m in row.metrics))
        self.assertIsNone(calculate_weapon_tracker_row(replace(weapon, upgrade_stat_ids=(12,)), _globals(), ("duration",)))
        for cap in (-1, None):
            result = calculate_weapon_tracker_row(replace(weapon, max_duration=cap), _globals(), ("duration",)).metrics[0]
            self.assertEqual(result.value, 4)
            self.assertIsNone(result.cap.value)

    def test_one_snapshot_has_consistent_values_and_caps_are_overlay_only(self):
        snapshot = SimpleNamespace(weapons=(_weapon(),), stats=_globals(**{"Attack Speed": 2}), weapons_available=True)
        row = calculate_weapon_tracker_row(snapshot.weapons[0], snapshot.stats, WEAPON_TRACKER_METRIC_ORDER)
        payload = weapon_tracker_payload(snapshot)
        self.assertEqual([m["value"] for m in payload["rows"][0]["metrics"]], [m.value for m in row.metrics])
        self.assertEqual(
            [m["display_value_with_cap"] for m in payload["rows"][0]["metrics"]],
            [m.overlay_value(True) for m in row.metrics],
        )
        payload_metrics = {
            metric["key"]: metric for metric in payload["rows"][0]["metrics"]
        }
        self.assertEqual(
            payload_metrics["projectile_count"]["display_value_with_cap"],
            "2 / 12 (SC)",
        )
        chat = format_effective_weapons(snapshot)
        for layout in ("compact", "detailed"):
            hidden = build_weapon_tracker_overlay_html((row,), layout=layout)
            shown = build_weapon_tracker_overlay_html((row,), layout=layout, show_caps=True)
            self.assertNotIn("cap", hidden)
            self.assertIn("2 / 12 (SC)", shown)
            self.assertNotIn("soft cap", shown)
            for metric in row.metrics:
                self.assertIn(metric.display_value, hidden)
                self.assertIn(metric.display_value, shown)
                self.assertIn(metric.display_value, chat)
        self.assertNotIn("cap", chat)
        self.assertFalse(weapon_tracker_payload(None)["available"])
        self.assertEqual(weapon_tracker_payload(SimpleNamespace(weapons=(), weapons_available=True))["rows"], [])

    def test_native_cap_display_uses_value_slash_cap_for_soft_and_hard_caps(self):
        soft = calculate_weapon_tracker_row(
            _weapon(weapon_id=23, upgrade_stat_ids=(16,), values={16: 4}),
            _globals(**{"Projectile Count": 1, "Attack Speed": 2}),
            ("projectile_count",),
        ).metrics[0]
        hard = calculate_weapon_tracker_row(
            _weapon(
                weapon_id=5,
                upgrade_stat_ids=(10,),
                values={10: 2},
                max_duration=8,
            ),
            _globals(Duration=2),
            ("duration",),
        ).metrics[0]

        self.assertEqual(soft.overlay_value(True), "5 / 12 (SC)")
        self.assertEqual(hard.overlay_value(True), "4s / 8s (HC)")
        self.assertEqual(soft.overlay_value(False), "5")
