from __future__ import annotations

import unittest

from memory import MemoryReadError
from player_stats import (
    DisabledItemsReadStatus,
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
    money_utility_type_info = base + PlayerStatsClient.MONEY_UTILITY_TYPE_INFO_OFFSET
    money_utility_class_ptr = 0x20001300
    money_utility_static_fields = 0x20001400
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
            money_utility_type_info: money_utility_class_ptr,
            money_utility_class_ptr + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: money_utility_static_fields,
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
        passive_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
        item_value + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET: 2,
        run_stats_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
        run_stats_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
        run_stats_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
        player_xp + PlayerStatsClient.PLAYER_XP_LEVEL_OFFSET: 2,
        money_utility_static_fields + PlayerStatsClient.MONEY_UTILITY_CHESTS_PURCHASED_OFFSET: 12,
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


def build_disabled_items_memory(
    *,
    global_ids: tuple[int, ...],
    available_groups: tuple[tuple[int, ...] | None, ...],
    banished_ids: tuple[int, ...] = (),
) -> FakeMemory:
    base = 0x10000000
    data_type_info = base + PlayerStatsClient.DATA_MANAGER_TYPE_INFO_OFFSET
    data_class = 0x30000000
    data_static = 0x30000100
    data_instance = 0x30000200
    global_list = 0x30000300
    global_array = 0x30000400
    run_type_info = base + PlayerStatsClient.RUN_UNLOCKABLES_TYPE_INFO_OFFSET
    run_class = 0x30000500
    run_static = 0x30000600
    available_dict = 0x30000700
    available_entries = 0x30000800
    banished_set = 0x30000900
    banished_slots = 0x30000A00

    pointers = {
        data_type_info: data_class,
        data_class + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: data_static,
        data_static + 0x8: data_instance,
        data_instance + 0x60: global_list,
        global_list + PlayerStatsClient.LIST_ITEMS_OFFSET: global_array,
        run_type_info: run_class,
        run_class + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: run_static,
        run_static + 0x10: available_dict,
        available_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: available_entries,
        run_static + PlayerStatsClient.RUN_UNLOCKABLES_BANISHED_ITEMS_OFFSET: banished_set,
        banished_set + PlayerStatsClient.HASHSET_SLOTS_OFFSET: banished_slots,
    }
    ints = {
        global_list + PlayerStatsClient.LIST_SIZE_OFFSET: len(global_ids),
        available_dict + PlayerStatsClient.DICT_COUNT_OFFSET: sum(group is not None for group in available_groups),
        available_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET: len(available_groups),
        banished_set + PlayerStatsClient.HASHSET_COUNT_OFFSET: len(banished_ids),
        banished_set + PlayerStatsClient.HASHSET_LAST_INDEX_OFFSET: len(banished_ids),
    }

    for index, item_id in enumerate(global_ids):
        item_ptr = 0x31000000 + index * 0x100
        pointers[global_array + PlayerStatsClient.ARRAY_DATA_OFFSET + index * PlayerStatsClient.OBJECT_POINTER_SIZE] = item_ptr
        ints[item_ptr + PlayerStatsClient.ITEM_DATA_ENUM_OFFSET] = item_id

    for index, group in enumerate(available_groups):
        entry = available_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + index * PlayerStatsClient.DICT_ENTRY_SIZE
        if group is None:
            ints[entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET] = -1
            continue
        item_list = 0x32000000 + index * 0x1000
        item_array = item_list + 0x400
        ints[entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET] = index + 1
        pointers[entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET] = item_list
        pointers[item_list + PlayerStatsClient.LIST_ITEMS_OFFSET] = item_array
        ints[item_list + PlayerStatsClient.LIST_SIZE_OFFSET] = len(group)
        for item_index, item_id in enumerate(group):
            item_ptr = 0x33000000 + index * 0x1000 + item_index * 0x100
            pointers[item_array + PlayerStatsClient.ARRAY_DATA_OFFSET + item_index * PlayerStatsClient.OBJECT_POINTER_SIZE] = item_ptr
            ints[item_ptr + PlayerStatsClient.ITEM_DATA_ENUM_OFFSET] = item_id

    for index, item_id in enumerate(banished_ids):
        slot = banished_slots + PlayerStatsClient.HASHSET_SLOT_START_OFFSET + index * PlayerStatsClient.HASHSET_SLOT_SIZE
        item_ptr = 0x34000000 + index * 0x100
        ints[slot + PlayerStatsClient.HASHSET_SLOT_HASH_CODE_OFFSET] = index + 1
        pointers[slot + PlayerStatsClient.HASHSET_SLOT_VALUE_OFFSET] = item_ptr
        ints[item_ptr + PlayerStatsClient.ITEM_DATA_ENUM_OFFSET] = item_id

    return FakeMemory(module_base=base, pointers=pointers, ints=ints)


class PlayerStatsClientTests(unittest.TestCase):
    def build_memory(self) -> FakeMemory:
        return build_player_stats_memory()

    def test_get_player_stats_reads_confirmed_offsets(self) -> None:
        client = PlayerStatsClient(memory=self.build_memory())

        stats = client.get_player_stats()

        self.assertEqual(stats["Max HP"].display_value, "198")
        self.assertEqual(stats["Armor"].display_value, "15%")
        self.assertEqual(stats["Difficulty"].display_value, "9%")

    def test_get_disabled_items_reports_uninitialized_empty_pool(self) -> None:
        memory = build_disabled_items_memory(global_ids=(4, 7), available_groups=())

        result = PlayerStatsClient(memory=memory).get_disabled_items()

        self.assertEqual(result.status, DisabledItemsReadStatus.NOT_INITIALIZED)
        self.assertEqual(result.items, ())

    def test_get_disabled_items_reports_memory_read_error(self) -> None:
        memory = build_disabled_items_memory(global_ids=(4, 7), available_groups=((4,),))
        del memory.pointers[
            memory.module_base + PlayerStatsClient.DATA_MANAGER_TYPE_INFO_OFFSET
        ]

        result = PlayerStatsClient(memory=memory).get_disabled_items()

        self.assertEqual(result.status, DisabledItemsReadStatus.READ_ERROR)
        self.assertEqual(result.items, ())

    def test_get_disabled_items_allows_successful_empty_result(self) -> None:
        memory = build_disabled_items_memory(global_ids=(4, 7), available_groups=((4, 7),))

        result = PlayerStatsClient(memory=memory).get_disabled_items()

        self.assertTrue(result.available)
        self.assertEqual(result.items, ())

    def test_get_disabled_items_restores_banished_items_to_active_pool(self) -> None:
        memory = build_disabled_items_memory(
            global_ids=(4, 7, 35),
            available_groups=((35,),),
            banished_ids=(4,),
        )

        result = PlayerStatsClient(memory=memory).get_disabled_items()

        self.assertTrue(result.available)
        self.assertEqual(result.items, ("Battery",))

    def test_get_disabled_items_reads_entries_after_dictionary_holes(self) -> None:
        memory = build_disabled_items_memory(
            global_ids=(4, 7),
            available_groups=((4,), None, (7,)),
        )

        result = PlayerStatsClient(memory=memory).get_disabled_items()

        self.assertTrue(result.available)
        self.assertEqual(result.items, ())

    def test_get_passive_items_reads_item_names_and_counts(self) -> None:
        client = PlayerStatsClient(memory=self.build_memory())

        items = client.get_passive_items()

        self.assertEqual(items, ("Wrench x2",))

    def test_get_passive_item_count_reads_only_requested_stack(self) -> None:
        memory = self.build_memory()
        memory.ascii_strings[0x20000B00] = "ItemKey"
        memory.ints[0x20000900 + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET] = 13
        client = PlayerStatsClient(memory=memory)

        self.assertEqual(client.get_passive_item_count("Key"), 13)
        self.assertEqual(client.get_passive_item_count("Wrench"), 0)

    def test_get_passive_item_count_defaults_found_item_to_one(self) -> None:
        memory = self.build_memory()
        memory.ascii_strings[0x20000B00] = "ItemKey"
        del memory.ints[0x20000900 + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET]
        client = PlayerStatsClient(memory=memory)

        self.assertEqual(client.get_passive_item_count("Key"), 1)

    def test_get_passive_items_falls_back_to_player_item_inventory(self) -> None:
        memory = self.build_memory()
        owner_stats = 0x20000300
        inventory_container = 0x20000600
        player_inventory = 0x20001600
        item_inventory = 0x20001800
        item_dict = 0x20001900
        item_entries = 0x20001A00
        item_value = 0x20001B00
        class_meta = 0x20001C00
        class_name_ptr = 0x20001D00
        memory.pointers[inventory_container + PlayerStatsClient.PASSIVE_ITEM_DICT_OFFSET] = 0
        memory.pointers[player_inventory + PlayerStatsClient.ITEM_INVENTORY_OFFSET] = item_inventory
        memory.pointers[item_inventory + PlayerStatsClient.ITEM_INVENTORY_ITEMS_DICT_OFFSET] = item_dict
        memory.pointers[item_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET] = item_entries
        memory.pointers[
            item_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET
        ] = item_value
        memory.pointers[item_value + PlayerStatsClient.ITEM_CLASS_META_OFFSET] = class_meta
        memory.pointers[class_meta + PlayerStatsClient.CLASS_META_NAME_PTR_OFFSET] = class_name_ptr
        memory.ints[item_dict + PlayerStatsClient.DICT_COUNT_OFFSET] = 1
        memory.ints[item_value + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET] = 199
        memory.ascii_strings[class_name_ptr] = "ItemClover"
        client = PlayerStatsClient(memory=memory)

        items = client.get_passive_items(owner_stats)

        self.assertEqual(items, ("Clover x199",))

    def test_format_item_name_uses_item_display_overrides(self) -> None:
        self.assertEqual(PlayerStatsClient._format_item_name("ItemNoImplementation"), "The One Ring")
        self.assertEqual(PlayerStatsClient._format_item_name("ItemGoldenRing"), "The One Ring")
        self.assertEqual(PlayerStatsClient._format_item_name("ItemBobsLantern"), "Bob's Light")
        self.assertEqual(PlayerStatsClient._format_item_name("ItemGloveBlood"), "Slurp Gloves")

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

    def test_get_chest_counters_reads_bought_and_purchased(self) -> None:
        memory = self.build_memory()
        run_stats_entries = 0x20001100
        memory.mono_strings[0x20001200] = "chestsBought"
        memory.floats[
            run_stats_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.RUN_STATS_ENTRY_VALUE_OFFSET
        ] = 19.0
        client = PlayerStatsClient(memory=memory)

        self.assertEqual(client.get_chest_counters(), (19, 12))
        self.assertEqual(client.get_chests_bought(), 19)

    def test_get_chest_counters_defaults_missing_bought_key_to_zero(self) -> None:
        memory = self.build_memory()
        memory.mono_strings[0x20001200] = "kills"
        memory.ints[
            0x20001400 + PlayerStatsClient.MONEY_UTILITY_CHESTS_PURCHASED_OFFSET
        ] = 0
        client = PlayerStatsClient(memory=memory)

        self.assertEqual(client.get_chest_counters(), (0, 0))

    def test_expected_chest_inputs_reuse_validated_entry_addresses(self) -> None:
        memory = self.build_memory()
        memory.ascii_strings[0x20000B00] = "ItemKey"
        memory.ints[0x20000900 + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET] = 13
        memory.mono_strings[0x20001200] = "chestsBought"
        value_address = (
            0x20001100
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.RUN_STATS_ENTRY_VALUE_OFFSET
        )
        memory.floats[value_address] = 19.0
        client = PlayerStatsClient(memory=memory)

        self.assertEqual(client.get_expected_chest_inputs(0x20000300), (19, 13))

        del memory.ascii_strings[0x20000B00]
        del memory.mono_strings[0x20001200]
        memory.floats[value_address] = 20.0
        memory.ints[0x20000900 + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET] = 14
        self.assertEqual(client.get_expected_chest_inputs(0x20000300), (20, 14))

    def test_expected_chest_inputs_rescan_key_after_dictionary_change(self) -> None:
        memory = self.build_memory()
        memory.ascii_strings[0x20000B00] = "ItemKey"
        memory.mono_strings[0x20001200] = "chestsBought"
        client = PlayerStatsClient(memory=memory)

        self.assertEqual(client.get_expected_chest_inputs(0x20000300)[1], 2)

        memory.ints[0x20000700 + PlayerStatsClient.DICT_VERSION_OFFSET] = 2
        memory.ascii_strings[0x20000B00] = "ItemWrench"
        self.assertEqual(client.get_expected_chest_inputs(0x20000300)[1], 0)

    def test_expected_chest_inputs_find_bought_stat_when_it_appears(self) -> None:
        memory = self.build_memory()
        client = PlayerStatsClient(memory=memory)

        self.assertEqual(client.get_expected_chest_inputs(0x20000300)[0], 0)

        memory.mono_strings[0x20001200] = "chestsBought"
        memory.ints[0x20001000 + PlayerStatsClient.DICT_VERSION_OFFSET] = 2
        self.assertEqual(client.get_expected_chest_inputs(0x20000300)[0], 37)

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

    def test_get_live_tomes_reads_levels_and_effective_values(self) -> None:
        memory = build_player_stats_memory()
        owner_stats = 0x20000300
        player_inventory = 0x22000000
        tome_inventory = 0x22000100
        tome_levels_dict = 0x22000200
        tome_levels_entries = 0x22000300
        tome_upgrades_dict = 0x22000400
        tome_upgrades_entries = 0x22000500
        damage_modifier = 0x22000600
        armor_modifier = 0x22000700

        memory.pointers.update(
            {
                owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
                player_inventory + PlayerStatsClient.TOME_INVENTORY_OFFSET: tome_inventory,
                tome_inventory + PlayerStatsClient.TOME_LEVELS_DICT_OFFSET: tome_levels_dict,
                tome_inventory + PlayerStatsClient.TOME_UPGRADES_DICT_OFFSET: tome_upgrades_dict,
                tome_levels_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: tome_levels_entries,
                tome_upgrades_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: tome_upgrades_entries,
                tome_upgrades_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.WEAPON_DICT_ENTRY_VALUE_OFFSET: damage_modifier,
                tome_upgrades_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_SIZE
                + PlayerStatsClient.WEAPON_DICT_ENTRY_VALUE_OFFSET: armor_modifier,
            }
        )
        memory.ints.update(
            {
                tome_levels_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 2,
                tome_levels_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                tome_levels_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET: 0,
                tome_levels_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET: 3,
                tome_levels_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_SIZE + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                tome_levels_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_SIZE + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET: 5,
                tome_levels_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.STAT_DICT_ENTRY_SIZE + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET: 2,
                tome_upgrades_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 2,
                tome_upgrades_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                tome_upgrades_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.WEAPON_DICT_ENTRY_KEY_OFFSET: 0,
                tome_upgrades_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_SIZE + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                tome_upgrades_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_SIZE + PlayerStatsClient.WEAPON_DICT_ENTRY_KEY_OFFSET: 5,
                damage_modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 12,
                armor_modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 4,
            }
        )
        memory.floats.update(
            {
                damage_modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET: 1.25,
                armor_modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET: 0.2,
            }
        )

        client = PlayerStatsClient(memory=memory)

        tomes = client.get_live_tomes()

        self.assertEqual(len(tomes), 2)
        self.assertEqual(tomes[0].name, "Damage")
        self.assertEqual(tomes[0].level, 3)
        self.assertEqual(tomes[0].stat_id, 12)
        self.assertEqual(tomes[0].stat_label, "Damage")
        self.assertEqual(tomes[0].display_value, "1.25x")
        self.assertEqual(tomes[1].name, "Armor")
        self.assertEqual(tomes[1].level, 2)
        self.assertEqual(tomes[1].stat_label, "Armor")
        self.assertEqual(tomes[1].display_value, "20%")

    def test_get_live_tomes_returns_empty_when_tome_inventory_is_missing(self) -> None:
        client = PlayerStatsClient(memory=build_player_stats_memory())

        tomes = client.get_live_tomes()

        self.assertEqual(tomes, ())

    def test_get_passive_items_falls_back_when_primary_dictionary_read_fails(self) -> None:
        memory = build_player_stats_memory()
        owner_stats = 0x20000300
        inventory_container = 0x21000000
        player_inventory = 0x22000000
        item_inventory = 0x22000100
        passive_item_dict = 0x22000200
        entries = 0x22000300
        item_value = 0x22000400
        class_meta = 0x22000500
        name_ptr = 0x22000600

        memory.pointers.update(
            {
                owner_stats + PlayerStatsClient.INVENTORY_CONTAINER_OFFSET: inventory_container,
                owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
                player_inventory + PlayerStatsClient.ITEM_INVENTORY_OFFSET: item_inventory,
                item_inventory + PlayerStatsClient.ITEM_INVENTORY_ITEMS_DICT_OFFSET: passive_item_dict,
                passive_item_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: entries,
                entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: item_value,
                item_value + PlayerStatsClient.ITEM_CLASS_META_OFFSET: class_meta,
                class_meta + PlayerStatsClient.CLASS_META_NAME_PTR_OFFSET: name_ptr,
            }
        )
        memory.ints.update(
            {
                passive_item_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                item_value + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET: 2,
            }
        )
        memory.ascii_strings[name_ptr] = "ItemGoldenEgg"

        client = PlayerStatsClient(memory=memory)

        items = client.get_passive_items(owner_stats)

        self.assertEqual(items, ("Golden Egg x2",))

    def test_get_live_banishes_reads_items_and_tomes(self) -> None:
        memory = build_player_stats_memory()
        base = memory.module_base
        type_info = base + PlayerStatsClient.RUN_UNLOCKABLES_TYPE_INFO_OFFSET
        class_ptr = 0x23000000
        static_fields = 0x23000100
        item_set = 0x23000200
        upgradable_set = 0x23000300
        item_slots = 0x23000400
        upgradable_slots = 0x23000500
        item_data = 0x23000600
        item_klass = 0x23000700
        item_klass_name = 0x23000800
        tome_data = 0x23000900
        tome_klass = 0x23000A00
        tome_klass_name = 0x23000B00

        memory.pointers.update(
            {
                type_info: class_ptr,
                class_ptr + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: static_fields,
                static_fields + PlayerStatsClient.RUN_UNLOCKABLES_BANISHED_ITEMS_OFFSET: item_set,
                static_fields + PlayerStatsClient.RUN_UNLOCKABLES_BANISHED_UPGRADABLES_OFFSET: upgradable_set,
                item_set + PlayerStatsClient.HASHSET_SLOTS_OFFSET: item_slots,
                upgradable_set + PlayerStatsClient.HASHSET_SLOTS_OFFSET: upgradable_slots,
                item_slots + PlayerStatsClient.HASHSET_SLOT_START_OFFSET + PlayerStatsClient.HASHSET_SLOT_VALUE_OFFSET: item_data,
                upgradable_slots + PlayerStatsClient.HASHSET_SLOT_START_OFFSET + PlayerStatsClient.HASHSET_SLOT_VALUE_OFFSET: tome_data,
                item_data + PlayerStatsClient.OBJECT_KLASS_OFFSET: item_klass,
                item_klass + PlayerStatsClient.KLASS_NAME_PTR_OFFSET: item_klass_name,
                tome_data + PlayerStatsClient.OBJECT_KLASS_OFFSET: tome_klass,
                tome_klass + PlayerStatsClient.KLASS_NAME_PTR_OFFSET: tome_klass_name,
            }
        )
        memory.ints.update(
            {
                item_set + PlayerStatsClient.HASHSET_COUNT_OFFSET: 1,
                item_set + PlayerStatsClient.HASHSET_LAST_INDEX_OFFSET: 1,
                upgradable_set + PlayerStatsClient.HASHSET_COUNT_OFFSET: 1,
                upgradable_set + PlayerStatsClient.HASHSET_LAST_INDEX_OFFSET: 1,
                item_slots + PlayerStatsClient.HASHSET_SLOT_START_OFFSET + PlayerStatsClient.HASHSET_SLOT_HASH_CODE_OFFSET: 1,
                upgradable_slots + PlayerStatsClient.HASHSET_SLOT_START_OFFSET + PlayerStatsClient.HASHSET_SLOT_HASH_CODE_OFFSET: 1,
                item_data + PlayerStatsClient.ITEM_DATA_ENUM_OFFSET: 35,
                tome_data + PlayerStatsClient.TOME_DATA_ENUM_OFFSET: 15,
            }
        )
        memory.ascii_strings.update(
            {
                item_klass_name: "ItemData",
                tome_klass_name: "TomeData",
            }
        )

        client = PlayerStatsClient(memory=memory)

        banishes = client.get_live_banishes()

        self.assertEqual(banishes, ("Clover", "Golden Tome"))

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
