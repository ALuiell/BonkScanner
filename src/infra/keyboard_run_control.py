from __future__ import annotations

import time

from infra.keyboard_runtime import keyboard_operation, keyboard_send_scope

from core.run_control import (
    DynamicFloat,
    DynamicString,
    RunControlError,
    RunControlProvider,
    SleepFunction,
)

__all__ = [
    "DynamicFloat",
    "DynamicString",
    "KeyboardRunControlProvider",
    "RunControlError",
    "RunControlProvider",
    "SleepFunction",
]


class KeyboardRunControlProvider:
    def __init__(
        self,
        keyboard_module: object | None,
        *,
        reset_hotkey: DynamicString,
        reset_hold_duration: DynamicFloat,
        sleep: SleepFunction = time.sleep,
    ) -> None:
        self.keyboard = keyboard_module
        self.reset_hotkey = reset_hotkey
        self.reset_hold_duration = reset_hold_duration
        self._sleep = sleep

    def restart_run(self) -> None:
        if self.keyboard is None:
            raise RunControlError("Keyboard restart control is unavailable; install the 'keyboard' dependency.")

        reset_hotkey = self._reset_hotkey()
        parse = getattr(self.keyboard, "parse_hotkey", None)
        if callable(parse):
            parse(reset_hotkey)  # Validate before keyboard.send sets is_replaying.
        # Hold the shared send lock for the complete press/release transaction.
        with keyboard_send_scope(self.keyboard):
            try:
                keyboard_operation(self.keyboard, "press", reset_hotkey)
                self._sleep(self._reset_hold_duration())
            except BaseException as error:
                # press can fail after part of a combination was submitted.
                try:
                    keyboard_operation(self.keyboard, "release", reset_hotkey)
                except Exception as release_error:
                    error.add_note(f"Reset key release also failed: {release_error}")
                raise
            else:
                keyboard_operation(self.keyboard, "release", reset_hotkey)

    def _reset_hotkey(self) -> str:
        return str(self.reset_hotkey() if callable(self.reset_hotkey) else self.reset_hotkey)

    def _reset_hold_duration(self) -> float:
        return float(
            self.reset_hold_duration() if callable(self.reset_hold_duration) else self.reset_hold_duration
        )
