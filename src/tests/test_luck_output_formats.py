"""The output formats of the loot rarity feature, across its surfaces.

Item 5's Deliverables settled these against a real game frame rather than
against a mockup, so they are fixed shapes rather than defaults: the game's
rarity vocabulary in chat, the tenths rule below 10, and the unavailable state
dropping half a line instead of filling it with dashes.

Kept in one module rather than split per surface because the point of most of
them is that the surfaces agree.
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest
from types import SimpleNamespace

from core.luck_rarity import LUCK_RARITY_ORDER, format_expected_count
from core.tracker.snapshots import LootStatsSnapshot
from projections.twitch import format_luck


def _loot(
    *,
    available: bool = True,
    actual: dict[str, int] | None = None,
    expected: dict[str, float] | None = None,
) -> LootStatsSnapshot:
    return LootStatsSnapshot(
        actual=actual or {"LEGENDARY": 116, "RARE": 78, "UNCOMMON": 38, "COMMON": 45},
        expected=expected or {"LEGENDARY": 118.4, "RARE": 78.0, "UNCOMMON": 36.2, "COMMON": 45.0},
        acquisitions=277,
        map_chest_opens=77,
        available=available,
    )


def _runtime(*, luck: float | None = 3.0, loot: LootStatsSnapshot | None = None):
    return SimpleNamespace(luck=luck, loot_stats=_loot() if loot is None else loot)


def _template(_key: str, default: str, **values) -> str:
    return default.format(**values)


class ExpectedCountFormatTests(unittest.TestCase):
    """One decimal below 10, whole numbers above."""

    def test_below_ten_keeps_one_decimal(self) -> None:
        # `1 (0.8)` collapsed to `1 (1)` would read as exactly on expectation
        # when the player was ahead, and `0 (0.4)` to `0 (0)` as if nothing had
        # been expected at all. Both are the reason the tenth is kept.
        self.assertEqual("0.8", format_expected_count(0.84))
        self.assertEqual("0.4", format_expected_count(0.4))
        self.assertEqual("9.6", format_expected_count(9.55))

    def test_ten_and_above_are_whole(self) -> None:
        self.assertEqual("10", format_expected_count(10.0))
        self.assertEqual("118", format_expected_count(118.4))
        self.assertEqual("119", format_expected_count(118.6))

    def test_a_missing_expectation_is_not_a_zero(self) -> None:
        self.assertEqual("--", format_expected_count(None))


class TwitchLuckLineTests(unittest.TestCase):
    def test_the_line_pairs_each_tier_chance_with_what_it_produced(self) -> None:
        line = format_luck(_runtime(luck=3.0), _template)

        self.assertTrue(line.startswith("Luck: "))
        groups = line[len("Luck: "):].split(" | ")
        self.assertEqual(4, len(groups))
        for group in groups:
            self.assertIn(" (exp ", group)
        self.assertIn("116 (exp 118)", groups[0])
        self.assertIn("78 (exp 78)", groups[1])
        self.assertIn("38 (exp 36)", groups[2])
        self.assertIn("45 (exp 45)", groups[3])

    def test_chat_speaks_the_games_rarity_names_not_ours(self) -> None:
        """Our keys are offset by one tier in the middle.

        A viewer reading "Rare" pictures the blue tier; our `RARE` is the purple
        one. Colour carries the meaning everywhere else, so chat is the only
        surface where the mismatch is visible -- and the only one where it is
        wrong.
        """
        line = format_luck(_runtime(), _template)
        names = [group.split()[0] for group in line[len("Luck: "):].split(" | ")]

        self.assertEqual(["Legendary", "Epic", "Rare", "Common"], names)
        # The two schemes agree on the outer tiers and disagree on both middle
        # ones, so those are where substituting our keys would show.
        self.assertEqual("Epic", names[LUCK_RARITY_ORDER.index("RARE")])
        self.assertEqual("Rare", names[LUCK_RARITY_ORDER.index("UNCOMMON")])
        self.assertNotIn("Uncommon", line)

    def test_the_middle_two_tiers_are_not_swapped(self) -> None:
        """Named apart from the vocabulary test: this is the count mapping.

        Renaming the tiers correctly while reading the counts off the wrong key
        would pass a test that only checks the words.
        """
        loot = _loot(
            actual={"LEGENDARY": 1, "RARE": 2, "UNCOMMON": 3, "COMMON": 4},
            expected={"LEGENDARY": 1.0, "RARE": 2.0, "UNCOMMON": 3.0, "COMMON": 4.0},
        )
        line = format_luck(_runtime(loot=loot), _template)

        self.assertIn("Epic", line.split("|")[1])
        self.assertIn("- 2 (exp 2.0)", line.split("|")[1])
        self.assertIn("Rare", line.split("|")[2])
        self.assertIn("- 3 (exp 3.0)", line.split("|")[2])

    def test_an_unmeasurable_run_keeps_the_chances_and_drops_the_rest(self) -> None:
        """Half a line, not a line of dashes.

        The chance depends only on the Luck the player holds now, so it survives
        a late attach untouched. Omitting the rest leaves a shorter answer;
        `--` in its place would read as a fault.
        """
        line = format_luck(_runtime(loot=_loot(available=False)), _template)

        self.assertNotIn("exp", line)
        self.assertNotIn("--", line)
        self.assertNotIn("116", line)
        groups = line[len("Luck: "):].split(" | ")
        self.assertEqual(4, len(groups))
        for group in groups:
            self.assertTrue(group.endswith("%"), group)

    def test_the_chance_half_is_the_current_luck_not_a_stored_one(self) -> None:
        low = format_luck(_runtime(luck=0.0), _template)
        high = format_luck(_runtime(luck=100.0), _template)

        # At Luck 0 the raw base weights normalize straight through: 1.5/92.5.
        self.assertIn("Legendary 1.62%", low)
        self.assertNotEqual(low, high)

    def test_an_unread_luck_leaves_the_chances_blank_rather_than_zero(self) -> None:
        """`None` is "no reading", and 0.0 is a real Luck with a real answer."""
        line = format_luck(_runtime(luck=None), _template)

        self.assertIn("Legendary --", line)
        self.assertNotIn("0.00%", line)

    def test_the_line_fits_a_chat_message_with_room_to_spare(self) -> None:
        line = format_luck(_runtime(), _template)
        self.assertLess(len(line), 200)


if __name__ == "__main__":
    unittest.main()
