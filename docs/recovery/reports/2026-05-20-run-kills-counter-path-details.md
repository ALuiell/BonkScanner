# Run Kills Counter Path Details

Date: 2026-05-20

## Goal

Document the confirmed live memory path for the current-run killed-mobs counter
shown in the Megabonk HUD and used by BonkScanner `Live Stats` / `Recordings`.

This report supersedes the earlier boxed-value hypothesis and records the
current-build dictionary layout observed in the live process.

## Best Confirmed Path

Canonical source:

```text
GameAssembly.dll + 0x02F7A170
-> [read qword] RunStats class ptr
-> +0xB8
-> [read qword] static fields
-> +0x0
-> [read qword] Dictionary<string, float> stats
-> +0x18
-> [read qword] entries array
-> +0x20 + (index * 0x18)
-> find entry where key == "kills"
-> +0x10
-> float value
```

Important:

- the stable root is the `RunStats.stats` dictionary
- the final kill value is not a fixed leaf pointer
- the last step is a dictionary entry scan by key string

## CE-Safe Description

Base:

```text
GameAssembly.dll + 0x02F7A170
```

Offsets top-to-bottom:

```text
+0xB8
+0x0
+0x18
```

Then:

- read dictionary `count` at `stats + 0x20`
- iterate entries from `entries + 0x20`
- entry size is `0x18`
- stop when managed string at `entry + 0x8` is `"kills"`
- read `float` at `entry + 0x10`

Value type:

- `float` in memory
- practical consumer type: `int` after truncation / clamp

## Current Build Layout

Class and fields from dump:

- `Assets.Scripts.Saves___Serialization.Progression.Stats.RunStats`
- `private static Dictionary<string, float> stats; // 0x0`
- `public static void AddValue(EMyStat stat, int value)`
- `public static int GetStat(EMyStat stat)`
- `public static void AddValue(string stat, int value)`
- `public static int GetStat(string stat)`
- `EMyStat.kills = 0`

Observed dictionary layout in the live process:

```text
Dictionary<string, float>
+0x18 = entries array ptr
+0x20 = count
```

Observed `Dictionary.Entry<string, float>` layout:

```text
+0x0  = hashCode (int)
+0x4  = next (int)
+0x8  = key ptr (System.String*)
+0x10 = value (float, inline)
```

This means the value is stored inline in the entry.

It is not a boxed `Single` in the current build.

## Live Validation

Live target process:

- `Megabonk.exe`

Confirmed session behavior:

1. User reported HUD kill counter = `14`
2. Live `RunStats.stats["kills"]` readback = `14.0`
3. User killed one more mob and reported HUD = `15`
4. Same live entry changed to `15.0`

Observed live addresses during confirmation:

```text
RunStats class ptr      = 0x19BA24485E0
RunStats static fields  = 0x19DB02E89A0
RunStats.stats dict     = 0x19DB4495480
entries array           = 0x19DB438B380
kills entry             = 0x19DB438B3B8
kills value field       = 0x19DB438B3C8
current value           = 15.0f
```

Observed `kills` entry snapshot:

```text
hashCode = 287745009
next     = -1
key      = "kills"
raw      = 0x41700000
float    = 15.0
```

This is strong live confirmation that the entry tracks the HUD kill counter.

## Why This Is The Right Source

- the key is literally `"kills"`
- the container is `RunStats`, which is run-scoped gameplay state
- dump symbols show HUD-related consumers:
  - `KillsAndGoldCounter`
  - `OnRunStatChanged(string stat, float value)`
  - `UpdateKillCounter()`
- the value matched HUD exactly
- the value incremented immediately on a real kill event

This excludes the main false positives:

- not `EnemyManager.numEnemies`
  - that tracks currently alive enemies
- not profile/account lifetime kills
  - source object is `RunStats`, not progression/profile storage
- not kills-per-minute
  - field name is `kills`, not `killsMinuteX`
- not a derived display-only metric
  - it is directly attached to run stat change flow

## Fallback Analysis

Earlier fallback candidate:

```text
GameAssembly.dll + 0x02F6FC78
-> [read qword] Potato class ptr
-> +0xB8
-> [read qword] static fields
-> +0x2C
-> int totalKills
```

Dump symbols:

- `Assets.Scripts.Tools.Potato`
- `private static int totalKills; // 0x2C`
- `public static int killsMinute1; // 0x30`
- `public static int killsMinute2; // 0x34`
- `public static int killsMinute5; // 0x38`
- `public static int killsMinute10; // 0x3C`

Live observation during the same run:

```text
totalKills    = 0
killsMinute1  = 14
killsMinute2  = 14
killsMinute5  = 14
killsMinute10 = 14
```

Conclusion:

- `Potato.totalKills` is not confirmed as the HUD kill counter
- `Potato.killsMinuteX` are clearly not the canonical total kills field
- do not use `Potato` as primary source for BonkScanner

If the dictionary path ever breaks, a better fallback is:

- return unavailable / no data
- or hook `RunStats.AddValue(EMyStat stat, int value)`

## CE Steps

1. Attach CE to `Megabonk.exe`.
2. Resolve `GameAssembly.dll+2F7A170`.
3. Read qword at base to get `RunStats` class ptr.
4. Read qword at `class + 0xB8` to get static fields.
5. Read qword at `static_fields + 0x0` to get `RunStats.stats`.
6. Read qword at `stats + 0x18` for entries and int at `stats + 0x20` for count.
7. For each entry:
   - `entry = entries + 0x20 + index * 0x18`
   - decode managed string at `entry + 0x8`
   - when key is `"kills"`, read float at `entry + 0x10`

## Integration Notes For Python

Recommended read strategy:

- keep the stable chain only to `RunStats.stats`
- scan entries by key each read
- convert the float to `int`

Pseudo-logic:

```text
type_info = module_base + 0x02F7A170
class_ptr = *type_info
static_fields = *(class_ptr + 0xB8)
stats_dict = *(static_fields + 0x0)
count = *(int*)(stats_dict + 0x20)
entries = *(ptr*)(stats_dict + 0x18)

for i in range(count):
    entry = entries + 0x20 + i * 0x18
    hash_code = *(int*)(entry + 0x0)
    if hash_code < 0:
        continue
    key_ptr = *(ptr*)(entry + 0x8)
    key = read_managed_string(key_ptr)
    if key == "kills":
        return int(*(float*)(entry + 0x10))
```

## Confidence

Confidence: high

Why high:

- live-validated against HUD
- live-validated across a kill increment
- symbol names and UI flow agree with the memory source

Known caveat:

- the final entry address is session-dependent because dictionary slots can move
- the stable artifact is the dictionary root plus key lookup, not a fixed final
  leaf pointer
