"""Fault/recovery sequences: exercise the same client after memory recovers."""
from __future__ import annotations

import src  # noqa: F401

import unittest
from dataclasses import replace
from unittest.mock import patch

from core.stats.types import ItemCooldownSnapshot
from core.tracker.live_run import LiveRunTracker, FAST_ITEM_COOLDOWNS_TTL_SECONDS
from infra.memory.reader import MemoryReadError
from tests.test_item_cooldowns import (
    DICT, ENTRIES, LANTERN_ID, LANTERN_META,
    LANTERN_NAME_PTR, LANTERN_VALUE, MY_TIME_STATICS, OWNER_STATS,
    WRENCH_ID, WRENCH_VALUE, ITEM_COOLDOWN_LAYOUTS, PlayerStatsClient,
    build_memory, client_for, read,
)

C = PlayerStatsClient
ENTRY = ENTRIES + C.DICT_ENTRY_START_OFFSET
KEY = ENTRY + C.DICT_ENTRY_KEY_OFFSET
VALUE = ENTRY + C.DICT_ENTRY_VALUE_OFFSET
VERSION = DICT + C.DICT_VERSION_OFFSET
COOLDOWN = LANTERN_VALUE + ITEM_COOLDOWN_LAYOUTS[LANTERN_ID].cooldown_offset
MARK = LANTERN_VALUE + ITEM_COOLDOWN_LAYOUTS[LANTERN_ID].next_trigger_offset
CLOCK = MY_TIME_STATICS + C.MY_TIME_TIME_OFFSET


class BindingRecoveryTests(unittest.TestCase):
    def test_missing_id_recovers_without_version_change_or_new_client(self):
        memory = build_memory()
        memory.unreadable.add(KEY)
        client = client_for(memory)
        self.assertEqual(read(client).readings, ())
        memory.unreadable.remove(KEY)
        self.assertEqual(len(read(client).readings), 1)
        self.assertEqual(memory.ints[VERSION], 7)

    def test_unknown_id_recovers_without_version_change(self):
        memory = build_memory()
        memory.ints[KEY] = 99999
        client = client_for(memory)
        self.assertEqual(read(client).readings, ())
        memory.ints[KEY] = LANTERN_ID
        self.assertEqual(len(read(client).readings), 1)

    def test_wrong_readable_class_is_not_a_permanent_refusal(self):
        memory = build_memory(lantern_class="ItemSpikyShield")
        client = client_for(memory)
        self.assertEqual(read(client).readings, ())
        memory.strings[LANTERN_NAME_PTR] = "ItemBobLantern"
        self.assertEqual(len(read(client).readings), 1)

    def test_missing_binding_is_not_a_successful_empty_inventory(self):
        memory = build_memory()
        memory.unreadable.add(KEY)
        self.assertFalse(getattr(read(client_for(memory)), "complete", True))

    def test_periodic_revalidation_recovers_a_plausible_wrong_id(self):
        memory = build_memory()
        memory.ints[KEY] = WRENCH_ID
        client = client_for(memory)
        with patch("infra.memory.player_stats_client.time.monotonic", return_value=100.0):
            self.assertEqual(read(client).readings, ())
        memory.ints[KEY] = LANTERN_ID
        with patch("infra.memory.player_stats_client.time.monotonic", return_value=106.0):
            self.assertEqual(len(read(client).readings), 1)

    def test_a_removed_entries_array_cannot_reuse_the_old_layout(self):
        memory = build_memory()
        client = client_for(memory)
        self.assertEqual(len(read(client).readings), 1)
        memory.pointers[DICT + C.DICT_ENTRIES_OFFSET] = 0
        memory.ints[DICT + C.DICT_COUNT_OFFSET] = 0
        self.assertEqual(read(client).readings, ())
        self.assertIsNone(client._cached_item_layout)


    def test_nonempty_dictionary_without_entries_is_rejected(self):
        for warm in (False, True):
            with self.subTest(warm=warm):
                memory = build_memory()
                client = client_for(memory)
                if warm:
                    self.assertEqual(len(read(client).readings), 1)
                memory.pointers[DICT + C.DICT_ENTRIES_OFFSET] = 0
                self.assertEqual(memory.ints[DICT + C.DICT_COUNT_OFFSET], 2)

                with self.assertRaisesRegex(MemoryReadError, "entries.*count"):
                    client._read_passive_item_dictionary(DICT)
                self.assertIsNone(client._cached_item_layout)

                memory.pointers[DICT + C.DICT_ENTRIES_OFFSET] = ENTRIES
                self.assertEqual(len(read(client).readings), 1)
                self.assertEqual(memory.ints[VERSION], 7)

    def test_null_entries_with_unreadable_count_is_not_confirmed_empty(self):
        memory = build_memory()
        client = client_for(memory)
        self.assertEqual(len(read(client).readings), 1)
        memory.pointers[DICT + C.DICT_ENTRIES_OFFSET] = 0
        memory.unreadable.add(DICT + C.DICT_COUNT_OFFSET)

        with self.assertRaises(MemoryReadError):
            read(client)
        self.assertIsNone(client._cached_item_layout)

    def test_empty_fallback_does_not_mask_missing_entries(self):
        memory = build_memory()
        client = client_for(memory)
        self.assertEqual(len(read(client).readings), 1)
        memory.pointers[DICT + C.DICT_ENTRIES_OFFSET] = 0
        memory.pointers[OWNER_STATS + C.PLAYER_INVENTORY_OFFSET] = 0

        with self.assertRaisesRegex(MemoryReadError, "entries.*count"):
            client.get_passive_items(OWNER_STATS)
        self.assertIsNone(client._cached_item_layout)


