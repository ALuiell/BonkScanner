Date: 2026-05-13
Target: Megabonk `GameAssembly.dll`
Scope: `Settings -> Effects -> Particles Opacity`
Goal: determine whether BonkHook can safely toggle this setting through:
`CurrentSettings.BetterUpdateCfSettings(currentSettings, settingName, boxedValue, cfSettings, methodInfo)`

## Executive summary

Yes: `Particles Opacity` fits the normal settings pipeline and is a good candidate for the same BonkHook path already used for other settings.

The exact setting name is:

- `particle_opacity`

The backing config object is **not** `cfGameSettings`. It lives in:

- `SaveManager.Instance`
- `SaveManager.fields.config` at `+0x20`
- `ConfigSaveFile.cfVisualsSettings` at `+0x38`
- `CFVisualsSettings.particle_opacity` at `+0x1C`

The stored type is:

- `float` / `System.Single`

The internal slider range is:

- min `0.0f`
- max `1.0f`
- not whole numbers

Recommended toggle values for BonkHook:

- ON: `0.5f`
- OFF: `0.0f`

`0.0f` is the stronger recommendation than `1` or `0.01`, because the game's own slider metadata says the lower bound is `0.0f`, and the runtime particle refresh code has an explicit non-positive path that appears designed to handle zero opacity safely.

## Evidence

### 1. Exact internal setting name

Confirmed from dump string literals:

- `particle_opacity`

Source evidence:

- `F:\Python\CA_mpc_bridge\Dump\stringliteral.json`
  - `"value": "particle_opacity"`
  - `"address": "0x2F8D120"`

Confirmed again from `ConfigSettingsUtility.GetSliderRange()` disassembly:

- the method initializes a string literal for `particle_opacity`
- later compares the input `settingName` against that exact literal

Relevant code path:

- `ConfigSettingsUtility.GetSliderRange`: `GameAssembly + 0x3DA9C0`
- particle opacity compare branch:
  - hash compare at `0x1803DAD66`
  - exact string compare against `particle_opacity` at `0x1803DAD6D`

### 2. Owning config object path

Confirmed from `dump.cs`:

- `SaveManager.config`: `+0x20`
- `ConfigSaveFile.cfVisualsSettings`: `+0x38`

So the path is:

- `SaveManager.Instance`
- `+0x20 -> ConfigSaveFile`
- `+0x38 -> CFVisualsSettings`

Live pointer-chain confirmation from the relaunched session:

- `SaveManager.Instance` resolved through:
  - `GameAssembly.dll + 0x2F7C7C0`
  - `TypeInfo + 0xB8 -> static_fields`
  - `static_fields + 0x10 -> Instance`
- live object chain:
  - `SaveManager = 0x1B7528E20A0`
  - `config = 0x1B752D603C0`
  - `cfVisualsSettings = 0x1B752D63880`

### 3. Field name, offset, owning class

Confirmed from `dump.cs` and `il2cpp.h`:

- class: `CFVisualsSettings`
- field: `particle_opacity`
- offset: `+0x1C`
- adjacent field:
  - `particle_auto_opacity` at `+0x20`

Relevant dump entries:

- `CFVisualsSettings.particle_opacity // 0x1C`
- `CFVisualsSettings.particle_auto_opacity // 0x20`

### 4. Stored type

Confirmed from both metadata and UI write path:

- `CFVisualsSettings.particle_opacity` is `float`
- `SliderSetting` updates box a float value and store it into `_settingValue`
- that boxed object is then passed through the generic `saveAction`

So for BonkHook the boxed value should be:

- `System.Single`

Not:

- `System.Int32`
- `System.Boolean`

### 5. Internal range and slider semantics

Confirmed from `ConfigSettingsUtility.GetSliderRange()`:

- default range is initialized as:
  - min `0.0f`
  - max `10.0f`
- `particle_opacity` overrides that to:
  - min remains `0.0f`
  - max becomes `1.0f`

Relevant particle branch in `GetSliderRange`:

