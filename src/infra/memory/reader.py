from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any

import pymem
import pymem.exception
import pymem.memory
import pymem.process


class ProcessNotFoundError(Exception):
    """Raised when the target process cannot be opened."""


class ModuleNotFoundError(Exception):
    """Raised when the target module is not loaded in the process."""


class MemoryReadError(Exception):
    """Raised when memory cannot be read or interpreted."""


@dataclass(frozen=True)
class LoadedProcessModule:
    """Privacy-neutral raw module facts read from the target process."""

    name: str
    filename: str
    base_address: int
    size: int


@dataclass(frozen=True)
class PrivateExecutableRegion:
    """One committed executable MEM_PRIVATE range in the target process."""

    base_address: int
    allocation_base: int
    size: int
    protection: int


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
        # -- the module base cache -------------------------------------
        #
        # `module_from_name` enumerates every loaded module in the target
        # process; measured live it costs ~3.4 ms, against ~0.004 ms for one
        # `ReadProcessMemory`. The fast combat pair resolved the base twice per
        # tick and spent essentially its whole budget there.
        #
        # A module's base is fixed for the life of a process image: ASLR
        # re-bases it per launch, not per read, and GameAssembly.dll is the
        # IL2CPP core, never unloaded mid-run. So the base can only change
        # across a process restart -- and a restart invalidates the handle we
        # cached it against, which is exactly what `_base_cache_handle` below
        # keys on. A stale entry can therefore never be served: either the
        # handle still names the same live process (base unchanged), or it does
        # not (cache dropped).
        self._base_cache: dict[str, int] = {}
        self._base_cache_handle: Any = None

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
        # Closing releases the handle the cache was keyed against, and Windows
        # recycles handle values -- so drop the entries rather than trust the
        # identity check to notice.
        self._base_cache = {}
        self._base_cache_handle = None

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

        handle = self._pm.process_handle
        if handle != self._base_cache_handle:
            self._base_cache = {}
            self._base_cache_handle = handle

        cached = self._base_cache.get(module_name)
        if cached is not None:
            return cached

        try:
            module = self._module_from_name(handle, module_name)
        except Exception as exc:
            raise ModuleNotFoundError(
                f"Could not resolve module '{module_name}'."
            ) from exc

        base_address = getattr(module, "lpBaseOfDll", 0)
        if not base_address:
            raise ModuleNotFoundError(f"Module '{module_name}' is not loaded.")

        base_address = int(base_address)
        self._base_cache[module_name] = base_address
        return base_address

    def module_offset(self, module_name: str, offset: int) -> int:
        return self.module_base_address(module_name) + offset

    def loaded_modules(self) -> tuple[LoadedProcessModule, ...]:
        """Enumerate native images currently registered in the game process."""
        if self._pm is None:
            raise MemoryReadError("Process memory is not initialized.")
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                modules = []
                for module in pymem.process.enum_process_module(
                    self._pm.process_handle
                ):
                    name = str(module.name or "").strip()
                    filename = str(module.filename or "").strip()
                    if not name or not filename:
                        continue
                    modules.append(
                        LoadedProcessModule(
                            name=name,
                            filename=filename,
                            base_address=int(
                                getattr(module, "lpBaseOfDll", 0) or 0
                            ),
                            size=max(
                                0,
                                int(getattr(module, "SizeOfImage", 0) or 0),
                            ),
                        )
                    )
                if modules:
                    return tuple(modules)
                last_error = MemoryReadError(
                    "The process module enumeration returned no usable modules."
                )
            except Exception as exc:
                last_error = exc
        # EnumProcessModulesEx can transiently fail while the process is
        # loading or unloading an image. One immediate retry filters that
        # expected race; the caller owns the slower ten-second retry cadence.
        raise MemoryReadError("Failed to enumerate loaded process modules.") from last_error

    def private_executable_regions(self) -> tuple[PrivateExecutableRegion, ...]:
        """Enumerate committed executable memory not backed by an image file."""
        if self._pm is None:
            raise MemoryReadError("Process memory is not initialized.")
        committed = 0x1000
        private = 0x20000
        executable = frozenset({0x10, 0x20, 0x40, 0x80})
        max_user_address = 0x7FFF_FFFF_FFFF
        max_regions = 4096
        address = 0
        queried = 0
        regions: list[PrivateExecutableRegion] = []
        while address < max_user_address:
            try:
                info = pymem.memory.virtual_query(
                    self._pm.process_handle,
                    address,
                )
            except pymem.exception.WinAPIError as exc:
                # VirtualQueryEx reports ERROR_INVALID_PARAMETER after the
                # highest valid user-mode address. It is only a normal end
                # marker after at least one successful query.
                if queried and int(getattr(exc, "error_code", 0)) == 87:
                    break
                raise MemoryReadError(
                    "Failed to enumerate the process virtual-memory map."
                ) from exc
            except Exception as exc:
                raise MemoryReadError(
                    "Failed to enumerate the process virtual-memory map."
                ) from exc
            queried += 1
            base = int(getattr(info, "BaseAddress", 0) or 0)
            size = int(getattr(info, "RegionSize", 0) or 0)
            next_address = base + size
            if size <= 0 or next_address <= address:
                raise MemoryReadError(
                    "The process virtual-memory map did not advance."
                )
            state = int(getattr(info, "State", 0) or 0)
            region_type = int(getattr(info, "Type", 0) or 0)
            protection = int(getattr(info, "Protect", 0) or 0)
            base_protection = protection & 0xFF
            if (
                state == committed
                and region_type == private
                and base_protection in executable
            ):
                regions.append(
                    PrivateExecutableRegion(
                        base_address=base,
                        allocation_base=int(
                            getattr(info, "AllocationBase", 0) or base
                        ),
                        size=size,
                        protection=protection,
                    )
                )
                if len(regions) > max_regions:
                    raise MemoryReadError(
                        "The private executable-region safety limit was exceeded."
                    )
            address = next_address
        if not queried:
            raise MemoryReadError("The process virtual-memory map is unavailable.")
        return tuple(regions)

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

    def read_float(self, address: int) -> float:
        return struct.unpack("<f", self.read_bytes(address, 4))[0]

    def read_u8(self, address: int) -> int:
        return self.read_bytes(address, 1)[0]

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

    def read_ascii_string(self, address: int, max_length: int = 128) -> str | None:
        if not address:
            return None

        try:
            raw = self.read_bytes(address, max_length)
        except MemoryReadError:
            return None

        raw = raw.split(b"\x00", 1)[0]
        if not raw:
            return ""

        try:
            return raw.decode("ascii")
        except UnicodeDecodeError:
            return None

    @staticmethod
    def _missing_module_lookup(_handle: Any, module_name: str) -> Any:
        raise ModuleNotFoundError(f"Module lookup is not configured for '{module_name}'.")
