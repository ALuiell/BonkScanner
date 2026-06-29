# Teleport Memory Detection Notes

Date: 2026-06-04

Source dump: `F:\Python\CA_mpc_bridge\Dump`

Files checked:

- `dump.cs`
- `script.json`
- `il2cpp.h`
- `stringliteral.json`

Goal: find memory-only signals that can detect when the player uses a stage portal/teleport, without adding a new native hook.

## Summary

The dump contains direct portal and teleport symbols. The most relevant game-side flow appears to be:

1. `InteractablePortal.Interact()`
2. `InteractablePortal.DoLoadNextStage()`
3. `MyPlayer.TeleportPlayerNextStage()`
4. `MyPlayer.TeleportEnd()`
5. `MapController.LoadNextStage()`
6. `MapController.currentStage/index` update

For a memory-only implementation, the best practical signals are:

- Read `MapController.index` for current stage index.
- Read `MapController.currentStage` and detect pointer changes.
- Optionally read `MyPlayer.Instance.isTeleporting` as a short-lived transition flag.

The most reliable memory-only detector is likely a combined edge detector:

- `isTeleporting` changes `false -> true`, or
- `currentStage` pointer changes, or
- `MapController.index` increases.

Using only `currentStage`/`index` detects that a stage transition happened. Using `isTeleporting` adds a closer signal to the actual teleport animation, but it may be short-lived and may also cover non-portal player teleports.

## Important Strings

Found in `stringliteral.json`:

- `ENTER_PORTAL`
- `FINAL_PORTAL`
- `SpawnPortal`
- `TeleportEnd`
- `Teleported to next stage (Stage {0})`
- `Next Stage ({0})`
- `numStages`
- `skip_portal_animation`
- `FinalBossMap`

These confirm that the dumped build has explicit portal/teleport concepts rather than only generic scene loading.

## MapController

Class:

```text
Assets.Scripts.Managers.MapController
```

TypeInfo:

```text
Assets.Scripts.Managers.MapController_TypeInfo = GameAssembly.dll + 0x2F58E08
```

This TypeInfo offset is already used by the project.

Static fields from `dump.cs` / `il2cpp.h`:

```text
static PlayerInventory inventory                 // static fields + 0x0
static int index                                  // static fields + 0x8
static MapData currentMap                         // static fields + 0x10
static StageData currentStage                     // static fields + 0x18
static bool isFinalBossStage                      // static fields + 0x20
static bool reseting                              // static fields + 0x21
static Action A_NewRunStarted                     // static fields + 0x28
static RunConfig runConfig                        // static fields + 0x30
static string mainMenuSceneName                   // static fields + 0x38
```

Relevant methods:

```text
MapController.GetStageIndex() = GameAssembly.dll + 0x4218B0
MapController.LoadNextStage() = GameAssembly.dll + 0x421DF0
MapController.LoadFinalStage() = GameAssembly.dll + 0x421C00
MapController.RestartRun() = GameAssembly.dll + 0x4220B0
```

Memory read path:

```text
type_info_addr = GameAssembly.dll + 0x2F58E08
class_ptr = read_ptr(type_info_addr)
static_fields = read_ptr(class_ptr + 0xB8)
stage_index = read_i32(static_fields + 0x8)
current_map = read_ptr(static_fields + 0x10)
current_stage = read_ptr(static_fields + 0x18)
is_final_boss_stage = read_u8(static_fields + 0x20) != 0
is_resetting = read_u8(static_fields + 0x21) != 0
```

Recommended use:

- Treat `currentStage` pointer change as a stage transition signal.
- Treat `index` increase as a stronger stage index signal.
- Keep `currentMap/currentStage != 0` as a loaded-map sanity check.
- Ignore transitions while `reseting` is true.

Open question:

- Confirm whether `index` is zero-based or one-based in live memory. The method name `GetStageIndex()` strongly suggests it is an index, but UI/log text may add 1.

## MyPlayer

Class:

```text
Assets.Scripts.Actors.Player.MyPlayer
```

TypeInfo:

```text
Assets.Scripts.Actors.Player.MyPlayer_TypeInfo = GameAssembly.dll + 0x2F620F8
```

Relevant static fields:

```text
static Action<PlayerInventory> A_PlayerInventoryInitialized  // static fields + 0x0
static MyPlayer Instance                                     // static fields + 0x8
static Action A_PrePlayerSpawn                               // static fields + 0x10
static Action A_Collided                                     // static fields + 0x18
static Action A_CollidedEnemy                                // static fields + 0x20
static float defaultBaseDamage                               // static fields + 0x28
```

Relevant instance field:

```text
bool isTeleporting // player instance + 0x128
```

Relevant methods:

```text
MyPlayer.TeleportPlayerNextStage() = GameAssembly.dll + 0x4B6EB0
MyPlayer.TeleportPlayerImmediate(...) = GameAssembly.dll + 0x4B6E00
MyPlayer.TeleportEnd() = GameAssembly.dll + 0x4B6D90
```

Memory read path:

