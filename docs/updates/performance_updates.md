# Performance Updates

Last reviewed: 2026-08-30

This file tracks current performance work. Completed items are retained here
only when they explain which former recommendations no longer belong in the
backlog.

Status legend:

- `[Implemented]` present in the current repository and covered by tests
- `[Partial]` meaningful work is complete, but follow-up remains
- `[Open]` not implemented
- `[External / Unverified]` refers to code that is not present in this repository

## Implemented

### Memory-read cost and refresh gating

Status: `[Implemented]`

- `ProcessMemory` caches module base addresses per process handle and clears the
  cache when the handle changes or closes.
- Passive-item dictionary walks have hard count/stack limits and a cached
  validated layout.
- A refresh tick resolves `owner_stats` once and shares named reads through
  `RefreshTickContext`.
- Full player snapshots are demand-gated by visible/active consumers, and
  opening Live Stats requests an immediate refresh.
- Fast combat/powerup/Expected-chest tasks, the 1-second passive lane, and the
  10-second full snapshot are independently scheduled instead of multiplying
  the full read for every consumer.

### Disk writes and recording-library work

Status: `[Implemented]`

- VOD snapshots flush in batches (`SNAPSHOT_FLUSH_EVERY = 3`) with final
  flush/close behavior on stop.
- `TOTAL_REROLLS` uses a dirty flag, a 15-second periodic flush, and forced
  flushes during scanner/application shutdown instead of writing every reroll.
- Recording metadata is cached; changed files are refreshed in the background,
  and full payloads load asynchronously only after selection.
- Stale asynchronous recording results are rejected after a newer selection.

These items replace the old backlog entries for module-base caching, per-reroll
config writes, per-snapshot VOD flushing, and synchronous recording-list scans.

## Remaining Work

### 1. Native-hook hotkey settings persistence

Status: `[External / Unverified]`

The earlier proposal referenced native symbols such as
`CurrentSettings.BetterUpdateCfSettings`, `SaveConfig`, and an injected
`AlwaysManager.Update` path. That native-hook source is not stored in this
repository, so this tree cannot prove whether immediate game-side settings
saves, idle atomic writes, or request coalescing still need work.

If the native project is audited separately, keep these goals:

- apply a hotkey change immediately in memory;
- defer persistence with a debounce or clean uninitialization flush;
- avoid file I/O, sleeps, blocking waits, logging, and heap-heavy work inside a
  game-frame hook;
- measure before changing atomic/request behavior.

Do not treat this section as evidence that the current native build still has
the old behavior.

### 2. Batch the full player-stat block

Status: `[Open]`

The current reader shares roots and caches stable dictionary layouts, but most
individual stat values are still decoded through separate external reads.
Consider a validated block read only if profiling shows the 10-second full lane
causes meaningful frametime or UI stalls. Preserve per-field validation and
fail-closed behavior; a faster partial/garbage snapshot is not an improvement.

### 3. Repeat performance measurements on release builds

Status: `[Open]`

Measure, rather than infer:

- idle CPU with the game focused and backgrounded;
- refresh duration and read census for 500 ms, 1 s, and 10 s tasks;
- GUI stalls while loading a large cold and warm recording library;
- VOD validity after manual stop, application close, and auto-stop;
- map-marker worker latency with automatic discovery off and on;
- gameplay frametime while changing any setting that reaches the native hook.

The active scanner/map-ready polling path is intentional workload. Performance
work should target avoidable duplicate reads, blocking UI/disk work, and
measured spikes without weakening lifecycle or memory-safety checks.
