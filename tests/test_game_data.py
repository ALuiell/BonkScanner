from __future__ import annotations

import unittest

from game_data import GameDataClient, MapStat, StatValue
from memory import MemoryReadError


class FakeMemory:
    def __init__(
        self,
        *,
        module_base: int = 0x10000000,
        pointers: dict[int, int] | None = None,
        integers: dict[int, int] | None = None,
        strings: dict[int, str | None] | None = None,
        broken_i32: set[int] | None = None,
        broken_ptr: set[int] | None = None,
    ) -> None:
        self.module_base = module_base
        self.pointers = pointers or {}
        self.integers = integers or {}
        self.strings = strings or {}
        self.broken_i32 = broken_i32 or set()
        self.broken_ptr = broken_ptr or set()

    def module_offset(self, _module_name: str, offset: int) -> int:
        return self.module_base + offset

    def read_ptr(self, address: int) -> int:
        if address in self.broken_ptr:
            raise MemoryReadError(f"broken ptr at 0x{address:X}")
        return self.pointers.get(address, 0)

    def read_i32(self, address: int) -> int:
        if address in self.broken_i32:
            raise MemoryReadError(f"broken i32 at 0x{address:X}")
        if address not in self.integers:
            raise MemoryReadError(f"missing i32 at 0x{address:X}")
        return self.integers[address]

    def read_mono_string(self, address: int, max_length: int = 512) -> str | None:
        del max_length
        return self.strings.get(address)


class GameDataClientTests(unittest.TestCase):
    def build_memory(self) -> FakeMemory:
        base = 0x10000000
        type_info = base + GameDataClient.TYPE_INFO_OFFSET
        class_ptr = 0x20000000
        static_fields = 0x20000100
        interactables_dict = 0x20000200
        entries = 0x20000300

        key_challenges = 0x30000000
        key_greed = 0x30000080
        key_unknown = 0x30000100
        key_moais = 0x30000180
        key_broken = 0x30000200

        container_challenges = 0x40000000
        container_greed = 0x40000080
        container_boss = 0x40000100
        container_moais = 0x40000180
        container_broken = 0x40000200

        entry0 = entries + GameDataClient.ENTRY_BASE_OFFSET
        entry1 = entry0 + GameDataClient.ENTRY_SIZE
        entry2 = entry1 + GameDataClient.ENTRY_SIZE
        entry3 = entry2 + GameDataClient.ENTRY_SIZE
        entry4 = entry3 + GameDataClient.ENTRY_SIZE
        entry5 = entry4 + GameDataClient.ENTRY_SIZE

        pointers = {
            type_info: class_ptr,
            class_ptr + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: static_fields,
            static_fields: interactables_dict,
            interactables_dict + GameDataClient.DICT_ENTRIES_OFFSET: entries,
            entry0 + GameDataClient.ENTRY_KEY_OFFSET: key_challenges,
            entry0 + GameDataClient.ENTRY_VALUE_OFFSET: container_challenges,
            entry1 + GameDataClient.ENTRY_KEY_OFFSET: key_greed,
            entry1 + GameDataClient.ENTRY_VALUE_OFFSET: container_greed,
            entry2 + GameDataClient.ENTRY_KEY_OFFSET: key_unknown,
            entry2 + GameDataClient.ENTRY_VALUE_OFFSET: container_boss,
            entry3 + GameDataClient.ENTRY_KEY_OFFSET: 0,
            entry3 + GameDataClient.ENTRY_VALUE_OFFSET: 0x40000120,
            entry4 + GameDataClient.ENTRY_KEY_OFFSET: key_moais,
            entry4 + GameDataClient.ENTRY_VALUE_OFFSET: container_moais,
            entry5 + GameDataClient.ENTRY_KEY_OFFSET: key_broken,
            entry5 + GameDataClient.ENTRY_VALUE_OFFSET: container_broken,
        }
        integers = {
            interactables_dict + GameDataClient.DICT_COUNT_OFFSET: 6,
            container_challenges + GameDataClient.CONTAINER_MAX_OFFSET: 5,
            container_challenges + GameDataClient.CONTAINER_CURRENT_OFFSET: 2,
            container_greed + GameDataClient.CONTAINER_MAX_OFFSET: 3,
            container_greed + GameDataClient.CONTAINER_CURRENT_OFFSET: 1,
            container_boss + GameDataClient.CONTAINER_MAX_OFFSET: 4,
            container_boss + GameDataClient.CONTAINER_CURRENT_OFFSET: 1,
            container_moais + GameDataClient.CONTAINER_MAX_OFFSET: 7,
            container_moais + GameDataClient.CONTAINER_CURRENT_OFFSET: 4,
        }
        strings = {
            key_challenges: "Challenges",
            key_greed: "Greed Shrines",
            key_unknown: "Boss Curses",
            key_moais: "Moais",
            key_broken: "Pots",
        }

        return FakeMemory(
            module_base=base,
            pointers=pointers,
            integers=integers,
            strings=strings,
            broken_i32={
                container_broken + GameDataClient.CONTAINER_MAX_OFFSET,
                container_broken + GameDataClient.CONTAINER_CURRENT_OFFSET,
            },
        )

    def test_get_map_stats_returns_only_known_found_stats(self) -> None:
        memory = self.build_memory()
        client = GameDataClient(memory=memory)

        stats = client.get_map_stats()

        self.assertEqual(
            stats,
            {
                MapStat.BOSS_CURSES: StatValue(current=1, max=4),
                MapStat.CHALLENGES: StatValue(current=2, max=5),
                MapStat.GREED_SHRINES: StatValue(current=1, max=3),
                MapStat.MOAIS: StatValue(current=4, max=7),
            },
        )
        self.assertNotIn(MapStat.POTS, stats)

    def test_get_map_stats_returns_empty_when_root_pointer_is_null(self) -> None:
        base = 0x10000000
        type_info = base + GameDataClient.TYPE_INFO_OFFSET
        memory = FakeMemory(module_base=base, pointers={type_info: 0})
        client = GameDataClient(memory=memory)

        self.assertEqual(client.get_map_stats(), {})

    def test_get_map_stats_raises_on_invalid_dictionary_count(self) -> None:
        base = 0x10000000
        type_info = base + GameDataClient.TYPE_INFO_OFFSET
        class_ptr = 0x20000000
        static_fields = 0x20000100
        interactables_dict = 0x20000200
        entries = 0x20000300
        memory = FakeMemory(
            module_base=base,
            pointers={
                type_info: class_ptr,
                class_ptr + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: static_fields,
                static_fields: interactables_dict,
                interactables_dict + GameDataClient.DICT_ENTRIES_OFFSET: entries,
            },
            integers={
                interactables_dict + GameDataClient.DICT_COUNT_OFFSET: 5000,
            },
        )
        client = GameDataClient(memory=memory)

        with self.assertRaises(MemoryReadError):
            client.get_map_stats()


if __name__ == "__main__":
    unittest.main()
