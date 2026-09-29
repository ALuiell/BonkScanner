"""The maintainer's shared storage must not add public settings controls."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app import data_storage as storage_app
from infra.data_storage import MigrationActionResult, StorageContext
from ui.dialogs import SettingsDialog
from ui.dialogs import data_storage as module


class SharedDataPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.installation = self.root / "installation"
        self.installation.mkdir()

    def context(self, mode="shared", *, custom=False, status="") -> StorageContext:
        return StorageContext(
            mode=mode,
            installation_dir=self.installation,
            data_dir=self.data,
            recommended_dir=(
                None if mode == "source"
                else self.root / "recommended" if custom else self.data
            ),
            installation_key="shared" if mode == "shared" else None,
            migration_status=status,
        )

    def page(self, context: StorageContext):
        migration = Mock(return_value=MigrationActionResult(True, "pending", "Move scheduled."))
        page = module.DataStoragePage(
            request_migration=migration,
            context_provider=lambda: context,
        )
        self.addCleanup(page.close)
        return page, migration

    def assert_no_private_copy(self, text: str) -> None:
        for token in (
            "edition", "config.json", "config_advanced.json", "shared profile",
            "shared data", "use existing data folder", "advanced", "regular uses",
        ):
            self.assertNotIn(token, text.casefold())

    def assert_public_page(self, page) -> None:
        self.assertFalse(hasattr(page, "config_name_label"))
        self.assertFalse(hasattr(page, "connect_button"))
        self.assertFalse(hasattr(page, "_choose_shared_folder"))
        self.assertIsNone(page.findChild(QPushButton, "DataStorageConnect"))
        for widget in (*page.findChildren(QLabel), *page.findChildren(QPushButton)):
            self.assert_no_private_copy(widget.text())
            self.assert_no_private_copy(widget.toolTip())
        self.assertEqual(page.open_button.text(), "Open data folder")
        self.assertEqual(page.current_path_label.text(), str(self.data))

    def test_public_page_never_exposes_private_connection_or_config_controls(self) -> None:
        with patch.object(storage_app, "request_shared_folder") as connect:
            for mode, custom in (
                ("source", False), ("legacy", False), ("local", False),
                ("local", True), ("shared", False), ("shared", True),
            ):
                with self.subTest(mode=mode, custom=custom):
                    page, migration = self.page(self.context(mode, custom=custom))
                    page.refresh()
                    self.assert_public_page(page)
                    migration.assert_not_called()
            connect.assert_not_called()

    def test_source_keeps_previous_caption_and_no_migration_controls(self) -> None:
        page, _ = self.page(self.context("source"))
        self.assertEqual(
            page.mode_label.text(),
            "Source run: data stays in the repository root. Installed-build migration rules are ignored.",
        )
        self.assertTrue(page.migration_card.isHidden())
        self.assert_public_page(page)

    def test_shared_folder_uses_the_same_captions_as_ordinary_storage(self) -> None:
        for custom in (False, True):
            with self.subTest(custom=custom):
                ordinary, _ = self.page(self.context("local", custom=custom))
                shared, _ = self.page(self.context("shared", custom=custom))
                self.assertEqual(shared.mode_label.text(), ordinary.mode_label.text())
                self.assertEqual(shared.migration_note.text(), ordinary.migration_note.text())
                self.assertFalse(shared.migration_card.isHidden())
                self.assertEqual(shared.choose_button.isHidden(), ordinary.choose_button.isHidden())
                self.assert_public_page(shared)

    def test_existing_open_folder_action_uses_active_data_directory(self) -> None:
        page, _ = self.page(self.context())
        with patch.object(page, "_open_folder") as open_folder:
            page.open_button.click()
        open_folder.assert_called_once_with(self.data)

    def test_existing_choose_folder_action_keeps_ordinary_migration_confirmation(self) -> None:
        page, migration = self.page(self.context())
        target = self.root / "destination"
        with patch.object(module.QFileDialog, "getExistingDirectory", return_value=str(target)), \
             patch.object(module, "ask_app_confirmation", return_value=True) as confirm, \
             patch.object(module, "show_app_notice") as notice, \
             patch.object(storage_app, "request_shared_folder") as connect:
            page.choose_button.click()
        migration.assert_called_once_with(target)
        connect.assert_not_called()
        expected = (
            "BonkScanner will copy and verify all known data on the next start.\n\n"
            f"From:\n{self.data}\n\nTo:\n{target}\n\n"
            "The original files will be kept as a backup."
        )
        self.assertEqual(confirm.call_args.kwargs["message"], expected)
        self.assertEqual(confirm.call_args.kwargs["title"], "Move BonkScanner data?")
        self.assertEqual(notice.call_args.kwargs["title"], "Migration scheduled")
        for arguments in (confirm.call_args.kwargs, notice.call_args.kwargs):
            for value in arguments.values():
                if isinstance(value, str):
                    self.assert_no_private_copy(value)

    def test_cancelled_migration_confirmation_does_not_change_storage(self) -> None:
        page, migration = self.page(self.context())
        with patch.object(module, "ask_app_confirmation", return_value=False), \
             patch.object(module, "show_app_notice") as notice:
            page._schedule_migration(self.root / "destination")
        migration.assert_not_called()
        notice.assert_not_called()

    def test_pending_shared_move_keeps_existing_pending_controls(self) -> None:
        context = replace(
            self.context(status="pending"),
            pending_target=self.root / "destination",
            migration_message="Data will be copied on the next start.",
        )
        page, _ = self.page(context)
        self.assertTrue(page.choose_button.isHidden())
        self.assertTrue(page.move_button.isHidden())
        self.assertFalse(page.cancel_migration_button.isHidden())
        self.assertFalse(page.pending_path_label.isHidden())
        self.assertIn(str(context.pending_target), page.pending_path_label.text())
        self.assert_public_page(page)

    def test_failed_migration_keeps_existing_error_notice(self) -> None:
        page, migration = self.page(self.context())
        migration.return_value = MigrationActionResult(False, "failed", "Destination is in use.")
        with patch.object(module, "ask_app_confirmation", return_value=True), \
             patch.object(module, "show_app_notice") as notice:
            page._schedule_migration(self.root / "destination")
        self.assertEqual(notice.call_args.kwargs["title"], "Migration not scheduled")
        self.assertEqual(notice.call_args.kwargs["message"], "Destination is in use.")
        self.assertTrue(notice.call_args.kwargs["danger"])

    def test_shared_cleanup_guard_remains_without_exposing_other_editions(self) -> None:
        old = self.root / "previous"
        old.mkdir()
        (old / "config.json").write_text("{}", encoding="utf-8")
        context = replace(self.context(status="success"), previous_dir=old)
        page, _ = self.page(context)
        self.assertFalse(page.old_folder_button.isHidden())
        self.assertTrue(page.remove_old_data_button.isHidden())
        self.assert_public_page(page)

    def test_settings_bridge_only_requests_ordinary_migration(self) -> None:
        target = self.root / "destination"
        owner = SimpleNamespace(
            _general_settings_dirty=False, _editable_settings_dirty=False,
        )
        result = MigrationActionResult(True, "pending", "Move scheduled.")
        with patch.object(storage_app, "request_migration", return_value=result) as migration, \
             patch.object(storage_app, "request_shared_folder") as connect:
            actual = SettingsDialog._request_data_migration(owner, target)
        self.assertIs(actual, result)
        migration.assert_called_once_with(target)
        connect.assert_not_called()
