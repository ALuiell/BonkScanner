"""The compare card's item changes, as chips instead of a wall of text.

`format_snapshot_item_changes_details` renders the same data as one rich-text
block: a coloured bullet at the start of each rarity's row, then that row's
items joined with `" | "`. Everything after the first item in a row is an
unmarked name in a pipe-separated run, so past about six items the block says
only that *something* changed.

`compare_detail_chips` hands back `(section, ((text, tag), ...))` instead, one
chip per item carrying its own rarity tag. Pure, so the grouping is asserted
here rather than through a widget; the rendered card is asserted in
`test_recordings_layout.py`.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from projections import formatting


def _snapshot(*items):
    return SimpleNamespace(items=tuple(items))


class CompareDetailChipTests(unittest.TestCase):
    def test_nothing_changed_is_no_sections_at_all(self) -> None:
        """The card writes its own note; an empty "Gained" heading is worse."""
        base = _snapshot("Key x1")

        self.assertEqual(formatting.compare_detail_chips(base, _snapshot("Key x1")), ())

    def test_a_gain_becomes_one_chip_with_its_delta(self) -> None:
        sections = formatting.compare_detail_chips(
            _snapshot("Key x1"), _snapshot("Key x3")
        )

        self.assertEqual(sections, (("Gained", (("Key +2", "tagCommon"),)),))

    def test_each_chip_carries_its_own_rarity_tag(self) -> None:
        """The point of the change: rarity per item, not per row."""
        sections = formatting.compare_detail_chips(
            _snapshot(), _snapshot("Bonker x1", "Key x1", "Beer x1")
        )

        # "Bonker" is the raw name; "Big Bonk" is its display name, which is
        # what a chip has to show.
        tags = {text: tag for text, tag in sections[0][1]}
        self.assertEqual(tags["Big Bonk +1"], "tagLegendary")
        self.assertEqual(tags["Beer +1"], "tagUncommon")
        self.assertEqual(tags["Key +1"], "tagCommon")

    def test_chips_stay_in_rarity_order(self) -> None:
        sections = formatting.compare_detail_chips(
            _snapshot(), _snapshot("Key x1", "Bonker x1")
        )

        self.assertEqual(
            [text for text, _tag in sections[0][1]], ["Big Bonk +1", "Key +1"]
        )

    def test_a_loss_is_its_own_section_and_signed(self) -> None:
        sections = formatting.compare_detail_chips(
            _snapshot("Key x3"), _snapshot("Key x1")
        )

        self.assertEqual(sections, (("Lost", (("Key -2", "tagCommon"),)),))

    def test_sections_keep_a_fixed_order(self) -> None:
        """Gained before Lost, whatever the run did, so the card reads the same."""
        sections = formatting.compare_detail_chips(
            _snapshot("Key x2"), _snapshot("Key x1", "Bonker x1")
        )

        self.assertEqual([title for title, _chips in sections], ["Gained", "Lost"])

    def test_an_unknown_item_is_shown_rather_than_dropped(self) -> None:
        sections = formatting.compare_detail_chips(
            _snapshot(), _snapshot("Not A Real Item x1")
        )

        self.assertEqual(sections[0][1], (("Not A Real Item +1", "tagNeutral"),))

    def test_a_whole_segment_is_summed_not_just_its_endpoints(self) -> None:
        """The pin can be far from the playhead; every step between counts."""
        segment = (
            _snapshot("Key x1"),
            _snapshot("Key x2"),
            _snapshot("Key x4"),
        )

        sections = formatting.compare_detail_chips(
            segment[0], segment[-1], segment_snapshots=segment
        )

        self.assertEqual(sections, (("Gained", (("Key +3", "tagCommon"),)),))


if __name__ == "__main__":
    unittest.main()
