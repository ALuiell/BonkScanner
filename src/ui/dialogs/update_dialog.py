from __future__ import annotations

import re
from typing import Callable, Literal

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.version import CURRENT_VERSION
from core.update_types import PreparedUpdate, ReleaseInfo
from ui.dialogs.shell import DIALOG_REGULAR, dialog_body, dialog_footer


UpdateDecision = Literal["later", "skip", "update"]
StartDownload = Callable[
    [Callable[[int, int], None], Callable[[PreparedUpdate], None], Callable[[str], None]],
    object,
]
InstallUpdate = Callable[[PreparedUpdate], None]


class UpdateDialog(QDialog):
    """Release notes, verified download progress, and restart in one surface."""

    progress_changed = Signal(int, int)
    download_ready = Signal(object)
    download_failed = Signal(str)

    def __init__(
        self,
        parent,
        release: ReleaseInfo,
        *,
        start_download: StartDownload,
        install_update: InstallUpdate,
    ) -> None:
        super().__init__(parent)
        self.release = release
        self.decision: UpdateDecision = "later"
        self._start_download = start_download
        self._install_update = install_update
        self._busy = False
        self._allow_close = False
        self._prepared: PreparedUpdate | None = None
        self._installer_scheduled = False
        self._installer_launched = False

        self.setWindowTitle("BonkScanner Update")
        layout = dialog_body(
            self,
            title="BonkScanner update",
            subtitle="A verified update is ready to download.",
            width=DIALOG_REGULAR,
            height=540,
        )

        summary = QFrame(self)
        summary.setObjectName("UpdateSummaryCard")
        summary_row = QHBoxLayout(summary)
        summary_row.setContentsMargins(14, 11, 14, 11)
        summary_row.setSpacing(10)
        current = QLabel(f"v{CURRENT_VERSION}", summary)
        current.setObjectName("UpdateVersionOld")
        arrow = QLabel("→", summary)
        arrow.setObjectName("UpdateVersionArrow")
        latest = QLabel(f"v{release.version}", summary)
        latest.setObjectName("UpdateVersionNew")
        verified = QLabel("SHA-256 verified before restart", summary)
        verified.setObjectName("UpdateTrustNote")
        summary_row.addWidget(current)
        summary_row.addWidget(arrow)
        summary_row.addWidget(latest)
        summary_row.addStretch(1)
        summary_row.addWidget(verified)
        layout.addWidget(summary)

        notes_title = QLabel("What’s new", self)
        notes_title.setObjectName("UpdateSectionTitle")
        layout.addWidget(notes_title)

        self.notes = QTextEdit(self)
        self.notes.setObjectName("UpdateReleaseNotes")
        self.notes.setReadOnly(True)
        self.notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        _set_release_notes_content(self.notes, release.notes)
        layout.addWidget(self.notes, 1)

        self.progress_panel = QFrame(self)
        self.progress_panel.setObjectName("UpdateProgressPanel")
        progress_layout = QVBoxLayout(self.progress_panel)
        progress_layout.setContentsMargins(14, 11, 14, 11)
        progress_layout.setSpacing(7)
        self.progress_status = QLabel("Preparing download…", self.progress_panel)
        self.progress_status.setObjectName("UpdateProgressStatus")
        progress_layout.addWidget(self.progress_status)
        self.progress_bar = QProgressBar(self.progress_panel)
        self.progress_bar.setObjectName("UpdateDownloadProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_bar)
        self.progress_detail = QLabel("0 MB of 0 MB", self.progress_panel)
        self.progress_detail.setObjectName("UpdateProgressDetail")
        progress_layout.addWidget(self.progress_detail)
        self.progress_panel.hide()
        layout.addWidget(self.progress_panel)

        self.skip_button = QPushButton(f"Skip v{release.version}", self)
        self.skip_button.setObjectName("ghost")
        self.skip_button.setProperty("footerEdge", True)
        self.skip_button.clicked.connect(self._choose_skip)
        self.later_button = QPushButton("Later", self)
        self.later_button.clicked.connect(self.reject)
        self.update_button = QPushButton("Update and restart", self)
        self.update_button.clicked.connect(self._begin_download)
        dialog_footer(
            self,
            primary=self.update_button,
            secondary=self.later_button,
            leading=self.skip_button,
        )

        self.progress_changed.connect(self._on_progress)
        self.download_ready.connect(self._on_download_ready)
        self.download_failed.connect(self._on_download_failed)

    def _choose_skip(self) -> None:
        if self._busy:
            return
        self.decision = "skip"
        super().reject()

    def reject(self) -> None:
        if self._busy and not self._allow_close:
            return
        if not self._installer_launched:
            self.decision = "later"
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if self._busy and not self._allow_close:
            event.ignore()
            return
        event.accept()

    def _set_progress_state(self, state: str) -> None:
        self.progress_panel.setProperty("state", state)
        self.progress_bar.setProperty("state", state)
        for widget in (self.progress_panel, self.progress_bar):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _begin_download(self) -> None:
        if self._busy:
            return
        self.decision = "update"
        self._busy = True
        self._allow_close = False
        self._prepared = None
        self._installer_scheduled = False
        self._installer_launched = False
        self.progress_panel.show()
        self.progress_status.setText("Downloading update…")
        self.progress_detail.setText("Connecting securely to GitHub…")
        self.progress_bar.setValue(0)
        self._set_progress_state("downloading")
        self.update_button.setText("Downloading…")
        self.update_button.setEnabled(False)
        self.later_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        try:
            self._start_download(
                self.progress_changed.emit,
                self.download_ready.emit,
                self.download_failed.emit,
            )
        except Exception as exc:
            self._on_download_failed(str(exc))

    def _on_progress(self, downloaded: int, total: int) -> None:
        if not self._busy or self._installer_scheduled:
            return
        total = max(1, int(total))
        downloaded = max(0, min(int(downloaded), total))
        percentage = max(0, min(100, int(downloaded * 100 / total)))
        self.progress_bar.setValue(percentage)
        self.progress_detail.setText(
            f"{_format_bytes(downloaded)} of {_format_bytes(total)}  ·  {percentage}%"
        )
        if downloaded >= total:
            self.progress_status.setText("Verifying SHA-256 integrity…")
            self._set_progress_state("verifying")

    def _on_download_ready(self, prepared: PreparedUpdate) -> None:
        if not self._busy or self._installer_scheduled:
            return
        if not isinstance(prepared, PreparedUpdate):
            self._on_download_failed("The updater returned an invalid prepared update.")
            return
        self._installer_scheduled = True
        self._prepared = prepared
        self.progress_bar.setValue(100)
        self.progress_status.setText("Verified — restarting BonkScanner…")
        self.progress_detail.setText(
            f"{_format_bytes(prepared.downloaded_size)} downloaded and verified"
        )
        self.update_button.setText("Restarting…")
        self._set_progress_state("verified")
        # Give Qt a context object so deleting the modal during application
        # shutdown cancels the callback instead of invoking a dead wrapper.
        QTimer.singleShot(700, self, self._launch_installer)

    def _launch_installer(self) -> None:
        if not self._busy or self._installer_launched:
            return
        if self._prepared is None:
            self._on_download_failed("The verified update is no longer available.")
            return
        self._installer_launched = True
        try:
            self._install_update(self._prepared)
        except Exception as exc:
            self._installer_launched = False
            self._on_download_failed(str(exc))
            return
        # The parent application now follows its normal shutdown path. Its close
        # event must be allowed to close this modal child too.
        self._allow_close = True

    def _on_download_failed(self, message: str) -> None:
        if self._installer_launched:
            # A completed worker must not be able to re-lock the modal after
            # the helper was launched and clean application shutdown was queued.
            return
        self._busy = False
        self._allow_close = False
        self._prepared = None
        self._installer_scheduled = False
        self._installer_launched = False
        self.progress_panel.show()
        self.progress_status.setText("Update could not be installed")
        self.progress_detail.setText(message or "Unknown updater error.")
        self.progress_bar.setValue(0)
        self._set_progress_state("error")
        self.update_button.setText("Retry download")
        self.update_button.setEnabled(True)
        self.later_button.setEnabled(True)
        self.skip_button.setEnabled(True)


def show_update_dialog(
    parent,
    release: ReleaseInfo,
    *,
    start_download: StartDownload,
    install_update: InstallUpdate,
) -> UpdateDecision:
    dialog = UpdateDialog(
        parent,
        release,
        start_download=start_download,
        install_update=install_update,
    )
    try:
        dialog.exec()
        return dialog.decision
    finally:
        # The update surface is created for one modal session. Explicit
        # deferred deletion prevents closed child dialogs accumulating on the
        # main window and also cancels context-bound timers.
        dialog.deleteLater()


def _format_bytes(value: int) -> str:
    size = max(0, int(value))
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _set_release_notes_content(notes: QTextEdit, release_notes: str) -> None:
    if _looks_like_html(release_notes):
        try:
            notes.setHtml(release_notes)
            return
        except Exception:
            pass

    try:
        notes.setMarkdown(release_notes)
        return
    except Exception:
        notes.setPlainText(release_notes)


def _looks_like_html(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return re.search(r"<[A-Za-z][^>]*>", text) is not None
