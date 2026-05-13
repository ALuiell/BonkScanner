# BonkHook UI Refresh Reverse Findings

Date: 2026-05-12
Target: Megabonk `GameAssembly.dll`
Goal: safe UI refresh path after programmatic toggle of `CFGameSettings.skip_chest_animation` and `CFGameSettings.auto_select_upgrades`

## Executive summary

Do not call `Settings.RefreshSettings()` directly from `BonkHook`.

The game already has a safer native path for a manual settings change:

1. UI setting widget saves through `CurrentSettings.BetterUpdateCfSettings(...)`
2. `BetterUpdateCfSettings(...)` writes the field by `settingName` into the target `CFSettings`
3. it then tail-jumps into `CurrentSettings.OnSettingUpdated(...)`
4. `OnSettingUpdated(...)` runs per-setting side effects and the normal settings update pipeline
5. UI listeners such as `BetterSetting.OnSettingUpdated(...)` refresh themselves through `BetterSetting.UpdateValue()`

That path is the best candidate for BonkHook.

## Confirmed classes, methods, offsets

### Settings UI

- `Settings_TypeInfo`: `GameAssembly + 0x2F80B58`
- `Settings.Instance`: `Settings_TypeInfo->static_fields + 0x8`
- `Settings.RefreshSettings`: `GameAssembly + 0x374340`
- Signature:
  `void Settings__RefreshSettings(Settings_o* __this, const MethodInfo* method);`

### CurrentSettings

- `CurrentSettings_TypeInfo`: `GameAssembly + 0x2F82E88`
- `CurrentSettings.Instance`: `CurrentSettings_TypeInfo->static_fields + 0x0`
- `CurrentSettings.A_SettingUpdated`: `CurrentSettings_TypeInfo->static_fields + 0x10`
- `CurrentSettings.BetterUpdateCfSettings`: `GameAssembly + 0x366150`
- Signature:
  `void CurrentSettings__BetterUpdateCfSettings(CurrentSettings_o* __this, System_String_o* settingName, Il2CppObject* value, CFSettings_o* cfSettings, const MethodInfo* method);`
- `CurrentSettings.OnSettingUpdated`: `GameAssembly + 0x366490`
- Signature:
  `void CurrentSettings__OnSettingUpdated(CurrentSettings_o* __this, System_String_o* name, Il2CppObject* value, Il2CppObject* oldValue, const MethodInfo* method);`
- `CurrentSettings.UpdateSkipChestAnimation`: `GameAssembly + 0x368BE0`
- Signature:
  `void CurrentSettings__UpdateSkipChestAnimation(CurrentSettings_o* __this, int32_t i, const MethodInfo* method);`

### Save path

- `SaveManager.SaveConfig`: `GameAssembly + 0x524CC0`
- Signature:
  `void SaveManager__SaveConfig(SaveManager_o* __this, const MethodInfo* method);`

### BetterSetting / UI refresh listeners

- `BetterSetting.OnSettingUpdated`: `GameAssembly + 0x364820`
- Signature:
  `void BetterSetting__OnSettingUpdated(BetterSetting_o* __this, System_String_o* settingName, Il2CppObject* oldValue, Il2CppObject* newValue, const MethodInfo* method);`
- `BetterSetting.UpdateValue`: `GameAssembly + 0x364C80`
- Signature:
  `void BetterSetting__UpdateValue(BetterSetting_o* __this, const MethodInfo* method);`

### Useful MethodInfo symbols

- `Method$CurrentSettings.BetterUpdateCfSettings()`: `GameAssembly + 0x2FB38A8`
- `Method$BetterSetting.OnSettingUpdated()`: `GameAssembly + 0x2F81DC8`

## Confirmed data layout

### SaveManager

- `SaveManager.fields.config`: `+0x20`

### ConfigSaveFile

- `ConfigSaveFile.cfGameSettings`: `+0x18`

### CFGameSettings

- `auto_select_upgrades`: `+0x68`
- `skip_chest_animation`: `+0x78`

These match the current stable hook path.

## What `Settings.RefreshSettings()` actually does

Confirmed from live disassembly of `GameAssembly + 0x374340`:

