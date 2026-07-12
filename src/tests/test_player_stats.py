from __future__ import annotations

import src

import unittest
from unittest.mock import patch

from memory import MemoryReadError
from player_stats import (
    ChaosTomeStatSnapshot,
    DisabledItemsReadStatus,
    PLAYER_STAT_SPEC_BY_LABEL,
    PlayerStatsClient,
    PlayerStatFormat,
    PlayerStatsTimeline,
    WeaponStatFormat,
    calculate_chests_per_minute,
    format_chaos_tome_stat_delta,
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

    def test_player_crit_damage_display_includes_base_crit_multiplier(self) -> None:
        memory = self.build_memory()
        entries = 0x20000500
        crit_damage_offset = (
            PlayerStatsClient.STAT_VALUE_BASE_OFFSET
            + (19 * PlayerStatsClient.STAT_SLOT_SIZE)
        )
        memory.floats[entries + crit_damage_offset] = 3.3
        client = PlayerStatsClient(memory=memory)

        stats = client.get_player_stats()

        self.assertEqual(stats["Crit Damage"].value, 3.3)
        self.assertEqual(stats["Crit Damage"].display_value, "6.6x")

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

    def test_get_passive_items_prefers_item_id_for_crypt_key_over_placeholder_class(self) -> None:
        memory = self.build_memory()
        passive_entries = 0x20000800
        class_name_ptr = 0x20000B00
        memory.ints[
            passive_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET
        ] = 81
        memory.ascii_strings[class_name_ptr] = "ItemNoImplementation"
        client = PlayerStatsClient(memory=memory)

        items = client.get_passive_items()

        self.assertEqual(items, ("Crypt key x2",))

    def test_get_passive_items_uses_item_id_for_one_ring_when_class_is_placeholder(self) -> None:
        memory = self.build_memory()
        passive_entries = 0x20000800
        class_name_ptr = 0x20000B00
        memory.ints[
            passive_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET
        ] = 79
        memory.ascii_strings[class_name_ptr] = "ItemNoImplementation"
        client = PlayerStatsClient(memory=memory)

        items = client.get_passive_items()

        self.assertEqual(items, ("The One Ring x2",))

    def test_get_passive_items_falls_back_to_class_name_when_item_id_is_unknown(self) -> None:
        memory = self.build_memory()
        passive_entries = 0x20000800
        class_name_ptr = 0x20000B00
        memory.ints[
            passive_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET
        ] = 999
        memory.ascii_strings[class_name_ptr] = "ItemGoldenEgg"
        client = PlayerStatsClient(memory=memory)

        items = client.get_passive_items()

        self.assertEqual(items, ("Golden Egg x2",))

    def test_get_passive_items_falls_back_to_class_name_when_item_id_is_unreadable(self) -> None:
        memory = self.build_memory()
        class_name_ptr = 0x20000B00
        memory.ascii_strings[class_name_ptr] = "ItemGoldenEgg"
        client = PlayerStatsClient(memory=memory)

        items = client.get_passive_items()

        self.assertEqual(items, ("Golden Egg x2",))

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

    def test_get_powerup_tracking_snapshot_reads_status_effects_and_stage_time(self) -> None:
        memory = self.build_memory()
        base = memory.module_base
        player_inventory = 0x20001600
        status_effects = 0x26000000
        status_dict = 0x26000100
        status_entries = 0x26000200
        rage_effect = 0x26000300
        clock_effect = 0x26000400
        map_controller_type_info = base + PlayerStatsClient.MAP_CONTROLLER_TYPE_INFO_OFFSET
        map_controller_class = 0x26000500
        map_controller_static = 0x26000600
        current_stage = 0x26000700
        stage_timeline = 0x26000800
        run_timer_static_fields = 0x20000D00

        memory.pointers.update(
            {
                player_inventory + PlayerStatsClient.PLAYER_STATUS_EFFECTS_OFFSET: status_effects,
                status_effects + PlayerStatsClient.PLAYER_STATUS_EFFECTS_DICT_OFFSET: status_dict,
                status_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: status_entries,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: rage_effect,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_SIZE
                + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: clock_effect,
                map_controller_type_info: map_controller_class,
                map_controller_class + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: map_controller_static,
                map_controller_static + PlayerStatsClient.MAP_CONTROLLER_CURRENT_STAGE_OFFSET: current_stage,
                current_stage + PlayerStatsClient.STAGE_DATA_TIMELINE_OFFSET: stage_timeline,
            }
        )
        memory.ints.update(
            {
                status_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 2,
                status_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET: 2,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 1,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_SIZE
                + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 4,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_SIZE
                + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 4,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 1,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 4,
                map_controller_static + PlayerStatsClient.MAP_CONTROLLER_INDEX_OFFSET: 2,
            }
        )
        memory.floats.update(
            {
                run_timer_static_fields + PlayerStatsClient.MY_TIME_TIME_OFFSET: 1000.0,
                run_timer_static_fields + PlayerStatsClient.STAGE_TIMER_OFFSET: 46.5,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 990.0,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1068.0,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 995.0,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1057.4,
                stage_timeline + PlayerStatsClient.STAGE_TIMELINE_STAGE_TIME_OFFSET: 480.0,
            }
        )

        snapshot = PlayerStatsClient(memory=memory).get_powerup_tracking_snapshot()

        self.assertEqual(snapshot.stage_index, 2)
        self.assertEqual(snapshot.stage_time_seconds, 480.0)
        self.assertEqual(snapshot.stage_timer_seconds, 46.5)
        self.assertEqual([effect.name for effect in snapshot.effects], ["Rage", "Clock"])

    def test_get_powerup_tracking_snapshot_caches_powerup_multiplier_until_ttl(self) -> None:
        memory = self.build_memory()
        base = memory.module_base
        owner_stats = 0x20000300
        entries = 0x20000500
        player_inventory = 0x20001600
        status_effects = 0x26000000
        status_dict = 0x26000100
        status_entries = 0x26000200
        rage_effect = 0x26000300
        map_controller_type_info = base + PlayerStatsClient.MAP_CONTROLLER_TYPE_INFO_OFFSET
        map_controller_class = 0x26000500
        map_controller_static = 0x26000600
        current_stage = 0x26000700
        stage_timeline = 0x26000800
        run_timer_static_fields = 0x20000D00
        powerup_spec = PLAYER_STAT_SPEC_BY_LABEL["Powerup Multiplier"]
        memory.pointers.update(
            {
                owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
                player_inventory + PlayerStatsClient.PLAYER_STATUS_EFFECTS_OFFSET: status_effects,
                status_effects + PlayerStatsClient.PLAYER_STATUS_EFFECTS_DICT_OFFSET: status_dict,
                status_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: status_entries,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: rage_effect,
                map_controller_type_info: map_controller_class,
                map_controller_class + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: map_controller_static,
                map_controller_static + PlayerStatsClient.MAP_CONTROLLER_CURRENT_STAGE_OFFSET: current_stage,
                current_stage + PlayerStatsClient.STAGE_DATA_TIMELINE_OFFSET: stage_timeline,
            }
        )
        memory.ints.update(
            {
                status_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                status_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET: 1,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 1,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 1,
                map_controller_static + PlayerStatsClient.MAP_CONTROLLER_INDEX_OFFSET: 1,
            }
        )
        memory.floats.update(
            {
                entries + powerup_spec.offset: 1.5,
                run_timer_static_fields + PlayerStatsClient.MY_TIME_TIME_OFFSET: 1000.0,
                run_timer_static_fields + PlayerStatsClient.STAGE_TIMER_OFFSET: 46.5,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 990.0,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1015.0,
                stage_timeline + PlayerStatsClient.STAGE_TIMELINE_STAGE_TIME_OFFSET: 540.0,
            }
        )
        client = PlayerStatsClient(memory=memory)

        with patch("player_stats.time.monotonic", side_effect=(100.0, 101.0, 106.0)):
            first = client.get_powerup_tracking_snapshot(owner_stats)
            memory.floats[entries + powerup_spec.offset] = 2.0
            second = client.get_powerup_tracking_snapshot(owner_stats)
            third = client.get_powerup_tracking_snapshot(owner_stats)

        self.assertEqual(first.powerup_multiplier_display, "1.5x")
        self.assertEqual(second.powerup_multiplier_display, "1.5x")
        self.assertEqual(third.powerup_multiplier_display, "2x")

    def test_get_powerup_tracking_snapshot_does_not_reuse_pm_cache_for_other_owner(self) -> None:
        memory = self.build_memory()
        base = memory.module_base
        owner_stats = 0x20000300
        owner_stats_2 = 0x20010300
        stats_context_2 = 0x20010400
        entries_2 = 0x20010500
        player_inventory = 0x20001600
        status_effects = 0x26000000
        status_dict = 0x26000100
        status_entries = 0x26000200
        map_controller_type_info = base + PlayerStatsClient.MAP_CONTROLLER_TYPE_INFO_OFFSET
        map_controller_class = 0x26000500
        map_controller_static = 0x26000600
        current_stage = 0x26000700
        stage_timeline = 0x26000800
        run_timer_static_fields = 0x20000D00
        powerup_spec = PLAYER_STAT_SPEC_BY_LABEL["Powerup Multiplier"]

        memory.pointers.update(
            {
                owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
                owner_stats_2 + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
                owner_stats_2 + PlayerStatsClient.STATS_CONTEXT_OFFSET: stats_context_2,
                stats_context_2 + PlayerStatsClient.STATS_ENTRIES_OFFSET: entries_2,
                player_inventory + PlayerStatsClient.PLAYER_STATUS_EFFECTS_OFFSET: status_effects,
                status_effects + PlayerStatsClient.PLAYER_STATUS_EFFECTS_DICT_OFFSET: status_dict,
                status_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: status_entries,
                map_controller_type_info: map_controller_class,
                map_controller_class + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: map_controller_static,
                map_controller_static + PlayerStatsClient.MAP_CONTROLLER_CURRENT_STAGE_OFFSET: current_stage,
                current_stage + PlayerStatsClient.STAGE_DATA_TIMELINE_OFFSET: stage_timeline,
            }
        )
        memory.ints.update(
            {
                status_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                status_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET: 0,
                map_controller_static + PlayerStatsClient.MAP_CONTROLLER_INDEX_OFFSET: 1,
            }
        )
        memory.floats.update(
            {
                run_timer_static_fields + PlayerStatsClient.MY_TIME_TIME_OFFSET: 1000.0,
                run_timer_static_fields + PlayerStatsClient.STAGE_TIMER_OFFSET: 46.5,
                stage_timeline + PlayerStatsClient.STAGE_TIMELINE_STAGE_TIME_OFFSET: 540.0,
                0x20000500 + powerup_spec.offset: 1.5,
                entries_2 + powerup_spec.offset: 2.0,
            }
        )
        client = PlayerStatsClient(memory=memory)

        with patch("player_stats.time.monotonic", side_effect=(100.0, 101.0)):
            first = client.get_powerup_tracking_snapshot(owner_stats)
            second = client.get_powerup_tracking_snapshot(owner_stats_2)

        self.assertEqual(first.powerup_multiplier_display, "1.5x")
        self.assertEqual(second.powerup_multiplier_display, "2x")

    def test_get_active_status_effects_picks_up_new_effect_without_dict_rescan(self) -> None:
        memory = self.build_memory()
        owner_stats = 0x20000300
        player_inventory = 0x20001600
        status_effects = 0x26000000
        status_dict = 0x26000100
        status_entries = 0x26000200
        rage_effect = 0x26000300
        shield_effect = 0x26000400
        rage_value_address = (
            status_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET
        )
        shield_value_address = (
            status_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.DICT_ENTRY_SIZE
            + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET
        )

        memory.pointers.update(
            {
                player_inventory + PlayerStatsClient.PLAYER_STATUS_EFFECTS_OFFSET: status_effects,
                status_effects + PlayerStatsClient.PLAYER_STATUS_EFFECTS_DICT_OFFSET: status_dict,
                status_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: status_entries,
                rage_value_address: rage_effect,
                shield_value_address: 0,
            }
        )
        memory.ints.update(
            {
                status_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                status_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                status_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET: 2,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 1,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_SIZE
                + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 2,
                status_entries
                + PlayerStatsClient.DICT_ENTRY_START_OFFSET
                + PlayerStatsClient.DICT_ENTRY_SIZE
                + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 2,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 1,
                shield_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 2,
            }
        )
        memory.floats.update(
            {
                rage_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 990.0,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1015.0,
                shield_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 991.0,
                shield_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1016.0,
            }
        )
        client = PlayerStatsClient(memory=memory)

        first = client.get_active_status_effects(owner_stats)
        memory.pointers[shield_value_address] = shield_effect
        second = client.get_active_status_effects(owner_stats)

        self.assertEqual([effect.name for effect in first], ["Rage"])
        self.assertEqual([effect.name for effect in second], ["Rage", "Shield"])

    def test_get_active_status_effects_rescans_when_supported_effect_count_changes(self) -> None:
        memory = self.build_memory()
        owner_stats = 0x20000300
        player_inventory = 0x20001600
        status_effects = 0x26000000
        status_dict = 0x26000100
        status_entries = 0x26000200
        rage_effect = 0x26000300
        shield_effect = 0x26000400
        clock_effect = 0x26000500
        stonks_effect = 0x26000600
        rage_entry = status_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET
        shield_entry = rage_entry + PlayerStatsClient.DICT_ENTRY_SIZE
        clock_entry = shield_entry + PlayerStatsClient.DICT_ENTRY_SIZE
        stonks_entry = clock_entry + PlayerStatsClient.DICT_ENTRY_SIZE

        memory.pointers.update(
            {
                player_inventory + PlayerStatsClient.PLAYER_STATUS_EFFECTS_OFFSET: status_effects,
                status_effects + PlayerStatsClient.PLAYER_STATUS_EFFECTS_DICT_OFFSET: status_dict,
                status_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: status_entries,
                rage_entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: rage_effect,
                shield_entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: shield_effect,
                clock_entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: clock_effect,
            }
        )
        memory.ints.update(
            {
                status_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 3,
                status_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                status_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET: 4,
                rage_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                rage_entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 1,
                shield_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 2,
                shield_entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 2,
                clock_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 3,
                clock_entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 4,
                stonks_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: -1,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 1,
                shield_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 2,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 4,
            }
        )
        memory.floats.update(
            {
                rage_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 990.0,
                rage_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1015.0,
                shield_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 991.0,
                shield_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1016.0,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 992.0,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1017.0,
            }
        )
        client = PlayerStatsClient(memory=memory)

        first = client.get_active_status_effects(owner_stats)

        memory.ints[status_dict + PlayerStatsClient.DICT_COUNT_OFFSET] = 4
        memory.ints[stonks_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET] = 4
        memory.ints[stonks_entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET] = 3
        memory.pointers[stonks_entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET] = stonks_effect
        memory.ints[stonks_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET] = 3
        memory.floats[stonks_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET] = 993.0
        memory.floats[stonks_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET] = 1018.0

        second = client.get_active_status_effects(owner_stats)

        self.assertEqual([effect.name for effect in first], ["Rage", "Shield", "Clock"])
        self.assertEqual([effect.name for effect in second], ["Rage", "Shield", "Stonks", "Clock"])

    def test_get_active_status_effects_uses_object_effect_id_after_slot_reuse(self) -> None:
        memory = self.build_memory()
        owner_stats = 0x20000300
        player_inventory = 0x20001600
        status_effects = 0x26000000
        status_dict = 0x26000100
        status_entries = 0x26000200
        shield_effect = 0x26000300
        haste_effect = 0x26000400
        shield_entry = status_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET

        memory.pointers.update(
            {
                player_inventory + PlayerStatsClient.PLAYER_STATUS_EFFECTS_OFFSET: status_effects,
                status_effects + PlayerStatsClient.PLAYER_STATUS_EFFECTS_DICT_OFFSET: status_dict,
                status_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: status_entries,
                shield_entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: shield_effect,
            }
        )
        memory.ints.update(
            {
                status_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                status_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                status_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET: 1,
                shield_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 2,
                shield_entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 2,
                shield_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 2,
                haste_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 0,
            }
        )
        memory.floats.update(
            {
                shield_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 990.0,
                shield_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1015.0,
                haste_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 1016.0,
                haste_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 1033.0,
            }
        )
        client = PlayerStatsClient(memory=memory)

        first = client.get_active_status_effects(owner_stats)
        memory.pointers[shield_entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET] = haste_effect
        second = client.get_active_status_effects(owner_stats)

        self.assertEqual([effect.name for effect in first], ["Shield"])
        self.assertEqual(second, ())

    def test_get_active_status_effects_rescans_when_unsupported_slot_becomes_clock(self) -> None:
        memory = self.build_memory()
        owner_stats = 0x20000300
        player_inventory = 0x26000000
        status_effects = 0x26000100
        status_dict = 0x26000200
        status_entries = 0x26000300
        invulnerability_effect = 0x26000400
        clock_effect = 0x26000500
        entry = status_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET

        memory.pointers.update(
            {
                owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
                player_inventory + PlayerStatsClient.PLAYER_STATUS_EFFECTS_OFFSET: status_effects,
                status_effects + PlayerStatsClient.PLAYER_STATUS_EFFECTS_DICT_OFFSET: status_dict,
                status_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: status_entries,
                entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: invulnerability_effect,
            }
        )
        memory.ints.update(
            {
                status_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 3,
                status_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 2,
                status_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET: 3,
                entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 5,
                entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 5,
                invulnerability_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 5,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 4,
            }
        )
        memory.floats.update(
            {
                invulnerability_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 100.0,
                invulnerability_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 100.5,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_ADDED_OFFSET: 100.6,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_EXPIRATION_OFFSET: 115.6,
            }
        )
        client = PlayerStatsClient(memory=memory)

        self.assertEqual(client.get_active_status_effects(owner_stats), ())

        memory.ints[entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET] = 4
        memory.ints[entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET] = 4
        memory.pointers[entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET] = clock_effect

        effects = client.get_active_status_effects(owner_stats)

        self.assertEqual([effect.name for effect in effects], ["Clock"])
        self.assertEqual(effects[0].expiration_time, 115.6)

    def test_active_status_effects_reports_unavailable_when_inventory_is_missing(self) -> None:
        memory = self.build_memory()
        owner_stats = 0x20000300
        memory.pointers[owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET] = 0
        client = PlayerStatsClient(memory=memory)

        result = client._read_active_status_effects(owner_stats)

        self.assertEqual(result.effects, ())
        self.assertFalse(result.health.available)
        self.assertFalse(result.health.complete)
        self.assertEqual(result.health.failure_reason, "status_effects_unavailable")

    def test_active_status_effects_reports_partial_when_effect_object_is_unreadable(self) -> None:
        memory = self.build_memory()
        owner_stats = 0x20000300
        player_inventory = 0x26000000
        status_effects = 0x26000100
        status_dict = 0x26000200
        status_entries = 0x26000300
        clock_effect = 0x26000400
        entry = status_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET
        memory.pointers.update(
            {
                owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
                player_inventory + PlayerStatsClient.PLAYER_STATUS_EFFECTS_OFFSET: status_effects,
                status_effects + PlayerStatsClient.PLAYER_STATUS_EFFECTS_DICT_OFFSET: status_dict,
                status_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: status_entries,
                entry + PlayerStatsClient.DICT_ENTRY_VALUE_OFFSET: clock_effect,
            }
        )
        memory.ints.update(
            {
                status_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                status_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                status_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET: 1,
                entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 4,
                entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET: 4,
                clock_effect + PlayerStatsClient.STATUS_EFFECT_ESTATUS_OFFSET: 4,
            }
        )
        client = PlayerStatsClient(memory=memory)

        result = client._read_active_status_effects(owner_stats)

        self.assertEqual(result.effects, ())
        self.assertTrue(result.health.available)
        self.assertFalse(result.health.complete)
        self.assertEqual(result.health.failure_reason, "status_effects_partial")

    def test_read_current_stage_time_clears_stale_timeline_when_current_stage_is_missing(self) -> None:
        memory = self.build_memory()
        base = memory.module_base
        map_controller_type_info = base + PlayerStatsClient.MAP_CONTROLLER_TYPE_INFO_OFFSET
        map_controller_class = 0x26000500
        map_controller_static = 0x26000600
        current_stage = 0x26000700
        stage_timeline = 0x26000800
        memory.pointers.update(
            {
                map_controller_type_info: map_controller_class,
                map_controller_class + PlayerStatsClient.CLASS_STATIC_FIELDS_OFFSET: map_controller_static,
                map_controller_static + PlayerStatsClient.MAP_CONTROLLER_CURRENT_STAGE_OFFSET: current_stage,
                current_stage + PlayerStatsClient.STAGE_DATA_TIMELINE_OFFSET: stage_timeline,
            }
        )
        memory.ints.update(
            {
                map_controller_static + PlayerStatsClient.MAP_CONTROLLER_INDEX_OFFSET: 1,
            }
        )
        memory.floats.update(
            {
                stage_timeline + PlayerStatsClient.STAGE_TIMELINE_STAGE_TIME_OFFSET: 540.0,
            }
        )
        client = PlayerStatsClient(memory=memory)

        first_stage_index, first_stage_time = client._read_current_stage_time()
        memory.pointers[map_controller_static + PlayerStatsClient.MAP_CONTROLLER_CURRENT_STAGE_OFFSET] = 0
        memory.ints[map_controller_static + PlayerStatsClient.MAP_CONTROLLER_INDEX_OFFSET] = 2
        second_stage_index, second_stage_time = client._read_current_stage_time()

        self.assertEqual((first_stage_index, first_stage_time), (1, 540.0))
        self.assertEqual((second_stage_index, second_stage_time), (2, 480.0))

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

    def test_get_killed_mobs_rescans_when_dictionary_version_changes(self) -> None:
        memory = self.build_memory()
        run_stats_dict = 0x20001000
        run_stats_entries = 0x20001100
        first_value_address = (
            run_stats_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.RUN_STATS_ENTRY_VALUE_OFFSET
        )
        second_entry = run_stats_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET + PlayerStatsClient.DICT_ENTRY_SIZE
        second_value_address = second_entry + PlayerStatsClient.RUN_STATS_ENTRY_VALUE_OFFSET
        memory.ints[run_stats_dict + PlayerStatsClient.DICT_COUNT_OFFSET] = 2
        memory.ints[run_stats_entries + PlayerStatsClient.ARRAY_LENGTH_OFFSET] = 2

        client = PlayerStatsClient(memory=memory)
        self.assertEqual(client.get_killed_mobs(), 37)

        memory.ints[run_stats_dict + PlayerStatsClient.DICT_VERSION_OFFSET] = 2
        memory.ints[
            run_stats_entries
            + PlayerStatsClient.DICT_ENTRY_START_OFFSET
            + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET
        ] = -1
        memory.mono_strings[0x20001200] = "otherStat"
        memory.floats[first_value_address] = 1.0
        memory.ints[second_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET] = 2
        memory.pointers[second_entry + PlayerStatsClient.DICT_ENTRY_KEY_OFFSET] = 0x20001210
        memory.mono_strings[0x20001210] = "kills"
        memory.floats[second_value_address] = 91.0

        self.assertEqual(client.get_killed_mobs(), 91)

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

    def test_chaos_tracking_state_reuses_cached_level_and_modifier_addresses(self) -> None:
        memory = build_player_stats_memory()
        owner_stats = 0x20000300
        player_inventory = 0x20001600
        tome_inventory = 0x23000000
        levels_dict = 0x23000100
        level_entries = 0x23000200
        stat_inventory = 0x23000300
        modifiers_dict = 0x23000400
        modifier_entries = 0x23000500
        modifier_list = 0x23000600
        modifier_array = 0x23000700
        modifier = 0x23000800
        level_entry = level_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET
        modifier_entry = modifier_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET

        memory.pointers.update(
            {
                player_inventory + PlayerStatsClient.TOME_INVENTORY_OFFSET: tome_inventory,
                tome_inventory + PlayerStatsClient.TOME_LEVELS_DICT_OFFSET: levels_dict,
                levels_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: level_entries,
                player_inventory + PlayerStatsClient.STAT_INVENTORY_OFFSET: stat_inventory,
                stat_inventory + PlayerStatsClient.STAT_INVENTORY_PERMANENT_CHANGES_OFFSET: modifiers_dict,
                modifiers_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: modifier_entries,
                modifier_entry + PlayerStatsClient.WEAPON_DICT_ENTRY_VALUE_OFFSET: modifier_list,
                modifier_list + PlayerStatsClient.LIST_ITEMS_OFFSET: modifier_array,
                modifier_array + PlayerStatsClient.ARRAY_DATA_OFFSET: modifier,
            }
        )
        memory.ints.update(
            {
                levels_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                levels_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                level_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                level_entry + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET: PlayerStatsClient.CHAOS_TOME_ID,
                level_entry + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET: 3,
                modifiers_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                modifiers_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                modifier_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                modifier_entry + PlayerStatsClient.WEAPON_DICT_ENTRY_KEY_OFFSET: 12,
                modifier_list + PlayerStatsClient.LIST_SIZE_OFFSET: 1,
                modifier_list + PlayerStatsClient.LIST_VERSION_OFFSET: 1,
                modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 12,
            }
        )
        memory.floats[modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET] = 0.168
        client = PlayerStatsClient(memory=memory)

        level, modifiers = client.get_chaos_tracking_state(owner_stats)
        self.assertEqual(level, 3)
        self.assertAlmostEqual(modifiers[12][0].value, 0.168)

        del memory.ints[level_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET]
        del memory.ints[level_entry + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET]
        memory.ints[level_entry + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET] = 4
        memory.floats[modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET] = 0.336

        level, modifiers = client.get_chaos_tracking_state(owner_stats)
        self.assertEqual(level, 4)
        self.assertAlmostEqual(modifiers[12][0].value, 0.336)

        del memory.ints[modifier_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET]
        del memory.ints[modifier_entry + PlayerStatsClient.WEAPON_DICT_ENTRY_KEY_OFFSET]
        del memory.ints[modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET]
        memory.floats[modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET] = 0.504

        level, modifiers = client.get_chaos_tracking_state(owner_stats)
        self.assertEqual(level, 4)
        self.assertAlmostEqual(modifiers[12][0].value, 0.504)

    def test_chaos_tracking_state_retries_unresolved_level_entry_without_version_change(self) -> None:
        memory = build_player_stats_memory()
        owner_stats = 0x20000300
        player_inventory = 0x20001600
        tome_inventory = 0x23100000
        levels_dict = 0x23100100
        level_entries = 0x23100200
        level_entry = level_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET

        memory.pointers.update(
            {
                owner_stats + PlayerStatsClient.PLAYER_INVENTORY_OFFSET: player_inventory,
                player_inventory + PlayerStatsClient.TOME_INVENTORY_OFFSET: tome_inventory,
                player_inventory + PlayerStatsClient.STAT_INVENTORY_OFFSET: 0,
                tome_inventory + PlayerStatsClient.TOME_LEVELS_DICT_OFFSET: levels_dict,
                levels_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: level_entries,
            }
        )
        memory.ints.update(
            {
                levels_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                levels_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 7,
                level_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: -1,
                level_entry + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET: 2,
            }
        )
        client = PlayerStatsClient(memory=memory)

        level, modifiers = client.get_chaos_tracking_state(owner_stats)
        self.assertIsNone(level)
        self.assertEqual(modifiers, {})

        memory.ints[level_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET] = 1
        memory.ints[level_entry + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET] = (
            PlayerStatsClient.CHAOS_TOME_ID
        )
        memory.ints[level_entry + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET] = 3

        level, modifiers = client.get_chaos_tracking_state(owner_stats)
        self.assertEqual(level, 3)
        self.assertEqual(modifiers, {})

    def test_chaos_tracking_state_rescans_changed_modifier_list(self) -> None:
        memory = build_player_stats_memory()
        owner_stats = 0x20000300
        player_inventory = 0x20001600
        tome_inventory = 0x24000000
        levels_dict = 0x24000100
        level_entries = 0x24000200
        stat_inventory = 0x24000300
        modifiers_dict = 0x24000400
        modifier_entries = 0x24000500
        modifier_list = 0x24000600
        modifier_array = 0x24000700
        first_modifier = 0x24000800
        second_modifier = 0x24000900
        level_entry = level_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET
        modifier_entry = modifier_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET
        memory.pointers.update(
            {
                player_inventory + PlayerStatsClient.TOME_INVENTORY_OFFSET: tome_inventory,
                tome_inventory + PlayerStatsClient.TOME_LEVELS_DICT_OFFSET: levels_dict,
                levels_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: level_entries,
                player_inventory + PlayerStatsClient.STAT_INVENTORY_OFFSET: stat_inventory,
                stat_inventory + PlayerStatsClient.STAT_INVENTORY_PERMANENT_CHANGES_OFFSET: modifiers_dict,
                modifiers_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: modifier_entries,
                modifier_entry + PlayerStatsClient.WEAPON_DICT_ENTRY_VALUE_OFFSET: modifier_list,
                modifier_list + PlayerStatsClient.LIST_ITEMS_OFFSET: modifier_array,
                modifier_array + PlayerStatsClient.ARRAY_DATA_OFFSET: first_modifier,
            }
        )
        memory.ints.update(
            {
                levels_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                levels_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                level_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                level_entry + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET: PlayerStatsClient.CHAOS_TOME_ID,
                level_entry + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET: 2,
                modifiers_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                modifiers_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                modifier_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                modifier_entry + PlayerStatsClient.WEAPON_DICT_ENTRY_KEY_OFFSET: 12,
                modifier_list + PlayerStatsClient.LIST_SIZE_OFFSET: 1,
                modifier_list + PlayerStatsClient.LIST_VERSION_OFFSET: 1,
                first_modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 12,
                second_modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 12,
            }
        )
        memory.floats.update(
            {
                first_modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET: 0.168,
                second_modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET: 0.168,
            }
        )
        client = PlayerStatsClient(memory=memory)
        self.assertEqual(len(client.get_chaos_tracking_state(owner_stats)[1][12]), 1)

        memory.pointers[
            modifier_array + PlayerStatsClient.ARRAY_DATA_OFFSET + PlayerStatsClient.OBJECT_POINTER_SIZE
        ] = second_modifier
        memory.ints[modifier_list + PlayerStatsClient.LIST_SIZE_OFFSET] = 2
        memory.ints[modifier_list + PlayerStatsClient.LIST_VERSION_OFFSET] = 2

        _, modifiers = client.get_chaos_tracking_state(owner_stats)
        self.assertEqual(len(modifiers[12]), 2)

    def test_chaos_tracking_state_rescans_changed_modifier_dictionary_count(self) -> None:
        memory = build_player_stats_memory()
        owner_stats = 0x20000300
        player_inventory = 0x20001600
        tome_inventory = 0x25000000
        levels_dict = 0x25000100
        level_entries = 0x25000200
        stat_inventory = 0x25000300
        modifiers_dict = 0x25000400
        modifier_entries = 0x25000500
        damage_list = 0x25000600
        damage_array = 0x25000700
        damage_modifier = 0x25000800
        luck_list = 0x25000900
        luck_array = 0x25000A00
        luck_modifier = 0x25000B00
        level_entry = level_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET
        damage_entry = modifier_entries + PlayerStatsClient.DICT_ENTRY_START_OFFSET
        luck_entry = damage_entry + PlayerStatsClient.DICT_ENTRY_SIZE
        memory.pointers.update(
            {
                player_inventory + PlayerStatsClient.TOME_INVENTORY_OFFSET: tome_inventory,
                tome_inventory + PlayerStatsClient.TOME_LEVELS_DICT_OFFSET: levels_dict,
                levels_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: level_entries,
                player_inventory + PlayerStatsClient.STAT_INVENTORY_OFFSET: stat_inventory,
                stat_inventory + PlayerStatsClient.STAT_INVENTORY_PERMANENT_CHANGES_OFFSET: modifiers_dict,
                modifiers_dict + PlayerStatsClient.DICT_ENTRIES_OFFSET: modifier_entries,
                damage_entry + PlayerStatsClient.WEAPON_DICT_ENTRY_VALUE_OFFSET: damage_list,
                damage_list + PlayerStatsClient.LIST_ITEMS_OFFSET: damage_array,
                damage_array + PlayerStatsClient.ARRAY_DATA_OFFSET: damage_modifier,
                luck_entry + PlayerStatsClient.WEAPON_DICT_ENTRY_VALUE_OFFSET: luck_list,
                luck_list + PlayerStatsClient.LIST_ITEMS_OFFSET: luck_array,
                luck_array + PlayerStatsClient.ARRAY_DATA_OFFSET: luck_modifier,
            }
        )
        memory.ints.update(
            {
                levels_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                levels_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                level_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                level_entry + PlayerStatsClient.STAT_DICT_ENTRY_KEY_OFFSET: PlayerStatsClient.CHAOS_TOME_ID,
                level_entry + PlayerStatsClient.STAT_DICT_ENTRY_VALUE_OFFSET: 2,
                modifiers_dict + PlayerStatsClient.DICT_COUNT_OFFSET: 1,
                modifiers_dict + PlayerStatsClient.DICT_VERSION_OFFSET: 1,
                damage_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                damage_entry + PlayerStatsClient.WEAPON_DICT_ENTRY_KEY_OFFSET: 12,
                damage_list + PlayerStatsClient.LIST_SIZE_OFFSET: 1,
                damage_list + PlayerStatsClient.LIST_VERSION_OFFSET: 1,
                damage_modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 12,
                luck_entry + PlayerStatsClient.DICT_ENTRY_HASH_CODE_OFFSET: 1,
                luck_entry + PlayerStatsClient.WEAPON_DICT_ENTRY_KEY_OFFSET: 30,
                luck_list + PlayerStatsClient.LIST_SIZE_OFFSET: 1,
                luck_list + PlayerStatsClient.LIST_VERSION_OFFSET: 1,
                luck_modifier + PlayerStatsClient.STAT_MODIFIER_STAT_OFFSET: 30,
            }
        )
        memory.floats.update(
            {
                damage_modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET: 0.168,
                luck_modifier + PlayerStatsClient.STAT_MODIFIER_VALUE_OFFSET: 0.07,
            }
        )
        client = PlayerStatsClient(memory=memory)
        self.assertEqual(set(client.get_chaos_tracking_state(owner_stats)[1]), {12})

        memory.ints[modifiers_dict + PlayerStatsClient.DICT_COUNT_OFFSET] = 2

        _, modifiers = client.get_chaos_tracking_state(owner_stats)
        self.assertEqual(set(modifiers), {12, 30})

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

    def test_format_chaos_tome_stat_delta_converts_pickup_range_to_meters(self) -> None:
        self.assertEqual(
            format_chaos_tome_stat_delta("Pickup Range", 2.72, PlayerStatFormat.FLAT),
            "+24.5",
        )

    def test_format_chaos_tome_stat_delta_converts_crit_damage_to_effective_scale(self) -> None:
        self.assertEqual(
            format_chaos_tome_stat_delta("Crit Damage", 1.31, PlayerStatFormat.MULTIPLIER),
            "+262%",
        )

    def test_chaos_tome_snapshot_display_delta_converts_pickup_range_to_meters(self) -> None:
        stat = ChaosTomeStatSnapshot(
            stat_id=29,
            label="Pickup Range",
            value=2.72,
            value_format=PlayerStatFormat.FLAT,
        )

        self.assertEqual(stat.display_delta, "+24.5")

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
