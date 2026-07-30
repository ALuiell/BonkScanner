"""A widget that renders a `MetricTable` -- the compare-runs diff cards.

Why this exists is a measurement. The Weapons, Tomes and Chaos cards were
`QLabel`s holding 7--16 KB of `<table>` HTML, and Qt re-parsed and re-laid-out
the whole document on every write: 63 ms, 62 ms and 23 ms per card against
0.26 ms for the entire Python half of a scrub frame. The frame was ~200 ms and
essentially all of it was rich-text layout.

Four renderers were measured on the same content (32 rows x 4 columns, header,
zebra, right-aligned numbers, coloured delta), updating once per frame:

    QLabel + <table>                67.3 ms   (as shipped)
    QLabel + flat <br> rows          6.7 ms   loses the columns and the zebra
    pooled QGridLayout of QLabels    3.7 ms   this file
    QTreeWidget                      2.0 ms

The tree is marginally faster but brings its own scroll area and header into a
card that already lives inside one, and needs a stylesheet the app does not
have. The grid is the one that keeps the look under our control: real column
alignment rather than an HTML approximation of it, and no nested scrolling.

Two rules keep it fast, and breaking either puts the cost back:

* cells are created once and pooled -- a repaint replaces text, never widgets;
* the delta colour is restyled only when its **direction** changes, because
  `setStyleSheet` triggers a style recalculation and doing it per row per frame
  costs more than the text ever did.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from projections.metric_table import (
    DELTA_NEGATIVE,
    DELTA_POSITIVE,
    EMPTY_METRIC_TABLE,
    MetricTable,
)

#: Same palette the HTML cards used, so the change is invisible except for the
#: alignment being real.
CARD_BACKGROUND = QColor("#0F1722")
CARD_BORDER = QColor("#1E2A3A")
HEADER_RULE = QColor("#26364A")
ROW_RULE = QColor("#1E2A3A")
ZEBRA_BACKGROUND = QColor("#121C28")

TEXT_COLOR = "#E5E7EB"
MUTED_COLOR = "#98A7BA"
DELTA_COLORS = {
    DELTA_POSITIVE: "#22C55E",
    DELTA_NEGATIVE: "#FB7185",
}

#: The HTML tables used width="52%"/16/16/16; the same proportions as stretch
#: factors keep every card's columns lined up with every other card's.
COLUMN_STRETCH = (52, 16, 16, 16)


def _cell_style(color: str, *, bold: bool = False) -> str:
    """A cell's stylesheet, always transparent.

    The app stylesheet carries a global `QWidget { background: #10141B; }`, and
    giving a widget any stylesheet of its own routes it through
    `QStyleSheetStyle`, which then paints that background. Without the explicit
    `transparent` here every cell tiles its own dark rectangle over the zebra
    this widget paints, leaving a visible seam in each gap between columns.
    """
    weight = " font-weight:700;" if bold else ""
    return f"color:{color}; background: transparent;{weight}"

_ROW_PADDING = 5
_CARD_SPACING = 8


class MetricSectionView(QWidget):
    """One section: a heading row, then the metric rows under it.

    The card's chrome -- background, border, header rule, row rules, zebra --
    is painted here rather than applied as per-cell stylesheets, which is what
    makes a repaint cost nothing beyond the text.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(10, 7, 10, 7)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(_ROW_PADDING)
        for column, stretch in enumerate(COLUMN_STRETCH):
            self._grid.setColumnStretch(column, stretch)

        # Title and subtitle share the first header cell, so they live in one
        # container rather than being stacked into the same grid cell with
        # opposing alignments -- which overlaps as soon as a name is long.
        self._heading = QWidget(self)
        self._heading.setStyleSheet("background: transparent;")
        heading_layout = QHBoxLayout(self._heading)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(6)
        self._title_label = QLabel(self._heading)
        self._title_label.setStyleSheet(_cell_style(TEXT_COLOR, bold=True))
        self._subtitle_label = QLabel(self._heading)
        self._subtitle_label.setStyleSheet(_cell_style(MUTED_COLOR))
        heading_layout.addWidget(self._title_label)
        heading_layout.addWidget(self._subtitle_label)
        heading_layout.addStretch(1)
        self._grid.addWidget(self._heading, 0, 0)

        self._header_cells: list[QLabel] = []
        for column in range(1, len(COLUMN_STRETCH)):
            cell = QLabel()
            cell.setStyleSheet(_cell_style(MUTED_COLOR, bold=True))
            cell.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._grid.addWidget(cell, 0, column)
            self._header_cells.append(cell)

        self._rows: list[list[QLabel]] = []
        self._row_directions: list[str | None] = []
        self._row_label_colors: list[str | None] = []
        self._visible_row_count = 0
        self._heading_color = TEXT_COLOR

    # -- rendering ------------------------------------------------------------

    def set_section(self, section) -> None:
        title = str(section.title or "")
        subtitle = str(section.subtitle or "")
        # A named entity puts its name and level in the first header cell; a
        # plain table puts a column name there instead.
        self._title_label.setText(title or str(section.headers[0]))
        self._subtitle_label.setText(subtitle)
        self._subtitle_label.setVisible(bool(subtitle))
        # A plain table's first header cell is a column name, so it reads as a
        # header; an entity's name reads as a heading.
        heading_color = TEXT_COLOR if title else MUTED_COLOR
        if self._heading_color != heading_color:
            self._heading_color = heading_color
            self._title_label.setStyleSheet(_cell_style(heading_color, bold=True))
        for cell, header in zip(self._header_cells, section.headers[1:]):
            cell.setText(str(header))

        rows = section.rows
        self._ensure_row_capacity(len(rows))
        for index, row in enumerate(rows):
            cells = self._rows[index]
            cells[0].setText(row.label)
            cells[1].setText(row.value_a)
            cells[2].setText(row.value_b)
            cells[3].setText(row.delta)
            direction = row.direction
            if self._row_directions[index] != direction:
                self._row_directions[index] = direction
                cells[3].setStyleSheet(
                    _cell_style(DELTA_COLORS.get(direction, MUTED_COLOR), bold=True)
                )
            # Same rule as the delta: restyle on change only. The Items card is
            # the only one that colours labels, and its rows are re-sorted by
            # rarity, so the colour of a given row index changes rarely.
            label_color = row.label_color or MUTED_COLOR
            if self._row_label_colors[index] != label_color:
                self._row_label_colors[index] = label_color
                cells[0].setStyleSheet(
                    _cell_style(label_color, bold=bool(row.label_color))
                )
        self._set_visible_row_count(len(rows))

    def _ensure_row_capacity(self, count: int) -> None:
        while len(self._rows) < count:
            index = len(self._rows)
            cells: list[QLabel] = []
            for column in range(len(COLUMN_STRETCH)):
                cell = QLabel()
                if column == 0:
                    cell.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    cell.setStyleSheet(_cell_style(MUTED_COLOR))
                else:
                    cell.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    # The delta column is styled on its first row write, by
                    # direction; the value columns never change colour.
                    cell.setStyleSheet(_cell_style(TEXT_COLOR))
                self._grid.addWidget(cell, index + 1, column)
                cells.append(cell)
            self._rows.append(cells)
            self._row_directions.append(None)
            self._row_label_colors.append(MUTED_COLOR)

    def _set_visible_row_count(self, count: int) -> None:
        if count == self._visible_row_count:
            return
        # Only the rows crossing the boundary change visibility, so a card whose
        # row count is stable -- which is most frames -- does nothing here.
        low, high = sorted((count, self._visible_row_count))
        for index in range(low, high):
            for cell in self._rows[index]:
                cell.setVisible(index < count)
        self._visible_row_count = count

    # -- chrome ---------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, CARD_BACKGROUND)

        if self._visible_row_count:
            for index in range(self._visible_row_count):
                if index % 2:
                    continue
                painter.fillRect(self._row_rect(index), ZEBRA_BACKGROUND)

        header_bottom = self._heading.geometry().bottom() + _ROW_PADDING // 2
        painter.setPen(HEADER_RULE)
        painter.drawLine(rect.left(), header_bottom, rect.right(), header_bottom)
        painter.setPen(ROW_RULE)
        for index in range(self._visible_row_count - 1):
            bottom = self._row_rect(index).bottom()
            painter.drawLine(rect.left(), bottom, rect.right(), bottom)
        painter.setPen(CARD_BORDER)
        painter.drawRect(rect)
        painter.end()
        super().paintEvent(event)

    def _row_rect(self, index: int):
        cells = self._rows[index]
        geometry = cells[0].geometry().united(cells[-1].geometry())
        return geometry.adjusted(
            -self._grid.contentsMargins().left(),
            -(_ROW_PADDING // 2),
            self._grid.contentsMargins().right(),
            _ROW_PADDING // 2,
        )


class MetricTableView(QWidget):
    """A stack of `MetricSectionView`s, pooled across repaints."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(_CARD_SPACING)
        self._empty_label = QLabel()
        self._empty_label.setStyleSheet(_cell_style(MUTED_COLOR))
        self._empty_label.setWordWrap(True)
        self._empty_label.setVisible(False)
        self._layout.addWidget(self._empty_label)
        self._sections: list[MetricSectionView] = []
        self._visible_section_count = 0
        self._table: MetricTable = EMPTY_METRIC_TABLE

    @property
    def table(self) -> MetricTable:
        return self._table

    def set_table(self, table: MetricTable | None) -> None:
        """Render `table`. Repeating the current one is a no-op.

        The tab dirty-checks its whole card payload before calling here, but a
        second check costs one comparison of two frozen dataclasses and makes
        this widget safe to drive from anywhere.
        """
        table = table if table is not None else EMPTY_METRIC_TABLE
        if table == self._table:
            return
        self._table = table

        sections = table.sections
        if not sections:
            # No caption means "render nothing": the Items card writes an empty
            # table whenever its details are folded away, and a stray `--` under
            # the summary line would be worse than an empty card.
            self._empty_label.setText(str(table.empty_text))
            self._empty_label.setVisible(bool(table.empty_text))
            self._set_visible_section_count(0)
            return

        self._empty_label.setVisible(False)
        while len(self._sections) < len(sections):
            view = MetricSectionView(self)
            self._layout.addWidget(view)
            self._sections.append(view)
        for index, section in enumerate(sections):
            self._sections[index].set_section(section)
        self._set_visible_section_count(len(sections))

    def _set_visible_section_count(self, count: int) -> None:
        if count == self._visible_section_count:
            return
        low, high = sorted((count, self._visible_section_count))
        for index in range(low, high):
            self._sections[index].setVisible(index < count)
        self._visible_section_count = count


class CompactMetricCellView(QFrame):
    """One compact ``label / A / B / delta`` cell inside a comparison card.

    The widgets are allocated once and only their text changes while scrubbing.
    Delta styles are updated only when their direction changes, mirroring the
    performance rule used by :class:`MetricSectionView`.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CompareRunsMetricCell")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        layout = QGridLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setHorizontalSpacing(5)
        layout.setVerticalSpacing(2)
        layout.setColumnStretch(1, 1)

        self._label = QLabel(self)
        self._label.setObjectName("CompareRunsMetricLabel")
        layout.addWidget(self._label, 0, 0, 1, 2)

        self._run_labels: list[QLabel] = []
        self._value_labels: list[QLabel] = []
        for row_index, side in enumerate(("A", "B"), start=1):
            run_label = QLabel(side, self)
            run_label.setObjectName("CompareRunsMetricRunLabel")
            run_label.setProperty("side", side)
            value_label = QLabel(self)
            value_label.setObjectName("CompareRunsMetricValue")
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(run_label, row_index, 0)
            layout.addWidget(value_label, row_index, 1)
            self._run_labels.append(run_label)
            self._value_labels.append(value_label)

        self._delta = QLabel(self)
        self._delta.setObjectName("CompareRunsMetricDelta")
        self._delta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._delta, 3, 0, 1, 2)

        self._direction: str | None = None
        self._label_color: str | None = None

    def set_row(self, row) -> None:
        self._label.setText(str(row.label))
        self._value_labels[0].setText(str(row.value_a))
        self._value_labels[1].setText(str(row.value_b))
        self._delta.setText(f"Δ {row.delta}")

        direction = row.direction
        # Finishing a stage sooner is an improvement, unlike the count metrics.
        if str(row.label).casefold() == "time":
            if direction == DELTA_POSITIVE:
                direction = DELTA_NEGATIVE
            elif direction == DELTA_NEGATIVE:
                direction = DELTA_POSITIVE
        if self._direction != direction:
            self._direction = direction
            self._delta.setStyleSheet(
                _cell_style(DELTA_COLORS.get(direction, MUTED_COLOR), bold=True)
            )

        label_color = str(row.label_color or "")
        if self._label_color != label_color:
            self._label_color = label_color
            self._label.setStyleSheet(
                _cell_style(label_color, bold=True) if label_color else ""
            )


