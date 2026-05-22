# Performance Benchmark Plan

Date: 2026-05-22

This file is a manual benchmark template for checking how BonkScanner affects
game performance without changing application code.

## Goal

Measure whether these BonkScanner modes materially affect the game's frame
time, FPS stability, CPU usage, RAM usage, and disk activity.

## Important observation from current code

- `Live Stats` does not refresh every frame. It refreshes on a `10,000 ms`
  timer in `gui.py`.
- Recording does not continuously stream to disk. It captures on the configured
  snapshot interval and flushes every few snapshots.
- Scanner load is the most likely continuous CPU contributor because its map
  readiness polling uses a `0.05 s` interval in `game_data.py`.
- Recording with the `Live Stats` tab closed still performs live memory reads,
  because recording itself requires fresh snapshot data.

## Recommended metrics

Primary game metrics:

- Average FPS
- 1% low FPS
- Average frame time (ms)
- P95 frame time (ms)
- P99 frame time (ms)
- Frame time stutter count above 16.7 ms / 33.3 ms

Process metrics:

- `Megabonk.exe` CPU %
- `BonkScanner.exe` or Python process CPU %
- `Megabonk.exe` RAM
- `BonkScanner.exe` or Python process RAM
- BonkScanner disk write rate during recording

## Test rules

- Use the same map/scene if possible.
- Use the same game graphics settings.
- Measure each scenario for at least `3-5` minutes.
- Repeat each scenario `3` times.
- Rebooting is not required, but close unrelated heavy apps.
- If possible, keep character movement/scene complexity roughly similar.

## Scenarios

1. Game only. `Live Stats` tab closed. Scanner not running.
2. `Live Stats` tab open.
3. `Live Stats` tab open + scanner running.
4. `Live Stats` tab open + scanner running + recording active.
5. Recording active only.

## Result table

| Scenario | Duration | Avg FPS | 1% Low FPS | Avg FT ms | P95 FT ms | P99 FT ms | Stutters >16.7ms | Stutters >33.3ms | Game CPU % | Scanner CPU % | Game RAM MB | Scanner RAM MB | Scanner Disk KB/s | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1. Closed Live Stats, no scanner |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 2. Open Live Stats |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 3. Open Live Stats + scanner |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 4. Open Live Stats + scanner + recording |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| 5. Recording only |  |  |  |  |  |  |  |  |  |  |  |  |  |  |

## What to expect before measuring

- Scenario `1` should be the baseline.
- Scenario `2` should usually be close to baseline, because `Live Stats`
  refreshes periodically, not constantly.
- Scenario `3` is the most likely to show a measurable CPU increase because the
  scanner loop polls game state repeatedly.
- Scenario `4` may be only slightly worse than scenario `3` unless storage is
  slow, because recording writes are interval-based rather than continuous.
- Scenario `5` is important because it isolates recording overhead from scanner
  overhead. It may still be heavier than expected because recording triggers
  live stat reads even with the tab closed.

## Suggested interpretation

- If FPS average barely changes but P95/P99 frame time gets worse, BonkScanner
  is causing spikes rather than constant load.
- If scenario `2` is almost identical to scenario `1`, the `Live Stats` UI is
  likely not a major issue.
- If scenario `3` jumps clearly over scenario `2`, the scanner polling loop is
  the main suspect.
- If scenario `4` is only marginally worse than scenario `3`, disk recording is
  probably cheap enough and memory reads dominate.
- If scenario `5` is much heavier than scenario `2`, recording-side data
  collection is worth optimizing separately from the scanner.
