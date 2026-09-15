from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import src
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from app import config
from core.map_markers import (
    MAP_MARKER_ACTION_BY_ID,
    MapMarkerSnapshot,
    MapViewport,
    MerchantOffer,
    MerchantStockCapture,
    MinimapProjection,
    WorldMapMarker,
    build_marker_palette,
    map_marker_screen_geometry,
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
            "weapon_tracker": {
                "enabled": True,
                "x": 0,
                "y": 0,
                "scale": 1.0,
                "layout": "compact",
                "selected_stats": ["damage", "projectile_count", "size"],
            },
        }
    }


class InGameOverlayWindowTests(unittest.TestCase):
    def test_price_coin_column_is_built_in_and_cached(self):
        from core.shady_prices import format_shady_price
        layer = MapMarkerLayer()
        layer.resize(600, 400)
        stock = MerchantStockCapture(1, 1, '1', 1, 0, 0, (
            MerchantOffer(1, 'Beer', 'Beer', 'UNCOMMON', 999),
            MerchantOffer(2, 'Lamp', 'Overpowered Lamp', 'LEGENDARY', 1500),
        ))
        snapshot = MapMarkerSnapshot(map_id=1, map_open=True, world_size=600,
            viewport=MapViewport(0, 0, 600, 400),
            markers=(WorldMapMarker('1', 'shady_guy_blue', 0, 0, object_ptr=1),),
            merchant_stocks=(stock,))
        image = QImage(1200, 800, QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(2)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            layer.set_snapshot(snapshot, scale=1, merchant_stock_display='always')
            with patch('gui_in_game_overlay_window.format_shady_price', wraps=format_shady_price) as formatter:
                layer._paint_snapshot(painter, snapshot, snapshot.viewport)
                self.assertEqual(formatter.call_count, 2)
                layer._paint_snapshot(painter, snapshot, snapshot.viewport)
                self.assertEqual(formatter.call_count, 2)
        finally:
            painter.end()
            layer.close()

    def test_stock_card_background_is_translucent_and_text_stays_opaque(self):
        from ui.stock_card_layout import group_stock_entries, layout_stock_cards
        layer = MapMarkerLayer()
        stock = MerchantStockCapture(1, 1, "1", 1, 0, 0,
                                     (MerchantOffer(1, "Beer", "Beer", "UNCOMMON"),))
        entries = tuple((
            WorldMapMarker(str(i), "shady_guy_blue", 0, 0, object_ptr=i + 1),
            replace(stock, merchant_object_ptr=i + 1, marker_id=str(i)),
            (300.0 + i * 20, 150.0, 48.0),
        ) for i in range(2))
        try:
            for grouped in (False, True):
                plan = layout_stock_cards(
                    group_stock_entries(entries if grouped else entries[:1]),
                    MapViewport(0, 0, 600, 400), 1, "always", None,
                )[0]
                image = QImage(600, 400, QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                try:
                    if grouped:
                        layer._paint_stock_group_card(painter, plan.bounds, plan, None)
                    else:
                        layer._paint_stock_card(painter, plan.bounds, stock)
                finally:
                    painter.end()
                self.assertAlmostEqual(
                    image.pixelColor(int(plan.bounds.center().x()), int(plan.bounds.bottom() - 4)).alpha(),
                    179, delta=1,
                )
                self.assertTrue(any(
                    image.pixelColor(x, y).alpha() == 255
                    for x in range(int(plan.bounds.left() + 12), int(plan.bounds.right() - 12))
                    for y in range(int(plan.bounds.top() + 25), int(plan.bounds.bottom() - 6))
                ))
        finally:
            layer.close()

    def test_microwave_badges_render_on_maps_and_minimap(self):
        layer = MapMarkerLayer()
        layer.resize(400, 400)
        viewport = MapViewport(0, 0, 400, 400)
        snapshot = MapMarkerSnapshot(
            map_id=1, map_open=True, world_size=600, viewport=viewport,
            markers=(WorldMapMarker("1", "microwave_blue", 0, 0, object_ptr=1, uses_remaining=2),),
            minimap_projection=MinimapProjection(
                True, False, viewport, 200, 200, 200, 0, 0, 1, 0, 0, 1, 110, 1,
            ),
        )
        image = QImage(400, 400, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        try:
            for style in ("modern", "classic"):
                for full_map in (True, False):
                    current = replace(snapshot, map_open=full_map)
                    layer.set_snapshot(current, scale=1, style=style)
                    with patch.object(layer, "_microwave_badge_pixmap", wraps=layer._microwave_badge_pixmap) as badge:
                        if full_map:
                            layer._paint_snapshot(painter, current, viewport)
                        else:
                            layer._paint_minimap(painter, current)
                    self.assertEqual(badge.call_count, 1)
                    self.assertEqual(badge.call_args.args[0], 2)
            with patch.object(layer, "_microwave_badge_pixmap") as badge:
                layer._paint_microwave_uses_badge(painter, 100, 100, 36, None)
                layer._paint_microwave_uses_badge(painter, 100, 100, 36, -1)
                badge.assert_not_called()
        finally:
            painter.end()
            layer.close()

    def test_microwave_badge_cache_supports_zero_and_display_scaling(self):
        layer = MapMarkerLayer()
        try:
            for dpr in (1.0, 1.25, 1.5, 2.0):
                with patch.object(layer, "devicePixelRatioF", return_value=dpr):
                    for uses in (0, 1, 2, 3):
                        badge = layer._microwave_badge_pixmap(uses, 24)
                        self.assertIs(badge, layer._microwave_badge_pixmap(uses, 24))
                        self.assertEqual(badge.devicePixelRatioF(), dpr)
                        self.assertEqual(badge.width(), round(24 * dpr))
                        self.assertEqual(badge.toImage().pixelColor(0, 0).alpha(), 0)
                        pixels = badge.toImage()
                        self.assertTrue(any(
                            pixels.pixelColor(x, y).red() > 200
                            for x in range(int(6*dpr), int(18*dpr))
                            for y in range(int(5*dpr), int(19*dpr))
                        ))
        finally:
            layer.close()

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_partial_updates_match_full_redraw_on_motion_hide_and_map_switch(self):
        projection = MinimapProjection(
            True, False, MapViewport(300, 30, 180, 180), 390, 120, 90,
            0, 0, 1, 0, 0, 1, 110, 1,
        )
        snap = MapMarkerSnapshot(map_id=1, world_size=600,
            markers=(WorldMapMarker("1", "shady_guy_blue", 0, 0, object_ptr=1),),
            minimap_projection=projection)
        moved = replace(snap, minimap_projection=replace(projection,
            content_rect=MapViewport(250, 50, 200, 200), center_x=350, center_y=150, radius=100,
            camera_world_x=25))
        full = replace(snap, map_open=True, viewport=MapViewport(50, 20, 350, 350))
        sequence = (snap, moved, replace(moved, minimap_projection=None), moved,
                    replace(moved, markers=()), full, snap, MapMarkerSnapshot())
        for dpr in (1.0, 1.25, 1.5):
            with self.subTest(dpr=dpr):
                layer = MapMarkerLayer()
                layer.setAttribute(Qt.WA_DontShowOnScreen, True)
                layer.resize(600, 400)
                images = [QImage(round(600*dpr), round(400*dpr), QImage.Format_ARGB32_Premultiplied) for _ in range(2)]
                for image in images:
                    image.setDevicePixelRatio(dpr)
                    image.fill(Qt.transparent)
                try:
                    for index, snapshot in enumerate(sequence):
                        with patch.object(layer, "update") as update:
                            layer.set_snapshot(snapshot, scale=1.0, style="classic" if index % 2 else "modern")
                        self.assertTrue(update.called)
                        args = update.call_args.args
                        dirty = args[0] if args else layer.rect()
                        if index == 1:
                            self.assertTrue(dirty.contains(QRect(300, 30, 180, 180)))
                            self.assertTrue(dirty.contains(QRect(250, 50, 200, 200)))
                            self.assertLess(dirty.width()*dirty.height(), 600*400)
                        if index in (5, 6):
                            self.assertEqual(args, ())
                        for image, rect in zip(images, (layer.rect(), dirty)):
                            painter = QPainter(image)
                            painter.setClipRect(rect)
                            painter.setCompositionMode(QPainter.CompositionMode_Source)
                            painter.fillRect(rect, Qt.transparent)
                            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                            if snapshot.map_open:
                                layer._paint_snapshot(painter, snapshot, snapshot.viewport)
                            else:
                                layer._paint_minimap(painter, snapshot)
                            painter.end()
                        self.assertEqual(images[0], images[1])
                finally:
                    layer.close()

    def test_stock_cursor_repaints_only_when_hover_selection_changes(self):
        layer = MapMarkerLayer()
        layer.setAttribute(Qt.WA_DontShowOnScreen, True)
        layer.resize(600, 400)
        viewport = MapViewport(0, 0, 600, 400)
        snapshot = MapMarkerSnapshot(map_id=1, map_open=True, world_size=600, viewport=viewport,
            markers=(WorldMapMarker("1", "shady_guy_blue", 0, 0, object_ptr=1),),
            merchant_stocks=(MerchantStockCapture(1, 1, "1", 1, 0, 0,
                (MerchantOffer(1, "Beer", "Beer", "UNCOMMON"),)),))
        image = QImage(600, 400, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        def paint():
            painter = QPainter(image)
            layer._paint_snapshot(painter, snapshot, viewport)
            painter.end()
        try:
            layer.set_snapshot(snapshot, scale=1.0, cursor_position=(5, 5))
            paint()
            with patch.object(layer, "update") as update:
                layer.set_snapshot(snapshot, scale=1.0, cursor_position=(6, 6))
                update.assert_not_called()
                layer.set_snapshot(snapshot, scale=1.0, cursor_position=(300, 200))
                update.assert_called_once_with()
            paint()
            self.assertEqual(layer._stock_hovered_marker, "1")
            with patch.object(layer, "update") as update:
                layer.set_snapshot(snapshot, scale=1.0, cursor_position=(301, 200))
                center = layer._stock_plans[0].bounds.center()
                layer.set_snapshot(snapshot, scale=1.0, cursor_position=(center.x(), center.y()))
                update.assert_not_called()
                layer.set_snapshot(snapshot, scale=1.0, cursor_position=(5, 5))
                update.assert_called_once_with()
        finally:
            layer.close()

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

    def test_map_marker_layer_appears_for_visible_minimap_and_clips_circle(self) -> None:
        layer = MapMarkerLayer()
        projection = MinimapProjection(
            visible=True,
            jammed=False,
            content_rect=MapViewport(20.0, 20.0, 160.0, 160.0),
            center_x=100.0,
            center_y=100.0,
            radius=80.0,
            camera_world_x=0.0,
            camera_world_z=0.0,
            camera_right_x=1.0,
            camera_right_z=0.0,
            camera_up_x=0.0,
            camera_up_z=1.0,
            orthographic_size=80.0,
            aspect=1.0,
        )
        snapshot = MapMarkerSnapshot(
            map_id=1,
            markers=(WorldMapMarker("auto:1", "moai", 0.0, 0.0),),
            minimap_projection=projection,
        )
        try:
            layer.set_snapshot(snapshot, scale=1.0, minimap_scale=1.0)
            self.assertFalse(layer.isHidden())

            # Timer delivery of the same sample must not paint again merely
            # because the cursor moved after the immediate worker delivery.
            with patch.object(layer, "update") as update:
                layer.set_snapshot(snapshot, scale=1.0, cursor_position=(80, 90))
                update.assert_not_called()

            image = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            try:
                layer._paint_minimap(painter, snapshot)
            finally:
                if painter.isActive():
                    painter.end()
            self.assertGreater(image.pixelColor(100, 100).alpha(), 0)
            self.assertEqual(image.pixelColor(19, 19).alpha(), 0)

            covered = replace(
                snapshot,
                map_open=True,
                viewport=MapViewport(20.0, 20.0, 160.0, 160.0),
            )
            covered_image = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
            covered_image.fill(Qt.transparent)
            covered_painter = QPainter(covered_image)
            try:
                layer._paint_minimap(covered_painter, covered)
            finally:
                if covered_painter.isActive():
                    covered_painter.end()
            self.assertEqual(covered_image.pixelColor(100, 100).alpha(), 0)

            layer.set_snapshot(
                MapMarkerSnapshot(
                    markers=snapshot.markers,
                    minimap_projection=MinimapProjection(
                        True,
                        True,
                        projection.content_rect,
                        projection.center_x,
                        projection.center_y,
                        projection.radius,
                        projection.camera_world_x,
                        projection.camera_world_z,
                        projection.camera_right_x,
                        projection.camera_right_z,
                        projection.camera_up_x,
                        projection.camera_up_z,
                        projection.orthographic_size,
                        projection.aspect,
                    ),
                ),
                scale=1.0,
            )
            self.assertTrue(layer.isHidden())
        finally:
            layer.close()

    def test_stock_memory_adds_badge_and_full_map_card(self) -> None:
        layer = MapMarkerLayer()
        viewport = MapViewport(0.0, 0.0, 400.0, 400.0)
        snapshot = MapMarkerSnapshot(
            map_id=1,
            map_open=True,
            world_size=600.0,
            viewport=viewport,
            markers=(
                WorldMapMarker(
                    "auto:5150", "shady_guy_blue", 0.0, 0.0,
                    object_ptr=0x5150,
                ),
            ),
            merchant_stocks=(
                MerchantStockCapture(
                    1,
                    0x5150,
                    "auto:5150",
                    1,
                    0.0,
                    0.0,
                    (MerchantOffer(1, "Beer", "Beer", "UNCOMMON"),),
                ),
            ),
        )
        layer.set_snapshot(snapshot, scale=1.0)
        image = QImage(400, 400, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            with patch.object(
                layer,
                "_premium_pixmap",
                wraps=layer._premium_pixmap,
            ) as premium_pixmap, patch.object(
                layer,
                "_stock_badge_pixmap",
                wraps=layer._stock_badge_pixmap,
            ) as stock_badge:
                layer._paint_snapshot(painter, snapshot, viewport)
        finally:
            if painter.isActive():
                painter.end()
            layer.close()

        # The card retains its Premium heading; the marker uses a distinct
        # list-in-circle indicator for remembered stock.
        card_center = layer._stock_plans[0].bounds.center()
        self.assertGreater(image.pixelColor(int(card_center.x()), int(card_center.y())).alpha(), 0)
        stock_badge.assert_called_once_with(26)
        self.assertEqual(premium_pixmap.call_count, 1)
        self.assertIn(14, [call.args[0] for call in premium_pixmap.call_args_list])

    def test_stock_groups_cache_layout_and_text_until_selection_changes(self) -> None:
        from ui.stock_card_layout import group_stock_entries, layout_stock_cards

        layer = MapMarkerLayer()
        entries = tuple((
            WorldMapMarker(str(i), "shady_guy_blue", 0, 0, object_ptr=i + 1),
            MerchantStockCapture(1, i + 1, str(i), 1, 0, 0,
                                 (MerchantOffer(1, "Beer", "Beer", "UNCOMMON"),)),
            (300.0 + i * 30, 300.0, 48.0),
        ) for i in range(3))
        viewport = MapViewport(0, 0, 900, 700)
        image = QImage(900, 700, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            with patch("gui_in_game_overlay_window.group_stock_entries", wraps=group_stock_entries) as grouping, \
                 patch("gui_in_game_overlay_window.layout_stock_cards", wraps=layout_stock_cards) as layout, \
                 patch.object(layer, "_paint_stock_group_card", wraps=layer._paint_stock_group_card) as raster:
                layer._cursor_position = (300, 300)
                layer._paint_stock_cards(painter, viewport, entries)
                layer._cursor_position = (301, 300)
                layer._paint_stock_cards(painter, viewport, entries)
                self.assertEqual(grouping.call_count, 1)
                self.assertEqual(layout.call_count, 1)
                self.assertEqual(raster.call_count, 1)
                self.assertEqual(len(layer._stock_plans), 1)
                self.assertEqual(len(layer._stock_plans[0].entries), 3)

                layer._cursor_position = (330, 300)
                layer._paint_stock_cards(painter, viewport, entries)
                self.assertEqual(grouping.call_count, 1)
                self.assertEqual(layout.call_count, 2)
                self.assertEqual(raster.call_count, 2)
                self.assertEqual(len(layer._stock_card_pixmaps), 1)

                layer._scale = 1.5
                layer._paint_stock_cards(painter, viewport, entries)
                self.assertEqual(layout.call_count, 3)
                self.assertEqual(raster.call_count, 3)
                changed = (entries[0], (entries[1][0], replace(entries[1][1], items=()), entries[1][2]), entries[2])
                layer._paint_stock_cards(painter, viewport, changed)
                self.assertEqual(grouping.call_count, 2)
                self.assertEqual(raster.call_count, 4)

                layer._paint_stock_cards(painter, viewport, ())
                self.assertEqual(layer._stock_plans, ())
                self.assertEqual(layer._stock_card_pixmaps, {})
        finally:
            painter.end()
            layer.close()

    def test_two_green_merchants_render_their_own_stock_after_refresh(self) -> None:
        from app.map_marker_tracker import MapMarkerTracker
        from infra.memory.map_marker_client import MapMemoryFrame

        viewport = MapViewport(0, 0, 900, 700)
        beer = MerchantOffer(1, "Beer", "Beer", "UNCOMMON")
        key = MerchantOffer(0, "Key", "Key", "COMMON")
        first = MerchantStockCapture(1, 0x5150, "first", 0, 0, 0, (beer,))
        second = MerchantStockCapture(1, 0x6160, "second", 0, 20, 0, (beer,))
        captures = iter((first, second, replace(second, items=(key,))))
        client = SimpleNamespace(
            poll=lambda **_kwargs: MapMemoryFrame(1, True, 600, viewport, None, merchant_stock_capture=next(captures)),
            activity_is_active=lambda *_args, **_kwargs: True,
            close=lambda: None,
        )
        tracker = MapMarkerTracker("game", client_factory=lambda _name: client, automatic_scan_interval=0.0)
        layer = MapMarkerLayer()
        image = QImage(900, 700, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        text = []
        original_draw_text = QPainter.drawText

        def record_text(target, *args):
            text.append(args[-1])
            return original_draw_text(target, *args)

        try:
            for _ in range(2):
                snapshot = tracker.tick(client_height=700, merchant_memory_enabled=True)
            # Warm the grouped card cache with the previous incorrect values.
            layer._paint_snapshot(painter, snapshot, viewport)
            corrected = tracker.tick(client_height=700, merchant_memory_enabled=True)
            with patch.object(QPainter, "drawText", new=record_text):
                layer._paint_snapshot(painter, corrected, viewport)
            self.assertEqual(text.count("• Beer"), 1)
            self.assertEqual(text.count("• Key"), 1)
            self.assertEqual(len(layer._stock_plans), 1)
            self.assertEqual([e[1].items for e in layer._stock_plans[0].entries], [(beer,), (key,)])
        finally:
            painter.end()
            layer.close()
            tracker.close()

    def test_classic_stock_thumbnail_includes_rarity_circle_and_outline(self) -> None:
        layer = MapMarkerLayer()
        layer._style = "classic"
        try:
            for rarity in ("white", "blue", "purple", "gold"):
                with self.subTest(rarity=rarity):
                    action = MAP_MARKER_ACTION_BY_ID[f"shady_guy_{rarity}"]
                    image = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
                    image.fill(Qt.transparent)
                    painter = QPainter(image)
                    original_transform = painter.transform()
                    try:
                        layer._paint_stock_merchant_icon(painter, action, 5, 5)
                        self.assertEqual(painter.transform(), original_transform)
                    finally:
                        painter.end()
                    # Left interior is colored even outside the black glyph;
                    # the circle's upper edge has the light classic outline.
                    fill = image.pixelColor(9, 16)
                    self.assertGreater(fill.alpha(), 200)
                    self.assertGreater(max(fill.red(), fill.green(), fill.blue()), 180)
                    outline = image.pixelColor(16, 5)
                    self.assertGreater(min(outline.red(), outline.green(), outline.blue()), 180)
                    self.assertEqual(image.pixelColor(1, 1).alpha(), 0)
        finally:
            layer.close()

    def test_stock_memory_crystal_is_transparent_line_art_not_a_filled_square(
        self,
    ) -> None:
        layer = MapMarkerLayer()
        try:
            image = layer._premium_pixmap(24).toImage()
            opaque_pixels = sum(
                image.pixelColor(x, y).alpha() > 0
                for y in range(image.height())
                for x in range(image.width())
            )

            self.assertFalse(image.isNull())
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            self.assertGreater(opaque_pixels, 20)
            self.assertLess(opaque_pixels, image.width() * image.height() // 2)
        finally:
            layer.close()

    def test_compact_stock_card_expands_on_hover_without_flickering(self) -> None:
        layer = MapMarkerLayer()
        entries = tuple((
            WorldMapMarker(str(i), "shady_guy_blue", 0, 0, object_ptr=i + 1),
            MerchantStockCapture(1, i + 1, str(i), 1, 0, 0, tuple(
                MerchantOffer(j, "Beer", "Beer", "UNCOMMON") for j in range(3)
            )),
            (250.0 + i * 20, 80.0, 48.0),
        ) for i in range(3))
        viewport = MapViewport(0, 0, 900, 180)
        image = QImage(900, 180, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            layer._paint_stock_cards(painter, viewport, entries)
            self.assertTrue(layer._stock_plans[0].compact)
            center = layer._stock_plans[0].bounds.center()
            layer._cursor_position = (center.x(), center.y())
            for _ in range(3):
                layer._paint_stock_cards(painter, viewport, entries)
                self.assertFalse(layer._stock_plans[0].compact)
                self.assertEqual(layer._stock_plans[0].entries, (entries[0],))
            layer._cursor_position = (0, 0)
            layer._paint_stock_cards(painter, viewport, entries)
            self.assertTrue(layer._stock_plans[0].compact)
        finally:
            painter.end()
            layer.close()

    def test_map_marker_layer_loads_filled_and_existing_multicolor_icons(
        self,
    ) -> None:
        layer = MapMarkerLayer()
        try:
            for action_id, action in MAP_MARKER_ACTION_BY_ID.items():
                with self.subTest(action=action_id):
                    pixmap = layer._pictogram_pixmap(action, 64)
                    self.assertFalse(pixmap.isNull())
                    classic = layer._pictogram_pixmap(
                        action,
                        64,
                        style="classic",
                    )
                    self.assertFalse(classic.isNull())
                    if action.icon_file:
                        image = pixmap.toImage()
                        self.assertGreater(image.pixelColor(32, 32).alpha(), 0)
                        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)

            shady = layer._pictogram_pixmap(
                MAP_MARKER_ACTION_BY_ID["shady_guy_white"],
                64,
            ).toImage()
            shady_colors = {
                shady.pixelColor(x, y).name().upper()
                for y in range(shady.height())
                for x in range(shady.width())
                if shady.pixelColor(x, y).alpha() >= 240
            }
            self.assertGreater(len(shady_colors), 10)
            self.assertGreater(shady.pixelColor(32, 32).alpha(), 0)

            def opaque_width(action_id: str) -> int:
                image = layer._pictogram_pixmap(
                    MAP_MARKER_ACTION_BY_ID[action_id],
                    256,
                ).toImage()
                columns = {
                    x
                    for y in range(image.height())
                    for x in range(image.width())
                    if image.pixelColor(x, y).alpha() >= 128
                }
                return max(columns) - min(columns) + 1

            self.assertGreaterEqual(opaque_width("boss_curse"), 170)
            self.assertGreaterEqual(opaque_width("moai"), 175)

            for action_id, background_color in (
                ("magnet_shrine", "#0B1D42"),
                ("challenge_shrine", "#431217"),
            ):
                with self.subTest(background=action_id):
                    image = layer._pictogram_pixmap(
                        MAP_MARKER_ACTION_BY_ID[action_id],
                        256,
                    ).toImage()
                    matching_pixels = sum(
                        image.pixelColor(x, y).name().upper()
                        == background_color
                        for y in range(image.height())
                        for x in range(image.width())
                    )
                    self.assertGreater(matching_pixels, 1000)

            egg = layer._pictogram_pixmap(
                MAP_MARKER_ACTION_BY_ID["egg"],
                64,
            ).toImage()
            egg_colors = {
                egg.pixelColor(x, y).name().upper()
                for y in range(egg.height())
                for x in range(egg.width())
                if egg.pixelColor(x, y).alpha() >= 240
            }
            self.assertGreater(len(egg_colors), 2)
            self.assertIn("#FFFBEA", egg_colors)
            self.assertIn("#55C94D", egg_colors)
        finally:
            layer.close()

    def test_classic_style_paints_original_circle_and_dark_pictogram(self) -> None:
        layer = MapMarkerLayer()
        viewport = MapViewport(0, 0, 200, 200)
        snapshot = MapMarkerSnapshot(
            map_id=1,
            map_open=True,
            world_size=600,
            viewport=viewport,
            markers=(
                WorldMapMarker("auto:classic", "shady_guy_white", 0, 0),
            ),
        )
        layer.set_snapshot(snapshot, scale=1.0, style="classic")
        image = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            layer._paint_snapshot(painter, snapshot, viewport)
        finally:
            if painter.isActive():
                painter.end()
            layer.close()

        self.assertEqual(layer._style, "classic")
        circle_fill = image.pixelColor(110, 100)
        self.assertGreater(circle_fill.alpha(), 0)
        self.assertLessEqual(abs(circle_fill.red() - 0x16), 1)
        self.assertLessEqual(abs(circle_fill.green() - 0xF2), 1)
        self.assertLessEqual(abs(circle_fill.blue() - 0x8B), 1)
        dark_symbol = image.pixelColor(100, 100)
        self.assertLess(dark_symbol.red(), 20)
        self.assertLess(dark_symbol.green(), 100)
        white_outline = image.pixelColor(114, 100)
        self.assertGreater(white_outline.red(), 200)
        self.assertGreater(white_outline.green(), 200)
        self.assertGreater(white_outline.blue(), 200)
        self.assertEqual(image.pixelColor(116, 100).alpha(), 0)

    def test_map_marker_layer_paints_filled_pictogram_without_enclosing_plate(
        self,
    ) -> None:
        layer = MapMarkerLayer()
        viewport = MapViewport(0, 0, 200, 200)
        snapshot = MapMarkerSnapshot(
            map_id=1,
            map_open=True,
            world_size=600,
            viewport=viewport,
            markers=(
                WorldMapMarker("auto:1", "shady_guy_white", 0, 0),
            ),
        )
        image = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            layer._paint_snapshot(painter, snapshot, viewport)
        finally:
            if painter.isActive():
                painter.end()
            layer.close()

        geometry = map_marker_screen_geometry(
            0,
            0,
            world_size=600,
            viewport=viewport,
            scale=1.0,
        )
        self.assertIsNotNone(geometry)
        center_x, center_y, icon_size = geometry
        half = icon_size / 2.0 - 1
        for delta_x, delta_y in (
            (-half, -half),
            (half, -half),
            (-half, half),
            (half, half),
        ):
            corner = image.pixelColor(
                int(round(center_x + delta_x)),
                int(round(center_y + delta_y)),
            )
            self.assertEqual(corner.alpha(), 0)

        center = image.pixelColor(int(round(center_x)), int(round(center_y)))
        self.assertGreater(center.alpha(), 0)

        painted_colors = {
            image.pixelColor(x, y).name().upper()
            for y in range(
                int(center_y - icon_size / 2),
                int(center_y + icon_size / 2),
            )
            for x in range(
                int(center_x - icon_size / 2),
                int(center_x + icon_size / 2),
            )
            if image.pixelColor(x, y).alpha() >= 240
        }
        self.assertGreater(len(painted_colors), 10)

    def test_map_marker_at_boundary_is_clipped_without_moving_its_center(
        self,
    ) -> None:
        layer = MapMarkerLayer()
        viewport = MapViewport(20, 30, 100, 100)
        snapshot = MapMarkerSnapshot(
            map_id=1,
            map_open=True,
            world_size=100,
            viewport=viewport,
            markers=(
                WorldMapMarker("auto:edge", "shady_guy_white", -50, 50),
            ),
        )
        image = QImage(160, 160, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        try:
            layer._paint_snapshot(painter, snapshot, viewport)
        finally:
            if painter.isActive():
                painter.end()
            layer.close()

        self.assertGreater(image.pixelColor(20, 30).alpha(), 0)
        self.assertEqual(image.pixelColor(19, 30).alpha(), 0)
        self.assertEqual(image.pixelColor(20, 29).alpha(), 0)
        self.assertEqual(image.pixelColor(49, 49).alpha(), 0)

    def test_weapon_tracker_is_registered_as_one_draggable_widget(self) -> None:
        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=lambda: QRect(0, 0, 640, 480),
            _toggle_igo_edit_mode=lambda: None,
        )
        overlay_config = _test_overlay_config()

        with patch.object(config, "IN_GAME_OVERLAY", overlay_config):
            window = InGameOverlayWindow(parent_mixin)
            try:
                self.assertIn("weapon_tracker", window.widgets)
                self.assertEqual(
                    window.widgets["weapon_tracker"].widget_id,
                    "weapon_tracker",
                )
            finally:
                window.close()

    def test_weapon_tracker_drag_position_persists_through_shared_path(self) -> None:
        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=lambda: QRect(0, 0, 640, 480),
            _toggle_igo_edit_mode=lambda: None,
        )
        overlay_config = _test_overlay_config()

        with patch.object(config, "IN_GAME_OVERLAY", overlay_config):
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.on_widget_moved("weapon_tracker", 123, 234)

                self.assertEqual(
                    overlay_config["widgets"]["weapon_tracker"]["x"], 123
                )
                self.assertEqual(
                    overlay_config["widgets"]["weapon_tracker"]["y"], 234
                )
            finally:
                window.close()

    def test_weapon_tracker_reclamps_when_rows_or_layout_change_size(self) -> None:
        # Leave enough room for the compact row at the configured position on
        # every supported Windows DPI/font setup, while the deliberately large
        # table below still overflows in both directions.
        target_rect = QRect(0, 0, 400, 320)
        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=lambda: target_rect,
            _toggle_igo_edit_mode=lambda: None,
        )
        overlay_config = _test_overlay_config()
        overlay_config["widgets"]["weapon_tracker"]["x"] = 120
        overlay_config["widgets"]["weapon_tracker"]["y"] = 160

        with patch.object(config, "IN_GAME_OVERLAY", overlay_config):
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.sync_geometry_to_target()
                widget = window.widgets["weapon_tracker"]
                widget.set_text(
                    "<table>"
                    + "".join(
                        f"<tr><td>Weapon {index}</td><td>DMG 100 · PROJ 2 · SIZE ×1.4</td></tr>"
                        for index in range(8)
                    )
                    + "</table>"
                )

                self.assertEqual(
                    widget.x(), max(0, target_rect.width() - widget.width())
                )
                self.assertEqual(
                    widget.y(), max(0, target_rect.height() - widget.height())
                )

                widget.set_text("<span>Katana DMG 100</span>")
                self.assertEqual(widget.pos(), QPoint(120, 160))
            finally:
                window.close()

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
