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
    PowerupEffectState,
    PowerupMapContext,
    PowerupsSnapshot,
    _PowerupUiContext,
)

POWERUP_MAP_CONTEXT_TTL_SECONDS = 15.0
FAST_STAGE_TIMER_TTL_SECONDS = 2.0
POWERUPS_SNAPSHOT_TTL_SECONDS = 1.5

_GRAVEYARD_CRYPT_MARKERS = frozenset(("Crypt Chests", "Crypt Pots"))
_GRAVEYARD_OUTDOOR_MARKERS = frozenset(("Pumpkin", "Gravestones"))


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
    # Graveyard's boss room replaces the outdoor activity dictionary, so it
    # no longer contains a strong Graveyard marker.  The map itself has not
    # changed: preserve a fresh, already-confirmed Graveyard identity until
    # the tracker resets for the next run.
    previous = state.powerup_map_context
    if previous.is_graveyard and not context.is_graveyard:
        context = PowerupMapContext(
            is_graveyard=True,
            captured_at=context.captured_at,
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
) -> _PowerupUiContext:
    map_context = fresh_map_context(state, now)
    if map_context is None:
        return _PowerupUiContext(stage_timer, None)

    try:
        final_swarm_value = float(final_swarm_timer)
    except (TypeError, ValueError):
        final_swarm_value = float("nan")
    final_swarm_is_usable = isfinite(final_swarm_value) and final_swarm_value > 0.0

    if not map_context.is_graveyard:
        # On ordinary maps the game keeps FinalSwarm in lockstep with the UI
        # final-swarm clock, including manual timer changes. It begins after
        # the ordinary stage, so it has its own zero origin: do not subtract
        # the 10-minute stage duration from it. A missing/zero value remains a
        # safe stage-timer fallback.
        if final_swarm_is_usable:
            return _PowerupUiContext(final_swarm_value, 0.0)
        return _PowerupUiContext(stage_timer, stage_time)

    activities = map_context.activity_max or {}
    if _GRAVEYARD_CRYPT_MARKERS & activities.keys():
        # Both crypts use their own upward timer and have no meaningful stage
        # timeline. Effects carried in from outdoors need the same fallback as
        # effects picked up inside.
        return _PowerupUiContext(stage_timer, None)

    if not (_GRAVEYARD_OUTDOOR_MARKERS & activities.keys()):
        # The confirmed Graveyard map has neither crypt nor outdoor markers in
        # its boss room. Its stage clock is temporarily rewritten there, so
        # only seconds remaining are honest. When the player exits back to the
        # outdoor post-boss phase, Pumpkin/Gravestones return and the normal
        # 16-minute stage timeline below resumes.
        return _PowerupUiContext(stage_timer, None)

    if final_swarm_is_usable and pickup_time >= my_time - final_swarm_value:
        # In the outdoor final-swarm phase this is the game/UI clock. Keeping
        # its zero origin makes manual time adjustments move both endpoints,
        # as they did before the Graveyard room fallback was introduced.
        return _PowerupUiContext(final_swarm_value, 0.0)

    graveyard_stage_limit = 960.0
    return _PowerupUiContext(stage_timer, graveyard_stage_limit)


def check_health(snapshot: Any) -> str | None:
    """Return a failure reason if any dependency of this read is unusable.

    A partial powerup read must be rejected outright rather than merged: a
    missing multiplier or timing value would silently produce wrong pickup
    and expiry times.  Rejecting leaves the previous good snapshot in place
    until its TTL expires.
    """
    for health_name in (
        "status_effects_health",
        "timing_health",
        "multiplier_health",
    ):
        health = getattr(snapshot, health_name, None)
        if health is None:
            continue
        if bool(getattr(health, "available", False)) and bool(
            getattr(health, "complete", False)
        ):
            continue
        return str(
            getattr(health, "failure_reason", None)
            or "powerup_snapshot_incomplete"
        )
    return None


