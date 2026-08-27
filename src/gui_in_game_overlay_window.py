from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QMoveEvent,
    QPainter,
    QPainterPath,
    QPen,
    QResizeEvent,
    QScreen,
)
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app import config
from core.map_markers import (
    MAP_MARKER_ACTION_BY_ID,
    MarkerPalette,
    MapMarkerSnapshot,
    map_marker_screen_geometry,
)
from projections.in_game_html import (
    LUCK_EXPECTED_DEFAULT_LAYOUT,
    LUCK_RARITY_ORDER,
    build_luck_expected_overlay_html,
    build_luck_rarity_overlay_html_for_probabilities,
)
from core.item_metadata import ITEM_RARITY_COLOR_MAP
from ui.shared import resource_path

if TYPE_CHECKING:
    from gui_in_game_overlay import InGameOverlay


class MapMarkerLayer(QWidget):
    """Click-through painter aligned to the game's live Full Map RectTransform."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._snapshot = MapMarkerSnapshot()
        self._palette: MarkerPalette | None = None
        self._scale = 1.0
        self._icons = {
            action.icon_name: QIcon(
                resource_path(
                    f"media/map_markers/pictograms/{action.icon_name}.svg"
                )
            )
            for action in MAP_MARKER_ACTION_BY_ID.values()
        }
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.hide()

    def set_snapshot(self, snapshot: MapMarkerSnapshot, *, scale: float) -> None:
        normalized_scale = max(0.5, min(float(scale), 3.0))
        changed = snapshot != self._snapshot or normalized_scale != self._scale
        was_shown = not self.isHidden()
        self._snapshot = snapshot
        self._scale = normalized_scale
        if not snapshot.map_open:
            self._palette = None
        should_show = self._should_show()
        if should_show != was_shown:
            self.setVisible(should_show)
        if should_show and (changed or not was_shown):
            self.raise_()
        if changed:
            self.update()

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
        return bool(
            self._snapshot.map_open
            and self._snapshot.viewport is not None
            and (self._snapshot.markers or self._palette is not None)
        )

    def paintEvent(self, event) -> None:
        snapshot = self._snapshot
        viewport = snapshot.viewport
        if not snapshot.map_open or viewport is None:
            return

        painter = QPainter(self)
        if not painter.isActive():
            return
        try:
            self._paint_snapshot(painter, snapshot, viewport)
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
            icon_size = int(icon_size_value)
            pictogram_size = max(12, int(round(icon_size * 0.68)))
            half = icon_size / 2.0
            bounds = QRectF(
                center_x - half,
                center_y - half,
                float(icon_size),
                float(icon_size),
            )

            outline = QColor(action.outline_color)
            outline.setAlpha(225)
            painter.setPen(QPen(outline, max(2, icon_size // 11)))
            fill = QColor(action.color)
            fill.setAlpha(232)
            painter.setBrush(fill)
            painter.drawEllipse(bounds)

            if marker.source == "manual":
                manual_pen = QPen(QColor(255, 255, 255, 205), 1.4)
                manual_pen.setStyle(Qt.DashLine)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(manual_pen)
                painter.drawEllipse(bounds.adjusted(-2, -2, 2, 2))

            icon = self._icons.get(action.icon_name)
            if icon is not None:
                pixmap = icon.pixmap(pictogram_size, pictogram_size)
                painter.drawPixmap(
                    int(round(center_x - pictogram_size / 2.0)),
                    int(round(center_y - pictogram_size / 2.0)),
                    pixmap,
                )

        self._paint_palette(painter)

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

            swatch_size = row.height * 0.58
            swatch = QRectF(
                row.left + row.height * 0.20,
                row.top + (row.height - swatch_size) / 2.0,
                swatch_size,
                swatch_size,
            )
            outline = QColor(action.outline_color)
            outline.setAlpha(220)
            painter.setPen(QPen(outline, 1.2))
            painter.setBrush(QColor(action.color))
            painter.drawEllipse(swatch)

            icon = self._icons.get(action.icon_name)
            if icon is not None:
                pictogram = max(10, int(round(swatch_size * 0.72)))
                painter.drawPixmap(
                    int(round(swatch.center().x() - pictogram / 2.0)),
                    int(round(swatch.center().y() - pictogram / 2.0)),
                    icon.pixmap(pictogram, pictogram),
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
        for widget_id in ("scanner", "recording", "kps", "powerups", "luck_rarity", "stats", "event_timer", "item_cooldowns", "build_progression"):
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