class CoherentLayoutTests(unittest.TestCase):
    def test_change_during_cold_walk_is_rejected_not_stored_under_new_version(self):
        memory = build_memory()
        memory.ints[KEY] = WRENCH_ID
        memory.pointers[VALUE] = WRENCH_VALUE
        original = memory.read_i32
        stack_reads = 0

        def mutate_after_last_stack_read(address):
            nonlocal stack_reads
            value = original(address)
            if address == WRENCH_VALUE + C.ITEM_STACK_COUNT_OFFSET:
                stack_reads += 1
                if stack_reads == 4:
                    memory.ints[KEY] = LANTERN_ID
                    memory.pointers[VALUE] = LANTERN_VALUE
                    memory.ints[VERSION] += 1
            return value

        memory.read_i32 = mutate_after_last_stack_read
        client = client_for(memory)
        with self.assertRaises(MemoryReadError):
            read(client)
        self.assertIsNone(client._cached_item_layout)
        memory.read_i32 = original
        self.assertEqual(len(read(client).readings), 1)

    def test_unreadable_initial_version_never_becomes_a_trusted_layout(self):
        memory = build_memory()
        original = memory.read_i32
        calls = 0

        def fail_first_version(address):
            nonlocal calls
            if address == VERSION:
                calls += 1
                if calls == 1:
                    raise MemoryReadError("initial version unavailable")
            return original(address)

        memory.read_i32 = fail_first_version
        client = client_for(memory)
        result = read(client)
        self.assertFalse(getattr(result, "complete", True))
        self.assertIsNone(client._cached_item_layout)
        self.assertEqual(len(read(client).readings), 1)

    def test_entries_replacement_during_walk_is_rejected(self):
        memory = build_memory()
        original = memory.read_i32
        changed = False

        def replace_entries(address):
            nonlocal changed
            value = original(address)
            if address == WRENCH_VALUE + C.ITEM_STACK_COUNT_OFFSET and not changed:
                changed = True
                memory.pointers[DICT + C.DICT_ENTRIES_OFFSET] = 0x51000000
            return value

        memory.read_i32 = replace_entries
        client = client_for(memory)
        with self.assertRaises(MemoryReadError):
            read(client)
        self.assertIsNone(client._cached_item_layout)


