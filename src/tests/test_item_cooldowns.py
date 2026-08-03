"""Timed passive item cooldowns, read off the passive-inventory pass.

Every number in these tests is a live measurement from 2026-08-03 against
`Megabonk.exe`, not an invention: `cooldown = max(5, 45 - 3n)` at 42/36/33/30
for n = 1/3/4/5, an absolute mark on `MyTime.time` re-armed by exactly
`+cooldown` on a trigger and to `my_time + 2.000` on any pickup, and a clock
that freezes bit-exact under pause and on the death screen.

The class-name check is the load-bearing test here. Field offsets are per class,
so binding the wrong class does not raise -- a live sweep for floats that track
the game clock returned nine hits, of which one was this item, seven were
sub-second proc timers (two of them at `0x3C`, exactly where the lantern keeps
`cooldown`), and one was not a declared field at all.
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import struct
import unittest

from core.stats.types import InvalidItemStackCountError
from infra.memory.player_stats_client import (
    ITEM_COOLDOWN_LAYOUTS,
    PlayerStatsClient,
)
from infra.memory.reader import MemoryReadError


DICT = 0x30000000
ENTRIES = 0x31000000
LANTERN_VALUE = 0x32000000
WRENCH_VALUE = 0x32001000
LANTERN_META = 0x33000000
WRENCH_META = 0x33001000
LANTERN_NAME_PTR = 0x34000000
WRENCH_NAME_PTR = 0x34001000

LANTERN_ID = 85
WRENCH_ID = 77

MY_TIME_STATICS = 0x35000000
OWNER_STATS = 0x36000000
INVENTORY_CONTAINER = 0x37000000


def cooldown_for(stacks: int) -> float:
    """The game's own formula, live-confirmed at n = 1/3/4/5."""
    return max(5.0, 45.0 - 3.0 * stacks)


class FakeMemory:
    def __init__(self, *, ints, pointers, floats, strings) -> None:
        self.ints = ints
        self.pointers = pointers
        self.floats = floats
        self.strings = strings
        self.unreadable: set[int] = set()
        self.float_reads = 0
        self.reads = 0

    def read_ptr(self, address: int) -> int:
        self.reads += 1
        if address in self.unreadable or address not in self.pointers:
            raise MemoryReadError(f"missing ptr at 0x{address:X}")
        return self.pointers[address]

    def read_i32(self, address: int) -> int:
        self.reads += 1
        if address in self.unreadable or address not in self.ints:
            raise MemoryReadError(f"missing int at 0x{address:X}")
        return self.ints[address]

    def read_float(self, address: int) -> float:
        self.reads += 1
        self.float_reads += 1
        if address in self.unreadable or address not in self.floats:
            raise MemoryReadError(f"missing float at 0x{address:X}")
        # Round-trip through float32 so the fake cannot hold precision the
        # game's own fields do not have.
        return struct.unpack("<f", struct.pack("<f", self.floats[address]))[0]

    def read_ascii_string(self, address: int, max_length: int = 128) -> str | None:
        self.reads += 1
        if address in self.unreadable:
            raise MemoryReadError(f"unreadable string at 0x{address:X}")
        return self.strings.get(address)


def build_memory(
    *,
    stacks: int = 1,
    next_trigger: float = 42.0,
    my_time: float = 0.0,
    lantern_class: str = "ItemBobLantern",
    cooldown: float | None = None,
) -> FakeMemory:
    C = PlayerStatsClient
    entry_0 = ENTRIES + C.DICT_ENTRY_START_OFFSET
    entry_1 = entry_0 + C.DICT_ENTRY_SIZE
    layout = ITEM_COOLDOWN_LAYOUTS[LANTERN_ID]
    return FakeMemory(
        pointers={
            OWNER_STATS + C.INVENTORY_CONTAINER_OFFSET: INVENTORY_CONTAINER,
            INVENTORY_CONTAINER + C.PASSIVE_ITEM_DICT_OFFSET: DICT,
            DICT + C.DICT_ENTRIES_OFFSET: ENTRIES,
            entry_0 + C.DICT_ENTRY_VALUE_OFFSET: LANTERN_VALUE,
            entry_1 + C.DICT_ENTRY_VALUE_OFFSET: WRENCH_VALUE,
            LANTERN_VALUE + C.ITEM_CLASS_META_OFFSET: LANTERN_META,
            WRENCH_VALUE + C.ITEM_CLASS_META_OFFSET: WRENCH_META,
            LANTERN_META + C.CLASS_META_NAME_PTR_OFFSET: LANTERN_NAME_PTR,
            WRENCH_META + C.CLASS_META_NAME_PTR_OFFSET: WRENCH_NAME_PTR,
        },
        ints={
            DICT + C.DICT_COUNT_OFFSET: 2,
            DICT + C.DICT_VERSION_OFFSET: 7,
            entry_0 + C.DICT_ENTRY_KEY_OFFSET: LANTERN_ID,
            entry_1 + C.DICT_ENTRY_KEY_OFFSET: WRENCH_ID,
            LANTERN_VALUE + C.ITEM_STACK_COUNT_OFFSET: stacks,
            WRENCH_VALUE + C.ITEM_STACK_COUNT_OFFSET: 1,
        },
        floats={
            MY_TIME_STATICS + C.MY_TIME_TIME_OFFSET: my_time,
            LANTERN_VALUE + layout.cooldown_offset: (
                cooldown_for(stacks) if cooldown is None else cooldown
            ),
            LANTERN_VALUE + layout.next_trigger_offset: next_trigger,
        },
        strings={
            LANTERN_NAME_PTR: lantern_class,
            WRENCH_NAME_PTR: "ItemWrench",
        },
    )


