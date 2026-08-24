from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ui.tabs.player_stats.stat_cards import StatCardsView


def _stat(stat_id: int, label: str, rolls: int, display: str):
    return SimpleNamespace(
        stat_id=stat_id,
        label=label,
        rolls=rolls,
        value=float(rolls),
        display_delta=display,
        rarity_counts=(("Common", rolls),),
    )


def _effect(key: str, label: str, display: str, count: int):
    return SimpleNamespace(
        key=key,
        stat_id=int(key.split(":")[-1]),
        label=label,
        display_delta=display,
        count=count,
        kind=SimpleNamespace(value="stat"),
    )


class StatCardReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.roots = []

    def _view(self):
        layouts = {}
        labels = {}
        for section in (
            "weapons",
            "tomes",
            "chaos",
            "shrine",
            "character_passive",
            "damage_sources",
        ):
            root = QWidget()
            self.roots.append(root)
            layouts[section] = QVBoxLayout(root)
            labels[section] = QLabel()
        return StatCardsView(
            weapons_layout=layouts["weapons"],
            weapons_status_label=labels["weapons"],
            tomes_layout=layouts["tomes"],
            tomes_status_label=labels["tomes"],
            chaos_layout=layouts["chaos"],
            chaos_status_label=labels["chaos"],
            shrine_layout=layouts["shrine"],
            shrine_status_label=labels["shrine"],
            character_passive_layout=layouts["character_passive"],
            character_passive_status_label=labels["character_passive"],
            damage_sources_layout=layouts["damage_sources"],
            damage_sources_status_label=labels["damage_sources"],
        )

    @staticmethod
    def _texts(card) -> list[str]:
        return [label.text() for label in card.findChildren(QLabel) if label.text()]

    def test_chaos_reorders_existing_cards_when_roll_rank_changes(self) -> None:
        view = self._view()
        damage = _stat(12, "Damage", 1, "+12%")
        luck = _stat(30, "Luck", 3, "+15%")
        view.display_chaos_tome(
            SimpleNamespace(level=4, ambiguous_rolls=0, stats=(damage, luck))
        )
        first = tuple(view._chaos_grid._cards)
        self.assertIn("Luck", self._texts(first[0]))
        self.assertIn("Damage", self._texts(first[1]))

        damage = _stat(12, "Damage", 5, "+60%")
        luck = _stat(30, "Luck", 3, "+15%")
        view.display_chaos_tome(
            SimpleNamespace(level=8, ambiguous_rolls=0, stats=(damage, luck))
        )
        second = tuple(view._chaos_grid._cards)

        self.assertIs(second[0], first[1])
        self.assertIs(second[1], first[0])
        self.assertIn("+60%", self._texts(second[0]))

    def test_shrines_reorder_existing_cards_when_roll_rank_changes(self) -> None:
        view = self._view()
        damage = _stat(12, "Damage", 1, "+12%")
        luck = _stat(30, "Luck", 2, "+10%")
        view.display_charge_shrines(
            SimpleNamespace(
                charged=3,
                selected=3,
                pending=0,
                ambiguous_matches=0,
                stats=(damage, luck),
            )
        )
        first = tuple(view._shrine_grid._cards)

        damage = _stat(12, "Damage", 4, "+48%")
        view.display_charge_shrines(
            SimpleNamespace(
                charged=6,
                selected=6,
                pending=0,
                ambiguous_matches=0,
                stats=(damage, luck),
            )
        )
        second = tuple(view._shrine_grid._cards)

        self.assertIs(second[0], first[1])
        self.assertIs(second[1], first[0])

    def test_passives_follow_snapshot_order_without_recreating_effect_cards(self) -> None:
        view = self._view()
        evasion = _effect("stat:8", "Evasion", "+5%", 2)
        luck = _effect("stat:30", "Luck", "+10%", 1)

        def passive(effects):
            return SimpleNamespace(
                character_id=1,
                passive_id=2,
                character_name="Dice",
                passive_name="Gamba",
                level=10,
                status=SimpleNamespace(value="supported"),
                coverage="full",
                ambiguous=0,
                pending=0,
                effects=effects,
            )

        view.display_character_passive(passive((evasion, luck)))
        first = tuple(view._character_passive_grid._cards)
        view.display_character_passive(passive((luck, evasion)))
        second = tuple(view._character_passive_grid._cards)

        self.assertIs(second[0], first[1])
        self.assertIs(second[1], first[0])

    def test_weapon_and_tome_outer_cards_survive_value_changes(self) -> None:
        view = self._view()
        weapon = SimpleNamespace(
            weapon_id=1,
            name="Sword",
            level=1,
            upgrade_stat_ids=(12,),
            upgraded_stats={
                12: SimpleNamespace(label="Damage", display_value="12")
            },
        )
        tome = SimpleNamespace(
            tome_id=2,
            name="Damage Tome",
            level=1,
            stat_id=12,
            stat_label="Damage",
            display_value="1.12x",
        )
        view.display_weapons((weapon,))
        view.display_tomes((tome,))
        weapon_card = view._weapon_cards[0]
        tome_card = view._tome_cards[0]

        weapon.level = 2
        weapon.upgraded_stats[12].display_value = "24"
        tome.level = 2
        tome.display_value = "1.24x"
        view.display_weapons((weapon,))
        view.display_tomes((tome,))

        self.assertIs(view._weapon_cards[0], weapon_card)
        self.assertIs(view._tome_cards[0], tome_card)
        self.assertIn("24", self._texts(weapon_card))
        self.assertIn("1.24x", self._texts(tome_card))


if __name__ == "__main__":
    unittest.main()
