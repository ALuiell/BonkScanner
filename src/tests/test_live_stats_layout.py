from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from ui.tabs.player_stats.live_stats import responsive_card_column_count
from ui.tabs.player_stats.stat_cards import (
    chaos_card_column_count,
    damage_source_column_count,
    damage_source_share_text,
)


class LiveStatsResponsiveLayoutTests(unittest.TestCase):
    def test_card_column_count_tracks_available_width(self) -> None:
        self.assertEqual(responsive_card_column_count(211), 1)
        self.assertEqual(responsive_card_column_count(432), 2)
        self.assertEqual(responsive_card_column_count(652), 3)
        self.assertEqual(responsive_card_column_count(872), 4)
        self.assertEqual(responsive_card_column_count(2000), 4)

    def test_chaos_grid_uses_five_columns_only_when_they_fit(self) -> None:
        self.assertEqual(chaos_card_column_count(823), 4)
        self.assertEqual(chaos_card_column_count(824), 5)
        self.assertEqual(chaos_card_column_count(2000), 5)

    def test_damage_source_layout_and_share_formatting(self) -> None:
        self.assertEqual(damage_source_column_count(885), 2)
        self.assertEqual(damage_source_column_count(886), 3)
        self.assertEqual(damage_source_share_text(1, 2000), "<0.1%")
        self.assertEqual(damage_source_share_text(0, 2000), "0%")
        self.assertEqual(damage_source_share_text(100, 200), "50.0%")
        self.assertEqual(damage_source_share_text(None, 200), "--")
        self.assertEqual(damage_source_share_text(100, None), "--")

    def test_build_uses_v4_two_column_page_structure(self) -> None:
        script = textwrap.dedent(
            """
            import os
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import src
            from types import SimpleNamespace
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import (
                QApplication,
                QFrame,
                QGroupBox,
                QLabel,
                QProgressBar,
                QPushButton,
                QScrollArea,
                QTabWidget,
                QWidget,
            )
            from app import config
            from ui.tabs.player_stats.live_stats import LiveStatsTab

            config.user_config.pop("LIVE_STATS_EXPANDED", None)
            saved_configs = []
            config.save_config = lambda payload: saved_configs.append(dict(payload))

            class Recorder:
                is_recording = False
                def elapsed_label(self):
                    return "00:00"

            class SnapshotStore:
                def reset_for_new_match(self):
                    pass

            app = QApplication([])
            tabview = QTabWidget()
            view = LiveStatsTab(
                tabview=tabview,
                live_run_tracker=lambda: object(),
                vod_recorder=lambda: Recorder(),
                vod_snapshots=lambda: (),
                selected_snapshot_index=lambda: None,
                recording_waiting_mode=lambda: None,
                ensure_live_snapshot_store=lambda: SnapshotStore(),
                is_recording_armed=lambda: False,
                on_toggle_recording=lambda: None,
                on_snapshot_selected=lambda *_args, **_kwargs: None,
            ).build()
            page = view.root_widget.findChild(QWidget, "LiveStatsPage")
            items = view.root_widget.findChild(QGroupBox, "LiveStatsItems")
            assert page is not None and items is not None
            assert page.layout().columnStretch(0) == 3
            assert page.layout().columnStretch(1) == 1
            assert [
                view._detail_tabs.tabText(index)
                for index in range(view._detail_tabs.count())
            ] == ["Stats", "Loot", "Weapons", "Tomes", "Chaos", "Damage Sources", "Build Progression"]
            build_card = view.root_widget.findChild(QFrame, "BuildProgressionCard")
            assert build_card is not None
            assert build_card.findChild(QLabel, "BuildProgressionName") is not None
            assert build_card.findChild(QLabel, "BuildProgressionProgress").text() == "NOT CONFIGURED"
            build_scroll = build_card.findChild(QScrollArea, "BuildProgressionScroll")
            build_rows = build_card.findChild(QWidget, "BuildProgressionRows")
            assert build_scroll is not None and build_rows is not None
            assert build_scroll.widget() is build_rows
            assert build_scroll.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
            assert build_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert view._banishes_label.parent().objectName() == "LiveStatsBanishes"
            assert view._banishes_label.objectName() == "LiveStatsBanishesText"
            assert view._banishes_chips_container.objectName() == "BanishesChips"
            # Inside a bounded viewport, as in Recordings: the chips' flow layout
            # grows its container's `minimumHeight` per wrapped row, and that
            # minimum is taken out of the item list's share of the panel.
            chips_scroll = view._banishes_chips_container.parentWidget().parentWidget()
            assert chips_scroll.objectName() == "BanishesChipsScroll", (
                chips_scroll.objectName()
            )
            assert chips_scroll.parent().objectName() == "LiveStatsBanishes"
            view.set_items(tuple(f"Item {index}" for index in range(12)))
            assert not any(
                button.text() == "Show more"
                for button in items.findChildren(QPushButton)
            )
            chips = items.findChild(QWidget, "cardContent")
            assert chips is not None
            assert len(chips.findChildren(QLabel)) == 12
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

            tabview.resize(900, 550)
            tabview.show()
            for _ in range(4):
                app.processEvents()
            stats_page = view._detail_tabs.widget(0)
            stats_grids = stats_page.findChildren(QWidget, "LiveStatsCardGrid")
            compact_grid = next(
                grid for grid in stats_grids if grid.property("viewMode") == "compact"
            )
            expanded_grid = next(
                grid for grid in stats_grids if grid.property("viewMode") == "expanded"
            )
            expanded_toggle = view._detail_tabs.headerControl()
            assert expanded_toggle is not None
            assert expanded_toggle.objectName() == "LiveStatsExpandedToggle"
            corner = view._detail_tabs.cornerWidget()
            corner_center = corner.mapTo(
                view._detail_tabs, corner.rect().center()
            ).y()
            tab_center = view._detail_tabs.tabBar().geometry().center().y()
            assert abs(corner_center - tab_center) <= 1
            assert view._detail_tabs._header_frame.width() == view._detail_tabs.width()
            assert view._detail_tabs._header_frame.height() == view._detail_tabs.tabBar().height()
            assert not expanded_toggle.isChecked()
            assert compact_grid.isVisible()
            assert not expanded_grid.isVisible()
            compact_stat_names = [
                label.text()
                for label in compact_grid.findChildren(QLabel, "LiveStatsCompactStatName")
            ]
            assert "DMG" in compact_stat_names
            assert "AS" in compact_stat_names
            assert "XP" in compact_stat_names
            assert expanded_grid.findChildren(QLabel, "LiveStatsExpandedStatName")
            assert expanded_grid.findChildren(QLabel, "LiveStatsExpandedStatValue")
            compact_cards = compact_grid.findChildren(QFrame, "StatCard")
            assert len(compact_cards) == 5
            assert {(card.width(), card.height()) for card in compact_cards} == {(160, 174)}
            expanded_toggle.setChecked(True)
            app.processEvents()
            assert not compact_grid.isVisible()
            assert expanded_grid.isVisible()
            assert config.user_config["LIVE_STATS_EXPANDED"] is True
            assert saved_configs[-1]["LIVE_STATS_EXPANDED"] is True
            expanded_toggle.setChecked(False)
            app.processEvents()
            assert compact_grid.isVisible()
            assert not expanded_grid.isVisible()
            assert config.user_config["LIVE_STATS_EXPANDED"] is False
            assert saved_configs[-1]["LIVE_STATS_EXPANDED"] is False
            outer_scroll = view.root_widget.findChildren(QScrollArea)[0]
            geometry_by_tab = []
            for index in range(view._detail_tabs.count()):
                view._detail_tabs.setCurrentIndex(index)
                for _ in range(3):
                    app.processEvents()
                geometry_by_tab.append((
                    view._detail_tabs.width(),
                    view._detail_tabs.height(),
                    page.width(),
                    page.height(),
                    outer_scroll.verticalScrollBar().isVisible(),
                ))
            assert len(set(geometry_by_tab)) == 1, geometry_by_tab

            chaos_stats = tuple(
                SimpleNamespace(
                    stat_id=30 + index,
                    label=f"Chaos stat {index}",
                    value=float(index + 1),
                    display_delta=f"+{index + 1}%",
                    rolls=index + 1,
                )
                for index in range(6)
            )
            view.set_chaos_tome_card(
                SimpleNamespace(
                    level=10,
                    ambiguous_rolls=0,
                    stats=chaos_stats,
                )
            )
            chaos_page = view._detail_tabs.widget(4)
            view._detail_tabs.setCurrentIndex(4)
            app.processEvents()
            chaos_cards = [
                card
                for card in chaos_page.findChildren(QFrame, "StatCard")
                if any(
                    label.text().endswith((" roll", " rolls"))
                    and not label.text().startswith("Tracked")
                    for label in card.findChildren(QLabel)
                )
            ]
            assert len(chaos_cards) == 6
            assert len({card.geometry().y() for card in chaos_cards[:4]}) == 1
            assert chaos_cards[4].geometry().y() > chaos_cards[0].geometry().y()
            chaos_scroll = chaos_page.findChild(QScrollArea)
            assert chaos_scroll.horizontalScrollBar().maximum() == 0
            for card in chaos_cards:
                assert card.maximumWidth() > 1000
                labels = card.findChildren(QLabel)
                assert not labels[0].wordWrap()
                assert "font-size: 13px" in labels[0].styleSheet()
                rolls_label = next(label for label in labels if "roll" in label.text())
                assert "font-size: 12px" in rolls_label.styleSheet()

            view._stat_cards.display_damage_sources((
                SimpleNamespace(source_key="zero", source_name="Zero Source", damage=0.0),
                SimpleNamespace(source_key="katana", source_name="Katana", damage=300.0),
                SimpleNamespace(source_key="dice", source_name="Dice", damage=100.0),
                SimpleNamespace(source_key="staff", source_name="Fire Staff", damage=400.0),
            ))
            damage_page = view._detail_tabs.widget(5)
            view._detail_tabs.setCurrentIndex(5)
            for _ in range(3):
                app.processEvents()
            source_names = damage_page.findChildren(QLabel, "DamageSourceName")
            assert [label.text() for label in source_names] == [
                "Fire Staff", "Katana", "Dice", "Zero Source"
            ]
            source_cards = [label.parent() for label in source_names]
            assert len({card.geometry().y() for card in source_cards[:2]}) == 1
            assert source_cards[2].geometry().y() > source_cards[0].geometry().y()
            assert damage_page.findChild(QLabel, "DamageSourcesSummaryValue").text() == "800"
            assert damage_page.findChild(QLabel, "DamageSourcesSummaryCount").text() == "4 sources"
            assert [
                label.text()
                for label in damage_page.findChildren(QLabel, "DamageSourcePercent")
            ] == ["50.0%", "37.5%", "12.5%", "0%"]
            assert [
                bar.value()
                for bar in damage_page.findChildren(QProgressBar, "DamageSourceBar")
            ] == [500, 375, 125, 0]
            damage_scroll = damage_page.findChild(QScrollArea)
            assert damage_scroll.horizontalScrollBar().maximum() == 0

            tabview.resize(1500, 740)
            for _ in range(4):
                app.processEvents()
            view._detail_tabs.setCurrentIndex(4)
            app.processEvents()
            assert len({card.geometry().y() for card in chaos_cards[:5]}) == 1
            assert chaos_cards[5].geometry().y() > chaos_cards[0].geometry().y()
            view._detail_tabs.setCurrentIndex(5)
            app.processEvents()
            assert len({card.geometry().y() for card in source_cards[:3]}) == 1
            assert source_cards[3].geometry().y() > source_cards[0].geometry().y()

            tabview.resize(1040, 740)
            for _ in range(4):
                app.processEvents()
            page_height_before_items = page.height()
            outer_scroll_maximum = outer_scroll.verticalScrollBar().maximum()
            rendered_item_sets = []
            original_render_chips = view._items_section._render_chips
            def count_rendered_items(*args, **kwargs):
                rendered_item_sets.append(tuple(args[0]))
                return original_render_chips(*args, **kwargs)
            view._items_section._render_chips = count_rendered_items
            many_items = tuple(f"Item {index}" for index in range(180))
            view.set_items(many_items)
            for _ in range(6):
                app.processEvents()
            items_scroll = items.findChild(QScrollArea, "LiveStatsItemsScroll")
            assert items_scroll is not None
            assert items_scroll.verticalScrollBar().maximum() > 0
            assert page.height() == page_height_before_items
            assert outer_scroll.verticalScrollBar().maximum() == outer_scroll_maximum
            assert view._banishes_label.isVisible()

            view.set_items(many_items)
            for _ in range(2):
                app.processEvents()
            assert len(rendered_item_sets) == 1

            scrollbar = items_scroll.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum() // 2)
            saved_scroll_position = scrollbar.value()
            changed_items = many_items[:-1] + ("Changed item",)
            view.set_items(changed_items)
            for _ in range(4):
                app.processEvents()
            assert len(rendered_item_sets) == 2
            assert scrollbar.value() == min(
                saved_scroll_position,
                scrollbar.maximum(),
            )
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
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
