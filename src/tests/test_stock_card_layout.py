from __future__ import annotations

import unittest
from dataclasses import replace

import src
from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtWidgets import QApplication

from core.item_metadata import ITEMS
from core.map_markers import MapViewport, MerchantOffer, MerchantStockCapture, WorldMapMarker
from ui.stock_card_layout import group_stock_entries, hovered_stock_marker, layout_stock_cards, marker_bounds
from ui.stock_card_layout import stock_card_width, stock_card_height, stock_item_lines


def entry(index, x, y, size=48, items=3):
    marker = WorldMapMarker(str(index), "shady_guy_blue", x, y, object_ptr=index + 1)
    stock = MerchantStockCapture(1, index + 1, str(index), 1, x, y, tuple(
        MerchantOffer(i, "Beer", "Beer", "UNCOMMON") for i in range(items)
    ))
    return marker, stock, (float(x), float(y), float(size))


class StockCardLayoutTests(unittest.TestCase):
    def test_price_columns_fit_names_and_compact_frame(self):
        from ui.stock_card_layout import priced_stock_columns, priced_stock_card_width
        items = (MerchantOffer(1, 'a', 'Cursed Doll', 'COMMON', 412000),
                 MerchantOffer(2, 'b', 'Pot (stainless steel)', 'LEGENDARY', 999000),
                 MerchantOffer(3, 'c', 'Overpowered Lamp', 'LEGENDARY', 1200000))
        names, prices = priced_stock_columns(items)
        width = priced_stock_card_width(items, False)
        self.assertLessEqual(width - (8 + names + 9 + prices), 9)
        self.assertLess(width, 280)
        original = entry(0, 300, 300)
        entries = ((original[0], replace(original[1], items=items), original[2]),)
        for viewport in (MapViewport(0, 0, 1000, 800), MapViewport(0, 0, 170, 800)):
            plans = layout_stock_cards(group_stock_entries(entries), viewport, 1, 'always', None, show_prices=True)
            self.assertEqual(len(plans), 1)
            plan = plans[0]
            self.assertLessEqual(plan.bounds.right(), viewport.left + viewport.width)
            name_width = max(1, min(names, plan.bounds.width() - 25 - prices))
            expected_height = 31 + 17 * sum(len(stock_item_lines(i.display_name, int(name_width))) for i in items)
            self.assertEqual(plan.bounds.height(), expected_height)

    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_catalog_width_fits_current_names_and_is_shared_by_groups(self):
        font = QFont("Segoe UI")
        font.setPixelSize(12)
        metrics = QFontMetricsF(font)
        width = stock_card_width()
        self.assertLessEqual(width, 190)
        for item in ITEMS:
            name = item.ui_name or item.scanner_name
            lines = stock_item_lines(name, int(width - 22))
            self.assertEqual("".join(lines).replace(" ", ""), f"• {name}".replace(" ", ""))
            for line in lines:
                self.assertLessEqual(metrics.horizontalAdvance(line), width - 22)
        entries = (entry(0, 250, 250), entry(1, 280, 250), entry(2, 900, 250, items=1))
        groups = group_stock_entries(entries)
        for scale in (.5, 1, 1.5, 2):
            plans = layout_stock_cards(groups, MapViewport(0, 0, 1400, 1000), scale, "always", None)
            self.assertEqual(len(plans), 2)
            self.assertEqual([plan.bounds.width() for plan in plans], [width, width])

    def test_wrapped_names_keep_complete_text_and_increase_card_height(self):
        font = QFont("Segoe UI")
        font.setPixelSize(12)
        metrics = QFontMetricsF(font)
        original = entry(0, 250, 250, items=1)
        for name in ("A much longer item name than the current catalog contains", "W" * 50):
            offer = MerchantOffer(1, "future", name, "RARE")
            modified = (original[0], replace(original[1], items=(offer,)), original[2])
            lines = stock_item_lines(name, 90)
            self.assertGreater(len(lines), 1)
            self.assertEqual(''.join(lines).replace(' ', ''), ('• ' + name).replace(' ', ''))
            for line in lines:
                self.assertLessEqual(metrics.horizontalAdvance(line), 90)
            for grouped in (False, True):
                height = stock_card_height((modified,), 1, grouped, 112)
                self.assertEqual(height, (60 if grouped else 31) + 17 * len(lines))
            self.assertIs(lines, stock_item_lines(name, 90))

    def test_groups_transitive_neighbors_without_moving_markers(self):
        entries = (entry(0, 200, 200), entry(1, 260, 200), entry(2, 320, 200), entry(3, 650, 500))
        groups = group_stock_entries(entries)
        self.assertEqual([len(g.entries) for g in groups], [3, 1])
        self.assertEqual(tuple(e for g in groups for e in g.entries), entries)

    def test_nearest_hover_resolves_overlapping_hit_circles(self):
        groups = group_stock_entries((entry(0, 200, 200), entry(1, 225, 200)))
        self.assertEqual(hovered_stock_marker(groups, (224, 200)), "1")
        self.assertEqual(hovered_stock_marker(groups, (201, 200)), "0")
        self.assertIsNone(hovered_stock_marker(groups, (50, 50)))

    def test_three_merchants_share_one_complete_card_in_all_modes(self):
        entries = (entry(0, 300, 300), entry(1, 330, 310), entry(2, 315, 335))
        groups = group_stock_entries(entries)
        viewport = MapViewport(0, 0, 900, 700)
        obstacles = tuple(marker_bounds(e[2]) for e in entries)
        for mode in ("smart", "always", "cursor"):
            with self.subTest(mode=mode):
                plans = layout_stock_cards(groups, viewport, 1, mode, "1", obstacles)
                self.assertEqual(len(plans), 1)
                self.assertEqual(plans[0].entries, entries)
                self.assertFalse(plans[0].compact)
                self.assertFalse(any(plans[0].bounds.intersects(r) for r in obstacles))

    def test_cursor_mode_does_not_show_unhovered_groups(self):
        groups = group_stock_entries((entry(0, 200, 200), entry(1, 700, 200)))
        viewport = MapViewport(0, 0, 1000, 700)
        self.assertEqual(layout_stock_cards(groups, viewport, 1, "cursor", None), ())
        plans = layout_stock_cards(groups, viewport, 1, "cursor", "1")
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].entries[0][0].marker_id, "1")

    def test_edge_and_scaled_cards_stay_inside_viewport(self):
        viewport = MapViewport(70, 90, 750, 620)
        area = QRectF(75, 95, 740, 610)
        for x, y in ((90, 110), (800, 110), (90, 690), (800, 690)):
            for scale in (.5, 1, 2, 3):
                groups = group_stock_entries((entry(0, x, y, 48 * scale),))
                plans = layout_stock_cards(groups, viewport, scale, "smart", "0")
                self.assertEqual(len(plans), 1)
                self.assertTrue(area.contains(plans[0].bounds))

    def test_oversized_group_collapses_and_hover_exposes_selected_stock(self):
        entries = tuple(entry(i, 250 + i, 220) for i in range(30))
        groups = group_stock_entries(entries)
        viewport = MapViewport(0, 0, 700, 500)
        collapsed = layout_stock_cards(groups, viewport, 1, "smart", None)
        self.assertTrue(collapsed[0].compact)
        expanded = layout_stock_cards(groups, viewport, 1, "smart", "15")
        self.assertFalse(expanded[0].compact)
        self.assertEqual(expanded[0].entries, (entries[15],))

    def test_smart_avoids_card_collisions_and_reserves_hovered_card(self):
        entries = tuple(entry(i, 160 + (i % 3) * 180, 140 + (i // 3) * 180) for i in range(9))
        groups = group_stock_entries(entries)
        plans = layout_stock_cards(groups, MapViewport(0, 0, 750, 750), 1, "smart", "4")
        self.assertTrue(any(e[0].marker_id == "4" for e in plans[-1].entries))
        for i, plan in enumerate(plans):
            self.assertFalse(any(plan.bounds.intersects(other.bounds) for other in plans[:i]))

    def test_narrow_viewport_does_not_produce_invalid_rectangles(self):
        groups = group_stock_entries((entry(0, 20, 20),))
        self.assertEqual(layout_stock_cards(groups, MapViewport(0, 0, 50, 30), 1, "smart", None), ())


if __name__ == "__main__":
    unittest.main()
