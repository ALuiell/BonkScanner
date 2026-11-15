"""Icon-only height selector shared by the recording timelines."""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QButtonGroup

from app.vod_library import TIMELINE_COMPACT, TIMELINE_EXPANDED, TIMELINE_STANDARD
from ui import i18n as l10n
from ui.segmented_toggle import SegmentedToggle


def _draw_timeline_icon(height: int, color: str) -> QPixmap:
    pixmap = QPixmap(40, 40)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.25, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawRoundedRect(QRectF(2.5, (21 - height) / 2, 15, height - 1), 2, 2)
    rise = min(2.0, height * 0.18)
    painter.drawPolyline(QPolygonF([
        QPointF(5.5, 10 + rise), QPointF(8, 10), QPointF(11, 10.4), QPointF(14.5, 10 - rise),
    ]))
    painter.end()
    return pixmap


class TimelineSizeToggle(SegmentedToggle):
    def __init__(self, mode: str = TIMELINE_STANDARD) -> None:
        modes = (
            (TIMELINE_EXPANDED, l10n.tr("Expanded timeline"), 16),
            (TIMELINE_STANDARD, l10n.tr("Standard timeline (default)"), 12),
            (TIMELINE_COMPACT, l10n.tr("Compact timeline"), 8),
        )
        super().__init__(tuple((key, "", "timeline-size") for key, _, _ in modes), disable_inactive=False)
        self.setProperty("timelineSizeToggle", "true")
        self.layout().setContentsMargins(2, 1, 2, 1)
        self.layout().setSpacing(2)
        l10n.display(self, "setAccessibleName", l10n.tr("Timeline height"))

        group = QButtonGroup(self)
        for key, label, height in modes:
            button = self.segment(key)
            button.setCheckable(True)
            group.addButton(button)
            button.setFixedSize(26, 22)
            button.setIconSize(QSize(19, 19))
            icon = QIcon(_draw_timeline_icon(height, "#98A7BA"))
            icon.addPixmap(_draw_timeline_icon(height, "#EDF1F5"), QIcon.Normal, QIcon.On)
            button.setIcon(icon)
            l10n.display(button, "setToolTip", label)
            l10n.display(button, "setAccessibleName", label)
        self.set_active(mode)

    def set_active(self, key: str, *, variant: str = "") -> None:
        super().set_active(key, variant=variant)
        self.segment(key).setChecked(True)
