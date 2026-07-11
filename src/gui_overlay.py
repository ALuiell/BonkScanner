from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QAbstractItemView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import config
import run_summary
from gui_shared import (
    TRACKED_ITEM_LIST_HEIGHT,
    CollapsibleSection,
    CollapsibleSectionGroup,
    FlowLayout,
    TrackedRuleTagWidget,
    _make_scroll_section,
    _set_text,
    _set_text_input,
)
from gui_styles import (
    ITEM_RARITY_COLOR_MAP,
    ITEM_RARITY_SORT_ORDER,
    PLAYER_STATS_REFRESH_MS,
    _button_state_stylesheet,
)
from item_metadata import (
    ITEM_RARITY_BY_NAME,
    available_item_display_names,
    item_display_color,
    normalize_item_name_for_rarity,
    preferred_item_display_name,
)
from live_run_tracker import LiveRunTracker, TrackedItemRule
from overlay_server import LocalOverlayServer, OverlayStateStore
from overlay_state import build_overlay_state
from player_stats import PLAYER_STAT_GROUPS


OVERLAY_WIDGET_LABELS = {
    "stage_summary": "Stage summary",
    "tracked_items": "Tracked items",
    "stats": "Stats",
    "kps": "KPS",
    "banishes": "Banishes",
}

OVERLAY_KPS_METRIC_LABELS = (
    ("current", "Current KPS"),
    ("minute_avg", "60s Avg"),
    ("five_minute_avg", "5m Avg"),
    ("run_avg", "Run Avg"),
)

