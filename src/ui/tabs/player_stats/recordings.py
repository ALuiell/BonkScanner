"""The Recordings tab: browsing, loading and managing saved runs.

The recordings list and chooser, loading a VOD, scrubbing its timeline, the
in-tab snapshot comparison, and rename/delete/cleanup.

**Not** ``ui/tabs/compare_runs/``. That is the separate Compare Runs tab (step 9);
the ``vod_compare_*`` feature here compares two snapshots *within one loaded
recording* and deliberately stayed with this tab when step 9 split the other one
out.

Every storage call goes through ``app/vod_library.py``. The layering table forbids
``ui/ -> infra/``, and this tab does not just read -- it renames, deletes and
reindexes -- so step 14a widened that seam rather than letting this module import
``infra.vod_storage``.

Capture is not here either: starting and stopping a recording is lifecycle, and
it lives in ``app/vod_capture.py``.

An object with explicit dependencies since step 21c, not a base class of
``MegabonkApp``. Step 19 was meant to convert it and deferred to step 21,
because the blocker was step 21's own subject: this tab's metadata refresh
wrote the *Compare Runs* tab's list signature and called its repaint, while
that tab called back into this one to start the refresh, over an index that
belonged to neither. ``app.vod_library.VodLibrary`` owns the index now; this
tab subscribes to it and no longer names the other tab at all.

Note for whoever moves this again: ``ui.tabs.player_stats.recordings`` is in
``gui.py``'s ``_PATCH_COMPAT_MODULES`` because four tests do
``patch.object(gui, "load_vod")`` and expect it to reach this module. Same reason
``infra.process`` is in that tuple.
"""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.vod_library import (
    delete_vod,
    delete_vods_below_snapshot_count,
    load_vod,
    minimum_snapshot_count,
    recording_library_open,
    recording_library_width,
    recording_sort_mode,
    rename_vod,
    set_minimum_snapshot_count,
    set_recording_library_open,
    set_recording_library_width,
    set_recording_sort_mode,
)
from core.run_summary import item_counts
from core.stat_labels import abbreviate_stat_label
from core.stats.types import PLAYER_STAT_GROUPS, PLAYER_STAT_SPEC_BY_LABEL
from projections.item_sort import ITEM_SORT_RARITY_DESC
from projections.recording_sort import normalize_recording_sort_mode, sort_recordings
from projections.timeline_axis import AXIS_TIME, build_axis_projection
from ui.dialogs import CleanupRecordingsDialog, ConfirmDeleteRecordingDialog
from ui.recording_library import RecordingLibraryRow
from ui.tabs.player_stats.metrics import (
    LIVE_STATS_VALUE_WIDTH,
    RECORDINGS_LIST_MAX_WIDTH,
    RECORDINGS_LIST_MIN_WIDTH,
    _apply_player_stat_value_baseline,
    _build_chests_stats_card,
    _build_loot_rarity_card,
)
from ui.shared import (
    FlowLayout,
    FullWidthTabWidget,
    LabeledSwitch,
    LazyPage,
    _apply_button_icon,
    _apply_summary_label_padding,
    _clear_layout,
    _clear_text_input,
    _make_scroll_section,
    _read_text,
    _set_text,
    _set_text_input,
)
from ui.styles import ITEM_SORT_LABELS, RECORDING_SORT_LABELS
from ui.throttle import UiUpdateThrottle, batched_updates
from ui.tabs.player_stats.items_section import (
    BANISHES_CHIPS_MAX_HEIGHT,
    BANISHES_SECTION_MARGINS,
    BanishesSectionView,
    CompactItemsSortComboBox,
    ItemsSectionView,
    update_banishes_section,
)
from ui.tabs.player_stats.live_stats import (
    LIVE_STATS_EXPANDED_CONFIG_KEY,
    _ResponsiveCardGrid,
)
from ui.tabs.player_stats.recording_scrubber import RecordingScrubber
from ui.tabs.player_stats.stat_cards import StatCardsView, section_visibility_over
from ui.tabs.player_stats.summary_cards import (
    set_chests_card_values,
    set_loot_rarity_card_values,
    set_stage_summary_labels,
)
from projections import formatting, scrubber as scrubber_model
from ui.timeline_controls import (
    TIMELINE_SERIES_GROUPS,
    build_timeline_cap_checkboxes,
    build_timeline_series_menu,
    checked_timeline_caps,
    save_timeline_caps,
    refresh_timeline_slot_button,
)


#: The library drawer's toggle, closed and open. Named rather than inlined so
#: the test can assert on them without carrying the glyphs in its own source:
#: `test_recordings_layout` runs its checks through `python -c`, and a Windows
#: command line is encoded in the ANSI codepage -- a `»` written there arrives
#: in the child as mojibake and the assertion fails for a reason that has
#: nothing to do with the button.
LIBRARY_TOGGLE_CLOSED_CHEVRON = "»"
LIBRARY_TOGGLE_OPEN_CHEVRON = "«"


#: Which series each of the scrubber's four slots holds. Persisted because the
#: choice is about how *this user* reads a run, not about the recording: having
#: to re-pick it every time a different recording loads would make the fourth
#: slot useless for the comparison it exists to support.
SCRUBBER_SLOTS_CONFIG_KEY = "recordings_scrubber_slots"


#: The graph menu's own grouping. It starts from the same stat set as the cards,
#: but is arranged by how the series are read together on a timeline.
# Compatibility name for tests/extensions that imported the former local list.
SCRUBBER_STAT_GROUPS = TIMELINE_SERIES_GROUPS


#: Width of the label column in Compare Details. Measured, not guessed: bold
#: `Broken` is the widest of the labels at 72px, and a four-digit rarity total
#: is the same, so both kinds of row start their items in the same place.
COMPARE_ROW_LABEL_WIDTH = 74


def _build_compare_rarity_row(badge_html: str, items_html: str) -> QWidget:
    """One row's label beside its items, as two labels.

    Two rather than one so the wrapped lines of a long run stay clear of the
    label column: a single label would wrap the second line back under the dot.
    """
    row = QWidget()
    row.setObjectName("CompareRarityRow")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    badge = QLabel(badge_html)
    badge.setObjectName("CompareRarityBadge")
    badge.setTextFormat(Qt.RichText)
    badge.setFixedWidth(COMPARE_ROW_LABEL_WIDTH)
    layout.addWidget(badge, 0, Qt.AlignTop)
    items = QLabel(items_html)
    items.setObjectName("CompareRarityItems")
    items.setTextFormat(Qt.RichText)
    items.setWordWrap(True)
    layout.addWidget(items, 1, Qt.AlignTop)
    _apply_summary_label_padding(badge, items)
    return row


def _load_scrubber_slots() -> tuple[tuple[str, ...], ...]:
    """The configured slots, falling back to the defaults slot by slot.

    Validated per entry rather than wholesale: a config written by an older
    build can name a stat that no longer exists, and dropping the *whole*
    configuration for one stale name would silently reset the three slots the
    user did still want.
    """
    stored = config.user_config.get(SCRUBBER_SLOTS_CONFIG_KEY)
    if not isinstance(stored, list):
        return scrubber_model.DEFAULT_SLOTS
    known = set(scrubber_model.available_series_keys())
    slots: list[tuple[str, ...]] = []
    for index, default in enumerate(scrubber_model.DEFAULT_SLOTS):
        if index >= len(stored):
            slots.append(default)
            continue
        entry = stored[index]
        if not isinstance(entry, list):
            slots.append(default)
            continue
        # An empty list is a slot the user cleared, and is honoured. Only a
        # *malformed* entry falls back to the default -- otherwise clearing a
        # slot would silently refill itself on the next launch.
        slots.append(tuple(str(key) for key in entry if str(key) in known))
    return tuple(slots)


def filter_recordings(vods, query: str):
    """The recordings a search box shows, by case-insensitive name match.

    A free function so the decision can be tested without Qt. Building the
    whole tab inside the suite's process is what `test_recordings_layout.py`
    already runs in a subprocess for -- the widget tree outlives the test and
    takes the interpreter down later -- so anything that can be decided without
    widgets is decided here.
    """
    query = str(query or "").strip().casefold()
    if not query:
        return list(vods)
    return [vod for vod in vods if query in str(vod.name).casefold()]


def short_recording_count(vods, threshold: int) -> int:
    """How many recordings the auto-filter threshold would remove."""
    threshold = max(0, int(threshold))
    return sum(1 for vod in vods if vod.snapshot_count < threshold)


def library_size_bytes(vods) -> int:
    """Total size on disk, skipping anything that vanished under us."""
    total = 0
    for vod in vods:
        try:
            total += vod.path.stat().st_size
        except OSError:
            # Deleted between the index refresh and this walk. Not an error
            # worth surfacing; it simply does not count towards the size.
            continue
    return total


def _format_bytes(total: int) -> str:
    """Library size, in the largest unit that keeps it under four digits."""
    size = float(max(0, int(total)))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def _save_scrubber_slots(slots) -> None:
    config.user_config[SCRUBBER_SLOTS_CONFIG_KEY] = [list(slot) for slot in slots]
    config.save_config(config.user_config)


