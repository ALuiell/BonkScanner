"""The Templates and Scores tabs: choosing which maps count as a hit.

Step 22c. `TemplatesMixin` was the last of the three things sharing
`gui_templates.py`; 22a took map evaluation to `app.map_scoring` and 22b took
the runtime filter state to `app.template_filters`. What is left is this: two
left-hand tabs, their checkboxes, and the four dialogs that edit them.

**It builds its own widgets.** `gui_layout._build_left_panel` built eight names
onto `MegabonkApp` -- `tab_templates`, `tab_scores`, `scrollable_templates`,
`template_layout`, `scores_templates_layout`, `scores_desc_label`, `checkboxes`,
`scores_checkboxes` -- and this module read them back off the shared `self`.
Measured before the move, exactly as steps 21c and 21d measured theirs: **none
of the eight has a production reader outside this module and the builder**.
Their only other mention was the `= None` line in `gui_app.__init__`. That is
what let them move whole rather than stay as app surface behind a port.
(`scores_templates_frame` had *only* the `= None` line -- it was never built at
all, and it is gone.)

**The dialogs are injected, not imported.** The layer table lets `ui/` import
`app`, `projections` and `core`, and `gui_dialogs` is none of those -- it is
still top-level. `ui/tabs/player_stats/recordings.py` reaches it through a
`TOPLEVEL_DEBT` entry, and that allowlist may only shrink. So the four dialog
factories and the "no custom templates" message come in as constructor
arguments from the composition root in `gui_layout`, which is top-level and may
import them freely. That is also the shape the roadmap asks for in as many
words: "shared dialogs and the parent window are passed as narrow UI
dependencies rather than discovered through `self`".

**It does not own the runtime filters.** `sync_filters` is a port onto
`app.template_filters.TemplateRuntimeFilters`. This panel reports *what is
checked*; that object decides what the scan loop runs with. The direction
matters: `gui_scanner` calls the filters, and the filters ask this panel through
`selected_template_names`, so no scanner call arrives here.

**It does not own the left tab bar.** `on_left_tab_changed` stays in
`gui_layout` -- the router is step 26's subject -- and `MegabonkApp` keeps thin
delegators for the two methods it calls on the app. Same finding and shape as
step 20g's two delegators and step 21's four.

`open_settings_dialog` and `open_help_dialog` are **not** here. They sat in
`gui_templates.py` and have nothing to do with templates: they hang off the
footer buttons, and `SettingsDialog(self.window, master=self)` hands the dialog
the *application*, which then reaches `master` for about ten things, several
under `hasattr`. Moving them here would have made `master` this panel and turned
those branches into silent misses -- hotkeys quietly not re-registering after a
settings save, green suite, no exception. That is the exact failure step 19
recorded. They are `MegabonkApp`'s methods now, where `master=self` still means
the app.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import config
from core.item_metadata import COLOR_MAP
from ui.shared import (
    _apply_button_icon,
    _clear_layout,
    _make_scroll_section,
    _read_bool,
    format_template_conditions,
)
from ui.styles import _template_checkbox_stylesheet, _tier_color


TIERS = ("Light", "Good", "Perfect", "Perfect+")

# Templates with an id at or below this are the shipped defaults and cannot be
# deleted. Lifted verbatim from `del_template_dialog`, where it was a bare 7.
LAST_BUILTIN_TEMPLATE_ID = 7


class TemplatesPanel:
    """The Templates and Scores tabs and the dialogs that edit them."""

    def __init__(
        self,
        *,
        left_tabview,
        window: Callable[[], object],
        sync_filters: Callable[..., None],
        template_dialog,
        template_manager_dialog,
        delete_dialog,
        scores_settings_dialog,
        no_custom_templates_message,
    ) -> None:
        self._left_tabview = left_tabview
        self._window = window
        self._sync_filters = sync_filters
        self._template_dialog = template_dialog
        self._template_manager_dialog = template_manager_dialog
        self._delete_dialog = delete_dialog
        self._scores_settings_dialog = scores_settings_dialog
        self._no_custom_templates_message = no_custom_templates_message

        self._tab_templates = None
        self._tab_scores = None
        self._scrollable_templates = None
        self._template_layout = None
        self._scores_templates_layout = None
        self._scores_desc_label = None
        self._checkboxes: dict[str, QCheckBox] = {}
        self._scores_checkboxes: dict[str, QCheckBox] = {}

    # -- construction ------------------------------------------------------

    def build(self) -> None:
        """Add both tabs to the left tab bar, in their original order.

        The ~35 lines this replaces were `gui_layout._build_left_panel`'s. The
        tab-bar *selection* is not set here: `_build_left_panel` still does it,
        because which tab opens is a question about the router, not the panel.
        """
        self._build_templates_tab()
        self._build_scores_tab()

    def _build_templates_tab(self) -> None:
        self._tab_templates = QWidget()
        templates_layout = QVBoxLayout(self._tab_templates)
        self._scrollable_templates, content, self._template_layout = _make_scroll_section()
        content.setObjectName("templateListSurface")
        self._scrollable_templates.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        templates_layout.addWidget(self._scrollable_templates, 1)

        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.add_btn.setObjectName("primary")
        _apply_button_icon(self.add_btn, "media/add_icon.svg", 18)
        self.add_btn.clicked.connect(self.add_template_dialog)
        self.edit_btn = QPushButton("Edit")
        _apply_button_icon(self.edit_btn, "media/edit_icon.svg", 18)
        self.edit_btn.clicked.connect(self.edit_template_dialog)
        self.del_btn = QPushButton("")
        self.del_btn.setObjectName("danger")
        self.del_btn.setToolTip("Delete")
        _apply_button_icon(self.del_btn, "media/delete_icon.svg", 18)
        self.del_btn.clicked.connect(self.del_template_dialog)
        buttons.addWidget(self.add_btn, 1)
        buttons.addWidget(self.edit_btn, 1)
        self.del_btn.setFixedWidth(44)
        buttons.addWidget(self.del_btn)
        templates_layout.addLayout(buttons)
        self._left_tabview.addTab(self._tab_templates, "Templates")

    def _build_scores_tab(self) -> None:
        self._tab_scores = QWidget()
        scores_layout = QVBoxLayout(self._tab_scores)
        scores_group = QGroupBox("Active Tiers")
        self._scores_templates_layout = QVBoxLayout(scores_group)
        scores_layout.addWidget(scores_group)
        self._scores_desc_label = QTextEdit()
        self._scores_desc_label.setReadOnly(True)
        scores_layout.addWidget(self._scores_desc_label, 1)

        buttons = QHBoxLayout()
        self.edit_scores_btn = QPushButton("Edit")
        _apply_button_icon(self.edit_scores_btn, "media/edit_icon.svg", 18)
        self.edit_scores_btn.clicked.connect(self.open_scores_settings_dialog)
        buttons.addWidget(self.edit_scores_btn, 1)
        scores_layout.addLayout(buttons)
        self._left_tabview.addTab(self._tab_scores, "Scores")

    # -- what the filters ask ----------------------------------------------

    def selected_template_names(self) -> list[str]:
        """The checked templates. `TemplateRuntimeFilters`' one question."""
        return [name for name, cb in self._checkboxes.items() if _read_bool(cb)]

    # -- templates tab ------------------------------------------------------

    def refresh_templates(self) -> None:
        _clear_layout(self._template_layout)
        self._checkboxes.clear()
        active_names = set(config.ACTIVE_TEMPLATES)
        for template in config.TEMPLATES:
            color_tag = template.get("color", "LIGHTBLUE_EX").upper()
            color_hex = COLOR_MAP.get(color_tag, COLOR_MAP["DEFAULT"])
            cb = QCheckBox(_format_template_checkbox_text(template))
            cb.setChecked(template["name"] in active_names)
            cb.toggled.connect(self.save_checkbox_state)
            cb.setStyleSheet(_template_checkbox_stylesheet(color_hex))
            self._template_layout.addWidget(cb)
            self._checkboxes[template["name"]] = cb
        self._template_layout.addStretch(1)
        self._sync_filters(announce=True)

    def save_checkbox_state(self, *_args) -> None:
        selected = self.selected_template_names()
        config.ACTIVE_TEMPLATES = selected
        config.user_config["ACTIVE_TEMPLATES"] = selected
        config.save_config(config.user_config)

        self._sync_filters(announce=True)

    def add_template_dialog(self) -> None:
        dialog = self._template_dialog(self._window())
        if dialog.exec() != QDialog.Accepted or dialog.result_payload is None:
            return
        payload = dialog.result_payload
        next_id = max([t.get("id", 0) for t in config.TEMPLATES] + [0]) + 1
        payload["id"] = next_id
        config.TEMPLATES = list(config.TEMPLATES) + [payload]
        config.user_config["TEMPLATES"] = config.TEMPLATES
        config.save_config(config.user_config)
        self.refresh_templates()

    def apply_template_edit(self, original_template: dict, updated_template: dict) -> bool:
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

    def edit_template_dialog(self) -> None:
        dialog = self._template_manager_dialog(
            self._window(), config.TEMPLATES, self.apply_template_edit
        )
        dialog.exec()

    def del_template_dialog(self) -> None:
        custom_templates = [
            template
            for template in config.TEMPLATES
            if template.get("id", 0) > LAST_BUILTIN_TEMPLATE_ID
        ]
        if not custom_templates:
            self._no_custom_templates_message(self._window())
            return
        dialog = self._delete_dialog(self._window(), custom_templates)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_templates()

    # -- scores tab ---------------------------------------------------------

    def refresh_scores_templates_list(self) -> None:
        _clear_layout(self._scores_templates_layout)
        self._scores_checkboxes.clear()
        for tier in TIERS:
            cb = QCheckBox(tier)
            cb.setChecked(tier in config.SCORES_SYSTEM.get("active_tiers", []))
            cb.setStyleSheet(f"color: {_tier_color(tier)}; font-weight: 700; background: transparent;")
            cb.toggled.connect(self.refresh_scores_ui)
            self._scores_templates_layout.addWidget(cb)
            self._scores_checkboxes[tier] = cb
        self._scores_templates_layout.addStretch(1)

    def refresh_scores_ui(self) -> None:
        if self._scores_desc_label is None:
            return
        active_tiers = [tier for tier, cb in self._scores_checkboxes.items() if cb.isChecked()]
        if active_tiers != config.SCORES_SYSTEM.get("active_tiers", []):
            config.SCORES_SYSTEM["active_tiers"] = active_tiers
            config.user_config["SCORES_SYSTEM"] = config.SCORES_SYSTEM
            config.save_config(config.user_config)
            self._sync_filters(announce=True)

        self._scores_desc_label.setHtml("<br>".join(_score_system_lines()))

    def open_scores_settings_dialog(self) -> None:
        dialog = self._scores_settings_dialog(self._window())
        if dialog.exec() == QDialog.Accepted:
            self.refresh_scores_templates_list()
            self.refresh_scores_ui()


# -- module-level, for the reason `ui/tabs/compare_runs/tab.py` states: a free
# function has no class to be orphaned from when its class moves, which is the
# failure mode step 14b hit and step 19 retired rather than relocated.


def _format_template_checkbox_text(template: dict) -> str:
    conditions = format_template_conditions(template)
    compact_conditions = (
        conditions
        .replace("S+M:", "S+M")
        .replace("Micro:", "Mic")
        .replace("Boss:", "Boss")
    )
    return f"{template['name']}\n{compact_conditions}"


def _score_system_lines() -> list[str]:
    """The scores description, as the HTML lines it is joined from."""
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
    for tier in TIERS:
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
    return lines