def client_for(memory: FakeMemory) -> PlayerStatsClient:
    client = PlayerStatsClient.__new__(PlayerStatsClient)
    client.memory = memory
    client._clear_passive_item_layout()
    client._resolve_my_time_static_fields = lambda: MY_TIME_STATICS
    return client


def read(client: PlayerStatsClient):
    return client.get_item_cooldowns(OWNER_STATS)


class ItemCooldownReadTests(unittest.TestCase):
    def test_a_normal_countdown_is_the_mark_minus_the_clock(self) -> None:
        client = client_for(build_memory(my_time=100.0, next_trigger=126.52))
        snapshot = read(client)

        self.assertEqual(snapshot.my_time_seconds, 100.0)
        (reading,) = snapshot.readings
        self.assertEqual(reading.item_id, LANTERN_ID)
        self.assertEqual(reading.stack_count, 1)
        self.assertAlmostEqual(reading.cooldown_seconds, 42.0, places=4)
        self.assertAlmostEqual(reading.next_trigger_time, 126.52, places=3)
        self.assertAlmostEqual(
            reading.next_trigger_time - snapshot.my_time_seconds, 26.52, places=3
        )

    def test_no_remaining_time_is_computed_at_read_time(self) -> None:
        """The record carries the mark, never a countdown.

        A `remaining` frozen here would be stale by however long it waits to be
        painted -- and the overlay repaints at 500 ms against a 1 s read lane,
        so it always waits. Subtraction belongs to the renderer.
        """
        (reading,) = read(client_for(build_memory())).readings
        self.assertFalse(
            [name for name in vars(reading) if "remain" in name.lower()],
            "a remaining time was baked into the reading",
        )

    def test_stack_scaling_matches_the_game_formula(self) -> None:
        for stacks, expected in ((1, 42.0), (3, 36.0), (4, 33.0), (5, 30.0)):
            with self.subTest(stacks=stacks):
                (reading,) = read(client_for(build_memory(stacks=stacks))).readings
                self.assertEqual(reading.stack_count, stacks)
                self.assertAlmostEqual(reading.cooldown_seconds, expected, places=4)

    def test_the_mark_is_passed_through_when_it_is_already_in_the_past(self) -> None:
        """`remaining` went to -0.01 for one tick before a re-arm was observed.

        The read side must hand that through rather than clamp it: clamping is
        a rendering decision, and a reader that silently floors at zero makes
        "just fired" indistinguishable from "no reading".
        """
        (reading,) = read(client_for(build_memory(my_time=126.53, next_trigger=126.52))).readings
        self.assertLess(reading.next_trigger_time - 126.53, 0.0)

    def test_a_trigger_moves_the_mark_forward_by_one_cooldown(self) -> None:
        memory = build_memory(my_time=126.51, next_trigger=126.52)
        client = client_for(memory)
        before = read(client).readings[0].next_trigger_time

        layout = ITEM_COOLDOWN_LAYOUTS[LANTERN_ID]
        memory.floats[MY_TIME_STATICS + PlayerStatsClient.MY_TIME_TIME_OFFSET] = 126.60
        memory.floats[LANTERN_VALUE + layout.next_trigger_offset] = 168.52

        after = read(client).readings[0].next_trigger_time
        self.assertAlmostEqual(after - before, 42.0, places=3)

    def test_a_pickup_moves_the_mark_backwards_to_two_seconds(self) -> None:
        """Measured: any pickup re-arms to exactly `my_time + 2.000`.

        For an item mid-cooldown that is a jump *backwards* of tens of seconds,
        which is why nothing may extrapolate the mark and why a "just fired"
        pulse has to watch for an increase rather than a change.
        """
        memory = build_memory(stacks=3, my_time=1518.723, next_trigger=1557.659)
        client = client_for(memory)
        before = read(client).readings[0]
        self.assertAlmostEqual(before.next_trigger_time - 1518.723, 38.936, places=3)

        layout = ITEM_COOLDOWN_LAYOUTS[LANTERN_ID]
        memory.floats[LANTERN_VALUE + layout.next_trigger_offset] = 1520.723

        after = read(client).readings[0]
        self.assertLess(after.next_trigger_time, before.next_trigger_time)
        self.assertAlmostEqual(after.next_trigger_time - 1518.723, 2.0, places=3)

    def test_a_frozen_clock_yields_an_identical_reading_every_pass(self) -> None:
        """Pause and the death screen both freeze `my_time` bit-exact.

        Measured across 385 consecutive reads on the death screen and 68 under
        pause. Every read succeeds, so nothing here can distinguish the two --
        that is a run-lifecycle question, deliberately not this method's.
        """
        client = client_for(build_memory(my_time=2146.530, next_trigger=2164.473))
        first = read(client)
        readings = [read(client) for _ in range(5)]

        for snapshot in readings:
            self.assertEqual(snapshot.my_time_seconds, first.my_time_seconds)
            self.assertEqual(snapshot.readings, first.readings)


