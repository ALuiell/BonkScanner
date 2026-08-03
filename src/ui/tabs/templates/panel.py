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

from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QColor, QDrag, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app import config
from core.template_colors import template_color_hex, template_color_tag
from ui.shared import (
    _apply_button_icon,
    _clear_layout,
    _read_bool,
    format_template_conditions,
)
from ui.styles import _template_row_stylesheet, _tier_color


TIERS = ("Light", "Good", "Perfect", "Perfect+")
_TEMPLATE_DRAG_MIME = "application/x-megabonk-template-id"
_TEMPLATE_ROW_HEIGHT = 62


class _DragHandle(QWidget):
    """Six-dot handle that starts a drag without stealing checkbox clicks."""

    def __init__(self, row: "_TemplateRow") -> None:
        super().__init__(row)
        self._row = row
        self._press_pos: QPoint | None = None
        self.setFixedSize(18, 30)
        self.setCursor(Qt.OpenHandCursor)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white if self.underMouse() else Qt.lightGray)
        for column in (5, 13):
            for row in (7, 15, 23):
                painter.drawEllipse(column - 2, row - 2, 4, 4)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        distance = (event.position().toPoint() - self._press_pos).manhattanLength()
        if distance >= QApplication.startDragDistance():
            self._press_pos = None
            self._row.start_drag()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)


