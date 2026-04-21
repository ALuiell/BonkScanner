# BonkHook

Minimal NativeAOT smoke-test hook for Megabonk IL2CPP.

The hook detours `AlwaysManager.Update` and uses it as a main-thread dispatcher.
External callers can run `RequestRestartRun` from any thread/process; the export
only sets an atomic flag, and the actual `MapController.RestartRun` call is
drained inside the hooked Unity update.

Build:

```powershell
dotnet publish native\BonkHook -c Release -r win-x64
```

The publish output must contain:

- `BonkHook.dll`

MinHook is statically linked from `native/BonkHook/libs/libMinHook.x64.lib`;
no separate `MinHook.x64.dll` is required at runtime.

NativeAOT on Windows requires the Visual Studio Desktop Development for C++
workload because the publish step needs the platform linker.
