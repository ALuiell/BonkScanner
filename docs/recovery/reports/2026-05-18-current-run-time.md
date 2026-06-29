# Current Run Time Memory Path

Date: 2026-05-18

## Goal

Document the reverse path used to read the live in-game run timer shown in the
top-left HUD clock in Megabonk.

The target value is the run timer that starts at `0:00` when a run begins and
counts upward in seconds while the run is active. The HUD formats it as
`M:SS`.

## Confirmed Stable Pointer Path

The live run timer is stored in `Assets.Scripts.Utility.MyTime.runTimer`.

The implementation-relevant path is:

```text
GameAssembly.dll + 0x02F62398
-> +0xB8
-> +0x20
```

In Cheat Engine pointer-entry order, offsets are entered top-to-bottom as:

```text
20
B8
```

For CE:

```text
Base address: GameAssembly.dll+02F62398
Type: Float
Pointer: enabled
Hexadecimal value display: disabled
Offsets top-to-bottom:
  20
  B8
```

## Value Type And Units

- Type: `float`
- Semantic meaning: current run elapsed time
- Units: seconds

Examples:

```text
HUD 0:21  -> memory ~= 21.52
HUD 9:43  -> memory ~= 583.x
```

The fractional part is expected because the stored value is a live float while
the HUD rounds or truncates to whole seconds for display.

## Reverse Evidence

The dump shows a dedicated static utility class:

```text
Assets.Scripts.Utility.MyTime
```

Its static fields in `il2cpp.h` include:

```text
bool paused
float time
float deltaTime
float fixedDeltaTime
float _timeScale_k__BackingField
int tick
int unpauseTick
float stageTimer
float runTimer
float finalSwarmTimer
float difficultyTimer
float cryptTimer
```

So `runTimer` is not an inferred alias. It exists as a named static float in
the dumped type layout.

The dump also shows the HUD-side timer class:

```text
GameTimer
```

with fields:

```text
TextMeshProUGUI t_timerRun
TextMeshProUGUI t_timerStage
TextMeshProUGUI t_timerSpeedrun
```

and update methods:

```text
GameTimer.FixedUpdate()
GameTimer.UpdateTimers()
GameTimer.UpdateTimer(...)
```

This is strong structural evidence that the run HUD clock is driven by the same
timer subsystem rather than by an unrelated UI-only cached string.

## Live Validation

Live CE bridge validation on 2026-05-18:

- attached process: `Megabonk.exe`
- candidate record:
  - address: `[[GameAssembly.dll+2F62398]+B8]+20`
  - type: `float`
- observed value while the HUD showed `0:21`:
  - `21.52338219`

That matches the expected unit and display behavior closely enough to confirm
the source.

## Implementation Path Used In This Repo

Current code reads the timer through:

```text
src/player_stats.py
PlayerStatsClient.get_run_timer()
```

using:

```text
RUN_TIMER_TYPE_INFO_OFFSET = 0x02F62398
CLASS_STATIC_FIELDS_OFFSET = 0xB8
RUN_TIMER_OFFSET = 0x20
```

## Caveats

- This value is a float in seconds, not a preformatted string.
- The HUD only shows minutes and seconds, so sub-second precision is expected
  to be hidden from the player.
- We have confirmed value meaning and units.
- We have not yet fully characterized all edge behavior for:
  - pause menu
  - post-death state
  - loading transitions
  - special slow/fast time effects

Those can be documented later if compare-by-time features become important.

## Recommended Usage

For recordings:

- store this as a dedicated field such as `in_game_elapsed_seconds`
- keep the existing recorder-local `elapsed_seconds` field for backward
  compatibility and recorder diagnostics

For live comparisons:

- treat `runTimer` as the authoritative in-game elapsed time source
- do not derive it from wall-clock capture timing