def apply_snapshot(
    state: _PowerupState,
    snapshot: Any,
    *,
    clock: Callable[[], float],
) -> None:
    """Build and store the powerup snapshot from a health-checked read.

    Takes the clock callable because it samples time at several points the
    original did -- once for the graveyard map-context check, once or twice
    per effect inside resolve_ui_context, and once for captured_at.
    """
    # Graveyard room transitions replace entries in the activity dictionary.
    # `crypt_timer` remains non-zero after leaving a crypt, so it cannot
    # identify the current room.
    map_context = fresh_map_context(state, clock())
    is_graveyard = bool(map_context and map_context.is_graveyard)

    if is_graveyard:
        final_swarm_timer = getattr(snapshot, "final_swarm_timer_seconds", None) if snapshot is not None else None
        try:
            swarm_val = float(final_swarm_timer)
        except (TypeError, ValueError):
            swarm_val = float("nan")
        state.graveyard_final_swarm_timer_is_zero = swarm_val == 0.0
    else:
        state.graveyard_final_swarm_timer_is_zero = False
    powerup_multiplier = getattr(snapshot, "powerup_multiplier", None)
    try:
        powerup_multiplier = float(powerup_multiplier)
    except (TypeError, ValueError):
        powerup_multiplier = None
    if powerup_multiplier is not None and not isfinite(powerup_multiplier):
        powerup_multiplier = None

    standard_duration = (
        15.0 * powerup_multiplier if powerup_multiplier is not None else None
    )
    clock_duration = (
        12.0 * powerup_multiplier if powerup_multiplier is not None else None
    )

    my_time = getattr(snapshot, "my_time_seconds", None)
    stage_timer = getattr(snapshot, "stage_timer_seconds", None)
    stage_time = getattr(snapshot, "stage_time_seconds", None)
    final_swarm_timer = getattr(snapshot, "final_swarm_timer_seconds", None)
    stage_index = getattr(snapshot, "stage_index", None)
    active: list[PowerupEffectState] = []

    if (
        my_time is not None
        and stage_timer is not None
        and stage_time is not None
        and powerup_multiplier is not None
        and int(stage_index if stage_index is not None else -1) < 3
    ):
        for effect in getattr(snapshot, "effects", ()) or ():
            try:
                effect_id = int(getattr(effect, "effect_id", -1))
                added_time_raw = getattr(effect, "added_time", None)
                added_time = (
                    float(added_time_raw) if added_time_raw is not None else float("nan")
                )
                expiration_time = float(getattr(effect, "expiration_time", 0.0))
                remaining = expiration_time - float(my_time)
                if remaining <= 0 or not isfinite(remaining):
                    continue
                base_duration = 12.0 if effect_id == 4 else 15.0
                duration = base_duration * powerup_multiplier
                pickup_time = expiration_time - duration
                ui_context = resolve_ui_context(
                    state,
                    clock(),
                    my_time=float(my_time),
                    pickup_time=pickup_time,
                    stage_timer=float(stage_timer),
                    stage_time=float(stage_time),
                    final_swarm_timer=final_swarm_timer,
                )
                if (
                    isfinite(added_time)
                    and added_time <= expiration_time
                    and added_time <= float(my_time)
                    # A stale effect record can survive a timer epoch. Its
                    # added_time then implies a duration wildly beyond the
                    # current powerup duration, and must not be projected
                    # onto the current stage timeline.
                    and expiration_time - added_time
                    <= max(duration * 2.0, duration + 10.0)
                ):
                    added_time_ui_context = resolve_ui_context(
                        state,
                        clock(),
                        my_time=float(my_time),
                        pickup_time=added_time,
                        stage_timer=float(stage_timer),
                        stage_time=float(stage_time),
                        final_swarm_timer=final_swarm_timer,
                    )
                    if added_time_ui_context == ui_context:
                        pickup_time = added_time
                        ui_context = added_time_ui_context
                raw_pickup = ui_context.timer_value + (pickup_time - float(my_time))
                raw_expiration = ui_context.timer_value + (
                    expiration_time - float(my_time)
                )
                if not isfinite(raw_pickup) or not isfinite(raw_expiration):
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
            active.append(
                PowerupEffectState(
                    effect_id=effect_id,
                    name=str(getattr(effect, "name", effect_id)),
                    pickup_ui=(
                        format_ui_stage_time(
                            raw_pickup,
                            ui_context.timer_limit,
                        )
                        if ui_context.timer_limit is not None
                        else None
                    ),
                    expires_ui=(
                        format_ui_stage_time(
                            raw_expiration,
                            ui_context.timer_limit,
                        )
                        if ui_context.timer_limit is not None
                        else None
                    ),
                    pickup_offset_seconds=pickup_time - float(my_time),
                    expiration_offset_seconds=expiration_time - float(my_time),
                    remaining_seconds=remaining,
                    duration_seconds=duration,
                    stage_index=stage_index,
                    raw_stage_pickup=raw_pickup,
                    raw_stage_expiration=raw_expiration,
                )
            )

    active.sort(key=lambda effect: effect.raw_stage_expiration, reverse=True)
    state.powerups_snapshot = PowerupsSnapshot(
        active=tuple(active),
        powerup_multiplier=powerup_multiplier,
        powerup_multiplier_display=str(
            getattr(snapshot, "powerup_multiplier_display", "--") or "--"
        ),
        standard_duration_seconds=standard_duration,
        clock_duration_seconds=clock_duration,
        stage_index=stage_index,
        stage_time_seconds=stage_time,
        captured_at=clock(),
        available=True,
    )


def clear(state: _PowerupState) -> None:
    state.powerups_snapshot = PowerupsSnapshot()


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
