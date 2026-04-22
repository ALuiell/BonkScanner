## LLM Reverse Entry Points

Use these files as the source of truth:

- `game_data.py` - current memory read chain, offsets, stat labels, and readiness logic.
- `memory.py` - process/module access and primitive memory reads.
- `native/BonkHook/HookExports.cs` - native hook targets, expected bytes, and exported hook calls.
- `hook_loader.py` - hook DLL path resolution, injection, and remote export invocation.

Important: only offsets applied as `GameAssembly.dll + offset` are module-relative.
Dictionary, entry, container, and Mono string offsets are relative to the pointer
read at the previous step.

Start from `GameDataClient.get_map_stats()` before changing interactables memory
logic. Start from `GameDataClient.get_map_generation_state()` before changing
map readiness logic. Start from `HookExports.cs` before changing restart or hook
logic.

Current native hook entry points:

- `AlwaysManager.Update` at `GameAssembly.dll + 0x4F7520` is the main-thread
  dispatcher for queued `MapController.RestartRun` calls.
- `MapGenerationController.<GenerateMap>d__39.MoveNext` at
  `GameAssembly.dll + 0x4A26F0` is the map-generation completion signal. The
  detour calls the original coroutine first, then publishes snapshot readiness
  only when the coroutine returned false, `MapGenerationController.isGenerating`
  is false, and `MapController.currentMap/currentStage` are both non-null.

External native exports:

- `RequestRestartRun` clears the snapshot-ready flag and queues a restart for
  the next `AlwaysManager.Update` tick.
- `WaitForSnapshotReady` waits for the completion hook to publish readiness and
  returns `1` for ready or `0` for timeout.
