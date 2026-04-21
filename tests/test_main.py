from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main


class MainEntrypointTests(unittest.TestCase):
    def test_main_prints_error_when_keyboard_is_missing(self) -> None:
        stdout = io.StringIO()

        with patch.object(main, "keyboard", None):
            with redirect_stdout(stdout):
                main.main()

        output = stdout.getvalue()
        self.assertIn("[CRITICAL ERROR] Missing dependency: keyboard.", output)
        self.assertIn("Install it with: pip install keyboard", output)

    def test_main_creates_app_registers_close_handler_and_starts_loop(self) -> None:
        events: list[tuple[str, object] | str] = []

        class FakeApp:
            def protocol(self, name: str, callback: object) -> None:
                events.append((name, callback))

            def on_closing(self) -> None:
                events.append("closed")

            def mainloop(self) -> None:
                events.append("mainloop")

        with patch.object(main, "keyboard", object()):
            with patch.object(main, "MegabonkApp", return_value=FakeApp()):
                main.main()

        self.assertEqual(len(events), 2)
        protocol_name, close_handler = events[0]
        self.assertEqual(protocol_name, "WM_DELETE_WINDOW")
        self.assertTrue(callable(close_handler))
        self.assertEqual(events[1], "mainloop")


if __name__ == "__main__":
    unittest.main()
