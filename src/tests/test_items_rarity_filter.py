"""The rarity chips: they count, and pressing one filters the list.

They replace four coloured dots with numbers and no legend -- which said how
many of each you had while leaving which colour meant what to be learnt
somewhere else. Giving each one its name made it labelled; giving it a label
is what made it able to be a control.

No Qt here, and deliberately none: `ItemsSectionView` takes its widgets as
constructor arguments and guards for missing ones, so the chips are stand-ins
that record what was written to them. Nothing in this file may reach
`_render_chips` -- it constructs a `QLabel`, and constructing a widget with no
`QApplication` does not fail, it takes the interpreter down. The rendered
panel is asserted in `test_recordings_layout.py`.
"""

from __future__ import annotations

import unittest

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from projections import formatting
from ui.tabs.player_stats.items_section import FILTERED_EMPTY_NOTE, ItemsSectionView


class FakeLabel:
    def __init__(self) -> None:
        self._text = ""

    def setText(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class FakeChip:
    def __init__(self, rarity: str) -> None:
        self.rarity = rarity
        self._text = ""
        self._enabled = True
        self._checked = False
        self.signals_blocked = False

    def setText(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def isEnabled(self) -> bool:
        return self._enabled

    def setChecked(self, checked: bool) -> None:
        self._checked = bool(checked)

    def isChecked(self) -> bool:
        return self._checked

    def blockSignals(self, blocked: bool) -> None:
        self.signals_blocked = bool(blocked)


# Real names, taken from `core.item_metadata`: the rarity table is the thing
# under test here, so invented names would just be filtered as UNKNOWN.
ITEMS = (
    "Bonker x1",          # LEGENDARY
    "Big Bonk x1",        # LEGENDARY
    "Key x2",             # COMMON
    "Slippery Ring x3",   # COMMON
)


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.label = FakeLabel()
        self.chips: dict[str, FakeChip] = {}
        self.view = ItemsSectionView(
            group=None,
            label=self.label,
            rarity_label=None,
            toggle_btn=None,
            sort_combo=None,
            always_expanded=True,
            rarity_chips_container=object(),
            rarity_chip_factory=self._make_chip,
        )

    def _make_chip(self, rarity: str) -> FakeChip:
        chip = FakeChip(rarity)
        self.chips[rarity] = chip
        return chip

    def _rarity_of(self, item: str) -> str | None:
        return formatting.item_rarity(item)

    def _shown(self) -> str:
        return self.label.text()


class ChipCountTests(_Fixture):
    def test_a_chip_is_made_for_every_rarity(self) -> None:
        self.view.update(ITEMS)

        self.assertEqual(
            list(self.chips), list(formatting.ITEM_RARITY_ORDER)
        )

    def test_a_chip_says_its_name_and_its_count(self) -> None:
        self.view.update(ITEMS)

        self.assertEqual(self.chips["LEGENDARY"].text(), "Legendary 2")
        self.assertEqual(self.chips["COMMON"].text(), "Common 5")

    def test_a_rarity_the_run_has_none_of_is_not_pressable(self) -> None:
        self.view.update(ITEMS)

        self.assertFalse(self.chips["RARE"].isEnabled())
        self.assertTrue(self.chips["LEGENDARY"].isEnabled())

    def test_counts_stay_unfiltered_so_you_can_get_back(self) -> None:
        """Filtered counts would drop to zero and strand you on one rarity."""
        self.view.update(ITEMS)

        self.view.toggle_rarity("LEGENDARY")

        self.assertEqual(self.chips["COMMON"].text(), "Common 5")
        self.assertTrue(self.chips["COMMON"].isEnabled())

    def test_no_items_leaves_every_chip_at_zero(self) -> None:
        self.view.update((), items_text="Select a recording")

        self.assertEqual(self.chips["LEGENDARY"].text(), "Legendary 0")
        self.assertFalse(self.chips["LEGENDARY"].isEnabled())


class FilterTests(_Fixture):
    def test_no_chip_pressed_shows_everything(self) -> None:
        self.view.update(ITEMS)

        self.assertEqual(self.view.rarity_filter(), frozenset())
        for item in ITEMS:
            self.assertIn(item.split(" x")[0], self._shown())

    def test_pressing_a_chip_shows_only_that_rarity(self) -> None:
        self.view.update(ITEMS)

        self.view.toggle_rarity("LEGENDARY")

        self.assertIn("Bonker", self._shown())
        self.assertNotIn("Key", self._shown())

    def test_two_chips_are_a_union_not_an_intersection(self) -> None:
        self.view.update(ITEMS)

        self.view.toggle_rarity("LEGENDARY")
        self.view.toggle_rarity("COMMON")

        self.assertIn("Bonker", self._shown())
        self.assertIn("Key", self._shown())

    def test_pressing_the_same_chip_again_turns_it_off(self) -> None:
        self.view.update(ITEMS)

        self.view.toggle_rarity("LEGENDARY")
        self.view.toggle_rarity("LEGENDARY")

        self.assertEqual(self.view.rarity_filter(), frozenset())
        self.assertIn("Key", self._shown())

    def test_the_chip_reflects_the_filter_it_caused(self) -> None:
        self.view.update(ITEMS)

        self.view.toggle_rarity("LEGENDARY")

        self.assertTrue(self.chips["LEGENDARY"].isChecked())
        self.assertFalse(self.chips["COMMON"].isChecked())

    def test_the_view_sets_the_chip_without_re_entering_the_handler(self) -> None:
        """Otherwise writing the state back would toggle it straight off again."""
        self.view.update(ITEMS)

        self.view.toggle_rarity("LEGENDARY")

        self.assertFalse(self.chips["LEGENDARY"].signals_blocked)

    def test_clearing_restores_the_whole_list(self) -> None:
        self.view.update(ITEMS)
        self.view.toggle_rarity("LEGENDARY")

        self.view.clear_rarity_filter()

        self.assertEqual(self.view.rarity_filter(), frozenset())
        self.assertIn("Key", self._shown())

    def test_a_filter_that_hides_everything_is_not_an_empty_recording(self) -> None:
        """The panel says which it is; "--" would read as "picked up nothing"."""
        self.view.update(("Key x2",))

        self.view.toggle_rarity("LEGENDARY")

        self.assertEqual(self.view._apply_rarity_filter(("Key x2",)), ())
        self.assertEqual(FILTERED_EMPTY_NOTE, "No items of the selected rarity")

    def test_a_new_snapshot_keeps_the_filter(self) -> None:
        """Scrubbing must not silently undo a filter the user set."""
        self.view.update(ITEMS)
        self.view.toggle_rarity("LEGENDARY")

        self.view.update(ITEMS + ("Beer x1",))

        self.assertEqual(self.view.rarity_filter(), frozenset({"LEGENDARY"}))
        self.assertNotIn("Key", self._shown())


if __name__ == "__main__":
    unittest.main()
