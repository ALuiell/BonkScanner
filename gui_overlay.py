from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from gui_shared import _make_scroll_section, _set_text, _set_text_input
from gui_styles import PLAYER_STATS_REFRESH_MS, _button_state_stylesheet
from item_metadata import available_item_display_names, preferred_item_display_name
from live_run_tracker import LiveRunTracker, TrackedItemRule
from overlay_server import LocalOverlayServer, OverlayStateStore
from overlay_state import build_overlay_state
from player_stats import PLAYER_STAT_GROUPS


OVERLAY_WIDGET_LABELS = {
    "stage_summary": "Stage summary",
    "tracked_items": "Tracked items",
    "stats": "Stats",
    "banishes": "Banishes",
}

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
        self.overlay_state_store.set_state(build_overlay_state(self.live_run_tracker, config.OVERLAY))

    def _build_overlay_tab(self) -> None:
        self.tab_overlay = QWidget()
        tab_layout = QVBoxLayout(self.tab_overlay)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        overlay_scroll, _overlay_content, layout = _make_scroll_section()
        layout.setSpacing(10)
        tab_layout.addWidget(overlay_scroll)

        status_group = QGroupBox("OBS Browser Source")
        status_layout = QVBoxLayout(status_group)

        intro_label = QLabel(
            "<span style='font-size:10.5pt; font-weight:bold; color:#ffd23f;'>💡 Visual Layout Editor Mode is active!</span><br>"
            "<span style='font-size:9.5pt; color:#ffffff;'>"
            "Open your overlay URL in any browser with <b>?edit=true</b> to drag & drop widgets and change HUD resolution! "
            "Set Width & Height in OBS Browser Source properties to match your custom canvas resolution (default: 1920x1080)."
            "</span>"
        )
        intro_label.setTextFormat(Qt.RichText)
        intro_label.setWordWrap(True)
        status_layout.addWidget(intro_label)

        self.overlay_status_label = QLabel()
        self.overlay_status_label.setTextFormat(Qt.RichText)
        self.overlay_url_entry = QLineEdit()
        self.overlay_url_entry.setReadOnly(True)
        self.overlay_url_entry.setText(self._overlay_url_text())
        self.overlay_widget_url_combo = QComboBox()
        for widget_id, label in OVERLAY_WIDGET_LABELS.items():
            self.overlay_widget_url_combo.addItem(label, widget_id)
        self.overlay_widget_url_combo.addItem("Layout Editor Mode", "editor")
        self.overlay_widget_url_combo.currentIndexChanged.connect(lambda _index: self.refresh_overlay_ui())
        self.overlay_widget_url_entry = QLineEdit()
        self.overlay_widget_url_entry.setReadOnly(True)
        self.overlay_server_toggle_btn = QPushButton("Start")
        self.overlay_server_toggle_btn.setObjectName("SuccessButton")
        self.overlay_server_toggle_btn.clicked.connect(self.toggle_overlay_server)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("OBS Overlay server"))
        controls.addWidget(self.overlay_status_label)
        controls.addWidget(self.overlay_server_toggle_btn)
        controls.addStretch(1)
        status_layout.addLayout(controls)
        url_grid = QGridLayout()
        url_grid.addWidget(QLabel("Full overlay"), 0, 0)
        url_grid.addWidget(self.overlay_url_entry, 0, 1)
        url_grid.addWidget(QLabel("Widget URL"), 1, 0)
        url_grid.addWidget(self.overlay_widget_url_combo, 1, 1)
        url_grid.addWidget(self.overlay_widget_url_entry, 2, 1)
        status_layout.addLayout(url_grid)
        layout.addWidget(status_group)

        settings_group = QGroupBox("Settings")
        settings_layout = QFormLayout(settings_group)
        self.overlay_port_entry = QLineEdit(str(config.OVERLAY.get("port", 17845)))
        self.overlay_port_entry.editingFinished.connect(self.save_overlay_settings_from_ui)
        settings_layout.addRow("Port", self.overlay_port_entry)
        layout.addWidget(settings_group)

        widgets_group = QGroupBox("Widgets")
        widgets_layout = QVBoxLayout(widgets_group)
        widgets_header = QHBoxLayout()
        widgets_header.addWidget(QLabel("Visible widgets"))
        widgets_header.addStretch(1)
        self.overlay_widget_settings_btn = QPushButton("Widget Settings")
        self.overlay_widget_settings_btn.clicked.connect(self.open_overlay_widget_settings_dialog)
        widgets_header.addWidget(self.overlay_widget_settings_btn)
        widgets_layout.addLayout(widgets_header)

        widgets_grid = QGridLayout()
        self.overlay_widget_checkboxes = {}
        widget_config = self._overlay_widget_config_by_id()
        for index, (widget_id, label) in enumerate(OVERLAY_WIDGET_LABELS.items()):
            checkbox = QCheckBox(label)
            checkbox.setChecked(bool(widget_config.get(widget_id, {}).get("enabled", True)))
            checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
            self.overlay_widget_checkboxes[widget_id] = checkbox
            widgets_grid.addWidget(checkbox, index // 4, index % 4)
        widgets_layout.addLayout(widgets_grid)
        layout.addWidget(widgets_group)

        self.overlay_tracked_items_label = None

        help_row = QHBoxLayout()
        help_label = QLabel(
            "Add the local URL as an OBS Browser Source. Recording is not required.<br>"
            "<b>Tip: Open the overlay URL in your browser with '?edit=true' to visually position widgets and customize canvas resolution!</b>"
        )
        help_label.setTextFormat(Qt.RichText)
        help_label.setWordWrap(True)
        help_btn = QPushButton("Open Help")
        help_btn.clicked.connect(self.open_help_dialog)
        help_row.addWidget(help_label, 1)
        help_row.addWidget(help_btn)
        layout.addLayout(help_row)
        layout.addStretch(1)
        self.tabview.addTab(self.tab_overlay, "OBS Overlay")
        self.refresh_overlay_item_selector()
        self.refresh_overlay_tracked_items_ui()
        self.refresh_overlay_ui()

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
        basic_layout.addStretch(1)

        stats_group = QGroupBox("Stats")
        stats_layout = QVBoxLayout(stats_group)
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

        items_group = QGroupBox("Tracked Items")
        items_layout = QVBoxLayout(items_group)
        items_layout.addWidget(QLabel("Configure tracked item counters for the overlay."))
        self.overlay_map_one_only_checkbox = QCheckBox("Map 1 only")
        self.overlay_map_one_only_checkbox.setChecked(True)
        items_layout.addWidget(self.overlay_map_one_only_checkbox)
        self.overlay_item_names = self._overlay_available_item_names()
        self.overlay_item_search_entry = QLineEdit()
        self.overlay_item_search_entry.setPlaceholderText("Search items...")
        self.overlay_item_search_entry.textChanged.connect(self.refresh_overlay_item_selector)
        items_layout.addWidget(self.overlay_item_search_entry)
        self.overlay_item_selector = QListWidget()
        self.overlay_item_selector.setMinimumHeight(180)
        items_layout.addWidget(self.overlay_item_selector)
        add_row = QHBoxLayout()
        self.overlay_add_tracked_item_btn = QPushButton("Add Tracked Item")
        self.overlay_add_tracked_item_btn.clicked.connect(self.add_overlay_tracked_item)
        add_row.addWidget(self.overlay_add_tracked_item_btn)
        add_row.addStretch(1)
        items_layout.addLayout(add_row)
        items_layout.addWidget(QLabel("Currently tracked"))
        self.overlay_tracked_rules_list = QListWidget()
        self.overlay_tracked_rules_list.setMinimumHeight(140)
        items_layout.addWidget(self.overlay_tracked_rules_list)
        remove_row = QHBoxLayout()
        self.overlay_remove_tracked_item_btn = QPushButton("Remove Selected")
        self.overlay_remove_tracked_item_btn.clicked.connect(self.remove_overlay_tracked_item)
        remove_row.addWidget(self.overlay_remove_tracked_item_btn)
        remove_row.addStretch(1)
        items_layout.addLayout(remove_row)
        advanced_layout.addWidget(items_group)
        advanced_layout.addStretch(1)

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
        self.overlay_banishes_bg_checkbox = None
        self.overlay_banishes_header_checkbox = None
        self.overlay_item_search_entry = None
        self.overlay_item_selector = None
        self.overlay_map_one_only_checkbox = None
        self.overlay_add_tracked_item_btn = None
        self.overlay_tracked_rules_list = None
        self.overlay_remove_tracked_item_btn = None
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
                if widget_id == "banishes":
                    widget = dict(widget)
                    if getattr(self, "overlay_banishes_bg_checkbox", None) is not None:
                        widget["background_opacity"] = 0.4 if self.overlay_banishes_bg_checkbox.isChecked() else 0.0
                    if getattr(self, "overlay_banishes_header_checkbox", None) is not None:
                        widget["show_header"] = bool(self.overlay_banishes_header_checkbox.isChecked())
                widgets.append(widget)
            overlay["widgets"] = widgets
            if getattr(self, "overlay_tracked_rules_list", None) is not None:
                overlay["tracked_items"] = self._tracked_item_config_from_ui()
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
                status = 'Status: <span style="color:#4fd67a;">live</span>'
            elif server is not None and server.last_error:
                status = f'Status: <span style="color:#f08b72;">port error</span> ({server.last_error})'
            else:
                status = 'Status: <span style="color:#f08b72;">stopped</span>'
            _set_text(self.overlay_status_label, status)
        if getattr(self, "overlay_server_toggle_btn", None) is not None:
            self.overlay_server_toggle_btn.setText("Stop" if running else "Start")
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
        selector.clear()
        for item_name in getattr(self, "overlay_item_names", ()):
            display_name = self._tracked_item_display_name(item_name)
            haystacks = {item_name.lower(), display_name.lower()}
            if query and not any(query in haystack for haystack in haystacks):
                continue
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, item_name)
            selector.addItem(item)
        if selector.count() > 0:
            selector.setCurrentRow(0)

    def refresh_overlay_tracked_items_ui(self) -> None:
        rules_list = getattr(self, "overlay_tracked_rules_list", None)
        if rules_list is not None:
            rules_list.clear()
        tracked_count = 0
        for rule in config.OVERLAY.get("tracked_items") or ():
            if not isinstance(rule, dict):
                continue
            item_names = [str(name) for name in rule.get("item_names") or () if str(name).strip()]
            if not item_names:
                continue
            mode = str(rule.get("mode") or "all_run")
            mode_label = "Map 1" if mode == "map_1_only" else "All run"
            label = self._tracked_rule_display_label(dict(rule), item_names, mode)
            if rules_list is not None:
                item = QListWidgetItem(f"{label}  [{mode_label}]")
                item.setData(Qt.UserRole, dict(rule))
                rules_list.addItem(item)
            tracked_count += 1
        if self.overlay_tracked_items_label is not None:
            detail = "Map 1 only counts gains observed during stage 1."
            _set_text(self.overlay_tracked_items_label, f"Tracking {tracked_count} rule(s). {detail}")

    def add_overlay_tracked_item(self) -> None:
        item_name = self._selected_overlay_item_name()
        if not item_name:
            return
        map_one_only = bool(self.overlay_map_one_only_checkbox.isChecked())
        mode = "map_1_only" if map_one_only else "all_run"
        display_name = self._tracked_item_display_name(item_name)
        label = f"{display_name} Map 1" if map_one_only else display_name
        rule = {
            "id": self._overlay_rule_id(item_name, mode),
            "label": label,
            "item_names": [item_name],
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
        self.refresh_overlay_tracked_items_ui()
        self.save_overlay_settings_from_ui()

    def remove_overlay_tracked_item(self) -> None:
        rules_list = getattr(self, "overlay_tracked_rules_list", None)
        if rules_list is None or rules_list.currentRow() < 0:
            return
        rules_list.takeItem(rules_list.currentRow())
        config.OVERLAY["tracked_items"] = self._tracked_item_config_from_ui()
        config.user_config["OVERLAY"] = config.OVERLAY
        self.save_overlay_settings_from_ui()

    def open_session_tracked_item_settings_dialog(self) -> None:
        dialog = QDialog(self.tab_stats)
        dialog.setUpdatesEnabled(False)
        dialog.setWindowTitle("Session Tracked Items")
        dialog.resize(700, 640)
        dialog.setMinimumSize(620, 520)
        dialog_layout = QVBoxLayout(dialog)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(10)
        content_layout.addWidget(QLabel("Track item gains in Session Stats. Map 1 only counts gains observed during stage 1."))

        self.session_map_one_only_checkbox = QCheckBox("Map 1 only")
        self.session_map_one_only_checkbox.setChecked(True)
        content_layout.addWidget(self.session_map_one_only_checkbox)

        self.session_item_names = self._overlay_available_item_names()
        self.session_item_search_entry = QLineEdit()
        self.session_item_search_entry.setPlaceholderText("Search items...")
        self.session_item_search_entry.textChanged.connect(self.refresh_session_item_selector)
        content_layout.addWidget(self.session_item_search_entry)

        self.session_item_selector = QListWidget()
        self.session_item_selector.setMinimumHeight(140)
        content_layout.addWidget(self.session_item_selector)

        add_row = QHBoxLayout()
        self.session_add_tracked_item_btn = QPushButton("Add Tracked Item")
        self.session_add_tracked_item_btn.clicked.connect(self.add_session_tracked_item)
        add_row.addWidget(self.session_add_tracked_item_btn)
        add_row.addStretch(1)
        content_layout.addLayout(add_row)

        content_layout.addWidget(QLabel("Currently tracked"))
        self.session_tracked_rules_list = QListWidget()
        self.session_tracked_rules_list.setMinimumHeight(100)
        content_layout.addWidget(self.session_tracked_rules_list)

        remove_row = QHBoxLayout()
        self.session_remove_tracked_item_btn = QPushButton("Remove Selected")
        self.session_remove_tracked_item_btn.clicked.connect(self.remove_session_tracked_item)
        remove_row.addWidget(self.session_remove_tracked_item_btn)
        remove_row.addStretch(1)
        content_layout.addLayout(remove_row)

        dialog_layout.addWidget(content)

        close_row = QHBoxLayout()
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
        selector.clear()
        for item_name in getattr(self, "session_item_names", ()):
            display_name = self._tracked_item_display_name(item_name)
            haystacks = {item_name.lower(), display_name.lower()}
            if query and not any(query in haystack for haystack in haystacks):
                continue
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, item_name)
            selector.addItem(item)
        if selector.count() > 0:
            selector.setCurrentRow(0)

    def refresh_session_tracked_items_ui(self) -> None:
        rules_list = getattr(self, "session_tracked_rules_list", None)
        if rules_list is None:
            return
        rules_list.clear()
        for rule in config.SESSION_TRACKED_ITEMS.get("tracked_items") or ():
            if not isinstance(rule, dict):
                continue
            item_names = [str(name) for name in rule.get("item_names") or () if str(name).strip()]
            if not item_names:
                continue
            mode = str(rule.get("mode") or "all_run")
            mode_label = "Map 1" if mode == "map_1_only" else "All run"
            label = self._tracked_rule_display_label(dict(rule), item_names, mode)
            item = QListWidgetItem(f"{label}  [{mode_label}]")
            item.setData(Qt.UserRole, dict(rule))
            rules_list.addItem(item)

    def refresh_session_tracked_item_stats_ui(self) -> None:
        label = getattr(self, "stats_tracked_items_label", None)
        if label is None or self.live_run_tracker is None:
            return
        rules = self._session_tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS)
        rows = self.live_run_tracker.tracked_item_rows_for_rules(rules)
        if not rows:
            _set_text(label, "No tracked items configured")
            return
        _set_text(label, " | ".join(f"{row['label']}: {row['count']}" for row in rows))

    def add_session_tracked_item(self) -> None:
        item_name = self._selected_session_item_name()
        if not item_name:
            return
        map_one_only = bool(self.session_map_one_only_checkbox.isChecked())
        mode = "map_1_only" if map_one_only else "all_run"
        display_name = self._tracked_item_display_name(item_name)
        label = f"{display_name} Map 1" if map_one_only else display_name
        rule = {
            "id": self._session_rule_id(item_name, mode),
            "label": label,
            "item_names": [item_name],
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
        self.refresh_session_tracked_items_ui()
        self.save_session_tracked_items_from_ui()

    def remove_session_tracked_item(self) -> None:
        rules_list = getattr(self, "session_tracked_rules_list", None)
        if rules_list is None or rules_list.currentRow() < 0:
            return
        rules_list.takeItem(rules_list.currentRow())
        config.SESSION_TRACKED_ITEMS["tracked_items"] = self._session_tracked_item_config_from_ui()
        self.save_session_tracked_items_from_ui()

    def save_session_tracked_items_from_ui(self) -> None:
        if getattr(self, "session_tracked_rules_list", None) is not None:
            config.SESSION_TRACKED_ITEMS["tracked_items"] = self._session_tracked_item_config_from_ui()
        config.SESSION_TRACKED_ITEMS = config.normalize_session_tracked_items_config(config.SESSION_TRACKED_ITEMS)
        config.user_config["SESSION_TRACKED_ITEMS"] = config.SESSION_TRACKED_ITEMS
        config.save_config(config.user_config)
        self.live_run_tracker.set_tracked_item_rules(self._combined_tracked_item_rules())
        self.refresh_session_tracked_items_ui()
        self.refresh_session_tracked_item_stats_ui()

    def _selected_session_item_name(self) -> str:
        selector = getattr(self, "session_item_selector", None)
        if selector is not None and selector.currentItem() is not None:
            return str(selector.currentItem().data(Qt.UserRole) or selector.currentItem().text()).strip()
        if getattr(self, "session_item_search_entry", None) is not None:
            query = self.session_item_search_entry.text().strip()
            for item_name in getattr(self, "session_item_names", ()):
                display_name = self._tracked_item_display_name(item_name)
                if item_name.lower() == query.lower() or display_name.lower() == query.lower():
                    return item_name
        return ""

    def _session_tracked_item_config_from_ui(self) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        rules_list = getattr(self, "session_tracked_rules_list", None)
        if rules_list is None:
            return rules
        for index in range(rules_list.count()):
            item = rules_list.item(index)
            rule = item.data(Qt.UserRole)
            if isinstance(rule, dict):
                rules.append(dict(rule))
        return rules

    def _clear_session_tracked_item_dialog_refs(self) -> None:
        self.session_item_search_entry = None
        self.session_item_selector = None
        self.session_map_one_only_checkbox = None
        self.session_add_tracked_item_btn = None
        self.session_tracked_rules_list = None
        self.session_remove_tracked_item_btn = None

    def _selected_overlay_item_name(self) -> str:
        selector = getattr(self, "overlay_item_selector", None)
        if selector is not None and selector.currentItem() is not None:
            return str(selector.currentItem().data(Qt.UserRole) or selector.currentItem().text()).strip()
        if getattr(self, "overlay_item_search_entry", None) is not None:
            query = self.overlay_item_search_entry.text().strip()
            for item_name in getattr(self, "overlay_item_names", ()):
                display_name = self._tracked_item_display_name(item_name)
                if item_name.lower() == query.lower() or display_name.lower() == query.lower():
                    return item_name
        return ""

    def _tracked_item_config_from_ui(self) -> list[dict[str, Any]]:
        rules: list[dict[str, Any]] = []
        rules_list = getattr(self, "overlay_tracked_rules_list", None)
        if rules_list is None:
            return rules
        for index in range(rules_list.count()):
            item = rules_list.item(index)
            rule = item.data(Qt.UserRole)
            if isinstance(rule, dict):
                rules.append(dict(rule))
        return rules

    def update_overlay_state_from_tracker(self) -> None:
        if self.overlay_state_store is None:
            return
        self.overlay_state_store.set_state(build_overlay_state(self.live_run_tracker, config.OVERLAY))
        if getattr(self, "tab_overlay", None) is not None:
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
        if bool(config.OVERLAY.get("enabled", False)):
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

    def _combined_tracked_item_rules(self) -> tuple[TrackedItemRule, ...]:
        combined: dict[str, TrackedItemRule] = {}
        for rule in self._tracked_item_rules_from_config(config.OVERLAY):
            combined[rule.id] = rule
        for rule in self._session_tracked_item_rules_from_config(config.SESSION_TRACKED_ITEMS):
            combined[rule.id] = rule
        return tuple(combined.values())

    @staticmethod
    def _overlay_available_item_names() -> tuple[str, ...]:
        return available_item_display_names()

    @staticmethod
    def _tracked_item_display_name(item_name: str) -> str:
        return preferred_item_display_name(str(item_name))

    @classmethod
    def _tracked_rule_display_label(
        cls,
        rule: dict[str, Any],
        item_names: list[str],
        mode: str,
    ) -> str:
        raw_label = str(rule.get("label") or ", ".join(item_names))
        if len(item_names) != 1:
            return raw_label
        canonical_name = str(item_names[0])
        preferred_name = cls._tracked_item_display_name(canonical_name)
        default_label = f"{canonical_name} Map 1" if mode == "map_1_only" else canonical_name
        preferred_label = f"{preferred_name} Map 1" if mode == "map_1_only" else preferred_name
        return preferred_label if raw_label == default_label else raw_label

    @staticmethod
    def _overlay_rule_id(item_name: str, mode: str) -> str:
        folded = "".join(char.lower() for char in item_name if char.isalnum())
        return f"{folded or 'item'}_{mode}"

    @staticmethod
    def _session_rule_id(item_name: str, mode: str) -> str:
        folded = "".join(char.lower() for char in item_name if char.isalnum())
        return f"session_{folded or 'item'}_{mode}"


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
