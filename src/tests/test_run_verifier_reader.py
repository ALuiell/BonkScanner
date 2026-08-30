from __future__ import annotations

import unittest

from infra.memory.player_stats_client import PlayerStatsClient


class _Memory:
    def __init__(self) -> None:
        self.ptrs = {}
        self.ints = {}
        self.floats = {}
        self.u8 = {}
        self.float_sequences = {}
        self.module_base = 0x10000000

    def module_offset(self, _module_name, offset):
        return self.module_base + offset

    def read_ptr(self, address):
        return self.ptrs.get(address, 0)

    def read_i32(self, address):
        return self.ints.get(address, 0)

    def read_float(self, address):
        sequence = self.float_sequences.get(address)
        if sequence:
            return sequence.pop(0)
        return self.floats.get(address, 0.0)

    def read_u8(self, address):
        return self.u8.get(address, 0)


def _build_memory() -> tuple[_Memory, int, dict[int, int]]:
    memory = _Memory()
    owner = 0x1000
    dictionaries = {"final": 0x2000, "raw": 0x3000, "components": 0x4000}
    entries = {"final": 0x5000, "raw": 0x6000, "components": 0x7000}
    memory.ptrs[owner + 0x10] = dictionaries["final"]
    memory.ptrs[owner + 0x18] = dictionaries["raw"]
    memory.ptrs[owner + 0x20] = dictionaries["components"]
    for name in dictionaries:
        memory.ptrs[dictionaries[name] + 0x18] = entries[name]
        memory.ints[dictionaries[name] + 0x20] = 57

    final_addresses = {}
    for stat_id, value in ((39, 1.3), (40, 1.2), (41, 1.06)):
        final_entry = entries["final"] + 0x20 + stat_id * 0x10
        raw_entry = entries["raw"] + 0x20 + stat_id * 0x10
        component_entry = entries["components"] + 0x20 + stat_id * 0x18
        for entry in (final_entry, raw_entry, component_entry):
            memory.ints[entry] = 0
            memory.ints[entry + 0x8] = stat_id
        memory.floats[final_entry + 0xC] = value
        memory.floats[raw_entry + 0xC] = value
        final_addresses[stat_id] = final_entry + 0xC
        component = 0x8000 + stat_id * 0x100
        memory.ptrs[component_entry + 0x10] = component
        memory.u8[component + 0x10] = 0
        memory.floats[component + 0x14] = 1.0
        memory.floats[component + 0x18] = value
        memory.floats[component + 0x1C] = 1.0
    return memory, owner, final_addresses


class RunVerifierReaderTests(unittest.TestCase):
    def test_reads_and_confirms_stable_component_frame(self):
        memory, owner, _addresses = _build_memory()
        client = PlayerStatsClient(memory=memory)

        frame = client.get_verifier_stat_components(owner)

        self.assertTrue(frame.stable)
        self.assertEqual(tuple(stat.stat_id for stat in frame.stats), (39, 40, 41))
        self.assertAlmostEqual(frame.stats[1].final_value, 1.2)
        self.assertAlmostEqual(frame.stats[1].additive_value, 1.2)

    def test_marks_frame_unstable_when_all_three_reads_differ(self):
        memory, owner, addresses = _build_memory()
        memory.float_sequences[addresses[39]] = [1.0, 1.1, 1.2]
        client = PlayerStatsClient(memory=memory)

        frame = client.get_verifier_stat_components(owner)

        self.assertFalse(frame.stable)
        self.assertAlmostEqual(frame.stats[0].final_value, 1.2)

    def test_reads_pe_build_identity_once(self):
        memory, _owner, _addresses = _build_memory()
        memory.ints[memory.module_base + 0x3C] = 0x100
        memory.ints[memory.module_base + 0x100] = 0x00004550
        memory.ints[memory.module_base + 0x108] = 0x6980D323
        memory.ints[memory.module_base + 0x150] = 0x036FA000
        client = PlayerStatsClient(memory=memory)

        self.assertEqual(client.get_game_build_id(), "pe-6980d323-036fa000")
        memory.ints[memory.module_base + 0x108] = 0
        self.assertEqual(client.get_game_build_id(), "pe-6980d323-036fa000")


if __name__ == "__main__":
    unittest.main()
