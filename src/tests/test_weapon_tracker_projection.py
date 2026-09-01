from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

import src

from core.stats.types import WeaponSnapshot, WeaponStatFormat, WeaponStatValue
from core.stats.weapon_tracker import (
    DEFAULT_WEAPON_TRACKER_SELECTED_STATS,
    WEAPON_TRACKER_METRIC_ORDER,
    calculate_weapon_tracker_row,
    calculate_weapon_tracker_rows,
    format_weapon_tracker_value,
    normalize_weapon_tracker_metric_keys,
)


def _weapon(
    *,
    weapon_id: int = 23,
    name: str = "Katana",
    level: int = 4,
    upgrade_stat_ids=(9, 10, 12, 16, 18, 19),
    values=None,
    max_duration=None,
    max_size_multiplier=None,
) -> WeaponSnapshot:
    values = values or {9: 1.4, 10: 2.0, 12: 50.0, 16: 1.0, 18: 0.2, 19: 0.0}
    full_stats = {
        stat_id: WeaponStatValue(
            stat_id=stat_id,
            label=f"Stat {stat_id}",
            value=value,
            value_format=WeaponStatFormat.FLAT,
        )
        for stat_id, value in values.items()
    }
    return WeaponSnapshot(
        weapon_id=weapon_id,
        name=name,
        level=level,
        upgrade_stat_ids=tuple(upgrade_stat_ids),
        upgraded_stats={
            stat_id: full_stats[stat_id]
            for stat_id in upgrade_stat_ids
            if stat_id in full_stats
        },
        full_stats=full_stats,
        max_duration=max_duration,
        max_size_multiplier=max_size_multiplier,
    )


def _globals(**overrides):
    values = {
        "Damage": 2.0,
        "Projectile Count": 1.0,
        "Size": 1.5,
        "Duration": 2.0,
        "Crit Chance": 0.1,
        "Crit Damage": 1.0,
        "Thorns": 7.0,
    }
    values.update(overrides)
    return {key: SimpleNamespace(value=value) for key, value in values.items()}


