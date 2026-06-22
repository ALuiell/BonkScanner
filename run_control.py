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
        abort_condition: AbortCondition | None = None,
    ) -> None:
        snapshot_ready = False
        try:
            if abort_condition is None:
                snapshot_ready = self.loader.wait_for_snapshot_ready(timeout=self.snapshot_timeout)
            else:
                deadline = time.monotonic() + self.snapshot_timeout
                while True:
                    self._raise_if_aborted(abort_condition)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    snapshot_ready = self.loader.wait_for_snapshot_ready(timeout=min(0.2, remaining))
                    if snapshot_ready:
                        break
        except HookLoadError as exc:
            self._warn(warn, f"Native snapshot-ready wait failed; using memory readiness polling: {exc}")

        if client is not None and not snapshot_ready:
            try:
                client.wait_for_map_ready(
                    previous_state=previous_state,
                    previous_stats=previous_stats,
                    abort_condition=abort_condition,
                )
            except InterruptedError:
                raise
            except (TimeoutError, MemoryReadError) as exc:
                self._warn(warn, f"Map readiness polling failed; using fallback delay: {exc}")
                self._sleep_abortable(self._map_load_delay(), abort_condition)
        elif client is None:
            self._sleep_abortable(self._map_load_delay(), abort_condition)

    @staticmethod
    def _warn(warn: WarningHandler | None, message: str) -> None:
        if warn is not None:
            warn(message)

    def _map_load_delay(self) -> float:
        return float(self.map_load_delay() if callable(self.map_load_delay) else self.map_load_delay)

    def _sleep_abortable(
        self,
        duration: float,
        abort_condition: AbortCondition | None,
    ) -> None:
        if abort_condition is None:
            self._sleep(duration)
            return
        deadline = time.monotonic() + max(0.0, float(duration))
        while True:
            self._raise_if_aborted(abort_condition)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._sleep(min(0.05, remaining))

    @staticmethod
    def _raise_if_aborted(abort_condition: AbortCondition | None) -> None:
        if abort_condition is not None and abort_condition():
            raise InterruptedError("Run-control wait aborted.")


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
