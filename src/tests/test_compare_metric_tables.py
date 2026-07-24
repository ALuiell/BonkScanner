"""The Weapons/Tomes/Chaos cards as data, and its parity with the HTML path.

These three cards moved from a `QLabel` holding 7--16 KB of `<table>` markup to
a widget renderer, because the markup cost 63/23/65 ms of Qt layout per scrub
frame against 0.26 ms for the whole Python half of the frame. The move is only
safe while the two renderers agree about *content*, so the cases here compare
the model the widget renders against the HTML the formatter still produces --
every label, both values and the delta of every row.

That parity is the reason `_weapon_compare_metric_rows`,
`_tome_compare_metric_rows` and `_chaos_compare_overview_rows` were extracted
rather than reimplemented: if either side stops folding over them, one of these
cases fails.
"""

from __future__ import annotations

import html
import unittest
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from projections import formatting
from projections.metric_table import (
    DELTA_NEGATIVE,
    DELTA_NEUTRAL,
    DELTA_POSITIVE,
    MetricRow,
    MetricTable,
    delta_direction,
)


def stat(label: str, value, display: str):
    return SimpleNamespace(label=label, value=value, display_value=display)


def weapon(name: str, level: int, stats: dict[int, object]):
    return SimpleNamespace(
        name=name,
        level=level,
        upgrade_stat_ids=tuple(stats),
        upgraded_stats=stats,
        full_stats=stats,
    )


def tome(name: str, level: int, stat_label: str, value, display: str):
    return SimpleNamespace(
        name=name,
        level=level,
        stat_label=stat_label,
        value=value,
        display_value=display,
    )


def chaos(level: int, stats):
    return SimpleNamespace(level=level, stats=tuple(stats), ambiguous_rolls=0)


def chaos_stat(stat_id: int, label: str, value, display: str, rolls: int = 0):
    return SimpleNamespace(
        stat_id=stat_id,
        label=label,
        value=value,
        display_delta=display,
        rolls=rolls,
    )


def snapshot(**fields):
    defaults = {"weapons": (), "tomes": (), "chaos_tome": None}
    defaults.update(fields)
    return SimpleNamespace(**defaults)


class DeltaDirectionTests(unittest.TestCase):
    def test_the_sign_decides_the_direction(self) -> None:
        self.assertEqual(DELTA_POSITIVE, delta_direction("+2"))
        self.assertEqual(DELTA_NEGATIVE, delta_direction("-2"))
        self.assertEqual(DELTA_NEUTRAL, delta_direction("0"))
        self.assertEqual(DELTA_NEUTRAL, delta_direction("--"))
        self.assertEqual(DELTA_NEUTRAL, delta_direction(""))

    def test_a_row_reports_its_own_direction(self) -> None:
        self.assertEqual(
            DELTA_POSITIVE, MetricRow("Damage", "1.00x", "1.50x", "+0.50x").direction
        )


class MetricTableShapeTests(unittest.TestCase):
    def test_an_empty_table_is_falsey_and_keeps_its_caption(self) -> None:
        table = MetricTable(empty_text="No weapon data")

        self.assertFalse(table)
        self.assertEqual("No weapon data", table.empty_text)

    def test_equal_tables_compare_equal(self) -> None:
        """The diff-card dirty check is a `==` on this; it has to hold."""
        rows = (MetricRow("Level", "3", "5", "+2"),)
        first = MetricTable(sections=(formatting.MetricSection(("", "A", "B", "Diff"), rows, "Sword"),))
        second = MetricTable(sections=(formatting.MetricSection(("", "A", "B", "Diff"), rows, "Sword"),))

        self.assertEqual(first, second)


