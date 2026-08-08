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

from PySide6.QtCore import (
    QEasingCurve,
    QMimeData,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QDrag, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
_TEMPLATE_ROW_HEIGHT = 48
_SCORE_TIER_ROW_HEIGHT = 40
_TEMPLATE_PANEL_MIN_WIDTH = 360
_TEMPLATE_PANEL_MAX_WIDTH = 420
_LIVE_REORDER_DURATION_MS = 140


class _ElidedLabel(QLabel):
    """Keep the full value for sizing/tooltips, but shorten it when squeezed."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._full_text = str(text)
        super().setText(self._full_text)

    @property
    def full_text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        super().setText(self._full_text)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        available = max(0, self.contentsRect().width())
        displayed = self.fontMetrics().elidedText(
            self._full_text, Qt.ElideRight, available
        )
        if self.text() != displayed:
            super().setText(displayed)
        self.setToolTip(self._full_text if displayed != self._full_text else "")


class _DragHandle(QWidget):
    """Six-dot handle that starts a drag without stealing checkbox clicks."""

    def __init__(self, row: "_TemplateRow") -> None:
        super().__init__(row)
        self._row = row
        self._press_pos: QPoint | None = None
        self.setFixedSize(16, 24)
        self.setCursor(Qt.OpenHandCursor)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(Qt.white if self.underMouse() else Qt.lightGray)
        for column in (4, 12):
            for row in (5, 12, 19):
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
    """One compact template record: bracket, handle, check, name, conditions."""

    def __init__(self, template: dict, active: bool, on_toggled: Callable) -> None:
        super().__init__()
        self.template_id = int(template.get("id", 0))
        self._color_hex = template_color_hex(template_color_tag(template))
        self._hovered = False
        self._dragging = False
        self._drop_edge = 0
        self._press_pos: QPoint | None = None
        self.setObjectName("TemplateRow")
        self.setFixedHeight(_TEMPLATE_ROW_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 14, 0)
        layout.setSpacing(7)

        self.drag_handle = _DragHandle(self)
        layout.addWidget(self.drag_handle)

        self.checkbox = QCheckBox()
        self.checkbox.setObjectName("TemplateActive")
        self.checkbox.setFixedSize(24, 24)
        self.checkbox.setChecked(bool(active))
        layout.addWidget(self.checkbox)

        self.name_label = QLabel(str(template.get("name", "")))
        self.name_label.setObjectName("TemplateName")
        self.name_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        layout.addWidget(self.name_label)

        self.conditions_label = _ElidedLabel(_format_template_conditions_inline(template))
        self.conditions_label.setObjectName("TemplateConditions")
        self.conditions_label.setMinimumWidth(0)
        self.conditions_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.conditions_label, 1)

        self.checkbox.toggled.connect(self._apply_style)
        self.checkbox.toggled.connect(on_toggled)
        self._apply_style()

    def preferred_width(self) -> int:
        """Natural one-line width, including 14 px after the final character."""
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()
        return (
            margins.left()
            + self.drag_handle.width()
            + self.checkbox.width()
            + self.name_label.fontMetrics().horizontalAdvance(self.name_label.text())
            + self.conditions_label.fontMetrics().horizontalAdvance(
                self.conditions_label.full_text
            )
            + spacing * 3
            + margins.right()
            + self.frameWidth() * 2
        )

    def _apply_style(self, *_args) -> None:
        self.setStyleSheet(
            _template_row_stylesheet(
                self._color_hex,
                checked=self.checkbox.isChecked(),
                hovered=self._hovered,
                dragging=self._dragging,
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

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is not None and event.buttons() & Qt.LeftButton:
            distance = (event.position().toPoint() - self._press_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                self._press_pos = None
                self.start_drag()
                event.accept()
                return
        super().mouseMoveEvent(event)

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
        bracket.moveTo(9, 2)
        bracket.quadTo(4, 2, 4, 8)
        bracket.lineTo(4, self.height() - 8)
        bracket.quadTo(4, self.height() - 2, 9, self.height() - 2)
        bracket_color = QColor(self._color_hex)
        if self._dragging:
            bracket_color.setAlpha(90)
        painter.setPen(QPen(bracket_color, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
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
        source_pixmap = self.grab()
        ghost = QPixmap(source_pixmap.size())
        ghost.fill(Qt.transparent)
        ghost_painter = QPainter(ghost)
        ghost_painter.setOpacity(0.88)
        ghost_painter.drawPixmap(0, 0, source_pixmap)
        ghost_painter.end()

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_TEMPLATE_DRAG_MIME, str(self.template_id).encode("ascii"))
        drag.setMimeData(mime)
        drag.setPixmap(ghost)
        drag.setHotSpot(QPoint(28, self.height() // 2))

        surface = self.parentWidget()
        if not isinstance(surface, _TemplateListSurface):
            surface = None
        if surface is not None:
            surface.begin_live_drag(self)

        self._set_dragging(True)
        action = Qt.IgnoreAction
        try:
            action = drag.exec(Qt.MoveAction)
        finally:
            self._set_dragging(False)
            if surface is not None:
                ordered_ids = surface.finish_live_drag(
                    action == Qt.MoveAction and surface.drop_accepted
                )
                if ordered_ids is not None:
                    surface.persist_order(ordered_ids)

    def _set_dragging(self, dragging: bool) -> None:
        self._dragging = bool(dragging)
        for widget in (
            self.drag_handle,
            self.checkbox,
            self.name_label,
            self.conditions_label,
        ):
            widget.setVisible(not self._dragging)
        self.setCursor(Qt.ClosedHandCursor if self._dragging else Qt.PointingHandCursor)
        self._apply_style()


class _ScoreTierRow(QFrame):
    """A fixed-order score tier presented with the Templates row language."""

    def __init__(self, tier: str, active: bool, on_toggled: Callable) -> None:
        super().__init__()
        self.tier = tier
        self._color_hex = _tier_color(tier)
        self.setObjectName("ScoreTierRow")
        self.setFixedHeight(_SCORE_TIER_ROW_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 14, 0)
        layout.setSpacing(9)

        self.checkbox = QCheckBox()
        self.checkbox.setObjectName("ScoreTierActive")
        self.checkbox.setFixedSize(24, 24)
        self.checkbox.setChecked(bool(active))
        layout.addWidget(self.checkbox)

        self.name_label = QLabel(tier.upper())
        self.name_label.setObjectName("ScoreTierName")
        self.name_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        layout.addWidget(self.name_label)

        self.meta_label = _ElidedLabel("")
        self.meta_label.setObjectName("ScoreTierMeta")
        self.meta_label.setMinimumWidth(0)
        self.meta_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.meta_label, 1)

        self.checkbox.toggled.connect(self._apply_style)
        self.checkbox.toggled.connect(on_toggled)
        self._apply_style()

    def set_summary(self, threshold: float) -> None:
        threshold_text = _format_number(threshold)
        if self.tier == "Perfect":
            summary = f"{threshold_text}+  ·  2 Mic, or 1 Mic + S+M 8, Boss 2"
        elif self.tier == "Perfect+":
            summary = f"{threshold_text}+  ·  needs 2 Microwaves"
        else:
            summary = f"{threshold_text}+"
        self.meta_label.setText(summary)

    def _apply_style(self, *_args) -> None:
        checked = self.checkbox.isChecked()
        background = "#141A22" if checked else "#0B0F14"
        border = "#2E3A48" if checked else "#1B222B"
        self.setStyleSheet(
            f"""
            QFrame#ScoreTierRow {{
                background: {background};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QLabel#ScoreTierName {{
                color: {self._color_hex};
                font-weight: 700;
                background: transparent;
                border: none;
            }}
            QLabel#ScoreTierMeta {{
                color: #8A94A3;
                font-weight: 600;
                background: transparent;
                border: none;
            }}
            QCheckBox#ScoreTierActive {{
                background: transparent;
                border: none;
                padding: 0;
                min-height: 0;
            }}
            """
        )
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.checkbox.toggle()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bracket = QPainterPath()
        bracket.moveTo(9, 2)
        bracket.quadTo(4, 2, 4, 8)
        bracket.lineTo(4, self.height() - 8)
        bracket.quadTo(4, self.height() - 2, 9, self.height() - 2)
        painter.setPen(
            QPen(QColor(self._color_hex), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.drawPath(bracket)


class _ScoreValueRow(QFrame):
    def __init__(self, label: str, note: str = "") -> None:
        super().__init__()
        self.setObjectName("ScoreValueRow")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 5, 9, 5)
        layout.setSpacing(1)

        line = QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        self.name_label = QLabel(label)
        self.name_label.setObjectName("ScoreValueLabel")
        line.addWidget(self.name_label)
        line.addStretch(1)
        self.value_label = QLabel()
        self.value_label.setObjectName("ScoreValueNumber")
        line.addWidget(self.value_label)
        layout.addLayout(line)

        if note:
            note_label = QLabel(note)
            note_label.setObjectName("ScoresInlineNote")
            note_label.setWordWrap(True)
            layout.addWidget(note_label)

    def set_value(self, value: float) -> None:
        if value > 0:
            text, tone = f"+{_format_number(value)}", "positive"
        elif value < 0:
            text, tone = f"−{_format_number(abs(value))}", "negative"
        else:
            text, tone = "0  ·  ignored", "ignored"
        self.value_label.setText(text)
        self.value_label.setProperty("tone", tone)
        self.value_label.style().unpolish(self.value_label)
        self.value_label.style().polish(self.value_label)


class _ScoresOverview(QWidget):
    """Compact explanation of the configured score formula."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        points_card, points_layout = _scores_card(
            "Shrine Points",
            "Positive rewards  ·  0 ignores  ·  Negative penalizes",
        )
        self.point_rows = {
            "moais": _ScoreValueRow("Moais"),
            "shady": _ScoreValueRow("Shady"),
            "boss": _ScoreValueRow("Boss"),
            "magnet": _ScoreValueRow(
                "Magnet", "Positive counts up to 2; negative counts all."
            ),
            "challenges": _ScoreValueRow("Challenges"),
        }
        for row in self.point_rows.values():
            points_layout.addWidget(row)
        layout.addWidget(points_card)

        bonus_card, bonus_layout = _scores_card("Whole-map bonus")
        self.bonus_label = QLabel()
        self.bonus_label.setObjectName("ScoresBonusValue")
        self.bonus_label.setWordWrap(True)
        bonus_layout.addWidget(self.bonus_label)
        bonus_note = QLabel("Applied after shrine points are summed.")
        bonus_note.setObjectName("ScoresSectionHint")
        bonus_layout.addWidget(bonus_note)
        layout.addWidget(bonus_card)

        example_card, example_layout = _scores_card(
            "Example score", object_name="ScoresExampleCard"
        )
        self.example_formula = QLabel()
        self.example_formula.setObjectName("ScoresExampleFormula")
        self.example_formula.setWordWrap(True)
        example_layout.addWidget(self.example_formula)
        self.example_result = QLabel()
        self.example_result.setObjectName("ScoresExampleResult")
        self.example_result.setWordWrap(True)
        example_layout.addWidget(self.example_result)
        example_note = QLabel("ⓘ  Perfect+ also requires 2 Microwaves.")
        example_note.setObjectName("ScoresExampleNote")
        example_layout.addWidget(example_note)
        layout.addWidget(example_card)

    def refresh_from_config(self) -> None:
        weights = config.SCORES_SYSTEM.get("weights", {})
        for key, row in self.point_rows.items():
            row.set_value(float(weights.get(key, 0.0)))

        multipliers = config.SCORES_SYSTEM.get("multipliers", {}).get("microwave", {})
        one = float(multipliers.get("1", 1.0))
        two = float(multipliers.get("2", 1.25))
        self.bonus_label.setText(
            f"1 Microwave ×{_format_number(one)}     "
            f"2 Microwaves ×{_format_number(two)}"
        )

        counts = {
            "moais": 4,
            "shady": 5,
            "boss": 3,
            "magnet": 1,
            "challenges": 0,
        }
        contributions = [
            counts[key] * float(weights.get(key, 0.0)) for key in counts
        ]
        base_score = sum(contributions)
        final_score = base_score * two
        expression = " ".join(
            _format_signed_term(value, index == 0)
            for index, value in enumerate(contributions)
        )
        self.example_formula.setText(f"{expression} = {_format_number(base_score)}")
        tier = _example_score_tier(final_score)
        tier_color = _tier_color(tier) if tier in TIERS else "#8A94A3"
        self.example_result.setText(
            f"{_format_number(base_score)} × {_format_number(two)} = "
            f"{_format_number(final_score)}  →  "
            f"<span style='color:{tier_color}'>{tier.upper()}</span>"
        )

    # Retains the old label-shaped seam used by lightweight component tests.
    def setHtml(self, _html: str) -> None:
        self.refresh_from_config()


