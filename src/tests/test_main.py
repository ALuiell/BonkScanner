from __future__ import annotations

import src

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main


class MainEntrypointTests(unittest.TestCase):
    def test_crash_journal_is_installed_before_optional_and_gui_imports(self) -> None:
        events: list[str] = []

        class FakeApp:
            def __init__(self, **_kwargs) -> None:
                events.append("construct")

            def protocol(self, _name, _callback) -> None:
                pass

            def start(self) -> None:
                events.append("start")

            def mainloop(self) -> None:
                pass

            def on_closing(self) -> bool:
                return True

        with patch.object(
            main, "install_crash_journal", side_effect=lambda: events.append("journal")
        ), patch.object(
            main,
            "_initialize_configuration",
            side_effect=lambda: events.append("config"),
        ), patch.object(
            main,
            "_load_keyboard_dependency",
            side_effect=lambda: events.append("keyboard") or object(),
        ), patch.object(
            main,
            "_load_gui_application",
            side_effect=lambda: events.append("gui") or FakeApp,
        ), patch.object(main, "mark_clean_exit"), patch.object(main, "log_runtime_event"):
            main.main()

        self.assertEqual(
            events[:5],
            ["journal", "config", "keyboard", "gui", "construct"],
        )
        self.assertIn("start", events)

    def test_gui_import_failure_keeps_pending_crash_journal(self) -> None:
        with patch.object(main, "install_crash_journal"), patch.object(
            main, "_initialize_configuration"
        ), patch.object(
            main, "_load_keyboard_dependency", return_value=object()
        ), patch.object(
            main, "_load_gui_application", side_effect=ImportError("QtCore missing")
        ), patch.object(main, "mark_clean_exit") as mark_clean_exit:
            with self.assertRaisesRegex(ImportError, "QtCore missing"):
                main.main()

        mark_clean_exit.assert_not_called()

    def test_main_prints_error_when_keyboard_is_missing(self) -> None:
        stdout = io.StringIO()

        with patch.object(main, "install_crash_journal"), patch.object(
            main, "_initialize_configuration"
        ), patch.object(
            main, "mark_clean_exit"
        ), patch.object(main, "keyboard", None):
            with redirect_stdout(stdout):
                main.main()

        output = stdout.getvalue()
        self.assertIn("[CRITICAL ERROR] Missing dependency: keyboard.", output)
        self.assertIn("Install it with: pip install keyboard", output)

    def test_main_creates_app_registers_close_handler_and_starts_loop(self) -> None:
        events: list[tuple[str, object] | str] = []

        class FakeApp:
            def start(self) -> None:
                events.append("start")

            def protocol(self, name: str, callback: object) -> None:
                events.append((name, callback))

            def on_closing(self) -> None:
                events.append("closed")
                return True

            def mainloop(self) -> None:
                events.append("mainloop")

        with patch.object(main, "install_crash_journal"), patch.object(
            main, "_initialize_configuration"
        ), patch.object(
            main, "mark_clean_exit"
        ) as mark_clean_exit, patch.object(main, "log_runtime_event"), patch.object(
            main, "keyboard", object()
        ):
            with patch.object(main, "MegabonkApp", return_value=FakeApp()):
                main.main()

        self.assertEqual(len(events), 4)
        protocol_name, close_handler = events[0]
        self.assertEqual(protocol_name, "WM_DELETE_WINDOW")
        self.assertTrue(callable(close_handler))
        self.assertEqual(events[1], "start")
        self.assertEqual(events[2], "mainloop")
        self.assertEqual(events[3], "closed")
        mark_clean_exit.assert_called_once_with()

    def test_main_cleans_up_when_the_event_loop_raises_without_marking_clean_exit(self) -> None:
        events: list[str] = []

        class FakeApp:
            def start(self) -> None:
                pass

            def protocol(self, _name: str, _callback: object) -> None:
                pass

            def on_closing(self) -> bool:
                events.append("closed")
                return True

            def mainloop(self) -> None:
                raise RuntimeError("event loop failed")

        with patch.object(main, "install_crash_journal"), patch.object(
            main, "_initialize_configuration"
        ), patch.object(
            main, "mark_clean_exit"
        ) as mark_clean_exit, patch.object(main, "log_runtime_event"), patch.object(
            main, "keyboard", object()
        ), patch.object(main, "MegabonkApp", return_value=FakeApp()):
            with self.assertRaisesRegex(RuntimeError, "event loop failed"):
                main.main()

        self.assertEqual(events, ["closed"])
        mark_clean_exit.assert_not_called()

    def test_main_keeps_the_crash_journal_when_shutdown_reports_failure(self) -> None:
        class FakeApp:
            def start(self) -> None:
                pass

            def protocol(self, _name: str, _callback: object) -> None:
                pass

            def on_closing(self) -> bool:
                return False

            def mainloop(self) -> None:
                pass

        with patch.object(main, "install_crash_journal"), patch.object(
            main, "_initialize_configuration"
        ), patch.object(
            main, "mark_clean_exit"
        ) as mark_clean_exit, patch.object(main, "log_runtime_event"), patch.object(
            main, "keyboard", object()
        ), patch.object(main, "MegabonkApp", return_value=FakeApp()):
            main.main()

        mark_clean_exit.assert_not_called()

    def test_main_cleans_up_if_setup_after_construction_fails(self) -> None:
        events: list[str] = []

        class FakeApp:
            def start(self) -> None:
                pass

            def protocol(self, _name: str, _callback: object) -> None:
                raise RuntimeError("protocol failed")

            def on_closing(self) -> bool:
                events.append("closed")
                return True

            def mainloop(self) -> None:
                raise AssertionError("must not enter the event loop")

        with patch.object(main, "install_crash_journal"), patch.object(
            main, "_initialize_configuration"
        ), patch.object(
            main, "mark_clean_exit"
        ) as mark_clean_exit, patch.object(main, "log_runtime_event"), patch.object(
            main, "keyboard", object()
        ), patch.object(main, "MegabonkApp", return_value=FakeApp()):
            with self.assertRaisesRegex(RuntimeError, "protocol failed"):
                main.main()

        self.assertEqual(events, ["closed"])
        mark_clean_exit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
