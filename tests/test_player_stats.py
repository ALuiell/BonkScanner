from __future__ import annotations

import unittest

from memory import MemoryReadError
from player_stats import (
    PlayerStatsClient,
    PlayerStatFormat,
    PlayerStatsTimeline,
    WeaponStatFormat,
    calculate_chests_per_minute,
    format_player_stat_value,
    format_weapon_stat_value,
)


class FakeMemory:
    def __init__(
        self,
        *,
        module_base: int = 0x10000000,
        pointers: dict[int, int] | None = None,
        floats: dict[int, float] | None = None,
        ints: dict[int, int] | None = None,
        ascii_strings: dict[int, str] | None = None,
        mono_strings: dict[int, str] | None = None,
    ) -> None:
        self.module_base = module_base
        self.pointers = pointers or {}
        self.floats = floats or {}
        self.ints = ints or {}
        self.ascii_strings = ascii_strings or {}
        self.mono_strings = mono_strings or {}

    def module_offset(self, _module_name: str, offset: int) -> int:
        return self.module_base + offset

    def read_ptr(self, address: int) -> int:
        if address not in self.pointers:
            raise MemoryReadError(f"missing ptr at 0x{address:X}")
        return self.pointers[address]

    def read_float(self, address: int) -> float:
        if address not in self.floats:
            raise MemoryReadError(f"missing float at 0x{address:X}")
        return self.floats[address]

    def read_i32(self, address: int) -> int:
        if address not in self.ints:
            raise MemoryReadError(f"missing int at 0x{address:X}")
        return self.ints[address]

    def read_ascii_string(self, address: int, max_length: int = 128) -> str | None:
        _ = max_length
        if address not in self.ascii_strings:
            raise MemoryReadError(f"missing ascii string at 0x{address:X}")
        return self.ascii_strings[address]

    def read_mono_string(self, address: int, max_length: int = 512) -> str | None:
        _ = max_length
        if address not in self.mono_strings:
            raise MemoryReadError(f"missing mono string at 0x{address:X}")
        return self.mono_strings[address]


def build_player_stats_memory() -> FakeMemory:
    base = 0x10000000
    type_info = base + PlayerStatsClient.TYPE_INFO_OFFSET
    class_ptr = 0x20000000
    static_fields = 0x20000100
    root = 0x20000200
    owner_stats = 0x20000300
    stats_context = 0x20000400
    entries = 0x20000500

    pointers = {
        type_info: class_ptr,
        class_ptr + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: static_fields,
        static_fields + PlayerStatsClient.STATIC_ROOT_OFFSET: root,
        root + PlayerStatsClient.OWNER_STATS_OFFSET: owner_stats,
        owner_stats + PlayerStatsClient.STATS_CONTEXT_OFFSET: stats_context,
        stats_context + PlayerStatsClient.STATS_ENTRIES_OFFSET: entries,
    }
    run_timer_type_info = base + PlayerStatsClient.RUN_TIMER_TYPE_INFO_OFFSET
    run_timer_class_ptr = 0x20000C00
    run_timer_static_fields = 0x20000D00
    run_stats_type_info = base + PlayerStatsClient.RUN_STATS_TYPE_INFO_OFFSET
    run_stats_class_ptr = 0x20000E00
    run_stats_static_fields = 0x20000F00
    run_stats_dict = 0x20001000
    run_stats_entries = 0x20001100
    kills_key = 0x20001200
    player_inventory = 0x20001600
    player_xp = 0x20001700
    pointers.update(
        {
            run_timer_type_info: run_timer_class_ptr,
            run_timer_class_ptr + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: run_timer_static_fields,
            run_stats_type_info: run_stats_class_ptr,
            run_stats_class_ptr + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: run_stats_static_fields,
            run_stats_static_fields + PlayerStatsClient.RUN_STATS_DICT_OFFSET: run_stats_dict,
            run_stats_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: run_stats_entries,
            run_stats_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: kills_key,
            owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
            player_inventory + PlayerStatsClient.PLAYER_XP_OFFSET: player_xp,
        }
    )
    floats = {
        run_timer_static_fields + PlayerStatsClient.STAGE_TIMER_OFFSET: 9.75,
        entries + 0x2C: 198.0,
        entries + 0x6C: 0.15,
        entries + 0x28C: 0.09,
        run_timer_static_fields + PlayerStatsClient.RUN_TIMER_OFFSET: 21.52338219,
        run_stats_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.RUN_STATS_ENTRY_VALUE_OFFSET: 37.0,
    }
    inventory_container = 0x20000600
    passive_dict = 0x20000700
    passive_entries = 0x20000800
    item_value = 0x20000900
    class_meta = 0x20000A00
    class_name_ptr = 0x20000B00

    pointers.update(
        {
            owner_stats + PlayerStatsClient.INVENTORY_CONTAINER_OFFSET: inventory_container,
            inventory_container + PlayerStatsClient.PASSIVE_ITEM_DICT_OFFSET: passive_dict,
            passive_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: passive_entries,
            passive_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: item_value,
            item_value + PlayerStatsClient.ITEM_CLASS_META_OFFSET: class_meta,
            class_meta + PlayerStatsClient.CLASS_META_NAME_PTR_OFFSET: class_name_ptr,
        }
    )
    ints = {
        passive_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
        item_value + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET: 2,
        run_stats_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
        run_stats_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
        player_xp + PlayerStatsClient.PLAYER_XP_LEVEL_OFFSET: 2,
    }
    ascii_strings = {
        class_name_ptr: "ItemWrench",
    }
    mono_strings = {
        kills_key: "kills",
    }
    return FakeMemory(
        module_base=base,
        pointers=pointers,
        floats=floats,
        ints=ints,
        ascii_strings=ascii_strings,
        mono_strings=mono_strings,
    )


