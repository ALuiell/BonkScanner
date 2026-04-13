from __future__ import annotations

import io
import sys
import types
import unittest
from contextlib import redirect_stdout

sys.modules.setdefault(
    "keyboard",
    types.SimpleNamespace(
        add_hotkey=lambda *args, **kwargs: None,
        press=lambda *args, **kwargs: None,
        release=lambda *args, **kwargs: None,
        press_and_release=lambda *args, **kwargs: None,
    ),
)

import main
from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError

from main import confirm_template_match, reset_client_after_disconnect, run_scanner, toggle_script, wait_for_game_client


class MainFlowTests(unittest.TestCase):
    def tearDown(self) -> None:
        main.is_running = False
        main.return_to_menu = False
        main.is_ready_to_start = False
        main.active_templates = []

    def setUp(self) -> None:
        self.templates = [
            {"id": 1, "name": "GOOD", "color": "GREEN", "sm_total": 8, "micro": 2, "boss": 1},
            {"id": 2, "name": "PERFECT+", "color": "LIGHTRED_EX", "sm_total": 9, "micro": 2, "boss": 3},
        ]
        self.active_templates = ["GOOD", "PERFECT+"]

    def test_confirm_template_match_returns_none_when_initial_stats_do_not_match(self) -> None:
        initial_stats = {
            "Boss Curses": 0,
            "Challenges": 0,
            "Charge Shrines": 0,
            "Chests": 0,
            "Greed Shrines": 0,
            "Magnet Shrines": 0,
            "Microwaves": 1,
            "Moais": 3,
            "Pots": 0,
            "Shady Guy": 4,
        }
        confirmed_stats = {
            **initial_stats,
            "Microwaves": 2,
            "Boss Curses": 3,
        }

        self.assertIsNone(
            confirm_template_match(
                initial_stats,
                confirmed_stats,
                self.active_templates,
                self.templates,
            )
        )

    def test_confirm_template_match_returns_none_when_confirmation_fails(self) -> None:
        initial_stats = {
            "Boss Curses": 3,
            "Challenges": 0,
            "Charge Shrines": 0,
            "Chests": 0,
            "Greed Shrines": 0,
            "Magnet Shrines": 0,
            "Microwaves": 2,
            "Moais": 4,
            "Pots": 0,
            "Shady Guy": 5,
        }
        confirmed_stats = {
            **initial_stats,
            "Boss Curses": 0,
        }

        self.assertIsNone(
            confirm_template_match(
                initial_stats,
                confirmed_stats,
                self.active_templates,
                self.templates,
            )
        )

    def test_confirm_template_match_returns_confirmed_template(self) -> None:
        initial_stats = {
            "Boss Curses": 3,
            "Challenges": 0,
            "Charge Shrines": 0,
            "Chests": 0,
            "Greed Shrines": 0,
            "Magnet Shrines": 0,
            "Microwaves": 2,
            "Moais": 4,
            "Pots": 0,
            "Shady Guy": 5,
        }
        confirmed_stats = dict(initial_stats)

        template = confirm_template_match(
            initial_stats,
            confirmed_stats,
            self.active_templates,
            self.templates,
        )

        self.assertIsNotNone(template)
        self.assertEqual(template["name"], "PERFECT+")

    def test_wait_for_game_client_retries_until_client_is_available(self) -> None:
        main.is_running = False
        main.return_to_menu = False
        calls: list[str] = []
        sleeps: list[float] = []
        client = object()

        def fake_factory(*, process_name: str):
            calls.append(process_name)
            if len(calls) == 1:
                raise ProcessNotFoundError(process_name)
            if len(calls) == 2:
                raise ModuleNotFoundError("GameAssembly.dll")
            return client

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = wait_for_game_client(
                "Megabonk.exe",
                client_factory=fake_factory,
                sleep_fn=sleeps.append,
                retry_delay=0.25,
            )

        self.assertIs(result, client)
        self.assertEqual(calls, ["Megabonk.exe", "Megabonk.exe", "Megabonk.exe"])
        self.assertEqual(sleeps, [0.25, 0.25])
        output = stdout.getvalue()
        self.assertIn("[WAIT] Waiting for process 'Megabonk.exe'...", output)
        self.assertIn("[WAIT] Process found. Waiting for GameAssembly.dll...", output)
        self.assertIn("[WAIT] Game detected. Press 'f6' to start scanning.", output)
        self.assertFalse(main.is_running)

    def test_wait_for_game_client_returns_none_when_returning_to_menu(self) -> None:
        main.is_running = False
        main.return_to_menu = False
        calls: list[str] = []
        sleeps: list[float] = []

        def fake_factory(*, process_name: str):
            calls.append(process_name)
            raise ProcessNotFoundError(process_name)

        def fake_sleep(delay: float) -> None:
            sleeps.append(delay)
            main.return_to_menu = True

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = wait_for_game_client(
                "Megabonk.exe",
                client_factory=fake_factory,
                sleep_fn=fake_sleep,
                retry_delay=0.5,
            )

        self.assertIsNone(result)
        self.assertEqual(calls, ["Megabonk.exe"])
        self.assertEqual(sleeps, [0.5])
        output = stdout.getvalue()
        self.assertEqual(output.count("[WAIT] Waiting for process 'Megabonk.exe'..."), 1)
        self.assertNotIn("[WAIT] Game detected. Press 'f6' to start scanning.", output)

    def test_wait_for_game_client_does_not_repeat_same_wait_message(self) -> None:
        main.is_running = False
        main.return_to_menu = False
        sleeps: list[float] = []
        calls = 0

        def fake_factory(*, process_name: str):
            nonlocal calls
            calls += 1
            if calls >= 3:
                return object()
            raise ProcessNotFoundError(process_name)

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = wait_for_game_client(
                "Megabonk.exe",
                client_factory=fake_factory,
                sleep_fn=sleeps.append,
                retry_delay=0.2,
            )

        self.assertIsNotNone(result)
        self.assertEqual(sleeps, [0.2, 0.2])
        output = stdout.getvalue()
        self.assertEqual(output.count("[WAIT] Waiting for process 'Megabonk.exe'..."), 1)
        self.assertEqual(output.count("[WAIT] Game detected. Press 'f6' to start scanning."), 1)

    def test_reset_client_after_disconnect_closes_client_and_waits(self) -> None:
        sleeps: list[float] = []

        class FakeClient:
            def __init__(self) -> None:
                self.closed = False

            def close(self) -> None:
                self.closed = True

        client = FakeClient()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            reset_client_after_disconnect(
                client,
                ProcessNotFoundError("Megabonk.exe"),
                sleep_fn=sleeps.append,
                process_name="Megabonk.exe",
                retry_delay=0.75,
            )

        self.assertTrue(client.closed)
        self.assertEqual(sleeps, [0.75])
        self.assertIn(
            "[WAIT] Lost connection to the game (Megabonk.exe). Returning to wait mode...",
            stdout.getvalue(),
        )

    def test_toggle_script_does_not_start_before_ready(self) -> None:
        main.is_running = False
        main.is_ready_to_start = False

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            toggle_script()

        self.assertFalse(main.is_running)
        self.assertIn("[WAIT] Scanner is not ready yet. Finish process wait first.", stdout.getvalue())

    def test_run_scanner_returns_reconnect_and_requires_fresh_start(self) -> None:
        main.active_templates = self.active_templates
        main.is_running = False
        main.is_ready_to_start = False
        main.return_to_menu = False
        original_sleep = main.time.sleep
        original_templates = main.config.TEMPLATES

        class FakeMemory:
            process_name = "Megabonk.exe"

        class FakeClient:
            def __init__(self) -> None:
                self.memory = FakeMemory()
                self.closed = False

            def get_map_stats(self):
                raise MemoryReadError("boom")

            def close(self) -> None:
                self.closed = True

        def fake_sleep(_delay: float) -> None:
            if not main.is_running:
                main.is_running = True

        try:
            main.time.sleep = fake_sleep
            main.config.TEMPLATES = self.templates
            client = FakeClient()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = run_scanner(client)
        finally:
            main.time.sleep = original_sleep
            main.config.TEMPLATES = original_templates

        self.assertEqual(result, "reconnect")
        self.assertTrue(client.closed)
        self.assertFalse(main.is_running)
        self.assertFalse(main.is_ready_to_start)
        self.assertIn("[WAIT] Lost connection to the game (boom). Returning to wait mode...", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
