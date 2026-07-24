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

from dataclasses import dataclass, field, replace
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
# A second, wider window for consumers that answer once and cannot wait for
# the next tick.  The strict TTL is right for anything that repaints -- a
# missed read is corrected 250 ms later and nobody sees it -- but it is wrong
# for a one-shot reply, where "no snapshot" gets read as "no effects".
POWERUPS_SNAPSHOT_GRACE_SECONDS = 6.0

# How long an effect observation stays usable as evidence that the *same*
# effect instance is still on screen.  Powerups are read every 500 ms; this
# tolerates two missed ticks and then gives up, because past that the record
# could belong to a different timer epoch.
_EFFECT_HISTORY_TTL_SECONDS = 3.0

_GRAVEYARD_CRYPT_MARKERS = frozenset(("Crypt Chests", "Crypt Pots"))
_GRAVEYARD_OUTDOOR_MARKERS = frozenset(("Pumpkin", "Gravestones"))


@dataclass(frozen=True)
class _EffectObservation:
    """What the previous tick saw of one active effect.

    Kept so the next tick can tell a buff it has been watching all along from
    one it is meeting for the first time.  The game hands out no instance id,
    so continuity has to be reconstructed from the values themselves.
    """

    added_time: float
    expiration_time: float
    my_time: float
    duration: float
    captured_at: float


@dataclass
class _PowerupState:
    powerups_snapshot: PowerupsSnapshot = field(default_factory=PowerupsSnapshot)
    powerup_map_context: PowerupMapContext = field(default_factory=PowerupMapContext)
    fast_stage_timer_context: FastStageTimerContext = field(default_factory=FastStageTimerContext)
    graveyard_final_swarm_timer_is_zero: bool = False
    effect_history: dict[int, _EffectObservation] = field(default_factory=dict)
    # The previous tick's ``crypt_timer`` reading, kept so the *delta* can drive
    # crypt detection. The value alone cannot: ``crypt_timer`` retains its last
    # reading outdoors (measured frozen at 70.7 across the whole main map), so
    # ``> 0`` is true for the rest of the run after crypt 1. Only "advanced
    # since last tick" means "inside a crypt now". Reset with the run.
    previous_crypt_timer: float | None = None
    # Sticky latch for Graveyard's post-boss phase. ``GraveyardBossRoom.isBossDefeated``
    # latches true in memory too, but reading it back requires the RSG object to
    # survive the door transition to the main map -- unmeasured. Latching it here
    # the moment we first see it (while still in the room, RSG intact) makes the
    # post-boss fallback hold on the looted main map regardless. Reset with the run.
    graveyard_boss_ever_defeated: bool = False


def fresh_snapshot(state: _PowerupState, now: float) -> PowerupsSnapshot:
    snapshot = state.powerups_snapshot
    if not snapshot.available:
        return snapshot
    if snapshot.captured_at <= 0:
        return PowerupsSnapshot()
    if now - snapshot.captured_at > POWERUPS_SNAPSHOT_TTL_SECONDS:
        return PowerupsSnapshot()
    return snapshot


