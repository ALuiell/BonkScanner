"""The Compare Runs tab: choosing two recorded runs and rendering their diff.

Moved out of ``PlayerStatsMixin`` by step 9 -- the first module under ``ui/``
and the first tab to get its own package. It stayed a *mixin* through eleven
steps for one reason: eleven of its methods were called class-qualified from
the suite (``gui.MegabonkApp._refresh_compare_runs_diff(app)`` and friends),
which only resolves through ``MegabonkApp``'s MRO.

**Step 21d closed that out.** This is an object with explicit dependencies, it
builds its own widgets, and it has no class-qualified callers left anywhere:
the nine ``format_compare_runs_*`` passthroughs are gone (``projections.
formatting`` is the target), and the config readers, ``_nearest_snapshot_index``,
``_set_visible`` and ``_checkbox_checked`` are module-level functions at the
bottom of this file. A free function has no class to be orphaned from, which
retires the failure mode instead of moving it.

Two things this file no longer does, both worth stating because both were
load-bearing coupling:

* It does not read its widgets off a shared ``self``. ``gui_layout`` built
  ~40 ``compare_run*`` widgets onto ``MegabonkApp`` and this module read them
  back; ``build()`` below is those ~250 lines, moved here. That also retired the
  method-body ``ItemsSectionView`` import ``gui_layout`` needed to avoid the
  ``gui_layout -> ui.tabs.player_stats -> live_stats -> gui_layout`` cycle.
* It does not name the Recordings tab. It used to call
  ``_ensure_vod_metadata_refresh`` on it to start the shared metadata refresh,
  while that method's completion callback reached forward into this tab's list
  signature and repaint. ``app.vod_library.VodLibrary`` owns the index now and
  tells each tab separately; see that module's header for the measurement.

``_set_visible``, ``_checkbox_checked``, ``_nearest_snapshot_index`` and
``_snapshot_compare_time`` came here from ``PlayerStatsMixin`` despite their
generic names: once the tab left, that mixin had no callers of any of them.
"""
from __future__ import annotations

import bisect
import threading
from collections import OrderedDict
from math import isfinite
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.vod_library import (
    RECORDING_SORT_CONFIG_KEY,
    load_vod,
    recording_sort_mode,
)
from core.run_summary import item_counts
from core.stats.formats import PlayerStatFormat
from core.stats.formatters import format_player_stat_delta
from core.stats.types import PLAYER_STAT_GROUPS
from projections.item_sort import ITEM_SORT_RARITY_DESC
from projections.recording_sort import normalize_recording_sort_mode, sort_recordings
from projections.timeline_axis import snapshot_times as projected_snapshot_times
from ui.metric_table import CompactMetricCardGridView, MetricTableView
from ui.recording_library import RecordingLibraryRow, recording_search_text
from ui.shared import (
    FullWidthTabWidget,
    LabeledSwitch,
    StagedLoadingPage,
    _apply_summary_label_padding,
    _make_scroll_section,
    _set_text,
)
from ui.styles import ITEM_SORT_LABELS, RECORDING_SORT_LABELS
from ui.throttle import UiUpdateThrottle, batched_updates
from ui.tabs.player_stats.items_section import ItemsSectionView
from projections import compare_overview
from projections import formatting
from projections import scrubber as scrubber_model
from projections.compare_overview import EMPTY_AXIS_TABLE, EMPTY_LUCK_LOOT
from projections.formatting import COMPARE_RUN_STAT_LABELS
from projections.metric_table import EMPTY_METRIC_TABLE, MetricSection, MetricTable
from ui.compare_overview import (
    CompareRunsAxisView,
    CompareRunsHubView,
    CompareRunsLuckLootView,
)
from ui.tabs.compare_runs.timeline import (
    AXIS_TIME,
    CompareRunsTimeline,
)
from ui.tabs.compare_runs.timeline_legend import CompareRunsTimelineLegend
from ui.timeline_controls import (
    TimelineSeriesSlots,
    TIMELINE_CAPS_CONFIG_KEY,
    build_timeline_cap_checkboxes,
    build_timeline_series_menu,
    checked_timeline_caps,
    refresh_timeline_slot_button,
)


COMPARE_RUN_STAT_CONFIG_KEY = "COMPARE_RUN_STAT_LABELS"

COMPARE_RUN_SECTIONS_CONFIG_KEY = "COMPARE_RUN_SECTIONS"
COMPARE_RUN_COMPACT_TIMELINE_CONFIG_KEY = "COMPARE_RUN_COMPACT_TIMELINE"
_RECORDING_SEARCH_ROLE = Qt.UserRole + 1

#: How many rendered diffs to keep. A diff is four short HTML strings and three
#: `MetricTable`s, and scrubbing back and forth over the same stretch of two
#: runs is the motion this cache exists for; 128 covers a few seconds of
#: dragging in each direction without holding a whole recording's worth.
COMPARE_RUN_DIFF_CACHE_SIZE = 128

COMPARE_RUN_SECTION_DEFAULTS = {
    "items": False,
    "stage_summary": False,
    "weapons": False,
    "tomes": False,
    "chaos": False,
    "shrines": False,
    "passives": False,
}


def _timeline_series_numeric_value(key: str, snapshot) -> float | None:
    if snapshot is None:
        return None
    if key == scrubber_model.KILLS_SERIES:
        value = getattr(snapshot, "mob_kills", None)
    elif key == scrubber_model.ITEMS_SERIES:
        return float(sum(item_counts(getattr(snapshot, "items", ())).values()))
    else:
        stats = getattr(snapshot, "stats", None)
        stat = stats.get(key) if isinstance(stats, dict) else None
        value = getattr(stat, "value", None)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _timeline_series_display_value(key: str, snapshot) -> str:
    value = _timeline_series_numeric_value(key, snapshot)
    if value is None:
        return "--"
    if key in {scrubber_model.KILLS_SERIES, scrubber_model.ITEMS_SERIES}:
        return formatting.format_count(value)
    stats = getattr(snapshot, "stats", None)
    stat = stats.get(key) if isinstance(stats, dict) else None
    return str(getattr(stat, "display_value", "--") or "--")


def _timeline_series_delta_value(key: str, snapshot_a, snapshot_b) -> str:
    value_a = _timeline_series_numeric_value(key, snapshot_a)
    value_b = _timeline_series_numeric_value(key, snapshot_b)
    if value_a is None or value_b is None:
        return "--"
    # `A - B`, matching every other delta on this screen. The legend sits above
    # the tabs, so a legend that subtracted the other way would contradict the
    # card the user reads next.
    delta = value_a - value_b
    if key in {scrubber_model.KILLS_SERIES, scrubber_model.ITEMS_SERIES}:
        sign = "+" if delta >= 0 else "-"
        return f"{sign}{formatting.format_count(abs(delta))}"

    stats_a = getattr(snapshot_a, "stats", None)
    stats_b = getattr(snapshot_b, "stats", None)
    stat_a = stats_a.get(key) if isinstance(stats_a, dict) else None
    stat_b = stats_b.get(key) if isinstance(stats_b, dict) else None
    spec = getattr(stat_b, "spec", None) or getattr(stat_a, "spec", None)
    display_scale = float(getattr(spec, "display_scale", 1.0) or 1.0)
    value_format = getattr(spec, "value_format", PlayerStatFormat.FLAT)
    if not isinstance(value_format, PlayerStatFormat):
        value_format = PlayerStatFormat.FLAT
    return format_player_stat_delta(delta * display_scale, value_format)


def _timeline_game_time_value(snapshot) -> float | None:
    if snapshot is None:
        return None
    try:
        value = float(getattr(snapshot, "game_time_seconds", None))
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _timeline_game_time_display(snapshot) -> str:
    value = _timeline_game_time_value(snapshot)
    return "--" if value is None else formatting.format_elapsed_time(value)


def _timeline_game_time_delta(snapshot_a, snapshot_b) -> str:
    value_a = _timeline_game_time_value(snapshot_a)
    value_b = _timeline_game_time_value(snapshot_b)
    if value_a is None or value_b is None:
        return "--"
    delta = value_a - value_b
    sign = "+" if delta > 0 else "-" if delta < 0 else ""
    return f"{sign}{formatting.format_elapsed_time(abs(delta))}"


# --------------------------------------------------------------------------
# Module-level, not methods on the tab.
#
# These were `@classmethod` / `@staticmethod` passthroughs on `CompareRunsMixin`
# and, together with the nine `format_compare_runs_*` delegators to
# `projections.formatting`, they were the whole of this file's class-qualified
# surface: sixteen `MegabonkApp.<name>(...)` call sites in the suite, resolving
# through the MRO. Step 21d **retires** the failure mode rather than relocating
# it, the way step 19 did with `chaos_stats_in_game_order` and step 20 with the
# two memory recorders: a free function has no class to be orphaned from, so a
# later move cannot strand a call site the way 14b stranded the Chaos Tome
# panel. The nine formatting delegators are simply gone -- `projections.
# formatting` is the caller's target now, which is where they always went.
# --------------------------------------------------------------------------


def default_compare_run_stat_labels() -> tuple[str, ...]:
    return COMPARE_RUN_STAT_LABELS


def all_compare_run_stat_labels() -> tuple[str, ...]:
    return tuple(spec.label for group in PLAYER_STAT_GROUPS for spec in group)


def configured_compare_run_stat_labels() -> tuple[str, ...]:
    saved_labels = config.user_config.get(COMPARE_RUN_STAT_CONFIG_KEY)
    if isinstance(saved_labels, list):
        allowed_labels = set(all_compare_run_stat_labels())
        selected = tuple(str(label) for label in saved_labels if str(label) in allowed_labels)
        if selected:
            return selected
    return default_compare_run_stat_labels()


def configured_compare_run_sections() -> dict[str, bool]:
    saved_sections = config.user_config.get(COMPARE_RUN_SECTIONS_CONFIG_KEY)
    sections = dict(COMPARE_RUN_SECTION_DEFAULTS)
    if isinstance(saved_sections, dict):
        for key in sections:
            if key in saved_sections:
                sections[key] = bool(saved_sections[key])
    return sections


def _filter_metric_table(table: MetricTable, query: str) -> MetricTable:
    """The table narrowed to rows whose label matches ``query``.

    An `Only differences` checkbox used to sit beside the search field and drop
    every row whose delta parsed as zero. It is gone: two runs that agree
    exactly on a stat are rare enough that the control spent its life switched
    off, hiding nothing while costing a slot in the toolbar and a second piece
    of filter state to keep in sync with the search box.
    """
    needle = str(query or "").strip().casefold()
    sections = []
    for section in table.sections:
        rows = tuple(
            row
            for row in section.rows
            if not needle or needle in row.label.casefold()
        )
        if rows:
            sections.append(
                MetricSection(
                    headers=section.headers,
                    rows=rows,
                    title=section.title,
                    subtitle=section.subtitle,
                )
            )
    return MetricTable(
        sections=tuple(sections),
        empty_text="No matching stats" if table.sections else table.empty_text,
    )


def _set_visible(widget, visible: bool) -> None:
    if widget is not None and hasattr(widget, "setVisible"):
        widget.setVisible(visible)


def _set_metric_table(view, table) -> None:
    """`_set_text`'s counterpart for the widget-rendered cards.

    No-ops on an unbuilt tab for the same reason `_set_text` does: the refresh
    paths run before `build()` in several tests and in the error path.
    """
    if view is not None and hasattr(view, "set_table"):
        view.set_table(table)


def _checkbox_checked(checkbox) -> bool:
    return bool(checkbox is not None and checkbox.isChecked())


