from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import src  # noqa: F401

from app import config
from app.update_flow import UpdateCheckResult
from infra.updater import PreparedUpdate, ReleaseInfo
from ui.dialogs import update_prompt


DOWNLOAD_URL = (
    "https://github.com/ALuiell/BonkScanner/releases/download/v3.2.1/BonkScanner.exe"
)


class RecordingFooter:
    def __init__(self) -> None:
        self.states: list[tuple[str, str]] = []

    def set_update_status(self, state: str, version: str = "") -> None:
        self.states.append((state, version))


class FakeApp:
    def __init__(self) -> None:
        self.window = self
        self.footer = RecordingFooter()
        self.logs: list[tuple[str, str | None]] = []
        self.shutdowns = 0

    def after(self, _delay: int, callback) -> None:
        callback()

    def log(self, message: str, tag: str | None = None) -> None:
        self.logs.append((message, tag))

    def on_closing(self) -> None:
        self.shutdowns += 1


def available_result() -> UpdateCheckResult:
    release = ReleaseInfo("3.2.1", "notes", DOWNLOAD_URL, 3, "a" * 64)
    return UpdateCheckResult(
        state="available",
        version=release.version,
        release=release,
        exe_path="BonkScanner.exe",
        should_prompt=True,
    )


class UpdatePromptTests(unittest.TestCase):
    def test_registered_thread_removes_itself_after_completion(self) -> None:
        app = FakeApp()
        finished = threading.Event()

        thread = update_prompt._start_registered_thread(
            app,
            target=finished.set,
            name="TestRegisteredThread",
        )
        thread.join(timeout=3)

        self.assertTrue(finished.is_set())
        self.assertNotIn(thread, app.__dict__["_background_threads"])

    def test_previous_installer_failure_is_reported_in_the_app_log(self) -> None:
        app = FakeApp()
        with (
            patch.object(
                update_prompt,
                "consume_update_result",
                return_value=("error", "The previous version was restored."),
            ),
            patch.object(
                update_prompt,
                "check_for_update",
                return_value=UpdateCheckResult(state="current", version="3.0.1"),
            ),
        ):
            thread = update_prompt.start_update_check(app, force_check=False)
            thread.join(timeout=3)

        self.assertTrue(
            any("previous version was restored" in message for message, _tag in app.logs)
        )

    def test_only_one_update_session_can_run_at_a_time(self) -> None:
        app = FakeApp()
        entered = threading.Event()
        release = threading.Event()

        def slow_check(*, force_check: bool):
            del force_check
            entered.set()
            self.assertTrue(release.wait(timeout=3))
            return UpdateCheckResult(state="current", version="3.0.1")

        with patch.object(
            update_prompt, "check_for_update", side_effect=slow_check
        ) as check:
            first = update_prompt.start_update_check(app, force_check=False)
            self.assertTrue(entered.wait(timeout=3))
            second = update_prompt.start_update_check(app, force_check=True)
            release.set()
            first.join(timeout=3)

        self.assertIsNone(second)
        self.assertFalse(first.is_alive())
        self.assertEqual(1, check.call_count)
        self.assertFalse(app.__dict__["_update_session_active"])

    def test_unexpected_check_exception_releases_the_update_session(self) -> None:
        app = FakeApp()
        with patch.object(
            update_prompt,
            "check_for_update",
            side_effect=RuntimeError("probe exploded"),
        ):
            thread = update_prompt.start_update_check(app, force_check=True)
            thread.join(timeout=3)

        self.assertFalse(app.__dict__["_update_session_active"])
        self.assertTrue(
            any("probe exploded" in message for message, _tag in app.logs)
        )
        self.assertIn(("unknown", ""), app.footer.states)

    def test_thread_start_failure_releases_the_update_session(self) -> None:
        app = FakeApp()
        with patch.object(
            update_prompt,
            "_start_registered_thread",
            side_effect=RuntimeError("thread unavailable"),
        ):
            worker = update_prompt.start_update_check(app, force_check=True)

        self.assertIsNone(worker)
        self.assertFalse(app.__dict__["_update_session_active"])
        self.assertTrue(
            any("thread unavailable" in message for message, _tag in app.logs)
        )

    def test_failed_skip_save_is_reported_and_session_is_released(self) -> None:
        app = FakeApp()
        failure = config.SettingsSaveResult(False, "config is read-only")
        with (
            patch.object(update_prompt, "check_for_update", return_value=available_result()),
            patch.object(update_prompt, "show_update_dialog", return_value="skip"),
            patch.object(update_prompt, "skip_update_version", return_value=failure),
        ):
            thread = update_prompt.start_update_check(app, force_check=True)
            thread.join(timeout=3)

        self.assertFalse(app.__dict__["_update_session_active"])
        self.assertTrue(
            any("config is read-only" in message for message, _tag in app.logs)
        )
        self.assertIn(("available", "3.2.1"), app.footer.states)

    def test_verified_install_launches_helper_then_uses_clean_shutdown(self) -> None:
        app = FakeApp()
        with tempfile.TemporaryDirectory() as temp_dir:
            new_exe = Path(temp_dir) / "new.exe"
            installer = Path(temp_dir) / "update.bat"
            new_exe.write_bytes(b"new")
            installer.write_text("@echo off\n", encoding="utf-8")
            prepared = PreparedUpdate(
                version="3.2.1",
                exe_path=str(Path(temp_dir) / "BonkScanner.exe"),
                new_exe_path=str(new_exe),
                installer_path=str(installer),
                downloaded_size=3,
                sha256="a" * 64,
            )

            def show_dialog(_parent, _release, *, start_download, install_update):
                del start_download
                install_update(prepared)
                return "update"

            with (
                patch.object(update_prompt, "check_for_update", return_value=available_result()),
                patch.object(update_prompt, "show_update_dialog", side_effect=show_dialog),
                patch.object(update_prompt, "launch_prepared_update") as launch,
            ):
                thread = update_prompt.start_update_check(app, force_check=True)
                thread.join(timeout=3)

        launch.assert_called_once_with(prepared)
        self.assertEqual(1, app.shutdowns)
        self.assertIn(("installing", "3.2.1"), app.footer.states)

    def test_skip_button_persists_only_the_named_release(self) -> None:
        app = FakeApp()
        with (
            patch.object(update_prompt, "check_for_update", return_value=available_result()),
            patch.object(update_prompt, "show_update_dialog", return_value="skip"),
            patch.object(update_prompt, "skip_update_version") as skip,
        ):
            thread = update_prompt.start_update_check(app, force_check=True)
            thread.join(timeout=3)

        skip.assert_called_once_with("3.2.1")


if __name__ == "__main__":
    unittest.main()