class ItemCooldownBindingTests(unittest.TestCase):
    def test_an_item_with_no_layout_entry_produces_no_reading(self) -> None:
        client = client_for(build_memory())
        readings = read(client).readings
        self.assertEqual([r.item_id for r in readings], [LANTERN_ID])

    def test_a_class_name_mismatch_refuses_rather_than_reads(self) -> None:
        """The check that stops a plausible-looking wrong number.

        Same enum id, different class behind it -- which is what a game update
        renumbering ids looks like. Reading `0x3C`/`0x40` anyway would return
        well-formed floats, so refusing is the only way this fails loudly enough
        to notice.
        """
        client = client_for(build_memory(lantern_class="ItemSpikyShield"))
        self.assertEqual(read(client).readings, ())

    def test_an_unreadable_class_name_refuses_and_retries_next_pass(self) -> None:
        memory = build_memory()
        memory.unreadable.add(LANTERN_NAME_PTR)
        client = client_for(memory)
        self.assertEqual(read(client).readings, ())

        # The refusal must not be memoised into the layout: the class name is
        # resolved on the clean walk, so a slot dropped for one pass has to come
        # back on the next rather than wait for the dictionary to change.
        memory.unreadable.discard(LANTERN_NAME_PTR)
        client._clear_passive_item_layout()
        self.assertEqual(len(read(client).readings), 1)

    def test_a_torn_cooldown_field_skips_that_item_only(self) -> None:
        layout = ITEM_COOLDOWN_LAYOUTS[LANTERN_ID]
        memory = build_memory()
        memory.unreadable.add(LANTERN_VALUE + layout.cooldown_offset)
        client = client_for(memory)

        snapshot = read(client)
        self.assertEqual(snapshot.readings, ())
        # The clock still came back -- an unreadable item is not an unreadable
        # pass, and the caller needs to tell those apart.
        self.assertIsNotNone(snapshot.my_time_seconds)

    def test_a_zero_cooldown_is_skipped(self) -> None:
        client = client_for(build_memory(cooldown=0.0))
        self.assertEqual(read(client).readings, ())

    def test_a_torn_stack_count_aborts_the_batch(self) -> None:
        """Fail closed, matching the item ladders' policy exactly."""
        memory = build_memory()
        client = client_for(memory)
        read(client)  # warm the layout so the cached stack path is the one used

        original = memory.read_i32
        toggle = {"n": 0}

        def unstable(address: int) -> int:
            if address == LANTERN_VALUE + PlayerStatsClient.ITEM_STACK_COUNT_OFFSET:
                toggle["n"] += 1
                return toggle["n"]
            return original(address)

        memory.read_i32 = unstable
        with self.assertRaises(InvalidItemStackCountError):
            read(client)

    def test_a_missing_dictionary_still_reports_the_clock(self) -> None:
        memory = build_memory(my_time=17.5)
        memory.pointers[INVENTORY_CONTAINER + PlayerStatsClient.PASSIVE_ITEM_DICT_OFFSET] = 0
        memory.unreadable.add(OWNER_STATS + PlayerStatsClient.PLAYER_INVENTORY_OFFSET)
        client = client_for(memory)

        snapshot = read(client)
        self.assertEqual(snapshot.my_time_seconds, 17.5)
        self.assertEqual(snapshot.readings, ())


