from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from gui_shared import _set_text, _set_text_input
from gui_styles import ITEM_RARITY_BY_NAME
from live_run_tracker import LiveRunTracker, TrackedItemRule
from overlay_server import LocalOverlayServer, OverlayStateStore
from overlay_state import build_overlay_state
from player_stats import ITEM_ENUM_NAMES_BY_ID, PLAYER_STAT_GROUPS, PlayerStatsClient


OVERLAY_WIDGET_LABELS = {
    "run_timer": "Run timer",
    "level": "Level",
    "kills": "Kills",
    "current_stage": "Current stage",
    "stage_summary": "Stage summary",
    "tracked_items": "Tracked items",
    "stats": "Stats",
    "weapons": "Weapons",
    "items": "Items",
}


class OverlayMixin:
    def initialize_overlay_runtime(self) -> None:
        self.overlay_state_store = OverlayStateStore()
        self.live_run_tracker = LiveRunTracker(
            tracked_item_rules=self._tracked_item_rules_from_config(config.OVERLAY),
        )
        self.overlay_server = LocalOverlayServer(
            host=config.OVERLAY.get("host", "127.0.0.1"),
            port=int(config.OVERLAY.get("port", 17845)),
            state_store=self.overlay_state_store,
        )
        self.overlay_state_store.set_state(build_overlay_state(self.live_run_tracker, config.OVERLAY))

    def _build_overlay_tab(self) -> None:
        self.tab_overlay = QWidget()
        layout = QVBoxLayout(self.tab_overlay)
        layout.setSpacing(10)

        status_group = QGroupBox("OBS Browser Source")
        status_layout = QVBoxLayout(status_group)
        self.overlay_status_label = QLabel("status: stopped")
        self.overlay_url_entry = QLineEdit()
        self.overlay_url_entry.setReadOnly(True)
        self.overlay_url_entry.setText(self._overlay_url_text())
        self.overlay_widget_url_combo = QComboBox()
        for widget_id, label in OVERLAY_WIDGET_LABELS.items():
            self.overlay_widget_url_combo.addItem(label, widget_id)
        self.overlay_widget_url_combo.currentIndexChanged.connect(lambda _index: self.refresh_overlay_ui())
        self.overlay_widget_url_entry = QLineEdit()
        self.overlay_widget_url_entry.setReadOnly(True)
        self.overlay_server_toggle_btn = QPushButton("Start")
        self.overlay_server_toggle_btn.clicked.connect(self.toggle_overlay_server)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("OBS Overlay server"))
        controls.addWidget(self.overlay_status_label)
        controls.addStretch(1)
        controls.addWidget(self.overlay_server_toggle_btn)
        self.overlay_enabled_checkbox = QCheckBox("Auto-start")
        self.overlay_enabled_checkbox.setChecked(bool(config.OVERLAY.get("enabled", False)))
        self.overlay_enabled_checkbox.stateChanged.connect(lambda _state: self.on_overlay_enabled_changed())
        controls.addWidget(self.overlay_enabled_checkbox)
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
        self.overlay_template_combo = QComboBox()
        self.overlay_template_combo.addItem("Compact", "compact")
        self.overlay_template_combo.addItem("Full", "full")
        template_index = self.overlay_template_combo.findData(str(config.OVERLAY.get("template", "compact")))
        self.overlay_template_combo.setCurrentIndex(max(0, template_index))
        self.overlay_template_combo.currentIndexChanged.connect(lambda _index: self.save_overlay_settings_from_ui())
        settings_layout.addRow("Port", self.overlay_port_entry)
        settings_layout.addRow("Template", self.overlay_template_combo)
        layout.addWidget(settings_group)

        widgets_group = QGroupBox("Widgets")
        widgets_layout = QGridLayout(widgets_group)
        self.overlay_widget_checkboxes = {}
        widget_config = self._overlay_widget_config_by_id()
        for index, (widget_id, label) in enumerate(OVERLAY_WIDGET_LABELS.items()):
            checkbox = QCheckBox(label)
            checkbox.setChecked(bool(widget_config.get(widget_id, {}).get("enabled", True)))
            checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
            self.overlay_widget_checkboxes[widget_id] = checkbox
            widgets_layout.addWidget(checkbox, index // 4, index % 4)
        layout.addWidget(widgets_group)

        stats_group = QGroupBox("Stats Widget")
        stats_layout = QVBoxLayout(stats_group)
        stats_header = QHBoxLayout()
        self.overlay_stats_toggle_btn = QPushButton("Configure Stats")
        self.overlay_stats_toggle_btn.setCheckable(True)
        self.overlay_stats_toggle_btn.setChecked(False)
        self.overlay_stats_toggle_btn.toggled.connect(self._set_overlay_stats_expanded)
        stats_header.addWidget(QLabel("Selected stats appear in the Stats overlay widget."))
        stats_header.addStretch(1)
        stats_header.addWidget(self.overlay_stats_toggle_btn)
        stats_layout.addLayout(stats_header)
        self.overlay_stats_content = QWidget()
        stats_config_layout = QGridLayout(self.overlay_stats_content)
        self.overlay_stats_checkboxes = {}
        selected_stats = set(self._overlay_selected_stat_labels())
        all_stats = self._overlay_all_stat_labels()
        for index, label in enumerate(all_stats):
            checkbox = QCheckBox(label)
            checkbox.setChecked(label in selected_stats)
            checkbox.stateChanged.connect(lambda _state: self.save_overlay_settings_from_ui())
            self.overlay_stats_checkboxes[label] = checkbox
            stats_config_layout.addWidget(checkbox, index // 4, index % 4)
        self.overlay_stats_content.setVisible(False)
        stats_layout.addWidget(self.overlay_stats_content)
        layout.addWidget(stats_group)

        tracked_group = QGroupBox("Tracked Items")
        tracked_layout = QVBoxLayout(tracked_group)
        tracked_header = QHBoxLayout()
        self.overlay_tracked_items_label = QLabel("Track selected item gains in the overlay.")
        self.overlay_tracked_items_label.setWordWrap(True)
        self.overlay_tracked_items_toggle_btn = QPushButton("Configure Items")
        self.overlay_tracked_items_toggle_btn.setCheckable(True)
        self.overlay_tracked_items_toggle_btn.setChecked(False)
        self.overlay_tracked_items_toggle_btn.toggled.connect(self._set_overlay_tracked_items_expanded)
        tracked_header.addWidget(self.overlay_tracked_items_label, 1)
        tracked_header.addWidget(self.overlay_tracked_items_toggle_btn)
        tracked_layout.addLayout(tracked_header)
        self.overlay_tracked_items_content = QWidget()
        tracked_content_layout = QVBoxLayout(self.overlay_tracked_items_content)
        tracked_content_layout.setContentsMargins(0, 0, 0, 0)
        self.overlay_item_names = self._overlay_available_item_names()
        self.overlay_item_search_entry = QLineEdit()
        self.overlay_item_search_entry.setPlaceholderText("Search items...")
        self.overlay_item_search_entry.textChanged.connect(self.refresh_overlay_item_selector)
        tracked_content_layout.addWidget(self.overlay_item_search_entry)
        self.overlay_item_selector = QListWidget()
        self.overlay_item_selector.setMaximumHeight(110)
        tracked_content_layout.addWidget(self.overlay_item_selector)
        add_row = QHBoxLayout()
        self.overlay_map_one_only_checkbox = QCheckBox("Map 1 only")
        self.overlay_map_one_only_checkbox.setChecked(True)
        self.overlay_add_tracked_item_btn = QPushButton("Add Tracked Item")
        self.overlay_add_tracked_item_btn.clicked.connect(self.add_overlay_tracked_item)
        add_row.addWidget(self.overlay_map_one_only_checkbox)
        add_row.addWidget(self.overlay_add_tracked_item_btn)
        add_row.addStretch(1)
        tracked_content_layout.addLayout(add_row)
        tracked_content_layout.addWidget(QLabel("Currently tracked"))
        self.overlay_tracked_rules_list = QListWidget()
        self.overlay_tracked_rules_list.setMaximumHeight(100)
        tracked_content_layout.addWidget(self.overlay_tracked_rules_list)
        remove_row = QHBoxLayout()
        self.overlay_remove_tracked_item_btn = QPushButton("Remove Selected")
        self.overlay_remove_tracked_item_btn.clicked.connect(self.remove_overlay_tracked_item)
        remove_row.addWidget(self.overlay_remove_tracked_item_btn)
        remove_row.addStretch(1)
        tracked_content_layout.addLayout(remove_row)
        self.overlay_tracked_items_content.setVisible(False)
        tracked_layout.addWidget(self.overlay_tracked_items_content)
        layout.addWidget(tracked_group)

        help_row = QHBoxLayout()
        help_label = QLabel("Add the local URL as an OBS Browser Source. Recording is not required.")
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

    def on_overlay_enabled_changed(self) -> None:
        config.OVERLAY["enabled"] = bool(self.overlay_enabled_checkbox.isChecked())
        config.user_config["OVERLAY"] = config.OVERLAY
        config.save_config(config.user_config)
        if config.OVERLAY["enabled"]:
            self.start_overlay_server()
        else:
            self.stop_overlay_server()
        self.refresh_overlay_ui()

    def toggle_overlay_server(self) -> None:
        server = getattr(self, "overlay_server", None)
        should_start = not bool(server is not None and server.is_running)
        if self.overlay_enabled_checkbox is not None:
            self.overlay_enabled_checkbox.blockSignals(True)
            self.overlay_enabled_checkbox.setChecked(should_start)
            self.overlay_enabled_checkbox.blockSignals(False)
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
        if self.overlay_template_combo is not None:
            overlay["template"] = str(self.overlay_template_combo.currentData() or "compact")

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
            widgets.append(widget)
        overlay["widgets"] = widgets
        if getattr(self, "overlay_tracked_rules_list", None) is not None:
            overlay["tracked_items"] = self._tracked_item_config_from_ui()
        config.OVERLAY = overlay
        config.user_config["OVERLAY"] = config.OVERLAY
        self.live_run_tracker.set_tracked_item_rules(self._tracked_item_rules_from_config(config.OVERLAY))
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
                status = "status: live"
            elif server is not None and server.last_error:
                status = f"status: port error ({server.last_error})"
            else:
                status = "status: stopped"
            _set_text(self.overlay_status_label, status)
        if getattr(self, "overlay_server_toggle_btn", None) is not None:
            self.overlay_server_toggle_btn.setText("Stop" if running else "Start")
        if self.overlay_enabled_checkbox is not None and self.overlay_enabled_checkbox.isChecked() != bool(
            config.OVERLAY.get("enabled", False)
        ):
            self.overlay_enabled_checkbox.blockSignals(True)
            self.overlay_enabled_checkbox.setChecked(bool(config.OVERLAY.get("enabled", False)))
            self.overlay_enabled_checkbox.blockSignals(False)

    def refresh_overlay_item_selector(self) -> None:
        selector = getattr(self, "overlay_item_selector", None)
        if selector is None:
            return
        query = ""
        if getattr(self, "overlay_item_search_entry", None) is not None:
            query = self.overlay_item_search_entry.text().strip().lower()
        selector.clear()
        for item_name in getattr(self, "overlay_item_names", ()):
            if query and query not in item_name.lower():
                continue
            item = QListWidgetItem(item_name)
            item.setData(Qt.UserRole, item_name)
            selector.addItem(item)
        if selector.count() > 0:
            selector.setCurrentRow(0)

    def refresh_overlay_tracked_items_ui(self) -> None:
        rules_list = getattr(self, "overlay_tracked_rules_list", None)
        if rules_list is None:
            return
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
            label = str(rule.get("label") or ", ".join(item_names))
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
        label = f"{item_name} Map 1" if map_one_only else item_name
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
        config.save_config(config.user_config)
        self.refresh_overlay_tracked_items_ui()
        self.save_overlay_settings_from_ui()

    def remove_overlay_tracked_item(self) -> None:
        rules_list = getattr(self, "overlay_tracked_rules_list", None)
        if rules_list is None or rules_list.currentRow() < 0:
            return
        rules_list.takeItem(rules_list.currentRow())
        config.OVERLAY["tracked_items"] = self._tracked_item_config_from_ui()
        config.user_config["OVERLAY"] = config.OVERLAY
        config.save_config(config.user_config)
        self.save_overlay_settings_from_ui()

    def _selected_overlay_item_name(self) -> str:
        selector = getattr(self, "overlay_item_selector", None)
        if selector is not None and selector.currentItem() is not None:
            return str(selector.currentItem().data(Qt.UserRole) or selector.currentItem().text()).strip()
        if getattr(self, "overlay_item_search_entry", None) is not None:
            query = self.overlay_item_search_entry.text().strip()
            for item_name in getattr(self, "overlay_item_names", ()):
                if item_name.lower() == query.lower():
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
        return f"{self._overlay_url_text()}/{widget_id}"

    def _set_overlay_tracked_items_expanded(self, expanded: bool) -> None:
        if getattr(self, "overlay_tracked_items_content", None) is not None:
            self.overlay_tracked_items_content.setVisible(bool(expanded))
        if getattr(self, "overlay_tracked_items_toggle_btn", None) is not None:
            self.overlay_tracked_items_toggle_btn.setText("Hide Items" if expanded else "Configure Items")

    def _set_overlay_stats_expanded(self, expanded: bool) -> None:
        if getattr(self, "overlay_stats_content", None) is not None:
            self.overlay_stats_content.setVisible(bool(expanded))
        if getattr(self, "overlay_stats_toggle_btn", None) is not None:
            self.overlay_stats_toggle_btn.setText("Hide Stats" if expanded else "Configure Stats")

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
    def _overlay_available_item_names() -> tuple[str, ...]:
        names = set(ITEM_RARITY_BY_NAME)
        for raw_name in ITEM_ENUM_NAMES_BY_ID.values():
            display_name = PlayerStatsClient._format_item_name(f"Item{raw_name}")
            if display_name:
                names.add(display_name)
        return tuple(sorted(names, key=str.lower))

    @staticmethod
    def _overlay_rule_id(item_name: str, mode: str) -> str:
        folded = "".join(char.lower() for char in item_name if char.isalnum())
        return f"{folded or 'item'}_{mode}"


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