class SnapshotTimeIndex:
    """Snapshot compare-times, pre-sorted once so lookup is a bisect.

    ``_nearest_snapshot_index`` used to walk every snapshot and call
    ``_snapshot_compare_time`` on each one, and the time-sync path calls it
    once per ``valueChanged`` -- so a drag across a 900-snapshot recording did
    ~900 attribute probes per mouse pixel. The snapshot list of a *loaded*
    recording never changes, so the walk belongs at load time.

    Tie-breaking is the part worth being careful about, because the linear scan
    it replaces had one: it kept the first strictly-closer snapshot, so among
    equally distant candidates the lowest **original list index** won. A target
    exactly between two snapshots is not a contrived case -- the two runs being
    compared are sampled independently -- so ``nearest`` reproduces that
    lexicographic ``(distance, index)`` order rather than whatever the sort
    happens to yield.
    """

    __slots__ = ("_times", "_indices")

    def __init__(self, times: tuple[float, ...], indices: tuple[int, ...]) -> None:
        self._times = times
        self._indices = indices

    @classmethod
    def build(cls, snapshots) -> "SnapshotTimeIndex":
        entries = list(enumerate(projected_snapshot_times(snapshots)))
        entries = [(time_value, index) for index, time_value in entries]
        return cls(
            tuple(entry[0] for entry in entries),
            tuple(entry[1] for entry in entries),
        )

    def nearest(self, target_time: float) -> int:
        times = self._times
        if not times:
            return 0
        target = float(target_time)
        position = bisect.bisect_left(times, target)

        best: tuple[float, int] | None = None
        for neighbour in (position - 1, position):
            if not 0 <= neighbour < len(times):
                continue
            # Every entry sharing this exact time is a candidate; the scan this
            # replaces would have picked the earliest of them.
            time_value = times[neighbour]
            low = bisect.bisect_left(times, time_value)
            high = bisect.bisect_right(times, time_value)
            candidate = (abs(time_value - target), min(self._indices[low:high]))
            if best is None or candidate < best:
                best = candidate
        return 0 if best is None else best[1]


def _nearest_snapshot_index(snapshots, target_time: float) -> int:
    """Uncached nearest lookup, for callers that hold no index.

    The tab itself goes through ``SnapshotTimeIndex`` -- see
    ``_compare_run_time_index`` -- because it can cache one per loaded side.
    """
    return SnapshotTimeIndex.build(snapshots).nearest(target_time)



