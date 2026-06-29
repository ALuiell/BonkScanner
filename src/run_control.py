from __future__ import annotations

import time
from typing import Callable, Protocol

from game_data import GameDataClient, MapGenerationState, MapStat, StatValue


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


class KeyboardRunControlProvider:
    def __init__(
        self,
        keyboard_module: object | None,
        *,
        reset_hotkey: DynamicString,
        reset_hold_duration: DynamicFloat,
        map_load_delay: DynamicFloat,
        sleep: SleepFunction = time.sleep,
    ) -> None:
        self.keyboard = keyboard_module
        self.reset_hotkey = reset_hotkey
        self.reset_hold_duration = reset_hold_duration
        self.map_load_delay = map_load_delay
        self._sleep = sleep

    def restart_run(self) -> None:
        if self.keyboard is None:
            raise RunControlError("Keyboard restart control is unavailable; install the 'keyboard' dependency.")

        reset_hotkey = self._reset_hotkey()
        self.keyboard.press(reset_hotkey)
        try:
            self._sleep(self._reset_hold_duration())
        finally:
            self.keyboard.release(reset_hotkey)

    def wait_for_next_run(
        self,
        *,
        client: GameDataClient | None = None,
        previous_state: MapGenerationState | None = None,
        previous_stats: dict[MapStat, StatValue] | None = None,
        warn: WarningHandler | None = None,
        abort_condition: AbortCondition | None = None,
    ) -> None:
        del client, previous_state, previous_stats, warn
        duration = self._map_load_delay()
        if abort_condition is None:
            self._sleep(duration)
            return
        deadline = time.monotonic() + max(0.0, float(duration))
        while True:
            if abort_condition():
                raise InterruptedError("Run-control wait aborted.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._sleep(min(0.05, remaining))

    def _reset_hotkey(self) -> str:
        return str(self.reset_hotkey() if callable(self.reset_hotkey) else self.reset_hotkey)

    def _reset_hold_duration(self) -> float:
        return float(
            self.reset_hold_duration() if callable(self.reset_hold_duration) else self.reset_hold_duration
        )

    def _map_load_delay(self) -> float:
        return float(self.map_load_delay() if callable(self.map_load_delay) else self.map_load_delay)