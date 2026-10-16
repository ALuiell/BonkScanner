from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from core.merchant_analytics import (
    MerchantHistoryRecord,
    aggregate_merchant_history,
    stable_history_ids,
)
from infra.merchant_history_store import (
    MerchantHistoryConflict,
    MerchantHistoryStore,
)
from app.merchant_analytics import MerchantAnalyticsService
from core.map_markers import MerchantOffer, MerchantStockCapture


def record(*, merchant="b" * 32, family="forest_desert", stage=1, rarity="white", items=(1, 2, 3)):
    return MerchantHistoryRecord(
        map_id="a" * 32,
        merchant_id=merchant,
        map_family=family,
        stage=stage,
        merchant_rarity=rarity,
        item_ids=items,
    )


class MerchantHistoryStoreTests(unittest.TestCase):
    def test_append_reload_and_duplicate_are_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "merchant_history.jsonl"
            store = MerchantHistoryStore(path)
            self.assertTrue(store.append(record()))
            self.assertFalse(store.append(record()))
            store.close()

            reopened = MerchantHistoryStore(path)
            self.assertEqual(reopened.records(), (record(),))
            reopened.close()
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_conflicting_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MerchantHistoryStore(Path(directory) / "history.jsonl")
            self.assertTrue(store.append(record()))
            with self.assertRaises(MerchantHistoryConflict):
                store.append(replace(record(), item_ids=(4, 5, 6)))
            store.close()

    def test_broken_tail_is_preserved_and_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            store = MerchantHistoryStore(path)
            store.append(record())
            store.close()
            with path.open("ab") as stream:
                stream.write(b'{"v":1,"broken"')

            repaired = MerchantHistoryStore(path)
            self.assertEqual(repaired.records(), (record(),))
            self.assertTrue(repaired.writable)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(len(list(path.parent.glob("history.jsonl.broken-*"))), 1)
            repaired.close()

    def test_mid_file_corruption_makes_store_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            path.write_text('{"bad":true}\n{"also":"bad"}\n', encoding="utf-8")
            store = MerchantHistoryStore(path)
            self.assertFalse(store.writable)
            self.assertIn("line 1", store.error)
            store.close()

    def test_lock_open_failure_degrades_to_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            original_open = Path.open

            def fail_lock(candidate, *args, **kwargs):
                if str(candidate).endswith(".lock"):
                    raise PermissionError("denied")
                return original_open(candidate, *args, **kwargs)

            with patch.object(Path, "open", fail_lock):
                store = MerchantHistoryStore(path)
            self.assertFalse(store.writable)
            self.assertIn("denied", store.error)
            store.close()

    def test_failed_tail_repair_preserves_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            store = MerchantHistoryStore(path)
            store.append(record())
            store.close()
            with path.open("ab") as stream:
                stream.write(b'{"v":1,"broken"')
            original = path.read_bytes()

            with patch.object(
                MerchantHistoryStore,
                "_atomic_write_bytes",
                side_effect=OSError("disk full"),
            ):
                repaired = MerchantHistoryStore(path)
            self.assertFalse(repaired.writable)
            self.assertIn("could not be repaired", repaired.error)
            self.assertEqual(path.read_bytes(), original)
            repaired.close()


class MerchantAggregationTests(unittest.TestCase):
    def test_merchant_count_counts_each_merchant_once(self):
        snapshot = aggregate_merchant_history((
            record(items=(1, 1, 2)),
            record(merchant="c" * 32, items=(2, 3, 4)),
        ))
        beer = next(row for row in snapshot.rows if row.item_id == 1)
        self.assertEqual((beer.offer_count, beer.merchant_count, snapshot.merchants), (2, 1, 2))
        self.assertEqual(beer.merchant_percent, 50.0)

    def test_filters_and_percent_use_selected_merchants(self):
        records = (
            record(items=(1, 2, 3)),
            record(merchant="c" * 32, stage=2, rarity="gold", items=(1, 4, 5)),
        )
        snapshot = aggregate_merchant_history(records)
        self.assertEqual((snapshot.merchants, snapshot.offers), (2, 6))
        beer = next(row for row in snapshot.rows if row.item_id == 1)
        self.assertEqual((beer.offer_count, beer.merchant_percent), (2, 100.0))

        rarity_filtered = aggregate_merchant_history(records, merchant_rarity="gold", search="beer")
        self.assertEqual((rarity_filtered.merchants, rarity_filtered.offers), (1, 3))
        self.assertEqual(dict(rarity_filtered.rarity_counts), dict(snapshot.rarity_counts))
        self.assertEqual(rarity_filtered.rows[0].merchant_percent, 100.0)
        stage_filtered = aggregate_merchant_history(records, stage=2, merchant_rarity="white")
        self.assertEqual(stage_filtered.merchants, 0)
        self.assertEqual(dict(stage_filtered.rarity_counts)["gold"], 1)
        self.assertEqual(dict(stage_filtered.rarity_counts)["white"], 0)

        filtered = aggregate_merchant_history(records, stage=2, search="golden glove")
        self.assertEqual(filtered.merchants, 1)
        self.assertEqual([row.item_id for row in filtered.rows], [23] if 23 in (1, 4, 5) else [])

    def test_stable_ids_distinguish_merchants_and_maps(self):
        map_a, merchant_a = stable_history_ids(10, 20)
        self.assertEqual((map_a, merchant_a), stable_history_ids(10, 20))
        self.assertNotEqual(merchant_a, stable_history_ids(10, 21)[1])
        self.assertNotEqual(map_a, stable_history_ids(11, 20)[0])
        self.assertNotEqual(
            stable_history_ids(10, 20, game_process_identity="100:1"),
            stable_history_ids(10, 20, game_process_identity="100:2"),
        )