class CompareRunsTab:
    """The Compare Runs tab: an object with explicit dependencies.

    Constructed once by `gui_layout._build_compare_runs_view`, which is its
    composition root. Step 9 split this out of `PlayerStatsMixin` as a mixin
    and said turning it into a standalone object was a behaviour change
    belonging to a later step; this is that step.

    It holds **no reference to the Recordings tab**. It used to call back into
    `RecordingsTabMixin._ensure_vod_metadata_refresh` to start the shared
    metadata refresh, while that method's completion callback reached forward
    into this tab's list signature and repaint. Both directions are gone:
    `vod_library` (step 21b) owns the index, this tab asks *it* to refresh, and
    it is told through the `invalidate`/`repaint` pair the composition root
    registers.

    `is_active` is a supplier and not a method here for the reason
    `RecordingsTab` records: the tab-switch router is **step 26's**. The tab
    asks the tab-bar question; it does not own the router that answers it.
    """

    def __init__(
        self,
        *,
        tabview,
        vod_library,
        is_active: Callable[[], bool],
        schedule: Callable[[Callable[[], None]], None] | None = None,
        diff_throttle: UiUpdateThrottle | None = None,
        timeline_series_slots: TimelineSeriesSlots | None = None,
        log: Callable[..., None] | None = None,
    ) -> None:
        self._tabview = tabview
        self._library = vod_library
        self._is_active = is_active
        self._schedule = schedule
        self._log = log or (lambda _message, **_kwargs: None)
        self._disposed = False

        # Slider-drag rate limiting. Injectable so a test can drive the
        # coalescing with a fake clock instead of a real event loop; the
        # default is the shared ~30 FPS window.
        self._uses_default_diff_throttle = diff_throttle is None
        self._diff_throttle = diff_throttle or UiUpdateThrottle()
        self._timeline_series_slots = timeline_series_slots or TimelineSeriesSlots()
        # Formatted diffs, keyed by everything that can change one. Cleared
        # whenever a side's recording is replaced, which is also what keeps the
        # `id(vod)` in the key from ever outliving its object.
        self._diff_cache: OrderedDict = OrderedDict()
        self._time_indexes: dict = {}
        # The payload last written to the diff cards, for dirty-checking. Reset
        # by `build()`, because widgets created after a write have not seen it.
        self._rendered_diff_cards = None

        # Selection and view state. Sixteen names on `MegabonkApp` until step
        # 21d, every one measured to have zero production readers outside this
        # module -- their only other mention was the init line in
        # `gui_app.__init__`.
        self._vod_a = None
        self._vod_b = None
        self._index_a = None
        self._index_b = None
        self._list_signature = None
        self._chooser_expanded = False
        self._guided_selection_active = False
        self._stats_config_expanded = False
        self._item_details_expanded = False
        self._syncing = False
        self._load_generations = {}
        self._timeline_compact = bool(
            config.user_config.get(COMPARE_RUN_COMPACT_TIMELINE_CONFIG_KEY, False)
        )
        self._series_slots = self._timeline_series_slots.slots
        self._timeline_series_slots.subscribe(self._apply_timeline_series_slots)
        self._pending_diff_payload = None
        self._active_diff_page = 0
        self._stats_query = ""

        # The legacy visibility config is deliberately retained on disk for
        # compatibility, but it no longer controls redesigned full-width tabs.
        self._sections = configured_compare_run_sections()
        self._items_enabled = True
        self._stage_summary_enabled = True
        self._weapons_enabled = True
        self._tomes_enabled = True
        self._chaos_enabled = True
        self._shrines_enabled = True
        self._passives_enabled = True

        # Every widget `build()` creates. `MegabonkApp.__init__` declared these
        # as 34 `= None` lines; they are declared here for the same reason
        # `RecordingsTab` declares its own -- so the readers below can be plain
        # attribute access and an unbuilt tab raises rather than rendering into
        # `None`.
        self._tab = None
        self._select_btn = None
        self._run_a_change_btn = None
        self._run_b_change_btn = None
        self._swap_btn = None
        self._stats_config_btn = None
        self._chooser_group = None
        self._stats_config_group = None
        self._stat_checkboxes = {}
        self._items_checkbox = None
        self._stage_summary_checkbox = None
        self._weapons_checkbox = None
        self._tomes_checkbox = None
        self._chaos_checkbox = None
        self._shrines_checkbox = None
        self._passives_checkbox = None
        self._item_details_btn = None
        self._diff_overview_group = None
        self._diff_overview_label = None
        self._diff_stats_group = None
        self._diff_stats_label = None
        self._diff_items_group = None
        self._diff_items_label = None
        self._diff_items_table = None
        self._diff_stage_summary_group = None
        self._diff_stage_summary_label = None
        self._diff_stages_table = None
        self._diff_weapons_group = None
        self._diff_weapons_table = None
        self._diff_tomes_group = None
        self._diff_tomes_table = None
        self._diff_chaos_group = None
        self._diff_chaos_table = None
        self._diff_shrines_group = None
        self._diff_shrines_table = None
        self._diff_passives_group = None
        self._diff_passives_table = None
        # Never built, in either tree. `_refresh_compare_runs_selected_labels`
        # writes these through `_set_text`, which no-ops on `None`; `gui_layout`
        # built no such label and `gui_app` only ever set it to `None`. Kept, not
        # deleted: removing them is a behaviour change dressed as cleanup, and it
        # belongs with whoever decides the panel wants a selected-run caption.
        self._run_a_selected_label = None
        self._run_b_selected_label = None
        self._run_a_list_frame = None
        self._run_a_status_label = None
        self._run_a_slider = None
        self._run_a_timeline_label = None
        self._run_a_summary_label = None
        self._snapshot_comparison_table = None
        self._run_a_items_view = None
        self._run_b_list_frame = None
        self._run_b_status_label = None
        self._run_b_slider = None
        self._run_b_timeline_label = None
        self._run_b_summary_label = None
        self._run_b_items_view = None
        self._timeline = None
        self._timeline_position_label = None
        self._timeline_legend = None
        self._compact_timeline_btn = None
        self._series_slot_buttons = []
        self._detail_tabs = None
        self._sort_combo = None
        self._cap_checkboxes: dict = {}
        self._luck_loot_view = None
        self._axis_view = None
        self._hub_view = None
        self._stats_search = None
        self._stats_table = None
        self._stats_source_table = EMPTY_METRIC_TABLE
        self._run_a_search = None
        self._run_b_search = None
        self._workspace_stack = None
        self._workspace_page = None
        self._chooser_page = None

    def refresh_compare_runs_list(self):
        """Refresh both chooser lists synchronously after the initial build."""
        if self._disposed:
            return
        for _step in self._refresh_compare_runs_list_steps(batch_size=0):
            pass

    def _refresh_compare_runs_list_steps(self, *, batch_size: int):
        """Refresh both lists, yielding between row batches when requested."""
        if self._disposed:
            return
        list_a = self._run_a_list_frame
        list_b = self._run_b_list_frame
        if list_a is None or list_b is None:
            return

        vods = sort_recordings(self._library.index, self._compare_runs_sort_mode())
        selected_a = self._vod_a.metadata.path if self._vod_a is not None else None
        selected_b = self._vod_b.metadata.path if self._vod_b is not None else None
        available_paths = {vod.path for vod in vods}
        if selected_a is not None and selected_a not in available_paths:
            self._set_compare_run_error("a", "Selected recording is no longer available")
            selected_a = None
        if selected_b is not None and selected_b not in available_paths:
            self._set_compare_run_error("b", "Selected recording is no longer available")
            selected_b = None
        # The sort mode belongs in the signature: reordering changes neither
        # selection nor the set of recordings, so without it the early return
        # below eats the repaint and the combo box silently does nothing.
        signature = (
            str(selected_a) if selected_a is not None else "",
            str(selected_b) if selected_b is not None else "",
            self._compare_runs_sort_mode(),
            tuple((str(vod.path), vod.name, vod.snapshot_count, vod.duration_seconds) for vod in vods),
        )
        self._library.ensure_refresh()
        if self._list_signature == signature:
            return

        yield from self._populate_compare_run_list_steps(
            list_a,
            vods,
            selected_a,
            batch_size=batch_size,
        )
        if batch_size:
            yield None
        yield from self._populate_compare_run_list_steps(
            list_b,
            vods,
            selected_b,
            batch_size=batch_size,
        )
        if batch_size:
            yield None
        self._filter_compare_run_list("a")
        self._filter_compare_run_list("b")
        self._list_signature = signature
        self._refresh_compare_runs_selected_labels()

    def _compare_runs_sort_mode(self) -> str:
        """The combo's order, or the saved one before the combo exists."""
        combo = self._sort_combo
        if combo is None:
            return recording_sort_mode()
        return normalize_recording_sort_mode(combo.currentData())

    def on_compare_runs_sort_changed(self, _index: int = 0) -> None:
        self._save_compare_run_config_value(
            "recording sort order",
            RECORDING_SORT_CONFIG_KEY,
            normalize_recording_sort_mode(self._compare_runs_sort_mode()),
        )
        self._list_signature = None
        self.refresh_compare_runs_list()

    def _save_compare_run_config_value(self, label: str, key: str, value) -> bool:
        """Persist one preference without leaking an exception through Qt."""
        missing = object()
        previous = config.user_config.get(key, missing)
        config.user_config[key] = value
        try:
            result = config.save_config(config.user_config)
        except Exception as exc:
            reason = str(exc)
        else:
            if getattr(result, "success", True) is not False:
                return True
            reason = str(getattr(result, "reason", "") or "unknown error")
        if previous is missing:
            config.user_config.pop(key, None)
        else:
            config.user_config[key] = previous
        self._log(f"Could not save {label}: {reason}", tag="warning")
        return False

    def invalidate_compare_runs_list(self) -> None:
        """Drop the painted-list signature. `VodLibrary`'s invalidate hook.

        This is the whole of what the Recordings tab used to reach in and do.
        The Recordings tab no longer names this tab at all.
        """
        self._list_signature = None

    def _configured_sections(self) -> dict[str, bool]:
        """What `__init__` read, so `build()` cannot read something else.

        `gui_layout` used to call `configured_compare_run_sections()` a second
        time when building the checkboxes, while `gui_app.__init__` had already
        called it for the five enabled flags. Two reads of one config file, one
        object apart -- harmless in practice and exactly the kind of thing a
        constructor removes for free.
        """
        return dict(self._sections)

    def _populate_compare_run_list(self, list_frame, vods, selected_path) -> None:
        for _step in self._populate_compare_run_list_steps(
            list_frame,
            vods,
            selected_path,
            batch_size=0,
        ):
            pass

    def _populate_compare_run_list_steps(
        self,
        list_frame,
        vods,
        selected_path,
        *,
        batch_size: int,
    ):
        list_frame.blockSignals(True)
        list_frame.clear()
        if not vods:
            item = QListWidgetItem("No saved recordings")
            item.setFlags(Qt.NoItemFlags)
            list_frame.addItem(item)
            list_frame.blockSignals(False)
            return

        selected_row = None
        longest_seconds = max(
            (max(0, int(getattr(vod, "duration_seconds", 0) or 0)) for vod in vods),
            default=0,
        )
        for row, vod in enumerate(vods):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, str(vod.path))
            item.setData(_RECORDING_SEARCH_ROLE, recording_search_text(vod))
            widget = RecordingLibraryRow(vod, longest_seconds=longest_seconds)
            item.setSizeHint(widget.sizeHint())
            list_frame.addItem(item)
            list_frame.setItemWidget(item, widget)
            if selected_path == vod.path:
                selected_row = row
            if batch_size and (row + 1) % batch_size == 0:
                yield None
        if selected_row is not None:
            list_frame.setCurrentRow(selected_row)
        list_frame.blockSignals(False)

    def _filter_compare_run_list(self, side: str) -> None:
        list_frame = self._compare_run_widget(side, "list_frame")
        search = getattr(self, f"_run_{side}_search", None)
        if list_frame is None:
            return
        needle = search.text().strip().casefold() if search is not None else ""
        for row in range(list_frame.count()):
            item = list_frame.item(row)
            searchable = str(item.data(_RECORDING_SEARCH_ROLE) or item.text()).casefold()
            item.setHidden(bool(needle and needle not in searchable))

    def _on_compare_run_selection_changed(self, side: str, current: QListWidgetItem | None):
        if current is None:
            return
        path_str = current.data(Qt.UserRole)
        if path_str:
            self.load_compare_run(side, path_str)

    def load_compare_run(self, side: str, path) -> None:
        if self._disposed:
            return
        path = Path(path)
        generations = self._load_generations
        generation = int(generations.get(side, 0)) + 1
        generations[side] = generation
        self._load_generations = generations
        self._report_compare_run_state(side, "Loading recording…")

        def finish(loaded_vod, error) -> None:
            if self._disposed or generation != self._load_generations.get(side):
                return
            if error is not None:
                self._report_compare_run_state(
                    side, f"Could not load recording: {error}"
                )
                return
            try:
                self._set_compare_run_vod(side, loaded_vod)
                self._set_compare_run_index(side, 0 if loaded_vod.snapshots else None)
                self.refresh_compare_runs_list()
                self.refresh_compare_runs_ui(changed_side=side)
                self._auto_close_compare_runs_chooser_if_ready()
            except Exception as exc:
                # A malformed recording can fail after parsing, while building
                # its timeline/diff model. Keep that inside the queued UI slot.
                try:
                    self._set_compare_run_vod(side, None)
                except Exception:
                    # If the renderer itself is the failing boundary, reset the
                    # Python selection directly and leave repainting for the
                    # next valid load.
                    if side == "a":
                        self._vod_a = None
                    else:
                        self._vod_b = None
                self._set_compare_run_index(side, None)
                self._report_compare_run_state(
                    side, f"Could not display recording: {exc}"
                )

        def load() -> None:
            try:
                loaded = load_vod(path)
                error = None
            except Exception as exc:
                loaded = None
                error = exc
            self._marshal(lambda: finish(loaded, error))

        # Background only when there is somewhere to marshal the result back
        # to -- the same two branches the mixin chose between by reading
        # `self.after` and `self._invoker` off the shared namespace, now one
        # injected callable.
        if callable(self._schedule):
            try:
                threading.Thread(
                    target=load,
                    name=f"compare-{side}-loader",
                    daemon=True,
                ).start()
            except Exception as exc:
                finish(None, exc)
        else:
            load()

    def _marshal(self, callback) -> bool:
        schedule = self._schedule
        if callable(schedule):
            return schedule(callback) is not False
        else:
            callback()
            return True

    def toggle_compare_runs_chooser(self):
        next_expanded = not bool(self._chooser_expanded)
        self.set_compare_runs_chooser_expanded(next_expanded, guided=False)
        if next_expanded:
            self.refresh_compare_runs_list()

    def toggle_compare_runs_stats_config(self):
        self._stats_config_expanded = not bool(
            self._stats_config_expanded
        )
        if self._stats_config_expanded:
            self.set_compare_runs_chooser_expanded(False, guided=False)
        self._refresh_compare_runs_stats_config()

    def _auto_close_compare_runs_chooser_if_ready(self) -> None:
        if not bool(self._chooser_expanded):
            return
        if not bool(self._guided_selection_active):
            return
        if self._vod_a is None or self._vod_b is None:
            return
        self.set_compare_runs_chooser_expanded(False, guided=False)

    def ensure_compare_runs_chooser_for_empty_selection(self) -> None:
        if self._disposed or not self._is_active():
            return
        if self._vod_a is not None or self._vod_b is not None:
            return
        if bool(self._chooser_expanded):
            return
        self.set_compare_runs_chooser_expanded(True, guided=True)

    def set_compare_runs_chooser_expanded(self, expanded: bool, *, guided: bool) -> None:
        self._chooser_expanded = bool(expanded)
        self._guided_selection_active = bool(expanded and guided)
        if self._chooser_expanded:
            self._stats_config_expanded = False
            self._refresh_compare_runs_stats_config()
        self._refresh_compare_runs_chooser()

    def on_compare_run_section_selection_changed(self):
        sections = self._compare_run_checked_sections()
        self._items_enabled = sections["items"]
        self._stage_summary_enabled = sections["stage_summary"]
        self._weapons_enabled = sections["weapons"]
        self._tomes_enabled = sections["tomes"]
        self._chaos_enabled = sections["chaos"]
        self._shrines_enabled = sections["shrines"]
        self._passives_enabled = sections["passives"]
        if not self._items_enabled:
            self._item_details_expanded = False
        self._save_compare_run_sections()
        self.refresh_compare_runs_ui()

    def toggle_compare_runs_item_details(self):
        self._item_details_expanded = not bool(
            self._item_details_expanded
        )
        self.refresh_compare_runs_ui()

    def on_compare_run_stat_selection_changed(self):
        self._save_compare_run_stat_selection()
        self.refresh_compare_runs_ui()

    def toggle_compare_run_items_expanded(self, side: str) -> None:
        """One click opens both inventories.

        These two panels exist to be read against each other, and a per-side
        toggle let them drift: A expanded against a folded B is a comparison of
        26 items with 6. The clicked side still decides the direction, so the
        button under the cursor does what its own caption says.
        """
        clicked = self._compare_run_items_view(side)
        if clicked is None:
            return
        expanded = not clicked.expanded()
        for run_side in ("a", "b"):
            view = self._compare_run_items_view(run_side)
            if view is not None:
                view.set_expanded(expanded)

    def on_compare_run_items_sort_changed(self, side: str) -> None:
        """Sorting one inventory sorts the other, for the same reason.

        Two lists in different orders cannot be compared by eye at all. The
        mirrored combo emits `currentIndexChanged` and re-enters here, which the
        equality check below stops -- the second pass finds nothing to change.
        """
        source = self._compare_run_items_view(side)
        if source is None or source.sort_combo is None:
            return
        mode = source.sort_combo.currentData()
        for run_side in ("a", "b"):
            view = self._compare_run_items_view(run_side)
            if view is None:
                continue
            combo = view.sort_combo
            if combo is not None and combo.currentData() != mode:
                index = combo.findData(mode)
                if index >= 0:
                    combo.setCurrentIndex(index)
            view.on_sort_changed()

    def _compare_run_items_view(self, side: str):
        """The `ItemsSectionView` for one compare side.

        Built by `gui_layout._build_compare_run_panel`, which is where
        the widgets it owns are created. Step 21 moves that
        construction into this tab; until then the lookup stays here
        rather than each call site reaching for the attribute.
        """
        return getattr(self, f"_run_{side}_items_view")

    def swap_compare_runs(self):
        self._vod_a, self._vod_b = self._vod_b, self._vod_a
        self._index_a, self._index_b = (
            self._index_b,
            self._index_a,
        )
        # A/B is part of every cached diff -- the overview literally reads
        # "Run B compared to Run A" -- so a swap invalidates all of them.
        self._invalidate_compare_runs_diff_cache()
        self._list_signature = None
        self.refresh_compare_runs_list()
        self._refresh_compare_runs_timeline_model()
        self.refresh_compare_runs_ui(changed_side="a")

    def on_compare_timeline_position_changed(self, position: float) -> None:
        """Immediate playhead/index update; content follows through coalescing."""
        if self._disposed:
            return
        timeline = self._timeline
        if timeline is None:
            return
        index_a, index_b = timeline.nearest_indices(position)
        self._set_compare_run_index("a", index_a)
        self._set_compare_run_index("b", index_b)
        self._refresh_compare_timeline_readout()
        self._diff_throttle.request(self.refresh_compare_runs_ui)

    def _refresh_compare_timeline_readout(self) -> None:
        self._refresh_compare_timeline_position_label()
        self._refresh_compare_timeline_legend()

    def _refresh_compare_timeline_position_label(self) -> None:
        values = []
        for side, color in (("a", "#38BDF8"), ("b", "#C084FC")):
            snapshot = self._compare_run_snapshot(side)
            label = getattr(snapshot, "time_label", "--") if snapshot is not None else "--"
            values.append(f'<span style="color:{color}; font-weight:700;">{side.upper()}</span> {label}')
        _set_text(self._timeline_position_label, " &nbsp;·&nbsp; ".join(values))

    def _refresh_compare_timeline_legend(self) -> None:
        legend = self._timeline_legend
        if legend is None:
            return
        keys = tuple(dict.fromkeys(key for slot in self._series_slots for key in slot))
        legend.set_keys(keys)
        snapshot_a = self._compare_run_snapshot("a")
        snapshot_b = self._compare_run_snapshot("b")
        legend.set_game_values(
            _timeline_game_time_display(snapshot_a),
            _timeline_game_time_display(snapshot_b),
            _timeline_game_time_delta(snapshot_a, snapshot_b),
        )
        legend.set_values(
            (
                key,
                (
                    _timeline_series_display_value(key, snapshot_a),
                    _timeline_series_display_value(key, snapshot_b),
                    _timeline_series_delta_value(key, snapshot_a, snapshot_b),
                ),
            )
            for key in keys
        )

    def _refresh_compare_runs_timeline_model(self) -> None:
        if self._timeline is None:
            return
        keys = tuple(key for slot in self._series_slots for key in slot)
        self._timeline.set_runs(
            self._vod_a,
            self._vod_b,
            series_keys=keys,
            cap_keys=self._enabled_cap_keys(),
        )
        self._timeline.set_axis_mode(AXIS_TIME)
        self._timeline.set_compact(self._timeline_compact)
        self._refresh_series_slot_buttons()
        self._refresh_compare_timeline_readout()

    def _enabled_cap_keys(self) -> tuple[str, ...]:
        """Which cap staircases to draw. Deliberately not the plotted series."""
        return checked_timeline_caps(self._cap_checkboxes)

    def on_compare_run_caps_changed(self) -> None:
        keys = self._enabled_cap_keys()
        self._save_compare_run_config_value(
            "timeline caps",
            TIMELINE_CAPS_CONFIG_KEY,
            list(keys),
        )
        if self._timeline is not None:
            self._timeline.set_cap_keys(keys)

    def _set_timeline_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact == self._timeline_compact:
            return
        self._timeline_compact = compact
        self._save_compare_run_config_value(
            "compact timeline state",
            COMPARE_RUN_COMPACT_TIMELINE_CONFIG_KEY,
            compact,
        )
        if self._timeline is not None:
            self._timeline.set_compact(compact)
        if self._timeline_legend is not None:
            self._timeline_legend.setVisible(not compact)

    def _set_series_slot(self, slot_index: int, keys) -> None:
        try:
            self._timeline_series_slots.set_slot(slot_index, keys)
        except Exception as exc:
            self._log(f"Could not save timeline series: {exc}", tag="warning")

    def _apply_timeline_series_slots(self, slots) -> None:
        if self._disposed:
            return
        slots = tuple(tuple(slot) for slot in slots)
        if slots == self._series_slots:
            return
        self._series_slots = slots
        self._refresh_compare_runs_timeline_model()

    def _refresh_series_slot_buttons(self) -> None:
        for index, button in enumerate(self._series_slot_buttons):
            refresh_timeline_slot_button(
                button,
                index,
                self._series_slots[index],
            )

    def on_compare_run_slider_changed(self, side: str, value):
        vod = self._compare_run_vod(side)
        if vod is None or not vod.snapshots:
            return
        index = min(max(int(round(float(value))), 0), len(vod.snapshots) - 1)
        if self._compare_run_index(side) == index:
            return

        self._set_compare_run_index(side, index)
        if not self._syncing:
            self._syncing = True
            try:
                other_side = "b" if side == "a" else "a"
                self._sync_compare_run_to_side(other_side, side)
            finally:
                self._syncing = False

        # Two tiers, and the split is the whole point of this handler. The
        # timeline captions are one string each, so they follow the drag 1:1
        # and the slider never feels detached from its readout. Everything else
        # -- summaries, seven diff formatters, the card writes -- is coalesced
        # to the throttle's window, because a frame the user has already
        # scrubbed past is work nobody sees.
        self._refresh_compare_run_timeline_label("a")
        self._refresh_compare_run_timeline_label("b")
        self._diff_throttle.request(
            lambda: self.refresh_compare_runs_ui(changed_side=side)
        )

    def refresh_compare_runs_ui(self, *, changed_side: str | None = None):
        if self._disposed:
            return
        if changed_side in {"a", "b"} and not self._syncing:
            self._syncing = True
            try:
                self._sync_compare_run_to_side("b" if changed_side == "a" else "a", changed_side)
            finally:
                self._syncing = False

        # One repaint for the whole panel instead of one per widget written
        # below; the tab owns ~40 of them and Qt would otherwise lay out
        # between each pair.
        with batched_updates(self._tab):
            self._refresh_compare_run_side("a")
            self._refresh_compare_run_side("b")
            self._refresh_compare_runs_diff()
            self._refresh_compare_runs_selected_labels()
            self._refresh_compare_runs_chooser()
            self._refresh_compare_runs_stats_config()
            self._refresh_compare_timeline_readout()

    def _sync_compare_run_to_side(self, target_side: str, source_side: str) -> None:
        source_vod = self._compare_run_vod(source_side)
        target_vod = self._compare_run_vod(target_side)
        if source_vod is None or target_vod is None or not source_vod.snapshots or not target_vod.snapshots:
            return
        source_index = self._compare_run_index(source_side)
        if source_index is None:
            return
        source_snapshot = source_vod.snapshots[min(max(int(source_index), 0), len(source_vod.snapshots) - 1)]
        target_time = formatting._snapshot_compare_time(source_snapshot)
        if target_time is None:
            return
        target_index = self._compare_run_time_index(target_side).nearest(target_time)
        self._set_compare_run_index(target_side, target_index)
        slider = self._compare_run_slider(target_side)
        if slider is not None and slider.value() != target_index:
            slider.blockSignals(True)
            slider.setValue(target_index)
            slider.blockSignals(False)

    def _compare_run_time_index(self, side: str) -> SnapshotTimeIndex:
        """The side's snapshot time index, built once per loaded recording.

        Keyed by the vod object so a reload -- or a swap -- gets a fresh index
        rather than the previous run's times.
        """
        vod = self._compare_run_vod(side)
        cached = self._time_indexes.get(side)
        if cached is not None and cached[0] is vod:
            return cached[1]
        index = SnapshotTimeIndex.build(() if vod is None else vod.snapshots)
        self._time_indexes[side] = (vod, index)
        return index

    def _compare_run_timeline_text(self, side: str) -> str:
        vod = self._compare_run_vod(side)
        if vod is None or not vod.snapshots:
            return "Timeline: --"
        index = self._compare_run_index(side)
        index = 0 if index is None else min(max(int(index), 0), len(vod.snapshots) - 1)
        return (
            f"Timeline: {vod.snapshots[0].time_label} - {vod.snapshots[-1].time_label}"
            f" | Selected: {vod.snapshots[index].time_label}"
        )

    def _refresh_compare_run_timeline_label(self, side: str) -> None:
        """The cheap half of `_refresh_compare_run_side`, on its own.

        Split out so the slider handler can keep the caption in step with the
        drag without paying for the summary and the items view. The full
        refresh still writes the same text through the same builder, so the two
        paths cannot drift apart.
        """
        _set_text(
            self._compare_run_widget(side, "timeline_label"),
            self._compare_run_timeline_text(side),
        )

    def _refresh_compare_run_side(self, side: str) -> None:
        vod = self._compare_run_vod(side)
        status_label = self._compare_run_widget(side, "status_label")
        slider = self._compare_run_slider(side)
        timeline_label = self._compare_run_widget(side, "timeline_label")
        summary_label = self._compare_run_widget(side, "summary_label")
        if vod is None:
            _set_text(status_label, "Select a recording")
            _set_text(timeline_label, "Timeline: --")
            _set_text(summary_label, "--")
            self._refresh_overview_snapshot_table()
            if self._timeline is None:
                view = self._compare_run_items_view(side)
                if view is not None:
                    view.update((), items_text="--")
            if slider is not None:
                slider.setEnabled(False)
                slider.setMaximum(1)
                slider.setValue(0)
            return

        snapshot_count = len(vod.snapshots)
        if not snapshot_count:
            _set_text(status_label, f"{vod.metadata.name} | no snapshots")
            _set_text(timeline_label, "Timeline: --")
            _set_text(summary_label, "No snapshots")
            self._refresh_overview_snapshot_table()
            if slider is not None:
                slider.setEnabled(False)
                slider.setMaximum(1)
                slider.setValue(0)
            return

        index = self._compare_run_index(side)
        if index is None:
            index = 0
        index = min(max(int(index), 0), snapshot_count - 1)
        self._set_compare_run_index(side, index)
        snapshot = vod.snapshots[index]
        if slider is not None:
            slider.setEnabled(True)
            slider.setMaximum(max(snapshot_count - 1, 1))
            if slider.value() != index:
                slider.blockSignals(True)
                slider.setValue(index)
                slider.blockSignals(False)
        if self._timeline is None:
            _set_text(status_label, f"{vod.metadata.name} | {index + 1}/{snapshot_count}")
        else:
            _set_text(status_label, f"{vod.metadata.name} · {snapshot_count} snapshots")
        _set_text(timeline_label, self._compare_run_timeline_text(side))
        _set_text(
            summary_label,
            formatting.format_compare_run_snapshot_summary(vod, snapshot, index),
        )
        self._refresh_overview_snapshot_table()
        if self._detail_tabs is not None and self._detail_tabs.currentIndex() == 3:
            view = self._compare_run_items_view(side)
            if view is not None:
                view.update(getattr(snapshot, "items", ()))

    def _refresh_overview_snapshot_table(self) -> None:
        table = self._snapshot_comparison_table
        if table is None:
            return
        snapshot_a = self._compare_run_snapshot("a")
        snapshot_b = self._compare_run_snapshot("b")
        if self._vod_a is None or self._vod_b is None or snapshot_a is None or snapshot_b is None:
            table.set_table(MetricTable(empty_text="Select two recordings"))
            return
        table.set_table(
            formatting.build_compare_runs_snapshot_table(
                self._vod_a,
                int(self._compare_run_index("a") or 0),
                snapshot_a,
                self._vod_b,
                int(self._compare_run_index("b") or 0),
                snapshot_b,
            )
        )

    def _refresh_compare_runs_diff(self) -> None:
        vod_a = self._vod_a
        vod_b = self._vod_b
        snapshot_a = self._compare_run_snapshot("a")
        snapshot_b = self._compare_run_snapshot("b")
        if vod_a is None or vod_b is None:
            self._set_compare_runs_diff_cards("Select two recordings")
            self._refresh_compare_runs_item_details_button(False)
            return
        if snapshot_a is None or snapshot_b is None:
            self._set_compare_runs_diff_cards("Both recordings need snapshots")
            self._refresh_compare_runs_item_details_button(False)
            return
        show_items = bool(self._items_enabled)
        show_stage_summary = bool(self._stage_summary_enabled)
        show_weapons = bool(self._weapons_enabled)
        show_tomes = bool(self._tomes_enabled)
        show_chaos = bool(self._chaos_enabled)
        show_shrines = bool(self._shrines_enabled)
        show_passives = bool(self._passives_enabled)
        item_details_expanded = bool(self._item_details_expanded)
        stat_labels = tuple(self._compare_run_selected_stat_labels())
        legacy_diff_cards = self._detail_tabs is None

        # Everything that can change a formatted diff is in this key -- both
        # recordings, both indexes, which sections are on, the selected stats,
        # and the item-details toggle -- so a hit is safe without any
        # invalidation beyond replacing a recording, which clears the cache
        # outright.
        cache_key = (
            id(vod_a),
            int(self._compare_run_index("a") or 0),
            id(vod_b),
            int(self._compare_run_index("b") or 0),
            stat_labels,
            show_items,
            item_details_expanded,
            show_stage_summary,
            show_weapons,
            show_tomes,
            show_chaos,
            show_shrines,
            show_passives,
            legacy_diff_cards,
        )
        cached = self._diff_cache.get(cache_key)
        if cached is None:
            cached = (
                formatting.format_compare_runs_overview_compact_diff(
                    vod_a,
                    snapshot_a,
                    vod_b,
                    snapshot_b,
                ),
                formatting.format_compare_runs_stats_diff(
                    snapshot_a,
                    snapshot_b,
                    stat_labels=stat_labels,
                ),
                formatting.build_compare_runs_stats_table(
                    snapshot_a,
                    snapshot_b,
                    stat_labels=stat_labels,
                ),
                (
                    formatting.build_compare_runs_items_summary(
                        snapshot_a,
                        snapshot_b,
                        details_expanded=item_details_expanded,
                    )
                    if show_items
                    else "--"
                ),
                (
                    formatting.build_compare_runs_items_table(
                        snapshot_a,
                        snapshot_b,
                        details_expanded=item_details_expanded,
                    )
                    if show_items
                    else EMPTY_METRIC_TABLE
                ),
                (
                    formatting.format_compare_runs_stage_summary_diff(
                        vod_a,
                        self._compare_run_index("a"),
                        vod_b,
                        self._compare_run_index("b"),
                    )
                    if show_stage_summary and legacy_diff_cards
                    else "--"
                ),
                (
                    formatting.build_compare_runs_stages_table(
                        vod_a,
                        self._compare_run_index("a"),
                        vod_b,
                        self._compare_run_index("b"),
                    )
                    if show_stage_summary
                    else EMPTY_METRIC_TABLE
                ),
                (
                    formatting.build_compare_runs_weapons_table(snapshot_a, snapshot_b)
                    if show_weapons
                    else EMPTY_METRIC_TABLE
                ),
                (
                    formatting.build_compare_runs_tomes_table(snapshot_a, snapshot_b)
                    if show_tomes
                    else EMPTY_METRIC_TABLE
                ),
                (
                    formatting.build_compare_runs_chaos_table(snapshot_a, snapshot_b)
                    if show_chaos
                    else EMPTY_METRIC_TABLE
                ),
                (
                    formatting.build_compare_runs_shrines_table(snapshot_a, snapshot_b)
                    if show_shrines
                    else EMPTY_METRIC_TABLE
                ),
                (
                    formatting.build_compare_runs_passives_table(snapshot_a, snapshot_b)
                    if show_passives
                    else EMPTY_METRIC_TABLE
                ),
                compare_overview.build_compare_runs_axis(
                    snapshot_a,
                    snapshot_b,
                    stat_labels=stat_labels,
                ),
                compare_overview.build_compare_runs_luck_loot(snapshot_a, snapshot_b),
            )
            # The hub facts read the stage and weapon tables that were just
            # built, so they are appended rather than folded into the tuple
            # above -- and they are cached with it, because they cost a walk
            # over both.
            cached = cached + (
                compare_overview.build_hub_facts(
                    snapshot_a,
                    snapshot_b,
                    stages_table=cached[6],
                    weapons_table=cached[7],
                    enabled={
                        "items": show_items,
                        "stage_summary": show_stage_summary,
                        "weapons": show_weapons,
                    },
                ),
            )
            self._store_compare_runs_diff(cache_key, cached)
        else:
            self._diff_cache.move_to_end(cache_key)

        (
            overview_text,
            stats_text,
            stats_table,
            items_text,
            items_table,
            stage_summary_text,
            stages_table,
            weapons_table,
            tomes_table,
            chaos_table,
            shrines_table,
            passives_table,
            axis_table,
            luck_loot,
            hub_facts,
        ) = cached
        card_kwargs = dict(
            stats_text=stats_text,
            items_text=items_text,
            items_table=items_table,
            stage_summary_text=stage_summary_text,
            weapons_table=weapons_table,
            tomes_table=tomes_table,
            chaos_table=chaos_table,
            shrines_table=shrines_table,
            passives_table=passives_table,
            show_items=show_items,
            show_stage_summary=show_stage_summary,
            show_weapons=show_weapons,
            show_tomes=show_tomes,
            show_chaos=show_chaos,
            show_shrines=show_shrines,
            show_passives=show_passives,
        )
        if self._detail_tabs is not None:
            card_kwargs["stats_table"] = stats_table
            card_kwargs["stages_table"] = stages_table
            card_kwargs["axis_table"] = axis_table
            card_kwargs["luck_loot"] = luck_loot
            card_kwargs["hub_facts"] = hub_facts
        self._set_compare_runs_diff_cards(overview_text, **card_kwargs)
        self._refresh_compare_runs_item_details_button(show_items)

    def _store_compare_runs_diff(self, key, payload) -> None:
        cache = self._diff_cache
        cache[key] = payload
        cache.move_to_end(key)
        while len(cache) > COMPARE_RUN_DIFF_CACHE_SIZE:
            cache.popitem(last=False)

    def _invalidate_compare_runs_diff_cache(self) -> None:
        """Drop cached diffs and time indexes. Called when a side's vod changes.

        This is also what makes the `id(vod)` in the cache key sound: no key can
        outlive the object it identifies, so a recycled address cannot be read
        as a hit for a different recording.
        """
        self._diff_cache.clear()
        self._time_indexes.clear()

    def _set_compare_run_error(self, side: str, text: str) -> None:
        # A queued frame describes a selection that no longer exists.
        self._diff_throttle.cancel()
        self._set_compare_run_vod(side, None)
        self._set_compare_run_index(side, None)
        self._refresh_compare_run_side(side)
        error_html = f'<span style="color:#f08b72;">{text}</span>'
        _set_text(self._compare_run_widget(side, "status_label"), error_html)
        self._refresh_compare_runs_diff()
        self._refresh_compare_runs_selected_labels()

    def _report_compare_run_state(self, side: str, text: str) -> None:
        """Keep load/render status failures inside their Qt callback."""
        try:
            self._set_compare_run_error(side, text)
        except Exception as exc:
            # A malformed payload can make the normal diff renderer fail even
            # while it is trying to paint the error state. The selection has
            # already been cleared; do not let that secondary failure escape
            # the queued invoker or list-selection signal.
            self._log(
                f"Could not update Compare Runs state ({text}): {exc}",
                tag="warning",
            )
            try:
                error_html = f'<span style="color:#f08b72;">{text}</span>'
                _set_text(self._compare_run_widget(side, "status_label"), error_html)
            except RuntimeError:
                # The status widget was deleted during application teardown.
                pass

    def _refresh_compare_runs_item_details_button(self, visible: bool) -> None:
        item_details_btn = self._item_details_btn
        if item_details_btn is None:
            return
        item_details_btn.setVisible(visible)
        item_details_btn.setText(
            "Hide Item Details"
            if bool(self._item_details_expanded)
            else "Show Item Details"
        )

    def _set_compare_runs_diff_cards(
        self,
        overview_text: str,
        *,
        stats_text: str = "--",
        stats_table: MetricTable = EMPTY_METRIC_TABLE,
        items_text: str = "--",
        items_table: MetricTable = EMPTY_METRIC_TABLE,
        stage_summary_text: str = "--",
        stages_table: MetricTable = EMPTY_METRIC_TABLE,
        weapons_table: MetricTable = EMPTY_METRIC_TABLE,
        tomes_table: MetricTable = EMPTY_METRIC_TABLE,
        chaos_table: MetricTable = EMPTY_METRIC_TABLE,
        shrines_table: MetricTable = EMPTY_METRIC_TABLE,
        passives_table: MetricTable = EMPTY_METRIC_TABLE,
        axis_table=EMPTY_AXIS_TABLE,
        luck_loot=EMPTY_LUCK_LOOT,
        hub_facts: dict[str, str] | None = None,
        show_items: bool = False,
        show_stage_summary: bool = False,
        show_weapons: bool = False,
        show_tomes: bool = False,
        show_chaos: bool = False,
        show_shrines: bool = False,
        show_passives: bool = False,
    ) -> None:
        # Dirty check. Consecutive snapshots of the same run very often produce
        # an identical diff -- nothing changed in that game second -- and
        # re-writing seven widgets with the payload they already hold still
        # costs a document re-parse or a relayout each. The three tables are
        # frozen dataclasses, so they compare by value here exactly as the
        # strings beside them do.
        payload = (
            overview_text,
            stats_text,
            stats_table,
            items_text,
            items_table,
            stage_summary_text,
            stages_table,
            weapons_table,
            tomes_table,
            chaos_table,
            shrines_table,
            passives_table,
            axis_table,
            luck_loot,
            tuple(sorted((hub_facts or {}).items())),
            show_items,
            show_stage_summary,
            show_weapons,
            show_tomes,
            show_chaos,
            show_shrines,
            show_passives,
        )
        self._pending_diff_payload = payload
        self._render_active_diff_page()

    def _render_active_diff_page(self) -> None:
        payload = self._pending_diff_payload
        if payload is None:
            return
        if self._detail_tabs is None:
            # Compatibility for headless collaborators and old unit doubles.
            # The built redesign always has `_detail_tabs` and therefore takes
            # the lazy branch below.
            (
                overview_text,
                stats_text,
                _stats_table,
                items_text,
                items_table,
                stage_summary_text,
                _stages_table,
                weapons_table,
                tomes_table,
                chaos_table,
                shrines_table,
                passives_table,
                _axis_table,
                _luck_loot,
                _hub_facts,
                show_items,
                show_stage_summary,
                show_weapons,
                show_tomes,
                show_chaos,
                show_shrines,
                show_passives,
            ) = payload
            eager_payload = payload
            if self._rendered_diff_cards == eager_payload:
                return
            _set_text(self._diff_overview_label, overview_text)
            _set_text(self._diff_stats_label, stats_text)
            _set_text(self._diff_items_label, items_text)
            _set_metric_table(self._diff_items_table, items_table)
            _set_text(self._diff_stage_summary_label, stage_summary_text)
            _set_metric_table(self._diff_weapons_table, weapons_table)
            _set_metric_table(self._diff_tomes_table, tomes_table)
            _set_metric_table(self._diff_chaos_table, chaos_table)
            _set_metric_table(self._diff_shrines_table, shrines_table)
            _set_metric_table(self._diff_passives_table, passives_table)
            _set_visible(self._diff_overview_group, True)
            _set_visible(self._diff_stats_group, bool(stats_text and stats_text != "--"))
            _set_visible(self._diff_items_group, show_items)
            _set_visible(self._diff_stage_summary_group, show_stage_summary)
            _set_visible(self._diff_weapons_group, show_weapons)
            _set_visible(self._diff_tomes_group, show_tomes)
            _set_visible(self._diff_chaos_group, show_chaos)
            _set_visible(self._diff_shrines_group, show_shrines)
            _set_visible(self._diff_passives_group, show_passives)
            self._rendered_diff_cards = eager_payload
            return
        page = self._detail_tabs.currentIndex() if self._detail_tabs is not None else 0
        previous = self._rendered_diff_cards
        if previous is not None and previous[0] == page and previous[1] == payload:
            return
        (
            overview_text,
            stats_text,
            stats_table,
            items_text,
            items_table,
            stage_summary_text,
            stages_table,
            weapons_table,
            tomes_table,
            chaos_table,
            shrines_table,
            passives_table,
            axis_table,
            luck_loot,
            hub_facts,
            _show_items,
            _show_stage_summary,
            _show_weapons,
            _show_tomes,
            _show_chaos,
            _show_shrines,
            _show_passives,
        ) = payload
        if page == 0:
            # A test double can hand this class `_detail_tabs` without ever
            # running `_build_overview_page`, so the three views are checked
            # rather than assumed.
            if self._luck_loot_view is not None:
                self._luck_loot_view.set_payload(luck_loot)
            if self._axis_view is not None:
                self._axis_view.set_table(axis_table)
            if self._hub_view is not None:
                self._hub_view.set_facts(dict(hub_facts))
        elif page == 1:
            self._stats_source_table = stats_table
            self._render_filtered_stats()
        elif page == 2:
            _set_metric_table(self._diff_stages_table, stages_table)
        elif page == 3:
            _set_text(self._diff_items_label, items_text)
            _set_metric_table(self._diff_items_table, items_table)
            for side in ("a", "b"):
                snapshot = self._compare_run_snapshot(side)
                view = self._compare_run_items_view(side)
                if view is not None:
                    view.update(getattr(snapshot, "items", ()) if snapshot is not None else ())
        elif page == 4:
            _set_metric_table(self._diff_weapons_table, weapons_table)
        elif page == 5:
            _set_metric_table(self._diff_tomes_table, tomes_table)
        elif page == 6:
            _set_metric_table(self._diff_chaos_table, chaos_table)
        elif page == 7:
            _set_metric_table(self._diff_shrines_table, shrines_table)
        elif page == 8:
            _set_metric_table(self._diff_passives_table, passives_table)
        self._rendered_diff_cards = (page, payload)

    def _render_filtered_stats(self) -> None:
        if self._stats_table is None:
            return
        table = _filter_metric_table(self._stats_source_table, self._stats_query)
        self._stats_table.set_table(table)

    def _on_stats_filter_changed(self) -> None:
        self._stats_query = self._stats_search.text() if self._stats_search is not None else ""
        self._rendered_diff_cards = None
        self._render_filtered_stats()

    def _on_detail_tab_changed(self, index: int) -> None:
        self._active_diff_page = int(index)
        self._rendered_diff_cards = None
        self._render_active_diff_page()

    def _refresh_compare_runs_chooser(self) -> None:
        expanded = bool(self._chooser_expanded)
        chooser = self._chooser_group
        button = self._select_btn
        swap_btn = self._swap_btn
        if chooser is not None:
            chooser.setVisible(expanded)
        stack = self._workspace_stack
        workspace_page = self._workspace_page
        chooser_page = self._chooser_page
        if stack is not None and workspace_page is not None and chooser_page is not None:
            target = chooser_page if expanded else workspace_page
            if stack.currentWidget() is not target:
                stack.setCurrentWidget(target)
        change_buttons = tuple(
            candidate
            for candidate in (self._run_a_change_btn, self._run_b_change_btn)
            if candidate is not None
        )
        if change_buttons:
            for change_button in change_buttons:
                change_button.setText("Done" if expanded else "Change")
                change_button.setToolTip(
                    "Hide recording library" if expanded else "Choose a recording"
                )
        elif button is not None:
            button.setText("Done" if expanded else "Select Runs")
        if swap_btn is not None:
            swap_btn.setEnabled(self._vod_a is not None or self._vod_b is not None)

    def _refresh_compare_runs_stats_config(self) -> None:
        expanded = bool(self._stats_config_expanded)
        group = self._stats_config_group
        button = self._stats_config_btn
        if group is not None:
            group.setVisible(expanded)
        if button is not None:
            button.setText("Hide stats" if expanded else "Choose stats")

    def _refresh_compare_runs_selected_labels(self) -> None:
        _set_text(
            self._run_a_selected_label,
            self._compare_run_selected_text("a"),
        )
        _set_text(
            self._run_b_selected_label,
            self._compare_run_selected_text("b"),
        )

    def _compare_run_selected_text(self, side: str) -> str:
        vod = self._compare_run_vod(side)
        if vod is None:
            return "--"
        snapshot_count = len(vod.snapshots)
        return f"{vod.metadata.name} · {snapshot_count} snapshots"

    def _save_compare_run_stat_selection(self) -> None:
        self._save_compare_run_config_value(
            "selected comparison stats",
            COMPARE_RUN_STAT_CONFIG_KEY,
            list(self._compare_run_checked_stat_labels()),
        )

    def _save_compare_run_sections(self) -> None:
        self._save_compare_run_config_value(
            "comparison sections",
            COMPARE_RUN_SECTIONS_CONFIG_KEY,
            self._compare_run_checked_sections(),
        )

    def _compare_run_checked_sections(self) -> dict[str, bool]:
        return {
            "items": bool(_checkbox_checked(self._items_checkbox)),
            "stage_summary": bool(
                _checkbox_checked(self._stage_summary_checkbox)
            ),
            "weapons": bool(_checkbox_checked(self._weapons_checkbox)),
            "tomes": bool(_checkbox_checked(self._tomes_checkbox)),
            "chaos": bool(_checkbox_checked(self._chaos_checkbox)),
            "shrines": bool(_checkbox_checked(self._shrines_checkbox)),
            "passives": bool(_checkbox_checked(self._passives_checkbox)),
        }

    def _compare_run_checked_stat_labels(self) -> tuple[str, ...]:
        checkboxes = self._stat_checkboxes or {}
        return tuple(label for label, checkbox in checkboxes.items() if checkbox.isChecked())

    def _compare_run_selected_stat_labels(self) -> tuple[str, ...]:
        checkboxes = self._stat_checkboxes or {}
        if not checkboxes:
            return configured_compare_run_stat_labels()
        selected = self._compare_run_checked_stat_labels()
        return selected or default_compare_run_stat_labels()

    def _compare_run_vod(self, side: str):
        return self._vod_a if side == "a" else self._vod_b

    def _set_compare_run_vod(self, side: str, vod) -> None:
        if self._compare_run_vod(side) is not vod:
            self._invalidate_compare_runs_diff_cache()
        if side == "a":
            self._vod_a = vod
        else:
            self._vod_b = vod
        self._refresh_compare_runs_timeline_model()

    def _compare_run_index(self, side: str) -> int | None:
        return self._index_a if side == "a" else self._index_b

    def _set_compare_run_index(self, side: str, index: int | None) -> None:
        if side == "a":
            self._index_a = index
        else:
            self._index_b = index

    def _compare_run_snapshot(self, side: str):
        vod = self._compare_run_vod(side)
        index = self._compare_run_index(side)
        if vod is None or not vod.snapshots or index is None:
            return None
        index = min(max(int(index), 0), len(vod.snapshots) - 1)
        return vod.snapshots[index]

    def _compare_run_widget(self, side: str, widget_name: str):
        prefix = f"_run_{side}_"
        return getattr(self, f"{prefix}{widget_name}", None)

    def _compare_run_slider(self, side: str):
        return self._compare_run_widget(side, "slider")

    def _build_legacy(self):
        """Create the tab's widgets and add it to the tab bar.

        Moved here from `gui_layout` by step 21d. `gui_layout` was building
        this tab's ~40 widgets onto the shared `self` while the tab's own
        module read them back off it -- the coupling step 9 left visible across
        a file boundary. Moving the construction is what closes it, and it also
        retires the `ItemsSectionView` import that had to sit inside a method
        body down there to avoid the
        `gui_layout -> ui.tabs.player_stats -> live_stats -> gui_layout` cycle,
        which the old comment names as a symptom of the panel being built there
        at all.

        Separate from `__init__`, matching `LiveStatsTab` and `RecordingsTab`.
        """
        self._tab = QWidget()
        compare_layout = QVBoxLayout(self._tab)

        selected_row = QHBoxLayout()
        self._select_btn = QPushButton("Select Runs")
        self._select_btn.setProperty("class", "CompareRunsGhostButton")
        self._select_btn.clicked.connect(self.toggle_compare_runs_chooser)
        self._swap_btn = QPushButton("Swap")
        self._swap_btn.setProperty("class", "CompareRunsGhostButton")
        self._swap_btn.clicked.connect(self.swap_compare_runs)
        self._stats_config_btn = QPushButton("Compare Settings")
        self._stats_config_btn.setProperty("class", "CompareRunsGhostButton")
        self._stats_config_btn.clicked.connect(self.toggle_compare_runs_stats_config)
        selected_row.addStretch(1)
        selected_row.addWidget(self._select_btn)
        selected_row.addWidget(self._swap_btn)
        selected_row.addWidget(self._stats_config_btn)
        compare_layout.addLayout(selected_row)

        self._chooser_group = QGroupBox("Select Recordings")
        self._chooser_group.setVisible(False)
        chooser_layout = QVBoxLayout(self._chooser_group)
        selector_grid = QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(8)
        selector_grid.setVerticalSpacing(6)
        selector_grid.addWidget(QLabel("Run A"), 0, 0)
        selector_grid.addWidget(QLabel("Run B"), 0, 1)
        self._run_a_list_frame = QListWidget()
        self._run_b_list_frame = QListWidget()
        for list_frame in (self._run_a_list_frame, self._run_b_list_frame):
            list_frame.setMinimumHeight(230)
            list_frame.setMaximumHeight(320)
        self._run_a_list_frame.currentItemChanged.connect(
            lambda current, _previous: self._on_compare_run_selection_changed("a", current)
        )
        self._run_b_list_frame.currentItemChanged.connect(
            lambda current, _previous: self._on_compare_run_selection_changed("b", current)
        )
        selector_grid.addWidget(self._run_a_list_frame, 1, 0)
        selector_grid.addWidget(self._run_b_list_frame, 1, 1)
        selector_grid.setColumnStretch(0, 1)
        selector_grid.setColumnStretch(1, 1)
        chooser_layout.addLayout(selector_grid)
        compare_layout.addWidget(self._chooser_group)

        self._stats_config_group = QGroupBox("Compare Settings")
        self._stats_config_group.setVisible(False)
        settings_layout = QVBoxLayout(self._stats_config_group)
        section_layout = QHBoxLayout()
        # Read once in `__init__` and kept, so the checkboxes and the
        # enabled flags cannot disagree about what was configured.
        configured_sections = self._configured_sections()
        self._items_checkbox = QCheckBox("Items")
        self._items_checkbox.setChecked(configured_sections["items"])
        self._items_checkbox.stateChanged.connect(lambda _state: self.on_compare_run_section_selection_changed())
        self._stage_summary_checkbox = QCheckBox("Stage Summary")
        self._stage_summary_checkbox.setChecked(configured_sections["stage_summary"])
        self._stage_summary_checkbox.stateChanged.connect(
            lambda _state: self.on_compare_run_section_selection_changed()
        )
        self._weapons_checkbox = QCheckBox("Weapons")
        self._weapons_checkbox.setChecked(configured_sections["weapons"])
        self._weapons_checkbox.stateChanged.connect(lambda _state: self.on_compare_run_section_selection_changed())
        self._tomes_checkbox = QCheckBox("Tomes")
        self._tomes_checkbox.setChecked(configured_sections["tomes"])
        self._tomes_checkbox.stateChanged.connect(lambda _state: self.on_compare_run_section_selection_changed())
        self._chaos_checkbox = QCheckBox("Chaos")
        self._chaos_checkbox.setChecked(configured_sections["chaos"])
        self._chaos_checkbox.stateChanged.connect(lambda _state: self.on_compare_run_section_selection_changed())
        self._shrines_checkbox = QCheckBox("Shrines")
        self._shrines_checkbox.setChecked(configured_sections["shrines"])
        self._shrines_checkbox.stateChanged.connect(
            lambda _state: self.on_compare_run_section_selection_changed()
        )
        self._passives_checkbox = QCheckBox("Passives")
        self._passives_checkbox.setChecked(configured_sections["passives"])
        self._passives_checkbox.stateChanged.connect(
            lambda _state: self.on_compare_run_section_selection_changed()
        )
        section_layout.addWidget(QLabel("Show in Difference:"))
        section_layout.addWidget(self._stage_summary_checkbox)
        section_layout.addWidget(self._items_checkbox)
        section_layout.addWidget(self._weapons_checkbox)
        section_layout.addWidget(self._tomes_checkbox)
        section_layout.addWidget(self._chaos_checkbox)
        section_layout.addWidget(self._shrines_checkbox)
        section_layout.addWidget(self._passives_checkbox)
        section_layout.addStretch(1)
        settings_layout.addLayout(section_layout)

        settings_scroll, _settings_scroll_content, settings_scroll_layout = _make_scroll_section()
        settings_scroll.setMinimumHeight(150)
        settings_scroll.setMaximumHeight(240)

        stats_config_layout = QGridLayout()
        stats_config_layout.setContentsMargins(8, 8, 8, 8)
        stats_config_layout.setHorizontalSpacing(12)
        stats_config_layout.setVerticalSpacing(4)
        self._stat_checkboxes = {}
        stat_specs = [spec for group in PLAYER_STAT_GROUPS for spec in group]
        selected_defaults = set(configured_compare_run_stat_labels())
        for index, spec in enumerate(stat_specs):
            checkbox = QCheckBox(spec.label)
            checkbox.setChecked(spec.label in selected_defaults)
            checkbox.stateChanged.connect(lambda _state: self.on_compare_run_stat_selection_changed())
            self._stat_checkboxes[spec.label] = checkbox
            stats_config_layout.addWidget(checkbox, index // 4, index % 4)
        for column in range(4):
            stats_config_layout.setColumnStretch(column, 1)
        stats_group = QGroupBox("Stats Selector")
        stats_group.setLayout(stats_config_layout)
        settings_scroll_layout.addWidget(stats_group)
        settings_scroll_layout.addStretch(1)
        settings_layout.addWidget(settings_scroll)
        compare_layout.addWidget(self._stats_config_group)

        body_layout = QHBoxLayout()
        body_layout.setSpacing(8)
        run_a_group, self._run_a_status_label, self._run_a_slider, self._run_a_timeline_label, self._run_a_summary_label = self._build_side_panel(
            "Run A",
            "a",
        )
        diff_group = QGroupBox("Difference")
        diff_layout = QVBoxLayout(diff_group)
        diff_scroll, _diff_scroll_content, diff_scroll_layout = _make_scroll_section()
        self._diff_overview_group, self._diff_overview_label = self._build_diff_card(
            "Overview",
            "Select two recordings",
        )
        self._diff_stats_group, self._diff_stats_label = self._build_diff_card(
            "Stats",
            "--",
        )
        self._diff_items_group, self._diff_items_label = self._build_diff_card(
            "Items",
            "--",
        )
        # The card is a summary line plus, when expanded, a per-item table. The
        # table is the widget-rendered half for the same reason the three cards
        # below are: as `<table>` markup it was 19 KB and 70 ms of layout per
        # frame -- the most expensive card of the seven.
        self._diff_items_table = MetricTableView()
        self._diff_items_group.layout().addWidget(self._diff_items_table)
        self._item_details_btn = QPushButton("Show Item Details")
        self._item_details_btn.setProperty("class", "SmallGhostButton")
        self._item_details_btn.clicked.connect(self.toggle_compare_runs_item_details)
        self._item_details_btn.setVisible(False)
        self._diff_items_group.layout().addWidget(self._item_details_btn, 0, Qt.AlignLeft)
        self._diff_stage_summary_group, self._diff_stage_summary_label = self._build_diff_card(
            "Stage Summary",
            "--",
        )
        # The three heavy cards are widget-rendered rather than rich text. As
        # `QLabel` documents they cost 63/23/65 ms of layout per scrub frame
        # against 0.26 ms for the whole Python half of that frame; see
        # `ui/metric_table.py` for the renderer comparison behind the choice.
        self._diff_weapons_group, self._diff_weapons_table = self._build_diff_table_card("Weapons")
        self._diff_tomes_group, self._diff_tomes_table = self._build_diff_table_card("Tomes")
        self._diff_chaos_group, self._diff_chaos_table = self._build_diff_table_card("Chaos")
        self._diff_shrines_group, self._diff_shrines_table = self._build_diff_table_card("Shrines")
        self._diff_passives_group, self._diff_passives_table = self._build_diff_table_card("Passives")
        diff_scroll_layout.addWidget(self._diff_overview_group)
        diff_scroll_layout.addWidget(self._diff_stats_group)
        diff_scroll_layout.addWidget(self._diff_stage_summary_group)
        diff_scroll_layout.addWidget(self._diff_items_group)
        diff_scroll_layout.addWidget(self._diff_weapons_group)
        diff_scroll_layout.addWidget(self._diff_tomes_group)
        diff_scroll_layout.addWidget(self._diff_chaos_group)
        diff_scroll_layout.addWidget(self._diff_shrines_group)
        diff_scroll_layout.addWidget(self._diff_passives_group)
        diff_scroll_layout.addStretch(1)
        diff_layout.addWidget(diff_scroll, 1)
        run_b_group, self._run_b_status_label, self._run_b_slider, self._run_b_timeline_label, self._run_b_summary_label = self._build_side_panel(
            "Run B",
            "b",
        )
        body_layout.addWidget(run_a_group, 3)
        body_layout.addWidget(diff_group, 4)
        body_layout.addWidget(run_b_group, 3)
        compare_layout.addLayout(body_layout, 1)
        # The diff cards above are brand new widgets holding their initial
        # captions, so whatever the dirty check last saw was written to widgets
        # that no longer exist.
        self._rendered_diff_cards = None
        self._tabview.addTab(self._tab, "Compare Runs")

    def _build_diff_card(self, title: str, initial_text: str):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        label = QLabel(initial_text)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        _apply_summary_label_padding(label)
        layout.addWidget(label)
        return group, label

    def _build_diff_table_card(self, title: str):
        """A diff card whose body is a restyled four-column comparison table."""
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        view = MetricTableView()
        layout.addWidget(view)
        return group, view

    def _build_side_panel(self, title: str, side: str):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        status_label = QLabel("Select a recording")
        status_label.setTextFormat(Qt.RichText)
        status_label.setWordWrap(True)
        slider = QSlider(Qt.Horizontal)
        slider.setEnabled(False)
        slider.valueChanged.connect(lambda value, run_side=side: self.on_compare_run_slider_changed(run_side, value))
        timeline_label = QLabel("Timeline: --")
        summary_label = QLabel("--")
        summary_label.setTextFormat(Qt.RichText)
        summary_label.setWordWrap(True)
        _apply_summary_label_padding(status_label, timeline_label, summary_label)
        layout.addWidget(status_label)
        layout.addWidget(slider)
        layout.addWidget(timeline_label)
        summary_group = QGroupBox("Snapshot")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.addWidget(summary_label)
        items_group = QGroupBox("Items")
        items_layout = QVBoxLayout(items_group)
        items_label = QLabel("--")
        items_label.setTextFormat(Qt.RichText)
        items_label.setWordWrap(True)
        items_layout.addWidget(items_label)
        items_actions = QHBoxLayout()
        items_toggle_btn = QPushButton("Show all")
        items_toggle_btn.setProperty("class", "SmallGhostButton")
        items_toggle_btn.clicked.connect(lambda _checked=False, run_side=side: self.toggle_compare_run_items_expanded(run_side))
        items_toggle_btn.setVisible(False)
        items_rarity_label = QLabel("")
        items_rarity_label.setTextFormat(Qt.RichText)
        items_rarity_label.setStyleSheet("font-size: 14px; background: transparent;")
        items_rarity_label.setVisible(False)
        items_sort_combo = QComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            items_sort_combo.addItem(label, mode)
        rarity_desc_index = items_sort_combo.findData("rarity_desc")
        if rarity_desc_index >= 0:
            items_sort_combo.setCurrentIndex(rarity_desc_index)
        # One ordinary ItemsSectionView per compare side. The module-scope
        # import is fine from here; it was a method-body import in `gui_layout`
        # only because building this panel there closed an import cycle.
        items_view = ItemsSectionView(
            group=items_group,
            label=items_label,
            rarity_label=items_rarity_label,
            toggle_btn=items_toggle_btn,
            sort_combo=items_sort_combo,
            initial_sort_mode=ITEM_SORT_RARITY_DESC,
        )
        setattr(self, f"_run_{side}_items_view", items_view)
        items_sort_combo.currentIndexChanged.connect(
            lambda _index, view=items_view: view.on_sort_changed()
        )
        items_actions.addWidget(items_toggle_btn, 0, Qt.AlignLeft)
        items_actions.addWidget(items_rarity_label, 0, Qt.AlignLeft)
        items_actions.addStretch(1)
        items_actions.addWidget(QLabel("Sort:"))
        items_actions.addWidget(items_sort_combo)
        items_layout.addLayout(items_actions)
        layout.addWidget(summary_group)
        layout.addWidget(items_group)
        layout.addStretch(1)
        return group, status_label, slider, timeline_label, summary_label

    def build(self):
        """Put the tab in the bar. Its contents wait until someone opens it.

        This tab is 741 widgets -- more than a third of the whole window -- and
        every launch paid for them whether or not the tab was ever opened.
        Measured, that is about 20 MB and most of the two seconds the window
        took to build.

        Deferring it is safe because nothing outside reaches in unless this tab
        is the active one: the router gates `refresh_compare_runs_list` and
        `ensure_compare_runs_chooser_for_empty_selection` on
        `is_compare_runs_tab_active`, and by then the page has been shown. The
        one ungated caller, `invalidate_compare_runs_list`, touches no widget.
        Every widget attribute is already declared `None` in `__init__`, and
        the readers already treat that as "not built" -- see
        `refresh_compare_runs_list`, which returns on it, and
        `_compare_runs_sort_mode`, which falls back to the saved order.
        """
        self._tab = StagedLoadingPage(
            self._build_workspace,
            object_prefix="CompareRuns",
            # Run A is blue and Run B is purple everywhere else in this tab.
            spinner_colors=("#38BDF8", "#C084FC"),
        )
        self._disposed = False
        self._tab.destroyed.connect(self._on_tab_destroyed)
        self._tab.setObjectName("CompareRunsPage")
        self._tabview.addTab(self._tab, "Compare Runs")

    def _on_tab_destroyed(self, _object=None) -> None:
        """Invalidate trailing work without touching widgets being destroyed."""
        self._disposed = True
        self._load_generations = {
            side: int(self._load_generations.get(side, 0)) + 1
            for side in ("a", "b")
        }
        self._diff_throttle.cancel()

    def build_now(self) -> None:
        """Build the contents without waiting for a show. For tests."""
        if self._tab is not None:
            self._tab.build_now()

    def _build_workspace(self, workspace):
        """Build the timeline-first workspace in short GUI-thread stages."""
        compare_layout = QVBoxLayout(workspace)
        compare_layout.setContentsMargins(8, 8, 8, 8)
        compare_layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        plaque_a, self._run_a_status_label = self._build_run_plaque("a")
        plaque_b, self._run_b_status_label = self._build_run_plaque("b")
        self._select_btn = self._run_a_change_btn
        self._swap_btn = QPushButton("Swap")
        self._swap_btn.setObjectName("CompareRunsSwapButton")
        self._swap_btn.clicked.connect(self.swap_compare_runs)
        # The direction governs all seven tabs and the timeline legend, so it is
        # stated once, here, rather than repeated per card -- and it sits on
        # `Swap`, which is the control that reverses it.
        self._swap_btn.setToolTip("Swap A and B, reversing every delta")
        direction = QLabel("Δ = A − B")
        direction.setObjectName("CompareRunsDeltaDirection")
        direction.setToolTip(
            "Every delta compares run A to run B, so a positive number means run A has more"
        )
        direction.setAlignment(Qt.AlignCenter)
        swap_column = QVBoxLayout()
        swap_column.setSpacing(2)
        swap_column.addWidget(self._swap_btn, 0, Qt.AlignHCenter)
        swap_column.addWidget(direction, 0, Qt.AlignHCenter)
        header.addWidget(plaque_a, 1)
        header.addLayout(swap_column)
        header.addWidget(plaque_b, 1)
        compare_layout.addLayout(header)
        yield None

        self._workspace_stack = QStackedWidget()
        self._workspace_stack.setObjectName("CompareRunsWorkspaceStack")
        compare_layout.addWidget(self._workspace_stack, 1)

        self._workspace_page = QWidget()
        self._workspace_page.setObjectName("CompareRunsWorkspacePage")
        workspace_layout = QVBoxLayout(self._workspace_page)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(10)
        self._workspace_stack.addWidget(self._workspace_page)
        self._workspace_stack.setCurrentWidget(self._workspace_page)
        yield None

        self._build_stats_selector(workspace_layout)
        yield None

        timeline_card = QGroupBox("Timeline")
        timeline_card.setObjectName("CompareRunsTimelineCard")
        timeline_layout = QVBoxLayout(timeline_card)
        # The stylesheet's `QGroupBox` padding already insets the card, so the
        # layout adds none of its own -- doubling them pushed the track in.
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        # The controls have to sit on the track, not float above it -- the
        # series pickers name the curves directly below them.
        timeline_layout.setSpacing(2)

        timeline_series_row = QHBoxLayout()
        timeline_series_row.setSpacing(6)
        for index in range(4):
            button = QPushButton()
            button.setObjectName("CompareRunsSeriesSlot")
            button.setProperty("slotIndex", index)
            button.setProperty("timelineSlot", True)
            button.setMenu(
                build_timeline_series_menu(
                    button,
                    index,
                    self._set_series_slot,
                )
            )
            self._series_slot_buttons.append(button)
            timeline_series_row.addWidget(button)

        # Beside the slots, because they answer the same question -- what is
        # drawn on the track -- but as checkboxes rather than slots, because a
        # cap is a reference line the game imposes, not one of the four series
        # the user is spending slots on. Built by the shared helper so the
        # Recordings scrubber offers the identical control.
        self._cap_checkboxes = build_timeline_cap_checkboxes(
            self.on_compare_run_caps_changed
        )
        for checkbox in self._cap_checkboxes.values():
            timeline_series_row.addWidget(checkbox)
        timeline_series_row.addStretch(1)

        # A switch, not a push button, and on the title row rather than at the
        # end of the series slots. It is the same "change how much of this you
        # see" control as `Expanded` on Live Stats and Recordings, so it uses
        # the same widget; and it belongs beside the readout it resizes, not in
        # a row of series pickers it has nothing to do with.
        self._compact_timeline_btn = LabeledSwitch("Compact")
        self._compact_timeline_btn.setObjectName("CompareRunsCompactTimeline")
        self._compact_timeline_btn.setProperty("timelineCompact", True)
        self._compact_timeline_btn.setChecked(self._timeline_compact)
        self._compact_timeline_btn.setToolTip(
            "Collapse the timeline into a compact overview strip"
        )
        self._compact_timeline_btn.toggled.connect(self._set_timeline_compact)
        # The name rides the frame, not a row of its own: it is the card's
        # title, and every other titled card on this tab -- Item differences,
        # Stage comparison, both inventories -- already puts it there. That
        # leaves one control row above the track instead of two.
        self._timeline_position_label = QLabel("A -- · B --")
        self._timeline_position_label.setObjectName("CompareRunsTimelinePosition")
        self._timeline_position_label.setProperty("timelinePosition", True)
        self._timeline_position_label.setTextFormat(Qt.RichText)
        timeline_series_row.addWidget(self._compact_timeline_btn, 0, Qt.AlignVCenter)
        timeline_series_row.addWidget(self._timeline_position_label, 0, Qt.AlignVCenter)
        timeline_layout.addLayout(timeline_series_row)

        self._timeline = CompareRunsTimeline()
        if self._uses_default_diff_throttle:
            # A trailing diff render writes most of the tab. Tie its QTimer to
            # the timeline so Qt cancels it with the page during teardown.
            self._diff_throttle.cancel()
            self._diff_throttle = UiUpdateThrottle(qt_context=self._timeline)
        self._timeline.set_compact(self._timeline_compact)
        self._timeline.positionChanged.connect(self.on_compare_timeline_position_changed)
        timeline_layout.addWidget(self._timeline)
        self._timeline_legend = CompareRunsTimelineLegend()
        # Parent first, then show. `setVisible(True)` on a widget that has no
        # parent yet makes it a top-level window, so building the UI flashed a
        # stray frame on screen -- which is exactly what
        # `test_building_the_ui_shows_no_window_of_its_own` catches. It only
        # reproduced with the compact timeline switched off, because that is
        # the branch that passes `True`.
        timeline_layout.addWidget(self._timeline_legend)
        self._timeline_legend.setVisible(not self._timeline_compact)
        workspace_layout.addWidget(timeline_card)
        yield None

        self._detail_tabs = FullWidthTabWidget()
        self._detail_tabs.setObjectName("CompareRunsTabs")
        self._detail_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        workspace_layout.addWidget(self._detail_tabs, 1)
        yield None

        yield from self._build_overview_page_steps()
        self._build_stats_page()
        yield None
        self._build_stages_page()
        yield None
        self._build_items_page()
        yield None
        self._build_table_page("Weapons", "_diff_weapons_group", "_diff_weapons_table")
        self._build_table_page("Tomes", "_diff_tomes_group", "_diff_tomes_table")
        yield None
        self._build_table_page("Chaos", "_diff_chaos_group", "_diff_chaos_table")
        self._build_table_page("Shrines", "_diff_shrines_group", "_diff_shrines_table")
        yield None
        self._build_table_page("Passives", "_diff_passives_group", "_diff_passives_table")
        self._detail_tabs.currentChanged.connect(self._on_detail_tab_changed)
        yield None

        self._chooser_page = QWidget()
        self._chooser_page.setObjectName("CompareRunsChooserPage")
        chooser_page_layout = QVBoxLayout(self._chooser_page)
        chooser_page_layout.setContentsMargins(0, 0, 0, 0)
        chooser_page_layout.setSpacing(0)
        self._workspace_stack.addWidget(self._chooser_page)
        self._build_chooser(chooser_page_layout)
        yield None

        self._run_a_slider = None
        self._run_b_slider = None
        self._run_a_timeline_label = None
        self._run_b_timeline_label = None
        self._run_a_selected_label = self._run_a_status_label
        self._run_b_selected_label = self._run_b_status_label
        self._rendered_diff_cards = None
        self._refresh_series_slot_buttons()
        self._refresh_compare_runs_timeline_model()
        # The list was not painted while there was nothing to paint into, and
        # the signature says "painted" only because it starts as `None`. A tab
        # opened for the first time must find its library, not an empty column.
        self._list_signature = None
        # Each recording renders twice, once per chooser side. Batch the rows so
        # a large library cannot freeze the A/B loading ring for the whole pass.
        yield from self._refresh_compare_runs_list_steps(batch_size=8)
        self.refresh_compare_runs_ui()

    def _build_run_plaque(self, side: str):
        plaque = QFrame()
        plaque.setObjectName("CompareRunsRunPlaque")
        plaque.setProperty("side", side.upper())
        layout = QHBoxLayout(plaque)
        layout.setContentsMargins(11, 8, 9, 8)
        layout.setSpacing(8)
        badge = QLabel(side.upper())
        badge.setObjectName("CompareRunsRunBadge")
        badge.setProperty("side", side.upper())
        label = QLabel("Select a recording")
        label.setObjectName("CompareRunsRunName")
        label.setTextFormat(Qt.RichText)
        change = QPushButton("Change")
        change.setObjectName("CompareRunsChangeButton")
        change.setProperty("side", side.upper())
        change.setToolTip("Choose a recording")
        change.clicked.connect(self.toggle_compare_runs_chooser)
        setattr(self, f"_run_{side}_change_btn", change)
        layout.addWidget(badge)
        layout.addWidget(label, 1)
        layout.addWidget(change)
        return plaque, label

    def _build_chooser(self, parent_layout: QVBoxLayout) -> None:
        self._chooser_group = QGroupBox("Recording library")
        self._chooser_group.setObjectName("CompareRunsChooser")
        self._chooser_group.setVisible(False)
        chooser_layout = QGridLayout(self._chooser_group)
        chooser_layout.setContentsMargins(10, 12, 10, 10)
        chooser_layout.setHorizontalSpacing(10)
        chooser_layout.setVerticalSpacing(7)
        for column, side in enumerate(("a", "b")):
            title = QLabel(f"Run {side.upper()}")
            title.setObjectName("CompareRunsChooserTitle")
            title.setProperty("side", side.upper())
            search = QLineEdit()
            search.setObjectName("CompareRunsChooserSearch")
            search.setPlaceholderText("Search recordings…")
            setattr(self, f"_run_{side}_search", search)
            list_frame = QListWidget()
            list_frame.setObjectName("CompareRunsRecordingList")
            list_frame.setProperty("side", side.upper())
            list_frame.setMinimumHeight(320)
            list_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            setattr(self, f"_run_{side}_list_frame", list_frame)
            search.textChanged.connect(lambda _text, run_side=side: self._filter_compare_run_list(run_side))
            list_frame.currentItemChanged.connect(
                lambda current, _previous, run_side=side:
                self._on_compare_run_selection_changed(run_side, current)
            )
            chooser_layout.addWidget(title, 1, column)
            chooser_layout.addWidget(search, 2, column)
            chooser_layout.addWidget(list_frame, 3, column)
            chooser_layout.setColumnStretch(column, 1)
        # One combo above both columns, not one per side. These are two views
        # of the same library, and hunting the same recording in two different
        # orders is harder than hunting it in one.
        self._sort_combo = QComboBox()
        self._sort_combo.setObjectName("CompareRunsSortCombo")
        for mode, label in RECORDING_SORT_LABELS.items():
            self._sort_combo.addItem(label, mode)
        saved_index = self._sort_combo.findData(recording_sort_mode())
        if saved_index >= 0:
            self._sort_combo.setCurrentIndex(saved_index)
        self._sort_combo.currentIndexChanged.connect(self.on_compare_runs_sort_changed)
        chooser_layout.addWidget(self._sort_combo, 0, 0, 1, 2, Qt.AlignRight)
        chooser_layout.setRowStretch(3, 1)
        parent_layout.addWidget(self._chooser_group, 1)

    def _build_stats_selector(self, parent_layout: QVBoxLayout) -> None:
        self._stats_config_group = QGroupBox("Choose Stats")
        self._stats_config_group.setObjectName("CompareRunsStatsSelector")
        self._stats_config_group.setVisible(False)
        layout = QGridLayout(self._stats_config_group)
        layout.setContentsMargins(10, 10, 10, 10)
        self._stat_checkboxes = {}
        specs = [spec for group in PLAYER_STAT_GROUPS for spec in group]
        selected = set(configured_compare_run_stat_labels())
        for index, spec in enumerate(specs):
            checkbox = QCheckBox(spec.label)
            checkbox.setChecked(spec.label in selected)
            checkbox.stateChanged.connect(
                lambda _state: self.on_compare_run_stat_selection_changed()
            )
            self._stat_checkboxes[spec.label] = checkbox
            layout.addWidget(checkbox, index // 4, index % 4)
        parent_layout.addWidget(self._stats_config_group)

    def _new_scroll_page(self):
        page = QWidget()
        page.setObjectName("CompareRunsTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        scroll, content, content_layout = _make_scroll_section()
        scroll.setObjectName("CompareRunsPageScroll")
        layout.addWidget(scroll)
        return page, content, content_layout

    def _build_overview_page(self) -> None:
        for _step in self._build_overview_page_steps():
            pass

    def _build_overview_page_steps(self):
        """Luck &amp; Loot, then the axis, then three ways out.

        What this replaced was a three-line verdict beside a six-row snapshot
        table with a fifth of the width left as an empty stretch, and both
        halves repeated the four numbers the run plaques and the timeline
        legend had already shown. The axis answers a question none of them
        did -- *where* the runs diverge -- and it names its leader per row, so
        the page carries no delta sign of its own.
        """
        page, _content, layout = self._new_scroll_page()
        self._luck_loot_view = CompareRunsLuckLootView()
        layout.addWidget(self._luck_loot_view)
        yield None
        self._axis_view = CompareRunsAxisView()
        layout.addWidget(self._axis_view)
        yield None
        self._hub_view = CompareRunsHubView(("Stages", "Items", "Weapons"))
        self._hub_view.jumpRequested.connect(self._jump_to_page)
        layout.addWidget(self._hub_view)
        layout.addStretch(1)

        # The legacy build path and the headless doubles still write these; the
        # redesigned page has no widget for either, and `_render_active_diff_page`
        # only touches them when `_detail_tabs` is absent.
        self._diff_overview_group = page
        self._diff_overview_label = None
        self._snapshot_comparison_table = None
        self._run_a_summary_label = None
        self._run_b_summary_label = None
        self._detail_tabs.addTab(page, "Overview")

    def _jump_to_page(self, title: str) -> None:
        """Hub tiles name their target, so a reordered tab bar cannot mis-jump."""
        tabs = self._detail_tabs
        if tabs is None:
            return
        for index in range(tabs.count()):
            if tabs.tabText(index) == title:
                tabs.setCurrentIndex(index)
                return

    def _build_stats_page(self) -> None:
        page = QWidget()
        page.setObjectName("CompareRunsTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        toolbar = QHBoxLayout()
        self._stats_search = QLineEdit()
        self._stats_search.setObjectName("CompareRunsStatsSearch")
        self._stats_search.setPlaceholderText("Search stats…")
        choose = QPushButton("Choose stats")
        choose.setObjectName("CompareRunsChooseStats")
        choose.clicked.connect(self.toggle_compare_runs_stats_config)
        self._stats_search.textChanged.connect(lambda _text: self._on_stats_filter_changed())
        toolbar.addWidget(self._stats_search, 1)
        toolbar.addWidget(choose)
        layout.addLayout(toolbar)
        scroll, _content, content_layout = _make_scroll_section()
        self._stats_table = MetricTableView()
        self._stats_table.setObjectName("CompareRunsStatsTable")
        content_layout.addWidget(self._stats_table)
        content_layout.addStretch(1)
        layout.addWidget(scroll)
        # Compatibility attributes now point at the structured renderer.
        self._diff_stats_group = page
        self._diff_stats_label = None
        self._stats_config_btn = choose
        self._detail_tabs.addTab(page, "Stats")

    def _build_stages_page(self) -> None:
        page, _content, layout = self._new_scroll_page()
        self._diff_stage_summary_group = QGroupBox("Stage comparison")
        stage_layout = QVBoxLayout(self._diff_stage_summary_group)
        self._diff_stages_table = CompactMetricCardGridView(
            section_capacity=4,
            metric_capacity=4,
            metrics_per_row=4,
        )
        self._diff_stages_table.setObjectName("CompareRunsStageCards")
        stage_layout.addWidget(self._diff_stages_table)
        self._diff_stage_summary_label = None
        self._diff_stage_summary_group.setObjectName("CompareRunsStageTable")
        layout.addWidget(self._diff_stage_summary_group)
        layout.addStretch(1)
        self._detail_tabs.addTab(page, "Stages")

    def _build_items_page(self) -> None:
        page, _content, layout = self._new_scroll_page()
        self._diff_items_group, self._diff_items_label = self._build_diff_card(
            "Item differences", "--"
        )
        self._diff_items_group.setObjectName("CompareRunsItemsDiff")
        self._diff_items_table = MetricTableView()
        self._diff_items_table.setObjectName("CompareRunsItemsTable")
        self._diff_items_group.layout().addWidget(self._diff_items_table)
        self._item_details_btn = QPushButton("Show Item Details")
        self._item_details_btn.setObjectName("CompareRunsItemDetails")
        self._item_details_btn.clicked.connect(self.toggle_compare_runs_item_details)
        self._diff_items_group.layout().addWidget(self._item_details_btn, 0, Qt.AlignLeft)
        layout.addWidget(self._diff_items_group)
        inventories = QHBoxLayout()
        for side in ("a", "b"):
            group, view = self._build_inventory_panel(side)
            setattr(self, f"_run_{side}_items_view", view)
            inventories.addWidget(group, 1)
        layout.addLayout(inventories)
        layout.addStretch(1)
        self._detail_tabs.addTab(page, "Items")

    def _build_inventory_panel(self, side: str):
        group = QGroupBox(f"Run {side.upper()} inventory")
        group.setObjectName("CompareRunsInventory")
        group.setProperty("side", side.upper())
        layout = QVBoxLayout(group)
        label = QLabel("--")
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        rarity = QLabel("")
        rarity.setTextFormat(Qt.RichText)
        toggle = QPushButton("Show all")
        toggle.setObjectName("CompareRunsInventoryToggle")
        sort = QComboBox()
        sort.setObjectName("CompareRunsItemsSort")
        for mode, text in ITEM_SORT_LABELS.items():
            sort.addItem(text, mode)
        rarity_index = sort.findData(ITEM_SORT_RARITY_DESC)
        if rarity_index >= 0:
            sort.setCurrentIndex(rarity_index)
        view = ItemsSectionView(
            group=group,
            label=label,
            rarity_label=rarity,
            toggle_btn=toggle,
            sort_combo=sort,
            initial_sort_mode=ITEM_SORT_RARITY_DESC,
        )
        toggle.clicked.connect(lambda _checked=False, run_side=side: self.toggle_compare_run_items_expanded(run_side))
        sort.currentIndexChanged.connect(
            lambda _index, run_side=side: self.on_compare_run_items_sort_changed(run_side)
        )
        layout.addWidget(label)
        actions = QHBoxLayout()
        actions.addWidget(toggle)
        actions.addWidget(rarity)
        actions.addStretch(1)
        actions.addWidget(sort)
        layout.addLayout(actions)
        return group, view

    def _build_table_page(self, title: str, group_attr: str, table_attr: str) -> None:
        page, _content, layout = self._new_scroll_page()
        group, table = self._build_diff_table_card(title)
        group.setObjectName(f"CompareRuns{title}Table")
        table.setObjectName("CompareRunsMetricTable")
        setattr(self, group_attr, group)
        setattr(self, table_attr, table)
        layout.addWidget(group)
        layout.addStretch(1)
        self._detail_tabs.addTab(page, title)
