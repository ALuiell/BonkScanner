"""Recording selection and a cancellable, bounded loading lane for Roll Analytics."""
from __future__ import annotations

from pathlib import Path
import weakref

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QPushButton, QWidget

from app.latest_wins_loader import LatestWinsLoader
from app.roll_analytics_view import RollRecordingCache


class RollRecordingPicker(QWidget):
    changed = Signal()
    _dispatch = Signal(object)

    def __init__(self, library=None, parent=None):
        super().__init__(parent)
        self._library = library
        self._cache = RollRecordingCache()
        self._lane = None
        self._active = False
        self._generation = 0
        self._library_key = None
        self.path = None
        self.recorded = None
        self.loading = False
        self.error = ""
        self.combo = QComboBox(self)
        self.combo.setMinimumContentsLength(16)
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setToolTip("Choose a saved recording; active recordings are excluded.")
        self.combo.currentIndexChanged.connect(self._choose_current)
        self.latest_button = QPushButton("Latest saved", self)
        self.latest_button.clicked.connect(self._latest)
        self.open_button = QPushButton("Open file…", self)
        self.open_button.clicked.connect(self._browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.latest_button)
        layout.addWidget(self.open_button)
        self._dispatch.connect(self._deliver, Qt.QueuedConnection)
        reference = weakref.ref(self)
        def dispose_on_destroy(*_args):
            owner = reference()
            if owner is not None:
                owner.cancel()
        self.destroyed.connect(dispose_on_destroy)

    def _deliver(self, callback):
        if self._active:
            callback()

    def set_active(self, active):
        self._active = bool(active)
        if not active:
            self.cancel()
            return
        if self._library is not None:
            self._library.ensure_refresh()
        self.refresh_library()
        if self.path is not None and not self.loading:
            self.select_path(self.path)

    def cancel(self):
        self._generation += 1
        self.loading = False
        if self._lane is not None:
            self._lane.dispose()
            self._lane = None

    def refresh_library(self):
        if not self._active:
            return
        entries = tuple(getattr(self._library, "index", ()))
        entries = sorted(
            (entry for entry in entries
             if not self._library.is_active_path(entry.path) and entry.snapshot_count > 0),
            key=lambda entry: (entry.created_at, str(entry.path)), reverse=True,
        )
        key = tuple((str(e.path), e.name, e.created_at) for e in entries)
        if key == self._library_key:
            return
        self._library_key = key
        old_path = str(self.path) if self.path is not None else None
        self.combo.blockSignals(True)
        try:
            self.combo.clear()
            for entry in entries:
                self.combo.addItem(f"{entry.name} · {entry.created_label}", str(entry.path))
            selected = self.combo.findData(old_path) if old_path else -1
            if old_path and selected < 0:
                # An explicitly opened external file need not be in the app library.
                self.combo.addItem(Path(old_path).name, old_path)
                selected = self.combo.count() - 1
            self.combo.setCurrentIndex(selected if selected >= 0 else 0)
        finally:
            self.combo.blockSignals(False)
        self.latest_button.setEnabled(bool(entries))
        if self.path is None and self.combo.count():
            self._choose_current()

    def _latest(self):
        self.refresh_library()
        if self.combo.count() and self._library_key:
            self.combo.setCurrentIndex(0)
            self._choose_current()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select recording", str(self.path.parent) if self.path else "", "BonkScanner recordings (*.jsonl)",
        )
        if path:
            self.select_path(Path(path))

    def _choose_current(self, *_args):
        path = self.combo.currentData()
        if path:
            self.select_path(Path(path))

    def select_path(self, path):
        path = Path(path).resolve()
        if self.loading and self.path == path:
            return
        self.path = path
        self.recorded = None
        self.error = ""
        self._generation += 1
        generation = self._generation
        if self._library is not None and self._library.is_active_path(path):
            self.loading = False
            self.error = "Finish saving this recording before opening its roll analytics."
            self.cancel()
            self.changed.emit()
            return
        selected = self.combo.findData(str(path))
        if selected < 0:
            self.combo.blockSignals(True)
            self.combo.addItem(path.name, str(path))
            selected = self.combo.count() - 1
            self.combo.blockSignals(False)
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(selected)
        self.combo.setToolTip(str(path))
        self.combo.blockSignals(False)
        self.loading = True
        self.changed.emit()
        if self._lane is None:
            self._lane = LatestWinsLoader(schedule=self._dispatch.emit, thread_name="roll-recording")

        def complete(result, error):
            if not self._active or generation != self._generation:
                return
            self.loading = False
            self.recorded = result if error is None else None
            self.error = str(error) if error is not None else ""
            if result is not None:
                self.combo.setItemText(self.combo.currentIndex(), result.name)
            self.changed.emit()

        self._lane.submit(
            path,
            load=lambda value, event, _progress: self._cache.load(value, cancelled=event.is_set),
            complete=complete, cancellable=True,
        )
