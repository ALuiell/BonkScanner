"""The compare card's item changes, as one wrapping row per rarity.

The four-column chip grid this replaces gave every item its own rarity -- which
the pipe-joined block before it did not -- but four columns wide enough for a
two-word name need most of the tab, and the card gets a third of it, so a
thirty-item segment came out as a tall block of half-empty columns.

`compare_detail_rarity_rows` hands back `((label, items), ...)` instead: the
rarity colour on the leading dot *and* on every name, so the grouping survives
wrapping. Pure, so the grouping is asserted here rather than through a widget;
the rendered card is asserted in `test_recordings_layout.py`.
"""

from __future__ import annotations

import html as html_module
import re
import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from core.item_metadata import ITEM_RARITY_COLOR_MAP
from projections import formatting


def _snapshot(*items, **fields):
    return SimpleNamespace(items=tuple(items), **fields)


def _plain(rich_text: str) -> str:
    """The row's text without its markup.

    The name and its count sit in separate spans -- the name wears the rarity
    colour, the count stays grey -- so asserting on `"Key +2"` has to look at
    what the row *reads* as rather than at one span's contents.
    """
    return html_module.unescape(re.sub(r"<[^>]+>", "", rich_text))


class CompareDetailRowTests(unittest.TestCase):
    def test_nothing_changed_is_no_sections_at_all(self) -> None:
        """The card writes its own note; an empty heading is worse."""
        base = _snapshot("Key x1")

        self.assertEqual(
            formatting.compare_detail_rarity_rows(base, _snapshot("Key x1")), ()
        )

    def test_a_gains_row_is_a_dot_a_total_and_its_items(self) -> None:
        """No heading above it: the dot and the total say what the row is."""
        rows = formatting.compare_detail_rarity_rows(
            _snapshot("Key x1"), _snapshot("Key x3")
        )

        self.assertEqual(len(rows), 1)
        badge, items = rows[0]
        self.assertIn(ITEM_RARITY_COLOR_MAP["COMMON"], badge)
        self.assertIn(">2<", badge)
        self.assertIn("Key +2", _plain(items))

    def test_one_row_per_rarity_brightest_first(self) -> None:
        """The point of the change: the grouping is the layout, not a column."""
        rows = formatting.compare_detail_rarity_rows(
            _snapshot(), _snapshot("Bonker x1", "Key x1", "Beer x1")
        )

        self.assertEqual(len(rows), 3)
        # "Bonker" is the raw name; "Big Bonk" is its display name, which is
        # what the row has to show.
        self.assertIn("Big Bonk +1", _plain(rows[0][1]))
        self.assertIn(ITEM_RARITY_COLOR_MAP["LEGENDARY"], rows[0][0])
        self.assertIn("Beer +1", _plain(rows[1][1]))
        self.assertIn(ITEM_RARITY_COLOR_MAP["UNCOMMON"], rows[1][0])
        self.assertIn("Key +1", _plain(rows[2][1]))
        self.assertIn(ITEM_RARITY_COLOR_MAP["COMMON"], rows[2][0])

    def test_every_name_wears_its_rarity_colour_not_just_the_dot(self) -> None:
        """`_format_item_change_text` passed a flat `#E5E7EB` fallback.

        `item_display_color` only special-cases a couple of items, so every
        other name came out the same light grey and the rarity lived on the
        leading dot alone -- unreadable exactly where the row is long.
        """
        rows = formatting.compare_detail_rarity_rows(
            _snapshot(), _snapshot("Bonker x1", "Key x1")
        )

        legendary_items, common_items = rows[0][1], rows[1][1]
        self.assertIn(ITEM_RARITY_COLOR_MAP["LEGENDARY"], legendary_items)
        self.assertIn(ITEM_RARITY_COLOR_MAP["COMMON"], common_items)
        self.assertNotIn("#E5E7EB", legendary_items)

    def test_an_items_own_colour_still_beats_its_rarity(self) -> None:
        """The One Ring is orange on purpose, whatever tier it sits in."""
        rows = formatting.compare_detail_rarity_rows(
            _snapshot(), _snapshot("Golden Ring x1")
        )

        self.assertIn("The One Ring +1", _plain(rows[0][1]))
        self.assertIn("#F97316", rows[0][1])

    def test_a_rarity_badge_totals_its_own_row(self) -> None:
        rows = formatting.compare_detail_rarity_rows(
            _snapshot(), _snapshot("Key x2", "Time Bracelet x3")
        )

        badge, items = rows[0]
        self.assertIn(">5<", badge)
        self.assertIn("Time Bracelet +3", _plain(items))
        self.assertIn("Key +2", _plain(items))

    def test_items_inside_a_row_stay_in_count_order(self) -> None:
        rows = formatting.compare_detail_rarity_rows(
            _snapshot(), _snapshot("Key x1", "Time Bracelet x4")
        )

        items = _plain(rows[0][1])
        self.assertLess(items.index("Time Bracelet"), items.index("Key"))

    def test_losses_are_one_labelled_row_not_a_heading_and_a_row(self) -> None:
        """`Lost  Key -2`, in the column the rarity dots use.

        Ungrouped and on one line: what matters about a lost item is that it is
        gone, not how rare it was, and a heading above it cost a whole line to
        say what the label column says for free.
        """
        rows = formatting.compare_detail_rarity_rows(
            _snapshot("Key x3"), _snapshot("Key x1")
        )

        self.assertEqual(len(rows), 1)
        label, items = rows[0]
        self.assertIn(">Lost<", label)
        self.assertIn("#F0787E", label)
        self.assertIn("Key -2", items)

    def test_broken_and_lost_are_separate_rows_after_the_gains(self) -> None:
        """A fixed order, whatever the run did, so the card reads the same."""
        rows = formatting.compare_detail_rarity_rows(
            _snapshot("Key x2", "Za Warudo x1"),
            _snapshot("Key x1", "Bonker x1"),
        )

        self.assertIn("Big Bonk +1", _plain(rows[0][1]))
        self.assertIn(">Broken<", rows[1][0])
        self.assertIn("Za Warudo -1", rows[1][1])
        self.assertIn(">Lost<", rows[2][0])
        self.assertIn("Key -1", rows[2][1])

    def test_an_unknown_item_is_shown_rather_than_dropped(self) -> None:
        rows = formatting.compare_detail_rarity_rows(
            _snapshot(), _snapshot("Not A Real Item x1")
        )

        self.assertIn("Not A Real Item +1", _plain(rows[-1][1]))

    def test_a_whole_segment_is_summed_not_just_its_endpoints(self) -> None:
        """The pin can be far from the playhead; every step between counts."""
        segment = (
            _snapshot("Key x1"),
            _snapshot("Key x2"),
            _snapshot("Key x4"),
        )

        rows = formatting.compare_detail_rarity_rows(
            segment[0], segment[-1], segment_snapshots=segment
        )

        self.assertIn("Key +3", _plain(rows[0][1]))


