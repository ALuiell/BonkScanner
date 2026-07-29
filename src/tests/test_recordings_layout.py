from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite


class RecordingsLayoutTests(unittest.TestCase):
    def test_recordings_reuses_the_live_stats_card_composition(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from PySide6.QtWidgets import (
                QApplication,
                QFrame,
                QGroupBox,
                QLabel,
                QPushButton,
                QTabWidget,
                QWidget,
            )
            from app import config
            from ui.tabs.player_stats.recordings import RecordingsTab

            config.user_config.pop("LIVE_STATS_EXPANDED", None)
            config.save_config = lambda _payload: None

            class Library:
                index = ()
                def ensure_refresh(self):
                    pass

            app = QApplication([])
            tabview = QTabWidget()
            view = RecordingsTab(
                tabview=tabview,
                vod_library=Library(),
                window=lambda: None,
                vod_recorder=lambda: None,
                is_active=lambda: True,
                log=lambda *_args, **_kwargs: None,
            )
            view.build()

            page = view._tab.findChild(QWidget, "LiveStatsPage")
            items = view._tab.findChild(QGroupBox, "LiveStatsItems")
            assert page is not None and items is not None
            assert page.layout().columnStretch(0) == 3
            assert page.layout().columnStretch(1) == 1
            assert [
                view._detail_tabs.tabText(index)
                for index in range(view._detail_tabs.count())
            ] == ["Stats", "Loot", "Weapons", "Tomes", "Chaos", "Damage Sources"]
            assert view._banishes_label.parent().objectName() == "LiveStatsBanishes"
            assert not any(
                button.text() == "Show more"
                for button in items.findChildren(QPushButton)
            )
            assert items.findChild(QWidget, "cardContent") is not None
            assert {
                group.objectName()
                for group in page.findChildren(QGroupBox)
                if group.objectName().startswith("LiveStats")
            } == {
                "LiveStatsRunSummary",
                "LiveStatsStageSummary",
                "LiveStatsPowerups",
                "LiveStatsItems",
            }

            tabview.resize(900, 600)
            tabview.show()
            for _ in range(4):
                app.processEvents()
            stats_page = view._detail_tabs.widget(0)
            grids = stats_page.findChildren(QWidget, "LiveStatsCardGrid")
            compact = next(
                grid for grid in grids if grid.property("viewMode") == "compact"
            )
            expanded = next(
                grid for grid in grids if grid.property("viewMode") == "expanded"
            )
            assert compact.isVisible()
            assert not expanded.isVisible()
            assert len(compact.findChildren(QFrame, "StatCard")) == 5
            assert {
                (card.width(), card.height())
                for card in compact.findChildren(QFrame, "StatCard")
            } == {(160, 174)}
            assert "DMG" in [
                label.text()
                for label in compact.findChildren(
                    QLabel, "LiveStatsCompactStatName"
                )
            ]

            loot_page = view._detail_tabs.widget(1)
            loot_groups = {
                group.title() for group in loot_page.findChildren(QGroupBox)
            }
            assert "Chests (Expected = key procs)" in loot_groups
            assert "Item Rarity (Expected = items by tier)" in loot_groups
            """
        )
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


if __name__ == "__main__":
    unittest.main()
