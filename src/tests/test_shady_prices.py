import unittest
from dataclasses import replace
from core.shady_prices import ShadyEconomy, shady_price, format_shady_price


class ShadyPriceTests(unittest.TestCase):
    def test_tracker_updates_visited_stock_with_throttled_economy_reads(self):
        from unittest.mock import Mock
        from core.map_markers import MerchantStockCapture, MerchantOffer
        from app.map_marker_tracker import MapMarkerTracker
        from infra.memory.map_marker_client import MapMemoryFrame
        stock = MerchantStockCapture(1, 123, 'auto:7B', 1, 0, 0,
            (MerchantOffer(1, 'Beer', 'Beer', 'UNCOMMON', 60, 1.0),), class_ptr=99)
        frame = MapMemoryFrame(1, False, 1000, None, None, merchant_stock_capture=stock)
        client = Mock()
        client.poll.return_value = frame
        client.activity_is_active.return_value = True
        client.read_shady_economy.return_value = ShadyEconomy(0, 0, 1)
        now = [1.0]
        tracker = MapMarkerTracker('test', client_factory=lambda _: client, clock=lambda: now[0])
        def tick(**kwargs):
            return tracker.tick(client_height=1000, merchant_memory_enabled=True,
                                merchant_prices_enabled=kwargs.get('enabled', True))
        self.assertEqual(tick().merchant_stocks[0].items[0].price, 60)
        client.poll.return_value = replace(frame, merchant_stock_capture=None)
        for t in (1.025, 1.1, 1.25, 1.49):
            now[0] = t
            tick()
        self.assertEqual(client.read_shady_economy.call_count, 1)
        now[0] = 1.5
        client.read_shady_economy.return_value = ShadyEconomy(1, 0, 1)
        self.assertEqual(tick().merchant_stocks[0].items[0].price, 68)
        self.assertEqual(client.read_shady_economy.call_count, 2)
        now[0] = 2
        client.read_shady_economy.side_effect = OSError('unavailable')
        self.assertIsNone(tick().merchant_stocks[0].items[0].price)
        client.read_shady_economy.side_effect = None
        now[0] = 2.5
        self.assertEqual(tick().merchant_stocks[0].items[0].price, 68)
        self.assertIsNone(tick(enabled=False).merchant_stocks[0].items[0].price)
        calls = client.read_shady_economy.call_count
        now[0] = 4
        tick(enabled=False)
        self.assertEqual(client.read_shady_economy.call_count, calls)
        client.poll.return_value = replace(frame, map_id=2, merchant_stock_capture=None)
        self.assertEqual(tick().merchant_stocks, ())

    def test_price_capture_requires_matching_visible_ui_price(self):
        from unittest.mock import Mock
        from core.map_markers import MerchantOffer
        from infra.memory.map_marker_client import MapMarkerMemoryClient
        mem = Mock()
        mem.module_base_address.return_value = 0x100000
        c = MapMarkerMemoryClient(memory=mem)
        c.read_shady_economy = Mock(return_value=ShadyEconomy(0, 0, 1))
        merchant, picker, multipliers, buttons, button = 1000, 2000, 3000, 4000, 5000
        pointers = {merchant + 0xA8: multipliers, picker + 0x20: buttons, buttons + 0x20: button}
        ints = {multipliers + 0x18: 1, button + 0xDC: 60}
        mem.read_ptr.side_effect = pointers.__getitem__
        mem.read_i32.side_effect = ints.__getitem__
        mem.read_float.return_value = 1.0
        offers = (MerchantOffer(1, 'Beer', 'Beer', 'UNCOMMON'),)
        enriched = c._read_shady_prices((merchant, 0, picker), offers)
        self.assertEqual(enriched[0].price, 60)
        self.assertEqual(enriched[0].slot_multiplier, 1)
        ints[button + 0xDC] = 61
        self.assertEqual(c._read_shady_prices((merchant, 0, picker), offers), offers)
        c._read_shady_offer_gate = Mock(return_value=None)
        c._read_shady_prices = Mock(side_effect=AssertionError('closed window'))
        self.assertIsNone(c._read_shady_stock_capture(1, prices_enabled=True))
        c._read_shady_prices.assert_not_called()

    def test_live_observed_three_chest_states(self):
        # Live prices, independent of the implementation: same merchant, no
        # price-modifying pickups, stage 1. Include intermediate rounding.
        for rarity, multiplier, expected in (
            ('LEGENDARY', 1.0251795053482056, (246, 279, 320)),
            ('UNCOMMON', 1.3208847045898438, (79, 90, 103)),
            ('UNCOMMON', .5757653713226318, (35, 39, 45)),
            ('COMMON', 1.2168240547180176, (37, 41, 47)),
        ):
            with self.subTest(rarity=rarity, multiplier=multiplier):
                self.assertEqual(tuple(shady_price(ShadyEconomy(n, 0, 1), rarity, multiplier) for n in range(3)), expected)

    def test_formats_boundaries_without_rounding_up(self):
        for value, expected in ((None, '—'), (-1, '—'), (0, '0'), (300, '300'),
            (999, '999'), (1000, '1k'), (1099, '1k'), (1599, '1.5k'),
            (9999, '9.9k'), (10000, '10k'), (45999, '45k'), (412999, '412k'),
            (999999, '999k'), (1000000, '1m'), (1299999, '1.2m'), (2147483647, '2147.4m')):
            with self.subTest(value=value):
                self.assertEqual(format_shady_price(value), expected)

    def test_invalid_economy_and_slot_hide_price(self):
        economy = ShadyEconomy(0, 0, 1)
        for bad in (replace(economy, purchased=-1), replace(economy, price_multiplier=float('nan')),
                    replace(economy, stage_index=-1), replace(economy, purchased=10000)):
            self.assertIsNone(shady_price(bad, 'COMMON', 1))
        for slot in (0, 2, float('nan')):
            self.assertIsNone(shady_price(economy, 'COMMON', slot))

    def test_stage_and_global_price_modifiers(self):
        self.assertEqual(shady_price(ShadyEconomy(0, 1, 1.1), 'UNCOMMON', 1), 132)


if __name__ == '__main__':
    unittest.main()