class OverlayMixin:
    def initialize_overlay_runtime(self) -> None:
        self.overlay_state_store = OverlayStateStore()
        stale_seconds = max(25.0, (float(PLAYER_STATS_REFRESH_MS) / 1000.0) * 2.5)
        self.live_run_tracker = LiveRunTracker(
            tracked_item_rules=self._combined_tracked_item_rules(),
            stale_after_seconds=stale_seconds,
        )
        self.overlay_server = LocalOverlayServer(
            host=config.OVERLAY.get("host", "127.0.0.1"),
            port=int(config.OVERLAY.get("port", 17845)),
            state_store=self.overlay_state_store,
        )
        self.overlay_state_store.set_state(build_overlay_state(self.live_run_tracker, self._effective_overlay_config()))

    def _build_overlay_tab(self) -> None:
        self.tab_overlay = QWidget()
        tab_layout = QVBoxLayout(self.tab_overlay)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        overlay_scroll, _overlay_content, layout = _make_scroll_section()
        layout.setSpacing(10)
        tab_layout.addWidget(overlay_scroll)

        # Grid layout: cards are aligned initially, but AlignTop lets each grow independently
        grid_layout = QGridLayout()
        grid_layout.setSpacing(16)
        grid_layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(grid_layout)

        # Left column narrower, right column wider
        grid_layout.setColumnStretch(0, 1)
        grid_layout.setColumnStretch(1, 2)

        # ----------------------------------------------------
        # WIDGET DEFINITIONS
        # ----------------------------------------------------

        # 1. Server Control Card (Twitch Bot Style)
        server_group = QGroupBox("Overlay Server")
        server_layout = QVBoxLayout(server_group)
        server_layout.setContentsMargins(16, 12, 16, 12)
        server_layout.setSpacing(10)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.addWidget(QLabel("Server Status:"))
        self.overlay_status_label = QLabel()
        self.overlay_status_label.setTextFormat(Qt.RichText)
        status_row.addWidget(self.overlay_status_label)
        status_row.addStretch(1)
        server_layout.addLayout(status_row)

        settings_row = QHBoxLayout()
        settings_row.setContentsMargins(0, 0, 0, 0)
        self.overlay_auto_start_cb = QCheckBox("Auto-start server")
        self.overlay_auto_start_cb.setChecked(config.OVERLAY.get("auto_start", False))
        self.overlay_auto_start_cb.setToolTip("Start the overlay server automatically when the application starts.")
        self.overlay_auto_start_cb.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        settings_row.addWidget(self.overlay_auto_start_cb)
        settings_row.addStretch(1)
        port_label = QLabel("Port:")
        self.overlay_port_entry = QLineEdit(str(config.OVERLAY.get("port", 17845)))
        self.overlay_port_entry.setMaximumWidth(70)
        self.overlay_port_entry.editingFinished.connect(self.save_overlay_settings_from_ui)
        settings_row.addWidget(port_label)
        settings_row.addWidget(self.overlay_port_entry)
        server_layout.addLayout(settings_row)

        self.overlay_server_toggle_btn = QPushButton("Start Server")
        self.overlay_server_toggle_btn.setObjectName("SuccessButton")
        self.overlay_server_toggle_btn.setMinimumHeight(36)
        btn_font = self.overlay_server_toggle_btn.font()
        btn_font.setBold(True)
        self.overlay_server_toggle_btn.setFont(btn_font)
        self.overlay_server_toggle_btn.clicked.connect(self.toggle_overlay_server)
        server_layout.addWidget(self.overlay_server_toggle_btn)


        # 3. Styled Info Card (Visual Layout Editor guidance)
        editor_info_card = QFrame()
        editor_info_card.setStyleSheet("""
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
        editor_info_layout = QVBoxLayout(editor_info_card)
        editor_info_layout.setContentsMargins(12, 12, 12, 12)

        intro_label = QLabel(
            "<span style='font-size:10.5pt; font-weight:bold; color:#ffd23f;'>💡 Visual Layout Editor Mode is active!</span><br>"
            "<span style='font-size:9.5pt; color:#ffffff;'>"
            "Open your overlay URL in any browser with <b>?edit=true</b> to drag & drop widgets and change HUD resolution! "
            "Set Width & Height in OBS Browser Source properties to match your custom canvas resolution (default: 1920x1080)."
            "</span>"
        )
        intro_label.setTextFormat(Qt.RichText)
        intro_label.setWordWrap(True)
        editor_info_layout.addWidget(intro_label)

        # 4. Visible Widgets Card
        widgets_group = QGroupBox("Visible Widgets")
        widgets_layout = QVBoxLayout(widgets_group)
        widgets_layout.setContentsMargins(16, 12, 16, 12)
        widgets_layout.setSpacing(10)

        # Header Row (Label on the left, Button on the right)
        widgets_header_layout = QHBoxLayout()
        widgets_header_layout.setContentsMargins(4, 0, 0, 0)
        widgets_header_lbl = QLabel("Active Overlay Widgets:")
        widgets_header_lbl.setStyleSheet("font-weight: bold;")
        self.overlay_widget_settings_btn = QPushButton("Widget Settings")
        self.overlay_widget_settings_btn.clicked.connect(self.open_overlay_widget_settings_dialog)
        widgets_header_layout.addWidget(widgets_header_lbl)
        widgets_header_layout.addStretch(1)
        widgets_header_layout.addWidget(self.overlay_widget_settings_btn)
        widgets_layout.addLayout(widgets_header_layout)

        # Checkboxes Grid
        widgets_grid = QGridLayout()
        widgets_grid.setSpacing(10)
        self.overlay_widget_checkboxes = {}
        widget_config = self._overlay_widget_config_by_id()
        for index, (widget_id, label) in enumerate(OVERLAY_WIDGET_LABELS.items()):
            checkbox = QCheckBox(label)
            checkbox.setChecked(bool(widget_config.get(widget_id, {}).get("enabled", True)))
            checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
            self.overlay_widget_checkboxes[widget_id] = checkbox
            # 2x2 layout
            widgets_grid.addWidget(checkbox, index // 2, index % 2)
        widgets_layout.addLayout(widgets_grid)

        # 5. Browser Source URLs Card
        urls_group = QGroupBox("Browser Source URLs")
        urls_layout = QGridLayout(urls_group)
        urls_group.setContentsMargins(16, 12, 16, 12)
        urls_layout.setSpacing(10)

        # Full Overlay URL
        urls_layout.addWidget(QLabel("Full Overlay:"), 0, 0)
        self.overlay_url_entry = QLineEdit()
        self.overlay_url_entry.setReadOnly(True)
        self.overlay_url_entry.setText(self._overlay_url_text())
        urls_layout.addWidget(self.overlay_url_entry, 0, 1)

        copy_full_btn = QPushButton("Copy")
        copy_full_btn.setStyleSheet("QPushButton { padding: 5px 10px; min-width: 50px; }")
        copy_full_btn.clicked.connect(lambda: self._copy_to_clipboard(self.overlay_url_entry.text(), copy_full_btn))
        urls_layout.addWidget(copy_full_btn, 0, 2)

        # Widget selector
        urls_layout.addWidget(QLabel("Select Widget:"), 1, 0)
        self.overlay_widget_url_combo = QComboBox()
        for widget_id, label in OVERLAY_WIDGET_LABELS.items():
            self.overlay_widget_url_combo.addItem(label, widget_id)
        self.overlay_widget_url_combo.addItem("Layout Editor Mode", "editor")
        self.overlay_widget_url_combo.currentIndexChanged.connect(lambda _index: self.refresh_overlay_ui())
        urls_layout.addWidget(self.overlay_widget_url_combo, 1, 1, 1, 2)

        # Widget URL
        urls_layout.addWidget(QLabel("Widget URL:"), 2, 0)
        self.overlay_widget_url_entry = QLineEdit()
        self.overlay_widget_url_entry.setReadOnly(True)
        urls_layout.addWidget(self.overlay_widget_url_entry, 2, 1)

        copy_widget_btn = QPushButton("Copy")
        copy_widget_btn.setStyleSheet("QPushButton { padding: 5px 10px; min-width: 50px; }")
        copy_widget_btn.clicked.connect(lambda: self._copy_to_clipboard(self.overlay_widget_url_entry.text(), copy_widget_btn))
        urls_layout.addWidget(copy_widget_btn, 2, 2)

        # Place all cards in grid - AlignTop ensures no card stretches to fill its neighbour's height
        grid_layout.addWidget(server_group,      0, 0, Qt.AlignTop)
        grid_layout.addWidget(urls_group,        0, 1, Qt.AlignTop)
        grid_layout.addWidget(editor_info_card,  1, 0, Qt.AlignTop)
        grid_layout.addWidget(widgets_group,     1, 1, Qt.AlignTop)
        grid_layout.setRowStretch(2, 1)

        self.overlay_tracked_items_label = None

        layout.addStretch(1)
        self.tabview.addTab(self.tab_overlay, "OBS Overlay")
        self.refresh_overlay_item_selector()
        self.refresh_overlay_tracked_items_ui()
        self.refresh_overlay_ui()

    def _copy_to_clipboard(self, text: str, button: QPushButton) -> None:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import QTimer
        QGuiApplication.clipboard().setText(text)
        original_text = button.text()
        button.setText("Copied!")
        button.setEnabled(False)
        button.setStyleSheet("background-color: #2F9E6D; color: white; padding: 5px 10px; min-width: 50px;")
        def restore():
            button.setText(original_text)
            button.setEnabled(True)
            button.setStyleSheet("QPushButton { padding: 5px 10px; min-width: 50px; }")
        QTimer.singleShot(1500, restore)

    def open_overlay_widget_settings_dialog(self) -> None:
        dialog = QDialog(self.tab_overlay)
        dialog.setUpdatesEnabled(False)
        dialog.setWindowTitle("Widget Settings")
        dialog.resize(700, 760)
        dialog.setMinimumSize(640, 680)
        dialog_layout = QVBoxLayout(dialog)

        settings_tabs = QTabWidget()
        dialog_layout.addWidget(settings_tabs, 1)

        basic_tab = QWidget()
        basic_tab_layout = QVBoxLayout(basic_tab)
        basic_scroll, _basic_content, basic_layout = _make_scroll_section()
        basic_layout.setSpacing(10)
        basic_tab_layout.addWidget(basic_scroll)

        advanced_tab = QWidget()
        advanced_tab_layout = QVBoxLayout(advanced_tab)
        advanced_scroll, _advanced_content, advanced_layout = _make_scroll_section()
        advanced_layout.setSpacing(10)
        advanced_tab_layout.addWidget(advanced_scroll)

        stage_summary_group = QGroupBox("Stage Summary")
        stage_summary_layout = QVBoxLayout(stage_summary_group)
        stage_summary_layout.addWidget(QLabel("Configure the Stage Summary overlay widget."))
        stage_summary_widget_cfg = self._overlay_widget_config_by_id().get("stage_summary", {})
        self.overlay_stage_summary_bg_checkbox = QCheckBox("Show background")
        self.overlay_stage_summary_bg_checkbox.setChecked(float(stage_summary_widget_cfg.get("background_opacity", 0)) > 0)
        self.overlay_stage_summary_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        stage_summary_layout.addWidget(self.overlay_stage_summary_bg_checkbox)
        basic_layout.addWidget(stage_summary_group)

        banishes_group = QGroupBox("Banishes")
        banishes_layout = QVBoxLayout(banishes_group)
        banishes_layout.addWidget(QLabel("Configure the Banishes overlay widget."))
        banishes_widget_cfg = self._overlay_widget_config_by_id().get("banishes", {})
        self.overlay_banishes_bg_checkbox = QCheckBox("Show background")
        self.overlay_banishes_bg_checkbox.setChecked(float(banishes_widget_cfg.get("background_opacity", 0)) > 0)
        self.overlay_banishes_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        banishes_layout.addWidget(self.overlay_banishes_bg_checkbox)

        self.overlay_banishes_header_checkbox = QCheckBox("Show header")
        self.overlay_banishes_header_checkbox.setChecked(bool(banishes_widget_cfg.get("show_header", True)))
        self.overlay_banishes_header_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        banishes_layout.addWidget(self.overlay_banishes_header_checkbox)
        basic_layout.addWidget(banishes_group)

        kps_group = QGroupBox("KPS")
        kps_layout = QVBoxLayout(kps_group)
        kps_layout.addWidget(QLabel("Configure the compact KPS overlay widget."))
        kps_widget_cfg = self._overlay_widget_config_by_id().get("kps", {})
        self.overlay_kps_bg_checkbox = QCheckBox("Show background")
        self.overlay_kps_bg_checkbox.setChecked(float(kps_widget_cfg.get("background_opacity", 0)) > 0)
        self.overlay_kps_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        kps_layout.addWidget(self.overlay_kps_bg_checkbox)

        self.overlay_kps_header_checkbox = QCheckBox("Show header")
        self.overlay_kps_header_checkbox.setChecked(bool(kps_widget_cfg.get("show_header", False)))
        self.overlay_kps_header_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        kps_layout.addWidget(self.overlay_kps_header_checkbox)

        kps_layout.addSpacing(12)
        self.overlay_kps_metric_checkboxes = {}
        selected_kps_metrics = set(self._overlay_selected_kps_metric_ids())
        for metric_id, metric_label in self._overlay_all_kps_metric_labels():
            checkbox = QCheckBox(metric_label)
            checkbox.setChecked(metric_id in selected_kps_metrics)
            checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
            self.overlay_kps_metric_checkboxes[metric_id] = checkbox
            kps_layout.addWidget(checkbox)
        basic_layout.addWidget(kps_group)
        basic_layout.addStretch(1)

        stats_group = CollapsibleSection("Stats", expanded=True)
        stats_layout = stats_group.body_layout
        stats_layout.addWidget(QLabel("Selected stats appear in the Stats overlay widget."))
        stats_widget_cfg = self._overlay_widget_config_by_id().get("stats", {})
        self.overlay_stats_bg_checkbox = QCheckBox("Show background")
        self.overlay_stats_bg_checkbox.setChecked(float(stats_widget_cfg.get("background_opacity", 0)) > 0)
        self.overlay_stats_bg_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        stats_layout.addWidget(self.overlay_stats_bg_checkbox)

        self.overlay_stats_header_checkbox = QCheckBox("Show header")
        self.overlay_stats_header_checkbox.setChecked(bool(stats_widget_cfg.get("show_header", True)))
        self.overlay_stats_header_checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
        stats_layout.addWidget(self.overlay_stats_header_checkbox)

        stats_layout.addSpacing(12)
        stats_config_layout = QGridLayout()
        self.overlay_stats_checkboxes = {}
        selected_stats = set(self._overlay_selected_stat_labels())
        for index, label in enumerate(self._overlay_all_stat_labels()):
            checkbox = QCheckBox(label)
            checkbox.setChecked(label in selected_stats)
            checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
            self.overlay_stats_checkboxes[label] = checkbox
            stats_config_layout.addWidget(checkbox, index // 4, index % 4)
        stats_layout.addLayout(stats_config_layout)
        stats_layout.addSpacing(12)

        reset_btn_layout = QHBoxLayout()
        self.overlay_stats_reset_btn = QPushButton("Reset to Default Stats")
        self.overlay_stats_reset_btn.clicked.connect(self._reset_overlay_stats_to_default)
        reset_btn_layout.addWidget(self.overlay_stats_reset_btn)
        reset_btn_layout.addStretch(1)
        stats_layout.addLayout(reset_btn_layout)

        advanced_layout.addWidget(stats_group)

        items_group = CollapsibleSection(
            "Tracked Items",
            expanded=False,
        )
        items_layout = items_group.body_layout
        items_layout.addWidget(QLabel("Configure tracked item counters for the overlay."))

        self.overlay_use_session_tracked_items_cb = QCheckBox("Use Session Stats tracked items")
        self.overlay_use_session_tracked_items_cb.setChecked(self._uses_session_tracked_items(config.OVERLAY, default="custom"))
        self.overlay_use_session_tracked_items_cb.stateChanged.connect(self.on_overlay_tracked_items_source_toggled)
        items_layout.addWidget(self.overlay_use_session_tracked_items_cb)

        self.overlay_tracked_items_source_label = QLabel()
        self.overlay_tracked_items_source_label.setWordWrap(True)
        items_layout.addWidget(self.overlay_tracked_items_source_label)

        self.overlay_custom_tracked_items_widget = QWidget()
        overlay_custom_layout = QVBoxLayout(self.overlay_custom_tracked_items_widget)
        overlay_custom_layout.setContentsMargins(0, 0, 0, 0)
        overlay_custom_layout.setSpacing(8)

        top_layout = QVBoxLayout()
        top_layout.setSpacing(4)

        search_top_layout = QHBoxLayout()
        search_top_layout.addWidget(QLabel("Available Items (select one or more)"))
        search_top_layout.addStretch(1)
        top_layout.addLayout(search_top_layout)

        self.overlay_item_names = self._overlay_available_item_names()
        self.overlay_item_search_entry = QLineEdit()
        self.overlay_item_search_entry.setPlaceholderText("Search items...")
        self.overlay_item_search_entry.textChanged.connect(self.refresh_overlay_item_selector)
        top_layout.addWidget(self.overlay_item_search_entry)

        self.overlay_item_selector = QListWidget()
        self.overlay_item_selector.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.overlay_item_selector.setMinimumHeight(220)
        self.overlay_item_selector.setMaximumHeight(280)
        self.overlay_item_selector.setFlow(QListView.Flow.LeftToRight)
        self.overlay_item_selector.setWrapping(True)
        self.overlay_item_selector.setResizeMode(QListView.ResizeMode.Adjust)
        self.overlay_item_selector.setStyleSheet("QListWidget { font-size: 13px; }")
        top_layout.addWidget(self.overlay_item_selector)

        action_row = QHBoxLayout()
        self.overlay_map_one_only_checkbox = QCheckBox("Map 1 only")
        self.overlay_map_one_only_checkbox.setChecked(True)
        self.overlay_map_one_only_checkbox.setToolTip("If checked, only counts gains on the first map.")
        action_row.addWidget(self.overlay_map_one_only_checkbox)
        action_row.addStretch(1)

        self.overlay_add_tracked_item_btn = QPushButton("Add Rule")
        self.overlay_add_tracked_item_btn.clicked.connect(self.add_overlay_tracked_item)
        action_row.addWidget(self.overlay_add_tracked_item_btn)

        top_layout.addLayout(action_row)
        overlay_custom_layout.addLayout(top_layout)

        overlay_custom_layout.addSpacing(10)

        tags_top_layout = QHBoxLayout()
        tags_top_layout.addWidget(QLabel("Currently tracked"))
        tags_top_layout.addStretch(1)

        overlay_custom_layout.addLayout(tags_top_layout)

        self.overlay_tags_container = QWidget()
        self.overlay_tags_container.setStyleSheet("background-color: #0B1220;")
        self.overlay_tags_layout = FlowLayout(self.overlay_tags_container, margin=6, spacing=4)

        self.overlay_tags_scroll = QScrollArea()
        self.overlay_tags_scroll.setWidgetResizable(True)
        self.overlay_tags_scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #2B3648;
                border-radius: 6px;
                background-color: #0B1220;
            }
        """)
        self.overlay_tags_scroll.setWidget(self.overlay_tags_container)
        self.overlay_tags_scroll.setMinimumHeight(80)
        self.overlay_tags_scroll.setMaximumHeight(130)
        overlay_custom_layout.addWidget(self.overlay_tags_scroll)

        tags_bottom_layout = QHBoxLayout()
        self.overlay_clear_all_tags_btn = QPushButton("Clear All")
        self.overlay_clear_all_tags_btn.clicked.connect(self.clear_all_overlay_tracked_items)
        tags_bottom_layout.addWidget(self.overlay_clear_all_tags_btn)
        tags_bottom_layout.addStretch(1)

        overlay_custom_layout.addLayout(tags_bottom_layout)
        items_layout.addWidget(self.overlay_custom_tracked_items_widget)
        advanced_layout.addWidget(items_group)
        advanced_layout.addStretch(1)
        self.overlay_advanced_sections_group = CollapsibleSectionGroup((stats_group, items_group))

        settings_tabs.addTab(basic_tab, "Basic")
        settings_tabs.addTab(advanced_tab, "Advanced")

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Done")
        close_btn.clicked.connect(dialog.accept)
        close_row.addWidget(close_btn)
        dialog_layout.addLayout(close_row)

        self.refresh_overlay_item_selector()
        self.refresh_overlay_tracked_items_ui()
        dialog.setUpdatesEnabled(True)
        try:
            dialog.exec()
        finally:
            self._clear_overlay_widget_settings_dialog_refs()
            self.refresh_overlay_tracked_items_ui()

    def _reset_overlay_stats_to_default(self) -> None:
        if not getattr(self, "overlay_stats_checkboxes", None):
            return
        default_stats = set(self._overlay_default_stat_labels())
        for label, checkbox in self.overlay_stats_checkboxes.items():
            checkbox.blockSignals(True)
            checkbox.setChecked(label in default_stats)
            checkbox.blockSignals(False)
        self.save_overlay_settings_from_ui()

    def _clear_overlay_widget_settings_dialog_refs(self) -> None:
        self.overlay_stats_checkboxes = None
        self.overlay_stats_bg_checkbox = None
        self.overlay_stats_header_checkbox = None
        self.overlay_stats_reset_btn = None
        self.overlay_stage_summary_bg_checkbox = None
        self.overlay_kps_bg_checkbox = None
        self.overlay_kps_header_checkbox = None
        self.overlay_kps_metric_checkboxes = None
        self.overlay_banishes_bg_checkbox = None
        self.overlay_banishes_header_checkbox = None
        self.overlay_item_search_entry = None
        self.overlay_item_selector = None
        self.overlay_map_one_only_checkbox = None
        self.overlay_add_tracked_item_btn = None
        self.overlay_clear_all_tags_btn = None
        self.overlay_tags_container = None
        self.overlay_tags_layout = None
        self.overlay_tags_scroll = None
        self.overlay_use_session_tracked_items_cb = None
        self.overlay_tracked_items_source_label = None
        self.overlay_custom_tracked_items_widget = None

    def toggle_overlay_server(self) -> None:
        server = getattr(self, "overlay_server", None)
        should_start = not bool(server is not None and server.is_running)
        config.OVERLAY["enabled"] = should_start
        config.user_config["OVERLAY"] = config.OVERLAY
        config.save_config(config.user_config)
        if should_start:
            self.start_overlay_server()
        else:
            self.stop_overlay_server()
        self.refresh_overlay_ui()

    def start_overlay_server(self) -> bool:
        self.save_overlay_settings_from_ui(persist=False)
        if self.overlay_server.is_running:
            return True
        self.overlay_server = LocalOverlayServer(
            host="127.0.0.1",
            port=int(config.OVERLAY.get("port", 17845)),
            state_store=self.overlay_state_store,
        )
        try:
            self.overlay_server.start()
        except OSError:
            self.refresh_overlay_ui()
            return False
        self.refresh_overlay_ui()
        return True

    def stop_overlay_server(self) -> None:
        self.overlay_server.stop()
        self.refresh_overlay_ui()

    def save_overlay_settings_from_ui(self, *, persist: bool = True) -> None:
        with config.config_lock:
            overlay = config.normalize_overlay_config(config.OVERLAY)
            port_text = self.overlay_port_entry.text().strip() if self.overlay_port_entry is not None else ""
            try:
                port = int(port_text)
            except ValueError:
                port = int(overlay.get("port", 17845))
            overlay["port"] = port
            if getattr(self, "overlay_auto_start_cb", None) is not None:
                overlay["auto_start"] = bool(self.overlay_auto_start_cb.isChecked())
            overlay = config.normalize_overlay_config(overlay)
            if self.overlay_port_entry is not None:
                _set_text_input(self.overlay_port_entry, str(overlay["port"]))

            widget_config = self._overlay_widget_config_by_id()
            widgets = []
            for widget in overlay.get("widgets", []):
                if not isinstance(widget, dict):
                    continue
                widget_id = str(widget.get("id") or "")
                if widget_id in self.overlay_widget_checkboxes:
                    widget = dict(widget)
                    widget["enabled"] = bool(self.overlay_widget_checkboxes[widget_id].isChecked())
                if widget_id == "stats" and getattr(self, "overlay_stats_checkboxes", None):
                    widget = dict(widget)
                    selected_stats = [
                        label
                        for label, checkbox in self.overlay_stats_checkboxes.items()
                        if checkbox.isChecked()
                    ]
                    widget["selected_stats"] = selected_stats or list(self._overlay_default_stat_labels())
                    if getattr(self, "overlay_stats_bg_checkbox", None) is not None:
                        widget["background_opacity"] = 0.4 if self.overlay_stats_bg_checkbox.isChecked() else 0.0
                    if getattr(self, "overlay_stats_header_checkbox", None) is not None:
                        widget["show_header"] = bool(self.overlay_stats_header_checkbox.isChecked())
                if widget_id == "stage_summary" and getattr(self, "overlay_stage_summary_bg_checkbox", None) is not None:
                    widget = dict(widget)
                    widget["background_opacity"] = 0.4 if self.overlay_stage_summary_bg_checkbox.isChecked() else 0.0
                if widget_id == "kps":
                    widget = dict(widget)
                    if getattr(self, "overlay_kps_metric_checkboxes", None):
                        selected_kps_metrics = [
                            metric_id
                            for metric_id, checkbox in self.overlay_kps_metric_checkboxes.items()
                            if checkbox.isChecked()
                        ]
                        widget["selected_kps_metrics"] = selected_kps_metrics or ["current"]
                    if getattr(self, "overlay_kps_bg_checkbox", None) is not None:
                        widget["background_opacity"] = 0.4 if self.overlay_kps_bg_checkbox.isChecked() else 0.0
                    if getattr(self, "overlay_kps_header_checkbox", None) is not None:
                        widget["show_header"] = bool(self.overlay_kps_header_checkbox.isChecked())
                if widget_id == "banishes":
                    widget = dict(widget)
                    if getattr(self, "overlay_banishes_bg_checkbox", None) is not None:
                        widget["background_opacity"] = 0.4 if self.overlay_banishes_bg_checkbox.isChecked() else 0.0
                    if getattr(self, "overlay_banishes_header_checkbox", None) is not None:
                        widget["show_header"] = bool(self.overlay_banishes_header_checkbox.isChecked())
                widgets.append(widget)
            overlay["widgets"] = widgets
            if getattr(self, "overlay_tags_layout", None) is not None:
                overlay["tracked_items"] = config.OVERLAY.get("tracked_items", [])
            if getattr(self, "overlay_use_session_tracked_items_cb", None) is not None:
                overlay["tracked_items_source"] = (
                    "session" if self.overlay_use_session_tracked_items_cb.isChecked() else "custom"
                )
            config.OVERLAY = overlay
            config.user_config["OVERLAY"] = config.OVERLAY
            self.live_run_tracker.set_tracked_item_rules(self._combined_tracked_item_rules())
            self.update_overlay_state_from_tracker()
            if persist:
                config.save_config(config.user_config)
            if self.overlay_server.is_running and self.overlay_server.port != int(config.OVERLAY["port"]):
                self.overlay_server.stop()
                if bool(config.OVERLAY.get("enabled", False)):
                    self.start_overlay_server()
            self.refresh_overlay_ui()

    def refresh_overlay_ui(self) -> None:
        server = getattr(self, "overlay_server", None)
        running = bool(server is not None and server.is_running)
        if self.overlay_url_entry is not None:
            _set_text_input(self.overlay_url_entry, self._overlay_url_text())
        if getattr(self, "overlay_widget_url_entry", None) is not None:
            _set_text_input(self.overlay_widget_url_entry, self._overlay_selected_widget_url_text())
        if self.overlay_status_label is not None:
            if running:
                status = '<span style="color:#4fd67a; font-weight: bold;">Live</span>'
            elif server is not None and server.last_error:
                status = f'<span style="color:#f08b72; font-weight: bold;">Port Error</span> ({server.last_error})'
            else:
                status = '<span style="color:#f08b72; font-weight: bold;">Stopped</span>'
            _set_text(self.overlay_status_label, status)
        if getattr(self, "overlay_server_toggle_btn", None) is not None:
            self.overlay_server_toggle_btn.setText("Stop Server" if running else "Start Server")
            if running:
                self.overlay_server_toggle_btn.setStyleSheet(_button_state_stylesheet("#B91C1C", "#DC2626"))
            else:
                self.overlay_server_toggle_btn.setStyleSheet("")

    def refresh_overlay_item_selector(self) -> None:
        selector = getattr(self, "overlay_item_selector", None)
        if selector is None:
            return
        query = ""
        if getattr(self, "overlay_item_search_entry", None) is not None:
            query = self.overlay_item_search_entry.text().strip().lower()
        if selector.count() == 0:
            for item_name in getattr(self, "overlay_item_names", ()):
                display_name = self._tracked_item_display_name(item_name)
                item = QListWidgetItem(display_name)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item.setData(Qt.UserRole, item_name)
                item.setForeground(QBrush(QColor(self._tracked_item_color(item_name))))
                selector.addItem(item)

        for i in range(selector.count()):
            item = selector.item(i)
            item_name = str(item.data(Qt.UserRole) or item.text())
            display_name = self._tracked_item_display_name(item_name)
            haystacks = {item_name.lower(), display_name.lower()}
            if query and not any(query in haystack for haystack in haystacks):
                item.setHidden(True)
            else:
                item.setHidden(False)

    def refresh_overlay_tracked_items_ui(self) -> None:
        layout = getattr(self, "overlay_tags_layout", None)
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

        tracked_count = 0
        for rule in config.OVERLAY.get("tracked_items") or ():
            if not isinstance(rule, dict):
                continue
            item_names = [str(name) for name in rule.get("item_names") or () if str(name).strip()]
            if not item_names:
                continue
            mode = str(rule.get("mode") or "all_run")
            label = self._tracked_rule_display_label(dict(rule), item_names, mode)
            rule_id = str(rule.get("id") or "")

            if layout is not None:
                accent = self._tracked_rule_color(item_names)
                tag = TrackedRuleTagWidget(
                    rule_id,
                    self._tracked_rule_tag_label(label, mode),
                    text_color=accent,
                    border_color=accent,
                    background_color="#18212C",
                )
                tag.remove_clicked.connect(self.remove_overlay_tracked_item)
                layout.addWidget(tag)
            tracked_count += 1

        if self.overlay_tracked_items_label is not None:
            if self._uses_session_tracked_items(config.OVERLAY, default="custom"):
                tracked_count = len(self._session_tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS))
                detail = "Using Session Stats tracked items. Map 1 only counts gains observed during stage 1."
            else:
                detail = "Map 1 only counts gains observed during stage 1."
            _set_text(self.overlay_tracked_items_label, f"Tracking {tracked_count} rule(s). {detail}")
        self._refresh_overlay_tracked_items_source_ui()

    def _refresh_overlay_tracked_items_source_ui(self) -> None:
        use_session = self._uses_session_tracked_items(config.OVERLAY, default="custom")
        custom_count = len(self._tracked_item_rules_from_config(config.OVERLAY))
        session_rules = self._session_tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS)
        session_count = len(session_rules)
        source_label = getattr(self, "overlay_tracked_items_source_label", None)
        if source_label is not None:
            if use_session:
                preview = ", ".join(
                    self._session_tracked_item_command_label({"label": rule.label, "mode": rule.mode})
                    for rule in session_rules[:4]
                )
                if session_count > 4:
                    preview += ", ..."
                detail = preview or "No Session Stats tracked items configured"
                _set_text(
                    source_label,
                    f"Overlay source: Session Stats ({session_count}). Custom list is preserved ({custom_count}). {detail}",
                )
            else:
                _set_text(source_label, f"Overlay source: Custom ({custom_count}). Session Stats has {session_count} rule(s).")
        custom_widget = getattr(self, "overlay_custom_tracked_items_widget", None)
        if custom_widget is not None:
            custom_widget.setVisible(not use_session)
        for widget in (
            getattr(self, "overlay_map_one_only_checkbox", None),
            getattr(self, "overlay_item_search_entry", None),
            getattr(self, "overlay_item_selector", None),
            getattr(self, "overlay_add_tracked_item_btn", None),
            getattr(self, "overlay_clear_all_tags_btn", None),
        ):
            if widget is not None:
                widget.setEnabled(not use_session)

    def on_overlay_tracked_items_source_toggled(self, *_args) -> None:
        self.save_overlay_settings_from_ui()
        self.refresh_overlay_tracked_items_ui()

    def add_overlay_tracked_item(self) -> None:
        item_names = self._selected_overlay_item_names()
        if not item_names:
            return
        map_one_only = bool(self.overlay_map_one_only_checkbox.isChecked())
        mode = "map_1_only" if map_one_only else "all_run"
        display_name = self._tracked_item_combo_display_name(item_names)
        label = f"{display_name} Map 1" if map_one_only else display_name
        rule = {
            "id": self._overlay_rule_id(item_names, mode),
            "label": label,
            "item_names": item_names,
            "mode": mode,
        }
        existing_rules = [
            dict(raw_rule)
            for raw_rule in config.OVERLAY.get("tracked_items") or ()
            if isinstance(raw_rule, dict)
        ]
        existing_ids = {str(raw_rule.get("id") or "") for raw_rule in existing_rules}
        if rule["id"] not in existing_ids:
            existing_rules.append(rule)
        config.OVERLAY["tracked_items"] = existing_rules
        config.user_config["OVERLAY"] = config.OVERLAY

        if getattr(self, "overlay_item_selector", None) is not None:
            self.overlay_item_selector.clearSelection()
            self.overlay_item_selector.setCurrentItem(None)

        self.refresh_overlay_tracked_items_ui()
        self.save_overlay_settings_from_ui()

    def remove_overlay_tracked_item(self, rule_id: str) -> None:
        rule_id = str(rule_id)
        existing_rules = [
            dict(raw_rule)
            for raw_rule in config.OVERLAY.get("tracked_items") or ()
            if isinstance(raw_rule, dict)
        ]
        new_rules = [r for r in existing_rules if str(r.get("id") or "") != rule_id]
        config.OVERLAY["tracked_items"] = new_rules
        config.user_config["OVERLAY"] = config.OVERLAY
        self.refresh_overlay_tracked_items_ui()
        self.save_overlay_settings_from_ui()

    def clear_all_overlay_tracked_items(self) -> None:
        config.OVERLAY["tracked_items"] = []
        config.user_config["OVERLAY"] = config.OVERLAY
        self.refresh_overlay_tracked_items_ui()
        self.save_overlay_settings_from_ui()

    def open_session_tracked_item_settings_dialog(self) -> None:
        dialog = QDialog(self.tab_stats)
        dialog.setUpdatesEnabled(False)
        dialog.setWindowTitle("Session Tracked Items")
        dialog.resize(700, 570)
        dialog.setMinimumSize(620, 520)
        dialog_layout = QVBoxLayout(dialog)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(10)
        content_layout.addWidget(QLabel("Track item gains in Session Stats. Map 1 only counts gains observed during stage 1."))
        top_layout = QVBoxLayout()
        top_layout.setSpacing(8)

        search_top_layout = QHBoxLayout()
        search_top_layout.addWidget(QLabel("Available Items (select one or more)"))
        search_top_layout.addStretch(1)
        top_layout.addLayout(search_top_layout)

        self.session_item_names = self._overlay_available_item_names()
        self.session_item_search_entry = QLineEdit()
        self.session_item_search_entry.setPlaceholderText("Search items...")
        self.session_item_search_entry.textChanged.connect(self.refresh_session_item_selector)
        top_layout.addWidget(self.session_item_search_entry)

        self.session_item_selector = QListWidget()
        self.session_item_selector.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.session_item_selector.setFixedHeight(220)
        self.session_item_selector.setFlow(QListView.Flow.LeftToRight)
        self.session_item_selector.setWrapping(True)
        self.session_item_selector.setResizeMode(QListView.ResizeMode.Adjust)
        self.session_item_selector.setStyleSheet("QListWidget { font-size: 13px; }")
        top_layout.addWidget(self.session_item_selector)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 6, 0, 0)
        self.session_map_one_only_checkbox = QCheckBox("Map 1 only")
        self.session_map_one_only_checkbox.setChecked(True)
        self.session_map_one_only_checkbox.setToolTip("If checked, only counts gains on the first map.")
        action_row.addWidget(self.session_map_one_only_checkbox)
        action_row.addStretch(1)

        self.session_add_tracked_item_btn = QPushButton("Add Rule")
        self.session_add_tracked_item_btn.clicked.connect(self.add_session_tracked_item)
        action_row.addWidget(self.session_add_tracked_item_btn)

        top_layout.addLayout(action_row)
        content_layout.addLayout(top_layout)

        content_layout.addSpacing(10)

        tags_top_layout = QHBoxLayout()
        tags_top_layout.addWidget(QLabel("Currently tracked"))
        tags_top_layout.addStretch(1)

        content_layout.addLayout(tags_top_layout)

        self.session_tags_container = QWidget()
        self.session_tags_container.setStyleSheet("background-color: #0B1220;")
        self.session_tags_layout = FlowLayout(self.session_tags_container, margin=6, spacing=4)

        tags_scroll = QScrollArea()
        tags_scroll.setWidgetResizable(True)
        tags_scroll.setStyleSheet("""
            QScrollArea {
                border: 1px solid #2B3648;
                border-radius: 6px;
                background-color: #0B1220;
            }
        """)
        tags_scroll.setWidget(self.session_tags_container)
        tags_scroll.setMinimumHeight(80)
        tags_scroll.setMaximumHeight(130)  # Stop the window from growing indefinitely
        content_layout.addWidget(tags_scroll)
        dialog_layout.addWidget(content)

        close_row = QHBoxLayout()
        self.session_clear_all_tags_btn = QPushButton("Clear All")
        self.session_clear_all_tags_btn.clicked.connect(self.clear_all_session_tracked_items)
        close_row.addWidget(self.session_clear_all_tags_btn)

        close_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        close_row.addWidget(close_btn)
        dialog_layout.addLayout(close_row)

        self.refresh_session_item_selector()
        self.refresh_session_tracked_items_ui()
        dialog.setUpdatesEnabled(True)
        try:
            dialog.exec()
        finally:
            self._clear_session_tracked_item_dialog_refs()
            self.refresh_session_tracked_item_stats_ui()

    def refresh_session_item_selector(self) -> None:
        selector = getattr(self, "session_item_selector", None)
        if selector is None:
            return
        query = ""
        if getattr(self, "session_item_search_entry", None) is not None:
            query = self.session_item_search_entry.text().strip().lower()
        if selector.count() == 0:
            for item_name in getattr(self, "session_item_names", ()):
                display_name = self._tracked_item_display_name(item_name)
                item = QListWidgetItem(display_name)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item.setData(Qt.UserRole, item_name)
                item.setForeground(QBrush(QColor(self._tracked_item_color(item_name))))
                selector.addItem(item)

        for i in range(selector.count()):
            item = selector.item(i)
            item_name = str(item.data(Qt.UserRole) or item.text())
            display_name = self._tracked_item_display_name(item_name)
            haystacks = {item_name.lower(), display_name.lower()}
            if query and not any(query in haystack for haystack in haystacks):
                item.setHidden(True)
            else:
                item.setHidden(False)

    def refresh_session_tracked_items_ui(self) -> None:
        layout = getattr(self, "session_tags_layout", None)
        if layout is None:
            return

        # Clear existing tags
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for rule in config.SESSION_TRACKED_ITEMS.get("tracked_items") or ():
            if not isinstance(rule, dict):
                continue
            item_names = [str(name) for name in rule.get("item_names") or () if str(name).strip()]
            if not item_names:
                continue
            mode = str(rule.get("mode") or "all_run")
            label = self._tracked_rule_display_label(dict(rule), item_names, mode)
            rule_id = str(rule.get("id", ""))

            accent = self._tracked_rule_color(item_names)
            tag = TrackedRuleTagWidget(
                rule_id=rule_id,
                label_text=self._tracked_rule_tag_label(label, mode),
                text_color=accent,
                border_color=accent,
                background_color="#18212C",
            )
            tag.remove_clicked.connect(self.remove_session_tracked_item)
            layout.addWidget(tag)

    def refresh_session_tracked_item_stats_ui(self) -> None:
        label = getattr(self, "stats_tracked_items_label", None)
        if label is None or self.live_run_tracker is None:
            return
        text = self.format_session_tracked_items_for_stats_tab()
        if not text:
            _set_text(label, "No tracked items configured")
            return
        _set_text(label, text)

    def session_found_seed_count(self) -> int:
        count = 0
        for data in getattr(self, "template_stats", {}).values():
            if not isinstance(data, dict):
                continue
            history = data.get("history")
            if isinstance(history, (list, tuple)):
                count += len(history)
        return count

    def session_tracked_item_stat_rows(self) -> list[dict[str, Any]]:
        return self._tracked_item_stat_rows_for_rules(
            self._session_tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS)
        )

    def twitch_tracked_item_stat_rows(self) -> list[dict[str, Any]]:
        return self._tracked_item_stat_rows_for_rules(self._effective_twitch_tracked_item_rules())

    def _tracked_item_stat_rows_for_rules(self, rules: tuple[TrackedItemRule, ...]) -> list[dict[str, Any]]:
        if self.live_run_tracker is None:
            return []
        rows = self.live_run_tracker.tracked_item_rows_for_rules(rules)
        seed_count = self.session_found_seed_count()
        formatted_rows: list[dict[str, Any]] = []
        for row in rows:
            count = int(row.get("count") or 0)
            percent = (count / seed_count * 100.0) if seed_count > 0 else None
            formatted_rows.append(
                {
                    "label": self._session_tracked_item_command_label(row),
                    "count": count,
                    "percent": percent,
                }
            )
        return formatted_rows

    def format_session_tracked_items_for_stats_tab(self) -> str:
        rows = self.session_tracked_item_stat_rows()
        if not rows:
            return ""
        parts = []
        for row in rows:
            percent = row.get("percent")
            if percent is None:
                parts.append(f"{row['label']}: {row['count']}")
            else:
                parts.append(f"{row['label']}: {row['count']} ({percent:.2f}%)")
        return " | ".join(parts)

    def format_twitch_session_summary(self) -> str:
        snapshot = self.get_twitch_session_snapshot()
        rerolls = max(0, int(snapshot.get("rerolls", 0) or 0))
        seeds_found = max(0, int(snapshot.get("seeds_found", 0) or 0))
        seed_rate = f"{(seeds_found / rerolls * 100.0) if rerolls > 0 else 0.0:.2f}"

        tracked_parts = []
        for row in snapshot.get("tracked_rows", ()):
            percent = row.get("percent")
            if percent is None:
                tracked_parts.append(f"{row['label']} {row['count']}")
            else:
                tracked_parts.append(f"{row['label']} {row['count']} ({percent:.2f}%)")

        items_str = ", ".join(tracked_parts) if tracked_parts else "None"

        import config
        tpl = config.TWITCH_BOT.get("templates", {}).get(
            "session", "{resets} resets, {seeds} seeds found ({seed_rate}%) | Tracked Items: {items}"
        )
        try:
            return tpl.format(resets=rerolls, seeds=seeds_found, seed_rate=seed_rate, items=items_str)
        except Exception:
            return f"{rerolls} resets, {seeds_found} seeds found ({seed_rate}%) | Tracked Items: {items_str}"

    def _refresh_twitch_session_snapshot(self) -> None:
        rows = tuple(dict(row) for row in self.twitch_tracked_item_stat_rows())
        snapshot = {
            "rerolls": max(0, int(getattr(self, "session_rerolls", 0) or 0)),
            "seeds_found": max(0, int(self.session_found_seed_count())),
            "tracked_rows": rows,
        }
        lock = getattr(self, "_twitch_session_snapshot_lock", None)
        if lock is None:
            self._twitch_session_snapshot = snapshot
            return
        with lock:
            self._twitch_session_snapshot = snapshot

    def get_twitch_session_snapshot(self) -> dict[str, Any]:
        lock = getattr(self, "_twitch_session_snapshot_lock", None)
        if lock is None:
            return dict(getattr(self, "_twitch_session_snapshot", {}))
        with lock:
            snapshot = dict(self._twitch_session_snapshot)
            snapshot["tracked_rows"] = tuple(dict(row) for row in snapshot.get("tracked_rows", ()))
            return snapshot

    @staticmethod
    def _session_tracked_item_command_label(row: dict[str, Any]) -> str:
        label = str(row.get("label") or "").strip() or "Item"
        mode = str(row.get("mode") or "")
        if mode != "map_1_only":
            return label

        lowered = label.casefold()
        for suffix in (" map 1", " map1", " t1"):
            if lowered.endswith(suffix):
                label = label[: -len(suffix)].rstrip()
                break
        if label.casefold().endswith(" t1"):
            return label
        return f"{label} T1"

    def add_session_tracked_item(self) -> None:
        item_names = self._selected_session_item_names()
        if not item_names:
            return
        map_one_only = bool(self.session_map_one_only_checkbox.isChecked())
        mode = "map_1_only" if map_one_only else "all_run"
        display_name = self._tracked_item_combo_display_name(item_names)
        label = f"{display_name} Map 1" if map_one_only else display_name
        rule = {
            "id": self._session_rule_id(item_names, mode),
            "label": label,
            "item_names": item_names,
            "mode": mode,
        }
        existing_rules = [
            dict(raw_rule)
            for raw_rule in config.SESSION_TRACKED_ITEMS.get("tracked_items") or ()
            if isinstance(raw_rule, dict)
        ]
        existing_ids = {str(raw_rule.get("id") or "") for raw_rule in existing_rules}
        if rule["id"] not in existing_ids:
            existing_rules.append(rule)
        config.SESSION_TRACKED_ITEMS["tracked_items"] = existing_rules
        self.save_session_tracked_items_from_ui()
        self.refresh_session_tracked_items_ui()
        if getattr(self, "session_item_selector", None) is not None:
            self.session_item_selector.clearSelection()

    def clear_all_session_tracked_items(self) -> None:
        config.SESSION_TRACKED_ITEMS["tracked_items"] = []
        self.save_session_tracked_items_from_ui()
        self.refresh_session_tracked_items_ui()

    def remove_session_tracked_item(self, rule_id: str = "") -> None:
        if not rule_id:
            return
        rules = config.SESSION_TRACKED_ITEMS.get("tracked_items") or []
        config.SESSION_TRACKED_ITEMS["tracked_items"] = [
            r for r in rules if isinstance(r, dict) and r.get("id") != rule_id
        ]
        self.save_session_tracked_items_from_ui()
        self.refresh_session_tracked_items_ui()

    def save_session_tracked_items_from_ui(self) -> None:
        config.SESSION_TRACKED_ITEMS = config.normalize_session_tracked_items_config(config.SESSION_TRACKED_ITEMS)
        config.user_config["SESSION_TRACKED_ITEMS"] = config.SESSION_TRACKED_ITEMS
        config.save_config(config.user_config)
        if self.live_run_tracker is not None:
            self.live_run_tracker.set_tracked_item_rules(self._combined_tracked_item_rules())
        self.refresh_session_tracked_items_ui()
        self.refresh_session_tracked_item_stats_ui()

    def _selected_session_item_names(self) -> list[str]:
        selector = getattr(self, "session_item_selector", None)
        if selector is not None:
            selected_items = selector.selectedItems()
            if not selected_items and selector.currentItem() is not None:
                selected_items = [selector.currentItem()]
            item_names = [
                str(item.data(Qt.UserRole) or item.text()).strip()
                for item in selected_items
                if str(item.data(Qt.UserRole) or item.text()).strip()
            ]
            if item_names:
                return self._dedupe_item_names(item_names)
        if getattr(self, "session_item_search_entry", None) is not None:
            query = self.session_item_search_entry.text().strip()
            for item_name in getattr(self, "session_item_names", ()):
                display_name = self._tracked_item_display_name(item_name)
                if item_name.lower() == query.lower() or display_name.lower() == query.lower():
                    return [item_name]
        return []

    def _session_tracked_item_config_from_ui(self) -> list[dict[str, Any]]:
        return [
            dict(raw_rule)
            for raw_rule in config.SESSION_TRACKED_ITEMS.get("tracked_items") or ()
            if isinstance(raw_rule, dict)
        ]

    def _clear_session_tracked_item_dialog_refs(self) -> None:
        self.session_item_search_entry = None
        self.session_item_selector = None
        self.session_map_one_only_checkbox = None
        self.session_add_tracked_item_btn = None
        self.session_tags_container = None
        self.session_tags_layout = None

    def _selected_overlay_item_names(self) -> list[str]:
        selector = getattr(self, "overlay_item_selector", None)
        if selector is not None:
            selected_items = selector.selectedItems()
            if not selected_items and selector.currentItem() is not None:
                selected_items = [selector.currentItem()]
            item_names = [
                str(item.data(Qt.UserRole) or item.text()).strip()
                for item in selected_items
                if str(item.data(Qt.UserRole) or item.text()).strip()
            ]
            if item_names:
                return self._dedupe_item_names(item_names)
        if getattr(self, "overlay_item_search_entry", None) is not None:
            query = self.overlay_item_search_entry.text().strip()
            for item_name in getattr(self, "overlay_item_names", ()):
                display_name = self._tracked_item_display_name(item_name)
                if item_name.lower() == query.lower() or display_name.lower() == query.lower():
                    return [item_name]
        return []

    def _tracked_item_config_from_ui(self) -> list[dict[str, Any]]:
        return [
            dict(raw_rule)
            for raw_rule in config.OVERLAY.get("tracked_items") or ()
            if isinstance(raw_rule, dict)
        ]

    def update_overlay_state_from_tracker(self) -> None:
        if self.overlay_state_store is None:
            return
        self.overlay_state_store.set_state(build_overlay_state(self.live_run_tracker, self._effective_overlay_config()))
        tab_active = getattr(self, "_is_overlay_tab_active", lambda: True)
        if getattr(self, "tab_overlay", None) is not None and tab_active():
            self.refresh_overlay_ui()

    def mark_overlay_read_failed(self, *, no_game: bool = False) -> None:
        self.live_run_tracker.mark_read_failed(no_game=no_game)
        self.update_overlay_state_from_tracker()

    def overlay_should_refresh_live_stats(self) -> bool:
        return bool(
            getattr(config, "OVERLAY", {}).get("enabled", False)
            or (getattr(self, "overlay_server", None) is not None and self.overlay_server.is_running)
        )

    def apply_overlay_autostart(self) -> None:
        if bool(config.OVERLAY.get("auto_start", False)):
            self.start_overlay_server()
        self.update_overlay_state_from_tracker()

    def close_overlay_server(self) -> None:
        server = getattr(self, "overlay_server", None)
        if server is not None:
            server.stop()

    def _overlay_widget_config_by_id(self) -> dict[str, dict[str, Any]]:
        widgets: dict[str, dict[str, Any]] = {}
        for widget in config.OVERLAY.get("widgets", []):
            if isinstance(widget, dict) and widget.get("id"):
                widgets[str(widget["id"])] = dict(widget)
        return widgets

    def _overlay_url_text(self) -> str:
        return f"http://127.0.0.1:{int(config.OVERLAY.get('port', 17845))}/overlay"

    def _overlay_selected_widget_url_text(self) -> str:
        widget_id = "stats"
        if getattr(self, "overlay_widget_url_combo", None) is not None:
            widget_id = str(self.overlay_widget_url_combo.currentData() or widget_id)
        if widget_id == "editor":
            return f"{self._overlay_url_text()}?edit=true"
        return f"{self._overlay_url_text()}/{widget_id}"

    @staticmethod
    def _overlay_default_stat_labels() -> tuple[str, ...]:
        return ("Damage", "Attack Speed", "Luck", "XP Gain")

    @classmethod
    def _overlay_all_stat_labels(cls) -> tuple[str, ...]:
        return tuple(spec.label for group in PLAYER_STAT_GROUPS for spec in group)

    @classmethod
    def _overlay_selected_stat_labels(cls) -> tuple[str, ...]:
        widget_config = {}
        for widget in config.OVERLAY.get("widgets", []):
            if isinstance(widget, dict) and widget.get("id") == "stats":
                widget_config = widget
                break
        allowed = set(cls._overlay_all_stat_labels())
        selected = tuple(
            str(label)
            for label in widget_config.get("selected_stats", ())
            if str(label) in allowed
        )
        return selected or cls._overlay_default_stat_labels()

    @staticmethod
    def _overlay_default_kps_metric_ids() -> tuple[str, ...]:
        return tuple(metric_id for metric_id, _label in OVERLAY_KPS_METRIC_LABELS)

    @staticmethod
    def _overlay_all_kps_metric_labels() -> tuple[tuple[str, str], ...]:
        return OVERLAY_KPS_METRIC_LABELS

    @classmethod
    def _overlay_selected_kps_metric_ids(cls) -> tuple[str, ...]:
        widget_config = {}
        for widget in config.OVERLAY.get("widgets", []):
            if isinstance(widget, dict) and widget.get("id") == "kps":
                widget_config = widget
                break
        allowed = {metric_id for metric_id, _label in cls._overlay_all_kps_metric_labels()}
        selected = tuple(
            str(metric_id)
            for metric_id in widget_config.get("selected_kps_metrics", ())
            if str(metric_id) in allowed
        )
        return selected or cls._overlay_default_kps_metric_ids()

    @staticmethod
    def _tracked_item_rules_from_config(overlay_config: dict[str, Any]) -> tuple[TrackedItemRule, ...]:
        rules: list[TrackedItemRule] = []
        for raw_rule in overlay_config.get("tracked_items") or ():
            if not isinstance(raw_rule, dict):
                continue
            item_names = tuple(str(name) for name in raw_rule.get("item_names") or () if str(name).strip())
            if not item_names:
                continue
            rules.append(
                TrackedItemRule(
                    id=str(raw_rule.get("id") or "_".join(item_names).lower()),
                    label=str(raw_rule.get("label") or ", ".join(item_names)),
                    item_names=item_names,
                    mode=str(raw_rule.get("mode") or "all_run"),
                    before_stage=_coerce_optional_int(raw_rule.get("before_stage")),
                    before_seconds=_coerce_optional_float(raw_rule.get("before_seconds")),
                    max_copies=_coerce_optional_int(raw_rule.get("max_copies")),
                )
            )
        return tuple(rules)

    @staticmethod
    def _session_tracked_item_rules_from_config(session_config: dict[str, Any]) -> tuple[TrackedItemRule, ...]:
        return OverlayMixin._tracked_item_rules_from_config(session_config)

    @staticmethod
    def _twitch_tracked_item_rules_from_config(twitch_config: dict[str, Any]) -> tuple[TrackedItemRule, ...]:
        return OverlayMixin._tracked_item_rules_from_config(twitch_config)

    @staticmethod
    def _uses_session_tracked_items(source_config: dict[str, Any], *, default: str = "custom") -> bool:
        return str(source_config.get("tracked_items_source") or default).strip().lower() == "session"

    def _effective_overlay_tracked_item_rules(self) -> tuple[TrackedItemRule, ...]:
        if self._uses_session_tracked_items(config.OVERLAY, default="custom"):
            return self._session_tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS)
        return self._tracked_item_rules_from_config(config.OVERLAY)

    def _effective_twitch_tracked_item_rules(self) -> tuple[TrackedItemRule, ...]:
        if self._uses_session_tracked_items(config.TWITCH_BOT, default="custom"):
            return self._session_tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS)
        return self._twitch_tracked_item_rules_from_config(config.TWITCH_BOT)

    def _effective_overlay_config(self) -> dict[str, Any]:
        overlay = dict(config.OVERLAY)
        if self._uses_session_tracked_items(overlay, default="custom"):
            overlay["tracked_items"] = list(config.SESSION_TRACKED_ITEMS.get("tracked_items") or [])
        return overlay

    def _combined_tracked_item_rules(self) -> tuple[TrackedItemRule, ...]:
        combined: dict[str, TrackedItemRule] = {}
        for rule in self._tracked_item_rules_from_config(config.OVERLAY):
            combined[rule.id] = rule
        for rule in self._session_tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS):
            combined[rule.id] = rule
        for rule in self._twitch_tracked_item_rules_from_config(config.TWITCH_BOT):
            combined[rule.id] = rule
        return tuple(combined.values())

    @classmethod
    def _overlay_available_item_names(cls) -> tuple[str, ...]:
        return tuple(sorted(available_item_display_names(), key=cls._tracked_item_sort_key))

    @staticmethod
    def _tracked_item_display_name(item_name: str) -> str:
        return preferred_item_display_name(str(item_name))

    @classmethod
    def _tracked_item_sort_key(cls, item_name: str) -> tuple[int, str]:
        return (-cls._tracked_item_rarity_rank(item_name), cls._tracked_item_display_name(item_name).lower())

    @staticmethod
    def _tracked_item_rarity_rank(item_name: str) -> int:
        canonical_name = normalize_item_name_for_rarity(str(item_name))
        rarity = ITEM_RARITY_BY_NAME.get(canonical_name)
        return ITEM_RARITY_SORT_ORDER.get(rarity, -1)

    @staticmethod
    def _tracked_item_color(item_name: str) -> str:
        direct_color = item_display_color(item_name)
        if direct_color:
            return direct_color
        canonical_name = normalize_item_name_for_rarity(str(item_name))
        rarity = ITEM_RARITY_BY_NAME.get(canonical_name)
        return ITEM_RARITY_COLOR_MAP.get(rarity, "#E5E7EB")

    @classmethod
    def _tracked_item_combo_display_name(cls, item_names: list[str] | tuple[str, ...]) -> str:
        return " + ".join(cls._tracked_item_display_name(item_name) for item_name in item_names)

    @classmethod
    def _tracked_rule_color(cls, item_names: list[str] | tuple[str, ...]) -> str:
        if not item_names:
            return "#E5E7EB"
        ranked_items = sorted(
            item_names,
            key=lambda item_name: ITEM_RARITY_SORT_ORDER.get(
                ITEM_RARITY_BY_NAME.get(normalize_item_name_for_rarity(str(item_name))), -1
            ),
            reverse=True,
        )
        return cls._tracked_item_color(ranked_items[0])

    @staticmethod
    def _tracked_rule_tag_label(label: str, mode: str) -> str:
        label = str(label).strip() or "Item"
        if mode == "map_1_only":
            lowered = label.casefold()
            if lowered.endswith((" map 1", " map1", " t1")):
                return label
            return f"{label} [Map 1]"
        if mode == "all_run":
            return label
        return f"{label} [{mode}]"

    @classmethod
    def _tracked_rule_display_label(
        cls,
        rule: dict[str, Any],
        item_names: list[str],
        mode: str,
    ) -> str:
        raw_label = str(rule.get("label") or " + ".join(item_names))
        if len(item_names) != 1:
            return raw_label
        canonical_name = str(item_names[0])
        preferred_name = cls._tracked_item_display_name(canonical_name)
        default_label = f"{canonical_name} Map 1" if mode == "map_1_only" else canonical_name
        preferred_label = f"{preferred_name} Map 1" if mode == "map_1_only" else preferred_name
        return preferred_label if raw_label == default_label else raw_label

    @staticmethod
    def _overlay_rule_id(item_names: list[str] | tuple[str, ...], mode: str) -> str:
        folded = "_".join(
            "".join(char.lower() for char in item_name if char.isalnum())
            for item_name in item_names
        )
        return f"{folded or 'item'}_{mode}"

    @staticmethod
    def _session_rule_id(item_names: list[str] | tuple[str, ...], mode: str) -> str:
        folded = "_".join(
            "".join(char.lower() for char in item_name if char.isalnum())
            for item_name in item_names
        )
        return f"session_{folded or 'item'}_{mode}"

    @staticmethod
    def _dedupe_item_names(item_names: list[str] | tuple[str, ...]) -> list[str]:
        deduped: list[str] = []
        for item_name in item_names:
            value = str(item_name).strip()
            if value and value not in deduped:
                deduped.append(value)
        return deduped


def _coerce_optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
