"""Isolated examples rendered by Scanner's merchant UI components."""
from itertools import groupby, zip_longest

from PySide6.QtCore import QLocale, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHeaderView, QHBoxLayout, QLabel, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from core.item_metadata import ITEMS, ITEM_RARITY_COLOR_MAP
from core.map_markers import MapMarkerSnapshot, MapViewport, MerchantOffer, MerchantStockCapture, WorldMapMarker
from core.merchant_analytics import MerchantHistoryRecord, aggregate_merchant_history
from projections.item_sort import ITEM_RARITY_SORT_ORDER
from ui.shared import resource_path
from ui import i18n as l10n
from .guide_locale import bind, message, ui
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


def _example_history():
    # Fixed, illustrative observations; never reads the player's saved history.
    item_ids = tuple(item.item_id for item in ITEMS[:24])
    return tuple(MerchantHistoryRecord(
        'map' + str(i), 'merchant' + str(i),
        'forest_desert' if i % 2 else 'graveyard', 1 + i % 4,
        ('white', 'blue', 'purple', 'gold')[(i * 3 + i // 5) % 4],
        tuple(item_ids[(i * i + j * 7 + i // 3) % len(item_ids)] for j in range(3)),
    ) for i in range(32))


def _text(text, *, color='#e5edf5', size=12, bold=False):
    label = QLabel()
    label.setStyleSheet(f'color:{color};font-size:{size}px;'
                        f'font-weight:{700 if bold else 400};background:transparent;border:0;')
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    if callable(text):
        bind(label, text)
    else:
        label.setText(str(text))
    return label


class _AnalyticsTable(QTableWidget):
    """Show only complete rows in the space allocated by the guide."""
    _ROW_HEIGHT = 23

    def __init__(self, snapshot):
        super().__init__(0, 3)
        self.setObjectName('merchantAnalyticsGuideTable')
        metadata = {item.item_id: item for item in ITEMS}

        def rarity_rank(row):
            item = metadata.get(row.item_id)
            return ITEM_RARITY_SORT_ORDER.get(item.rarity, -1) if item else -1

        self._rows = sorted(snapshot.rows, key=lambda row: (
            -rarity_rank(row), -row.offer_count, row.display_name.casefold(), row.item_id,
        ))
        # Give each rarity a slot before adding its next most frequently seen item.
        groups = [tuple(index for index, _ in group)
                  for _, group in groupby(enumerate(self._rows), key=lambda pair: rarity_rank(pair[1]))]
        self._sample_order = [index for tier in zip_longest(*groups) for index in tier if index is not None]
        self._colors = {item.item_id: ITEM_RARITY_COLOR_MAP[item.rarity]
                        for item in ITEMS if item.rarity in ITEM_RARITY_COLOR_MAP}
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.setMinimumSize(0, 0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(self._ROW_HEIGHT)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setStyleSheet(
            'QTableWidget {background:#172333;color:#e5edf5;border:1px solid #2d4258;'
            'border-radius:8px;} QTableWidget::item {border-bottom:1px solid #223448;'
            'padding:1px 5px;} QHeaderView::section {background:#172333;color:#a7bcd1;'
            'border:0;border-bottom:1px solid #2d4258;padding:4px;}')
        l10n.RefreshBinding(self, self._refresh_language)
        self._refresh_language()

    def _refresh_language(self):
        self.setHorizontalHeaderLabels((ui('Item'), ui('Offers'), message('guide.shady_share')))
        header = self.horizontalHeader()
        for column in (1, 2):
            self.horizontalHeaderItem(column).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.setColumnWidth(column, header.sectionSizeHint(column))
        self._populate()

    def _populate(self):
        count = min(len(self._rows), max(0, self.viewport().height() // self._ROW_HEIGHT))
        locale = QLocale(l10n.active_translator().language)
        self.setRowCount(count)
        for index, row_index in enumerate(sorted(self._sample_order[:count])):
            row = self._rows[row_index]
            percent = locale.toString(row.merchant_percent, 'f', 1) + '%'
            values = (str(l10n.game('items', row.display_name)), locale.toString(row.offer_count), percent)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                elif row.item_id in self._colors:
                    item.setForeground(QColor(self._colors[row.item_id]))
                self.setItem(index, col, item)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.rowCount() != min(len(self._rows), self.viewport().height() // self._ROW_HEIGHT):
            self._populate()


class _AnalyticsPreview(QWidget):
    """Compact read-only view of saved or illustrative merchant analytics."""
    def __init__(self, snapshot=None):
        super().__init__()
        self.setObjectName('merchantAnalyticsGuidePreview')
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet('QWidget#merchantAnalyticsGuidePreview {background:#141d29;}')
        saved = snapshot is not None and bool(snapshot.merchants and snapshot.rows)
        if not saved:
            snapshot = aggregate_merchant_history(_example_history())
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(_text(lambda: message('guide.shady_saved' if saved else 'guide.preview'), color='#a7bcd1'))

        totals = QHBoxLayout()
        totals.setSpacing(7)
        for value, key in ((snapshot.merchants, 'guide.shady_merchants'),
                           (snapshot.offers, 'guide.shady_offers')):
            card = QFrame()
            card.setObjectName('merchantExampleCard')
            card.setStyleSheet('QFrame#merchantExampleCard {background:#172333;'
                               'border:1px solid #2d4258;border-radius:9px;}')
            box = QVBoxLayout(card)
            box.setContentsMargins(12, 5, 12, 5)
            box.setSpacing(1)
            box.addWidget(_text(lambda k=key: message(k), color='#a7bcd1'))
            box.addWidget(_text(lambda n=value: QLocale(l10n.active_translator().language).toString(n), size=19, bold=True))
            totals.addWidget(card, 1)
        layout.addLayout(totals)
        layout.addWidget(_AnalyticsTable(snapshot), 1)


def build_merchant_preview(topic: str, widgets: OverlayPreviewWidgets, *, snapshot=None) -> QWidget:
    """Build a self-contained sample using the supplied overlay widgets."""
    if topic == 'shady':
        return _AnalyticsPreview(snapshot)
    if topic != 'stock':
        raise ValueError(f'Unknown merchant topic: {topic}')
    panel = QFrame()
    panel.setObjectName('merchantGuidePreview')
    panel.setStyleSheet('QFrame#merchantGuidePreview {background:#101925;border:1px solid #2b3c50;border-radius:10px;}')
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(10, 8, 10, 10)
    label = bind(QLabel(), lambda: message('guide.preview'))
    label.setStyleSheet('color:#9bb1c1;font-size:11px;font-weight:600;background:transparent;border:0;')
    layout.addWidget(label)
    layout.addWidget(_StockScene(widgets), 1)
    return panel
