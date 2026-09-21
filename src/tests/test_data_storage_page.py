from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from infra.data_storage import MigrationActionResult, StorageContext
from ui.dialogs.data_storage import DataStoragePage


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
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes), patch.object(
                QMessageBox, "information"
            ):
                page._schedule_migration()
            request.assert_called_once_with()
            self.assertTrue(page.move_button.isHidden())
            self.assertFalse(page.cancel_migration_button.isHidden())
            self.assertIn("Migration scheduled", page.status_label.text())
        finally:
            page.close()

    def test_success_mode_exposes_old_folder(self) -> None:
        local = self.root / "local"
        local.mkdir()
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
            self.assertIn("Migration completed", page.status_label.text())
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
