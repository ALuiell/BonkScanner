"""Isolated examples rendered by Scanner's merchant UI components."""
from types import SimpleNamespace

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from core.map_markers import MapMarkerSnapshot, MapViewport, MerchantOffer, MerchantStockCapture, WorldMapMarker
from core.merchant_analytics import MerchantHistoryRecord, aggregate_merchant_history
from ui.shared import resource_path
from ui import i18n as l10n
from ui.dialogs.merchant_analytics import MerchantAnalyticsWindow
from .guide_locale import bind, message
from .overlay_previews import OverlayPreviewWidgets

_MAP = resource_path("media/guides/map-scene.jpg")


class _StockScene(QWidget):
    def __init__(self, widgets: OverlayPreviewWidgets):
        super().__init__()
        self._map = QPixmap(str(_MAP))
        self._layer = widgets.map_markers(self)
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layer.setGeometry(self.rect())
        marker = WorldMapMarker('example', 'shady_guy_blue', 0, 0, object_ptr=1)
        stock = MerchantStockCapture(1, 1, 'example', 1, 0, 0, (
            MerchantOffer(1, 'Beer', 'Beer', 'UNCOMMON', 999),
            MerchantOffer(22, 'Dragonfire', 'Dragonfire', 'LEGENDARY', 1500),
            MerchantOffer(26, 'Overpowered Lamp', 'Overpowered Lamp', 'LEGENDARY', 2100),
        ))
        self._layer.set_snapshot(MapMarkerSnapshot(map_id=1, map_open=True, world_size=600,
            viewport=MapViewport(0, 0, self.width(), self.height()), markers=(marker,),
            merchant_stocks=(stock,)), scale=1, style='modern', merchant_stock_display='always')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#16232b'))
        if not self._map.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            src = QRectF(self._map.rect())
            aspect = self.width() / max(1, self.height())
            if src.width() / src.height() > aspect:
                inset = (src.width() - src.height() * aspect) / 2
                src.adjust(inset, 0, -inset, 0)
            else:
                inset = (src.height() - src.width() / aspect) / 2
                src.adjust(0, inset, 0, -inset)
            painter.drawPixmap(QRectF(self.rect()), self._map, src)
        painter.end()


class _FixtureService:
    def __init__(self):
        self._records = tuple(MerchantHistoryRecord('map' + str(i), 'merchant' + str(i),
            'forest_desert' if i % 2 else 'graveyard', 1 + i % 4,
            ('white', 'blue', 'purple', 'gold')[i % 4],
            ((1, 22, 26), (1, 22, 3), (1, 26, 4), (22, 26, 5))[i % 4]) for i in range(24))

    def status(self):
        return SimpleNamespace(error=None, revision=1, session_recorded=3, total_recorded=24)

    def snapshot(self, **filters):
        return aggregate_merchant_history(self._records, **filters)


class _AnalyticsCapture(QWidget):
    """Paint a scaled crop of the actual dialog, without a top-level window."""
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._host = QWidget(self)
        self._host.hide()
        proxy = SimpleNamespace(coordinator=SimpleNamespace(merchant_analytics=_FixtureService()),
                                has_premium_access=lambda: True)
        self._dialog = MerchantAnalyticsWindow(proxy, self._host)
        self._dialog.setWindowFlags(Qt.Widget)
        self._dialog.resize(900, 720)
        self._dialog.ensurePolished()
        self._dialog.show()  # Child of a hidden host; never appears on the desktop.
        self._dialog.layout().activate()
        self._capture = QPixmap()
        l10n.RefreshBinding(self, self._refresh)
        self._refresh()

    def _refresh(self):
        self._dialog._last_snapshot_key = None
        self._dialog.refresh()
        self._dialog.ensurePolished()
        self._dialog.layout().activate()
        pixmap = QPixmap(self._dialog.size())
        pixmap.fill(Qt.transparent)
        self._dialog.render(pixmap)
        self._capture = pixmap.copy(0, 0, 900, 420)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#101925'))
        if not self._capture.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            size = self._capture.size().scaled(self.size(), Qt.KeepAspectRatio)
            dest = QRectF((self.width()-size.width())/2, (self.height()-size.height())/2,
                          size.width(), size.height())
            painter.drawPixmap(dest, self._capture, QRectF(self._capture.rect()))
        painter.end()


def build_merchant_preview(topic: str, widgets: OverlayPreviewWidgets) -> QWidget:
    """Build a self-contained sample using the supplied overlay widgets."""
    if topic not in ('stock', 'shady'):
        raise ValueError(f'Unknown merchant topic: {topic}')
    panel = QFrame()
    panel.setObjectName('merchantGuidePreview')
    panel.setStyleSheet('QFrame#merchantGuidePreview {background:#101925;border:1px solid #2b3c50;border-radius:10px;}')
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(10, 8, 10, 10)
    label = bind(QLabel(), lambda: message('guide.preview'))
    label.setStyleSheet('color:#9bb1c1;font-size:11px;font-weight:600;background:transparent;border:0;')
    layout.addWidget(label)
    layout.addWidget(_StockScene(widgets) if topic == 'stock' else _AnalyticsCapture(), 1)
    return panel
