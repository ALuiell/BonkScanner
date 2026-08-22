"""Widgets for the redesigned Compare Runs Overview.

Three blocks, in the order the page reads them:

* `CompareRunsLuckLootView` -- was the run built better, or did it just draw
  better? Nothing else in the app answers that, so it goes first.
* `CompareRunsAxisView` -- every metric the runs disagree on, ranked, drawn
  from a centre line. A row names its leader ("A +572"), which is why this
  block needs no sign convention of its own.
* `CompareRunsHubView` -- three jump targets, because Overview is a hub and the
  page it replaced was a dead end.

The performance rules are the ones `ui/metric_table.py` established and
measured: widgets are allocated once and pooled, a repaint only writes text,
and a stylesheet is re-applied only when a *colour* changes -- `setStyleSheet`
forces a style recalculation, and doing it per row per frame costs more than
the text ever did. The playhead can be dragged, so every write here happens at
frame rate.

Chrome -- surfaces, borders, the bars -- is painted rather than styled, for the
same reason: a `QWidget` with its own stylesheet is routed through
`QStyleSheetStyle` and repaints its own background over what this file drew.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.item_metadata import ITEM_RARITY_COLOR_MAP
from projections.compare_overview import (
    EMPTY_AXIS_TABLE,
    EMPTY_LUCK_LOOT,
    LEAD_A,
    AxisTable,
    LuckLoot,
)

#: The palette the rest of Compare Runs already uses. Kept as literals rather
#: than pulled from the stylesheet because these are painted, not styled.
SURFACE = QColor("#0B0F14")
SURFACE_INSET = QColor("#0E1217")
BORDER = QColor("#1B222B")
TRACK_BORDER = QColor("#2A3542")
CENTRE_LINE = QColor("#2E3A48")

RUN_A = QColor("#38BDF8")
RUN_B = QColor("#C084FC")
GOOD = QColor("#22C55E")
BAD = QColor("#FB7185")

TEXT = "#EDF1F5"
HEADING = "#B9C2CE"
SECONDARY = "#8A94A3"
MUTED = "#5C6675"
RUN_A_TEXT = "#38BDF8"
RUN_B_TEXT = "#C084FC"
WARN_TEXT = "#E8D9A0"

#: Below this the block stacks; above it the tiles sit four across. One number
#: for the whole page, so two blocks cannot reflow at different widths.
NARROW_WIDTH = 960
MEDIUM_WIDTH = 1280

_ROW_HEIGHT = 26
_BAR_INSET = 3


def _style(color: str, *, bold: bool = False, size: float | None = None) -> str:
    """A label's stylesheet, always transparent -- see the module docstring."""
    parts = [f"color:{color}", "background: transparent"]
    if bold:
        parts.append("font-weight:800")
    if size is not None:
        parts.append(f"font-size:{size}px")
    return "; ".join(parts) + ";"


def _label(parent, color: str, *, bold: bool = False, size: float | None = None, align=None):
    label = QLabel(parent)
    label.setStyleSheet(_style(color, bold=bold, size=size))
    if align is not None:
        label.setAlignment(align)
    return label


def _fill_card(painter: QPainter, rect, *, surface: QColor = SURFACE) -> None:
    path = QPainterPath()
    path.addRoundedRect(rect, 10, 10)
    painter.fillPath(path, surface)
    painter.setPen(BORDER)
    painter.drawPath(path)


def _draw_diverging_bar(
    painter: QPainter, rect, magnitude: float, color: QColor, *, to_left: bool
) -> None:
    """A bar growing out of the centre, left or right, in `color`.

    The side is a parameter rather than something inferred from the colour:
    the axis draws A left / B right, and the loot ladder draws shortfall left /
    surplus right in a different pair of colours entirely.

    `magnitude` is already normalised against the widest row in the table, so
    the widest row fills its half exactly and nothing has to be clamped here
    beyond guarding against a caller passing something out of range.
    """
    track = QPainterPath()
    track.addRoundedRect(rect, 5, 5)
    painter.fillPath(track, SURFACE_INSET)
    painter.setPen(TRACK_BORDER)
    painter.drawPath(track)

    centre = rect.center().x()
    painter.setPen(CENTRE_LINE)
    painter.drawLine(centre, rect.top() + 1, centre, rect.bottom() - 1)

    span = max(0.0, min(1.0, float(magnitude))) * (rect.width() / 2 - _BAR_INSET)
    if span < 1:
        return
    top = rect.top() + _BAR_INSET
    height = rect.height() - _BAR_INSET * 2
    left = centre - span if to_left else centre
    fill = QPainterPath()
    fill.addRoundedRect(float(left), float(top), float(span), float(height), 3, 3)
    painter.fillPath(fill, color)


