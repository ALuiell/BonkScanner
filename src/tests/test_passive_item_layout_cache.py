"""The passive-inventory layout cache.

`_read_passive_item_dictionary` costs 4 reads per entry: the value pointer, the
key id, and two for the stabilised stack count. Only the last pair can change
while the dictionary's `_version` holds -- a .NET dictionary bumps it on every
Add/Remove, and an item levelling up mutates the value object rather than the
dictionary. So the slot layout is memoised and only the stack counts are
re-read, halving the walk.

The invalidation is not new: `_get_cached_key_count` has validated the Key
entry's address against exactly this quadruple (dictionary pointer, entries
pointer, count, `_version`) in production since before the fast lane existed.
This reuses that invariant across the whole dictionary instead of one entry.
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest

from core.stats.types import InvalidItemStackCountError
from infra.memory.player_stats_client import PlayerStatsClient
from infra.memory.reader import MemoryReadError


DICT = 0x30000000
ENTRIES = 0x31000000
ANVIL_VALUE = 0x32000000
WRENCH_VALUE = 0x32001000
ANVIL_ID = 41
WRENCH_ID = 77


class CountingMemory:
    """Only the reads this walk performs, each one counted."""

    def __init__(self, *, ints: dict[int, int], pointers: dict[int, int]) -> None:
        self.ints = ints
        self.pointers = pointers
        self.ptr_reads = 0
        self.int_reads = 0

    @property
    def reads(self) -> int:
        return self.ptr_reads + self.int_reads

    def read_ptr(self, address: int) -> int:
        self.ptr_reads += 1
        if address not in self.pointers:
            raise MemoryReadError(f"missing ptr at 0x{address:X}")
        return self.pointers[address]

    def read_i32(self, address: int) -> int:
        self.int_reads += 1
        if address not in self.ints:
            raise MemoryReadError(f"missing int at 0x{address:X}")
        return self.ints[address]

    def read_ascii_string(self, address: int, max_length: int = 128) -> str | None:
        raise MemoryReadError(f"missing ascii string at 0x{address:X}")


def build_memory(*, anvil_stack: int = 1, wrench_stack: int = 1, version: int = 7):
    C = PlayerStatsClient
    entry_0 = ENTRIES + C.DICT_ENTRY_START_OFFSET
    entry_1 = entry_0 + C.DICT_ENTRY_SIZE
    return CountingMemory(
        pointers={
            DICT + C.DICT_ENTRIES_OFFSET: ENTRIES,
            entry_0 + C.DICT_ENTRY_VALUE_OFFSET: ANVIL_VALUE,
            entry_1 + C.DICT_ENTRY_VALUE_OFFSET: WRENCH_VALUE,
        },
        ints={
            DICT + C.DICT_COUNT_OFFSET: 2,
            DICT + C.DICT_VERSION_OFFSET: version,
            entry_0 + C.DICT_ENTRY_KEY_OFFSET: ANVIL_ID,
            entry_1 + C.DICT_ENTRY_KEY_OFFSET: WRENCH_ID,
            ANVIL_VALUE + C.ITEM_STACK_COUNT_OFFSET: anvil_stack,
            WRENCH_VALUE + C.ITEM_STACK_COUNT_OFFSET: wrench_stack,
        },
    )


def client_for(memory) -> PlayerStatsClient:
    client = PlayerStatsClient.__new__(PlayerStatsClient)
    client.memory = memory
    client._clear_passive_item_layout()
    return client


class PassiveItemLayoutCacheTests(unittest.TestCase):
    def test_the_cached_pass_reads_only_the_stack_counts(self) -> None:
        memory = build_memory()
        client = client_for(memory)

        first = client._read_passive_item_dictionary(DICT)
        cold_reads = memory.reads
        second = client._read_passive_item_dictionary(DICT)
        warm_reads = memory.reads - cold_reads

        self.assertEqual(first, second)
        # Cold: entries + count + version, then 4 per entry.
        self.assertEqual(cold_reads, 3 + 4 * 2)
        # Warm: entries + count + version, then only the stabilised stack pair.
        self.assertEqual(warm_reads, 3 + 2 * 2)
        self.assertLess(warm_reads, cold_reads)

    def test_a_level_up_is_seen_through_the_cache(self) -> None:
        """The case the cache must not break. Levelling an item mutates the
        value object's stack count without touching the dictionary, so
        `_version` does not move -- and the stack counts are exactly what the
        cached path still reads."""
        memory = build_memory(anvil_stack=1)
        client = client_for(memory)
        self.assertEqual(
            client._read_passive_item_dictionary(DICT), ("Anvil x1", "Wrench x1")
        )

        memory.ints[ANVIL_VALUE + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET] = 4

        self.assertEqual(
            client._read_passive_item_dictionary(DICT), ("Anvil x4", "Wrench x1")
        )

    def test_a_version_bump_rebuilds_the_layout(self) -> None:
        """An Add or Remove changes which slots hold what. `_version` is the
        signal, and it must force a full walk even when the entries pointer and
        the count happen to be unchanged (a Remove followed by an Add)."""
        memory = build_memory(version=7)
        client = client_for(memory)
        client._read_passive_item_dictionary(DICT)

        C = PlayerStatsClient
        entry_0 = ENTRIES + C.DICT_ENTRY_START_OFFSET
        memory.ints[DICT + C.DICT_VERSION_OFFSET] = 8
        memory.ints[entry_0 + C.DICT_ENTRY_KEY_OFFSET] = 78  # Beacon
        memory.pointers[entry_0 + C.DICT_ENTRY_VALUE_OFFSET] = 0x32002000
        memory.ints[0x32002000 + C.ITEM_STACK_COUNT_OFFSET] = 2

        self.assertEqual(
            client._read_passive_item_dictionary(DICT), ("Beacon x2", "Wrench x1")
        )

    def test_a_different_dictionary_is_not_served_from_the_cache(self) -> None:
        """`get_passive_items` has two candidate dictionaries and falls back
        between them. A layout memoised for one must never answer for the
        other."""
        memory = build_memory()
        client = client_for(memory)
        client._read_passive_item_dictionary(DICT)

        with self.assertRaises(MemoryReadError):
            client._read_passive_item_dictionary(0x39000000)

    def test_a_torn_walk_is_not_memoised(self) -> None:
        """A pass that skipped an entry saw an incomplete inventory. Caching it
        would keep that item invisible until the next Add/Remove instead of
        until the next read."""
        C = PlayerStatsClient
        memory = build_memory()
        entry_1 = ENTRIES + C.DICT_ENTRY_START_OFFSET + C.DICT_ENTRY_SIZE
        del memory.pointers[entry_1 + C.DICT_ENTRY_VALUE_OFFSET]
        client = client_for(memory)

        self.assertEqual(client._read_passive_item_dictionary(DICT), ("Anvil x1",))
        self.assertIsNone(client._cached_item_layout)

        memory.pointers[entry_1 + C.DICT_ENTRY_VALUE_OFFSET] = WRENCH_VALUE
        self.assertEqual(
            client._read_passive_item_dictionary(DICT), ("Anvil x1", "Wrench x1")
        )

    def test_a_torn_stack_count_still_raises_on_the_cached_path(self) -> None:
        """`InvalidItemStackCountError` must reach the caller from both paths.
        Smoothing it into a plausible count here would put a fabricated stack
        into the tracked-item ladders."""
        memory = build_memory()
        client = client_for(memory)
        client._read_passive_item_dictionary(DICT)

        unstable = iter([3, 9, 3, 9])
        original = memory.read_i32

        def read_i32(address: int) -> int:
            if address == ANVIL_VALUE + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET:
                memory.int_reads += 1
                return next(unstable)
            return original(address)

        memory.read_i32 = read_i32

        with self.assertRaises(InvalidItemStackCountError):
            client._read_passive_item_dictionary(DICT)


if __name__ == "__main__":
    unittest.main()
