from __future__ import annotations

import html

from PySide6.QtWidgets import QCheckBox, QDialog, QMessageBox

import config
import logic
from gui_dialogs import DeleteDialog, HelpDialog, ScoresSettingsDialog, SettingsDialog, TemplateDialog, TemplateManagerDialog
from gui_shared import _clear_layout, _read_bool, _set_text, format_template_conditions
from gui_styles import COLOR_MAP, _template_checkbox_stylesheet, _tier_color

class TemplatesMixin:

    def refresh_scores_templates_list(self):
        _clear_layout(self.scores_templates_layout)
        self.scores_checkboxes.clear()
        for tier in ("Light", "Good", "Perfect", "Perfect+"):
            cb = QCheckBox(tier)
            cb.setChecked(tier in config.SCORES_SYSTEM.get("active_tiers", []))
            cb.setStyleSheet(f"color: {_tier_color(tier)}; font-weight: 700;")
            cb.toggled.connect(self.refresh_scores_ui)
            self.scores_templates_layout.addWidget(cb)
            self.scores_checkboxes[tier] = cb
        self.scores_templates_layout.addStretch(1)

    def refresh_scores_ui(self):
        if self.scores_desc_label is None:
            return
        active_tiers = [tier for tier, cb in self.scores_checkboxes.items() if cb.isChecked()]
        if active_tiers and active_tiers != config.SCORES_SYSTEM.get("active_tiers", []):
            config.SCORES_SYSTEM["active_tiers"] = active_tiers
            config.user_config["SCORES_SYSTEM"] = config.SCORES_SYSTEM
            config.save_config(config.user_config)
            self._sync_runtime_filters(announce=True)

        weights = config.SCORES_SYSTEM.get("weights", {})
        thresholds = config.SCORES_SYSTEM.get("thresholds", {})
        multipliers = config.SCORES_SYSTEM.get("multipliers", {}).get("microwave", {})
        lines = [
            "<b>Score system</b>",
            "",
            f"Active tiers: {', '.join(config.SCORES_SYSTEM.get('active_tiers', [])) or 'None'}",
            "",
            "<b>Thresholds</b>",
        ]
        for tier in ("Light", "Good", "Perfect", "Perfect+"):
            lines.append(f"{tier}: {thresholds.get(tier, 0.0)}")
        lines.extend(
            [
                "",
                "<b>Weights</b>",
                f"Moais: {weights.get('moais', 0.0)}",
                f"Shady: {weights.get('shady', 0.0)}",
                f"Boss: {weights.get('boss', 0.0)}",
                f"Magnet: {weights.get('magnet', 0.0)}",
                "",
                "<b>Microwave Multipliers</b>",
                f"1 Microwave: {multipliers.get('1', 1.0)}",
                f"2 Microwaves: {multipliers.get('2', 1.25)}",
            ]
        )
        self.scores_desc_label.setHtml("<br>".join(lines))

    def open_scores_settings_dialog(self):
        dialog = ScoresSettingsDialog(self.window)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_scores_templates_list()
            self.refresh_scores_ui()

    def save_checkbox_state(self, *_args):
        selected = [name for name, cb in self.checkboxes.items() if _read_bool(cb)]
        config.ACTIVE_TEMPLATES = selected
        config.user_config["ACTIVE_TEMPLATES"] = selected
        config.save_config(config.user_config)

        self._sync_runtime_filters(announce=True)

    def _is_main_loop_active(self) -> bool:
        scanner_thread = getattr(self, "scanner_thread", None)
        return scanner_thread is not None and scanner_thread.is_alive()

    def _get_selected_template_names(self) -> list[str]:
        checkboxes = getattr(self, "checkboxes", {})
        return [name for name, cb in checkboxes.items() if _read_bool(cb)]

    def _get_active_profile_names(self) -> list[str]:
        if config.EVALUATION_MODE == "templates":
            return self._get_selected_template_names()
        return list(config.SCORES_SYSTEM.get("active_tiers", []))

    def _sync_runtime_filters(self, *, announce: bool = False) -> None:
        active_names = self._get_active_profile_names()
        previous_names = list(getattr(self, "template_stats", {}).keys())

        if config.EVALUATION_MODE == "templates":
            self.active_templates = list(active_names)

        existing_stats = getattr(self, "template_stats", {})
        for name in active_names:
            existing_stats.setdefault(name, {"rerolls_since_last": 0, "history": []})
        self.template_stats = existing_stats

        if hasattr(self, "stats_avg_labels") and hasattr(self, "stats_avg_layout"):
            self.refresh_stats_ui()

        if not announce or not self._is_main_loop_active():
            return

        if active_names == previous_names:
            return

        mode_label = "tiers" if config.EVALUATION_MODE == "scores" else "templates"
        names_text = ", ".join(active_names) if active_names else "none"
        self.log(f"[*] Active {mode_label} updated live: {names_text}")

    def refresh_templates(self):
        _clear_layout(self.template_layout)
        self.checkboxes.clear()
        for template in config.TEMPLATES:
            color_tag = template.get("color", "LIGHTBLUE_EX").upper()
            color_hex = COLOR_MAP.get(color_tag, COLOR_MAP["DEFAULT"])
            cb = QCheckBox(self._format_template_checkbox_text(template))
            cb.setChecked(template["name"] in config.ACTIVE_TEMPLATES)
            cb.toggled.connect(self.save_checkbox_state)
            cb.setStyleSheet(_template_checkbox_stylesheet(color_hex))
            self.template_layout.addWidget(cb)
            self.checkboxes[template["name"]] = cb
        self.template_layout.addStretch(1)
        self._sync_runtime_filters(announce=True)

    def add_template_dialog(self):
        dialog = TemplateDialog(self.window)
        if dialog.exec() != QDialog.Accepted or dialog.result_payload is None:
            return
        payload = dialog.result_payload
        next_id = max([t.get("id", 0) for t in config.TEMPLATES] + [0]) + 1
        payload["id"] = next_id
        config.TEMPLATES = list(config.TEMPLATES) + [payload]
        config.user_config["TEMPLATES"] = config.TEMPLATES
        config.save_config(config.user_config)
        self.refresh_templates()

    def apply_template_edit(self, original_template: dict, updated_template: dict):
        for index, template in enumerate(config.TEMPLATES):
            if template.get("id") == original_template.get("id"):
                updated_template["id"] = original_template.get("id")
                config.TEMPLATES[index] = updated_template
                config.user_config["TEMPLATES"] = config.TEMPLATES
                config.ACTIVE_TEMPLATES = [
                    updated_template["name"] if name == original_template["name"] else name
                    for name in config.ACTIVE_TEMPLATES
                ]
                config.user_config["ACTIVE_TEMPLATES"] = config.ACTIVE_TEMPLATES
                config.save_config(config.user_config)
                self.refresh_templates()
                return True
        return False

    def edit_template_dialog(self):
        dialog = TemplateManagerDialog(self.window, config.TEMPLATES, self.apply_template_edit)
        dialog.exec()

    def del_template_dialog(self):
        custom_templates = [template for template in config.TEMPLATES if template.get("id", 0) > 7]
        if not custom_templates:
            QMessageBox.information(self.window, "No Custom Templates", "There are no custom templates to delete.")
            return
        dialog = DeleteDialog(self.window, custom_templates)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_templates()

    def open_settings_dialog(self):
        dialog = SettingsDialog(self.window, master=self)
        dialog.exec()

    def open_help_dialog(self):
        dialog = HelpDialog(self.window)
        dialog.exec()

    def _active_templates_require_bald_heads(self) -> bool:
        if config.EVALUATION_MODE != "templates":
            return False
        active_names = set(getattr(self, "active_templates", []) or [])
        if not active_names:
            return False
        return any(
            template.get("name") in active_names and int(template.get("bald_heads", 0) or 0) > 0
            for template in config.TEMPLATES
        )

    def format_stats(self, stats: dict) -> str:
        shady = stats.get("Shady Guy", 0)
        moai = stats.get("Moais", 0)
        microwaves = logic.template_microwaves(stats)
        boss = stats.get("Boss Curses", 0)
        magnet = stats.get("Magnet Shrines", 0)
        parts = [
            f"Shady: {shady}, Moai: {moai}, Microwaves: {microwaves}, "
            f"Boss: {boss}, Magnet: {magnet}"
        ]
        if self._active_templates_require_bald_heads():
            parts.append(f", Bald Heads: {stats.get('Bald Heads', 0)}")
        parts.append(f", Score: {logic.calculate_score(stats, config.SCORES_SYSTEM):.1f}")
        return "".join(parts)

    @staticmethod
    def _format_template_checkbox_text(template: dict) -> str:
        conditions = format_template_conditions(template)
        compact_conditions = (
            conditions
            .replace("S+M:", "S+M")
            .replace("Micro:", "Mic")
            .replace("Boss:", "Boss")
        )
        return f"{template['name']} ({compact_conditions})"

    @staticmethod
    def calculate_map_score(stats: dict) -> float:
        return logic.calculate_score(stats, config.SCORES_SYSTEM)

    def evaluate_candidate(self, stats: dict, *, context: dict | None = None) -> dict | None:
        if config.EVALUATION_MODE == "templates":
            return logic.find_matching_template(
                stats,
                self.active_templates,
                config.TEMPLATES,
                context=context,
            )
        return logic.evaluate_map_by_scores(stats, config.SCORES_SYSTEM)
