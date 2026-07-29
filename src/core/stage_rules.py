"""Per-stage game rules: stage durations, Difficulty caps, the XP Gain cap.

Numbers the *game* fixes, not the app. They were literals inside two functions
in ``projections/in_game_html.py`` -- ``build_player_stats_overlay_html`` for
the cap suffix, ``build_event_timer_overlay_html`` for the countdown base --
and the Recordings scrubber needs the same table to draw the cap staircase
over a recorded run.

Named here once rather than copied: a game constant with two homes is a game
constant that drifts, and the drift is silent because each copy keeps working
on its own.

Qt-free and I/O-free, so ``projections/`` and ``ui/`` may both import it.

Note the two *different* stage-timing values these rules read, which are easy
to confuse because their names differ by one word:

* the **elapsed** stage timer (``MyTime``), which counts up and resets when the
  stage changes -- this is what ``VodSnapshot.stage_time_seconds`` records;
* the stage's **duration**, which is a fixed property of the map stage and is
  what ``STAGE_DURATION_SECONDS`` holds.

``build_event_timer_overlay_html`` carries a comment saying the live
``CurrentStage -> Timeline -> stageTime`` read is "a live timeline marker, not
the map's total duration", which is why the event schedule uses the constants
below rather than the live value.
"""
from __future__ import annotations


#: Fixed duration of each non-graveyard map stage, by raw ``stage_index``.
STAGE_DURATION_SECONDS: dict[int, float] = {0: 600.0, 1: 540.0, 2: 480.0}

#: The Graveyard carries no stage tier -- its raw ``stage_index`` stays at
#: whatever stage pointer the map reuses (2 in practice) -- so it is keyed
#: separately rather than through the table above.
GRAVEYARD_STAGE_DURATION_SECONDS = 960.0

#: How long after a stage's nominal end the ghosts have been out long enough to
#: lower the Difficulty cap.
GHOSTS_DELAY_SECONDS = 120.0

#: ``stage_index -> (base cap, cap once the ghosts have been out 2 minutes)``.
#: Stage 3 is absent on purpose: it has no Difficulty cap.
DIFFICULTY_CAP_BY_STAGE: dict[int, tuple[float, float]] = {
    0: (5.71, 4.95),
    1: (5.14, 4.38),
    2: (4.57, 3.81),
}

#: Flat, unlike Difficulty's staircase.
XP_GAIN_CAP = 10.0


def stage_duration_seconds(stage_index: int | None, *, is_graveyard: bool) -> float:
    """The active stage's fixed duration, or ``0.0`` where there is none."""
    if is_graveyard:
        return GRAVEYARD_STAGE_DURATION_SECONDS
    if stage_index is None:
        return 0.0
    return STAGE_DURATION_SECONDS.get(int(stage_index), 0.0)


def difficulty_cap(
    stage_index: int | None,
    stage_timer_seconds: float,
    *,
    is_graveyard: bool,
    cap_stage_duration: float,
) -> float | None:
    """The Difficulty cap in force, or ``None`` where the stage has none.

    ``cap_stage_duration`` is passed in rather than looked up here because the
    two callers disagree about where it comes from, and that disagreement is
    load-bearing: the overlay reads the live per-stage value it already holds,
    while the Recordings scrubber has only the recorded elapsed timer and so
    passes ``stage_duration_seconds``. Deciding it here would silently change
    the overlay.
    """
    if is_graveyard:
        base, after_ghosts = DIFFICULTY_CAP_BY_STAGE[0]
    else:
        capped = DIFFICULTY_CAP_BY_STAGE.get(int(stage_index)) if stage_index is not None else None
        if capped is None:
            return None
        base, after_ghosts = capped
    is_after_2m_ghosts = stage_timer_seconds >= (cap_stage_duration + GHOSTS_DELAY_SECONDS)
    return after_ghosts if is_after_2m_ghosts else base
