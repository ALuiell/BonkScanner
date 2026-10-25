"""Shared visual building blocks for recording-library pickers."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QListWidgetItem, QProgressBar, QVBoxLayout, QWidget

from projections import formatting


class RecordingLibraryRow(QWidget):
    """One recording row: name, metadata, and relative-duration bar.

    Both Recordings and Compare Runs use this exact widget. Selection colour
    belongs to the containing list because Compare Runs gives A and B different
    accents; the row itself stays transparent so that colour remains visible.
    """

    def __init__(
        self,
        vod,
        *,
        longest_seconds: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RecordingRow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(3)

        self._name_label = QLabel()
        self._name_label.setObjectName("RecordingRowName")
        layout.addWidget(self._name_label)
        self._meta_label = QLabel()
        self._meta_label.setObjectName("RecordingRowMeta")
        layout.addWidget(self._meta_label)
        self._bar = QProgressBar()
        self._bar.setObjectName("RecordingRowBar")
        self._bar.setRange(0, 1000)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(3)
        layout.addWidget(self._bar)
        self.metadata = None
        self._display_signature = None
        self.set_metadata(vod, longest_seconds=longest_seconds)

    def set_metadata(self, vod, *, longest_seconds: int, live: bool = False) -> None:
        """Update an existing row; live duration changes must not rebuild lists."""
        self.metadata = vod
        name = str(getattr(vod, "name", "") or "Unnamed recording")
        created_label = str(getattr(vod, "created_label", "") or "")
        snapshot_count = max(0, int(getattr(vod, "snapshot_count", 0) or 0))
        duration_seconds = max(0, int(getattr(vod, "duration_seconds", 0) or 0))
        longest = max(1, int(longest_seconds))
        signature = (name, created_label, snapshot_count, duration_seconds, longest, live)
        if signature == self._display_signature:
            return
        self._display_signature = signature
        self._name_label.setText(name)
        parts = [f"{snapshot_count} snapshots", formatting.format_duration(duration_seconds)]
        if live:
            parts.insert(0, "LIVE")
        elif created_label and created_label not in name:
            parts.insert(0, created_label)
        self._meta_label.setText("  ·  ".join(parts))
        self._bar.setValue(round(min(1.0, duration_seconds / longest) * 1000))


class RecordingLibraryItem(QListWidgetItem):
    """Sort existing rows in place, keeping their widgets and selection alive."""

    sort_rank = 0

    def __lt__(self, other) -> bool:
        return self.sort_rank < getattr(other, "sort_rank", 0)


def sync_recording_rows(
    list_frame, vods, items, rows, *, longest_seconds,
    is_live, batch_size: int = 0, search_role=None,
):
    """Reconcile metadata without rebuilding unchanged Qt widget subtrees.

    Only new recordings pay for construction/QSS polish. Initial staged pages
    can yield between small batches; sorting uses Qt's model to move existing
    items, which also preserves their attached widgets.
    """
    available = {str(vod.path) for vod in vods}
    blocked = list_frame.blockSignals(True)
    signals_held = True
    try:
        for row in range(list_frame.count() - 1, -1, -1):
            if not list_frame.item(row).data(Qt.UserRole):
                list_frame.takeItem(row)
        for key in tuple(items):
            if key not in available:
                item = items.pop(key)
                rows.pop(key, None)
                list_frame.takeItem(list_frame.row(item))
        # Remove the empty-library placeholder before real rows arrive.
        if not items:
            list_frame.clear()
        for rank, vod in enumerate(vods):
            key = str(vod.path)
            item = items.get(key)
            if item is None:
                item = RecordingLibraryItem()
                item.setData(Qt.UserRole, key)
                widget = RecordingLibraryRow(vod, longest_seconds=longest_seconds)
                item.setSizeHint(widget.sizeHint())
                list_frame.addItem(item)
                list_frame.setItemWidget(item, widget)
                items[key] = item
                rows[key] = widget
            item.sort_rank = rank
            rows[key].set_metadata(vod, longest_seconds=longest_seconds, live=is_live(vod.path))
            if search_role is not None:
                item.setData(search_role, recording_search_text(vod))
            if batch_size and (rank + 1) % batch_size == 0:
                list_frame.blockSignals(blocked)
                signals_held = False
                yield None
                list_frame.blockSignals(True)
                signals_held = True
        if any(
            str(vod.path) != list_frame.item(rank).data(Qt.UserRole)
            for rank, vod in enumerate(vods)
        ):
            list_frame.sortItems()
        if not vods:
            item = QListWidgetItem("No saved recordings")
            item.setFlags(Qt.NoItemFlags)
            list_frame.addItem(item)
    finally:
        # A staged iterator may be closed after Qt has destroyed the page.
        # No widget access is needed when the iterator is paused at a yield.
        if signals_held:
            list_frame.blockSignals(blocked)


def recording_search_text(vod) -> str:
    """Normalized searchable metadata for a row-backed list item."""

    return " ".join(
        (
            str(getattr(vod, "name", "") or ""),
            str(getattr(vod, "created_label", "") or ""),
            str(getattr(vod, "snapshot_count", "") or ""),
            formatting.format_duration(
                max(0, int(getattr(vod, "duration_seconds", 0) or 0))
            ),
        )
    ).casefold()
