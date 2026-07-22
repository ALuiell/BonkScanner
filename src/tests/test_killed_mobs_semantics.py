"""Step 28c commit 1: an absent ``"kills"`` entry in a *valid* RunStats
dictionary is the domain value zero, not a memory-read failure.

step_28_plan.md section 12.1. The game creates that dictionary entry lazily, on
its first increment, so before the first kill it is simply absent -- and
``_get_cached_chests_bought``, this method's structural twin, has always
returned 0 at the identical decision point. Raising instead made every kills
read fail for the opening stretch of a run, and the shared ``try`` in
``_refresh_combat_metrics_task`` then discarded a run timer that had already
been read successfully.

The two paths must stay distinguishable: a *structural* failure -- uninitialised
type info, static fields, dictionary or entries array, or an invalid entry count
-- still raises ``MemoryReadError``. Each is tested separately below, because a
single "does it raise" test would pass just as well if the semantic change had
never been made.
"""
from __future__ import annotations

import src  # noqa: F401

import unittest

from infra.memory.player_stats_client import PlayerStatsClient
from infra.memory.reader import MemoryReadError

CLASS_PTR = 0x1000
STATIC_FIELDS = 0x2000
STATS_DICT = 0x3000
ENTRIES = 0x4000


class ScriptedReader:
    """A RunStats dictionary scripted down to the pointer level.

    Every structural stage is independently breakable, which is what lets the
    tests below separate "valid dictionary, no kills entry" from each of the
    structural failures that must still raise.
    """

    def __init__(
        self,
        *,
        names=("chestsBought", "goldEarned"),
        class_ptr=CLASS_PTR,
        static_fields=STATIC_FIELDS,
        stats_dict=STATS_DICT,
        entries=ENTRIES,
        count=None,
        kills_value=7.0,
    ) -> None:
        self.names = list(names)
        self.class_ptr = class_ptr
        self.static_fields = static_fields
        self.stats_dict = stats_dict
        self.entries = entries
        self.count = len(self.names) if count is None else count
        self.kills_value = kills_value

    def module_offset(self, _module: str, offset: int) -> int:
        return offset

    def read_ptr(self, address: int) -> int:
        c = PlayerStatsClient
        if address == c.RUN_STATS_TYPE_INFO_OFFSET:
            return self.class_ptr
        if address == self.class_ptr + c.CLASS_STATIC_FIELDS_OFFSET:
            return self.static_fields
        if address == self.static_fields + c.RUN_STATS_DICT_OFFSET:
            return self.stats_dict
        if address == self.stats_dict + c.DICT_ENTRIES_OFFSET:
            return self.entries
        return address  # an entry's key pointer

    def read_i32(self, address: int) -> int:
        c = PlayerStatsClient
        if address == self.stats_dict + c.DICT_COUNT_OFFSET:
            return self.count
        if address == self.stats_dict + c.DICT_VERSION_OFFSET:
            return 1
        return 0  # entry hash codes: non-negative, so no entry is skipped

    def read_float(self, _address: int) -> float:
        return self.kills_value

    def read_mono_string(self, address: int):
        c = PlayerStatsClient
        index = (address - (self.entries + c.DICT_ENTRY_START_OFFSET)) // c.DICT_ENTRY_SIZE
        if 0 <= index < len(self.names):
            return self.names[index]
        return None


def _client(**kwargs) -> PlayerStatsClient:
    return PlayerStatsClient(memory=ScriptedReader(**kwargs))


class AbsentKillsEntryIsZeroTests(unittest.TestCase):
    def test_valid_dictionary_without_a_kills_entry_reads_zero(self) -> None:
        """The pre-first-kill state. This is the whole defect."""
        client = _client(names=("chestsBought", "goldEarned", "damageDealt"))

        self.assertEqual(client.get_killed_mobs(), 0)

    def test_valid_dictionary_with_a_kills_entry_reads_the_value(self) -> None:
        client = _client(names=("chestsBought", "kills"), kills_value=42.0)

        self.assertEqual(client.get_killed_mobs(), 42)

    def test_an_empty_but_valid_dictionary_reads_zero(self) -> None:
        client = _client(names=(), count=0)

        self.assertEqual(client.get_killed_mobs(), 0)

    def test_it_matches_its_structural_twin(self) -> None:
        """`_get_cached_chests_bought` and `_get_cached_killed_mobs` are
        structural twins; the point of this slice is that they now agree at the
        one decision point where they used to disagree."""
        client = _client(names=("goldEarned",))

        self.assertEqual(client.get_killed_mobs(), client._get_cached_chests_bought())
        self.assertEqual(client.get_killed_mobs(), 0)


class StructuralFailuresStillRaiseTests(unittest.TestCase):
    """Each structural stage, separately. A single combined test would pass
    even if the semantic change had gone too far and swallowed these."""

    def test_uninitialised_type_info_raises(self) -> None:
        client = _client(class_ptr=0)

        with self.assertRaises(MemoryReadError) as caught:
            client.get_killed_mobs()
        self.assertIn("type info", str(caught.exception))

    def test_uninitialised_static_fields_raises(self) -> None:
        client = _client(static_fields=0)

        with self.assertRaises(MemoryReadError) as caught:
            client.get_killed_mobs()
        self.assertIn("static fields", str(caught.exception))

    def test_uninitialised_dictionary_raises(self) -> None:
        client = _client(stats_dict=0)

        with self.assertRaises(MemoryReadError) as caught:
            client.get_killed_mobs()
        self.assertIn("dictionary is not initialized", str(caught.exception))

    def test_uninitialised_entries_array_raises(self) -> None:
        client = _client(entries=0)

        with self.assertRaises(MemoryReadError) as caught:
            client.get_killed_mobs()
        self.assertIn("entries are not initialized", str(caught.exception))

    def test_invalid_entry_count_raises(self) -> None:
        client = _client(count=PlayerStatsClient.MAX_RUN_STATS_ENTRIES + 1)

        with self.assertRaises(MemoryReadError) as caught:
            client.get_killed_mobs()
        self.assertIn("count is invalid", str(caught.exception))

    def test_negative_entry_count_raises(self) -> None:
        client = _client(count=-1)

        with self.assertRaises(MemoryReadError):
            client.get_killed_mobs()


if __name__ == "__main__":
    unittest.main()