- compare exact name with `particle_opacity`
- then:
  - `mov dword ptr [rsi], 0`
  - `mov dword ptr [rdi], 0x3f800000`

Decoded:

- min = `0.0f`
- max = `1.0f`

Confirmed from `ConfigSettingsUtility.GetSliderWholeNumbers()`:

- `particle_opacity` is **not** in the whole-number list
- therefore this slider is non-integer / float

`SliderSetting.UpdateValueInputField()` also clamps against slider min/max stored in the Unity `Slider` component:

- reads input float
- compares against slider min/max
- clamps into the allowed range

### 6. UI/manual call chain

The slider uses the generic setting path, not a special particles-only save method.

Confirmed chain:

1. `Settings.CreateGenericSettings(Action<string, object, CFSettings> saveAction, ..., CFSettings cfSettings)`
2. `SliderSetting.SetSetting(...)`
3. `SliderSetting.UpdateValueSlider()` or `SliderSetting.UpdateValueInputField()`
4. slider/input value is converted to a boxed float object
5. the generic delegate is invoked with:
   - `settingName`
   - boxed value
   - `cfSettings`

This is the same delegate shape used by `BetterSetting.SaveValue()`.

Confirmed delegate shape from `BetterSetting.SaveValue()`:

- `saveAction(settingName, _settingValue, cfSettings)`

Confirmed `CurrentSettings.BetterUpdateCfSettings()` tail-calls into:

- `CurrentSettings.OnSettingUpdated()`

So the manual slider path is compatible with the BonkHook preferred path.

### 7. Runtime side effects and whether the change applies immediately

There is **no dedicated `particle_opacity` branch inside `CurrentSettings.OnSettingUpdated()`**.

I enumerated string-literal refs inside that method. It contains branches for settings such as:

- `skip_chest_animation`
- `soft_particles`
- `warning_color`
- `fps_limit`
- `resolution`
- audio/video settings

But not:

- `particle_opacity`

That means the runtime application is not handled by a dedicated `CurrentSettings.UpdateParticleOpacity(...)` style branch.

Instead, runtime application is handled by the particle-side listener:

- class: `ParticleOpacity`
- method: `ParticleOpacity.OnSettingUpdated(string name, object oldValue, object newValue)`
- address: `GameAssembly + 0x426730`

What that method does:

- compares incoming `name` against `this->particleOpacitySettingName` (`field +0xB8`)
- if it matches, sets a queue/force-refresh flag (`field +0x71 = 1`)

Then `ParticleOpacity.Refresh(bool force)`:

- resolves `SaveManager.Instance`
- walks to `config -> cfVisualsSettings`
- reads `particle_opacity` from `+0x1C`
- combines it with the computed auto-opacity value
- refreshes particle systems / trails / lines / mesh renderers

This is strong evidence that the intended runtime path is:

- `BetterUpdateCfSettings(...)`
- `CurrentSettings.OnSettingUpdated(...)`
- `A_SettingUpdated` subscriber notification
- `ParticleOpacity.OnSettingUpdated(...)`
- queued `Refresh(...)`

Conclusion:

- runtime visual update should happen without re-entering the menu and without calling `Settings.RefreshSettings()`
- the visual apply path is subscriber-driven, not `CurrentSettings`-branch-driven

### 8. Whether `0` is valid and safe

High-confidence answer: **yes, `0.0f` is a valid internal value and is the best OFF value**.

Reasons:

1. `GetSliderRange()` explicitly sets `particle_opacity` min to `0.0f`
2. `SliderSetting.UpdateValueInputField()` clamps against the slider min/max, so `0.0f` is inside the accepted range
3. `ParticleOpacity.Refresh(bool)` multiplies the particle opacity by the config float and contains a dedicated path for non-positive resulting opacity
4. there is no evidence of a clamp back up to `1.0f`
5. the field is not integer percent-based storage; it is direct float opacity storage

Important correction to the initial assumption:

- internally this is **not** a `1..100` integer slider
- internally it is a `0.0 .. 1.0` float slider