class _TemplateRow(QFrame):
    """One 62px template record: bracket, handle, check, name, conditions."""

    def __init__(self, template: dict, active: bool, on_toggled: Callable) -> None:
        super().__init__()
        self.template_id = int(template.get("id", 0))
        self._color_hex = template_color_hex(template_color_tag(template))
        self._hovered = False
        self._drop_edge = 0
        self._press_pos: QPoint | None = None
        self.setObjectName("TemplateRow")
        self.setFixedHeight(_TEMPLATE_ROW_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 0, 14, 0)
        layout.setSpacing(10)

        self.drag_handle = _DragHandle(self)
        layout.addWidget(self.drag_handle)

        self.checkbox = QCheckBox()
        self.checkbox.setObjectName("TemplateActive")
        self.checkbox.setFixedSize(26, 26)
        self.checkbox.setChecked(bool(active))
        layout.addWidget(self.checkbox)

        self.name_label = QLabel(str(template.get("name", "")))
        self.name_label.setObjectName("TemplateName")
        self.name_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        layout.addWidget(self.name_label)

        self.conditions_label = QLabel(_format_template_conditions_inline(template))
        self.conditions_label.setObjectName("TemplateConditions")
        self.conditions_label.setMinimumWidth(0)
        self.conditions_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.conditions_label, 1)

        self.checkbox.toggled.connect(self._apply_style)
        self.checkbox.toggled.connect(on_toggled)
        self._apply_style()

    def _apply_style(self, *_args) -> None:
        self.setStyleSheet(
            _template_row_stylesheet(
                self._color_hex,
                checked=self.checkbox.isChecked(),
                hovered=self._hovered,
            )
        )
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._apply_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._press_pos is not None:
            distance = (event.position().toPoint() - self._press_pos).manhattanLength()
            if distance < QApplication.startDragDistance() and self.rect().contains(event.position().toPoint()):
                self.checkbox.toggle()
                event.accept()
                self._press_pos = None
                return
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # The rounded left bracket is the template's sole colour marker.
        bracket = QPainterPath()
        bracket.moveTo(10, 2)
        bracket.quadTo(4, 2, 4, 9)
        bracket.lineTo(4, self.height() - 9)
        bracket.quadTo(4, self.height() - 2, 10, self.height() - 2)
        painter.setPen(QPen(QColor(self._color_hex), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(bracket)

        if self._drop_edge:
            y = 1 if self._drop_edge < 0 else self.height() - 2
            painter.setPen(QPen(QColor("#4DA3FF"), 2, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(14, y, self.width() - 12, y)

    def set_drop_edge(self, edge: int) -> None:
        edge = -1 if edge < 0 else (1 if edge > 0 else 0)
        if edge != self._drop_edge:
            self._drop_edge = edge
            self.update()

    def start_drag(self) -> None:
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_TEMPLATE_DRAG_MIME, str(self.template_id).encode("ascii"))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(QPoint(32, self.height() // 2))
        drag.exec(Qt.MoveAction)


class _TemplateListSurface(QWidget):
    """Drop target that turns row positions into a persisted id order."""

    def __init__(self, on_reorder: Callable[[list[int]], None]) -> None:
        super().__init__()
        self._on_reorder = on_reorder
        self._drop_index: int | None = None
        self.setObjectName("templateListSurface")
        self.setAcceptDrops(True)
        self.rows_layout = QVBoxLayout(self)
        self.rows_layout.setContentsMargins(8, 8, 8, 8)
        self.rows_layout.setSpacing(6)

    def rows(self) -> list[_TemplateRow]:
        result = []
        for index in range(self.rows_layout.count()):
            widget = self.rows_layout.itemAt(index).widget()
            if isinstance(widget, _TemplateRow):
                result.append(widget)
        return result

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_TEMPLATE_DRAG_MIME):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_TEMPLATE_DRAG_MIME):
            event.ignore()
            return
        y = event.position().toPoint().y()
        rows = self.rows()
        index = len(rows)
        for candidate, row in enumerate(rows):
            if y < row.geometry().center().y():
                index = candidate
                break
        self._show_drop_index(index)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._clear_drop_indicator()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(_TEMPLATE_DRAG_MIME):
            event.ignore()
            return
        try:
            template_id = int(bytes(event.mimeData().data(_TEMPLATE_DRAG_MIME)).decode("ascii"))
        except (TypeError, ValueError, UnicodeDecodeError):
            self._clear_drop_indicator()
            event.ignore()
            return

        current = [row.template_id for row in self.rows()]
        if template_id not in current:
            self._clear_drop_indicator()
            event.ignore()
            return

        target = self._drop_index if self._drop_index is not None else len(current)
        source = current.index(template_id)
        reordered = list(current)
        reordered.pop(source)
        if source < target:
            target -= 1
        reordered.insert(max(0, min(target, len(reordered))), template_id)
        self._clear_drop_indicator()
        if reordered != current:
            self._on_reorder(reordered)
        event.setDropAction(Qt.MoveAction)
        event.accept()

    def _show_drop_index(self, index: int) -> None:
        rows = self.rows()
        self._drop_index = max(0, min(index, len(rows)))
        for row in rows:
            row.set_drop_edge(0)
        if not rows:
            return
        if self._drop_index == len(rows):
            rows[-1].set_drop_edge(1)
        else:
            rows[self._drop_index].set_drop_edge(-1)

    def _clear_drop_indicator(self) -> None:
        self._drop_index = None
        for row in self.rows():
            row.set_drop_edge(0)


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
        self._template_surface = None
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
        self._scrollable_templates = QScrollArea()
        self._scrollable_templates.setWidgetResizable(True)
        self._scrollable_templates.setFrameShape(QFrame.NoFrame)
        self._scrollable_templates.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._template_surface = _TemplateListSurface(self._save_template_order)
        self._template_layout = self._template_surface.rows_layout
        self._scrollable_templates.setWidget(self._template_surface)
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

    # -- what the collapsed rail asks --------------------------------------
    #
    # The rail is a remote control for the two checkbox dicts below, not a
    # second copy of them. Flipping the box here is what re-runs the existing
    # persistence path -- `save_checkbox_state` for templates,
    # `refresh_scores_ui` for tiers -- so the rail cannot drift out of sync
    # with the expanded panel, and neither one owns state the other has to be
    # told about.

    def rail_tier_entries(self) -> list[tuple[str, str, bool]]:
        """`(tier, colour, is_active)` in `TIERS` order, for the rail.

        Light -> Perfect+ is a progression, so each tier keeps a stable slot,
        matching the stable template order in the other rail mode.
        """
        return [
            (tier, _tier_color(tier), cb.isChecked())
            for tier, cb in self._scores_checkboxes.items()
        ]

    def set_template_active(self, name: str, active: bool) -> None:
        """Check or uncheck one template's box by name.

        Looked up by name on every call, never held: `refresh_templates`
        rebuilds the dict wholesale, so a cached widget would outlive the box
        it points at.
        """
        cb = self._checkboxes.get(name)
        if cb is not None:
            cb.setChecked(active)

    def set_tier_active(self, tier: str, active: bool) -> None:
        """Check or uncheck one score tier's box by name."""
        cb = self._scores_checkboxes.get(tier)
        if cb is not None:
            cb.setChecked(active)

    # -- templates tab ------------------------------------------------------

    def refresh_templates(self) -> None:
        _clear_layout(self._template_layout)
        self._checkboxes.clear()
        active_names = set(config.ACTIVE_TEMPLATES)
        for template in config.TEMPLATES:
            row = _TemplateRow(
                template,
                template["name"] in active_names,
                self.save_checkbox_state,
            )
            self._template_layout.addWidget(row)
            self._checkboxes[template["name"]] = row.checkbox
        self._template_layout.addStretch(1)
        self._sync_filters(announce=True)

    def _save_template_order(self, ordered_ids: list[int]) -> bool:
        """Persist one complete drag result; active selections stay untouched."""
        templates = list(config.TEMPLATES)
        try:
            current_ids = [int(template.get("id", 0)) for template in templates]
            normalized = [int(template_id) for template_id in ordered_ids]
        except (TypeError, ValueError):
            return False
        if len(set(current_ids)) != len(current_ids) or sorted(normalized) != sorted(current_ids):
            return False
        if normalized == current_ids:
            return False

        by_id = {int(template.get("id", 0)): template for template in templates}
        config.TEMPLATES = [by_id[template_id] for template_id in normalized]
        config.user_config["TEMPLATES"] = config.TEMPLATES
        config.save_config(config.user_config)
        self.refresh_templates()
        return True

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
        builtin_max = max(
            [template.get("id", 0) for template in config.DEFAULT_TEMPLATES] + [0]
        )
        next_id = max(
            [template.get("id", 0) for template in config.TEMPLATES] + [builtin_max]
        ) + 1
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
        dialog = self._delete_dialog(self._window(), list(config.TEMPLATES))
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


def _format_template_conditions_inline(template: dict) -> str:
    conditions = format_template_conditions(template)
    return (
        conditions
        .replace("S+M:", "S+M")
        .replace("Micro:", "Mic")
        .replace("Boss:", "Boss")
    )


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
