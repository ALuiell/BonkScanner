"""The redesigned Overview's two projections.

The axis and the Luck & Loot block replaced a verdict label that repeated what
the run plaques already said. What they add is the pair of claims nothing else
in the app makes -- *where* two runs diverge, and whether the winner built
better or drew better -- so the cases here are mostly about the second one
staying honest: an unmeasured recording must never read as a zero.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from projections import compare_overview as overview
from projections.metric_table import MetricRow, MetricSection, MetricTable


def stat(value, display):
    return SimpleNamespace(value=value, display_value=display)


def snapshot(**fields):
    defaults = {
        "mob_kills": None,
        "player_level": None,
        "items": (),
        "chests_opened": None,
        "stats": {},
        "loot_actual": None,
        "loot_expected": None,
    }
    defaults.update(fields)
    return SimpleNamespace(**defaults)


class AxisTests(unittest.TestCase):
    def test_rows_are_ranked_by_relative_gap_and_name_their_leader(self) -> None:
        table = overview.build_compare_runs_axis(
            snapshot(mob_kills=1000, player_level=10),
            snapshot(mob_kills=990, player_level=5),
        )

        self.assertEqual(["Level", "Kills"], [row.label for row in table.rows])
        self.assertEqual("A +5", table.rows[0].summary)
        self.assertEqual("A +10", table.rows[1].summary)
        self.assertEqual(overview.LEAD_A, table.rows[0].lead)

    def test_the_widest_row_fills_its_half_and_the_rest_scale_against_it(self) -> None:
        table = overview.build_compare_runs_axis(
            snapshot(mob_kills=1000, player_level=10),
            snapshot(mob_kills=990, player_level=5),
        )

        self.assertEqual(1.0, table.rows[0].magnitude)
        self.assertLess(table.rows[1].magnitude, 0.1, "a 1% gap must not look like a 50% one")

    def test_metrics_the_runs_agree_on_are_dropped(self) -> None:
        """A screen of centred zero-length bars would bury the rows that matter."""
        table = overview.build_compare_runs_axis(
            snapshot(mob_kills=1000, player_level=7),
            snapshot(mob_kills=1000, player_level=5),
        )

        self.assertEqual(["Level"], [row.label for row in table.rows])

    def test_a_stat_gap_is_reported_in_that_stat_s_own_units(self) -> None:
        """`+102.86%`, not `+102.857` -- the summary must match the Stats column."""
        table = overview.build_compare_runs_axis(
            snapshot(stats={"Luck": stat(1212.0, "1212%")}),
            snapshot(stats={"Luck": stat(1100.0, "1100%")}),
            stat_labels=("Luck",),
        )

        self.assertEqual("A +112%", table.rows[0].summary)

    def test_two_identical_runs_say_so_rather_than_drawing_nothing(self) -> None:
        same = snapshot(mob_kills=1000, player_level=5)

        table = overview.build_compare_runs_axis(same, same)

        self.assertEqual((), table.rows)
        self.assertEqual(overview.AXIS_NO_DIFFERENCE_TEXT, table.empty_text)

    def test_a_missing_side_is_the_select_two_recordings_state(self) -> None:
        self.assertEqual(
            overview.EMPTY_AXIS_TABLE,
            overview.build_compare_runs_axis(None, snapshot()),
        )


class LuckLootTests(unittest.TestCase):
    def _measured(self):
        return (
            snapshot(
                stats={"Luck": stat(64.0, "64")},
                loot_actual={"LEGENDARY": 3, "RARE": 11},
                loot_expected={"LEGENDARY": 1.2, "RARE": 12.4},
            ),
            snapshot(
                stats={"Luck": stat(78.0, "78")},
                loot_actual={"LEGENDARY": 1, "RARE": 13},
                loot_expected={"LEGENDARY": 1.4, "RARE": 13.1},
            ),
        )

    def test_the_index_is_what_dropped_over_what_was_expected(self) -> None:
        payload = overview.build_compare_runs_luck_loot(*self._measured())

        self.assertEqual("1.03x", payload.index_a, "14 drops against 13.6 expected")
        self.assertEqual("0.97x", payload.index_b)
        self.assertTrue(payload.available_a and payload.available_b)
        self.assertEqual("", payload.notice)

    def test_an_unmeasured_recording_is_not_a_zero(self) -> None:
        """The whole point of the block: absence is "we do not know"."""
        measured, _other = self._measured()
        unmeasured = snapshot(stats={"Luck": stat(78.0, "78")})

        payload = overview.build_compare_runs_luck_loot(measured, unmeasured)

        self.assertTrue(payload.available_a)
        self.assertFalse(payload.available_b)
        self.assertEqual("--", payload.index_b)
        self.assertNotEqual("0.00x", payload.index_b)
        self.assertIn("Run B did not measure", payload.notice)

    def test_one_measured_side_still_gets_its_own_numbers(self) -> None:
        """A half that can be computed is still worth showing."""
        measured, _other = self._measured()

        payload = overview.build_compare_runs_luck_loot(
            measured, snapshot(stats={"Luck": stat(78.0, "78")})
        )
        legendary = payload.rungs[0]

        self.assertEqual("3", legendary.actual_a)
        self.assertEqual("--", legendary.actual_b)
        self.assertIsNone(legendary.ratio_b)
        self.assertAlmostEqual(2.5, legendary.ratio_a)

    def test_neither_side_measured_says_why_and_shows_no_ladder(self) -> None:
        bare = snapshot()

        payload = overview.build_compare_runs_luck_loot(bare, bare)

        self.assertEqual((), payload.rungs)
        self.assertEqual(overview.LOOT_UNMEASURED_TEXT, payload.notice)

    def test_the_luck_stat_half_survives_a_recording_with_no_loot_counts(self) -> None:
        """The two halves fail apart, exactly as the live rarity card's do."""
        payload = overview.build_compare_runs_luck_loot(
            snapshot(stats={"Luck": stat(64.0, "64")}),
            snapshot(stats={"Luck": stat(78.0, "78")}),
        )

        self.assertEqual("64", payload.luck_a)
        self.assertEqual("78", payload.luck_b)
        self.assertEqual("-14", payload.luck_delta, "A - B, like every other delta")

    def test_the_verdict_stays_silent_when_the_two_runs_drew_alike(self) -> None:
        """A verdict on every frame would be noise; this one has a threshold."""
        measured, _other = self._measured()

        payload = overview.build_compare_runs_luck_loot(measured, measured)

        self.assertEqual("Both runs landed close to their expected loot", payload.verdict)

    def test_the_verdict_names_the_run_that_carried_luck_and_still_lost(self) -> None:
        lucky = snapshot(
            stats={"Luck": stat(20.0, "20")},
            loot_actual={"RARE": 20},
            loot_expected={"RARE": 10.0},
        )
        unlucky = snapshot(
            stats={"Luck": stat(90.0, "90")},
            loot_actual={"RARE": 5},
            loot_expected={"RARE": 10.0},
        )

        payload = overview.build_compare_runs_luck_loot(lucky, unlucky)

        self.assertEqual("B carried more Luck but drew less loot", payload.verdict)