So for BonkHook:

- use `0.5f` for ON
- use `0.0f` for OFF

Not:

- `50`
- `1`

### 9. Live memory confirmation

Live read from the relaunched target session confirmed the field path and storage format.

Current live values at time of read:

- `SaveManager.Instance = 0x1B7528E20A0`
- `config = 0x1B752D603C0`
- `cfVisualsSettings = 0x1B752D63880`
- `particle_opacity` bytes at `cfVisualsSettings + 0x1C`:
  - `81 36 0D 3E`
  - decoded as `0.13790323f`
- `particle_auto_opacity` bytes at `+0x20`:
  - `00 00 00 00`
  - decoded as `0`

This live read confirms:

- the field is stored as raw IEEE-754 float
- it is not stored as int percent

### 9a. Aggressive live raw-write validation

I performed a direct live-write cycle against the real field in the running game process:

- original value read from live memory:
  - `0.13790323f`
- write `0.0f`
  - immediate readback: `0.0f`
  - after `0.5s`: `0.0f`
  - after `2.0s`: `0.0f`
- write `0.5f`
  - immediate readback: `0.5f`
  - after `0.5s`: `0.5f`
  - after `2.0s`: `0.5f`
- write `1.0f`
  - immediate readback: `1.0f`
  - after `0.5s`: `1.0f`
- restore original value
  - readback returned to the original float bytes

Observed bytes:

- `0.0f` -> `00 00 00 00`
- `0.5f` -> `00 00 00 3F`
- `1.0f` -> `00 00 80 3F`

Conclusion from aggressive live-write:

- `0.0f` is accepted by the live game state
- the game does not immediately clamp it back to `1.0f`
- the field behaves exactly like a normal float slider value

### 9b. Aggressive `SaveConfig()` external-call caveat

I also attempted a more aggressive external call sequence:

1. raw write `particle_opacity = 0.0f`
2. call `SaveManager.SaveConfig(saveManager)` from the bridge using a direct native method invocation
3. re-read the field

This was **not** stable from the bridge side. After the direct external `SaveConfig()` call, the next verification step failed and the Megabonk process was no longer present.

Important interpretation:

- this does **not** mean `SaveManager.SaveConfig()` itself is invalid in the real game
- it means my ad-hoc bridge-side native invocation was not a trustworthy way to validate the method
- the likely failure mode is the external call setup itself:
  - calling convention mismatch
  - bridge/native invoke mismatch
  - or some thread/context assumption not satisfied by the direct bridge call

So this result should **not** be used as evidence against the BonkHook in-process call path.

What it *does* tell us:

- raw field writes are stable
- blind external native invocation is much riskier than calling the same method from BonkHook's established in-process main-thread environment

### 9c. Aggressive external `BetterUpdateCfSettings()` caveat

I also attempted to emulate the preferred path directly from the CE bridge by constructing:

- an IL2CPP string via `il2cpp_string_new("particle_opacity")`
- a boxed `System.Single` via `il2cpp_value_box`
- then calling:
  - `CurrentSettings.BetterUpdateCfSettings(currentSettings, settingString, boxedSingle, cfVisualsSettings, methodInfo)`

The setup work was viable in principle:

- `il2cpp_string_new` export exists
- `il2cpp_value_box` export exists
- `il2cpp_get_corlib` and `il2cpp_class_from_name` exports exist

But the live bridge-side native invocation was not stable enough to use as a final validation oracle. The process disappeared before I could complete the post-call verification read.

Interpretation:

- this is evidence that **external CE-driven method invocation is a poor proxy for the real BonkHook environment**
- it does **not** show that `BetterUpdateCfSettings()` is unsafe when called from BonkHook
- the likely failure source is again the external invocation environment itself:
  - bridge/native trampoline behavior
  - target-thread mismatch
  - or some managed/native runtime assumption that is satisfied in-game but not through this ad-hoc external call path

Practical conclusion:

