from __future__ import annotations

import time
import unittest

from game_data import (
    GameDataClient,
    MapGenerationState,
    MapStat,
    RuntimeGameMode,
    RuntimeGameState,
    StatValue,
)
from memory import MemoryReadError


class FakeMemory:
    def __init__(
        self,
        *,
        module_base: int = 0x10000000,
        pointers: dict[int, int] | None = None,
        integers: dict[int, int] | None = None,
        bytes_: dict[int, int] | None = None,
        strings: dict[int, str | None] | None = None,
        floats: dict[int, float] | None = None,
        broken_i32: set[int] | None = None,
        broken_ptr: set[int] | None = None,
        broken_u8: set[int] | None = None,
        broken_float: set[int] | None = None,
    ) -> None:
        self.module_base = module_base
        self.pointers = pointers or {}
        self.integers = integers or {}
        self.bytes = bytes_ or {}
        self.strings = strings or {}
        self.floats = floats or {}
        self.broken_i32 = broken_i32 or set()
        self.broken_ptr = broken_ptr or set()
        self.broken_u8 = broken_u8 or set()
        self.broken_float = broken_float or set()

    def module_offset(self, _module_name: str, offset: int) -> int:
        return self.module_base + offset

    def read_ptr(self, address: int) -> int:
        if address in self.broken_ptr:
            raise MemoryReadError(f"broken ptr at 0x{address:X}")
        return self.pointers.get(address, 0)

    def read_i32(self, address: int) -> int:
        if address in self.broken_i32:
            raise MemoryReadError(f"broken i32 at 0x{address:X}")
        if address not in self.integers:
            raise MemoryReadError(f"missing i32 at 0x{address:X}")
        return self.integers[address]

    def read_float(self, address: int) -> float:
        if address in self.broken_float:
            raise MemoryReadError(f"broken float at 0x{address:X}")
        if address not in self.floats:
            raise MemoryReadError(f"missing float at 0x{address:X}")
        return self.floats[address]

    def read_u8(self, address: int) -> int:
        if address in self.broken_u8:
            raise MemoryReadError(f"broken u8 at 0x{address:X}")
        if address not in self.bytes:
            raise MemoryReadError(f"missing u8 at 0x{address:X}")
        return self.bytes[address]

    def read_mono_string(self, address: int, max_length: int = 512) -> str | None:
        del max_length
        return self.strings.get(address)


def full_stats(current: int = 0, max_value: int = 1) -> dict[MapStat, StatValue]:
    return {stat: StatValue(current=current, max=max_value) for stat in MapStat}


