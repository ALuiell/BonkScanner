# Part 11: Game Lifecycle and Bosses Recovery Guide

## Overview
This component monitors core game readiness, match lifecycle states, loading transitions, and special stage boss states (specifically Graveyard RSG boss rooms).

- **Target Files**:
  - Code: `src/infra/memory/game_data_client.py`, `src/infra/memory/player_stats_client.py`
  - Unit Tests: `src/tests/test_game_data.py`, `src/tests/test_player_stats.py`, `src/tests/test_live_run_tracker.py`

---

## Memory Chain Diagrams

### 1. RSG Controller & Graveyard Boss State
Graveyard stage boss runs in a dedicated random stage generator (RSG) room. `MapController.isFinalBossStage` remains false on Graveyard; boss progression is verified directly through `RSGController`:

```
GameAssembly.dll + RSG_CONTROLLER_TYPE_INFO_OFFSET (0x02F79E50)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x20 (RSG_INSTANCE_OFFSET) -> [RSG Controller Instance Pointer]
        -> +0x48 (RSG_ROOM_BOSS_OFFSET) -> [GraveyardBossRoom Object Pointer]
          -> +0x38 (GRAVEYARD_BOSS_IS_FIGHTING_OFFSET) -> bool (is_fighting)
          -> +0xA0 (GRAVEYARD_BOSS_IS_DEFEATED_OFFSET) -> bool (is_defeated)
```

### 2. GameManager State
```
GameAssembly.dll + GAME_MANAGER_TYPE_INFO_OFFSET (0x02F9C1C0)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x0 (GAME_MANAGER_INSTANCE_OFFSET) -> [GameManager Instance Pointer]
        -> +0x74 (GAME_MANAGER_IS_GAME_OVER_OFFSET) -> bool (is_game_over)
        -> +0x84 (GAME_MANAGER_IS_PLAYING_OFFSET)   -> bool (is_playing)
```

### 3. LoadingScreen State
```
GameAssembly.dll + LOADING_SCREEN_TYPE_INFO_OFFSET (0x02F55E20)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x10 (LOADING_SCREEN_IS_LOADING_OFFSET) -> bool (is_loading)
```

### 4. MusicController (Menu vs In-Game)
```
GameAssembly.dll + MUSIC_CONTROLLER_TYPE_INFO_OFFSET (0x02F617C8)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x0 (MUSIC_CONTROLLER_INSTANCE_OFFSET) -> [MusicController Instance Pointer]
        -> +0x40 (MUSIC_CONTROLLER_MENU_TRACK_OFFSET)    -> pointer (menu_track)
        -> +0x48 (MUSIC_CONTROLLER_CURRENT_TRACK_OFFSET) -> pointer (current_track)
```

### 5. PlayerMovement Readiness
```
GameAssembly.dll + PLAYER_MOVEMENT_TYPE_INFO_OFFSET (0x02F6D670)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x18 (PLAYER_MOVEMENT_INSTANCE_OFFSET) -> pointer (player_movement_instance)
```

---

## Reversing Walkthrough (Il2CppDumper & Cheat Engine)

1. **Locate RSGController**:
   - In `dump.cs`, search for `public class RSGController`.
   - Note static instance offset (`+0x20`) and field `roomBoss` (`+0x48`).
   - In `dump.cs`, check `GraveyardBossRoom` for `isFighting` (`+0x38`) and `isDefeated` (`+0xA0`).
   - Extract `RSG_CONTROLLER_TYPE_INFO_OFFSET` from `script.json` / IDA Pro symbols.

2. **Locate Lifecycle Controllers**:
   - `GameManager`: inspect `isPlaying` and `isGameOver`.
   - `LoadingScreen`: inspect `isLoading`.
   - `MusicController`: inspect `menuTrack` and `currentTrack`.

---

## Verification Steps

1. Run player stats and tracker tests:
   ```powershell
   .\run_tests.bat src.tests.test_player_stats
   .\run_tests.bat src.tests.test_game_data
   ```
2. Launch game, enter Graveyard map, trigger boss room, and verify Live Stats / overlay registers fighting and defeat states.
