# Run Kills Counter Path

Date: 2026-05-20

## Goal

Document the best current memory path for the live in-run killed-mobs counter
 used by BonkScanner `Live Stats` and `Recordings`.

The target value is the number of enemies killed in the current run.

## Current Best Path

Primary path:

```text
GameAssembly.dll + 0x02F7A170
-> +0xB8
-> +0x0
-> Dictionary<string, float> stats
-> +0x18 entries
-> scan live entries
-> key == "kills"
-> value boxed Single
-> +0x10
```

Fallback path:

```text
GameAssembly.dll + 0x02F6FC78
-> +0xB8
-> +0x2C
```

The fallback value is `Assets.Scripts.Tools.Potato.totalKills`.

## Reverse Evidence

The dump shows:

- `Assets.Scripts.Saves___Serialization.Progression.Stats.RunStats`
- static field `Dictionary<string, float> stats`
- methods `AddValue(EMyStat stat, int value)` and `GetStat(EMyStat stat)`
- enum `EMyStat.kills = 0`

This strongly suggests that current-run kill tracking is stored under the run
stats dictionary and that the semantic key for the total kill counter is
`kills`.

The dump also shows:

- `KillsAndGoldCounter`
- `OnRunStatChanged(string stat, float value)`
- `UpdateKillCounter()`
- string literal `kills`

This reinforces that a run-stat string key named `kills` drives the visible
kill counter flow.

The dump also exposes `Assets.Scripts.Tools.Potato.totalKills`, plus
`killsMinute1`, `killsMinute2`, `killsMinute5`, and `killsMinute10`. This looks
like a secondary tracking/debug path and is suitable as a fallback.

## Confidence

Primary path confidence: medium

Why not high yet:

- this path is structurally strong from the dump
- it has not yet been live-validated in Cheat Engine against the HUD counter
- boxed-float dictionary decoding is implementation-reasonable, but still not
  confirmed against the live process

Fallback path confidence: low-to-medium

- `Potato.totalKills` is easy to read
- but it appears to belong to a tooling/debug-oriented subsystem
- use it only when the primary run-stats path is unavailable

## Implementation Notes

Current repo implementation:

- prefers `RunStats.stats["kills"]`
- falls back to `Potato.totalKills`
- stores the value as a dedicated `mob_kills` field in live snapshots and VOD
  recordings

## Next Validation Step

Use Cheat Engine to compare:

1. the on-screen kill counter
2. `RunStats.stats["kills"]`
3. `Potato.totalKills`

If `RunStats.stats["kills"]` tracks the HUD exactly through run start, active
combat, and run end, upgrade this path to high confidence and treat `Potato` as
fallback-only documentation.
