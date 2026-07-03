from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from gui_shared import _make_scroll_section
from gui_styles import _button_state_stylesheet


class InGameWidgetSettingsDialog(QDialog):
    def __init__(self, parent_mixin: Any, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_mixin = parent_mixin
        self.setWindowTitle("In-Game Widgets Configuration")
        self.resize(600, 650)
        self.setMinimumSize(500, 450)

        main_layout = QVBoxLayout(self)
        scroll, _scroll_content, scroll_layout = _make_scroll_section()
        scroll_layout.setSpacing(16)
        main_layout.addWidget(scroll)
        self._init_settings_layout(scroll_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

    def _init_settings_layout(self, layout) -> None:
        _add_scale_group(
            layout,
            title="Scanner Status Settings",
            attr_name="scanner_scale_spin",
            widget_id="scanner",
            parent=self,
        )
        _add_scale_group(
            layout,
            title="Recording Status Settings",
            attr_name="recording_scale_spin",
            widget_id="recording",
            parent=self,
        )

        kps_group = QGroupBox("KPS Settings")
        kps_layout = QVBoxLayout(kps_group)
        kps_layout.setContentsMargins(16, 12, 16, 12)
        _add_scale_row(kps_layout, self, "kps_scale_spin", "kps")

        metrics_group = QGroupBox("Metrics Displayed")
        metrics_layout = QHBoxLayout(metrics_group)
        metrics_layout.setSpacing(10)
        selected_metrics = set(config.IN_GAME_OVERLAY["widgets"]["kps"].get("metrics", ["instant"]))

        self.kps_instant_cb = _build_checkbox("KPS", "instant" in selected_metrics, self._save_settings)
        metrics_layout.addWidget(self.kps_instant_cb)
        self.kps_60s_cb = _build_checkbox("60s", "60s" in selected_metrics, self._save_settings)
        metrics_layout.addWidget(self.kps_60s_cb)
        self.kps_5m_cb = _build_checkbox("5m", "5m" in selected_metrics, self._save_settings)
        metrics_layout.addWidget(self.kps_5m_cb)
        self.kps_run_cb = _build_checkbox("Run", "run" in selected_metrics, self._save_settings)
        metrics_layout.addWidget(self.kps_run_cb)

        kps_layout.addWidget(metrics_group)
        layout.addWidget(kps_group)

        _add_scale_group(
            layout,
            title="Active Powerups Settings",
            attr_name="powerups_scale_spin",
            widget_id="powerups",
            parent=self,
        )
        _add_scale_group(
            layout,
            title="Luck Rarity Settings",
            attr_name="luck_rarity_scale_spin",
            widget_id="luck_rarity",
            parent=self,
        )
        layout.addStretch(1)

    def _save_settings(self, *_args) -> None:
        widgets = config.IN_GAME_OVERLAY["widgets"]
        widgets["scanner"]["scale"] = self.scanner_scale_spin.value()
        widgets["recording"]["scale"] = self.recording_scale_spin.value()
        widgets["kps"]["scale"] = self.kps_scale_spin.value()
        widgets["powerups"]["scale"] = self.powerups_scale_spin.value()
        widgets["luck_rarity"]["scale"] = self.luck_rarity_scale_spin.value()

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
        config.save_config(config.user_config)


def build_in_game_overlay_tab(parent_mixin: Any) -> None:
    parent_mixin.tab_in_game_overlay = QWidget()
    tab_layout = QVBoxLayout(parent_mixin.tab_in_game_overlay)
    tab_layout.setContentsMargins(0, 0, 0, 0)

    scroll, _scroll_content, layout = _make_scroll_section()
    layout.setSpacing(10)
    tab_layout.addWidget(scroll)

    grid_layout = QGridLayout()
    grid_layout.setSpacing(16)
    grid_layout.setContentsMargins(8, 8, 8, 8)
    grid_layout.setColumnStretch(0, 1)
    grid_layout.setColumnStretch(1, 2)
    layout.addLayout(grid_layout)

    general_group = QGroupBox("General Settings")
    general_layout = QVBoxLayout(general_group)
    general_layout.setContentsMargins(16, 12, 16, 12)
    general_layout.setSpacing(10)

    status_row = QHBoxLayout()
    status_row.setContentsMargins(0, 0, 0, 0)
    status_row.addWidget(QLabel("Overlay Status:"))
    parent_mixin.igo_status_label = QLabel()
    parent_mixin.igo_status_label.setTextFormat(Qt.RichText)
    status_row.addWidget(parent_mixin.igo_status_label)
    status_row.addStretch(1)
    general_layout.addLayout(status_row)

    parent_mixin.igo_auto_start_cb = QCheckBox("Auto-start overlay")
    parent_mixin.igo_auto_start_cb.setChecked(config.IN_GAME_OVERLAY.get("auto_start", False))
    parent_mixin.igo_auto_start_cb.setToolTip(
        "Start the transparent overlay automatically when the application starts."
    )
    parent_mixin.igo_auto_start_cb.stateChanged.connect(parent_mixin._on_igo_settings_changed)
    general_layout.addWidget(parent_mixin.igo_auto_start_cb)

    parent_mixin.igo_toggle_btn = QPushButton("Start Overlay")
    parent_mixin.igo_toggle_btn.setObjectName("SuccessButton")
    parent_mixin.igo_toggle_btn.setMinimumHeight(36)
    btn_font = parent_mixin.igo_toggle_btn.font()
    btn_font.setBold(True)
    parent_mixin.igo_toggle_btn.setFont(btn_font)
    parent_mixin.igo_toggle_btn.clicked.connect(parent_mixin._toggle_in_game_overlay)
    general_layout.addWidget(parent_mixin.igo_toggle_btn)

    parent_mixin.igo_edit_btn = QPushButton("Edit Layout")
    parent_mixin.igo_edit_btn.setMinimumHeight(36)
    parent_mixin.igo_edit_btn.clicked.connect(parent_mixin._toggle_igo_edit_mode)
    general_layout.addWidget(parent_mixin.igo_edit_btn)

    widgets_group = QGroupBox("Active Widgets")
    widgets_layout = QVBoxLayout(widgets_group)
    widgets_layout.setContentsMargins(16, 12, 16, 12)
    widgets_layout.setSpacing(10)

    widgets_header_layout = QHBoxLayout()
    widgets_header_layout.setContentsMargins(4, 0, 0, 0)
    widgets_header_lbl = QLabel("Active Overlay Widgets:")
    widgets_header_lbl.setStyleSheet("font-weight: bold;")

    parent_mixin.igo_widget_settings_btn = QPushButton("Widget Settings")
    parent_mixin.igo_widget_settings_btn.clicked.connect(parent_mixin._open_igo_widget_settings_dialog)

    widgets_header_layout.addWidget(widgets_header_lbl)
    widgets_header_layout.addStretch(1)
    widgets_header_layout.addWidget(parent_mixin.igo_widget_settings_btn)
    widgets_layout.addLayout(widgets_header_layout)

    widgets_grid = QGridLayout()
    widgets_grid.setSpacing(10)

    parent_mixin.igo_scanner_cb = _build_checkbox(
        "Scanner Status",
        config.IN_GAME_OVERLAY["widgets"]["scanner"]["enabled"],
        parent_mixin._on_igo_settings_changed,
    )
    widgets_grid.addWidget(parent_mixin.igo_scanner_cb, 0, 0)

    parent_mixin.igo_recording_cb = _build_checkbox(
        "Recording Status",
        config.IN_GAME_OVERLAY["widgets"]["recording"]["enabled"],
        parent_mixin._on_igo_settings_changed,
    )
    widgets_grid.addWidget(parent_mixin.igo_recording_cb, 0, 1)

    parent_mixin.igo_kps_cb = _build_checkbox(
        "KPS",
        config.IN_GAME_OVERLAY["widgets"]["kps"]["enabled"],
        parent_mixin._on_igo_settings_changed,
    )
    widgets_grid.addWidget(parent_mixin.igo_kps_cb, 1, 0)

    parent_mixin.igo_powerups_cb = _build_checkbox(
        "Active Powerups (Buffs)",
        config.IN_GAME_OVERLAY["widgets"]["powerups"]["enabled"],
        parent_mixin._on_igo_settings_changed,
    )
    widgets_grid.addWidget(parent_mixin.igo_powerups_cb, 1, 1)

    parent_mixin.igo_luck_rarity_cb = _build_checkbox(
        "Luck Rarity %",
        config.IN_GAME_OVERLAY["widgets"]["luck_rarity"]["enabled"],
        parent_mixin._on_igo_settings_changed,
    )
    widgets_grid.addWidget(parent_mixin.igo_luck_rarity_cb, 2, 0)
    widgets_layout.addLayout(widgets_grid)

    grid_layout.addWidget(general_group, 0, 0, Qt.AlignTop)
    grid_layout.addWidget(widgets_group, 0, 1, Qt.AlignTop)

    layout_info_card = QFrame()
    layout_info_card.setStyleSheet("""
        QFrame {
            background: #111A2E;
            border: 1px solid #1D4ED8;
            border-left: 4px solid #3B82F6;
            border-radius: 8px;
            margin-top: 8px;
        }
        QLabel {
            background: transparent;
            border: none;
        }
    """)
    layout_info_layout = QVBoxLayout(layout_info_card)
    layout_info_layout.setContentsMargins(12, 12, 12, 12)
    hotkey_text = str(getattr(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9") or "f9").upper()
    layout_info_label = QLabel(
        "<span style='font-size:10.5pt; font-weight:bold; color:#ffd23f;'>"
        "💡 In-Game Overlay Layout Mode</span><br>"
        "<span style='font-size:9.5pt; color:#ffffff;'>"
        f"To see how the overlay is placed over the game, press the overlay hotkey <b>{hotkey_text}</b> "
        "(default: <b>F9</b>) or click <b>Edit Layout</b>. "
        "Layout mode shows the live overlay on top of the game window so you can drag widgets into place, "
        "preview their real positions, and then press <b>Save Layout</b>, <b>Esc</b>, or <b>F9</b> again to exit and save. "
        "Use <b>Widget Settings</b> to change widget scale."
        "</span>"
    )
    layout_info_label.setTextFormat(Qt.RichText)
    layout_info_label.setWordWrap(True)
    layout_info_layout.addWidget(layout_info_label)

    grid_layout.addWidget(layout_info_card, 1, 0, 1, 2)
    grid_layout.setRowStretch(2, 1)

    update_in_game_overlay_status_ui(parent_mixin)


def update_in_game_overlay_status_ui(parent_mixin: Any) -> None:
    if not hasattr(parent_mixin, "igo_status_label") or parent_mixin.igo_status_label is None:
        return

    is_running = bool(config.IN_GAME_OVERLAY.get("enabled", False))
    if is_running:
        parent_mixin.igo_status_label.setText(
            "<span style='color: #4fd67a; font-weight: bold;'>Running</span>"
        )
        parent_mixin.igo_toggle_btn.setText("Stop Overlay")
        parent_mixin.igo_toggle_btn.setObjectName("DangerButton")
        parent_mixin.igo_toggle_btn.setStyleSheet(
            _button_state_stylesheet("#B91C1C", "#DC2626")
        )
    else:
        parent_mixin.igo_status_label.setText(
            "<span style='color: #f08b72; font-weight: bold;'>Stopped</span>"
        )
        parent_mixin.igo_toggle_btn.setText("Start Overlay")
        parent_mixin.igo_toggle_btn.setObjectName("SuccessButton")
        parent_mixin.igo_toggle_btn.setStyleSheet("")

    parent_mixin.igo_toggle_btn.style().unpolish(parent_mixin.igo_toggle_btn)
    parent_mixin.igo_toggle_btn.style().polish(parent_mixin.igo_toggle_btn)


def _add_scale_group(layout, *, title: str, attr_name: str, widget_id: str, parent: Any) -> None:
    group = QGroupBox(title)
    group_layout = QVBoxLayout(group)
    group_layout.setContentsMargins(16, 12, 16, 12)
    _add_scale_row(group_layout, parent, attr_name, widget_id)
    layout.addWidget(group)


def _add_scale_row(layout, parent: Any, attr_name: str, widget_id: str) -> None:
    scale_layout = QHBoxLayout()
    scale_layout.addWidget(QLabel("Scale:"))
    spin = QDoubleSpinBox()
    spin.setRange(0.5, 3.0)
    spin.setSingleStep(0.1)
    spin.setValue(config.IN_GAME_OVERLAY["widgets"][widget_id].get("scale", 1.0))
    spin.valueChanged.connect(parent._save_settings)
    scale_layout.addWidget(spin)
    scale_layout.addStretch(1)
    layout.addLayout(scale_layout)
    setattr(parent, attr_name, spin)


def _build_checkbox(label: str, checked: bool, handler) -> QCheckBox:
    checkbox = QCheckBox(label)
    checkbox.setChecked(checked)
    checkbox.stateChanged.connect(handler)
    return checkbox
