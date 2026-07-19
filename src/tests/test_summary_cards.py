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

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from projections import formatting
from ui.tabs.player_stats.summary_cards import (
    set_chests_card_values,
    set_stage_summary_labels,
)


class FakeLabel:
    def __init__(self) -> None:
        self._text = ""

    def setText(self, text) -> None:
        self._text = str(text)

    def text(self) -> str:
        return self._text


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
        from types import SimpleNamespace

        from ui.tabs.player_stats.live_stats import LiveStatsTabMixin

        labels = gridded_labels(2)
        owner = SimpleNamespace(player_stats_stage_summary_labels=labels)
        rows = [
            {"label": "Stage 1", "kills": "120", "time": "01:00", "items": "3"},
            {"label": "Stage 2", "kills": "240", "time": "02:00", "items": "5"},
        ]

        LiveStatsTabMixin.set_stage_summary_rows(owner, rows)

        self.assertEqual(labels[0]["kills"].text(), "120")
        self.assertEqual(labels[1]["time"].text(), "02:00")

    def test_the_port_operation_resets_to_dashes_with_no_rows(self) -> None:
        from types import SimpleNamespace

        from ui.tabs.player_stats.live_stats import LiveStatsTabMixin

        labels = gridded_labels(1)
        labels[0]["kills"].setText("stale")
        owner = SimpleNamespace(player_stats_stage_summary_labels=labels)

        LiveStatsTabMixin.set_stage_summary_rows(owner, None)

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

    def test_no_labels_is_a_no_op(self) -> None:
        set_chests_card_values(None, {"opened": "1"})
        set_chests_card_values({}, {"opened": "1"})


if __name__ == "__main__":
    unittest.main()