def build_runtime_state_memory(
    *,
    game_manager_instance: int = 0,
    is_playing: bool = False,
    is_game_over: bool = False,
    is_paused: bool = False,
    is_loading: bool = False,
    run_timer: float = 0.0,
    stage_timer: float = 0.0,
    current_map: int = 0,
    current_stage: int = 0,
    run_config: int = 0,
    player_movement_instance: int = 0,
    music_controller_instance: int = 0,
    music_menu_track: int = 0,
    music_current_track: int = 0,
) -> FakeMemory:
    base = 0x10000000
    game_manager_type_info = base + GameDataClient.GAME_MANAGER_TYPE_INFO_OFFSET
    map_controller_type_info = base + GameDataClient.MAP_CONTROLLER_TYPE_INFO_OFFSET
    my_time_type_info = base + GameDataClient.MY_TIME_TYPE_INFO_OFFSET
    loading_screen_type_info = base + GameDataClient.LOADING_SCREEN_TYPE_INFO_OFFSET
    player_movement_type_info = base + GameDataClient.PLAYER_MOVEMENT_TYPE_INFO_OFFSET
    music_controller_type_info = base + GameDataClient.MUSIC_CONTROLLER_TYPE_INFO_OFFSET
    game_manager_class = 0x20000000
    map_controller_class = 0x20000100
    my_time_class = 0x20000200
    loading_screen_class = 0x20000300
    player_movement_class = 0x20000400
    music_controller_class = 0x20000500
    game_manager_static = 0x30000000
    map_controller_static = 0x30000100
    my_time_static = 0x30000200
    loading_screen_static = 0x30000300
    player_movement_static = 0x30000400
    music_controller_static = 0x30000500

    pointers = {
        game_manager_type_info: game_manager_class,
        map_controller_type_info: map_controller_class,
        my_time_type_info: my_time_class,
        loading_screen_type_info: loading_screen_class,
        player_movement_type_info: player_movement_class,
        music_controller_type_info: music_controller_class,
        game_manager_class + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: game_manager_static,
        map_controller_class + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: map_controller_static,
        my_time_class + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: my_time_static,
        loading_screen_class + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: loading_screen_static,
        player_movement_class + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: player_movement_static,
        music_controller_class + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: music_controller_static,
        game_manager_static + GameDataClient.GAME_MANAGER_INSTANCE_OFFSET: game_manager_instance,
        map_controller_static + GameDataClient.MAP_CONTROLLER_CURRENT_MAP_OFFSET: current_map,
        map_controller_static + GameDataClient.MAP_CONTROLLER_CURRENT_STAGE_OFFSET: current_stage,
        map_controller_static + GameDataClient.MAP_CONTROLLER_RUN_CONFIG_OFFSET: run_config,
        player_movement_static + GameDataClient.PLAYER_MOVEMENT_INSTANCE_OFFSET: player_movement_instance,
        music_controller_static + GameDataClient.MUSIC_CONTROLLER_INSTANCE_OFFSET: music_controller_instance,
    }
    if music_controller_instance:
        pointers.update(
            {
                music_controller_instance + GameDataClient.MUSIC_CONTROLLER_MENU_TRACK_OFFSET: music_menu_track,
                music_controller_instance + GameDataClient.MUSIC_CONTROLLER_CURRENT_TRACK_OFFSET: music_current_track,
            }
        )
    bytes_ = {
        my_time_static + GameDataClient.MY_TIME_PAUSED_OFFSET: int(is_paused),
        loading_screen_static + GameDataClient.LOADING_SCREEN_IS_LOADING_OFFSET: int(is_loading),
    }
    if game_manager_instance:
        bytes_.update(
            {
                game_manager_instance + GameDataClient.GAME_MANAGER_IS_PLAYING_OFFSET: int(is_playing),
                game_manager_instance + GameDataClient.GAME_MANAGER_IS_GAME_OVER_OFFSET: int(is_game_over),
            }
        )
    floats = {
        my_time_static + GameDataClient.MY_TIME_RUN_TIMER_OFFSET: run_timer,
        my_time_static + GameDataClient.MY_TIME_STAGE_TIMER_OFFSET: stage_timer,
    }
    return FakeMemory(module_base=base, pointers=pointers, bytes_=bytes_, floats=floats)


class SequencedGameDataClient(GameDataClient):
    def __init__(
        self,
        *,
        states: list[MapGenerationState],
        stats_snapshots: list[dict[MapStat, StatValue]],
    ) -> None:
        self.states = states
        self.stats_snapshots = stats_snapshots
        self.state_reads = 0
        self.stat_reads = 0

    def get_map_generation_state(self) -> MapGenerationState:
        index = min(self.state_reads, len(self.states) - 1)
        self.state_reads += 1
        return self.states[index]

    def get_map_stats(self) -> dict[MapStat, StatValue]:
        index = min(self.stat_reads, len(self.stats_snapshots) - 1)
        self.stat_reads += 1
        return self.stats_snapshots[index]