def recent_snapshot(state: _PowerupState, now: float) -> PowerupsSnapshot:
    """``fresh_snapshot``, extended by a grace window and labelled.

    Within the strict TTL this is ``fresh_snapshot`` exactly.  Past it, and up
    to ``POWERUPS_SNAPSHOT_GRACE_SECONDS``, it returns the same read with
    ``available`` still False -- so nothing keyed on ``available`` changes --
    plus ``stale=True``.  That flag is the whole point: it is the only way a
    caller can distinguish "the reader is a tick behind" from "the reader says
    there is nothing", which are the same empty snapshot otherwise.
    """
    snapshot = state.powerups_snapshot
    if not snapshot.available or snapshot.captured_at <= 0:
        return PowerupsSnapshot()
    age = now - snapshot.captured_at
    if age <= POWERUPS_SNAPSHOT_TTL_SECONDS:
        return snapshot
    if age > POWERUPS_SNAPSHOT_GRACE_SECONDS:
        return PowerupsSnapshot()
    return replace(snapshot, available=False, stale=True)


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
    stage_time: float | None,
    final_swarm_timer: Any,
    is_final_boss_stage: bool = False,
    crypt_timer_advancing: bool = False,
    graveyard_boss_active: bool = False,
) -> _PowerupUiContext:
    """Pick the clock an effect's marks are drawn against.

    ``stage_time`` is optional because it is the one input here that can go
    missing on its own: ``_read_current_stage_time`` returns it as ``None``
    when MapController does not resolve, or when its raw value falls outside
    the sanity band and the stage index has no nominal duration to fall back
    on. A ``None`` reaches ``_PowerupUiContext`` as "no timer limit", which
    already means "report seconds remaining, draw no marks" -- the same
    degradation the Graveyard crypt and boss-room branches below use.

    ``is_final_boss_stage``, ``crypt_timer_advancing`` and
    ``graveyard_boss_active`` are the fast phase markers, read fresh every
    0.5 s straight from memory rather than inferred from the activity
    dictionary the map context carries. They decide *before* any map-context
    logic because the activity dictionary lags its 10 s slow tick, and
    switching to seconds-only is safe on every map: a stage mark can only ever
    be wrong in a crypt or boss room, never merely absent. The
    activity-dictionary crypt branch below stays as the backstop -- it is what
    catches the crypt-1 spawn room, where ``crypt_timer`` has not started
    ticking yet but the crypt markers are already loaded.
    """
    if is_final_boss_stage or crypt_timer_advancing or graveyard_boss_active:
        return _PowerupUiContext(stage_timer, None)
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
        # NOT the boss-room detector -- that is ``graveyard_boss_active`` at the
        # top, from the RSG flags. Live measurement (2026-07-24) showed the
        # Graveyard boss room keeps the FULL outdoor set, so this branch never
        # fires there. It survives only as a safe default for a genuinely
        # unknown/mid-rebuild activity shape: with no marker to trust, report
        # seconds remaining and draw no marks rather than guess a timeline.
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
    is_final_boss_stage = bool(getattr(snapshot, "is_final_boss_stage", False))

    # Crypt detection from the crypt-timer delta, computed here rather than in
    # the client so the "previous reading" lives in run-scoped state that
    # ``clear`` resets. A strictly greater reading means the timer advanced
    # since the last accepted tick -- i.e. we are inside a crypt now. Equality
    # (frozen outdoors) and a reset to zero (crypt re-entry) both read as not
    # advancing; the reset's single tick is covered by the activity-marker
    # backstop in ``resolve_ui_context``.
    crypt_timer = getattr(snapshot, "crypt_timer_seconds", None)
    crypt_timer_advancing = (
        state.previous_crypt_timer is not None
        and crypt_timer is not None
        and float(crypt_timer) > float(state.previous_crypt_timer)
    )
    if crypt_timer is not None:
        state.previous_crypt_timer = float(crypt_timer)

    # Graveyard boss room + everything after the kill. ``fighting`` covers the
    # live fight; ``ever_defeated`` is latched from ``defeated`` and covers the
    # ~10 s post-kill window (swarm still zero) and the looted main map, where
    # final_swarm would otherwise be ambiguous with the pre-boss ghost phase.
    # Gated on ``is_graveyard`` so a stray read on another map cannot latch it.
    if is_graveyard and bool(getattr(snapshot, "graveyard_boss_defeated", False)):
        state.graveyard_boss_ever_defeated = True
    graveyard_boss_active = is_graveyard and (
        bool(getattr(snapshot, "graveyard_boss_fighting", False))
        or state.graveyard_boss_ever_defeated
    )
    active: list[PowerupEffectState] = []
    # Rebuilt from scratch each tick: an effect that expired or was rejected
    # simply does not get re-recorded, so the history prunes itself.
    history: dict[int, _EffectObservation] = {}
    observed_at = clock()

    # Deliberately does not require ``stage_time``. Whether a stage mark can be
    # drawn says nothing about whether a buff is running, and conflating the
    # two is what let a silent read failure be published as "none active" over
    # a live effect: ``_read_current_stage_time`` hands back ``None`` without
    # raising, so no health flag catches it, the whole loop was skipped, and
    # the snapshot still went out available with its durations and multiplier
    # intact. The remaining three inputs are genuinely load-bearing -- seconds
    # remaining needs ``my_time``, the duration needs the multiplier, and every
    # ui context is anchored on ``stage_timer``.
    if (
        my_time is not None
        and stage_timer is not None
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
                previous = state.effect_history.get(effect_id)
                # The game hands out no instance id, so "still the same buff"
                # has to be reconstructed: a record we saw a tick or two ago,
                # with the same added_time, on a clock that has not run
                # backwards, whose expiry has not moved earlier.  A record
                # that survived a timer epoch fails the clock test; a
                # different pickup of the same type fails the added_time test.
                same_instance = (
                    previous is not None
                    and observed_at - previous.captured_at <= _EFFECT_HISTORY_TTL_SECONDS
                    and float(my_time) >= previous.my_time
                    and expiration_time >= previous.expiration_time
                    and _same_reading(added_time, previous.added_time)
                )

                base_duration = 12.0 if effect_id == 4 else 15.0
                duration = base_duration * powerup_multiplier
                if same_instance and expiration_time == previous.expiration_time:
                    # Nothing about this effect moved, so its duration may not
                    # move either.  ``powerup_multiplier`` is re-read every
                    # tick and its cache is deliberately busted the moment the
                    # active set changes; a single bad read would otherwise
                    # re-time a buff the game already committed to, dragging
                    # its pickup mark -- and through ``resolve_ui_context``
                    # its expiry mark -- with it.
                    duration = previous.duration
                elif (
                    previous is None
                    and isfinite(added_time)
                    and added_time <= float(my_time)
                    and float(my_time) - added_time <= _EFFECT_HISTORY_TTL_SECONDS
                    # Sanity band, not a second opinion: this only has to
                    # reject a nonsense pair, and it is wide enough that a
                    # multiplier read which is briefly wrong still admits the
                    # true duration.
                    and 0.5 * duration
                    <= expiration_time - added_time
                    <= 2.0 * duration
                ):
                    # We caught the pickup itself.  The game wrote added_time
                    # and expiration_time in the same frame, so their
                    # difference *is* the duration it granted: exact, and
                    # independent of what the multiplier read returns.
                    duration = expiration_time - added_time
                elif same_instance:
                    # A repeat pickup: expiration_time moved out, added_time
                    # did not, so their difference is no longer the duration.
                    #
                    # ``base_duration * powerup_multiplier`` is the wrong
                    # source here. The multiplier is served from a cache with
                    # its own 5 s TTL, and the read is only force-refreshed
                    # when the *set* of active effects changes -- which
                    # re-picking an already-active buff does not do. A live
                    # run caught this exact transition recording 98.07 s for a
                    # buff the game had granted 111.6 s of.
                    #
                    # The game's own numbers bound the grant far more tightly.
                    # The pickup happened somewhere between the previous read
                    # and this one, so the duration is at least
                    # ``expiration_time - my_time`` and at most
                    # ``expiration_time - previous.my_time`` -- a window one
                    # tick wide. Believe the multiplier only when it lands
                    # inside it; otherwise take the lower bound, which a
                    # 500 ms tick puts within half a second of the truth.
                    granted_at_least = expiration_time - float(my_time)
                    granted_at_most = expiration_time - previous.my_time
                    if not granted_at_least <= duration <= granted_at_most:
                        duration = granted_at_least
                pickup_time = expiration_time - duration
                ui_context = resolve_ui_context(
                    state,
                    clock(),
                    my_time=float(my_time),
                    pickup_time=pickup_time,
                    stage_timer=float(stage_timer),
                    stage_time=(
                        float(stage_time) if stage_time is not None else None
                    ),
                    final_swarm_timer=final_swarm_timer,
                    is_final_boss_stage=is_final_boss_stage,
                    crypt_timer_advancing=crypt_timer_advancing,
                    graveyard_boss_active=graveyard_boss_active,
                )
                if (
                    isfinite(added_time)
                    and added_time <= expiration_time
                    and added_time <= float(my_time)
                    and (
                        # Re-picking an active buff pushes expiration_time out
                        # but leaves added_time at the *first* pickup, so the
                        # gap grows past the window below on every refresh.
                        # For an instance we have watched the whole time that
                        # gap is a fact about the buff, not evidence of a
                        # stale record: rejecting it there is what made the
                        # pickup mark jump on every re-pickup.
                        same_instance
                        # A stale effect record can survive a timer epoch. Its
                        # added_time then implies a duration wildly beyond the
                        # current powerup duration, and must not be projected
                        # onto the current stage timeline.
                        or expiration_time - added_time
                        <= max(duration * 2.0, duration + 10.0)
                    )
                ):
                    added_time_ui_context = resolve_ui_context(
                        state,
                        clock(),
                        my_time=float(my_time),
                        pickup_time=added_time,
                        stage_timer=float(stage_timer),
                        stage_time=(
                            float(stage_time)
                            if stage_time is not None
                            else None
                        ),
                        final_swarm_timer=final_swarm_timer,
                        is_final_boss_stage=is_final_boss_stage,
                        crypt_timer_advancing=crypt_timer_advancing,
                        graveyard_boss_active=graveyard_boss_active,
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
            history[effect_id] = _EffectObservation(
                added_time=added_time,
                expiration_time=expiration_time,
                my_time=float(my_time),
                duration=duration,
                captured_at=observed_at,
            )
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
    state.effect_history = history
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
    state.effect_history = {}
    state.previous_crypt_timer = None
    state.graveyard_boss_ever_defeated = False


def _same_reading(left: float, right: float) -> bool:
    """Equality that also holds for two unreadable values.

    ``added_time`` becomes NaN when the field is missing, and NaN != NaN would
    make every such effect look brand new on every tick -- which is exactly
    the continuity the duration freeze depends on.
    """
    if left == right:
        return True
    return not isfinite(left) and not isfinite(right)


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
