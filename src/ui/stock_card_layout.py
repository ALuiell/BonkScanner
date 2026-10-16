"""Screen-space stock card layout; no game reads or marker coordinate changes."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import ceil, floor

from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QFontMetricsF, QGuiApplication, QTextLayout, QTextOption

from core.item_metadata import ITEMS
from core.shady_prices import format_shady_price
from core.map_markers import MAP_MARKER_ACTIONS, MapViewport, MerchantStockCapture, WorldMapMarker


StockEntry = tuple[WorldMapMarker, MerchantStockCapture, tuple[float, float, float]]


@dataclass(frozen=True)
class StockGroup:
    entries: tuple[StockEntry, ...]
    bounds: QRectF


@dataclass(frozen=True)
class StockCardPlan:
    group: StockGroup
    bounds: QRectF
    entries: tuple[StockEntry, ...]
    compact: bool = False


def marker_bounds(geometry: tuple[float, float, float]) -> QRectF:
    x, y, size = geometry
    # Include the stock badge on the marker's upper-right shoulder.
    return QRectF(x - size * .55, y - size * .65, size * 1.2, size * 1.2)


def group_stock_entries(entries: tuple[StockEntry, ...]) -> tuple[StockGroup, ...]:
    """Connected nearby icons, found with a screen-space grid, in stable order."""
    if not entries:
        return ()
    cell_size = max(48.0, max(e[2][2] for e in entries) * 1.4 + 12.0)
    parents = list(range(len(entries)))
    cells: dict[tuple[int, int], list[int]] = {}

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for i, (_, _, (x, y, size)) in enumerate(entries):
        cell = floor(x / cell_size), floor(y / cell_size)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cells.get((cell[0] + dx, cell[1] + dy), ()):
                    px, py, other_size = entries[j][2]
                    distance = max(48.0, (size + other_size) * .7 + 12.0)
                    if (x - px) ** 2 + (y - py) ** 2 <= distance ** 2:
                        parents[root(i)] = root(j)
        cells.setdefault(cell, []).append(i)

    grouped: dict[int, list[StockEntry]] = {}
    for i, entry in enumerate(entries):
        grouped.setdefault(root(i), []).append(entry)
    result = []
    for members in grouped.values():
        bounds = marker_bounds(members[0][2])
        for entry in members[1:]:
            bounds = bounds.united(marker_bounds(entry[2]))
        result.append(StockGroup(tuple(members), bounds))
    return tuple(result)


def hovered_stock_marker(groups: tuple[StockGroup, ...], cursor) -> str | None:
    """Pick one nearest merchant, never several overlapping hit circles."""
    if cursor is None:
        return None
    nearest = None
    best = float("inf")
    for group in groups:
        for marker, _stock, (x, y, size) in group.entries:
            distance = (cursor[0] - x) ** 2 + (cursor[1] - y) ** 2
            if distance <= max(34.0, size * .8) ** 2 and distance < best:
                nearest, best = marker.marker_id, distance
    return nearest


def _stock_item_metrics() -> QFontMetricsF:
    font = QFont("Segoe UI")
    font.setPixelSize(12)
    return QFontMetricsF(font)


def _measure_stock_card_width() -> float:
    """One catalog-based width for all cards; independent of marker icon scale."""
    metrics = _stock_item_metrics()
    widest = max(metrics.horizontalAdvance(f"• {item.ui_name or item.scanner_name}") for item in ITEMS)
    header = QFont("Segoe UI")
    header.setPixelSize(10)
    header.setBold(True)
    header_width = QFontMetricsF(header).horizontalAdvance("STOCK") + 37
    header.setPixelSize(11)
    merchant_metrics = QFontMetricsF(header)
    merchant_width = max(
        merchant_metrics.horizontalAdvance(f"1. {action.display_name}") + 46
        for action in MAP_MARKER_ACTIONS if action.family == "shady_guy"
    )
    # Cap unusually long future names; their full text wraps inside the card.
    return float(ceil(min(190.0, max(header_width, merchant_width, widest + 22))))


@lru_cache(maxsize=1)
def _cached_stock_card_width() -> float:
    return _measure_stock_card_width()


def stock_card_width() -> float:
    """Cache only after Qt exists; pre-app font metrics are platform defaults."""
    if QGuiApplication.instance() is None:
        return _measure_stock_card_width()
    return _cached_stock_card_width()


@lru_cache(maxsize=256)
def priced_stock_columns(items: tuple) -> tuple[float, float]:
    """One shared name column and coin/value column, measured only on changes."""
    name_width = min(190, ceil(max(
        (_stock_item_metrics().horizontalAdvance(f"• {item.display_name}") for item in items), default=0
    )))
    font = QFont('Segoe UI')
    font.setPixelSize(12)
    font.setBold(True)
    metrics = QFontMetricsF(font)
    value_width = ceil(max((metrics.horizontalAdvance(format_shady_price(item.price)) for item in items), default=0))
    return name_width, 11 + 4 + value_width


def priced_stock_card_width(items: tuple, grouped: bool) -> float:
    names, prices = priced_stock_columns(items)
    # 8 px side padding, 9 px between names and coins. Header may be wider.
    font = QFont('Segoe UI')
    font.setPixelSize(10)
    font.setBold(True)
    header = QFontMetricsF(font).horizontalAdvance('STOCK') + 37
    return ceil(max(names + 9 + prices + 16, header, 180 if grouped else 0))


@lru_cache(maxsize=512)
def stock_item_lines(name: str, available_width: int) -> tuple[str, ...]:
    """Share exact wrapping between geometry and paint, without per-frame work."""
    text = f"• {name}"
    width = max(1, available_width)
    metrics = _stock_item_metrics()
    if metrics.horizontalAdvance(text) <= width:
        return (text,)
    font = QFont("Segoe UI")
    font.setPixelSize(12)
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)
    lines = []
    layout.beginLayout()
    try:
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            lines.append(text[line.textStart():line.textStart() + line.textLength()].rstrip())
    finally:
        layout.endLayout()
    return tuple(lines)


def stock_items_height(stock: MerchantStockCapture, width: float, scale: float, *, name_width: float | None = None) -> float:
    row_height = max(16.0, 17.0 * scale)
    return row_height * sum(len(stock_item_lines(item.display_name, int(width - 22 if name_width is None else name_width))) for item in stock.items)


def stock_card_height(
    entries: tuple[StockEntry, ...], scale: float, grouped: bool, width: float | None = None,
    *, show_prices: bool = False,
) -> float:
    width = stock_card_width() if width is None else width
    name_width = None
    if show_prices:
        items = tuple(item for entry in entries for item in entry[1].items)
        names, prices = priced_stock_columns(items)
        name_width = max(1, min(names, width - 16 - 9 - prices))
    if not grouped:
        return 31.0 + stock_items_height(entries[0][1], width, scale, name_width=name_width)
    return 28.0 + sum(32.0 + stock_items_height(e[1], width, scale, name_width=name_width) for e in entries)


def _positions(anchor: QRectF, width: float, height: float, area: QRectF):
    """A fixed set of candidates, not an iterative physics/repulsion solver."""
    if width > area.width() or height > area.height():
        return ()
    x, y = anchor.center().x(), anchor.center().y()
    points = []
    for side in (anchor.right() + 9, anchor.left() - width - 9):
        for top in (y - height / 2, anchor.top(), anchor.bottom() - height):
            points.append((side, top))
    for top in (anchor.bottom() + 9, anchor.top() - height - 9):
        for left in (x - width / 2, anchor.left(), anchor.right() - width):
            points.append((left, top))
    return tuple(QRectF(
        max(area.left(), min(left, area.right() - width)),
        max(area.top(), min(top, area.bottom() - height)), width, height,
    ) for left, top in points)


def layout_stock_cards(
    groups: tuple[StockGroup, ...], viewport: MapViewport, scale: float,
    mode: str, hovered: str | None, obstacles: tuple[QRectF, ...] = (),
    *, show_prices: bool = False,
) -> tuple[StockCardPlan, ...]:
    area = QRectF(viewport.left, viewport.top, viewport.width, viewport.height).adjusted(5, 5, -5, -5)
    if area.width() < 80 or area.height() < 36:
        return ()
    occupied: list[QRectF] = []
    plans = []
    ordered = sorted(groups, key=lambda g: not any(e[0].marker_id == hovered for e in g.entries))
    for group in ordered:
        selected = tuple(e for e in group.entries if e[0].marker_id == hovered)
        if mode == "cursor" and not selected:
            continue
        grouped = len(group.entries) > 1
        entries = group.entries
        items = tuple(item for entry in entries for item in entry[1].items)
        width = min(area.width(), priced_stock_card_width(items, grouped) if show_prices else stock_card_width())
        height = stock_card_height(entries, scale, grouped, width, show_prices=show_prices)
        # An unusually large cluster must not allocate an enormous text bitmap.
        # Hover still exposes each member's stock individually in this case.
        if height > area.height() and selected:
            entries = selected
            height = stock_card_height(entries, scale, grouped, width, show_prices=show_prices)

        def score(rect):
            overlap = 0.0
            for other in (*obstacles, *occupied):
                intersection = rect.intersected(other)
                overlap += max(0.0, intersection.width()) * max(0.0, intersection.height())
            return overlap

        candidates = _positions(group.bounds, width, height, area)
        bounds = min(candidates, key=score) if candidates else None
        compact = False
        if bounds is None or (mode == "smart" and not selected and score(bounds) > 0):
            compact = True
            entries = ()
            candidates = _positions(group.bounds, min(width, 180.0), 36.0, area)
            bounds = min(candidates, key=score) if candidates else None
        if bounds is None:
            continue
        if compact and mode == "smart" and not selected and score(bounds) > 0:
            # No readable room even for the summary: keep the original marker
            # accessible instead of covering it with a label. Hover can still
            # reserve an expanded card on the next layout pass.
            continue
        # Never paint a later card over the currently inspected card. Smart
        # also omits a compact card if even it has nowhere readable to go.
        if any(bounds.intersects(other) for other in occupied):
            if mode != "always" or hovered is not None:
                continue
        occupied.append(bounds.adjusted(-4, -4, 4, 4))
        plans.append(StockCardPlan(group, bounds, entries, compact))
    # Hover first reserves its space above; paint it last as a final safeguard.
    plans.sort(key=lambda p: any(e[0].marker_id == hovered for e in p.group.entries))
    return tuple(plans)
