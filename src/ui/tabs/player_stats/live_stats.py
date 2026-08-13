"""The Live Stats tab: rendering the current run as it is read from memory.

An object with explicit dependencies, not a base class of ``MegabonkApp``.
Step 19 finished what the step-18 pilot started: the ten collaborators below
used to be ambient reads on a shared ``self``, and the eighteen Qt widgets used
to be public names on it that any of fourteen other mixins could reach.

What is *not* here: acquiring the data. ``refresh_live_player_stats_now`` and the
memory clients live in ``app/player_stats_memory.py``; this tab only renders what it is
handed. That boundary is the whole point of step 14 -- it is what let this module
land under ``ui/`` with no ``infra`` import at all.

How the app layer reaches it
============================

Through ``app/player_stats_view.py``'s ``PlayerStatsView`` port, whose seven
operations this class implements. ``player_stats_view(owner)`` returns the
instance the composition root stored on ``owner._player_stats_view``; step 19
is where its ambient ``owner`` fallback stopped being reachable in production,
which was this step's stated exit criterion.

Two callers are **not** in ``app/`` and were missing from every inventory of
this conversion, because ``src/tests/test_view_ports.py`` scans ``app/`` alone:

* ``gui_scanner.update_timer`` calls ``refresh_player_stats_timeline_ui`` once
  a second while recording, on the shared ``self``. Unguarded -- it would have
  raised ``AttributeError`` on the first tick after the mixin left the MRO.
* ``gui_dialogs.SettingsDialog.save`` calls the same method on ``self.master``,
  behind ``hasattr``. That one would **not** have raised: the guard would have
  gone quietly false and the timeline strip would have stopped refreshing after
  a settings save, with a green suite and no exception. The same silent-guard
  shape step 18 recorded as the reason making this tab's widgets private could
  break four panels without raising.

Both now resolve through ``player_stats_view()``. Neither belongs to step 19's
feature -- they are the scanner's (25) and the dialogs' -- so they go through
the declared port rather than reaching for the handle.

Why the collaborators are suppliers
===================================

The same reason ``RecordingTimelineView`` gives: the app layer rebinds the
underlying state. ``gui_overlay.initialize_overlay_runtime`` assigns
``live_run_tracker`` after ``__init__`` starts, ``app/vod_capture.py``
reassigns the snapshot list, and ``app/player_stats_refresh.py`` moves the
selected index. A component holding the *value* would go stale exactly where a
mixin reading ``self`` did not -- which is the kind of difference a shared
namespace hides until it is removed.
"""
from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from math import isfinite

from app import config
from core.stat_labels import abbreviate_stat_label
from core.stats.types import PLAYER_STAT_GROUPS
from projections.item_sort import ITEM_SORT_RARITY_DESC
from ui.shared import (
    FlowLayout,
    FullWidthTabWidget,
    LabeledSwitch,
    _apply_summary_label_padding,
    _make_scroll_section,
    _set_text,
)
from ui.styles import ITEM_SORT_LABELS
from ui.tabs.player_stats.items_section import (
    BANISHES_CHIPS_MAX_HEIGHT,
    BANISHES_SECTION_MARGINS,
    BanishesSectionView,
    CompactItemsSortComboBox,
    ItemsSectionView,
    update_banishes_section,
)
from ui.tabs.player_stats.metrics import (
    LIVE_STATS_VALUE_WIDTH,
    _apply_player_stat_value_baseline,
    _build_chests_stats_card,
    _build_loot_rarity_card,
)
from ui.tabs.player_stats.recording_timeline import RecordingTimelineView
from ui.tabs.player_stats.stat_cards import StatCardsView, section_visibility_over
from ui.tabs.player_stats.summary_cards import (
    set_chests_card_values,
    set_loot_rarity_card_values,
    set_stage_summary_labels,
)
from projections import formatting
from projections.build_progression import build_progression_payload
from ui.dialogs.build_progression import BuildProgressionHelpDialog


LIVE_STATS_EXPANDED_CONFIG_KEY = "LIVE_STATS_EXPANDED"


def pin_for_selection(index: int, snapshot_count: int) -> bool:
    """Should scrubbing to `index` pin the view against live repaints?

    Selecting the newest snapshot resumes following the run; anything earlier
    pins. Module-level and pure so it is directly testable -- the caller is a
    closure inside `build`, which needs a built Qt tab to reach.
    """
    return index < snapshot_count - 1


def responsive_card_column_count(
    width: int,
    *,
    minimum_card_width: int = 212,
    spacing: int = 8,
    maximum_columns: int = 4,
) -> int:
    """Number of compact stat cards that fit without squeezing below the design."""
    usable_width = max(0, int(width))
    stride = max(1, int(minimum_card_width) + max(0, int(spacing)))
    columns = (usable_width + max(0, int(spacing))) // stride
    return max(1, min(max(1, int(maximum_columns)), columns))


class _ResponsiveCardGrid(QWidget):
    """A small Qt reflow host for the Stats cards in the Live Stats tab."""

    def __init__(
        self,
        *,
        minimum_card_width: int = 212,
        spacing: int = 8,
        maximum_columns: int = 4,
        stretch_columns: bool = True,
    ) -> None:
        super().__init__()
        self.setObjectName("LiveStatsCardGrid")
        self._minimum_card_width = minimum_card_width
        self._spacing = spacing
        self._maximum_columns = maximum_columns
        self._stretch_columns = stretch_columns
        self._columns = 0
        self._cards: list[QWidget] = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(spacing)
        self._grid.setVerticalSpacing(spacing)

    def add_card(self, card: QWidget) -> None:
        self._cards.append(card)
        self._reflow(self.width())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow(event.size().width())

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        columns = responsive_card_column_count(
            width,
            minimum_card_width=self._minimum_card_width,
            spacing=self._spacing,
            maximum_columns=self._maximum_columns,
        )
        row_heights: list[int] = []
        for index, card in enumerate(self._cards):
            row = index // columns
            if row == len(row_heights):
                row_heights.append(0)
            row_heights[row] = max(row_heights[row], card.sizeHint().height())
        return sum(row_heights) + self._spacing * max(0, len(row_heights) - 1)

    def minimumSizeHint(self) -> QSize:
        width = self._minimum_card_width
        return QSize(width, self.heightForWidth(width))

    def sizeHint(self) -> QSize:
        # The scroll viewport supplies the useful width. Reporting a compact
        # hint prevents the current column count from inflating its own parent.
        return self.minimumSizeHint()

    def _reflow(self, width: int) -> None:
        columns = responsive_card_column_count(
            width,
            minimum_card_width=self._minimum_card_width,
            spacing=self._spacing,
            maximum_columns=self._maximum_columns,
        )
        required_height = self.heightForWidth(width)
        if self.minimumHeight() != required_height:
            self.setMinimumHeight(required_height)
        if columns == self._columns and self._grid.count() == len(self._cards):
            return
        while self._grid.count():
            self._grid.takeAt(0)
        for index, card in enumerate(self._cards):
            row = index // columns
            column = index % columns
            if self._stretch_columns:
                self._grid.addWidget(card, row, column)
            else:
                self._grid.addWidget(card, row, column, Qt.AlignLeft | Qt.AlignTop)
        for column in range(self._maximum_columns + 1):
            stretch = 1 if self._stretch_columns and column < columns else 0
            self._grid.setColumnStretch(column, stretch)
        if not self._stretch_columns:
            self._grid.setColumnStretch(columns, 1)
        self._columns = columns
        self.updateGeometry()