class PlayerStatsClientTests(unittest.TestCase):
    def build_memory(self) -> FakeMemory:
        return build_player_stats_memory()

    def test_get_player_stats_reads_confirmed_offsets(self) -> None:
        client = PlayerStatsClient(memory=self.build_memory())

        stats = client.get_player_stats()

        self.assertEqual(stats["Max HP"].display_value, "198")
        self.assertEqual(stats["Armor"].display_value, "15%")
        self.assertEqual(stats["Difficulty"].display_value, "9%")

    def test_get_passive_items_reads_item_names_and_counts(self) -> None:
        client = PlayerStatsClient(memory=self.build_memory())

        items = client.get_passive_items()

        self.assertEqual(items, ("Wrench x2",))

    def test_format_item_name_replaces_no_implementation_with_golden_ring(self) -> None:
        self.assertEqual(PlayerStatsClient._format_item_name("ItemNoImplementation"), "Golden Ring")

    def test_get_run_timer_reads_confirmed_static_float(self) -> None:
        client = PlayerStatsClient(memory=self.build_memory())

        value = client.get_run_timer()

        self.assertAlmostEqual(value, 21.52338219)

    def test_get_stage_timer_reads_confirmed_static_float(self) -> None:
        client = PlayerStatsClient(memory=self.build_memory())

        value = client.get_stage_timer()

        self.assertAlmostEqual(value, 9.75)

    def test_get_killed_mobs_reads_run_stats_kills(self) -> None:
        client = PlayerStatsClient(memory=self.build_memory())

        value = client.get_killed_mobs()

        self.assertEqual(value, 37)

    def test_get_player_level_reads_live_player_xp_level(self) -> None:
        client = PlayerStatsClient(memory=self.build_memory())

        value = client.get_player_level()

        self.assertEqual(value, 2)

    def test_get_killed_mobs_raises_when_entries_are_unavailable(self) -> None:
        memory = self.build_memory()
        run_stats_dict = 0x20001000
        del memory.pointers[run_stats_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET]
        client = PlayerStatsClient(memory=memory)

        with self.assertRaises(MemoryReadError):
            client.get_killed_mobs()

    def test_get_killed_mobs_raises_when_kills_entry_is_missing(self) -> None:
        memory = self.build_memory()
        run_stats_entries = 0x20001100
        del memory.mono_strings[0x20001200]
        memory.ints[
            run_stats_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET
        ] = 1
        client = PlayerStatsClient(memory=memory)

        with self.assertRaises(MemoryReadError):
            client.get_killed_mobs()

    def test_get_passive_items_uses_default_stack_when_count_is_unreadable(self) -> None:
        memory = self.build_memory()
        item_value = 0x20000900
        del memory.ints[item_value + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET]
        client = PlayerStatsClient(memory=memory)

        items = client.get_passive_items()

        self.assertEqual(items, ("Wrench x1",))

    def test_get_passive_items_raises_for_invalid_dictionary_count(self) -> None:
        memory = self.build_memory()
        passive_dict = 0x20000700
        memory.ints[passive_dict + PlayerStatsClient.DICT_COUNT_OFFSET] = (
            PlayerStatsClient.MAX_PASSIVE_ITEM_DICT_ENTRIES + 1
        )
        client = PlayerStatsClient(memory=memory)

        with self.assertRaises(MemoryReadError):
            client.get_passive_items()

    def test_get_passive_items_skips_broken_entries_and_keeps_valid_ones(self) -> None:
        memory = self.build_memory()
        passive_dict = 0x20000700
        passive_entries = 0x20000800
        second_item_value = 0x20000C00
        memory.ints[passive_dict + PlayerStatsClient.DICT_COUNT_OFFSET] = 2
        memory.pointers[
            passive_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.DICT_ENTRY_SIZE
            + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET
        ] = second_item_value

        client = PlayerStatsClient(memory=memory)

        items = client.get_passive_items()

        self.assertEqual(items, ("Wrench x2",))

    def test_get_passive_items_raises_when_positive_count_has_no_decodable_entries(self) -> None:
        memory = self.build_memory()
        item_value = 0x20000900
        del memory.pointers[item_value + PlayerStatsClient.ITEM_CLASS_META_OFFSET]
        client = PlayerStatsClient(memory=memory)

        with self.assertRaises(MemoryReadError):
            client.get_passive_items()

    def test_format_player_stat_values_match_game_display_style(self) -> None:
        self.assertEqual(format_player_stat_value(0.15, PlayerStatFormat.PERCENT), "15%")
        self.assertEqual(format_player_stat_value(1.25, PlayerStatFormat.MULTIPLIER), "1.25x")
        self.assertEqual(format_player_stat_value(10.0, PlayerStatFormat.FLAT), "10")
        self.assertEqual(format_player_stat_value(None, PlayerStatFormat.FLAT), "--")

    def test_format_weapon_stat_values_follow_weapon_ui_rules(self) -> None:
        self.assertEqual(format_weapon_stat_value(10.0, WeaponStatFormat.FLAT), "10")
        self.assertEqual(format_weapon_stat_value(2.0, WeaponStatFormat.FLAT), "2")
        self.assertEqual(format_weapon_stat_value(1.16, WeaponStatFormat.MULTIPLIER), "1.16x")
        self.assertEqual(format_weapon_stat_value(0.6, WeaponStatFormat.MULTIPLIER), "0.6x")
        self.assertEqual(format_weapon_stat_value(0.34, WeaponStatFormat.PERCENT), "34%")

    def test_calculate_chests_per_minute_matches_expected_formula(self) -> None:
        value = calculate_chests_per_minute(15.0, 2.0)

        self.assertAlmostEqual(value, 1.5424457965)

    def test_calculate_chests_per_minute_returns_zero_for_non_positive_inputs(self) -> None:
        self.assertEqual(calculate_chests_per_minute(0.0, 2.0), 0.0)
        self.assertEqual(calculate_chests_per_minute(15.0, 0.0), 0.0)

    def test_calculate_chests_per_minute_caps_elite_chance_at_one(self) -> None:
        capped = calculate_chests_per_minute(1_000.0, 1.0)
        expected = calculate_chests_per_minute(1.0 / 0.006, 1.0)

        self.assertAlmostEqual(capped, expected)


