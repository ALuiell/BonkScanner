"""The tracked-item rule builder, as a widget rather than a dialog body.

A rule is a set of items and a condition, and the window that builds one used
to be a hundred lines of construction inside ``gui_overlay`` -- the component
that serves OBS, which has nothing to do with what the user is tracking.

Three of the things that came out of reading it are not about appearance.

**Two silent refusals.** ``Add Rule`` was always enabled, and the handler began
``if not item_names: return``: pressing it with nothing selected did nothing and
said nothing. A duplicate went the same way, through
``if rule["id"] not in existing_ids``. `add_button_state` below turns both into
answers -- the button is disabled with a reason under it.

**The selection fought the rarity colours.** The list was a ``QListWidget`` in
``MultiSelection`` whose item text was coloured by rarity with ``setForeground``,
while Qt painted selection as a blue row fill over it. Two colour systems on one
element, and the rarity lost. A picked item is filled with *its own* colour and
gains a tick instead.

**The order was by rarity and nothing said so.** ``available_tracked_item_names``
has sorted that way since it was written, so 87 items read as one arbitrary run;
`group_tracked_items_by_rarity` gives them captions.

Why a widget with ports
=======================

Because there are two of these windows. This one configures Session Stats and
lives in ``gui_overlay``; the Twitch bot has its own copy in
``ui/dialogs/__init__.py`` with the same list, the same interaction and its own
``twitch_``-prefixed widgets. Only the session one is wired here -- converting
the other is not this change -- but the seam is the three ports below rather
than a second copy, so it can be.
"""

from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from projections.tracked_items import (
    available_tracked_item_names,
    group_tracked_items_by_rarity,
    tracked_item_color,
    tracked_item_display_name,
)
from ui.segmented_toggle import ROLE_GO, ROLE_HALT, SegmentedToggle
from ui.shared import FlowLayout, _clear_layout

#: The two conditions, and the captions the picker shows for them. The tracker
#: defines three more modes; nothing in any dialog can produce them.
MODE_MAP_ONE = "map_1_only"
MODE_ALL_RUN = "all_run"
MODE_CAPTIONS = {MODE_MAP_ONE: "Map 1", MODE_ALL_RUN: "Whole run"}


def add_button_state(
    *,
    selected: Sequence[str],
    mode: str,
    existing_signatures: Sequence[tuple[tuple[str, ...], str]],
) -> tuple[bool, str]:
    """`(enabled, message)` for the Add button.

    Pure, and the reason this function exists at all: both of the states it
    reports used to be a click that did nothing. The message is empty when the
    button is live, because a live button explains itself.
    """
    items = tuple(str(name) for name in selected if str(name).strip())
    if not items:
        return False, "Pick one or more items on the left"
    if (items, str(mode)) in {
        (tuple(names), str(rule_mode)) for names, rule_mode in existing_signatures
    }:
        return False, "That rule is already tracked"
    return True, ""


def rule_signature(rule) -> tuple[tuple[str, ...], str]:
    """A rule's identity for the duplicate check: its items and its condition."""
    return (
        tuple(str(name) for name in (rule.get("item_names") or ())),
        str(rule.get("mode") or MODE_ALL_RUN),
    )


