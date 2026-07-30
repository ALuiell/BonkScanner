"""Coverage for the stage-summary and chests-card writers.

These moved out of `PlayerStatsCardsMixin` at step 19 and became module-level
functions. Mutating them first showed the suite asserted nothing about either:
neutering `set_stage_summary_rows` and dropping the chests fallback projection
both left all 627 tests green. They were never covered as mixin methods --
every test that reached them stubbed them out -- and being module functions
taking their labels as an argument is what finally makes them cheap to test.

That is the step-14c "exercises it / would catch it" gap, closed rather than
carried, on code this step is responsible for moving.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from core.luck_rarity import LUCK_RARITY_ORDER
from projections import formatting
from ui.tabs.player_stats.summary_cards import (
    set_chests_card_values,
    set_loot_rarity_card_values,
    set_stage_summary_labels,
)


class FakeLabel:
    def __init__(self) -> None:
        self._text = ""
        self._visible = True

    def setText(self, text) -> None:
        self._text = str(text)

    def text(self) -> str:
        return self._text

    def setVisible(self, visible) -> None:
        self._visible = bool(visible)

    def isVisible(self) -> bool:
        return self._visible


def gridded_labels(count: int = 4) -> list[dict]:
    """The shape both tabs build: one dict of four labels per stage row."""
    return [
        {key: FakeLabel() for key in ("stage", "time", "kills", "items")}
        for _ in range(count)
    ]


class StageSummaryTests(unittest.TestCase):
    def test_rows_are_written_into_the_matching_columns(self) -> None:
        labels = gridded_labels()
        rows = [
            {"label": "Stage 1", "kills": "120", "time": "01:00", "items": "3"},
            {"label": "Stage 2", "kills": "240", "time": "02:00", "items": "5"},
        ]

        set_stage_summary_labels(labels, rows)

        self.assertEqual(labels[0]["stage"].text(), "1")
        self.assertEqual(labels[0]["kills"].text(), "120")
        self.assertEqual(labels[0]["time"].text(), "01:00")
        self.assertEqual(labels[0]["items"].text(), "3")
        self.assertEqual(labels[1]["stage"].text(), "2")
        self.assertEqual(labels[1]["kills"].text(), "240")

    def test_the_stage_prefix_is_stripped_not_the_whole_label(self) -> None:
        """`"Stage 3"` renders as `"3"`; the column header supplies the word."""
        labels = gridded_labels(1)
        set_stage_summary_labels(
            labels, [{"label": "Stage 3", "kills": "1", "time": "t", "items": "i"}]
        )
        self.assertEqual(labels[0]["stage"].text(), "3")

    def test_no_rows_renders_four_dashed_stages(self) -> None:
        labels = gridded_labels()

        set_stage_summary_labels(labels, None)

        for index, row in enumerate(labels, start=1):
            self.assertEqual(row["stage"].text(), str(index))
            self.assertEqual(row["kills"].text(), "--")
            self.assertEqual(row["time"].text(), "--")
            self.assertEqual(row["items"].text(), "--")

    def test_an_empty_row_list_is_treated_as_no_rows(self) -> None:
        labels = gridded_labels(1)
        set_stage_summary_labels(labels, [])
        self.assertEqual(labels[0]["kills"].text(), "--")

    def test_more_rows_than_labels_stops_at_the_labels(self) -> None:
        """`zip` truncates; a fifth stage must not raise."""
        labels = gridded_labels(2)
        rows = [
            {"label": f"Stage {n}", "kills": str(n), "time": "t", "items": "i"}
            for n in range(1, 6)
        ]

        set_stage_summary_labels(labels, rows)

        self.assertEqual(labels[1]["kills"].text(), "2")

    def test_the_flat_label_shape_is_still_supported(self) -> None:
        """The older one-label-per-stage form renders a single joined line."""
        labels = [FakeLabel()]
        set_stage_summary_labels(
            labels, [{"label": "Stage 1", "kills": "9", "time": "01:00", "items": "2"}]
        )
        self.assertEqual(
            labels[0].text(), "Stage 1: Kills 9 | Time 01:00 | Items 2"
        )


class StageSummaryPortTests(unittest.TestCase):
    """`set_stage_summary_rows`, the `PlayerStatsView` operation itself.

    Separate from the writer above because neutering the *delegation* -- the
    one line in `LiveStatsTabMixin` that hands the tab's own labels to the
    writer -- left the whole suite green even with the writer fully covered.
    The tests that drive `refresh_tasks` all inject a substitute view, so they
    assert the app layer *calls* the port and never that the real
    implementation does anything.

    An unbound call against a plain stub, which is what the step-18 phase-1
    plan prescribes while the subject is still a mixin.
    """

    def test_the_port_operation_writes_the_tabs_own_labels(self) -> None:
        from tests.support.player_stats import build_live_stats_tab

        labels = gridded_labels(2)
        view = build_live_stats_tab()
        view._stage_summary_labels = labels
        rows = [
            {"label": "Stage 1", "kills": "120", "time": "01:00", "items": "3"},
            {"label": "Stage 2", "kills": "240", "time": "02:00", "items": "5"},
        ]

        view.set_stage_summary_rows(rows)

        self.assertEqual(labels[0]["kills"].text(), "120")
        self.assertEqual(labels[1]["time"].text(), "02:00")

    def test_the_port_operation_resets_to_dashes_with_no_rows(self) -> None:
        from tests.support.player_stats import build_live_stats_tab

        labels = gridded_labels(1)
        labels[0]["kills"].setText("stale")
        view = build_live_stats_tab()
        view._stage_summary_labels = labels

        view.set_stage_summary_rows(None)

        self.assertEqual(labels[0]["kills"].text(), "--")


class ChestsCardTests(unittest.TestCase):
    def test_values_are_written_by_key(self) -> None:
        labels = {"opened": FakeLabel(), "total": FakeLabel()}

        set_chests_card_values(labels, {"opened": "12", "total": "30"})

        self.assertEqual(labels["opened"].text(), "12")
        self.assertEqual(labels["total"].text(), "30")

    def test_a_missing_key_falls_back_to_a_dash(self) -> None:
        labels = {"opened": FakeLabel(), "absent": FakeLabel()}
        set_chests_card_values(labels, {"opened": "12"})
        self.assertEqual(labels["absent"].text(), "--")

    def test_no_values_uses_the_all_empty_projection(self) -> None:
        """`None` must render the projection's own empties, not blanks.

        Dropping this fallback left every test green: nothing asserted that
        the card resets rather than keeping its previous text.
        """
        empty = formatting.chests_card_values(
            None, None, None, None, None, None, None, None, None
        )
        self.assertTrue(empty, "the projection should produce keys to write")

        labels = {key: FakeLabel() for key in empty}
        for label in labels.values():
            label.setText("stale")

        set_chests_card_values(labels, None)

        for key, label in labels.items():
            self.assertEqual(label.text(), empty[key], key)
            self.assertNotEqual(label.text(), "stale", key)

    def test_chest_rate_is_a_compact_card_value(self) -> None:
        values = formatting.chests_card_values(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            chests_per_minute=1.425,
        )

        self.assertEqual(values["chests_per_minute"], "1.43")

    def test_no_labels_is_a_no_op(self) -> None:
        set_chests_card_values(None, {"opened": "1"})
        set_chests_card_values({}, {"opened": "1"})

    def test_expected_present_hides_the_status_line(self) -> None:
        labels = {"expected": FakeLabel(), "status": FakeLabel()}

        set_chests_card_values(labels, {"expected": "23.4"})

        self.assertFalse(labels["status"].isVisible())
        self.assertEqual("", labels["status"].text())

    def test_expected_dashed_shows_the_shared_reason(self) -> None:
        labels = {"expected": FakeLabel(), "status": FakeLabel()}

        set_chests_card_values(labels, {"expected": "--"})

        self.assertTrue(labels["status"].isVisible())
        self.assertIn("running from the start", labels["status"].text())


def _rarity_labels() -> dict:
    labels = {
        rarity: {"chance": FakeLabel(), "counts": FakeLabel()}
        for rarity in LUCK_RARITY_ORDER
    }
    labels["status"] = FakeLabel()
    return labels


class LootRarityCardTests(unittest.TestCase):
    """The Live Stats rarity card: four lines, and a reason when it cannot fill."""

    LOOT = SimpleNamespace(
        available=True,
        actual={"LEGENDARY": 116, "RARE": 78, "UNCOMMON": 38, "COMMON": 45},
        expected={"LEGENDARY": 118.4, "RARE": 78.0, "UNCOMMON": 36.2, "COMMON": 45.0},
    )

    def test_each_tier_gets_a_chance_and_a_count_pair(self) -> None:
        labels = _rarity_labels()

        set_loot_rarity_card_values(labels, 3.0, self.LOOT)

        self.assertEqual("116 (exp 118)", labels["LEGENDARY"]["counts"].text())
        self.assertEqual("38 (exp 36)", labels["UNCOMMON"]["counts"].text())
        for rarity in LUCK_RARITY_ORDER:
            self.assertTrue(labels[rarity]["chance"].text().endswith("%"))
        self.assertFalse(labels["status"].isVisible())

    def test_an_unmeasurable_run_keeps_the_chances_and_says_why(self) -> None:
        """The two halves fail apart, as they do in `!luck`.

        This is the surface the *streamer* reads, and the only one that can
        carry the reason -- viewers see nothing, and the one person who can act
        on it sees it here.
        """
        labels = _rarity_labels()

        set_loot_rarity_card_values(
            labels, 3.0, SimpleNamespace(available=False, actual={}, expected={})
        )

        for rarity in LUCK_RARITY_ORDER:
            self.assertTrue(labels[rarity]["chance"].text().endswith("%"))
            self.assertEqual("--", labels[rarity]["counts"].text())
        self.assertTrue(labels["status"].isVisible())
        self.assertIn("running from the start", labels["status"].text())

    def test_no_loot_stats_at_all_is_the_unmeasurable_state(self) -> None:
        labels = _rarity_labels()
        set_loot_rarity_card_values(labels, None, None)
        self.assertEqual("--", labels["LEGENDARY"]["chance"].text())
        self.assertTrue(labels["status"].isVisible())

    def test_no_labels_is_a_no_op(self) -> None:
        set_loot_rarity_card_values(None, 1.0, self.LOOT)
        set_loot_rarity_card_values({}, 1.0, self.LOOT)


if __name__ == "__main__":
    unittest.main()
