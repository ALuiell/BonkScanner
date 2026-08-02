"""Every shared dialog the application opens.

``gui_dialogs.py`` until step 27a, which moved it here whole -- the last
``TOPLEVEL_DEBT`` entry that was about neither the layout nor the tracker. It
reads only ``ui``, ``core``, ``projections`` and ``app``, all of which the §2
layer table already lets ``ui`` import, so the move needed no split and changed
no dependency: ``ui/tabs/player_stats/recordings.py`` reached it through a debt
entry and now reaches it as an ordinary within-``ui`` import.

``ui/dialogs/`` was already a package holding ``update_dialog.py``, which is
what settled §2's open question of package-versus-flat-module. The contents are
**not** split -- step 27 is closure, not migration -- so this ``__init__``
carries all 1,847 lines.

``update_prompt.py`` moved in with it, out of ``ui/``. It had to: it imports
``ui.dialogs.update_dialog``, and this module imports ``start_update_check``
from it, so leaving it outside would make ``ui.dialogs`` and ``ui.update_prompt``
import each other. That cycle would have survived -- Python resolves it by
statement order, and neither the suite nor ``test_import_direction`` imports
anything -- which is exactly the shape step 19 shipped once through
``gui_layout``. Inside the package it is a plain ``__init__ -> update_prompt ->
update_dialog`` chain with no back edge.
"""
from __future__ import annotations

import html
import re
import webbrowser
from functools import partial
from pathlib import Path

from ui.dialogs.shell import (
    DIALOG_COMPACT,
    DIALOG_REGULAR,
    DIALOG_TALL,
    DIALOG_WIDE,
    dialog_body,
    dialog_card,
    dialog_footer,
    dialog_note,
)
from ui.shared import (
    CollapsibleSection,
    CollapsibleSectionGroup,
    _clear_layout,
    _make_scroll_section,
    _read_bool,
    _read_text,
    _safe_float,
    build_template_payload,
    format_template_conditions,
    resource_path,
)
from ui.styles import (
    _template_color_hex,
    _template_manager_card_stylesheet,
    _template_manager_header_stylesheet,
    _tier_color,
)

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSpinBox,
    QDoubleSpinBox,
)
from core.settings import DEFAULT_MINIMUM_SNAPSHOT_COUNT
from core.stats.types import PLAYER_STAT_GROUPS
from core.stat_labels import abbreviate_stat_label

from app import config
from app.player_stats_view import overlay_view, player_stats_view
from app.vod_capture import vod_capture
from ui.dialogs.update_prompt import start_update_check

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
        self.bald_heads_entry = QLineEdit()
        self.magnet_entry = QLineEdit()

        layout.addRow("S+M Total (optional):", self.sm_entry)
        layout.addRow("Shady Guy (min):", self.shady_entry)
        layout.addRow("Moais (min):", self.moai_entry)
        layout.addRow("Microwaves (min):", self.micro_entry)
        layout.addRow("Boss Curses (min):", self.boss_entry)
        layout.addRow("Magnets (min):", self.magnet_entry)
        layout.addRow("Bald Heads (min):", self.bald_heads_entry)

        self.sm_entry.textChanged.connect(self._sync_sm_fields)
        self.shady_entry.textChanged.connect(self._sync_sm_fields)
        self.moai_entry.textChanged.connect(self._sync_sm_fields)
        self.load_template(self.template_data)

    def load_template(self, template_data=None):
        self.template_data = template_data or {}
        for widget in (self.sm_entry, self.shady_entry, self.moai_entry):
            widget.blockSignals(True)
        self.name_entry.setText(self.template_data.get("name", ""))
        self.name_entry.setEnabled(self.template_data.get("id", 100) > 7)
        self.sm_entry.setText(str(self.template_data.get("sm_total", 0)))
        self.shady_entry.setText(str(self.template_data.get("shady", 0)))
        self.moai_entry.setText(str(self.template_data.get("moai", 0)))
        self.micro_entry.setText(str(self.template_data.get("micro", 0)))
        self.boss_entry.setText(str(self.template_data.get("boss", 0)))
        self.magnet_entry.setText(str(self.template_data.get("magnet", self.template_data.get("magnet_shrines", 0))))
        self.bald_heads_entry.setText(str(self.template_data.get("bald_heads", 0)))
        for widget in (self.sm_entry, self.shady_entry, self.moai_entry):
            widget.blockSignals(False)
        self._sync_sm_fields()

    def _sync_sm_fields(self) -> None:
        sender = self.sender()

        sm_text = self.sm_entry.text().strip()
        shady_text = self.shady_entry.text().strip()
        moai_text = self.moai_entry.text().strip()

        sm_val = int(sm_text) if sm_text.isdigit() else 0
        shady_val = int(shady_text) if shady_text.isdigit() else 0
        moai_val = int(moai_text) if moai_text.isdigit() else 0

        if sender is self.sm_entry and sm_val > 0:
            for widget in (self.shady_entry, self.moai_entry):
                widget.blockSignals(True)
                widget.setText("0")
                widget.blockSignals(False)
        elif sender in (self.shady_entry, self.moai_entry) and (shady_val > 0 or moai_val > 0):
            self.sm_entry.blockSignals(True)
            self.sm_entry.setText("0")
            self.sm_entry.blockSignals(False)

    def get_payload(self):
        return build_template_payload(
            self.name_entry.text(),
            self.sm_entry.text(),
            self.shady_entry.text(),
            self.moai_entry.text(),
            self.micro_entry.text(),
            self.boss_entry.text(),
            self.bald_heads_entry.text(),
            self.magnet_entry.text(),
            source_template=self.template_data,
        )