class SegmentHeadlineTests(unittest.TestCase):
    """The card's header line, which replaced two stacked labels.

    The pair before it -- a rarity-dot gains preview and a
    `Snapshot 305 -> 1 | 51:02 -> 00:00 | +154 items` line -- said the item
    total twice and led with a snapshot index.
    """

    def _snapshot(self, seconds, *items, level=0, kills=0):
        return _snapshot(
            *items,
            game_time_seconds=seconds,
            player_level=level,
            mob_kills=kills,
        )

    def test_names_the_two_ends_the_scrubber_pins(self) -> None:
        headline = formatting.format_segment_headline(
            self._snapshot(760, "Key x1"), self._snapshot(3130, "Key x2")
        )

        self.assertIn(">A<", headline)
        self.assertIn("12:40", headline)
        self.assertIn(">B<", headline)
        self.assertIn("52:10", headline)

    def test_both_ends_are_accented_not_just_the_anchor(self) -> None:
        """A and B name one selection; colouring only A read as "A is live"."""
        headline = formatting.format_segment_headline(
            self._snapshot(0, "Key x1"), self._snapshot(60, "Key x2")
        )

        self.assertIn('<b style="color:#38BDF8;">A</b>', headline)
        self.assertIn('<b style="color:#38BDF8;">B</b>', headline)

    def test_totals_read_levels_items_kills(self) -> None:
        headline = formatting.format_segment_headline(
            self._snapshot(0, "Key x1", level=12, kills=1_000),
            self._snapshot(60, "Key x4", level=30, kills=6_000),
        )

        self.assertLess(headline.index("levels"), headline.index("items"))
        self.assertLess(headline.index("items"), headline.index("kills"))
        self.assertIn("+18", headline)
        self.assertIn("+3", headline)
        self.assertIn(f"+{formatting.format_count(5_000)}", headline)

    def test_a_pin_below_the_playhead_still_reports_levels_and_kills(self) -> None:
        """The pin can sit *after* the playhead -- shift-clicking back does it.

        The item totals never cared: the segment is walked low index to high.
        Subtracting the A/B pair in the order the tab passed them gave a
        negative, and a clamped negative is a zero, and a zero is dropped --
        which is why the header used to say only "+N items".
        """
        earlier = self._snapshot(60, "Key x1", level=10, kills=500)
        later = self._snapshot(600, "Key x4", level=90, kills=9_000)

        headline = formatting.format_segment_headline(
            later, earlier, segment_snapshots=(earlier, later)
        )

        self.assertIn("+80", headline)
        self.assertIn("levels", headline)
        self.assertIn(f"+{formatting.format_count(8_500)}", headline)
        self.assertIn("kills", headline)

    def test_a_gap_at_one_end_does_not_drop_the_whole_total(self) -> None:
        """`player_level` and `mob_kills` are optional per snapshot."""
        segment = (
            _snapshot("Key x1", game_time_seconds=0, player_level=None, mob_kills=None),
            self._snapshot(30, "Key x2", level=12, kills=400),
            self._snapshot(60, "Key x3", level=44, kills=2_400),
        )

        headline = formatting.format_segment_headline(
            segment[0], segment[-1], segment_snapshots=segment
        )

        self.assertIn("+32", headline)
        self.assertIn(f"+{formatting.format_count(2_000)}", headline)

    def test_a_flat_counter_is_left_out_rather_than_shown_as_zero(self) -> None:
        headline = formatting.format_segment_headline(
            self._snapshot(0, level=7, kills=90), self._snapshot(30, level=7, kills=90)
        )

        self.assertNotIn("levels", headline)
        self.assertNotIn("kills", headline)
        # Items stays: it is the one total the card exists to show, and "+0
        # items" is the answer to "what did this segment give me".
        self.assertIn("items", headline)

    def test_a_legacy_snapshot_without_a_clock_falls_back_to_its_label(self) -> None:
        base = _snapshot("Key x1", time_label="00:20")
        current = _snapshot("Key x2", time_label="01:40")

        headline = formatting.format_segment_headline(base, current)

        self.assertIn("00:20", headline)
        self.assertIn("01:40", headline)

    def test_no_segment_at_all_is_a_dash(self) -> None:
        self.assertEqual(formatting.format_segment_headline(None, None), "--")


if __name__ == "__main__":
    unittest.main()
