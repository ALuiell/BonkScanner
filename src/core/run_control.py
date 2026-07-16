"""Run-control port: the protocol every run-control provider satisfies.

The keyboard adapter that implements this protocol stays in ``run_control.py``
until step 10 moves it to ``infra/``. ``GameDataClient`` is a type-only
reference (it lives in ``game_data.py``, not yet in ``infra/``) so it is
imported under ``TYPE_CHECKING`` to avoid a runtime core -> infra edge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Protocol

from core.game_state import MapGenerationState, MapStat, StatValue

if TYPE_CHECKING:
    from game_data import GameDataClient


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