class HubFactTests(unittest.TestCase):
    def _stages(self):
        return MetricTable(
            sections=(
                MetricSection(
                    headers=("Metric", "A", "B", "Delta"),
                    rows=(MetricRow("Time", "5:04", "5:11", "-7s"),),
                    title="Stage 1",
                ),
                MetricSection(
                    headers=("Metric", "A", "B", "Delta"),
                    rows=(MetricRow("Time", "6:19", "5:47", "+32s"),),
                    title="Stage 2",
                ),
            )
        )

    def test_a_disabled_section_gets_no_tile(self) -> None:
        """A tile that jumped to an empty tab is worse than no tile."""
        facts = overview.build_hub_facts(
            snapshot(items=("Key x2",)),
            snapshot(items=("Key x1",)),
            stages_table=self._stages(),
            enabled={"items": True},
        )

        self.assertEqual(["Items"], list(facts))

    def test_the_stage_fact_names_the_widest_gap_as_a_time(self) -> None:
        """The stages table carries raw seconds; a sentence cannot."""
        facts = overview.build_hub_facts(
            snapshot(),
            snapshot(),
            stages_table=self._stages(),
            enabled={"stage_summary": True},
        )

        self.assertEqual("Stage 2 diverges most · B −00:32", facts["Stages"])

    def test_the_weapon_fact_picks_the_weapon_with_the_most_changes(self) -> None:
        weapons = MetricTable(
            sections=(
                MetricSection(("", "A", "B", "Diff"), (MetricRow("Level", "3", "3", "--"),), "Bow"),
                MetricSection(
                    ("", "A", "B", "Diff"),
                    (MetricRow("Level", "5", "3", "+2"), MetricRow("Damage", "9", "4", "+5")),
                    "Sword",
                ),
            )
        )

        facts = overview.build_hub_facts(
            snapshot(), snapshot(), weapons_table=weapons, enabled={"weapons": True}
        )

        self.assertEqual("Sword · 2 differences", facts["Weapons"])


