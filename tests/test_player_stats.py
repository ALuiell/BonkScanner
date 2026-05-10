from __future__ import annotations

import unittest

from memory import MemoryReadError
from player_stats import (
    PlayerStatsClient,
    PlayerStatFormat,
    format_player_stat_value,
)


class FakeMemory:
    def __init__(
        self,
        *,
        module_base: int = 0x10000000,
        pointers: dict[int, int] | None = None,
        floats: dict[int, float] | None = None,
    ) -> None:
        self.module_base = module_base
        self.pointers = pointers or {}
        self.floats = floats or {}

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


class PlayerStatsClientTests(unittest.TestCase):
    def build_memory(self) -> FakeMemory:
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
        return FakeMemory(module_base=base, pointers=pointers, floats=floats)

    def test_get_player_stats_reads_confirmed_offsets(self) -> None:
        client = PlayerStatsClient(memory=self.build_memory())

        stats = client.get_player_stats()

        self.assertEqual(stats["Max HP"].display_value, "198")
        self.assertEqual(stats["Armor"].display_value, "15%")
        self.assertEqual(stats["Difficulty"].display_value, "9%")

    def test_format_player_stat_values_match_game_display_style(self) -> None:
        self.assertEqual(format_player_stat_value(0.15, PlayerStatFormat.PERCENT), "15%")
        self.assertEqual(format_player_stat_value(1.25, PlayerStatFormat.MULTIPLIER), "1.25x")
        self.assertEqual(format_player_stat_value(10.0, PlayerStatFormat.FLAT), "10")
        self.assertEqual(format_player_stat_value(None, PlayerStatFormat.FLAT), "--")


if __name__ == "__main__":
    unittest.main()
