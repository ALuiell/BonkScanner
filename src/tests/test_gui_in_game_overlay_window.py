from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QWidget

from app import config
from core.map_markers import (
    MapMarkerSnapshot,
    MapViewport,
    WorldMapMarker,
    build_marker_palette,
)
from gui_in_game_overlay_window import InGameOverlayWindow, MapMarkerLayer


def _test_overlay_config() -> dict:
    return {
        "widgets": {
            "scanner": {"enabled": True, "x": 0, "y": 0, "scale": 1.0},
            "recording": {"enabled": True, "x": 0, "y": 0, "scale": 1.0},
            "kps": {"enabled": True, "x": 0, "y": 0, "scale": 1.0},
            "powerups": {"enabled": True, "x": 0, "y": 0, "scale": 1.0},
            "luck_rarity": {"enabled": True, "x": 0, "y": 0, "scale": 1.0, "show_bar": True},
            "stats": {"enabled": True, "x": 0, "y": 0, "scale": 1.0, "selected_stats": ["Damage", "Difficulty", "XP Gain", "Luck"]},
            "event_timer": {"enabled": True, "x": 0, "y": 0, "scale": 1.0, "warning_seconds": 15},
        }
    }


class InGameOverlayWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_map_marker_layer_only_appears_for_open_map_content(self) -> None:
        layer = MapMarkerLayer()
        viewport = MapViewport(20, 30, 600, 600)
        try:
            layer.set_snapshot(
                MapMarkerSnapshot(
                    map_id=1,
                    map_open=True,
                    world_size=600,
                    viewport=viewport,
                    markers=(
                        WorldMapMarker("auto:1", "moai", 10, -20),
                    ),
                ),
                scale=1.0,
            )
            self.assertFalse(layer.isHidden())

            layer.set_snapshot(MapMarkerSnapshot(), scale=1.0)
            self.assertTrue(layer.isHidden())
        finally:
            layer.close()

    def test_hold_palette_can_show_without_existing_markers(self) -> None:
        layer = MapMarkerLayer()
        viewport = MapViewport(20, 30, 600, 600)
        snapshot = MapMarkerSnapshot(
            map_id=1,
            map_open=True,
            world_size=600,
            viewport=viewport,
        )
        try:
            layer.set_snapshot(snapshot, scale=1.0)
            self.assertTrue(layer.isHidden())

            layer.set_palette(
                build_marker_palette(300, 300, viewport=viewport)
            )
            self.assertFalse(layer.isHidden())

            layer.set_snapshot(MapMarkerSnapshot(), scale=1.0)
            self.assertTrue(layer.isHidden())
        finally:
            layer.close()

    def test_unchanged_marker_snapshot_does_not_repeat_native_visibility_work(self) -> None:
        class CountingLayer(MapMarkerLayer):
            def __init__(self) -> None:
                self.visibility_calls = 0
                self.raise_calls = 0
                super().__init__()

            def setVisible(self, visible: bool) -> None:
                self.visibility_calls += 1
                super().setVisible(visible)

            def raise_(self) -> None:
                self.raise_calls += 1
                super().raise_()

        layer = CountingLayer()
        snapshot = MapMarkerSnapshot(
            map_id=1,
            map_open=True,
            world_size=600,
            viewport=MapViewport(20, 30, 600, 600),
            markers=(WorldMapMarker("auto:1", "moai", 10, -20),),
        )
        try:
            layer.set_snapshot(snapshot, scale=1.0)
            first_visibility_calls = layer.visibility_calls
            first_raise_calls = layer.raise_calls

            layer.set_snapshot(snapshot, scale=1.0)

            self.assertEqual(layer.visibility_calls, first_visibility_calls)
            self.assertEqual(layer.raise_calls, first_raise_calls)
        finally:
            layer.close()

    def test_sync_geometry_repositions_save_button_in_edit_mode(self) -> None:
        screen_rect = QApplication.primaryScreen().availableGeometry()
        target_rect = QRect(
            screen_rect.left() + 20,
            screen_rect.top() + 20,
            max(320, min(800, screen_rect.width() - 40)),
            max(240, min(600, screen_rect.height() - 40)),
        )

        def current_geometry() -> QRect:
            return target_rect

        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=current_geometry,
            _toggle_igo_edit_mode=lambda: None,
        )

        with patch.object(config, "IN_GAME_OVERLAY", _test_overlay_config()):
            window = InGameOverlayWindow(parent_mixin)
            try:
                self.assertIs(window._position_save_timer.parent(), window)
                window.toggle_edit_mode(True)
                self.assertIsNotNone(window.save_btn)

                window.sync_geometry_to_target()

                self.assertEqual(window.geometry(), target_rect)
                visible_rect = window._visible_local_rect()
                self.assertEqual(window.save_btn.width(), 280)
                self.assertEqual(window.save_btn.height(), 40)
                self.assertEqual(
                    window.save_btn.x(),
                    visible_rect.left() + (visible_rect.width() - window.save_btn.width()) // 2,
                )
                self.assertEqual(
                    window.save_btn.y(),
                    visible_rect.bottom() + 1 - window.save_btn.height() - 60,
                )
            finally:
                window.close()

    def test_save_button_stays_inside_visible_screen_area_when_overlay_bottom_is_offscreen(self) -> None:
        screen_rect = QApplication.primaryScreen().availableGeometry()
        target_rect = QRect(
            screen_rect.left() + 20,
            screen_rect.bottom() - 80,
            max(320, min(800, screen_rect.width() - 40)),
            600,
        )

        def current_geometry() -> QRect:
            return target_rect

        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=current_geometry,
            _toggle_igo_edit_mode=lambda: None,
        )

        with patch.object(config, "IN_GAME_OVERLAY", _test_overlay_config()):
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.toggle_edit_mode(True)
                self.assertIsNotNone(window.save_btn)
                window.sync_geometry_to_target()

                visible_rect = window._visible_local_rect()
                self.assertLessEqual(window.save_btn.y() + window.save_btn.height(), visible_rect.bottom() + 1)
                self.assertGreaterEqual(window.save_btn.y(), visible_rect.top())
            finally:
                window.close()

    def test_sync_geometry_keeps_widgets_inside_smaller_game_window(self) -> None:
        target_rect = QRect(0, 0, 320, 240)
        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=lambda: target_rect,
            _toggle_igo_edit_mode=lambda: None,
        )
        overlay_config = _test_overlay_config()
        overlay_config["widgets"]["stats"]["x"] = 1500
        overlay_config["widgets"]["stats"]["y"] = 900

        with patch.object(config, "IN_GAME_OVERLAY", overlay_config), patch.object(
            config, "save_config"
        ) as save_config:
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.sync_geometry_to_target()
                stats = window.widgets["stats"]

                self.assertGreaterEqual(stats.x(), 0)
                self.assertGreaterEqual(stats.y(), 0)
                self.assertLessEqual(stats.x() + stats.width(), window.width())
                self.assertLessEqual(stats.y() + stats.height(), window.height())
                # The clamp is a display adjustment, not an edit. It used to be
                # written back, and that is what made a widget near an edge
                # creep permanently upward every time it grew a row -- which the
                # Luck widget now does whenever the expected frame is switched
                # on or its layout changes. The configured position is the
                # user's intent and only a drag changes it.
                self.assertEqual(1500, overlay_config["widgets"]["stats"]["x"])
                self.assertEqual(900, overlay_config["widgets"]["stats"]["y"])
                save_config.assert_not_called()
            finally:
                window.close()

    def test_a_clamped_widget_returns_to_its_configured_place(self) -> None:
        """The half of the fix the clamp alone cannot give.

        Growing a widget pushes it off the bottom edge; shrinking it back has to
        put it where the user left it, not where the clamp last parked it.
        """
        target_rect = QRect(0, 0, 320, 240)
        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=lambda: target_rect,
            _toggle_igo_edit_mode=lambda: None,
        )
        overlay_config = _test_overlay_config()
        overlay_config["widgets"]["stats"]["x"] = 200
        overlay_config["widgets"]["stats"]["y"] = 180

        with patch.object(config, "IN_GAME_OVERLAY", overlay_config), patch.object(
            config, "save_config"
        ):
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.sync_geometry_to_target()
                stats = window.widgets["stats"]
                stats.set_text("<span>" + "<br>".join(["tall"] * 12) + "</span>")
                self.assertLess(stats.y(), 180, "a grown widget should be clamped up")

                stats.set_text("<span>short</span>")

                self.assertEqual(QPoint(200, 180), stats.pos())
            finally:
                window.close()

    def test_a_widget_that_grows_in_layout_mode_stays_on_screen(self) -> None:
        """Layout mode used to be a hole in the right and bottom clamps.

        Those two are `parent.width() - self.width()`, so they hold only for the
        size at the last clamp; the left and top ones are `max(0, ...)` and hold
        always. `reclamp_to_parent` skipped the whole of edit mode, so a widget
        parked against the right edge grew with its live text and slid straight
        past it -- sticking to two edges and escaping the other two, which is
        exactly how it looked. Only the drag itself skips now.
        """
        target_rect = QRect(0, 0, 320, 240)
        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=lambda: target_rect,
            _toggle_igo_edit_mode=lambda: None,
        )
        overlay_config = _test_overlay_config()

        with patch.object(config, "IN_GAME_OVERLAY", overlay_config), patch.object(
            config, "save_config"
        ):
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.sync_geometry_to_target()
                window.toggle_edit_mode(True)
                scanner = window.widgets["scanner"]

                scanner.set_text("<span>ON</span>")
                # Park it hard against the right and bottom edges, the way a
                # drag-release does, and record that as the user's intent.
                parked = scanner._clamp_to_parent(QPoint(10_000, 10_000))
                scanner.move(parked)
                window.on_widget_moved("scanner", parked.x(), parked.y())

                # The live text grows on the next tick.
                scanner.set_text("<span>SCANNER ON &nbsp; REC &nbsp; 12345 kills</span>")

                # Asserted as "the clamp was applied at the new size" rather
                # than "the right edge is inside the parent". Font metrics differ
                # by platform: run after a test that sets QT_QPA_PLATFORM, the
                # grown widget is wider than the whole 320px window and no
                # placement can fit it. What must hold either way is that the
                # position was re-derived from the size it has *now*.
                self.assertEqual(
                    max(0, target_rect.width() - scanner.width()),
                    scanner.x(),
                    "the right clamp still used the size from before the text grew",
                )
                self.assertEqual(
                    max(0, target_rect.height() - scanner.height()),
                    scanner.y(),
                    "the bottom clamp still used the size from before the text grew",
                )
            finally:
                window.close()

    def test_drag_position_is_limited_to_overlay_bounds(self) -> None:
        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=lambda: QRect(0, 0, 320, 240),
            _toggle_igo_edit_mode=lambda: None,
        )

        with patch.object(config, "IN_GAME_OVERLAY", _test_overlay_config()):
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.sync_geometry_to_target()
                widget = window.widgets["stats"]

                self.assertEqual(widget._clamp_to_parent(QPoint(-50, -20)), QPoint(0, 0))
                self.assertEqual(
                    widget._clamp_to_parent(QPoint(1000, 900)),
                    QPoint(
                        max(0, window.width() - widget.width()),
                        max(0, window.height() - widget.height()),
                    ),
                )
            finally:
                window.close()


