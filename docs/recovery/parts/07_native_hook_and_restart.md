# Part 7: Native Hook and Restart Recovery Guide

## Overview
This component controls the injection of the native helper DLL (`BonkHook.dll`) into the game process, validates that the game runtime is in a safe state for injection, and invokes exported hook functions to handle run restarting, animation skipping, auto-leveling, and opacity toggles.

- **Target Files**:
  - Python Loader: [hook_loader.py](file:///f:/Python/MegabonkReroll/hook_loader.py)
  - Python Control: [run_control.py](file:///f:/Python/MegabonkReroll/run_control.py)
  - C# Native Code: [native/BonkHook/HookExports.cs](file:///f:/Python/MegabonkReroll/native/BonkHook/HookExports.cs)
  - Unit Tests: [tests/test_hook_loader.py](file:///f:/Python/MegabonkReroll/tests/test_hook_loader.py), [tests/test_run_control.py](file:///f:/Python/MegabonkReroll/tests/test_run_control.py)

---

## Memory Validation & Injection Safety Check
Before injecting the DLL, the loader performs strict safety checks to ensure the game has fully initialized its IL2CPP runtime. It reads memory locations in `GameAssembly.dll` and verifies the byte signature at the target function entry point.

```
GameAssembly.dll + ALWAYS_MANAGER_UPDATE_OFFSET (0x4F7520)
  -> Verify memory is committed and executable (VirtualQueryEx check)
  -> Read first 16 bytes and verify they match EXPECTED_ALWAYS_MANAGER_UPDATE_BYTES
     [ 0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83, 0xEC, 0x20, 0x80, 0x3D, 0x64, 0xB8, 0xC7, 0x02 ]

GameAssembly.dll + GENERATE_MAP_MOVE_NEXT_OFFSET (0x4A26F0)
  -> Verify memory is committed and executable

GameAssembly.dll + ALWAYS_MANAGER_TYPE_INFO_OFFSET (0x2F6BAA8)
  -> Read static class pointer
    -> Read static fields pointer (+0xB8)
      -> Read AlwaysManager.Instance pointer (+0x0)
        -> Verify Instance pointer is non-zero
```

If any of these checks fail, injection is aborted with a `HookProcessNotReadyError`, preventing game crashes.

---

## Native Hooks (C# Exports)
Once `BonkHook.dll` is injected into the remote process, the loader finds export function addresses by loading the local DLL, resolving the function offset, and applying it to the remote base module address. It then runs them via `CreateRemoteThread`.

### Key Export Signatures
- **`Initialize`**: Hooks targeted functions in the game assemblies using the MinHook engine.
- **`RequestRestartRun`**: Resets the current active run layout.
- **`WaitForSnapshotReady`**: Pauses and checks if the game data snapshot has been fully written and stabilized.
- **`ToggleSkipChestAnimation`**: Skips the chest opening sequences.
- **`ToggleAutoSelectUpgrades`**: Enables automatic selection of item upgrades during leveling.
- **`ToggleParticlesOpacity`**: Reduces particle opacity to improve rendering performance.
- **`Uninitialize`**: Cleans up and uninstalls hooks before unloading the DLL.

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for target class methods in `dump.cs` or using IDA Pro / Ghidra:
- **`AlwaysManager.Update`**:
  - Search for `AlwaysManager$$Update` or check the class method list.
  - Note the relative virtual address (RVA) offset (e.g., `0x4F7520`).
- **`MapGenerationController.GenerateMap.MoveNext`**:
  - Search for the nested class and method `MapGenerationController.<GenerateMap>d__24.MoveNext` (name might slightly differ depending on compiler version).
  - Note the RVA offset (e.g., `0x4A26F0`).
- **`AlwaysManager` TypeInfo**:
  - Search for `AlwaysManager_TypeInfo` or look at metadata structures.
  - Note the address (e.g., `0x2F6BAA8`).

### 2. Updating Byte Signatures
If `AlwaysManager.Update` offset has moved, the entry bytes at that offset might also change:
- Open `GameAssembly.dll` in a disassembler or Cheat Engine.
- Navigate to the address of `AlwaysManager.Update`.
- Copy the first 16 bytes.
- Update `EXPECTED_ALWAYS_MANAGER_UPDATE_BYTES` in `hook_loader.py` with these new bytes.

---

## Code Reference
Offsets and signatures are defined in `NativeHookLoader` in `hook_loader.py`:
```python
class NativeHookLoader:
    ALWAYS_MANAGER_UPDATE_OFFSET = 0x4F7520
    GENERATE_MAP_MOVE_NEXT_OFFSET = 0x4A26F0
    ALWAYS_MANAGER_TYPE_INFO_OFFSET = 0x2F6BAA8
    
    EXPECTED_ALWAYS_MANAGER_UPDATE_BYTES = bytes(
        [
            0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83, 0xEC, 0x20, 
            0x80, 0x3D, 0x64, 0xB8, 0xC7, 0x02,
        ]
    )
```

Target functions hook implementation (like restart mechanisms) are defined in C# in:
- `native/BonkHook/HookExports.cs`
- Check target methods in `HookExports.cs` if game engine hooks fail to initialize.

---

## Verification Steps
1. Run pytest:
   ```powershell
   pytest tests/test_hook_loader.py
   pytest tests/test_run_control.py
   ```
2. Verify in application logs that hook injection completes and reports "Ready".
3. Verify that pressing "Restart" button correctly restarts the run without freezing or crashing the game.