class LinkedInventoryTests(unittest.TestCase):
    """Both inventories open together, and sort together.

    They exist to be read against each other; A expanded beside a folded B is a
    comparison of 26 items with 6, and two different sort orders cannot be
    compared by eye at all.
    """

    def _tab(self):
        from tests.support.compare_runs import build_compare_runs_tab

        tab = build_compare_runs_tab()
        views = {}
        for side in ("a", "b"):
            view = SimpleNamespace(
                _expanded=False,
                sort_combo=None,
                sorted_calls=0,
            )
            view.expanded = lambda v=view: v._expanded
            view.set_expanded = lambda value, v=view: setattr(v, "_expanded", bool(value))
            view.on_sort_changed = lambda v=view: setattr(v, "sorted_calls", v.sorted_calls + 1)
            views[side] = view
            setattr(tab, f"_run_{side}_items_view", view)
        return tab, views

    def test_one_click_expands_both_panels(self) -> None:
        tab, views = self._tab()

        tab.toggle_compare_run_items_expanded("a")

        self.assertTrue(views["a"]._expanded)
        self.assertTrue(views["b"]._expanded)

    def test_clicking_the_folded_side_opens_both_rather_than_swapping_them(self) -> None:
        """Two `toggle_expanded` calls on drifted panels would swap, not align."""
        tab, views = self._tab()
        views["a"]._expanded = True

        tab.toggle_compare_run_items_expanded("b")

        self.assertTrue(views["a"]._expanded)
        self.assertTrue(views["b"]._expanded)

    def test_the_clicked_side_decides_the_direction(self) -> None:
        tab, views = self._tab()
        views["a"]._expanded = True
        views["b"]._expanded = True

        tab.toggle_compare_run_items_expanded("a")

        self.assertFalse(views["a"]._expanded)
        self.assertFalse(views["b"]._expanded)

    def test_sorting_one_panel_re_sorts_the_other(self) -> None:
        tab, views = self._tab()
        combos = {}
        for side, view in views.items():
            combo = SimpleNamespace(_data="rarity_desc" if side == "a" else "default")
            combo.currentData = lambda c=combo: c._data
            combo.findData = lambda value, c=combo: 0
            combo.setCurrentIndex = lambda _index, c=combo, s=side: setattr(
                c, "_data", combos["a"]._data
            )
            combos[side] = combo
            view.sort_combo = combo

        tab.on_compare_run_items_sort_changed("a")

        self.assertEqual("rarity_desc", combos["b"]._data)
        self.assertEqual(1, views["a"].sorted_calls)
        self.assertEqual(1, views["b"].sorted_calls)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
