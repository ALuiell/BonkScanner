"""Shared visual building blocks for recording-library pickers."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

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
        self.set_metadata(vod, longest_seconds=longest_seconds)

    def set_metadata(self, vod, *, longest_seconds: int, live: bool = False) -> None:
        """Update an existing row; live duration changes must not rebuild lists."""
        self.metadata = vod
        name = str(getattr(vod, "name", "") or "Unnamed recording")
        self._name_label.setText(name)
        created_label = str(getattr(vod, "created_label", "") or "")
        snapshot_count = max(0, int(getattr(vod, "snapshot_count", 0) or 0))
        duration_seconds = max(0, int(getattr(vod, "duration_seconds", 0) or 0))
        parts = [f"{snapshot_count} snapshots", formatting.format_duration(duration_seconds)]
        if live:
            parts.insert(0, "LIVE")
        elif created_label and created_label not in name:
            parts.insert(0, created_label)
        self._meta_label.setText("  ·  ".join(parts))
        longest = max(1, int(longest_seconds))
        self._bar.setValue(round(min(1.0, duration_seconds / longest) * 1000))


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
