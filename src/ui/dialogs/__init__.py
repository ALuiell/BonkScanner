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

``update_prompt.py`` moved in with it, out of ``ui/``. The update surface now
lives beside the shared dialog shell while the always-visible footer owns the
manual check action.
"""
from __future__ import annotations

import html
import re
import webbrowser
from copy import deepcopy
from functools import partial
from pathlib import Path

from ui.dialogs.shell import (
    DIALOG_COMPACT,
    DIALOG_REGULAR,
    DIALOG_TALL,
    DIALOG_WIDE,
    dialog_body,
    dialog_card,
    dialog_danger_card,
    dialog_footer,
    dialog_info_card,
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
from PySide6.QtGui import QColor, QIcon, QIntValidator, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QColorDialog,
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
from core.template_colors import (
    DEFAULT_TEMPLATE_COLOR,
    template_color_hex,
    template_color_hex_or_none,
)

from app import config
from app.player_stats_view import overlay_view, player_stats_view
from app.vod_capture import vod_capture

PATREON_SUPPORT_URL = config.PATREON_SUPPORT_URL
CRYPTO_SUPPORT_URL = config.CRYPTO_SUPPORT_URL
GITHUB_REPOSITORY_URL = config.GITHUB_REPOSITORY_URL
DISCORD_SUPPORT_URL = config.DISCORD_SUPPORT_URL
PATREON_ICON_PATH = "media/patreon_logo.svg"
CRYPTO_ICON_PATH = "media/crypto_coins.svg"
GITHUB_ICON_PATH = "media/github_logo.svg"
DISCORD_ICON_PATH = "media/discord_logo.svg"

class TemplateFormFrame(QWidget):
    def __init__(self, parent=None, template_data=None):
        super().__init__(parent)
        self.template_data = template_data or {}
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)

        self.name_entry = QLineEdit()
        layout.addWidget(QLabel("Template Name:"), 0, 0)
        layout.addWidget(self.name_entry, 0, 1, 1, 2)

        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._choose_color)
        self.reset_color_btn = QPushButton("Reset")
        self.reset_color_btn.clicked.connect(self._reset_color)
        color_row = QWidget()
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(8)
        color_layout.addWidget(self.color_btn, 1)
        color_layout.addWidget(self.reset_color_btn)
        layout.addWidget(QLabel("Color:"), 1, 0)
        layout.addWidget(color_row, 1, 1, 1, 2)

        self.sm_entry = QLineEdit()
        self.shady_entry = QLineEdit()
        self.moai_entry = QLineEdit()
        self.micro_entry = QLineEdit()
        self.boss_entry = QLineEdit()
        self.bald_heads_entry = QLineEdit()
        self.magnet_entry = QLineEdit()
        self.challenges_entry = QLineEdit()
        self.shady_max_entry = QLineEdit()
        self.moai_max_entry = QLineEdit()
        self.micro_max_entry = QLineEdit()
        self.boss_max_entry = QLineEdit()
        self.magnet_max_entry = QLineEdit()
        self.challenges_max_entry = QLineEdit()
        self.bald_heads_max_entry = QLineEdit()

        minimum_header = QLabel("MINIMUM")
        minimum_header.setObjectName("dialogHint")
        maximum_header = QLabel("MAXIMUM")
        maximum_header.setObjectName("dialogHint")
        layout.addWidget(minimum_header, 2, 1)
        layout.addWidget(maximum_header, 2, 2)

        no_total_maximum = QLabel("—")
        no_total_maximum.setObjectName("dialogHint")
        rows = (
            ("S+M Total", self.sm_entry, no_total_maximum),
            ("Shady Guy", self.shady_entry, self.shady_max_entry),
            ("Moais", self.moai_entry, self.moai_max_entry),
            ("Microwaves", self.micro_entry, self.micro_max_entry),
            ("Boss Curses", self.boss_entry, self.boss_max_entry),
            ("Magnets", self.magnet_entry, self.magnet_max_entry),
            ("Challenges", self.challenges_entry, self.challenges_max_entry),
            ("Bald Heads", self.bald_heads_entry, self.bald_heads_max_entry),
        )
        integer_validator = QIntValidator(0, 999, self)
        for row_index, (caption, minimum_entry, maximum_entry) in enumerate(rows, start=3):
            minimum_entry.setValidator(integer_validator)
            layout.addWidget(QLabel(caption), row_index, 0)
            layout.addWidget(minimum_entry, row_index, 1)
            layout.addWidget(maximum_entry, row_index, 2)
            if isinstance(maximum_entry, QLineEdit):
                maximum_entry.setValidator(integer_validator)
                maximum_entry.setPlaceholderText("No limit")

        maximum_note = QLabel("Maximum: empty = no limit; 0 = none allowed.")
        maximum_note.setObjectName("dialogHint")
        layout.addWidget(maximum_note, len(rows) + 3, 1, 1, 2)

        self.sm_entry.textChanged.connect(self._sync_sm_fields)
        self.shady_entry.textChanged.connect(self._sync_sm_fields)
        self.moai_entry.textChanged.connect(self._sync_sm_fields)
        self.load_template(self.template_data)

    def load_template(self, template_data=None):
        self.template_data = template_data or {}
        self._default_color = self._default_color_for(self.template_data)
        candidate = str(self.template_data.get("color") or self._default_color)
        self._color_value = (
            candidate if template_color_hex_or_none(candidate) is not None else self._default_color
        )
        self._refresh_color_button()
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
        self.challenges_entry.setText(str(self.template_data.get("challenges", 0)))
        self.bald_heads_entry.setText(str(self.template_data.get("bald_heads", 0)))
        for key, widget in (
            ("shady_max", self.shady_max_entry),
            ("moai_max", self.moai_max_entry),
            ("micro_max", self.micro_max_entry),
            ("boss_max", self.boss_max_entry),
            ("magnet_max", self.magnet_max_entry),
            ("challenges_max", self.challenges_max_entry),
            ("bald_heads_max", self.bald_heads_max_entry),
        ):
            value = self.template_data.get(key)
            widget.setText("" if value is None else str(value))
        for widget in (self.sm_entry, self.shady_entry, self.moai_entry):
            widget.blockSignals(False)
        self._sync_sm_fields()

    @staticmethod
    def _default_color_for(template_data: dict) -> str:
        template_id = template_data.get("id")
        for default in config.DEFAULT_TEMPLATES:
            if default.get("id") == template_id:
                return str(default.get("color") or DEFAULT_TEMPLATE_COLOR)
        return DEFAULT_TEMPLATE_COLOR

    def _refresh_color_button(self) -> None:
        color_hex = template_color_hex(self._color_value)
        swatch = QPixmap(18, 18)
        swatch.fill(QColor(color_hex))
        self.color_btn.setIcon(QIcon(swatch))
        self.color_btn.setText(color_hex.upper())
        self.color_btn.setToolTip("Choose template color")

    def _choose_color(self) -> None:
        selected = QColorDialog.getColor(
            QColor(template_color_hex(self._color_value)),
            self,
            "Choose Template Color",
        )
        if not selected.isValid():
            return
        self._color_value = selected.name(QColor.HexRgb).upper()
        self._refresh_color_button()

    def _reset_color(self) -> None:
        self._color_value = self._default_color
        self._refresh_color_button()

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
        payload = build_template_payload(
            self.name_entry.text(),
            self.sm_entry.text(),
            self.shady_entry.text(),
            self.moai_entry.text(),
            self.micro_entry.text(),
            self.boss_entry.text(),
            self.bald_heads_entry.text(),
            self.magnet_entry.text(),
            source_template=self.template_data,
            challenges=self.challenges_entry.text(),
            shady_max=self.shady_max_entry.text(),
            moai_max=self.moai_max_entry.text(),
            micro_max=self.micro_max_entry.text(),
            boss_max=self.boss_max_entry.text(),
            magnet_max=self.magnet_max_entry.text(),
            challenges_max=self.challenges_max_entry.text(),
            bald_heads_max=self.bald_heads_max_entry.text(),
        )
        if payload is not None:
            payload["color"] = self._color_value
        return payload


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
            subtitle="Minimum 0 is ignored. Leave Maximum empty for no limit.",
            width=DIALOG_WIDE,
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
            QMessageBox.warning(
                self,
                "Invalid Template",
                "Enter a template name and make sure no minimum is greater than its maximum.",
            )
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
            # The expanded form almost fills the 720 px viewport. Give its
            # Save button enough room to remain fully visible after the card
            # is scrolled into view.
            height=DIALOG_TALL + 15,
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
            QMessageBox.warning(
                self,
                "Invalid Template",
                "Enter a template name and make sure no minimum is greater than its maximum.",
            )
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


class ScoresHelpDialog(QDialog):
    """In-app explanation of score calculation and tier behaviour."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("How Scores Work")
        self.setModal(True)

        outer = dialog_body(
            self,
            title="How Scores Work",
            subtitle="A step-by-step guide to what the scanner counts and why a map passes or fails.",
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )
        scroll, _scroll_content, scroll_layout = _make_scroll_section()
        outer.addWidget(scroll, 1)

        scroll_layout.addWidget(
            dialog_info_card(
                "<b>1. What is Score?</b><br><br>"
                "Score is one number that represents how valuable the generated map "
                "is according to <i>your</i> settings. The scanner counts Moais, "
                "Shady Guys, Boss Curses, Magnet Shrines, and Challenges. Each count "
                "is converted into points, then all points are added together."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>2. What does each Shrine Points value mean?</b><br><br>"
                "The number beside a shrine is the amount added for <b>each</b> one "
                "found on the map.<br><br>"
                "&bull; <b>Positive value:</b> you want this shrine. For example, "
                "Moais = 3 means every Moai adds 3 points. Four Moais add 12.<br>"
                "&bull; <b>Zero:</b> this shrine does not change Score. It is still "
                "shown in map statistics, but whether the map has zero or ten makes "
                "no difference to Scores mode.<br>"
                "&bull; <b>Negative value:</b> you do not want this shrine. For "
                "example, Challenges = -3 means every Challenge removes 3 points. "
                "Two Challenges remove 6.<br><br>"
                "All five Shrine Points fields accept positive, zero, and negative values."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>3. How is the base score calculated?</b><br><br>"
                "For every shrine type, the scanner multiplies the map count by its "
                "configured Shrine Points value:<br><br>"
                "<b>Base Score =</b><br>"
                "(Moais &times; Moai points)<br>"
                "+ (Shady Guys &times; Shady points)<br>"
                "+ (Boss Curses &times; Boss points)<br>"
                "+ (counted Magnets &times; Magnet points)<br>"
                "+ (Challenges &times; Challenge points)<br><br>"
                "Negative results are simply subtracted. A penalty is <b>soft</b>: "
                "it lowers the number, but it never rejects a map by itself. Enough "
                "positive shrines can compensate for it."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>4. The special Magnet rule</b><br><br>"
                "Magnet rewards and Magnet penalties are counted differently:<br><br>"
                "&bull; If Magnet points are positive, only the first two Magnet "
                "Shrines add points. A third or fourth Magnet adds nothing.<br>"
                "&bull; If Magnet points are zero, Magnets do not affect Score.<br>"
                "&bull; If Magnet points are negative, <b>every</b> Magnet Shrine "
                "removes points. Five unwanted Magnets receive five penalties."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>5. When is the Microwave multiplier applied?</b><br><br>"
                "The scanner first finishes the entire Base Score calculation, "
                "including every reward and penalty. Only then is the whole result "
                "multiplied by the Microwave value.<br><br>"
                "<b>Final Score = Base Score &times; Microwave Multiplier</b><br><br>"
                "This means the multiplier affects penalties too. A Base Score of 24 "
                "with a 1.25 multiplier becomes a Final Score of 30."
            )
        )
        scroll_layout.addWidget(
            dialog_info_card(
                "<b>6. Full example</b><br><br>"
                "Settings: Moai = 3, Shady = 2, Boss = 1, Magnet = -1, "
                "Challenges = -3, and the two-Microwave multiplier = 1.25.<br><br>"
                "Map: 4 Moais, 5 Shady Guys, 3 Boss Curses, 1 Magnet, "
                "0 Challenges, and 2 Microwaves.<br><br>"
                "Moais: 4 &times; 3 = 12<br>"
                "Shady Guys: 5 &times; 2 = 10<br>"
                "Boss Curses: 3 &times; 1 = 3<br>"
                "Magnet: 1 &times; -1 = -1<br>"
                "Challenges: 0 &times; -3 = 0<br><br>"
                "Base Score: 12 + 10 + 3 - 1 + 0 = <b>24</b><br>"
                "Final Score: 24 &times; 1.25 = <b>30</b>"
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>7. What are thresholds and active tiers?</b><br><br>"
                "A threshold is the minimum Final Score needed for a tier. If Light "
                "is 14, a map with 13.9 fails Light and a map with 14 passes it.<br><br>"
                "Only enabled tiers can stop the scanner. The scanner stops as soon "
                "as the map reaches <b>any enabled tier</b>. Enabling Light means a "
                "Light-or-better map may stop the scan; enabling every tier does not "
                "make the scanner wait specifically for Perfect+."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>8. Extra Perfect and Perfect+ requirements</b><br><br>"
                "Reaching the number alone is not always enough:<br><br>"
                "&bull; <b>Perfect+:</b> the score must reach its threshold and the "
                "map must have at least 2 Microwaves.<br>"
                "&bull; <b>Perfect:</b> the score must reach its threshold and the map "
                "must have either 2 Microwaves, or 1 Microwave together with at least "
                "8 total Shady Guys + Moais and at least 2 Boss Curses.<br>"
                "&bull; <b>Good and Light:</b> only their score threshold is checked."
            )
        )
        scroll_layout.addWidget(
            dialog_card(
                "<b>9. Automatic vs Manual Thresholds</b><br><br>"
                "<b>Automatic Thresholds</b> scale the tier targets when you change "
                "positive Shrine Points. Negative values are excluded from this "
                "scaling, so making a penalty stronger never makes the target easier.<br><br>"
                "If every Shrine Points value is zero or negative, automatic targets "
                "cannot be calculated usefully. Add at least one positive value or "
                "enable <b>Manual Thresholds</b> and enter the tier targets yourself."
            )
        )
        scroll_layout.addWidget(
            dialog_note(
                "Templates mode is separate. Template maximums are hard conditions; "
                "negative Shrine Points in Scores mode are only soft penalties."
            )
        )
        scroll_layout.addStretch(1)

        close_btn = QPushButton("Got It")
        close_btn.clicked.connect(self.accept)
        dialog_footer(self, primary=close_btn)


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

        weight_group = QGroupBox("Shrine Points")
        weight_layout = QFormLayout(weight_group)
        point_labels = {
            "moais": "Moais",
            "shady": "Shady",
            "boss": "Boss",
            "magnet": "Magnet",
            "challenges": "Challenges",
        }
        for key, label in point_labels.items():
            entry = QLineEdit(str(config.SCORES_SYSTEM.get("weights", {}).get(key, 0)))
            entry.setToolTip(
                "Positive values add score, zero has no effect, and negative values subtract score."
            )
            self.weight_entries[key] = entry
            weight_layout.addRow(f"{label}:", entry)
        points_note = QLabel(
            "Positive values add score. Zero means the shrine count does not affect Score. "
            "Negative values subtract score."
        )
        points_note.setWordWrap(True)
        weight_layout.addRow(points_note)
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

        weights = {key: _safe_float(entry.text(), 0.0) for key, entry in self.weight_entries.items()}
        multipliers = {key: _safe_float(entry.text(), 1.0) for key, entry in self.multiplier_entries.items()}
        manual_thresholds = self.manual_thresholds_var.isChecked()

        if any(value <= 0 for value in multipliers.values()):
            QMessageBox.warning(self, "Invalid Settings", "Microwave multipliers must be greater than zero.")
            return
        if not manual_thresholds and not any(value > 0 for value in weights.values()):
            QMessageBox.warning(
                self,
                "Invalid Settings",
                "Automatic thresholds need at least one positive Shrine Points value. "
                "Add a positive value or enable Manual Thresholds.",
            )
            return

        scores_system = {
            "manual_thresholds": manual_thresholds,
            "base_target_score": config.SCORES_SYSTEM.get("base_target_score", 30.0),
            "weights": weights,
            "multipliers": {
                "microwave": multipliers,
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
    def __init__(self, parent, templates):
        super().__init__(parent)
        self.templates = list(templates)
        self.checks: dict[int, QCheckBox] = {}
        self.setWindowTitle("Delete Templates")
        layout = dialog_body(
            self,
            title="Delete Templates",
            subtitle="Tick templates to remove. Built-ins can be restored later.",
            width=DIALOG_REGULAR,
        )
        scroll, _content, scroll_layout = _make_scroll_section()
        layout.addWidget(scroll, 1)
        builtin_ids = {template.get("id") for template in config.DEFAULT_TEMPLATES}
        for template in self.templates:
            suffix = "  •  Built-in" if template.get("id") in builtin_ids else ""
            cb = QCheckBox(f"{template['name']}{suffix}")
            self.checks[template["id"]] = cb
            scroll_layout.addWidget(cb)
        if not self.templates:
            empty_label = QLabel("No templates in the list.")
            empty_label.setObjectName("dialogNote")
            scroll_layout.addWidget(empty_label)
        scroll_layout.addStretch(1)
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self.delete)
        restore_btn = QPushButton("Restore Built-ins")
        restore_btn.setEnabled(bool(self._missing_builtins()))
        restore_btn.clicked.connect(self.restore_builtins)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        # `QDialogButtonBox` is gone with it: it put Delete next to Cancel and
        # ordered them by platform convention, which is the one thing a shared
        # footer cannot let a dialog decide for itself.
        dialog_footer(
            self,
            secondary=cancel_btn,
            destructive=delete_btn,
            leading=restore_btn,
        )

    def _missing_builtins(self) -> list[dict]:
        current_ids = {template.get("id") for template in config.TEMPLATES}
        return [
            dict(template)
            for template in config.DEFAULT_TEMPLATES
            if template.get("id") not in current_ids
        ]

    def restore_builtins(self):
        missing = self._missing_builtins()
        if not missing:
            return
        # Restored rows are intentionally inactive: restoring appearance should
        # not change what a running scanner accepts without an explicit check.
        config.TEMPLATES = list(config.TEMPLATES) + missing
        config.user_config["TEMPLATES"] = config.TEMPLATES
        config.save_config(config.user_config)
        self.accept()

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

    def __init__(
        self,
        parent,
        *,
        default_threshold: int | None = None,
        recordings=(),
    ):
        super().__init__(parent)
        self.threshold: int | None = None
        self.recordings = tuple(recordings)
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
        self.confirm_btn = QPushButton("Remove")
        self.confirm_btn.clicked.connect(self.confirm)
        self.threshold_entry.textChanged.connect(self._refresh_removal_count)
        dialog_footer(self, secondary=cancel_btn, destructive=self.confirm_btn)
        self._refresh_removal_count()

    def _refresh_removal_count(self, _text: str = "") -> None:
        try:
            threshold = int(float(_read_text(self.threshold_entry)))
        except ValueError:
            self.confirm_btn.setText("Remove")
            self.confirm_btn.setEnabled(False)
            return

        if threshold < 0:
            self.confirm_btn.setText("Remove")
            self.confirm_btn.setEnabled(False)
            return

        count = sum(
            1
            for recording in self.recordings
            if int(recording.snapshot_count) < threshold
        )
        noun = "recording" if count == 1 else "recordings"
        self.confirm_btn.setText(f"Remove {count} {noun}")
        self.confirm_btn.setEnabled(count > 0)

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


class AutoRerollSetupGuideDialog(QDialog):
    """Versioned setup guide shown after meaningful Auto-Reroll changes."""

    def __init__(self, parent):
        super().__init__(parent)
        self.acknowledged = False
        self.setWindowTitle("Auto-Reroll Setup")
        self.setModal(True)
        margin = config.RESET_HOLD_SAFETY_MARGIN
        minimum_hold = config.minimum_reset_hold_duration(margin)
        minimum_game_value = config.reset_hold_duration_to_game_value(
            minimum_hold,
            safety_margin=margin,
        )
        example_margin = min(config.MAX_RESET_HOLD_SAFETY_MARGIN, margin + 0.02)

        layout = dialog_body(
            self,
            title="Configure Auto-Reroll",
            subtitle=(
                "To configure BonkScanner's Auto-Reroll feature correctly, make "
                "these small changes in Megabonk's game settings."
            ),
            width=DIALOG_WIDE,
        )
        layout.addWidget(
            dialog_card(
                "Open <b>Settings &rarr; Game</b> in Megabonk and make sure these "
                "settings are <b>ON</b>:"
                "<br><br><b>Quick Reset</b>"
                "<br><b>Skip Portal Animation</b>"
                "<br><b>Super Quick Resets</b>"
            )
        )
        layout.addWidget(
            dialog_card(
                "<b>Reset speed</b><br><br>"
                "The old <b>0.10 s minimum has been removed</b>. Reset Hold Duration "
                "can now be set below 0.10 s to make restarts faster.<br><br>"
                "Reset Hold Duration controls how long BonkScanner holds the reset key. "
                "Safety Margin is the extra hold time between Megabonk's reset threshold "
                "and the moment BonkScanner releases the key. Lowering the margin lets "
                "you use a shorter scanner hold; BonkScanner calculates and synchronizes "
                "the corresponding Megabonk value automatically.<br><br>"
                f"With the current <b>{margin:.2f}-second safety margin</b>, the lowest "
                f"available scanner hold is <b>{minimum_hold:.2f} s</b>."
                f"<br><br><b>BonkScanner:</b> {minimum_hold:.2f} s &nbsp;&rarr;&nbsp; "
                f"<b>Megabonk:</b> {minimum_game_value:.2f} s"
                "<br><br>Close Megabonk before saving Reset Speed. BonkScanner verifies "
                "both config files before applying the new value."
            )
        )
        layout.addWidget(
            dialog_danger_card(
                "<b>Experimental tuning</b><br><br>"
                "Values below 0.10 s can improve restart speed, but very low Reset Hold "
                "Duration or Safety Margin values may release R before the game reliably "
                "registers the reset. The best minimum can vary with game performance and "
                "system timing.<br><br>"
                "If Auto-Reroll presses R but the run does not restart, check Reset "
                "Hold Duration and Safety Margin in BonkScanner Settings first.<br><br>"
                "Before Auto-Reroll starts, BonkScanner compares the configured hold "
                "duration with Megabonk's <b>quick_reset_time</b>. If the game requires "
                "a longer hold, BonkScanner automatically raises its value while "
                "preserving the safety margin.<br><br>"
                "If resets still do not register after the automatic adjustment, increase "
                "the advanced <b>Safety Margin</b> field in Settings &mdash; for example, from "
                f"<b>{margin:.2f}</b> to <b>{example_margin:.2f}</b>.<br><br>"
                "<b>Megabonk's game config:</b> %USERPROFILE%\\&#8203;AppData\\&#8203;"
                "LocalLow\\&#8203;Ved\\&#8203;Megabonk\\&#8203;Saves\\&#8203;"
                "LocalDir\\&#8203;config.json"
            )
        )

        got_it_btn = QPushButton("Got it")
        got_it_btn.clicked.connect(self.confirm)
        dialog_footer(self, primary=got_it_btn)

    def confirm(self) -> None:
        self.acknowledged = True
        self.accept()


class GameResetTimeNoticeDialog(QDialog):
    """App-styled, explicit outcome of the verified Reset Speed transaction."""

    def __init__(
        self,
        parent,
        *,
        saved: bool,
        reason: str = "",
        scanner_hold: float | None = None,
        game_value: float | None = None,
        margin: float | None = None,
    ):
        super().__init__(parent)
        self.setModal(True)

        if saved:
            self.setWindowTitle("Settings Saved")
            layout = dialog_body(
                self,
                title="Reset hold saved",
                width=DIALOG_REGULAR,
            )
            value_summary = ""
            if scanner_hold is not None and game_value is not None and margin is not None:
                value_summary = (
                    f"<br><br><b>BonkScanner hold:</b> {scanner_hold:.2f} s"
                    f"<br><b>Megabonk quick reset:</b> {game_value:.2f} s"
                    f"<br><b>Safety margin:</b> {margin:.2f} s"
                )
            layout.addWidget(
                dialog_info_card(
                    "Reset Speed was written to and verified in both config files."
                    f"{value_summary}"
                    "<br><br>The value will be active the next time Megabonk starts."
                )
            )
        else:
            self.setWindowTitle("Settings Not Saved")
            layout = dialog_body(
                self,
                title="Could not save settings",
                width=DIALOG_REGULAR,
            )
            layout.addWidget(
                dialog_card(
                    "BonkScanner did not apply the new settings because the complete "
                    "save could not be verified.<br><br>"
                    f"<b>Reason:</b> {html.escape(reason or 'The change could not be verified.')}"
                    "<br><br>Correct the problem and press Save again."
                )
            )

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

        self.reset_hold_safety_margin_entry = QDoubleSpinBox()
        self.reset_hold_safety_margin_entry.setRange(
            0.0,
            config.MAX_RESET_HOLD_SAFETY_MARGIN,
        )
        self.reset_hold_safety_margin_entry.setSingleStep(0.01)
        self.reset_hold_safety_margin_entry.setDecimals(2)
        self.reset_hold_safety_margin_entry.setValue(
            float(config.RESET_HOLD_SAFETY_MARGIN)
        )
        self.reset_hold_safety_margin_entry.setSuffix(" s")
        self.reset_hold_safety_margin_entry.setMaximumWidth(_SETTINGS_FIELD_WIDTH)
        self.reset_hold_safety_margin_entry.setToolTip(
            "Extra time BonkScanner holds R beyond Megabonk's own threshold. "
            "Lower values are faster but leave less tolerance for timing variation."
        )

        self.reset_hold_duration_entry = QDoubleSpinBox()
        self.reset_hold_duration_entry.setRange(
            config.minimum_reset_hold_duration(
                self.reset_hold_safety_margin_entry.value()
            ),
            config.MAX_RESET_HOLD_DURATION,
        )
        self.reset_hold_duration_entry.setCorrectionMode(
            QAbstractSpinBox.CorrectionMode.CorrectToNearestValue
        )
        self.reset_hold_duration_entry.setSingleStep(0.01)
        self.reset_hold_duration_entry.setDecimals(2)
        self.reset_hold_duration_entry.setValue(float(config.RESET_HOLD_DURATION))
        self.reset_hold_duration_entry.setSuffix(" s")
        self.reset_hold_duration_entry.setMaximumWidth(_SETTINGS_FIELD_WIDTH)
        self.reset_hold_duration_entry.setToolTip(
            "How long BonkScanner physically holds the reset key."
        )
        self._initial_reset_hold_duration = round(float(config.RESET_HOLD_DURATION), 2)
        self._initial_reset_hold_safety_margin = round(
            float(config.RESET_HOLD_SAFETY_MARGIN),
            2,
        )

        self.reset_game_value_label = QLabel()
        self.reset_game_value_label.setObjectName("rowValue")
        self.reset_game_value_label.setMinimumWidth(_SETTINGS_FIELD_WIDTH)
        self.reset_game_value_label.setToolTip(
            "The quick_reset_time value BonkScanner will write to Megabonk. "
            "It is Reset Hold minus Safety Margin."
        )

        self.record_interval_entry = QSpinBox()
        self.record_interval_entry.setRange(
            0,
            3600,
        )
        self.record_interval_entry.setSingleStep(5)
        self.record_interval_entry.setValue(
            int(
                getattr(
                    config,
                    "PLAYER_STATS_RECORD_INTERVAL_SECONDS",
                    config.DEFAULT_PLAYER_STATS_RECORD_INTERVAL_SECONDS,
                )
            )
        )
        self.record_interval_entry.setSuffix(" s")
        self.record_interval_entry.setMaximumWidth(_SETTINGS_FIELD_WIDTH)
        self.record_interval_entry.setToolTip(
            "Recording snapshots use the full player-state read, which runs every "
            f"{config.MIN_RECORDING_SNAPSHOT_INTERVAL_SECONDS} seconds. Lower input "
            "is corrected to that minimum."
        )
        self.record_interval_entry.editingFinished.connect(
            self._normalize_record_interval_entry
        )

        layout.addWidget(_settings_group_label("Timing"))
        reset_hold_note = QLabel(
            "Close Megabonk before changing Reset Speed. The game value is calculated "
            "for you and both config files are verified when you save. Safety margin "
            "is an advanced setting: lower is faster, but less tolerant."
        )
        reset_hold_note.setObjectName("dialogHint")
        reset_hold_note.setWordWrap(True)
        layout.addWidget(reset_hold_note)
        layout.addLayout(
            _settings_grid(
                (
                    ("Reset hold:", self.reset_hold_duration_entry),
                    ("Snapshot every:", self.record_interval_entry),
                    ("Safety margin:", self.reset_hold_safety_margin_entry),
                    ("Game quick reset:", self.reset_game_value_label),
                )
            )
        )
        self.reset_timing_status_label = QLabel()
        self.reset_timing_status_label.setObjectName("dialogHint")
        self.reset_timing_status_label.setWordWrap(True)
        layout.addWidget(self.reset_timing_status_label)
        self.reset_hold_duration_entry.valueChanged.connect(
            self._refresh_reset_timing_preview
        )
        self.reset_hold_safety_margin_entry.valueChanged.connect(
            self._refresh_reset_timing_preview
        )
        self._refresh_reset_timing_preview()

        layout.addWidget(_settings_group_label("Auto-Reroll"))
        self.stop_scanning_on_player_movement_var = QCheckBox(
            "Stop scanning when player moves"
        )
        self.stop_scanning_on_player_movement_var.setChecked(
            bool(getattr(config, "STOP_SCANNING_ON_PLAYER_MOVEMENT", True))
        )
        self.stop_scanning_on_player_movement_var.setToolTip(
            "While Auto-Reroll is active, pressing W, A, S, D or Space pauses it immediately."
        )
        layout.addWidget(self.stop_scanning_on_player_movement_var)

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
        self.crypto_btn = QPushButton("Crypto")
        self.crypto_btn.setObjectName("CryptoButton")
        self.crypto_btn.setIcon(QIcon(resource_path(CRYPTO_ICON_PATH)))
        self.crypto_btn.setIconSize(QSize(18, 18))
        self.crypto_btn.clicked.connect(self.open_crypto_support_page)
        self.crypto_btn.setProperty("class", "SupportPlatformButton")
        self.crypto_btn.setEnabled(bool(CRYPTO_SUPPORT_URL))
        if not CRYPTO_SUPPORT_URL:
            self.crypto_btn.setToolTip("Crypto support page is coming soon.")
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
        # the surplus behind them, which read as buttons that had run out of
        # room rather than a complete row.
        for button in (
            self.patreon_btn,
            self.crypto_btn,
            self.github_btn,
            self.discord_btn,
        ):
            support_button_row.addWidget(button, 1)
        support_layout.addLayout(support_button_row)
        layout.addWidget(support_card)

        # Update checking lives in the always-visible footer. Settings keeps one
        # clear job and one primary action instead of duplicating that control.
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        dialog_footer(self, primary=self.save_btn, secondary=cancel_btn)

    def reload_from_config(self) -> None:
        """Discard unsaved edits before reopening the reusable dialog."""
        self.hotkey_entry.setText(str(config.HOTKEY))
        self.reset_hotkey_entry.setText(str(config.RESET_HOTKEY))
        self.record_hotkey_entry.setText(
            str(getattr(config, "PLAYER_STATS_RECORD_HOTKEY", "f8"))
        )
        self.overlay_edit_hotkey_entry.setText(
            str(getattr(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9") or "f9")
        )
        reset_hold_safety_margin = round(
            float(config.RESET_HOLD_SAFETY_MARGIN),
            2,
        )
        self.reset_hold_safety_margin_entry.setValue(reset_hold_safety_margin)
        self.reset_hold_duration_entry.setMinimum(
            config.minimum_reset_hold_duration(reset_hold_safety_margin)
        )
        reset_hold_duration = max(
            config.minimum_reset_hold_duration(reset_hold_safety_margin),
            round(float(config.RESET_HOLD_DURATION), 2),
        )
        self.reset_hold_duration_entry.setValue(reset_hold_duration)
        self._initial_reset_hold_duration = reset_hold_duration
        self._initial_reset_hold_safety_margin = reset_hold_safety_margin
        self.record_interval_entry.setValue(
            int(
                getattr(
                    config,
                    "PLAYER_STATS_RECORD_INTERVAL_SECONDS",
                    config.DEFAULT_PLAYER_STATS_RECORD_INTERVAL_SECONDS,
                )
            )
        )
        self.stop_scanning_on_player_movement_var.setChecked(
            bool(getattr(config, "STOP_SCANNING_ON_PLAYER_MOVEMENT", True))
        )
        self.auto_start_recording_var.setChecked(
            bool(getattr(config, "AUTO_START_RECORDING", False))
        )
        self.show_obs_reminder_on_start_scanner_var.setChecked(
            bool(getattr(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False))
        )
        self._refresh_reset_timing_preview()

    def _normalize_record_interval_entry(self) -> None:
        self.record_interval_entry.setValue(
            max(
                config.MIN_RECORDING_SNAPSHOT_INTERVAL_SECONDS,
                self.record_interval_entry.value(),
            )
        )

    def _detect_game_running(self) -> tuple[bool, str]:
        detector = getattr(self.master, "is_game_running", None)
        if not callable(detector):
            return False, ""
        try:
            return bool(detector()), ""
        except Exception as exc:
            return True, f"BonkScanner could not check whether Megabonk is running: {exc}"

    def _refresh_reset_timing_preview(self, *_args) -> None:
        margin = config.normalize_reset_hold_safety_margin(
            self.reset_hold_safety_margin_entry.value()
        )
        minimum_hold = config.minimum_reset_hold_duration(margin)
        self.reset_hold_duration_entry.setMinimum(minimum_hold)
        scanner_hold = max(
            minimum_hold,
            round(float(self.reset_hold_duration_entry.value()), 2),
        )
        game_value = config.reset_hold_duration_to_game_value(
            scanner_hold,
            safety_margin=margin,
        )
        self.reset_game_value_label.setText(f"{game_value:.2f} s")

        game_running, detection_error = self._detect_game_running()
        game_read = config.read_game_quick_reset_time()
        if detection_error:
            status = detection_error
        elif game_running:
            status = "Megabonk is running. Close it before saving Reset Speed changes."
        elif not game_read.success or game_read.value is None:
            status = game_read.reason or "Megabonk quick_reset_time could not be read."
        elif round(float(game_read.value), 2) == game_value:
            status = "Scanner and Megabonk reset values are in sync."
        else:
            status = (
                f"Megabonk currently uses {game_read.value:.2f} s. "
                f"Save will update it to {game_value:.2f} s."
            )
        self.reset_timing_status_label.setText(status)

    def open_patreon_support_page(self):
        webbrowser.open(PATREON_SUPPORT_URL)

    def open_crypto_support_page(self):
        if CRYPTO_SUPPORT_URL:
            webbrowser.open(CRYPTO_SUPPORT_URL)

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
        movement_checkbox = getattr(
            self, "stop_scanning_on_player_movement_var", None
        )
        stop_scanning_on_player_movement = (
            bool(getattr(config, "STOP_SCANNING_ON_PLAYER_MOVEMENT", True))
            if movement_checkbox is None
            else _read_bool(movement_checkbox)
        )

        def _read_numeric(entry) -> float:
            if entry is None:
                return 0.0
            if hasattr(entry, "value"):
                val = entry.value
                return float(val() if callable(val) else val)
            return float(_read_text(entry))

        try:
            margin_entry = getattr(self, "reset_hold_safety_margin_entry", None)
            new_margin = config.normalize_reset_hold_safety_margin(
                config.RESET_HOLD_SAFETY_MARGIN
                if margin_entry is None
                else _read_numeric(margin_entry)
            )
            new_duration = max(
                config.minimum_reset_hold_duration(new_margin),
                round(_read_numeric(self.reset_hold_duration_entry), 2),
            )
        except (TypeError, ValueError, OverflowError):
            QMessageBox.warning(
                self,
                "Invalid Settings",
                "Reset Hold Duration must be a valid number.",
            )
            return

        try:
            new_interval = max(
                config.MIN_RECORDING_SNAPSHOT_INTERVAL_SECONDS,
                int(_read_numeric(self.record_interval_entry)),
            )
        except (TypeError, ValueError, OverflowError):
            QMessageBox.warning(
                self,
                "Invalid Settings",
                "Snapshot interval must be a valid number.",
            )
            return

        initial_duration = round(
            float(getattr(self, "_initial_reset_hold_duration", config.RESET_HOLD_DURATION)),
            2,
        )
        initial_margin = round(
            float(
                getattr(
                    self,
                    "_initial_reset_hold_safety_margin",
                    config.RESET_HOLD_SAFETY_MARGIN,
                )
            ),
            2,
        )
        timing_changed = (
            new_duration != initial_duration or new_margin != initial_margin
        )
        if not timing_changed:
            # The dialog may have stayed open while scanner startup re-read the
            # game's threshold and raised the live timing. Preserve that newer
            # value instead of treating the stale fields as edits.
            new_duration = round(float(config.RESET_HOLD_DURATION), 2)
            new_margin = round(float(config.RESET_HOLD_SAFETY_MARGIN), 2)
        game_value = config.reset_hold_duration_to_game_value(
            new_duration,
            safety_margin=new_margin,
        )
        game_read = config.read_game_quick_reset_time()
        game_matches = (
            game_read.success
            and game_read.value is not None
            and round(float(game_read.value), 2) == game_value
        )
        needs_game_sync = not game_matches
        game_running, detection_error = SettingsDialog._detect_game_running(self)
        if game_running and (timing_changed or needs_game_sync):
            reason = detection_error or (
                "Megabonk is currently running. Close the game before saving Reset "
                "Speed so it cannot overwrite config.json and so the scanner and game "
                "cannot start with different reset values."
            )
            GameResetTimeNoticeDialog(self, saved=False, reason=reason).exec()
            return

        settings_updates = {
            "HOTKEY": new_hotkey,
            "RESET_HOTKEY": new_reset_hotkey,
            "PLAYER_STATS_RECORD_HOTKEY": new_record_hotkey,
            "IN_GAME_OVERLAY_EDIT_HOTKEY": new_overlay_edit_hotkey,
            "AUTO_START_RECORDING": auto_start_recording,
            "SHOW_OBS_REMINDER_ON_START_SCANNER": show_obs_reminder_on_start_scanner,
            "STOP_SCANNING_ON_PLAYER_MOVEMENT": stop_scanning_on_player_movement,
            "PLAYER_STATS_RECORD_INTERVAL_SECONDS": new_interval,
        }
        if timing_changed:
            settings_updates.update(
                {
                    "RESET_HOLD_DURATION": new_duration,
                    "RESET_HOLD_SAFETY_MARGIN": new_margin,
                }
            )

        save_result = config.save_settings_with_game_reset(
            settings_updates,
            game_value if timing_changed else None,
            # When the game is closed, always write and read back its value. This
            # both repairs hand-edited drift and closes the old false-success gap
            # where an unchanged UI field meant the game file was never checked.
            sync_game=not game_running,
        )
        if not save_result.success:
            GameResetTimeNoticeDialog(
                self,
                saved=False,
                reason=save_result.reason or "The settings change could not be verified.",
            ).exec()
            return

        # The config transaction already committed these keys to the runtime
        # mapping. Keep this idempotent update for isolated dialog tests that
        # replace the transaction with a success double.
        config.user_config.update(settings_updates)

        config.HOTKEY = new_hotkey
        config.RESET_HOTKEY = new_reset_hotkey
        config.PLAYER_STATS_RECORD_HOTKEY = new_record_hotkey
        config.IN_GAME_OVERLAY_EDIT_HOTKEY = new_overlay_edit_hotkey
        config.AUTO_START_RECORDING = auto_start_recording
        config.SHOW_OBS_REMINDER_ON_START_SCANNER = show_obs_reminder_on_start_scanner
        config.STOP_SCANNING_ON_PLAYER_MOVEMENT = stop_scanning_on_player_movement
        if timing_changed:
            config.RESET_HOLD_DURATION = new_duration
            config.RESET_HOLD_SAFETY_MARGIN = new_margin
        config.PLAYER_STATS_RECORD_INTERVAL_SECONDS = new_interval
        effective_duration = round(float(config.RESET_HOLD_DURATION), 2)
        effective_margin = round(float(config.RESET_HOLD_SAFETY_MARGIN), 2)
        effective_game_value = config.reset_hold_duration_to_game_value(
            effective_duration,
            safety_margin=effective_margin,
        )
        self._initial_reset_hold_duration = effective_duration
        self._initial_reset_hold_safety_margin = effective_margin
        if auto_start_recording:
            # Was `hasattr(self.master, ...)` + a direct assignment. The service
            # always has the flag, so the guard is gone -- and with it the
            # step-19 failure shape where a `hasattr` goes quietly false and
            # re-enabling auto-start silently stops clearing a suppression.
            vod_capture(self.master).clear_auto_recording_suppression()

        if hasattr(self.master, "player_stats_vod_recorder") and self.master.player_stats_vod_recorder is not None:
            self.master.player_stats_vod_recorder.interval_seconds = new_interval

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

        # `self.accept()`, unguarded. This was `if hasattr(self, "accept") ...
        # elif hasattr(self, "destroy"): self.destroy()`, and the `elif` was the
        # tk close call: `QWidget.destroy()` tears down the native handle rather
        # than closing a dialog, so taking that branch in production would have
        # been a bug. It was unreachable there -- this class is a `QDialog` and
        # always has `accept` -- and reachable only from the suite, whose
        # stand-ins carried `destroy` and no `accept`. Those stand-ins model a
        # `QDialog` now, so the branch that only the fakes could take is gone.
        self.accept()
        if timing_changed or needs_game_sync:
            GameResetTimeNoticeDialog(
                self.parent(),
                saved=True,
                scanner_hold=effective_duration,
                game_value=effective_game_value,
                margin=effective_margin,
            ).exec()


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
            ("dice", "!dice:", default_templates.get("dice", "Dice Lv{level}: {dice}"), "Tags: {level}, {dice}, {rolls}, {ambiguous}"),
            ("shrines", "!shrines:", default_templates.get("shrines", "Shrines: {shrines}"), "Tags: {rewards}, {selected}, {pending}, {charged}, {shrines}"),
            ("powerups", "!powerups:", default_templates.get("powerups", "Powerups: {powerups} (PM {pm})"), "Tags: {powerups}, {standard_duration}, {clock_duration}, {pm}"),
            ("kps", "!kps:", default_templates.get("kps", "KPS: {kps} | 60s Avg: {minute_avg} | 5m Avg: {five_minute_avg} | Run Avg: {run_avg}"), "Tags: {kps}, {minute_avg}, {five_minute_avg}, {run_avg}"),
            ("build", "!build:", default_templates.get("build", "{name} · {progress}{requirements}{remaining_suffix}"), "Tags: {name}, {progress}, {requirements}, {remaining_suffix}, {completion_time}"),
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
