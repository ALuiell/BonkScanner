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
            from types import SimpleNamespace
            from PySide6.QtWidgets import (
                QApplication,
                QComboBox,
                QFrame,
                QGroupBox,
                QLabel,
                QPushButton,
                QTabWidget,
                QWidget,
            )
            from app import config
            from ui.dialogs import CleanupRecordingsDialog
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
            # The tab's contents wait for a show; this test drives the
            # widgets without one, so it asks for them. See `LazyPage`.
            view.build_now()

            page = view._tab.findChild(QWidget, "LiveStatsPage")
            items = view._tab.findChild(QGroupBox, "LiveStatsItems")
            assert page is not None and items is not None
            assert page.layout().columnStretch(0) == 3
            assert page.layout().columnStretch(1) == 1
            assert [
                view._detail_tabs.tabText(index)
                for index in range(view._detail_tabs.count())
            ] == ["Stats", "Loot", "Weapons", "Tomes", "Chaos", "Shrines", "Passives", "Damage Sources"]
            assert view._banishes_label.parent().objectName() == "LiveStatsBanishes"
            assert view._banishes_chips_container.objectName() == "BanishesChips"
            # Inside a bounded viewport now, not straight in the section: the
            # chips' flow layout grows its container's `minimumHeight` per
            # wrapped row, and that minimum came out of the item list above.
            chips_scroll = view._banishes_chips_container.parentWidget().parentWidget()
            assert chips_scroll.objectName() == "BanishesChipsScroll", (
                chips_scroll.objectName()
            )
            assert chips_scroll.parent().objectName() == "LiveStatsBanishes"
            assert not any(
                button.text() == "Show more"
                for button in items.findChildren(QPushButton)
            )
            assert items.findChild(QWidget, "cardContent") is not None

            # Match Live Stats: no empty zero-count rarity controls. The compact
            # coloured-dot summary appears only after real items arrive.
            rarity_summary = items.findChild(QLabel, "ItemsRaritySummary")
            assert rarity_summary is not None
            assert not rarity_summary.isVisibleTo(items)
            assert rarity_summary.text() == ""
            assert items.findChild(QWidget, "ItemsRarityFilters") is None
            assert not items.findChildren(QPushButton, "ItemsRarityFilterChip")
            sort_combo = items.findChild(QComboBox, "ItemsSortCombo")
            assert sort_combo is not None
            sort_label = items.findChild(QLabel, "ItemsSortLabel")
            assert sort_label is None
            assert (sort_combo.width(), sort_combo.height()) == (38, 22)
            assert [
                sort_combo.itemText(index)
                for index in range(sort_combo.count())
            ] == [
                "Default item order",
                "Rarity — highest first",
                "Rarity — lowest first",
            ]
            assert sort_combo.currentData() == "rarity_desc"
            assert sort_combo.view().minimumWidth() >= 190
            assert not sort_combo.isVisibleTo(items)

            view._items_section.update(("Big Bonk x2", "Key x3"))
            app.processEvents()
            assert rarity_summary.isVisibleTo(items)
            assert sort_combo.isVisibleTo(items)
            assert "Legendary" not in rarity_summary.text()
            assert "Common" not in rarity_summary.text()
            assert "&#9679;" in rarity_summary.text()
            assert ">2<" in rarity_summary.text()
            assert ">3<" in rarity_summary.text()

            # The chip list gets its room from stretch and from the ceiling on
            # Banishes below it -- never from a `minimumHeight` floor. A floor
            # cannot yield, and a QVBoxLayout that cannot compress a child still
            # positions the ones after it as if it had, so on a short panel the
            # divider and Banishes landed inside this scroll's rect and the item
            # chips drew over them.
            from PySide6.QtCore import Qt as _Qt
            from PySide6.QtWidgets import QScrollArea
            items_scroll = items.findChild(QScrollArea, "LiveStatsItemsScroll")
            assert items_scroll is not None
            assert items_scroll.minimumHeight() == 0, items_scroll.minimumHeight()
            assert (
                items_scroll.verticalScrollBarPolicy() == _Qt.ScrollBarAsNeeded
            )
            banishes_scroll = items.findChild(QScrollArea, "BanishesChipsScroll")
            assert banishes_scroll is not None
            assert banishes_scroll.maximumHeight() <= 66, (
                banishes_scroll.maximumHeight()
            )
            # The whole panel has to fit a short window, which is the same
            # statement as "nothing inside it overlaps".
            assert items.minimumSizeHint().height() <= 260, (
                items.minimumSizeHint().height()
            )
            assert {
                group.objectName()
                for group in page.findChildren(QGroupBox)
                if group.objectName().startswith("LiveStats")
            } == {
                "LiveStatsItems",
            }

            # "Segment Compare" is gone: its height followed its own contents,
            # so every scrub frame resized it and shoved the stage cards
            # around. What it said lives in Compare Details' header line, which
            # is hidden until a compare pin exists.
            compare_details = view._compare_details_group
            assert compare_details is not None
            assert not compare_details.isVisibleTo(view._tab)
            header = compare_details.findChild(QWidget, "CompareSegmentHeader")
            assert header is not None
            assert view._compare_details_summary_label.parent() is header
            # The two stacked labels above the rows are one line now, and the
            # anchor has a control of its own rather than only an Esc key.
            assert not hasattr(view, "_new_items_label")
            assert view._compare_clear_button.parent() is header
            assert view._compare_clear_button.text() == "Clear B"

            # Item changes are one wrapping row per rarity, not a four-column
            # chip grid. Nothing is pinned, so the card says so rather than
            # showing an empty row.
            rows_host = compare_details.findChild(QWidget, "CompareDetailsRows")
            assert rows_host is not None
            assert not hasattr(view, "_compare_details_items_label")
            notes = rows_host.findChildren(QLabel, "itemChipNote")
            assert [note.text() for note in notes] == [
                "No item changes in this segment"
            ], [note.text() for note in notes]

            # A pinned segment fills it with one row per rarity: a dot-and-total
            # badge, and the rarity's items beside it. Both wear the rarity
            # colour, which is what survives the wrapping the grid could not do.
            from types import SimpleNamespace
            base = SimpleNamespace(
                items=("Key x2",),
                game_time_seconds=10,
                player_level=4,
                mob_kills=100,
            )
            current = SimpleNamespace(
                items=("Key x1", "Bonker x1"),
                game_time_seconds=70,
                player_level=9,
                mob_kills=420,
            )
            view._compare_start_index = 0
            view._refresh_vod_compare_details(base, current, index=1)
            headline = view._compare_details_summary_label.text()
            assert "00:10" in headline and "01:10" in headline
            # Levels and kills, not only items -- the header carried the item
            # total alone while it subtracted the A/B pair in call order.
            assert "+5" in headline and "levels" in headline
            assert "+320" in headline and "kills" in headline
            item_rows = rows_host.findChildren(QWidget, "CompareRarityRow")
            assert len(item_rows) == 2, len(item_rows)
            labels = [
                (
                    row.findChild(QLabel, "CompareRarityBadge").text(),
                    row.findChild(QLabel, "CompareRarityItems").text(),
                )
                for row in item_rows
            ]
            # A rarity row is a coloured dot and a total; losses are one row of
            # their own, labelled rather than given a heading line above them.
            # The rarity colour is on the dot *and* on the name -- it used to be
            # on the dot alone, with every name a flat #E5E7EB.
            assert ">Big Bonk</span>" in labels[0][1], labels[0][1]
            assert labels[0][1].upper().count("#FACC15") == 1, labels[0][1]
            assert "#FACC15" in labels[0][0].upper(), labels[0][0]
            assert ">Lost<" in labels[1][0], labels[1][0]
            assert "Key -1" in labels[1][1]
            assert not rows_host.findChildren(QLabel, "CompareDetailsSection")

            # The way out of the segment reads as a control rather than as the
            # muted ghost buttons around it: it is on the same accent as the
            # A/B letters, and it is the only exit that does not need Esc.
            clear = view._compare_clear_button
            assert clear.property("class") is None, clear.property("class")
            assert clear.objectName() == "CompareSegmentClear"
            from ui.styles import build_qt_app_stylesheet
            sheet = build_qt_app_stylesheet("")
            assert "QPushButton#CompareSegmentClear {" in sheet
            clear.setStyleSheet(sheet)
            app.processEvents()
            assert clear.palette().button().color().name() == "#173352", (
                clear.palette().button().color().name()
            )

            # And the control clears the pin, which hides the card again.
            view._compare_clear_button.click()
            assert view._compare_start_index is None
            assert not compare_details.isVisibleTo(view._tab)

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

            # When data arrives the labels must leave their initial dimmed
            # state too. Re-polishing only the card does not make Qt
            # re-evaluate a selector that targets descendants.
            first_card = cards[0]
            first_card.setStyleSheet(
                'QLabel#StageChapterKills { color: #F8FAFC; }'
                'QFrame#StageChapterCard[hasData="false"] QLabel { color: #3D4756; }'
            )
            app.processEvents()
            kills = first_card.findChild(QLabel, "StageChapterKills")
            assert kills.palette().color(kills.foregroundRole()).name() == "#3d4756"
            first_card.set_state(has_data=True, is_current=False, is_anchor=False)
            app.processEvents()
            assert kills.palette().color(kills.foregroundRole()).name() == "#f8fafc"

            tabview.resize(900, 600)
            tabview.show()
            for _ in range(4):
                app.processEvents()
            assert sort_combo.y() == rarity_summary.y()
            assert sort_combo.x() > rarity_summary.x()
            assert sort_combo.y() < items_scroll.y()
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
            # Recordings adds the rate as one more compact name/value row in
            # the Chests card. Live Stats keeps its existing summary placement.
            assert "chests_per_minute" in view._chests_card_values
            assert (
                view._chests_per_minute_label
                is view._chests_card_values["chests_per_minute"]
            )
            assert view._chests_per_minute_label.objectName() == "LiveStatsLootStatValue"
            assert "Average chests/min" in {
                label.text() for label in loot_page.findChildren(QLabel)
            }

            # The library panel: search, the auto-filter footer, and the
            # button that used to sit between the name field and Delete. It
            # acts on the whole library, so its home is the footer.
            from PySide6.QtWidgets import QFrame, QLineEdit, QSpinBox
            chooser = view._chooser_group
            assert chooser is not None
            # Eight extra pixels keep the recording-row metadata inside the
            # viewport instead of creating a horizontal scrollbar; the whole
            # library then carries another 43 on top, so a recording name has
            # room before it elides.
            assert chooser.minimumWidth() == 241
            assert chooser.maximumWidth() == 371
            assert chooser.findChild(QLineEdit, "RecordingsSearch") is not None
            assert (
                view._list_frame.horizontalScrollBarPolicy()
                == _Qt.ScrollBarAlwaysOff
            )
            footer = chooser.findChild(QFrame, "RecordingsLibraryFooter")
            assert footer is not None
            assert footer.findChild(QSpinBox, "RecordingsMinimumSnapshots") is not None
            assert view._cleanup_btn.parent() is footer
            assert view._cleanup_btn.text() == "Recording cleanup"
            # Filled at build time, not on the first refresh: the panel starts
            # collapsed, so a footer that waits would read "0 recordings".
            assert view._library_summary_label.text() != "--"

            cleanup = CleanupRecordingsDialog(
                None,
                default_threshold=10,
                recordings=(
                    SimpleNamespace(snapshot_count=3),
                    SimpleNamespace(snapshot_count=10),
                    SimpleNamespace(snapshot_count=20),
                ),
            )
            assert cleanup.confirm_btn.text() == "Remove 1 recording"
            assert cleanup.confirm_btn.isEnabled()
            cleanup.threshold_entry.setText("21")
            assert cleanup.confirm_btn.text() == "Remove 3 recordings"
            cleanup.threshold_entry.setText("0")
            assert cleanup.confirm_btn.text() == "Remove 0 recordings"
            assert not cleanup.confirm_btn.isEnabled()

            # The record plaque is one compact context row: library selector,
            # current name, then the two explicit actions for that recording.
            # The rename field itself only appears while a rename is active.
            plaque = view._tab.findChild(QFrame, "RecordingPlaque")
            assert plaque is not None
            assert plaque.y() == 0

            title = view._tab.findChild(QLabel, "RecordingPlaqueTitle")
            library = view._tab.findChild(QPushButton, "RecordingPlaqueLibrary")
            assert title is not None
            assert library is not None
            # The drawer toggle leads the row: it opens a panel on the left
            # edge of the tab, so it sits at that edge rather than in the far
            # corner it used to occupy.
            assert library.x() < title.x()
            assert library.geometry().left() == plaque.contentsRect().left()
            assert view._title_label.parent() is plaque
            assert view._status_label.parent() is plaque
            assert not view._name_entry.isVisibleTo(plaque)
            assert view._select_btn.parent() is plaque
            assert view._select_btn.isCheckable()
            # Chevron plus count, pointing where the drawer will go. The word
            # is in the tooltip; the count is what earns space in this row.
            # The glyph comes from the module rather than being written here:
            # this script reaches the child through a Windows command line,
            # which is not UTF-8.
            from ui.tabs.player_stats.recordings import (
                LIBRARY_TOGGLE_CLOSED_CHEVRON,
                LIBRARY_TOGGLE_OPEN_CHEVRON,
            )
            # Stated, not assumed: the drawer's build-time state comes from the
            # saved config, which is not this test's subject.
            view.set_recordings_chooser_expanded(False, guided=False, remember=False)
            assert view._select_btn.text().startswith(LIBRARY_TOGGLE_CLOSED_CHEVRON)
            assert view._select_btn.text().rstrip().endswith("0")
            assert "Recordings" in view._select_btn.toolTip()
            # Opening it flips the chevron and moves the count with it.
            view.set_recordings_chooser_expanded(True, guided=False, remember=False)
            assert view._select_btn.text().startswith(LIBRARY_TOGGLE_OPEN_CHEVRON)
            assert view._chooser_group.isVisibleTo(view._tab)
            view.set_recordings_chooser_expanded(False, guided=False, remember=False)
            assert not view._chooser_group.isVisibleTo(view._tab)
            # Rename reuses the full secondary-action treatment from Templates:
            # real edit icon, explicit label, and the same 18 px icon scale.
            assert view._rename_btn.text() == "Rename"
            assert not view._rename_btn.icon().isNull()
            assert view._rename_btn.iconSize().width() == 18
            assert view._delete_btn.parent() is plaque
            assert view._delete_btn.text() == "Delete"
            assert plaque.findChild(QPushButton, "RecordingPlaqueMenu") is None

            legend = view._tab.findChild(QLabel, "RecordingScrubberLegend")
            legend_meta = view._tab.findChild(QLabel, "RecordingScrubberMeta")
            assert legend is not None
            assert legend_meta is not None
            assert legend.x() < legend_meta.x()
            assert legend_meta.geometry().right() == plaque.contentsRect().right()
            # The compact chest rate is part of the muted run metadata at the
            # far-right footer of the timeline.
            view._loaded_vod = SimpleNamespace(
                snapshots=(
                    SimpleNamespace(
                        stats={},
                        chests_per_minute=1.425,
                        player_level=None,
                        minute_avg_kps_at_capture=None,
                        five_minute_avg_kps_at_capture=None,
                        mob_kills=None,
                        kps_at_capture=None,
                    ),
                )
            )
            _, legend_meta_text = view._legend_parts(0)
            assert "Chests/min: 1.43" in legend_meta_text
            assert "#5C6675" in legend_meta_text
            view._loaded_vod = None
            # Nothing is loaded, so neither recording action is live.
            assert not view._rename_btn.isEnabled()
            assert not view._delete_btn.isEnabled()

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
            assert view._detail_tabs.headerControl() is view._stats_expanded_toggle
            corner = view._detail_tabs.cornerWidget()
            corner_center = corner.mapTo(
                view._detail_tabs, corner.rect().center()
            ).y()
            tab_center = view._detail_tabs.tabBar().geometry().center().y()
            assert abs(corner_center - tab_center) <= 1
            stats_page = view._detail_tabs.widget(0)
            assert view._stats_expanded_toggle.parent() is not stats_page

            # Both trailing timers own Recordings widgets/config callbacks and
            # must be cancelled with the page. Exercise real QTimers in this
            # isolated process so DeferredDelete cannot affect other Qt tests.
            from PySide6.QtCore import QCoreApplication
            from PySide6.QtTest import QTest
            view._loaded_vod = SimpleNamespace(
                snapshots=tuple(
                    SimpleNamespace(time_label=f"00:{index}0")
                    for index in range(3)
                )
            )
            view._snapshot_index = 0
            view._requested_snapshot_index = 0
            view._refresh_scrub_readout = lambda _index: None
            rendered = []
            view.display_loaded_vod_snapshot = rendered.append
            view._snapshot_throttle.cancel()
            view._snapshot_throttle.request(lambda: None)
            view.on_scrub_index_changed(2)
            assert view._snapshot_throttle.has_pending

            persisted_widths = []
            view._library_width_throttle.cancel()
            view._library_width_throttle.request(lambda: None)
            view._library_width_throttle.request(
                lambda: persisted_widths.append(True)
            )
            assert view._library_width_throttle.has_pending

            view._tab.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            QTest.qWait(550)
            QCoreApplication.processEvents()
            assert rendered == [], rendered
            assert persisted_widths == [], persisted_widths
            print("BLOCK9_RECORDINGS_QT_CONTEXT_OK")
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
        self.assertIn("BLOCK9_RECORDINGS_QT_CONTEXT_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
