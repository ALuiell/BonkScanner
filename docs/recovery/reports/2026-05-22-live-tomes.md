## Goal

Document the live memory path used to read current-run tomes for Megabonk, in a
form suitable for:

- `Live Stats` tome display
- player stats / VOD recordings
- recording playback

This report focuses on the rooted runtime path and the final user-facing values
we now show in the app: tome name, level, and the current effective modifier
stored for that tome.

## Current Result

Status: `[Done]`

Live tome tracking is now implemented and confirmed in-game.

The current rooted path is:

```text
GameAssembly.dll + 0x02F6A4B8
-> PlayerStatsNew static type info
-> class_ptr
-> +0xB8 static fields
-> +0x0 root
-> +0x40 PlayerStatsNew owner
-> +0x28 PlayerInventory
-> +0x48 TomeInventory
```

Inside `TomeInventory`:

- `+0x18` -> `Dictionary<ETome, int> tomeLevels`
- `+0x28` -> `Dictionary<ETome, StatModifier> tomeUpgrade`

For v1 implementation:

- `tomeLevels` provides the displayed tome level
- `tomeUpgrade` provides the live effective stat/value shown in UI and stored in
  recordings

## Relevant Dump Findings

Sources:

- `F:\Python\CA_mpc_bridge\Dump\dump.cs`
- `F:\Python\CA_mpc_bridge\Dump\il2cpp.h`

Confirmed layout:

`PlayerInventory`:

```text
+0x20 itemInventory
+0x28 weaponInventory
+0x30 playerXp
+0x48 tomeInventory
```

`TomeInventory`:

```text
+0x18 tomeLevels Dictionary<ETome, int>
+0x20 statToTomes Dictionary<EStat, HashSet<ETome>>
+0x28 tomeUpgrade Dictionary<ETome, StatModifier>
```

`StatModifier`:

```text
+0x10 stat EStat
+0x18 modification float
```

`TomeData`:

```text
+0x50 eTome ETome
```

## ETome Names Used In Code

The current implementation maps these ids to display names:

- `0 Damage`
- `1 Agility`
- `2 Cooldown`
- `3 Quantity`
- `4 Knockback`
- `5 Armor`
- `6 Health`
- `7 Regeneration`
- `8 Size`
- `9 Projectile Speed`
- `10 Duration`
- `11 Evasion`
- `12 Attraction`
- `13 Luck`
- `14 XP`
- `15 Golden`
- `16 Precision`
- `17 Shield`
- `18 Blood`
- `19 Thorns`
- `20 Bounce`
- `21 Cursed`
- `22 Silver`
- `23 Balance`
- `24 Chaos`
- `25 Gambler`
- `26 Hoarder`

## Implementation Shape

Implemented in:

- `src/player_stats.py`
- `src/vod_storage.py`
- `src/gui.py`

Normalized runtime structure:

```text
TomeSnapshot(
  tome_id,
  name,
  level,
  stat_id,
  stat_label,
  value,
  value_format,
)
```

Display behavior:

- `Live Stats` shows tomes in a dedicated `Tomes` tab
- `Recordings` playback shows the same structure
- each card shows:
  - tome name
  - `Lv. N`
  - one live effective stat/value row

Recording behavior:

- VOD snapshots now store optional `tomes`
- old recordings without `tomes` remain loadable
- playback falls back cleanly when tome data is absent

## Why This Path Is Good

This path is rooted and implementation-safe:

- it starts from the same stable `PlayerStatsNew` root already used by other
  live stats features
- it avoids heap scans
- it reads the current live `TomeInventory` object instead of stale detached
  objects

For the user-facing feature, `tomeUpgrade` is especially useful because it
already contains the live effective modifier to display, instead of requiring us
to re-derive every tome effect from static catalog data.

## Caveats

- `statToTomes` exists but is not needed for the current UI/recording feature
- special tomes such as `Chaos` may use more complex internal generation logic,
  but the current feature intentionally shows the already stored live modifier
  rather than reconstructing every internal formula
- if the game later stores multiple active modifiers per tome in a different
  shape, this path may need refresh

## Live Validation

Manual validation outcome on 2026-05-22:

- the app detected live tomes immediately during an active run
- multiple tomes were shown correctly in UI
- user confirmed the feature worked live after acquiring four tomes in-game

That is strong confirmation that:

- `PlayerInventory +0x48` resolves the live tome inventory
- `tomeLevels` is valid for current run tome level display
- `tomeUpgrade` is valid for the displayed effective tome modifier
