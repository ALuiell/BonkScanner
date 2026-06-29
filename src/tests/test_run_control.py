from __future__ import annotations

import src

import unittest

from run_control import KeyboardRunControlProvider, RunControlError


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
            map_load_delay=0.4,
            sleep=sleep_calls.append,
        )

        provider.restart_run()
        provider.wait_for_next_run()

        self.assertEqual(keyboard.events, [("press", "r"), ("release", "r")])
        self.assertEqual(sleep_calls, [0.3, 0.4])

    def test_keyboard_provider_reads_current_settings_from_callables(self) -> None:
        keyboard = FakeKeyboard()
        settings = {
            "hotkey": "r",
            "hold": 0.3,
            "delay": 0.4,
        }
        sleep_calls: list[float] = []
        provider = KeyboardRunControlProvider(
            keyboard,
            reset_hotkey=lambda: settings["hotkey"],
            reset_hold_duration=lambda: settings["hold"],
            map_load_delay=lambda: settings["delay"],
            sleep=sleep_calls.append,
        )

        settings.update(hotkey="f5", hold=0.6, delay=0.7)
        provider.restart_run()
        provider.wait_for_next_run()

        self.assertEqual(keyboard.events, [("press", "f5"), ("release", "f5")])
        self.assertEqual(sleep_calls, [0.6, 0.7])

    def test_keyboard_provider_releases_reset_key_when_sleep_fails(self) -> None:
        keyboard = FakeKeyboard()

        def broken_sleep(_duration: float) -> None:
            raise RuntimeError("sleep boom")

        provider = KeyboardRunControlProvider(
            keyboard,
            reset_hotkey="r",
            reset_hold_duration=0.3,
            map_load_delay=0.4,
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
            map_load_delay=0.4,
        )

        with self.assertRaisesRegex(RunControlError, "Keyboard restart control is unavailable"):
            provider.restart_run()

    def test_keyboard_provider_wait_can_be_aborted(self) -> None:
        provider = KeyboardRunControlProvider(
            FakeKeyboard(),
            reset_hotkey="r",
            reset_hold_duration=0.3,
            map_load_delay=0.4,
        )

        with self.assertRaises(InterruptedError):
            provider.wait_for_next_run(abort_condition=lambda: True)


if __name__ == "__main__":
    unittest.main()