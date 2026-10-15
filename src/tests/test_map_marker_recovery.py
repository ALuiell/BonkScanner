"""Controlled game-memory transitions; no live process access or sleeps."""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from app.map_marker_tracker import MapMarkerTracker
from infra.memory.map_marker_client import MapMarkerMemoryClient, MapScopeNotReadyError
from infra.memory.reader import MemoryReadError
from tests import test_map_marker_runtime as fixtures


class MarkerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MapMarkerResilienceTests()
        self.fixture.setUp()
        self.memory = self.fixture.memory
        self.client = self.fixture.client
        self.tracker = self.fixture.tracker
        self.obj = self.fixture.object_ptr
        self.now = self.fixture.now
        self.options = self.fixture.options

    def tick(self, elapsed=0.0):
        self.now[0] += elapsed
        return self.tracker.tick(**self.options)

    def microwave(self):
        self.client._class_name_from_ptr.return_value = "InteractableMicrowave"
        self.state(uses=1)
        self.before = self.fixture.remember_markers()
        return self.before

    def state(self, *, uses=0, cooking=0, item=0):
        self.memory.i32s[self.obj + self.client.MICROWAVE_USES_LEFT_OFFSET] = uses
        self.memory.u8s[self.obj + self.client.MICROWAVE_IS_COOKING_OFFSET] = cooking
        self.memory.u8s[self.obj + self.client.MICROWAVE_HAS_ITEM_OFFSET] = item

    def other_markers(self, snapshot):
        return tuple(m for m in snapshot.markers if m.object_ptr != self.obj)

    def retire(self):
        self.state()
        self.assertIn(self.obj, {m.object_ptr for m in self.tick().markers})
        hidden = self.tick(0.4)
        self.assertNotIn(self.obj, {m.object_ptr for m in hidden.markers})
        self.assertIn(self.obj, self.tracker._retired_markers)
        return hidden

    def install_real_stage_resolver(self, *, index=0):
        c = self.client
        static = 0x710000
        self.memory.ptrs[c._module_base + c.MAP_CONTROLLER_TYPE_INFO_OFFSET] = 0x720000
        self.memory.ptrs[0x720000 + c.CLASS_STATIC_FIELDS_OFFSET] = static
        self.stage_address = static + c.MAP_CONTROLLER_CURRENT_STAGE_OFFSET
        self.index_address = static + c.MAP_CONTROLLER_INDEX_OFFSET
        self.memory.ptrs[self.stage_address] = self.fixture.state["stage"]
        self.memory.i32s[self.index_address] = index
        c._resolve_stage_scope = MapMarkerMemoryClient._resolve_stage_scope.__get__(c)

    def test_stage_index_zero_is_valid_and_null_pointer_preserves_all_markers(self):
        self.install_real_stage_resolver(index=0)
        before = self.microwave()
        scope = self.tracker._map_scope
        self.assertEqual(scope[-1], 0)
        self.memory.ptrs[self.stage_address] = 0
        for _ in range(3):
            waiting = self.tick(0.1)
            self.assertEqual(waiting.markers, before.markers)
            self.assertFalse(waiting.map_open)
            self.assertIsNone(waiting.viewport)
            self.assertEqual(self.tracker._map_scope, scope)
        self.memory.ptrs[self.stage_address] = self.fixture.state["stage"]
        self.assertEqual(self.tick().markers, before.markers)
        self.assertEqual(self.fixture.factory.call_count, 1)

    def test_new_stage_after_incomplete_sample_clears_old_markers_even_same_seed(self):
        self.install_real_stage_resolver()
        self.microwave()
        self.retire()
        self.memory.ptrs[self.stage_address] = 0
        self.tick()
        self.memory.ptrs[self.stage_address] = 0x750000
        changed = self.tick()
        self.assertEqual(changed.markers, ())
        self.assertEqual(self.tracker._retired_markers, {})
        self.assertEqual(self.tracker._completion_pending, {})
        self.state(item=1)
        self.assertEqual(self.tick(0.6).markers, ())

    def test_missing_stage_type_info_is_waiting_not_an_invalid_dereference(self):
        self.install_real_stage_resolver()
        slot = self.client._module_base + self.client.MAP_CONTROLLER_TYPE_INFO_OFFSET
        for token in (0, 0x2000A397):
            with self.subTest(token=token):
                self.client._map_controller_static_fields = 0
                self.memory.ptrs[slot] = token
                self.memory.ptr_reads.clear()
                with self.assertRaises(MapScopeNotReadyError):
                    self.client._resolve_stage_scope()
                self.assertNotIn(token + self.client.CLASS_STATIC_FIELDS_OFFSET, self.memory.ptr_reads)

    def test_negative_stage_index_waits_but_zero_recovers(self):
        self.install_real_stage_resolver(index=-1)
        with self.assertRaises(MapScopeNotReadyError):
            self.client._resolve_stage_scope()
        self.memory.i32s[self.index_address] = 0
        self.assertEqual(self.client._resolve_stage_scope()[1], 0)

    def test_last_use_cooking_ready_collection_and_destruction_keep_other_markers(self):
        before = self.microwave()
        others = self.other_markers(before)
        for state in (dict(cooking=1), dict(item=1)):
            self.state(**state)
            snapshot = self.tick(0.2)
            self.assertEqual(self.other_markers(snapshot), others)
            microwave = next(m for m in snapshot.markers if m.object_ptr == self.obj)
            self.assertEqual(microwave.uses_remaining, 0)
        hidden = self.retire()
        self.assertEqual(hidden.markers, others)
        self.memory.ptrs[self.obj + self.client.MANAGED_NATIVE_OFFSET] = 0
        self.assertEqual(self.tick(0.5).markers, others)
        self.assertNotIn(self.obj, self.tracker._retired_markers)
        for _ in range(4):
            self.assertEqual(self.tick(0.5).markers, others)
        self.assertIs(self.tracker._client, self.client)

    def test_two_microwaves_keep_independent_counts_through_last_use_and_recovery(self):
        self.microwave()
        second = self.obj + 0x1000
        self.memory.ptrs[second] = 0xA000
        self.memory.ptrs[second + self.client.MANAGED_NATIVE_OFFSET] = 0x33000
        self.memory.i32s[second + self.client.MICROWAVE_USES_LEFT_OFFSET] = 2
        self.memory.ptrs[self.fixture.current_address] = second
        self.tick()
        self.assertEqual(len(self.tracker.snapshot.markers), 4)
        self.state()
        self.tick()
        exhausted = self.tick(0.4)
        self.assertEqual(len(exhausted.markers), 3)
        self.assertEqual(next(m.uses_remaining for m in exhausted.markers if m.object_ptr == second), 2)
        self.state(item=1)
        restored = self.tick(0.5)
        counts = {m.object_ptr: m.uses_remaining for m in restored.markers}
        self.assertEqual(len(restored.markers), 4)
        self.assertEqual(counts[self.obj], 0)
        self.assertEqual(counts[second], 2)
        self.assertEqual(self.memory.ptrs[self.fixture.current_address], second)

    def test_one_false_sample_does_not_delete_microwave(self):
        before = self.microwave()
        self.state()
        self.assertEqual(len(self.tick().markers), len(before.markers))
        self.state(item=1)
        restored = self.tick(0.1)
        self.assertEqual(len(restored.markers), len(before.markers))
        self.assertEqual(self.tracker._completion_pending, {})
        self.assertEqual(self.tracker._retired_markers, {})

    def test_recently_hidden_microwave_recovers_without_current_interactable(self):
        before = self.microwave()
        self.retire()
        self.assertEqual(self.memory.ptrs[self.fixture.current_address], 0)
        self.state(item=1)
        restored = self.tick(0.5)
        self.assertEqual({m.marker_id for m in restored.markers}, {m.marker_id for m in before.markers})
        self.assertEqual(self.tracker._retired_markers, {})
        self.assertEqual(next(m.uses_remaining for m in restored.markers if m.object_ptr == self.obj), 0)

    def test_unknown_sample_interrupts_completion_confirmation(self):
        self.microwave()
        self.state()
        self.tick()
        self.state(uses=-1)
        self.assertEqual(len(self.tick(0.4).markers), 3)
        self.assertNotIn(self.obj, self.tracker._completion_pending)
        self.state()
        self.assertEqual(len(self.tick(0.1).markers), 3)
        self.assertEqual(len(self.tick(0.4).markers), 2)

    def test_persistently_unreadable_object_hides_without_losing_other_markers(self):
        before = self.microwave()
        original_read = self.memory.read_bytes

        def read(address, size):
            if address == self.obj:
                raise MemoryReadError("object no longer readable")
            return original_read(address, size)

        self.memory.read_bytes = read
        self.assertEqual(len(self.tick().markers), len(before.markers))
        for _ in range(19):
            self.assertEqual(len(self.tick(0.1).markers), len(before.markers))
        hidden = self.tick(0.1)
        self.assertEqual(hidden.markers, self.other_markers(before))
        self.assertIn(self.obj, self.tracker._retired_markers)
        self.assertIs(self.tracker._client, self.client)

        self.memory.read_bytes = original_read
        restored = self.tick(0.5)
        self.assertEqual({m.marker_id for m in restored.markers},
                         {m.marker_id for m in before.markers})
        self.assertNotIn(self.obj, self.tracker._retired_markers)

    def test_map_read_failure_restarts_unreadable_object_confirmation(self):
        before = self.microwave()
        original_read = self.memory.read_bytes

        def read(address, size):
            if address == self.obj:
                raise MemoryReadError("object read failed")
            return original_read(address, size)

        self.memory.read_bytes = read
        self.tick()
        for _ in range(15):
            self.tick(0.1)
        with patch.object(
            self.client, "poll", side_effect=MapScopeNotReadyError("stage waiting")
        ):
            self.tick(1.0)
        self.assertEqual(self.tracker._unreadable_since, {})
        self.assertEqual(self.tick().markers, tuple(
            replace(marker, uses_remaining=None) if marker.object_ptr == self.obj else marker
            for marker in before.markers
        ))
        for _ in range(19):
            self.assertEqual(len(self.tick(0.1).markers), len(before.markers))
        self.assertEqual(self.tick(0.1).markers, self.other_markers(before))

    def test_long_gap_does_not_count_as_consecutive_object_failures(self):
        before = self.microwave()
        original_read = self.memory.read_bytes

        def read(address, size):
            if address == self.obj:
                raise MemoryReadError("object read failed")
            return original_read(address, size)

        self.memory.read_bytes = read
        self.tick()
        self.assertEqual(len(self.tick(5.0).markers), len(before.markers))
        self.assertNotIn(self.obj, self.tracker._retired_markers)

    def test_waiting_for_stage_interrupts_completion_confirmation(self):
        self.install_real_stage_resolver()
        self.microwave()
        self.state()
        self.tick()
        self.memory.ptrs[self.stage_address] = 0
        self.tick(0.4)
        self.memory.ptrs[self.stage_address] = self.fixture.state["stage"]
        self.assertEqual(len(self.tick().markers), 3)
        self.assertEqual(len(self.tick(0.4).markers), 2)

    def test_destroyed_object_is_removed_without_resurrection_window(self):
        before = self.microwave()
        self.memory.ptrs[self.obj + self.client.MANAGED_NATIVE_OFFSET] = 0
        self.assertEqual(self.tick().markers, self.other_markers(before))
        self.assertNotIn(self.obj, self.tracker._retired_markers)

    def test_recycled_class_or_native_identity_never_restores_old_marker(self):
        for field in (0, MapMarkerMemoryClient.MANAGED_NATIVE_OFFSET):
            with self.subTest(field=field):
                self.setUp()
                before = self.microwave()
                self.retire()
                self.state(item=1)
                self.memory.ptrs[self.obj + field] = 0xDEAD00
                self.assertEqual(self.tick(0.5).markers, self.other_markers(before))
                self.assertNotIn(self.obj, self.tracker._retired_markers)

    def test_expired_candidate_is_not_read_or_resurrected(self):
        before = self.microwave()
        self.retire()
        self.state(item=1)
        self.client.activity_is_active = Mock(wraps=self.client.activity_is_active)
        self.assertEqual(self.tick(3.0).markers, self.other_markers(before))
        self.assertNotIn(self.obj, [call.args[0] for call in self.client.activity_is_active.call_args_list])
        self.assertEqual(self.tracker._retired_markers, {})

    def test_disabling_discovery_drops_recovery_candidates(self):
        self.microwave()
        self.retire()
        self.options.update(automatic_discovery=False, merchant_memory_enabled=False)
        self.tick()
        self.assertEqual(self.tracker._retired_markers, {})
        self.options["automatic_discovery"] = True
        self.state(item=1)
        self.assertNotIn(self.obj, {m.object_ptr for m in self.tick(0.5).markers})

    def test_disabling_merchant_memory_does_not_resurrect_cached_stock(self):
        self.microwave()
        self.tick()  # Learn the visited merchant's native identity too.
        ptr = 0x5150
        self.memory.u8s[ptr + self.client.SHADY_DONE_OFFSET] = 1
        self.tick()
        self.tick(0.4)
        self.assertIn(ptr, self.tracker._retired_markers)
        self.options["merchant_memory_enabled"] = False
        self.memory.u8s[ptr + self.client.SHADY_DONE_OFFSET] = 0
        self.tick(0.5)
        self.assertEqual(self.tracker._merchant_stocks, {})
        self.options["merchant_memory_enabled"] = True
        self.assertEqual(self.tick().merchant_stocks, ())

    def test_first_seed_sample_relabels_retired_stock_without_inventing_seed(self):
        self.fixture.state["seed"] = None
        self.microwave()
        self.tick()
        ptr = 0x5150
        self.memory.u8s[ptr + self.client.SHADY_DONE_OFFSET] = 1
        self.tick()
        self.tick(0.4)
        self.assertIn(ptr, self.tracker._retired_markers)
        self.fixture.state["seed"] = 42
        self.tick()
        self.memory.u8s[ptr + self.client.SHADY_DONE_OFFSET] = 0
        restored = self.tick(0.5)
        self.assertEqual(len(restored.merchant_stocks), 1)
        self.assertEqual(restored.merchant_stocks[0].map_id, restored.map_id)
        self.assertIsNone(restored.merchant_stocks[0].map_seed)

    def test_worker_reconnect_preserves_ledger_but_drops_screen_projection(self):
        before = self.microwave()
        self.tracker.recover()
        self.assertEqual(self.tracker.snapshot.markers, before.markers)
        self.assertIsNone(self.tracker.snapshot.viewport)
        replacement = self.fixture.make_client()
        self.fixture.factory.return_value = replacement
        after = self.tick()
        self.assertEqual(after.markers, before.markers)
        self.assertIs(self.tracker._client, replacement)

    def test_same_seed_new_process_drops_retired_markers_after_reconnect(self):
        self.microwave()
        self.retire()
        self.tracker.recover()
        replacement = self.fixture.make_client()
        replacement._game_process_identity = "another-process"
        self.fixture.factory.return_value = replacement
        self.state(item=1)
        self.assertEqual(self.tick(0.5).markers, ())
        self.assertEqual(self.tracker._retired_markers, {})

    def test_microwave_flags_and_count_share_one_bounded_read(self):
        self.microwave()
        self.state(cooking=1)
        self.memory.byte_reads.clear()
        self.client.activity_is_active(self.obj)
        first = self.client.MICROWAVE_USES_LEFT_OFFSET
        self.assertEqual(self.memory.byte_reads, [
            (self.obj, 24), (self.obj + first, self.client.MICROWAVE_HAS_ITEM_OFFSET - first + 1)
        ])
        self.assertTrue(self.client.last_activity_read(self.obj).active)
        self.assertEqual(self.client.last_microwave_uses(self.obj), 0)

    def test_count_reader_failure_is_isolated_to_one_marker(self):
        f = fixtures.MapMarkerTrackerTests()
        f.setUp()
        activity = fixtures.DetectedMapActivity(1, 123, "InteractableMicrowave", "microwave_white", 0, 0, 1)
        client = fixtures.FakeMarkerClient([f.frame(activity=activity), f.frame()])
        client.last_microwave_uses = Mock(side_effect=RuntimeError("count adapter failed"))
        tracker = MapMarkerTracker("game", client_factory=lambda _: client, automatic_scan_interval=0)
        tracker.tick(client_height=600, automatic_discovery=True)
        snapshot = tracker.tick(client_height=600, automatic_discovery=True)
        self.assertEqual(len(snapshot.markers), 1)
        self.assertIsNone(snapshot.markers[0].uses_remaining)

    def test_recovery_checks_have_a_budget_and_do_not_starve_later_entries(self):
        self.microwave()
        self.retire()
        template = self.tracker._retired_markers.pop(self.obj)
        pointers = {0x1000000 + i * 0x1000 for i in range(128)}
        for ptr in pointers:
            self.memory.ptrs[ptr] = template.identity[0]
            self.memory.ptrs[ptr + self.client.MANAGED_NATIVE_OFFSET] = ptr + 0x100
            self.tracker._retired_markers[ptr] = replace(
                template, marker=replace(template.marker, object_ptr=ptr, marker_id=f"auto:{ptr:X}"),
                native_ptr=ptr + 0x100, next_check_at=self.now[0],
            )
        seen = set()
        original = self.client.activity_is_active
        checked = []
        def read(ptr, **kwargs):
            if ptr in pointers:
                checked.append(ptr)
            return original(ptr, **kwargs)
        self.client.activity_is_active = read
        for _ in range(16):
            checked.clear()
            self.tick(0.1)
            self.assertLessEqual(len(checked), self.tracker.RECOVERY_CHECK_BUDGET)
            seen.update(checked)
        self.assertEqual(seen, pointers)

    def test_close_clears_all_completion_and_recovery_state(self):
        self.microwave()
        self.retire()
        self.tracker.close()
        self.assertEqual(self.tracker._retired_markers, {})
        self.assertEqual(self.tracker._completion_pending, {})
        self.assertEqual(self.tracker._native_by_object, {})


if __name__ == "__main__":
    unittest.main()