class WeaponsTableTests(unittest.TestCase):
    def _snapshots(self):
        snapshot_a = snapshot(
            weapons=(
                weapon("Sword", 3, {1: stat("Damage", 10.0, "10"), 2: stat("Area", 1.0, "1.00x")}),
                weapon("Bow", 1, {1: stat("Damage", 4.0, "4")}),
            )
        )
        snapshot_b = snapshot(
            weapons=(
                weapon("Sword", 5, {1: stat("Damage", 14.0, "14"), 2: stat("Area", 1.0, "1.00x")}),
            )
        )
        return snapshot_a, snapshot_b

    def test_one_section_per_weapon_in_name_order(self) -> None:
        table = formatting.build_compare_runs_weapons_table(*self._snapshots())

        self.assertEqual(["Bow", "Sword"], [section.title for section in table.sections])

    def test_the_section_subtitle_is_the_level_transition(self) -> None:
        table = formatting.build_compare_runs_weapons_table(*self._snapshots())
        sections = {section.title: section for section in table.sections}

        self.assertEqual("Lv. 3 -> 5", sections["Sword"].subtitle)
        self.assertEqual("Lv. 1 -> --", sections["Bow"].subtitle, "gone in run B")

    def test_level_leads_the_rows_and_upgrades_follow_by_label(self) -> None:
        table = formatting.build_compare_runs_weapons_table(*self._snapshots())
        sword = next(section for section in table.sections if section.title == "Sword")

        self.assertEqual(["Level", "Area", "Damage"], [row.label for row in sword.rows])
        self.assertEqual(("3", "5", "+2"), (sword.rows[0].value_a, sword.rows[0].value_b, sword.rows[0].delta))

    def test_every_row_also_appears_in_the_html_the_formatter_builds(self) -> None:
        snapshot_a, snapshot_b = self._snapshots()
        table = formatting.build_compare_runs_weapons_table(snapshot_a, snapshot_b)
        rendered = formatting.format_compare_runs_weapons_diff(snapshot_a, snapshot_b)

        for section in table.sections:
            self.assertIn(html.escape(section.title), rendered)
            for row in section.rows:
                for cell in (row.label, row.value_a, row.value_b, row.delta):
                    self.assertIn(html.escape(cell), rendered, f"{section.title}/{row.label}")

    def test_no_weapons_yields_the_same_caption_the_html_shows(self) -> None:
        table = formatting.build_compare_runs_weapons_table(snapshot(), snapshot())

        self.assertEqual((), table.sections)
        self.assertEqual(formatting.WEAPONS_COMPARE_EMPTY_TEXT, table.empty_text)
        self.assertIn(
            formatting.WEAPONS_COMPARE_EMPTY_TEXT,
            formatting.format_compare_runs_weapons_diff(snapshot(), snapshot()),
        )


class TomesTableTests(unittest.TestCase):
    def _snapshots(self):
        snapshot_a = snapshot(
            tomes=(
                tome("Fire", 2, "Damage", 10.0, "10%"),
                tome("Chaos", 4, "Chaos", None, "--"),
            )
        )
        snapshot_b = snapshot(
            tomes=(
                tome("Fire", 3, "Damage", 18.0, "18%"),
                tome("Chaos", 7, "Chaos", None, "--"),
            )
        )
        return snapshot_a, snapshot_b

    def test_a_normal_tome_shows_its_stat_row(self) -> None:
        table = formatting.build_compare_runs_tomes_table(*self._snapshots())
        fire = next(section for section in table.sections if section.title == "Fire")

        self.assertEqual(["Damage"], [row.label for row in fire.rows])
        self.assertEqual(("10%", "18%"), (fire.rows[0].value_a, fire.rows[0].value_b))

    def test_chaos_shows_its_level_instead(self) -> None:
        """Chaos has no single stat value, so its card compares levels."""
        table = formatting.build_compare_runs_tomes_table(*self._snapshots())
        chaos_section = next(section for section in table.sections if section.title == "Chaos")

        self.assertEqual(["Level"], [row.label for row in chaos_section.rows])
        self.assertEqual(("4", "7", "+3"), (
            chaos_section.rows[0].value_a,
            chaos_section.rows[0].value_b,
            chaos_section.rows[0].delta,
        ))

    def test_every_row_also_appears_in_the_html_the_formatter_builds(self) -> None:
        snapshot_a, snapshot_b = self._snapshots()
        table = formatting.build_compare_runs_tomes_table(snapshot_a, snapshot_b)
        rendered = formatting.format_compare_runs_tomes_diff(snapshot_a, snapshot_b)

        for section in table.sections:
            self.assertIn(html.escape(section.title), rendered)
            for row in section.rows:
                for cell in (row.label, row.value_a, row.value_b, row.delta):
                    self.assertIn(html.escape(cell), rendered, f"{section.title}/{row.label}")

    def test_no_tomes_yields_the_same_caption_the_html_shows(self) -> None:
        table = formatting.build_compare_runs_tomes_table(snapshot(), snapshot())

        self.assertEqual((), table.sections)
        self.assertEqual(formatting.TOMES_COMPARE_EMPTY_TEXT, table.empty_text)


