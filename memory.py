from __future__ import annotations

import struct
from typing import Any

import pymem
import pymem.exception
import pymem.process


class ProcessNotFoundError(Exception):
    """Raised when the target process cannot be opened."""


class ModuleNotFoundError(Exception):
    """Raised when the target module is not loaded in the process."""


class MemoryReadError(Exception):
    """Raised when memory cannot be read or interpreted."""


class ProcessMemory:
    """Thin wrapper around process memory access for the game."""

    def __init__(
        self,
        process_name: str,
        *,
        _pm: Any | None = None,
        _module_from_name: Any | None = None,
    ) -> None:
        self.process_name = process_name
        self._pm: Any | None = None
        self._module_from_name = _module_from_name

        if _pm is not None:
            self._pm = _pm
            self._module_from_name = _module_from_name or self._missing_module_lookup
            return

        try:
            self._pm = pymem.Pymem(process_name)
        except (
            pymem.exception.ProcessNotFound,
            pymem.exception.CouldNotOpenProcess,
        ) as exc:
            raise ProcessNotFoundError(
                f"Could not open process '{process_name}'."
            ) from exc
        except Exception as exc:
            raise MemoryReadError(
                f"Failed to initialize memory access for '{process_name}'."
            ) from exc

        self._module_from_name = pymem.process.module_from_name

    def close(self) -> None:
        if self._pm is None:
            return

        close_process = getattr(self._pm, "close_process", None)
        if callable(close_process):
            try:
                close_process()
            except Exception:
                pass

    def __enter__(self) -> "ProcessMemory":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def module_base_address(self, module_name: str) -> int:
        if self._pm is None:
            raise MemoryReadError("Process memory is not initialized.")

        try:
            module = self._module_from_name(self._pm.process_handle, module_name)
        except Exception as exc:
            raise ModuleNotFoundError(
                f"Could not resolve module '{module_name}'."
            ) from exc

        base_address = getattr(module, "lpBaseOfDll", 0)
        if not base_address:
            raise ModuleNotFoundError(f"Module '{module_name}' is not loaded.")

        return int(base_address)

    def module_offset(self, module_name: str, offset: int) -> int:
        return self.module_base_address(module_name) + offset

    def read_bytes(self, address: int, size: int) -> bytes:
        if self._pm is None:
            raise MemoryReadError("Process memory is not initialized.")

        try:
            data = self._pm.read_bytes(address, size)
        except Exception as exc:
            raise MemoryReadError(
                f"Failed to read {size} bytes at 0x{address:X}."
            ) from exc

        if len(data) != size:
            raise MemoryReadError(
                f"Short read at 0x{address:X}: expected {size}, got {len(data)}."
            )

        return data

    def read_ptr(self, address: int) -> int:
        return struct.unpack("<Q", self.read_bytes(address, 8))[0]

    def read_i32(self, address: int) -> int:
        return struct.unpack("<i", self.read_bytes(address, 4))[0]

    def read_mono_string(self, address: int, max_length: int = 512) -> str | None:
        if not address:
            return None

        try:
            length = self.read_i32(address + 0x10)
        except MemoryReadError:
            return None

        if length < 0 or length > max_length:
            return None

        if length == 0:
            return ""

        try:
            raw = self.read_bytes(address + 0x14, length * 2)
        except MemoryReadError:
            return None

        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError:
            return None

    @staticmethod
    def _missing_module_lookup(_handle: Any, module_name: str) -> Any:
        raise ModuleNotFoundError(f"Module lookup is not configured for '{module_name}'.")