class _BuildProgressionRow(QFrame):
    """One structured checklist row; values update without rebuilding widgets."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("BuildProgressionRow")
        self.setProperty("status", "neutral")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)

        self.symbol = QLabel("·")
        self.symbol.setObjectName("BuildProgressionSymbol")
        self.symbol.setAlignment(Qt.AlignCenter)
        self.symbol.setFixedWidth(18)
        layout.addWidget(self.symbol)

        self.name = QLabel()
        self.name.setObjectName("BuildProgressionTarget")
        layout.addWidget(self.name, 1)

        self.value = QLabel()
        self.value.setObjectName("BuildProgressionValue")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.value)

        self.deadline = QLabel()
        self.deadline.setObjectName("BuildProgressionDeadline")
        self.deadline.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.deadline)

    def update_row(self, row: dict) -> None:
        status = str(row.get("status") or "neutral")
        if self.property("status") != status:
            self.setProperty("status", status)
            self.style().unpolish(self)
            self.style().polish(self)
        self.symbol.setText(str(row.get("symbol") or "·"))
        self.name.setText(str(row.get("label") or ""))
        self.name.setStyleSheet(
            f"color: {row.get('label_color') or '#E4E9F0'}; background: transparent;"
        )
        self.value.setText(str(row.get("value") or ""))
        # Once Required is met, the deadline has done its job.  Keeping an
        # overdue delta or target clock on a green row made it read as both
        # complete and late; if the value regresses, the evaluator restores
        # the current deadline and the badge comes back automatically.
        timing = "" if status == "satisfied" else str(row.get("time") or "")
        self.deadline.setText(timing)
        self.deadline.setVisible(bool(timing))
        self.setVisible(True)


class LiveStatsTab:
    """The Live Stats tab, and the `PlayerStatsView` port's implementation.

    Constructed once by `gui_layout._build_live_stats_view`, which is the
    composition root for it, and stored as `MegabonkApp._player_stats_view`.
    """

    def __init__(
        self,
        *,
        tabview,
        live_run_tracker: Callable[[], object],
        vod_recorder: Callable[[], object],
        vod_snapshots: Callable[[], Sequence],
        selected_snapshot_index: Callable[[], int | None],
        recording_waiting_mode: Callable[[], object],
        ensure_live_snapshot_store: Callable[[], object],
        is_recording_armed: Callable[[], bool],
        on_toggle_recording: Callable[[], None],
        on_snapshot_selected: Callable[..., None],
        build_progression_snapshot: Callable[[], object | None] = lambda: None,
        open_build_progression_settings: Callable[[], None] = lambda: None,
    ) -> None:
        self._tabview = tabview
        self._live_run_tracker = live_run_tracker
        self._vod_recorder = vod_recorder
        self._vod_snapshots = vod_snapshots
        self._selected_snapshot_index = selected_snapshot_index
        self._recording_waiting_mode = recording_waiting_mode
        self._ensure_live_snapshot_store = ensure_live_snapshot_store
        self._is_recording_armed = is_recording_armed
        self._on_toggle_recording = on_toggle_recording
        self._on_snapshot_selected = on_snapshot_selected
        self._build_progression_snapshot = build_progression_snapshot
        self._open_build_progression_settings = open_build_progression_settings

        # Widgets, all created by `build`. Declared here so the set this tab
        # owns is readable in one place rather than scattered through 260
        # lines of builder.
        self._root = None
        self._status_label = None
        self._detail_tabs = None
        self._stat_value_rows: dict = {}
        self._compact_stat_value_rows: dict = {}
        self._stats_expanded_toggle = None
        self._chests_per_minute_label = None
        self._in_game_time_label = None
        self._mob_kills_label = None
        self._kps_averages_label = None
        self._level_label = None
        self._stage_summary_labels: list = []
        self._powerups_group = None
        self._powerup_labels: dict = {}
        self._banishes_label = None
        self._chests_card_values = None
        self._loot_rarity_card_values = None
        # These two are never built, here or anywhere else -- they were `None`
        # on the shared namespace and `_set_text(None, ...)` is a no-op, so
        # every write to them has always been dead in production. Carried over
        # rather than deleted: "this looks unreachable" is what step 14c had to
        # walk back, and keeping the write targets makes the trace identical.
        self._new_items_label = None
        self._powerups_duration_label = None
        # Child components.
        self._recording_timeline = None
        self._items_section = None
        self._stat_cards = None
        self._build_progression_header = None
        self._build_progression_progress = None
        self._build_progression_clock = None
        self._build_progression_empty = None
        self._build_progression_complete = None
        self._build_progression_footer = None
        self._build_progression_scroll = None
        self._build_progression_rows_layout = None
        self._build_progression_rows: list[_BuildProgressionRow] = []

    @property
    def root_widget(self):
        """The tab's own QWidget, for harnesses that need to inspect it."""
        return self._root

    # -- PlayerStatsView --------------------------------------------------

    def refresh_powerups_card(self) -> None:
        """`PlayerStatsView` operation: repaint the Powerups card.

        Was `_refresh_live_powerups_label`, called on the shared `self` from
        `app/refresh_tasks.py`. Same body; it now has a name the port declares
        and one that says what it renders.
        """
        self._apply_live_powerups_card(None)

    def _apply_live_powerups_card(self, stats) -> None:
        """Write the Powerups card.

        Moved out of `PlayerStatsCardsMixin` at step 19: the Live Stats tab is
        its only caller and it writes two widgets this file builds, so it was
        never shared card rendering.
        """
        group = self._powerups_group
        labels = self._powerup_labels
        if group is None or not isinstance(labels, dict):
            return
        title, values = self.format_live_powerups_card(stats)
        group.setTitle(title)
        for effect_name, label in labels.items():
            _set_text(label, f"{effect_name}: {values.get(effect_name, '--')}")

    def format_live_powerups_card(self, stats) -> tuple[str, dict[str, str]]:
        values = {name: "--" for name in ("Rage", "Clock", "Shield", "Stonks")}
        title = "Powerups"

        snapshot_reader = getattr(self._live_run_tracker(), "powerups_snapshot", None)
        snapshot = snapshot_reader() if callable(snapshot_reader) else None
        if getattr(snapshot, "available", False):
            pm_display = str(getattr(snapshot, "powerup_multiplier_display", "--") or "--")
            if pm_display != "--":
                title = f"Powerups (PM {pm_display})"
            active_by_name = {
                str(getattr(effect, "name", "")): effect
                for effect in getattr(snapshot, "active", ()) or ()
            }
            for effect_name in values:
                effect = active_by_name.get(effect_name)
                if effect is not None:
                    left_text = f"({formatting.format_seconds_compact(effect.remaining_seconds)}s)"
                    if (
                        getattr(effect, "pickup_ui", None) is None
                        or getattr(effect, "expires_ui", None) is None
                    ):
                        values[effect_name] = left_text
                    else:
                        values[effect_name] = (
                            f"{effect.pickup_ui} -> {effect.expires_ui} "
                            f"{left_text}"
                        )
                    continue
                duration = (
                    getattr(snapshot, "clock_duration_seconds", None)
                    if effect_name == "Clock"
                    else getattr(snapshot, "standard_duration_seconds", None)
                )
                if duration is not None:
                    values[effect_name] = f"-- ({formatting.format_seconds_compact(duration)}s)"
            return title, values

        stat = (stats or {}).get("Powerup Multiplier")
        try:
            powerup_multiplier = float(getattr(stat, "value", None))
        except (TypeError, ValueError):
            return title, values
        if not isfinite(powerup_multiplier):
            return title, values

        pm_display = str(getattr(stat, "display_value", "") or "").strip()
        if pm_display:
            title = f"Powerups (PM {pm_display})"
        standard_duration = formatting.format_seconds_compact(15.0 * powerup_multiplier)
        clock_duration = formatting.format_seconds_compact(12.0 * powerup_multiplier)
        values["Rage"] = f"-- ({standard_duration}s)"
        values["Clock"] = f"-- ({clock_duration}s)"
        values["Shield"] = f"-- ({standard_duration}s)"
        values["Stonks"] = f"-- ({standard_duration}s)"
        return title, values

    def set_stage_summary_rows(self, rows) -> None:
        """Render stage-summary rows into this tab's own labels.

        A `PlayerStatsView` operation, added at step 19 for the same reason
        step 17 added `set_mob_kills_text`: `app/refresh_tasks.py` was reaching
        `self.player_stats_stage_summary_labels` -- a Qt widget -- and calling
        the writer on it directly. The app layer still decides what the rows
        say; it no longer reaches through the shared namespace to a widget to
        put them there, which is what let these labels stay public.
        """
        set_stage_summary_labels(self._stage_summary_labels, rows)

    def set_items(self, items) -> None:
        """`PlayerStatsView` operation: repaint the items panel alone.

        The section keeps its own sort mode and render signature, so identical
        one-second readings are skipped and a real repaint preserves the
        internal scroll position.
        `items_text` is deliberately not passed: the "Items unavailable" string
        is the slow path's to write, and the fast task simply does not repaint
        when its read failed rather than blanking a panel that still holds a
        good reading.
        """
        self._items_section.update(items)

    def _reset_live_player_stats_ui(self, status_text: str, *, items_text: str = "--") -> None:
        _set_text(self._status_label, status_text)
        for label in self._stat_value_rows.values():
            _set_text(label, "--")
        for label in self._compact_stat_value_rows.values():
            _set_text(label, "--")
        self._items_section.collapse()
        self._ensure_live_snapshot_store().reset_for_new_match()
        self._items_section.update((), items_text=items_text)
        _set_text(self._chests_per_minute_label, "Average chests/min: --")
        self._apply_live_powerups_card(None)
        _set_text(self._in_game_time_label, "In-Game Time: --")
        _set_text(self._mob_kills_label, "Mob Kills: --")
        _set_text(self._kps_averages_label, "KPS: --")
        _set_text(self._level_label, "Level: --")
        set_chests_card_values(
            self._chests_card_values,
            None,
        )
        set_loot_rarity_card_values(self._loot_rarity_card_values, None, None)
        _set_text(self._new_items_label, "Live snapshot")
        update_banishes_section(
            getattr(self, "_banishes_view", None), self._banishes_label, ()
        )
        set_stage_summary_labels(self._stage_summary_labels, None)
        self._stat_cards.invalidate()
        self._stat_cards.display_weapons((), status_text="Waiting for weapon data...")
        self._stat_cards.display_tomes((), status_text="Waiting for tome data...")
        self._stat_cards.display_chaos_tome(None, status_text="Waiting for Chaos Tome data...")
        self._stat_cards.display_damage_sources(
            (), status_text="Waiting for damage source data..."
        )

    def display_player_stats(
        self,
        stats,
        items=(),
        *,
        weapons=(),
        tomes=(),
        chaos_tome=None,
        banishes=(),
        damage_sources=(),
        weapons_available: bool = True,
        tomes_available: bool = True,
        damage_sources_available: bool = True,
        status_text: str | None = None,
        chests_per_minute: float | None = None,
        items_text: str | None = None,
        game_time_seconds: float | None = None,
        mob_kills: int | None = None,
        kps: int | None = None,
        minute_avg_kps: int | None = None,
        five_minute_avg_kps: int | None = None,
        player_level: int | None = None,
        new_items_text: str | None = None,
        stage_summary_rows: list[dict[str, str]] | None = None,
    ):
        if status_text:
            _set_text(self._status_label, status_text)
        for label, stat in stats.items():
            value_label = self._stat_value_rows.get(label)
            if value_label is not None:
                _set_text(value_label, stat.display_value)
            compact_value_label = self._compact_stat_value_rows.get(label)
            if compact_value_label is not None:
                _set_text(compact_value_label, stat.display_value)
        self._items_section.update(items, items_text=items_text)
        if chests_per_minute is None:
            chests_per_minute = formatting.calculate_player_chests_per_minute(stats)
        _set_text(
            self._chests_per_minute_label,
            formatting.format_chests_per_minute(chests_per_minute),
        )
        _set_text(
            self._powerups_duration_label,
            self.format_live_powerups(stats),
        )
        self._apply_live_powerups_card(stats)
        _set_text(
            self._in_game_time_label,
            formatting.format_in_game_time(game_time_seconds),
        )
        _set_text(
            self._mob_kills_label,
            formatting.format_mob_kills(mob_kills, kps),
        )
        _set_text(
            self._kps_averages_label,
            formatting.format_kps_averages(minute_avg_kps, five_minute_avg_kps),
        )
        _set_text(
            self._level_label,
            formatting.format_player_level(player_level),
        )
        tracker = self._live_run_tracker()
        get_chest_stats = getattr(tracker, "get_chest_stats", None)
        if callable(get_chest_stats):
            self._update_live_chest_summary(get_chest_stats())
        self._update_live_loot_rarity_summary(tracker, stats)
        if new_items_text is not None:
            _set_text(self._new_items_label, new_items_text)
        else:
            _set_text(self._new_items_label, "Live snapshot")
        update_banishes_section(
            getattr(self, "_banishes_view", None), self._banishes_label, banishes
        )
        set_stage_summary_labels(self._stage_summary_labels, stage_summary_rows)
        self._stat_cards.display_weapons(
            weapons if weapons_available else (),
            status_text=None if weapons_available else "Weapons unavailable",
        )
        self._stat_cards.display_tomes(
            tomes if tomes_available else (),
            status_text=None if tomes_available else "Tomes unavailable",
        )
        self._stat_cards.display_chaos_tome(
            chaos_tome,
            status_text=None if chaos_tome is not None else "No Chaos Tome data yet",
        )
        self._stat_cards.display_damage_sources(
            damage_sources if damage_sources_available else (),
            status_text=None if damage_sources_available else "Damage sources unavailable",
        )
        self.refresh_build_progression()

    def display_player_stats_snapshot(self, snapshot, *, items_text: str | None = None):
        snapshots = self._vod_snapshots()
        index = snapshots.index(snapshot) + 1
        total = len(snapshots)
        self.display_player_stats(
            snapshot.stats,
            snapshot.items,
            weapons=getattr(snapshot, "weapons", ()),
            tomes=getattr(snapshot, "tomes", ()),
            chaos_tome=getattr(snapshot, "chaos_tome", None),
            banishes=getattr(snapshot, "banishes", ()),
            damage_sources=getattr(snapshot, "damage_sources", ()),
            status_text=(
                f"Recorded snapshot {index}/{total} at {snapshot.time_label}"
                f" | {formatting.format_in_game_time(snapshot.game_time_seconds)}"
            ),
            chests_per_minute=formatting.resolve_snapshot_chests_per_minute(snapshot),
            items_text=items_text,
            game_time_seconds=snapshot.game_time_seconds,
            mob_kills=getattr(snapshot, "mob_kills", None),
            kps=getattr(snapshot, "kps_at_capture", None),
            minute_avg_kps=getattr(snapshot, "minute_avg_kps_at_capture", None),
            five_minute_avg_kps=getattr(snapshot, "five_minute_avg_kps_at_capture", None),
            player_level=getattr(snapshot, "player_level", None),
            new_items_text=formatting.format_snapshot_item_gains_preview(
                self._previous_player_stats_snapshot(snapshot),
                snapshot,
                segment_snapshots=self._player_stats_snapshot_segment(snapshot),
            ),
            stage_summary_rows=formatting.build_stage_summary(snapshots[:index]),
        )

    def _previous_player_stats_snapshot(self, snapshot):
        snapshots = self._vod_snapshots()
        try:
            index = snapshots.index(snapshot)
        except ValueError:
            return None
        if index <= 0:
            return None
        return snapshots[index - 1]

    def _player_stats_snapshot_segment(self, snapshot) -> tuple[object, ...]:
        snapshots = self._vod_snapshots()
        try:
            index = snapshots.index(snapshot)
        except ValueError:
            return (snapshot,)
        start_index = max(0, index - 1)
        return tuple(snapshots[start_index : index + 1])

    def on_player_stats_slider_changed(self, value):
        self._recording_timeline.handle_slider_value(value)

    def set_recording_status_text(self, text: str) -> None:
        """Set the Live Stats status line.

        This tab builds `_status_label`, so it is the only place that should
        write it. `app/vod_capture.py` used to reach in and call `_set_text` on
        the widget directly -- a Qt write from the app layer, against the
        widget whose creator had already moved here in step 14b. It now goes
        through `PlayerStatsView` instead.
        """
        _set_text(self._status_label, text)

    def set_mob_kills_text(self, text: str) -> None:
        """Set the Live Stats mob-kills line.

        Same shape, and the same reason, as `set_recording_status_text` above:
        this tab builds `_mob_kills_label`, so it is the only place that should
        write it. `app/refresh_tasks.py` used to import `_set_text` from
        `gui_shared` and write the widget itself -- the last consumer of
        `gui_shared` outside UI code, outstanding since step 6. The app layer
        still decides what the line says; it no longer reaches through a Qt
        helper to put it there.
        """
        _set_text(self._mob_kills_label, text)

    def set_kps_averages_text(self, text: str) -> None:
        """Set the Live Stats KPS averages line.

        The same shape as `set_mob_kills_text` above, for the label directly
        beneath it.
        """
        _set_text(self._kps_averages_label, text)

    def set_chaos_tome_card(self, chaos_tome) -> None:
        """Repaint the Chaos Tome card alone.

        The status text is derived here rather than passed in, exactly as
        `display_player_stats` derives it, so the fast caller does not have to
        know the card's empty-state wording.
        """
        self._stat_cards.display_chaos_tome(
            chaos_tome,
            status_text=None if chaos_tome is not None else "No Chaos Tome data yet",
        )

    def set_in_game_time_text(self, text: str) -> None:
        """Set the Live Stats in-game time line.

        The same shape as `set_mob_kills_text` directly above, for the label
        sitting next to it in the same card.
        """
        _set_text(self._in_game_time_label, text)

    def refresh_build_progression(self) -> None:
        header = self._build_progression_header
        progress = self._build_progression_progress
        clock = self._build_progression_clock
        empty = self._build_progression_empty
        complete = self._build_progression_complete
        footer = self._build_progression_footer
        if any(widget is None for widget in (header, progress, clock, empty, complete, footer)):
            return
        snapshot = self._build_progression_snapshot()
        payload = build_progression_payload(
            snapshot,
            {
                "max_rows": 20,
                "show_completed": True,
                "show_target_time": True,
                "show_section_headings": True,
            },
        )
        if not payload.get("configured"):
            header.setText("Build Progression")
            progress.setText("NOT CONFIGURED")
            clock.clear()
            clock.hide()
            empty.setText(
                "No active build yet. Create or import a build, then set it active; the "
                "same checklist will appear here, in overlays, and in Twitch chat."
            )
            empty.show()
            complete.hide()
            footer.hide()
            self._hide_build_progression_rows()
            return
        header.setText(str(payload.get("name") or "Build Progression"))
        progress.setText(str(payload.get("progress") or "0/0"))
        clock.clear()
        clock.hide()

        if not payload.get("available"):
            empty.setText(
                "Waiting for an active run. Every new run starts this checklist clean."
            )
            empty.show()
            complete.hide()
            footer.hide()
            self._hide_build_progression_rows()
            return
        if payload.get("complete"):
            empty.hide()
            complete.setText(
                f"✓  BUILD COMPLETE  ·  {payload.get('completion_time') or '--:--'}"
            )
            complete.show()
            footer.hide()
            self._hide_build_progression_rows()
            return
        empty.hide()
        complete.hide()
        rows = list(payload.get("rows") or ())
        self._ensure_build_progression_rows(len(rows))
        for index, row_widget in enumerate(self._build_progression_rows):
            if index < len(rows):
                row_widget.update_row(rows[index])
            else:
                row_widget.hide()
        completed_count = sum(row.get("status") == "satisfied" for row in rows)
        remaining_count = max(0, len(rows) - completed_count)
        footer.setText(f"{remaining_count} remaining  ·  {completed_count} completed")
        footer.show()

    def _ensure_build_progression_rows(self, count: int) -> None:
        layout = self._build_progression_rows_layout
        if layout is None:
            return
        while len(self._build_progression_rows) < count:
            row = _BuildProgressionRow()
            self._build_progression_rows.append(row)
            layout.addWidget(row)

    def _hide_build_progression_rows(self) -> None:
        for row in self._build_progression_rows:
            row.hide()

    def refresh_player_stats_timeline_ui(self, *, update_slider: bool = True):
        """Re-render the recording timeline strip.

        A `PlayerStatsView` operation with eight app-layer callers plus the two
        outside `app/` this module's header names; the rendering itself lives
        in `RecordingTimelineView`. The name and signature predate the pilot.
        """
        self._recording_timeline.refresh(update_slider=update_slider)

    def toggle_player_items_expanded(self) -> None:
        self._items_section.toggle_expanded()

    @staticmethod
    def _save_stats_expanded_preference(expanded: bool) -> None:
        config.user_config[LIVE_STATS_EXPANDED_CONFIG_KEY] = bool(expanded)
        config.save_config(config.user_config)

    def _update_live_chest_summary(self, chest_stats) -> None:
        labels = self._chests_card_values
        if labels:
            set_chests_card_values(
                labels,
                formatting.chests_card_values(
                    chest_stats.opened_by_stage,
                    chest_stats.total_by_stage,
                    chest_stats.total_opened,
                    chest_stats.total_chests,
                    chest_stats.paid if chest_stats.counters_available else None,
                    chest_stats.key_procs if chest_stats.counters_available else None,
                    chest_stats.free_chests if chest_stats.counters_available else None,
                    chest_stats.keys_count,
                    chest_stats.expected_key_procs if chest_stats.expected_complete else None,
                    chest_stats.total_opened_is_minimum,
                ),
            )

    def _update_live_loot_rarity_summary(self, tracker, stats) -> None:
        """Repaint the rarity card from the tracker's own summary.

        Luck comes from the fast lane when there is a fresh reading and from
        the 10 s snapshot's `stats` otherwise -- the same fallback the in-game
        widget uses, and for the same reason: a slightly stale Luck is a better
        chance row than none, and `None` here means "not read", never zero.
        """
        labels = self._loot_rarity_card_values
        if not labels:
            return
        get_loot_stats = getattr(tracker, "get_loot_stats", None)
        loot_stats = get_loot_stats() if callable(get_loot_stats) else None
        fast_luck = getattr(tracker, "fast_luck", None)
        luck_value = fast_luck() if callable(fast_luck) else None
        if luck_value is None and isinstance(stats, dict):
            luck_value = getattr(stats.get("Luck"), "value", None)
        set_loot_rarity_card_values(labels, luck_value, loot_stats)

    # -- construction -----------------------------------------------------

    def build(self):
        """Create this tab's widgets and add it to the parent tab bar.

        Was `_build_live_stats_tab` on the mixin, called from
        `gui_layout._build_layout`. Same body, same order, same position in the
        tab bar -- the widgets it assigns are this object's now rather than
        `MegabonkApp`'s.
        """
        self._root = QWidget()
        player_layout = QVBoxLayout(self._root)
        player_scroll, _player_content, player_content_layout = _make_scroll_section()
        player_layout.addWidget(player_scroll)
        self._status_label = QLabel("Waiting for game...")
        player_content_layout.addWidget(self._status_label)
        # Step-18 pilot: the timeline strip is a component, not four more
        # attributes on the shared `self`. Its seven collaborators are named
        # here -- this is the composition root for it -- and it owns its Qt
        # widgets privately.
        def _select_snapshot(index: int) -> None:
            # Pin, so the next refresh tick does not repaint live values over
            # the snapshot the user just scrubbed to. Landing on the newest
            # snapshot un-pins instead: that is the affordance for "resume
            # following the run", and it means the pin can always be cleared
            # from the slider alone.
            #
            # Both values are app-layer state rather than this tab's --
            # `vod_capture` and `player_stats_refresh` write them too -- so
            # they go back through a callback instead of being assigned here.
            snapshots = self._vod_snapshots()
            self._on_snapshot_selected(
                index, pinned=pin_for_selection(index, len(snapshots))
            )
            self.display_player_stats_snapshot(snapshots[index])

        self._recording_timeline = RecordingTimelineView(
            recorder=self._vod_recorder,
            snapshots=self._vod_snapshots,
            selected_index=self._selected_snapshot_index,
            recording_armed=self._is_recording_armed,
            waiting_mode=self._recording_waiting_mode,
            on_toggle_recording=self._on_toggle_recording,
            on_snapshot_selected=_select_snapshot,
        )
        self._recording_timeline.install(player_content_layout)

        live_page = QWidget()
        live_page.setObjectName("LiveStatsPage")
        live_page_layout = QGridLayout(live_page)
        live_page_layout.setContentsMargins(0, 0, 0, 0)
        live_page_layout.setHorizontalSpacing(10)
        live_page_layout.setVerticalSpacing(0)

        live_main = QWidget()
        live_main.setObjectName("LiveStatsMain")
        live_main_layout = QVBoxLayout(live_main)
        live_main_layout.setContentsMargins(0, 0, 0, 0)
        live_main_layout.setSpacing(14)

        items_group = QGroupBox("Items")
        items_group.setObjectName("LiveStatsItems")
        items_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        items_group.setMinimumWidth(220)
        items_layout = QVBoxLayout(items_group)
        items_layout.setContentsMargins(11, 11, 11, 11)
        items_layout.setSpacing(8)

        items_meta = QHBoxLayout()
        items_meta.setContentsMargins(0, 0, 0, 0)
        items_rarity_label = QLabel("")
        items_rarity_label.setTextFormat(Qt.RichText)
        items_rarity_label.setObjectName("ItemsRaritySummary")
        items_rarity_label.setStyleSheet("font-size: 12px; background: transparent;")
        items_rarity_label.setVisible(False)
        items_meta.addWidget(items_rarity_label, 0, Qt.AlignLeft)
        items_meta.addStretch(1)
        items_sort_combo = CompactItemsSortComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            items_sort_combo.addItem(label, mode)
        items_sort_combo.setCurrentIndex(
            items_sort_combo.findData(ITEM_SORT_RARITY_DESC)
        )
        items_sort_combo.setVisible(False)
        items_meta.addWidget(items_sort_combo, 0, Qt.AlignRight | Qt.AlignVCenter)
        items_layout.addLayout(items_meta)

        items_chips_container = QWidget()
        items_chips_container.setObjectName("cardContent")
        FlowLayout(items_chips_container, margin=0, spacing=6)
        items_scroll = QScrollArea()
        items_scroll.setObjectName("LiveStatsItemsScroll")
        items_scroll.setWidgetResizable(True)
        items_scroll.setFrameShape(QFrame.NoFrame)
        items_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        items_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        items_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        items_scroll.setWidget(items_chips_container)
        items_layout.addWidget(items_scroll, 3)

        self._items_section = ItemsSectionView(
            group=items_group,
            label=None,
            rarity_label=items_rarity_label,
            toggle_btn=None,
            sort_combo=items_sort_combo,
            chips_container=items_chips_container,
            always_expanded=True,
            scroll_area=items_scroll,
        )
        items_sort_combo.currentIndexChanged.connect(
            lambda _index: self._items_section.on_sort_changed()
        )

        items_divider = QFrame()
        items_divider.setObjectName("LiveStatsItemsDivider")
        items_divider.setFrameShape(QFrame.HLine)
        items_layout.addWidget(items_divider)

        banishes_section = QWidget()
        banishes_section.setObjectName("LiveStatsBanishes")
        banishes_layout = QVBoxLayout(banishes_section)
        banishes_layout.setContentsMargins(*BANISHES_SECTION_MARGINS)
        banishes_layout.setSpacing(4)
        banishes_title = QLabel("BANISHES")
        banishes_title.setObjectName("LiveStatsBanishesTitle")
        banishes_layout.addWidget(banishes_title)
        self._banishes_label = QLabel("No banishes yet")
        self._banishes_label.setObjectName("LiveStatsBanishesText")
        self._banishes_label.setTextFormat(Qt.RichText)
        self._banishes_label.setWordWrap(True)
        banishes_layout.addWidget(self._banishes_label)
        self._banishes_chips_container = QWidget()
        self._banishes_chips_container.setObjectName("BanishesChips")
        FlowLayout(self._banishes_chips_container, margin=0, spacing=5)
        self._banishes_chips_container.setVisible(False)
        # Bounded, as in Recordings: the flow layout pushes a `minimumHeight`
        # onto its container per wrapped row, and that minimum comes straight
        # out of the item list's share of a panel of fixed height.
        banishes_chips_scroll = QScrollArea()
        banishes_chips_scroll.setObjectName("BanishesChipsScroll")
        banishes_chips_scroll.setWidgetResizable(True)
        banishes_chips_scroll.setFrameShape(QFrame.NoFrame)
        banishes_chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        banishes_chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        banishes_chips_scroll.setMinimumHeight(BANISHES_CHIPS_MAX_HEIGHT)
        banishes_chips_scroll.setMaximumHeight(BANISHES_CHIPS_MAX_HEIGHT)
        banishes_chips_scroll.setWidget(self._banishes_chips_container)
        banishes_chips_scroll.setVisible(False)
        banishes_layout.addWidget(banishes_chips_scroll)
        self._banishes_view = BanishesSectionView(
            label=self._banishes_label,
            chips_container=self._banishes_chips_container,
            chips_scroll=banishes_chips_scroll,
        )
        items_layout.addWidget(banishes_section)

        live_summary_grid = QGridLayout()
        live_summary_grid.setContentsMargins(0, 0, 0, 0)
        live_summary_grid.setHorizontalSpacing(8)
        live_summary_grid.setVerticalSpacing(8)
        chest_rate_group = QGroupBox("Run Summary")
        chest_rate_group.setObjectName("LiveStatsRunSummary")
        chest_rate_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        chest_rate_layout = QVBoxLayout(chest_rate_group)
        self._chests_per_minute_label = QLabel("Average chests/min: --")
        chest_rate_layout.addWidget(self._chests_per_minute_label)
        self._in_game_time_label = QLabel("In-Game Time: --")
        chest_rate_layout.addWidget(self._in_game_time_label)
        self._mob_kills_label = QLabel("Mob Kills: --")
        chest_rate_layout.addWidget(self._mob_kills_label)
        self._kps_averages_label = QLabel("KPS: --")
        chest_rate_layout.addWidget(self._kps_averages_label)
        self._level_label = QLabel("Level: --")
        chest_rate_layout.addWidget(self._level_label)
        for label in (
            self._chests_per_minute_label,
            self._in_game_time_label,
            self._mob_kills_label,
            self._kps_averages_label,
            self._level_label,
        ):
            label.setWordWrap(True)
        _apply_summary_label_padding(
            self._chests_per_minute_label,
            self._in_game_time_label,
            self._mob_kills_label,
            self._kps_averages_label,
            self._level_label,
        )
        live_summary_grid.addWidget(chest_rate_group, 0, 0)
        live_stage_summary_group = QGroupBox("Stage Summary")
        live_stage_summary_group.setObjectName("LiveStatsStageSummary")
        live_stage_summary_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        live_stage_summary_layout = QGridLayout(live_stage_summary_group)
        live_stage_summary_layout.setContentsMargins(10, 10, 10, 10)
        live_stage_summary_layout.setHorizontalSpacing(10)
        live_stage_summary_layout.setVerticalSpacing(4)
        for column, header in enumerate(("Stage", "Time", "Kills", "Items")):
            label = QLabel(header)
            label.setStyleSheet("font-weight: 700; color: #F3F4F6; background: transparent;")
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            live_stage_summary_layout.addWidget(label, 0, column)
        self._stage_summary_labels = []
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
            live_stage_summary_layout.addWidget(stage_label, index + 1, 0)
            live_stage_summary_layout.addWidget(time_label, index + 1, 1)
            live_stage_summary_layout.addWidget(kills_label, index + 1, 2)
            live_stage_summary_layout.addWidget(items_label, index + 1, 3)
            self._stage_summary_labels.append(
                {
                    "stage": stage_label,
                    "time": time_label,
                    "kills": kills_label,
                    "items": items_label,
                }
            )
        live_stage_summary_layout.setColumnStretch(0, 1)
        live_stage_summary_layout.setColumnStretch(1, 2)
        live_stage_summary_layout.setColumnStretch(2, 1)
        live_stage_summary_layout.setColumnStretch(3, 1)
        live_summary_grid.addWidget(live_stage_summary_group, 0, 1)
        self._powerups_group = QGroupBox("Powerups")
        self._powerups_group.setObjectName("LiveStatsPowerups")
        self._powerups_group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        live_powerups_layout = QVBoxLayout(self._powerups_group)
        self._powerup_labels = {}
        for effect_name in ("Rage", "Clock", "Shield", "Stonks"):
            label = QLabel(f"{effect_name}: --")
            label.setWordWrap(True)
            _apply_summary_label_padding(label)
            live_powerups_layout.addWidget(label)
            self._powerup_labels[effect_name] = label
        live_summary_grid.addWidget(self._powerups_group, 0, 2)
        for column in range(3):
            live_summary_grid.setColumnStretch(column, 1)
        live_main_layout.addLayout(live_summary_grid)
        self._detail_tabs = FullWidthTabWidget()
        self._detail_tabs.setObjectName("subTabs")
        # The detail pages scroll their own contents. Their card grids must not
        # enlarge the whole Live Stats page and create a second outer scrollbar.
        self._detail_tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        player_stats_tab = QWidget()
        player_stats_tab_layout = QVBoxLayout(player_stats_tab)
        self._stats_expanded_toggle = LabeledSwitch("Expanded")
        self._stats_expanded_toggle.setObjectName("LiveStatsExpandedToggle")
        self._stats_expanded_toggle.setChecked(
            bool(config.user_config.get(LIVE_STATS_EXPANDED_CONFIG_KEY, False))
        )
        self._stats_expanded_toggle.setToolTip(
            "Show the full stat names in detailed label/value rows"
        )
        self._detail_tabs.setHeaderControl(self._stats_expanded_toggle)
        player_stats_scroll, _player_stats_scroll_content, player_stats_scroll_layout = _make_scroll_section()
        player_stats_tab_layout.addWidget(player_stats_scroll)

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
                self._compact_stat_value_rows[spec.label] = value_label
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
                self._stat_value_rows[spec.label] = value_label
                group_layout.addRow(name_label, value_label)
            expanded_stats_grid.add_card(stat_group)

        compact_stats_grid.setVisible(False)
        self._stats_expanded_toggle.toggled.connect(compact_stats_grid.setHidden)
        self._stats_expanded_toggle.toggled.connect(expanded_stats_grid.setVisible)
        self._stats_expanded_toggle.toggled.connect(
            self._save_stats_expanded_preference
        )
        # Both grids join the layout **before** either is made visible, and that
        # order is the whole point. `_ResponsiveCardGrid` is built parentless, so
        # showing one here -- which `setHidden(False)` does whenever the toggle
        # is off -- gave it a real top-level window, titled with the application
        # name because the widget has none of its own. `addWidget` reparented it
        # ~20 ms later and the window died. That is the blank `BonkScanner`
        # window that flashed before the real one at every start; Recordings had
        # its own copy of these lines and its own flash.
        player_stats_scroll_layout.addWidget(compact_stats_grid)
        player_stats_scroll_layout.addWidget(expanded_stats_grid)
        compact_stats_grid.setHidden(self._stats_expanded_toggle.isChecked())
        expanded_stats_grid.setVisible(self._stats_expanded_toggle.isChecked())
        player_stats_scroll_layout.addStretch(1)
        # The Loot tab: the chests card as it was, and the rarity card beside
        # it. Both say "Expected" and they mean different things -- key procs
        # there, items per tier here -- so the group titles say which, which is
        # the labelling-apart the design asks for without touching the chests
        # card's own layout.
        loot_tab = QWidget()
        loot_tab_layout = QVBoxLayout(loot_tab)
        loot_scroll, _loot_scroll_content, loot_scroll_layout = _make_scroll_section()
        loot_tab_layout.addWidget(loot_scroll)
        loot_grid = QGridLayout()
        loot_grid.setContentsMargins(0, 0, 0, 0)
        loot_grid.setHorizontalSpacing(8)
        loot_grid.setVerticalSpacing(8)

        chests_group = QGroupBox("Chests (Expected = key procs)")
        chests_group_layout = QVBoxLayout(chests_group)
        chests_card, self._chests_card_values = _build_chests_stats_card()
        chests_card.setObjectName("StatCardInner")
        chests_group_layout.addWidget(chests_card)
        loot_grid.addWidget(chests_group, 0, 0)

        rarity_group = QGroupBox("Item Rarity (Expected = items by tier)")
        rarity_group_layout = QVBoxLayout(rarity_group)
        rarity_card, self._loot_rarity_card_values = _build_loot_rarity_card()
        rarity_card.setObjectName("StatCardInner")
        rarity_group_layout.addWidget(rarity_card)
        loot_grid.addWidget(rarity_group, 0, 1)

        for column in range(2):
            loot_grid.setColumnStretch(column, 1)
        loot_scroll_layout.addLayout(loot_grid)
        loot_scroll_layout.addStretch(1)

        weapons_tab = QWidget()
        weapons_tab_layout = QVBoxLayout(weapons_tab)
        weapons_status_label = QLabel("Waiting for weapon data...")
        weapons_status_label.setWordWrap(True)
        weapons_tab_layout.addWidget(weapons_status_label)
        player_weapons_scroll, _player_weapons_scroll_content, player_weapons_scroll_layout = _make_scroll_section()
        player_weapons_scroll_layout.setContentsMargins(0, 0, 0, 0)
        weapons_tab_layout.addWidget(player_weapons_scroll)
        tomes_tab = QWidget()
        tomes_tab_layout = QVBoxLayout(tomes_tab)
        tomes_status_label = QLabel("Waiting for tome data...")
        tomes_status_label.setWordWrap(True)
        tomes_tab_layout.addWidget(tomes_status_label)
        player_tomes_scroll, _player_tomes_scroll_content, player_tomes_scroll_layout = _make_scroll_section()
        player_tomes_scroll_layout.setContentsMargins(0, 0, 0, 0)
        tomes_tab_layout.addWidget(player_tomes_scroll)
        chaos_tab = QWidget()
        chaos_tab_layout = QVBoxLayout(chaos_tab)
        chaos_status_label = QLabel("Waiting for Chaos Tome data...")
        chaos_status_label.setWordWrap(True)
        chaos_tab_layout.addWidget(chaos_status_label)
        player_chaos_scroll, _player_chaos_scroll_content, player_chaos_scroll_layout = _make_scroll_section()
        player_chaos_scroll_layout.setContentsMargins(0, 0, 0, 0)
        chaos_tab_layout.addWidget(player_chaos_scroll)
        damage_sources_tab = QWidget()
        damage_sources_tab_layout = QVBoxLayout(damage_sources_tab)
        damage_sources_status_label = QLabel("Waiting for damage source data...")
        damage_sources_status_label.setWordWrap(True)
        damage_sources_tab_layout.addWidget(damage_sources_status_label)
        player_damage_sources_scroll, _player_damage_sources_scroll_content, player_damage_sources_scroll_layout = _make_scroll_section()
        player_damage_sources_scroll_layout.setContentsMargins(0, 0, 0, 0)
        damage_sources_tab_layout.addWidget(player_damage_sources_scroll)
        build_progression_tab = QWidget()
        build_progression_layout = QVBoxLayout(build_progression_tab)
        build_progression_layout.setContentsMargins(8, 8, 8, 8)
        build_progression_layout.setSpacing(10)

        build_actions = QHBoxLayout()
        build_eyebrow = QLabel("LIVE BUILD")
        build_eyebrow.setObjectName("kpiLabel")
        build_actions.addWidget(build_eyebrow)
        build_actions.addStretch(1)
        build_help = QPushButton("How it works")
        build_help.clicked.connect(lambda: BuildProgressionHelpDialog(self._root).exec())
        build_configure = QPushButton("Configure")
        build_configure.setObjectName("primary")
        build_configure.clicked.connect(self._open_build_progression_settings)
        build_actions.addWidget(build_help)
        build_actions.addWidget(build_configure)
        build_progression_layout.addLayout(build_actions)

        build_card = QFrame()
        build_card.setObjectName("BuildProgressionCard")
        build_card_layout = QVBoxLayout(build_card)
        build_card_layout.setContentsMargins(14, 13, 14, 13)
        build_card_layout.setSpacing(8)

        build_card_header = QHBoxLayout()
        build_card_header.setSpacing(8)
        self._build_progression_header = QLabel("Build Progression")
        self._build_progression_header.setObjectName("BuildProgressionName")
        build_card_header.addWidget(self._build_progression_header, 1)
        self._build_progression_progress = QLabel("NOT CONFIGURED")
        self._build_progression_progress.setObjectName("BuildProgressionProgress")
        build_card_header.addWidget(self._build_progression_progress)
        self._build_progression_clock = QLabel()
        self._build_progression_clock.setObjectName("BuildProgressionClock")
        build_card_header.addWidget(self._build_progression_clock)
        build_card_layout.addLayout(build_card_header)

        build_rule = QFrame()
        build_rule.setObjectName("BuildProgressionDivider")
        build_card_layout.addWidget(build_rule)

        self._build_progression_empty = QLabel()
        self._build_progression_empty.setObjectName("BuildProgressionEmpty")
        self._build_progression_empty.setWordWrap(True)
        build_card_layout.addWidget(self._build_progression_empty)

        self._build_progression_complete = QLabel()
        self._build_progression_complete.setObjectName("BuildProgressionComplete")
        self._build_progression_complete.setAlignment(Qt.AlignCenter)
        self._build_progression_complete.hide()
        build_card_layout.addWidget(self._build_progression_complete)

        rows_host = QWidget()
        rows_host.setObjectName("BuildProgressionRows")
        self._build_progression_rows_layout = QVBoxLayout(rows_host)
        self._build_progression_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._build_progression_rows_layout.setSpacing(6)
        self._build_progression_rows_layout.setAlignment(Qt.AlignTop)
        self._build_progression_scroll = QScrollArea()
        self._build_progression_scroll.setObjectName("BuildProgressionScroll")
        self._build_progression_scroll.setWidgetResizable(True)
        self._build_progression_scroll.setFrameShape(QFrame.NoFrame)
        self._build_progression_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self._build_progression_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )
        self._build_progression_scroll.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding
        )
        self._build_progression_scroll.setWidget(rows_host)
        build_card_layout.addWidget(self._build_progression_scroll, 1)

        self._build_progression_footer = QLabel()
        self._build_progression_footer.setObjectName("BuildProgressionFooter")
        self._build_progression_footer.setAlignment(Qt.AlignRight)
        build_card_layout.addWidget(self._build_progression_footer)

        build_progression_layout.addWidget(build_card, 1)
        # These eight widgets are the component's, not the shared namespace's.
        # As `self.player_stats_weapons_layout` and friends they were reached
        # by composed name from `cards.py` behind guards that returned silently
        # on `None` -- the arrangement step 18 identified as the reason making
        # this tab's widgets private could break four panels without raising.
        self._stat_cards = StatCardsView(
            weapons_layout=player_weapons_scroll_layout,
            weapons_status_label=weapons_status_label,
            tomes_layout=player_tomes_scroll_layout,
            tomes_status_label=tomes_status_label,
            chaos_layout=player_chaos_scroll_layout,
            chaos_status_label=chaos_status_label,
            damage_sources_layout=player_damage_sources_scroll_layout,
            damage_sources_status_label=damage_sources_status_label,
            # Same waste as the Recordings tab, on a one-second refresh instead
            # of a scrub: four panels rebuilt every tick while at most one of
            # them is on screen, and the tab opens on Stats where none is.
            section_visible=section_visibility_over(lambda: self._detail_tabs),
        )
        self._detail_tabs.currentChanged.connect(
            lambda _index: (
                self._stat_cards.flush_pending(),
                self._stats_expanded_toggle.setVisible(
                    self._detail_tabs.currentIndex() == 0
                ),
            )
        )
        self._detail_tabs.addTab(player_stats_tab, "Stats")
        self._detail_tabs.addTab(loot_tab, "Loot")
        self._detail_tabs.addTab(weapons_tab, "Weapons")
        self._detail_tabs.addTab(tomes_tab, "Tomes")
        self._detail_tabs.addTab(chaos_tab, "Chaos")
        self._detail_tabs.addTab(damage_sources_tab, "Damage Sources")
        self._detail_tabs.addTab(build_progression_tab, "Build Progression")
        self.refresh_build_progression()
        # QTabWidget otherwise derives the outer page's preferred height from
        # whichever child is current. Stats/Loot are taller than the card tabs,
        # so switching could add or remove the outer scrollbar and visibly
        # shift the whole page. Reserve the tallest initial page once; every
        # detail page keeps its own scroll area for content beyond this height.
        self._detail_tabs.setMinimumHeight(self._detail_tabs.sizeHint().height())
        live_main_layout.addWidget(self._detail_tabs)
        player_stats_tab_layout.setContentsMargins(0, 0, 0, 0)
        weapons_tab_layout.setContentsMargins(0, 0, 0, 0)
        tomes_tab_layout.setContentsMargins(0, 0, 0, 0)
        chaos_tab_layout.setContentsMargins(0, 0, 0, 0)
        damage_sources_tab_layout.setContentsMargins(0, 0, 0, 0)
        loot_tab_layout.setContentsMargins(0, 0, 0, 0)

        live_page_layout.addWidget(live_main, 0, 0)
        live_page_layout.addWidget(items_group, 0, 1)
        live_page_layout.setColumnStretch(0, 3)
        live_page_layout.setColumnStretch(1, 1)
        live_page_layout.setRowStretch(0, 1)
        player_content_layout.addWidget(live_page)
        self._tabview.addTab(self._root, "Live Stats")
        return self

    def format_live_powerups(self, stats) -> str:
        tracker = self._live_run_tracker()
        formatter = getattr(tracker, "format_powerups_summary", None)
        snapshot_reader = getattr(tracker, "powerups_snapshot", None)
        if callable(formatter) and callable(snapshot_reader):
            try:
                if getattr(snapshot_reader(), "available", False) is True:
                    return formatter(include_left_word=False)
            except Exception:
                pass
        return formatting.format_powerups_duration(stats)