class ItemsTableTests(unittest.TestCase):
    """The Items card is split: a summary line, plus a table only when expanded."""

    def _snapshots(self):
        return (
            snapshot(items=("Key x2", "Za Warudo x1", "Golden Ring x1")),
            snapshot(items=("Key x5", "Golden Ring x1", "Magnet x1")),
        )

    def test_the_table_is_empty_until_the_details_are_expanded(self) -> None:
        table = formatting.build_compare_runs_items_table(*self._snapshots())

        self.assertEqual((), table.sections)
        self.assertEqual(
            "",
            table.empty_text,
            "an empty caption is what tells the view to render nothing at all",
        )

    def test_expanded_lists_one_row_per_changed_item(self) -> None:
        table = formatting.build_compare_runs_items_table(*self._snapshots(), details_expanded=True)
        rows = {row.label: row for row in table.sections[0].rows}

        self.assertEqual(("Name", "A", "B", "Diff"), table.sections[0].headers)
        self.assertEqual({"Key", "Za Warudo", "Magnet"}, set(rows), "unchanged items are omitted")
        self.assertEqual(("2", "5", "+3"), (rows["Key"].value_a, rows["Key"].value_b, rows["Key"].delta))
        self.assertEqual(("1", "0", "-1"), (
            rows["Za Warudo"].value_a,
            rows["Za Warudo"].value_b,
            rows["Za Warudo"].delta,
        ))

    def test_each_row_carries_the_item_colour_the_html_used(self) -> None:
        table = formatting.build_compare_runs_items_table(*self._snapshots(), details_expanded=True)

        for row in table.sections[0].rows:
            self.assertTrue(row.label_color.startswith("#"), row.label)
            self.assertIn(row.label_color, formatting._format_item_delta_name(row.label))

    def test_the_summary_keeps_the_inline_lists_only_while_collapsed(self) -> None:
        snapshot_a, snapshot_b = self._snapshots()

        collapsed = formatting.build_compare_runs_items_summary(snapshot_a, snapshot_b)
        expanded = formatting.build_compare_runs_items_summary(
            snapshot_a, snapshot_b, details_expanded=True
        )

        self.assertIn("B has more", collapsed)
        self.assertNotIn("B has more", expanded, "the table below replaces the inline list")
        self.assertIn("Rarity Delta", expanded)

    def test_identical_inventories_say_so_and_show_no_table(self) -> None:
        same = snapshot(items=("Key x2",))

        summary = formatting.build_compare_runs_items_summary(same, same, details_expanded=True)
        table = formatting.build_compare_runs_items_table(same, same, details_expanded=True)

        self.assertIn("No item count differences", summary)
        self.assertEqual((), table.sections)

    def test_the_summary_and_table_together_cover_the_html_formatter(self) -> None:
        """Nothing the old single-string card showed may have been dropped."""
        snapshot_a, snapshot_b = self._snapshots()
        rendered = formatting.format_compare_runs_items_diff(
            snapshot_a, snapshot_b, details_expanded=True
        )
        table = formatting.build_compare_runs_items_table(
            snapshot_a, snapshot_b, details_expanded=True
        )

        self.assertIn("Rarity Delta", rendered)
        for row in table.sections[0].rows:
            for cell in (row.label, row.value_a, row.value_b, row.delta):
                self.assertIn(html.escape(cell), rendered, row.label)


