from __future__ import annotations

import unittest

from memory import MemoryReadError
from player_stats import (
    PlayerStatsClient,
    PlayerStatFormat,
    PlayerStatsTimeline,
    calculate_chests_per_minute,
    format_player_stat_value,
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
    ) -> None:
        self.module_base = module_base
        self.pointers = pointers or {}
        self.floats = floats or {}
        self.ints = ints or {}
        self.ascii_strings = ascii_strings or {}

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
    floats = {
        entries + 0x2C: 198.0,
        entries + 0x6C: 0.15,
        entries + 0x28C: 0.09,
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
    }
    ascii_strings = {
        class_name_ptr: "ItemWrench",
    }
    return FakeMemory(
        module_base=base,
        pointers=pointers,
        floats=floats,
        ints=ints,
        ascii_strings=ascii_strings,
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

    def test_get_passive_items_raises_for_invalid_dictionary_count(self) -> None:
        memory = self.build_memory()
        passive_dict = 0x20000700
        memory.ints[passive_dict + PlayerStatsClient.DICT_COUNT_OFFSET] = (
            PlayerStatsClient.MAX_PASSIVE_ITEM_DICT_ENTRIES + 1
        )
        client = PlayerStatsClient(memory=memory)

        with self.assertRaises(MemoryReadError):
            client.get_passive_items()

    def test_format_player_stat_values_match_game_display_style(self) -> None:
        self.assertEqual(format_player_stat_value(0.15, PlayerStatFormat.PERCENT), "15%")
        self.assertEqual(format_player_stat_value(1.25, PlayerStatFormat.MULTIPLIER), "1.25x")
        self.assertEqual(format_player_stat_value(10.0, PlayerStatFormat.FLAT), "10")
        self.assertEqual(format_player_stat_value(None, PlayerStatFormat.FLAT), "--")

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