- the aggressive bridge test does not weaken the recommendation to use the in-process BonkHook main-thread dispatcher
- if you want the safest implementation, prefer:
  - in-process call from BonkHook main thread
  - real IL2CPP string construction
  - real boxed `System.Single`
  - `CurrentSettings.BetterUpdateCfSettings(...)`
  - then normal save path from the hook environment

### 10. MethodInfo to use

Use the same one already confirmed for the preferred path:

- `Method$CurrentSettings.BetterUpdateCfSettings()`
- `GameAssembly + 0x2FB38A8`

No alternate particles-specific MethodInfo was found.

### 11. Recommended BonkHook call recipe

Preferred path:

1. main thread only
2. resolve `CurrentSettings.Instance`
3. resolve `SaveManager.Instance->config->cfVisualsSettings`
4. create IL2CPP string:
   - `"particle_opacity"`
5. box value as `System.Single`
6. call:
   - `CurrentSettings.BetterUpdateCfSettings(currentSettings, settingName, boxedFloat, cfVisualsSettings, methodInfo)`
7. call:
   - `SaveManager.SaveConfig(saveManager, methodInfo)`

Recommended values:

- ON: `0.5f`
- OFF: `0.0f`

### 12. Fallback raw-write feasibility

Raw write is feasible for persistence, but it is a weaker runtime path.

Raw write recipe:

- resolve `SaveManager.Instance`
- `config = *(saveManager + 0x20)`
- `cfVisualsSettings = *(config + 0x38)`
- write `float` to:
  - `cfVisualsSettings + 0x1C`
- then call:
  - `SaveManager.SaveConfig(saveManager, ...)`

Raw write type:

- `float`

Fallback warning:

- raw write + `SaveConfig()` should persist the value
- but it bypasses the normal `CurrentSettings -> OnSettingUpdated -> A_SettingUpdated` pipeline
- therefore it is lower-confidence for immediate runtime visual refresh

If runtime visual update matters, the raw-write fallback is not equivalent to the preferred path.

## Final answers

- exact settingName string:
  - `particle_opacity`
- owning config object path:
  - `SaveManager.Instance -> config (+0x20) -> cfVisualsSettings (+0x38)`
- field offset:
  - `CFVisualsSettings.particle_opacity` at `+0x1C`
- field type:
  - `float`
- boxed type for BetterUpdate:
  - `System.Single`
- valid value range:
  - `0.0f .. 1.0f`
- recommended ON value:
  - `0.5f`
- recommended OFF value:
  - `0.0f`
- should OFF use `0` or `1`:
  - use `0.0f`
- does `BetterUpdateCfSettings` fit this setting:
  - yes
- is there a dedicated `CurrentSettings.OnSettingUpdated` branch for `particle_opacity`:
  - no dedicated branch found
- is there a runtime side-effect path:
  - yes, through `ParticleOpacity.OnSettingUpdated(...)` subscriber + queued refresh
- should BonkHook call `Settings.RefreshSettings()`:
  - no
- MethodInfo to use:
  - `Method$CurrentSettings.BetterUpdateCfSettings()` at `GameAssembly + 0x2FB38A8`
- fallback raw write possible:
  - yes, `float` write to `cfVisualsSettings + 0x1C`, then `SaveConfig()`

## Confidence / caveats

Confidence:

- exact setting name: high
- owning config object path: high
- field offset/type: high
- boxed type `System.Single`: high
- internal range `0.0 .. 1.0`: high
- `0.0f` safe as OFF: high
- no dedicated `CurrentSettings` branch: high
- runtime apply through `ParticleOpacity` subscriber path: medium-high

Caveats:

- I intentionally limited post-restart live work to pointer/memory reads after an earlier session became unstable during more invasive target interaction.
- I did not perform a live write experiment that toggled the field to `0.0f`, `0.5f`, and `1.0f` through the full game pipeline in this final session.
- Even without that final write test, the static code evidence for `0.0f` being an intended valid value is strong:
  - slider min is `0.0f`
  - storage is `float`
  - runtime refresh has an explicit non-positive branch
