from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

import src  # noqa: F401
from PySide6.QtGui import QColor, QFont, QPalette
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
            self.assertIn(":delete_backup", script)
            self.assertIn(
                "if %DELETE_ATTEMPTS% GEQ 30 goto cleanup_complete", script
            )
            self.assertIn("goto delete_backup", script)
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

    def test_startup_removes_only_updater_owned_stale_backups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            exe_path = directory / "BonkScanner.exe"
            exe_path.write_bytes(b"current")
            stale_backup = directory / ".BonkScanner-1234-abcdef1234.old.exe"
            stale_backup.write_bytes(b"old")
            manual_backup = directory / ".BonkScanner-manual.old.exe"
            manual_backup.write_bytes(b"keep")
            other_backup = directory / ".Other-1234-abcdef1234.old.exe"
            other_backup.write_bytes(b"keep")

            self.assertIsNone(updater.consume_update_result(str(exe_path)))

            self.assertFalse(stale_backup.exists())
            self.assertTrue(manual_backup.exists())
            self.assertTrue(other_backup.exists())

    def test_locked_stale_backup_is_retried_on_a_later_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            exe_path = directory / "BonkScanner.exe"
            exe_path.write_bytes(b"current")
            stale_backup = directory / ".BonkScanner-1234-abcdef1234.old.exe"
            stale_backup.write_bytes(b"old")

            with patch.object(Path, "unlink", side_effect=PermissionError("locked")):
                self.assertIsNone(updater.consume_update_result(str(exe_path)))
            self.assertTrue(stale_backup.exists())

            self.assertIsNone(updater.consume_update_result(str(exe_path)))
            self.assertFalse(stale_backup.exists())


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

    def _dialog(self, *, notes: str = "## Improvements"):
        callbacks = {}

        def start_download(progress, ready, failed):
            callbacks.update(progress=progress, ready=ready, failed=failed)

        installed = []
        dialog = update_dialog.UpdateDialog(
            None,
            ReleaseInfo("3.2.1", notes, DOWNLOAD_URL, 100, "a" * 64),
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

        self.assertEqual("UpdateDialog", dialog.objectName())
        self.assertIsNotNone(dialog.findChild(QFrame, "dialogHeadRule"))
        self.assertEqual(
            "A new update is available",
            dialog.findChild(QLabel, "dialogTitle").text(),
        )
        self.assertEqual(
            "v3.2.1",
            dialog.findChild(QLabel, "UpdateVersionBadge").text(),
        )
        self.assertIsNotNone(dialog.findChild(QLabel, "UpdateVersionOld"))
        self.assertIsNotNone(dialog.findChild(QLabel, "UpdateVersionNew"))
        self.assertIsNotNone(dialog.findChild(QFrame, "UpdateFooterRule"))
        self.assertEqual("primary", dialog.update_button.objectName())
        self.assertEqual("Update and restart", dialog.update_button.text())
        self.assertEqual("Later", dialog.later_button.text())
        self.assertEqual("Skip v3.2.1", dialog.skip_button.text())
        self.assertTrue(dialog.skip_button.property("footerEdge"))

    def test_dialog_forces_a_dark_palette_over_a_light_application_palette(self) -> None:
        original_palette = self.app.palette()
        light_palette = QPalette(original_palette)
        light_palette.setColor(QPalette.Window, QColor("#FFFFFF"))
        light_palette.setColor(QPalette.WindowText, QColor("#000000"))
        light_palette.setColor(QPalette.Base, QColor("#FFFFFF"))
        light_palette.setColor(QPalette.Text, QColor("#000000"))
        self.app.setPalette(light_palette)
        self.addCleanup(self.app.setPalette, original_palette)

        dialog, _callbacks, _installed = self._dialog()
        palette = dialog.palette()

        self.assertEqual("#0e1217", palette.color(QPalette.Window).name())
        self.assertEqual("#edf1f5", palette.color(QPalette.WindowText).name())
        self.assertEqual("#0b0f14", palette.color(QPalette.Base).name())
        self.assertEqual("#d7dee8", palette.color(QPalette.Text).name())
        self.assertEqual("#2f6fb0", palette.color(QPalette.Highlight).name())

    def test_dark_title_bar_is_applied_when_the_dialog_is_shown(self) -> None:
        dialog, _callbacks, _installed = self._dialog()

        with patch.object(
            update_dialog,
            "_enable_windows_dark_title_bar",
            return_value=True,
        ) as enable_dark_title_bar:
            dialog.show()
            self.app.processEvents()

        self.assertGreaterEqual(enable_dark_title_bar.call_count, 1)
        self.assertTrue(
            all(call.args == (dialog,) for call in enable_dark_title_bar.call_args_list)
        )
        self.assertTrue(dialog._dark_title_bar_applied)

    def test_dark_title_bar_requests_explicit_dwm_colours(self) -> None:
        window = MagicMock()
        window.winId.return_value = 123
        set_window_attribute = MagicMock(return_value=0)
        dwmapi = MagicMock(DwmSetWindowAttribute=set_window_attribute)

        with (
            patch.object(update_dialog.sys, "platform", "win32"),
            patch.object(
                update_dialog.ctypes,
                "WinDLL",
                return_value=dwmapi,
                create=True,
            ),
        ):
            applied = update_dialog._enable_windows_dark_title_bar(window)

        self.assertTrue(applied)
        attributes = [call.args[1].value for call in set_window_attribute.call_args_list]
        self.assertEqual([20, 35, 36, 34], attributes)

    def test_dialog_disables_subpixel_font_antialiasing(self) -> None:
        dialog, _callbacks, _installed = self._dialog()

        dialog.show()
        self.app.processEvents()

        widgets = (
            dialog.findChild(QLabel, "dialogTitle"),
            dialog.findChild(QLabel, "UpdateSupportMessage"),
            dialog.update_button,
            dialog.notes,
        )
        for widget in widgets:
            with self.subTest(widget=widget.objectName() or widget.text()):
                self.assertTrue(
                    widget.font().styleStrategy() & QFont.NoSubpixelAntialias
                )
        self.assertTrue(
            dialog.notes.document().defaultFont().styleStrategy()
            & QFont.NoSubpixelAntialias
        )

    def test_release_notes_use_the_updater_html_stylesheet(self) -> None:
        release_html = """
        <h2>What's New in v3.2.1</h2>
        <h3>ENG</h3>
        <ul><li>Improved <code>Settings</code>.</li></ul>
        <h3>RU</h3>
        <p><strong>Важно:</strong> улучшены настройки.</p>
        <hr><a href="https://example.invalid">Details</a>
        """
        dialog, _callbacks, _installed = self._dialog(notes=release_html)

        self.assertEqual(
            update_dialog.RELEASE_NOTES_STYLESHEET,
            dialog.notes.document().defaultStyleSheet(),
        )
        for selector in ("h2", "h3", "p", "ul", "li", "code", "strong", "hr", "a"):
            with self.subTest(selector=selector):
                self.assertIn(f"{selector} {{", update_dialog.RELEASE_NOTES_STYLESHEET)
        rendered_text = dialog.notes.toPlainText()
        self.assertIn("What's New in v3.2.1", rendered_text)
        self.assertIn("ENG", rendered_text)
        self.assertIn("RU", rendered_text)

    def test_dialog_typography_matches_the_approved_mockup(self) -> None:
        dialog, _callbacks, _installed = self._dialog()
        theme_path = (
            Path(update_dialog.__file__).resolve().parents[2]
            / "media"
            / "bonkscanner_theme.qss"
        )
        theme = theme_path.read_text(encoding="utf-8")
        dialog.setStyleSheet(theme)

        expectations = (
            (dialog.findChild(QLabel, "dialogTitle"), 18, QFont.DemiBold),
            (dialog.findChild(QLabel, "dialogSubtitle"), 12, QFont.Normal),
            (dialog.findChild(QLabel, "UpdateVersionBadge"), 11, QFont.DemiBold),
            (dialog.findChild(QLabel, "UpdateVersionNew"), 12, QFont.DemiBold),
            (dialog.findChild(QLabel, "UpdateTrustNote"), 12, QFont.Normal),
            (dialog.findChild(QLabel, "UpdateSupportHeart"), 15, QFont.DemiBold),
            (dialog.findChild(QLabel, "UpdateSupportMessage"), 12, QFont.Normal),
            (dialog.patreon_button, 11, QFont.DemiBold),
            (dialog.crypto_button, 11, QFont.DemiBold),
            (dialog.later_button, 12, QFont.Normal),
            (dialog.update_button, 12, QFont.DemiBold),
            (dialog.skip_button, 11, QFont.Normal),
        )
        for widget, pixel_size, weight in expectations:
            with self.subTest(widget=widget.objectName() or widget.text()):
                widget.ensurePolished()
                font = widget.font()
                self.assertEqual("Segoe UI", font.family())
                self.assertEqual(pixel_size, font.pixelSize())
                self.assertEqual(weight, font.weight())

        release_stylesheet = update_dialog.RELEASE_NOTES_STYLESHEET
        self.assertRegex(
            release_stylesheet,
            r"(?s)h2\s*\{.*?font-size: 17px;.*?font-weight: 500;",
        )
        self.assertRegex(
            release_stylesheet,
            r"(?s)h3\s*\{.*?font-size: 13px;.*?font-weight: 500;",
        )
        self.assertRegex(release_stylesheet, r"(?s)li\s*\{.*?font-size: 13px;")
        self.assertRegex(release_stylesheet, r"(?s)code\s*\{.*?font-size: 12px;")
        self.assertIn("color: #CBD4DE;", release_stylesheet)
        self.assertIn("background-color: #151F2A;", release_stylesheet)

        for stylesheet_name, stylesheet in (
            ("theme", theme),
            ("dialog", dialog.styleSheet()),
        ):
            with self.subTest(stylesheet=stylesheet_name):
                self.assertRegex(
                    stylesheet,
                    r"(?s)QTextEdit#UpdateReleaseNotes\s*\{"
                    r".*?(?:background|background-color): #0E151D;"
                    r".*?border: 1px solid #273340;"
                    r".*?border-radius: 7px;"
                    r".*?color: #CBD4DE;"
                    r".*?font-size: 13px;",
                )
        self.assertNotIn("line-height:", release_stylesheet)

    def test_support_card_uses_compact_text_routes(self) -> None:
        dialog, _callbacks, _installed = self._dialog()

        self.assertEqual(
            update_dialog.SUPPORT_MESSAGE,
            dialog.findChild(QLabel, "UpdateSupportMessage").text(),
        )
        self.assertEqual("♥", dialog.findChild(QLabel, "UpdateSupportHeart").text())
        self.assertEqual("Patreon", dialog.patreon_button.text())
        self.assertEqual("Crypto", dialog.crypto_button.text())
        self.assertTrue(dialog.patreon_button.icon().isNull())
        self.assertTrue(dialog.crypto_button.icon().isNull())
        self.assertTrue(dialog.patreon_button.property("updateSupportAction"))
        self.assertTrue(dialog.crypto_button.property("updateSupportAction"))

    def test_support_routes_open_without_changing_the_update_decision(self) -> None:
        dialog, _callbacks, _installed = self._dialog()

        with patch.object(update_dialog, "_open_browser_page", return_value=True) as open_page:
            dialog._open_patreon()
            dialog._open_crypto()

        self.assertEqual(
            [
                call(update_dialog.config.PATREON_SUPPORT_URL),
                call(update_dialog.config.CRYPTO_SUPPORT_URL),
            ],
            open_page.call_args_list,
        )
        self.assertEqual("later", dialog.decision)

    def test_failed_support_route_shows_the_url_and_keeps_the_dialog_state(self) -> None:
        dialog, _callbacks, _installed = self._dialog()

        with (
            patch.object(update_dialog, "_open_browser_page", return_value=False),
            patch.object(update_dialog.QMessageBox, "warning") as warning,
        ):
            dialog._open_patreon()

        warning.assert_called_once()
        self.assertIn(
            update_dialog.config.PATREON_SUPPORT_URL,
            warning.call_args.args[2],
        )
        self.assertEqual("later", dialog.decision)

    def test_missing_crypto_url_disables_only_the_crypto_route(self) -> None:
        with patch.object(update_dialog.config, "CRYPTO_SUPPORT_URL", ""):
            dialog, _callbacks, _installed = self._dialog()

        self.assertTrue(dialog.patreon_button.isEnabled())
        self.assertFalse(dialog.crypto_button.isEnabled())
        self.assertIn("coming soon", dialog.crypto_button.toolTip())

    def test_support_card_remains_available_across_download_and_error_states(self) -> None:
        dialog, callbacks, _installed = self._dialog()
        self.assertFalse(dialog.support_card.isHidden())

        dialog._begin_download()
        self.assertFalse(dialog.support_card.isHidden())

        callbacks["failed"]("network unavailable")
        self.app.processEvents()
        self.assertFalse(dialog.support_card.isHidden())

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
