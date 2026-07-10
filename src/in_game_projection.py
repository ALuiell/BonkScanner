"""Read-only values for in-game overlay rendering."""
from __future__ import annotations

from dataclasses import dataclass

from live_run_tracker import RuntimeStateSnapshot


@dataclass(frozen=True)
class InGameOverlayProjection:
    latest_snapshot: object | None
    kps: dict[str, int | None]
    powerups: object
    is_graveyard: bool
    fast_stage_timer: object | None
    graveyard_main_map_events_active: bool


def project_in_game_overlay(runtime: RuntimeStateSnapshot) -> InGameOverlayProjection:
    context = runtime.powerup_map_context
    return InGameOverlayProjection(
        latest_snapshot=runtime.latest_snapshot,
        kps=dict(runtime.kps),
        powerups=runtime.powerups,
        is_graveyard=bool(context and context.is_graveyard),
        fast_stage_timer=runtime.fast_stage_timer,
        graveyard_main_map_events_active=runtime.graveyard_main_map_events_active,
    )
