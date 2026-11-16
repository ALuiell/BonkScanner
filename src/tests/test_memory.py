from __future__ import annotations

import src

import struct
import types
import unittest
from unittest.mock import Mock, call, patch

from infra.memory import reader as memory_reader
from infra.memory.reader import MemoryReadError, ProcessMemory, ProcessNotFoundError


class FakePymem:
    def __init__(self, payload: dict[int, bytes]) -> None:
        self.payload = payload
        self.process_handle = object()
        self.process_id = 4321

    def read_bytes(self, address: int, size: int) -> bytes:
        data = self.payload.get(address)
        if data is None or len(data) < size:
            raise RuntimeError(f"missing bytes at 0x{address:X}")
        return data[:size]


class ProcessMemoryTests(unittest.TestCase):
    def create_reader(self, payload: dict[int, bytes]) -> ProcessMemory:
        return ProcessMemory(
            "fake.exe",
            _pm=FakePymem(payload),
            _module_from_name=lambda _handle, _name: types.SimpleNamespace(lpBaseOfDll=0x10000000),
        )

    def test_read_mono_string_decodes_utf16(self) -> None:
        string_address = 0x2000
        payload = {
            string_address + 0x10: struct.pack("<i", 5),
            string_address + 0x14: "Moais".encode("utf-16-le"),
        }
        reader = self.create_reader(payload)

        self.assertEqual(reader.read_mono_string(string_address), "Moais")

    def test_read_mono_string_rejects_invalid_length(self) -> None:
        string_address = 0x3000
        payload = {
            string_address + 0x10: struct.pack("<i", 1024),
        }
        reader = self.create_reader(payload)

        self.assertIsNone(reader.read_mono_string(string_address))

    def test_module_offset_uses_module_base(self) -> None:
        reader = self.create_reader({})

        self.assertEqual(reader.module_offset("GameAssembly.dll", 0x1234), 0x10001234)

    def test_process_identity_has_a_stable_pid_fallback(self) -> None:
        reader = self.create_reader({})

        self.assertEqual(reader.process_identity(), "4321:0")

    def test_clients_reuse_a_live_target_with_independent_handles(self) -> None:
        first = Mock(process_id=4321)
        second = Mock(process_id=4321)
        with (
            patch.dict(memory_reader._known_processes, clear=True),
            patch.object(memory_reader, "_process_times", return_value=(100, 0)),
            patch.object(memory_reader.pymem, "Pymem", side_effect=[first, second]) as open_process,
        ):
            with ProcessMemory("MegaBonk.exe") as scan_reader:
                with ProcessMemory("megabonk.exe") as stats_reader:
                    self.assertEqual(scan_reader.process_identity(), stats_reader.process_identity())
                second.close_process.assert_called_once()
                first.close_process.assert_not_called()
            first.close_process.assert_called_once()

        self.assertEqual(open_process.call_args_list, [call("MegaBonk.exe"), call(4321)])

    def test_pid_reuse_or_exit_triggers_rediscovery(self) -> None:
        for stale_times in ((200, 0), (100, 150)):
            with self.subTest(stale_times=stale_times):
                stale = Mock(process_id=4321)
                replacement = Mock(process_id=5678)
                next_reader = Mock(process_id=5678)
                with (
                    patch.dict(memory_reader._known_processes, {"megabonk.exe": (4321, 100)}, clear=True),
                    patch.object(memory_reader, "_process_times", side_effect=[stale_times, (300, 0), (300, 0)]),
                    patch.object(memory_reader.pymem, "Pymem", side_effect=[stale, replacement, next_reader]) as open_process,
                ):
                    with ProcessMemory("MegaBonk.exe"), ProcessMemory("MegaBonk.exe"):
                        stale.close_process.assert_called_once()
                self.assertEqual(open_process.call_args_list, [call(4321), call("MegaBonk.exe"), call(5678)])

    def test_failed_cached_open_falls_back_and_preserves_process_not_found(self) -> None:
        failures = [
            memory_reader.pymem.exception.CouldNotOpenProcess(4321),
            memory_reader.pymem.exception.ProcessNotFound("MegaBonk.exe"),
        ]
        with (
            patch.dict(memory_reader._known_processes, {"megabonk.exe": (4321, 100)}, clear=True),
            patch.object(memory_reader.pymem, "Pymem", side_effect=failures) as open_process,
        ):
            with self.assertRaises(ProcessNotFoundError):
                ProcessMemory("MegaBonk.exe")
            self.assertNotIn("megabonk.exe", memory_reader._known_processes)
        self.assertEqual(open_process.call_args_list, [call(4321), call("MegaBonk.exe")])

    def test_module_base_is_resolved_once_per_module(self) -> None:
        # `module_from_name` enumerates the whole module list -- ~3.4 ms live,
        # against ~0.004 ms for a read -- so the fast combat pair must not pay
        # it per call. Distinct names must still each resolve.
        calls: list[str] = []

        def lookup(_handle, name):
            calls.append(name)
            return types.SimpleNamespace(lpBaseOfDll=0x10000000 + len(calls))

        reader = ProcessMemory("fake.exe", _pm=FakePymem({}), _module_from_name=lookup)

        first = reader.module_base_address("GameAssembly.dll")
        self.assertEqual(reader.module_base_address("GameAssembly.dll"), first)
        self.assertEqual(reader.module_offset("GameAssembly.dll", 0x10), first + 0x10)
        self.assertEqual(calls, ["GameAssembly.dll"])

        self.assertNotEqual(reader.module_base_address("UnityPlayer.dll"), first)
        self.assertEqual(calls, ["GameAssembly.dll", "UnityPlayer.dll"])

    def test_module_base_cache_is_dropped_when_the_handle_changes(self) -> None:
        # ASLR re-bases per launch, so a cached base must never outlive the
        # handle it was resolved against.
        bases = iter([0x10000000, 0x20000000])
        reader = ProcessMemory(
            "fake.exe",
            _pm=FakePymem({}),
            _module_from_name=lambda _handle, _name: types.SimpleNamespace(
                lpBaseOfDll=next(bases)
            ),
        )

        self.assertEqual(reader.module_base_address("GameAssembly.dll"), 0x10000000)

        reader._pm.process_handle = object()  # a reattach to a restarted process

        self.assertEqual(reader.module_base_address("GameAssembly.dll"), 0x20000000)

    def test_close_drops_the_module_base_cache(self) -> None:
        reader = self.create_reader({})
        reader.module_base_address("GameAssembly.dll")

        reader.close()

        self.assertEqual(reader._base_cache, {})

    def test_read_float_decodes_little_endian_float(self) -> None:
        reader = self.create_reader({0x4000: struct.pack("<f", 1.25)})

        self.assertAlmostEqual(reader.read_float(0x4000), 1.25)

    def test_read_bytes_raises_memory_error_on_missing_data(self) -> None:
        reader = self.create_reader({})

        with self.assertRaises(MemoryReadError):
            reader.read_bytes(0x9999, 4)


if __name__ == "__main__":
    unittest.main()