class WeaponTrackerProjectionTests(unittest.TestCase):
    def test_all_six_supported_formulas(self) -> None:
        row = calculate_weapon_tracker_row(
            _weapon(),
            _globals(),
            WEAPON_TRACKER_METRIC_ORDER,
        )

        self.assertIsNotNone(row)
        self.assertEqual(
            [metric.key for metric in row.metrics],
            list(WEAPON_TRACKER_METRIC_ORDER),
        )
        for metric, expected in zip(
            row.metrics,
            (100.0, 2.0, 2.1, 4.0, 0.3, 2.0),
        ):
            self.assertAlmostEqual(metric.value, expected)

    def test_aegis_damage_includes_thorns_before_damage_multiplier(self) -> None:
        row = calculate_weapon_tracker_row(
            _weapon(weapon_id=7, name="Aegis", values={12: 10.0}, upgrade_stat_ids=(12,)),
            _globals(),
            ("damage",),
        )

        self.assertEqual(row.metrics[0].value, 34.0)

    def test_shotgun_uses_underlying_projectile_stat_projection(self) -> None:
        row = calculate_weapon_tracker_row(
            _weapon(weapon_id=29, name="Shotgun", values={16: 2.0}, upgrade_stat_ids=(16,)),
            _globals(**{"Projectile Count": 5.0}),
            ("projectile_count",),
        )

        self.assertEqual(row.metrics[0].value, 7.0)

    def test_projectile_count_truncates_toward_zero_and_keeps_minimum_one(self) -> None:
        row = calculate_weapon_tracker_row(
            _weapon(values={16: -3.5}, upgrade_stat_ids=(16,)),
            _globals(**{"Projectile Count": 1.9}),
            ("projectile_count",),
        )

        self.assertEqual(row.metrics[0].value, 1.0)

    def test_size_and_duration_caps_apply_after_global_multiplication(self) -> None:
        row = calculate_weapon_tracker_row(
            _weapon(max_duration=3.5, max_size_multiplier=1.8),
            _globals(),
            ("size", "duration"),
        )

        self.assertEqual(
            [(metric.key, metric.value) for metric in row.metrics],
            [("size", 1.8), ("duration", 3.5)],
        )

    def test_negative_cap_sentinels_disable_caps(self) -> None:
        row = calculate_weapon_tracker_row(
            _weapon(max_duration=-1.0, max_size_multiplier=-1.0),
            _globals(),
            ("size", "duration"),
        )

        self.assertAlmostEqual(row.metrics[0].value, 2.1)
        self.assertAlmostEqual(row.metrics[1].value, 4.0)

    def test_crit_chance_above_one_is_not_clamped(self) -> None:
        row = calculate_weapon_tracker_row(
            _weapon(values={18: 1.2}, upgrade_stat_ids=(18,)),
            _globals(**{"Crit Chance": 0.35}),
            ("crit_chance",),
        )

        self.assertAlmostEqual(row.metrics[0].value, 1.55)
        self.assertEqual(row.metrics[0].display_value, "155%")

    def test_default_crit_damage_baseline_formats_as_two_x(self) -> None:
        row = calculate_weapon_tracker_row(
            _weapon(values={19: 0.0}, upgrade_stat_ids=(19,)),
            _globals(**{"Crit Damage": 1.0}),
            ("crit_damage",),
        )

        self.assertEqual(row.metrics[0].value, 2.0)
        self.assertEqual(row.metrics[0].display_value, "×2")

    def test_missing_or_non_finite_operand_hides_only_that_metric(self) -> None:
        weapon = _weapon(values={12: math.nan, 16: 2.0, 9: 1.0})
        general = _globals(**{"Size": math.inf})

        row = calculate_weapon_tracker_row(
            weapon,
            general,
            ("damage", "projectile_count", "size"),
        )

        self.assertEqual([metric.key for metric in row.metrics], ["projectile_count"])

    def test_aegis_damage_is_hidden_when_thorns_is_unavailable(self) -> None:
        general = _globals()
        del general["Thorns"]

        row = calculate_weapon_tracker_row(
            _weapon(weapon_id=7, values={12: 10.0}, upgrade_stat_ids=(12,)),
            general,
            ("damage",),
        )

        self.assertIsNone(row)

    def test_selected_stats_intersect_upgrade_pool_and_use_full_stats(self) -> None:
        weapon = _weapon(
            upgrade_stat_ids=(12, 18),
            values={12: 40.0, 16: 99.0, 18: 0.2},
        )

        row = calculate_weapon_tracker_row(
            weapon,
            _globals(),
            ("damage", "projectile_count", "crit_chance"),
        )

        self.assertEqual([metric.key for metric in row.metrics], ["damage", "crit_chance"])
        self.assertEqual(row.metrics[0].value, 80.0)

    def test_weapon_without_matching_metrics_is_hidden(self) -> None:
        row = calculate_weapon_tracker_row(
            _weapon(upgrade_stat_ids=(11,), values={11: 2.0}),
            _globals(),
            DEFAULT_WEAPON_TRACKER_SELECTED_STATS,
        )

        self.assertIsNone(row)

    def test_inventory_filter_preserves_reader_order(self) -> None:
        rows = calculate_weapon_tracker_rows(
            (
                _weapon(weapon_id=29, name="Shotgun", values={12: 1.0}, upgrade_stat_ids=(12,)),
                _weapon(weapon_id=7, name="Aegis", values={12: 1.0}, upgrade_stat_ids=(12,)),
            ),
            _globals(),
            ("damage",),
        )

        self.assertEqual([row.weapon_id for row in rows], [29, 7])

    def test_metric_key_normalization_is_canonical_and_deduplicated(self) -> None:
        self.assertEqual(
            normalize_weapon_tracker_metric_keys(
                ["crit_damage", "size", "unknown", "size", "damage"]
            ),
            ("damage", "size", "crit_damage"),
        )

    def test_approved_formatting_uses_two_useful_decimals(self) -> None:
        self.assertEqual(format_weapon_tracker_value("damage", 100.0), "100")
        self.assertEqual(format_weapon_tracker_value("projectile_count", 2.0), "2")
        self.assertEqual(format_weapon_tracker_value("size", 1.4), "×1.4")
        self.assertEqual(format_weapon_tracker_value("duration", 3.456), "3.46s")
        self.assertEqual(format_weapon_tracker_value("crit_chance", 0.25001), "25%")
        self.assertEqual(format_weapon_tracker_value("crit_damage", 2.005), "×2")


if __name__ == "__main__":
    unittest.main()