class CompactMetricCardView(QFrame):
    """A compact section card whose metric cells are pooled and reused."""

    def __init__(
        self,
        parent=None,
        *,
        metric_capacity: int = 4,
        metrics_per_row: int = 4,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CompareRunsComparisonCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._metrics_per_row = max(1, int(metrics_per_row))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame(self)
        header.setObjectName("CompareRunsComparisonCardHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(9, 7, 9, 7)
        header_layout.setSpacing(7)
        self._badge = QLabel(header)
        self._badge.setObjectName("CompareRunsComparisonCardBadge")
        self._badge.setAlignment(Qt.AlignCenter)
        self._title = QLabel(header)
        self._title.setObjectName("CompareRunsComparisonCardTitle")
        self._meta = QLabel(header)
        self._meta.setObjectName("CompareRunsComparisonCardMeta")
        self._meta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header_layout.addWidget(self._badge)
        header_layout.addWidget(self._title)
        header_layout.addStretch(1)
        header_layout.addWidget(self._meta)
        root.addWidget(header)

        metrics = QWidget(self)
        metrics.setObjectName("CompareRunsComparisonMetrics")
        self._metrics_layout = QGridLayout(metrics)
        self._metrics_layout.setContentsMargins(0, 0, 0, 0)
        self._metrics_layout.setHorizontalSpacing(1)
        self._metrics_layout.setVerticalSpacing(1)
        for column in range(self._metrics_per_row):
            self._metrics_layout.setColumnStretch(column, 1)
        root.addWidget(metrics)

        self._cells: list[CompactMetricCellView] = []
        self._visible_cell_count = 0
        self._ensure_cell_capacity(max(0, int(metric_capacity)))

    def set_section(self, section, *, fallback_number: int) -> None:
        title = str(section.title or section.headers[0])
        self._title.setText(title)
        suffix = title.rsplit(" ", 1)[-1]
        self._badge.setText(suffix if suffix.isdigit() else str(fallback_number))

        rows = section.rows
        changed = sum(
            str(row.delta).strip() not in {"", "--", "0", "+0", "-0", "+0s", "-0s"}
            for row in rows
        )
        meta_parts = []
        if section.subtitle:
            meta_parts.append(str(section.subtitle))
        elif rows and str(rows[0].label).casefold() == "time":
            meta_parts.append(f"{rows[0].value_a} vs {rows[0].value_b}")
        meta_parts.append(f"{changed} changes")
        self._meta.setText(" · ".join(meta_parts))

        self._ensure_cell_capacity(len(rows))
        for index, row in enumerate(rows):
            self._cells[index].set_row(row)
        self._set_visible_cell_count(len(rows))

    def _ensure_cell_capacity(self, count: int) -> None:
        while len(self._cells) < count:
            index = len(self._cells)
            cell = CompactMetricCellView(self)
            self._metrics_layout.addWidget(
                cell,
                index // self._metrics_per_row,
                index % self._metrics_per_row,
            )
            cell.setVisible(False)
            self._cells.append(cell)

    def _set_visible_cell_count(self, count: int) -> None:
        if count == self._visible_cell_count:
            return
        low, high = sorted((count, self._visible_cell_count))
        for index in range(low, high):
            self._cells[index].setVisible(index < count)
        self._visible_cell_count = count


class CompactMetricCardGridView(QWidget):
    """A responsive two-column grid of pooled compact comparison cards."""

    def __init__(
        self,
        parent=None,
        *,
        section_capacity: int = 4,
        metric_capacity: int = 4,
        metrics_per_row: int = 4,
        narrow_breakpoint: int = 900,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CompareRunsCompactMetricGrid")
        self._metric_capacity = max(0, int(metric_capacity))
        self._metrics_per_row = max(1, int(metrics_per_row))
        self._narrow_breakpoint = max(1, int(narrow_breakpoint))
        self._column_count = 2

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(_CARD_SPACING)

        self._empty_label = QLabel(self)
        self._empty_label.setObjectName("CompareRunsCompactMetricEmpty")
        self._empty_label.setWordWrap(True)
        self._empty_label.setVisible(False)
        root.addWidget(self._empty_label)

        self._cards_host = QWidget(self)
        self._cards_host.setObjectName("CompareRunsCompactMetricCards")
        self._grid = QGridLayout(self._cards_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(_CARD_SPACING)
        self._grid.setVerticalSpacing(_CARD_SPACING)
        root.addWidget(self._cards_host)

        self._cards: list[CompactMetricCardView] = []
        self._visible_section_count = 0
        self._table: MetricTable = EMPTY_METRIC_TABLE
        self._ensure_section_capacity(max(0, int(section_capacity)))
        self._reflow_cards()

    @property
    def table(self) -> MetricTable:
        return self._table

    @property
    def column_count(self) -> int:
        return self._column_count

    def set_table(self, table: MetricTable | None) -> None:
        table = table if table is not None else EMPTY_METRIC_TABLE
        if table == self._table:
            return
        self._table = table

        sections = table.sections
        self._empty_label.setText(str(table.empty_text))
        self._empty_label.setVisible(not sections and bool(table.empty_text))
        self._cards_host.setVisible(bool(sections))
        if not sections:
            self._set_visible_section_count(0)
            return

        self._ensure_section_capacity(len(sections))
        for index, section in enumerate(sections):
            self._cards[index].set_section(section, fallback_number=index + 1)
        self._set_visible_section_count(len(sections))

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().resizeEvent(event)
        columns = 1 if event.size().width() < self._narrow_breakpoint else 2
        if columns != self._column_count:
            self._column_count = columns
            self._reflow_cards()

    def _ensure_section_capacity(self, count: int) -> None:
        while len(self._cards) < count:
            card = CompactMetricCardView(
                self._cards_host,
                metric_capacity=self._metric_capacity,
                metrics_per_row=self._metrics_per_row,
            )
            card.setVisible(False)
            self._cards.append(card)
        self._reflow_cards()

    def _reflow_cards(self) -> None:
        if not hasattr(self, "_grid"):
            return
        for index, card in enumerate(self._cards):
            self._grid.addWidget(
                card,
                index // self._column_count,
                index % self._column_count,
            )
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1 if self._column_count == 2 else 0)

    def _set_visible_section_count(self, count: int) -> None:
        if count == self._visible_section_count:
            return
        low, high = sorted((count, self._visible_section_count))
        for index in range(low, high):
            self._cards[index].setVisible(index < count)
        self._visible_section_count = count
