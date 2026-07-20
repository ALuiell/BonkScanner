"""Builder for the run-lifecycle service.

The same contract as `tests/support/player_stats.py`: call the component's
**real** constructor with explicit fakes, rather than borrowing
`MegabonkApp`'s MRO through `object.__new__`. Adding a dependency to
`RunLifecycle` breaks every call site here loudly, where `object.__new__`
absorbs it silently and surfaces it as an `AttributeError` at the first read,
in whichever test happens to reach it first.

Before step 20 the tests these replace poked three names on the shared `self`
-- `_core_runtime_game_state`, `_core_runtime_game_state_checked_at` and
`_player_stats_completed_run` -- and called the lifecycle methods unbound off
`MegabonkApp`. Both are gone: the state has one owner now, and these helpers
talk to that owner directly.
"""

from __future__ import annotations

from typing import Any, Callable

from app.run_lifecycle import RunLifecycle
from core.game_state import RuntimeGameState


def build_run_lifecycle(
    *,
    activity_states: Any = None,
    game_states: Any = None,
    live_run_tracker: Any = None,
    clock: Callable[[], float] | None = None,
    cached_state: RuntimeGameState | None = None,
    checked_at: float | None = None,
    completed_run: bool = False,
) -> RunLifecycle:
    """A real `RunLifecycle` with the two memory reads faked.

    `activity_states` / `game_states` accept either a callable (used as the
    reader directly) or an iterable of states consumed one per read, with
    `None` returned once exhausted -- which is what a failed read looks like to
    this service, and the branch that turns it into `UNKNOWN`.
    """
    lifecycle = RunLifecycle(
        read_activity_state=_reader(activity_states),
        read_game_state=_reader(game_states),
        live_run_tracker=(
            live_run_tracker
            if callable(live_run_tracker)
            else (lambda: live_run_tracker)
        ),
        **({"clock": clock} if clock is not None else {}),
    )
    if cached_state is not None or checked_at is not None:
        lifecycle.seed_cache(cached_state, checked_at)
    if completed_run:
        lifecycle.set_completed(True)
    return lifecycle


def _reader(source) -> Callable[[], Any]:
    if source is None:
        return lambda: None
    if callable(source):
        return source
    remaining = iter(source)

    def read():
        try:
            return next(remaining)
        except StopIteration:
            return None

    return read


def install_run_lifecycle(app, **overrides) -> RunLifecycle:
    """Give an app double a lifecycle service, the way production would.

    `app.run_lifecycle(...)` resolves through the coordinator when there is
    one and `__dict__` otherwise; an `object.__new__` double has no
    coordinator, so this is the branch it takes. Setting the attribute is
    exactly what the resolver's cache does on first use.
    """
    lifecycle = build_run_lifecycle(**overrides)
    app._run_lifecycle = lifecycle
    return lifecycle