class _AxisRowView(QWidget):
    """One ranked metric: name, a bar out of the centre, and the leader."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(_ROW_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(10)
        self._name = _label(self, HEADING, bold=True, size=12)
        self._name.setFixedWidth(132)
        self._spacer = QWidget(self)
        self._spacer.setStyleSheet("background: transparent;")
        self._spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._summary = _label(
            self, RUN_A_TEXT, bold=True, size=12, align=Qt.AlignRight | Qt.AlignVCenter
        )
        # Fixed, not content-sized: the playhead is dragged, and a column that
        # resized with its text would relayout the whole card every frame.
        self._summary.setFixedWidth(96)
        layout.addWidget(self._name)
        layout.addWidget(self._spacer, 1)
        layout.addWidget(self._summary)

        self._magnitude = 0.0
        self._lead = LEAD_A
        self._summary_color = RUN_A_TEXT

    def set_row(self, row) -> None:
        self._name.setText(str(row.label))
        self._summary.setText(str(row.summary))
        self._magnitude = float(row.magnitude)
        self._lead = str(row.lead)
        color = RUN_A_TEXT if self._lead == LEAD_A else RUN_B_TEXT
        if self._summary_color != color:
            self._summary_color = color
            self._summary.setStyleSheet(_style(color, bold=True, size=12))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self._spacer.geometry().adjusted(0, 5, 0, -5)
        leads_a = self._lead == LEAD_A
        _draw_diverging_bar(
            painter,
            rect,
            self._magnitude,
            RUN_A if leads_a else RUN_B,
            to_left=leads_a,
        )
        painter.end()


class _Card(QFrame):
    """A titled surface. The heading row is the same in every Overview block."""

    def __init__(self, title: str, hint: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CompareRunsOverviewCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget(self)
        header.setStyleSheet("background: transparent;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 9, 12, 9)
        header_layout.setSpacing(9)
        self._title = _label(header, TEXT, bold=True, size=12.5)
        self._title.setText(title.upper())
        self._hint = _label(
            header, SECONDARY, size=11.5, align=Qt.AlignRight | Qt.AlignVCenter
        )
        self._hint.setText(hint)
        self._hint.setVisible(bool(hint))
        header_layout.addWidget(self._title)
        header_layout.addStretch(1)
        header_layout.addWidget(self._hint)
        root.addWidget(header)

        self.body = QWidget(self)
        self.body.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(self.body)
        self._body_layout.setContentsMargins(12, 4, 12, 12)
        self._body_layout.setSpacing(8)
        root.addWidget(self.body)
        self._header_height = 0

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        _fill_card(painter, self.rect().adjusted(0, 0, -1, -1))
        bottom = self.body.geometry().top() - 2
        painter.setPen(BORDER)
        painter.drawLine(1, bottom, self.width() - 2, bottom)
        painter.end()


class CompareRunsAxisView(_Card):
    """Every metric the two runs disagree on, widest gap first."""

    def __init__(self, parent=None, *, row_capacity: int = 12) -> None:
        super().__init__("All differences on one axis", "length = relative difference", parent)
        legend = QWidget(self.body)
        legend.setStyleSheet("background: transparent;")
        legend_layout = QHBoxLayout(legend)
        legend_layout.setContentsMargins(0, 0, 0, 2)
        left = _label(legend, RUN_A_TEXT, bold=True, size=10.5)
        left.setText("◀  A AHEAD")
        right = _label(legend, RUN_B_TEXT, bold=True, size=10.5, align=Qt.AlignRight | Qt.AlignVCenter)
        right.setText("B AHEAD  ▶")
        legend_layout.addWidget(left)
        legend_layout.addStretch(1)
        legend_layout.addWidget(right)
        self._legend = legend
        self.body_layout().addWidget(legend)

        self._empty = _label(self.body, SECONDARY, size=12)
        self._empty.setWordWrap(True)
        self._empty.setVisible(False)
        self.body_layout().addWidget(self._empty)

        self._rows: list[_AxisRowView] = []
        self._visible_rows = 0
        self._table: AxisTable = EMPTY_AXIS_TABLE
        self._ensure_capacity(max(0, int(row_capacity)))

    def set_table(self, table: AxisTable | None) -> None:
        table = table if table is not None else EMPTY_AXIS_TABLE
        if table == self._table:
            return
        self._table = table

        rows = table.rows
        self._empty.setText(str(table.empty_text))
        self._empty.setVisible(not rows and bool(table.empty_text))
        self._legend.setVisible(bool(rows))
        self._ensure_capacity(len(rows))
        for index, row in enumerate(rows):
            self._rows[index].set_row(row)
        self._set_visible_rows(len(rows))

    def _ensure_capacity(self, count: int) -> None:
        while len(self._rows) < count:
            row = _AxisRowView(self.body)
            row.setVisible(False)
            self.body_layout().addWidget(row)
            self._rows.append(row)

    def _set_visible_rows(self, count: int) -> None:
        if count == self._visible_rows:
            return
        low, high = sorted((count, self._visible_rows))
        for index in range(low, high):
            self._rows[index].setVisible(index < count)
        self._visible_rows = count


class _LuckTile(QFrame):
    """One inset tile: a label, one big value, one quiet line under it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(2)
        self._label = _label(self, SECONDARY, bold=True, size=10.5)
        self._value = _label(self, TEXT, bold=True, size=19)
        self._value.setWordWrap(True)
        self._detail = _label(self, MUTED, size=11)
        self._detail.setWordWrap(True)
        layout.addWidget(self._label)
        layout.addWidget(self._value)
        layout.addWidget(self._detail)
        self._value_color = TEXT
        self._value_size = 19.0

    def set_tile(self, label: str, value: str, detail: str, color: str, *, size: float = 19) -> None:
        self._label.setText(label)
        self._value.setText(value)
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))
        if (color, size) != (self._value_color, self._value_size):
            self._value_color = color
            self._value_size = size
            self._value.setStyleSheet(_style(color, bold=True, size=size))

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        _fill_card(painter, self.rect().adjusted(0, 0, -1, -1), surface=SURFACE_INSET)
        painter.end()


