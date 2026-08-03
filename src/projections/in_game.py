"""Read-only values for in-game overlay rendering."""
from __future__ import annotations

from dataclasses import dataclass

from core.tracker.snapshots import RunLifecycle, RuntimeStateSnapshot


@dataclass(frozen=True)
class InGameOverlayProjection:
    latest_snapshot: object | None
    kps: dict[str, int | None]
    powerups: object
    is_graveyard: bool
    fast_stage_timer: object | None
    graveyard_main_map_events_active: bool
    # From the fast loot pass. ``None`` means no fresh read, not "Luck is zero";
    # the Luck Rarity widget falls back to the 10 s snapshot's copy on ``None``
    # rather than rendering a failed read as a real reading.
    luck: float | None = None
    # The actual-versus-expected summary the Luck widget's expected frame
    # renders. Carried on the projection rather than read off the tracker for
    # the same reason ``luck`` is: this object is the whole of what the fast
    # tick hands the widgets, so anything missing here is simply invisible --
    # which is exactly how the frame shipped switched off.
    loot_stats: object | None = None
    # Timed-item cooldowns from the 1 s loot pass: the readings and the game
    # clock they were measured against, in one object. ``None`` means no fresh
    # read; a snapshot whose ``readings`` are empty means no timed item is held.
    item_cooldowns: object | None = None
    # Whether the run is still going. Carried because the cooldown widget cannot
    # be cleared by freshness alone: on the death screen the game clock freezes
    # and every read keeps succeeding, so the reading stays fresh forever and
    # the countdown would sit frozen on screen. Measured, not assumed -- 256
    # consecutive successful reads over 26 s there. This is the only signal that
    # separates that state from a pause, which is byte-identical.
    run_completed: bool = False


def project_in_game_overlay(runtime: RuntimeStateSnapshot) -> InGameOverlayProjection:
    context = runtime.powerup_map_context
    return InGameOverlayProjection(
        latest_snapshot=runtime.latest_snapshot,
        kps=dict(runtime.kps),
        powerups=runtime.powerups,
        is_graveyard=bool(context and context.is_graveyard),
        fast_stage_timer=runtime.fast_stage_timer,
        graveyard_main_map_events_active=runtime.graveyard_main_map_events_active,
        luck=getattr(runtime, "luck", None),
        loot_stats=getattr(runtime, "loot_stats", None),
        item_cooldowns=getattr(runtime, "item_cooldowns", None),
        run_completed=getattr(runtime, "lifecycle", None) is RunLifecycle.COMPLETED,
    )
