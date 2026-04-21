from __future__ import annotations

import time
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

    def read_u8(self, address: int) -> int:
        ...

    def read_mono_string(self, address: int, max_length: int = 512) -> str | None:
        ...


class MapStat(Enum):
    BOSS_CURSES = "boss_curses"
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


@dataclass(frozen=True)
class MapGenerationState:
    is_generating: bool = False
    map_seed: int | None = None
    current_map_ptr: int = 0
    current_stage_ptr: int = 0
    is_resetting: bool = False

    @property
    def has_loaded_map(self) -> bool:
        return bool(self.current_map_ptr and self.current_stage_ptr)


class GameDataClient:
    TYPE_INFO_OFFSET = 0x2FB5E68
    MAP_CONTROLLER_TYPE_INFO_OFFSET = 0x2F58E08
    MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET = 0x2F59000
    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    MAP_CONTROLLER_CURRENT_MAP_OFFSET = 0x10
    MAP_CONTROLLER_CURRENT_STAGE_OFFSET = 0x18
    MAP_CONTROLLER_RESETING_OFFSET = 0x21
    MAP_GENERATION_IS_GENERATING_OFFSET = 0x10
    MAP_GENERATION_MAP_SEED_OFFSET = 0x2C
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
        "Boss Curses": MapStat.BOSS_CURSES,
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
    EXPECTED_READY_STATS = frozenset(LABEL_TO_STAT.values())

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

    def get_map_generation_state(self) -> MapGenerationState:
        map_generation_static_fields = self._read_static_fields(
            self.MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET,
        )
        map_controller_static_fields = self._read_static_fields(
            self.MAP_CONTROLLER_TYPE_INFO_OFFSET,
        )

        if not map_generation_static_fields and not map_controller_static_fields:
            return MapGenerationState()

        is_generating = self._read_bool(
            map_generation_static_fields,
            self.MAP_GENERATION_IS_GENERATING_OFFSET,
        )
        map_seed = self._read_i32_optional(
            map_generation_static_fields,
            self.MAP_GENERATION_MAP_SEED_OFFSET,
        )
        current_map_ptr = self._read_ptr_optional(
            map_controller_static_fields,
            self.MAP_CONTROLLER_CURRENT_MAP_OFFSET,
        )
        current_stage_ptr = self._read_ptr_optional(
            map_controller_static_fields,
            self.MAP_CONTROLLER_CURRENT_STAGE_OFFSET,
        )
        is_resetting = self._read_bool(
            map_controller_static_fields,
            self.MAP_CONTROLLER_RESETING_OFFSET,
        )

        return MapGenerationState(
            is_generating=is_generating,
            map_seed=map_seed,
            current_map_ptr=current_map_ptr,
            current_stage_ptr=current_stage_ptr,
            is_resetting=is_resetting,
        )

    def wait_for_map_ready(
        self,
        previous_seed: int | None = None,
        *,
        previous_stats: dict[MapStat, StatValue] | None = None,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
    ) -> dict[MapStat, StatValue]:
        deadline = time.monotonic() + timeout
        generation_seen = False
        map_change_seen = previous_seed is None
        baseline_stats = previous_stats
        stable_stats: dict[MapStat, StatValue] | None = None
        last_state = MapGenerationState()
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            try:
                last_state = self.get_map_generation_state()
                generation_seen = generation_seen or last_state.is_generating

                if previous_seed is not None and last_state.map_seed != previous_seed:
                    map_change_seen = True

                stats = self.get_map_stats()
                if baseline_stats is None:
                    baseline_stats = stats
                elif stats != baseline_stats:
                    map_change_seen = True

                if (
                    (generation_seen or map_change_seen)
                    and not last_state.is_generating
                    and not last_state.is_resetting
                    and last_state.has_loaded_map
                    and self._is_ready_stats(stats)
                ):
                    if stats == stable_stats:
                        return stats
                    stable_stats = stats
                else:
                    stable_stats = None
            except MemoryReadError as exc:
                last_error = exc
                stable_stats = None

            time.sleep(poll_interval)

        error_text = (
            f"Timed out waiting for map readiness after {timeout:.1f}s. "
            f"Last state: {last_state}."
        )
        if last_error is not None:
            error_text += f" Last memory error: {last_error}"
        raise TimeoutError(error_text)

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

    def _read_static_fields(self, type_info_offset: int) -> int:
        try:
            type_info_address = self.memory.module_offset(self.module_name, type_info_offset)
            class_ptr = self.memory.read_ptr(type_info_address)
            if not class_ptr:
                return 0
            return self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        except MemoryReadError:
            return 0

    def _read_bool(self, base_address: int, offset: int) -> bool:
        if not base_address:
            return False
        try:
            return self.memory.read_u8(base_address + offset) != 0
        except MemoryReadError:
            return False

    def _read_i32_optional(self, base_address: int, offset: int) -> int | None:
        if not base_address:
            return None
        try:
            return self.memory.read_i32(base_address + offset)
        except MemoryReadError:
            return None

    def _read_ptr_optional(self, base_address: int, offset: int) -> int:
        if not base_address:
            return 0
        try:
            return self.memory.read_ptr(base_address + offset)
        except MemoryReadError:
            return 0

    def _is_ready_stats(self, stats: dict[MapStat, StatValue]) -> bool:
        return self.EXPECTED_READY_STATS.issubset(stats.keys())