class ChaosTableTests(unittest.TestCase):
    def _snapshots(self):
        snapshot_a = snapshot(
            chaos_tome=chaos(30, [chaos_stat(1, "Damage", 40.0, "+40%", rolls=4)])
        )
        snapshot_b = snapshot(
            chaos_tome=chaos(
                37,
                [
                    chaos_stat(1, "Damage", 84.0, "+84%", rolls=6),
                    chaos_stat(2, "Luck", 21.0, "+21%", rolls=3),
                ],
            )
        )
        return snapshot_a, snapshot_b

    def test_an_overview_section_and_a_stats_section(self) -> None:
        table = formatting.build_compare_runs_chaos_table(*self._snapshots())

        self.assertEqual(2, len(table.sections))
        self.assertEqual("Metric", table.sections[0].headers[0])
        self.assertEqual("Stat", table.sections[1].headers[0])
        self.assertEqual(
            "",
            table.sections[0].title,
            "a plain table names its first column instead of carrying a title",
        )

    def test_the_overview_compares_level_rolls_and_stat_count(self) -> None:
        table = formatting.build_compare_runs_chaos_table(*self._snapshots())
        overview = table.sections[0]

        self.assertEqual(["Level", "Tracked Rolls", "Stats"], [row.label for row in overview.rows])
        self.assertEqual(("30", "37", "+7"), (
            overview.rows[0].value_a,
            overview.rows[0].value_b,
            overview.rows[0].delta,
        ))
        self.assertEqual(("4", "9", "+5"), (
            overview.rows[1].value_a,
            overview.rows[1].value_b,
            overview.rows[1].delta,
        ))

    def test_a_stat_only_run_b_rolled_still_gets_a_row(self) -> None:
        table = formatting.build_compare_runs_chaos_table(*self._snapshots())
        stats = {row.label: row for row in table.sections[1].rows}

        self.assertIn("Luck", stats)
        self.assertEqual("--", stats["Luck"].value_a)
        self.assertEqual("+21%", stats["Luck"].value_b)

    def test_every_row_also_appears_in_the_html_the_formatter_builds(self) -> None:
        snapshot_a, snapshot_b = self._snapshots()
        table = formatting.build_compare_runs_chaos_table(snapshot_a, snapshot_b)
        rendered = formatting.format_compare_runs_chaos_diff(snapshot_a, snapshot_b)

        for section in table.sections:
            for row in section.rows:
                for cell in (row.label, row.value_a, row.value_b, row.delta):
                    self.assertIn(html.escape(cell), rendered, row.label)

    def test_no_chaos_data_yields_the_same_caption_the_html_shows(self) -> None:
        table = formatting.build_compare_runs_chaos_table(snapshot(), snapshot())

        self.assertEqual((), table.sections)
        self.assertEqual(formatting.CHAOS_COMPARE_EMPTY_TEXT, table.empty_text)
        self.assertIn(
            formatting.CHAOS_COMPARE_EMPTY_TEXT,
            formatting.format_compare_runs_chaos_diff(snapshot(), snapshot()),
        )

    def test_an_untracked_chaos_tome_has_no_stats_section(self) -> None:
        snapshot_a = snapshot(chaos_tome=chaos(3, []))
        snapshot_b = snapshot(chaos_tome=chaos(4, []))

        table = formatting.build_compare_runs_chaos_table(snapshot_a, snapshot_b)

        self.assertEqual(1, len(table.sections))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
