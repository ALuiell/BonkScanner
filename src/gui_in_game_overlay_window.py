from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
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

import config
from gui_in_game_overlay_render import (
    LUCK_RARITY_ORDER,
    build_luck_rarity_overlay_html_for_probabilities,
)
from gui_styles import ITEM_RARITY_COLOR_MAP

if TYPE_CHECKING:
    from gui_in_game_overlay import InGameOverlayMixin


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
            self.move(self.mapToParent(event.pos() - self._drag_start_pos))
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.edit_mode and event.button() == Qt.LeftButton:
            self._dragging = False
            self.moved.emit(self.widget_id, self.x(), self.y())
            event.accept()

    def set_text(self, text: str) -> None:
        if self.label.text() != text:
            self.label.setText(text)
            self.adjustSize()


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
    def __init__(self, widget_id: str, parent: QWidget | None = None):
        self._current_probabilities: dict[str, float | None] = {
            rarity: None for rarity in LUCK_RARITY_ORDER
        }
        super().__init__(widget_id, parent)
        self.bar_widget = LuckRarityBarWidget(self)
        self._widget_layout.addWidget(self.bar_widget)
        widget_cfg = config.IN_GAME_OVERLAY["widgets"][self.widget_id]
        self.bar_widget.set_show_bar(widget_cfg.get("show_bar", True))
        self.update_scale(widget_cfg.get("scale", 1.0))

    def update_scale(self, scale: float) -> None:
        super().update_scale(scale)
        if hasattr(self, "bar_widget"):
            self.bar_widget.set_bar_scale(scale)
            self.adjustSize()

    def set_probabilities(self, probabilities: dict[str, float | None], *, show_bar: bool) -> None:
        self._current_probabilities = dict(probabilities)
        self.set_text(build_luck_rarity_overlay_html_for_probabilities(probabilities))
        self.bar_widget.set_probabilities(probabilities, show_bar)
        self.adjustSize()

    def set_show_bar(self, show_bar: bool) -> None:
        self.bar_widget.set_show_bar(show_bar)
        self.adjustSize()


class InGameOverlayWindow(QWidget):
    def __init__(self, parent_mixin: InGameOverlayMixin, parent: QWidget | None = None):
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

        self.widgets: dict[str, DraggableOverlayWidget] = {}
        for widget_id in ("scanner", "recording", "kps", "powerups", "luck_rarity", "stats", "event_timer"):
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
            QTimer.singleShot(0, self._position_save_btn)
        super().showEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
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
        if self.edit_mode:
            self._position_save_btn()

    def paintEvent(self, event) -> None:
        if self.edit_mode:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 50))
        super().paintEvent(event)

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
        if self.parent_mixin and hasattr(self.parent_mixin, "_toggle_igo_edit_mode"):
            self.parent_mixin._toggle_igo_edit_mode()

    def on_widget_moved(self, widget_id: str, x: int, y: int) -> None:
        config.IN_GAME_OVERLAY["widgets"][widget_id]["x"] = x
        config.IN_GAME_OVERLAY["widgets"][widget_id]["y"] = y
