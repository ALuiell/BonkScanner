from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from gui_shared import _set_text, _set_text_input
from live_run_tracker import DEFAULT_TRACKED_ITEM_RULES, LiveRunTracker, TrackedItemRule
from overlay_server import LocalOverlayServer, OverlayStateStore
from overlay_state import build_overlay_state


OVERLAY_WIDGET_LABELS = {
    "run_timer": "Run timer",
    "level": "Level",
    "kills": "Kills",
    "current_stage": "Current stage",
    "stage_summary": "Stage summary",
    "tracked_items": "Tracked items",
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
        self.overlay_status_label = QLabel("Overlay stopped")
        self.overlay_url_entry = QLineEdit()
        self.overlay_url_entry.setReadOnly(True)
        self.overlay_url_entry.setText(self._overlay_url_text())
        status_layout.addWidget(self.overlay_status_label)
        status_layout.addWidget(QLabel("OBS URL"))
        status_layout.addWidget(self.overlay_url_entry)

        controls = QHBoxLayout()
        self.overlay_enabled_checkbox = QCheckBox("Enable overlay server")
        self.overlay_enabled_checkbox.setChecked(bool(config.OVERLAY.get("enabled", False)))
        self.overlay_enabled_checkbox.stateChanged.connect(lambda _state: self.on_overlay_enabled_changed())
        self.overlay_start_stop_btn = QPushButton("Start")
        self.overlay_start_stop_btn.clicked.connect(self.toggle_overlay_server)
        controls.addWidget(self.overlay_enabled_checkbox)
        controls.addWidget(self.overlay_start_stop_btn)
        controls.addStretch(1)
        status_layout.addLayout(controls)
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

        tracked_group = QGroupBox("Tracked Items")
        tracked_layout = QVBoxLayout(tracked_group)
        self.overlay_tracked_items_label = QLabel("Default counter: Anvils Map 1 (observed gains during stage 1).")
        self.overlay_tracked_items_label.setWordWrap(True)
        tracked_layout.addWidget(self.overlay_tracked_items_label)
        layout.addWidget(tracked_group)

        help_label = QLabel(
            "Add the OBS URL as a Browser Source. The server binds only to 127.0.0.1 and does not use Twitch API."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        layout.addStretch(1)
        self.tabview.addTab(self.tab_overlay, "Overlay")
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
        if self.overlay_server.is_running:
            config.OVERLAY["enabled"] = False
            if self.overlay_enabled_checkbox is not None:
                self.overlay_enabled_checkbox.setChecked(False)
            self.stop_overlay_server()
        else:
            config.OVERLAY["enabled"] = True
            if self.overlay_enabled_checkbox is not None:
                self.overlay_enabled_checkbox.setChecked(True)
            self.start_overlay_server()
        config.user_config["OVERLAY"] = config.OVERLAY
        config.save_config(config.user_config)
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
            widgets.append(widget)
        overlay["widgets"] = widgets
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
        if self.overlay_start_stop_btn is not None:
            self.overlay_start_stop_btn.setText("Stop" if running else "Start")
        if self.overlay_url_entry is not None:
            _set_text_input(self.overlay_url_entry, self._overlay_url_text())
        if self.overlay_status_label is not None:
            if running:
                status = f"Overlay running | {self.live_run_tracker.status()}"
            elif server is not None and server.last_error:
                status = f"Port unavailable: {server.last_error}"
            else:
                status = "Overlay stopped"
            _set_text(self.overlay_status_label, status)

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
        return tuple(rules) or DEFAULT_TRACKED_ITEM_RULES


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