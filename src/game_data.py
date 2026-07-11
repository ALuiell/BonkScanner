from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Callable

from memory import MemoryReadError, ProcessMemory


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


class GameDataClient:
    TYPE_INFO_OFFSET = 0x2FB5E68
    GAME_MANAGER_TYPE_INFO_OFFSET = 0x2F9C1C0
    LOADING_SCREEN_TYPE_INFO_OFFSET = 0x2F55E20
    MAP_CONTROLLER_TYPE_INFO_OFFSET = 0x2F58E08
    MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET = 0x2F59000
    MUSIC_CONTROLLER_TYPE_INFO_OFFSET = 0x2F617C8
    MY_TIME_TYPE_INFO_OFFSET = 0x2F62398
    PLAYER_MOVEMENT_TYPE_INFO_OFFSET = 0x2F6D670
    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    GAME_MANAGER_INSTANCE_OFFSET = 0x0
    GAME_MANAGER_IS_GAME_OVER_OFFSET = 0x74
    GAME_MANAGER_IS_PLAYING_OFFSET = 0x84
    MAP_CONTROLLER_CURRENT_MAP_OFFSET = 0x10
    MAP_CONTROLLER_CURRENT_STAGE_OFFSET = 0x18
    MAP_CONTROLLER_INDEX_OFFSET = 0x08
    MAP_CONTROLLER_RESETING_OFFSET = 0x21
    MAP_CONTROLLER_RUN_CONFIG_OFFSET = 0x30
    MAP_GENERATION_IS_GENERATING_OFFSET = 0x10
    MAP_GENERATION_MAP_SEED_OFFSET = 0x2C
    LOADING_SCREEN_IS_LOADING_OFFSET = 0x10
    MY_TIME_PAUSED_OFFSET = 0x0
    MY_TIME_STAGE_TIMER_OFFSET = 0x1C
    MY_TIME_RUN_TIMER_OFFSET = 0x20
    MY_TIME_FINAL_SWARM_TIMER_OFFSET = 0x24
    MY_TIME_DIFFICULTY_TIMER_OFFSET = 0x28
    MY_TIME_CRYPT_TIMER_OFFSET = 0x2C
    PLAYER_MOVEMENT_INSTANCE_OFFSET = 0x18
    MUSIC_CONTROLLER_INSTANCE_OFFSET = 0x0
    MUSIC_CONTROLLER_MENU_TRACK_OFFSET = 0x40
    MUSIC_CONTROLLER_CURRENT_TRACK_OFFSET = 0x48
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
        "Bald Heads": MapStat.BALD_HEADS,
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
    # Readiness/change detection should stay anchored to the baseline stat set
    # shared across maps. Map-specific extras remain readable, but do not
    # participate in map-ready normalization.
    OPTIONAL_READY_STATS = frozenset({MapStat.BALD_HEADS})
    EXPECTED_READY_STATS = frozenset(LABEL_TO_STAT.values()) - OPTIONAL_READY_STATS

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
        self._cached_static_fields: dict[int, int] = {}

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

    def get_runtime_activity_state(self) -> RuntimeGameState:
        """Read only the fields needed to decide whether a run is active.

        The type-info to static-field paths are stable for a client lifetime;
        object pointers and lifecycle flags remain fresh on every probe.
        """
        game_manager_static_fields = self._read_static_fields_cached(
            self.GAME_MANAGER_TYPE_INFO_OFFSET,
        )
        my_time_static_fields = self._read_static_fields_cached(
            self.MY_TIME_TYPE_INFO_OFFSET,
        )
        loading_screen_static_fields = self._read_static_fields_cached(
            self.LOADING_SCREEN_TYPE_INFO_OFFSET,
        )
        player_movement_static_fields = self._read_static_fields_cached(
            self.PLAYER_MOVEMENT_TYPE_INFO_OFFSET,
        )
        music_controller_static_fields = self._read_static_fields_cached(
            self.MUSIC_CONTROLLER_TYPE_INFO_OFFSET,
        )

        game_manager_ptr = self._read_ptr_optional(
            game_manager_static_fields,
            self.GAME_MANAGER_INSTANCE_OFFSET,
        )
        is_playing = self._read_bool(
            game_manager_ptr,
            self.GAME_MANAGER_IS_PLAYING_OFFSET,
        )
        is_game_over = self._read_bool(
            game_manager_ptr,
            self.GAME_MANAGER_IS_GAME_OVER_OFFSET,
        )
        is_paused = self._read_bool(
            my_time_static_fields,
            self.MY_TIME_PAUSED_OFFSET,
        )
        is_loading = self._read_bool(
            loading_screen_static_fields,
            self.LOADING_SCREEN_IS_LOADING_OFFSET,
        )
        player_movement_ptr = self._read_ptr_optional(
            player_movement_static_fields,
            self.PLAYER_MOVEMENT_INSTANCE_OFFSET,
        )
        music_controller_ptr = self._read_ptr_optional(
            music_controller_static_fields,
            self.MUSIC_CONTROLLER_INSTANCE_OFFSET,
        )
        music_menu_track_ptr = self._read_ptr_optional(
            music_controller_ptr,
            self.MUSIC_CONTROLLER_MENU_TRACK_OFFSET,
        )
        music_current_track_ptr = self._read_ptr_optional(
            music_controller_ptr,
            self.MUSIC_CONTROLLER_CURRENT_TRACK_OFFSET,
        )

        looks_like_manual_menu = (
            not player_movement_ptr
            and bool(music_controller_ptr)
            and bool(music_current_track_ptr)
            and music_current_track_ptr == music_menu_track_ptr
        )
        if game_manager_ptr and is_playing and is_game_over:
            mode = RuntimeGameMode.GAME_OVER
        elif looks_like_manual_menu:
            mode = RuntimeGameMode.MAIN_MENU
        elif game_manager_ptr and is_playing:
            mode = RuntimeGameMode.PAUSED_IN_GAME if is_paused else RuntimeGameMode.IN_GAME
        elif not game_manager_ptr and not is_loading:
            mode = RuntimeGameMode.MAIN_MENU
        else:
            mode = RuntimeGameMode.UNKNOWN

        return RuntimeGameState(
            mode=mode,
            game_manager_ptr=game_manager_ptr,
            is_playing=is_playing,
            is_game_over=is_game_over,
            is_paused=is_paused,
            is_loading=is_loading,
            player_movement_ptr=player_movement_ptr,
            music_controller_ptr=music_controller_ptr,
            music_current_track_ptr=music_current_track_ptr,
            music_menu_track_ptr=music_menu_track_ptr,
        )

    def get_runtime_game_state(self) -> RuntimeGameState:
        game_manager_static_fields = self._read_static_fields(
            self.GAME_MANAGER_TYPE_INFO_OFFSET,
        )
        map_controller_static_fields = self._read_static_fields(
            self.MAP_CONTROLLER_TYPE_INFO_OFFSET,
        )
        my_time_static_fields = self._read_static_fields(
            self.MY_TIME_TYPE_INFO_OFFSET,
        )
        loading_screen_static_fields = self._read_static_fields(
            self.LOADING_SCREEN_TYPE_INFO_OFFSET,
        )
        player_movement_static_fields = self._read_static_fields(
            self.PLAYER_MOVEMENT_TYPE_INFO_OFFSET,
        )
        music_controller_static_fields = self._read_static_fields(
            self.MUSIC_CONTROLLER_TYPE_INFO_OFFSET,
        )

        game_manager_ptr = self._read_ptr_optional(
            game_manager_static_fields,
            self.GAME_MANAGER_INSTANCE_OFFSET,
        )
        is_playing = self._read_bool(
            game_manager_ptr,
            self.GAME_MANAGER_IS_PLAYING_OFFSET,
        )
        is_game_over = self._read_bool(
            game_manager_ptr,
            self.GAME_MANAGER_IS_GAME_OVER_OFFSET,
        )
        is_paused = self._read_bool(
            my_time_static_fields,
            self.MY_TIME_PAUSED_OFFSET,
        )
        is_loading = self._read_bool(
            loading_screen_static_fields,
            self.LOADING_SCREEN_IS_LOADING_OFFSET,
        )
        run_timer_seconds = self._read_float_optional(
            my_time_static_fields,
            self.MY_TIME_RUN_TIMER_OFFSET,
        )
        stage_timer_seconds = self._read_float_optional(
            my_time_static_fields,
            self.MY_TIME_STAGE_TIMER_OFFSET,
        )
        final_swarm_timer_seconds = self._read_float_optional(
            my_time_static_fields,
            self.MY_TIME_FINAL_SWARM_TIMER_OFFSET,
        )
        difficulty_timer_seconds = self._read_float_optional(
            my_time_static_fields,
            self.MY_TIME_DIFFICULTY_TIMER_OFFSET,
        )
        crypt_timer_seconds = self._read_float_optional(
            my_time_static_fields,
            self.MY_TIME_CRYPT_TIMER_OFFSET,
        )
        current_stage_index = self._read_i32_optional(
            map_controller_static_fields,
            self.MAP_CONTROLLER_INDEX_OFFSET,
        )
        current_map_ptr = self._read_ptr_optional(
            map_controller_static_fields,
            self.MAP_CONTROLLER_CURRENT_MAP_OFFSET,
        )
        current_stage_ptr = self._read_ptr_optional(
            map_controller_static_fields,
            self.MAP_CONTROLLER_CURRENT_STAGE_OFFSET,
        )
        run_config_ptr = self._read_ptr_optional(
            map_controller_static_fields,
            self.MAP_CONTROLLER_RUN_CONFIG_OFFSET,
        )
        player_movement_ptr = self._read_ptr_optional(
            player_movement_static_fields,
            self.PLAYER_MOVEMENT_INSTANCE_OFFSET,
        )
        music_controller_ptr = self._read_ptr_optional(
            music_controller_static_fields,
            self.MUSIC_CONTROLLER_INSTANCE_OFFSET,
        )
        music_menu_track_ptr = self._read_ptr_optional(
            music_controller_ptr,
            self.MUSIC_CONTROLLER_MENU_TRACK_OFFSET,
        )
        music_current_track_ptr = self._read_ptr_optional(
            music_controller_ptr,
            self.MUSIC_CONTROLLER_CURRENT_TRACK_OFFSET,
        )

        mode = RuntimeGameMode.UNKNOWN
        looks_like_manual_menu = (
            not player_movement_ptr
            and bool(music_controller_ptr)
            and bool(music_current_track_ptr)
            and music_current_track_ptr == music_menu_track_ptr
        )
        if game_manager_ptr and is_playing and is_game_over:
            mode = RuntimeGameMode.GAME_OVER
        elif looks_like_manual_menu:
            mode = RuntimeGameMode.MAIN_MENU
        elif game_manager_ptr and is_playing and not is_game_over:
            mode = RuntimeGameMode.PAUSED_IN_GAME if is_paused else RuntimeGameMode.IN_GAME
        elif not game_manager_ptr and not is_loading:
            mode = RuntimeGameMode.MAIN_MENU

        return RuntimeGameState(
            mode=mode,
            game_manager_ptr=game_manager_ptr,
            is_playing=is_playing,
            is_game_over=is_game_over,
            is_paused=is_paused,
            is_loading=is_loading,
            run_timer_seconds=run_timer_seconds,
            stage_timer_seconds=stage_timer_seconds,
            final_swarm_timer_seconds=final_swarm_timer_seconds,
            difficulty_timer_seconds=difficulty_timer_seconds,
            crypt_timer_seconds=crypt_timer_seconds,
            current_stage_index=current_stage_index,
            current_map_ptr=current_map_ptr,
            current_stage_ptr=current_stage_ptr,
            run_config_ptr=run_config_ptr,
            player_movement_ptr=player_movement_ptr,
            music_controller_ptr=music_controller_ptr,
            music_current_track_ptr=music_current_track_ptr,
            music_menu_track_ptr=music_menu_track_ptr,
        )

    def wait_for_map_ready(
        self,
        previous_seed: int | None = None,
        *,
        previous_state: MapGenerationState | None = None,
        previous_stats: dict[MapStat, StatValue] | None = None,
        require_change: bool = True,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
        abort_condition: Callable[[], bool] | None = None,
    ) -> dict[MapStat, StatValue]:
        deadline = time.monotonic() + timeout
        generation_seen = False
        map_change_seen = False
        baseline_seed = (
            previous_state.map_seed
            if previous_state is not None and previous_state.map_seed is not None
            else previous_seed
        )
        baseline_map_ptr = (
            previous_state.current_map_ptr
            if previous_state is not None and previous_state.current_map_ptr
            else None
        )
        baseline_stage_ptr = (
            previous_state.current_stage_ptr
            if previous_state is not None and previous_state.current_stage_ptr
            else None
        )
        baseline_stats = self._normalize_ready_stats(previous_stats) if previous_stats is not None else None
        stable_stats: dict[MapStat, StatValue] | None = None
        ready_raw_stats: dict[MapStat, StatValue] | None = None
        stable_stats_seen = False
        last_stats_count = 0
        zero_defaulted_stats: set[MapStat] = set(self.EXPECTED_READY_STATS)
        last_state = MapGenerationState()
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            if abort_condition is not None and abort_condition():
                raise InterruptedError("Wait aborted by user.")

            try:
                last_state = self.get_map_generation_state()
                generation_seen = generation_seen or last_state.is_generating
                map_change_seen = map_change_seen or generation_seen

                if (
                    baseline_seed is not None
                    and last_state.map_seed is not None
                    and last_state.map_seed != baseline_seed
                ):
                    map_change_seen = True
                if (
                    baseline_map_ptr is not None
                    and last_state.current_map_ptr
                    and last_state.current_map_ptr != baseline_map_ptr
                ):
                    map_change_seen = True
                if (
                    baseline_stage_ptr is not None
                    and last_state.current_stage_ptr
                    and last_state.current_stage_ptr != baseline_stage_ptr
                ):
                    map_change_seen = True

                stats = self.get_map_stats()
                ready_stats = self._normalize_ready_stats(stats)
                last_stats_count = len(stats)
                zero_defaulted_stats = self.EXPECTED_READY_STATS.difference(stats.keys())
                if baseline_stats is None:
                    baseline_stats = ready_stats
                elif ready_stats != baseline_stats:
                    map_change_seen = True

                if (
                    (not require_change or generation_seen or map_change_seen)
                    and not last_state.is_generating
                    and not last_state.is_resetting
                    and last_state.has_loaded_map
                    and self._is_ready_stats(stats)
                ):
                    if ready_stats == stable_stats and ready_raw_stats is not None:
                        return ready_raw_stats
                    stable_stats = ready_stats
                    ready_raw_stats = stats
                    stable_stats_seen = True
                else:
                    stable_stats = None
                    ready_raw_stats = None
            except MemoryReadError as exc:
                last_error = exc
                stable_stats = None
                ready_raw_stats = None

            time.sleep(poll_interval)

        error_text = (
            f"Timed out waiting for map readiness after {timeout:.1f}s. "
            f"Last state: {last_state}. "
            f"change_seen={map_change_seen}, generation_seen={generation_seen}, "
            f"stats_count={last_stats_count}, "
            f"zero_defaulted_stats={self._format_stats(zero_defaulted_stats)}, "
            f"stable_stats_seen={stable_stats_seen}."
        )
        if last_error is not None:
            error_text += f" Last memory error: {last_error}"
        raise TimeoutError(error_text)

    def get_map_stats(self) -> dict[MapStat, StatValue]:
        return {
            stat: value
            for label, value in self.get_map_activity_values().items()
            if (stat := self.LABEL_TO_STAT.get(label)) is not None
        }

    def get_map_activity_values(self) -> dict[str, StatValue]:
        activities: dict[str, StatValue] = {}
        type_info_address = self.memory.module_offset(
            self.module_name,
            self.TYPE_INFO_OFFSET,
        )
        class_ptr = self.memory.read_ptr(type_info_address)
        if not class_ptr:
            return activities

        static_fields = self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        if not static_fields:
            return activities

        interactables_dict = self.memory.read_ptr(static_fields)
        if not interactables_dict:
            return activities

        entries = self.memory.read_ptr(interactables_dict + self.DICT_ENTRIES_OFFSET)
        count = self.memory.read_i32(interactables_dict + self.DICT_COUNT_OFFSET)

        if not entries:
            return activities

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

            try:
                max_value = self.memory.read_i32(value_ptr + self.CONTAINER_MAX_OFFSET)
                current_value = self.memory.read_i32(value_ptr + self.CONTAINER_CURRENT_OFFSET)
            except MemoryReadError:
                continue

            activities[label] = StatValue(current=current_value, max=max_value)

        return activities

    def _read_static_fields(self, type_info_offset: int) -> int:
        try:
            type_info_address = self.memory.module_offset(self.module_name, type_info_offset)
            class_ptr = self.memory.read_ptr(type_info_address)
            if not class_ptr:
                return 0
            return self.memory.read_ptr(class_ptr + self.CLASS_STATIC_FIELDS_OFFSET)
        except MemoryReadError:
            return 0

    def _read_static_fields_cached(self, type_info_offset: int) -> int:
        cached = self._cached_static_fields.get(type_info_offset, 0)
        if cached:
            return cached
        static_fields = self._read_static_fields(type_info_offset)
        if static_fields:
            self._cached_static_fields[type_info_offset] = static_fields
        return static_fields

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

    def _read_float_optional(self, base_address: int, offset: int) -> float | None:
        if not base_address:
            return None
        try:
            return self.memory.read_float(base_address + offset)
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
        return bool(stats)

    def _normalize_ready_stats(
        self,
        stats: dict[MapStat, StatValue],
    ) -> dict[MapStat, StatValue]:
        return {
            stat: stats.get(stat, StatValue(current=0, max=0))
            for stat in self.EXPECTED_READY_STATS
        }

    def _format_stats(self, stats: set[MapStat]) -> str:
        if not stats:
            return "none"
        return ",".join(sorted(stat.value for stat in stats))
