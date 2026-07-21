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
from typing import Callable

from PySide6.QtCore import Qt
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
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.vod_library import (
    delete_vod,
    delete_vods_below_snapshot_count,
    load_vod,
    rename_vod,
)
from core.stats.types import PLAYER_STAT_GROUPS
from gui_dialogs import CleanupRecordingsDialog, ConfirmDeleteRecordingDialog
from gui_layout import (
    LIVE_STATS_VALUE_WIDTH,
    RECORDINGS_LIST_MAX_WIDTH,
    RECORDINGS_LIST_MIN_WIDTH,
    RECORDINGS_STATS_CARD_COLUMNS,
    _apply_player_stat_value_baseline,
    _apply_run_summary_baselines,
    _apply_stage_summary_column_baseline,
    _build_chests_stats_card,
    _retain_hidden_widget_size,
)
from ui.shared import (
    _apply_summary_label_padding,
    _clear_text_input,
    _make_scroll_section,
    _read_text,
    _set_text,
    _set_text_input,
)
from ui.styles import ITEM_SORT_LABELS
from ui.tabs.player_stats.items_section import ItemsSectionView
from ui.tabs.player_stats.stat_cards import StatCardsView
from ui.tabs.player_stats.summary_cards import (
    set_chests_card_values,
    set_stage_summary_labels,
)
from projections import formatting


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
        self._compare_start_index = None
        self._compare_details_expanded = False
        self._chooser_expanded = False
        self._guided_selection_active = False
        self._list_signature = None
        self._load_generation = 0
        self._load_in_progress = False

        self._rows = {}
        self._stage_summary_labels = []

        # Every widget `build()` creates, named here as `None`. They were
        # `getattr(self, "vods_...", None)` reads on the mixin -- a default that
        # existed only because `object.__new__` doubles skipped `__init__` and
        # so quietly tolerated a half-built tab. Declaring them is what lets the
        # readers below be plain attribute access: an unbuilt tab now raises at
        # the right place instead of rendering into `None`.
        self._tab = None
        self._select_btn = None
        self._status_label = None
        self._name_entry = None
        self._rename_btn = None
        self._cleanup_btn = None
        self._delete_btn = None
        self._slider = None
        self._slider_time_label = None
        self._compare_set_btn = None
        self._compare_clear_btn = None
        self._items_section = None
        self._chests_per_minute_label = None
        self._in_game_time_label = None
        self._mob_kills_label = None
        self._kps_averages_label = None
        self._level_label = None
        self._new_items_label = None
        self._compare_details_btn = None
        self._banishes_label = None
        self._compare_details_group = None
        self._compare_details_summary_label = None
        self._compare_details_items_label = None
        self._detail_tabs = None
        self._stat_cards = None
        self._chooser_group = None
        self._list_frame = None
        self._chests_card_values = None

    def refresh_vods_list(self):
        if self._list_frame is None:
            return

        vods = list(self._library.index)
        selected_path = self._loaded_vod.metadata.path if self._loaded_vod is not None else None
        signature = (
            str(selected_path) if selected_path is not None else "",
            tuple((str(vod.path), vod.name, vod.snapshot_count, vod.duration_seconds) for vod in vods),
        )
        self._library.ensure_refresh()
        if self._list_signature == signature:
            return

        self._list_frame.blockSignals(True)
        self._list_frame.clear()
        if not vods:
            item = QListWidgetItem("No saved recordings")
            item.setFlags(Qt.NoItemFlags)
            self._list_frame.addItem(item)
            self._list_frame.blockSignals(False)
            self._list_signature = signature
            return

        selected_row = None
        for row, vod in enumerate(vods):
            duration = formatting.format_duration(vod.duration_seconds)
            item = QListWidgetItem(f"{vod.name}\n{vod.snapshot_count} snapshots | {duration}")
            item.setData(Qt.UserRole, str(vod.path))
            self._list_frame.addItem(item)
            if selected_path == vod.path:
                selected_row = row
        if selected_row is not None:
            self._list_frame.setCurrentRow(selected_row)
        self._list_frame.blockSignals(False)
        self._list_signature = signature
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
        self.set_recordings_chooser_expanded(True, guided=True)
    def set_recordings_chooser_expanded(self, expanded: bool, *, guided: bool) -> None:
        self._chooser_expanded = bool(expanded)
        self._guided_selection_active = bool(expanded and guided)
        self._refresh_recordings_chooser()
    def _refresh_recordings_chooser(self) -> None:
        expanded = bool(self._chooser_expanded)
        chooser = self._chooser_group
        button = self._select_btn
        if chooser is not None:
            chooser.setVisible(expanded)
        if button is not None:
            button.setText("Hide Recordings" if expanded else "Select Recordings")
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
            (self._cleanup_btn, not loading),
            (self._delete_btn, has_recording),
            (self._slider, has_snapshots),
        ):
            if widget is not None:
                widget.setEnabled(enabled)
        self._refresh_vod_compare_controls()
    def load_selected_vod(self, path):
        path = Path(path)
        generation = int(self._load_generation) + 1
        self._load_generation = generation
        self._loaded_vod = None
        self._snapshot_index = None
        self._compare_start_index = None
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
            self._compare_start_index = None
            self._compare_details_expanded = False
            _clear_text_input(self._name_entry)
            _set_text_input(self._name_entry, loaded_vod.metadata.name)
            self.refresh_loaded_vod_ui()
            self._set_vod_loading_state(False)
            self.refresh_vods_list()
            if bool(self._chooser_expanded) and bool(
                self._guided_selection_active
            ):
                self.set_recordings_chooser_expanded(False, guided=False)

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
        _set_text(self._status_label, f"{metadata.created_label} | {snapshot_count} snapshots | {duration}")

        if snapshot_count:
            self._slider.setEnabled(True)
            self._slider.setMaximum(max(snapshot_count - 1, 1))
            if update_slider:
                self._slider.setValue(self._snapshot_index or 0)
            self.display_loaded_vod_snapshot(self._snapshot_index or 0)
        else:
            self._slider.setEnabled(False)
            self._slider.setMaximum(1)
            self._slider.setValue(0)
            for label in self._rows.values():
                _set_text(label, "--")
            _set_text(self._slider_time_label, "Timeline: --")
            self._items_section.collapse()
            self._items_section.update((), items_text="--")
            _set_text(self._chests_per_minute_label, "Average chests/min: --")
            _set_text(self._in_game_time_label, "In-Game Time: --")
            _set_text(self._mob_kills_label, "Mob Kills: --")
            _set_text(self._kps_averages_label, "KPS: --")
            _set_text(self._level_label, "Level: --")
            set_chests_card_values(
                self._chests_card_values,
                None,
            )
            _set_text(self._new_items_label, "No previous snapshot")
            self._refresh_vod_compare_controls()
            self._refresh_vod_compare_details(None, None, index=None)
            _set_text(self._banishes_label, "No banishes yet")
            set_stage_summary_labels(self._stage_summary_labels, None)
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
        snapshot = self._loaded_vod.snapshots[index]
        _set_text(
            self._status_label,
            (
                f"{self._loaded_vod.metadata.name} | {index + 1}/{len(self._loaded_vod.snapshots)}"
                f" at {snapshot.time_label} | {formatting.format_in_game_time(snapshot.game_time_seconds)}"
            ),
        )
        first = self._loaded_vod.snapshots[0].time_label
        last = self._loaded_vod.snapshots[-1].time_label
        _set_text(self._slider_time_label, f"Timeline: {first} - {last} | Selected: {snapshot.time_label}")
        for spec_group in PLAYER_STAT_GROUPS:
            for spec in spec_group:
                value_label = self._rows.get(spec.label)
                if value_label is not None:
                    stat = snapshot.stats.get(spec.label)
                    _set_text(value_label, stat.display_value if stat is not None else "--")
        self._items_section.update(snapshot.items)
        _set_text(
            self._chests_per_minute_label,
            formatting.format_chests_per_minute(formatting.resolve_snapshot_chests_per_minute(snapshot)),
        )
        _set_text(
            self._in_game_time_label,
            formatting.format_in_game_time(snapshot.game_time_seconds),
        )
        _set_text(
            self._mob_kills_label,
            formatting.format_mob_kills(
                getattr(snapshot, "mob_kills", None),
                getattr(snapshot, "kps_at_capture", None),
            ),
        )
        _set_text(
            self._kps_averages_label,
            formatting.format_kps_averages(
                getattr(snapshot, "minute_avg_kps_at_capture", None),
                getattr(snapshot, "five_minute_avg_kps_at_capture", None),
            ),
        )
        _set_text(
            self._level_label,
            formatting.format_player_level(getattr(snapshot, "player_level", None)),
        )
        self._update_recorded_chest_summary(snapshot)
        set_stage_summary_labels(
            self._stage_summary_labels,
            formatting.build_stage_summary(self._loaded_vod.snapshots[: index + 1]),
        )
        previous_snapshot = self._resolve_vod_compare_base_snapshot(index)
        segment_snapshots = self._vod_compare_segment_snapshots(index)
        _set_text(
            self._new_items_label,
            formatting.format_snapshot_item_gains_preview(previous_snapshot, snapshot, segment_snapshots=segment_snapshots),
        )
        self._refresh_vod_compare_controls()
        self._refresh_vod_compare_details(previous_snapshot, snapshot, index=index, segment_snapshots=segment_snapshots)
        _set_text(
            self._banishes_label,
            formatting.format_banishes_rich_text(getattr(snapshot, "banishes", ())),
        )
        self._stat_cards.display_weapons(getattr(snapshot, "weapons", ()))
        self._stat_cards.display_tomes(getattr(snapshot, "tomes", ()))
        self._stat_cards.display_chaos_tome(
            getattr(snapshot, "chaos_tome", None),
            status_text=None if getattr(snapshot, "chaos_tome", None) is not None else "No Chaos Tome data in this snapshot",
        )
        self._stat_cards.display_damage_sources(getattr(snapshot, "damage_sources", ()))
    def on_vods_slider_changed(self, value):
        if self._loaded_vod is None or not self._loaded_vod.snapshots:
            return
        index = min(max(int(round(float(value))), 0), len(self._loaded_vod.snapshots) - 1)
        if self._snapshot_index == index:
            return
        self.display_loaded_vod_snapshot(index)
    def set_vod_compare_start(self):
        if self._loaded_vod is None or not self._loaded_vod.snapshots:
            return
        index = self._snapshot_index
        if index is None:
            index = 0
        self._compare_start_index = min(max(int(index), 0), len(self._loaded_vod.snapshots) - 1)
        self._compare_details_expanded = True
        self.display_loaded_vod_snapshot(self._snapshot_index or 0)
    def clear_vod_compare_start(self):
        self._compare_start_index = None
        self._compare_details_expanded = False
        if self._loaded_vod is not None and self._loaded_vod.snapshots:
            self.display_loaded_vod_snapshot(self._snapshot_index or 0)
        else:
            self._refresh_vod_compare_controls()
            self._refresh_vod_compare_details(None, None, index=None)
    def toggle_vod_compare_details(self):
        self._compare_details_expanded = not bool(self._compare_details_expanded)
        if self._loaded_vod is not None and self._loaded_vod.snapshots:
            self.display_loaded_vod_snapshot(self._snapshot_index or 0)
        else:
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
        compare_index = self._compare_start_index
        set_btn = self._compare_set_btn
        clear_btn = self._compare_clear_btn
        details_btn = self._compare_details_btn
        if set_btn is not None:
            set_btn.setEnabled(has_snapshots)
        if clear_btn is not None:
            clear_btn.setEnabled(has_snapshots and compare_index is not None)
        if details_btn is not None:
            details_btn.setVisible(has_snapshots)
            expanded = bool(self._compare_details_expanded)
            details_btn.setText("Hide details" if expanded else "Show details")
    def _refresh_vod_compare_details(self, base_snapshot, snapshot, *, index: int | None, segment_snapshots=()) -> None:
        self._refresh_vod_compare_controls()
        expanded = bool(self._compare_details_expanded)
        group = self._compare_details_group
        if group is not None:
            group.setVisible(expanded and base_snapshot is not None and snapshot is not None)
        if base_snapshot is None or snapshot is None:
            _set_text(self._compare_details_summary_label, "--")
            _set_text(self._compare_details_items_label, "--")
            return

        compare_index = self._compare_start_index
        base_index = compare_index if compare_index is not None else (index - 1 if index is not None else None)
        summary = formatting.format_snapshot_compare_summary(
            base_snapshot,
            snapshot,
            base_index=base_index,
            current_index=index,
            segment_snapshots=segment_snapshots,
        )
        _set_text(self._compare_details_summary_label, summary)
        _set_text(
            self._compare_details_items_label,
            formatting.format_snapshot_item_changes_details(base_snapshot, snapshot, segment_snapshots=segment_snapshots),
        )
    def rename_selected_vod(self):
        if self._loaded_vod is None or self._name_entry is None:
            return
        new_name = _read_text(self._name_entry).strip()
        try:
            metadata = rename_vod(self._loaded_vod.metadata.path, new_name)
            self._loaded_vod = load_vod(metadata.path)
        except Exception as exc:
            _set_text(self._status_label, f"Could not rename recording: {exc}")
            return
        self.refresh_loaded_vod_ui(update_slider=False)
        self.refresh_vods_list()
    def _clear_loaded_vod_selection(self) -> None:
        self._loaded_vod = None
        self._snapshot_index = None
        self._compare_start_index = None
        self._compare_details_expanded = False
        _clear_text_input(self._name_entry)
        _set_text(self._status_label, "Select a recording")
        self._slider.setEnabled(False)
        self._slider.setMaximum(1)
        self._slider.setValue(0)
        _set_text(self._slider_time_label, "Timeline: --")
        for label in self._rows.values():
            _set_text(label, "--")
        self._items_section.collapse()
        self._items_section.update((), items_text="--")
        _set_text(self._chests_per_minute_label, "Average chests/min: --")
        _set_text(self._in_game_time_label, "In-Game Time: --")
        _set_text(self._mob_kills_label, "Mob Kills: --")
        _set_text(self._kps_averages_label, "KPS: --")
        _set_text(self._level_label, "Level: --")
        set_chests_card_values(
            self._chests_card_values,
            None,
        )
        _set_text(self._new_items_label, "No previous snapshot")
        self._refresh_vod_compare_controls()
        self._refresh_vod_compare_details(None, None, index=None)
        _set_text(self._banishes_label, "No banishes yet")
        set_stage_summary_labels(self._stage_summary_labels, None)
        self._stat_cards.invalidate()
        self._stat_cards.display_weapons((), status_text="Select a recording")
        self._stat_cards.display_tomes((), status_text="Select a recording")
        self._stat_cards.display_chaos_tome(None, status_text="Select a recording")
        self._stat_cards.display_damage_sources((), status_text="Select a recording")
    def cleanup_recordings_by_snapshot_count(self):
        dialog = CleanupRecordingsDialog(self._window())
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
                ),
            )
    def build(self):
        """Create the tab's widgets and add it to the tab bar.

        Separate from `__init__` for the same reason `LiveStatsTab.build` is:
        it needs real offscreen Qt, so `tests/support/player_stats.py`'s builder
        can construct the component without paying for a widget tree, and the
        built tab is covered by `tools/step21_vod_trace.py` instead.
        """
        self._tab = QWidget()
        vods_layout = QVBoxLayout(self._tab)
        selected_row = QHBoxLayout()
        self._select_btn = QPushButton("Select Recordings")
        self._select_btn.setProperty("class", "CompareRunsGhostButton")
        self._select_btn.clicked.connect(self.toggle_recordings_chooser)
        selected_row.addStretch(1)
        selected_row.addWidget(self._select_btn)
        vods_layout.addLayout(selected_row)

        vods_body_layout = QHBoxLayout()
        vods_detail = QWidget()
        vods_detail_layout = QVBoxLayout(vods_detail)
        self._status_label = QLabel("Select a recording")
        vods_detail_layout.addWidget(self._status_label)
        name_row = QHBoxLayout()
        self._name_entry = QLineEdit()
        self._rename_btn = QPushButton("Rename")
        self._rename_btn.clicked.connect(self.rename_selected_vod)
        self._cleanup_btn = QPushButton("Clean Short")
        self._cleanup_btn.clicked.connect(self.cleanup_recordings_by_snapshot_count)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("DangerButton")
        self._delete_btn.clicked.connect(self.delete_selected_vod)
        name_row.addWidget(self._name_entry, 1)
        name_row.addWidget(self._rename_btn)
        name_row.addWidget(self._cleanup_btn)
        name_row.addWidget(self._delete_btn)
        vods_detail_layout.addLayout(name_row)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setEnabled(False)
        self._slider.valueChanged.connect(self.on_vods_slider_changed)
        vods_detail_layout.addWidget(self._slider)
        self._slider_time_label = QLabel("Timeline: --")
        vods_detail_layout.addWidget(self._slider_time_label)
        vod_compare_actions = QHBoxLayout()
        self._compare_set_btn = QPushButton("Set Compare Start")
        self._compare_set_btn.setProperty("class", "SmallGhostButton")
        self._compare_set_btn.clicked.connect(self.set_vod_compare_start)
        self._compare_clear_btn = QPushButton("Clear Compare")
        self._compare_clear_btn.setProperty("class", "SmallGhostButton")
        self._compare_clear_btn.clicked.connect(self.clear_vod_compare_start)
        self._compare_clear_btn.setEnabled(False)
        vod_compare_actions.addWidget(self._compare_set_btn)
        vod_compare_actions.addWidget(self._compare_clear_btn)
        vod_compare_actions.addStretch(1)
        vods_detail_layout.addLayout(vod_compare_actions)
        vod_items_group = QGroupBox("Items")
        vod_items_layout = QVBoxLayout(vod_items_group)
        vods_items_label = QLabel("--")
        vods_items_label.setTextFormat(Qt.RichText)
        vods_items_label.setWordWrap(True)
        vod_items_layout.addWidget(vods_items_label)
        vods_items_toggle_btn = QPushButton("Show more")
        vods_items_toggle_btn.clicked.connect(self.toggle_vod_items_expanded)
        vods_items_toggle_btn.setProperty("class", "SmallGhostButton")
        _retain_hidden_widget_size(vods_items_toggle_btn)
        vods_items_toggle_btn.setEnabled(False)
        vod_items_actions = QHBoxLayout()
        vods_items_rarity_label = QLabel("")
        vods_items_rarity_label.setTextFormat(Qt.RichText)
        vods_items_rarity_label.setStyleSheet("font-size: 14px;")
        vods_items_rarity_label.setVisible(False)
        vods_items_sort_combo = QComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            vods_items_sort_combo.addItem(label, mode)
        self._items_section = ItemsSectionView(
            group=vod_items_group,
            label=vods_items_label,
            rarity_label=vods_items_rarity_label,
            toggle_btn=vods_items_toggle_btn,
            sort_combo=vods_items_sort_combo,
        )
        vods_items_sort_combo.currentIndexChanged.connect(
            lambda _index: self._items_section.on_sort_changed()
        )
        vod_items_actions.addWidget(vods_items_toggle_btn, 0, Qt.AlignLeft)
        vod_items_actions.addWidget(vods_items_rarity_label, 0, Qt.AlignLeft)
        vod_items_actions.addStretch(1)
        vod_items_actions.addWidget(QLabel("Sort:"))
        vod_items_actions.addWidget(vods_items_sort_combo)
        vod_items_layout.addLayout(vod_items_actions)
        vods_detail_layout.addWidget(vod_items_group)
        vod_summary_grid = QGridLayout()
        vod_summary_grid.setContentsMargins(0, 0, 0, 0)
        vod_summary_grid.setHorizontalSpacing(8)
        vod_summary_grid.setVerticalSpacing(8)
        vod_chest_rate_group = QGroupBox("Run Summary")
        vod_chest_rate_layout = QVBoxLayout(vod_chest_rate_group)
        self._chests_per_minute_label = QLabel("Average chests/min: --")
        vod_chest_rate_layout.addWidget(self._chests_per_minute_label)
        self._in_game_time_label = QLabel("In-Game Time: --")
        vod_chest_rate_layout.addWidget(self._in_game_time_label)
        self._mob_kills_label = QLabel("Mob Kills: --")
        vod_chest_rate_layout.addWidget(self._mob_kills_label)
        self._kps_averages_label = QLabel("KPS: --")
        vod_chest_rate_layout.addWidget(self._kps_averages_label)
        self._level_label = QLabel("Level: --")
        vod_chest_rate_layout.addWidget(self._level_label)
        _apply_summary_label_padding(
            self._chests_per_minute_label,
            self._in_game_time_label,
            self._mob_kills_label,
            self._kps_averages_label,
            self._level_label,
        )
        _apply_run_summary_baselines(
            self._chests_per_minute_label,
            self._in_game_time_label,
            self._mob_kills_label,
            self._kps_averages_label,
            self._level_label,
        )
        vod_summary_grid.addWidget(vod_chest_rate_group, 0, 0)
        vod_stage_summary_group = QGroupBox("Stage Summary")
        vod_stage_summary_layout = QGridLayout(vod_stage_summary_group)
        vod_stage_summary_layout.setContentsMargins(10, 10, 10, 10)
        vod_stage_summary_layout.setHorizontalSpacing(10)
        vod_stage_summary_layout.setVerticalSpacing(4)
        for column, header in enumerate(("Stage", "Time", "Kills", "Items")):
            label = QLabel(header)
            label.setStyleSheet("font-weight: 700; color: #F3F4F6;")
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            vod_stage_summary_layout.addWidget(label, 0, column)
        for index in range(4):
            stage_label = QLabel(str(index + 1))
            time_label = QLabel("--")
            kills_label = QLabel("--")
            items_label = QLabel("--")
            items_label.setTextFormat(Qt.RichText)
            stage_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            for value_label in (time_label, kills_label, items_label):
                value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            _apply_summary_label_padding(stage_label, time_label, kills_label, items_label)
            vod_stage_summary_layout.addWidget(stage_label, index + 1, 0)
            vod_stage_summary_layout.addWidget(time_label, index + 1, 1)
            vod_stage_summary_layout.addWidget(kills_label, index + 1, 2)
            vod_stage_summary_layout.addWidget(items_label, index + 1, 3)
            self._stage_summary_labels.append(
                {
                    "stage": stage_label,
                    "time": time_label,
                    "kills": kills_label,
                    "items": items_label,
                }
            )
        _apply_stage_summary_column_baseline(
            vod_stage_summary_layout,
            self._stage_summary_labels,
        )
        vod_stage_summary_layout.setColumnStretch(0, 1)
        vod_stage_summary_layout.setColumnStretch(1, 2)
        vod_stage_summary_layout.setColumnStretch(2, 1)
        vod_stage_summary_layout.setColumnStretch(3, 1)
        vod_summary_grid.addWidget(vod_stage_summary_group, 0, 1)
        vod_new_items_group = QGroupBox("Segment Compare")
        vod_new_items_layout = QVBoxLayout(vod_new_items_group)
        self._new_items_label = QLabel("No previous snapshot")
        self._new_items_label.setTextFormat(Qt.RichText)
        self._new_items_label.setWordWrap(True)
        _apply_summary_label_padding(self._new_items_label)
        vod_new_items_layout.addWidget(self._new_items_label)
        self._compare_details_btn = QPushButton("Show details")
        self._compare_details_btn.setProperty("class", "SmallGhostButton")
        self._compare_details_btn.clicked.connect(self.toggle_vod_compare_details)
        self._compare_details_btn.setVisible(False)
        vod_new_items_layout.addWidget(self._compare_details_btn, 0, Qt.AlignLeft)
        vod_summary_grid.addWidget(vod_new_items_group, 0, 2)
        vod_banishes_group = QGroupBox("Banishes")
        vod_banishes_layout = QVBoxLayout(vod_banishes_group)
        self._banishes_label = QLabel("No banishes yet")
        self._banishes_label.setTextFormat(Qt.RichText)
        self._banishes_label.setWordWrap(True)
        _apply_summary_label_padding(self._banishes_label)
        vod_banishes_layout.addWidget(self._banishes_label)
        vod_summary_grid.addWidget(vod_banishes_group, 0, 3)
        for column in range(4):
            vod_summary_grid.setColumnStretch(column, 1)
        vods_detail_layout.addLayout(vod_summary_grid)
        self._compare_details_group = QGroupBox("Compare Details")
        vod_compare_details_layout = QVBoxLayout(self._compare_details_group)
        self._compare_details_summary_label = QLabel("--")
        self._compare_details_summary_label.setWordWrap(True)
        self._compare_details_items_label = QLabel("--")
        self._compare_details_items_label.setTextFormat(Qt.RichText)
        self._compare_details_items_label.setWordWrap(True)
        _apply_summary_label_padding(
            self._compare_details_summary_label,
            self._compare_details_items_label,
        )
        vod_compare_details_layout.addWidget(self._compare_details_summary_label)
        vod_compare_scroll, _vod_compare_scroll_content, vod_compare_scroll_layout = _make_scroll_section()
        vod_compare_scroll.setMinimumHeight(120)
        vod_compare_scroll.setMaximumHeight(220)
        vod_compare_scroll_layout.setContentsMargins(0, 0, 0, 0)
        vod_compare_scroll_layout.addWidget(self._compare_details_items_label)
        vod_compare_scroll_layout.addStretch(1)
        vod_compare_details_layout.addWidget(vod_compare_scroll)
        self._compare_details_group.setVisible(False)
        vods_detail_layout.addWidget(self._compare_details_group)
        self._detail_tabs = QTabWidget()
        vod_stats_tab = QWidget()
        vod_stats_tab_layout = QVBoxLayout(vod_stats_tab)
        vods_scroll, _vods_scroll_content, vods_scroll_layout = _make_scroll_section()
        vod_stats_tab_layout.addWidget(vods_scroll)
        vods_stats_grid = QGridLayout()
        vods_stats_grid.setContentsMargins(0, 0, 0, 0)
        vods_stats_grid.setHorizontalSpacing(8)
        vods_stats_grid.setVerticalSpacing(8)
        for index, group in enumerate(PLAYER_STAT_GROUPS):
            stat_group = QFrame()
            stat_group.setObjectName("StatCard")
            group_layout = QFormLayout(stat_group)
            group_layout.setContentsMargins(8, 8, 8, 8)
            group_layout.setHorizontalSpacing(6)
            group_layout.setVerticalSpacing(4)
            for spec in group:
                value_label = QLabel("--")
                value_label.setMinimumWidth(LIVE_STATS_VALUE_WIDTH)
                _apply_player_stat_value_baseline(value_label, spec.value_format)
                value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._rows[spec.label] = value_label
                group_layout.addRow(spec.label, value_label)
            vods_stats_grid.addWidget(
                stat_group,
                index // RECORDINGS_STATS_CARD_COLUMNS,
                index % RECORDINGS_STATS_CARD_COLUMNS,
            )
        placeholder_index = len(PLAYER_STAT_GROUPS)
        placeholder_group, self._chests_card_values = _build_chests_stats_card()
        vods_stats_grid.addWidget(
            placeholder_group,
            placeholder_index // RECORDINGS_STATS_CARD_COLUMNS,
            placeholder_index % RECORDINGS_STATS_CARD_COLUMNS,
        )
        for column in range(RECORDINGS_STATS_CARD_COLUMNS):
            vods_stats_grid.setColumnStretch(column, 1)
        vods_scroll_layout.addLayout(vods_stats_grid)
        vods_scroll_layout.addStretch(1)
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
        )
        self._detail_tabs.addTab(vod_stats_tab, "Stats")
        self._detail_tabs.addTab(vod_weapons_tab, "Weapons")
        self._detail_tabs.addTab(vod_tomes_tab, "Tomes")
        self._detail_tabs.addTab(vod_chaos_tab, "Chaos")
        self._detail_tabs.addTab(vod_damage_sources_tab, "Damage Sources")
        vod_stats_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_weapons_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_tomes_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_chaos_tab_layout.setContentsMargins(0, 0, 0, 0)
        vod_damage_sources_tab_layout.setContentsMargins(0, 0, 0, 0)
        vods_detail_layout.addWidget(self._detail_tabs, 1)
        self._chooser_group = QGroupBox("Select Recordings")
        self._chooser_group.setVisible(False)
        self._chooser_group.setMinimumWidth(RECORDINGS_LIST_MIN_WIDTH)
        self._chooser_group.setMaximumWidth(RECORDINGS_LIST_MAX_WIDTH + 40)
        chooser_layout = QVBoxLayout(self._chooser_group)
        self._list_frame = QListWidget()
        self._list_frame.setMinimumWidth(RECORDINGS_LIST_MIN_WIDTH)
        self._list_frame.setMaximumWidth(RECORDINGS_LIST_MAX_WIDTH)
        self._list_frame.currentItemChanged.connect(self._on_vod_selection_changed)
        chooser_layout.addWidget(self._list_frame)
        vods_body_layout.addWidget(self._chooser_group, 0)
        vods_body_layout.addWidget(vods_detail, 1)
        vods_layout.addLayout(vods_body_layout, 1)
        self._tabview.addTab(self._tab, "Recordings")
