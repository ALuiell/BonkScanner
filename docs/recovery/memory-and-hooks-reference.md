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
