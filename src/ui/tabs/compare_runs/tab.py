"""The Compare Runs tab: choosing two recorded runs and rendering their diff.

Moved out of ``PlayerStatsMixin`` without behaviour change. This is the first
module under ``ui/`` and the first tab to get its own package.

Still a mixin, deliberately. The Definition of Done wants tabs to be classes
with explicit dependencies rather than mixins sharing ``self``, but eleven of
these methods are called class-qualified from the suite
(``gui.MegabonkApp._refresh_compare_runs_diff(app)`` and friends), which only
resolves through ``MegabonkApp``'s MRO. Turning this into a standalone tab
object is a behaviour change and belongs with step 14, not with a pure move.

The tab reads its widgets (``compare_runs_*``) from the shared ``self``; they
are built in ``gui_layout.py``. That coupling is unchanged by this move -- it is
simply now visible across a file boundary instead of hidden inside a 3,800-line
module.

``_set_visible``, ``_checkbox_checked``, ``_nearest_snapshot_index`` and
``_snapshot_compare_time`` came along despite their generic names: once the tab
left, the player-stats mixin had no callers of any of them.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidgetItem

from app import config
from app.vod_library import load_vod
from core.stats.types import PLAYER_STAT_GROUPS
from gui_shared import _set_text
from projections import formatting
from projections.formatting import COMPARE_RUN_STAT_LABELS


COMPARE_RUN_STAT_CONFIG_KEY = "COMPARE_RUN_STAT_LABELS"

COMPARE_RUN_SECTIONS_CONFIG_KEY = "COMPARE_RUN_SECTIONS"

COMPARE_RUN_SECTION_DEFAULTS = {
    "items": False,
    "stage_summary": False,
    "weapons": False,
    "tomes": False,
    "chaos": False,
}


class CompareRunsMixin:
    def refresh_compare_runs_list(self):
        list_a = getattr(self, "compare_run_a_list_frame", None)
        list_b = getattr(self, "compare_run_b_list_frame", None)
        if list_a is None or list_b is None:
            return

        vods = list(getattr(self, "_vod_metadata_index", ()))
        selected_a = self.compare_run_a_vod.metadata.path if self.compare_run_a_vod is not None else None
        selected_b = self.compare_run_b_vod.metadata.path if self.compare_run_b_vod is not None else None
        signature = (
            str(selected_a) if selected_a is not None else "",
            str(selected_b) if selected_b is not None else "",
            tuple((str(vod.path), vod.name, vod.snapshot_count, vod.duration_seconds) for vod in vods),
        )
        available_paths = {vod.path for vod in vods}
        if selected_a is not None and selected_a not in available_paths:
            self._set_compare_run_error("a", "Selected recording is no longer available")
            selected_a = None
        if selected_b is not None and selected_b not in available_paths:
            self._set_compare_run_error("b", "Selected recording is no longer available")
            selected_b = None
        signature = (
            str(selected_a) if selected_a is not None else "",
            str(selected_b) if selected_b is not None else "",
            tuple((str(vod.path), vod.name, vod.snapshot_count, vod.duration_seconds) for vod in vods),
        )
        self._ensure_vod_metadata_refresh()
        if self.compare_runs_list_signature == signature:
            return

        self._populate_compare_run_list(list_a, vods, selected_a)
        self._populate_compare_run_list(list_b, vods, selected_b)
        self.compare_runs_list_signature = signature
        self._refresh_compare_runs_selected_labels()

    def _populate_compare_run_list(self, list_frame, vods, selected_path) -> None:
        list_frame.blockSignals(True)
        list_frame.clear()
        if not vods:
            item = QListWidgetItem("No saved recordings")
            item.setFlags(Qt.NoItemFlags)
            list_frame.addItem(item)
            list_frame.blockSignals(False)
            return

        selected_row = None
        for row, vod in enumerate(vods):
            duration = formatting.format_duration(vod.duration_seconds)
            item = QListWidgetItem(f"{vod.name}\n{vod.snapshot_count} snapshots | {duration}")
            item.setData(Qt.UserRole, str(vod.path))
            list_frame.addItem(item)
            if selected_path == vod.path:
                selected_row = row
        if selected_row is not None:
            list_frame.setCurrentRow(selected_row)
        list_frame.blockSignals(False)

    def _on_compare_run_selection_changed(self, side: str, current: QListWidgetItem | None):
        if current is None:
            return
        path_str = current.data(Qt.UserRole)
        if path_str:
            self.load_compare_run(side, path_str)

    def load_compare_run(self, side: str, path) -> None:
        path = Path(path)
        generations = getattr(self, "_compare_run_load_generations", {})
        generation = int(generations.get(side, 0)) + 1
        generations[side] = generation
        self._compare_run_load_generations = generations
        self._set_compare_run_error(side, "Loading recording…")

        def finish(loaded_vod, error) -> None:
            if generation != getattr(self, "_compare_run_load_generations", {}).get(side):
                return
            if error is not None:
                self._set_compare_run_error(side, f"Could not load recording: {error}")
                return
            self._set_compare_run_vod(side, loaded_vod)
            self._set_compare_run_index(side, 0 if loaded_vod.snapshots else None)
            self.refresh_compare_runs_list()
            self.refresh_compare_runs_ui(changed_side=side)
            self._auto_close_compare_runs_chooser_if_ready()

        def load() -> None:
            try:
                loaded = load_vod(path)
                error = None
            except Exception as exc:
                loaded = None
                error = exc
            after = getattr(self, "after", None)
            if callable(after) and getattr(self, "_invoker", None) is not None:
                after(0, lambda: finish(loaded, error))
            else:
                finish(loaded, error)

        if callable(getattr(self, "after", None)) and getattr(self, "_invoker", None) is not None:
            threading.Thread(target=load, name=f"compare-{side}-loader", daemon=True).start()
        else:
            load()

    def toggle_compare_runs_chooser(self):
        next_expanded = not bool(getattr(self, "compare_runs_chooser_expanded", False))
        self.set_compare_runs_chooser_expanded(next_expanded, guided=False)
        if next_expanded:
            self.refresh_compare_runs_list()

    def toggle_compare_runs_stats_config(self):
        self.compare_runs_stats_config_expanded = not bool(
            getattr(self, "compare_runs_stats_config_expanded", False)
        )
        if self.compare_runs_stats_config_expanded:
            self.set_compare_runs_chooser_expanded(False, guided=False)
        self._refresh_compare_runs_stats_config()

    def _auto_close_compare_runs_chooser_if_ready(self) -> None:
        if not bool(getattr(self, "compare_runs_chooser_expanded", False)):
            return
        if not bool(getattr(self, "compare_runs_guided_selection_active", False)):
            return
        if self.compare_run_a_vod is None or self.compare_run_b_vod is None:
            return
        self.set_compare_runs_chooser_expanded(False, guided=False)

    def ensure_compare_runs_chooser_for_empty_selection(self) -> None:
        if not self._is_compare_runs_tab_active():
            return
        if self.compare_run_a_vod is not None or self.compare_run_b_vod is not None:
            return
        if bool(getattr(self, "compare_runs_chooser_expanded", False)):
            return
        self.set_compare_runs_chooser_expanded(True, guided=True)

    def set_compare_runs_chooser_expanded(self, expanded: bool, *, guided: bool) -> None:
        self.compare_runs_chooser_expanded = bool(expanded)
        self.compare_runs_guided_selection_active = bool(expanded and guided)
        if self.compare_runs_chooser_expanded:
            self.compare_runs_stats_config_expanded = False
            self._refresh_compare_runs_stats_config()
        self._refresh_compare_runs_chooser()

    def on_compare_run_section_selection_changed(self):
        sections = self._compare_run_checked_sections()
        self.compare_runs_items_enabled = sections["items"]
        self.compare_runs_stage_summary_enabled = sections["stage_summary"]
        self.compare_runs_weapons_enabled = sections["weapons"]
        self.compare_runs_tomes_enabled = sections["tomes"]
        self.compare_runs_chaos_enabled = sections["chaos"]
        if not self.compare_runs_items_enabled:
            self.compare_runs_item_details_expanded = False
        self._save_compare_run_sections()
        self.refresh_compare_runs_ui()

    def toggle_compare_runs_item_details(self):
        self.compare_runs_item_details_expanded = not bool(
            getattr(self, "compare_runs_item_details_expanded", False)
        )
        self.refresh_compare_runs_ui()

    def on_compare_run_stat_selection_changed(self):
        self._save_compare_run_stat_selection()
        self.refresh_compare_runs_ui()

    def toggle_compare_run_items_expanded(self, side: str) -> None:
        scope = f"compare_{side}"
        prefix = self._scope_prefix(scope)
        setattr(self, f"{prefix}_items_expanded", not bool(getattr(self, f"{prefix}_items_expanded", False)))
        self._update_items_section(
            scope,
            getattr(self, f"{prefix}_items_current", ()),
            items_text=getattr(self, f"{prefix}_items_text_current", None),
        )

    def swap_compare_runs(self):
        self.compare_run_a_vod, self.compare_run_b_vod = self.compare_run_b_vod, self.compare_run_a_vod
        self.compare_run_a_snapshot_index, self.compare_run_b_snapshot_index = (
            self.compare_run_b_snapshot_index,
            self.compare_run_a_snapshot_index,
        )
        self.compare_runs_list_signature = None
        self.refresh_compare_runs_list()
        self.refresh_compare_runs_ui(changed_side="a")

    def on_compare_run_slider_changed(self, side: str, value):
        vod = self._compare_run_vod(side)
        if vod is None or not vod.snapshots:
            return
        index = min(max(int(round(float(value))), 0), len(vod.snapshots) - 1)
        if self._compare_run_index(side) == index:
            return

        self._set_compare_run_index(side, index)
        if not self.compare_runs_syncing:
            self.compare_runs_syncing = True
            try:
                other_side = "b" if side == "a" else "a"
                self._sync_compare_run_to_side(other_side, side)
            finally:
                self.compare_runs_syncing = False
        self.refresh_compare_runs_ui(changed_side=side)

    def refresh_compare_runs_ui(self, *, changed_side: str | None = None):
        if changed_side in {"a", "b"} and not self.compare_runs_syncing:
            self.compare_runs_syncing = True
            try:
                self._sync_compare_run_to_side("b" if changed_side == "a" else "a", changed_side)
            finally:
                self.compare_runs_syncing = False

        self._refresh_compare_run_side("a")
        self._refresh_compare_run_side("b")
        self._refresh_compare_runs_diff()
        self._refresh_compare_runs_selected_labels()
        self._refresh_compare_runs_chooser()
        self._refresh_compare_runs_stats_config()

    def _sync_compare_run_to_side(self, target_side: str, source_side: str) -> None:
        source_vod = self._compare_run_vod(source_side)
        target_vod = self._compare_run_vod(target_side)
        if source_vod is None or target_vod is None or not source_vod.snapshots or not target_vod.snapshots:
            return
        source_index = self._compare_run_index(source_side)
        if source_index is None:
            return
        source_snapshot = source_vod.snapshots[min(max(int(source_index), 0), len(source_vod.snapshots) - 1)]
        target_time = self._snapshot_compare_time(source_snapshot)
        if target_time is None:
            return
        target_index = self._nearest_snapshot_index(target_vod.snapshots, target_time)
        self._set_compare_run_index(target_side, target_index)
        slider = self._compare_run_slider(target_side)
        if slider is not None and slider.value() != target_index:
            slider.blockSignals(True)
            slider.setValue(target_index)
            slider.blockSignals(False)

    def _refresh_compare_run_side(self, side: str) -> None:
        vod = self._compare_run_vod(side)
        status_label = self._compare_run_widget(side, "status_label")
        slider = self._compare_run_slider(side)
        timeline_label = self._compare_run_widget(side, "timeline_label")
        summary_label = self._compare_run_widget(side, "summary_label")
        items_scope = f"compare_{side}"
        if vod is None:
            _set_text(status_label, "Select a recording")
            _set_text(timeline_label, "Timeline: --")
            _set_text(summary_label, "--")
            self._update_items_section(items_scope, items_text="--")
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
            self._update_items_section(items_scope, items_text="--")
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
        first = vod.snapshots[0].time_label
        last = vod.snapshots[-1].time_label
        _set_text(status_label, f"{vod.metadata.name} | {index + 1}/{snapshot_count}")
        _set_text(timeline_label, f"Timeline: {first} - {last} | Selected: {snapshot.time_label}")
        _set_text(summary_label, self.format_compare_run_snapshot_summary(vod, snapshot, index))
        self._update_items_section(items_scope, getattr(snapshot, "items", ()))

    def _refresh_compare_runs_diff(self) -> None:
        vod_a = self.compare_run_a_vod
        vod_b = self.compare_run_b_vod
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
        show_items = bool(getattr(self, "compare_runs_items_enabled", False))
        show_stage_summary = bool(getattr(self, "compare_runs_stage_summary_enabled", False))
        show_weapons = bool(getattr(self, "compare_runs_weapons_enabled", False))
        show_tomes = bool(getattr(self, "compare_runs_tomes_enabled", False))
        show_chaos = bool(getattr(self, "compare_runs_chaos_enabled", False))
        self._set_compare_runs_diff_cards(
            self.format_compare_runs_overview_diff(vod_a, snapshot_a, vod_b, snapshot_b),
            stats_text=self.format_compare_runs_stats_diff(
                snapshot_a,
                snapshot_b,
                stat_labels=self._compare_run_selected_stat_labels(),
            ),
            items_text=(
                self.format_compare_runs_items_diff(
                    snapshot_a,
                    snapshot_b,
                    details_expanded=bool(getattr(self, "compare_runs_item_details_expanded", False)),
                )
                if show_items
                else "--"
            ),
            stage_summary_text=(
                self.format_compare_runs_stage_summary_diff(
                    vod_a,
                    self._compare_run_index("a"),
                    vod_b,
                    self._compare_run_index("b"),
                )
                if show_stage_summary
                else "--"
            ),
            weapons_text=(
                self.format_compare_runs_weapons_diff(snapshot_a, snapshot_b) if show_weapons else "--"
            ),
            tomes_text=(
                self.format_compare_runs_tomes_diff(snapshot_a, snapshot_b) if show_tomes else "--"
            ),
            chaos_text=(
                self.format_compare_runs_chaos_diff(snapshot_a, snapshot_b) if show_chaos else "--"
            ),
            show_items=show_items,
            show_stage_summary=show_stage_summary,
            show_weapons=show_weapons,
            show_tomes=show_tomes,
            show_chaos=show_chaos,
        )
        self._refresh_compare_runs_item_details_button(show_items)

    def _set_compare_run_error(self, side: str, text: str) -> None:
        self._set_compare_run_vod(side, None)
        self._set_compare_run_index(side, None)
        self._refresh_compare_run_side(side)
        error_html = f'<span style="color:#f08b72;">{text}</span>'
        _set_text(self._compare_run_widget(side, "status_label"), error_html)
        self._refresh_compare_runs_diff()
        self._refresh_compare_runs_selected_labels()

    def _refresh_compare_runs_item_details_button(self, visible: bool) -> None:
        item_details_btn = getattr(self, "compare_runs_item_details_btn", None)
        if item_details_btn is None:
            return
        item_details_btn.setVisible(visible)
        item_details_btn.setText(
            "Hide Item Details"
            if bool(getattr(self, "compare_runs_item_details_expanded", False))
            else "Show Item Details"
        )

    def _set_compare_runs_diff_cards(
        self,
        overview_text: str,
        *,
        stats_text: str = "--",
        items_text: str = "--",
        stage_summary_text: str = "--",
        weapons_text: str = "--",
        tomes_text: str = "--",
        chaos_text: str = "--",
        show_items: bool = False,
        show_stage_summary: bool = False,
        show_weapons: bool = False,
        show_tomes: bool = False,
        show_chaos: bool = False,
    ) -> None:
        _set_text(getattr(self, "compare_runs_diff_overview_label", None), overview_text)
        _set_text(getattr(self, "compare_runs_diff_stats_label", None), stats_text)
        _set_text(getattr(self, "compare_runs_diff_items_label", None), items_text)
        _set_text(getattr(self, "compare_runs_diff_stage_summary_label", None), stage_summary_text)
        _set_text(getattr(self, "compare_runs_diff_weapons_label", None), weapons_text)
        _set_text(getattr(self, "compare_runs_diff_tomes_label", None), tomes_text)
        _set_text(getattr(self, "compare_runs_diff_chaos_label", None), chaos_text)
        self._set_visible(getattr(self, "compare_runs_diff_overview_group", None), True)
        self._set_visible(getattr(self, "compare_runs_diff_stats_group", None), bool(stats_text and stats_text != "--"))
        self._set_visible(getattr(self, "compare_runs_diff_items_group", None), show_items)
        self._set_visible(getattr(self, "compare_runs_diff_stage_summary_group", None), show_stage_summary)
        self._set_visible(getattr(self, "compare_runs_diff_weapons_group", None), show_weapons)
        self._set_visible(getattr(self, "compare_runs_diff_tomes_group", None), show_tomes)
        self._set_visible(getattr(self, "compare_runs_diff_chaos_group", None), show_chaos)

    def _refresh_compare_runs_chooser(self) -> None:
        expanded = bool(getattr(self, "compare_runs_chooser_expanded", False))
        chooser = getattr(self, "compare_runs_chooser_group", None)
        button = getattr(self, "compare_runs_select_btn", None)
        swap_btn = getattr(self, "compare_runs_swap_btn", None)
        if chooser is not None:
            chooser.setVisible(expanded)
        if button is not None:
            button.setText("Hide Runs" if expanded else "Select Runs")
        if swap_btn is not None:
            swap_btn.setEnabled(self.compare_run_a_vod is not None or self.compare_run_b_vod is not None)

    def _refresh_compare_runs_stats_config(self) -> None:
        expanded = bool(getattr(self, "compare_runs_stats_config_expanded", False))
        group = getattr(self, "compare_runs_stats_config_group", None)
        button = getattr(self, "compare_runs_stats_config_btn", None)
        if group is not None:
            group.setVisible(expanded)
        if button is not None:
            button.setText("Hide Settings" if expanded else "Compare Settings")

    def _refresh_compare_runs_selected_labels(self) -> None:
        _set_text(
            getattr(self, "compare_run_a_selected_label", None),
            f"Run A: {self._compare_run_selected_text('a')}",
        )
        _set_text(
            getattr(self, "compare_run_b_selected_label", None),
            f"Run B: {self._compare_run_selected_text('b')}",
        )

    def _compare_run_selected_text(self, side: str) -> str:
        vod = self._compare_run_vod(side)
        if vod is None:
            return "--"
        snapshot_count = len(vod.snapshots)
        duration = formatting.format_duration(vod.metadata.duration_seconds)
        return f"{vod.metadata.name} ({snapshot_count} snapshots | {duration})"

    @staticmethod
    def default_compare_run_stat_labels() -> tuple[str, ...]:
        return COMPARE_RUN_STAT_LABELS

    @classmethod
    def all_compare_run_stat_labels(cls) -> tuple[str, ...]:
        return tuple(spec.label for group in PLAYER_STAT_GROUPS for spec in group)

    @classmethod
    def configured_compare_run_stat_labels(cls) -> tuple[str, ...]:
        saved_labels = config.user_config.get(COMPARE_RUN_STAT_CONFIG_KEY)
        if isinstance(saved_labels, list):
            allowed_labels = set(cls.all_compare_run_stat_labels())
            selected = tuple(str(label) for label in saved_labels if str(label) in allowed_labels)
            if selected:
                return selected
        return cls.default_compare_run_stat_labels()

    @classmethod
    def configured_compare_run_sections(cls) -> dict[str, bool]:
        saved_sections = config.user_config.get(COMPARE_RUN_SECTIONS_CONFIG_KEY)
        sections = dict(COMPARE_RUN_SECTION_DEFAULTS)
        if isinstance(saved_sections, dict):
            for key in sections:
                if key in saved_sections:
                    sections[key] = bool(saved_sections[key])
        return sections

    def _save_compare_run_stat_selection(self) -> None:
        config.user_config[COMPARE_RUN_STAT_CONFIG_KEY] = list(self._compare_run_checked_stat_labels())
        config.save_config(config.user_config)

    def _save_compare_run_sections(self) -> None:
        config.user_config[COMPARE_RUN_SECTIONS_CONFIG_KEY] = self._compare_run_checked_sections()
        config.save_config(config.user_config)

    def _compare_run_checked_sections(self) -> dict[str, bool]:
        return {
            "items": bool(self._checkbox_checked(getattr(self, "compare_runs_items_checkbox", None))),
            "stage_summary": bool(
                self._checkbox_checked(getattr(self, "compare_runs_stage_summary_checkbox", None))
            ),
            "weapons": bool(self._checkbox_checked(getattr(self, "compare_runs_weapons_checkbox", None))),
            "tomes": bool(self._checkbox_checked(getattr(self, "compare_runs_tomes_checkbox", None))),
            "chaos": bool(self._checkbox_checked(getattr(self, "compare_runs_chaos_checkbox", None))),
        }

    def _compare_run_checked_stat_labels(self) -> tuple[str, ...]:
        checkboxes = getattr(self, "compare_runs_stat_checkboxes", None) or {}
        return tuple(label for label, checkbox in checkboxes.items() if checkbox.isChecked())

    def _compare_run_selected_stat_labels(self) -> tuple[str, ...]:
        checkboxes = getattr(self, "compare_runs_stat_checkboxes", None) or {}
        if not checkboxes:
            return self.configured_compare_run_stat_labels()
        selected = self._compare_run_checked_stat_labels()
        return selected or self.default_compare_run_stat_labels()

    def _compare_run_vod(self, side: str):
        return self.compare_run_a_vod if side == "a" else self.compare_run_b_vod

    def _set_compare_run_vod(self, side: str, vod) -> None:
        if side == "a":
            self.compare_run_a_vod = vod
        else:
            self.compare_run_b_vod = vod

    def _compare_run_index(self, side: str) -> int | None:
        return self.compare_run_a_snapshot_index if side == "a" else self.compare_run_b_snapshot_index

    def _set_compare_run_index(self, side: str, index: int | None) -> None:
        if side == "a":
            self.compare_run_a_snapshot_index = index
        else:
            self.compare_run_b_snapshot_index = index

    def _compare_run_snapshot(self, side: str):
        vod = self._compare_run_vod(side)
        index = self._compare_run_index(side)
        if vod is None or not vod.snapshots or index is None:
            return None
        index = min(max(int(index), 0), len(vod.snapshots) - 1)
        return vod.snapshots[index]

    def _compare_run_widget(self, side: str, widget_name: str):
        prefix = f"compare_run_{side}_"
        return getattr(self, f"{prefix}{widget_name}", None)

    def _compare_run_slider(self, side: str):
        return self._compare_run_widget(side, "slider")

    @classmethod
    def format_compare_run_snapshot_summary(cls, vod, snapshot, index: int) -> str:
        return formatting.format_compare_run_snapshot_summary(vod, snapshot, index)

    @classmethod
    def format_compare_runs_diff(
        cls,
        vod_a,
        snapshot_a,
        vod_b,
        snapshot_b,
        *,
        stat_labels: tuple[str, ...] | None = None,
        include_items: bool = False,
        item_details_expanded: bool = False,
        include_weapons: bool = False,
        include_tomes: bool = False,
        include_chaos: bool = False,
    ) -> str:
        return formatting.format_compare_runs_diff(vod_a, snapshot_a, vod_b, snapshot_b, stat_labels=stat_labels, include_items=include_items, item_details_expanded=item_details_expanded, include_weapons=include_weapons, include_tomes=include_tomes, include_chaos=include_chaos)

    @classmethod
    def format_compare_runs_overview_diff(cls, vod_a, snapshot_a, vod_b, snapshot_b) -> str:
        return formatting.format_compare_runs_overview_diff(vod_a, snapshot_a, vod_b, snapshot_b)

    @classmethod
    def format_compare_runs_stats_diff(cls, snapshot_a, snapshot_b, *, stat_labels: tuple[str, ...] | None = None) -> str:
        return formatting.format_compare_runs_stats_diff(snapshot_a, snapshot_b, stat_labels=stat_labels)

    @classmethod
    def format_compare_runs_items_diff(cls, snapshot_a, snapshot_b, *, details_expanded: bool = False) -> str:
        return formatting.format_compare_runs_items_diff(snapshot_a, snapshot_b, details_expanded=details_expanded)

    @classmethod
    def format_compare_runs_stage_summary_diff(cls, vod_a, index_a, vod_b, index_b) -> str:
        return formatting.format_compare_runs_stage_summary_diff(vod_a, index_a, vod_b, index_b)

    @classmethod
    def format_compare_runs_weapons_diff(cls, snapshot_a, snapshot_b) -> str:
        return formatting.format_compare_runs_weapons_diff(snapshot_a, snapshot_b)

    @classmethod
    def format_compare_runs_tomes_diff(cls, snapshot_a, snapshot_b) -> str:
        return formatting.format_compare_runs_tomes_diff(snapshot_a, snapshot_b)

    @classmethod
    def format_compare_runs_chaos_diff(cls, snapshot_a, snapshot_b) -> str:
        return formatting.format_compare_runs_chaos_diff(snapshot_a, snapshot_b)

    @staticmethod
    def _set_visible(widget, visible: bool) -> None:
        if widget is not None and hasattr(widget, "setVisible"):
            widget.setVisible(visible)
    @staticmethod
    def _checkbox_checked(checkbox) -> bool:
        return bool(checkbox is not None and checkbox.isChecked())
    @classmethod
    def _nearest_snapshot_index(cls, snapshots, target_time: float) -> int:
        best_index = 0
        best_distance = float("inf")
        for index, snapshot in enumerate(snapshots):
            snapshot_time = cls._snapshot_compare_time(snapshot)
            if snapshot_time is None:
                continue
            distance = abs(float(snapshot_time) - float(target_time))
            if distance < best_distance:
                best_index = index
                best_distance = distance
        return best_index
    @staticmethod
    def _snapshot_compare_time(snapshot) -> float | None:
        return formatting._snapshot_compare_time(snapshot)
