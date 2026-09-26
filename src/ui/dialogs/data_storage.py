"""The Settings page for BonkScanner's active user-data directory."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.data_storage import (
    MigrationActionResult,
    StorageContext,
    cancel_migration,
    legacy_data_exists,
    migration_status,
    remove_legacy_data,
)
from ui.dialogs.shell import ask_app_confirmation, show_app_notice


class DataStoragePage(QWidget):
    def __init__(
        self,
        *,
        request_migration: Callable[..., MigrationActionResult],
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

        self.pending_path_label = QLabel(self.migration_card)
        self.pending_path_label.setObjectName("DataStoragePendingPath")
        self.pending_path_label.setWordWrap(True)
        self.pending_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        migration_layout.addWidget(self.pending_path_label)

        self.migration_note = QLabel(self.migration_card)
        self.migration_note.setObjectName("dialogHint")
        self.migration_note.setWordWrap(True)
        migration_layout.addWidget(self.migration_note)

        migration_actions = QHBoxLayout()
        migration_actions.setContentsMargins(0, 4, 0, 0)
        migration_actions.setSpacing(8)
        self.move_button = QPushButton("Use recommended folder", self.migration_card)
        self.move_button.setObjectName("DataStorageMove")
        self.move_button.clicked.connect(lambda: self._schedule_migration())
        migration_actions.addWidget(self.move_button)
        self.choose_button = QPushButton("Choose another folder…", self.migration_card)
        self.choose_button.setObjectName("DataStorageChoose")
        self.choose_button.clicked.connect(self._choose_folder)
        migration_actions.addWidget(self.choose_button)
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
        self.remove_old_data_button = QPushButton("Remove old data", self)
        self.remove_old_data_button.setObjectName("danger")
        self.remove_old_data_button.clicked.connect(self._remove_old_data)
        legacy_actions = QHBoxLayout()
        legacy_actions.setContentsMargins(0, 0, 0, 0)
        legacy_actions.setSpacing(8)
        legacy_actions.addWidget(self.old_folder_button)
        legacy_actions.addWidget(self.remove_old_data_button)
        legacy_actions.addStretch(1)
        outer.addLayout(legacy_actions)
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
        elif context.data_dir == context.recommended_dir:
            mode_text = "BonkScanner is using the recommended per-user data folder."
        else:
            mode_text = "BonkScanner is using a folder you selected."
        self.mode_label.setText(mode_text)

        show_migration = context.can_migrate
        self.migration_card.setVisible(show_migration)
        if context.recommended_dir is not None:
            self.recommended_path_label.setText(str(context.recommended_dir))
            self.recommended_path_label.setToolTip(str(context.recommended_dir))
        pending = context.migration_status == "pending"
        self.move_button.setVisible(
            show_migration and not pending and context.data_dir != context.recommended_dir
        )
        self.choose_button.setVisible(show_migration and not pending)
        self.cancel_migration_button.setVisible(show_migration and pending)
        self.pending_path_label.setVisible(pending)
        if pending and context.pending_target is not None:
            self.pending_path_label.setText(f"Scheduled destination: {context.pending_target}")
        self.migration_note.setText(
            "The next BonkScanner start will copy and verify all known data. "
            "The original files will remain unchanged."
            if pending
            else "Choose a destination. On the next start, files are copied and verified before BonkScanner switches folders; the originals are kept."
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
        if context.migration_message and not context.legacy_cleanup_status:
            status_parts.append(context.migration_message)
        if context.legacy_cleanup_status:
            cleanup_labels = {
                "success": "Old data removed",
                "partial": "Old data removal incomplete",
                "failed": "Old data was not removed",
            }
            status_parts.append(
                cleanup_labels.get(
                    context.legacy_cleanup_status,
                    context.legacy_cleanup_status.title(),
                )
            )
        if context.legacy_cleanup_message:
            status_parts.append(context.legacy_cleanup_message)
        self.status_label.setText(" — ".join(status_parts))
        self.status_label.setVisible(bool(status_parts))

        legacy = context.previous_dir or context.legacy_dir
        show_old = (
            context.mode == "local"
            and legacy is not None
            and legacy.is_dir()
            and legacy != context.data_dir
        )
        self.old_folder_button.setVisible(show_old)
        self.remove_old_data_button.setVisible(
            show_old
            and context.migration_status == "success"
            and legacy_data_exists(legacy)
        )

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
            show_app_notice(
                self,
                title="Could not open folder",
                subtitle="Data storage",
                message=f"BonkScanner could not open this folder.\n\n{folder}\n\n{reason}",
                danger=True,
            )

    def _open_current_folder(self) -> None:
        self._open_folder(self._context.data_dir)

    def _open_old_folder(self) -> None:
        previous = self._context.previous_dir or self._context.legacy_dir
        if previous is not None:
            self._open_folder(previous)

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose BonkScanner data folder", str(self._context.data_dir.parent)
        )
        if chosen:
            self._schedule_migration(Path(chosen))

    def _schedule_migration(self, destination: Path | None = None) -> None:
        context = self._context
        if context.recommended_dir is None:
            return
        target = destination or context.recommended_dir
        confirmed = ask_app_confirmation(
            self,
            title="Move BonkScanner data?",
            subtitle="Data storage",
            message="BonkScanner will copy and verify all known data on the next start.\n\n"
            f"From:\n{context.data_dir}\n\nTo:\n{target}\n\n"
            "The original files will be kept as a backup.",
            confirm_text="Schedule migration",
            note="Nothing is moved during the current session.",
        )
        if not confirmed:
            return
        result = self._request_migration(target) if destination is not None else self._request_migration()
        self.refresh()
        if not result.success:
            show_app_notice(
                self,
                title="Migration not scheduled",
                subtitle="Data storage",
                message=result.message,
                danger=True,
            )
        else:
            show_app_notice(
                self,
                title="Migration scheduled",
                subtitle="Data storage",
                message=result.message
                + "\n\nClose BonkScanner normally, then start it again.",
                button_text="Got it",
            )

    def _cancel_migration(self) -> None:
        confirmed = ask_app_confirmation(
            self,
            title="Cancel data migration?",
            subtitle="Data storage",
            message="Cancel the migration scheduled for the next start?",
            confirm_text="Cancel migration",
        )
        if not confirmed:
            return
        result = cancel_migration()
        self.refresh()
        if not result.success:
            show_app_notice(
                self,
                title="Migration not cancelled",
                subtitle="Data storage",
                message=result.message,
                danger=True,
            )

    def _remove_old_data(self) -> None:
        legacy = self._context.previous_dir or self._context.legacy_dir
        if legacy is None:
            return
        confirmed = ask_app_confirmation(
            self,
            title="Remove old BonkScanner data?",
            subtitle="Data storage",
            message=(
                "BonkScanner will permanently remove the migrated settings, recordings, "
                f"Shady Guy history, and logs from:\n\n{legacy}"
            ),
            confirm_text="Remove old data",
            note=(
                "This cannot be undone. The storage selection record, BonkScanner.exe, "
                "updater files, unknown files, and unfinished temporary files will remain. "
                "Other BonkScanner copies may share this old folder."
            ),
            destructive=True,
        )
        if not confirmed:
            return
        result = remove_legacy_data()
        self.refresh()
        show_app_notice(
            self,
            title=("Old data removed" if result.success else "Old data not fully removed"),
            subtitle="Data storage",
            message=result.message,
            danger=not result.success,
            button_text="Done" if result.success else "Close",
        )
