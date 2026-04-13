from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from memory import MemoryReadError, ProcessMemory


class MemoryReader(Protocol):
    def module_offset(self, module_name: str, offset: int) -> int:
        ...

    def read_ptr(self, address: int) -> int:
        ...

    def read_i32(self, address: int) -> int:
        ...

    def read_mono_string(self, address: int, max_length: int = 512) -> str | None:
        ...


class MapStat(Enum):
    CHALLENGES = "challenges"
    CHARGE_SHRINES = "charge_shrines"
    CHESTS = "chests"
    GREED_SHRINES = "greed_shrines"
    MAGNET_SHRINES = "magnet_shrines"
    MICROWAVES = "microwaves"
    MOAIS = "moais"
    POTS = "pots"
    SHADY_GUY = "shady_guy"


@dataclass(frozen=True)
class StatValue:
    current: int
    max: int


class GameDataClient:
    TYPE_INFO_OFFSET = 0x2FA4548
    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    DICT_ENTRIES_OFFSET = 0x18
    DICT_COUNT_OFFSET = 0x20
    ENTRY_BASE_OFFSET = 0x20
    ENTRY_SIZE = 0x18
    ENTRY_KEY_OFFSET = 0x8
    ENTRY_VALUE_OFFSET = 0x10
    CONTAINER_MAX_OFFSET = 0x10
    CONTAINER_CURRENT_OFFSET = 0x14
    MAX_DICT_ENTRIES = 4096

    LABEL_TO_STAT = {
        "Challenges": MapStat.CHALLENGES,
        "Charge Shrines": MapStat.CHARGE_SHRINES,
        "Chests": MapStat.CHESTS,
        "Greed Shrines": MapStat.GREED_SHRINES,
        "Magnet Shrines": MapStat.MAGNET_SHRINES,
        "Microwaves": MapStat.MICROWAVES,
        "Moais": MapStat.MOAIS,
        "Pots": MapStat.POTS,
        "Shady Guy": MapStat.SHADY_GUY,
    }

    def __init__(
        self,
        process_name: str | None = None,
        *,
        module_name: str = "GameAssembly.dll",
        memory: MemoryReader | None = None,
    ) -> None:
        if memory is None and not process_name:
            raise ValueError("process_name is required when memory backend is not provided.")

        self.module_name = module_name
        self._owns_memory = memory is None
        self.memory: MemoryReader = memory or ProcessMemory(process_name)

    def close(self) -> None:
        if self._owns_memory and hasattr(self.memory, "close"):
            self.memory.close()

    def __enter__(self) -> "GameDataClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_map_stats(self) -> dict[MapStat, StatValue]:
        stats: dict[MapStat, StatValue] = {}

        type_info_address = self.memory.module_offset(
            self.module_name,
            self.TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            return stats

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            return stats

        interactables_dict = self.memory.read_ptr(static_fields)
        if not interactables_dict:
            return stats

        entries = self.memory.read_ptr(interactables_dict + self.DICT_ENTRIES_OFFSET)
        count = self.memory.read_i32(interactables_dict + self.DICT_COUNT_OFFSET)

        if not entries:
            return stats

        if count < 0 or count > self.MAX_DICT_ENTRIES:
            raise MemoryReadError(f"Interactables dictionary count is invalid: {count}")

        for index in range(count):
            interactables_entry = entries + self.ENTRY_BASE_OFFSET + (index * self.ENTRY_SIZE)

            try:
                key_ptr = self.memory.read_ptr(interactables_entry + self.ENTRY_KEY_OFFSET)
                value_ptr = self.memory.read_ptr(interactables_entry + self.ENTRY_VALUE_OFFSET)
            except MemoryReadError:
                continue

            if not key_ptr or not value_ptr:
                continue

            label = self.memory.read_mono_string(key_ptr)
            if not label:
                continue

            stat = self.LABEL_TO_STAT.get(label)
            if stat is None:
                continue

            try:
                max_value = self.memory.read_i32(value_ptr + self.CONTAINER_MAX_OFFSET)
                current_value = self.memory.read_i32(value_ptr + self.CONTAINER_CURRENT_OFFSET)
            except MemoryReadError:
                continue

            stats[stat] = StatValue(current=current_value, max=max_value)

        return stats