class DrainedDictionaryTests(unittest.TestCase):
    """The container route can resolve a live pointer to a dead dictionary.

    Measured 2026-08-03 mid-run, 25 items held: `owner_stats +0xA0 -> +0x50`
    gave a non-null dictionary with `count=0, version=0, entries=0x0`, while
    `+0x28 -> +0x20 -> +0x10` gave the real one with `count=25`. A resolver that
    stops at the first non-null pointer picks the corpse.

    This was not theoretical when it was found: `get_expected_chest_inputs`
    reported `key_count=0` for a player holding `Key x1`.
    """

    def _drain_the_container_route(self, memory: FakeMemory) -> int:
        C = PlayerStatsClient
        drained = 0x38000000
        memory.pointers[INVENTORY_CONTAINER + C.PASSIVE_ITEM_DICT_OFFSET] = drained
        memory.pointers[drained + C.DICT_ENTRIES_OFFSET] = 0
        memory.ints[drained + C.DICT_COUNT_OFFSET] = 0
        memory.ints[drained + C.DICT_VERSION_OFFSET] = 0
        # The live inventory now hangs off the fallback route only.
        memory.pointers[OWNER_STATS + C.PLAYER_INVENTORY_OFFSET] = 0x39000000
        memory.pointers[0x39000000 + C.ITEM_INVENTORY_OFFSET] = 0x39001000
        memory.pointers[0x39001000 + C.ITEM_INVENTORY_ITEMS_DICT_OFFSET] = DICT
        return drained

    def test_the_resolver_skips_a_dictionary_with_no_entries(self) -> None:
        memory = build_memory()
        drained = self._drain_the_container_route(memory)
        client = client_for(memory)

        chosen = client._resolve_preferred_passive_item_dict(OWNER_STATS)
        self.assertNotEqual(chosen, drained, "resolver picked the drained dictionary")
        self.assertEqual(chosen, DICT)

    def test_cooldowns_are_read_through_the_live_dictionary(self) -> None:
        memory = build_memory(my_time=100.0, next_trigger=133.0, stacks=4)
        self._drain_the_container_route(memory)
        client = client_for(memory)

        (reading,) = read(client).readings
        self.assertEqual(reading.stack_count, 4)
        self.assertAlmostEqual(reading.cooldown_seconds, 33.0, places=4)

    def test_an_empty_inventory_still_resolves_to_a_dictionary(self) -> None:
        """Both routes empty is "owns nothing yet", not a failed read."""
        C = PlayerStatsClient
        memory = build_memory()
        drained = self._drain_the_container_route(memory)
        memory.pointers[0x39001000 + C.ITEM_INVENTORY_ITEMS_DICT_OFFSET] = 0
        client = client_for(memory)

        self.assertEqual(client._resolve_preferred_passive_item_dict(OWNER_STATS), drained)

    def test_a_stale_layout_from_another_dictionary_is_not_reused(self) -> None:
        """The memo belongs to one dictionary and may not outlive it.

        Reproduces the accident that hid the bug: a live layout cached by an
        earlier call made a read against a *drained* dictionary return
        correct-looking numbers.
        """
        memory = build_memory()
        client = client_for(memory)
        self.assertEqual(len(read(client).readings), 1)

        C = PlayerStatsClient
        drained = 0x38000000
        memory.pointers[INVENTORY_CONTAINER + C.PASSIVE_ITEM_DICT_OFFSET] = drained
        memory.pointers[drained + C.DICT_ENTRIES_OFFSET] = 0
        memory.ints[drained + C.DICT_COUNT_OFFSET] = 0
        memory.ints[drained + C.DICT_VERSION_OFFSET] = 0
        memory.unreadable.add(OWNER_STATS + C.PLAYER_INVENTORY_OFFSET)

        self.assertEqual(
            read(client).readings,
            (),
            "readings were served from a layout belonging to another dictionary",
        )


class ItemCooldownCostTests(unittest.TestCase):
    def test_the_warm_pass_does_not_walk_the_dictionary_again(self) -> None:
        """The whole argument for riding the existing items lane.

        A cold pass pays for the walk; every pass after it pays for the clock,
        the stack counts and two floats. If this regresses, the feature has
        quietly grown a second walk of the inventory.

        The counts are **exact on purpose.** This assertion started life as
        "warm < cold" and was vacuous: a tamper that walked the dictionary twice
        inflated *both* passes, so the comparison still held while the cost had
        doubled. A defect that scales both sides is invisible to a relative
        bound, which is the whole failure mode a cost test exists to catch.
        """
        memory = build_memory()
        client = client_for(memory)

        read(client)
        self.assertEqual(memory.reads, 23, "cold pass: resolve, walk, clock, fields")

        memory.reads = 0
        memory.float_reads = 0
        read(client)

        self.assertEqual(
            memory.reads,
            16,
            "warm pass grew: something is re-walking the dictionary",
        )
        self.assertEqual(
            memory.float_reads,
            3,
            "expected exactly the clock plus the one item's cooldown pair",
        )


if __name__ == "__main__":
    unittest.main()
