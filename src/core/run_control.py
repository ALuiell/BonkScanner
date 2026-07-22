"""Run-control port: the protocol every run-control provider satisfies.

The keyboard adapter that implements this protocol still lives in
``run_control.py``; moving it to ``infra/`` is the remaining half of step 10.

``wait_for_next_run`` used to annotate its ``client`` argument against
``infra.memory.GameDataClient``, imported under ``TYPE_CHECKING`` so there was
no runtime edge -- but the import still named ``infra`` from ``core``, which
the layering table forbids in either direction. Step 27d replaced it with
``MapStateReader`` below, the last ``TYPE_CHECKING_DEBT`` entry. ``core`` now
imports nothing outside itself at all, at runtime or under annotation.
"""

from __future__ import annotations

from typing import Callable, Protocol

from core.game_state import MapGenerationState, MapStat, StatValue


WarningHandler = Callable[[str], None]
SleepFunction = Callable[[float], None]
DynamicFloat = float | Callable[[], float]
DynamicString = str | Callable[[], str]
AbortCondition = Callable[[], bool]


class MapStateReader(Protocol):
    """What a run-control provider may ask the game while it waits for a run.

    Two methods, and the call site rather than the client is what picked them:
    ``gui_scanner`` reads ``get_map_generation_state()`` and ``get_map_stats()``
    immediately before calling ``wait_for_next_run``, and passes both results
    alongside the client as ``previous_state`` and ``previous_stats``. Sampling
    the same two again and comparing is the only thing the ``client`` argument
    is for, so that is the whole surface. Both return types are ``core``'s
    already.

    Deliberately *not* the client's API. ``GameDataClient`` also offers
    ``close``, ``get_runtime_activity_state``, ``get_runtime_game_state``,
    ``wait_for_map_ready`` and ``get_map_activity_values``; a protocol wide
    enough to cover those would be the concrete class with a different name,
    which the step 27 stop condition names as a reason to stop rather than
    ship. ``core/settings.py`` is the precedent -- a narrow protocol ``core``
    owns and a lower layer satisfies structurally, with no import either way.

    Nothing declares that it implements this. ``GameDataClient`` satisfies it
    by shape, and ``test_run_control.py`` checks that it still does, because
    structural conformance breaks silently when a signature drifts.
    """

    def get_map_generation_state(self) -> MapGenerationState:
        ...

    def get_map_stats(self) -> dict[MapStat, StatValue]:
        ...


class RunControlError(Exception):
    """Raised when a run-control provider cannot restart the run."""


class RunControlProvider(Protocol):
    def restart_run(self) -> None:
        ...

    def wait_for_next_run(
        self,
        *,
        client: MapStateReader | None = None,
        previous_state: MapGenerationState | None = None,
        previous_stats: dict[MapStat, StatValue] | None = None,
        warn: WarningHandler | None = None,
        abort_condition: AbortCondition | None = None,
    ) -> None:
        ...