class FieldRecoveryTests(unittest.TestCase):
    def _move_lantern_without_header_change(self, memory):
        target = 0x52000000
        memory.pointers[VALUE] = target
        memory.pointers[target + C.ITEM_CLASS_META_OFFSET] = LANTERN_META
        memory.ints[target + C.ITEM_STACK_COUNT_OFFSET] = 1
        layout = ITEM_COOLDOWN_LAYOUTS[LANTERN_ID]
        memory.floats[target + layout.cooldown_offset] = 42.0
        memory.floats[target + layout.next_trigger_offset] = 140.0
        return target

    def test_invalid_cached_float_forces_address_rediscovery(self):
        memory = build_memory(my_time=100.0, next_trigger=130.0)
        client = client_for(memory)
        self.assertEqual(len(read(client).readings), 1)
        self._move_lantern_without_header_change(memory)
        memory.floats[COOLDOWN] = 0.0
        failed = read(client)
        self.assertFalse(getattr(failed, "complete", True))
        self.assertEqual(read(client).readings[0].next_trigger_time, 140.0)

    def test_unreadable_cached_float_forces_address_rediscovery(self):
        memory = build_memory(my_time=100.0, next_trigger=130.0)
        client = client_for(memory)
        read(client)
        self._move_lantern_without_header_change(memory)
        memory.unreadable.add(COOLDOWN)
        self.assertEqual(read(client).readings, ())
        self.assertEqual(len(read(client).readings), 1)

    def test_periodic_revalidation_rebinds_readable_but_obsolete_object(self):
        memory = build_memory(my_time=100.0, next_trigger=130.0)
        client = client_for(memory)
        with patch("infra.memory.player_stats_client.time.monotonic", return_value=100.0):
            self.assertEqual(read(client).readings[0].next_trigger_time, 130.0)
        self._move_lantern_without_header_change(memory)
        with patch("infra.memory.player_stats_client.time.monotonic", return_value=106.0):
            self.assertEqual(read(client).readings[0].next_trigger_time, 140.0)

    def test_invalid_numbers_are_incomplete_and_recover(self):
        cases = [(COOLDOWN, float("nan")), (COOLDOWN, float("inf")),
                 (COOLDOWN, -1.0), (COOLDOWN, 1e12),
                 (MARK, float("nan")), (MARK, float("inf")),
                 (MARK, -1.0), (MARK, 1e12)]
        for address, bad_value in cases:
            with self.subTest(address=address, bad_value=bad_value):
                memory = build_memory(my_time=100.0, next_trigger=130.0)
                client = client_for(memory)
                original = memory.floats[address]
                memory.floats[address] = bad_value
                result = read(client)
                self.assertEqual(result.readings, ())
                self.assertFalse(getattr(result, "complete", True))
                memory.floats[address] = original
                self.assertEqual(len(read(client).readings), 1)

    def test_invalid_clock_is_rejected_and_its_cache_is_dropped(self):
        for clock in (float("nan"), float("inf"), -1.0):
            with self.subTest(clock=clock):
                memory = build_memory(my_time=clock)
                client = client_for(memory)
                client._cached_my_time_static_fields = MY_TIME_STATICS
                with self.assertRaises(MemoryReadError):
                    read(client)
                self.assertEqual(client._cached_my_time_static_fields, 0)
                memory.floats[CLOCK] = 0.0
                self.assertEqual(len(read(client).readings), 1)

    def test_unreadable_clock_also_drops_its_cached_address(self):
        memory = build_memory()
        memory.unreadable.add(CLOCK)
        client = client_for(memory)
        client._cached_my_time_static_fields = MY_TIME_STATICS
        with self.assertRaises(MemoryReadError):
            read(client)
        self.assertEqual(client._cached_my_time_static_fields, 0)

    def test_pause_and_old_trigger_are_not_rejected_as_a_stuck_clock(self):
        memory = build_memory(my_time=100.0, next_trigger=99.99)
        client = client_for(memory)
        for now in (100.0, 101.0, 107.0, 150.0):
            with patch("infra.memory.player_stats_client.time.monotonic", return_value=now):
                result = read(client)
                self.assertEqual(len(result.readings), 1)
                self.assertTrue(getattr(result, "complete", True))


