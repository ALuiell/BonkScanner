import unittest
from dataclasses import replace
from core.shady_prices import format_shady_price


class ShadyPriceTests(unittest.TestCase):
    def test_tracker_keeps_last_visited_price_until_next_capture(self):
        from unittest.mock import Mock
        from core.map_markers import MerchantStockCapture, MerchantOffer
        from app.map_marker_tracker import MapMarkerTracker
        from infra.memory.map_marker_client import MapMemoryFrame
        stock = MerchantStockCapture(1, 123, 'auto:7B', 1, 0, 0,
            (MerchantOffer(1, 'Beer', 'Beer', 'UNCOMMON', 60),), class_ptr=99)
        frame = MapMemoryFrame(1, False, 1000, None, None, merchant_stock_capture=stock)
        client = Mock()
        client.poll.return_value = frame
        client.activity_is_active.return_value = True
        now = [1.0]
        tracker = MapMarkerTracker('test', client_factory=lambda _: client, clock=lambda: now[0])
        def tick(**kwargs):
            return tracker.tick(client_height=1000, merchant_memory_enabled=True,
                                merchant_prices_enabled=kwargs.get('enabled', True))
        self.assertEqual(tick().merchant_stocks[0].items[0].price, 60)
        client.poll.return_value = replace(frame, merchant_stock_capture=None)
        for t in (1.025, 1.1, 1.5, 5.0):
            now[0] = t
            self.assertEqual(tick().merchant_stocks[0].items[0].price, 60)

        revisited = replace(
            stock,
            items=(replace(stock.items[0], price=68),),
        )
        client.poll.return_value = replace(frame, merchant_stock_capture=revisited)
        self.assertEqual(tick().merchant_stocks[0].items[0].price, 68)

        client.poll.return_value = replace(frame, merchant_stock_capture=None)
        self.assertIsNone(tick(enabled=False).merchant_stocks[0].items[0].price)
        self.assertIsNone(tick().merchant_stocks[0].items[0].price)
        client.poll.return_value = replace(frame, map_id=2, merchant_stock_capture=None)
        self.assertEqual(tick().merchant_stocks, ())

    def test_price_capture_uses_visible_button_without_economy_or_multiplier(self):
        from unittest.mock import Mock
        from core.map_markers import MerchantOffer
        from infra.memory.map_marker_client import MapMarkerMemoryClient
        mem = Mock()
        mem.module_base_address.return_value = 0x100000
        c = MapMarkerMemoryClient(memory=mem)
        merchant, picker, buttons, button = 1000, 2000, 4000, 5000
        pointers = {picker + 0x20: buttons, buttons + 0x20: button}
        ints = {button + 0xDC: 60}
        mem.read_ptr.side_effect = pointers.__getitem__
        mem.read_i32.side_effect = ints.__getitem__
        offers = (MerchantOffer(1, 'Beer', 'Beer', 'UNCOMMON'),)
        enriched = c._read_shady_prices((merchant, 0, picker), offers)
        self.assertEqual(enriched[0].price, 60)
        mem.read_float.assert_not_called()
        ints[button + 0xDC] = -1
        self.assertEqual(c._read_shady_prices((merchant, 0, picker), offers), offers)
        c._read_shady_offer_gate = Mock(return_value=None)
        c._read_shady_prices = Mock(side_effect=AssertionError('closed window'))
        self.assertIsNone(c._read_shady_stock_capture(1, prices_enabled=True))
        c._read_shady_prices.assert_not_called()

    def test_formats_boundaries_without_rounding_up(self):
        for value, expected in ((None, '—'), (-1, '—'), (0, '0'), (300, '300'),
            (999, '999'), (1000, '1k'), (1099, '1k'), (1599, '1.5k'),
            (9999, '9.9k'), (10000, '10k'), (45999, '45k'), (412999, '412k'),
            (999999, '999k'), (1000000, '1m'), (1299999, '1.2m'), (2147483647, '2147.4m')):
            with self.subTest(value=value):
                self.assertEqual(format_shady_price(value), expected)

if __name__ == '__main__':
    unittest.main()