class _TemplateListSurface(QWidget):
    """Drop target whose rows make room while the dragged card is moving."""

    def __init__(self, on_reorder: Callable[[list[int]], None]) -> None:
        super().__init__()
        self._on_reorder = on_reorder
        self._drag_source: _TemplateRow | None = None
        self._original_order: list[int] = []
        self._drop_accepted = False
        self._standalone_drag = False
        self._reorder_animation: QParallelAnimationGroup | None = None
        self.setObjectName("templateListSurface")
        self.setAcceptDrops(True)
        self.rows_layout = QVBoxLayout(self)
        self.rows_layout.setContentsMargins(8, 8, 8, 8)
        self.rows_layout.setSpacing(4)

    def rows(self) -> list[_TemplateRow]:
        result = []
        for index in range(self.rows_layout.count()):
            widget = self.rows_layout.itemAt(index).widget()
            if isinstance(widget, _TemplateRow):
                result.append(widget)
        return result

    @property
    def drop_accepted(self) -> bool:
        return self._drop_accepted

    def persist_order(self, ordered_ids: list[int]) -> None:
        self._on_reorder(ordered_ids)

    def begin_live_drag(
        self, row: _TemplateRow, *, standalone: bool = False
    ) -> None:
        if self._drag_source is row:
            return
        if self._drag_source is not None:
            self.finish_live_drag(False)
        if row not in self.rows():
            return
        self._drag_source = row
        self._original_order = [item.template_id for item in self.rows()]
        self._drop_accepted = False
        self._standalone_drag = bool(standalone)
        policy = row.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        row.setSizePolicy(policy)
        self._animate_relayout(row.hide)

    def finish_live_drag(self, accepted: bool) -> list[int] | None:
        source = self._drag_source
        if source is None:
            return None
        current = [row.template_id for row in self.rows()]
        original = list(self._original_order)
        target = current if accepted else original

        def finish_layout() -> None:
            self._set_row_order(target)
            source.show()
            policy = source.sizePolicy()
            policy.setRetainSizeWhenHidden(False)
            source.setSizePolicy(policy)

        self._animate_relayout(finish_layout)
        self._drag_source = None
        self._original_order = []
        self._drop_accepted = False
        self._standalone_drag = False
        return current if accepted and current != original else None

    def dragEnterEvent(self, event) -> None:
        template_id = self._event_template_id(event)
        if template_id is not None:
            if self._drag_source is None:
                source = next(
                    (row for row in self.rows() if row.template_id == template_id),
                    None,
                )
                if source is not None:
                    self.begin_live_drag(source, standalone=True)
            if self._drag_source is None or self._drag_source.template_id != template_id:
                event.ignore()
                return
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        template_id = self._event_template_id(event)
        if (
            template_id is None
            or self._drag_source is None
            or self._drag_source.template_id != template_id
        ):
            event.ignore()
            return
        self._move_source_to_y(event.position().toPoint().y())
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        template_id = self._event_template_id(event)
        if (
            template_id is None
            or self._drag_source is None
            or self._drag_source.template_id != template_id
        ):
            event.ignore()
            return
        self._move_source_to_y(event.position().toPoint().y())
        self._drop_accepted = True
        event.setDropAction(Qt.MoveAction)
        event.accept()
        if self._standalone_drag:
            ordered_ids = self.finish_live_drag(True)
            if ordered_ids is not None:
                self.persist_order(ordered_ids)

    def _event_template_id(self, event) -> int | None:
        if not event.mimeData().hasFormat(_TEMPLATE_DRAG_MIME):
            return None
        try:
            return int(
                bytes(event.mimeData().data(_TEMPLATE_DRAG_MIME)).decode("ascii")
            )
        except (TypeError, ValueError, UnicodeDecodeError):
            return None

    def _move_source_to_y(self, y: int) -> None:
        source = self._drag_source
        if source is None:
            return
        other_rows = [row for row in self.rows() if row is not source]
        target = len(other_rows)
        for index, row in enumerate(other_rows):
            if y < row.geometry().center().y():
                target = index
                break
        desired = list(other_rows)
        desired.insert(target, source)
        if desired == self.rows():
            return
        self._animate_relayout(lambda: self._set_row_order(desired))

    def _set_row_order(self, ordered) -> None:
        by_id = {row.template_id: row for row in self.rows()}
        rows = [by_id[item] if isinstance(item, int) else item for item in ordered]
        for index, row in enumerate(rows):
            self.rows_layout.removeWidget(row)
            self.rows_layout.insertWidget(index, row)

    def _animate_relayout(self, mutation: Callable[[], None]) -> None:
        if self._reorder_animation is not None:
            self._reorder_animation.stop()
            self._reorder_animation.deleteLater()
            self._reorder_animation = None
        moving_rows = [row for row in self.rows() if not row.isHidden()]
        old_positions = {row: row.pos() for row in moving_rows}
        mutation()
        self.rows_layout.invalidate()
        self.rows_layout.activate()

        group = QParallelAnimationGroup(self)
        for row in moving_rows:
            if row.isHidden():
                continue
            start = old_positions[row]
            end = row.pos()
            if start == end:
                continue
            row.move(start)
            animation = QPropertyAnimation(row, b"pos", group)
            animation.setDuration(_LIVE_REORDER_DURATION_MS)
            animation.setStartValue(start)
            animation.setEndValue(end)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(animation)
        if group.animationCount() == 0:
            group.deleteLater()
            return
        self._reorder_animation = group
        group.finished.connect(lambda: self._animation_finished(group))
        group.start()

    def _animation_finished(self, group: QParallelAnimationGroup) -> None:
        if self._reorder_animation is group:
            self._reorder_animation = None
        group.deleteLater()


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
        scores_help_dialog,
        no_custom_templates_message,
    ) -> None:
        self._left_tabview = left_tabview
        self._window = window
        self._sync_filters = sync_filters
        self._template_dialog = template_dialog
        self._template_manager_dialog = template_manager_dialog
        self._delete_dialog = delete_dialog
        self._scores_settings_dialog = scores_settings_dialog
        self._scores_help_dialog = scores_help_dialog
        self._no_custom_templates_message = no_custom_templates_message

        self._tab_templates = None
        self._tab_scores = None
        self._scrollable_templates = None
        self._template_surface = None
        self._template_layout = None
        self._scores_templates_layout = None
        self._scores_desc_label = None
        self._score_tier_rows: dict[str, _ScoreTierRow] = {}
        self._checkboxes: dict[str, QCheckBox] = {}
        self._scores_checkboxes: dict[str, QCheckBox] = {}
        self._preferred_width_changed: Callable[[int], None] | None = None

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
        self._template_surface = _TemplateListSurface(self.save_template_order)
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
        scores_layout.setContentsMargins(6, 6, 6, 6)

        scroll = QScrollArea()
        scroll.setObjectName("ScoresScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        surface = QWidget()
        surface.setObjectName("ScoresSurface")
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(4, 4, 4, 4)
        surface_layout.setSpacing(10)

        tiers_card, tiers_layout = _scores_card(
            "Stop tiers", "The scanner stops at any enabled tier."
        )
        self._scores_templates_layout = QVBoxLayout()
        self._scores_templates_layout.setContentsMargins(0, 4, 0, 0)
        self._scores_templates_layout.setSpacing(4)
        tiers_layout.addLayout(self._scores_templates_layout)
        surface_layout.addWidget(tiers_card)

        self._scores_desc_label = _ScoresOverview()
        surface_layout.addWidget(self._scores_desc_label)
        surface_layout.addStretch(1)
        scroll.setWidget(surface)
        scores_layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        self.scores_help_btn = QPushButton("Score Guide")
        _apply_button_icon(self.scores_help_btn, "media/help_icon.svg", 18)
        self.scores_help_btn.clicked.connect(self.open_scores_help_dialog)
        buttons.addWidget(self.scores_help_btn, 2)
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

    def set_preferred_width_changed(self, callback: Callable[[int], None]) -> None:
        """Connect the panel's measured content width to its outer splitter."""
        self._preferred_width_changed = callback

    def preferred_width(self) -> int:
        """Width of the longest card plus the tab/list layout margins."""
        if self._template_surface is None or self._tab_templates is None:
            return _TEMPLATE_PANEL_MIN_WIDTH
        rows = self._template_surface.rows()
        natural_row_width = max(
            (row.preferred_width() for row in rows),
            default=_TEMPLATE_PANEL_MIN_WIDTH,
        )
        surface_margins = self._template_layout.contentsMargins()
        tab_margins = self._tab_templates.layout().contentsMargins()
        measured = (
            natural_row_width
            + surface_margins.left()
            + surface_margins.right()
            + tab_margins.left()
            + tab_margins.right()
        )
        return max(
            _TEMPLATE_PANEL_MIN_WIDTH,
            min(_TEMPLATE_PANEL_MAX_WIDTH, measured),
        )

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
        if self._preferred_width_changed is not None:
            self._preferred_width_changed(self.preferred_width())
        self._sync_filters(announce=True)

    def save_template_order(self, ordered_ids: list[int]) -> bool:
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
        surface_order = (
            [row.template_id for row in self._template_surface.rows()]
            if self._template_surface is not None
            else []
        )
        # A live drag has already put these exact row widgets in final order;
        # rebuilding here would cut off their settling animation. Compact-rail
        # drags still refresh because the hidden expanded list has the old order.
        if surface_order != normalized:
            self.refresh_templates()
        else:
            self._checkboxes = {
                template["name"]: self._checkboxes[template["name"]]
                for template in config.TEMPLATES
                if template["name"] in self._checkboxes
            }
            self._sync_filters(announce=True)
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
        self._score_tier_rows.clear()
        thresholds = config.SCORES_SYSTEM.get("thresholds", {})
        for tier in TIERS:
            row = _ScoreTierRow(
                tier,
                tier in config.SCORES_SYSTEM.get("active_tiers", []),
                self.refresh_scores_ui,
            )
            row.set_summary(float(thresholds.get(tier, 0.0)))
            self._scores_templates_layout.addWidget(row)
            self._score_tier_rows[tier] = row
            self._scores_checkboxes[tier] = row.checkbox

    def refresh_scores_ui(self) -> None:
        if self._scores_desc_label is None:
            return
        active_tiers = [tier for tier, cb in self._scores_checkboxes.items() if cb.isChecked()]
        if active_tiers != config.SCORES_SYSTEM.get("active_tiers", []):
            config.SCORES_SYSTEM["active_tiers"] = active_tiers
            config.user_config["SCORES_SYSTEM"] = config.SCORES_SYSTEM
            config.save_config(config.user_config)
            self._sync_filters(announce=True)

        if hasattr(self._scores_desc_label, "refresh_from_config"):
            self._scores_desc_label.refresh_from_config()
        else:
            self._scores_desc_label.setHtml("<br>".join(_score_system_lines()))

    def open_scores_settings_dialog(self) -> None:
        dialog = self._scores_settings_dialog(self._window())
        if dialog.exec() == QDialog.Accepted:
            self.refresh_scores_templates_list()
            self.refresh_scores_ui()

    def open_scores_help_dialog(self) -> None:
        self._scores_help_dialog(self._window()).exec()


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


def _scores_card(
    title: str,
    hint: str = "",
    *,
    object_name: str = "ScoresSectionCard",
) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName(object_name)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(6)
    title_label = QLabel(title)
    title_label.setObjectName("ScoresSectionTitle")
    layout.addWidget(title_label)
    if hint:
        hint_label = QLabel(hint)
        hint_label.setObjectName("ScoresSectionHint")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
    return card, layout


def _format_number(value: float) -> str:
    return f"{float(value):.1f}"


def _format_signed_term(value: float, first: bool) -> str:
    magnitude = _format_number(abs(value))
    if first:
        return f"−{magnitude}" if value < 0 else magnitude
    return f"{'−' if value < 0 else '+'} {magnitude}"


def _example_score_tier(final_score: float) -> str:
    thresholds = config.SCORES_SYSTEM.get("thresholds", {})
    for tier in reversed(TIERS):
        if final_score >= float(thresholds.get(tier, 0.0)):
            return tier
    return "Below Light"


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
            "<b>Shrine Points</b>",
            f"Moais: {weights.get('moais', 0.0)}",
            f"Shady: {weights.get('shady', 0.0)}",
            f"Boss: {weights.get('boss', 0.0)}",
            f"Magnet: {weights.get('magnet', 0.0)}",
            f"Challenges: {weights.get('challenges', 0.0)}",
            "",
            "<b>Microwave Multipliers</b>",
            f"1 Microwave: {multipliers.get('1', 1.0)}",
            f"2 Microwaves: {multipliers.get('2', 1.25)}",
        ]
    )
    return lines