class TrackedItemPicker(QWidget):
    """Pick items, choose a condition, add the rule; and list what exists."""

    #: Emitted with the new rule list whenever the user changes it. The owner
    #: persists it -- this widget never writes config.
    rules_changed = Signal(list)

    def __init__(
        self,
        *,
        rules: Callable[[], list],
        make_rule: Callable[[tuple, str], dict],
        item_names: Callable[[], Sequence[str]] = available_tracked_item_names,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("trackedPicker")
        self._rules_port = rules
        self._make_rule = make_rule
        self._item_names = tuple(item_names())
        self._selected: list[str] = []
        self._picks: dict[str, QPushButton] = {}
        self._search = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        hint = QLabel(
            "Counts item pickups in Session Stats. "
            "<b>Map 1</b> counts only what was found on the first map."
        )
        hint.setObjectName("dialogHint")
        hint.setTextFormat(Qt.RichText)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(12)
        columns.addWidget(self._build_picker(), 115)
        columns.addWidget(self._build_side(), 100)
        layout.addLayout(columns, 1)

        self._refresh_picks()
        self._refresh_preview()
        self.refresh_rules()

    # -- construction ---------------------------------------------------------

    def _build_picker(self) -> QFrame:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(_eyebrow("Items"))
        head.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setObjectName("pickerCount")
        head.addWidget(self._count_label)
        layout.addLayout(head)

        self._search_entry = QLineEdit()
        self._search_entry.setObjectName("logSearch")
        self._search_entry.setPlaceholderText("Search…")
        self._search_entry.setClearButtonEnabled(True)
        self._search_entry.textChanged.connect(self._on_search)
        layout.addWidget(self._search_entry)

        scroll = QScrollArea()
        scroll.setObjectName("pickerScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("cardContent")
        self._groups_layout = QVBoxLayout(body)
        self._groups_layout.setContentsMargins(0, 0, 0, 0)
        self._groups_layout.setSpacing(4)
        scroll.setWidget(body)
        # Grows with the window. The list it replaces was pinned at 220px in a
        # dialog the user can resize, so the extra height went to empty space.
        layout.addWidget(scroll, 1)
        self._empty_search = QLabel("Nothing matches that search")
        self._empty_search.setObjectName("tableEmpty")
        self._empty_search.setVisible(False)
        layout.addWidget(self._empty_search)
        return card

    def _build_side(self) -> QWidget:
        side = QWidget()
        side.setObjectName("cardContent")
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        builder = _card()
        builder_layout = QVBoxLayout(builder)
        builder_layout.setContentsMargins(12, 12, 12, 12)
        builder_layout.setSpacing(10)
        builder_layout.addWidget(_eyebrow("New rule"))

        self._preview = QWidget()
        self._preview.setObjectName("rulePreview")
        self._preview_layout = FlowLayout(self._preview, margin=9, spacing=5)
        builder_layout.addWidget(self._preview)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        self._mode_toggle = SegmentedToggle(
            (
                (MODE_MAP_ONE, MODE_CAPTIONS[MODE_MAP_ONE], ROLE_GO),
                (MODE_ALL_RUN, MODE_CAPTIONS[MODE_ALL_RUN], ROLE_HALT),
            )
        )
        # Both segments are real choices here, not an action and its undo, so
        # pressing either one selects it rather than firing a transition.
        self._mode = MODE_MAP_ONE
        self._mode_toggle.set_active(MODE_MAP_ONE)
        self._mode_toggle.activated.connect(self._on_mode)
        actions.addWidget(self._mode_toggle)
        actions.addStretch(1)
        self._add_btn = QPushButton("Add")
        self._add_btn.setObjectName("primary")
        self._add_btn.clicked.connect(self._on_add)
        actions.addWidget(self._add_btn)
        builder_layout.addLayout(actions)

        self._add_note = QLabel("")
        self._add_note.setObjectName("addNote")
        self._add_note.setWordWrap(True)
        builder_layout.addWidget(self._add_note)
        layout.addWidget(builder)

        rules_card = _card()
        rules_layout = QVBoxLayout(rules_card)
        rules_layout.setContentsMargins(12, 12, 12, 12)
        rules_layout.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(_eyebrow("Tracked"))
        head.addStretch(1)
        self._rules_count = QLabel("")
        self._rules_count.setObjectName("pickerCount")
        head.addWidget(self._rules_count)
        rules_layout.addLayout(head)
        rules_layout.addSpacing(4)
        self._rules_layout = QVBoxLayout()
        self._rules_layout.setContentsMargins(0, 0, 0, 0)
        self._rules_layout.setSpacing(0)
        rules_layout.addLayout(self._rules_layout)
        self._rules_empty = QLabel("Nothing tracked yet")
        self._rules_empty.setObjectName("tableEmpty")
        rules_layout.addWidget(self._rules_empty)
        rules_layout.addStretch(1)
        layout.addWidget(rules_card, 1)
        return side

    # -- the item grid --------------------------------------------------------

    def _refresh_picks(self) -> None:
        _clear_layout(self._groups_layout)
        self._picks = {}
        query = self._search.strip().casefold()
        visible = [
            name
            for name in self._item_names
            if not query
            or query in tracked_item_display_name(name).casefold()
            or query in str(name).casefold()
        ]
        self._empty_search.setVisible(not visible)
        for caption, names in group_tracked_items_by_rarity(visible):
            header = QLabel(f"{caption} · {len(names)}")
            header.setObjectName("pickerGroup")
            self._groups_layout.addWidget(header)
            row = QWidget()
            row.setObjectName("cardContent")
            FlowLayout(row, margin=0, spacing=5)
            for name in names:
                row.layout().addWidget(self._build_pick(name))
            self._groups_layout.addWidget(row)
        self._refresh_count()

    def _build_pick(self, item_name: str) -> QPushButton:
        colour = tracked_item_color(item_name)
        button = QPushButton(tracked_item_display_name(item_name))
        button.setObjectName("pickChip")
        button.setCheckable(True)
        button.setChecked(item_name in self._selected)
        button.setCursor(Qt.PointingHandCursor)
        # The chip's own rarity colour, for both states: picked fills with it,
        # unpicked outlines with it. The list this replaces let Qt paint the
        # selection blue over the rarity, which is what lost it.
        button.setStyleSheet(_pick_stylesheet(colour))
        button.clicked.connect(lambda _checked=False, n=item_name: self._on_pick(n))
        self._picks[item_name] = button
        return button

    def _refresh_count(self) -> None:
        self._count_label.setText(
            f"{len(self._selected)} selected of {len(self._item_names)}"
        )

    # -- commands -------------------------------------------------------------

    def _on_search(self, text) -> None:
        self._search = str(text)
        self._refresh_picks()

    def _on_pick(self, item_name: str) -> None:
        if item_name in self._selected:
            self._selected.remove(item_name)
        else:
            self._selected.append(item_name)
        button = self._picks.get(item_name)
        if button is not None:
            button.setChecked(item_name in self._selected)
        self._refresh_count()
        self._refresh_preview()

    def _on_mode(self, key: str) -> None:
        self._mode = key
        self._mode_toggle.set_active(key)
        self._refresh_preview()

    def _on_add(self) -> None:
        enabled, _message = add_button_state(
            selected=self._selected,
            mode=self._mode,
            existing_signatures=[rule_signature(rule) for rule in self._rules_port()],
        )
        if not enabled:
            return
        rules = [dict(rule) for rule in self._rules_port()]
        rules.append(self._make_rule(tuple(self._selected), self._mode))
        self._selected = []
        self.rules_changed.emit(rules)
        self._refresh_picks()
        self._refresh_preview()
        self.refresh_rules()

    def remove_rule(self, rule_id: str) -> None:
        rules = [
            dict(rule)
            for rule in self._rules_port()
            if str(rule.get("id") or "") != str(rule_id)
        ]
        self.rules_changed.emit(rules)
        self.refresh_rules()
        self._refresh_preview()

    def clear_rules(self) -> None:
        self.rules_changed.emit([])
        self.refresh_rules()
        self._refresh_preview()

    # -- rendering ------------------------------------------------------------

    def _refresh_preview(self) -> None:
        _clear_layout(self._preview_layout)
        if not self._selected:
            note = QLabel("Pick one or more items on the left")
            note.setObjectName("previewEmpty")
            self._preview_layout.addWidget(note)
        else:
            for index, item_name in enumerate(self._selected):
                if index:
                    plus = QLabel("+")
                    plus.setObjectName("chipPlus")
                    self._preview_layout.addWidget(plus)
                self._preview_layout.addWidget(_item_chip(item_name))
        enabled, message = add_button_state(
            selected=self._selected,
            mode=self._mode,
            existing_signatures=[rule_signature(rule) for rule in self._rules_port()],
        )
        self._add_btn.setEnabled(enabled)
        self._add_note.setText(message)
        self._add_note.setVisible(bool(message))

    def refresh_rules(self) -> None:
        _clear_layout(self._rules_layout)
        rules = list(self._rules_port() or ())
        self._rules_empty.setVisible(not rules)
        self._rules_count.setText(str(len(rules)) if rules else "")
        for index, rule in enumerate(rules):
            self._rules_layout.addWidget(
                self._build_rule_row(rule, last=index == len(rules) - 1)
            )

    def _build_rule_row(self, rule, *, last: bool) -> QWidget:
        row = QWidget()
        row.setObjectName("trackedRowLast" if last else "trackedRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(8)

        items = QWidget()
        items.setObjectName("cardContent")
        items_layout = FlowLayout(items, margin=0, spacing=5)
        item_names = tuple(rule.get("item_names") or ())
        for index, item_name in enumerate(item_names):
            if index:
                plus = QLabel("+")
                plus.setObjectName("chipPlus")
                items_layout.addWidget(plus)
            items_layout.addWidget(_item_chip(item_name))
        layout.addWidget(items, 1)

        mode = str(rule.get("mode") or MODE_ALL_RUN)
        badge = QLabel(MODE_CAPTIONS.get(mode, MODE_CAPTIONS[MODE_ALL_RUN]))
        badge.setObjectName("condBadge" if mode == MODE_MAP_ONE else "condBadgeMuted")
        layout.addWidget(badge)

        remove = QPushButton("✕")
        remove.setObjectName("chipRemove")
        remove.setFixedSize(20, 20)
        remove.setCursor(Qt.PointingHandCursor)
        remove.setToolTip("Remove this rule")
        remove.clicked.connect(
            lambda _checked=False, rule_id=str(rule.get("id") or ""): self.remove_rule(rule_id)
        )
        layout.addWidget(remove)
        return row

    # -- inspection, for tests ------------------------------------------------

    @property
    def selected_items(self) -> tuple[str, ...]:
        return tuple(self._selected)

    @property
    def mode(self) -> str:
        return self._mode

    def pick(self, item_name: str) -> None:
        """Select or deselect `item_name`, as a click would."""
        self._on_pick(item_name)


# -- small builders -----------------------------------------------------------


def _card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    return card


def _eyebrow(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("kpiLabel")
    return label


def _item_chip(item_name: str) -> QLabel:
    chip = QLabel(tracked_item_display_name(item_name))
    chip.setObjectName("pickedChip")
    chip.setStyleSheet(_chip_stylesheet(tracked_item_color(item_name)))
    return chip


def _rgba(colour: str, alpha: float) -> str:
    """`colour` at `alpha`, as `rgba()` rather than an eight-digit hex.

    Qt reads `#RRGGBBAA` as **`#AARRGGBB`** -- the leading pair is alpha, not
    red. So `#FACC15` + `44` came out as `rgb(204, 21, 68)`, and every rarity in
    the picker rendered as some shade of crimson: legendary yellow, uncommon
    blue and common green all shifted by one byte. `rgba()` has one reading.
    """
    tint = QColor(str(colour))
    if not tint.isValid():
        tint = QColor("#E5E7EB")
    return f"rgba({tint.red()}, {tint.green()}, {tint.blue()}, {alpha:.2f})"


def _pick_stylesheet(colour: str) -> str:
    return (
        "QPushButton#pickChip {"
        f"  color: {colour};"
        f"  border: 1px solid {_rgba(colour, 0.27)};"
        "   background: transparent;"
        "   border-radius: 7px; padding: 3px 9px;"
        "   font-size: 11.5px; font-weight: 600;"
        "}"
        f"QPushButton#pickChip:hover {{ background-color: {_rgba(colour, 0.09)}; }}"
        "QPushButton#pickChip:checked {"
        f"  background-color: {_rgba(colour, 0.18)};"
        f"  border-color: {colour};"
        "}"
    )


def _chip_stylesheet(colour: str) -> str:
    return (
        "QLabel#pickedChip {"
        f"  color: {colour};"
        f"  background-color: {_rgba(colour, 0.18)};"
        f"  border: 1px solid {_rgba(colour, 0.40)};"
        "   border-radius: 7px; padding: 3px 8px;"
        "   font-size: 11.5px; font-weight: 600;"
        "}"
    )
