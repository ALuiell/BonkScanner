# Powerup Pipeline Hardening: Implementation Plan

## Status and scope

This is the implementation-ready follow-up to `functional_updates.md` item
"Harden The Live Powerup Read Pipeline". It is separate from the fixed
`Invulnerability (5) -> TimeFreeze (4)` dictionary-slot reuse bug.

The completed fix rescans status-effect keys every fast poll. This plan handles
the remaining case where a memory read is unavailable or incomplete but is
currently represented as a valid empty powerup list.

## Current failure mode

`PlayerStatsClient.get_active_status_effects()` can return `()` for two
different meanings:

1. A complete, valid dictionary contains no supported powerups.
2. A pointer, dictionary field, entry, or effect object could not be read.

`LiveRunTracker.update_powerups()` cannot distinguish them and writes a fresh
empty `PowerupsSnapshot` in both cases. That clears Live Stats, Twitch, and the
in-game overlay together.

## Target contract

Add a small reusable health value in `player_stats.py`:

```python
@dataclass(frozen=True)
class PowerupReadHealth:
    available: bool
    complete: bool
    failure_reason: str | None = None
    captured_at: float = 0.0
    source: str = "fast"
```

`PowerupTrackingSnapshot` gains separate health values for the independent
read groups:

```python
status_effects_health: PowerupReadHealth
timing_health: PowerupReadHealth
multiplier_health: PowerupReadHealth
```

`get_active_status_effects()` remains as a compatibility wrapper returning a
tuple. A new internal reader returns both the effects and `status_effects_health`.
The public powerup snapshot reader uses the detailed result.

## Read classification

| Situation | available | complete | failure_reason |
| --- | --- | --- | --- |
| Valid dictionary, including a valid empty list | true | true | `None` |
| Missing/null inventory, status-effects, dictionary, or entries pointer | false | false | `status_effects_unavailable` |
| Invalid count/capacity or unreadable required dictionary metadata | false | false | `status_effects_partial` |
| One or more active candidate entries cannot be read | true | false | `status_effects_partial` |
| Missing/invalid MyTime or stage timing | false | false | `powerup_timing_unavailable` |
| Missing/non-finite Powerup Multiplier | false | false | `powerup_multiplier_unavailable` |

The existing per-poll key rescan remains in place. A valid empty dictionary is
authoritative only when its health is `available=True, complete=True`.

## Tracker acceptance rule

`LiveRunTracker.update_powerups()` must validate all three health values before
replacing `_powerups_snapshot`:

1. A complete status-effects read plus valid timing and multiplier is accepted.
   A complete empty effect list clears active powerups normally.
2. Any unavailable or partial dependency is rejected. Do not replace the last
   accepted snapshot and do not refresh its `captured_at` value.
3. Existing `POWERUPS_SNAPSHOT_TTL_SECONDS` remains the bounded compatibility
   grace period for rejected reads. An explicit run reset continues to clear
   powerups immediately.
4. Rejected reads update feature diagnostics with the machine-readable reason;
   accepted reads mark the feature successful.

This preserves the current bounded stale-data policy while preventing a single
partial read from masquerading as "none active".

## Code touchpoints

| File | Change |
| --- | --- |
| `src/player_stats.py` | Add health contract; classify pointer/metadata/entry failures; attach health to `PowerupTrackingSnapshot`. |
| `src/live_run_tracker.py` | Validate snapshot health before replacement; retain last accepted snapshot on rejection; expose failure reason through feature status. |
| `src/gui_player_stats.py` | Treat a rejected update as a failed fast feature without changing consumers directly. |
| `src/tests/test_player_stats.py` | Verify health classification for empty, unavailable, and partial status-effects reads and PM/timing failures. |
| `src/tests/test_live_run_tracker.py` | Verify accepted empty clears state; rejected snapshots preserve state only within the existing TTL; verify recovery and reset behavior. |

No consumer changes are needed: Twitch, Live Stats, and the in-game overlay
already consume the common tracker snapshot.

## Required tests

1. Valid empty dictionary clears an active Clock snapshot.
2. Null status-effects pointer produces `status_effects_unavailable` and does
   not clear a prior active snapshot.
3. An unreadable active effect entry produces `status_effects_partial` and does
   not clear a prior active snapshot.
4. `Powerup Multiplier=None` and a non-finite multiplier preserve the prior
   active snapshot.
5. Invalid/missing MyTime or stage timing preserves the prior active snapshot.
6. Several rejected polls do not refresh `captured_at`; the existing TTL still
   expires as designed.
7. A subsequent complete read replaces the retained snapshot immediately.
8. Explicit run reset clears the retained snapshot immediately.
9. Existing `Invulnerability (5) -> TimeFreeze (4)` regression test remains
   green to protect the slot-reuse fix.

## Delivery order

1. Add the read-health data contract and player-stats tests.
2. Add tracker validation and tracker tests.
3. Wire the refresh task to report rejected snapshots as failed feature reads.
4. Run the full relevant test suite and perform one live `Zavaruda` smoke test.
5. Update the functional-updates item from `Open` to `Implemented` only after
   the live smoke test succeeds.
