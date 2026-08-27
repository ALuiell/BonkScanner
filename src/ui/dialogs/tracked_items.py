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

Because there were three of these screens: this one for Session Stats, a copy
in the OBS widget dialog and another in the Twitch command dialog, each with the
same list, the same interaction and its own widget prefix. ``TrackedItemsDialog``
at the bottom of this file is what replaced the other two -- one window, three
targets behind a segmented control -- and the ports are what let one picker
serve all three without knowing which config it is editing.
"""

from __future__ import annotations

from html import escape
from typing import Callable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from projections.tracked_items import (
    available_tracked_item_names,
    group_tracked_items_by_rarity,
    tracked_item_color,
    tracked_item_display_name,
)
from ui.dialogs.shell import (
    DIALOG_TALL,
    DIALOG_WIDE,
    dialog_body,
    dialog_danger_card,
    dialog_footer,
)
from ui.segmented_toggle import ROLE_GO, SegmentedToggle
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

        # Names its target, so it has to be settable: this one picker serves
        # three lists, and a line reading "in Session Stats" while the OBS
        # segment is lit is worse than no line -- it is the screen telling you
        # you are editing something you are not.
        self._hint = QLabel("")
        self._hint.setObjectName("dialogHint")
        self._hint.setTextFormat(Qt.RichText)
        self._hint.setWordWrap(True)
        self.set_hint("Session Stats")
        layout.addWidget(self._hint)

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
        # Both segments are choices, not an action and its undo -- so the
        # inactive one stays clickable. On the default it is disabled, which
        # made "Whole run" unselectable and that rule impossible to create.
        self._mode_toggle = SegmentedToggle(
            (
                (MODE_MAP_ONE, MODE_CAPTIONS[MODE_MAP_ONE], ROLE_GO),
                (MODE_ALL_RUN, MODE_CAPTIONS[MODE_ALL_RUN], ROLE_GO),
            ),
            disable_inactive=False,
        )
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

    def set_hint(self, target_caption: str) -> None:
        self._hint.setText(
            f"Counts item pickups for <b>{target_caption}</b>. "
            "<b>Map 1</b> counts only what was found on the first map."
        )

    def reset(self) -> None:
        """Drop the selection and re-read the rules.

        Called when the window switches to another target. Keeping the
        selection across a switch would offer to add the items you picked for
        one list to a different one, on a button whose duplicate check has just
        been re-evaluated against rules you were not looking at.
        """
        self._selected = []
        self._refresh_picks()
        self._refresh_preview()
        self.refresh_rules()


class TrackedItemsDialog(QDialog):
    """One window for all three tracked-item lists.

    The three used to be three screens in three places: a section in the OBS
    widget dialog, a section in the Twitch command dialog, and this picker in a
    window of its own. They were copies -- same list, same interaction, same
    silent refusals -- and being apart hid what they actually are: Session Stats
    keeps a list, and the other two each either keep their own or mirror it.

    That is what the two controls at the top say out loud. The mirroring one
    used to be a checkbox that greyed out the editor beside it, which reads as a
    broken screen rather than an answered question; here the editor is replaced
    by the list being mirrored, with a way through to edit it.

    Every write goes through `TrackedItemSettings`, which is what makes the
    third copy safe to delete: the two dialogs it replaces disagreed about when
    a change reaches the tracker, and one of them never got there at all.
    """

    def __init__(self, settings, *, target_key: str = "session", parent=None) -> None:
        super().__init__(parent)
        from app.tracked_item_settings import (
            SOURCE_OWN,
            SOURCE_SESSION,
            TARGETS,
            TARGETS_BY_KEY,
        )

        self._settings = settings
        self._SOURCE_OWN = SOURCE_OWN
        self._SOURCE_SESSION = SOURCE_SESSION
        self._targets = TARGETS
        self._target = TARGETS_BY_KEY.get(target_key, TARGETS[0])

        self.setWindowTitle("Tracked Items")

        layout = dialog_body(
            self,
            title="Tracked Items",
            subtitle=(
                "Session Stats keeps the list; the OBS overlay and !session "
                "each keep their own or mirror it."
            ),
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )

        # Captions carry no counts, deliberately: `SegmentedToggle` is built on
        # its captions never changing -- that is what keeps the control one
        # width in every state. The counts go on the summary line below it.
        self._target_toggle = SegmentedToggle(
            tuple((target.key, target.caption, ROLE_GO) for target in self._targets),
            disable_inactive=False,
        )
        self._target_toggle.activated.connect(self._on_target)
        target_row = QHBoxLayout()
        target_row.setContentsMargins(0, 0, 0, 0)
        target_row.addWidget(self._target_toggle)
        target_row.addStretch(1)
        layout.addLayout(target_row)

        self._source_toggle = SegmentedToggle(
            (
                (SOURCE_OWN, "Own list", ROLE_GO),
                (SOURCE_SESSION, "Same as Session Stats", ROLE_GO),
            ),
            disable_inactive=False,
        )
        self._source_toggle.activated.connect(self._on_source)
        self._source_row = QWidget()
        source_layout = QHBoxLayout(self._source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(10)
        source_layout.addWidget(self._source_toggle)
        self._summary = QLabel("")
        self._summary.setObjectName("dialogHint")
        source_layout.addWidget(self._summary, 1)
        layout.addWidget(self._source_row)

        self._status_card = dialog_danger_card("")
        self._status_label = self._status_card.findChild(QLabel, "dialogCardText")
        self._status_card.hide()
        layout.addWidget(self._status_card)

        self._picker = TrackedItemPicker(
            rules=lambda: self._settings.rules(self._target),
            make_rule=lambda names, mode: self._settings.make_rule(
                self._target, names, mode
            ),
        )
        self._picker.rules_changed.connect(self._on_rules_changed)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._picker)
        self._stack.addWidget(self._build_mirror_page())
        layout.addWidget(self._stack, 1)

        # Behind a confirmation, and the shared footer is what keeps it away
        # from Close. The two dialogs this replaces both wiped every rule on one
        # click of a button sitting next to the dismiss button.
        self._clear_btn = QPushButton("Remove all")
        self._clear_btn.clicked.connect(lambda _checked=False: self._confirm_clear())
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        dialog_footer(self, secondary=close_btn, destructive=self._clear_btn)

        self._target_toggle.set_active(self._target.key)
        self._refresh()

    def _build_mirror_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("cardContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = _card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(10)
        card_layout.addWidget(_eyebrow("Mirrored from Session Stats"))

        self._mirror_note = QLabel("")
        self._mirror_note.setObjectName("dialogHint")
        self._mirror_note.setWordWrap(True)
        card_layout.addWidget(self._mirror_note)

        self._mirror_rules = QVBoxLayout()
        self._mirror_rules.setContentsMargins(0, 0, 0, 0)
        self._mirror_rules.setSpacing(0)
        card_layout.addLayout(self._mirror_rules)

        self._mirror_empty = QLabel("Session Stats tracks nothing yet")
        self._mirror_empty.setObjectName("tableEmpty")
        card_layout.addWidget(self._mirror_empty)

        edit = QPushButton("Edit the Session Stats list")
        # A way through rather than a dead end: the greyed-out editor this
        # replaces left the reader with nowhere to go.
        edit.clicked.connect(lambda _checked=False: self._on_target("session"))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit)
        row.addStretch(1)
        card_layout.addLayout(row)

        layout.addWidget(card)
        layout.addStretch(1)
        return page

    # -- commands -------------------------------------------------------------

    def _on_target(self, key: str) -> None:
        from app.tracked_item_settings import TARGETS_BY_KEY

        self._clear_status()
        self._target = TARGETS_BY_KEY.get(key, self._target)
        self._target_toggle.set_active(self._target.key)
        self._picker.reset()
        self._refresh()

    def _on_source(self, source: str) -> None:
        self._apply_settings_change(
            lambda: self._settings.set_source(self._target, source)
        )

    def _on_rules_changed(self, rules) -> None:
        self._apply_settings_change(
            lambda: self._settings.set_rules(self._target, rules)
        )

    def _apply_settings_change(self, change: Callable[[], None]) -> None:
        from app.tracked_item_settings import TrackedItemPublishError

        title = ""
        message = ""
        try:
            change()
        except TrackedItemPublishError as exc:
            title = "Saved with warnings"
            message = str(exc) or "Live views could not all be refreshed."
        except Exception as exc:
            title = "Changes were not saved"
            message = str(exc) or type(exc).__name__

        try:
            self._refresh()
        except Exception as exc:
            if not message:
                title = "Tracked Items could not refresh"
                message = str(exc) or type(exc).__name__

        if message:
            self._show_status(title, message)
        else:
            self._clear_status()

    def _show_status(self, title: str, message: str) -> None:
        safe_title = escape(str(title))
        safe_message = escape(str(message)).replace("\n", "<br>")
        self._status_label.setText(f"<b>{safe_title}</b><br>{safe_message}")
        self._status_card.show()

    def _clear_status(self) -> None:
        self._status_label.clear()
        self._status_card.hide()

    def _confirm_clear(self) -> None:
        confirmed = QMessageBox.question(
            self,
            "Remove all tracked items?",
            f"Every rule in the {self._target.caption} list will be removed. "
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
            return
        try:
            self._picker.clear_rules()
        except RuntimeError:
            # The application can close while QMessageBox runs its nested loop.
            # In that case the parent dialog and picker are already gone.
            pass

    # -- rendering ------------------------------------------------------------

    def _refresh(self) -> None:
        source = self._settings.source(self._target)
        mirroring = source == self._SOURCE_SESSION

        self._source_row.setVisible(self._target.can_mirror)
        if self._target.can_mirror:
            self._source_toggle.set_active(source)

        self._stack.setCurrentIndex(1 if mirroring else 0)
        self._clear_btn.setEnabled(not mirroring)
        self._picker.set_hint(self._target.caption)

        own = len(self._settings.rules(self._target))
        session = len(self._settings.rules(self._targets[0]))
        if mirroring:
            self._summary.setText(
                f"{self._target.caption} shows the Session Stats list "
                f"({_rules(session)}). Its own {_rules(own)} stay saved."
            )
            self._mirror_note.setText(
                f"{self._target.caption} counts these. Switch to "
                f"<b>Own list</b> to give it a list of its own."
            )
        else:
            self._summary.setText(f"{self._target.caption} keeps {_rules(own)}.")

        self._picker.refresh_rules()
        self._refresh_mirror_rules()

    def _refresh_mirror_rules(self) -> None:
        _clear_layout(self._mirror_rules)
        rules = self._settings.rules(self._targets[0])
        self._mirror_empty.setVisible(not rules)
        for index, rule in enumerate(rules):
            self._mirror_rules.addWidget(
                _mirror_row(rule, last=index == len(rules) - 1)
            )

    # -- inspection, for tests ------------------------------------------------

    @property
    def target_key(self) -> str:
        return self._target.key

    @property
    def picker(self) -> TrackedItemPicker:
        return self._picker

    def is_mirroring(self) -> bool:
        return self._stack.currentIndex() == 1


def _release_dialog(dialog) -> None:
    if dialog is None:
        return
    delete_later = getattr(dialog, "deleteLater", None)
    if not callable(delete_later):
        return
    try:
        delete_later()
    except RuntimeError:
        pass


def show_tracked_items_dialog(
    settings,
    *,
    target_key: str = "session",
    parent=None,
) -> bool:
    """Run the one-shot editor without retaining a closed child on its parent."""
    dialog = None
    try:
        dialog = TrackedItemsDialog(
            settings,
            target_key=target_key,
            parent=parent,
        )
        dialog.exec()
        return True
    except Exception as exc:
        try:
            QMessageBox.warning(
                parent,
                "Tracked Items Error",
                str(exc) or "Tracked Items could not be opened.",
            )
        except Exception:
            pass
        return False
    finally:
        _release_dialog(dialog)


def _rules(count: int) -> str:
    return "1 rule" if count == 1 else f"{count} rules"


def _mirror_row(rule, *, last: bool) -> QWidget:
    """A rule as the picker draws it, minus the remove button.

    Read-only because it is not this target's rule: removing it here would edit
    the Session Stats list from a screen that says it is showing OBS.
    """
    row = QWidget()
    row.setObjectName("trackedRowLast" if last else "trackedRow")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 7, 0, 7)
    layout.setSpacing(8)

    items = QWidget()
    items.setObjectName("cardContent")
    items_layout = FlowLayout(items, margin=0, spacing=5)
    for index, item_name in enumerate(tuple(rule.get("item_names") or ())):
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
    return row


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