class CooldownPublishRecoveryTests(unittest.TestCase):
    def test_failed_pass_does_not_extend_last_good_ttl(self):
        now = [100.0]
        tracker = LiveRunTracker(clock=lambda: now[0])
        good = read(client_for(build_memory()))
        tracker.update_item_cooldowns(good)
        now[0] += 1.0
        tracker.update_item_cooldowns(None)
        self.assertIs(tracker.item_cooldowns(), good)
        now[0] = 100.0 + FAST_ITEM_COOLDOWNS_TTL_SECONDS + 0.01
        tracker.update_item_cooldowns(None)
        self.assertIsNone(tracker.item_cooldowns())

    def test_incomplete_read_does_not_replace_good_values_or_extend_ttl(self):
        now = [100.0]
        tracker = LiveRunTracker(clock=lambda: now[0])
        good = read(client_for(build_memory()))
        tracker.update_item_cooldowns(good)
        incomplete = replace(good, readings=(), complete=False)
        for i in range(1, 5):
            now[0] = 100.0 + i
            tracker.update_item_cooldowns(incomplete)
        self.assertIsNone(tracker.item_cooldowns())
        tracker.update_item_cooldowns(good)
        self.assertIs(tracker.item_cooldowns(), good)

    def test_confirmed_empty_inventory_hides_immediately(self):
        tracker = LiveRunTracker()
        tracker.update_item_cooldowns(read(client_for(build_memory())))
        empty = ItemCooldownSnapshot(my_time_seconds=100.0)
        tracker.update_item_cooldowns(empty)
        self.assertEqual(tracker.item_cooldowns().readings, ())

    def test_cooldown_alone_demands_fast_reads_but_not_full_stats(self):
        from app import config
        from tests.support.refresh_tasks import build_refresh_tasks
        service, world = build_refresh_tasks()
        cfg = {"enabled": True, "widgets": {"item_cooldowns": {"enabled": True}}}
        with patch.object(config, "IN_GAME_OVERLAY", cfg):
            self.assertFalse(service._should_refresh_full_player_snapshot())
            self.assertTrue(service._should_refresh_passive_items())
            world.lifecycle.completed_run = True
            self.assertFalse(service._should_refresh_passive_items())

    def test_disabled_overlay_does_not_add_read_demand(self):
        from app import config
        from tests.support.refresh_tasks import build_refresh_tasks
        service, _ = build_refresh_tasks()
        cfg = {"enabled": False, "widgets": {"item_cooldowns": {"enabled": True}}}
        with patch.object(config, "IN_GAME_OVERLAY", cfg):
            self.assertFalse(service._should_refresh_passive_items())


class CooldownDiagnosticsTests(unittest.TestCase):
    def test_failure_and_recovery_are_logged_without_per_tick_spam(self):
        memory = build_memory()
        client = client_for(memory)
        memory.unreadable.add(COOLDOWN)
        now = [100.0]
        with patch("infra.memory.player_stats_client.time.monotonic", side_effect=lambda: now[0]), patch(
            "infra.memory.player_stats_client.log_runtime_event"
        ) as log:
            for _ in range(20):
                read(client)
                now[0] += 0.05
            self.assertEqual(log.call_count, 1)
            self.assertEqual(log.call_args.kwargs["reason"], "fields_unreadable")
            memory.unreadable.remove(COOLDOWN)
            read(client)
            self.assertEqual(log.call_count, 1)
            now[0] = 106.0
            read(client)
            self.assertEqual(log.call_count, 2)
            self.assertEqual(log.call_args.kwargs["reason"], "ok")
            for _ in range(20):
                read(client)
            self.assertEqual(log.call_count, 2)

    def test_normal_play_does_not_write_cooldown_logs(self):
        client = client_for(build_memory())
        with patch("infra.memory.player_stats_client.log_runtime_event") as log:
            for _ in range(10):
                read(client)
            log.assert_not_called()


