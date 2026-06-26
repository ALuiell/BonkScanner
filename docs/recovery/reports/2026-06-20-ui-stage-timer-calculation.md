# UI Stage Timer Calculation and Formatting

Date: 2026-06-20

## Goal

Document the reverse-engineered logic and memory paths used to calculate and format the live in-game UI Stage Timer shown at the top center of the screen in Megabonk.

This allows the scanner to record events (e.g. powerup drop, pickup, and expiration) matching the exact UI timestamps seen by the player, including during the countdown phase and the overtime (Ghost/Overtime Phase) period.

## Confirmed Stable Pointer Path

### 1. In-game Stage Timer Accumulator

The raw elapsed stage time is kept in the static fields of `MyTime`:

```text
GameAssembly.dll + 0x2F62398  (MyTime_TypeInfo)
-> +0xB8 (class static fields pointer)
   -> +0x1C (stageTimer, float)
```

### 2. Stage Configuration

The configured limit of the stage is stored in the current map/stage controller:

```text
GameAssembly.dll + 0x2F58E08  (MapController_TypeInfo)
-> +0xB8 (class static fields pointer)
   -> +0x08 (index, int, 0-indexed stage number)
   -> +0x18 (currentStage, pointer to StageData)
```

From `currentStage` (if initialized and not null):
```text
currentStage
-> +0xD0 (stageTimeline, pointer to StageTimeline)
   -> +0x10 (stageTime, float, total duration in seconds)
```

## Calculation & Formatting Formula

The UI timer undergoes a phase transition depending on whether the raw stage timer has exceeded the configured duration of the stage.

Let $T_{\text{raw}}$ be `MyTime.stageTimer` and $T_{\text{limit}}$ be `StageData.stageTimeline.stageTime`.

### Phase A: Countdown ($T_{\text{raw}} \le T_{\text{limit}}$)

The timer counts down from the stage duration to zero.

$$\text{Time Displayed} = T_{\text{limit}} - T_{\text{raw}}$$

1. Convert to integer minutes and seconds:
   - $M = \lfloor \text{Time Displayed} \rfloor \mathbin{/} 60$
   - $S = \lfloor \text{Time Displayed} \rfloor \bmod 60$
2. Format as `MM:SS` (e.g., `08:42`).

### Phase B: Overtime / Ghost Phase ($T_{\text{raw}} > T_{\text{limit}}$)

The timer counts up from zero with a prepended `+` character.

$$\text{Time Displayed} = T_{\text{raw}} - T_{\text{limit}}$$

1. Convert to integer minutes and seconds:
   - $M = \lfloor \text{Time Displayed} \rfloor \mathbin{/} 60$
   - $S = \lfloor \text{Time Displayed} \rfloor \bmod 60$
2. Format as `+MM:SS` (e.g., `+02:46`).

---

## Stage Durations

| Stage Index | Stage Name | Configured Duration ($T_{\text{limit}}$) | Countdown Starts From |
|---|---|---|---|
| **0** | Stage 1 | `600.0` seconds | `10:00` |
| **1** | Stage 2 | `540.0` seconds | `09:00` |
| **2** | Stage 3 | `480.0` seconds | `08:00` |
| **3** | Stage 4 (Boss Stage) | *Special Stage / Ignored for tracking* | - |

If `currentStage` is not loaded (e.g. during scene load transitions), the scanner should fallback to hardcoded stage durations based on `MapController.index`.

---

## Live Verification Examples

Live verification was performed on `Megabonk.exe` (Stage 2 in Overtime Phase):

- `MapController.index`: `1` (Stage 2)
- `currentStage` pointer: `0x1b9b26a8ea0`
- `StageTimeline` pointer: `0x1b9b26aafc0`
- `StageTimeline.stageTime`: `540.00` seconds (9 minutes)
- `MyTime.stageTimer`: `784.4388` seconds
- **Calculation:**
  - $\text{Time Displayed} = 784.4388 - 540.0 = 244.4388$ seconds.
  - $M = 244 \mathbin{/} 60 = 4$
  - $S = 244 \bmod 60 = 4$
  - Result: `+04:04` (perfect match with the game's UI overlay).

---

## Reference Implementation

The following python function demonstrates how the UI timer is constructed:

```python
def get_ui_stage_timer(self) -> str:
    # 1. Resolve MyTime static fields and get stageTimer
    my_time_statics = self._read_static_fields(self.MY_TIME_TYPE_INFO_OFFSET)
    stage_timer = self.memory.read_float(my_time_statics + 0x1C)

    # 2. Resolve MapController static fields and get stage duration limit
    map_controller_statics = self._read_static_fields(self.MAP_CONTROLLER_TYPE_INFO_OFFSET)
    current_stage = self.memory.read_ptr(map_controller_statics + 0x18)

    stage_duration = 600.0  # Default fallback
    if current_stage:
        timeline_ptr = self.memory.read_ptr(current_stage + 0xD0)
        if timeline_ptr:
            stage_duration = self.memory.read_float(timeline_ptr + 0x10)
    else:
        stage_index = self.memory.read_i32(map_controller_statics + 0x08)
        if stage_index == 1:
            stage_duration = 540.0
        elif stage_index == 2:
            stage_duration = 480.0

    # 3. Format according to active phase
    if stage_timer <= stage_duration:
        remaining = max(0.0, stage_duration - stage_timer)
        minutes = int(remaining) // 60
        seconds = int(remaining) % 60
        return f"{minutes:02d}:{seconds:02d}"
    else:
        overtime = stage_timer - stage_duration
        minutes = int(overtime) // 60
        seconds = int(overtime) % 60
        return f"+{minutes:02d}:{seconds:02d}"
```
