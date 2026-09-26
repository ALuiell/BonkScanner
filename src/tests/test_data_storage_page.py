from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QPushButton

from infra.data_storage import MigrationActionResult, StorageContext
from ui.dialogs import data_storage as data_storage_dialogs
from ui.dialogs.data_storage import DataStoragePage
from ui.dialogs.shell import AppConfirmDialog, AppNoticeDialog, DIALOG_REGULAR


class DataStoragePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def page(self, context: StorageContext, request=None) -> DataStoragePage:
        return DataStoragePage(
            request_migration=request or MagicMock(),
            context_provider=lambda: context,
        )

    def test_storage_popups_use_the_shared_dialog_chrome(self) -> None:
        confirm = AppConfirmDialog(
            None,
            title="Move BonkScanner data?",
            subtitle="Data storage",
            message="From:\nC:\\Old\n\nTo:\nC:\\New",
            confirm_text="Schedule migration",
        )
        notice = AppNoticeDialog(
            None,
            title="Migration not scheduled",
            subtitle="Data storage",
            message="Access denied",
            danger=True,
        )
        try:
            self.assertGreaterEqual(confirm.minimumWidth(), DIALOG_REGULAR)
            self.assertIsNotNone(confirm.findChild(QFrame, "dialogHeadRule"))
            self.assertIsNotNone(confirm.findChild(QFrame, "InfoCard"))
            primary = confirm.findChild(QPushButton, "primary")
            self.assertIsNotNone(primary)
            self.assertEqual(primary.text(), "Schedule migration")

            self.assertGreaterEqual(notice.minimumWidth(), DIALOG_REGULAR)
            self.assertIsNotNone(notice.findChild(QFrame, "dialogHeadRule"))
            self.assertIsNotNone(notice.findChild(QFrame, "DangerInfoCard"))
            self.assertTrue(notice.isModal())
        finally:
            confirm.close()
            notice.close()

    def test_destructive_confirmation_uses_danger_chrome(self) -> None:
        confirm = AppConfirmDialog(
            None,
            title="Remove old BonkScanner data?",
            subtitle="Data storage",
            message="This action permanently removes migrated legacy data.",
            confirm_text="Remove old data",
            destructive=True,
        )
        try:
            self.assertIsNotNone(confirm.findChild(QFrame, "DangerInfoCard"))
            danger = confirm.findChild(QPushButton, "danger")
            self.assertIsNotNone(danger)
            self.assertEqual(danger.text(), "Remove old data")
        finally:
            confirm.close()

    def test_source_mode_shows_project_path_without_migration_controls(self) -> None:
        context = StorageContext(
            mode="source",
            installation_dir=self.root,
            data_dir=self.root,
            recommended_dir=None,
            installation_key=None,
        )
        page = self.page(context)
        try:
            page.show()
            QApplication.processEvents()
            self.assertEqual(page.current_path_label.text(), str(self.root))
            self.assertTrue(
                page.current_path_label.textInteractionFlags()
                & Qt.TextSelectableByMouse
            )
            self.assertTrue(page.migration_card.isHidden())
        finally:
            page.close()

    def test_legacy_mode_schedules_migration_and_then_shows_cancel(self) -> None:
        local = self.root / "local"
        contexts = [
            StorageContext(
                mode="legacy",
                installation_dir=self.root,
                data_dir=self.root,
                recommended_dir=local,
                installation_key="key",
            ),
            StorageContext(
                mode="legacy",
                installation_dir=self.root,
                data_dir=self.root,
                recommended_dir=local,
                installation_key="key",
                migration_status="pending",
                migration_message="Migration is scheduled for the next BonkScanner start.",
            ),
        ]
        request = MagicMock(
            return_value=MigrationActionResult(True, "pending", "Migration scheduled.")
        )
        index = {"value": 0}
        page = DataStoragePage(
            request_migration=request,
            context_provider=lambda: contexts[index["value"]],
        )
        original_request = page._request_migration

        def request_and_advance():
            result = original_request()
            index["value"] = 1
            return result

        page._request_migration = request_and_advance
        try:
            page.show()
            QApplication.processEvents()
            with patch.object(
                data_storage_dialogs, "ask_app_confirmation", return_value=True
            ) as confirm, patch.object(
                data_storage_dialogs, "show_app_notice"
            ) as notice:
                page._schedule_migration()
            confirm.assert_called_once()
            notice.assert_called_once()
            request.assert_called_once_with()
            self.assertTrue(page.move_button.isHidden())
            self.assertFalse(page.cancel_migration_button.isHidden())
            self.assertIn("Migration scheduled", page.status_label.text())
        finally:
            page.close()

    def test_installed_mode_can_choose_a_folder_after_initial_setup(self) -> None:
        local = self.root / "local"
        custom = self.root / "chosen"
        contexts = [
            StorageContext(
                mode="local",
                installation_dir=self.root,
                data_dir=local,
                recommended_dir=local,
                installation_key="key",
            ),
            StorageContext(
                mode="local",
                installation_dir=self.root,
                data_dir=local,
                recommended_dir=local,
                installation_key="key",
                migration_status="pending",
                pending_target=custom,
            ),
        ]
        selected = {"index": 0}

        def request(destination):
            self.assertEqual(destination, custom)
            selected["index"] = 1
            return MigrationActionResult(True, "pending", "Scheduled.")

        page = DataStoragePage(
            request_migration=request,
            context_provider=lambda: contexts[selected["index"]],
        )
        try:
            page.show()
            QApplication.processEvents()
            self.assertFalse(page.choose_button.isHidden())
            self.assertTrue(page.move_button.isHidden())
            with patch.object(
                data_storage_dialogs.QFileDialog,
                "getExistingDirectory",
                return_value=str(custom),
            ), patch.object(
                data_storage_dialogs, "ask_app_confirmation", return_value=True
            ) as confirm, patch.object(data_storage_dialogs, "show_app_notice"):
                page._choose_folder()
            self.assertIn(str(custom), confirm.call_args.kwargs["message"])
            self.assertIn(str(custom), page.pending_path_label.text())
            self.assertFalse(page.cancel_migration_button.isHidden())
        finally:
            page.close()

    def test_success_mode_exposes_old_folder(self) -> None:
        local = self.root / "local"
        local.mkdir()
        (self.root / "config.json").write_text("{}", encoding="utf-8")
        context = StorageContext(
            mode="local",
            installation_dir=self.root,
            data_dir=local,
            recommended_dir=local,
            installation_key="key",
            migration_status="success",
            migration_message="Data was copied and verified.",
            legacy_dir=self.root,
        )
        page = self.page(context)
        try:
            page.show()
            QApplication.processEvents()
            self.assertFalse(page.old_folder_button.isHidden())
            self.assertFalse(page.remove_old_data_button.isHidden())
            self.assertIn("Migration completed", page.status_label.text())
        finally:
            page.close()

    def test_custom_folder_move_can_offer_cleanup_of_previous_appdata(self) -> None:
        local = self.root / "local"
        local.mkdir()
        (local / "config.json").write_text("{}", encoding="utf-8")
        custom = self.root / "custom"
        custom.mkdir()
        context = StorageContext(
            mode="local",
            installation_dir=self.root,
            data_dir=custom,
            recommended_dir=local,
            installation_key="key",
            migration_status="success",
            previous_dir=local,
        )
        page = self.page(context)
        try:
            page.show()
            QApplication.processEvents()
            self.assertFalse(page.old_folder_button.isHidden())
            self.assertFalse(page.remove_old_data_button.isHidden())
            self.assertFalse(page.move_button.isHidden())
        finally:
            page.close()

    def test_remove_old_data_uses_destructive_confirmation_and_refreshes(self) -> None:
        local = self.root / "local"
        local.mkdir()
        old_config = self.root / "config.json"
        old_config.write_text("{}", encoding="utf-8")
        context = StorageContext(
            mode="local",
            installation_dir=self.root,
            data_dir=local,
            recommended_dir=local,
            installation_key="key",
            migration_status="success",
            migration_message="Data was copied and verified.",
            legacy_dir=self.root,
        )
        page = self.page(context)

        def remove():
            old_config.unlink()
            return MigrationActionResult(True, "success", "Old data removed.")

        try:
            page.show()
            QApplication.processEvents()
            with patch.object(
                data_storage_dialogs, "ask_app_confirmation", return_value=True
            ) as confirmation, patch.object(
                data_storage_dialogs, "remove_legacy_data", side_effect=remove
            ) as cleanup, patch.object(
                data_storage_dialogs, "show_app_notice"
            ) as notice:
                page._remove_old_data()

            self.assertTrue(confirmation.call_args.kwargs["destructive"])
            cleanup.assert_called_once_with()
            notice.assert_called_once()
            self.assertTrue(page.remove_old_data_button.isHidden())
            self.assertFalse(page.old_folder_button.isHidden())
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