class _RungView(QFrame):
    """One rarity tier: both sides' actual against expected, drawn as a bar."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(30)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 5, 9, 5)
        layout.setSpacing(8)
        self._rarity = _label(self, TEXT, bold=True, size=11.5)
        self._rarity.setFixedWidth(78)
        self._sides: list[dict] = []
        for side, color in (("A", RUN_A_TEXT), ("B", RUN_B_TEXT)):
            tag = _label(self, color, bold=True, size=10.5)
            tag.setText(side)
            tag.setFixedWidth(12)
            track = QWidget(self)
            track.setStyleSheet("background: transparent;")
            track.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            counts = _label(
                self, HEADING, size=11, align=Qt.AlignRight | Qt.AlignVCenter
            )
            counts.setFixedWidth(74)
            layout.addWidget(tag)
            layout.addWidget(track, 1)
            layout.addWidget(counts)
            self._sides.append({"track": track, "counts": counts, "ratio": None})
        layout.insertWidget(0, self._rarity)
        self._rarity_color = TEXT

    def set_rung(self, rung, color: str) -> None:
        self._rarity.setText(str(rung.rarity))
        if self._rarity_color != color:
            self._rarity_color = color
            self._rarity.setStyleSheet(_style(color, bold=True, size=11.5))
        for side, actual, expected, ratio in (
            (self._sides[0], rung.actual_a, rung.expected_a, rung.ratio_a),
            (self._sides[1], rung.actual_b, rung.expected_b, rung.ratio_b),
        ):
            side["ratio"] = ratio
            side["counts"].setText(
                "not measured" if actual == "--" else f"{actual} / {expected}"
            )
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        _fill_card(painter, self.rect().adjusted(0, 0, -1, -1), surface=SURFACE_INSET)
        for side in self._sides:
            rect = side["track"].geometry().adjusted(0, 9, 0, -9)
            ratio = side["ratio"]
            if ratio is None:
                # Still draw the empty track: a tier with no expectation has to
                # look like "nothing to compare", not like a missing row.
                _draw_diverging_bar(painter, rect, 0.0, GOOD, to_left=False)
                continue
            # A surplus grows right and green, a shortfall left and red. The
            # bar saturates at double-or-nothing, which is well past the point
            # where the count beside it is the thing being read.
            offset = max(-1.0, min(1.0, float(ratio) - 1.0))
            _draw_diverging_bar(
                painter,
                rect,
                abs(offset),
                GOOD if offset >= 0 else BAD,
                to_left=offset < 0,
            )
        painter.end()


class _ChestCell(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        layout.setSpacing(3)
        self._label = _label(self, SECONDARY, bold=True, size=10.5)
        values = QWidget(self)
        values.setStyleSheet("background: transparent;")
        values_layout = QHBoxLayout(values)
        values_layout.setContentsMargins(0, 0, 0, 0)
        values_layout.setSpacing(9)
        # A step up from the rarity ladder above: these are the row the eye
        # lands on after the four big index tiles, and at 11.5 they read as a
        # footnote to the ladder rather than as their own row of numbers.
        self._value_a = _label(self, HEADING, size=13)
        self._value_b = _label(self, HEADING, size=13)
        tag_a = _label(self, RUN_A_TEXT, bold=True, size=11.5)
        tag_a.setText("A")
        tag_b = _label(self, RUN_B_TEXT, bold=True, size=11.5)
        tag_b.setText("B")
        values_layout.addWidget(tag_a)
        values_layout.addWidget(self._value_a)
        values_layout.addWidget(tag_b)
        values_layout.addWidget(self._value_b)
        values_layout.addStretch(1)
        layout.addWidget(self._label)
        layout.addWidget(values)

    def set_row(self, row) -> None:
        self._label.setText(str(row.label))
        self._value_a.setText(str(row.value_a))
        self._value_b.setText(str(row.value_b))

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        _fill_card(painter, self.rect().adjusted(0, 0, -1, -1), surface=SURFACE_INSET)
        painter.end()


class CompareRunsLuckLootView(_Card):
    """Did the run build better, or draw better?"""

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Luck & Loot", "what dropped against what the run's Luck predicted", parent
        )
        self._notice = _label(self.body, WARN_TEXT, size=11.5)
        self._notice.setWordWrap(True)
        self._notice.setVisible(False)
        self.body_layout().addWidget(self._notice)

        self._tiles_host = QWidget(self.body)
        self._tiles_host.setStyleSheet("background: transparent;")
        self._tiles_grid = QGridLayout(self._tiles_host)
        self._tiles_grid.setContentsMargins(0, 0, 0, 0)
        self._tiles_grid.setHorizontalSpacing(8)
        self._tiles_grid.setVerticalSpacing(8)
        self._tiles = [_LuckTile(self._tiles_host) for _ in range(4)]
        self.body_layout().addWidget(self._tiles_host)

        self._ladder_host = QWidget(self.body)
        self._ladder_host.setStyleSheet("background: transparent;")
        ladder_layout = QVBoxLayout(self._ladder_host)
        ladder_layout.setContentsMargins(0, 0, 0, 0)
        ladder_layout.setSpacing(5)
        self._rungs = [
            _RungView(self._ladder_host)
            for _ in range(len(ITEM_RARITY_COLOR_MAP))
        ]
        for rung in self._rungs:
            rung.setVisible(False)
            ladder_layout.addWidget(rung)
        self.body_layout().addWidget(self._ladder_host)

        self._chest_host = QWidget(self.body)
        self._chest_host.setStyleSheet("background: transparent;")
        self._chest_grid = QGridLayout(self._chest_host)
        self._chest_grid.setContentsMargins(0, 0, 0, 0)
        self._chest_grid.setHorizontalSpacing(8)
        self._chest_grid.setVerticalSpacing(8)
        self._chests = [_ChestCell(self._chest_host) for _ in range(4)]
        self.body_layout().addWidget(self._chest_host)

        self._columns = 0
        self._payload: LuckLoot = EMPTY_LUCK_LOOT
        self._reflow(4)

    def set_payload(self, payload: LuckLoot | None) -> None:
        payload = payload if payload is not None else EMPTY_LUCK_LOOT
        if payload == self._payload:
            return
        self._payload = payload

        self._notice.setText(payload.notice)
        self._notice.setVisible(bool(payload.notice))

        self._tiles[0].set_tile(
            "A · LUCK INDEX",
            payload.index_a,
            payload.detail_a,
            _index_color(payload.index_a, payload.available_a),
        )
        self._tiles[1].set_tile(
            "B · LUCK INDEX",
            payload.index_b,
            payload.detail_b,
            _index_color(payload.index_b, payload.available_b),
        )
        self._tiles[2].set_tile(
            "LUCK (STAT)",
            f"{payload.luck_a} → {payload.luck_b}",
            f"A − B  {payload.luck_delta}",
            TEXT,
            size=16,
        )
        self._tiles[3].set_tile(
            "VERDICT",
            payload.verdict or "—",
            payload.verdict_detail,
            HEADING if payload.verdict else MUTED,
            size=12.5,
        )

        rungs = payload.rungs
        for index, rung in enumerate(self._rungs):
            visible = index < len(rungs)
            if visible:
                rarity = str(rungs[index].rarity).upper()
                rung.set_rung(
                    rungs[index], ITEM_RARITY_COLOR_MAP.get(rarity, TEXT)
                )
            rung.setVisible(visible)
        self._ladder_host.setVisible(bool(rungs))

        chests = payload.chests
        for index, cell in enumerate(self._chests):
            visible = index < len(chests)
            if visible:
                cell.set_row(chests[index])
            cell.setVisible(visible)
        self._chest_host.setVisible(bool(chests))

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().resizeEvent(event)
        width = event.size().width()
        self._reflow(1 if width < NARROW_WIDTH else 2 if width < MEDIUM_WIDTH else 4)

    def _reflow(self, columns: int) -> None:
        if columns == self._columns:
            return
        self._columns = columns
        for grid, widgets in ((self._tiles_grid, self._tiles), (self._chest_grid, self._chests)):
            for index, widget in enumerate(widgets):
                grid.addWidget(widget, index // columns, index % columns)
            for column in range(4):
                grid.setColumnStretch(column, 1 if column < columns else 0)


def _index_color(index: str, available: bool) -> str:
    if not available or index == "--":
        return MUTED
    try:
        ratio = float(str(index).rstrip("x"))
    except ValueError:
        return TEXT
    if ratio >= 1.05:
        return "#22C55E"
    if ratio <= 0.95:
        return "#FB7185"
    return TEXT


class _HubTile(QFrame):
    """A jump target. The old Overview had none, which is why it was a dead end."""

    clicked = Signal(str)

    def __init__(self, target: str, parent=None) -> None:
        super().__init__(parent)
        self._target = target
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(10)
        text = QWidget(self)
        text.setStyleSheet("background: transparent;")
        text_layout = QVBoxLayout(text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        self._where = _label(text, MUTED, bold=True, size=10)
        self._where.setText(target.upper())
        self._fact = _label(text, TEXT, bold=True, size=12.5)
        text_layout.addWidget(self._where)
        text_layout.addWidget(self._fact)
        arrow = _label(self, "#5B9BDD", bold=True, size=13)
        arrow.setText("→")
        layout.addWidget(text, 1)
        layout.addWidget(arrow)
        self._hovered = False

    def set_fact(self, fact: str) -> None:
        self._fact.setText(fact)

    def enterEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self._target)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, QColor("#10161F") if self._hovered else SURFACE)
        painter.setPen(QColor("#3E82C6") if self._hovered else BORDER)
        painter.drawPath(path)
        painter.end()


class CompareRunsHubView(QWidget):
    """The three jump targets under the axis."""

    jumpRequested = Signal(str)

    def __init__(self, targets: tuple[str, ...], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CompareRunsOverviewHubs")
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(8)
        self._tiles: dict[str, _HubTile] = {}
        for target in targets:
            tile = _HubTile(target, self)
            tile.setVisible(False)
            tile.clicked.connect(self.jumpRequested)
            self._tiles[target] = tile
        self._facts: dict[str, str] = {}
        self._visible: tuple[_HubTile, ...] = ()
        self._columns = 0
        self.setVisible(False)

    def set_facts(self, facts: dict[str, str]) -> None:
        """A target with no fact gets no tile -- see `build_hub_facts`."""
        if facts == self._facts:
            return
        self._facts = dict(facts)
        for target, tile in self._tiles.items():
            fact = facts.get(target, "")
            if fact:
                tile.set_fact(fact)
            tile.setVisible(bool(fact))
        self._visible = tuple(
            tile for target, tile in self._tiles.items() if facts.get(target)
        )
        self.setVisible(bool(self._visible))
        self._columns = 0
        self._reflow(1 if self.width() < NARROW_WIDTH else max(1, len(self._visible)))

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().resizeEvent(event)
        self._reflow(
            1 if event.size().width() < NARROW_WIDTH else max(1, len(self._visible))
        )

    def _reflow(self, columns: int) -> None:
        columns = max(1, columns)
        if columns == self._columns:
            return
        self._columns = columns
        for index, tile in enumerate(self._visible):
            self._grid.addWidget(tile, index // columns, index % columns)
        for column in range(len(self._tiles)):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