class PlayerStatsTimelineTests(unittest.TestCase):
    def test_timeline_captures_immediately_and_then_on_interval(self) -> None:
        now = 1000.0
        timeline = PlayerStatsTimeline(interval_seconds=60, clock=lambda: now)
        stats = PlayerStatsClient(memory=build_player_stats_memory()).get_player_stats()

        timeline.start()

        self.assertTrue(timeline.should_capture())
        first = timeline.capture(stats)
        self.assertEqual(first.time_label, "00:00")
        self.assertFalse(timeline.should_capture())

        now += 59
        self.assertFalse(timeline.should_capture())

        now += 1
        self.assertTrue(timeline.should_capture())
        second = timeline.capture(stats, ("Wrench x2",))
        self.assertEqual(second.time_label, "01:00")
        self.assertEqual(second.items, ("Wrench x2",))

    def test_get_live_weapons_filters_stats_by_upgrade_pool(self) -> None:
        memory = build_player_stats_memory()
        owner_stats = 0x20000300
        player_inventory = 0x21000000
        weapon_inventory = 0x21000100
        weapons_dict = 0x21000200
        weapon_entries = 0x21000300
        weapon_base = 0x21000400
        weapon_data = 0x21000500
        weapon_stats_dict = 0x21000600
        weapon_stat_entries = 0x21000700
        upgrade_data = 0x21000800
        upgrade_modifiers = 0x21000900
        upgrade_items = 0x21000A00
        damage_modifier = 0x21000B00
        speed_modifier = 0x21000C00

        memory.pointers.update(
            {
                owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
                player_inventory + PlayerStatsClient.WEAPON_INVENTORY_OFFSET: weapon_inventory,
                weapon_inventory + PlayerStatsClient.WEAPONS_DICT_OFFSET: weapons_dict,
                weapons_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: weapon_entries,
                weapon_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.WEAPON_DICT_ENTRY_VALUE_OFFSET: weapon_base,
                weapon_base + PlayerStatsClient.WEAPON_DATA_OFFSET: weapon_data,
                weapon_base + PlayerStatsClient.WEAPON_STATS_DICT_OFFSET: weapon_stats_dict,
                weapon_stats_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: weapon_stat_entries,
                weapon_data + PlayerStatsClient.WEAPON_UPGRADE_DATA_OFFSET: upgrade_data,
                upgrade_data + PlayerStatsClient.UPGRADE_MODIFIERS_OFFSET: upgrade_modifiers,
                upgrade_modifiers + PlayerStatsClient.LIST_ITEMS_OFFSET: upgrade_items,
                upgrade_items + PlayerStatsClient.ARRAY_DATA_OFFSET: damage_modifier,
                upgrade_items + PlayerStatsClient.ARRAY_DATA_OFFSET + PlayerStatsClient.OBJECT_POINTER_SIZE: speed_modifier,
            }
        )
        memory.ints.update(
            {
                weapons_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                weapon_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                weapon_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.WEAPON_DICT_ENTRY_KEY_OFFSET: 0,
                weapon_base + PlayerStatsClient.WEAPON_LEVEL_OFFSET: 3,
                weapon_data + PlayerStatsClient.WEAPON_ID_OFFSET: 0,
                weapon_stats_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 3,
                weapon_stat_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                weapon_stat_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET: 12,
                weapon_stat_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_SIZE + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                weapon_stat_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_SIZE + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET: 16,
                weapon_stat_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + (2 * PlayerStatsClient.STAT_DICT_ENTRY_SIZE) + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                weapon_stat_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + (2 * PlayerStatsClient.STAT_DICT_ENTRY_SIZE) + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET: 11,
                upgrade_modifiers + PlayerStatsClient.LIST_SIZE_OFFSET: 2,
                damage_modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 12,
                speed_modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 11,
            }
        )
        memory.floats.update(
            {
                weapon_stat_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET: 10.0,
                weapon_stat_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_SIZE + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET: 2.0,
                weapon_stat_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + (2 * PlayerStatsClient.STAT_DICT_ENTRY_SIZE) + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET: 0.6,
            }
        )

        client = PlayerStatsClient(memory=memory)

        weapons = client.get_live_weapons()

        self.assertEqual(len(weapons), 1)
        self.assertEqual(weapons[0].name, "Fire Staff")
        self.assertEqual(weapons[0].level, 3)
        self.assertEqual(weapons[0].upgrade_stat_ids, (12, 11))
        self.assertEqual(tuple(weapons[0].upgraded_stats), (12, 11))
        self.assertEqual(weapons[0].upgraded_stats[12].display_value, "10")
        self.assertEqual(weapons[0].upgraded_stats[11].display_value, "0.6x")
        self.assertIn(16, weapons[0].full_stats)

    def test_timeline_elapsed_label_tracks_recording_time(self) -> None:
        now = 1000.0
        timeline = PlayerStatsTimeline(interval_seconds=60, clock=lambda: now)

        self.assertEqual(timeline.elapsed_label(), "00:00")

        timeline.start()
        now += 75

        self.assertEqual(timeline.elapsed_seconds(), 75)
        self.assertEqual(timeline.elapsed_label(), "01:15")

    def test_timeline_clamps_snapshot_selection(self) -> None:
        now = 1000.0
        timeline = PlayerStatsTimeline(interval_seconds=60, clock=lambda: now)
        stats = PlayerStatsClient(memory=build_player_stats_memory()).get_player_stats()

        timeline.start()
        first = timeline.capture(stats)

        self.assertIs(timeline.get_snapshot(-100), first)
        self.assertIs(timeline.get_snapshot(100), first)


if __name__ == "__main__":
    unittest.main()
