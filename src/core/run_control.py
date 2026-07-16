"""Run-control port: the protocol every run-control provider satisfies.

The keyboard adapter that implements this protocol still lives in
``run_control.py``; moving it to ``infra/`` is the remaining half of step 10.

``GameDataClient`` is a type-only reference, imported under ``TYPE_CHECKING``
so there is no runtime core -> infra edge. Now that step 10 has moved the
client, that import names ``infra`` from ``core`` outright -- forbidden by the
layering table even though nothing is imported at runtime. A port should be
defined over a Protocol rather than a concrete client, which would remove the
reference entirely; that is a design change, not a move, so it is deliberately
left for the import-direction checker in the Definition of Done to force.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Protocol

from core.game_state import MapGenerationState, MapStat, StatValue

if TYPE_CHECKING:
    from infra.memory.game_data_client import GameDataClient


WarningHandler = Callable[[str], None]
SleepFunction = Callable[[float], None]
DynamicFloat = float | Callable[[], float]
DynamicString = str | Callable[[], str]
AbortCondition = Callable[[], bool]


class RunControlError(Exception):
    """Raised when a run-control provider cannot restart the run."""


class RunControlProvider(Protocol):
    def restart_run(self) -> None:
        ...

    def wait_for_next_run(
        self,
        *,
        client: GameDataClient | None = None,
        previous_state: MapGenerationState | None = None,
        previous_stats: dict[MapStat, StatValue] | None = None,
        warn: WarningHandler | None = None,
        abort_condition: AbortCondition | None = None,
    ) -> None:
        ...