class TemplateDialog(QDialog):
    def __init__(self, parent=None, edit_template=None):
        super().__init__(parent)
        self.result_payload = None
        title = "Edit Template" if edit_template else "Add Template"
        self.setWindowTitle(title)
        self.setModal(True)
        body = dialog_body(
            self,
            title=title,
            subtitle="Leave a condition at 0 to ignore it.",
            width=DIALOG_REGULAR,
        )
        self.form = TemplateFormFrame(self, edit_template)
        body.addWidget(self.form)
        self.save_btn = QPushButton("Save Template")
        self.save_btn.clicked.connect(self.save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        dialog_footer(self, primary=self.save_btn, secondary=cancel_btn)

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
        self.expanded_template_id: int | None = None
        self.card_widgets: dict[int, dict[str, object]] = {}

        layout = dialog_body(
            self,
            title="Templates",
            subtitle="Pick one from the list and its settings open under the card.",
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )
        self.scroll, self.scroll_content, self.scroll_layout = _make_scroll_section()
        layout.addWidget(self.scroll, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        dialog_footer(self, secondary=close_btn)

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
            meta_label.setStyleSheet("color: #C5CEDB; background: transparent;")
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
            save_btn.setObjectName("primary")
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
        self._scroll_card_into_view(template_id)

    def _scroll_card_into_view(self, template_id: int) -> None:
        """Bring the just-expanded card to the top of the viewport.

        Previously the user had to click a card *and* scroll manually to see
        the form it just revealed. `card.y()` is stale at this point --
        `details.setVisible(True)` above hasn't been laid out yet -- so the
        scroll has to happen after Qt processes that pending layout, not in
        the same call.
        """
        widgets = self.card_widgets.get(template_id)
        if widgets is None:
            return
        card = widgets["card"]

        def _scroll() -> None:
            self.scroll.verticalScrollBar().setValue(card.y())

        QTimer.singleShot(0, _scroll)

    def save_template(self, template_id: int, form: TemplateFormFrame):
        payload = form.get_payload()
        if payload is None:
            QMessageBox.warning(self, "Invalid Template", "Template name cannot be empty.")
            return

        template = next((item for item in self.templates if int(item.get("id", 0)) == template_id), None)
        if template is None:
            return

        payload["id"] = template.get("id")
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
        self.setModal(True)
        self.active_tier_checks: dict[str, QCheckBox] = {}
        self.threshold_entries: dict[str, QLineEdit] = {}
        self.weight_entries: dict[str, QLineEdit] = {}
        self.multiplier_entries: dict[str, QLineEdit] = {}

        outer = dialog_body(
            self,
            title="Scores Settings",
            subtitle="Which tiers count, and what a run has to reach for each.",
            width=DIALOG_REGULAR,
            height=DIALOG_TALL,
        )
        scroll, scroll_content, scroll_layout = _make_scroll_section()
        outer.addWidget(scroll, 1)

        active_group = QGroupBox("Active Tiers")
        active_layout = QVBoxLayout(active_group)
        for tier in ("Light", "Good", "Perfect", "Perfect+"):
            cb = QCheckBox(tier)
            cb.setChecked(tier in config.SCORES_SYSTEM.get("active_tiers", []))
            cb.setStyleSheet(f"color: {_tier_color(tier)}; font-weight: 700; background: transparent;")
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
        scroll_layout.addStretch(1)

        # Outside the scroll area, not inside it: Save/Reset used to be the
        # last thing in `scroll_layout`, so on a dialog this content-heavy
        # they only came into view after scrolling all the way down. A footer
        # row on `outer` is always visible regardless of scroll position or
        # window size.
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save)
        dialog_footer(self, primary=save_btn, destructive=reset_btn)
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
        layout = dialog_body(
            self,
            title="Delete Templates",
            subtitle="Tick the ones to remove. Built-in templates are not listed.",
            width=DIALOG_REGULAR,
        )
        scroll, _content, scroll_layout = _make_scroll_section()
        layout.addWidget(scroll, 1)
        for template in custom_templates:
            cb = QCheckBox(template["name"])
            self.checks[template["id"]] = cb
            scroll_layout.addWidget(cb)
        scroll_layout.addStretch(1)
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        # `QDialogButtonBox` is gone with it: it put Delete next to Cancel and
        # ordered them by platform convention, which is the one thing a shared
        # footer cannot let a dialog decide for itself.
        dialog_footer(self, secondary=cancel_btn, destructive=delete_btn)

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
        layout = dialog_body(
            self,
            title="Delete recording?",
            width=DIALOG_COMPACT,
        )
        name = QLabel(str(recording_name))
        name.setObjectName("dialogSubject")
        name.setWordWrap(True)
        layout.addWidget(name)
        layout.addWidget(dialog_note("This cannot be undone."))
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancel)
        confirm_btn = QPushButton("Delete")
        confirm_btn.clicked.connect(self.confirm)
        dialog_footer(self, secondary=cancel_btn, destructive=confirm_btn)

    def confirm(self):
        self.result = True
        self.accept()

    def cancel(self):
        self.result = False
        self.reject()


