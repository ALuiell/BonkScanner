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

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel

from projections import formatting
from projections.item_sort import ITEM_SORT_DEFAULT
from ui.shared import _clear_layout, _set_text

PREVIEW_MAX_CHARS = 90


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
        initial_sort_mode=ITEM_SORT_DEFAULT,
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

    def toggle_expanded(self) -> None:
        if self._always_expanded:
            return
        self._expanded = not self._expanded
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
