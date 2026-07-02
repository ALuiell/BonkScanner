from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, Signal, Slot
from PySide6.QtGui import QMouseEvent, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QCheckBox, QDoubleSpinBox, QPushButton, QDialog, QTabWidget
)

import config
from gui_shared import UiInvoker, _make_scroll_section


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
        widget_cfg = config.IN_GAME_OVERLAY["widgets"][self.widget_id]
        self.update_scale(widget_cfg.get("scale", 1.0))
        self.move(widget_cfg["x"], widget_cfg["y"])
        self.setVisible(widget_cfg["enabled"])

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


class InGameWidgetSettingsDialog(QDialog):
    def __init__(self, parent_mixin: InGameOverlayMixin, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_mixin = parent_mixin
        self.setWindowTitle("In-Game Widgets Configuration")
        self.resize(500, 300)
        self.setMinimumSize(400, 250)
        
        main_layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        self._init_tabs()
        
        # Close button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

    def _init_tabs(self):
        # 1. Scanner Tab
        scanner_tab = QWidget()
        scanner_layout = QVBoxLayout(scanner_tab)
        
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Scale:"))
        self.scanner_scale_spin = QDoubleSpinBox()
        self.scanner_scale_spin.setRange(0.5, 3.0)
        self.scanner_scale_spin.setSingleStep(0.1)
        self.scanner_scale_spin.setValue(config.IN_GAME_OVERLAY["widgets"]["scanner"].get("scale", 1.0))
        self.scanner_scale_spin.valueChanged.connect(self._save_settings)
        scale_layout.addWidget(self.scanner_scale_spin)
        scale_layout.addStretch(1)
        scanner_layout.addLayout(scale_layout)
        scanner_layout.addStretch(1)
        self.tabs.addTab(scanner_tab, "Scanner")

        # 2. Recording Tab
        recording_tab = QWidget()
        recording_layout = QVBoxLayout(recording_tab)
        
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Scale:"))
        self.recording_scale_spin = QDoubleSpinBox()
        self.recording_scale_spin.setRange(0.5, 3.0)
        self.recording_scale_spin.setSingleStep(0.1)
        self.recording_scale_spin.setValue(config.IN_GAME_OVERLAY["widgets"]["recording"].get("scale", 1.0))
        self.recording_scale_spin.valueChanged.connect(self._save_settings)
        scale_layout.addWidget(self.recording_scale_spin)
        scale_layout.addStretch(1)
        recording_layout.addLayout(scale_layout)
        recording_layout.addStretch(1)
        self.tabs.addTab(recording_tab, "Recording")

        # 3. KPS Tab
        kps_tab = QWidget()
        kps_layout = QVBoxLayout(kps_tab)
        
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Scale:"))
        self.kps_scale_spin = QDoubleSpinBox()
        self.kps_scale_spin.setRange(0.5, 3.0)
        self.kps_scale_spin.setSingleStep(0.1)
        self.kps_scale_spin.setValue(config.IN_GAME_OVERLAY["widgets"]["kps"].get("scale", 1.0))
        self.kps_scale_spin.valueChanged.connect(self._save_settings)
        scale_layout.addWidget(self.kps_scale_spin)
        scale_layout.addStretch(1)
        kps_layout.addLayout(scale_layout)
        
        metrics_group = QGroupBox("Metrics Displayed")
        metrics_layout = QHBoxLayout(metrics_group)
        metrics_layout.setSpacing(10)
        
        selected_metrics = set(config.IN_GAME_OVERLAY["widgets"]["kps"].get("metrics", ["instant"]))
        
        self.kps_instant_cb = QCheckBox("KPS")
        self.kps_instant_cb.setChecked("instant" in selected_metrics)
        self.kps_instant_cb.stateChanged.connect(self._save_settings)
        metrics_layout.addWidget(self.kps_instant_cb)
        
        self.kps_60s_cb = QCheckBox("60s")
        self.kps_60s_cb.setChecked("60s" in selected_metrics)
        self.kps_60s_cb.stateChanged.connect(self._save_settings)
        metrics_layout.addWidget(self.kps_60s_cb)
        
        self.kps_5m_cb = QCheckBox("5m")
        self.kps_5m_cb.setChecked("5m" in selected_metrics)
        self.kps_5m_cb.stateChanged.connect(self._save_settings)
        metrics_layout.addWidget(self.kps_5m_cb)
        
        self.kps_run_cb = QCheckBox("Run")
        self.kps_run_cb.setChecked("run" in selected_metrics)
        self.kps_run_cb.stateChanged.connect(self._save_settings)
        metrics_layout.addWidget(self.kps_run_cb)
        
        kps_layout.addWidget(metrics_group)
        kps_layout.addStretch(1)
        self.tabs.addTab(kps_tab, "KPS")

        # 4. Powerups Tab
        powerups_tab = QWidget()
        powerups_layout = QVBoxLayout(powerups_tab)
        
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Scale:"))
        self.powerups_scale_spin = QDoubleSpinBox()
        self.powerups_scale_spin.setRange(0.5, 3.0)
        self.powerups_scale_spin.setSingleStep(0.1)
        self.powerups_scale_spin.setValue(config.IN_GAME_OVERLAY["widgets"]["powerups"].get("scale", 1.0))
        self.powerups_scale_spin.valueChanged.connect(self._save_settings)
        scale_layout.addWidget(self.powerups_scale_spin)
        scale_layout.addStretch(1)
        powerups_layout.addLayout(scale_layout)
        powerups_layout.addStretch(1)
        self.tabs.addTab(powerups_tab, "Powerups")

    def _save_settings(self, *_):
        widgets = config.IN_GAME_OVERLAY["widgets"]
        
        widgets["scanner"]["scale"] = self.scanner_scale_spin.value()
        widgets["recording"]["scale"] = self.recording_scale_spin.value()
        widgets["kps"]["scale"] = self.kps_scale_spin.value()
        widgets["powerups"]["scale"] = self.powerups_scale_spin.value()
        
        metrics = []
        if self.kps_instant_cb.isChecked():
            metrics.append("instant")
        if self.kps_60s_cb.isChecked():
            metrics.append("60s")
        if self.kps_5m_cb.isChecked():
            metrics.append("5m")
        if self.kps_run_cb.isChecked():
            metrics.append("run")
        widgets["kps"]["metrics"] = metrics or ["instant"]
        
        self.parent_mixin.apply_in_game_overlay_settings()
        
        if hasattr(self.parent_mixin, "save_config"):
            self.parent_mixin.save_config()


class InGameOverlayMixin:
    def initialize_in_game_overlay_runtime(self) -> None:
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
        
        # If enabled AND auto_start is true, show it on startup
        if config.IN_GAME_OVERLAY["enabled"] and config.IN_GAME_OVERLAY.get("auto_start", False):
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
            
        for wid, w_cfg in cfg["widgets"].items():
            widget = self.in_game_overlay_window.widgets.get(wid)
            if widget:
                widget.setVisible(w_cfg["enabled"])
                widget.update_scale(w_cfg.get("scale", 1.0))
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
            metrics_cfg = cfg["widgets"]["kps"].get("metrics", ["instant"])
            
            kps_vals = []
            
            # Map values
            for m in metrics_cfg:
                if m == "instant":
                    val = getattr(self.live_run_tracker, "current_ui_kps", lambda: None)()
                    lbl = "KPS"
                elif m == "60s":
                    val = getattr(self.live_run_tracker, "current_minute_avg_kps", lambda: None)()
                    lbl = "60s"
                elif m == "5m":
                    val = getattr(self.live_run_tracker, "current_five_minute_avg_kps", lambda: None)()
                    lbl = "5m"
                elif m == "run":
                    val = getattr(self.live_run_tracker, "current_run_avg_kps", lambda: None)()
                    lbl = "Run"
                else:
                    continue
                
                val_str = f"{val}" if val is not None else "--"
                kps_vals.append(f"{lbl} {val_str}")
            
            # Join with double spaces to look like a horizontal strip
            strip_text = "  ".join(kps_vals)
            
            text = f"<span style='color: white; -webkit-text-stroke: 1px black; text-shadow: -1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000;'>⚔️ {strip_text}</span>"
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
        self.tab_in_game_overlay = QWidget()
        tab_layout = QVBoxLayout(self.tab_in_game_overlay)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create scroll area (matches OBS tab structure)
        scroll, scroll_content, layout = _make_scroll_section()
        layout.setSpacing(10)
        tab_layout.addWidget(scroll)
        
        grid_layout = QGridLayout()
        grid_layout.setSpacing(16)
        grid_layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(grid_layout)
        
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 2)
        
        # 1. General Settings Card (Left Column)
        general_group = QGroupBox("General Settings")
        general_layout = QVBoxLayout(general_group)
        general_layout.setContentsMargins(16, 12, 16, 12)
        general_layout.setSpacing(10)
        
        self.igo_enable_cb = QCheckBox("Enable In-Game Overlay")
        self.igo_enable_cb.setChecked(config.IN_GAME_OVERLAY.get("enabled", False))
        self.igo_enable_cb.stateChanged.connect(self._on_igo_settings_changed)
        general_layout.addWidget(self.igo_enable_cb)
        
        self.igo_auto_start_cb = QCheckBox("Auto-start overlay")
        self.igo_auto_start_cb.setChecked(config.IN_GAME_OVERLAY.get("auto_start", False))
        self.igo_auto_start_cb.setToolTip("Start the transparent overlay automatically when the application starts.")
        self.igo_auto_start_cb.stateChanged.connect(self._on_igo_settings_changed)
        general_layout.addWidget(self.igo_auto_start_cb)
        
        self.igo_edit_btn = QPushButton("Edit Layout")
        self.igo_edit_btn.setMinimumHeight(36)
        self.igo_edit_btn.clicked.connect(self._toggle_igo_edit_mode)
        general_layout.addWidget(self.igo_edit_btn)
        
        # 2. Active Widgets Card (Right Column)
        widgets_group = QGroupBox("Active Widgets")
        widgets_layout = QVBoxLayout(widgets_group)
        widgets_layout.setContentsMargins(16, 12, 16, 12)
        widgets_layout.setSpacing(10)
        
        widgets_header_layout = QHBoxLayout()
        widgets_header_layout.setContentsMargins(4, 0, 0, 0)
        widgets_header_lbl = QLabel("Active Overlay Widgets:")
        widgets_header_lbl.setStyleSheet("font-weight: bold;")
        
        self.igo_widget_settings_btn = QPushButton("Widget Settings")
        self.igo_widget_settings_btn.clicked.connect(self._open_igo_widget_settings_dialog)
        
        widgets_header_layout.addWidget(widgets_header_lbl)
        widgets_header_layout.addStretch(1)
        widgets_header_layout.addWidget(self.igo_widget_settings_btn)
        widgets_layout.addLayout(widgets_header_layout)
        
        # 2x2 grid for widgets checkboxes
        widgets_grid = QGridLayout()
        widgets_grid.setSpacing(10)
        
        self.igo_scanner_cb = QCheckBox("Scanner Status")
        self.igo_scanner_cb.setChecked(config.IN_GAME_OVERLAY["widgets"]["scanner"]["enabled"])
        self.igo_scanner_cb.stateChanged.connect(self._on_igo_settings_changed)
        widgets_grid.addWidget(self.igo_scanner_cb, 0, 0)
        
        self.igo_recording_cb = QCheckBox("Recording Status")
        self.igo_recording_cb.setChecked(config.IN_GAME_OVERLAY["widgets"]["recording"]["enabled"])
        self.igo_recording_cb.stateChanged.connect(self._on_igo_settings_changed)
        widgets_grid.addWidget(self.igo_recording_cb, 0, 1)
        
        self.igo_kps_cb = QCheckBox("KPS")
        self.igo_kps_cb.setChecked(config.IN_GAME_OVERLAY["widgets"]["kps"]["enabled"])
        self.igo_kps_cb.stateChanged.connect(self._on_igo_settings_changed)
        widgets_grid.addWidget(self.igo_kps_cb, 1, 0)
        
        self.igo_powerups_cb = QCheckBox("Active Powerups (Buffs)")
        self.igo_powerups_cb.setChecked(config.IN_GAME_OVERLAY["widgets"]["powerups"]["enabled"])
        self.igo_powerups_cb.stateChanged.connect(self._on_igo_settings_changed)
        widgets_grid.addWidget(self.igo_powerups_cb, 1, 1)
        
        widgets_layout.addLayout(widgets_grid)
        
        # Add cards to layout
        grid_layout.addWidget(general_group, 0, 0, Qt.AlignTop)
        grid_layout.addWidget(widgets_group, 0, 1, Qt.AlignTop)
        grid_layout.setRowStretch(1, 1)

    def _on_igo_settings_changed(self, *_):
        cfg = config.IN_GAME_OVERLAY
        cfg["enabled"] = self.igo_enable_cb.isChecked()
        cfg["auto_start"] = self.igo_auto_start_cb.isChecked()
        
        cfg["widgets"]["scanner"]["enabled"] = self.igo_scanner_cb.isChecked()
        cfg["widgets"]["recording"]["enabled"] = self.igo_recording_cb.isChecked()
        cfg["widgets"]["kps"]["enabled"] = self.igo_kps_cb.isChecked()
        cfg["widgets"]["powerups"]["enabled"] = self.igo_powerups_cb.isChecked()
        
        self.apply_in_game_overlay_settings()
        
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

    def _open_igo_widget_settings_dialog(self):
        dialog = InGameWidgetSettingsDialog(self, self.tab_in_game_overlay)
        dialog.exec()
