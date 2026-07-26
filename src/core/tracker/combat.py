"""Kill/KPS tracking: pure functions over ``_CombatState``.

Split out of ``live_run_tracker.py`` in step 13.  Nothing here acquires a
lock; ``LiveRunTracker`` calls in while already holding its single ``RLock``.

Both KPS notions here are windowed rates over the same sample history and
differ only in window length and in when they are emitted:

``average_kps_for_window`` is computed on demand for the 3 s / 60 s / 300 s
readouts, and takes the *oldest* sample inside its window.  ``track_ui_kps``
is the instant readout: it publishes on each crossing of an integer
``run_timer`` second -- the rhythm of the game's own on-screen counter -- over
a fixed ~1 game-second window, and so takes the *newest* sample at or before
the cutoff.  Publication rhythm and measurement window are separate
decisions; conflating them collapses the window to the poll interval.

Application wall-clock time never enters either formula.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

UI_KPS_WINDOW_SECONDS = 1.0
"""Game-time length of the instant-KPS measurement window."""

UI_KPS_BASELINE_TOLERANCE_SECONDS = 0.05
"""How much later than the window mark a sample may sit and still be the baseline.

Not slack: without it a poll landing milliseconds short of the mark is
rejected and the next-oldest sample stretches the window to ~1.5 s at 500 ms
polling.  It must also stay below half of the tightest possible spacing --
``FAST_TRACKER_INTERVAL_MS`` floors at 100 ms -- or it *shrinks* the window
instead, which is what a 0.1 s tolerance did at 100 ms polling.
"""


@dataclass
class _CombatState:
    recent_kills_history: deque[tuple[float, int]] = field(default_factory=deque)
    ui_kps_second: int | None = None
    ui_kps_value: int | None = None


def reset_ui_kps(state: _CombatState) -> None:
    state.ui_kps_second = None
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
    """Publish the instant KPS if this sample crossed an integer game second.

    Called from ``track_kills`` *after* the sample has been appended, so the
    window is already in ``recent_kills_history`` and no private baseline pair
    is kept -- only the cursor naming the last second published for.

    A paused run never reaches here: ``track_kills`` collapses the repeated
    sample and returns, so the cursor does not advance and the last published
    value stays readable.
    """
    game_time_seconds = float(game_time_seconds)
    current_second = math.floor(game_time_seconds)

    last_second = state.ui_kps_second
    if last_second is None:
        # First sample after a reset: arm the cursor, publish nothing. The
        # window is not filled yet either.
        state.ui_kps_second = current_second
        return
    if current_second <= last_second:
        return

    state.ui_kps_second = current_second

    cutoff = game_time_seconds - UI_KPS_WINDOW_SECONDS + UI_KPS_BASELINE_TOLERANCE_SECONDS
    baseline: tuple[float, int] | None = None
    for sample in reversed(state.recent_kills_history):
        if sample[0] <= cutoff:
            baseline = sample
            break

    if baseline is None:
        # History shorter than the window -- start of a run or of a reattach.
        # KPS stays unavailable rather than being measured over a stub.
        return

    baseline_time, baseline_kills = baseline
    time_delta = game_time_seconds - baseline_time
    if time_delta <= 0:
        return

    state.ui_kps_value = max(0, int(round((int(current_kills) - baseline_kills) / time_delta)))


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
