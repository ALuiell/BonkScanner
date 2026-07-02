from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, Signal, Slot
from PySide6.QtGui import QMouseEvent, QPainter, QColor, QFont
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QFrame

import config
from gui_shared import UiInvoker


class DraggableOverlayWidget(QWidget):
    moved = Signal(str, int, int)

    def __init__(self, widget_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.widget_id = widget_id
        self._dragging = False
        self._drag_start_pos = QPoint()
        self.edit_mode = False
        self.setMouseTracking(True)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(2)

        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.layout.addWidget(self.label)
        
        # Apply initial settings
        self.update_scale(config.IN_GAME_OVERLAY.get("scale", 1.0))
        self.move(
            config.IN_GAME_OVERLAY["widgets"][self.widget_id]["x"],
            config.IN_GAME_OVERLAY["widgets"][self.widget_id]["y"]
        )
        self.setVisible(config.IN_GAME_OVERLAY["widgets"][self.widget_id]["enabled"])

    def update_scale(self, scale: float):
        base_size = 16
        font = self.label.font()
        font.setPixelSize(int(base_size * scale))
        font.setWeight(QFont.Bold)
        self.label.setFont(font)
        self.adjustSize()

    def set_edit_mode(self, enabled: bool):
        self.edit_mode = enabled
        if enabled:
            self.setStyleSheet("background-color: rgba(0, 0, 0, 150); border: 1px dashed rgba(255, 255, 255, 100);")
        else:
            self.setStyleSheet("background-color: transparent; border: none;")

    def mousePressEvent(self, event: QMouseEvent):
        if self.edit_mode and event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start_pos = event.pos()
            self.raise_()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.edit_mode and self._dragging:
            new_pos = self.mapToParent(event.pos() - self._drag_start_pos)
            self.move(new_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.edit_mode and event.button() == Qt.LeftButton:
            self._dragging = False
            self.moved.emit(self.widget_id, self.x(), self.y())
            event.accept()

    def set_text(self, text: str):
        if self.label.text() != text:
            self.label.setText(text)
            self.adjustSize()


class InGameOverlayWindow(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.edit_mode = False
        
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.widgets: dict[str, DraggableOverlayWidget] = {}
        
        self.widgets["scanner"] = DraggableOverlayWidget("scanner", self)
        self.widgets["recording"] = DraggableOverlayWidget("recording", self)
        self.widgets["kps"] = DraggableOverlayWidget("kps", self)
        self.widgets["powerups"] = DraggableOverlayWidget("powerups", self)
        
        for w in self.widgets.values():
            w.moved.connect(self.on_widget_moved)

    def showEvent(self, event):
        screen = self.screen()
        if screen:
            self.setGeometry(screen.geometry())
        super().showEvent(event)

    def paintEvent(self, event):
        if self.edit_mode:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 50))
        super().paintEvent(event)

    def toggle_edit_mode(self, enabled: bool):
        self.edit_mode = enabled
        
        # To change WindowTransparentForInput, we need to hide, change flags, and show again
        self.hide()
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        if not enabled:
            flags |= Qt.WindowTransparentForInput
            
        self.setWindowFlags(flags)
        
        for w in self.widgets.values():
            w.set_edit_mode(enabled)
            
        self.show()

    def on_widget_moved(self, widget_id: str, x: int, y: int):
        config.IN_GAME_OVERLAY["widgets"][widget_id]["x"] = x
        config.IN_GAME_OVERLAY["widgets"][widget_id]["y"] = y


class InGameOverlayMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.in_game_overlay_window = None
        
        self.overlay_fast_timer = QTimer()
        self.overlay_fast_timer.timeout.connect(self._overlay_fast_tick)
        self.overlay_fast_timer.setInterval(500)
        
        self.overlay_slow_timer = QTimer()
        self.overlay_slow_timer.timeout.connect(self._overlay_slow_tick)
        self.overlay_slow_timer.setInterval(10000)
        
        # Setup ui after app is ready
        UiInvoker.invoke(self._init_in_game_overlay)

    def _init_in_game_overlay(self):
        self.in_game_overlay_window = InGameOverlayWindow()
        
        if config.IN_GAME_OVERLAY["enabled"]:
            self.start_in_game_overlay()

    def start_in_game_overlay(self):
        if not self.in_game_overlay_window:
            return
        self.in_game_overlay_window.show()
        self.overlay_fast_timer.start()
        self.overlay_slow_timer.start()
        self._overlay_fast_tick()
        self._overlay_slow_tick()

    def stop_in_game_overlay(self):
        if self.in_game_overlay_window:
            self.in_game_overlay_window.hide()
        self.overlay_fast_timer.stop()
        self.overlay_slow_timer.stop()

    def apply_in_game_overlay_settings(self):
        cfg = config.IN_GAME_OVERLAY
        if not self.in_game_overlay_window:
            return
            
        if cfg["enabled"]:
            if not self.in_game_overlay_window.isVisible():
                self.start_in_game_overlay()
        else:
            self.stop_in_game_overlay()
            
        scale = cfg.get("scale", 1.0)
        for wid, w_cfg in cfg["widgets"].items():
            widget = self.in_game_overlay_window.widgets.get(wid)
            if widget:
                widget.setVisible(w_cfg["enabled"])
                widget.update_scale(scale)
                if not self.in_game_overlay_window.edit_mode:
                    widget.move(w_cfg["x"], w_cfg["y"])
                    
        self._overlay_fast_tick()
        self._overlay_slow_tick()

    def _overlay_fast_tick(self):
        if not self.in_game_overlay_window or not self.in_game_overlay_window.isVisible():
            return
            
        widgets = self.in_game_overlay_window.widgets
        cfg = config.IN_GAME_OVERLAY
        
        # Update KPS
        if cfg["widgets"]["kps"]["enabled"]:
            mode = cfg["widgets"]["kps"].get("mode", "instant")
            
            kps_instant = getattr(self.live_run_tracker, "current_ui_kps", lambda: None)()
            kps_60s = getattr(self.live_run_tracker, "current_minute_avg_kps", lambda: None)()
            kps_5m = getattr(self.live_run_tracker, "current_five_minute_avg_kps", lambda: None)()
            kps_run = getattr(self.live_run_tracker, "current_run_avg_kps", lambda: None)()
            
            val = "--"
            if mode == "instant" and kps_instant is not None:
                val = str(kps_instant)
            elif mode == "60s" and kps_60s is not None:
                val = str(kps_60s)
            elif mode == "5m" and kps_5m is not None:
                val = str(kps_5m)
            elif mode == "run" and kps_run is not None:
                val = str(kps_run)
            
            text = f"<span style='color: white; -webkit-text-stroke: 1px black; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;'>⚔️ KPS: {val}</span>"
            widgets["kps"].set_text(text)

        # Update Powerups
        if cfg["widgets"]["powerups"]["enabled"]:
            snapshot = getattr(self.live_run_tracker, "powerups_snapshot", lambda: None)()
            if snapshot and snapshot.active:
                lines = []
                for p in snapshot.active:
                    name = p.name
                    time_left = max(0, p.remaining_seconds)
                    lines.append(f"{name}: {time_left:.1f}s")
                content = "<br>".join(lines)
                text = f"<span style='color: #a855f7; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;'>⭐ Powerups:<br>{content}</span>"
            else:
                text = "<span style='color: #a855f7; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;'>⭐ Powerups: None</span>"
            widgets["powerups"].set_text(text)

    def _overlay_slow_tick(self):
        if not self.in_game_overlay_window or not self.in_game_overlay_window.isVisible():
            return
            
        widgets = self.in_game_overlay_window.widgets
        cfg = config.IN_GAME_OVERLAY
        
        # Update Scanner
        if cfg["widgets"]["scanner"]["enabled"]:
            is_active = getattr(self.logic, "scanner_active", False)
            color = "#22c55e" if is_active else "#ef4444"
            status = "🟢" if is_active else "🔴"
            text = f"<span style='color: {color}; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;'>Scanner {status}</span>"
            widgets["scanner"].set_text(text)
            
        # Update Recording
        if cfg["widgets"]["recording"]["enabled"]:
            is_rec = getattr(self.vod_recorder, "is_recording", False)
            color = "#ef4444" if is_rec else "#9ca3af"
            status = "🔴" if is_rec else "⚪"
            text = f"<span style='color: {color}; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;'>REC {status}</span>"
            widgets["recording"].set_text(text)

    def _build_in_game_overlay_tab(self) -> None:
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QCheckBox, QComboBox, QDoubleSpinBox, QPushButton
        
        self.tab_in_game_overlay = QWidget()
        tab_layout = QVBoxLayout(self.tab_in_game_overlay)
        tab_layout.setContentsMargins(8, 8, 8, 8)
        tab_layout.setSpacing(16)
        
        # 1. General Settings Card
        general_group = QGroupBox("General Settings")
        general_layout = QVBoxLayout(general_group)
        general_layout.setContentsMargins(16, 12, 16, 12)
        general_layout.setSpacing(10)
        
        enable_row = QHBoxLayout()
        self.igo_enable_cb = QCheckBox("Enable In-Game Overlay")
        self.igo_enable_cb.setChecked(config.IN_GAME_OVERLAY.get("enabled", False))
        self.igo_enable_cb.stateChanged.connect(self._on_igo_settings_changed)
        enable_row.addWidget(self.igo_enable_cb)
        enable_row.addStretch(1)
        general_layout.addLayout(enable_row)
        
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Scale:"))
        self.igo_scale_spin = QDoubleSpinBox()
        self.igo_scale_spin.setRange(0.5, 3.0)
        self.igo_scale_spin.setSingleStep(0.1)
        self.igo_scale_spin.setValue(config.IN_GAME_OVERLAY.get("scale", 1.0))
        self.igo_scale_spin.valueChanged.connect(self._on_igo_settings_changed)
        scale_row.addWidget(self.igo_scale_spin)
        scale_row.addStretch(1)
        general_layout.addLayout(scale_row)
        
        edit_btn = QPushButton("Edit Layout")
        edit_btn.setMinimumHeight(36)
        edit_btn.clicked.connect(self._toggle_igo_edit_mode)
        self.igo_edit_btn = edit_btn
        general_layout.addWidget(edit_btn)
        
        tab_layout.addWidget(general_group)
        
        # 2. Widgets Card
        widgets_group = QGroupBox("Active Widgets")
        widgets_layout = QVBoxLayout(widgets_group)
        widgets_layout.setContentsMargins(16, 12, 16, 12)
        widgets_layout.setSpacing(10)
        
        self.igo_scanner_cb = QCheckBox("Scanner Status")
        self.igo_scanner_cb.setChecked(config.IN_GAME_OVERLAY["widgets"]["scanner"]["enabled"])
        self.igo_scanner_cb.stateChanged.connect(self._on_igo_settings_changed)
        widgets_layout.addWidget(self.igo_scanner_cb)
        
        self.igo_recording_cb = QCheckBox("Recording Status")
        self.igo_recording_cb.setChecked(config.IN_GAME_OVERLAY["widgets"]["recording"]["enabled"])
        self.igo_recording_cb.stateChanged.connect(self._on_igo_settings_changed)
        widgets_layout.addWidget(self.igo_recording_cb)
        
        kps_row = QHBoxLayout()
        self.igo_kps_cb = QCheckBox("KPS")
        self.igo_kps_cb.setChecked(config.IN_GAME_OVERLAY["widgets"]["kps"]["enabled"])
        self.igo_kps_cb.stateChanged.connect(self._on_igo_settings_changed)
        kps_row.addWidget(self.igo_kps_cb)
        
        self.igo_kps_mode = QComboBox()
        self.igo_kps_mode.addItems(["instant", "60s", "5m", "run"])
        self.igo_kps_mode.setCurrentText(config.IN_GAME_OVERLAY["widgets"]["kps"]["mode"])
        self.igo_kps_mode.currentTextChanged.connect(self._on_igo_settings_changed)
        kps_row.addWidget(self.igo_kps_mode)
        kps_row.addStretch(1)
        widgets_layout.addLayout(kps_row)
        
        self.igo_powerups_cb = QCheckBox("Active Powerups (Buffs)")
        self.igo_powerups_cb.setChecked(config.IN_GAME_OVERLAY["widgets"]["powerups"]["enabled"])
        self.igo_powerups_cb.stateChanged.connect(self._on_igo_settings_changed)
        widgets_layout.addWidget(self.igo_powerups_cb)
        
        tab_layout.addWidget(widgets_group)
        tab_layout.addStretch(1)

    def _on_igo_settings_changed(self, *_):
        cfg = config.IN_GAME_OVERLAY
        cfg["enabled"] = self.igo_enable_cb.isChecked()
        cfg["scale"] = self.igo_scale_spin.value()
        
        cfg["widgets"]["scanner"]["enabled"] = self.igo_scanner_cb.isChecked()
        cfg["widgets"]["recording"]["enabled"] = self.igo_recording_cb.isChecked()
        cfg["widgets"]["kps"]["enabled"] = self.igo_kps_cb.isChecked()
        cfg["widgets"]["kps"]["mode"] = self.igo_kps_mode.currentText()
        cfg["widgets"]["powerups"]["enabled"] = self.igo_powerups_cb.isChecked()
        
        self.apply_in_game_overlay_settings()
        
        # Trigger save to config file if there's a mechanism, e.g. via main window
        if hasattr(self, 'save_config'):
            self.save_config()

    def _toggle_igo_edit_mode(self):
        if not self.in_game_overlay_window:
            return
            
        is_edit = not self.in_game_overlay_window.edit_mode
        self.in_game_overlay_window.toggle_edit_mode(is_edit)
        
        if is_edit:
            self.igo_edit_btn.setText("Save Layout")
            self.igo_edit_btn.setStyleSheet("background-color: #22c55e; color: white;")
            # Force enable so user can see what they are moving
            if not self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.show()
        else:
            self.igo_edit_btn.setText("Edit Layout")
            self.igo_edit_btn.setStyleSheet("")
            self.apply_in_game_overlay_settings() # Save and hide if disabled
            if hasattr(self, 'save_config'):
                self.save_config()