class _NameEdit(QLineEdit):
    """The rename field, which exists only while a rename is in progress.

    A subclass for one reason: Escape has to abandon the edit. `RecordingsTab`
    is a plain object rather than a `QObject`, so it cannot host an event
    filter, and a `QShortcut` on Escape would fire tab-wide -- including while
    the scrubber wants Escape for clearing the compare pin.
    """

    cancelled = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- Qt override
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class _StageChapterCard(QFrame):
    """One stage, as a card and a jump target.

    A `QFrame` with a click rather than a `QPushButton`: the card carries four
    laid-out labels including rich text, and a button would fight its own text
    rendering for all of them.

    The three visual states are properties rather than stylesheets set here, so
    the whole look stays in the QSS with the rest of the redesign:
    `hasData=false` for a stage this run never reached, `current=true` for the
    one the playhead is inside.
    """

    clicked = Signal(int, bool)

    def __init__(self, stage_number: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stage_number = int(stage_number)
        self.setObjectName("StageChapterCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(
            "Click moves point A to this stage\n"
            "Shift+click sets point B for the full stage range"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 10)
        layout.setSpacing(3)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(7)
        title = QLabel(f"Stage {self.stage_number}")
        title.setObjectName("StageChapterTitle")
        time_label = QLabel("--")
        time_label.setObjectName("StageChapterTime")
        title_row.addWidget(title)
        title_row.addWidget(time_label)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        kills_label = QLabel("--")
        kills_label.setObjectName("StageChapterKills")
        layout.addWidget(kills_label)

        items_label = QLabel("--")
        items_label.setObjectName("StageChapterItems")
        items_label.setTextFormat(Qt.RichText)
        layout.addWidget(items_label)

        # Keyed exactly as the table's rows were, so `set_stage_summary_labels`
        # writes these without knowing they now live in a card. `"stage"` still
        # receives the bare number the table showed in its first column; the
        # card puts it in the title instead, so it is written to a label the
        # card owns but does not display.
        self.value_labels = {
            "stage": QLabel(str(self.stage_number)),
            "time": time_label,
            "kills": kills_label,
            "items": items_label,
        }
        self.value_labels["stage"].setVisible(False)
        self.set_state(has_data=False, is_current=False, is_anchor=False)

    def set_state(
        self, *, has_data: bool, is_current: bool, is_anchor: bool
    ) -> None:
        self.setProperty("hasData", bool(has_data))
        self.setProperty("current", bool(is_current))
        self.setProperty("rangeAnchor", bool(is_anchor))
        self.setEnabled(bool(has_data))
        # Qt does not restyle on a property change on its own. The dimmed
        # `hasData=false` selector targets the labels through this frame, so
        # repolishing only the frame leaves every child stuck in its initial
        # muted colour even after real stage data arrives.
        self.style().unpolish(self)
        self.style().polish(self)
        for label in self.findChildren(QLabel):
            label.style().unpolish(label)
            label.style().polish(label)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit(
                self.stage_number,
                bool(event.modifiers() & Qt.ShiftModifier),
            )
            return
        super().mousePressEvent(event)


class RecordingsTab:
    """The Recordings tab: an object with explicit dependencies.

    Constructed once by `gui_layout._build_recordings_view`, which is its
    composition root and the only place its six collaborators are named.

    Step 19 was meant to convert this and deliberately deferred it to step 21,
    because the deferral's reason *was* step 21's subject: this tab's metadata
    refresh wrote the Compare Runs tab's list signature and called its repaint,
    and the shared index belonged to neither tab. That index has an owner now
    (`app.vod_library.VodLibrary`, step 21b), so this tab can take an honest
    constructor -- it holds no reference to the Compare Runs tab and never did
    anything to it that the library's `subscribe` does not now do for it.

    `window`, `vod_recorder` and `is_active` are **suppliers**, for the reason
    `LiveStatsTab` records: the app layer rebinds what they resolve to.
    `player_stats_vod_recorder` is reassigned per recording, and `is_active`
    asks a tab-bar question whose answer changes on every switch. A component
    holding the value would go stale exactly where the mixin reading `self` did
    not.

    `is_active` is a supplier and not a method here on purpose: the tab-switch
    router (`gui_layout.on_right_tab_changed`, `_refresh_right_tab_after_switch`,
    `_refresh_vods_list_if_visible`) is **step 26's** and must not be assigned
    to a tab by this step. The tab asks the question; it does not own the router
    that answers it.
    """

    def __init__(
        self,
        *,
        tabview,
        vod_library,
        window: Callable[[], object],
        vod_recorder: Callable[[], object],
        is_active: Callable[[], bool],
        log: Callable[..., None],
        schedule: Callable[[Callable[[], None]], None] | None = None,
        snapshot_throttle: UiUpdateThrottle | None = None,
    ) -> None:
        self._tabview = tabview
        self._library = vod_library
        self._window = window
        self._vod_recorder = vod_recorder
        self._is_active = is_active
        self._log = log
        self._schedule = schedule

        # Selection state. Nine names on `MegabonkApp` until step 21c; measured
        # to have zero production readers outside this module, which is what
        # let them move wholesale rather than stay as app surface.
        self._loaded_vod = None
        self._snapshot_index = None
        # What the slider has asked for, which runs ahead of `_snapshot_index`
        # while a throttled frame is queued. See `on_scrub_index_changed`.
        self._requested_snapshot_index = None
        # Slider-drag rate limiting; injectable so a test can drive the
        # coalescing with a fake clock instead of a real event loop.
        self._snapshot_throttle = snapshot_throttle or UiUpdateThrottle()
        self._compare_start_index = None
        self._stage_range_anchor_index = None
        self._stage_range_anchor_number = None
        self._chooser_expanded = False
        self._guided_selection_active = False
        self._body_splitter = None
        # The drawer's width, remembered across opens and across launches. The
        # saved value is clamped on the way in: config.json is hand-editable,
        # and a 4000px library would leave no detail column to read.
        self._library_width = min(
            RECORDINGS_LIST_MAX_WIDTH + 40,
            max(RECORDINGS_LIST_MIN_WIDTH, recording_library_width() or RECORDINGS_LIST_MAX_WIDTH),
        )
        # Half a second, not the render throttle's 33ms: this one guards a
        # config.json write, and a drag that saves 30 times a second is a disk
        # write per frame for a value only the next launch reads.
        self._library_width_throttle = UiUpdateThrottle(500)
        self._list_signature = None
        self._load_generation = 0
        self._load_in_progress = False

        self._rows = {}
        self._compact_rows = {}
        self._stage_summary_labels = []
        self._stage_cards = []

        # Every widget `build()` creates, named here as `None`. They were
        # `getattr(self, "vods_...", None)` reads on the mixin -- a default that
        # existed only because `object.__new__` doubles skipped `__init__` and
        # so quietly tolerated a half-built tab. Declaring them is what lets the
        # readers below be plain attribute access: an unbuilt tab now raises at
        # the right place instead of rendering into `None`.
        self._tab = None
        self._select_btn = None
        self._status_label = None
        self._title_label = None
        self._name_entry = None
        self._rename_btn = None
        self._cleanup_btn = None
        self._delete_btn = None
        # The scrubber replaces four widgets: the `QSlider`, the
        # "Timeline: … | Selected: …" caption, and the two compare buttons.
        # The compare anchor is a pin on the track now, so "set" and "clear"
        # are places you point at rather than buttons you press.
        self._scrubber = None
        self._position_label = None
        self._compare_hint_label = None
        self._legend_label = None
        self._legend_meta_label = None
        self._slot_buttons = []
        self._slots = _load_scrubber_slots()
        self._items_section = None
        self._chests_per_minute_label = None
        self._banishes_label = None
        self._compare_details_group = None
        self._compare_clear_button = None
        self._compare_details_summary_label = None
        self._compare_details_items = None
        self._detail_tabs = None
        self._stats_expanded_toggle = None
        self._stat_cards = None
        self._chooser_group = None
        self._list_frame = None
        self._search_entry = None
        self._sort_combo = None
        self._cap_checkboxes: dict = {}
        self._library_summary_label = None
        self._min_snapshots_spin = None
        self._chests_card_values = None
        self._loot_rarity_card_values = None

    def refresh_vods_list(self):
        if self._list_frame is None:
            return

        vods = list(self._library.index)
        selected_path = self._loaded_vod.metadata.path if self._loaded_vod is not None else None
        query = _read_text(self._search_entry).strip().casefold() if self._search_entry else ""
        sort_mode = self._recordings_sort_mode()
        # The sort mode is part of the signature, not just an input to the
        # paint below. Changing the order changes neither the selection, the
        # query nor the set of recordings, so without it here the early return
        # swallows the repaint and the combo box does nothing at all -- with no
        # error to say why.
        signature = (
            str(selected_path) if selected_path is not None else "",
            query,
            sort_mode,
            tuple((str(vod.path), vod.name, vod.snapshot_count, vod.duration_seconds) for vod in vods),
        )
        self._library.ensure_refresh()
        if self._list_signature == signature:
            return

        # The footer describes the *library*, so it is written from the full
        # index and not from the filtered view: "28 recordings" must not become
        # "3 recordings" because a search box has three letters in it.
        self._refresh_library_footer(vods)

        matches = sort_recordings(filter_recordings(vods, query), sort_mode)
        longest_seconds = max((vod.duration_seconds for vod in vods), default=0)

        self._list_frame.blockSignals(True)
        self._list_frame.clear()
        if not matches:
            item = QListWidgetItem(
                "No recordings match this search" if query else "No saved recordings"
            )
            item.setFlags(Qt.NoItemFlags)
            self._list_frame.addItem(item)
            self._list_frame.blockSignals(False)
            self._list_signature = signature
            return

        selected_row = None
        for row, vod in enumerate(matches):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, str(vod.path))
            widget = RecordingLibraryRow(vod, longest_seconds=longest_seconds)
            item.setSizeHint(widget.sizeHint())
            self._list_frame.addItem(item)
            self._list_frame.setItemWidget(item, widget)
            if selected_path == vod.path:
                selected_row = row
        if selected_row is not None:
            self._list_frame.setCurrentRow(selected_row)
        self._list_frame.blockSignals(False)
        self._list_signature = signature

    def _refresh_library_footer(self, vods) -> None:
        """The library's own totals, and how many the threshold would remove."""
        _set_text(
            self._library_summary_label,
            f"{len(vods)} recordings  ·  {_format_bytes(library_size_bytes(vods))}",
        )
        if self._cleanup_btn is not None:
            short = short_recording_count(vods, self._minimum_snapshot_count())
            self._cleanup_btn.setText(f"Delete short  ·  {short}")
            self._cleanup_btn.setEnabled(short > 0)
        self._refresh_recordings_chooser()

    def _minimum_snapshot_count(self) -> int:
        """The threshold as the *spinner* has it, falling back to the store."""
        if self._min_snapshots_spin is not None:
            return max(0, int(self._min_snapshots_spin.value()))
        return minimum_snapshot_count()

    def on_minimum_snapshot_count_changed(self, value: int) -> None:
        """Persist the auto-filter threshold and restate what it would remove.

        One number drives both halves: the recorder discards below it when a
        run ends, and "Delete short" applies it to what is already on disk.
        """
        set_minimum_snapshot_count(int(value))
        self._refresh_library_footer(list(self._library.index))

    def _recordings_sort_mode(self) -> str:
        """The combo's order, or the saved one before the combo exists."""
        combo = self._sort_combo
        if combo is None:
            return recording_sort_mode()
        return normalize_recording_sort_mode(combo.currentData())

    def on_recordings_search_changed(self, _text: str = "") -> None:
        self._list_signature = None
        self.refresh_vods_list()

    def on_recordings_sort_changed(self, _index: int = 0) -> None:
        set_recording_sort_mode(self._recordings_sort_mode())
        self._list_signature = None
        self.refresh_vods_list()
    def invalidate_vods_list(self) -> None:
        """Drop the painted-list signature. `VodLibrary`'s invalidate hook."""
        self._list_signature = None
    def on_vod_metadata_refresh_failed(self, error: BaseException) -> None:
        """`VodLibrary`'s failure hook -- the status line stays this tab's.

        The Compare Runs tab registers no failure listener, which is not an
        omission: the callback this replaced only ever wrote *this* status
        label on a failed refresh.
        """
        _set_text(self._status_label, f"Could not refresh recordings: {error}")
    def toggle_recordings_chooser(self):
        next_expanded = not bool(self._chooser_expanded)
        self.set_recordings_chooser_expanded(next_expanded, guided=False)
    def ensure_recordings_chooser_for_empty_selection(self) -> None:
        if not self._is_active():
            return
        if self._loaded_vod is not None:
            return
        if bool(self._chooser_expanded):
            return
        self.set_recordings_chooser_expanded(True, guided=True, remember=False)
    def set_recordings_chooser_expanded(
        self, expanded: bool, *, guided: bool, remember: bool = True
    ) -> None:
        """Open or close the library drawer.

        ``remember`` is what separates the user's choice from the app's own
        housekeeping, and only the first is worth persisting. Three callers
        pass ``False``: the build-time restore (it is replaying what was
        already saved), the guided open when nothing is selected, and the
        auto-close that follows a guided pick. Persisting a guided open is how
        merely *visiting* the tab with no recording loaded would teach the app
        to open the drawer on every launch from then on.
        """
        expanded = bool(expanded)
        if not expanded:
            # Read the width back *before* the drawer goes away: a hidden
            # splitter child reports 0, and 0 is what the next open would then
            # restore.
            self._remember_library_width()
        self._chooser_expanded = expanded
        self._guided_selection_active = bool(expanded and guided)
        self._refresh_recordings_chooser()
        if expanded:
            self._apply_library_width()
        if remember:
            set_recording_library_open(expanded)
    def _refresh_recordings_chooser(self) -> None:
        expanded = bool(self._chooser_expanded)
        chooser = self._chooser_group
        button = self._select_btn
        if chooser is not None:
            chooser.setVisible(expanded)
        if button is not None:
            count = len(getattr(self._library, "index", ()) or ())
            # The chevron points where the drawer will go, the way the left
            # rail's does. The word "Recordings" moved to the tooltip: it cost
            # ~80px in the row that carries the recording's own name, and the
            # count is the part that is worth space when the drawer is shut.
            chevron = (
                LIBRARY_TOGGLE_OPEN_CHEVRON if expanded else LIBRARY_TOGGLE_CLOSED_CHEVRON
            )
            button.setText(f"{chevron}  {count}")
            button.setChecked(expanded)
            button.setToolTip(
                f"Hide recordings library ({count})"
                if expanded
                else f"Recordings library ({count})"
            )

    # -- drawer width -------------------------------------------------------
    #
    # Split from the open/closed state on purpose: how wide the user dragged
    # the library is worth remembering whether or not it is open right now.

    def _library_width_bounds(self) -> tuple[int, int]:
        return RECORDINGS_LIST_MIN_WIDTH, RECORDINGS_LIST_MAX_WIDTH + 40

    def _remember_library_width(self) -> None:
        """Record the drawer's current width, if it is showing one."""
        splitter = self._body_splitter
        chooser = self._chooser_group
        if splitter is None or chooser is None or not chooser.isVisible():
            return
        sizes = splitter.sizes()
        if not sizes or sizes[0] <= 0:
            return
        low, high = self._library_width_bounds()
        self._library_width = max(low, min(high, int(sizes[0])))

    def _apply_library_width(self) -> None:
        """Give the drawer its remembered width, leaving the rest to the detail."""
        splitter = self._body_splitter
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) < 2:
            return
        low, high = self._library_width_bounds()
        width = max(low, min(high, int(self._library_width)))
        total = sum(sizes)
        if total <= width:
            # Nothing has been laid out yet (build time), so there is no total
            # to split. Qt will honour the size hints, and the first real
            # resize applies this.
            return
        splitter.setSizes([width, total - width])

    def _on_library_width_dragged(self) -> None:
        """The user moved the handle. Remember it, and persist it, coalesced.

        Persisting straight from `splitterMoved` would write config.json once
        per pixel of mouse travel.
        """
        self._remember_library_width()
        self._library_width_throttle.request(
            lambda: set_recording_library_width(int(self._library_width))
        )
    def _on_vod_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None):
        if current is None:
            return
        path_str = current.data(Qt.UserRole)
        if path_str:
            self.load_selected_vod(path_str)
    def _set_vod_loading_state(self, loading: bool) -> None:
        self._load_in_progress = bool(loading)
        has_recording = not loading and self._loaded_vod is not None
        has_snapshots = bool(has_recording and self._loaded_vod.snapshots)
        for widget, enabled in (
            (self._name_entry, has_recording),
            (self._rename_btn, has_recording),
            (self._delete_btn, has_recording),
            (self._scrubber, has_snapshots),
        ):
            if widget is not None:
                widget.setEnabled(enabled)
        if not has_recording:
            # A rename in flight when the recording underneath it changes would
            # otherwise commit the old name onto the new run.
            self._set_renaming(False)
        for button in self._slot_buttons:
            button.setEnabled(has_snapshots)
        self._refresh_vod_compare_controls()
    def load_selected_vod(self, path):
        path = Path(path)
        generation = int(self._load_generation) + 1
        self._load_generation = generation
        self._loaded_vod = None
        self._snapshot_index = None
        # A queued frame describes the recording being replaced.
        self._snapshot_throttle.cancel()
        self._requested_snapshot_index = None
        self._compare_start_index = None
        self._stage_range_anchor_index = None
        self._stage_range_anchor_number = None
        self._set_vod_loading_state(True)
        _set_text(self._status_label, "Loading recording…")

        def finish(loaded_vod, error) -> None:
            if generation != self._load_generation:
                return
            if error is not None:
                self._clear_loaded_vod_selection()
                _set_text(self._status_label, f"Could not load recording: {error}")
                self._set_vod_loading_state(False)
                return
            self._loaded_vod = loaded_vod
            self._snapshot_index = 0 if loaded_vod.snapshots else None
            self._requested_snapshot_index = self._snapshot_index
            self._compare_start_index = None
            self._stage_range_anchor_index = None
            self._stage_range_anchor_number = None
            _clear_text_input(self._name_entry)
            _set_text_input(self._name_entry, loaded_vod.metadata.name)
            self.refresh_loaded_vod_ui()
            self._set_vod_loading_state(False)
            self.refresh_vods_list()
            if bool(self._chooser_expanded) and bool(
                self._guided_selection_active
            ):
                # Closing the drawer the app opened for you is the other half
                # of that gesture, not a preference -- a library you pinned
                # open yourself never reaches here, because `guided` is only
                # set by `ensure_recordings_chooser_for_empty_selection`.
                self.set_recordings_chooser_expanded(
                    False, guided=False, remember=False
                )

        def load() -> None:
            try:
                loaded = load_vod(path)
                error = None
            except Exception as exc:
                loaded = None
                error = exc
            self._marshal(lambda: finish(loaded, error))

        # Background only when there is somewhere to marshal the result back to.
        # The mixin decided this by reading `self.after` and `self._invoker` off
        # the shared namespace on every load; it is one injected callable now,
        # and the two branches are the same two.
        if callable(self._schedule):
            threading.Thread(target=load, name="vod-loader", daemon=True).start()
        else:
            load()

    def _marshal(self, callback) -> None:
        schedule = self._schedule
        if callable(schedule):
            schedule(callback)
        else:
            callback()
    def refresh_loaded_vod_ui(self, *, update_slider: bool = True):
        if self._loaded_vod is None:
            return

        snapshot_count = len(self._loaded_vod.snapshots)
        metadata = self._loaded_vod.metadata
        duration = formatting.format_duration(metadata.duration_seconds)
        _set_text(self._title_label, metadata.name)
        _set_text(
            self._status_label,
            f"{metadata.created_label}  ·  {snapshot_count} snapshots  ·  {duration}",
        )

        if snapshot_count:
            self._scrubber.setEnabled(True)
            self._rebuild_scrubber_model()
            # The whole run, once. See `_render_loaded_vod_snapshot` for why
            # this is not a per-frame prefix any more.
            set_stage_summary_labels(
                self._stage_summary_labels,
                formatting.build_stage_summary(self._loaded_vod.snapshots),
            )
            if update_slider:
                self._scrubber.set_index(self._snapshot_index or 0)
            self.display_loaded_vod_snapshot(self._snapshot_index or 0)
        else:
            self._scrubber.setEnabled(False)
            self._scrubber.set_model(scrubber_model.ScrubberModel(count=0))
            _set_text(self._position_label, "--")
            for label in self._rows.values():
                _set_text(label, "--")
            for label in self._compact_rows.values():
                _set_text(label, "--")
            _set_text(self._legend_label, "--")
            _set_text(self._legend_meta_label, "")
            self._items_section.collapse()
            self._items_section.update((), items_text="--")
            set_chests_card_values(
                self._chests_card_values,
                None,
            )
            set_loot_rarity_card_values(self._loot_rarity_card_values, None, None)
            self._refresh_vod_compare_controls()
            self._refresh_vod_compare_details(None, None, index=None)
            update_banishes_section(
                getattr(self, "_banishes_view", None), self._banishes_label, ()
            )
            set_stage_summary_labels(self._stage_summary_labels, None)
            self._refresh_stage_cards()
            self._stat_cards.invalidate()
            self._stat_cards.display_weapons((), status_text="No weapon data in this recording")
            self._stat_cards.display_tomes((), status_text="No tome data in this recording")
            self._stat_cards.display_chaos_tome(
                None, status_text="No Chaos Tome data in this recording"
            )
            self._stat_cards.display_damage_sources(
                (), status_text="No damage source data in this recording"
            )
    def display_loaded_vod_snapshot(self, index: int):
        if self._loaded_vod is None or not self._loaded_vod.snapshots:
            return
        index = min(max(index, 0), len(self._loaded_vod.snapshots) - 1)
        self._snapshot_index = index
        self._requested_snapshot_index = index
        # Keeps the playhead honest when the index was chosen by something
        # other than a drag -- loading a recording, or `set_vod_compare_start`.
        # `set_index` is a no-op when it already agrees, so a drag does not
        # bounce back through here.
        if self._scrubber is not None:
            self._scrubber.set_index(index)
        snapshot = self._loaded_vod.snapshots[index]
        # One repaint for the whole tab rather than one per widget: this method
        # writes ~40 of them.
        with batched_updates(self._tab):
            self._render_loaded_vod_snapshot(index, snapshot)
    def _render_loaded_vod_snapshot(self, index: int, snapshot) -> None:
        # No status-line write here any more. It restated the position pill --
        # index, capture time, in-game time -- once per drag frame, on the one
        # path `on_scrub_index_changed` coalesces to keep short.
        self._refresh_scrub_readout(index)
        for spec_group in PLAYER_STAT_GROUPS:
            for spec in spec_group:
                value_label = self._rows.get(spec.label)
                if value_label is not None:
                    stat = snapshot.stats.get(spec.label)
                    _set_text(value_label, stat.display_value if stat is not None else "--")
                compact_value_label = self._compact_rows.get(spec.label)
                if compact_value_label is not None:
                    stat = snapshot.stats.get(spec.label)
                    _set_text(
                        compact_value_label,
                        stat.display_value if stat is not None else "--",
                    )
        self._items_section.update(snapshot.items)
        self._update_recorded_chest_summary(snapshot)
        self._update_recorded_loot_rarity_summary(snapshot)
        # Stage cards describe the whole recording and are written once at
        # load; only which one is *current* depends on the playhead. They used
        # to be rebuilt from `snapshots[: index + 1]` on every frame, which
        # both made them fill in gradually as you scrubbed -- a run's stage
        # totals are not a function of where you are looking -- and put a walk
        # over the whole prefix on the drag path.
        self._refresh_stage_cards()
        previous_snapshot = self._resolve_vod_compare_base_snapshot(index)
        segment_snapshots = self._vod_compare_segment_snapshots(index)
        self._refresh_vod_compare_controls()
        self._refresh_vod_compare_details(previous_snapshot, snapshot, index=index, segment_snapshots=segment_snapshots)
        update_banishes_section(
            getattr(self, "_banishes_view", None),
            self._banishes_label,
            getattr(snapshot, "banishes", ()),
        )
        self._stat_cards.display_weapons(getattr(snapshot, "weapons", ()))
        self._stat_cards.display_tomes(getattr(snapshot, "tomes", ()))
        self._stat_cards.display_chaos_tome(
            getattr(snapshot, "chaos_tome", None),
            status_text=None if getattr(snapshot, "chaos_tome", None) is not None else "No Chaos Tome data in this snapshot",
        )
        self._stat_cards.display_damage_sources(getattr(snapshot, "damage_sources", ()))
    def on_scrub_index_changed(self, value):
        """The scrubber moved the playhead. Coalesces the repaint.

        Was `on_vods_slider_changed`, and the coalescing below is unchanged:
        the scrubber emits at pointer rate exactly as the slider did, so the
        drag path still has to be a cheap caption write plus one queued frame.
        """
        if self._loaded_vod is None or not self._loaded_vod.snapshots:
            return
        index = min(max(int(round(float(value))), 0), len(self._loaded_vod.snapshots) - 1)
        # With nothing queued the rendered index *is* the truth, and comparing
        # against it is what keeps a programmatic `setValue` from looping back
        # into a redundant render. With a frame queued the two differ, and
        # comparing against the rendered index would let a drag that returns to
        # the last-painted snapshot exit here while the queued frame still
        # repaints one the user has scrubbed away from.
        current = (
            self._requested_snapshot_index
            if self._snapshot_throttle.has_pending
            else self._snapshot_index
        )
        if current == index:
            return
        self._requested_snapshot_index = index
        # Immediate and cheap, so the caption tracks the drag; the full
        # snapshot render -- stat rows, items, stage summary, four cards -- is
        # coalesced to the throttle window.
        self._refresh_scrub_readout(index)
        self._snapshot_throttle.request(
            lambda: self.display_loaded_vod_snapshot(index)
        )

    def _refresh_scrub_readout(self, index: int) -> None:
        """Position and legend, both written on every drag frame.

        Deliberately two `QLabel`s and not painting inside the scrubber: this
        runs at pointer rate, and a repaint of the whole track to change a
        number would put the curves back on the drag path that
        `on_scrub_index_changed` exists to keep clear.
        """
        _set_text(self._position_label, self._position_text(index))
        if self._legend_meta_label is None:
            # Lightweight test/adapter views own only the historical single
            # label. The real tab renders series and run metadata at opposite
            # ends of one row.
            _set_text(self._legend_label, self._legend_text(index))
        else:
            series, meta = self._legend_parts(index)
            _set_text(self._legend_label, series)
            _set_text(self._legend_meta_label, meta)
        self._refresh_compare_hint()

    def _position_text(self, index: int) -> str:
        if self._loaded_vod is None or not self._loaded_vod.snapshots:
            return "--"
        snapshots = self._loaded_vod.snapshots
        index = min(max(int(index), 0), len(snapshots) - 1)
        snapshot = snapshots[index]
        game_time = getattr(snapshot, "game_time_seconds", None)
        in_game = "--" if game_time is None else formatting.format_elapsed_time(game_time)
        return (
            f"{index + 1} / {len(snapshots)}  ·  {snapshot.time_label}"
            f"  ·  in-game {in_game}"
        )

    def _legend_parts(self, index: int) -> tuple[str, str]:
        """The series values at the playhead, plus what is not a series.

        This *is* the run-summary readout: Kills and Items are already slots,
        so giving them a second home in a KPI row would be two places to keep
        agreeing about one number.
        """
        if self._loaded_vod is None or not self._loaded_vod.snapshots:
            return "--", ""
        snapshots = self._loaded_vod.snapshots
        index = min(max(int(index), 0), len(snapshots) - 1)
        # The series half needs the scrubber's model; the tail below does not,
        # and deliberately: the tail is what the deleted "Run Summary" card
        # showed, and a run-level number must not vanish because the track has
        # not been built yet.
        model = self._scrubber.model if self._scrubber is not None else None
        series_keys = self._scrubber.series_keys if self._scrubber is not None else ()
        parts: list[str] = []
        if model is not None and model.count > 0:
            for key in series_keys:
                series = model.series(key)
                if series is None or not series.available:
                    continue
                parts.append(
                    f'<span style="color:{series.color};">&#9679;</span> '
                    f'<span style="color:#8A94A3;">{abbreviate_stat_label(series.label)}</span> '
                    f'<b style="color:#EDF1F5;">{self._series_display(key, snapshots[index])}</b>'
                )
        snapshot = snapshots[index]
        # What is not a series, in muted text. Mob Kills joins them only when
        # no slot is plotting it: the "Run Summary" card this readout replaced
        # always showed it, and clearing the Kills slot must not take a
        # run-level number off the screen with it -- but showing it twice while
        # the slot is filled is the duplication the card was deleted for.
        tail_parts = [
            formatting.format_player_level(getattr(snapshot, "player_level", None)),
            formatting.format_kps_averages(
                getattr(snapshot, "minute_avg_kps_at_capture", None),
                getattr(snapshot, "five_minute_avg_kps_at_capture", None),
            ),
            formatting.format_chests_per_minute_short(
                formatting.resolve_snapshot_chests_per_minute(snapshot)
            ),
        ]
        if scrubber_model.KILLS_SERIES not in series_keys:
            tail_parts.insert(
                0,
                formatting.format_mob_kills(
                    getattr(snapshot, "mob_kills", None),
                    getattr(snapshot, "kps_at_capture", None),
                ),
            )
        tail = f'<span style="color:#5C6675;">{" · ".join(tail_parts)}</span>'
        return "&nbsp;&nbsp;&nbsp;".join(parts), tail

    def _legend_text(self, index: int) -> str:
        """Combined fallback for views that have only one legend label."""
        series, meta = self._legend_parts(index)
        return "&nbsp;&nbsp;&nbsp;".join(part for part in (series, meta) if part)

    @staticmethod
    def _series_display(key: str, snapshot) -> str:
        """A series' value as the rest of the app already spells it.

        Stats quote their own `display_value` rather than being re-formatted
        here: the stat knows whether it is a multiplier, a percentage or a
        plain number, and a second formatter would disagree with the stat grid
        eight rows below.
        """
        if key == scrubber_model.KILLS_SERIES:
            kills = getattr(snapshot, "mob_kills", None)
            return "--" if kills is None else formatting.format_count(kills)
        if key == scrubber_model.ITEMS_SERIES:
            return formatting.format_count(
                sum(item_counts(getattr(snapshot, "items", ())).values())
            )
        stat = (snapshot.stats or {}).get(key) if isinstance(snapshot.stats, dict) else None
        return str(getattr(stat, "display_value", "--") or "--")
    def on_scrub_pin_changed(self, index) -> None:
        """The scrubber's pin moved, or was cleared.

        The two compare buttons collapsed into this: *Set Compare Start* could
        only ever anchor at the playhead, so it was a button for a position the
        user already had a pointer on.
        """
        if index is None:
            self.clear_vod_compare_start()
        else:
            self.set_vod_compare_start(index)

    def set_vod_compare_start(self, index: int | None = None):
        if self._loaded_vod is None or not self._loaded_vod.snapshots:
            return
        if index is None:
            index = self._snapshot_index
        if index is None:
            index = 0
        self._compare_start_index = min(max(int(index), 0), len(self._loaded_vod.snapshots) - 1)
        if self._scrubber is not None:
            self._scrubber.set_pin(self._compare_start_index)
        self.display_loaded_vod_snapshot(self._snapshot_index or 0)
    def clear_vod_compare_start(self):
        self._compare_start_index = None
        if self._scrubber is not None:
            self._scrubber.set_pin(None)
        if self._loaded_vod is not None and self._loaded_vod.snapshots:
            self.display_loaded_vod_snapshot(self._snapshot_index or 0)
        else:
            self._refresh_vod_compare_controls()
            self._refresh_vod_compare_details(None, None, index=None)
    def _resolve_vod_compare_base_snapshot(self, index: int):
        if self._loaded_vod is None or not self._loaded_vod.snapshots:
            return None
        compare_index = self._compare_start_index
        if compare_index is not None:
            compare_index = min(max(int(compare_index), 0), len(self._loaded_vod.snapshots) - 1)
            return self._loaded_vod.snapshots[compare_index]
        if index <= 0:
            return None
        return self._loaded_vod.snapshots[index - 1]
    def _vod_compare_segment_snapshots(self, index: int) -> tuple[object, ...]:
        if self._loaded_vod is None or not self._loaded_vod.snapshots:
            return ()
        compare_index = self._compare_start_index
        if compare_index is None:
            start_index = max(0, index - 1)
        else:
            start_index = min(max(int(compare_index), 0), len(self._loaded_vod.snapshots) - 1)
        end_index = min(max(int(index), 0), len(self._loaded_vod.snapshots) - 1)
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        return tuple(self._loaded_vod.snapshots[start_index : end_index + 1])
    def _refresh_vod_compare_controls(self) -> None:
        has_snapshots = bool(
            not self._load_in_progress
            and self._loaded_vod is not None
            and self._loaded_vod.snapshots
        )
        del has_snapshots
        self._refresh_compare_hint()
    def _refresh_vod_compare_details(self, base_snapshot, snapshot, *, index: int | None, segment_snapshots=()) -> None:
        self._refresh_vod_compare_controls()
        # Shown exactly when there is an anchor to compare against. There is no
        # separate expanded flag any more: it could only ever be true when a
        # pin was set, so it was a second name for the same fact.
        pinned = self._compare_start_index is not None
        group = self._compare_details_group
        if group is not None:
            group.setVisible(pinned and base_snapshot is not None and snapshot is not None)
        if base_snapshot is None or snapshot is None:
            _set_text(self._compare_details_summary_label, "--")
            self._render_compare_detail_rows(())
            return

        _set_text(
            self._compare_details_summary_label,
            formatting.format_segment_headline(
                base_snapshot, snapshot, segment_snapshots=segment_snapshots
            ),
        )
        self._render_compare_detail_rows(
            formatting.compare_detail_rarity_rows(
                base_snapshot, snapshot, segment_snapshots=segment_snapshots
            )
        )

    def _render_compare_detail_rows(self, rows) -> None:
        """Rebuild the gained-by-rarity rows, and the broken/lost ones below.

        Rebuilt rather than updated in place, unlike the Items panel: this card
        is visible only while a compare pin is set, and its contents change
        shape entirely between segments rather than gaining and losing an item
        at a time.
        """
        container = self._compare_details_items
        if container is None:
            return
        layout = container.layout()
        container.setUpdatesEnabled(False)
        try:
            _clear_layout(layout)
            if not rows:
                note = QLabel("No item changes in this segment")
                note.setObjectName("itemChipNote")
                layout.addWidget(note)
                return
            for badge_html, items_html in rows:
                layout.addWidget(_build_compare_rarity_row(badge_html, items_html))
        finally:
            container.setUpdatesEnabled(True)
            container.updateGeometry()
    def rename_selected_vod(self):
        if self._loaded_vod is None or self._name_entry is None:
            return
        new_name = _read_text(self._name_entry).strip()
        try:
            metadata = rename_vod(self._loaded_vod.metadata.path, new_name)
            self._loaded_vod = load_vod(metadata.path)
        except Exception as exc:
            # The field stays open on failure: the name it holds is the one the
            # user typed, and closing it would throw that away to show them the
            # old heading beside the complaint.
            _set_text(self._status_label, f"Could not rename recording: {exc}")
            return
        self._set_renaming(False)
        self.refresh_loaded_vod_ui(update_slider=False)
        self.refresh_vods_list()
    def _clear_loaded_vod_selection(self) -> None:
        self._loaded_vod = None
        self._snapshot_index = None
        self._snapshot_throttle.cancel()
        self._requested_snapshot_index = None
        self._compare_start_index = None
        self._stage_range_anchor_index = None
        self._stage_range_anchor_number = None
        _clear_text_input(self._name_entry)
        self._set_renaming(False)
        _set_text(self._title_label, "No recording selected")
        _set_text(self._status_label, "Select a recording")
        self._scrubber.setEnabled(False)
        self._scrubber.set_pin(None)
        self._scrubber.set_model(scrubber_model.ScrubberModel(count=0))
        _set_text(self._position_label, "--")
        _set_text(self._legend_label, "--")
        _set_text(self._legend_meta_label, "")
        for label in self._rows.values():
            _set_text(label, "--")
        for label in self._compact_rows.values():
            _set_text(label, "--")
        self._items_section.collapse()
        self._items_section.update((), items_text="--")
        set_chests_card_values(
            self._chests_card_values,
            None,
        )
        set_loot_rarity_card_values(self._loot_rarity_card_values, None, None)
        self._refresh_vod_compare_controls()
        self._refresh_vod_compare_details(None, None, index=None)
        update_banishes_section(
            getattr(self, "_banishes_view", None), self._banishes_label, ()
        )
        set_stage_summary_labels(self._stage_summary_labels, None)
        self._refresh_stage_cards()
        self._stat_cards.invalidate()
        self._stat_cards.display_weapons((), status_text="Select a recording")
        self._stat_cards.display_tomes((), status_text="Select a recording")
        self._stat_cards.display_chaos_tome(None, status_text="Select a recording")
        self._stat_cards.display_damage_sources((), status_text="Select a recording")
        # Same state the router opens the library for, reached from a different
        # direction: deleting the selected run, cleaning up, or a load that
        # failed. Without this the tab is left showing a screen of "--" with
        # the one control that could fix it collapsed behind a button.
        self.ensure_recordings_chooser_for_empty_selection()
    def cleanup_recordings_by_snapshot_count(self):
        dialog = CleanupRecordingsDialog(
            self._window(),
            default_threshold=minimum_snapshot_count(),
        )
        if dialog.exec() != QDialog.Accepted or dialog.threshold is None:
            return

        selected_path = self._loaded_vod.metadata.path if self._loaded_vod is not None else None
        recorder = self._vod_recorder()
        active_path = (
            getattr(recorder, "path", None)
            if recorder is not None and getattr(recorder, "is_recording", False)
            else None
        )
        try:
            result = delete_vods_below_snapshot_count(
                dialog.threshold,
                excluded_paths={active_path} if active_path is not None else None,
            )
        except Exception as exc:
            _set_text(self._status_label, f"Could not clean recordings: {exc}")
            return

        if selected_path is not None and not selected_path.exists():
            self._clear_loaded_vod_selection()

        self.refresh_vods_list()
        message = f"[*] Removed {result.removed} recordings with snapshot count below {dialog.threshold}."
        skipped = result.skipped_active + result.skipped_locked
        if skipped:
            message += f" Skipped {skipped} active or locked recording(s)."
        self._log(message, tag="success")
    def delete_selected_vod(self):
        if self._loaded_vod is None:
            return
        dialog = ConfirmDeleteRecordingDialog(self._window(), self._loaded_vod.metadata.name)
        dialog.exec()
        if not dialog.result:
            return
        path = self._loaded_vod.metadata.path
        try:
            delete_vod(path)
        except Exception as exc:
            _set_text(self._status_label, f"Could not delete recording: {exc}")
            return
        self._clear_loaded_vod_selection()
        self.refresh_vods_list()
    def toggle_vod_items_expanded(self) -> None:
        self._items_section.toggle_expanded()
    def _update_recorded_chest_summary(self, snapshot) -> None:
        paid = getattr(snapshot, "paid_chests", None)
        key_procs = getattr(snapshot, "key_procs", None)
        labels = self._chests_card_values
        if labels:
            set_chests_card_values(
                labels,
                formatting.chests_card_values(
                    getattr(snapshot, "chests_opened_by_stage", None),
                    getattr(snapshot, "chests_total_by_stage", None),
                    getattr(snapshot, "chests_opened", None),
                    getattr(snapshot, "chests_total", None),
                    paid,
                    key_procs,
                    getattr(snapshot, "free_chests", None),
                    getattr(snapshot, "keys_count", None),
                    getattr(snapshot, "expected_key_procs", None),
                    False,
                    chests_per_minute=formatting.resolve_snapshot_chests_per_minute(
                        snapshot
                    ),
                ),
            )

    def _update_recorded_loot_rarity_summary(self, snapshot) -> None:
        labels = self._loot_rarity_card_values
        if not labels:
            return
        actual = getattr(snapshot, "loot_actual", None)
        expected = getattr(snapshot, "loot_expected", None)
        luck_stat = snapshot.stats.get("Luck") if isinstance(snapshot.stats, dict) else None
        set_loot_rarity_card_values(
            labels,
            getattr(luck_stat, "value", None),
            SimpleNamespace(
                available=actual is not None and expected is not None,
                actual=actual or {},
                expected=expected or {},
            ),
        )

    # -- stage chapters -----------------------------------------------------

    def _build_stage_chapters(self) -> QWidget:
        """Four stage cards, replacing the 4x4 "Stage Summary" table.

        The labels are handed to `set_stage_summary_labels` in exactly the dict
        shape the table used, so the *writer* is untouched and its tests keep
        covering it: this changes where the four values are drawn, not what
        they say.

        Each card is a jump target. The table was a readout of a run's shape;
        the same four numbers next to a scrubber are navigation, and a stage
        the eye has already picked out should be one click away.
        """
        container = QWidget()
        container.setObjectName("StageChapters")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._stage_cards = []
        for stage_number in range(1, 5):
            card = _StageChapterCard(stage_number)
            card.clicked.connect(self.on_stage_card_clicked)
            layout.addWidget(card, 1)
            self._stage_cards.append(card)
            self._stage_summary_labels.append(card.value_labels)
        return container

    def jump_to_stage(self, stage_number: int) -> None:
        """Move the playhead to the first snapshot of `stage_number`.

        Resolved through the scrubber's model rather than by re-walking the
        snapshots: the bands are already grouped there, and a second grouping
        here could disagree with the one drawn on the track.
        """
        band = self._stage_band(stage_number)
        if band is None:
            return
        self._stage_range_anchor_index = int(band.start)
        self._stage_range_anchor_number = int(stage_number)
        # A plain stage click starts a new range-selection gesture. Keeping an
        # older manual pin here would show Compare Details before the Shift
        # endpoint exists and make the newly highlighted anchor lie.
        self._compare_start_index = None
        self._scrubber.set_pin(None)
        self.display_loaded_vod_snapshot(band.start)
        self._refresh_stage_cards()

    def on_stage_card_clicked(
        self, stage_number: int, shift_pressed: bool = False
    ) -> None:
        """Jump normally; Shift extends the last stage click into a full range."""
        if not shift_pressed or self._stage_range_anchor_number is None:
            self.jump_to_stage(stage_number)
            return

        anchor_band = self._stage_band(self._stage_range_anchor_number)
        target_band = self._stage_band(stage_number)
        if anchor_band is None or target_band is None:
            return

        anchor_index = int(anchor_band.start)
        if int(anchor_band.stage_index) == int(target_band.stage_index):
            compare_index = int(anchor_band.end)
        elif int(anchor_band.stage_index) < int(target_band.stage_index):
            compare_index = max(anchor_index, int(target_band.start) - 1)
        else:
            compare_index = int(target_band.start)

        # Stage navigation follows the scrubber's A/B semantics: the ordinary
        # click owns the playhead (A), while Shift supplies only the pin (B).
        # The old order pinned the start and moved the playhead to the end,
        # silently restoring the pre-swap A=pin/B=playhead behaviour.
        self.display_loaded_vod_snapshot(anchor_index)
        self.set_vod_compare_start(compare_index)
        self._refresh_stage_cards()

    def _stage_band(self, stage_number: int):
        if self._scrubber is None or self._loaded_vod is None:
            return None
        for band in self._scrubber.model.stages:
            if band.stage_index is None:
                continue
            if int(band.stage_index) + 1 == int(stage_number):
                return band
        return None

    def _refresh_stage_cards(self) -> None:
        """Dim the stages this recording never reached, and light the current.

        Reads the *written* text rather than the rows: `set_stage_summary_labels`
        is the single writer, and asking it what it wrote keeps the two from
        drifting when the empty-stage projection changes.
        """
        if not self._stage_cards:
            return
        current_stage = None
        if self._scrubber is not None:
            index = self._snapshot_index or 0
            for band in self._scrubber.model.stages:
                if band.stage_index is not None and band.start <= index <= band.end:
                    current_stage = int(band.stage_index) + 1
                    break
        for card in self._stage_cards:
            has_data = _read_text(card.value_labels["time"]) not in ("--", "")
            card.set_state(
                has_data=has_data,
                is_current=card.stage_number == current_stage,
                is_anchor=card.stage_number == self._stage_range_anchor_number,
            )

    # -- scrubber -----------------------------------------------------------

    def _build_record_plaque(self) -> QWidget:
        """Which recording is open, and the two things you can do to it.

        The recording library is opened from this context row instead of
        consuming a separate full-width strip above it. Actions for the current
        recording sit beside its name, so there is one obvious place to look
        and no duplicate overflow menu.

        The status line above it is gone rather than moved. It read
        `950k | 601/713 at 02:14:38 | In-Game Time: 01:43:22`, rewritten on
        every drag frame, while the position pill beside the slot buttons says
        the same three numbers -- and says them next to the playhead they
        describe. What is left here is what the pill does not carry: the name,
        and a line for how the recording was captured (or for what went wrong).
        """
        frame = QFrame()
        frame.setObjectName("RecordingPlaque")
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        # First in the row, not last. The drawer opens from the left edge of
        # the tab, and the control that opens it now sits at that edge --
        # `»  6` closed, `«  6` open, the same chevron vocabulary as the
        # Templates rail. As a full-width `Recordings (6)` pill on the far
        # right it was both ~80px wider and pointing away from what it moves.
        self._select_btn = QPushButton(f"{LIBRARY_TOGGLE_CLOSED_CHEVRON}  0")
        self._select_btn.setObjectName("RecordingPlaqueLibrary")
        self._select_btn.setCheckable(True)
        self._select_btn.setCursor(Qt.PointingHandCursor)
        self._select_btn.setToolTip("Recordings library")
        self._select_btn.clicked.connect(self.toggle_recordings_chooser)
        title_row.addWidget(self._select_btn)
        self._title_label = QLabel("No recording selected")
        self._title_label.setObjectName("RecordingPlaqueTitle")
        title_row.addWidget(self._title_label)
        # Same secondary action as Edit in Templates: a real shared icon and
        # explicit label, rather than a font glyph whose shape varies by OS.
        self._rename_btn = QPushButton("Rename")
        self._rename_btn.setObjectName("RecordingPlaqueRename")
        _apply_button_icon(self._rename_btn, "media/edit_icon.svg", 18)
        self._rename_btn.setToolTip("Rename this recording")
        self._rename_btn.setCursor(Qt.PointingHandCursor)
        self._rename_btn.setEnabled(False)
        self._rename_btn.clicked.connect(self.begin_rename)
        title_row.addWidget(self._rename_btn)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("RecordingPlaqueDelete")
        self._delete_btn.setToolTip("Delete this recording")
        self._delete_btn.setCursor(Qt.PointingHandCursor)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self.delete_selected_vod)
        title_row.addWidget(self._delete_btn)
        self._name_entry = _NameEdit()
        self._name_entry.setObjectName("RecordingPlaqueNameEdit")
        self._name_entry.setVisible(False)
        # Capped rather than stretched: recording names are short, and a field
        # spanning the detail column would put a text box where the heading is.
        self._name_entry.setMaximumWidth(360)
        self._name_entry.returnPressed.connect(self.rename_selected_vod)
        self._name_entry.cancelled.connect(self.cancel_rename)
        title_row.addWidget(self._name_entry, 1)
        title_row.addStretch(1)
        text_column.addLayout(title_row)

        self._status_label = QLabel("Select a recording")
        self._status_label.setObjectName("RecordingPlaqueStatus")
        self._status_label.setWordWrap(True)
        text_column.addWidget(self._status_label)
        row.addLayout(text_column, 1)
        return frame

    def _on_detail_tab_changed(self) -> None:
        """Draw what just became visible, and show only what applies to it."""
        self._stat_cards.flush_pending()
        toggle = self._stats_expanded_toggle
        if toggle is not None and self._detail_tabs is not None:
            toggle.setVisible(self._detail_tabs.currentIndex() == 0)

    def begin_rename(self) -> None:
        """Swap the heading for the field, prefilled with the current name."""
        if self._loaded_vod is None or self._name_entry is None:
            return
        _clear_text_input(self._name_entry)
        _set_text_input(self._name_entry, self._loaded_vod.metadata.name)
        self._set_renaming(True)
        self._name_entry.setFocus()
        self._name_entry.selectAll()

    def cancel_rename(self) -> None:
        self._set_renaming(False)

    def _set_renaming(self, renaming: bool) -> None:
        for widget, visible in (
            (self._name_entry, renaming),
            (self._title_label, not renaming),
            (self._rename_btn, not renaming),
            (self._delete_btn, not renaming),
        ):
            if widget is not None and hasattr(widget, "setVisible"):
                widget.setVisible(visible)

    def _build_scrubber_header(self) -> QHBoxLayout:
        """The four series slots, and the position readout they sit beside."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._slot_buttons = []
        for slot_index in range(len(self._slots)):
            button = QPushButton()
            button.setObjectName("RecordingScrubberSlot")
            button.setProperty("timelineSlot", True)
            button.setEnabled(False)
            button.setMenu(
                build_timeline_series_menu(button, slot_index, self._set_slot)
            )
            self._slot_buttons.append(button)
            row.addWidget(button)
        # Directly after the slots, on the left, because they answer the same
        # question the slots do -- what is drawn on the track. Same builder and
        # same position as Compare Runs: both timelines show the same two
        # ceilings, and a second implementation is how they stop agreeing.
        self._cap_checkboxes = build_timeline_cap_checkboxes(
            self.on_recording_caps_changed
        )
        for checkbox in self._cap_checkboxes.values():
            row.addWidget(checkbox)
        row.addStretch(1)
        # The compare anchor lost its two buttons to the pin, and with them the
        # only thing that ever announced the feature existed. A hint that turns
        # into the segment readout once the pin is down is what replaces them:
        # discoverable while unused, useful once used.
        self._compare_hint_label = QLabel("")
        self._compare_hint_label.setObjectName("RecordingScrubberCompareHint")
        self._compare_hint_label.setTextFormat(Qt.RichText)
        row.addWidget(self._compare_hint_label)
        self._position_label = QLabel("--")
        self._position_label.setObjectName("RecordingScrubberPosition")
        self._position_label.setProperty("timelinePosition", True)
        row.addWidget(self._position_label)
        self._refresh_slot_buttons()
        self._refresh_compare_hint()
        return row

    def _refresh_compare_hint(self) -> None:
        label = self._compare_hint_label
        if label is None:
            return
        has_snapshots = bool(
            self._loaded_vod is not None and self._loaded_vod.snapshots
        )
        if not has_snapshots:
            _set_text(label, "")
            return
        anchor = self._compare_start_index
        if anchor is None:
            _set_text(
                label,
                '<span style="color:#5C6675;">Shift+click sets compare point '
                '<b style="color:#C084FC;">B</b></span>&nbsp;&nbsp;·&nbsp;&nbsp;',
            )
            return
        snapshots = self._loaded_vod.snapshots
        anchor = min(max(int(anchor), 0), len(snapshots) - 1)
        current = min(max(int(self._snapshot_index or 0), 0), len(snapshots) - 1)
        _set_text(
            label,
            f'<b style="color:#38BDF8;">A</b> '
            f'<span style="color:#8A94A3;">{snapshots[current].time_label}</span> '
            f'<span style="color:#5C6675;">&rarr;</span> '
            f'<b style="color:#C084FC;">B</b> '
            f'<span style="color:#8A94A3;">{snapshots[anchor].time_label}</span>'
            f'<span style="color:#5C6675;">&nbsp;&nbsp;·&nbsp;&nbsp;Esc clears B'
            f'</span>&nbsp;&nbsp;·&nbsp;&nbsp;',
        )

    def _set_slot(self, slot_index: int, keys: tuple[str, ...]) -> None:
        slots = list(self._slots)
        if not 0 <= slot_index < len(slots) or slots[slot_index] == keys:
            return
        slots[slot_index] = keys
        self._slots = tuple(slots)
        _save_scrubber_slots(self._slots)
        self._refresh_slot_buttons()
        self._rebuild_scrubber_model()
        if self._loaded_vod is not None and self._loaded_vod.snapshots:
            self._refresh_scrub_readout(self._snapshot_index or 0)

    def on_recording_caps_changed(self) -> None:
        keys = checked_timeline_caps(self._cap_checkboxes)
        save_timeline_caps(keys)
        # A cap key can add a series the model does not carry yet, so this is a
        # rebuild rather than a repaint.
        self._rebuild_scrubber_model()

    def _refresh_slot_buttons(self) -> None:
        for index, (button, slot) in enumerate(zip(self._slot_buttons, self._slots)):
            refresh_timeline_slot_button(button, index, slot)

    def _rebuild_scrubber_model(self) -> None:
        """Rebuild what the scrubber paints. Once per load or slot change.

        Never on a scrub frame: this walks every snapshot for every selected
        series plus the whole marker pass, which is exactly the work
        `on_scrub_index_changed` coalesces away from the drag.
        """
        if self._scrubber is None:
            return
        self._scrubber.set_slots(self._slots)
        self._scrubber.set_cap_keys(checked_timeline_caps(self._cap_checkboxes))
        snapshots = self._loaded_vod.snapshots if self._loaded_vod is not None else ()
        self._scrubber.set_model(
            scrubber_model.build_model(
                snapshots,
                # Not `series_keys`: a cap drawn without its curve still needs
                # that stat's scale, which only the built series carries.
                series_keys=self._scrubber.model_keys,
            )
        )
        if hasattr(self._scrubber, "set_projection"):
            self._scrubber.set_projection(
                build_axis_projection(snapshots, mode=AXIS_TIME)
            )
        self._scrubber.set_pin(self._compare_start_index)

    @staticmethod
    def _save_stats_expanded_preference(expanded: bool) -> None:
        config.user_config[LIVE_STATS_EXPANDED_CONFIG_KEY] = bool(expanded)
        config.save_config(config.user_config)

    def build(self):
        """Put the tab in the bar. Its contents wait until someone opens it.

        400 widgets, built at every launch whether or not the tab was opened --
        the second-largest tab after Compare Runs, which went the same way.

        Safe to defer because every writer into this tab already asks whether it
        is showing: the router gates `refresh_vods_list` and
        `ensure_recordings_chooser_for_empty_selection` on
        `is_recordings_tab_active`, and `_refresh_vods_list_if_visible` -- the
        one the recording path calls on every captured snapshot -- gates itself
        by the same question. Measured as well as read: with all 63 public
        methods counted and the window parked on Logs, none of them was called.

        (`LiveStatsTab.build` is *not* deferred, and the difference is the
        measurement: `vod_capture` calls `refresh_player_stats_timeline_ui` and
        `set_recording_status_text` on it with no such gate, straight off the
        recording path.)

        Separate from `__init__` for the same reason `LiveStatsTab.build` is:
        it needs real offscreen Qt, so `tests/support/player_stats.py`'s builder
        can construct the component without paying for a widget tree, and the
        built tab is covered by `tools/step21_vod_trace.py` instead.
        """
        self._tab = LazyPage(self._build_workspace)
        self._tab.setObjectName("RecordingsPage")
        self._tabview.addTab(self._tab, "Recordings")

    def build_now(self) -> None:
        """Build the contents without waiting for a show. For tests."""
        if self._tab is not None:
            self._tab.build_now()

    def _build_workspace(self):
        vods_layout = QVBoxLayout(self._tab)

        # A splitter, not the QHBoxLayout this used to be: the library is a
        # drawer now, and a drawer the user cannot resize is a fixed panel that
        # merely hides. `setChildrenCollapsible(False)` keeps a drag from
        # squeezing either side to nothing -- closing is the toggle's job, and
        # a 3px-wide library nobody meant to make is not a state worth saving.
        self._body_splitter = QSplitter(Qt.Horizontal)
        self._body_splitter.setObjectName("RecordingsBodySplitter")
        self._body_splitter.setChildrenCollapsible(False)
        self._body_splitter.setHandleWidth(10)
        self._body_splitter.splitterMoved.connect(
            lambda _pos, _index: self._on_library_width_dragged()
        )
        vods_detail = QWidget()
        vods_detail_layout = QVBoxLayout(vods_detail)
        # `vods_layout` already supplies the tab's outer inset. Keeping Qt's
        # default 9 px margin here added a second empty strip above the
        # recording/title row and made it look detached from the timeline.
        vods_detail_layout.setContentsMargins(0, 0, 0, 0)
        vods_detail_layout.addWidget(self._build_record_plaque())
        vods_detail_layout.addLayout(self._build_scrubber_header())
        self._scrubber = RecordingScrubber()
        self._scrubber.setToolTip(
            "Drag to move A  ·  Shift+drag moves compare point B\n"
            "← → step (Shift × 10)  ·  Home / End  ·  B pins  ·  Esc clears B"
        )
        self._scrubber.setEnabled(False)
        self._scrubber.indexChanged.connect(self.on_scrub_index_changed)
        self._scrubber.pinChanged.connect(self.on_scrub_pin_changed)
        vods_detail_layout.addWidget(self._scrubber)
        legend_row = QHBoxLayout()
        legend_row.setContentsMargins(0, 0, 0, 0)
        legend_row.setSpacing(8)
        self._legend_label = QLabel("--")
        self._legend_label.setObjectName("RecordingScrubberLegend")
        self._legend_label.setTextFormat(Qt.RichText)
        legend_row.addWidget(self._legend_label)
        legend_row.addStretch(1)
        self._legend_meta_label = QLabel("")
        self._legend_meta_label.setObjectName("RecordingScrubberMeta")
        self._legend_meta_label.setTextFormat(Qt.RichText)
        self._legend_meta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        legend_row.addWidget(self._legend_meta_label)
        vods_detail_layout.addLayout(legend_row)
        recordings_page = QWidget()
        recordings_page.setObjectName("LiveStatsPage")
        recordings_page_layout = QGridLayout(recordings_page)
        recordings_page_layout.setContentsMargins(0, 0, 0, 0)
        recordings_page_layout.setHorizontalSpacing(10)
        recordings_page_layout.setVerticalSpacing(0)

        recordings_main = QWidget()
        recordings_main.setObjectName("LiveStatsMain")
        recordings_main_layout = QVBoxLayout(recordings_main)
        recordings_main_layout.setContentsMargins(0, 0, 0, 0)
        recordings_main_layout.setSpacing(14)

        vod_items_group = QGroupBox("Items")
        vod_items_group.setObjectName("LiveStatsItems")
        vod_items_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        vod_items_group.setMinimumWidth(220)
        vod_items_layout = QVBoxLayout(vod_items_group)
        vod_items_layout.setContentsMargins(11, 11, 11, 11)
        vod_items_layout.setSpacing(8)

        # Match Live Stats: an empty inventory has no rarity furniture at all;
        # once items exist, a compact row of coloured dots and counts appears.
        vod_items_meta = QHBoxLayout()
        vod_items_meta.setContentsMargins(0, 0, 0, 0)
        vods_items_rarity_label = QLabel("")
        vods_items_rarity_label.setObjectName("ItemsRaritySummary")
        vods_items_rarity_label.setTextFormat(Qt.RichText)
        vods_items_rarity_label.setVisible(False)
        vod_items_meta.addWidget(vods_items_rarity_label, 0, Qt.AlignLeft)
        vod_items_meta.addStretch(1)
        vods_items_sort_combo = CompactItemsSortComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            vods_items_sort_combo.addItem(label, mode)
        vods_items_sort_combo.setCurrentIndex(
            vods_items_sort_combo.findData(ITEM_SORT_RARITY_DESC)
        )
        vods_items_sort_combo.setVisible(False)
        vod_items_meta.addWidget(
            vods_items_sort_combo, 0, Qt.AlignRight | Qt.AlignVCenter
        )
        vod_items_layout.addLayout(vod_items_meta)

        vods_items_chips_container = QWidget()
        vods_items_chips_container.setObjectName("cardContent")
        FlowLayout(vods_items_chips_container, margin=0, spacing=6)
        vods_items_scroll = QScrollArea()
        vods_items_scroll.setObjectName("LiveStatsItemsScroll")
        vods_items_scroll.setWidgetResizable(True)
        vods_items_scroll.setFrameShape(QFrame.NoFrame)
        vods_items_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        vods_items_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        vods_items_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vods_items_scroll.setWidget(vods_items_chips_container)
        # No `setMinimumHeight` floor here, though the list does need the room:
        # a hard minimum cannot yield, and a QVBoxLayout that cannot compress a
        # child still *positions* the ones after it as if it had -- so on a
        # short panel the divider and Banishes landed inside this scroll's rect
        # and the item chips drew over them. The list wins the space by stretch
        # instead, and Banishes below is bounded so its minimum cannot grow
        # into it (which is what the floor was defending against).
        vod_items_layout.addWidget(vods_items_scroll, 3)

        self._items_section = ItemsSectionView(
            group=vod_items_group,
            label=None,
            rarity_label=vods_items_rarity_label,
            toggle_btn=None,
            sort_combo=vods_items_sort_combo,
            chips_container=vods_items_chips_container,
            always_expanded=True,
            scroll_area=vods_items_scroll,
        )
        vods_items_sort_combo.currentIndexChanged.connect(
            lambda _index: self._items_section.on_sort_changed()
        )

        vod_items_divider = QFrame()
        vod_items_divider.setObjectName("LiveStatsItemsDivider")
        vod_items_divider.setFrameShape(QFrame.HLine)
        vod_items_layout.addWidget(vod_items_divider)

        vod_banishes_section = QWidget()
        vod_banishes_section.setObjectName("LiveStatsBanishes")
        vod_banishes_layout = QVBoxLayout(vod_banishes_section)
        vod_banishes_layout.setContentsMargins(*BANISHES_SECTION_MARGINS)
        vod_banishes_layout.setSpacing(4)
        vod_banishes_title = QLabel("BANISHES")
        vod_banishes_title.setObjectName("LiveStatsBanishesTitle")
        vod_banishes_layout.addWidget(vod_banishes_title)
        self._banishes_label = QLabel("No banishes yet")
        self._banishes_label.setObjectName("LiveStatsBanishesText")
        self._banishes_label.setTextFormat(Qt.RichText)
        self._banishes_label.setWordWrap(True)
        vod_banishes_layout.addWidget(self._banishes_label)
        self._banishes_chips_container = QWidget()
        self._banishes_chips_container.setObjectName("BanishesChips")
        FlowLayout(self._banishes_chips_container, margin=0, spacing=5)
        self._banishes_chips_container.setVisible(False)
        # The chips scroll inside a bounded viewport rather than growing the
        # section. Their flow layout pushes a `minimumHeight` onto its container
        # for every row it wraps, and a minimum is what a QVBoxLayout cannot
        # compress -- see the item scroll below for what that did.
        vod_banishes_chips_scroll = QScrollArea()
        vod_banishes_chips_scroll.setObjectName("BanishesChipsScroll")
        vod_banishes_chips_scroll.setWidgetResizable(True)
        vod_banishes_chips_scroll.setFrameShape(QFrame.NoFrame)
        vod_banishes_chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        vod_banishes_chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        vod_banishes_chips_scroll.setMinimumHeight(BANISHES_CHIPS_MAX_HEIGHT)
        vod_banishes_chips_scroll.setMaximumHeight(BANISHES_CHIPS_MAX_HEIGHT)
        vod_banishes_chips_scroll.setWidget(self._banishes_chips_container)
        vod_banishes_chips_scroll.setVisible(False)
        vod_banishes_layout.addWidget(vod_banishes_chips_scroll)
        self._banishes_view = BanishesSectionView(
            label=self._banishes_label,
            chips_container=self._banishes_chips_container,
            chips_scroll=vod_banishes_chips_scroll,
        )
        vod_items_layout.addWidget(vod_banishes_section)

        vod_summary_grid = QGridLayout()
        vod_summary_grid.setContentsMargins(0, 0, 0, 0)
        vod_summary_grid.setHorizontalSpacing(8)
        vod_summary_grid.setVerticalSpacing(8)
        # "Run Summary" is gone: In-Game Time lives in the position pill, and
        # Level, KPS and Mob Kills in the scrubber's legend, which reads at the
        # playhead the same way this card did. Four widgets kept agreeing about
        # numbers one readout already owned.
        #
        # `chests_per_minute` survives it, in the Loot tab -- see
        # `_build_chest_rate_row`. It is the one value here that was never a
        # measurement: it is derived from Elite Spawn Increase and Powerup Drop
        # Chance, so sitting beside measured counters is what made it read as
        # one.
        vod_summary_grid.addWidget(self._build_stage_chapters(), 0, 0)
        vod_summary_grid.setColumnStretch(0, 1)
        recordings_main_layout.addLayout(vod_summary_grid)
        # "Segment Compare" is gone. It was a card whose height followed its
        # own contents, so every scrub frame resized it and shoved the stage
        # cards beside it around; and it duplicated the anchor readout the
        # scrubber header already carries. Its one unique line -- the gains
        # preview -- moved into Compare Details, which now appears only when a
        # pin is set. Without a pin it was comparing against the *previous*
        # snapshot, a ten-second delta nobody asked for.
        self._compare_details_group = QGroupBox("Compare Details")
        vod_compare_details_layout = QVBoxLayout(self._compare_details_group)
        # One header row, as in the mockup: the A -> B span and the segment's
        # totals on the left, the control that drops the anchor's counterpart
        # on the right. It replaces two stacked labels -- a rarity-dot gains
        # preview and a "Snapshot 305 -> 1 | 51:02 -> 00:00 | +154 items" line
        # -- which said the item total twice above the rows that answer it.
        compare_header = QWidget()
        compare_header.setObjectName("CompareSegmentHeader")
        compare_header_layout = QHBoxLayout(compare_header)
        compare_header_layout.setContentsMargins(0, 0, 0, 0)
        compare_header_layout.setSpacing(8)
        self._compare_details_summary_label = QLabel("--")
        self._compare_details_summary_label.setObjectName("CompareSegmentHeadline")
        self._compare_details_summary_label.setTextFormat(Qt.RichText)
        self._compare_details_summary_label.setWordWrap(True)
        _apply_summary_label_padding(self._compare_details_summary_label)
        compare_header_layout.addWidget(self._compare_details_summary_label, 1)
        # Esc clears the pin too -- the scrubber's hint says so -- but that is
        # only discoverable once the hint has been read, and the card is where
        # the user is looking when they are done with the segment.
        # Its own rule rather than `SmallGhostButton`: the ghost palette is for
        # controls that should stay quiet, and this one is the way out of a mode.
        self._compare_clear_button = QPushButton("Clear B")
        self._compare_clear_button.setObjectName("CompareSegmentClear")
        self._compare_clear_button.clicked.connect(self.clear_vod_compare_start)
        compare_header_layout.addWidget(
            self._compare_clear_button, 0, Qt.AlignRight | Qt.AlignTop
        )
        vod_compare_details_layout.addWidget(compare_header)
        # A row per rarity, not a four-column chip grid. Four columns wide
        # enough for a two-word item name need most of the tab; this card gets
        # a third of it, so a thirty-item segment came out as a tall block of
        # half-empty columns. A wrapping row keeps the rarity marking the grid
        # was for -- the colour is on the dot *and* on every name.
        vod_compare_scroll, _vod_compare_scroll_content, vod_compare_scroll_layout = _make_scroll_section()
        # Keep enough vertical room to see a full segment comparison at once.
        # The previous 96px viewport clipped the lower rarity/loss rows despite
        # the Recordings page still having useful height available.
        vod_compare_scroll.setMinimumHeight(140)
        vod_compare_scroll.setMaximumHeight(220)
        vod_compare_scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._compare_details_items = QWidget()
        self._compare_details_items.setObjectName("CompareDetailsRows")
        compare_items_layout = QVBoxLayout(self._compare_details_items)
        compare_items_layout.setContentsMargins(0, 0, 0, 0)
        compare_items_layout.setSpacing(4)
        self._render_compare_detail_rows(())
        vod_compare_scroll_layout.addWidget(self._compare_details_items)
        vod_compare_scroll_layout.addStretch(1)
        vod_compare_details_layout.addWidget(vod_compare_scroll)
        self._compare_details_group.setVisible(False)
        recordings_main_layout.addWidget(self._compare_details_group)
        self._detail_tabs = FullWidthTabWidget()
        self._detail_tabs.setObjectName("subTabs")
        self._detail_tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        vod_stats_tab = QWidget()
        vod_stats_tab_layout = QVBoxLayout(vod_stats_tab)
        # In the tab bar's corner rather than a row of its own inside the Stats
        # page: one checkbox was costing a full-width strip above the grid, on
        # a tab where vertical space is what the stat cards are competing for.
        # It only means anything on Stats, so it is hidden on the other five --
        # a control that stays visible while doing nothing reads as broken.
        self._stats_expanded_toggle = LabeledSwitch("Expanded")
        self._stats_expanded_toggle.setObjectName("LiveStatsExpandedToggle")
        self._stats_expanded_toggle.setChecked(
            bool(config.user_config.get(LIVE_STATS_EXPANDED_CONFIG_KEY, False))
        )
        self._stats_expanded_toggle.setToolTip(
            "Show the full stat names in detailed label/value rows"
        )
        self._detail_tabs.setHeaderControl(self._stats_expanded_toggle)
        vods_scroll, _vods_scroll_content, vods_scroll_layout = _make_scroll_section()
        vod_stats_tab_layout.addWidget(vods_scroll)

        compact_stats_grid = _ResponsiveCardGrid(
            minimum_card_width=160,
            spacing=6,
            maximum_columns=5,
            stretch_columns=False,
        )
        compact_stats_grid.setProperty("viewMode", "compact")
        for group in PLAYER_STAT_GROUPS:
            stat_group = QFrame()
            stat_group.setObjectName("StatCard")
            stat_group.setFixedSize(160, 174)
            group_layout = QVBoxLayout(stat_group)
            group_layout.setContentsMargins(8, 7, 8, 7)
            group_layout.setSpacing(2)
            compact_rows = QWidget()
            compact_rows.setObjectName("LiveStatsCompactRows")
            compact_rows_layout = QVBoxLayout(compact_rows)
            compact_rows_layout.setContentsMargins(0, 0, 0, 0)
            compact_rows_layout.setSpacing(2)
            for spec in group:
                compact_stat = QWidget()
                compact_stat.setObjectName("LiveStatsCompactStat")
                compact_stat_layout = QHBoxLayout(compact_stat)
                compact_stat_layout.setContentsMargins(0, 0, 0, 0)
                compact_stat_layout.setSpacing(5)

                name_label = QLabel(abbreviate_stat_label(spec.label))
                name_label.setObjectName("LiveStatsCompactStatName")
                compact_stat_layout.addWidget(name_label)
                compact_stat_layout.addStretch(1)

                value_label = QLabel("--")
                value_label.setObjectName("LiveStatsCompactStatValue")
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                compact_stat_layout.addWidget(value_label)
                self._compact_rows[spec.label] = value_label
                compact_rows_layout.addWidget(compact_stat)
            group_layout.addWidget(compact_rows)
            compact_stats_grid.add_card(stat_group)

        expanded_stats_grid = _ResponsiveCardGrid(
            minimum_card_width=300,
            spacing=8,
            maximum_columns=4,
        )
        expanded_stats_grid.setProperty("viewMode", "expanded")
        for group in PLAYER_STAT_GROUPS:
            stat_group = QFrame()
            stat_group.setObjectName("StatCard")
            group_layout = QFormLayout(stat_group)
            group_layout.setContentsMargins(6, 6, 6, 6)
            group_layout.setHorizontalSpacing(6)
            group_layout.setVerticalSpacing(3)
            for spec in group:
                name_label = QLabel(spec.label)
                name_label.setObjectName("LiveStatsExpandedStatName")
                value_label = QLabel("--")
                value_label.setObjectName("LiveStatsExpandedStatValue")
                value_label.setMinimumWidth(max(48, LIVE_STATS_VALUE_WIDTH - 16))
                _apply_player_stat_value_baseline(value_label, spec.value_format)
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._rows[spec.label] = value_label
                group_layout.addRow(name_label, value_label)
            expanded_stats_grid.add_card(stat_group)

        compact_stats_grid.setVisible(False)
        self._stats_expanded_toggle.toggled.connect(compact_stats_grid.setHidden)
        self._stats_expanded_toggle.toggled.connect(expanded_stats_grid.setVisible)
        self._stats_expanded_toggle.toggled.connect(
            self._save_stats_expanded_preference
        )
        # Parented before shown -- see the note on the same four lines in
        # `live_stats.py`. This copy was the second blank window.
        vods_scroll_layout.addWidget(compact_stats_grid)
        vods_scroll_layout.addWidget(expanded_stats_grid)
        compact_stats_grid.setHidden(self._stats_expanded_toggle.isChecked())
        expanded_stats_grid.setVisible(self._stats_expanded_toggle.isChecked())
        vods_scroll_layout.addStretch(1)

        vod_loot_tab = QWidget()
        vod_loot_tab_layout = QVBoxLayout(vod_loot_tab)
        vod_loot_scroll, _vod_loot_scroll_content, vod_loot_scroll_layout = (
            _make_scroll_section()
        )
        vod_loot_tab_layout.addWidget(vod_loot_scroll)
        vod_loot_grid = QGridLayout()
        vod_loot_grid.setContentsMargins(0, 0, 0, 0)
        vod_loot_grid.setHorizontalSpacing(8)
        vod_loot_grid.setVerticalSpacing(8)

        vod_chests_group = QGroupBox("Chests (Expected = key procs)")
        vod_chests_group_layout = QVBoxLayout(vod_chests_group)
        vod_chests_card, self._chests_card_values = _build_chests_stats_card(
            include_chests_per_minute=True
        )
        vod_chests_card.setObjectName("StatCardInner")
        vod_chests_group_layout.addWidget(vod_chests_card)
        self._chests_per_minute_label = self._chests_card_values["chests_per_minute"]
        vod_loot_grid.addWidget(vod_chests_group, 0, 0)

        vod_rarity_group = QGroupBox("Item Rarity (Expected = items by tier)")
        vod_rarity_group_layout = QVBoxLayout(vod_rarity_group)
        vod_rarity_card, self._loot_rarity_card_values = _build_loot_rarity_card()
        vod_rarity_card.setObjectName("StatCardInner")
        vod_rarity_group_layout.addWidget(vod_rarity_card)
        vod_loot_grid.addWidget(vod_rarity_group, 0, 1)

        for column in range(2):
            vod_loot_grid.setColumnStretch(column, 1)
        vod_loot_scroll_layout.addLayout(vod_loot_grid)
        vod_loot_scroll_layout.addStretch(1)
        vod_weapons_tab = QWidget()
        vod_weapons_tab_layout = QVBoxLayout(vod_weapons_tab)
        vods_weapons_status_label = QLabel("Select a recording")
        vods_weapons_status_label.setWordWrap(True)
        vod_weapons_tab_layout.addWidget(vods_weapons_status_label)
        vod_weapons_scroll, _vod_weapons_scroll_content, vod_weapons_scroll_layout = _make_scroll_section()
        vod_weapons_scroll_layout.setContentsMargins(0, 0, 0, 0)
        vod_weapons_tab_layout.addWidget(vod_weapons_scroll)
        vod_tomes_tab = QWidget()
        vod_tomes_tab_layout = QVBoxLayout(vod_tomes_tab)
        vods_tomes_status_label = QLabel("Select a recording")
        vods_tomes_status_label.setWordWrap(True)
        vod_tomes_tab_layout.addWidget(vods_tomes_status_label)
        vod_tomes_scroll, _vod_tomes_scroll_content, vod_tomes_scroll_layout = _make_scroll_section()
        vod_tomes_scroll_layout.setContentsMargins(0, 0, 0, 0)
        vod_tomes_tab_layout.addWidget(vod_tomes_scroll)
        vod_chaos_tab = QWidget()
        vod_chaos_tab_layout = QVBoxLayout(vod_chaos_tab)
        vods_chaos_status_label = QLabel("Select a recording")
        vods_chaos_status_label.setWordWrap(True)
        vod_chaos_tab_layout.addWidget(vods_chaos_status_label)
        vod_chaos_scroll, _vod_chaos_scroll_content, vod_chaos_scroll_layout = _make_scroll_section()
        vod_chaos_scroll_layout.setContentsMargins(0, 0, 0, 0)
        vod_chaos_tab_layout.addWidget(vod_chaos_scroll)
        vod_damage_sources_tab = QWidget()
        vod_damage_sources_tab_layout = QVBoxLayout(vod_damage_sources_tab)
        vods_damage_sources_status_label = QLabel("Select a recording")
        vods_damage_sources_status_label.setWordWrap(True)
        vod_damage_sources_tab_layout.addWidget(vods_damage_sources_status_label)
        vod_damage_sources_scroll, _vod_damage_sources_scroll_content, vod_damage_sources_scroll_layout = _make_scroll_section()
        vod_damage_sources_scroll_layout.setContentsMargins(0, 0, 0, 0)
        vod_damage_sources_tab_layout.addWidget(vod_damage_sources_scroll)
        # Owned by the component, same as the Live Stats tab's eight. See
        # `ui/tabs/player_stats/stat_cards.py` for why this half of the
        # cards renderer needs no Compare Runs adapter: the compare scopes
        # never reach these four sections.
        self._stat_cards = StatCardsView(
            weapons_layout=vod_weapons_scroll_layout,
            weapons_status_label=vods_weapons_status_label,
            tomes_layout=vod_tomes_scroll_layout,
            tomes_status_label=vods_tomes_status_label,
            chaos_layout=vod_chaos_scroll_layout,
            chaos_status_label=vods_chaos_status_label,
            damage_sources_layout=vod_damage_sources_scroll_layout,
            damage_sources_status_label=vods_damage_sources_status_label,
            section_visible=section_visibility_over(lambda: self._detail_tabs),
        )
        self._detail_tabs.currentChanged.connect(
            lambda _index: self._on_detail_tab_changed()
        )
        self._detail_tabs.addTab(vod_stats_tab, "Stats")
        self._detail_tabs.addTab(vod_loot_tab, "Loot")
        self._detail_tabs.addTab(vod_weapons_tab, "Weapons")
        self._detail_tabs.addTab(vod_tomes_tab, "Tomes")
        self._detail_tabs.addTab(vod_chaos_tab, "Chaos")
        self._detail_tabs.addTab(vod_damage_sources_tab, "Damage Sources")
        self._detail_tabs.setMinimumHeight(self._detail_tabs.sizeHint().height())
        recordings_main_layout.addWidget(self._detail_tabs)
        vod_stats_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_loot_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_weapons_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_tomes_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_chaos_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_damage_sources_tab_layout.setContentsMargins(0, 0, 0, 0)

        # The middle column scrolls, the scrubber and the Items panel do not.
        # Scrolling the *whole* tab was the alternative and is worse: the
        # scrubber is the thing everything below is read against, and a
        # navigation control that scrolls off the top stops being one. The
        # Items panel already scrolls inside itself.
        recordings_main_scroll = QScrollArea()
        recordings_main_scroll.setObjectName("RecordingsMainScroll")
        recordings_main_scroll.setWidgetResizable(True)
        recordings_main_scroll.setFrameShape(QFrame.NoFrame)
        recordings_main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        recordings_main_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        recordings_main_scroll.setWidget(recordings_main)
        recordings_page_layout.addWidget(recordings_main_scroll, 0, 0)
        recordings_page_layout.addWidget(vod_items_group, 0, 1)
        recordings_page_layout.setColumnStretch(0, 3)
        recordings_page_layout.setColumnStretch(1, 1)
        recordings_page_layout.setRowStretch(0, 1)
        vods_detail_layout.addWidget(recordings_page, 1)
        self._chooser_group = QGroupBox("Recordings")
        self._chooser_group.setVisible(False)
        self._chooser_group.setMinimumWidth(RECORDINGS_LIST_MIN_WIDTH)
        self._chooser_group.setMaximumWidth(RECORDINGS_LIST_MAX_WIDTH + 40)
        chooser_layout = QVBoxLayout(self._chooser_group)
        chooser_layout.setSpacing(8)

        self._search_entry = QLineEdit()
        self._search_entry.setObjectName("RecordingsSearch")
        self._search_entry.setPlaceholderText("Search by name…")
        self._search_entry.setClearButtonEnabled(True)
        self._search_entry.textChanged.connect(self.on_recordings_search_changed)
        chooser_layout.addWidget(self._search_entry)

        # A captioned combo, not the items panel's icon-only one: which order
        # the library is in has to be readable without opening the menu.
        self._sort_combo = QComboBox()
        self._sort_combo.setObjectName("RecordingsSortCombo")
        for mode, label in RECORDING_SORT_LABELS.items():
            self._sort_combo.addItem(label, mode)
        saved_index = self._sort_combo.findData(recording_sort_mode())
        if saved_index >= 0:
            self._sort_combo.setCurrentIndex(saved_index)
        self._sort_combo.currentIndexChanged.connect(self.on_recordings_sort_changed)
        chooser_layout.addWidget(self._sort_combo)

        self._list_frame = QListWidget()
        self._list_frame.setObjectName("RecordingsList")
        self._list_frame.setMinimumWidth(RECORDINGS_LIST_MIN_WIDTH)
        self._list_frame.setMaximumWidth(RECORDINGS_LIST_MAX_WIDTH)
        self._list_frame.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_frame.currentItemChanged.connect(self._on_vod_selection_changed)
        chooser_layout.addWidget(self._list_frame, 1)

        # The library's footer, and the auto-filter's home. `Clean Short` used
        # to sit between the name field and `Delete`, in the row of actions on
        # the *selected* recording -- a category error that put a
        # library-wide delete one button away from a rename.
        footer = QFrame()
        footer.setObjectName("RecordingsLibraryFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 8, 0, 0)
        footer_layout.setSpacing(7)

        self._library_summary_label = QLabel("--")
        self._library_summary_label.setObjectName("RecordingsLibrarySummary")
        footer_layout.addWidget(self._library_summary_label)

        threshold_row = QHBoxLayout()
        threshold_row.setContentsMargins(0, 0, 0, 0)
        threshold_row.setSpacing(6)
        threshold_row.addWidget(QLabel("Keep at least"))
        self._min_snapshots_spin = QSpinBox()
        self._min_snapshots_spin.setObjectName("RecordingsMinimumSnapshots")
        self._min_snapshots_spin.setRange(0, 9999)
        self._min_snapshots_spin.setValue(minimum_snapshot_count())
        self._min_snapshots_spin.valueChanged.connect(self.on_minimum_snapshot_count_changed)
        threshold_row.addWidget(self._min_snapshots_spin)
        threshold_row.addWidget(QLabel("snapshots"))
        threshold_row.addStretch(1)
        footer_layout.addLayout(threshold_row)

        threshold_hint = QLabel(
            "Applied when a run ends, and used as the threshold below."
        )
        threshold_hint.setObjectName("RecordingsLibraryHint")
        threshold_hint.setWordWrap(True)
        footer_layout.addWidget(threshold_hint)

        self._cleanup_btn = QPushButton("Delete short")
        self._cleanup_btn.setObjectName("danger")
        self._cleanup_btn.clicked.connect(self.cleanup_recordings_by_snapshot_count)
        footer_layout.addWidget(self._cleanup_btn, 0, Qt.AlignLeft)
        chooser_layout.addWidget(footer)
        # Filled here rather than waiting for the first `refresh_vods_list`:
        # the panel is built collapsed and shown later, so a footer that only
        # populates on refresh reads as "0 recordings, 0 MB" for however long
        # it takes the first refresh to arrive.
        self._refresh_library_footer(list(self._library.index))
        self._body_splitter.addWidget(self._chooser_group)
        self._body_splitter.addWidget(vods_detail)
        self._body_splitter.setStretchFactor(0, 0)
        self._body_splitter.setStretchFactor(1, 1)
        vods_layout.addWidget(self._body_splitter, 1)
        # Replay the saved drawer state. `guided=False` because this is not the
        # app offering the library, it is the user's own last choice coming
        # back -- so the auto-close after a pick must not fire on it.
        self.set_recordings_chooser_expanded(
            recording_library_open(), guided=False, remember=False
        )
        # The list was not painted while there was nothing to paint into, and
        # the signature says "painted" only because it starts as `None`. A tab
        # opened for the first time must find its library, not an empty column.
        self._list_signature = None
        self.refresh_vods_list()
