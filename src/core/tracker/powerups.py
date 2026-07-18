"""Powerup snapshots, map context and stage-timer freshness: pure functions
over ``_PowerupState``.

Split out of ``live_run_tracker.py`` in step 13.  Nothing here acquires a
lock; ``LiveRunTracker`` calls in while already holding its single ``RLock``.

Everything here is TTL-gated.  Powerup and stage-timer reads come from the
fast tick and go stale quickly, so each accessor takes ``now`` and decides
whether the stored value still counts.  ``now`` is a parameter rather than a
clock this module calls itself, so the caller keeps control of *when* time is
sampled -- the tracker reads its clock at exactly the points it used to,
which matters because several of these are consulted more than once while a
single snapshot is assembled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Callable

from core.tracker.snapshots import (
    FastStageTimerContext,
    PowerupMapContext,
    PowerupsSnapshot,
    _PowerupUiContext,
)

POWERUP_MAP_CONTEXT_TTL_SECONDS = 15.0
FAST_STAGE_TIMER_TTL_SECONDS = 2.0
POWERUPS_SNAPSHOT_TTL_SECONDS = 1.5


@dataclass
class _PowerupState:
    powerups_snapshot: PowerupsSnapshot = field(default_factory=PowerupsSnapshot)
    powerup_map_context: PowerupMapContext = field(default_factory=PowerupMapContext)
    fast_stage_timer_context: FastStageTimerContext = field(default_factory=FastStageTimerContext)
    graveyard_final_swarm_timer_is_zero: bool = False


def fresh_snapshot(state: _PowerupState, now: float) -> PowerupsSnapshot:
    snapshot = state.powerups_snapshot
    if not snapshot.available:
        return snapshot
    if snapshot.captured_at <= 0:
        return PowerupsSnapshot()
    if now - snapshot.captured_at > POWERUPS_SNAPSHOT_TTL_SECONDS:
        return PowerupsSnapshot()
    return snapshot


def fresh_map_context(state: _PowerupState, now: float) -> PowerupMapContext | None:
    context = state.powerup_map_context
    if context.captured_at <= 0:
        return None
    if now - context.captured_at > POWERUP_MAP_CONTEXT_TTL_SECONDS:
        return None
    return context


def fresh_fast_stage_timer_context(
    state: _PowerupState, now: float
) -> FastStageTimerContext | None:
    context = state.fast_stage_timer_context
    if context.captured_at <= 0:
        return None
    if now - context.captured_at > FAST_STAGE_TIMER_TTL_SECONDS:
        return None
    return context


def set_map_context(
    state: _PowerupState,
    context: PowerupMapContext,
    clock: Callable[[], float],
) -> None:
    """Store a map context, stamping it with the current time if it is unstamped.

    Takes the clock callable rather than a sampled ``now`` -- unlike the
    accessors above -- because the original only read the clock when the
    stamp was actually missing.  Every clock in use is pure, so an eager read
    would be harmless today, but preserving the read point costs nothing and
    keeps this a move rather than a change.
    """
    if context.captured_at <= 0:
        context = PowerupMapContext(
            is_graveyard=context.is_graveyard,
            captured_at=clock(),
            activity_max=context.activity_max,
        )
    state.powerup_map_context = context


def graveyard_main_map_events_active(state: _PowerupState, now: float) -> bool:
    map_context = fresh_map_context(state, now)
    if not map_context or not map_context.is_graveyard:
        return False
    activities = map_context.activity_max or {}
    return (
        "Crypt Chests" not in activities
        and "Crypt Pots" not in activities
        and state.graveyard_final_swarm_timer_is_zero
    )


def resolve_ui_context(
    state: _PowerupState,
    now: float,
    *,
    my_time: float,
    pickup_time: float,
    stage_timer: float,
    stage_time: float,
    final_swarm_timer: Any,
    crypt_timer: Any,
) -> _PowerupUiContext:
    map_context = fresh_map_context(state, now)
    if map_context is None:
        return _PowerupUiContext(stage_timer, None)
    if not map_context.is_graveyard:
        return _PowerupUiContext(stage_timer, stage_time)

    try:
        final_swarm_value = float(final_swarm_timer)
    except (TypeError, ValueError):
        final_swarm_value = float("nan")
    if (
        isfinite(final_swarm_value)
        and final_swarm_value > 0.0
        and pickup_time >= my_time - final_swarm_value
    ):
        return _PowerupUiContext(final_swarm_value, 0.0)

    try:
        crypt_value = float(crypt_timer)
    except (TypeError, ValueError):
        crypt_value = float("nan")
    if (
        isfinite(crypt_value)
        and crypt_value > 0.0
        and stage_timer <= 1.0
        and pickup_time >= my_time - crypt_value
    ):
        return _PowerupUiContext(crypt_value, None)

    graveyard_stage_limit = 960.0
    return _PowerupUiContext(stage_timer, graveyard_stage_limit)


def format_duration_seconds(value: float) -> str:
    return str(int(round(value)))


def format_ui_stage_time(raw_stage_timer: float, stage_time: float) -> str:
    if raw_stage_timer <= stage_time:
        value = max(0.0, stage_time - raw_stage_timer)
        prefix = ""
    else:
        value = raw_stage_timer - stage_time
        prefix = "+"
    total_seconds = max(0, int(value))
    return f"{prefix}{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def format_powerups_text(
    snapshot: PowerupsSnapshot,
    *,
    include_left_word: bool = True,
) -> str:
    durations_text = None
    if (
        snapshot.standard_duration_seconds is not None
        and snapshot.clock_duration_seconds is not None
    ):
        durations_text = (
            "Durations: "
            f"standard {format_duration_seconds(snapshot.standard_duration_seconds)}s, "
            f"clock {format_duration_seconds(snapshot.clock_duration_seconds)}s"
        )
    if snapshot.active:
        parts = []
        suffix = " left" if include_left_word else ""
        for effect in snapshot.active:
            duration_text = (
                f"({format_duration_seconds(effect.remaining_seconds)}s{suffix})"
            )
            if effect.pickup_ui is None or effect.expires_ui is None:
                parts.append(f"{effect.name} {duration_text}")
            else:
                parts.append(
                    f"{effect.name} {effect.pickup_ui} -> {effect.expires_ui} "
                    f"{duration_text}"
                )
        if durations_text is not None:
            parts.append(durations_text)
        return " | ".join(parts)
    if durations_text is None:
        return "none active"
    return f"none active | {durations_text}"


def format_summary(snapshot: PowerupsSnapshot, *, include_left_word: bool = True) -> str:
    if not snapshot.available:
        return "Powerups: --"
    powerups_text = format_powerups_text(snapshot, include_left_word=include_left_word)
    if snapshot.powerup_multiplier_display == "--":
        return f"Powerups: {powerups_text}"
    return f"Powerups: {powerups_text} (PM {snapshot.powerup_multiplier_display})"


def summary_text(snapshot: PowerupsSnapshot, *, include_left_word: bool = True) -> str:
    if not snapshot.available:
        return "--"
    return format_powerups_text(snapshot, include_left_word=include_left_word)
