from __future__ import annotations

import src

import inspect
import unittest

from core.run_control import MapStateReader, RunControlError
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


class MapStateReaderTests(unittest.TestCase):
    """The protocol step 27d put where the concrete client type used to be.

    `core/run_control.py` annotated `wait_for_next_run`'s `client` argument
    against `infra.memory.GameDataClient` under `TYPE_CHECKING` -- the last
    `TYPE_CHECKING_DEBT` entry, a `core -> infra` reference the layer table
    forbids in either direction. `MapStateReader` replaced it.

    Nothing declares the conformance: `GameDataClient` satisfies it by shape,
    which is what keeps `infra` from importing `core.run_control` to say so.
    Structural conformance is also what breaks silently -- rename a method or
    change a return type on the client and every test here still passes while
    the annotation quietly describes something else.
    """

    def test_the_concrete_client_still_satisfies_the_protocol(self) -> None:
        from infra.memory.game_data_client import GameDataClient

        for name in ("get_map_generation_state", "get_map_stats"):
            with self.subTest(method=name):
                self.assertTrue(
                    callable(getattr(GameDataClient, name, None)),
                    f"GameDataClient no longer has a callable {name!r}. "
                    "core.run_control.MapStateReader was measured from this "
                    "class and the call site in gui_scanner; if the client "
                    "moved on, the protocol has to move with it.",
                )
                self.assertEqual(
                    inspect.signature(getattr(GameDataClient, name)),
                    inspect.signature(getattr(MapStateReader, name)),
                    f"{name} has drifted from the protocol's signature",
                )

    def test_the_protocol_is_narrower_than_the_client(self) -> None:
        """A protocol that is the client's whole API is the client renamed.

        The step 27 stop condition names exactly that as a reason to stop and
        report rather than ship, so the margin is asserted rather than
        described.
        """
        from infra.memory.game_data_client import GameDataClient

        def surface(cls) -> set:
            return {
                name
                for name in vars(cls)
                if not name.startswith("_") and callable(getattr(cls, name, None))
            }

        protocol = surface(MapStateReader)
        self.assertEqual({"get_map_generation_state", "get_map_stats"}, protocol)
        self.assertTrue(
            protocol < surface(GameDataClient),
            "MapStateReader must stay a strict subset of the client's surface",
        )


if __name__ == "__main__":
    unittest.main()