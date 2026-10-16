"""Pixel-level regressions for moving minimap icons and circular edge clipping."""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

import src
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.map_markers import (
    MapMarkerSnapshot,
    MapViewport,
    MerchantStockCapture,
    MinimapProjection,
    WorldMapMarker,
    minimap_marker_screen_geometry,
    project_world_to_minimap,
)
from gui_in_game_overlay_window import MapMarkerLayer


def _projection() -> MinimapProjection:
    # One world unit equals one logical pixel, independent of device scaling.
    return MinimapProjection(
        True, False, MapViewport(40, 40, 160, 160), 120, 120, 80,
        0, 0, 1, 0, 0, 1, 80, 1,
    )


class MinimapMarkerGeometryTests(unittest.TestCase):
    def test_partial_icons_keep_their_exact_centres_outside_the_circle(self):
        projection = _projection()
        for scale in (0.5, 1.0, 2.0):
            for x, z in ((81.25, 0), (-81.25, 0), (0, 81.25), (0, -81.25), (65, 65)):
                with self.subTest(scale=scale, point=(x, z)):
                    # Point-only callers retain their original visibility contract.
                    self.assertIsNone(project_world_to_minimap(x, z, projection=projection))
                    geometry = minimap_marker_screen_geometry(x, z, projection=projection, scale=scale)
                    self.assertIsNotNone(geometry)
                    self.assertAlmostEqual(geometry[0], 120 + x)
                    self.assertAlmostEqual(geometry[1], 120 - z)
                    self.assertEqual(geometry[2], 36 * scale)

    def test_far_and_invalid_markers_are_still_rejected(self):
        projection = _projection()
        for scale in (0.5, 1.0, 2.0):
            for x, z in ((200, 0), (-200, 0), (0, 200), (200, 200), (float('nan'), 0), (0, float('inf'))):
                with self.subTest(scale=scale, point=(x, z)):
                    self.assertIsNone(minimap_marker_screen_geometry(x, z, projection=projection, scale=scale))
        for invalid in (
            replace(projection, visible=False), replace(projection, jammed=True),
            replace(projection, radius=0), replace(projection, orthographic_size=0),
        ):
            self.assertIsNone(minimap_marker_screen_geometry(0, 0, projection=invalid))


class MinimapMarkerRasterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.layer = MapMarkerLayer()
        self.layer.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.layer.resize(240, 240)

    def tearDown(self):
        self.layer.close()

    @staticmethod
    def _snapshot(marker, projection=None, *, stock=False):
        return MapMarkerSnapshot(
            map_id=1, markers=(marker,), minimap_projection=projection or _projection(),
            merchant_stocks=(MerchantStockCapture(
                1, marker.object_ptr, marker.marker_id, 1, marker.world_x, marker.world_z, (),
            ),) if stock else (),
        )

    def _render(self, snapshot, *, dpr=1.0, scale=1.0, style='modern'):
        image = QImage(round(240 * dpr), round(240 * dpr), QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.transparent)
        self.layer._minimap_scale = scale
        self.layer._style = style
        painter = QPainter(image)
        try:
            with patch.object(self.layer, 'devicePixelRatioF', return_value=dpr):
                self.layer._paint_minimap(painter, snapshot)
        finally:
            painter.end()
        return image

    def test_icons_move_between_physical_pixels_without_rounding_steps(self):
        marker = WorldMapMarker('m', 'moai', 0, 0)
        for dpr in (1.0, 1.25, 1.5, 2.0):
            for style in ('modern', 'classic'):
                for axis in ('camera_world_x', 'camera_world_z'):
                    with self.subTest(dpr=dpr, style=style, axis=axis):
                        images = [self._render(self._snapshot(marker, replace(
                            _projection(), **{axis: -step / dpr},
                        )), dpr=dpr, style=style) for step in (0.0, 0.2, 0.4, 0.6, 0.8)]
                        for previous, current in zip(images, images[1:]):
                            self.assertNotEqual(previous, current, 'Subpixel motion was rounded away')

    def test_each_badge_moves_between_physical_pixels_without_the_icon(self):
        for action in ('shady_guy_blue', 'microwave_blue'):
            marker = WorldMapMarker('m', action, 0, 0, object_ptr=1, uses_remaining=2)
            for dpr in (1.0, 1.25, 1.5, 2.0):
                with self.subTest(action=action, dpr=dpr), patch.object(self.layer, '_paint_marker'):
                    images = [self._render(self._snapshot(marker, replace(
                        _projection(), camera_world_x=-step / dpr,
                    ), stock=action == 'shady_guy_blue'), dpr=dpr)
                        for step in (0.0, 0.2, 0.4, 0.6, 0.8)]
                    for previous, current in zip(images, images[1:]):
                        self.assertNotEqual(previous, current, 'Badge motion was rounded away')

    def test_partially_visible_markers_are_drawn_but_never_outside_the_mask(self):
        for style in ('modern', 'classic'):
            for dpr in (1.0, 1.25, 1.5, 2.0):
                for x, z in ((81.25, 0), (-81.25, 0), (0, 81.25), (0, -81.25)):
                    with self.subTest(style=style, dpr=dpr, point=(x, z)):
                        marker = WorldMapMarker('m', 'moai', x, z, source='manual')
                        snapshot = self._snapshot(marker)
                        with patch.object(self.layer, '_paint_marker', wraps=self.layer._paint_marker) as paint:
                            image = self._render(snapshot, dpr=dpr, style=style)
                        paint.assert_called_once()
                        self.assertAlmostEqual(paint.call_args.args[3], 120 + x)
                        self.assertAlmostEqual(paint.call_args.args[4], 120 - z)
                        # Inspect only the local footprint, allowing one physical
                        # pixel for antialiasing at the circle boundary.
                        painted = 0
                        cx, cy = (120 + x) * dpr, (120 - z) * dpr
                        for py in range(max(0, int(cy - 30*dpr)), min(image.height(), int(cy + 30*dpr))):
                            for px in range(max(0, int(cx - 30*dpr)), min(image.width(), int(cx + 30*dpr))):
                                if image.pixelColor(px, py).alpha():
                                    painted += 1
                                    self.assertLessEqual(
                                        ((px + 0.5)/dpr - 120)**2 + ((py + 0.5)/dpr - 120)**2,
                                        (80 + 1/dpr)**2,
                                    )
                        self.assertGreater(painted, 0)

    def test_edge_visibility_decreases_until_the_marker_is_fully_clipped(self):
        for style in ('modern', 'classic'):
            with self.subTest(style=style):
                coverage = []
                for x in (40, 70, 80, 86, 95, 125):
                    marker = WorldMapMarker('m', 'moai', x, 0, source='manual')
                    image = self._render(self._snapshot(marker), style=style)
                    rgba = image.convertToFormat(QImage.Format_RGBA8888)
                    coverage.append(sum(bytes(rgba.constBits())[3::4]))
                self.assertTrue(all(a >= b for a, b in zip(coverage, coverage[1:])))
                self.assertGreater(coverage[0], coverage[2])
                self.assertGreater(coverage[2], 0)
                self.assertEqual(coverage[-1], 0)

    def test_badge_can_remain_visible_after_the_icon_leaves_the_circle(self):
        # At 50% size the icon ends left of the mask, but the top-right
        # 16 px badge still intersects it. Its extent must participate in culling.
        for action in ('shady_guy_blue', 'microwave_blue'):
            with self.subTest(action=action), patch.object(self.layer, '_paint_marker'):
                marker = WorldMapMarker('m', action, -90.5, -5.58, object_ptr=1, uses_remaining=2)
                image = self._render(self._snapshot(marker, stock=action == 'shady_guy_blue'), scale=0.5)
                self.assertTrue(any(image.pixelColor(x, y).alpha()
                    for x in range(40, 45) for y in range(113, 128)))

    def test_far_markers_skip_paint_and_moving_markers_reuse_their_caches(self):
        far = WorldMapMarker('far', 'microwave_blue', 200, 0, uses_remaining=2)
        with patch.object(self.layer, '_paint_marker') as icon, patch.object(self.layer, '_paint_microwave_uses_badge') as badge:
            self._render(self._snapshot(far))
            icon.assert_not_called()
            badge.assert_not_called()
        marker = WorldMapMarker('m', 'microwave_blue', 0, 0, object_ptr=1, uses_remaining=2)
        self._render(self._snapshot(marker, stock=True))
        sizes = (len(self.layer._pictogram_cache), len(self.layer._stock_badge_cache), len(self.layer._microwave_badge_cache))
        self.assertTrue(all(sizes))
        for step in range(12):
            self._render(self._snapshot(marker, replace(_projection(), camera_world_x=step * 0.2), stock=True))
        self.assertEqual(sizes, (len(self.layer._pictogram_cache), len(self.layer._stock_badge_cache), len(self.layer._microwave_badge_cache)))


if __name__ == '__main__':
    unittest.main()
