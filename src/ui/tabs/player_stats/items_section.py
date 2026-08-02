"""The Items panel, as an owned view -- for all four scopes.

Step 19, second commit, and the other half of `PlayerStatsCardsMixin`. Where
the stat-card panels turned out to be a two-scope surface that step 19 owned
outright, this one genuinely is four-scope: `live`, `vod`, `compare_a` and
`compare_b`.

Why four instances rather than a scope registry
===============================================

The step-19 brief offered a registry in which `live`/`vod` get real widget
groups and the two compare scopes get a temporary adapter over the shared
`self`, to be retired at step 21. That is rejected, because the roadmap's
"rules for steps 19-26" require the adapter to be gone at *this* step's merge
point, and because the adapter is not actually needed: nothing about the
compare scopes requires a different implementation. They differ from `live`
only in three constructor-visible ways --

* their initial sort mode is `rarity_desc` rather than the default,
* their toggle button starts captioned "Show all" and hidden,
* their widgets are built in `gui_layout._build_compare_run_panel`.

None of those is a behavioural fork; the first is a constructor argument and
the other two are just where and how the widgets are made. So Compare Runs
gets two ordinary instances of this class, constructed at the site that
already builds its widgets.

That is deliberately *not* the same thing as converting Compare Runs, which is
step 21's job and is not started here. `CompareRunsTabMixin` remains a mixin;
it simply holds a view object instead of nine string-keyed attributes per
side. What step 21 changes is where those two instances are constructed, not
whether they exist.

What the constructor makes visible
==================================

Five widgets and one initial mode, previously nine composed attribute names
per scope on the shared `MegabonkApp` (36 slots across the four). Four of the
nine were never widgets at all -- `_items_expanded`, `_items_sort_mode`,
`_items_current` and `_items_text_current` are this renderer's own state, and
it is the only reader or writer of any of them.

`update()` is called with the items to show; the view remembers them so that
`toggle_expanded()` and `on_sort_changed()` can re-render without their
callers having to hand the list back. That is what the three
`self.<prefix>_items_current` / `_items_text_current` reads at the old call
sites were doing.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QScrollArea,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
)

from projections import formatting
from projections.item_sort import ITEM_SORT_DEFAULT, ITEM_SORT_RARITY_DESC
from ui.shared import _clear_layout, _set_text

PREVIEW_MAX_CHARS = 90


#: Ceiling on the banish chips' own viewport -- two rows, then it scrolls.
#: Banishes sit under the item list in a panel of fixed height, and their flow
#: layout pushes a `minimumHeight` onto its container for every row it wraps, so
#: without a ceiling the section's minimum grew until it squeezed the list out.
#: Two rows rather than three because a QVBoxLayout takes a shortfall out of
#: whichever child has the most slack, and that is always the item list.
#:
#: Two 22px chip rows plus their 5px gap and enough viewport allowance for Qt's
#: scroll-area geometry. The viewport is fixed to this height while chips are
#: visible: merely raising its maximum still lets the surrounding layout keep
#: it at the smaller size hint and clip the second row.
BANISHES_CHIPS_MAX_HEIGHT = 66

#: Compact insets for the banishes footer: `(left, top, right, bottom)`.
#: The fixed chip viewport below already includes breathing room for two rows,
#: so a large bottom inset would only make the red frame unnecessarily tall.
BANISHES_SECTION_MARGINS = (8, 7, 8, 8)


class BanishesSectionView:
    """Render banishes as the same rarity chips used by the item surfaces."""

    def __init__(self, *, label, chips_container, chips_scroll=None) -> None:
        self._label = label
        self._chips_container = chips_container
        # The viewport the chips scroll inside, when there is one. Shown and
        # hidden with the container so an empty section is not a blank strip.
        self._chips_scroll = chips_scroll
        self._banishes: tuple[str, ...] | None = None

    def update(self, banishes=()) -> None:
        banishes = tuple(str(item) for item in (banishes or ()))
        if banishes == self._banishes:
            return
        self._banishes = banishes

        layout = self._chips_container.layout()
        self._chips_container.setUpdatesEnabled(False)
        try:
            _clear_layout(layout)
            if not banishes:
                self._label.setText("No banishes yet")
                self._label.setVisible(True)
                self._set_chips_visible(False)
                return

            self._label.setVisible(False)
            self._set_chips_visible(True)
            for item_text in banishes:
                display_text, object_name = formatting.item_chip_display(item_text)
                chip = QLabel(display_text)
                chip.setObjectName(object_name)
                layout.addWidget(chip)
        finally:
            self._chips_container.setUpdatesEnabled(True)
            self._chips_container.updateGeometry()
            self._chips_container.update()

    def _set_chips_visible(self, visible: bool) -> None:
        self._chips_container.setVisible(visible)
        if self._chips_scroll is not None:
            self._chips_scroll.setVisible(visible)


def update_banishes_section(view, fallback_label, banishes=()) -> None:
    """Use the chip view when built, preserving lightweight test adapters."""

    if view is not None:
        view.update(banishes)
        return
    _set_text(fallback_label, formatting.format_banishes_rich_text(banishes))


class CompactItemsSortComboBox(QComboBox):
    """A full sort menu behind a small, caption-free toolbar control.

    The glyph is painted, so its two colours come from the stylesheet through
    ``qproperty-`` for the same reason `LabeledSwitch`'s do: inlined here they
    were unreachable from the design asset, and the idle one (``#DDEEFF``) was
    not a palette value at all -- near text-primary ``#EDF1F5``, but not it.
    """

    hide_when_empty = True

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ItemsSortCombo")
        self.setFixedSize(38, 22)
        self._glyph_color = QColor("#EDF1F5")
        #: A non-default sort is active. Amber for the same reason the recording
        #: strip's `armed` segment is amber: a state worth noticing, not an error.
        self._glyph_active_color = QColor("#FACC15")
        self.view().setMinimumWidth(190)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Sort items")
        self.currentIndexChanged.connect(self._refresh_tooltip)
        self._refresh_tooltip()

    def _get_glyph_color(self) -> QColor:
        return self._glyph_color

    def _set_glyph_color(self, value: QColor) -> None:
        self._glyph_color = QColor(value)
        self.update()

    def _get_glyph_active_color(self) -> QColor:
        return self._glyph_active_color

    def _set_glyph_active_color(self, value: QColor) -> None:
        self._glyph_active_color = QColor(value)
        self.update()

    glyphColor = Property(QColor, _get_glyph_color, _set_glyph_color)
    glyphActiveColor = Property(QColor, _get_glyph_active_color, _set_glyph_active_color)

    def _refresh_tooltip(self, _index: int = -1) -> None:
        mode = self.currentText()
        self.setToolTip(f"Sort items: {mode}" if mode else "Sort items")

    def showPopup(self) -> None:
        # Qt derives the popup from the closed control's tiny geometry and can
        # otherwise fit only two of our three descriptive rows. Size the view
        # from its contents so every option is visible without a scroll arrow.
        row_heights = [
            max(22, self.view().sizeHintForRow(index))
            for index in range(self.count())
        ]
        self.view().setMinimumHeight(sum(row_heights) + 10)
        super().showPopup()

    def paintEvent(self, _event) -> None:
        # Keep the popup's descriptive item names, but draw a real descending
        # sort icon on the closed control. A font glyph was too small next to
        # the combo's own arrow and read as decoration rather than an action.
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)
        painter.setRenderHint(QPainter.Antialiasing)
        colour = QColor(
            self._glyph_active_color if self.currentIndex() > 0 else self._glyph_color
        )
        painter.setPen(QPen(colour, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

        # Down arrow at the left, then three progressively shorter bars. This
        # is the only icon: the combo's redundant system chevron is hidden.
        painter.drawLine(QPointF(11, 4.5), QPointF(11, 17.5))
        painter.drawLine(QPointF(8, 14.5), QPointF(11, 17.5))
        painter.drawLine(QPointF(14, 14.5), QPointF(11, 17.5))
        painter.drawLine(QPointF(17, 5.5), QPointF(29, 5.5))
        painter.drawLine(QPointF(17, 11), QPointF(25.5, 11))
        painter.drawLine(QPointF(17, 16.5), QPointF(22, 16.5))


class ItemsSectionView:
    """One scope's Items group: title, list, rarity summary, toggle and sort."""

    def __init__(
        self,
        *,
        group,
        label,
        rarity_label,
        toggle_btn,
        sort_combo,
        initial_sort_mode=ITEM_SORT_RARITY_DESC,
        chips_container=None,
        always_expanded: bool = False,
        scroll_area=None,
    ) -> None:
        self._group = group
        self._label = label
        self._rarity_label = rarity_label
        self._toggle_btn = toggle_btn
        self._sort_combo = sort_combo
        # Optional: a pre-built `FlowLayout` host the call site wires in
        # instead of (or alongside) `label`. When present, `update()` renders
        # each item as its own rarity-tagged chip widget rather than one
        # rich-text line -- everything else about the section (title, rarity
        # summary, toggle, sort) is unchanged and shared with the text path.
        self._chips_container = chips_container
        self._always_expanded = bool(always_expanded)
        self._scroll_area = scroll_area

        self._sort_mode = initial_sort_mode
        self._expanded = self._always_expanded
        self._items: tuple[str, ...] = ()
        self._items_text: str | None = None
        self._render_signature: tuple | None = None

    # -- rendering ------------------------------------------------------------

    def update(self, items=(), *, items_text: str | None = None) -> None:
        """Render `items`, or `items_text` in place of them.

        `items_text` is the "no data" path: it shows a literal string, blanks
        the rarity summary and disables the sort combo. Both are remembered so
        `toggle_expanded()` and `on_sort_changed()` can re-render.
        """
        self._items = tuple(items or ())
        self._items_text = items_text

        if self._label is None and self._chips_container is None:
            return
        render_signature = (
            self._items,
            self._items_text,
            self._sort_mode,
            self._expanded,
        )
        if render_signature == self._render_signature:
            return

        if items_text is not None:
            self._set_group_title(None)
            if self._label is not None:
                _set_items_text(self._label, items_text=items_text)
            self._render_chips((), placeholder=items_text)
            self._set_rarity_summary(())
            if self._toggle_btn is not None:
                self._toggle_btn.setVisible(True)
                self._toggle_btn.setEnabled(False)
                self._toggle_btn.setText("Show more")
            if self._sort_combo is not None:
                self._sort_combo.setEnabled(False)
                if getattr(self._sort_combo, "hide_when_empty", False):
                    self._sort_combo.setVisible(False)
            self._render_signature = render_signature
            return

        items = self._items
        self._set_group_title(formatting._item_total_count(items))
        self._set_rarity_summary(items)
        sorted_items = formatting.sort_items_for_display(items, self._sort_mode)
        preview_items, has_more = items_preview(sorted_items)
        visible_items = sorted_items if self._expanded or not has_more else preview_items
        if self._sort_combo is not None:
            self._sort_combo.setEnabled(bool(items))
            if getattr(self._sort_combo, "hide_when_empty", False):
                self._sort_combo.setVisible(bool(items))
        if self._label is not None:
            if hasattr(self._label, "setTextFormat"):
                text = formatting.format_items_rich_text(visible_items)
                if has_more and not self._expanded:
                    text = f'{text} <span style="color:#98A7BA;">...</span>'
                self._label.setText(text)
            else:
                text = formatting.format_items(visible_items)
                if has_more and not self._expanded:
                    text = f"{text} ..."
                _set_text(self._label, text)
        more_count = len(sorted_items) - len(visible_items) if has_more and not self._expanded else 0
        self._render_chips(visible_items, more_count=more_count)

        if self._toggle_btn is not None:
            self._toggle_btn.setVisible(True)
            self._toggle_btn.setEnabled(has_more)
            self._toggle_btn.setText(
                "Show less" if self._expanded and has_more else "Show more"
            )
        self._render_signature = render_signature

    def _render_chips(
        self, items, *, more_count: int = 0, placeholder: str | None = None
    ) -> None:
        if self._chips_container is None:
            return
        layout = self._chips_container.layout()
        scrollbar = (
            self._scroll_area.verticalScrollBar()
            if self._scroll_area is not None
            else None
        )
        scroll_position = scrollbar.value() if scrollbar is not None else None
        self._chips_container.setUpdatesEnabled(False)
        try:
            _clear_layout(layout)
            if placeholder is not None:
                note = QLabel(placeholder)
                note.setObjectName("itemChipNote")
                layout.addWidget(note)
                return
            if not items:
                note = QLabel("--")
                note.setObjectName("itemChipNote")
                layout.addWidget(note)
                return
            for item_text in items:
                display_text, object_name = formatting.item_chip_display(item_text)
                chip = QLabel(display_text)
                chip.setObjectName(object_name)
                layout.addWidget(chip)
            if more_count > 0:
                more_label = QLabel(f"+{more_count} more")
                more_label.setObjectName("itemChipNote")
                layout.addWidget(more_label)
        finally:
            self._chips_container.setUpdatesEnabled(True)
            self._chips_container.updateGeometry()
            self._chips_container.update()
            if scrollbar is not None and scroll_position is not None:
                restore = lambda: scrollbar.setValue(
                    min(scroll_position, scrollbar.maximum())
                )
                restore()
                QTimer.singleShot(0, restore)

    def _set_group_title(self, total_count: int | None) -> None:
        if self._group is None or not hasattr(self._group, "setTitle"):
            return
        self._group.setTitle(
            "Items" if total_count is None else f"Items ({total_count} total)"
        )

    def _set_rarity_summary(self, items) -> None:
        if self._rarity_label is None:
            return
        text = formatting.format_items_rarity_summary_rich_text(items)
        self._rarity_label.setVisible(bool(text))
        self._rarity_label.setText(text)

    # -- commands -------------------------------------------------------------

    @property
    def sort_combo(self):
        """The sort control, for a tab that has to mirror it across two panels."""
        return self._sort_combo

    def expanded(self) -> bool:
        return bool(self._expanded)

    def toggle_expanded(self) -> None:
        if self._always_expanded:
            return
        self._expanded = not self._expanded
        self._rerender()

    def set_expanded(self, expanded: bool) -> None:
        """Expand or fold and repaint, unlike `collapse`.

        Compare Runs drives both inventories from one click, so it needs to
        *set* a state rather than flip each side's own -- two `toggle_expanded`
        calls on panels that had drifted apart would swap them, not align them.
        """
        if self._always_expanded:
            return
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._rerender()

    def collapse(self) -> None:
        """Fold the list without repainting.

        Deliberately does not re-render. It replaces a bare
        `self.<prefix>_items_expanded = False` assignment in the two tab-reset
        paths, which sit several statements above the `update()` that actually
        repaints; rendering here would add a paint those paths never did.
        """
        self._expanded = self._always_expanded

    def on_sort_changed(self) -> None:
        mode = ITEM_SORT_DEFAULT
        if self._sort_combo is not None and hasattr(self._sort_combo, "currentData"):
            mode = self._sort_combo.currentData() or ITEM_SORT_DEFAULT
        self._sort_mode = mode
        self._rerender()

    def _rerender(self) -> None:
        self.update(self._items, items_text=self._items_text)


def items_preview(items) -> tuple[tuple[str, ...], bool]:
    """The leading items that fit the preview budget, and whether more remain.

    Module-level and pure, so it is testable without a widget. One item is
    always kept even when it alone exceeds the budget.
    """
    items = tuple(items or ())
    if len(items) <= 1:
        return items, False

    preview: list[str] = []
    current_length = 0
    for item in items:
        separator_length = 2 if preview else 0
        projected_length = current_length + separator_length + len(item)
        if preview and projected_length > PREVIEW_MAX_CHARS:
            break
        preview.append(item)
        current_length = projected_length

    if not preview:
        preview.append(items[0])
    return tuple(preview), len(preview) < len(items)


def _set_items_text(widget, items=(), *, items_text: str | None = None) -> None:
    text = items_text if items_text is not None else formatting.format_items(items)
    if widget is None:
        return
    if hasattr(widget, "setTextFormat"):
        widget.setText(formatting.format_items_rich_text(items) if items_text is None else text)
        return
    _set_text(widget, text)