- it is an instance method
- it reads `Settings.fields.settings` from `this + 0x90`
- it checks the list for null
- it iterates the list
- during iteration it calls `GameAssembly + 0x364C80`, which is `BetterSetting.UpdateValue()`

Meaning:

- `RefreshSettings()` is basically a force-refresh over the current list of settings widgets
- it is not the primary “setting changed” path
- it depends on `Settings.settings` being valid and populated

This explains why direct external invocation is risky: if the window is not in the exact state expected by the game, it may walk invalid or partially built UI state.

## What `CurrentSettings.BetterUpdateCfSettings()` actually does

Confirmed from live disassembly of `GameAssembly + 0x366150`:

- it receives:
  - `this = CurrentSettings`
  - `settingName = System_String*`
  - `value = Il2CppObject*`
  - `cfSettings = CFSettings*`
  - `method = MethodInfo*`
- it validates `cfSettings`
- it uses `settingName` plus the target `cfSettings` object to find the field dynamically
- it reads the previous value
- it writes the new value
- it then jumps directly into `CurrentSettings.OnSettingUpdated(...)` at `GameAssembly + 0x366490`

So `BetterUpdateCfSettings()` is not “UI only”. It is the game’s generic native entrypoint for “change setting by name and then run the normal update pipeline”.

## Manual click call chain

High-confidence reconstructed chain:

1. `Settings.CreateGenericSettings(...)`
2. each widget gets initialized through `BetterSetting.SetSetting(...)`
3. widget stores:
   - `saveAction`
   - `_settingName`
   - `cfSettings`
4. manual UI interaction reaches widget-specific change handler
   - examples: `BetterDropdownSetting.ValueChanged(...)`, slider handlers, etc.
5. widget calls `BetterSetting.SaveValue()`
6. `saveAction` target is the normal settings update path
7. for game settings this path is `CurrentSettings.BetterUpdateCfSettings(...)`
8. `BetterUpdateCfSettings(...)` writes the field and tail-jumps to `CurrentSettings.OnSettingUpdated(...)`
9. `OnSettingUpdated(...)` dispatches by setting name/hash
10. UI listeners refresh through `BetterSetting.OnSettingUpdated(...) -> BetterSetting.UpdateValue() -> subclass ShowValue()`

## Skip chest animation: special side effect path

Confirmed:

- `CurrentSettings.UpdateSkipChestAnimation(...)` exists as a dedicated method
- live `OnSettingUpdated(...)` contains a branch whose code matches the logic pattern seen in standalone `UpdateSkipChestAnimation(...)`

Conclusion:

- `skip_chest_animation` has special runtime side effects beyond raw config storage
- when changed through the normal path, those side effects are applied from `OnSettingUpdated(...)`
- bypassing `CurrentSettings` and only writing the field + `SaveConfig()` skips the game’s native update pipeline

Related gameplay symbols tied to chest behavior:

- `ChestOpening.AnimateOpening`: `GameAssembly + 0x55FBE0`
- `ChestOpening.AnimateEffects`: `GameAssembly + 0x560BE0`
- `InteractableChest.OpenChestImplementation`: `GameAssembly + 0x???` exposed in metadata as `Assets.Scripts.Inventory__Items__Pickups.Chests.InteractableChest__OpenChestImplementation`
- `ChestUtility.OpenChestNoAnimation`: metadata-exposed as `Assets.Scripts.Inventory__Items__Pickups.Interactables.ChestUtility__OpenChestNoAnimation`

I did not complete instruction-level xrefs from the field offset itself because `find_call_references` repeatedly destabilized the CE bridge, but the dedicated `CurrentSettings` side-effect method is confirmed.

## Auto select upgrades: current evidence

Confirmed:

- `CFGameSettings.auto_select_upgrades` is at `+0x68`
- gameplay method `UpgradePicker.AutoSelectUpgrade()` exists

Not confirmed:

- a dedicated `CurrentSettings.UpdateAutoSelectUpgrades(...)` method

Current best interpretation:

- `auto_select_upgrades` is handled by the generic settings pipeline for storage + UI refresh
- unlike `skip_chest_animation`, there is no obvious dedicated `CurrentSettings` side-effect method in metadata
- it is likely read by gameplay code when relevant rather than requiring an immediate native side-effect callback

## Safe recommendation for BonkHook.cs

Preferred path:

1. stay on main thread
2. resolve `CurrentSettings.Instance`
3. resolve `SaveManager.config.cfGameSettings`
4. box the new integer value as an `Il2CppObject*`
5. create an IL2CPP string for:
   - `"skip_chest_animation"`
   - `"auto_select_upgrades"`
6. call `CurrentSettings.BetterUpdateCfSettings(currentSettings, settingName, boxedValue, cfGameSettings, methodInfo)`
7. do not separately call `Settings.RefreshSettings()`

Why this is preferred:

- it uses the same path as manual UI changes
- it should update underlying data
- it should trigger the native settings update pipeline
- it should naturally refresh open UI through the existing `A_SettingUpdated` subscriber path
- for `skip_chest_animation` it should also preserve native side effects

## Recommended fallback path

If `CurrentSettings.Instance` is null:

1. fallback to current stable raw write
2. call `SaveManager.SaveConfig(saveManager, ...)`
3. do not attempt `Settings.RefreshSettings()`
4. optionally log that UI refresh was skipped because `CurrentSettings` was unavailable

## Guard checks to add

- ensure the hook runs on the game main thread
- ensure `saveManager != null`
- ensure `config != null`
- ensure `cfGameSettings != null`
- ensure `CurrentSettings.Instance != null` before using the preferred path
- ensure boxed value allocation succeeded
- ensure IL2CPP string creation succeeded
- prefer a real `MethodInfo*` for `CurrentSettings.BetterUpdateCfSettings`
- avoid any direct `Settings.RefreshSettings()` call unless you intentionally build a separate guarded experiment

If you ever experiment with direct `RefreshSettings()` again, add all of these guards first:

- `Settings.Instance != null`
- `Settings.Instance->fields.settings != null`
- settings list count > 0
- the settings window is actually active/open
- call only after the native setting update path completed

Even with those guards, direct `RefreshSettings()` is still lower-confidence than `BetterUpdateCfSettings(...)`.

## Why the previous `RefreshSettings()` experiment likely crashed

Confirmed:

- the method address and instance/static interpretation were correct
- `Settings.Instance` at `static_fields + 0x8` was correct
- the signature is `void(Settings_o*, MethodInfo*)`

So the failure was probably not caused by using the wrong target method.

Most likely causes:

- calling a force-refresh path that expects a fully valid `Settings.settings` widget list
- calling it while the menu object graph was not in the exact expected state
- calling it from a state where one or more widgets were stale/destroyed/not yet rebuilt

## Final implementation guidance

Recommended implementation change:

- replace raw field write as the primary path with `CurrentSettings.BetterUpdateCfSettings(...)`
- keep the raw write + `SaveConfig()` path only as fallback
- remove the direct `Settings.RefreshSettings()` call entirely

Expected effect:

- open settings UI should refresh through the game’s own event/subscriber system
- closed settings UI should remain safe because no direct widget walk is forced
- `skip_chest_animation` should preserve runtime side effects

## Confidence notes

Confirmed by dump metadata and live CE disassembly:

- method addresses and signatures listed above
- `Settings.RefreshSettings()` walks `Settings.settings` and calls `BetterSetting.UpdateValue()`
- `BetterUpdateCfSettings()` writes through the generic path and tail-jumps to `CurrentSettings.OnSettingUpdated()`
- `skip_chest_animation` has dedicated native side-effect logic under `CurrentSettings`

High-confidence inference:

- manual UI click uses `BetterSetting.SaveValue()` into `CurrentSettings.BetterUpdateCfSettings(...)`
- UI visual refresh after a native setting change should happen through the normal `A_SettingUpdated` subscriber path, not through explicit `Settings.RefreshSettings()` from the hook

Known limitation:

- `find_call_references` repeatedly broke the CE bridge session, so I did not finish a complete instruction-level caller graph for every case branch inside `OnSettingUpdated(...)`