class CooldownEndToEndTests(unittest.TestCase):
    def test_memory_failure_and_recovery_reach_the_real_publisher_and_renderer(self):
        from app.refresh_coordinator import RefreshTickContext
        from projections.in_game import project_in_game_overlay
        from projections.in_game_html import build_item_cooldowns_overlay_html
        from tests.support.refresh_tasks import build_refresh_tasks

        now = [100.0]
        memory = build_memory(my_time=100.0, next_trigger=130.0)
        client = client_for(memory)
        client.resolve_owner_stats = lambda: OWNER_STATS
        tracker = LiveRunTracker(clock=lambda: now[0])
        service, world = build_refresh_tasks(stats_client=client, tracker=tracker)

        def publish(pass_id):
            service._publish_item_cooldowns(
                RefreshTickContext(pass_id=pass_id, started_at=now[0], clock=lambda: now[0])
            )
            return build_item_cooldowns_overlay_html(
                project_in_game_overlay(tracker.runtime_snapshot())
            )

        publish(1)
        self.assertEqual(len(tracker.item_cooldowns().readings), 1)
        client._clear_passive_item_layout()
        memory.unreadable.add(KEY)
        now[0] += 1.0
        self.assertIn("30s", publish(2))
        now[0] += 3.0
        self.assertEqual(publish(3), "")
        memory.unreadable.remove(KEY)
        self.assertIn("30s", publish(4))
        self.assertIs(world.stats_client, client)
        self.assertEqual(world.memory._player_stats_memory_error_streak, 0)

    def test_null_entries_preserve_grace_expire_and_recover_without_restart(self):
        from app.refresh_coordinator import RefreshTickContext
        from projections.in_game import project_in_game_overlay
        from projections.in_game_html import build_item_cooldowns_overlay_html
        from tests.support.refresh_tasks import build_refresh_tasks

        now = [100.0]
        memory = build_memory(my_time=100.0, next_trigger=130.0)
        client = client_for(memory)
        client.resolve_owner_stats = lambda: OWNER_STATS
        tracker = LiveRunTracker(clock=lambda: now[0])
        service, world = build_refresh_tasks(stats_client=client, tracker=tracker)
        pass_id = 0

        def publish():
            nonlocal pass_id
            pass_id += 1
            service._publish_item_cooldowns(
                RefreshTickContext(pass_id=pass_id, started_at=now[0], clock=lambda: now[0])
            )
            return build_item_cooldowns_overlay_html(
                project_in_game_overlay(tracker.runtime_snapshot())
            )

        self.assertIn("30s", publish())
        good = tracker.item_cooldowns()
        captured_at = tracker._fast_item_cooldowns.captured_at
        memory.pointers[DICT + C.DICT_ENTRIES_OFFSET] = 0
        self.assertEqual(memory.ints[DICT + C.DICT_COUNT_OFFSET], 2)

        # Exercise the actual reader -> publisher -> tracker -> HTML path,
        # not a hand-built incomplete sample. Repeated failures cannot renew TTL.
        for elapsed in (0.1, 1.0, FAST_ITEM_COOLDOWNS_TTL_SECONDS - 0.01):
            now[0] = 100.0 + elapsed
            self.assertIn("30s", publish())
            self.assertIs(tracker.item_cooldowns(), good)
            self.assertEqual(tracker._fast_item_cooldowns.captured_at, captured_at)
            self.assertIsNone(client._cached_item_layout)

        now[0] = 100.0 + FAST_ITEM_COOLDOWNS_TTL_SECONDS + 0.01
        self.assertEqual(publish(), "")
        self.assertIsNone(tracker.item_cooldowns())
        self.assertEqual(tracker._fast_item_cooldowns.captured_at, captured_at)

        # Restore only the pointer and advance the game clock. No new client,
        # dictionary version bump, or manual cache reset is allowed.
        memory.pointers[DICT + C.DICT_ENTRIES_OFFSET] = ENTRIES
        memory.floats[CLOCK] = 104.0
        now[0] = 104.0
        self.assertIn("26s", publish())
        self.assertTrue(tracker.item_cooldowns().complete)
        self.assertEqual(memory.ints[VERSION], 7)
        self.assertIs(world.stats_client, client)
        self.assertEqual(world.memory._player_stats_memory_error_streak, 0)

        # A genuinely empty dictionary must still hide the widget immediately,
        # even though the recovered value is only 0.1 seconds old.
        memory.pointers[DICT + C.DICT_ENTRIES_OFFSET] = 0
        memory.ints[DICT + C.DICT_COUNT_OFFSET] = 0
        now[0] += 0.1
        self.assertEqual(publish(), "")
        empty = tracker.item_cooldowns()
        self.assertIsNotNone(empty)
        self.assertTrue(empty.complete)
        self.assertEqual(empty.readings, ())

    def test_genuine_item_loss_stays_hidden_after_subsequent_failed_samples(self):
        tracker = LiveRunTracker()
        tracker.update_item_cooldowns(read(client_for(build_memory())))
        tracker.update_item_cooldowns(ItemCooldownSnapshot(my_time_seconds=100.0))
        tracker.update_item_cooldowns(None)
        self.assertEqual(tracker.item_cooldowns().readings, ())

    def test_reset_during_failure_cannot_restore_the_previous_run(self):
        tracker = LiveRunTracker()
        tracker.update_item_cooldowns(read(client_for(build_memory())))
        tracker._reset_for_new_run()
        tracker.update_item_cooldowns(None)
        self.assertIsNone(tracker.item_cooldowns())


if __name__ == "__main__":
    unittest.main()
