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
                "LiveStatsItems",
            }

            # "Segment Compare" is gone: its height followed its own contents,
            # so every scrub frame resized it and shoved the stage cards
            # around. Its gains preview lives in Compare Details, which is
            # hidden until a compare pin exists.
            compare_details = view._compare_details_group
            assert compare_details is not None
            assert not compare_details.isVisibleTo(view._tab)
            assert view._new_items_label.parent() is compare_details

            # The Stage Summary table became four cards. They keep the table's
            # label dicts, so `set_stage_summary_labels` still writes them --
            # which is what makes this a layout change and not a data one.
            cards = page.findChildren(QFrame, "StageChapterCard")
            assert len(cards) == 4, len(cards)
            assert [card.stage_number for card in cards] == [1, 2, 3, 4]
            assert len(view._stage_summary_labels) == 4
            assert set(view._stage_summary_labels[0]) == {
                "stage",
                "time",
                "kills",
                "items",
            }
            # Nothing is loaded, so every stage is dimmed and none is current.
            assert all(card.property("hasData") is False for card in cards)
            assert all(card.property("current") is False for card in cards)

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
            # The chest-rate estimate moved here out of the deleted
            # "Run Summary" card: it predicts a rate from two stats and counts
            # no chests, so it belongs beside the counters, not beside the
            # measured run totals.
            assert view._chests_per_minute_label.parent().findChild(
                QLabel, "RecordingsChestRateEstimate"
            ) is not None
            assert loot_page.findChild(QLabel, "RecordingsChestRateEstimate") is not None

            # The library panel: search, the auto-filter footer, and the
            # button that used to sit between the name field and Delete. It
            # acts on the whole library, so its home is the footer.
            from PySide6.QtWidgets import QFrame, QLineEdit, QSpinBox
            chooser = view._chooser_group
            assert chooser is not None
            assert chooser.findChild(QLineEdit, "RecordingsSearch") is not None
            footer = chooser.findChild(QFrame, "RecordingsLibraryFooter")
            assert footer is not None
            assert footer.findChild(QSpinBox, "RecordingsMinimumSnapshots") is not None
            assert view._cleanup_btn.parent() is footer
            # Filled at build time, not on the first refresh: the panel starts
            # collapsed, so a footer that waits would read "0 recordings".
            assert view._library_summary_label.text() != "--"

            # The record plaque. The name is a heading; the field that used to
            # occupy the row full-time appears only during a rename, and Delete
            # is behind the menu button rather than one mis-click from it.
            plaque = view._tab.findChild(QFrame, "RecordingPlaque")
            assert plaque is not None
            assert view._title_label.parent() is plaque
            assert view._status_label.parent() is plaque
            assert not view._name_entry.isVisibleTo(plaque)
            assert view._menu_btn.menu() is not None
            assert [
                action.text()
                for action in view._menu_btn.menu().actions()
                if action.text()
            ] == ["Rename", "Delete"]
            # Nothing is loaded, so neither affordance is live.
            assert not view._rename_btn.isEnabled()
            assert not view._menu_btn.isEnabled()

            # Escape abandons a rename. Asserted here rather than in
            # `test_recording_plaque.py` because it needs a real QKeyEvent,
            # which is fatal to build once the suite has mock installed.
            from PySide6.QtCore import QEvent, Qt
            from PySide6.QtGui import QKeyEvent
            from ui.tabs.player_stats.recordings import _NameEdit

            field = _NameEdit()
            field.setText("950k")
            cancels = []
            field.cancelled.connect(lambda: cancels.append(True))
            field.keyPressEvent(
                QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
            )
            assert cancels == [True]
            assert field.text() == "950k"

            # "Expanded" is a corner widget of the detail tab bar now, not a
            # full-width row above the stat grid.
            assert view._detail_tabs.cornerWidget() is view._stats_expanded_toggle
            stats_page = view._detail_tabs.widget(0)
            assert view._stats_expanded_toggle.parent() is not stats_page
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
