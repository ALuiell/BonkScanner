from __future__ import annotations

import html
import re
import threading
import webbrowser
from functools import partial
from pathlib import Path

from gui_shared import (
    _apply_button_icon,
    _clear_layout,
    _make_scroll_section,
    _read_bool,
    _read_text,
    _safe_float,
    _set_bool,
    build_template_payload,
    format_template_conditions,
    resource_path,
)
from gui_styles import (
    _template_color_hex,
    _template_manager_card_stylesheet,
    _template_manager_header_stylesheet,
    _tier_color,
)

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import config
import updater

PATREON_SUPPORT_URL = "https://www.patreon.com/posts/bonkscanner-158115804?source=storefront"
KOFI_SUPPORT_URL = "https://ko-fi.com/s/34dc062a82"
PATREON_ICON_PATH = "media/patreon_logo.svg"
KOFI_ICON_PATH = "media/kofi_logo.svg"

class TemplateFormFrame(QWidget):
    def __init__(self, parent=None, template_data=None):
        super().__init__(parent)
        self.template_data = template_data or {}
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.name_entry = QLineEdit()
        layout.addRow("Template Name:", self.name_entry)

        self.sm_entry = QLineEdit()
        self.shady_entry = QLineEdit()
        self.moai_entry = QLineEdit()
        self.micro_entry = QLineEdit()
        self.boss_entry = QLineEdit()

        layout.addRow("S+M Total (optional):", self.sm_entry)
        layout.addRow("Shady Guy (min):", self.shady_entry)
        layout.addRow("Moais (min):", self.moai_entry)
        layout.addRow("Microwaves (min):", self.micro_entry)
        layout.addRow("Boss Curses (min):", self.boss_entry)

        self.shady_entry.textChanged.connect(self.update_sm_total)
        self.moai_entry.textChanged.connect(self.update_sm_total)
        self.load_template(self.template_data)

    def load_template(self, template_data=None):
        self.template_data = template_data or {}
        self.name_entry.setText(self.template_data.get("name", ""))
        self.name_entry.setEnabled(self.template_data.get("id", 100) > 7)
        self.sm_entry.setText(str(self.template_data.get("sm_total", 0)))
        self.shady_entry.setText(str(self.template_data.get("shady", 0)))
        self.moai_entry.setText(str(self.template_data.get("moai", 0)))
        self.micro_entry.setText(str(self.template_data.get("micro", 0)))
        self.boss_entry.setText(str(self.template_data.get("boss", 0)))
        self.update_sm_total()

    def update_sm_total(self) -> None:
        shady = self.shady_entry.text().strip()
        moai = self.moai_entry.text().strip()
        if shady.isdigit() and moai.isdigit() and (int(shady) > 0 or int(moai) > 0):
            self.sm_entry.setPlaceholderText("Disabled while individual S/M values are set")
        else:
            self.sm_entry.setPlaceholderText("")

    def get_payload(self):
        return build_template_payload(
            self.name_entry.text(),
            self.sm_entry.text(),
            self.shady_entry.text(),
            self.moai_entry.text(),
            self.micro_entry.text(),
            self.boss_entry.text(),
            source_template=self.template_data,
        )


class TemplateDialog(QDialog):
    def __init__(self, parent=None, edit_template=None):
        super().__init__(parent)
        self.result_payload = None
        self.setWindowTitle("Edit Template" if edit_template else "Add Template")
        self.setModal(True)
        self.resize(420, 260)
        self.form = TemplateFormFrame(self, edit_template)
        layout = QVBoxLayout(self)
        layout.addWidget(self.form)
        self.save_btn = QPushButton("Save Template")
        self.save_btn.clicked.connect(self.save)
        layout.addWidget(self.save_btn)

    def save(self):
        payload = self.form.get_payload()
        if payload is None:
            QMessageBox.warning(self, "Invalid Template", "Template name cannot be empty.")
            return
        self.result_payload = payload
        self.accept()


