"""The Settings page for BonkScanner's active user-data directory."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.data_storage import (
    MigrationActionResult,
    StorageContext,
    cancel_migration,
    migration_status,
)


class DataStoragePage(QWidget):
    def __init__(
        self,
        *,
        request_migration: Callable[[], MigrationActionResult],
        context_provider: Callable[[], StorageContext] = migration_status,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._request_migration = request_migration
        self._context_provider = context_provider
        self._context = context_provider()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        heading = QLabel("Data storage", self)
        heading.setObjectName("SettingsSectionTitle")
        outer.addWidget(heading)

        description = QLabel(
            "BonkScanner keeps settings, saved recordings, crash logs, and Shady Guy history here.",
            self,
        )
        description.setObjectName("dialogHint")
        description.setWordWrap(True)
        outer.addWidget(description)

        card = QFrame(self)
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 14)
        card_layout.setSpacing(8)

        location_title = QLabel("Current data folder", card)
        location_title.setObjectName("rowLabel")
        card_layout.addWidget(location_title)

        self.current_path_label = QLabel(card)
        self.current_path_label.setObjectName("DataStoragePath")
        self.current_path_label.setWordWrap(True)
        self.current_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card_layout.addWidget(self.current_path_label)

        self.mode_label = QLabel(card)
        self.mode_label.setObjectName("dialogHint")
        self.mode_label.setWordWrap(True)
        card_layout.addWidget(self.mode_label)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 4, 0, 0)
        action_row.setSpacing(8)
        self.open_button = QPushButton("Open data folder", card)
        self.open_button.setObjectName("DataStorageOpen")
        self.open_button.clicked.connect(self._open_current_folder)
        action_row.addWidget(self.open_button)
        action_row.addStretch(1)
        card_layout.addLayout(action_row)
        outer.addWidget(card)

        self.migration_card = QFrame(self)
        self.migration_card.setObjectName("InfoCard")
        migration_layout = QVBoxLayout(self.migration_card)
        migration_layout.setContentsMargins(14, 12, 14, 14)
        migration_layout.setSpacing(8)

        self.migration_title = QLabel("Recommended data folder", self.migration_card)
        self.migration_title.setObjectName("rowLabel")
        migration_layout.addWidget(self.migration_title)

        self.recommended_path_label = QLabel(self.migration_card)
        self.recommended_path_label.setObjectName("DataStorageRecommendedPath")
        self.recommended_path_label.setWordWrap(True)
        self.recommended_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        migration_layout.addWidget(self.recommended_path_label)

        self.migration_note = QLabel(self.migration_card)
        self.migration_note.setObjectName("dialogHint")
        self.migration_note.setWordWrap(True)
        migration_layout.addWidget(self.migration_note)

        migration_actions = QHBoxLayout()
        migration_actions.setContentsMargins(0, 4, 0, 0)
        migration_actions.setSpacing(8)
        self.move_button = QPushButton("Move to recommended folder", self.migration_card)
        self.move_button.setObjectName("DataStorageMove")
        self.move_button.clicked.connect(self._schedule_migration)
        migration_actions.addWidget(self.move_button)
        self.cancel_migration_button = QPushButton("Cancel migration", self.migration_card)
        self.cancel_migration_button.setObjectName("DataStorageCancelMigration")
        self.cancel_migration_button.clicked.connect(self._cancel_migration)
        migration_actions.addWidget(self.cancel_migration_button)
        migration_actions.addStretch(1)
        migration_layout.addLayout(migration_actions)
        outer.addWidget(self.migration_card)

        self.status_label = QLabel(self)
        self.status_label.setObjectName("DataStorageStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.status_label)

        self.old_folder_button = QPushButton("Open old folder", self)
        self.old_folder_button.setObjectName("DataStorageOpenOld")
        self.old_folder_button.clicked.connect(self._open_old_folder)
        outer.addWidget(self.old_folder_button, 0, Qt.AlignLeft)
        outer.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        self._context = self._context_provider()
        context = self._context
        self.current_path_label.setText(str(context.data_dir))
        self.current_path_label.setToolTip(str(context.data_dir))

        if context.mode == "source":
            mode_text = (
                "Source run: data stays in the repository root. Installed-build "
                "migration rules are ignored."
            )
        elif context.mode == "legacy":
            mode_text = "Legacy installation: data is still stored beside BonkScanner.exe."
        else:
            mode_text = "BonkScanner is using the recommended per-user data folder."
        self.mode_label.setText(mode_text)

        show_migration = context.mode == "legacy" and context.recommended_dir is not None
        self.migration_card.setVisible(show_migration)
        if context.recommended_dir is not None:
            self.recommended_path_label.setText(str(context.recommended_dir))
            self.recommended_path_label.setToolTip(str(context.recommended_dir))
        pending = context.migration_status == "pending"
        self.move_button.setVisible(show_migration and not pending)
        self.cancel_migration_button.setVisible(show_migration and pending)
        self.migration_note.setText(
            "The next BonkScanner start will copy and verify all known data. "
            "The original files will remain unchanged."
            if pending
            else "Migration runs on the next start. Files are copied and verified before BonkScanner switches folders; the originals are kept."
        )

        status_parts = []
        if context.migration_status:
            labels = {
                "pending": "Migration scheduled",
                "success": "Migration completed",
                "failed": "Migration was not completed",
                "cancelled": "Migration cancelled",
            }
            status_parts.append(labels.get(context.migration_status, context.migration_status.title()))
        if context.migration_message:
            status_parts.append(context.migration_message)
        self.status_label.setText(" — ".join(status_parts))
        self.status_label.setVisible(bool(status_parts))

        legacy = context.legacy_dir
        show_old = (
            context.mode == "local"
            and context.migration_status == "success"
            and legacy is not None
            and legacy.is_dir()
        )
        self.old_folder_button.setVisible(show_old)

    def _open_folder(self, folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except Exception as exc:
            opened = False
            reason = str(exc)
        else:
            reason = "Windows did not accept the folder request."
        if not opened:
            QMessageBox.warning(
                self,
                "Could Not Open Folder",
                f"BonkScanner could not open this folder.\n\n{folder}\n\n{reason}",
            )

    def _open_current_folder(self) -> None:
        self._open_folder(self._context.data_dir)

    def _open_old_folder(self) -> None:
        if self._context.legacy_dir is not None:
            self._open_folder(self._context.legacy_dir)

    def _schedule_migration(self) -> None:
        context = self._context
        if context.recommended_dir is None:
            return
        choice = QMessageBox.question(
            self,
            "Move BonkScanner Data",
            "BonkScanner will copy and verify all known data on the next start.\n\n"
            f"From:\n{context.data_dir}\n\nTo:\n{context.recommended_dir}\n\n"
            "The original files will be kept as a backup.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if choice != QMessageBox.Yes:
            return
        result = self._request_migration()
        self.refresh()
        if not result.success:
            QMessageBox.warning(self, "Migration Not Scheduled", result.message)
        else:
            QMessageBox.information(
                self,
                "Migration Scheduled",
                result.message + "\n\nClose BonkScanner normally, then start it again.",
            )

    def _cancel_migration(self) -> None:
        choice = QMessageBox.question(
            self,
            "Cancel Data Migration",
            "Cancel the migration scheduled for the next start?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if choice != QMessageBox.Yes:
            return
        result = cancel_migration()
        self.refresh()
        if not result.success:
            QMessageBox.warning(self, "Migration Not Cancelled", result.message)
