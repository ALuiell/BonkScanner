from __future__ import annotations

import html
import re
import threading
import webbrowser
from functools import partial
from pathlib import Path

from gui_shared import (
    TRACKED_ITEM_LIST_HEIGHT,
    CollapsibleSection,
    CollapsibleSectionGroup,
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
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSpinBox,
    QDoubleSpinBox,
)
from item_metadata import available_item_display_names, preferred_item_display_name
from player_stats import PLAYER_STAT_GROUPS

import config
import updater

PATREON_SUPPORT_URL = config.PATREON_SUPPORT_URL
KOFI_SUPPORT_URL = config.KOFI_SUPPORT_URL
GITHUB_REPOSITORY_URL = config.GITHUB_REPOSITORY_URL
DISCORD_SUPPORT_URL = config.DISCORD_SUPPORT_URL
PATREON_ICON_PATH = "media/patreon_logo.svg"
KOFI_ICON_PATH = "media/kofi_logo.svg"
GITHUB_ICON_PATH = "media/github_logo.svg"
DISCORD_ICON_PATH = "media/discord_logo.svg"

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
    def __init__(
        self,
        parent,
        *,
        title_text: str = "Enable Native Hook Restart?",
        summary_text: str | None = None,
        switch_text: str | None = None,
        repeat_text: str = "This dialog will appear whenever the native hook option is turned on.",
    ):
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

        title = QLabel(title_text)
        title.setObjectName("WarningTitle")
        card_layout.addWidget(title)

        summary = QLabel(
            summary_text
            or (
                "This enables a lower-level memory restart path. Using this mode\n"
                "may not be considered entirely fair and could have consequences."
            )
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("background: transparent; font-size: 15px;")
        card_layout.addWidget(summary)
        layout.addWidget(card)

        switch_note = QLabel(
            switch_text
            or (
                "You can safely switch back to standard keyboard restart at any time\n"
                "from Settings."
            )
        )
        switch_note.setWordWrap(True)
        switch_note.setStyleSheet("font-size: 15px;")
        layout.addWidget(switch_note)

        repeat_note = QLabel(repeat_text)
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


class RerollWarningDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = False
        self.dont_show_again = False
        self.setWindowTitle("Auto-Reroll Confirmation")
        self.setModal(True)
        self.resize(540, 310)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("WarningCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 14)
        card_layout.setSpacing(8)

        title = QLabel("Confirm Auto-Reroll Start")
        title.setObjectName("WarningTitle")
        card_layout.addWidget(title)

        summary = QLabel(
            "This button is only required for the Auto-Reroll map mode. Pressing OK will launch the automatic loop to monitor your runs and execute restarts until a matching target map is found.<br><br>"
            "For more details, please open the Help (?)."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("background: transparent; font-size: 15px;")
        card_layout.addWidget(summary)
        layout.addWidget(card)

        switch_note = QLabel(
            "Note: All other background features (Live Stats, VOD recordings, and the OBS Overlay) "
            "work fully automatically and do NOT require starting this loop."
        )
        switch_note.setWordWrap(True)
        switch_note.setStyleSheet("font-size: 14px; color: #9CA3AF;")
        layout.addWidget(switch_note)
        layout.addStretch(1)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        self.checkbox = QCheckBox("Don't show this again")
        self.checkbox.setStyleSheet("color: #F3F4F6; font-size: 14px;")
        bottom_row.addWidget(self.checkbox)

        bottom_row.addStretch(1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("DangerButton")
        cancel_btn.setProperty("class", "WideDialogButton")
        cancel_btn.setMinimumHeight(32)
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.cancel)

        confirm_btn = QPushButton("OK")
        confirm_btn.setObjectName("SuccessButton")
        confirm_btn.setProperty("class", "WideDialogButton")
        confirm_btn.setMinimumHeight(32)
        confirm_btn.setMinimumWidth(100)
        confirm_btn.clicked.connect(self.confirm)

        bottom_row.addWidget(cancel_btn)
        bottom_row.addWidget(confirm_btn)
        layout.addLayout(bottom_row)

    def confirm(self):
        self.result = True
        self.dont_show_again = self.checkbox.isChecked()
        self.accept()

    def cancel(self):
        self.result = False
        self.dont_show_again = False
        self.reject()


class ObsRecordingReminderDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("OBS Recording Reminder")
        self.setModal(True)
        self.resize(500, 245)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("WarningCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 14)
        card_layout.setSpacing(8)

        title = QLabel("OBS Recording Reminder")
        title.setObjectName("WarningTitle")
        card_layout.addWidget(title)

        summary = QLabel(
            "If this run is for leaderboard verification or YouTube, make sure OBS recording is started before beginning the run."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("background: transparent; font-size: 15px;")
        card_layout.addWidget(summary)
        layout.addWidget(card)

        note = QLabel("This reminder can be switched off at any time from Settings.")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 14px; color: #9CA3AF;")
        layout.addWidget(note)
        layout.addStretch(1)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("SuccessButton")
        ok_btn.setProperty("class", "WideDialogButton")
        ok_btn.setMinimumHeight(32)
        ok_btn.setMinimumWidth(100)
        ok_btn.clicked.connect(self.accept)
        bottom_row.addWidget(ok_btn)
        layout.addLayout(bottom_row)


class TwitchCommandsHelpDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.dont_show_again = False
        self.setWindowTitle("Twitch Command Aliases")
        self.setModal(True)
        self.resize(500, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(16)

        card = QFrame()
        card.setObjectName("WarningCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 14)
        card_layout.setSpacing(10)

        title = QLabel("!bonkhelp aliases")
        title.setObjectName("WarningTitle")
        card_layout.addWidget(title)

        summary = QLabel(
            "The command that lists enabled BonkScanner Twitch commands has several aliases. "
            "They all produce the same response, so viewers can use whichever one they prefer:"
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("background: transparent; font-size: 14px;")
        card_layout.addWidget(summary)

        aliases = QLabel(
            "<b>!bonkhelp</b><br>"
            "<b>!bonkcmds</b><br>"
            "<b>!bonkcommands</b><br>"
            "<b>!bhelp</b>"
        )
        aliases.setTextFormat(Qt.RichText)
        aliases.setStyleSheet("font-size: 15px;")
        card_layout.addWidget(aliases)
        layout.addWidget(card)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        self.checkbox = QCheckBox("Don't show this again")
        bottom_row.addWidget(self.checkbox)
        bottom_row.addStretch(1)

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("SuccessButton")
        ok_btn.setProperty("class", "WideDialogButton")
        ok_btn.setMinimumHeight(32)
        ok_btn.setMinimumWidth(100)
        ok_btn.clicked.connect(self.confirm)
        bottom_row.addWidget(ok_btn)
        layout.addLayout(bottom_row)

    def confirm(self):
        self.dont_show_again = self.checkbox.isChecked()
        self.accept()


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
        self._native_hook_hotkeys_toggle_guard = False
        self.setWindowTitle("Settings")
        self.resize(440, 420)
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

        self.min_delay_entry = QDoubleSpinBox()
        self.min_delay_entry.setRange(0.0, 60.0)
        self.min_delay_entry.setSingleStep(0.1)
        self.min_delay_entry.setDecimals(2)
        self.min_delay_entry.setValue(float(config.MIN_DELAY))
        self.min_delay_entry.setSuffix(" s")
        self.map_load_delay_entry = self.min_delay_entry
        form_layout.addRow("Min Reroll Delay (s):", self.min_delay_entry)

        self.reset_hold_duration_entry = QDoubleSpinBox()
        self.reset_hold_duration_entry.setRange(0.01, 10.0)
        self.reset_hold_duration_entry.setSingleStep(0.05)
        self.reset_hold_duration_entry.setDecimals(2)
        self.reset_hold_duration_entry.setValue(float(config.RESET_HOLD_DURATION))
        self.reset_hold_duration_entry.setSuffix(" s")
        form_layout.addRow("Reset Hold Duration (s):", self.reset_hold_duration_entry)

        self.record_interval_entry = QSpinBox()
        self.record_interval_entry.setRange(1, 3600)
        self.record_interval_entry.setSingleStep(5)
        self.record_interval_entry.setValue(int(getattr(config, "PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30)))
        self.record_interval_entry.setSuffix(" s")
        form_layout.addRow("Snapshot Interval (s):", self.record_interval_entry)

        self.auto_start_recording_var = QCheckBox("Auto-start recording")
        self.auto_start_recording_var.setChecked(bool(getattr(config, "AUTO_START_RECORDING", False)))
        layout.addWidget(self.auto_start_recording_var)

        self.show_obs_reminder_on_start_scanner_var = QCheckBox("Show OBS reminder on Start Scanner")
        self.show_obs_reminder_on_start_scanner_var.setChecked(
            bool(getattr(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False))
        )
        layout.addWidget(self.show_obs_reminder_on_start_scanner_var)

        self.native_hook_enabled_var = QCheckBox("Use native hook restart")
        self.native_hook_enabled_var.setChecked(bool(getattr(config, "NATIVE_HOOK_ENABLED", True)))
        self.native_hook_enabled_var.toggled.connect(self.on_native_hook_toggle)
        layout.addWidget(self.native_hook_enabled_var)

        self.native_hook_hotkeys_enabled_var = QCheckBox("Use hook for game toggles")
        self.native_hook_hotkeys_enabled_var.setChecked(
            bool(getattr(config, "NATIVE_HOOK_GAME_SETTING_HOTKEYS_ENABLED", False))
        )
        self.native_hook_hotkeys_enabled_var.toggled.connect(self.on_native_hook_hotkeys_toggle)
        layout.addWidget(self.native_hook_hotkeys_enabled_var)

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
            "You can also support the project. For feedback, bugs, "
            "or ideas, use GitHub or Discord."
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
        self.github_btn = QPushButton("GitHub")
        self.github_btn.setObjectName("GithubButton")
        self.github_btn.setIcon(QIcon(resource_path(GITHUB_ICON_PATH)))
        self.github_btn.setIconSize(QSize(18, 18))
        self.github_btn.clicked.connect(self.open_github_repository_page)
        self.github_btn.setProperty("class", "SupportPlatformButton")
        self.discord_btn = QPushButton("Discord")
        self.discord_btn.setObjectName("DiscordButton")
        self.discord_btn.setIcon(QIcon(resource_path(DISCORD_ICON_PATH)))
        self.discord_btn.setIconSize(QSize(18, 18))
        self.discord_btn.clicked.connect(self.open_discord_support_page)
        self.discord_btn.setProperty("class", "SupportPlatformButton")
        self._sync_support_button_sizes()
        support_button_row.addWidget(self.patreon_btn)
        support_button_row.addWidget(self.kofi_btn)
        support_button_row.addWidget(self.github_btn)
        support_button_row.addWidget(self.discord_btn)
        layout.addLayout(support_button_row)

    def _set_native_hook_checkbox_value(self, enabled: bool):
        self._native_hook_toggle_guard = True
        try:
            _set_bool(self.native_hook_enabled_var, enabled)
        finally:
            self._native_hook_toggle_guard = False

    def _set_native_hook_hotkeys_checkbox_value(self, enabled: bool):
        self._native_hook_hotkeys_toggle_guard = True
        try:
            _set_bool(self.native_hook_hotkeys_enabled_var, enabled)
        finally:
            self._native_hook_hotkeys_toggle_guard = False

    def _sync_support_button_sizes(self):
        buttons = [self.patreon_btn, self.kofi_btn, self.github_btn, self.discord_btn]
        target_width = max(button.sizeHint().width() for button in buttons)
        for button in buttons:
            button.setFixedWidth(target_width)
            button.setFixedHeight(26)

    def prompt_native_hook_enable_confirmation(self) -> bool:
        dialog = NativeHookWarningDialog(self)
        dialog.exec()
        return bool(dialog.result)

    def prompt_native_hook_hotkeys_enable_confirmation(self) -> bool:
        dialog = NativeHookWarningDialog(
            self,
            title_text="Enable Hook-Based Game-Setting Hotkeys?",
            summary_text=(
                "This enables lower-level hotkeys for supported game settings.\n"
                "Using this mode may not be considered entirely fair and could have consequences."
            ),
            switch_text=(
                "You can safely switch these hotkeys off at any time from Settings.\n"
                "Standard memory reads and keyboard restart will keep working."
            ),
            repeat_text="This dialog will appear whenever hook-based game-setting hotkeys are turned on.",
        )
        dialog.exec()
        return bool(dialog.result)

    def on_native_hook_toggle(self):
        if getattr(self, "_native_hook_toggle_guard", False):
            return
        if not _read_bool(self.native_hook_enabled_var):
            return
        if not SettingsDialog.prompt_native_hook_enable_confirmation(self):
            SettingsDialog._set_native_hook_checkbox_value(self, False)

    def on_native_hook_hotkeys_toggle(self):
        if getattr(self, "_native_hook_hotkeys_toggle_guard", False):
            return
        if not _read_bool(self.native_hook_hotkeys_enabled_var):
            return
        if not SettingsDialog.prompt_native_hook_hotkeys_enable_confirmation(self):
            SettingsDialog._set_native_hook_hotkeys_checkbox_value(self, False)

    def check_update(self):
        threading.Thread(target=updater.check_and_update, args=(self.master, True), daemon=True).start()
        if hasattr(self, "close"):
            self.close()

    def open_patreon_support_page(self):
        webbrowser.open(PATREON_SUPPORT_URL)

    def open_kofi_support_page(self):
        webbrowser.open(KOFI_SUPPORT_URL)

    def open_github_repository_page(self):
        webbrowser.open(GITHUB_REPOSITORY_URL)

    def open_discord_support_page(self):
        webbrowser.open(DISCORD_SUPPORT_URL)

    def save(self):
        new_hotkey = _read_text(self.hotkey_entry).strip()
        new_reset_hotkey = _read_text(self.reset_hotkey_entry).strip()
        new_record_hotkey = _read_text(self.record_hotkey_entry).strip()
        new_toggle_skip_chest_animation_hotkey = _read_text(self.toggle_skip_chest_animation_hotkey_entry).strip()
        new_toggle_auto_select_upgrades_hotkey = _read_text(self.toggle_auto_select_upgrades_hotkey_entry).strip()
        new_toggle_particles_opacity_hotkey = _read_text(self.toggle_particles_opacity_hotkey_entry).strip()
        auto_start_recording = _read_bool(self.auto_start_recording_var)
        show_obs_reminder_on_start_scanner = _read_bool(
            getattr(self, "show_obs_reminder_on_start_scanner_var", None)
        )
        native_hook_enabled = _read_bool(self.native_hook_enabled_var)
        native_hook_hotkeys_enabled = _read_bool(self.native_hook_hotkeys_enabled_var)

        config.user_config["HOTKEY"] = new_hotkey
        config.user_config["RESET_HOTKEY"] = new_reset_hotkey
        config.user_config["PLAYER_STATS_RECORD_HOTKEY"] = new_record_hotkey
        config.user_config["TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY"] = new_toggle_skip_chest_animation_hotkey
        config.user_config["TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY"] = new_toggle_auto_select_upgrades_hotkey
        config.user_config["TOGGLE_PARTICLES_OPACITY_HOTKEY"] = new_toggle_particles_opacity_hotkey
        config.user_config["AUTO_START_RECORDING"] = auto_start_recording
        config.user_config["SHOW_OBS_REMINDER_ON_START_SCANNER"] = show_obs_reminder_on_start_scanner
        config.user_config["NATIVE_HOOK_ENABLED"] = native_hook_enabled
        config.user_config["NATIVE_HOOK_GAME_SETTING_HOTKEYS_ENABLED"] = native_hook_hotkeys_enabled

        config.HOTKEY = new_hotkey
        config.RESET_HOTKEY = new_reset_hotkey
        config.PLAYER_STATS_RECORD_HOTKEY = new_record_hotkey
        config.TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY = new_toggle_skip_chest_animation_hotkey
        config.TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY = new_toggle_auto_select_upgrades_hotkey
        config.TOGGLE_PARTICLES_OPACITY_HOTKEY = new_toggle_particles_opacity_hotkey
        config.AUTO_START_RECORDING = auto_start_recording
        config.SHOW_OBS_REMINDER_ON_START_SCANNER = show_obs_reminder_on_start_scanner
        config.NATIVE_HOOK_ENABLED = native_hook_enabled
        config.NATIVE_HOOK_GAME_SETTING_HOTKEYS_ENABLED = native_hook_hotkeys_enabled
        if auto_start_recording and hasattr(self.master, "player_stats_auto_recording_suppressed"):
            self.master.player_stats_auto_recording_suppressed = False

        def _read_numeric(entry) -> float:
            if entry is None:
                return 0.0
            if hasattr(entry, "value"):
                val = entry.value
                return float(val() if callable(val) else val)
            return float(_read_text(entry))

        delay_entry = getattr(self, "min_delay_entry", None) or getattr(self, "map_load_delay_entry", None)
        try:
            new_delay = _read_numeric(delay_entry)
            config.user_config["MIN_DELAY"] = new_delay
            config.MIN_DELAY = new_delay
            config.MAP_LOAD_DELAY = new_delay
        except ValueError:
            pass

        try:
            new_duration = _read_numeric(self.reset_hold_duration_entry)
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
            new_interval = max(1, int(_read_numeric(self.record_interval_entry)))
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


class TwitchCommandSettingsDialog(QDialog):
    def __init__(self, parent, master=None):
        super().__init__(parent)
        self.master = master or parent
        self.setWindowTitle("Twitch Command Settings")
        self.resize(700, 760)
        self.setMinimumSize(640, 680)
        self.setModal(True)

        self.stat_checkboxes: dict[str, QCheckBox] = {}
        self.templates_entries: dict[str, QLineEdit] = {}
        self._init_guard = True

        outer_layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        outer_layout.addWidget(self.tabs, 1)

        # === TAB 1: Response Templates ===
        tab_templates = QWidget()
        tab_templates_layout = QVBoxLayout(tab_templates)

        templates_scroll, _, templates_scroll_layout = _make_scroll_section()
        tab_templates_layout.addWidget(templates_scroll)

        templates_form = QFormLayout()
        templates_config = [
            ("bans", "!bans / !banishes:", "Bans ({count}): {items}", "Tags: {count}, {items}"),
            ("items", "!items / !tracked:", "Items ({count}): {items}", "Tags: {count}, {items} (automatically collapsed if too long)"),
            ("weapons", "!weapons:", "Weapons: {weapons}", "Tags: {weapons}"),
            ("tomes", "!tomes:", "Tomes: {tomes}", "Tags: {tomes}"),
            ("chaos", "!chaos / !chaostome:", "Chaos Tome Lv{level}: {chaos}", "Tags: {level}, {chaos}"),
            ("powerups", "!powerups:", "Powerups: Rage/Shield/Coin/Speed {standard_duration}s | Clock {clock_duration}s (PM {pm})", "Tags: {standard_duration}, {clock_duration}, {pm}"),
            ("chests", "!chests / !chest:", config.DEFAULT_TWITCH_BOT["templates"]["chests"], "Tags: {stages}, {opened}, {total}, {paid}, {procs}, {normal}, {proc_rate}, {expected}, {free}, {keys}, {chance}"),
            ("commands", "!bonkhelp / !bonkcmds:", config.DEFAULT_TWITCH_BOT["templates"]["commands"], "Tags: {commands_list}"),
        ]

        for key, label_text, default_val, help_text in templates_config:
            current_val = config.TWITCH_BOT.get("templates", {}).get(key, default_val)
            entry = QLineEdit(current_val)
            self.templates_entries[key] = entry

            entry_layout = QVBoxLayout()
            entry_layout.addWidget(entry)
            help_lbl = QLabel(f"<span style='color: #9CA3AF; font-size: 11px;'>{help_text}</span>")
            help_lbl.setWordWrap(True)
            entry_layout.addWidget(help_lbl)

            templates_form.addRow(label_text, entry_layout)

        templates_scroll_layout.addLayout(templates_form)
        templates_scroll_layout.addStretch(1)
        self.tabs.addTab(tab_templates, "Response Templates")

        # === TAB 2: Advanced Commands ===
        tab_advanced = QWidget()
        tab_advanced_layout = QVBoxLayout(tab_advanced)
        adv_scroll, _, adv_scroll_layout = _make_scroll_section()
        tab_advanced_layout.addWidget(adv_scroll)

        # -- !stats section --
        stats_group = CollapsibleSection("!stats Command", expanded=False)
        stats_layout = stats_group.body_layout
        stats_layout.addWidget(QLabel("Select which stats appear in the {stats} placeholder:"))

        stats_config_layout = QGridLayout()
        stats_config_layout.setContentsMargins(5, 5, 5, 5)
        stats_config_layout.setSpacing(10)

        all_stats = [spec.label for group in PLAYER_STAT_GROUPS for spec in group]
        selected_stats = set(config.TWITCH_BOT.get("selected_stats", config.DEFAULT_TWITCH_BOT["selected_stats"]))

        for index, label in enumerate(all_stats):
            checkbox = QCheckBox(label)
            checkbox.setChecked(label in selected_stats)
            checkbox.stateChanged.connect(self.on_stat_toggled)
            self.stat_checkboxes[label] = checkbox

            stats_config_layout.addWidget(checkbox, index // 4, index % 4)

        stats_layout.addLayout(stats_config_layout)
        stats_layout.addSpacing(10)

        stats_form = QFormLayout()
        stats_tpl_val = config.TWITCH_BOT.get("templates", {}).get("stats", "Live Stats: DMG: {Damage} | XP: {XP Gain} | Luck: {Luck} | Size: {Size}")
        self.stats_tpl_entry = QLineEdit(stats_tpl_val)
        self.templates_entries["stats"] = self.stats_tpl_entry
        stats_form.addRow("Response template:", self.stats_tpl_entry)
        stats_layout.addLayout(stats_form)

        stats_help = QLabel(
            "<span style='color: #9CA3AF; font-size: 11px;'>"
            "Available tags: <b>{stats}</b> (auto-generated list of checked stats above), "
            "<b>{Damage}</b>, <b>{XP Gain}</b>, <b>{Luck}</b>, <b>{Difficulty}</b>, <b>{Size}</b>, etc."
            "</span>"
        )
        stats_help.setWordWrap(True)
        stats_layout.addWidget(stats_help)

        stats_reset_layout = QHBoxLayout()
        self.twitch_stats_reset_btn = QPushButton("Reset to Default Stats")
        self.twitch_stats_reset_btn.clicked.connect(self._reset_twitch_stats_to_default)
        stats_reset_layout.addWidget(self.twitch_stats_reset_btn)
        stats_reset_layout.addStretch(1)
        stats_layout.addLayout(stats_reset_layout)

        adv_scroll_layout.addWidget(stats_group)
        adv_scroll_layout.addSpacing(15)

        # -- !session tracked items section --
        twitch_uses_session_tracked_items = (
            config.normalize_tracked_items_source(
                config.TWITCH_BOT.get("tracked_items_source"),
                default="session",
            ) == "session"
        )
        twitch_tracked_group = CollapsibleSection(
            "!session Tracked Items",
            expanded=False,
        )
        twitch_tracked_layout = twitch_tracked_group.body_layout
        twitch_tracked_layout.addWidget(QLabel("Choose which tracked item counters appear in the Twitch !session response."))

        self.twitch_use_session_tracked_items_cb = QCheckBox("Use Session Stats tracked items")
        self.twitch_use_session_tracked_items_cb.setChecked(twitch_uses_session_tracked_items)
        self.twitch_use_session_tracked_items_cb.stateChanged.connect(self.on_twitch_tracked_items_source_toggled)
        twitch_tracked_layout.addWidget(self.twitch_use_session_tracked_items_cb)

        self.twitch_tracked_items_source_label = QLabel()
        self.twitch_tracked_items_source_label.setWordWrap(True)
        twitch_tracked_layout.addWidget(self.twitch_tracked_items_source_label)

        self.twitch_custom_tracked_items_widget = QWidget()
        twitch_custom_layout = QVBoxLayout(self.twitch_custom_tracked_items_widget)
        twitch_custom_layout.setContentsMargins(0, 0, 0, 0)
        twitch_custom_layout.setSpacing(8)

        shuttle_layout = QHBoxLayout()

        left_layout = QVBoxLayout()
        left_layout.setSpacing(4)

        search_top_layout = QHBoxLayout()
        search_top_layout.addWidget(QLabel("Available Items"))
        search_top_layout.addStretch(1)
        left_layout.addLayout(search_top_layout)

        self.twitch_item_names = available_item_display_names()
        self.twitch_item_search_entry = QLineEdit()
        self.twitch_item_search_entry.setPlaceholderText("Search items...")
        self.twitch_item_search_entry.textChanged.connect(self.refresh_twitch_item_selector)
        left_layout.addWidget(self.twitch_item_search_entry)

        self.twitch_item_selector = QListWidget()
        self.twitch_item_selector.setMinimumHeight(TRACKED_ITEM_LIST_HEIGHT)
        left_layout.addWidget(self.twitch_item_selector)
        shuttle_layout.addLayout(left_layout, 1)

        middle_layout = QVBoxLayout()
        middle_layout.setSpacing(10)
        middle_layout.addStretch(1)

        self.twitch_map_one_only_checkbox = QCheckBox("Map 1 only")
        self.twitch_map_one_only_checkbox.setChecked(True)
        self.twitch_map_one_only_checkbox.setToolTip("If checked, only counts gains on the first map.")
        middle_layout.addWidget(self.twitch_map_one_only_checkbox, 0, Qt.AlignmentFlag.AlignCenter)

        self.twitch_add_tracked_item_btn = QPushButton("Add >>")
        self.twitch_add_tracked_item_btn.clicked.connect(self.add_twitch_tracked_item)
        middle_layout.addWidget(self.twitch_add_tracked_item_btn)

        self.twitch_remove_tracked_item_btn = QPushButton("<< Remove")
        self.twitch_remove_tracked_item_btn.clicked.connect(self.remove_twitch_tracked_item)
        middle_layout.addWidget(self.twitch_remove_tracked_item_btn)

        middle_layout.addStretch(1)
        shuttle_layout.addLayout(middle_layout)

        right_layout = QVBoxLayout()
        right_layout.setSpacing(4)

        tracked_top_layout = QHBoxLayout()
        tracked_top_layout.addWidget(QLabel("Custom Twitch tracked items"))
        tracked_top_layout.addStretch(1)
        right_layout.addLayout(tracked_top_layout)

        self.twitch_tracked_rules_list = QListWidget()
        self.twitch_tracked_rules_list.setMinimumHeight(TRACKED_ITEM_LIST_HEIGHT + 28)
        right_layout.addWidget(self.twitch_tracked_rules_list)
        shuttle_layout.addLayout(right_layout, 1)

        twitch_custom_layout.addLayout(shuttle_layout)
        twitch_tracked_layout.addWidget(self.twitch_custom_tracked_items_widget)

        twitch_tracked_layout.addSpacing(10)
        session_form = QFormLayout()
        session_tpl_val = config.TWITCH_BOT.get("templates", {}).get("session", config.DEFAULT_TWITCH_BOT["templates"]["session"])
        self.session_tpl_entry = QLineEdit(session_tpl_val)
        self.templates_entries["session"] = self.session_tpl_entry
        session_form.addRow("Response template:", self.session_tpl_entry)
        twitch_tracked_layout.addLayout(session_form)

        session_help = QLabel(
            "<span style='color: #9CA3AF; font-size: 11px;'>"
            "Available tags: <b>{items}</b> (the tracked items configured above), "
            "<b>{resets}</b>, <b>{seeds}</b>, <b>{seed_rate}</b>."
            "</span>"
        )
        session_help.setWordWrap(True)
        twitch_tracked_layout.addWidget(session_help)
        twitch_tracked_layout.addSpacing(10)

        self.refresh_twitch_item_selector()
        self.refresh_twitch_tracked_items_ui()
        adv_scroll_layout.addWidget(twitch_tracked_group)
        adv_scroll_layout.addSpacing(15)

        # -- !disabled section --
        disabled_group = CollapsibleSection("!disabled Command Settings", expanded=False)
        disabled_layout = disabled_group.body_layout
        disabled_layout.addWidget(QLabel("Select key items to display when globally disabled in lobby:"))

        self.disabled_search_input = QLineEdit()
        self.disabled_search_input.setPlaceholderText("Search / Filter items...")
        self.disabled_search_input.textChanged.connect(self.filter_disabled_items)
        disabled_layout.addWidget(self.disabled_search_input)

        self.show_all_disabled_items_cb = QCheckBox("Show all items")
        self.show_all_disabled_items_cb.setChecked(False)
        self.show_all_disabled_items_cb.stateChanged.connect(self.filter_disabled_items)
        disabled_layout.addWidget(self.show_all_disabled_items_cb)

        disabled_scroll_area = QScrollArea()
        disabled_scroll_area.setWidgetResizable(True)
        disabled_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        disabled_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        disabled_scroll_area.setFixedHeight(150)

        disabled_scroll_content = QWidget()
        self.disabled_grid = QGridLayout(disabled_scroll_content)
        self.disabled_grid.setContentsMargins(5, 5, 5, 5)
        self.disabled_grid.setSpacing(8)

        from item_metadata import ITEMS, ITEM_DISPLAY_NAME_BY_RAW_VALUE

        display_names_to_item = {}
        for item in ITEMS:
            if item.rarity in ("COMMON", "UNCOMMON", "RARE", "LEGENDARY") and item.item_id != 79:
                if item.enum_name in ITEM_DISPLAY_NAME_BY_RAW_VALUE:
                    d_name = ITEM_DISPLAY_NAME_BY_RAW_VALUE[item.enum_name]
                else:
                    parts = []
                    current = ""
                    for char in item.enum_name:
                        if char.isupper() and current and not current[-1].isupper():
                            parts.append(current)
                            current = char
                        else:
                            current += char
                    if current:
                        parts.append(current)
                    d_name = " ".join(parts) if parts else item.enum_name
                display_names_to_item[d_name] = item

        disabled_in_game = []
        if self.master:
            cache = getattr(self.master, "player_stats_disabled_items_cache", None)
            if cache is not None:
                disabled_in_game = list(cache)
            elif hasattr(self.master, "live_run_tracker") and self.master.live_run_tracker:
                try:
                    result = self.master.live_run_tracker.get_disabled_items()
                    if result.available:
                        disabled_in_game = list(result.items)
                except Exception:
                    pass
        disabled_in_game_set = {name.lower() for name in disabled_in_game if name}

        highlighted_disabled = set(config.TWITCH_BOT.get("highlighted_disabled_items", []))

        def item_sort_key(d_name):
            is_checked = d_name in highlighted_disabled
            is_disabled_ingame = d_name.lower() in disabled_in_game_set
            if is_checked and is_disabled_ingame:
                return (0, d_name.lower())
            elif is_checked:
                return (1, d_name.lower())
            elif is_disabled_ingame:
                return (2, d_name.lower())
            else:
                return (3, d_name.lower())

        sorted_display_names = sorted(display_names_to_item.keys(), key=item_sort_key)

        self.disabled_item_checkboxes = {}
        num_cols = 3
        for idx, d_name in enumerate(sorted_display_names):
            is_disabled_ingame = d_name.lower() in disabled_in_game_set
            if is_disabled_ingame:
                cb = QCheckBox(f"🚫 {d_name}")
                cb.setStyleSheet("color: #FB7185; font-weight: bold;")
            else:
                cb = QCheckBox(d_name)
            cb.setProperty("is_disabled_ingame", is_disabled_ingame)
            cb.setChecked(d_name in highlighted_disabled)
            self.disabled_item_checkboxes[d_name] = cb
            cb.stateChanged.connect(self.filter_disabled_items)

            row = idx // num_cols
            col = idx % num_cols
            self.disabled_grid.addWidget(cb, row, col)

        self.filter_disabled_items()

        disabled_scroll_area.setWidget(disabled_scroll_content)
        disabled_layout.addWidget(disabled_scroll_area)
        disabled_layout.addSpacing(10)

        disabled_form = QFormLayout()
        disabled_tpl_val = config.TWITCH_BOT.get("templates", {}).get("disabled", "Disabled Items: {items}")
        self.disabled_tpl_entry = QLineEdit(disabled_tpl_val)
        self.templates_entries["disabled"] = self.disabled_tpl_entry
        disabled_form.addRow("Response template:", self.disabled_tpl_entry)
        disabled_layout.addLayout(disabled_form)

        disabled_help = QLabel(
            "<span style='color: #9CA3AF; font-size: 11px;'>"
            "Available tags: <b>{items}</b> (comma-separated list of selected items that are currently disabled)"
            "</span>"
        )
        disabled_help.setWordWrap(True)
        disabled_layout.addWidget(disabled_help)

        adv_scroll_layout.addWidget(disabled_group)
        adv_scroll_layout.addStretch(1)
        self.twitch_advanced_sections_group = CollapsibleSectionGroup(
            (stats_group, twitch_tracked_group, disabled_group)
        )
        self.tabs.addTab(tab_advanced, "Advanced Commands")

        # === TAB 3: Announcers ===
        tab_announcers = QWidget()
        tab_announcers_layout = QVBoxLayout(tab_announcers)
        ann_scroll, _, ann_scroll_layout = _make_scroll_section()
        tab_announcers_layout.addWidget(ann_scroll)

        announcers_form = QFormLayout()

        stage_ann_val = config.TWITCH_BOT.get("templates", {}).get(
            "stage_announcement",
            "🚩 Stage {stage} completed! Kills: {kills} | Time: {time}. Moving to Stage {next_stage}! 🚩"
        )
        stage_ann_entry = QLineEdit(stage_ann_val)
        self.templates_entries["stage_announcement"] = stage_ann_entry

        stage_ann_layout = QVBoxLayout()
        stage_ann_layout.addWidget(stage_ann_entry)
        stage_ann_help = QLabel(
            "<span style='color: #9CA3AF; font-size: 11px;'>"
            "Tags: {stage}, {kills}, {time}, {next_stage}"
            "</span>"
        )
        stage_ann_help.setWordWrap(True)
        stage_ann_layout.addWidget(stage_ann_help)
        announcers_form.addRow("Stage Transition:", stage_ann_layout)

        ann_scroll_layout.addLayout(announcers_form)

        # Commands announcer
        self.commands_announcement_interval_spin = QSpinBox()
        self.commands_announcement_interval_spin.setRange(1, 1440)
        self.commands_announcement_interval_spin.setValue(
            int(config.TWITCH_BOT.get("commands_announcement_interval_minutes", 30))
        )
        self.commands_announcement_interval_spin.setSuffix(" min")

        ann_extra_form = QFormLayout()
        ann_extra_form.addRow("Commands interval:", self.commands_announcement_interval_spin)
        ann_scroll_layout.addLayout(ann_extra_form)

        ann_scroll_layout.addStretch(1)
        self.tabs.addTab(tab_announcers, "Announcers")

        # 3. Sticky action buttons
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 10, 0, 0)
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setObjectName("DangerButton")
        reset_btn.clicked.connect(self.reset_to_defaults)

        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("SuccessButton")
        save_btn.clicked.connect(self.save)

        button_row.addWidget(reset_btn)
        button_row.addStretch(1)
        button_row.addWidget(save_btn)

        outer_layout.addLayout(button_row)

        self._init_guard = False

    def on_stat_toggled(self):
        if getattr(self, "_init_guard", False):
            return
        stat_abbrevs = {
            "Max HP": "HP",
            "HP Regen": "Regen",
            "Overheal": "Overheal",
            "Shield": "Shield",
            "Armor": "Armor",
            "Evasion": "Evasion",
            "Lifesteal": "Lifesteal",
            "Thorns": "Thorns",
            "Damage": "DMG",
            "Crit Chance": "Crit",
            "Crit Damage": "CritDMG",
            "Attack Speed": "AS",
            "Projectile Count": "Proj",
            "Projectile Bounces": "Bounces",
            "Size": "Size",
            "Projectile Speed": "ProjSpeed",
            "Duration": "Dur",
            "Damage to Elites": "EliteDMG",
            "Knockback": "KB",
            "Movement Speed": "MS",
            "Extra Jumps": "Jumps",
            "Jump Height": "JumpHeight",
            "Luck": "Luck",
            "Difficulty": "Diff",
            "Pickup Range": "Pickup",
            "XP Gain": "XP",
            "Gold Gain": "Gold",
            "Elite Spawn Increase": "ESI",
            "Powerup Multiplier": "PM",
            "Powerup Drop Chance": "PDC",
        }
        selected = [label for label, cb in self.stat_checkboxes.items() if cb.isChecked()]
        parts = [f"{stat_abbrevs.get(name, name)}: {{{name}}}" for name in selected]
        new_tpl = "Live Stats: " + " | ".join(parts)
        self.stats_tpl_entry.setText(new_tpl)

    def refresh_twitch_item_selector(self) -> None:
        selector = getattr(self, "twitch_item_selector", None)
        if selector is None:
            return
        query = ""
        if getattr(self, "twitch_item_search_entry", None) is not None:
            query = self.twitch_item_search_entry.text().strip().lower()
        selector.clear()
        for item_name in getattr(self, "twitch_item_names", ()):
            display_name = preferred_item_display_name(str(item_name))
            haystacks = {str(item_name).lower(), display_name.lower()}
            if query and not any(query in haystack for haystack in haystacks):
                continue
            item = QListWidgetItem(display_name)
            item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            item.setData(Qt.UserRole, item_name)
            selector.addItem(item)
        if selector.count() > 0:
            selector.setCurrentRow(0)

    def refresh_twitch_tracked_items_ui(self) -> None:
        rules_list = getattr(self, "twitch_tracked_rules_list", None)
        if rules_list is not None:
            rules_list.clear()
            for rule in config.TWITCH_BOT.get("tracked_items") or ():
                if not isinstance(rule, dict):
                    continue
                item_names = [str(name) for name in rule.get("item_names") or () if str(name).strip()]
                if not item_names:
                    continue
                mode = str(rule.get("mode") or "all_run")
                mode_label = "Map 1" if mode == "map_1_only" else "All run"
                label = self._twitch_tracked_rule_display_label(rule, item_names, mode)
                item = QListWidgetItem(f"{label}  [{mode_label}]")
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                item.setData(Qt.UserRole, dict(rule))
                rules_list.addItem(item)
        self._refresh_twitch_tracked_items_source_ui()

    def _refresh_twitch_tracked_items_source_ui(self) -> None:
        use_session = bool(
            getattr(self, "twitch_use_session_tracked_items_cb", None)
            and self.twitch_use_session_tracked_items_cb.isChecked()
        )
        custom_count = len(config.normalize_tracked_item_rules_config(config.TWITCH_BOT.get("tracked_items"), []))
        session_count = len(config.normalize_tracked_item_rules_config(config.SESSION_TRACKED_ITEMS.get("tracked_items"), []))
        source_label = getattr(self, "twitch_tracked_items_source_label", None)
        if source_label is not None:
            if use_session:
                source_label.setText(f"Twitch !session source: Session Stats ({session_count}). Custom Twitch list is preserved ({custom_count}).")
            else:
                source_label.setText(f"Twitch !session source: Custom ({custom_count}). Session Stats has {session_count} rule(s).")
        custom_widget = getattr(self, "twitch_custom_tracked_items_widget", None)
        if custom_widget is not None:
            custom_widget.setVisible(not use_session)
        for widget in (
            getattr(self, "twitch_map_one_only_checkbox", None),
            getattr(self, "twitch_item_search_entry", None),
            getattr(self, "twitch_item_selector", None),
            getattr(self, "twitch_add_tracked_item_btn", None),
            getattr(self, "twitch_tracked_rules_list", None),
            getattr(self, "twitch_remove_tracked_item_btn", None),
        ):
            if widget is not None:
                widget.setEnabled(not use_session)

    def on_twitch_tracked_items_source_toggled(self, *_args) -> None:
        self._refresh_twitch_tracked_items_source_ui()

    def add_twitch_tracked_item(self) -> None:
        item_name = self._selected_twitch_item_name()
        if not item_name:
            return
        map_one_only = bool(self.twitch_map_one_only_checkbox.isChecked())
        mode = "map_1_only" if map_one_only else "all_run"
        display_name = preferred_item_display_name(str(item_name))
        label = f"{display_name} Map 1" if map_one_only else display_name
        rule = {
            "id": self._twitch_rule_id(str(item_name), mode),
            "label": label,
            "item_names": [str(item_name)],
            "mode": mode,
        }
        existing_rules = self._twitch_tracked_item_config_from_ui()
        existing_ids = {str(raw_rule.get("id") or "") for raw_rule in existing_rules}
        if rule["id"] not in existing_ids:
            existing_rules.append(rule)
        config.TWITCH_BOT["tracked_items"] = existing_rules
        self.refresh_twitch_tracked_items_ui()

    def remove_twitch_tracked_item(self) -> None:
        rules_list = getattr(self, "twitch_tracked_rules_list", None)
        if rules_list is None or rules_list.currentRow() < 0:
            return
        rules_list.takeItem(rules_list.currentRow())
        config.TWITCH_BOT["tracked_items"] = self._twitch_tracked_item_config_from_ui()
        self.refresh_twitch_tracked_items_ui()

    def _selected_twitch_item_name(self) -> str:
        selector = getattr(self, "twitch_item_selector", None)
        if selector is not None and selector.currentItem() is not None:
            return str(selector.currentItem().data(Qt.UserRole) or selector.currentItem().text()).strip()
        if getattr(self, "twitch_item_search_entry", None) is not None:
            query = self.twitch_item_search_entry.text().strip()
            for item_name in getattr(self, "twitch_item_names", ()):
                display_name = preferred_item_display_name(str(item_name))
                if str(item_name).lower() == query.lower() or display_name.lower() == query.lower():
                    return str(item_name)
        return ""

    def _twitch_tracked_item_config_from_ui(self) -> list[dict[str, object]]:
        rules: list[dict[str, object]] = []
        rules_list = getattr(self, "twitch_tracked_rules_list", None)
        if rules_list is None:
            return rules
        for index in range(rules_list.count()):
            item = rules_list.item(index)
            rule = item.data(Qt.UserRole)
            if isinstance(rule, dict):
                rules.append(dict(rule))
        return rules

    @staticmethod
    def _twitch_rule_id(item_name: str, mode: str) -> str:
        folded = "".join(char.lower() for char in item_name if char.isalnum())
        return f"twitch_{folded or 'item'}_{mode}"

    @staticmethod
    def _twitch_tracked_rule_display_label(rule: dict, item_names: list[str], mode: str) -> str:
        raw_label = str(rule.get("label") or ", ".join(item_names))
        if len(item_names) != 1:
            return raw_label
        canonical_name = str(item_names[0])
        preferred_name = preferred_item_display_name(canonical_name)
        default_label = f"{canonical_name} Map 1" if mode == "map_1_only" else canonical_name
        preferred_label = f"{preferred_name} Map 1" if mode == "map_1_only" else preferred_name
        return preferred_label if raw_label == default_label else raw_label

    def reset_to_defaults(self):
        self._init_guard = True
        default_selected = set(config.DEFAULT_TWITCH_BOT["selected_stats"])
        for label, cb in self.stat_checkboxes.items():
            cb.setChecked(label in default_selected)

        self.stats_tpl_entry.setText(config.DEFAULT_TWITCH_BOT["templates"]["stats"])

        for cb in self.disabled_item_checkboxes.values():
            cb.setChecked(False)

        if getattr(self, "twitch_use_session_tracked_items_cb", None) is not None:
            self.twitch_use_session_tracked_items_cb.setChecked(True)
        if getattr(self, "twitch_tracked_rules_list", None) is not None:
            self.twitch_tracked_rules_list.clear()


        defaults = config.DEFAULT_TWITCH_BOT["templates"]
        for key, entry in self.templates_entries.items():
            entry.setText(defaults.get(key, ""))
        self.commands_announcement_interval_spin.setValue(
            int(config.DEFAULT_TWITCH_BOT.get("commands_announcement_interval_minutes", 30))
        )
        self._init_guard = False

    def _reset_twitch_stats_to_default(self):
        default_selected = set(config.DEFAULT_TWITCH_BOT["selected_stats"])
        for label, cb in self.stat_checkboxes.items():
            cb.setChecked(label in default_selected)
        self.stats_tpl_entry.setText(config.DEFAULT_TWITCH_BOT["templates"]["stats"])

    def filter_disabled_items(self):
        text = self.disabled_search_input.text().strip().lower()
        show_all = getattr(self, "show_all_disabled_items_cb", None) and self.show_all_disabled_items_cb.isChecked()

        # Temporarily remove all widgets from the grid layout
        for i in reversed(range(self.disabled_grid.count())):
            widget = self.disabled_grid.itemAt(i).widget()
            if widget is not None:
                self.disabled_grid.removeWidget(widget)

        # Re-add matching widgets in order
        num_cols = 3
        visible_idx = 0
        for d_name, cb in self.disabled_item_checkboxes.items():
            matches_text = not text or text in d_name.lower()
            is_priority = bool(cb.property("is_disabled_ingame")) or cb.isChecked()
            matches_visibility = show_all or is_priority

            if matches_text and matches_visibility:
                cb.setVisible(True)
                row = visible_idx // num_cols
                col = visible_idx % num_cols
                self.disabled_grid.addWidget(cb, row, col)
                visible_idx += 1
            else:
                cb.setVisible(False)

    def save(self):
        selected_stats = [label for label, cb in self.stat_checkboxes.items() if cb.isChecked()]
        if not selected_stats:
            QMessageBox.warning(self, "Invalid Settings", "At least one stat must be selected.")
            return

        config.TWITCH_BOT["selected_stats"] = selected_stats
        config.TWITCH_BOT["templates"] = config.TWITCH_BOT.get("templates", {})
        config.TWITCH_BOT["templates"]["stats"] = self.stats_tpl_entry.text().strip()

        for key, entry in self.templates_entries.items():
            config.TWITCH_BOT["templates"][key] = entry.text().strip()

        highlighted_disabled = [
            name for name, cb in self.disabled_item_checkboxes.items() if cb.isChecked()
        ]
        config.TWITCH_BOT["highlighted_disabled_items"] = highlighted_disabled
        config.TWITCH_BOT["commands_announcement_interval_minutes"] = (
            self.commands_announcement_interval_spin.value()
        )

        if getattr(self, "twitch_use_session_tracked_items_cb", None) is not None:
            config.TWITCH_BOT["tracked_items_source"] = (
                "session" if self.twitch_use_session_tracked_items_cb.isChecked() else "custom"
            )
        if getattr(self, "twitch_tracked_rules_list", None) is not None:
            config.TWITCH_BOT["tracked_items"] = self._twitch_tracked_item_config_from_ui()

        config.TWITCH_BOT = config.normalize_twitch_bot_config(config.TWITCH_BOT)
        master = getattr(self, "master", None)
        live_run_tracker = getattr(master, "live_run_tracker", None)
        if live_run_tracker is not None and hasattr(master, "_combined_tracked_item_rules"):
            live_run_tracker.set_tracked_item_rules(master._combined_tracked_item_rules())
        if master is not None and hasattr(master, "refresh_session_tracked_item_stats_ui"):
            master.refresh_session_tracked_item_stats_ui()

        config.user_config["TWITCH_BOT"] = config.TWITCH_BOT
        config.save_config(config.user_config)
        self.accept()