class LuckRarityExpectedFrameTests(unittest.TestCase):
    """The expected block against the percentage row, in all four toggle states.

    `show_bar` and `show_expected` are independent and every combination is
    valid, which is why the block is a sibling of the percentage row in the
    shared `QVBoxLayout` rather than positioned against the bar: the bar can be
    switched off, and an anchor that can disappear is not an anchor.
    """

    ACTUAL = {"LEGENDARY": 116, "RARE": 78, "UNCOMMON": 38, "COMMON": 45}
    EXPECTED = {"LEGENDARY": 118.4, "RARE": 78.0, "UNCOMMON": 36.2, "COMMON": 45.0}

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        # Every widget is parented to this host and torn down with it. A
        # parentless `LuckRarityOverlayWidget` becomes a real top-level window,
        # which Qt paints on the next event pass -- after the test has dropped
        # its reference, so the bar's `paintEvent` runs against a destroyed C++
        # object and takes the whole process down with an access violation.
        self._host = QWidget()
        self._host.resize(1200, 800)
        self.addCleanup(self._host.deleteLater)

    def _widget(
        self,
        *,
        show_bar: bool,
        show_expected: bool,
        layout: str = "column",
        status_message: str | None = None,
    ):
        from core.luck_rarity import calculate_luck_rarity_probabilities
        from gui_in_game_overlay_window import LuckRarityOverlayWidget

        overlay_config = _test_overlay_config()
        overlay_config["widgets"]["luck_rarity"].update(
            show_bar=show_bar, show_expected=show_expected, expected_layout=layout
        )
        with patch.object(config, "IN_GAME_OVERLAY", overlay_config):
            widget = LuckRarityOverlayWidget("luck_rarity", self._host)
            widget.set_probabilities(
                calculate_luck_rarity_probabilities(3.0), show_bar=show_bar
            )
            widget.set_expected(
                self.ACTUAL,
                self.EXPECTED,
                show_expected=show_expected,
                layout=layout,
                status_message=status_message,
            )
            widget.adjustSize()
            return widget

    def test_every_toggle_combination_keeps_the_percentage_rows_width(self) -> None:
        widths = {}
        for show_bar in (True, False):
            for show_expected in (True, False):
                widget = self._widget(show_bar=show_bar, show_expected=show_expected)
                widths[(show_bar, show_expected)] = widget.width()
                self.assertNotEqual("", widget.label.text(), "the percentage row is always drawn")
                self.assertEqual(
                    show_expected,
                    widget.expected_label.isVisibleTo(widget),
                    "the block must follow its own toggle, not the bar's",
                )
        self.assertEqual(
            1,
            len(set(widths.values())),
            f"the block must not change the widget's width: {widths}",
        )

    def test_the_frame_adds_height_and_removing_it_gives_it_back(self) -> None:
        for show_bar in (True, False):
            with self.subTest(show_bar=show_bar):
                without = self._widget(show_bar=show_bar, show_expected=False)
                with_frame = self._widget(show_bar=show_bar, show_expected=True)
                self.assertGreater(with_frame.height(), without.height())

    def test_row_is_shorter_than_column(self) -> None:
        column = self._widget(show_bar=True, show_expected=True, layout="column")
        row = self._widget(show_bar=True, show_expected=True, layout="row")
        self.assertLess(row.height(), column.height())

    def test_an_unmeasurable_run_hides_the_block_and_keeps_the_row(self) -> None:
        widget = self._widget(show_bar=True, show_expected=True)
        baseline = widget.width()
        widget.set_expected(None, None, show_expected=False)
        widget.adjustSize()

        # `isVisibleTo`, not `isVisible`: the host is never shown, so
        # `isVisible()` is false for every child regardless of the toggle and
        # asserting on it proves nothing. This assertion was vacuous until the
        # end-to-end render check showed a block that was on reporting false.
        self.assertFalse(widget.expected_label.isVisibleTo(widget))
        self.assertNotEqual("", widget.label.text())
        self.assertEqual(baseline, widget.width())

    def test_an_unmeasurable_run_with_a_status_message_shows_it_instead_of_hiding(
        self,
    ) -> None:
        """An empty area is indistinguishable from an unchecked toggle or a
        widget dragged off-screen. A status message is the third, distinct
        state: the toggle is on, but the run is not measurable (yet, or ever).
        """
        widget = self._widget(show_bar=True, show_expected=True)
        widget.set_expected(
            None,
            None,
            show_expected=False,
            status_message="Expected counts — waiting for first item",
        )
        widget.adjustSize()

        self.assertTrue(widget.expected_label.isVisibleTo(widget))
        self.assertIn("waiting for first item", widget.expected_label.text())

    def test_a_status_message_does_not_stretch_the_widget_or_the_bar(self) -> None:
        """The bar is `Expanding`, so whatever widens the column widens the bar.

        A status message is a run of unbreakable words, and before the block was
        capped it set the column's width all by itself -- the bar underneath the
        percentages stretched to about three times the row it belongs to. The
        message is the widest thing the block ever holds, so it is the case
        worth pinning.
        """
        widget = self._widget(show_bar=True, show_expected=False)
        baseline = widget.width()

        # Deliberately far longer than any message shipped. Two separate things
        # keep the column narrow -- word wrap, and the explicit cap -- and word
        # wrap alone happens to be enough for a message the length of the real
        # ones, so pinning the shipped wording here would prove only that the
        # string is short. Past roughly the percentage row's own width Qt's
        # wrapping hint starts widening again and only the cap holds, which is
        # the length this asserts at.
        widget.set_expected(
            None,
            None,
            show_expected=False,
            status_message=(
                "Expected counts unavailable because the app missed the run start. " * 4
            ).strip(),
        )
        widget.adjustSize()

        self.assertTrue(widget.expected_label.isVisibleTo(widget))
        self.assertEqual(
            baseline,
            widget.width(),
            "the percentage row alone decides the width, message or not",
        )
        self.assertLessEqual(
            widget.expected_label.width(),
            widget.label.width(),
            "the block fits itself to the row rather than the other way round",
        )



if __name__ == "__main__":
    unittest.main()
