from __future__ import annotations

import struct
import types
import unittest

from memory import MemoryReadError, ProcessMemory


class FakePymem:
    def __init__(self, payload: dict[int, bytes]) -> None:
        self.payload = payload
        self.process_handle = object()

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

    def test_read_bytes_raises_memory_error_on_missing_data(self) -> None:
        reader = self.create_reader({})

        with self.assertRaises(MemoryReadError):
            reader.read_bytes(0x9999, 4)


if __name__ == "__main__":
    unittest.main()

