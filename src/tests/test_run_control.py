from __future__ import annotations

import src

import unittest

from core.run_control import RunControlError
from infra.keyboard_run_control import KeyboardRunControlProvider


class FakeKeyboard:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def press(self, key: str) -> None:
        self.events.append(("press", key))

    def release(self, key: str) -> None:
        self.events.append(("release", key))


class RunControlTests(unittest.TestCase):
    def test_keyboard_provider_holds_and_releases_reset_key(self) -> None:
        keyboard = FakeKeyboard()
        sleep_calls: list[float] = []
        provider = KeyboardRunControlProvider(
            keyboard,
            reset_hotkey="r",
            reset_hold_duration=0.3,
            sleep=sleep_calls.append,
        )

        provider.restart_run()

        self.assertEqual(keyboard.events, [("press", "r"), ("release", "r")])
        self.assertEqual(sleep_calls, [0.3])

    def test_keyboard_provider_reads_current_settings_from_callables(self) -> None:
        keyboard = FakeKeyboard()
        settings = {
            "hotkey": "r",
            "hold": 0.3,
        }
        sleep_calls: list[float] = []
        provider = KeyboardRunControlProvider(
            keyboard,
            reset_hotkey=lambda: settings["hotkey"],
            reset_hold_duration=lambda: settings["hold"],
            sleep=sleep_calls.append,
        )

        settings.update(hotkey="f5", hold=0.6)
        provider.restart_run()

        self.assertEqual(keyboard.events, [("press", "f5"), ("release", "f5")])
        self.assertEqual(sleep_calls, [0.6])

    def test_keyboard_provider_releases_reset_key_when_sleep_fails(self) -> None:
        keyboard = FakeKeyboard()

        def broken_sleep(_duration: float) -> None:
            raise RuntimeError("sleep boom")

        provider = KeyboardRunControlProvider(
            keyboard,
            reset_hotkey="r",
            reset_hold_duration=0.3,
            sleep=broken_sleep,
        )

        with self.assertRaisesRegex(RuntimeError, "sleep boom"):
            provider.restart_run()

        self.assertEqual(keyboard.events, [("press", "r"), ("release", "r")])

    def test_keyboard_provider_without_keyboard_module_raises_clear_error(self) -> None:
        provider = KeyboardRunControlProvider(
            None,
            reset_hotkey="r",
            reset_hold_duration=0.3,
        )

        with self.assertRaisesRegex(RunControlError, "Keyboard restart control is unavailable"):
            provider.restart_run()

if __name__ == "__main__":
    unittest.main()
