"""Run-lifecycle state: is a run active, has it finished, and what mode is the
game in right now.

**Why this module exists at all.** Step 20 set out to convert five app-side
mixins into services and found ``PlayerStatsRefreshMixin`` and
``VodCaptureMixin`` in a two-way cycle: Refresh calls VodCapture's
``_is_player_stats_recording_armed`` and ``_maybe_auto_start_player_stats_recording``,
while VodCapture calls Refresh's ``_runtime_game_state_or_unknown``,
``_runtime_state_for_refresh`` and ``refresh_live_player_stats_now``. Neither
gets an honest constructor while that holds.

The step brief proposed inverting the VodCapture->Refresh direction through a
port, describing it as "three reads of state and one *repaint now*". Measurement
(``tools/step20_metrics.py --clusters``) says the three reads are not Refresh's
state to lend:

===================================  ======================  ==================
name                                 reads                   writes
===================================  ======================  ==================
``_core_runtime_game_state``         refresh, **tasks**      refresh
``_player_stats_completed_run``      refresh, **tasks**      **refresh, vod**
===================================  ======================  ==================

``_player_stats_completed_run`` is written by *both* sides of the supposed cycle
and read by a third module. A port that let VodCapture borrow this from Refresh
would name Refresh the owner of state VodCapture itself writes -- the same error
step 19 recorded for ``PlayerStatsView``, "a port named after its caller rather
than after its implementer".

So the cycle was never two services depending on each other. It was **three
services sharing one unnamed fourth**, and this is that fourth. Extracting it
removes two of the three VodCapture->Refresh edges by construction; the
remaining one, ``refresh_live_player_stats_now``, is a genuine one-operation
command and becomes a real port.

**What is deliberately preserved.**

* The two cache windows use **different comparisons**, and that is not a typo.
  ``refresh()`` re-reads at ``>=`` one interval (``<`` to keep the cache);
  ``state_for_refresh()`` keeps the cache at exactly one interval (``<=``).
  Both are inherited verbatim; the trace drives the exact boundary.
* ``refresh()`` marks the tracker's run completed **only on the transition**
  ("and not already completed"), while ``vod_capture`` marks it on every
  GAME_OVER sync. The asymmetry is inherited, not fixed: making them symmetric
  is a behaviour change and this commit is not one.
* **Pause is an active run.** ``RuntimeGameState.is_active_run`` includes
  ``PAUSED_IN_GAME``, so ``is_active_run()`` is true while paused and the
  full-snapshot and expected-chest demands survive a pause. Capture is gated
  separately and strictly on ``IN_GAME`` -- see ``app/vod_capture.py``. Do not
  'fix' these into symmetry.

Qt-free and client-free: the two memory reads arrive as callables, so this is
constructible in a test with two lambdas and no ``MegabonkApp``.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from core.game_state import RuntimeGameMode, RuntimeGameState

# The cadence at which the core run-lifecycle probe re-reads runtime state.
# Lives here now: this is the only module that applies it, and
# ``app/player_stats_refresh.py`` re-exports it for the callers that still name
# it there. Matches ``RECORDING_LIFECYCLE_REFRESH_MS`` in ``app/refresh_tasks.py``,
# whose task reads the state this caches.
CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS = 1.0


class RunLifecycle:
    """The run's lifecycle state, with exactly one owner.

    Three fields, previously three names on the shared ``self``:

    ``_core_runtime_game_state``          -> ``_cached_state``
    ``_core_runtime_game_state_checked_at`` -> ``_checked_at``
    ``_player_stats_completed_run``       -> ``_completed_run``
    """

    def __init__(
        self,
        *,
        read_activity_state: Callable[[], Any],
        read_game_state: Callable[[], Any],
        live_run_tracker: Callable[[], Any],
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._read_activity_state = read_activity_state
        self._read_game_state = read_game_state
        self._live_run_tracker = live_run_tracker
        self._clock = clock

        self._cached_state: RuntimeGameState | None = None
        self._checked_at: float | None = None
        self._completed_run: bool = False

    def _now(self) -> float:
        """The current monotonic time.

        ``None`` rather than ``clock=time.monotonic`` as the default, and the
        lookup deliberately happens **here** rather than at construction. A
        default argument binds ``time.monotonic`` once, at import; the code
        this replaces read ``time.monotonic`` as a module attribute on every
        call. Capturing it changes what the cache windows below measure
        against, and three tests caught it the moment it was written -- a
        shorter path than the trace, but the trace patches the same name and
        would have reported it too.
        """
        if self._clock is not None:
            return self._clock()
        return time.monotonic()

    # -- completed-run flag ------------------------------------------------

    @property
    def completed_run(self) -> bool:
        return bool(self._completed_run)

    def set_completed(self, value: bool) -> None:
        self._completed_run = bool(value)

    def mark_completed_on_tracker(self) -> None:
        """Tell the tracker the run is over, if it wants to know.

        Behind ``getattr`` + ``callable`` because not every tracker double in
        the suite has this method, and losing the guard turns an optional
        collaborator into a crash on the first GAME_OVER.

        Deliberately **not** guarded on ``completed_run`` here: ``refresh()``
        applies that guard and ``vod_capture`` does not, and this method is
        shared by both. Putting the guard inside would silently change the
        vod_capture path.
        """
        tracker = self._live_run_tracker()
        mark_completed = getattr(tracker, "mark_run_completed", None)
        if callable(mark_completed):
            mark_completed()

    # -- cached lifecycle state -------------------------------------------

    def seed_cache(self, state: RuntimeGameState | None, checked_at: float | None) -> None:
        """Set the cache directly, without a read.

        Exists for tests and traces, which previously assigned
        ``_core_runtime_game_state`` on the shared ``self``. Not used in
        production.
        """
        self._cached_state = state
        self._checked_at = checked_at

    def is_active_run(self) -> bool:
        """Was ``RefreshTasksMixin._core_run_active``.

        Reads the *cached* state and never triggers a read, exactly as before:
        it is called from demand predicates, which must be cheap enough to run
        on every fast tick.
        """
        state = self._cached_state
        return bool(state is not None and state.is_active_run)

    def refresh(self) -> RuntimeGameState:
        """Was ``PlayerStatsRefreshMixin._refresh_core_run_lifecycle_state``.

        The once-a-second probe that drives everything else. Note ``<``: a
        sample exactly one interval old is re-read.
        """
        now = self._now()
        last_checked_at = self._checked_at
        cached_state = self._cached_state
        if (
            cached_state is not None
            and last_checked_at is not None
            and now - last_checked_at < CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS
        ):
            return cached_state

        state = self._read_activity_state()
        if state is None:
            state = RuntimeGameState(mode=RuntimeGameMode.UNKNOWN)
        self._cached_state = state
        self._checked_at = now

        if state.is_active_run:
            self._completed_run = False
        elif state.mode is RuntimeGameMode.GAME_OVER and not self.completed_run:
            self._completed_run = True
            self.mark_completed_on_tracker()
        return state

    def state_or_unknown(self) -> RuntimeGameState:
        """Was ``PlayerStatsRefreshMixin._runtime_game_state_or_unknown``.

        An *uncached* read. A failed read becomes UNKNOWN rather than None,
        because every caller branches on ``.mode`` and would raise on None.
        """
        state = self._read_game_state()
        if state is None:
            return RuntimeGameState(mode=RuntimeGameMode.UNKNOWN)
        return state

    def state_for_refresh(self) -> RuntimeGameState:
        """Was ``PlayerStatsRefreshMixin._runtime_state_for_refresh``.

        Reuses the probe cache when it is fresh, falling back to an uncached
        read otherwise. Note ``<=``, which differs from ``refresh()``'s ``<``
        -- inherited verbatim.

        This is the reader the recording lifecycle uses, and the comment it
        replaces explains why: at the recording task's 1 s cadence an uncached
        ``get_runtime_game_state()`` would run ten times a second for a mode
        the cheaper cached reader computes identically.
        """
        cached_state = self._cached_state
        checked_at = self._checked_at
        if cached_state is not None and checked_at is not None:
            if self._now() - checked_at <= CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS:
                return cached_state
        return self.state_or_unknown()


def run_lifecycle(owner) -> RunLifecycle:
    """Resolve the owner's ``RunLifecycle``, building it on first use.

    The same shape as ``ensure_refresh_coordinator`` in ``app/refresh_tasks.py``
    and for the same reason: the service's dependencies are the owner's memory
    readers, so ``AppCoordinator`` cannot construct it in its own ``__init__``.
    The coordinator caches it when there is one; an app double built with
    ``object.__new__`` has none and keeps it in ``__dict__``.

    Still an owner-taking resolver, not yet a constructor argument. The later
    step-20 commits that convert ``vod_capture``, ``player_stats_refresh`` and
    ``refresh_tasks`` into constructed services take this as an argument, and
    this function loses those callers then.

    ``__dict__``, not ``getattr``: ``MegabonkApp.__getattr__`` forwards unknown
    names to its ``window``, so a ``getattr`` would consult the widget before
    deciding there is no coordinator.
    """
    coordinator = owner.__dict__.get("coordinator")
    if coordinator is not None:
        existing = getattr(coordinator, "run_lifecycle", None)
        if existing is not None:
            return existing

    existing = owner.__dict__.get("_run_lifecycle")
    if existing is not None:
        return existing

    # Bound through lambdas rather than by grabbing the bound methods here.
    # `self._read_..._safe()` resolved late, on every call; capturing the bound
    # method at construction would resolve it once and require **both** readers
    # to exist the moment the service is first touched, even for an owner that
    # only ever calls one. The suite has such owners, and one of them found
    # this within a minute of it being written.
    lifecycle = RunLifecycle(
        read_activity_state=lambda: owner._read_player_stats_runtime_activity_state_safe(),
        read_game_state=lambda: owner._read_player_stats_runtime_game_state_safe(),
        live_run_tracker=lambda: owner.live_run_tracker,
    )
    if coordinator is not None:
        coordinator.run_lifecycle = lifecycle
    else:
        owner.__dict__["_run_lifecycle"] = lifecycle
    return lifecycle
