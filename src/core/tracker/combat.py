"""Kill/KPS tracking: pure functions over ``_CombatState``.

Split out of ``live_run_tracker.py`` in step 13.  Nothing here acquires a
lock; ``LiveRunTracker`` calls in while already holding its single ``RLock``.

Two KPS notions live here and they are not interchangeable:

``average_kps_for_window`` is a windowed rate over the sample history, used
for the 3 s / 60 s / 300 s readouts.  ``track_ui_kps`` reproduces the game's
own on-screen counter, which only accepts a baseline pair roughly one second
apart -- hence the 0.9/1.2 s gate.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class _CombatState:
    recent_kills_history: deque[tuple[float, int]] = field(default_factory=deque)
    ui_kps_baseline: tuple[float, int] | None = None
    ui_kps_value: int | None = None


def reset_ui_kps(state: _CombatState) -> None:
    state.ui_kps_baseline = None
    state.ui_kps_value = None


def reset(state: _CombatState) -> None:
    """Drop the whole sample history -- new run, or the game went away."""
    state.recent_kills_history.clear()
    reset_ui_kps(state)


def track_kills(
    state: _CombatState,
    game_time_seconds: float,
    current_kills: int,
) -> None:
    """Record one (time, kills) sample.

    The caller has already rejected ``None`` inputs and marked the ``combat``
    feature fresh.  Every path through this function invalidates the stage
    summary cache, so the caller clears it unconditionally afterwards rather
    than being told which branch ran.
    """
    if state.recent_kills_history:
        last_time, last_kills = state.recent_kills_history[-1]
        if current_kills < last_kills or game_time_seconds < last_time:
            state.recent_kills_history.clear()
            reset_ui_kps(state)
        elif game_time_seconds == last_time:
            # Prevent deque bloat when the game is paused (time is frozen)
            state.recent_kills_history[-1] = (game_time_seconds, max(last_kills, current_kills))
            return

    state.recent_kills_history.append((game_time_seconds, current_kills))

    while state.recent_kills_history and state.recent_kills_history[0][0] < game_time_seconds - 300.0:
        state.recent_kills_history.popleft()

    track_ui_kps(state, game_time_seconds, current_kills)


def track_ui_kps(state: _CombatState, game_time_seconds: float, current_kills: int) -> None:
    baseline = state.ui_kps_baseline
    current_sample = (float(game_time_seconds), int(current_kills))
    if baseline is None:
        state.ui_kps_baseline = current_sample
        return

    baseline_time, baseline_kills = baseline
    time_delta = float(game_time_seconds) - baseline_time
    if time_delta <= 0:
        return
    if time_delta < 0.9:
        return
    if time_delta > 1.2:
        state.ui_kps_baseline = current_sample
        return

    state.ui_kps_value = max(0, int(current_kills) - baseline_kills)
    state.ui_kps_baseline = current_sample


def average_kps_for_window(state: _CombatState, window_seconds: float) -> int | None:
    if len(state.recent_kills_history) < 2:
        return None

    newest_time, newest_kills = state.recent_kills_history[-1]
    cutoff = newest_time - float(window_seconds)
    oldest_time, oldest_kills = state.recent_kills_history[0]
    for sample_time, sample_kills in state.recent_kills_history:
        if sample_time >= cutoff:
            oldest_time, oldest_kills = sample_time, sample_kills
            break

    time_delta = newest_time - oldest_time
    if time_delta <= 0:
        return None

    kills_delta = newest_kills - oldest_kills
    return int(round(kills_delta / time_delta))


def current_run_avg_kps(state: _CombatState) -> int | None:
    if not state.recent_kills_history:
        return None

    newest_time, newest_kills = state.recent_kills_history[-1]
    if newest_time <= 0:
        return None

    return int(round(newest_kills / newest_time))
