"""The Session Stats tab: the two numbers it recovered, and the rule rows.

Two of the cases here exist because the data was already being computed and
thrown away. `SessionStats.found_seed_count()` is computed so the tracked-item
percentages have a denominator, and `config.TOTAL_REROLLS` is incremented and
persisted on every reroll -- neither reached any tab, and neither did the
number that falls out of them, which is rerolls per seed.

The rest is about the tracked-item rows. A rule is a set of items *and* a
condition, and both used to be flattened into one string on the way to the tab.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from app.map_scoring import format_stats, map_highlight_rows
from ui.tabs.session_stats import (
    CONDITION_LABELS,
    average_bar_fractions,
    condition_label,
    rerolls_per_seed,
)


class SessionStatsProjectionTests(unittest.TestCase):
    def test_rerolls_per_seed_waits_for_a_seed(self) -> None:
        # Division by the seed count, and the seed count starts at zero -- so
        # the interesting case is the one before the first seed is found.
        self.assertEqual(rerolls_per_seed(3412, 18), "190")
        self.assertEqual(rerolls_per_seed(50, 0), "--")
        self.assertEqual(rerolls_per_seed(0, 0), "--")
        self.assertEqual(rerolls_per_seed(12000, 3), "4,000")

    def test_the_bars_compare_targets_against_each_other(self) -> None:
        # Against the largest, not a fixed ceiling: the question is which
        # target eats the rerolls, which is a comparison between rows.
        self.assertEqual(average_bar_fractions([4.0, 8.0, 2.0]), [0.5, 1.0, 0.25])
        self.assertEqual(average_bar_fractions([]), [])
        # Nothing found yet: every average is zero, and no bar may divide by it.
        self.assertEqual(average_bar_fractions([0.0, 0.0]), [0.0, 0.0])

    def test_only_the_two_conditions_the_dialog_can_produce(self) -> None:
        # `TrackedItemRule.mode` has five values in the tracker, but the
        # settings dialog writes `map_1_only` or `all_run` and nothing else.
        self.assertEqual(set(CONDITION_LABELS), {"map_1_only", "all_run"})
        self.assertEqual(condition_label("map_1_only"), "Map 1")
        self.assertEqual(condition_label("all_run"), "All run")
        # An unreachable mode must not render an empty badge.
        self.assertEqual(condition_label("before_stage"), "All run")
        self.assertEqual(condition_label(""), "All run")

    def test_the_map_rows_carry_the_same_numbers_as_the_logged_line(self) -> None:
        # `format_stats` still writes the one-line version into the log. The
        # cards must not drift from it.
        stats = {
            "Shady Guy": 2,
            "Moais": 4,
            "Boss Curses": 1,
            "Magnet Shrines": 3,
        }
        rows, score = map_highlight_rows(stats, [])
        line = format_stats(stats, [])
        for name, value in rows:
            self.assertIn(str(value), line, f"{name} missing from {line!r}")
        self.assertIn(f"{score:.1f}", line)
        self.assertEqual([name for name, _value in rows][:2], ["Shady Guy", "Moais"])


class SessionStatsTabWidgetTests(unittest.TestCase):
    def _run(self, body: str) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import QApplication, QLabel
            from ui.tabs.session_stats import SessionStatsTab
            from ui.styles import build_qt_app_stylesheet

            from PySide6.QtCore import QEvent

            app = QApplication([])
            app.setStyleSheet(build_qt_app_stylesheet(""))

            # Flush what a running event loop would flush. `_clear_layout`
            # removes widgets with `deleteLater`, so without the loop's
            # DeferredDelete pass the old rows are still in the tree and
            # `findChildren` still sees them. The app has a loop; this stands
            # in for it.
            def settle():
                app.processEvents()
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                app.processEvents()
            opened = []
            view = SessionStatsTab(on_open_tracked_item_settings=lambda: opened.append(1))
            root = view.build()
            root.resize(1100, 700)
            root.show()
            app.processEvents()

            def texts():
                return [w.text() for w in root.findChildren(QLabel) if w.text()]

            def object_names():
                return [w.objectName() for w in root.findChildren(QLabel)]
            """
        ) + textwrap.dedent(body)
        env = os.environ.copy()
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_recovered_numbers_are_on_screen(self) -> None:
        self._run(
            """
            view.set_counters(rerolls=3412, seeds_found=18, all_time_rerolls=128004)
            settle()
            shown = texts()
            assert "3,412" in shown, shown
            assert "18" in shown, shown          # seeds found
            assert "190" in shown, shown         # rerolls per seed
            assert "128,004" in shown, shown     # all-time rerolls
            """
        )

    def test_a_rule_renders_as_its_items_and_its_condition(self) -> None:
        self._run(
            """
            view.set_tracked_rows([
                {"item_names": ("Anvil",), "mode": "map_1_only",
                 "count": 12, "percent": 66.7, "label": "Anvil T1"},
                {"item_names": ("Kevin", "Electric Plug"), "mode": "all_run",
                 "count": 4, "percent": 22.2, "label": "Kevin + Electric Plug"},
            ])
            settle()
            shown = texts()

            # The items, each as its own chip, joined by a plus.
            for item in ("Anvil", "Kevin", "Electric Plug"):
                assert item in shown, (item, shown)
            assert "+" in shown, shown

            # The condition, which the old join kept only as a `T1` suffix.
            assert "Map 1" in shown and "All run" in shown, shown

            # ...and the label, which repeats the items, is not printed.
            assert "Anvil T1" not in shown, shown
            assert "Kevin + Electric Plug" not in shown, shown

            # Chips are rarity-coloured through the shared tag roles.
            names = object_names()
            assert "tagLegendary" in names, names   # Anvil
            assert "tagRare" in names, names        # Kevin
            assert "tagUncommon" in names, names    # Electric Plug
            """
        )

    def test_a_rule_with_no_percent_yet_shows_a_dash_not_a_zero(self) -> None:
        # `percent` is None until a seed is found. `0%` would be a claim.
        self._run(
            """
            view.set_tracked_rows([
                {"item_names": ("Clover",), "mode": "all_run",
                 "count": 0, "percent": None, "label": "Clover"},
            ])
            settle()
            shown = texts()
            assert "--" in shown, shown
            assert "0%" not in shown, shown
            """
        )

    def test_both_map_cards_say_so_when_there_is_no_map(self) -> None:
        self._run(
            """
            view.set_map_highlights(best_stats=None, worst_stats=None, active_templates=[])
            settle()
            assert texts().count("No map yet") == 2, texts()

            view.set_map_highlights(
                best_stats={"Shady Guy": 2, "Moais": 4},
                worst_stats=None,
                active_templates=[],
            )
            settle()
            shown = texts()
            assert shown.count("No map yet") == 1, shown
            assert "Shady Guy" in shown, shown
            """
        )

    def test_the_gear_opens_the_tracked_item_settings(self) -> None:
        self._run(
            """
            from PySide6.QtWidgets import QPushButton
            gears = [b for b in root.findChildren(QPushButton) if b.objectName() == "iconBtn"]
            assert len(gears) == 1, gears
            gears[0].click()
            assert opened == [1], opened
            """
        )


if __name__ == "__main__":
    unittest.main()