class MerchantAnalyticsServiceTests(unittest.TestCase):
    def test_confirmed_capture_persists_stage_family_and_three_items(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            service = MerchantAnalyticsService(MerchantHistoryStore(path))
            capture = MerchantStockCapture(
                map_id=77,
                merchant_object_ptr=0x5150,
                marker_id="auto:5150",
                merchant_rarity=3,
                world_x=1.0,
                world_z=2.0,
                items=tuple(
                    MerchantOffer(item_id, str(item_id), str(item_id), "COMMON")
                    for item_id in (1, 2, 3)
                ),
                game_process_identity="1234:5678",
                stage_ptr=0x9000,
                raw_stage_index=1,
                map_seed=4242,
            )
            runtime = SimpleNamespace(
                current_stage_index=2,
                latest_snapshot=SimpleNamespace(
                    map_seed=4242,
                    stage_ptr=0x9000,
                    stage_index=1,
                ),
                powerup_map_context=SimpleNamespace(
                    activity_max={"Pumpkin": 1}, is_graveyard=True
                ),
            )
            self.assertTrue(service.record_confirmed_capture(capture, runtime))
            service.close(wait=True)

            loaded = MerchantHistoryStore(path)
            saved = loaded.records()[0]
            self.assertEqual((saved.map_family, saved.stage), ("graveyard", 2))
            self.assertEqual(saved.merchant_rarity, "gold")
            self.assertEqual(saved.item_ids, (1, 2, 3))
            loaded.close()

    def test_capture_waits_for_matching_complete_map_context(self):
        with tempfile.TemporaryDirectory() as directory:
            service = MerchantAnalyticsService(
                MerchantHistoryStore(Path(directory) / "history.jsonl")
            )
            capture = MerchantStockCapture(
                map_id=77,
                merchant_object_ptr=0x5150,
                marker_id="auto:5150",
                merchant_rarity=0,
                world_x=0.0,
                world_z=0.0,
                items=tuple(
                    MerchantOffer(item_id, str(item_id), str(item_id), "COMMON")
                    for item_id in (1, 2, 3)
                ),
                game_process_identity="1234:5678",
                stage_ptr=0x9000,
                raw_stage_index=1,
                map_seed=4242,
            )
            incomplete = SimpleNamespace(
                current_stage_index=2,
                latest_snapshot=SimpleNamespace(
                    map_seed=4242, stage_ptr=0x9000, stage_index=1
                ),
                powerup_map_context=None,
            )
            mismatched = SimpleNamespace(
                current_stage_index=2,
                latest_snapshot=SimpleNamespace(
                    map_seed=4242, stage_ptr=0xA000, stage_index=1
                ),
                powerup_map_context=SimpleNamespace(
                    activity_max={"Pumpkin": 1}, is_graveyard=True
                ),
            )
            complete = SimpleNamespace(
                current_stage_index=2,
                latest_snapshot=SimpleNamespace(
                    map_seed=4242, stage_ptr=0x9000, stage_index=1
                ),
                powerup_map_context=SimpleNamespace(
                    activity_max={"Pumpkin": 1}, is_graveyard=True
                ),
            )

            self.assertFalse(service.record_confirmed_capture(capture, incomplete))
            self.assertFalse(service.record_confirmed_capture(capture, mismatched))
            self.assertTrue(service.record_confirmed_capture(capture, complete))
            while service.status().total_recorded < 1:
                time.sleep(0.01)
            changed = replace(capture, items=tuple(reversed(capture.items)))
            self.assertFalse(service.record_confirmed_capture(changed, complete))
            self.assertIsNone(service.status().error)
            service.close()

    def test_read_only_store_rejects_capture_without_queueing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            owner = MerchantHistoryStore(path)
            service = MerchantAnalyticsService(MerchantHistoryStore(path))
            capture = MerchantStockCapture(
                77,
                0x5150,
                "auto:5150",
                0,
                0.0,
                0.0,
                tuple(
                    MerchantOffer(item_id, str(item_id), str(item_id), "COMMON")
                    for item_id in (1, 2, 3)
                ),
                game_process_identity="1234:5678",
                stage_ptr=0x9000,
                raw_stage_index=1,
                map_seed=4242,
            )
            runtime = SimpleNamespace(
                current_stage_index=2,
                latest_snapshot=SimpleNamespace(
                    map_seed=4242, stage_ptr=0x9000, stage_index=1
                ),
                powerup_map_context=SimpleNamespace(
                    activity_max={"Pumpkin": 1}, is_graveyard=True
                ),
            )

            self.assertFalse(service.collection_available())
            self.assertFalse(service.record_confirmed_capture(capture, runtime))
            self.assertEqual(service._pending, set())
            service.close()
            owner.close()


if __name__ == "__main__":
    unittest.main()
