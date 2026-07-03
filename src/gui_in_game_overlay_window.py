from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QScreen
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

import config

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

        widget_cfg = config.IN_GAME_OVERLAY["widgets"][self.widget_id]
        self.update_scale(widget_cfg.get("scale", 1.0))
        self.move(widget_cfg["x"], widget_cfg["y"])
        self.setVisible(widget_cfg["enabled"])

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
        for widget_id in ("scanner", "recording", "kps", "powerups"):
            widget = DraggableOverlayWidget(widget_id, self)
            widget.moved.connect(self.on_widget_moved)
            self.widgets[widget_id] = widget

        self.save_btn: QPushButton | None = None

    def showEvent(self, event) -> None:
        self.sync_geometry_to_target()
        super().showEvent(event)

    def sync_geometry_to_target(self) -> None:
        geometry = None
        parent_mixin = getattr(self, "parent_mixin", None)
        if parent_mixin and hasattr(parent_mixin, "_in_game_overlay_target_geometry"):
            geometry = parent_mixin._in_game_overlay_target_geometry()
        if geometry is not None and geometry.isValid() and geometry != self.geometry():
            self.setGeometry(geometry)

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
                self.save_btn = QPushButton("Save Layout & Exit Edit Mode", self)
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
        target_rect = self.rect()
        if target_rect.width() <= 0 or target_rect.height() <= 0:
            screen: QScreen | None = self.screen()
            if screen is None:
                screen = QApplication.primaryScreen()
            target_rect = screen.geometry() if screen else QRect(0, 0, 0, 0)
        width = 280
        height = 40
        self.save_btn.resize(width, height)
        self.save_btn.move(
            max(0, (target_rect.width() - width) // 2),
            max(0, target_rect.height() - height - 60),
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
