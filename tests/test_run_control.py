from __future__ import annotations

import unittest

from hook_loader import HookLoadError
from memory import MemoryReadError
from run_control import HookRunControlProvider, KeyboardRunControlProvider, RunControlError


class FakeHookLoader:
    def __init__(
        self,
        *,
        snapshot_ready: bool = True,
        restart_error: Exception | None = None,
        snapshot_error: Exception | None = None,
    ) -> None:
        self.snapshot_ready = snapshot_ready
        self.restart_error = restart_error
        self.snapshot_error = snapshot_error
        self.restart_calls = 0
        self.snapshot_timeouts: list[float] = []

    def request_restart_run(self) -> None:
        self.restart_calls += 1
        if self.restart_error is not None:
            raise self.restart_error

    def wait_for_snapshot_ready(self, *, timeout: float) -> bool:
        self.snapshot_timeouts.append(timeout)
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return self.snapshot_ready


class FakeGameDataClient:
    def __init__(self, *, wait_error: Exception | None = None) -> None:
        self.wait_error = wait_error
        self.wait_calls: list[dict[str, object]] = []

    def wait_for_map_ready(self, **kwargs: object) -> None:
        self.wait_calls.append(kwargs)
        if self.wait_error is not None:
            raise self.wait_error


class FakeKeyboard:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def press(self, key: str) -> None:
        self.events.append(("press", key))

    def release(self, key: str) -> None:
        self.events.append(("release", key))


class RunControlTests(unittest.TestCase):
    def test_hook_provider_delegates_restart_and_snapshot_wait(self) -> None:
        loader = FakeHookLoader(snapshot_ready=True)
        sleep_calls: list[float] = []
        provider = HookRunControlProvider(
            loader,
            map_load_delay=0.4,
            snapshot_timeout=2.5,
            sleep=sleep_calls.append,
        )

        provider.restart_run()
        provider.wait_for_next_run(client=FakeGameDataClient())

        self.assertEqual(loader.restart_calls, 1)
        self.assertEqual(loader.snapshot_timeouts, [2.5])
        self.assertEqual(sleep_calls, [])

    def test_hook_provider_raises_run_control_error_for_restart_failure(self) -> None:
        provider = HookRunControlProvider(
            FakeHookLoader(restart_error=HookLoadError("boom")),
            map_load_delay=0.4,
        )

        with self.assertRaisesRegex(RunControlError, "Native RestartRun request failed: boom"):
            provider.restart_run()

    def test_hook_provider_uses_memory_polling_when_snapshot_is_not_ready(self) -> None:
        loader = FakeHookLoader(snapshot_ready=False)
        client = FakeGameDataClient()
        provider = HookRunControlProvider(loader, map_load_delay=0.4)
        previous_state = object()
        previous_stats = {}

        provider.wait_for_next_run(
            client=client,
            previous_state=previous_state,
            previous_stats=previous_stats,
        )

        self.assertEqual(
            client.wait_calls,
            [
                {
                    "previous_state": previous_state,
                    "previous_stats": previous_stats,
                }
            ],
        )

    def test_hook_provider_falls_back_to_delay_after_snapshot_and_memory_errors(self) -> None:
        loader = FakeHookLoader(snapshot_error=HookLoadError("snapshot boom"))
        client = FakeGameDataClient(wait_error=MemoryReadError("memory boom"))
        sleep_calls: list[float] = []
        warnings: list[str] = []
        provider = HookRunControlProvider(
            loader,
            map_load_delay=0.4,
            sleep=sleep_calls.append,
        )

        provider.wait_for_next_run(client=client, warn=warnings.append)

        self.assertEqual(sleep_calls, [0.4])
        self.assertEqual(len(client.wait_calls), 1)
        self.assertEqual(
            warnings,
            [
                "Native snapshot-ready wait failed; using memory readiness polling: snapshot boom",
                "Map readiness polling failed; using fallback delay: memory boom",
            ],
        )

    def test_hook_provider_falls_back_to_delay_without_client(self) -> None:
        loader = FakeHookLoader(snapshot_ready=False)
        sleep_calls: list[float] = []
        provider = HookRunControlProvider(
            loader,
            map_load_delay=0.4,
            sleep=sleep_calls.append,
        )

        provider.wait_for_next_run(client=None)

        self.assertEqual(sleep_calls, [0.4])

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


if __name__ == "__main__":
    unittest.main()
