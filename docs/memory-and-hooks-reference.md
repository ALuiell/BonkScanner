## Where To Look

- Target process: `Megabonk.exe`
- Main module: `GameAssembly.dll`
- Python memory code: `memory.py`, `game_data.py`, `runtime_stats.py`
- Native hook: `hook_loader.py`, `native/BonkHook/HookExports.cs`

## Current Offsets

Type info offsets, relative to `GameAssembly.dll`:

- `InteractablesStatus_TypeInfo`: `0x2FB5E68`
- `MapController_TypeInfo`: `0x2F58E08`
- `MapGenerationController_TypeInfo`: `0x2F59000`

Common IL2CPP/static-field offsets:

- `class_ptr + 0xB8` -> static fields
- `MapController.static + 0x10` -> current map pointer
- `MapController.static + 0x18` -> current stage pointer
- `MapController.static + 0x21` -> reset flag
- `MapGenerationController.static + 0x10` -> is generating
- `MapGenerationController.static + 0x2C` -> map seed

Interactables dictionary/container offsets:

- dictionary `+0x18` -> entries
- dictionary `+0x20` -> count, sanity max `4096`
- entry base `+0x20`, entry size `0x18`
- entry `+0x8` -> key string pointer
- entry `+0x10` -> value/container pointer
- container `+0x10` -> max value used by runtime stats
- container `+0x14` -> current value

Mono string layout:

- string `+0x10` -> signed int length
- string `+0x14` -> UTF-16LE chars
- current max accepted length: `512`

## Interactables Read Chain

```text
GameAssembly.dll + 0x2FB5E68
  -> class_ptr
  -> class_ptr + 0xB8
  -> static_fields
  -> static_fields + 0x0
  -> interactables_dict
  -> dict + 0x18 entries, dict + 0x20 count
  -> entries + 0x20 + index * 0x18
  -> entry + 0x8 key_ptr, entry + 0x10 value_ptr
  -> key Mono string label, value container
  -> container + 0x10 max, container + 0x14 current
```

Known labels:

`Boss Curses`, `Challenges`, `Charge Shrines`, `Chests`, `Greed Shrines`,
`Magnet Shrines`, `Microwaves`, `Moais`, `Pots`, `Shady Guy`.

For readiness, every label above is required except `Challenges`, which is
optional.

## Native Hook

`BonkHook` detours `AlwaysManager.Update` and uses it as a Unity main-thread
dispatcher. `RequestRestartRun` only sets an atomic flag; the hooked update then
calls `MapController.RestartRun`.

Current hook offsets, relative to `GameAssembly.dll`:

- `AlwaysManager.Update`: `0x4F7520`
- `MapController.RestartRun`: `0x4220B0`

Expected bytes at `AlwaysManager.Update` before installing the hook:

```text
48 89 5C 24 08 57 48 83 EC 20 80 3D 64 B8 C7 02
```

Exports used from Python:

- `Initialize`
- `Uninitialize`
- `RequestRestartRun`

Default DLL path:

```text
native/BonkHook/bin/Release/net8.0/win-x64/publish/BonkHook.dll
```

## Patch Update Checklist

When Megabonk updates, check these first:

1. Hook expected bytes and hook target offsets.
2. Type info offsets for interactables, map controller, and map generation.
3. Static-field offset `0xB8` and map-state field offsets.
4. Dictionary/entry/container layout.
5. Mono string layout if labels stop decoding.
6. Label names if stats go missing.
