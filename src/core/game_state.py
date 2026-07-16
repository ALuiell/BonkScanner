"""Game runtime domain: game mode/state, map stats and the memory-reader port.

Qt-free and I/O-free -- imports stdlib only.

``MemoryReader`` here is deliberately *not* the same protocol as
``core.stats.types.MemoryReader``: this one needs ``read_u8``, that one needs
``read_ascii_string``. Each client declares the narrow slice it actually uses;
``ProcessMemory`` satisfies both.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class MemoryReader(Protocol):
    def module_offset(self, module_name: str, offset: int) -> int:
        ...

    def read_ptr(self, address: int) -> int:
        ...

    def read_i32(self, address: int) -> int:
        ...

    def read_float(self, address: int) -> float:
        ...

    def read_u8(self, address: int) -> int:
        ...

    def read_mono_string(self, address: int, max_length: int = 512) -> str | None:
        ...


class MapStat(Enum):
    BALD_HEADS = "bald_heads"
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


class RuntimeGameMode(Enum):
    UNKNOWN = "unknown"
    IN_GAME = "in_game"
    PAUSED_IN_GAME = "paused_in_game"
    GAME_OVER = "game_over"
    MAIN_MENU = "main_menu"


@dataclass(frozen=True)
class RuntimeGameState:
    mode: RuntimeGameMode = RuntimeGameMode.UNKNOWN
    game_manager_ptr: int = 0
    is_playing: bool = False
    is_game_over: bool = False
    is_paused: bool = False
    is_loading: bool = False
    run_timer_seconds: float | None = None
    stage_timer_seconds: float | None = None
    final_swarm_timer_seconds: float | None = None
    difficulty_timer_seconds: float | None = None
    crypt_timer_seconds: float | None = None
    current_stage_index: int | None = None
    current_map_ptr: int = 0
    current_stage_ptr: int = 0
    run_config_ptr: int = 0
    player_movement_ptr: int = 0
    music_controller_ptr: int = 0
    music_current_track_ptr: int = 0
    music_menu_track_ptr: int = 0

    @property
    def is_active_run(self) -> bool:
        return self.mode in {
            RuntimeGameMode.IN_GAME,
            RuntimeGameMode.PAUSED_IN_GAME,
        }

    @property
    def is_paused_run(self) -> bool:
        return self.mode is RuntimeGameMode.PAUSED_IN_GAME

    @property
    def is_main_menu(self) -> bool:
        return self.mode is RuntimeGameMode.MAIN_MENU

    @property
    def is_game_over_run(self) -> bool:
        return self.mode is RuntimeGameMode.GAME_OVER