class GameDataClientTests(unittest.TestCase):
    def build_memory(self) -> FakeMemory:
        base = 0x10000000
        type_info = base + GameDataClient.TYPE_INFO_OFFSET
        class_ptr = 0x20000000
        static_fields = 0x20000100
        interactables_dict = 0x20000200
        entries = 0x20000300

        key_challenges = 0x30000000
        key_greed = 0x30000080
        key_unknown = 0x30000100
        key_moais = 0x30000180
        key_broken = 0x30000200

        container_challenges = 0x40000000
        container_greed = 0x40000080
        container_boss = 0x40000100
        container_moais = 0x40000180
        container_broken = 0x40000200

        entry0 = entries + GameDataClient.ENTRY_BASE_OFFSET
        entry1 = entry0 + GameDataClient.ENTRY_SIZE
        entry2 = entry1 + GameDataClient.ENTRY_SIZE
        entry3 = entry2 + GameDataClient.ENTRY_SIZE
        entry4 = entry3 + GameDataClient.ENTRY_SIZE
        entry5 = entry4 + GameDataClient.ENTRY_SIZE

        pointers = {
            type_info: class_ptr,
            class_ptr + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: static_fields,
            static_fields: interactables_dict,
            interactables_dict + GameDataClient.DICT_ENTRIES_OFFSET: entries,
            entry0 + GameDataClient.ENTRY_KEY_OFFSET: key_challenges,
            entry0 + GameDataClient.ENTRY_VALUE_OFFSET: container_challenges,
            entry1 + GameDataClient.ENTRY_KEY_OFFSET: key_greed,
            entry1 + GameDataClient.ENTRY_VALUE_OFFSET: container_greed,
            entry2 + GameDataClient.ENTRY_KEY_OFFSET: key_unknown,
            entry2 + GameDataClient.ENTRY_VALUE_OFFSET: container_boss,
            entry3 + GameDataClient.ENTRY_KEY_OFFSET: 0,
            entry3 + GameDataClient.ENTRY_VALUE_OFFSET: 0x40000120,
            entry4 + GameDataClient.ENTRY_KEY_OFFSET: key_moais,
            entry4 + GameDataClient.ENTRY_VALUE_OFFSET: container_moais,
            entry5 + GameDataClient.ENTRY_KEY_OFFSET: key_broken,
            entry5 + GameDataClient.ENTRY_VALUE_OFFSET: container_broken,
        }
        integers = {
            interactables_dict + GameDataClient.DICT_COUNT_OFFSET: 6,
            container_challenges + GameDataClient.CONTAINER_MAX_OFFSET: 5,
            container_challenges + GameDataClient.CONTAINER_CURRENT_OFFSET: 2,
            container_greed + GameDataClient.CONTAINER_MAX_OFFSET: 3,
            container_greed + GameDataClient.CONTAINER_CURRENT_OFFSET: 1,
            container_boss + GameDataClient.CONTAINER_MAX_OFFSET: 4,
            container_boss + GameDataClient.CONTAINER_CURRENT_OFFSET: 1,
            container_moais + GameDataClient.CONTAINER_MAX_OFFSET: 7,
            container_moais + GameDataClient.CONTAINER_CURRENT_OFFSET: 4,
        }
        strings = {
            key_challenges: "Challenges",
            key_greed: "Greed Shrines",
            key_unknown: "Boss Curses",
            key_moais: "Moais",
            key_broken: "Pots",
        }

        return FakeMemory(
            module_base=base,
            pointers=pointers,
            integers=integers,
            strings=strings,
            broken_i32={
                container_broken + GameDataClient.CONTAINER_MAX_OFFSET,
                container_broken + GameDataClient.CONTAINER_CURRENT_OFFSET,
            },
        )

    def test_get_map_stats_returns_only_known_found_stats(self) -> None:
        memory = self.build_memory()
        client = GameDataClient(memory=memory)

        stats = client.get_map_stats()

        self.assertEqual(
            stats,
            {
                MapStat.BOSS_CURSES: StatValue(current=1, max=4),
                MapStat.CHALLENGES: StatValue(current=2, max=5),
                MapStat.GREED_SHRINES: StatValue(current=1, max=3),
                MapStat.MOAIS: StatValue(current=4, max=7),
            },
        )
        self.assertNotIn(MapStat.POTS, stats)

    def test_get_map_stats_returns_empty_when_root_pointer_is_null(self) -> None:
        base = 0x10000000
        type_info = base + GameDataClient.TYPE_INFO_OFFSET
        memory = FakeMemory(module_base=base, pointers={type_info: 0})
        client = GameDataClient(memory=memory)

        self.assertEqual(client.get_map_stats(), {})

    def test_get_map_stats_raises_on_invalid_dictionary_count(self) -> None:
        base = 0x10000000
        type_info = base + GameDataClient.TYPE_INFO_OFFSET
        class_ptr = 0x20000000
        static_fields = 0x20000100
        interactables_dict = 0x20000200
        entries = 0x20000300
        memory = FakeMemory(
            module_base=base,
            pointers={
                type_info: class_ptr,
                class_ptr + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: static_fields,
                static_fields: interactables_dict,
                interactables_dict + GameDataClient.DICT_ENTRIES_OFFSET: entries,
            },
            integers={
                interactables_dict + GameDataClient.DICT_COUNT_OFFSET: 5000,
            },
        )
        client = GameDataClient(memory=memory)

        with self.assertRaises(MemoryReadError):
            client.get_map_stats()

    def test_get_map_generation_state_reads_static_fields(self) -> None:
        base = 0x10000000
        map_generation_type_info = base + GameDataClient.MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET
        map_controller_type_info = base + GameDataClient.MAP_CONTROLLER_TYPE_INFO_OFFSET
        map_generation_class = 0x20000000
        map_controller_class = 0x20000100
        map_generation_static = 0x30000000
        map_controller_static = 0x30000100
        current_map = 0x40000000
        current_stage = 0x40000100

        memory = FakeMemory(
            module_base=base,
            pointers={
                map_generation_type_info: map_generation_class,
                map_controller_type_info: map_controller_class,
                map_generation_class + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: map_generation_static,
                map_controller_class + GameDataClient.CLASS_STATIC_FIELDS_OFFSET: map_controller_static,
                map_controller_static + GameDataClient.MAP_CONTROLLER_CURRENT_MAP_OFFSET: current_map,
                map_controller_static + GameDataClient.MAP_CONTROLLER_CURRENT_STAGE_OFFSET: current_stage,
            },
            integers={
                map_generation_static + GameDataClient.MAP_GENERATION_MAP_SEED_OFFSET: 12345,
            },
            bytes_={
                map_generation_static + GameDataClient.MAP_GENERATION_IS_GENERATING_OFFSET: 1,
                map_controller_static + GameDataClient.MAP_CONTROLLER_RESETING_OFFSET: 1,
            },
        )
        client = GameDataClient(memory=memory)

        self.assertEqual(
            client.get_map_generation_state(),
            MapGenerationState(
                is_generating=True,
                map_seed=12345,
                current_map_ptr=current_map,
                current_stage_ptr=current_stage,
                is_resetting=True,
            ),
        )

    def test_get_map_generation_state_handles_missing_static_fields(self) -> None:
        client = GameDataClient(memory=FakeMemory())

        self.assertEqual(client.get_map_generation_state(), MapGenerationState())

    def test_get_runtime_game_state_detects_main_menu(self) -> None:
        memory = build_runtime_state_memory()
        client = GameDataClient(memory=memory)

        self.assertEqual(
            client.get_runtime_game_state(),
            RuntimeGameState(
                mode=RuntimeGameMode.MAIN_MENU,
                run_timer_seconds=0.0,
                stage_timer_seconds=0.0,
            ),
        )

    def test_get_runtime_game_state_detects_active_run(self) -> None:
        memory = build_runtime_state_memory(
            game_manager_instance=0x40000000,
            is_playing=True,
            is_game_over=False,
            is_paused=False,
            run_timer=82.5,
            stage_timer=82.5,
            current_map=0x50000000,
            current_stage=0x50000100,
            run_config=0x50000200,
        )
        client = GameDataClient(memory=memory)

        state = client.get_runtime_game_state()

        self.assertEqual(state.mode, RuntimeGameMode.IN_GAME)
        self.assertTrue(state.is_active_run)
        self.assertFalse(state.is_paused_run)
        self.assertFalse(state.is_main_menu)
        self.assertEqual(state.game_manager_ptr, 0x40000000)
        self.assertTrue(state.is_playing)
        self.assertFalse(state.is_game_over)
        self.assertFalse(state.is_paused)
        self.assertEqual(state.run_timer_seconds, 82.5)
        self.assertEqual(state.stage_timer_seconds, 82.5)
        self.assertEqual(state.current_map_ptr, 0x50000000)
        self.assertEqual(state.current_stage_ptr, 0x50000100)
        self.assertEqual(state.run_config_ptr, 0x50000200)

    def test_get_runtime_game_state_detects_paused_run(self) -> None:
        memory = build_runtime_state_memory(
            game_manager_instance=0x40000000,
            is_playing=True,
            is_game_over=False,
            is_paused=True,
            run_timer=14.5,
            stage_timer=14.5,
            current_map=0x50000000,
            current_stage=0x50000100,
            run_config=0x50000200,
        )
        client = GameDataClient(memory=memory)

        state = client.get_runtime_game_state()

        self.assertEqual(state.mode, RuntimeGameMode.PAUSED_IN_GAME)
        self.assertTrue(state.is_active_run)
        self.assertTrue(state.is_paused_run)
        self.assertFalse(state.is_main_menu)
        self.assertTrue(state.is_paused)

    def test_get_runtime_game_state_leaves_game_over_unknown(self) -> None:
        memory = build_runtime_state_memory(
            game_manager_instance=0x40000000,
            is_playing=True,
            is_game_over=True,
            is_paused=False,
        )
        client = GameDataClient(memory=memory)

        state = client.get_runtime_game_state()

        self.assertEqual(state.mode, RuntimeGameMode.GAME_OVER)
        self.assertTrue(state.is_game_over_run)

    def test_get_runtime_game_state_detects_manual_menu_after_game_manager_survives(self) -> None:
        memory = build_runtime_state_memory(
            game_manager_instance=0x40000000,
            is_playing=True,
            is_game_over=False,
            is_paused=False,
            run_timer=120.0,
            stage_timer=40.0,
            current_map=0x50000000,
            current_stage=0x50000100,
            run_config=0x50000200,
            player_movement_instance=0,
            music_controller_instance=0x60000000,
            music_menu_track=0x70000000,
            music_current_track=0x70000000,
        )
        client = GameDataClient(memory=memory)

        state = client.get_runtime_game_state()

        self.assertEqual(state.mode, RuntimeGameMode.MAIN_MENU)
        self.assertTrue(state.is_main_menu)
        self.assertEqual(state.music_controller_ptr, 0x60000000)
        self.assertEqual(state.music_current_track_ptr, 0x70000000)
        self.assertEqual(state.music_menu_track_ptr, 0x70000000)

    def test_wait_for_map_ready_waits_for_generation_and_stable_stats(self) -> None:
        ready_state = MapGenerationState(
            is_generating=False,
            map_seed=2,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        changed_stats = full_stats(current=1)
        stable_stats = full_stats(current=2)
        client = SequencedGameDataClient(
            states=[
                MapGenerationState(is_generating=True, map_seed=1),
                ready_state,
                ready_state,
                ready_state,
            ],
            stats_snapshots=[
                {},
                changed_stats,
                stable_stats,
                stable_stats,
            ],
        )

        self.assertEqual(
            client.wait_for_map_ready(previous_seed=1, timeout=1.0, poll_interval=0.001),
            stable_stats,
        )

    def test_wait_for_map_ready_rejects_empty_stats(self) -> None:
        ready_state = MapGenerationState(
            is_generating=False,
            map_seed=2,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        stable_stats = full_stats(current=2)
        client = SequencedGameDataClient(
            states=[ready_state, ready_state, ready_state],
            stats_snapshots=[{}, stable_stats, stable_stats],
        )

        self.assertEqual(
            client.wait_for_map_ready(previous_seed=1, timeout=1.0, poll_interval=0.001),
            stable_stats,
        )

    def test_wait_for_map_ready_allows_missing_stats(self) -> None:
        ready_state = MapGenerationState(
            is_generating=False,
            map_seed=2,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        stable_stats = full_stats(current=1)
        stable_stats.pop(MapStat.BOSS_CURSES)
        stable_stats.pop(MapStat.CHALLENGES)
        client = SequencedGameDataClient(
            states=[ready_state, ready_state],
            stats_snapshots=[stable_stats, stable_stats],
        )

        self.assertEqual(
            client.wait_for_map_ready(previous_seed=1, timeout=1.0, poll_interval=0.001),
            stable_stats,
        )

    def test_wait_for_map_ready_treats_missing_previous_stat_as_zero_change(self) -> None:
        ready_state = MapGenerationState(
            is_generating=False,
            map_seed=1,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        old_stats = full_stats(current=1)
        new_stats = full_stats(current=1)
        new_stats.pop(MapStat.BOSS_CURSES)
        client = SequencedGameDataClient(
            states=[ready_state, ready_state],
            stats_snapshots=[new_stats, new_stats],
        )

        self.assertEqual(
            client.wait_for_map_ready(
                previous_seed=1,
                previous_stats=old_stats,
                timeout=1.0,
                poll_interval=0.001,
            ),
            new_stats,
        )

    def test_wait_for_map_ready_does_not_treat_same_missing_stat_as_change(self) -> None:
        ready_state = MapGenerationState(
            is_generating=False,
            map_seed=1,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        old_stats = full_stats(current=1)
        old_stats.pop(MapStat.BOSS_CURSES)
        new_stats = full_stats(current=1)
        new_stats.pop(MapStat.BOSS_CURSES)
        client = SequencedGameDataClient(
            states=[ready_state],
            stats_snapshots=[new_stats],
        )

        with self.assertRaisesRegex(TimeoutError, "change_seen=False"):
            client.wait_for_map_ready(
                previous_seed=1,
                previous_stats=old_stats,
                timeout=0.01,
                poll_interval=0.001,
            )

    def test_wait_for_map_ready_ignores_missing_bald_heads_in_previous_stats(self) -> None:
        ready_state = MapGenerationState(
            is_generating=False,
            map_seed=1,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        old_stats = full_stats(current=1)
        new_stats = full_stats(current=1)
        new_stats.pop(MapStat.BALD_HEADS)
        client = SequencedGameDataClient(
            states=[ready_state],
            stats_snapshots=[new_stats],
        )

        with self.assertRaisesRegex(TimeoutError, "change_seen=False"):
            client.wait_for_map_ready(
                previous_seed=1,
                previous_stats=old_stats,
                timeout=0.01,
                poll_interval=0.001,
            )

    def test_wait_for_map_ready_can_use_previous_stats_as_baseline(self) -> None:
        ready_state = MapGenerationState(
            is_generating=False,
            map_seed=1,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        old_stats = full_stats(current=1)
        new_stats = full_stats(current=2)
        client = SequencedGameDataClient(
            states=[ready_state, ready_state],
            stats_snapshots=[new_stats, new_stats],
        )

        self.assertEqual(
            client.wait_for_map_ready(
                previous_seed=1,
                previous_stats=old_stats,
                timeout=1.0,
                poll_interval=0.001,
            ),
            new_stats,
        )

    def test_wait_for_map_ready_detects_pointer_change_without_seed_change(self) -> None:
        previous_state = MapGenerationState(
            is_generating=False,
            map_seed=1,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        ready_state = MapGenerationState(
            is_generating=False,
            map_seed=1,
            current_map_ptr=0x50000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        stable_stats = full_stats(current=1)
        client = SequencedGameDataClient(
            states=[ready_state, ready_state],
            stats_snapshots=[stable_stats, stable_stats],
        )

        self.assertEqual(
            client.wait_for_map_ready(
                previous_state=previous_state,
                previous_stats=stable_stats,
                timeout=1.0,
                poll_interval=0.001,
            ),
            stable_stats,
        )

    def test_wait_for_map_ready_times_out_when_ready_state_never_changes(self) -> None:
        previous_state = MapGenerationState(
            is_generating=False,
            map_seed=1,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        stable_stats = full_stats(current=1)
        client = SequencedGameDataClient(
            states=[previous_state],
            stats_snapshots=[stable_stats],
        )

        with self.assertRaisesRegex(TimeoutError, "change_seen=False"):
            client.wait_for_map_ready(
                previous_state=previous_state,
                previous_stats=stable_stats,
                timeout=0.01,
                poll_interval=0.001,
            )

    def test_wait_for_map_ready_ignores_missing_seed_and_pointers_as_change(self) -> None:
        previous_state = MapGenerationState(
            is_generating=False,
            map_seed=1,
            current_map_ptr=0x40000000,
            current_stage_ptr=0x40000100,
            is_resetting=False,
        )
        unreadable_state = MapGenerationState(
            is_generating=False,
            map_seed=None,
            current_map_ptr=0,
            current_stage_ptr=0,
            is_resetting=False,
        )
        stable_stats = full_stats(current=1)
        client = SequencedGameDataClient(
            states=[unreadable_state],
            stats_snapshots=[stable_stats],
        )

        with self.assertRaisesRegex(TimeoutError, "change_seen=False"):
            client.wait_for_map_ready(
                previous_state=previous_state,
                previous_stats=stable_stats,
                timeout=0.01,
                poll_interval=0.001,
            )

    def test_wait_for_map_ready_times_out_with_state(self) -> None:
        client = SequencedGameDataClient(
            states=[MapGenerationState(is_generating=True, map_seed=1)],
            stats_snapshots=[{}],
        )

        start = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "Last state"):
            client.wait_for_map_ready(previous_seed=1, timeout=0.01, poll_interval=0.001)
        self.assertLess(time.monotonic() - start, 0.5)


if __name__ == "__main__":
    unittest.main()
