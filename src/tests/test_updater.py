from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import src  # noqa: F401
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from infra import updater
from infra.updater import PreparedUpdate, ReleaseInfo, UpdateError
from ui.dialogs import update_dialog


DOWNLOAD_URL = (
    "https://github.com/ALuiell/BonkScanner/releases/download/v3.2.1/BonkScanner.exe"
)
REDIRECT_URL = "https://release-assets.githubusercontent.com/github-production-release/asset"


class FakeResponse:
    def __init__(
        self,
        *,
        payload=None,
        body: bytes = b"",
        url: str = REDIRECT_URL,
        content_length: int | None = None,
    ) -> None:
        self._payload = payload
        self._body = body
        self.url = url
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = str(content_length)

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload

    def iter_content(self, chunk_size: int):
        del chunk_size
        midpoint = max(1, len(self._body) // 2)
        yield self._body[:midpoint]
        yield self._body[midpoint:]


class FakeNotes:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def setHtml(self, value: str) -> None:
        self.calls.append(("html", value))

    def setMarkdown(self, value: str) -> None:
        self.calls.append(("markdown", value))

    def setPlainText(self, value: str) -> None:
        self.calls.append(("plain", value))


def release_for(body: bytes, *, digest: str | None = None) -> ReleaseInfo:
    return ReleaseInfo(
        version="3.2.1",
        notes="notes",
        exe_download_url=DOWNLOAD_URL,
        exe_size=len(body),
        exe_digest=digest or hashlib.sha256(body).hexdigest(),
    )


class UpdaterBackendTests(unittest.TestCase):
    def test_release_uses_exact_asset_and_carries_size_and_digest(self) -> None:
        digest = "a" * 64
        response = FakeResponse(
            payload={
                "tag_name": "v3.2.1",
                "body": "Release notes",
                "assets": [
                    {
                        "name": "BonkScanner-debug.exe",
                        "browser_download_url": DOWNLOAD_URL.replace(
                            "BonkScanner.exe", "BonkScanner-debug.exe"
                        ),
                        "size": 5,
                        "digest": f"sha256:{'b' * 64}",
                    },
                    {
                        "name": "BonkScanner.exe",
                        "browser_download_url": DOWNLOAD_URL,
                        "size": 12345,
                        "digest": f"sha256:{digest}",
                    },
                ],
            }
        )
        with patch("requests.get", return_value=response):
            release = updater.fetch_latest_release()

        self.assertEqual("3.2.1", release.version)
        self.assertEqual(DOWNLOAD_URL, release.exe_download_url)
        self.assertEqual(12345, release.exe_size)
        self.assertEqual(digest, release.exe_digest)

    def test_release_rejects_missing_digest(self) -> None:
        response = FakeResponse(
            payload={
                "tag_name": "v3.2.1",
                "assets": [
                    {
                        "name": "BonkScanner.exe",
                        "browser_download_url": DOWNLOAD_URL,
                        "size": 123,
                        "digest": None,
                    }
                ],
            }
        )
        with patch("requests.get", return_value=response):
            with self.assertRaisesRegex(UpdateError, "SHA-256"):
                updater.fetch_latest_release()

    def test_release_rejects_duplicate_exact_assets(self) -> None:
        asset = {
            "name": "BonkScanner.exe",
            "browser_download_url": DOWNLOAD_URL,
            "size": 123,
            "digest": f"sha256:{'a' * 64}",
        }
        response = FakeResponse(
            payload={"tag_name": "v3.2.1", "assets": [asset, dict(asset)]}
        )
        with patch("requests.get", return_value=response):
            with self.assertRaisesRegex(UpdateError, "exactly one"):
                updater.fetch_latest_release()

    def test_prepare_update_streams_reports_verifies_and_builds_bounded_helper(self) -> None:
        body = b"MZ" + bytes(range(256)) * 20
        response = FakeResponse(
            body=body,
            content_length=len(body),
        )
        progress: list[tuple[int, int]] = []

        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = Path(temp_dir) / "BonkScanner.exe"
            exe_path.write_bytes(b"old executable")
            with patch("requests.get", return_value=response):
                prepared = updater.prepare_update(
                    str(exe_path),
                    release_for(body),
                    progress=lambda current, total: progress.append((current, total)),
                )

            self.assertEqual(body, Path(prepared.new_exe_path).read_bytes())
            script = Path(prepared.installer_path).read_text(encoding="utf-8")
            self.assertIn("if %ATTEMPTS% GEQ 120 goto timed_out", script)
            self.assertIn(":move_old", script)
            self.assertIn(
                "if %MOVE_ATTEMPTS% GEQ 30 goto install_failed", script
            )
            self.assertIn("goto move_old", script)
            self.assertIn(":move_new_loop", script)
            self.assertIn(
                "if %MOVE_ATTEMPTS% GEQ 30 goto restore_old", script
            )
            self.assertIn("goto move_new_loop", script)
            self.assertIn(":restore_old", script)
            self.assertIn("echo SUCCESS 3.2.1", script)
            self.assertIn("echo ERROR The update could not be installed", script)
            self.assertNotIn("os._exit", script)
            self.assertEqual((0, len(body)), progress[0])
            self.assertEqual((len(body), len(body)), progress[-1])
            self.assertEqual(hashlib.sha256(body).hexdigest(), prepared.sha256)

    def test_prepare_update_removes_partial_file_on_digest_mismatch(self) -> None:
        body = b"not the promised executable"
        response = FakeResponse(body=body, content_length=len(body))
        wrong_release = release_for(body, digest="0" * 64)

        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = Path(temp_dir) / "BonkScanner.exe"
            exe_path.write_bytes(b"old executable")
            with patch("requests.get", return_value=response):
                with self.assertRaisesRegex(UpdateError, "SHA-256"):
                    updater.prepare_update(str(exe_path), wrong_release)

            self.assertEqual([], list(Path(temp_dir).glob(".*.new.exe")))
            self.assertEqual([], list(Path(temp_dir).glob(".bonkscanner-update-*.bat")))

    def test_prepare_update_rejects_untrusted_redirect(self) -> None:
        body = b"MZpayload"
        response = FakeResponse(
            body=body,
            content_length=len(body),
            url="https://example.test/BonkScanner.exe",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = Path(temp_dir) / "BonkScanner.exe"
            exe_path.write_bytes(b"old executable")
            with patch("requests.get", return_value=response):
                with self.assertRaisesRegex(UpdateError, "untrusted host"):
                    updater.prepare_update(str(exe_path), release_for(body))

    def test_launch_helper_does_not_exit_the_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = Path(temp_dir) / "BonkScanner.exe"
            new_path = Path(temp_dir) / ".BonkScanner.new.exe"
            installer_path = Path(temp_dir) / ".bonkscanner-update.bat"
            exe_path.write_bytes(b"old")
            new_path.write_bytes(b"new")
            installer_path.write_text("@echo off\n", encoding="utf-8")
            prepared = PreparedUpdate(
                version="3.2.1",
                exe_path=str(exe_path),
                new_exe_path=str(new_path),
                installer_path=str(installer_path),
                downloaded_size=3,
                sha256=hashlib.sha256(b"new").hexdigest(),
            )
            sentinel = object()
            with patch.object(updater.subprocess, "Popen", return_value=sentinel) as popen:
                result = updater.launch_prepared_update(prepared)

        self.assertIs(sentinel, result)
        popen.assert_called_once()

    def test_previous_installer_result_is_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = Path(temp_dir) / "BonkScanner.exe"
            exe_path.write_bytes(b"exe")
            result_path = Path(temp_dir) / updater.UPDATE_RESULT_NAME
            result_path.write_text("SUCCESS 3.2.1\n", encoding="utf-8")

            self.assertEqual(
                ("success", "3.2.1"), updater.consume_update_result(str(exe_path))
            )
            self.assertFalse(result_path.exists())
            self.assertIsNone(updater.consume_update_result(str(exe_path)))


class UpdateDialogContentTests(unittest.TestCase):
    def test_set_release_notes_content_prefers_html_for_html_input(self) -> None:
        notes = FakeNotes()

        update_dialog._set_release_notes_content(notes, "<p><b>IMPORTANT:</b></p>")

        self.assertEqual(notes.calls, [("html", "<p><b>IMPORTANT:</b></p>")])

    def test_set_release_notes_content_uses_markdown_for_plain_markdown_input(self) -> None:
        notes = FakeNotes()

        update_dialog._set_release_notes_content(notes, "## What's New")

        self.assertEqual(notes.calls, [("markdown", "## What's New")])

    def test_looks_like_html_detects_tags(self) -> None:
        self.assertTrue(update_dialog._looks_like_html("<hr><p>Hello</p>"))
        self.assertFalse(update_dialog._looks_like_html("## Hello"))

    def test_byte_count_is_user_readable(self) -> None:
        self.assertEqual("512 B", update_dialog._format_bytes(512))
        self.assertEqual("2.0 KB", update_dialog._format_bytes(2048))
        self.assertEqual("2.0 MB", update_dialog._format_bytes(2 * 1024 * 1024))


class UpdateDialogWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self):
        callbacks = {}

        def start_download(progress, ready, failed):
            callbacks.update(progress=progress, ready=ready, failed=failed)

        installed = []
        dialog = update_dialog.UpdateDialog(
            None,
            ReleaseInfo("3.2.1", "## Improvements", DOWNLOAD_URL, 100, "a" * 64),
            start_download=start_download,
            install_update=installed.append,
        )
        def dispose() -> None:
            dialog._allow_close = True
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

        self.addCleanup(dispose)
        return dialog, callbacks, installed

    def test_dialog_uses_shared_chrome_and_clear_version_transition(self) -> None:
        dialog, _callbacks, _installed = self._dialog()

        self.assertIsNotNone(dialog.findChild(QFrame, "dialogHeadRule"))
        self.assertIsNotNone(dialog.findChild(QLabel, "UpdateVersionOld"))
        self.assertIsNotNone(dialog.findChild(QLabel, "UpdateVersionNew"))
        self.assertEqual("Update and restart", dialog.update_button.text())
        self.assertEqual("Later", dialog.later_button.text())
        self.assertEqual("Skip v3.2.1", dialog.skip_button.text())
        self.assertTrue(dialog.skip_button.property("footerEdge"))

    def test_download_progress_and_verification_stay_in_the_dialog(self) -> None:
        dialog, callbacks, _installed = self._dialog()
        dialog._begin_download()

        callbacks["progress"](50, 100)
        self.app.processEvents()
        self.assertEqual(50, dialog.progress_bar.value())
        self.assertIn("50%", dialog.progress_detail.text())

        prepared = PreparedUpdate(
            version="3.2.1",
            exe_path="BonkScanner.exe",
            new_exe_path="BonkScanner.new.exe",
            installer_path="update.bat",
            downloaded_size=100,
            sha256="a" * 64,
        )
        with patch.object(update_dialog.QTimer, "singleShot") as single_shot:
            callbacks["ready"](prepared)
            self.app.processEvents()

        self.assertEqual(100, dialog.progress_bar.value())
        self.assertIn("Verified", dialog.progress_status.text())
        single_shot.assert_called_once()
        self.assertIs(single_shot.call_args.args[1], dialog)

    def test_duplicate_ready_signal_schedules_only_one_installer(self) -> None:
        dialog, callbacks, _installed = self._dialog()
        dialog._begin_download()
        prepared = PreparedUpdate(
            version="3.2.1",
            exe_path="BonkScanner.exe",
            new_exe_path="BonkScanner.new.exe",
            installer_path="update.bat",
            downloaded_size=100,
            sha256="a" * 64,
        )

        with patch.object(update_dialog.QTimer, "singleShot") as single_shot:
            callbacks["ready"](prepared)
            callbacks["ready"](prepared)
            self.app.processEvents()

        single_shot.assert_called_once()

    def test_late_failure_cannot_relock_dialog_after_installer_launch(self) -> None:
        dialog, callbacks, installed = self._dialog()
        dialog._begin_download()
        prepared = PreparedUpdate(
            version="3.2.1",
            exe_path="BonkScanner.exe",
            new_exe_path="BonkScanner.new.exe",
            installer_path="update.bat",
            downloaded_size=100,
            sha256="a" * 64,
        )
        with patch.object(update_dialog.QTimer, "singleShot"):
            callbacks["ready"](prepared)
            self.app.processEvents()
        dialog._launch_installer()

        callbacks["failed"]("late worker error")
        self.app.processEvents()

        self.assertEqual([prepared], installed)
        self.assertTrue(dialog._allow_close)
        self.assertIn("Verified", dialog.progress_status.text())
        dialog.reject()
        self.assertEqual("update", dialog.decision)

    def test_invalid_ready_payload_becomes_retryable_failure(self) -> None:
        dialog, callbacks, _installed = self._dialog()
        dialog._begin_download()

        callbacks["ready"](object())
        self.app.processEvents()

        self.assertEqual("Retry download", dialog.update_button.text())
        self.assertIn("invalid prepared update", dialog.progress_detail.text())

    def test_failed_download_becomes_retry_without_closing(self) -> None:
        dialog, callbacks, _installed = self._dialog()
        dialog._begin_download()

        callbacks["failed"]("SHA-256 mismatch")
        self.app.processEvents()

        self.assertEqual("Retry download", dialog.update_button.text())
        self.assertTrue(dialog.update_button.isEnabled())
        self.assertIn("SHA-256 mismatch", dialog.progress_detail.text())
        self.assertEqual("error", dialog.progress_panel.property("state"))

    def test_skip_is_distinct_from_later(self) -> None:
        dialog, _callbacks, _installed = self._dialog()
        dialog._choose_skip()
        self.assertEqual("skip", dialog.decision)

        later, _callbacks, _installed = self._dialog()
        later.reject()
        self.assertEqual("later", later.decision)

    def test_show_update_dialog_always_deletes_the_transient(self) -> None:
        dialog = MagicMock()
        dialog.decision = "later"
        with patch.object(update_dialog, "UpdateDialog", return_value=dialog):
            decision = update_dialog.show_update_dialog(
                None,
                ReleaseInfo("3.2.1", "notes", DOWNLOAD_URL, 100, "a" * 64),
                start_download=MagicMock(),
                install_update=MagicMock(),
            )

        self.assertEqual("later", decision)
        dialog.exec.assert_called_once_with()
        dialog.deleteLater.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
