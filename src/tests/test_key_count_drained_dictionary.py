"""The Key counter against a drained passive-item dictionary.

The passive inventory is reachable by two pointer routes, and **either can hand
back a live pointer to an emptied dictionary**. Measured live on 2026-08-03,
mid-run with 25 items held:

    owner_stats +0xA0 -> +0x50            count=0  version=0  entries=0x0
    owner_stats +0x28 -> +0x20 -> +0x10   count=25 version=25

`_resolve_preferred_passive_item_dict` used to return the first *non-null*
pointer, so it picked the corpse and never looked further. That is not a
theoretical failure: with the game in that state, `get_expected_chest_inputs`
reported `key_count=0` for a player visibly holding `Key x1`.

The Key is not special to any of this -- `_get_cached_key_count` resolves the
dictionary and then searches it by name, exactly as it would for any other
item. That is why these tests need no Key drop to be meaningful, and why the
fix is verified here rather than by waiting for one in a live run.

The drained state was reached by restarting a run **without restarting the
game**. A session that plays one run from a fresh launch never enters it, which
matches what the recordings show: `950k.jsonl` tracks `keys_count` correctly
from 1 to 7 across 670 snapshots holding a Key, and `970k.jsonl` predates the
field entirely. No recorded run carries the signature of this bug.
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest

from infra.memory.player_stats_client import PlayerStatsClient
from infra.memory.reader import MemoryReadError


OWNER_STATS = 0x40000000
CONTAINER = 0x41000000
DRAINED_DICT = 0x42000000

PLAYER_INVENTORY = 0x43000000
ITEM_INVENTORY = 0x43001000
LIVE_DICT = 0x44000000
LIVE_ENTRIES = 0x45000000

KEY_VALUE = 0x46000000
ANVIL_VALUE = 0x46001000
KEY_META = 0x47000000
ANVIL_META = 0x47001000
KEY_NAME_PTR = 0x48000000
ANVIL_NAME_PTR = 0x48001000


class FakeMemory:
    def __init__(self, *, pointers, ints, strings) -> None:
        self.pointers = pointers
        self.ints = ints
        self.strings = strings

    def read_ptr(self, address: int) -> int:
        if address not in self.pointers:
            raise MemoryReadError(f"missing ptr at 0x{address:X}")
        return self.pointers[address]

    def read_i32(self, address: int) -> int:
        if address not in self.ints:
            raise MemoryReadError(f"missing int at 0x{address:X}")
        return self.ints[address]

    def read_ascii_string(self, address: int, max_length: int = 128) -> str | None:
        return self.strings.get(address)


def build_memory(*, key_stack: int = 1, live_count: int = 2, live_version: int = 11):
    """The measured shape: a drained container route, a live inventory route."""
    C = PlayerStatsClient
    entry_0 = LIVE_ENTRIES + C.DICT_ENTRY_START_OFFSET
    entry_1 = entry_0 + C.DICT_ENTRY_SIZE
    return FakeMemory(
        pointers={
            OWNER_STATS + C.INVENTORY_CONTAINER_OFFSET: CONTAINER,
            CONTAINER + C.PASSIVE_ITEM_DICT_OFFSET: DRAINED_DICT,
            DRAINED_DICT + C.DICT_ENTRIES_OFFSET: 0,
            OWNER_STATS + C.PLAYER_INVENTORY_OFFSET: PLAYER_INVENTORY,
            PLAYER_INVENTORY + C.ITEM_INVENTORY_OFFSET: ITEM_INVENTORY,
            ITEM_INVENTORY + C.ITEM_INVENTORY_ITEMS_DICT_OFFSET: LIVE_DICT,
            LIVE_DICT + C.DICT_ENTRIES_OFFSET: LIVE_ENTRIES,
            entry_0 + C.DICT_ENTRY_VALUE_OFFSET: KEY_VALUE,
            entry_1 + C.DICT_ENTRY_VALUE_OFFSET: ANVIL_VALUE,
            KEY_VALUE + C.ITEM_CLASS_META_OFFSET: KEY_META,
            ANVIL_VALUE + C.ITEM_CLASS_META_OFFSET: ANVIL_META,
            KEY_META + C.CLASS_META_NAME_PTR_OFFSET: KEY_NAME_PTR,
            ANVIL_META + C.CLASS_META_NAME_PTR_OFFSET: ANVIL_NAME_PTR,
        },
        ints={
            DRAINED_DICT + C.DICT_COUNT_OFFSET: 0,
            DRAINED_DICT + C.DICT_VERSION_OFFSET: 0,
            LIVE_DICT + C.DICT_COUNT_OFFSET: live_count,
            LIVE_DICT + C.DICT_VERSION_OFFSET: live_version,
            entry_0 + C.DICT_ENTRY_KEY_OFFSET: 60,
            entry_1 + C.DICT_ENTRY_KEY_OFFSET: 41,
            KEY_VALUE + C.ITEM_STACK_COUNT_OFFSET: key_stack,
            ANVIL_VALUE + C.ITEM_STACK_COUNT_OFFSET: 1,
        },
        strings={KEY_NAME_PTR: "ItemKey", ANVIL_NAME_PTR: "ItemAnvil"},
    )


def client_for(memory) -> PlayerStatsClient:
    client = PlayerStatsClient.__new__(PlayerStatsClient)
    client.memory = memory
    client._clear_cached_key_address()
    client._clear_passive_item_layout()
    return client


class DrainedDictionaryKeyCountTests(unittest.TestCase):
    def test_the_key_is_counted_through_the_live_dictionary(self) -> None:
        """The measured failure, reproduced: `Key x1` held, count reported 0."""
        client = client_for(build_memory(key_stack=1))
        self.assertEqual(client._get_cached_key_count(OWNER_STATS), 1)

    def test_a_larger_stack_is_counted(self) -> None:
        client = client_for(build_memory(key_stack=4))
        self.assertEqual(client._get_cached_key_count(OWNER_STATS), 4)

    def test_the_lookup_is_by_name_and_not_special_to_the_key(self) -> None:
        """Why no Key drop was needed to verify this.

        `_get_cached_key_count` is a dictionary resolve plus a name search.
        Anything the player holds exercises the identical path, so proving the
        resolver reaches the live dictionary proves the Key case with it.
        """
        client = client_for(build_memory())
        chosen = client._resolve_preferred_passive_item_dict(OWNER_STATS)
        self.assertEqual(chosen, LIVE_DICT)
        for name in ("Key", "Anvil"):
            with self.subTest(item=name):
                self.assertNotEqual(
                    client._find_passive_item_stack_address(chosen, name),
                    0,
                    f"{name} was not found in the live dictionary",
                )

    def test_the_drained_dictionary_alone_finds_nothing(self) -> None:
        """The old behaviour, pinned so the regression is recognisable.

        Searching the corpse is not an error -- it returns 0, which reads as
        "the player holds no Key". That silence is the whole reason the bug
        survived: nothing anywhere raised.
        """
        client = client_for(build_memory())
        self.assertEqual(
            client._find_passive_item_stack_address(DRAINED_DICT, "Key"), 0
        )

    def test_the_cached_address_is_dropped_when_the_dictionary_switches(self) -> None:
        """The half that was reasoned about rather than tested.

        `_cached_key_stack_address` is validated against the quadruple
        (dictionary, entries, count, version). A switch between the two routes
        changes all four, so the cache must rebuild -- otherwise a Key address
        from one dictionary would be read against the other, which is a live
        pointer into an object that is no longer the one being counted.
        """
        memory = build_memory(key_stack=3)
        client = client_for(memory)
        self.assertEqual(client._get_cached_key_count(OWNER_STATS), 3)
        cached = client._cached_key_stack_address
        self.assertEqual(client._cached_key_dict, LIVE_DICT)

        # The container route comes back to life holding a different inventory;
        # the resolver now prefers it, and the cached address belongs elsewhere.
        C = PlayerStatsClient
        other_entries = 0x49000000
        entry_0 = other_entries + C.DICT_ENTRY_START_OFFSET
        other_key_value = 0x4A000000
        memory.pointers[DRAINED_DICT + C.DICT_ENTRIES_OFFSET] = other_entries
        memory.pointers[entry_0 + C.DICT_ENTRY_VALUE_OFFSET] = other_key_value
        memory.pointers[other_key_value + C.ITEM_CLASS_META_OFFSET] = KEY_META
        memory.ints[DRAINED_DICT + C.DICT_COUNT_OFFSET] = 1
        memory.ints[DRAINED_DICT + C.DICT_VERSION_OFFSET] = 1
        memory.ints[entry_0 + C.DICT_ENTRY_KEY_OFFSET] = 60
        memory.ints[other_key_value + C.ITEM_STACK_COUNT_OFFSET] = 9

        self.assertEqual(client._get_cached_key_count(OWNER_STATS), 9)
        self.assertEqual(client._cached_key_dict, DRAINED_DICT)
        self.assertNotEqual(
            client._cached_key_stack_address,
            cached,
            "the Key address survived a switch to a different dictionary",
        )

    def test_a_dictionary_with_an_allocated_but_empty_entry_array_is_skipped(self) -> None:
        """The second drained shape, and the one the other tests miss.

        Live, the container route showed `entries=0x0` -- a null array, caught
        by the first arm of the liveness check. A dictionary that *had* items
        and lost them keeps its entry array allocated and reports `count=0`
        instead, and only the second arm sees that. A tamper that deleted the
        count check passed the whole file before this case existed, so the arm
        was carrying no weight.

        Which shape the game actually produces here is not established -- only
        the null-array one was measured. This arm is defensive, and is tested
        as such rather than presented as a reproduction.
        """
        C = PlayerStatsClient
        memory = build_memory()
        memory.pointers[DRAINED_DICT + C.DICT_ENTRIES_OFFSET] = 0x4B000000
        memory.ints[DRAINED_DICT + C.DICT_COUNT_OFFSET] = 0
        client = client_for(memory)

        self.assertFalse(client._dictionary_has_entries(DRAINED_DICT))
        self.assertEqual(client._resolve_preferred_passive_item_dict(OWNER_STATS), LIVE_DICT)
        self.assertEqual(client._get_cached_key_count(OWNER_STATS), 1)

    def test_both_routes_empty_reports_no_key_rather_than_failing(self) -> None:
        """An inventory that genuinely holds nothing is not an error."""
        C = PlayerStatsClient
        memory = build_memory()
        memory.pointers[LIVE_DICT + C.DICT_ENTRIES_OFFSET] = 0
        memory.ints[LIVE_DICT + C.DICT_COUNT_OFFSET] = 0
        client = client_for(memory)
        self.assertEqual(client._get_cached_key_count(OWNER_STATS), 0)


if __name__ == "__main__":
    unittest.main()
