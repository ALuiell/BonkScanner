# BonkHook

Minimal NativeAOT smoke-test hook for Megabonk IL2CPP.

The hook detours `AlwaysManager.Update` and uses it as a main-thread dispatcher.
External callers can run `RequestRestartRun` from any thread/process; the export
only sets an atomic flag, and the actual `MapController.RestartRun` call is
drained inside the hooked Unity update.

The hook also detours `MapGenerationController.<GenerateMap>d__39.MoveNext` and
publishes a snapshot-ready signal when the map-generation coroutine completes
with `isGenerating == false` and loaded `currentMap/currentStage` pointers.
External callers poll and consume that signal with `WaitForSnapshotReady`; the
export returns immediately, and timeout/retry logic belongs to the caller.

Build with the project-local portable toolchain:

```bat
tools\bootstrap_tools.bat
tools\build_native_hook.bat
```

The publish output must contain:

- `BonkHook.dll`

The build script bootstraps a local .NET SDK into `.tools\dotnet` and a
portable MSVC/Windows SDK toolchain into `.tools\msvc` when they are missing.
Those downloaded toolchain folders are local developer artifacts and are not
committed. The bootstrap uses Windows PowerShell and requires internet access
the first time it runs.

MinHook is statically linked from `native/BonkHook/libs/libMinHook.x64.lib`;
no separate `MinHook.x64.dll` is required at runtime.

Fallback: if portable MSVC bootstrap fails, install Visual Studio Build Tools
with the Desktop development with C++ workload. NativeAOT on Windows still needs
an MSVC-compatible linker and Windows SDK for the publish step.