class TemplateManagerDialog(QDialog):
    def __init__(self, parent, templates, on_save):
        super().__init__(parent)
        self.templates = [dict(template) for template in templates]
        self.on_save = on_save
        self.setWindowTitle("Manage Templates")
        self.resize(760, 760)
        self.setMinimumSize(640, 560)
        self.expanded_template_id: int | None = None
        self.card_widgets: dict[int, dict[str, object]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        header = QLabel("Templates")
        header.setObjectName("SectionHeader")
        layout.addWidget(header)

        subtitle = QLabel("Select a template from the list, and its settings will appear directly below the card.")
        subtitle.setStyleSheet("color: #AAB4C4;")
        layout.addWidget(subtitle)

        self.scroll, self.scroll_content, self.scroll_layout = _make_scroll_section()
        layout.addWidget(self.scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self.build_cards()

    def build_cards(self):
        _clear_layout(self.scroll_layout)
        self.card_widgets.clear()
        for template in self.templates:
            template_id = int(template.get("id", 0))
            color_hex = _template_color_hex(template)
            card = QFrame()
            card.setObjectName("TemplateManagerCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(10)

            header_btn = QPushButton(f"▶ {template['name']}")
            header_btn.setCursor(Qt.PointingHandCursor)
            header_btn.setStyleSheet(_template_manager_header_stylesheet(color_hex))
            header_btn.clicked.connect(partial(self.toggle_template, template_id))
            card_layout.addWidget(header_btn)

            meta_text = format_template_conditions(template)
            if template.get("id", 100) <= 7:
                meta_text += "  •  Built-in"
            meta_label = QLabel(meta_text)
            meta_label.setStyleSheet("color: #C5CEDB;")
            card_layout.addWidget(meta_label)

            details = QFrame()
            details_layout = QVBoxLayout(details)
            details_layout.setContentsMargins(0, 8, 0, 0)
            details_layout.setSpacing(12)
            form = TemplateFormFrame(details, template)
            details_layout.addWidget(form)

            save_row = QHBoxLayout()
            save_row.addStretch(1)
            save_btn = QPushButton("Save")
            save_btn.setObjectName("SuccessButton")
            save_btn.clicked.connect(partial(self.save_template, template_id, form))
            save_row.addWidget(save_btn)
            details_layout.addLayout(save_row)
            details.setVisible(False)
            card_layout.addWidget(details)

            self.card_widgets[template_id] = {
                "card": card,
                "header_btn": header_btn,
                "details": details,
                "template": template,
                "form": form,
                "color_hex": color_hex,
            }
            self._apply_card_state(template_id, expanded=template_id == self.expanded_template_id)
            self.scroll_layout.addWidget(card)
        self.scroll_layout.addStretch(1)

    def _apply_card_state(self, template_id: int, *, expanded: bool) -> None:
        widgets = self.card_widgets.get(template_id)
        if widgets is None:
            return

        template = widgets["template"]
        header_btn = widgets["header_btn"]
        details = widgets["details"]
        color_hex = str(widgets["color_hex"])
        header_btn.setText(f"{'▼' if expanded else '▶'} {template['name']}")
        details.setVisible(expanded)
        widgets["card"].setStyleSheet(_template_manager_card_stylesheet(color_hex, expanded))

    def toggle_template(self, template_id: int) -> None:
        if self.expanded_template_id == template_id:
            self._apply_card_state(template_id, expanded=False)
            self.expanded_template_id = None
            return

        if self.expanded_template_id is not None:
            self._apply_card_state(self.expanded_template_id, expanded=False)

        self.expanded_template_id = template_id
        self._apply_card_state(template_id, expanded=True)

    def save_template(self, template_id: int, form: TemplateFormFrame):
        payload = form.get_payload()
        if payload is None:
            QMessageBox.warning(self, "Invalid Template", "Template name cannot be empty.")
            return

        template = next((item for item in self.templates if int(item.get("id", 0)) == template_id), None)
        if template is None:
            return

        payload["id"] = template.get("id")
        original_name = template.get("name")
        if callable(self.on_save) and not self.on_save(template, payload):
            return

        for index, existing in enumerate(self.templates):
            if int(existing.get("id", 0)) == template_id:
                self.templates[index] = payload
                break

        self.expanded_template_id = None
        self.build_cards()


class ScoresSettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Scores Settings")
        self.resize(460, 560)
        self.setModal(True)
        self.active_tier_checks: dict[str, QCheckBox] = {}
        self.threshold_entries: dict[str, QLineEdit] = {}
        self.weight_entries: dict[str, QLineEdit] = {}
        self.multiplier_entries: dict[str, QLineEdit] = {}

        outer = QVBoxLayout(self)
        scroll, scroll_content, scroll_layout = _make_scroll_section()
        outer.addWidget(scroll, 1)

        active_group = QGroupBox("Active Tiers")
        active_layout = QVBoxLayout(active_group)
        for tier in ("Light", "Good", "Perfect", "Perfect+"):
            cb = QCheckBox(tier)
            cb.setChecked(tier in config.SCORES_SYSTEM.get("active_tiers", []))
            cb.setStyleSheet(f"color: {_tier_color(tier)}; font-weight: 700;")
            self.active_tier_checks[tier] = cb
            active_layout.addWidget(cb)
        scroll_layout.addWidget(active_group)

        threshold_group = QGroupBox("Thresholds")
        threshold_layout = QGridLayout(threshold_group)
        self.manual_thresholds_var = QCheckBox("Manual Thresholds")
        self.manual_thresholds_var.setChecked(bool(config.SCORES_SYSTEM.get("manual_thresholds", False)))
        self.manual_thresholds_var.toggled.connect(self.toggle_thresholds_mode)
        threshold_layout.addWidget(self.manual_thresholds_var, 0, 0, 1, 2)
        for row, tier in enumerate(("Light", "Good", "Perfect", "Perfect+"), start=1):
            threshold_layout.addWidget(QLabel(f"{tier}:"), row, 0)
            entry = QLineEdit(str(config.SCORES_SYSTEM.get("thresholds", {}).get(tier, 0)))
            self.threshold_entries[tier] = entry
            threshold_layout.addWidget(entry, row, 1)
        scroll_layout.addWidget(threshold_group)

        weight_group = QGroupBox("Weights")
        weight_layout = QFormLayout(weight_group)
        for key in ("moais", "shady", "boss", "magnet"):
            entry = QLineEdit(str(config.SCORES_SYSTEM.get("weights", {}).get(key, 0)))
            self.weight_entries[key] = entry
            weight_layout.addRow(f"{key.capitalize()}:", entry)
        scroll_layout.addWidget(weight_group)

        multiplier_group = QGroupBox("Microwave Multipliers")
        multiplier_layout = QFormLayout(multiplier_group)
        for key in ("1", "2"):
            entry = QLineEdit(str(config.SCORES_SYSTEM.get("multipliers", {}).get("microwave", {}).get(key, 1.0)))
            self.multiplier_entries[key] = entry
            multiplier_layout.addRow(f"{key} Microwave(s):", entry)
        scroll_layout.addWidget(multiplier_group)

        button_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setObjectName("DangerButton")
        reset_btn.clicked.connect(self.reset_to_defaults)
        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("SuccessButton")
        save_btn.clicked.connect(self.save)
        button_row.addWidget(reset_btn)
        button_row.addStretch(1)
        button_row.addWidget(save_btn)
        scroll_layout.addLayout(button_row)
        scroll_layout.addStretch(1)
        self.toggle_thresholds_mode()

    def reset_to_defaults(self):
        defaults = config.DEFAULT_SCORES_SYSTEM
        self.manual_thresholds_var.setChecked(bool(defaults.get("manual_thresholds", False)))
        for tier, cb in self.active_tier_checks.items():
            cb.setChecked(tier in defaults.get("active_tiers", []))
        for tier, entry in self.threshold_entries.items():
            entry.setText(str(defaults.get("thresholds", {}).get(tier, 0.0)))
        for key, entry in self.weight_entries.items():
            entry.setText(str(defaults.get("weights", {}).get(key, 0.0)))
        for key, entry in self.multiplier_entries.items():
            entry.setText(str(defaults.get("multipliers", {}).get("microwave", {}).get(key, 1.0)))
        self.toggle_thresholds_mode()

    def auto_update_thresholds(self):
        thresholds = config.calculate_auto_thresholds(
            {key: _safe_float(entry.text(), 0.0) for key, entry in self.weight_entries.items()},
            {"microwave": {key: _safe_float(entry.text(), 1.0) for key, entry in self.multiplier_entries.items()}},
        )
        for tier, entry in self.threshold_entries.items():
            entry.setText(str(thresholds.get(tier, 0.0)))

    def toggle_thresholds_mode(self):
        manual = self.manual_thresholds_var.isChecked()
        if not manual:
            self.auto_update_thresholds()
        for entry in self.threshold_entries.values():
            entry.setEnabled(manual)

    def save(self):
        active_tiers = [tier for tier, cb in self.active_tier_checks.items() if cb.isChecked()]
        if not active_tiers:
            QMessageBox.warning(self, "Invalid Settings", "At least one score tier must stay active.")
            return

        scores_system = {
            "manual_thresholds": self.manual_thresholds_var.isChecked(),
            "base_target_score": config.SCORES_SYSTEM.get("base_target_score", 30.0),
            "weights": {key: _safe_float(entry.text(), 0.0) for key, entry in self.weight_entries.items()},
            "multipliers": {
                "microwave": {key: _safe_float(entry.text(), 1.0) for key, entry in self.multiplier_entries.items()},
            },
            "thresholds": {tier: _safe_float(entry.text(), 0.0) for tier, entry in self.threshold_entries.items()},
            "active_tiers": active_tiers,
        }

        if not scores_system["manual_thresholds"]:
            scores_system["thresholds"] = config.calculate_auto_thresholds(
                scores_system["weights"],
                scores_system["multipliers"],
            )

        config.SCORES_SYSTEM = scores_system
        config.user_config["SCORES_SYSTEM"] = scores_system
        config.save_config(config.user_config)
        self.accept()


class DeleteDialog(QDialog):
    def __init__(self, parent, custom_templates):
        super().__init__(parent)
        self.custom_templates = custom_templates
        self.checks: dict[int, QCheckBox] = {}
        self.setWindowTitle("Delete Templates")
        self.resize(320, 280)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select templates to delete:"))
        scroll, _content, scroll_layout = _make_scroll_section()
        layout.addWidget(scroll, 1)
        for template in custom_templates:
            cb = QCheckBox(template["name"])
            self.checks[template["id"]] = cb
            scroll_layout.addWidget(cb)
        scroll_layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        delete_btn = QPushButton("Delete Selected")
        delete_btn.setObjectName("DangerButton")
        buttons.addButton(delete_btn, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject)
        delete_btn.clicked.connect(self.delete)
        layout.addWidget(buttons)

    def delete(self):
        to_delete = {template_id for template_id, cb in self.checks.items() if cb.isChecked()}
        if not to_delete:
            self.reject()
            return
        config.TEMPLATES = [t for t in config.TEMPLATES if t.get("id") not in to_delete]
        config.user_config["TEMPLATES"] = config.TEMPLATES
        config.ACTIVE_TEMPLATES = [
            name for name in config.ACTIVE_TEMPLATES
            if name in {template["name"] for template in config.TEMPLATES}
        ]
        config.user_config["ACTIVE_TEMPLATES"] = config.ACTIVE_TEMPLATES
        config.save_config(config.user_config)
        self.accept()


class ConfirmDeleteRecordingDialog(QDialog):
    def __init__(self, parent, recording_name: str):
        super().__init__(parent)
        self.result = False
        self.setWindowTitle("Delete Recording")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Delete recording '{recording_name}'?"))
        buttons = QDialogButtonBox()
        cancel_btn = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        confirm_btn = buttons.addButton("Delete", QDialogButtonBox.AcceptRole)
        confirm_btn.setObjectName("DangerButton")
        cancel_btn.clicked.connect(self.cancel)
        confirm_btn.clicked.connect(self.confirm)
        layout.addWidget(buttons)

    def confirm(self):
        self.result = True
        self.accept()

    def cancel(self):
        self.result = False
        self.reject()


class CleanupRecordingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.threshold: int | None = None
        self.setWindowTitle("Clean Recordings")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Remove all recordings where snapshot count is less than:"))
        self.threshold_entry = QLineEdit("2")
        layout.addWidget(self.threshold_entry)
        buttons = QDialogButtonBox()
        cancel_btn = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        confirm_btn = buttons.addButton("Remove", QDialogButtonBox.AcceptRole)
        confirm_btn.setObjectName("DangerButton")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn.clicked.connect(self.confirm)
        layout.addWidget(buttons)

    def confirm(self):
        try:
            threshold = int(float(_read_text(self.threshold_entry)))
        except ValueError:
            QMessageBox.warning(self, "Invalid Count", "Please enter a valid snapshot count.")
            return
        if threshold < 0:
            QMessageBox.warning(self, "Invalid Count", "Snapshot count cannot be negative.")
            return
        self.threshold = threshold
        self.accept()


class NativeHookWarningDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = False
        self.setWindowTitle("Native Hook Warning")
        self.setModal(True)
        self.resize(525, 355)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("WarningCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 14)
        card_layout.setSpacing(8)

        title = QLabel("Enable Native Hook Restart?")
        title.setObjectName("WarningTitle")
        card_layout.addWidget(title)

        summary = QLabel(
            "This enables a lower-level memory restart path. Using this mode\n"
            "may not be considered entirely fair and could have consequences."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("background: transparent; font-size: 15px;")
        card_layout.addWidget(summary)
        layout.addWidget(card)

        switch_note = QLabel(
            "You can safely switch back to standard keyboard restart at any time\n"
            "from Settings."
        )
        switch_note.setWordWrap(True)
        switch_note.setStyleSheet("font-size: 15px;")
        layout.addWidget(switch_note)

        repeat_note = QLabel("This dialog will appear whenever the native hook option is turned on.")
        repeat_note.setWordWrap(True)
        repeat_note.setStyleSheet("font-size: 15px;")
        layout.addWidget(repeat_note)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(20)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("DangerButton")
        cancel_btn.setProperty("class", "WideDialogButton")
        cancel_btn.setMinimumHeight(34)
        continue_btn = QPushButton("Continue")
        continue_btn.setObjectName("SuccessButton")
        continue_btn.setProperty("class", "WideDialogButton")
        continue_btn.setMinimumHeight(34)
        cancel_btn.clicked.connect(self.cancel)
        continue_btn.clicked.connect(self.confirm)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(continue_btn)
        layout.addLayout(buttons)

    def confirm(self):
        self.result = True
        self.accept()

    def cancel(self):
        self.result = False
        self.reject()


class HelpDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("BonkScanner Help")
        self.resize(700, 620)
        self.setMinimumSize(560, 420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Quick Help")
        title.setObjectName("SectionHeader")
        layout.addWidget(title)

        subtitle = QLabel(
            "Practical notes for BonkScanner's main features, common workflows, and non-obvious behavior."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #AAB4C4;")
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.addTab(self._build_language_tab("docs/help/help_eng.txt", self._fallback_eng_text()), "ENG")
        tabs.addTab(self._build_language_tab("docs/help/help_ukr.txt", self._fallback_ukr_text()), "UA")
        tabs.addTab(self._build_language_tab("docs/help/help_ru.txt", self._fallback_ru_text()), "RU")
        layout.addWidget(tabs, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _build_language_tab(self, relative_path: str, fallback_text: str) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)

        content = QTextEdit()
        content.setReadOnly(True)
        content.setHtml(self._render_help_html(self._load_help_text(relative_path, fallback_text)))
        layout.addWidget(content)
        return tab

    @staticmethod
    def _load_help_text(relative_path: str, fallback_text: str) -> str:
        help_path = Path(resource_path(relative_path))
        try:
            return help_path.read_text(encoding="utf-8")
        except OSError:
            return fallback_text

    @staticmethod
    def _render_help_html(text: str) -> str:
        lines = text.splitlines()
        parts = [
            "<div style='font-size:13px; line-height:1.5; color:#DCE4EF;'>",
        ]
        in_list = False
        in_numbered_list = False

        def close_lists() -> None:
            nonlocal in_list, in_numbered_list
            if in_list:
                parts.append("</ul>")
                in_list = False
            if in_numbered_list:
                parts.append("</ol>")
                in_numbered_list = False

        for index, raw_line in enumerate(lines):
            line = raw_line.rstrip()
            stripped = line.strip()
            next_line = lines[index + 1].rstrip() if index + 1 < len(lines) else ""

            if not stripped:
                close_lists()
                parts.append("<div style='height:8px;'></div>")
                continue

            if set(stripped) == {"="} or set(stripped) == {"-"}:
                continue

            escaped = HelpDialog._format_inline_help_text(stripped)

            if next_line and set(next_line.strip()) == {"="}:
                close_lists()
                parts.append(
                    f"<h2 style='color:#F3F4F6; margin:0 0 10px 0; font-size:20px;'>{escaped}</h2>"
                )
                continue

            if next_line and set(next_line.strip()) == {"-"}:
                close_lists()
                parts.append(
                    f"<h3 style='color:#D7BF72; margin:10px 0 6px 0; font-size:16px;'>{escaped}</h3>"
                )
                continue

            if stripped.startswith("- "):
                if in_numbered_list:
                    parts.append("</ol>")
                    in_numbered_list = False
                if not in_list:
                    parts.append("<ul style='margin:2px 0 10px 18px; padding-left:12px;'>")
                    in_list = True
                parts.append(f"<li style='margin-bottom:4px;'>{HelpDialog._format_inline_help_text(stripped[2:])}</li>")
                continue

            if re.match(r"^\d+\.\s+", stripped):
                if in_list:
                    parts.append("</ul>")
                    in_list = False
                if not in_numbered_list:
                    parts.append("<ol style='margin:2px 0 10px 18px; padding-left:12px;'>")
                    in_numbered_list = True
                item_text = re.sub(r"^\d+\.\s+", "", stripped, count=1)
                parts.append(f"<li style='margin-bottom:4px;'>{HelpDialog._format_inline_help_text(item_text)}</li>")
                continue

            close_lists()
            parts.append(f"<p style='margin:0 0 8px 0;'>{escaped}</p>")

        close_lists()
        parts.append("</div>")
        return "".join(parts)

    @staticmethod
    def _format_inline_help_text(text: str) -> str:
        escaped = html.escape(text)
        return re.sub(
            r"`([^`]+)`",
            r"<span style='background:#162133; color:#B9D9FF; border:1px solid #29415A; border-radius:4px; padding:1px 4px;'>\1</span>",
            escaped,
        )

    @staticmethod
    def _fallback_ru_text() -> str:
        return "Файл справки не найден.\n\nПроверьте наличие docs/help/help_ru.txt рядом с приложением."

    @staticmethod
    def _fallback_eng_text() -> str:
        return "Help file not found.\n\nPlease check that docs/help/help_eng.txt is present next to the application."

    @staticmethod
    def _fallback_ukr_text() -> str:
        return "Файл довідки не знайдено.\n\nПеревірте, що docs/help/help_ukr.txt знаходиться поруч із застосунком."


class SettingsDialog(QDialog):
    def __init__(self, parent, master=None):
        super().__init__(parent)
        self.master = master or parent
        self._native_hook_toggle_guard = False
        self.setWindowTitle("Settings")
        self.resize(440, 380)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(14)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form_layout.setFormAlignment(Qt.AlignTop)
        form_layout.setHorizontalSpacing(18)
        form_layout.setVerticalSpacing(14)
        layout.addLayout(form_layout)

        self.hotkey_entry = QLineEdit(config.HOTKEY)
        form_layout.addRow("Scan Hotkey:", self.hotkey_entry)

        self.reset_hotkey_entry = QLineEdit(config.RESET_HOTKEY)
        form_layout.addRow("Reset Hotkey:", self.reset_hotkey_entry)

        self.record_hotkey_entry = QLineEdit(getattr(config, "PLAYER_STATS_RECORD_HOTKEY", "f8"))
        form_layout.addRow("Record Hotkey:", self.record_hotkey_entry)

        self.toggle_skip_chest_animation_hotkey_entry = QLineEdit(
            getattr(config, "TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY", "f11")
        )
        self.toggle_auto_select_upgrades_hotkey_entry = QLineEdit(
            getattr(config, "TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY", "f10")
        )
        self.toggle_particles_opacity_hotkey_entry = QLineEdit(
            getattr(config, "TOGGLE_PARTICLES_OPACITY_HOTKEY", "f7")
        )
        form_layout.addRow("Toggle Chest Skip Hotkey:", self.toggle_skip_chest_animation_hotkey_entry)
        form_layout.addRow("Toggle Auto Level-Up Hotkey:", self.toggle_auto_select_upgrades_hotkey_entry)
        form_layout.addRow("Toggle Particles Opacity Hotkey:", self.toggle_particles_opacity_hotkey_entry)

        self.min_delay_entry = QLineEdit(str(config.MIN_DELAY))
        self.map_load_delay_entry = self.min_delay_entry
        form_layout.addRow("Min Reroll Delay (s):", self.min_delay_entry)

        self.reset_hold_duration_entry = QLineEdit(str(config.RESET_HOLD_DURATION))
        form_layout.addRow("Reset Hold Duration (s):", self.reset_hold_duration_entry)

        self.record_interval_entry = QLineEdit(str(getattr(config, "PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30)))
        form_layout.addRow("Snapshot Interval (s):", self.record_interval_entry)

        self.auto_start_recording_var = QCheckBox("Auto-start recording")
        self.auto_start_recording_var.setChecked(bool(getattr(config, "AUTO_START_RECORDING", False)))
        layout.addWidget(self.auto_start_recording_var)

        self.native_hook_enabled_var = QCheckBox("Use native hook restart")
        self.native_hook_enabled_var.setChecked(bool(getattr(config, "NATIVE_HOOK_ENABLED", True)))
        self.native_hook_enabled_var.toggled.connect(self.on_native_hook_toggle)
        layout.addWidget(self.native_hook_enabled_var)

        button_row = QVBoxLayout()
        button_row.setSpacing(10)
        self.update_btn = QPushButton("Check for Updates")
        self.update_btn.clicked.connect(self.check_update)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("SuccessButton")
        self.save_btn.clicked.connect(self.save)
        button_row.addWidget(self.update_btn)
        button_row.addWidget(self.save_btn)
        layout.addLayout(button_row)

        layout.addSpacing(6)

        support_divider = QFrame()
        support_divider.setObjectName("SupportDivider")
        support_divider.setFrameShape(QFrame.HLine)
        support_divider.setFrameShadow(QFrame.Plain)
        layout.addWidget(support_divider)

        support_label = QLabel("Support")
        support_label.setObjectName("SupportSectionLabel")
        support_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(support_label)

        support_note = QLabel(
            "BonkScanner is free to download here. "
            "If you want, you can also support the project."
        )
        support_note.setObjectName("SupportSectionNote")
        support_note.setAlignment(Qt.AlignCenter)
        support_note.setWordWrap(True)
        layout.addWidget(support_note)

        support_button_row = QHBoxLayout()
        support_button_row.setSpacing(10)
        support_button_row.setAlignment(Qt.AlignHCenter)
        self.patreon_btn = QPushButton("Patreon")
        self.patreon_btn.setObjectName("PatreonButton")
        self.patreon_btn.setIcon(QIcon(resource_path(PATREON_ICON_PATH)))
        self.patreon_btn.setIconSize(QSize(18, 18))
        self.patreon_btn.clicked.connect(self.open_patreon_support_page)
        self.patreon_btn.setProperty("class", "SupportPlatformButton")
        self.kofi_btn = QPushButton("Ko-fi")
        self.kofi_btn.setObjectName("KofiButton")
        self.kofi_btn.setIcon(QIcon(resource_path(KOFI_ICON_PATH)))
        self.kofi_btn.setIconSize(QSize(18, 18))
        self.kofi_btn.clicked.connect(self.open_kofi_support_page)
        self.kofi_btn.setProperty("class", "SupportPlatformButton")
        self._sync_support_button_sizes()
        support_button_row.addWidget(self.patreon_btn)
        support_button_row.addWidget(self.kofi_btn)
        layout.addLayout(support_button_row)

    def _set_native_hook_checkbox_value(self, enabled: bool):
        self._native_hook_toggle_guard = True
        try:
            _set_bool(self.native_hook_enabled_var, enabled)
        finally:
            self._native_hook_toggle_guard = False

    def _sync_support_button_sizes(self):
        buttons = [self.patreon_btn, self.kofi_btn]
        target_width = max(button.sizeHint().width() for button in buttons)
        for button in buttons:
            button.setFixedWidth(target_width)
            button.setFixedHeight(26)

    def prompt_native_hook_enable_confirmation(self) -> bool:
        dialog = NativeHookWarningDialog(self)
        dialog.exec()
        return bool(dialog.result)

    def on_native_hook_toggle(self):
        if getattr(self, "_native_hook_toggle_guard", False):
            return
        if not _read_bool(self.native_hook_enabled_var):
            return
        if not SettingsDialog.prompt_native_hook_enable_confirmation(self):
            SettingsDialog._set_native_hook_checkbox_value(self, False)

    def check_update(self):
        threading.Thread(target=updater.check_and_update, args=(self.master, True), daemon=True).start()
        if hasattr(self, "close"):
            self.close()

    def open_patreon_support_page(self):
        webbrowser.open(PATREON_SUPPORT_URL)

    def open_kofi_support_page(self):
        webbrowser.open(KOFI_SUPPORT_URL)

    def save(self):
        new_hotkey = _read_text(self.hotkey_entry).strip()
        new_reset_hotkey = _read_text(self.reset_hotkey_entry).strip()
        new_record_hotkey = _read_text(self.record_hotkey_entry).strip()
        new_toggle_skip_chest_animation_hotkey = _read_text(self.toggle_skip_chest_animation_hotkey_entry).strip()
        new_toggle_auto_select_upgrades_hotkey = _read_text(self.toggle_auto_select_upgrades_hotkey_entry).strip()
        new_toggle_particles_opacity_hotkey = _read_text(self.toggle_particles_opacity_hotkey_entry).strip()
        auto_start_recording = _read_bool(self.auto_start_recording_var)
        native_hook_enabled = _read_bool(self.native_hook_enabled_var)

        config.user_config["HOTKEY"] = new_hotkey
        config.user_config["RESET_HOTKEY"] = new_reset_hotkey
        config.user_config["PLAYER_STATS_RECORD_HOTKEY"] = new_record_hotkey
        config.user_config["TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY"] = new_toggle_skip_chest_animation_hotkey
        config.user_config["TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY"] = new_toggle_auto_select_upgrades_hotkey
        config.user_config["TOGGLE_PARTICLES_OPACITY_HOTKEY"] = new_toggle_particles_opacity_hotkey
        config.user_config["AUTO_START_RECORDING"] = auto_start_recording
        config.user_config["NATIVE_HOOK_ENABLED"] = native_hook_enabled

        config.HOTKEY = new_hotkey
        config.RESET_HOTKEY = new_reset_hotkey
        config.PLAYER_STATS_RECORD_HOTKEY = new_record_hotkey
        config.TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY = new_toggle_skip_chest_animation_hotkey
        config.TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY = new_toggle_auto_select_upgrades_hotkey
        config.TOGGLE_PARTICLES_OPACITY_HOTKEY = new_toggle_particles_opacity_hotkey
        config.AUTO_START_RECORDING = auto_start_recording
        config.NATIVE_HOOK_ENABLED = native_hook_enabled

        delay_entry = getattr(self, "min_delay_entry", None) or getattr(self, "map_load_delay_entry", None)
        try:
            new_delay = float(_read_text(delay_entry))
            config.user_config["MIN_DELAY"] = new_delay
            config.MIN_DELAY = new_delay
            config.MAP_LOAD_DELAY = new_delay
        except ValueError:
            pass

        try:
            new_duration = float(_read_text(self.reset_hold_duration_entry))
            if new_duration < 0.01:
                new_duration = 0.01
            config.user_config["RESET_HOLD_DURATION"] = new_duration
            config.RESET_HOLD_DURATION = new_duration
            game_val = round(new_duration - 0.05, 2)
            if game_val < 0.01:
                game_val = 0.01
            config.update_game_reset_time(game_val)
        except ValueError:
            pass

        try:
            new_interval = max(1, int(float(_read_text(self.record_interval_entry))))
            config.user_config["PLAYER_STATS_RECORD_INTERVAL_SECONDS"] = new_interval
            config.PLAYER_STATS_RECORD_INTERVAL_SECONDS = new_interval
            if hasattr(self.master, "player_stats_vod_recorder") and self.master.player_stats_vod_recorder is not None:
                self.master.player_stats_vod_recorder.interval_seconds = new_interval
        except ValueError:
            pass

        config.save_config(config.user_config)

        if hasattr(self.master, "setup_hotkeys"):
            self.master.setup_hotkeys()
            if hasattr(self.master, "refresh_player_stats_timeline_ui"):
                self.master.refresh_player_stats_timeline_ui(update_slider=False)
            self.master.update_status_ui()
            if hasattr(self.master, "apply_run_control_mode"):
                self.master.apply_run_control_mode()
            self.master.log("[*] Settings saved and applied successfully!", tag="success")

        if hasattr(self, "accept"):
            self.accept()
        elif hasattr(self, "destroy"):
            self.destroy()