```text
type_info_addr = GameAssembly.dll + 0x2F620F8
class_ptr = read_ptr(type_info_addr)
static_fields = read_ptr(class_ptr + 0xB8)
player = read_ptr(static_fields + 0x8)
is_teleporting = read_u8(player + 0x128) != 0
```

Recommended use:

- Poll `isTeleporting` frequently enough to catch a short transition window.
- Detect rising edge: previous `false`, current `true`.
- Do not rely on this alone for stage transitions, because `TeleportPlayerImmediate()` exists and may share the same flag.
- Combine it with `MapController.currentStage` or `MapController.index` to distinguish next-stage portal teleports from other player teleports.

## Portal Classes

These are useful context even if no hook is planned.

Normal portal:

```text
InteractablePortal.Interact() = GameAssembly.dll + 0x4CCDB0
InteractablePortal.DoLoadNextStage() = GameAssembly.dll + 0x4CCCF0
InteractablePortal.<DoLoadNextStage>d__6.MoveNext() = GameAssembly.dll + 0x4D9480
```

Fields:

```text
bool done       // instance + 0x58
bool restarted  // instance + 0x59
```

Final portal:

```text
InteractablePortalFinal.Interact() = GameAssembly.dll + 0x4CCA20
InteractablePortalFinal.DoFinishGame() = GameAssembly.dll + 0x4CC960
InteractablePortalFinal.<DoFinishGame>d__3.MoveNext() = GameAssembly.dll + 0x4D8D60
```

These methods are the best exact hook points if memory-only detection turns out to be too weak. For now, keep them as reference only.

## Suggested Memory-Only Detector

Suggested state to store between polls:

```text
previous_stage_index
previous_stage_ptr
previous_is_teleporting
last_transition_time
```

Suggested current snapshot:

```text
stage_index = MapController.index
stage_ptr = MapController.currentStage
is_resetting = MapController.reseting
player_ptr = MyPlayer.Instance
is_teleporting = MyPlayer.Instance.isTeleporting
```

Detection logic:

```text
teleport_started =
    previous_is_teleporting == false
    and is_teleporting == true
    and currentStage != 0
    and not is_resetting

stage_changed =
    previous_stage_ptr != 0
    and current_stage_ptr != 0
    and previous_stage_ptr != current_stage_ptr
    and not is_resetting

stage_index_changed =
    previous_stage_index is not None
    and stage_index is not None
    and stage_index > previous_stage_index
    and not is_resetting
```

Recommended event types:

```text
portal_or_teleport_started:
    emitted on isTeleporting rising edge

stage_transition_confirmed:
    emitted on currentStage pointer change or index increase
```

The confirmed transition is safer for stats/announcements. The start edge is better for immediate UI feedback.

## Polling Interval

`isTeleporting` may be brief. A 1-second polling loop can miss it.

Recommended intervals:

- `50 ms` if this is part of a dedicated live memory loop.
- `100 ms` is probably acceptable.
- `250 ms` may work but can miss short animation-skipped transitions.

If only stage completion matters, `currentStage`/`index` can be polled slower because the changed value persists.

## Risk Notes

- `MapController.index` may be zero-based. Verify live.
- `currentStage` pointer changes are reliable for stage transitions, but not necessarily the exact moment the player pressed portal.
- `isTeleporting` is closer to the teleport action, but not guaranteed to mean the normal portal specifically.
- `skip_portal_animation` may make the teleporting window shorter.
- Final portal/end-game flow is separate: `InteractablePortalFinal` and `FINAL_PORTAL`.
- Offsets are build-specific and must be refreshed after a game update.

## Minimal Future Implementation Sketch

Add constants to `GameDataClient` only when ready:

```python
MY_PLAYER_TYPE_INFO_OFFSET = 0x2F620F8
MAP_CONTROLLER_STAGE_INDEX_OFFSET = 0x8
MY_PLAYER_INSTANCE_OFFSET = 0x8
MY_PLAYER_IS_TELEPORTING_OFFSET = 0x128
```

Then add a small snapshot dataclass:

```python
@dataclass(frozen=True)
class TeleportMemoryState:
    stage_index: int | None = None
    current_stage_ptr: int = 0
    is_resetting: bool = False
    player_ptr: int = 0
    is_player_teleporting: bool = False
```

Read it using the same `_read_static_fields`, `_read_i32_optional`, `_read_ptr_optional`, and `_read_bool` helpers already present in `src/game_data.py`.

## Best First Experiment

Before wiring UI or Twitch events, log these values during a live run:

```text
time
MapController.index
MapController.currentStage
MapController.reseting
MyPlayer.Instance
MyPlayer.isTeleporting
MyTime.stageTimer
```

Perform:

1. Start run.
2. Enter normal next-stage portal.
3. Enter another normal portal.
4. Use any non-stage player teleport if available.
5. Finish via final portal.

Expected result:

- Normal portal should produce `isTeleporting` rising edge and then `currentStage/index` change.
- Non-stage teleport may produce `isTeleporting` without `currentStage/index` change.
- Final portal may not produce a next-stage `currentStage/index` increase.