class CleanupRecordingsDialog(QDialog):
    """Confirm deleting every recording shorter than the auto-filter's threshold.

    The threshold is pre-filled from the library's "don't keep runs shorter
    than N" setting rather than defaulting to a hard-coded ``2``. They were two
    numbers for one question, and the pair disagreed by construction: the
    recorder discarded at one threshold while this dialog proposed another.
    Editable still, because "clean up harder than I record" is a real one-off.
    """

    def __init__(self, parent, *, default_threshold: int | None = None):
        super().__init__(parent)
        self.threshold: int | None = None
        self.setWindowTitle("Clean Recordings")
        self.setModal(True)
        layout = dialog_body(
            self,
            title="Clean up recordings",
            subtitle="Removes every recording shorter than the count below.",
            width=DIALOG_COMPACT,
        )
        if default_threshold is None:
            default_threshold = DEFAULT_MINIMUM_SNAPSHOT_COUNT
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        self.threshold_entry = QLineEdit(str(max(0, int(default_threshold))))
        form.addRow("Fewer snapshots than:", self.threshold_entry)
        layout.addLayout(form)
        layout.addWidget(dialog_note("This cannot be undone."))
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = QPushButton("Remove")
        confirm_btn.clicked.connect(self.confirm)
        dialog_footer(self, secondary=cancel_btn, destructive=confirm_btn)

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


class RerollWarningDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = False
        self.dont_show_again = False
        self.setWindowTitle("Auto-Reroll Confirmation")
        self.setModal(True)

        layout = dialog_body(
            self,
            title="Confirm Auto-Reroll Start",
            width=DIALOG_REGULAR,
        )
        layout.addWidget(
            dialog_card(
                "This button is only required for the Auto-Reroll map mode. "
                "Pressing OK will launch the automatic loop to monitor your runs "
                "and execute restarts until a matching target map is found."
                "<br><br>For more details, please open the Help (?)."
            )
        )
        layout.addWidget(
            dialog_note(
                "All other background features (Live Stats, VOD recordings and the "
                "OBS overlay) work automatically and do not require this loop."
            )
        )
        layout.addStretch(1)

        self.checkbox = QCheckBox("Don't show this again")
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancel)
        confirm_btn = QPushButton("OK")
        confirm_btn.clicked.connect(self.confirm)
        dialog_footer(
            self, primary=confirm_btn, secondary=cancel_btn, leading=self.checkbox
        )

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

        layout = dialog_body(
            self,
            title="OBS Recording Reminder",
            width=DIALOG_REGULAR,
        )
        layout.addWidget(
            dialog_card(
                "If this run is for leaderboard verification or YouTube, make sure "
                "OBS recording is started before beginning the run."
            )
        )
        layout.addWidget(
            dialog_note("This reminder can be switched off at any time in Settings.")
        )
        layout.addStretch(1)

        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        dialog_footer(self, primary=ok_btn)


class TwitchCommandsHelpDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.dont_show_again = False
        self.setWindowTitle("Twitch Command Aliases")
        self.setModal(True)

        layout = dialog_body(
            self,
            title="!bonkhelp aliases",
            subtitle="All four produce the same response; viewers can use any of them.",
            width=DIALOG_REGULAR,
        )
        layout.addWidget(
            dialog_card(
                "<b>!bonkhelp</b> &nbsp;·&nbsp; <b>!bonkcmds</b> &nbsp;·&nbsp; "
                "<b>!bonkcommands</b> &nbsp;·&nbsp; <b>!bhelp</b>"
            )
        )
        layout.addStretch(1)

        self.checkbox = QCheckBox("Don't show this again")
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.confirm)
        dialog_footer(self, primary=ok_btn, leading=self.checkbox)

    def confirm(self):
        self.dont_show_again = self.checkbox.isChecked()
        self.accept()


class HelpDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("BonkScanner Help")
        self.setModal(True)

        layout = dialog_body(
            self,
            title="Quick Help",
            subtitle=(
                "Practical notes on the main features, common workflows and "
                "the behaviour that is not obvious."
            ),
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )

        tabs = QTabWidget()
        tabs.addTab(self._build_language_tab("docs/help/help_eng.txt", self._fallback_eng_text()), "ENG")
        tabs.addTab(self._build_language_tab("docs/help/help_ukr.txt", self._fallback_ukr_text()), "UA")
        tabs.addTab(self._build_language_tab("docs/help/help_ru.txt", self._fallback_ru_text()), "RU")
        layout.addWidget(tabs, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        dialog_footer(self, secondary=close_btn)

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


#: Every value in the Settings form is two to five characters -- `f6`, `0.10 s`,
#: `30 s`. Capped so the field says so; before this they ran the width of the
#: window and the dialog read as six long boxes holding almost nothing.
_SETTINGS_FIELD_WIDTH = 130

#: Enough for `Snapshot every:`, the longest caption in the form. Fixed rather
#: than sized to content so the two pairs on a line start their fields at the
#: same x -- otherwise each column is as wide as its own longest label and the
#: fields step sideways from row to row.
_SETTINGS_LABEL_WIDTH = 120


def _settings_group_label(text: str) -> QLabel:
    label = QLabel(str(text).upper())
    label.setObjectName("sectionEyebrow")
    return label


def _settings_grid(rows) -> QGridLayout:
    """Label-and-field pairs, two pairs per line.

    A `QFormLayout` cannot do this: it is one column of rows by construction, so
    four two-character hotkeys took four full lines of a 560px window.
    """
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(8)
    for index, (caption, field) in enumerate(rows):
        row, column = divmod(index, 2)
        label = QLabel(str(caption))
        label.setObjectName("rowLabel")
        # Left-aligned, on a column wide enough for the longest caption, so the
        # labels share the window's left edge with the group headings and the
        # checkboxes. Right-aligning them against the fields instead put a
        # 120px gutter down the left of the dialog with nothing in it.
        label.setMinimumWidth(_SETTINGS_LABEL_WIDTH)
        grid.addWidget(label, row, column * 2, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(field, row, column * 2 + 1, Qt.AlignLeft | Qt.AlignVCenter)
    grid.setColumnStretch(1, 1)
    grid.setColumnStretch(3, 1)
    return grid


class SettingsDialog(QDialog):
    def __init__(self, parent, master=None):
        super().__init__(parent)
        self.master = master or parent
        self.setWindowTitle("Settings")
        self.setModal(True)
        layout = dialog_body(
            self,
            title="Settings",
            subtitle="Hotkeys, capture intervals and what the app reminds you about.",
            width=DIALOG_REGULAR,
        )

        # Three groups, two columns, and every field capped. One column of
        # full-width rows was what made this window read as scattered: a field
        # 430px wide holding `f6`, six of them stacked, and 14px between rows
        # to hold them apart. The values here are two to five characters; the
        # width was carrying no information at all.
        self.hotkey_entry = QLineEdit(config.HOTKEY)
        self.reset_hotkey_entry = QLineEdit(config.RESET_HOTKEY)
        self.record_hotkey_entry = QLineEdit(
            getattr(config, "PLAYER_STATS_RECORD_HOTKEY", "f8")
        )
        # The fourth hotkey. It has always existed in config but had no editor
        # anywhere, so changing it meant hand-editing config.json. It is edited
        # on the In-Game Overlay tab too, deliberately -- the tab is where you
        # read what the key is -- and `save` below tells that tab it changed.
        self.overlay_edit_hotkey_entry = QLineEdit(
            str(getattr(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9") or "f9")
        )
        for entry in (
            self.hotkey_entry,
            self.reset_hotkey_entry,
            self.record_hotkey_entry,
            self.overlay_edit_hotkey_entry,
        ):
            entry.setMaximumWidth(_SETTINGS_FIELD_WIDTH)

        layout.addWidget(_settings_group_label("Hotkeys"))
        layout.addLayout(
            _settings_grid(
                (
                    ("Scan:", self.hotkey_entry),
                    ("Reset:", self.reset_hotkey_entry),
                    ("Record:", self.record_hotkey_entry),
                    ("Overlay layout:", self.overlay_edit_hotkey_entry),
                )
            )
        )

        self.reset_hold_duration_entry = QDoubleSpinBox()
        self.reset_hold_duration_entry.setRange(0.01, 10.0)
        self.reset_hold_duration_entry.setSingleStep(0.05)
        self.reset_hold_duration_entry.setDecimals(2)
        self.reset_hold_duration_entry.setValue(float(config.RESET_HOLD_DURATION))
        self.reset_hold_duration_entry.setSuffix(" s")
        self.reset_hold_duration_entry.setMaximumWidth(_SETTINGS_FIELD_WIDTH)
        self._initial_reset_hold_duration = round(float(config.RESET_HOLD_DURATION), 2)

        self.record_interval_entry = QSpinBox()
        self.record_interval_entry.setRange(1, 3600)
        self.record_interval_entry.setSingleStep(5)
        self.record_interval_entry.setValue(
            int(getattr(config, "PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30))
        )
        self.record_interval_entry.setSuffix(" s")
        self.record_interval_entry.setMaximumWidth(_SETTINGS_FIELD_WIDTH)

        layout.addWidget(_settings_group_label("Timing"))
        # Reset hold is written into the game's own config, which the game reads
        # once at startup -- saving it here does nothing until the game restarts.
        # Without this line the only feedback is the reset key not holding.
        reset_hold_note = QLabel("Reset hold takes effect after a game restart.")
        reset_hold_note.setObjectName("dialogHint")
        reset_hold_note.setWordWrap(True)
        layout.addWidget(reset_hold_note)
        layout.addLayout(
            _settings_grid(
                (
                    ("Reset hold:", self.reset_hold_duration_entry),
                    ("Snapshot every:", self.record_interval_entry),
                )
            )
        )

        layout.addWidget(_settings_group_label("On start"))
        self.auto_start_recording_var = QCheckBox("Auto-start recording")
        self.auto_start_recording_var.setChecked(bool(getattr(config, "AUTO_START_RECORDING", False)))
        layout.addWidget(self.auto_start_recording_var)

        self.show_obs_reminder_on_start_scanner_var = QCheckBox("Show OBS reminder on Start Scanner")
        self.show_obs_reminder_on_start_scanner_var.setChecked(
            bool(getattr(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False))
        )
        layout.addWidget(self.show_obs_reminder_on_start_scanner_var)

        layout.addStretch(1)

        # A card rather than a centred block under a rule. Centred text under a
        # left-aligned form is two alignments in one short window, and the rule
        # above it was a third divider in a dialog that already has one under
        # its title.
        support_card = QFrame()
        support_card.setObjectName("card")
        support_layout = QVBoxLayout(support_card)
        support_layout.setContentsMargins(12, 10, 12, 12)
        support_layout.setSpacing(8)

        support_label = QLabel("Support", support_card)
        support_label.setObjectName("SupportSectionLabel")
        support_layout.addWidget(support_label)

        support_note = QLabel(
            "BonkScanner is free to download. For feedback, bugs or ideas, "
            "use GitHub or Discord.",
            support_card,
        )
        support_note.setObjectName("SupportSectionNote")
        support_note.setWordWrap(True)
        support_layout.addWidget(support_note)

        support_button_row = QHBoxLayout()
        support_button_row.setSpacing(8)
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
        # An equal share of the row each, filling the card. They used to be
        # fixed to the width of the longest caption and packed at the left with
        # the surplus behind them, which read as four buttons that had run out
        # of room rather than a row of four.
        for button in (self.patreon_btn, self.kofi_btn, self.github_btn, self.discord_btn):
            support_button_row.addWidget(button, 1)
        support_layout.addLayout(support_button_row)
        layout.addWidget(support_card)

        # Save is a footer button like every other dialog's, rather than a
        # full-width bar stacked above the support block -- which put the
        # window's primary action in its middle, with donation links under it.
        self.update_btn = QPushButton("Check for Updates")
        self.update_btn.clicked.connect(self.check_update)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        dialog_footer(
            self, primary=self.save_btn, secondary=cancel_btn, leading=self.update_btn
        )

    def check_update(self):
        start_update_check(self.master, force_check=True)
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
        # `getattr` because the suite drives this dialog with stand-in objects
        # that predate the field; an empty value keeps the current key rather
        # than unbinding the only way into overlay layout mode.
        new_overlay_edit_hotkey = _read_text(
            getattr(self, "overlay_edit_hotkey_entry", None)
        ).strip() or str(getattr(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9") or "f9")
        auto_start_recording = _read_bool(self.auto_start_recording_var)
        show_obs_reminder_on_start_scanner = _read_bool(
            getattr(self, "show_obs_reminder_on_start_scanner_var", None)
        )

        def _read_numeric(entry) -> float:
            if entry is None:
                return 0.0
            if hasattr(entry, "value"):
                val = entry.value
                return float(val() if callable(val) else val)
            return float(_read_text(entry))

        try:
            new_duration = max(0.01, round(_read_numeric(self.reset_hold_duration_entry), 2))
        except (TypeError, ValueError, OverflowError):
            QMessageBox.warning(
                self,
                "Invalid Settings",
                "Reset Hold Duration must be a valid number.",
            )
            return

        initial_duration = round(
            float(getattr(self, "_initial_reset_hold_duration", config.RESET_HOLD_DURATION)),
            2,
        )
        if new_duration != initial_duration:
            # The game threshold stays 0.05 s below the actual key hold. That
            # safety margin covers input/animation timing jitter at the boundary.
            game_val = max(0.01, round(new_duration - 0.05, 2))
            update_result = config.update_game_reset_time(game_val)
            if not update_result.success:
                reason = update_result.reason or "The game config change could not be verified."
                QMessageBox.warning(
                    self,
                    "Game Settings Not Applied",
                    (
                        "Reset Hold Duration was not saved because BonkScanner could not "
                        "apply it to the game config.\n\n"
                        f"Reason: {reason}\n\n"
                        "Close the game, run BonkScanner as Administrator, and try again."
                    ),
                )
                return

        config.user_config["HOTKEY"] = new_hotkey
        config.user_config["RESET_HOTKEY"] = new_reset_hotkey
        config.user_config["PLAYER_STATS_RECORD_HOTKEY"] = new_record_hotkey
        config.user_config["IN_GAME_OVERLAY_EDIT_HOTKEY"] = new_overlay_edit_hotkey
        config.user_config["AUTO_START_RECORDING"] = auto_start_recording
        config.user_config["SHOW_OBS_REMINDER_ON_START_SCANNER"] = show_obs_reminder_on_start_scanner
        config.user_config["RESET_HOLD_DURATION"] = new_duration

        config.HOTKEY = new_hotkey
        config.RESET_HOTKEY = new_reset_hotkey
        config.PLAYER_STATS_RECORD_HOTKEY = new_record_hotkey
        config.IN_GAME_OVERLAY_EDIT_HOTKEY = new_overlay_edit_hotkey
        config.AUTO_START_RECORDING = auto_start_recording
        config.SHOW_OBS_REMINDER_ON_START_SCANNER = show_obs_reminder_on_start_scanner
        config.RESET_HOLD_DURATION = new_duration
        self._initial_reset_hold_duration = new_duration
        if auto_start_recording:
            # Was `hasattr(self.master, ...)` + a direct assignment. The service
            # always has the flag, so the guard is gone -- and with it the
            # step-19 failure shape where a `hasattr` goes quietly false and
            # re-enabling auto-start silently stops clearing a suppression.
            vod_capture(self.master).clear_auto_recording_suppression()

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
            # Through the port, not the shared namespace: once `LiveStatsTab`
            # left `MegabonkApp`'s MRO this `hasattr` would have gone quietly
            # false and the timeline would have stopped refreshing after a
            # settings save -- no exception, green suite. The guard stays
            # because the suite drives this dialog with stand-in masters.
            timeline = player_stats_view(self.master)
            if hasattr(timeline, "refresh_player_stats_timeline_ui"):
                timeline.refresh_player_stats_timeline_ui(update_slider=False)
            self.master.update_status_ui()
            # The OBS reminder is edited here *and* on the OBS Overlay tab. This
            # dialog is modal and rebuilt per open, so it never shows a stale
            # value -- but the tab's checkbox is long-lived and has no way to
            # learn that this save happened. Unguarded and through the named
            # port on purpose: see `OverlayView.refresh_scanner_reminder_ui`.
            overlay_view(self.master).refresh_scanner_reminder_ui()
            # Same shape, for the same reason: the In-Game Overlay tab shows
            # this hotkey in a field *and* in the tip that is now the only place
            # explaining how to enter layout mode. A stale tip there tells the
            # user to press a key that no longer does anything.
            self.master.refresh_in_game_overlay_hotkey_ui()
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
        self.setModal(True)

        self.stat_checkboxes: dict[str, QCheckBox] = {}
        self.templates_entries: dict[str, QLineEdit] = {}
        # Multi-line template *pools*, kept apart from the single-line entries
        # above because they answer `toPlainText()`/`setPlainText()` rather than
        # `text()`/`setText()`. See `_build_pool_row`.
        self.template_pool_entries: dict[str, QPlainTextEdit] = {}
        self._init_guard = True

        outer_layout = dialog_body(
            self,
            title="Twitch Command Settings",
            subtitle="What each command answers with, and what the bot says on its own.",
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )

        self.tabs = QTabWidget()
        outer_layout.addWidget(self.tabs, 1)

        # === TAB 1: Response Templates ===
        tab_templates = QWidget()
        tab_templates_layout = QVBoxLayout(tab_templates)

        templates_scroll, _, templates_scroll_layout = _make_scroll_section()
        tab_templates_layout.addWidget(templates_scroll)

        templates_form = QFormLayout()
        default_templates = config.DEFAULT_TWITCH_BOT.get("templates", {})
        templates_config = [
            ("bans", "!bans / !banishes:", "Bans ({count}): {items}", "Tags: {count}, {items}"),
            ("items", "!items / !tracked:", "Items ({count}): {items}", "Tags: {count}, {items} (automatically collapsed if too long)"),
            ("weapons", "!weapons:", "Weapons: {weapons}", "Tags: {weapons}"),
            ("tomes", "!tomes:", "Tomes: {tomes}", "Tags: {tomes}"),
            ("chaos", "!chaos / !chaostome:", "Chaos Tome Lv{level}: {chaos}", "Tags: {level}, {chaos}"),
            ("powerups", "!powerups:", default_templates.get("powerups", "Powerups: {powerups} (PM {pm})"), "Tags: {powerups}, {standard_duration}, {clock_duration}, {pm}"),
            ("kps", "!kps:", default_templates.get("kps", "KPS: {kps} | 60s Avg: {minute_avg} | 5m Avg: {five_minute_avg} | Run Avg: {run_avg}"), "Tags: {kps}, {minute_avg}, {five_minute_avg}, {run_avg}"),
            ("chests", "!chests / !chest:", default_templates.get("chests", "Chests: {stages} | Total: {opened}/{total} | Paid: {paid} | Key Procs: {procs}/{normal} ({proc_rate}) | Expected: {expected} | Free Chests: {free} | Keys: {keys} ({chance})"), "Tags: {stages}, {opened}, {total}, {paid}, {procs}, {normal}, {proc_rate}, {expected}, {free}, {keys}, {chance}"),
            ("luck", "!luck:", default_templates.get("luck", "Luck: {tiers}"), "Tags: {tiers} (one group per rarity, already joined)"),
            ("bonkhelp", "!bonkhelp / !bonkcmds:", default_templates.get("bonkhelp", "Available commands: {commands_list}"), "Tags: {commands_list}"),
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

        # -- !session section --
        # The tracked-item half of this section is gone: it was a copy of the
        # OBS one, both of them copies of the Session Stats picker, and all
        # three are one window now (`ui/dialogs/tracked_items`). What is left
        # here is the one thing that is genuinely about this command -- the
        # response template.
        twitch_tracked_group = CollapsibleSection(
            "!session Command Settings",
            expanded=False,
        )
        twitch_tracked_layout = twitch_tracked_group.body_layout
        twitch_tracked_layout.addWidget(
            QLabel(
                "Tracked item counters for !session are configured in the "
                "Tracked Items window, on the Session Stats tab."
            )
        )

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

        from core.item_metadata import ITEMS, ITEM_DISPLAY_NAME_BY_RAW_VALUE

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
                cb.setStyleSheet("color: #FB7185; font-weight: bold; background: transparent;")
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

        # The two One Ring rows are pools, one phrase per line, so they get a
        # `QPlainTextEdit` rather than the `QLineEdit` every other template uses
        # -- a pool in a single-line box is editable only by scrolling sideways
        # through it. They are registered in their own dict for the same reason:
        # `save`/`reset_to_defaults` walk `templates_entries` with `text()` and
        # `setText()`, which a plain-text edit does not have.
        announcers_form.addRow(
            "The One Ring:",
            self._build_pool_row(
                "one_ring_announcement",
                "One phrase per line, drawn at random, recent lines skipped. "
                "Tags: {streamer}, {stage}, {time} -- note that the bot usually "
                "posts from your own account, so a line naming {streamer} reads "
                "as you talking about yourself unless you run a separate bot "
                "account.",
            ),
        )
        announcers_form.addRow(
            "The One Ring (duplicate):",
            self._build_pool_row(
                "one_ring_duplicate_announcement",
                "Fires on the second ring and every one after it. "
                "Tags: {streamer}, {stage}, {time}, {count} -- and a line that "
                "names no count must stay true for any number of rings.",
            ),
        )

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

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        dialog_footer(
            self, primary=save_btn, secondary=cancel_btn, destructive=reset_btn
        )

        self._init_guard = False

    def _build_pool_row(self, template_key: str, help_text: str):
        """A multi-line template field plus its help line, as one form row."""
        entry = QPlainTextEdit(
            config.TWITCH_BOT.get("templates", {}).get(
                template_key,
                config.DEFAULT_TWITCH_BOT["templates"][template_key],
            )
        )
        # Tall enough for five or six phrases without scrolling, which is the
        # size the shipped pools actually are; past that it scrolls rather than
        # pushing the rest of the tab off screen.
        entry.setMinimumHeight(120)
        entry.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.template_pool_entries[template_key] = entry

        layout = QVBoxLayout()
        layout.addWidget(entry)
        help_label = QLabel(
            f"<span style='color: #9CA3AF; font-size: 11px;'>{help_text}</span>"
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        return layout

    def on_stat_toggled(self):
        if getattr(self, "_init_guard", False):
            return
        selected = [label for label, cb in self.stat_checkboxes.items() if cb.isChecked()]
        parts = [f"{abbreviate_stat_label(name)}: {{{name}}}" for name in selected]
        new_tpl = "Live Stats: " + " | ".join(parts)
        self.stats_tpl_entry.setText(new_tpl)

    def reset_to_defaults(self):
        self._init_guard = True
        default_selected = set(config.DEFAULT_TWITCH_BOT["selected_stats"])
        for label, cb in self.stat_checkboxes.items():
            cb.setChecked(label in default_selected)

        self.stats_tpl_entry.setText(config.DEFAULT_TWITCH_BOT["templates"]["stats"])

        for cb in self.disabled_item_checkboxes.values():
            cb.setChecked(False)

        # Tracked items are not reset here any more. This dialog no longer
        # edits them, and "Reset to Defaults" on a screen about templates and
        # command settings has no business wiping a list configured in another
        # window -- which it did silently, with nothing on screen to say so.

        defaults = config.DEFAULT_TWITCH_BOT["templates"]
        for key, entry in self.templates_entries.items():
            entry.setText(defaults.get(key, ""))
        for key, entry in self.template_pool_entries.items():
            entry.setPlainText(defaults.get(key, ""))
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

        for key, entry in self.template_pool_entries.items():
            # Only the outer whitespace: the newlines *are* the separators, and
            # `_pool_lines` on the bot strips and drops blanks per line anyway.
            config.TWITCH_BOT["templates"][key] = entry.toPlainText().strip()

        highlighted_disabled = [
            name for name, cb in self.disabled_item_checkboxes.items() if cb.isChecked()
        ]
        config.TWITCH_BOT["highlighted_disabled_items"] = highlighted_disabled
        config.TWITCH_BOT["commands_announcement_interval_minutes"] = (
            self.commands_announcement_interval_spin.value()
        )

        # The tracked-item block that stood here is gone with the widgets that
        # fed it. It also carried the one live bug in this file: the rebuild of
        # the tracker's rule set was guarded by
        # `hasattr(master, "_combined_tracked_item_rules")`, and that method is
        # `gui_overlay.Overlay`'s -- `master` is the application, whose
        # `__getattr__` forwards to its window and nowhere else. False in every
        # build, true in the one test that covered it, because the double was
        # handed the attribute. `TrackedItemSettings` owns that path now and has
        # no probe in it.
        config.TWITCH_BOT = config.normalize_twitch_bot_config(config.TWITCH_BOT)
        master = getattr(self, "master", None)
        if master is not None and hasattr(master, "_refresh_session_stats_snapshot"):
            # `!session` reads an immutable snapshot from its worker thread, so
            # a template edited here would otherwise not show until the next
            # reroll refreshed it.
            master._refresh_session_stats_snapshot()

        config.user_config["TWITCH_BOT"] = config.TWITCH_BOT
        config.save_config(config.user_config)
        self.accept()
