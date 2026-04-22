from __future__ import annotations

import time
from typing import Callable, Protocol

from game_data import GameDataClient, MapGenerationState, MapStat, StatValue
from hook_loader import HookLoadError, NativeHookLoader
from memory import MemoryReadError


WarningHandler = Callable[[str], None]
SleepFunction = Callable[[float], None]
DynamicFloat = float | Callable[[], float]
DynamicString = str | Callable[[], str]


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
    ) -> None:
        ...


class HookRunControlProvider:
    def __init__(
        self,
        loader: NativeHookLoader,
        *,
        map_load_delay: DynamicFloat,
        snapshot_timeout: float = 10.0,
        sleep: SleepFunction = time.sleep,
    ) -> None:
        self.loader = loader
        self.map_load_delay = map_load_delay
        self.snapshot_timeout = snapshot_timeout
        self._sleep = sleep

    def restart_run(self) -> None:
        try:
            self.loader.request_restart_run()
        except HookLoadError as exc:
            raise RunControlError(f"Native RestartRun request failed: {exc}") from exc

    def wait_for_next_run(
        self,
        *,
        client: GameDataClient | None = None,
        previous_state: MapGenerationState | None = None,
        previous_stats: dict[MapStat, StatValue] | None = None,
        warn: WarningHandler | None = None,
    ) -> None:
        snapshot_ready = False
        try:
            snapshot_ready = self.loader.wait_for_snapshot_ready(timeout=self.snapshot_timeout)
        except HookLoadError as exc:
            self._warn(warn, f"Native snapshot-ready wait failed; using memory readiness polling: {exc}")

        if client is not None and not snapshot_ready:
            try:
                client.wait_for_map_ready(
                    previous_state=previous_state,
                    previous_stats=previous_stats,
                )
            except (TimeoutError, MemoryReadError) as exc:
                self._warn(warn, f"Map readiness polling failed; using fallback delay: {exc}")
                self._sleep(self._map_load_delay())
        elif client is None:
            self._sleep(self._map_load_delay())

    @staticmethod
    def _warn(warn: WarningHandler | None, message: str) -> None:
        if warn is not None:
            warn(message)

    def _map_load_delay(self) -> float:
        return float(self.map_load_delay() if callable(self.map_load_delay) else self.map_load_delay)


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
    ) -> None:
        del client, previous_state, previous_stats, warn
        self._sleep(self._map_load_delay())

    def _reset_hotkey(self) -> str:
        return str(self.reset_hotkey() if callable(self.reset_hotkey) else self.reset_hotkey)

    def _reset_hold_duration(self) -> float:
        return float(
            self.reset_hold_duration() if callable(self.reset_hold_duration) else self.reset_hold_duration
        )

    def _map_load_delay(self) -> float:
        return float(self.map_load_delay() if callable(self.map_load_delay) else self.map_load_delay)
