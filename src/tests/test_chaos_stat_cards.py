from __future__ import annotations

import src

import unittest
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QLabel

from core.tracker.chaos import CHAOS_FINGERPRINTS, CHAOS_TOME_GAME_STAT_ORDER
from ui.tabs.player_stats.stat_cards import (
    StatCardsView,
    chaos_average_roll_quality,
    chaos_roll_quality_color,
    chaos_stats_by_roll_count,
)


class ChaosStatCardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_stats_are_sorted_by_roll_count_then_game_order(self) -> None:
        low_game_position = min(CHAOS_TOME_GAME_STAT_ORDER, key=CHAOS_TOME_GAME_STAT_ORDER.get)
        high_game_position = max(CHAOS_TOME_GAME_STAT_ORDER, key=CHAOS_TOME_GAME_STAT_ORDER.get)
        stats = (
            SimpleNamespace(stat_id=high_game_position, label="Later", rolls=2),
            SimpleNamespace(stat_id=low_game_position, label="Earlier", rolls=2),
            SimpleNamespace(stat_id=30, label="Most", rolls=4),
        )

        ordered = chaos_stats_by_roll_count(SimpleNamespace(stats=stats))

        self.assertEqual([stat.label for stat in ordered], ["Most", "Earlier", "Later"])

    def test_average_quality_uses_the_stat_specific_roll_range(self) -> None:
        stat_id = 30
        minimum = min(CHAOS_FINGERPRINTS[stat_id])
        maximum = max(CHAOS_FINGERPRINTS[stat_id])

        low = SimpleNamespace(stat_id=stat_id, value=minimum * 2, rolls=2)
        high = SimpleNamespace(stat_id=stat_id, value=maximum * 3, rolls=3)

        self.assertAlmostEqual(chaos_average_roll_quality(low), 0.0)
        self.assertAlmostEqual(chaos_average_roll_quality(high), 1.0)
        self.assertEqual(chaos_roll_quality_color(chaos_average_roll_quality(low)), "#98A7BA")
        self.assertEqual(chaos_roll_quality_color(chaos_average_roll_quality(high)), "#FACC15")

    def test_quality_is_unavailable_without_rolls_or_known_fingerprints(self) -> None:
        self.assertIsNone(
            chaos_average_roll_quality(SimpleNamespace(stat_id=30, value=1.0, rolls=0))
        )
        self.assertIsNone(
            chaos_average_roll_quality(SimpleNamespace(stat_id=999, value=1.0, rolls=1))
        )

    def test_shrine_cards_mirror_chaos_roll_summary_shape(self) -> None:
        damage = SimpleNamespace(
            label="Damage",
            display_delta="+24%",
            rolls=2,
            rarity_counts=(("Common", 1), ("Rare", 1)),
        )
        luck = SimpleNamespace(
            label="Luck",
            display_delta="+5%",
            rolls=1,
            rarity_counts=(("Common", 1),),
        )
        shrines = SimpleNamespace(selected=3, stats=(damage, luck))

        summary = StatCardsView._build_charge_shrine_summary_card(shrines)
        stat_card = StatCardsView._build_charge_shrine_stat_card(damage)

        self.assertEqual(
            [label.text() for label in summary.findChildren(QLabel)],
            ["Charge Shrines", "Tracked rolls: 3 | Stats: 2"],
        )
        self.assertEqual(
            [label.text() for label in stat_card.findChildren(QLabel)],
            ["Damage", "+24%", "● 2 rolls"],
        )

    def test_passive_cards_show_identity_and_only_real_roll_counts(self) -> None:
        passive = SimpleNamespace(
            character_name="Dice",
            passive_name="Gamba",
            level=145,
        )
        dice_effect = SimpleNamespace(
            label="Evasion", display_delta="+10.6%", count=4
        )
        fox_effect = SimpleNamespace(
            label="Luck", display_delta="+259.5%", count=None
        )

        summary = StatCardsView._build_character_passive_summary_card(passive)
        dice_card = StatCardsView._build_character_passive_effect_card(dice_effect)
        fox_card = StatCardsView._build_character_passive_effect_card(fox_effect)

        self.assertEqual(
            [label.text() for label in summary.findChildren(QLabel)],
            ["Dice · Gamba", "Level 145"],
        )
        self.assertEqual(
            [label.text() for label in dice_card.findChildren(QLabel)],
            ["Evasion", "+10.6%", "● 4 rolls"],
        )
        self.assertEqual(
            [label.text() for label in fox_card.findChildren(QLabel)],
            ["Luck", "+259.5%"],
        )


if __name__ == "__main__":
    unittest.main()
