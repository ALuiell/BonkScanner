from __future__ import annotations

from html import escape
from math import ceil
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QMoveEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QResizeEvent,
    QScreen,
)
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app import config
from core.map_markers import (
    CLASSIC_MAP_MARKER_BASE_ICON_SIZE,
    MAP_MARKER_ACTION_BY_ID,
    MAP_MARKER_BASE_ICON_SIZE,
    MapMarkerAction,
    MarkerPalette,
    MapMarkerSnapshot,
    map_marker_screen_geometry,
    minimap_marker_screen_geometry,
)
from projections.in_game_html import (
    LUCK_EXPECTED_DEFAULT_LAYOUT,
    LUCK_RARITY_ORDER,
    build_luck_expected_overlay_html,
    build_luck_rarity_overlay_html_for_probabilities,
)
from core.item_metadata import ITEM_RARITY_COLOR_MAP
from core.shady_prices import format_shady_price
from ui.shared import resource_path
from ui.stock_card_layout import (
    group_stock_entries, hovered_stock_marker, layout_stock_cards, marker_bounds,
    stock_item_lines, stock_items_height, priced_stock_columns,
)

if TYPE_CHECKING:
    from gui_in_game_overlay import InGameOverlay


class MapMarkerLayer(QWidget):
    """Click-through painter for the game's Full Map and circular minimap."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot = MapMarkerSnapshot()
        self._palette: MarkerPalette | None = None
        self._scale = 1.0
        self._minimap_scale = 1.0
        self._style = "modern"
        self._merchant_stock_display = "smart"
        self._cursor_position: tuple[float, float] | None = None
        self._icons = {
            (style, action.id): QIcon(
                resource_path(
                    f"media/map_markers/pictograms/{pictogram_file}"
                )
            )
            for action in MAP_MARKER_ACTION_BY_ID.values()
            for style, pictogram_file in (
                ("modern", action.pictogram_file),
                ("classic", action.classic_pictogram_file),
            )
        }
        self._premium_icon = QIcon(resource_path("media/premium_access_icon.svg"))
        self._stock_badge_icon = QIcon(resource_path("media/map_markers/stock_memory_badge.svg"))
        self._pictogram_cache: dict[tuple[str, str, int], QPixmap] = {}
        self._premium_icon_cache: dict[int, QPixmap] = {}
        self._stock_badge_cache: dict[int, QPixmap] = {}
        self._microwave_badge_cache: dict[tuple, QPixmap] = {}
        self._stock_group_key = None
        self._stock_groups = ()
        self._stock_layout_key = None
        self._stock_plans = ()
        self._stock_card_pixmaps: dict[tuple, QPixmap] = {}
        self._stock_hovered_marker = None
        self._stock_hover_bridge = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.hide()

    def set_snapshot(
        self,
        snapshot: MapMarkerSnapshot,
        *,
        scale: float,
        style: str = "modern",
        minimap_scale: float = 1.0,
        merchant_stock_display: str = "smart",
        cursor_position: tuple[float, float] | None = None,
    ) -> None:
        normalized_scale = max(0.5, min(float(scale), 3.0))
        normalized_minimap_scale = max(0.5, min(float(minimap_scale), 2.0))
        normalized_style = "classic" if str(style).lower() == "classic" else "modern"
        normalized_stock_display = str(merchant_stock_display).strip().lower()
        if normalized_stock_display not in {"smart", "always", "cursor"}:
            normalized_stock_display = "smart"
        normalized_cursor = (
            (float(cursor_position[0]), float(cursor_position[1]))
            if cursor_position is not None
            else None
        )
        previous_snapshot = self._snapshot
        previous_palette = self._palette
        cursor_changed = normalized_cursor != self._cursor_position
        changed = (
            snapshot != self._snapshot
            or normalized_scale != self._scale
            or normalized_minimap_scale != self._minimap_scale
            or normalized_style != self._style
            or normalized_stock_display != self._merchant_stock_display
        )
        was_shown = not self.isHidden()
        self._snapshot = snapshot
        self._scale = normalized_scale
        self._minimap_scale = normalized_minimap_scale
        self._style = normalized_style
        self._merchant_stock_display = normalized_stock_display
        self._cursor_position = normalized_cursor
        if not changed and snapshot.map_open and cursor_changed:
            # A moving cursor only needs a repaint when the selected merchant
            # changes. Keep the marker-to-card hover bridge live either way.
            changed = self._stock_hover_selection() != self._stock_hovered_marker
        if not snapshot.map_open:
            self._palette = None
        should_show = self._should_show()
        if should_show != was_shown:
            self.setVisible(should_show)
        if should_show and (changed or not was_shown):
            self.raise_()
        if changed:
            if not previous_snapshot.map_open and not snapshot.map_open and previous_palette is None:
                dirty = self._minimap_update_rect(previous_snapshot).united(
                    self._minimap_update_rect(snapshot)
                ).intersected(self.rect())
                if not dirty.isEmpty():
                    self.update(dirty)
            else:
                # A Full Map/palette transition can leave content anywhere on
                # the layer, so clear the full surface on these rare changes.
                self.update()

    @staticmethod
    def _minimap_update_rect(snapshot: MapMarkerSnapshot) -> QRect:
        projection = snapshot.minimap_projection
        if (
            snapshot.map_open or projection is None or not projection.visible
            or projection.jammed or not snapshot.markers
        ):
            return QRect()
        rect = projection.content_rect
        # Include both old/new rectangles and an antialiasing margin. The
        # painter clips icons and stock badges to the circle inside this rect.
        return QRectF(rect.left, rect.top, rect.width, rect.height).toAlignedRect().adjusted(-3, -3, 3, 3)

    def set_palette(self, palette: MarkerPalette | None) -> None:
        if palette == self._palette:
            return
        was_shown = not self.isHidden()
        self._palette = palette
        should_show = self._should_show()
        if should_show != was_shown:
            self.setVisible(should_show)
        if should_show:
            self.raise_()
        self.update()

    def _should_show(self) -> bool:
        full_map_content = bool(
            self._snapshot.map_open
            and self._snapshot.viewport is not None
            and (self._snapshot.markers or self._palette is not None)
        )
        minimap = self._snapshot.minimap_projection
        minimap_content = bool(
            not self._snapshot.map_open
            and minimap is not None
            and minimap.visible
            and not minimap.jammed
            and self._snapshot.markers
        )
        return full_map_content or minimap_content

    def _pictogram_pixmap(
        self,
        action: MapMarkerAction,
        size: int,
        *,
        style: str | None = None,
    ) -> QPixmap:
        normalized_size = max(1, int(size))
        resolved_style = self._style if style is None else style
        resolved_style = "classic" if resolved_style == "classic" else "modern"
        cache_key = (resolved_style, action.id, normalized_size)
        cached = self._pictogram_cache.get(cache_key)
        if cached is not None:
            return cached

        icon = self._icons.get((resolved_style, action.id))
        if icon is None:
            pixmap = QPixmap()
        else:
            pixmap = icon.pixmap(normalized_size, normalized_size)

        self._pictogram_cache[cache_key] = pixmap
        return pixmap

    def _premium_pixmap(self, size: int) -> QPixmap:
        normalized_size = max(1, int(size))
        cached = self._premium_icon_cache.get(normalized_size)
        if cached is not None:
            return cached

        pixmap = self._premium_icon.pixmap(normalized_size, normalized_size)
        self._premium_icon_cache[normalized_size] = pixmap
        return pixmap

    def _stock_badge_pixmap(self, size: int) -> QPixmap:
        normalized_size = max(1, int(size))
        cached = self._stock_badge_cache.get(normalized_size)
        if cached is None:
            cached = self._stock_badge_icon.pixmap(normalized_size, normalized_size)
            self._stock_badge_cache[normalized_size] = cached
        return cached

    def paintEvent(self, event) -> None:
        snapshot = self._snapshot
        if not self._should_show():
            return

        painter = QPainter(self)
        if not painter.isActive():
            return
        try:
            viewport = snapshot.viewport
            if snapshot.map_open and viewport is not None:
                painter.save()
                try:
                    self._paint_snapshot(painter, snapshot, viewport)
                finally:
                    painter.restore()
            if snapshot.minimap_projection is not None:
                self._paint_minimap(painter, snapshot)
        finally:
            if painter.isActive():
                painter.end()

    def _paint_snapshot(
        self,
        painter: QPainter,
        snapshot: MapMarkerSnapshot,
        viewport,
    ) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setClipRect(
            QRectF(viewport.left, viewport.top, viewport.width, viewport.height)
        )
        stock_by_object = {
            stock.merchant_object_ptr: stock for stock in snapshot.merchant_stocks
        }
        stock_geometries = []
        marker_obstacles = []
        for marker in snapshot.markers:
            action = MAP_MARKER_ACTION_BY_ID.get(marker.action_id)
            if action is None:
                continue
            geometry = map_marker_screen_geometry(
                marker.world_x,
                marker.world_z,
                world_size=snapshot.world_size,
                viewport=viewport,
                scale=self._scale,
            )
            if geometry is None:
                continue
            center_x, center_y, icon_size_value = geometry
            marker_obstacles.append(marker_bounds(geometry))
            self._paint_marker(
                painter,
                action,
                marker.source,
                center_x,
                center_y,
                int(icon_size_value),
            )
            stock = stock_by_object.get(marker.object_ptr)
            if action.family == "microwave":
                self._paint_microwave_uses_badge(
                    painter, center_x, center_y, float(icon_size_value), marker.uses_remaining
                )
            if stock is not None:
                self._paint_stock_badge(
                    painter, center_x, center_y, float(icon_size_value)
                )
                stock_geometries.append((marker, stock, geometry))

        self._paint_stock_cards(painter, viewport, stock_geometries, tuple(marker_obstacles))
        self._paint_palette(painter)

    def _paint_minimap(self, painter: QPainter, snapshot: MapMarkerSnapshot) -> None:
        projection = snapshot.minimap_projection
        if (
            snapshot.map_open
            or projection is None
            or not projection.visible
            or projection.jammed
        ):
            return
        painter.save()
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            clip = QPainterPath()
            clip.addEllipse(
                QPointF(projection.center_x, projection.center_y),
                projection.radius,
                projection.radius,
            )
            painter.setClipPath(clip, Qt.IntersectClip)
            stock_objects = {
                stock.merchant_object_ptr for stock in snapshot.merchant_stocks
            }
            for marker in snapshot.markers:
                action = MAP_MARKER_ACTION_BY_ID.get(marker.action_id)
                if action is None:
                    continue
                geometry = minimap_marker_screen_geometry(
                    marker.world_x,
                    marker.world_z,
                    projection=projection,
                    scale=self._minimap_scale,
                )
                if geometry is None:
                    continue
                center_x, center_y, icon_size_value = geometry
                self._paint_marker(
                    painter,
                    action,
                    marker.source,
                    center_x,
                    center_y,
                    int(icon_size_value),
                )
                if marker.object_ptr in stock_objects:
                    self._paint_stock_badge(
                        painter, center_x, center_y, float(icon_size_value)
                    )
                if action.family == "microwave":
                    self._paint_microwave_uses_badge(
                        painter, center_x, center_y, float(icon_size_value), marker.uses_remaining
                    )
        finally:
            painter.restore()

    def _paint_marker(
        self,
        painter: QPainter,
        action: MapMarkerAction,
        source: str,
        center_x: float,
        center_y: float,
        icon_size: int,
    ) -> None:
        if self._style == "classic":
            marker_size = max(
                18,
                int(
                    round(
                        icon_size
                        * CLASSIC_MAP_MARKER_BASE_ICON_SIZE
                        / MAP_MARKER_BASE_ICON_SIZE
                    )
                ),
            )
            pictogram_size = max(12, int(round(marker_size * 0.68)))
            half = marker_size / 2.0
            bounds = QRectF(
                center_x - half,
                center_y - half,
                float(marker_size),
                float(marker_size),
            )
            outline = QColor(action.outline_color)
            outline.setAlpha(225)
            painter.setPen(QPen(outline, max(2, marker_size // 11)))
            fill = QColor(action.color)
            fill.setAlpha(232)
            painter.setBrush(fill)
            painter.drawEllipse(bounds)

            if source == "manual":
                manual_pen = QPen(QColor(255, 255, 255, 205), 1.4)
                manual_pen.setStyle(Qt.DashLine)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(manual_pen)
                painter.drawEllipse(bounds.adjusted(-2, -2, 2, 2))
        else:
            pictogram_size = max(18, icon_size)

        pixmap = self._pictogram_pixmap(
            action,
            pictogram_size,
            style=self._style,
        )
        if not pixmap.isNull():
            painter.drawPixmap(
                int(round(center_x - pictogram_size / 2.0)),
                int(round(center_y - pictogram_size / 2.0)),
                pixmap,
            )

    def _paint_stock_badge(
        self,
        painter: QPainter,
        center_x: float,
        center_y: float,
        icon_size: float,
    ) -> None:
        # A 22 px badge on the default 36 px minimap marker matches the preview.
        # Cache the entire circle/list together so moving markers still use one blit.
        size = max(16, min(26, int(round(icon_size * 0.61))))
        badge_x = center_x + icon_size * 0.31
        badge_y = center_y - icon_size * 0.31
        pixmap = self._stock_badge_pixmap(size)
        if pixmap.isNull():
            return
        painter.drawPixmap(
            int(round(badge_x - size / 2.0)),
            int(round(badge_y - size / 2.0)),
            pixmap,
        )

    def _microwave_badge_pixmap(self, uses: int, size: int) -> QPixmap:
        text = str(uses) if uses < 100 else "99+"
        dpr = self.devicePixelRatioF()
        key = (text, size, dpr)
        cached = self._microwave_badge_cache.get(key)
        if cached is not None:
            return cached
        pixmap = QPixmap(ceil(size * dpr), ceil(size * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QPen(QColor("#A0B7CC"), 1.0))
            painter.setBrush(QColor("#0A111B"))
            painter.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
            font = QFont("Segoe UI")
            font.setBold(True)
            font.setPixelSize(round(size * (0.62 if len(text) == 1 else 0.45)))
            painter.setFont(font)
            painter.setPen(QColor("#EDF5FC"))
            painter.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, text)
        finally:
            painter.end()
        # Keep resizing/display switches and unexpected counts bounded.
        if len(self._microwave_badge_cache) >= 128:
            self._microwave_badge_cache.clear()
        self._microwave_badge_cache[key] = pixmap
        return pixmap

    def _paint_microwave_uses_badge(
        self, painter, center_x, center_y, icon_size, uses: int | None,
    ) -> None:
        if uses is None or uses < 0:
            return
        size = max(16, min(26, int(round(icon_size * 0.61))))
        pixmap = self._microwave_badge_pixmap(uses, size)
        painter.drawPixmap(
            int(round(center_x + icon_size * 0.31 - size / 2.0)),
            int(round(center_y - icon_size * 0.31 - size / 2.0)),
            pixmap,
        )

    def _paint_stock_cards(self, painter, viewport, stock_geometries, obstacles=()) -> None:
        if not stock_geometries:
            self._stock_group_key = None
            self._stock_groups = ()
            self._stock_layout_key = None
            self._stock_plans = ()
            self._stock_card_pixmaps.clear()
            self._stock_hovered_marker = None
            self._stock_hover_bridge = None
            return
        group_key = tuple(stock_geometries)
        if group_key != self._stock_group_key:
            self._stock_groups = group_stock_entries(group_key)
            self._stock_group_key = group_key
            self._stock_layout_key = None
            self._stock_plans = ()
            self._stock_hover_bridge = None
        hovered = self._stock_hover_selection()
        self._stock_hovered_marker = hovered
        layout_key = (viewport, self._scale, self._merchant_stock_display, hovered, obstacles)
        if layout_key != self._stock_layout_key:
            self._stock_plans = layout_stock_cards(
                self._stock_groups, viewport, self._scale,
                self._merchant_stock_display, hovered, obstacles,
                show_prices=True,
            )
            self._stock_layout_key = layout_key

        active_pixmaps = {}
        for plan in self._stock_plans:
            bounds = plan.bounds
            selected = hovered if any(e[0].marker_id == hovered for e in plan.group.entries) else None
            # Cache only current visible cards. Cursor motion inside the same
            # merchant hit area neither solves layout nor rasterizes text again.
            dpr = self.devicePixelRatioF()
            cache_key = (
                plan.group.entries, plan.entries, plan.compact, bounds.width(),
                bounds.height(), self._scale, self._style, selected, dpr,
            )
            pixmap = self._stock_card_pixmaps.get(cache_key)
            if pixmap is None:
                pixmap = QPixmap(ceil((bounds.width() + 2) * dpr), ceil((bounds.height() + 2) * dpr))
                pixmap.setDevicePixelRatio(dpr)
                pixmap.fill(Qt.transparent)
                card_painter = QPainter(pixmap)
                try:
                    card_painter.setRenderHint(QPainter.Antialiasing, True)
                    local = QRectF(1, 1, bounds.width(), bounds.height())
                    if not plan.compact and len(plan.group.entries) == 1:
                        self._paint_stock_card(card_painter, local, plan.entries[0][1])
                    else:
                        self._paint_stock_group_card(card_painter, local, plan, selected)
                finally:
                    card_painter.end()
            active_pixmaps[cache_key] = pixmap
            anchor = plan.group.bounds.center()
            if selected is not None:
                entry = next(e for e in plan.group.entries if e[0].marker_id == selected)
                x, y, size = entry[2]
                anchor = QPointF(x, y)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor("#B9E5FA"), 1.4))
                painter.drawEllipse(anchor, size * .55, size * .55)
            endpoint = QPointF(
                max(bounds.left(), min(anchor.x(), bounds.right())),
                max(bounds.top(), min(anchor.y(), bounds.bottom())),
            )
            painter.setPen(QPen(QColor(117, 159, 183, 170), 1.0))
            painter.drawLine(anchor, endpoint)
            painter.drawPixmap(QPointF(bounds.left() - 1, bounds.top() - 1), pixmap)
        self._stock_card_pixmaps = active_pixmaps

    def _stock_hover_selection(self):
        hovered = hovered_stock_marker(self._stock_groups, self._cursor_position)
        if hovered is not None or self._cursor_position is None:
            self._stock_hover_bridge = None
            return hovered
        point = QPointF(*self._cursor_position)
        # Keep an expanded card alive while the cursor is over either the card
        # or its former compact label. Otherwise expansion could move the hit
        # target away from the cursor and flicker between the two layouts.
        if self._stock_hover_bridge is not None:
            bounds, marker_id = self._stock_hover_bridge
            if bounds.contains(point):
                return marker_id
        for plan in reversed(self._stock_plans):
            if plan.bounds.contains(point):
                ids = tuple(e[0].marker_id for e in plan.group.entries)
                marker_id = self._stock_hovered_marker if self._stock_hovered_marker in ids else ids[0]
                self._stock_hover_bridge = (QRectF(plan.bounds), marker_id)
                return marker_id
        self._stock_hover_bridge = None
        return None

    def _paint_stock_group_card(self, painter, bounds, plan, selected) -> None:
        painter.setPen(QPen(QColor(75, 145, 188, 220), 1.2))
        painter.setBrush(QColor(8, 17, 27, 179))
        painter.drawRoundedRect(bounds, 7.0, 7.0)
        font = painter.font()
        font.setFamily("Segoe UI")
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#8FDFFF"))
        count = len(plan.group.entries)
        title = f"{count} SHADIES" if count > 1 else "STOCK"
        if plan.compact:
            title += " · hover"
        elif len(plan.entries) < count:
            title += " · selected stock"
        title = painter.fontMetrics().elidedText(title, Qt.ElideRight, int(bounds.width() - 18))
        painter.drawText(bounds.adjusted(10, 5, -8, 0), Qt.AlignTop | Qt.AlignLeft, title)
        if plan.compact:
            return
        y = bounds.top() + 28
        items = tuple(item for entry in plan.entries for item in entry[1].items)
        name_width = self._stock_name_width(items, bounds.width())
        for marker, stock, _geometry in plan.entries:
            action = MAP_MARKER_ACTION_BY_ID[marker.action_id]
            section_height = 32 + stock_items_height(stock, bounds.width(), self._scale, name_width=name_width)
            if marker.marker_id == selected:
                painter.fillRect(QRectF(bounds.left() + 3, y - 2, bounds.width() - 6, section_height - 3), QColor(51, 91, 119, 105))
            self._paint_stock_merchant_icon(painter, action, bounds.left() + 9, y)
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(action.color))
            number = next(i + 1 for i, entry in enumerate(plan.group.entries) if entry[0].marker_id == marker.marker_id)
            label = f"{number}. {action.display_name}"
            label = painter.fontMetrics().elidedText(label, Qt.ElideRight, int(bounds.width() - 46))
            painter.drawText(QRectF(bounds.left() + 37, y, bounds.width() - 46, 22), Qt.AlignVCenter | Qt.AlignLeft, label)
            self._paint_stock_items(painter, bounds.left(), y + 25, bounds.width(), stock, name_width=name_width)
            y += section_height

    def _stock_name_width(self, items, width):
        names, prices = priced_stock_columns(items)
        return max(1, min(names, width - 16 - 9 - prices))

    def _paint_stock_items(self, painter, left, top, width, stock, *, name_width=None) -> None:
        font = QFont("Segoe UI")
        font.setPixelSize(12)
        painter.setFont(font)
        row_height = max(16.0, 17.0 * self._scale)
        if name_width is None:
            name_width = self._stock_name_width(stock.items, width)
        text_width = int(width - 22 if name_width is None else name_width)
        padding = 8
        for item in stock.items:
            painter.setFont(font)
            painter.setPen(QColor(ITEM_RARITY_COLOR_MAP.get(item.rarity, "#DDE7F2")))
            row_top = top
            for text in stock_item_lines(item.display_name, text_width):
                painter.drawText(
                    QRectF(left + padding, top, text_width, row_height),
                    Qt.AlignVCenter | Qt.AlignLeft, text,
                )
                top += row_height
            coin_left = left + padding + text_width + 9
            coin_top = row_top + (row_height - 11) / 2
            painter.setPen(QPen(QColor('#F7D96D'), 1))
            painter.setBrush(QColor('#DFAE30'))
            painter.drawEllipse(QRectF(coin_left, coin_top, 11, 11))
            painter.setPen(QPen(QColor('#98701A'), 1))
            painter.drawEllipse(QRectF(coin_left + 1.5, coin_top + 1.5, 8, 8))
            painter.setPen(QPen(QColor('#FFF0A9'), 1))
            painter.drawLine(QPointF(coin_left + 5.5, coin_top + 3), QPointF(coin_left + 5.5, coin_top + 8))
            price_font = QFont(font)
            price_font.setBold(True)
            painter.setFont(price_font)
            painter.setPen(QColor('#F4CE62'))
            painter.drawText(
                QRectF(coin_left + 15, row_top, max(1, left + width - 8 - coin_left - 15), row_height),
                Qt.AlignVCenter | Qt.AlignLeft, format_shady_price(item.price),
            )

    def _paint_stock_merchant_icon(self, painter, action, left, top) -> None:
        # Use the complete map symbol, not the bare black classic pictogram.
        # Scale its normal circle/outline together into the 22 px card slot.
        painter.save()
        try:
            painter.translate(left, top)
            if self._style == "classic":
                ratio = 22.0 / CLASSIC_MAP_MARKER_BASE_ICON_SIZE
                painter.scale(ratio, ratio)
                center = CLASSIC_MAP_MARKER_BASE_ICON_SIZE / 2.0
                self._paint_marker(painter, action, "automatic", center, center, MAP_MARKER_BASE_ICON_SIZE)
            else:
                self._paint_marker(painter, action, "automatic", 11.0, 11.0, 22)
        finally:
            painter.restore()

    def _paint_stock_card(self, painter: QPainter, bounds: QRectF, stock) -> None:
        painter.setPen(QPen(QColor(75, 145, 188, 220), 1.2))
        painter.setBrush(QColor(8, 17, 27, 179))
        painter.drawRoundedRect(bounds, 7.0, 7.0)

        font = painter.font()
        font.setFamily("Segoe UI")
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#8FDFFF"))
        header_icon_size = 14
        header_icon = self._premium_pixmap(header_icon_size)
        if not header_icon.isNull():
            painter.drawPixmap(
                int(round(bounds.left() + 9.0)),
                int(round(bounds.top() + 4.0)),
                header_icon,
            )
        painter.drawText(
            bounds.adjusted(29.0, 5.0, -8.0, 0.0),
            Qt.AlignTop | Qt.AlignLeft,
            "STOCK",
        )

        self._paint_stock_items(painter, bounds.left(), bounds.top() + 25, bounds.width(), stock)

    def _paint_palette(self, painter: QPainter) -> None:
        palette = self._palette
        if palette is None or not palette.rows:
            return
        first = palette.rows[0]
        last = palette.rows[-1]
        margin = max(4.0, first.height * 0.2)
        panel = QRectF(
            first.left - margin,
            first.top - margin,
            first.width + margin * 2.0,
            last.top + last.height - first.top + margin * 2.0,
        )
        painter.setClipping(False)
        painter.setPen(QPen(QColor(112, 137, 169, 220), 1.2))
        painter.setBrush(QColor(10, 17, 27, 242))
        painter.drawRoundedRect(panel, 7.0, 7.0)

        for index, row in enumerate(palette.rows):
            action = MAP_MARKER_ACTION_BY_ID[row.action_id]
            bounds = QRectF(row.left, row.top, row.width, row.height)
            selected = row.action_id == palette.selected_action_id
            painter.setPen(Qt.NoPen)
            painter.setBrush(
                QColor(48, 78, 112, 235) if selected else QColor(20, 31, 46, 220)
            )
            painter.drawRoundedRect(bounds, 4.0, 4.0)

            swatch_size = row.height * 0.66
            swatch = QRectF(
                row.left + row.height * 0.20,
                row.top + (row.height - swatch_size) / 2.0,
                swatch_size,
                swatch_size,
            )
            if self._style == "classic":
                outline = QColor(action.outline_color)
                outline.setAlpha(220)
                painter.setPen(QPen(outline, 1.2))
                painter.setBrush(QColor(action.color))
                painter.drawEllipse(swatch)
                pictogram = max(10, int(round(swatch_size * 0.72)))
            else:
                pictogram = max(12, int(round(swatch_size)))
            pixmap = self._pictogram_pixmap(
                action,
                pictogram,
                style=self._style,
            )
            if not pixmap.isNull():
                painter.drawPixmap(
                    int(round(swatch.center().x() - pictogram / 2.0)),
                    int(round(swatch.center().y() - pictogram / 2.0)),
                    pixmap,
                )

            font = painter.font()
            font.setFamily("Segoe UI")
            font.setPixelSize(max(11, int(round(row.height * 0.43))))
            font.setBold(selected)
            painter.setFont(font)
            painter.setPen(QColor(239, 246, 255))
            text_bounds = bounds.adjusted(row.height * 0.95, 0, -8, 0)
            painter.drawText(text_bounds, Qt.AlignVCenter | Qt.AlignLeft, action.display_name)

            if index in (3, 7):
                painter.setPen(QPen(QColor(102, 126, 154, 165), 1.0))
                divider_y = row.top + row.height + max(1.0, margin * 0.35)
                painter.drawLine(
                    int(round(row.left + 5)),
                    int(round(divider_y)),
                    int(round(row.left + row.width - 5)),
                    int(round(divider_y)),
                )


class DraggableOverlayWidget(QWidget):
    moved = Signal(str, int, int)

    def __init__(self, widget_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.widget_id = widget_id
        self._dragging = False
        self._drag_start_pos = QPoint()
        self.edit_mode = False
        self.setMouseTracking(True)

        self._widget_layout = QVBoxLayout(self)
        self._widget_layout.setContentsMargins(5, 5, 5, 5)
        self._widget_layout.setSpacing(2)

        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._widget_layout.addWidget(self.label)

        widget_cfg = config.IN_GAME_OVERLAY["widgets"].get(
            self.widget_id,
            {"enabled": False, "x": 0, "y": 0, "scale": 1.0}
        )
        self.update_scale(widget_cfg.get("scale", 1.0))
        self.move(widget_cfg.get("x", 0), widget_cfg.get("y", 0))
        self.setVisible(widget_cfg.get("enabled", False))

    def update_scale(self, scale: float) -> None:
        px_size = int(16 * scale)
        self.label.setStyleSheet(
            f"font-size: {px_size}px; font-weight: bold; background: transparent; border: none;"
        )
        text = self.label.text()
        self.label.setText("")
        self.label.setText(text)
        self.label.adjustSize()
        self.adjustSize()

    def set_edit_mode(self, enabled: bool) -> None:
        self.edit_mode = enabled
        if enabled:
            self.setStyleSheet(
                "background-color: rgba(0, 0, 0, 150); "
                "border: 1px dashed rgba(255, 255, 255, 100);"
            )
        else:
            self.setStyleSheet("background-color: transparent; border: none;")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.edit_mode and event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start_pos = event.pos()
            self.raise_()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.edit_mode and self._dragging:
            position = self.mapToParent(event.pos() - self._drag_start_pos)
            self.move(self._clamp_to_parent(position))
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.edit_mode and event.button() == Qt.LeftButton:
            self._dragging = False
            self.move(self._clamp_to_parent(self.pos()))
            self.moved.emit(self.widget_id, self.x(), self.y())
            event.accept()

    def _clamp_to_parent(self, position: QPoint) -> QPoint:
        parent = self.parentWidget()
        if parent is None:
            return position
        max_x = max(0, parent.width() - self.width())
        max_y = max(0, parent.height() - self.height())
        return QPoint(
            min(max(0, position.x()), max_x),
            min(max(0, position.y()), max_y),
        )

    def set_text(self, text: str) -> None:
        if self.label.text() != text:
            self.label.setText(text)
            self.adjustSize()
            self.reclamp_to_parent()

    def configured_position(self) -> QPoint:
        """Where the user put this widget, which is not always where it sits."""
        widget_cfg = config.IN_GAME_OVERLAY.get("widgets", {}).get(self.widget_id)
        if not isinstance(widget_cfg, dict):
            return self.pos()
        return QPoint(int(widget_cfg.get("x", self.x())), int(widget_cfg.get("y", self.y())))

    def reclamp_to_parent(self) -> None:
        """Re-place from the configured position rather than the current one.

        A widget that grows -- the Luck widget gains two rows when the expected
        frame is switched on, and changes height again between the two layouts
        -- gets pushed off the bottom edge and clamped upward. Clamping from
        where it *currently* sits makes that shift permanent, so the widget
        creeps up the screen and never comes back when the frame is switched off
        again. Clamping from the configured position instead makes the move
        purely a display adjustment: the intent survives, and the widget returns
        the moment there is room. Same fix covers a resized game window.

        Suppressed while *dragging* only, not for the whole of edit mode. It
        skipped both, and that is where widgets escaped the screen: the right
        and bottom clamps are `parent.width() - self.width()`, so they are only
        as good as the widget's size at the last clamp, while the left and top
        ones are `max(0, ...)` and hold regardless -- which is why widgets stuck
        to two edges and slid past the other two. Live text keeps growing the
        widget (measured: 170px wide with a short caption, 698px with a long
        one), so one parked against the right edge in layout mode grew straight
        past it with nothing to pull it back until edit mode ended. Dragging
        still skips, because clamping mid-drag would yank the widget out from
        under the cursor.
        """
        if self._dragging:
            return
        position = self._clamp_to_parent(self.configured_position())
        if position != self.pos():
            self.move(position)


class LuckRarityBarWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._probabilities: dict[str, float | None] = {rarity: None for rarity in LUCK_RARITY_ORDER}
        self._show_bar = True
        self._scale = 1.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._apply_scale()

    def set_probabilities(self, probabilities: dict[str, float | None], show_bar: bool) -> None:
        self._probabilities = dict(probabilities)
        self._show_bar = bool(show_bar)
        self.setVisible(self._show_bar)
        self.update()

    def set_show_bar(self, show_bar: bool) -> None:
        self._show_bar = bool(show_bar)
        self.setVisible(self._show_bar)
        self.update()

    def set_bar_scale(self, scale: float) -> None:
        self._scale = max(0.5, float(scale))
        self._apply_scale()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self.width(), self.height())

    def _apply_scale(self) -> None:
        height = int(round(6 * self._scale))
        self.setFixedHeight(max(4, height))

    def paintEvent(self, event) -> None:
        if not self._show_bar:
            return

        painter = QPainter(self)
        if not painter.isActive():
            return
        try:
            self._paint_bar(painter)
        finally:
            if painter.isActive():
                painter.end()

    def _paint_bar(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.Antialiasing)

        bounds = self.rect().adjusted(0, 0, -1, -1)
        radius = bounds.height() / 2.0

        # Background track
        clip_path = QPainterPath()
        clip_path.addRoundedRect(bounds, radius, radius)
        painter.setClipPath(clip_path)
        
        # Sleek dark track background
        painter.fillRect(bounds, QColor(15, 23, 42, 180))

        ordered_probs = [
            max(0.0, float(self._probabilities.get(rarity) or 0.0))
            for rarity in LUCK_RARITY_ORDER
        ]
        total = sum(ordered_probs)
        if total > 0.0:
            active_segments = []
            for rarity, prob in zip(LUCK_RARITY_ORDER, ordered_probs):
                if prob > 0.0:
                    active_segments.append((rarity, prob))

            num_active = len(active_segments)
            gap_width = max(1, int(round(1.5 * self._scale))) if num_active > 1 else 0
            total_gap_width = (num_active - 1) * gap_width
            
            usable_width = bounds.width() - total_gap_width
            if usable_width > 0:
                widths = [int(round((prob / total) * usable_width)) for rarity, prob in active_segments]
                # Adjust rounding errors
                diff = usable_width - sum(widths)
                if widths:
                    largest_index = max(range(len(widths)), key=lambda index: widths[index])
                    widths[largest_index] += diff

                current_x = bounds.x()
                for (rarity, prob), segment_width in zip(active_segments, widths):
                    if segment_width <= 0:
                        continue
                    color = ITEM_RARITY_COLOR_MAP.get(rarity, "#E5E7EB")
                    painter.fillRect(current_x, bounds.y(), segment_width, bounds.height(), QColor(color))
                    current_x += segment_width + gap_width

        # Subtle dark border outline instead of harsh white/gray
        painter.setClipping(False)
        painter.setPen(QPen(QColor(0, 0, 0, 100), max(1, int(round(0.8 * self._scale)))))
        painter.drawRoundedRect(bounds, radius, radius)



class LuckRarityOverlayWidget(DraggableOverlayWidget):
    """The percentage row, the bar, and the actual-versus-expected block.

    Three children of the one ``QVBoxLayout`` `DraggableOverlayWidget` already
    owns, in that order. Two independent toggles govern the second and third,
    and all four combinations are valid -- which is why the expected block is
    laid out as a sibling of the percentage row rather than positioned against
    the bar. `show_bar` can hide the bar, and an anchor that can disappear is
    not an anchor; the percentage row is always drawn.
    """

    def __init__(self, widget_id: str, parent: QWidget | None = None):
        self._current_probabilities: dict[str, float | None] = {
            rarity: None for rarity in LUCK_RARITY_ORDER
        }
        super().__init__(widget_id, parent)
        self.bar_widget = LuckRarityBarWidget(self)
        self._widget_layout.addWidget(self.bar_widget)

        self.expected_label = QLabel()
        self.expected_label.setTextFormat(Qt.RichText)
        self.expected_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # Minimum rather than Preferred so the block never widens the widget
        # past the percentage row it is anchored to; the 100%-width table inside
        # it takes whatever width the layout hands down.
        self.expected_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        # Word wrap plus the width cap `_fit_expected_block` applies is what
        # keeps that promise. The size policy alone never did: a policy governs
        # how spare space is *shared*, and the block's own size hint -- a status
        # sentence on one unbreakable line -- still fed the column's width.
        self.expected_label.setWordWrap(True)
        self._widget_layout.addWidget(self.expected_label)

        widget_cfg = config.IN_GAME_OVERLAY["widgets"][self.widget_id]
        self._show_expected = bool(widget_cfg.get("show_expected", False))
        self._expected_layout = str(
            widget_cfg.get("expected_layout", LUCK_EXPECTED_DEFAULT_LAYOUT)
        )
        self.expected_label.setVisible(self._show_expected)
        self.bar_widget.set_show_bar(widget_cfg.get("show_bar", True))
        self.update_scale(widget_cfg.get("scale", 1.0))

    def update_scale(self, scale: float) -> None:
        super().update_scale(scale)
        if hasattr(self, "expected_label"):
            px_size = int(16 * scale)
            self.expected_label.setStyleSheet(
                f"font-size: {px_size}px; font-weight: bold; "
                "background: transparent; border: none;"
            )
        self._fit_expected_block()
        if hasattr(self, "bar_widget"):
            self.bar_widget.set_bar_scale(scale)
            self.adjustSize()

    def set_text(self, text: str) -> None:
        super().set_text(text)
        # The percentage row is what the block is measured against, so a row
        # that changed width invalidates the cap computed for the old one.
        self._fit_expected_block()

    def _fit_expected_block(self) -> None:
        """Make the percentage row the only child that decides the width.

        The three children share one column layout, and a column is as wide as
        its widest child. The bar is `Expanding`, so it does not merely tolerate
        that width -- it paints itself across all of it. Which meant switching
        the expected frame on stretched the bar to whatever the block underneath
        happened to need, and a status message stretched it to roughly three
        times the percentage row it is supposed to sit under.

        Capping the block at the row's width inverts the relationship the user
        sees: the bar is sized by the percentages, exactly as it is with the
        frame switched off, and the block fits itself into that width. The
        explicit height is the other half -- a wrapping label's size hint is a
        guess made before the layout hands down a width, and without pinning the
        height to `heightForWidth` the wrapped lines get clipped.
        """
        if not hasattr(self, "expected_label"):
            return
        width = self.label.sizeHint().width()
        if width <= 0:
            return
        changed = False
        if self.expected_label.maximumWidth() != width:
            self.expected_label.setMaximumWidth(width)
            changed = True
        height = self.expected_label.heightForWidth(width)
        if height > 0 and self.expected_label.minimumHeight() != height:
            self.expected_label.setFixedHeight(height)
            changed = True
        if changed:
            self.adjustSize()
            self.reclamp_to_parent()

    def set_probabilities(self, probabilities: dict[str, float | None], *, show_bar: bool) -> None:
        self._current_probabilities = dict(probabilities)
        self.set_text(build_luck_rarity_overlay_html_for_probabilities(probabilities))
        self.bar_widget.set_probabilities(probabilities, show_bar)
        self.adjustSize()

    def set_show_bar(self, show_bar: bool) -> None:
        self.bar_widget.set_show_bar(show_bar)
        self.adjustSize()

    def set_expected(
        self,
        actual: dict[str, int] | None,
        expected: dict[str, float] | None,
        *,
        show_expected: bool,
        layout: str = LUCK_EXPECTED_DEFAULT_LAYOUT,
        status_message: str | None = None,
    ) -> None:
        """Update the block, show a status line in its place, or hide it.

        Three states, not two. Hidden is the toggle being off -- there is
        nothing to say about a block the user chose not to see. A run the
        tracker cannot (yet) measure instead draws `status_message`: an empty
        area reads the same as an unchecked toggle or a widget dragged off
        screen, and neither the player nor support could tell those apart.
        The percentage row above stays in all three -- it depends on the
        current Luck alone.
        """
        # `isVisibleTo(self)`, never `isVisible()`. The latter is false for
        # every child while the overlay window itself is hidden, so guarding on
        # it made "switch the frame off" a no-op whenever the overlay was not on
        # screen -- and the block came back the moment it was shown again.
        was_shown = self.expected_label.isVisibleTo(self)
        self._show_expected = bool(show_expected)
        self._expected_layout = str(layout)
        if not self._show_expected:
            if status_message:
                html = f'<span style="color: #8a8d9b;">{escape(status_message)}</span>'
                if self.expected_label.text() != html or not was_shown:
                    self.expected_label.setText(html)
                    self.expected_label.setVisible(True)
                    self._fit_expected_block()
                    self.adjustSize()
                    self.reclamp_to_parent()
                return
            if was_shown:
                self.expected_label.setVisible(False)
                self.adjustSize()
                self.reclamp_to_parent()
            return
        html = build_luck_expected_overlay_html(
            actual or {}, expected or {}, layout=self._expected_layout
        )
        if self.expected_label.text() != html or not was_shown:
            self.expected_label.setText(html)
            self.expected_label.setVisible(True)
            self._fit_expected_block()
            self.adjustSize()
            self.reclamp_to_parent()


class InGameOverlayWindow(QWidget):
    def __init__(self, parent_mixin: InGameOverlay, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_mixin = parent_mixin
        self.edit_mode = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.map_marker_layer = MapMarkerLayer(self)
        self.map_marker_layer.setGeometry(self.rect())
        self._position_save_timer = QTimer(self)
        self._position_save_timer.setSingleShot(True)
        self._position_save_timer.timeout.connect(self._position_save_btn)

        self.widgets: dict[str, DraggableOverlayWidget] = {}
        for widget_id in (
            "scanner",
            "recording",
            "kps",
            "powerups",
            "luck_rarity",
            "stats",
            "event_timer",
            "item_cooldowns",
            "build_progression",
            "weapon_tracker",
        ):
            widget = (
                LuckRarityOverlayWidget(widget_id, self)
                if widget_id == "luck_rarity"
                else DraggableOverlayWidget(widget_id, self)
            )
            widget.moved.connect(self.on_widget_moved)
            self.widgets[widget_id] = widget

        self.save_btn: QPushButton | None = None

    def showEvent(self, event) -> None:
        self.sync_geometry_to_target()
        if self.edit_mode:
            self._position_save_timer.start(0)
        super().showEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.map_marker_layer.setGeometry(self.rect())
        self._keep_widgets_inside_bounds()
        if self.edit_mode:
            self._position_save_btn()

    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        if self.edit_mode:
            self._position_save_btn()

    def sync_geometry_to_target(self) -> None:
        geometry = None
        parent_mixin = getattr(self, "parent_mixin", None)
        if parent_mixin and hasattr(parent_mixin, "_in_game_overlay_target_geometry"):
            geometry = parent_mixin._in_game_overlay_target_geometry()
        if geometry is not None and geometry.isValid() and geometry != self.geometry():
            self.setGeometry(geometry)
        self._keep_widgets_inside_bounds()
        if self.edit_mode:
            self._position_save_btn()

    def _keep_widgets_inside_bounds(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return

        # Deliberately does not write the clamped position back to the config.
        # It used to, and that is what made a widget near an edge creep upward
        # every time it grew a row -- see `reclamp_to_parent`. The configured
        # position is the user's intent and only the user changes it; a drag
        # already saves through the `moved` signal.
        for widget in getattr(self, "widgets", {}).values():
            widget.reclamp_to_parent()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.edit_mode:
            painter = QPainter(self)
            if painter.isActive():
                try:
                    painter.fillRect(self.rect(), QColor(0, 0, 0, 50))
                finally:
                    if painter.isActive():
                        painter.end()

    def toggle_edit_mode(self, enabled: bool) -> None:
        self.edit_mode = enabled

        self.hide()
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        if not enabled:
            flags |= Qt.WindowTransparentForInput
        self.setWindowFlags(flags)

        for widget in self.widgets.values():
            widget.set_edit_mode(enabled)

        if enabled:
            if self.save_btn is None:
                self.save_btn = QPushButton("Save Layout & Exit", self)
                self.save_btn.setStyleSheet(
                    """
                    QPushButton {
                        background-color: #22c55e;
                        color: white;
                        font-weight: bold;
                        font-size: 16px;
                        padding: 8px 16px;
                        border-radius: 5px;
                        border: 1px solid #15803d;
                    }
                    QPushButton:hover {
                        background-color: #15803d;
                    }
                    """
                )
                self.save_btn.clicked.connect(self._on_save_clicked)
            self.save_btn.show()
            self._position_save_btn()
        elif self.save_btn is not None:
            self.save_btn.hide()

        self.show()

    def _position_save_btn(self) -> None:
        if self.save_btn is None:
            return
        target_rect = self._visible_local_rect()
        width = 280
        height = 40
        self.save_btn.resize(width, height)
        x = target_rect.left() + (target_rect.width() - width) // 2
        if target_rect.width() >= width:
            x = min(max(target_rect.left(), x), target_rect.right() + 1 - width)
        else:
            x = target_rect.left()
        y = target_rect.bottom() + 1 - height - 60
        if target_rect.height() >= height + 48:
            y = min(max(target_rect.top() + 24, y), target_rect.bottom() + 1 - height - 24)
        else:
            y = target_rect.top()
        self.save_btn.move(x, y)
        self.save_btn.raise_()

    def _visible_local_rect(self) -> QRect:
        target_rect = self.rect()
        if target_rect.width() <= 0 or target_rect.height() <= 0:
            screen: QScreen | None = self.screen()
            if screen is None:
                screen = QApplication.primaryScreen()
            return screen.availableGeometry() if screen else QRect(0, 0, 0, 0)

        screen: QScreen | None = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return target_rect

        screen_rect = screen.availableGeometry()
        window_top_left = self.geometry().topLeft()
        visible_left = max(0, screen_rect.left() - window_top_left.x())
        visible_top = max(0, screen_rect.top() - window_top_left.y())
        visible_right = min(target_rect.width(), screen_rect.right() + 1 - window_top_left.x())
        visible_bottom = min(target_rect.height(), screen_rect.bottom() + 1 - window_top_left.y())
        if visible_right <= visible_left or visible_bottom <= visible_top:
            return target_rect
        return QRect(
            visible_left,
            visible_top,
            visible_right - visible_left,
            visible_bottom - visible_top,
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.edit_mode and event.key() == Qt.Key_Escape:
            self._on_save_clicked()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_save_clicked(self) -> None:
        # Called directly rather than behind `hasattr`. The probe was the shape
        # this codebase has already been bitten by: it goes quietly false and
        # the button stops working with nothing raising -- and this button is
        # now one of only three ways out of layout mode.
        if self.parent_mixin is not None:
            self.parent_mixin._toggle_igo_edit_mode()

    def on_widget_moved(self, widget_id: str, x: int, y: int) -> None:
        config.IN_GAME_OVERLAY["widgets"][widget_id]["x"] = x
        config.IN_GAME_OVERLAY["widgets"][widget_id]["y"] = y
