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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from math import isfinite

from core.stats.types import PLAYER_STAT_GROUPS
from ui.shared import _apply_summary_label_padding, _make_scroll_section, _set_text
from ui.styles import ITEM_SORT_LABELS
from ui.tabs.player_stats.items_section import ItemsSectionView
from ui.tabs.player_stats.metrics import (
    LIVE_STATS_CARD_COLUMNS,
    LIVE_STATS_VALUE_WIDTH,
    _apply_player_stat_value_baseline,
    _apply_powerups_card_baselines,
    _apply_run_summary_baselines,
    _apply_stage_summary_column_baseline,
    _build_chests_stats_card,
    _retain_hidden_widget_size,
)
from ui.tabs.player_stats.recording_timeline import RecordingTimelineView
from ui.tabs.player_stats.stat_cards import StatCardsView
from ui.tabs.player_stats.summary_cards import (
    set_chests_card_values,
    set_stage_summary_labels,
)
from projections import formatting


def pin_for_selection(index: int, snapshot_count: int) -> bool:
    """Should scrubbing to `index` pin the view against live repaints?

    Selecting the newest snapshot resumes following the run; anything earlier
    pins. Module-level and pure so it is directly testable -- the caller is a
    closure inside `build`, which needs a built Qt tab to reach.
    """
    return index < snapshot_count - 1


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

        # Widgets, all created by `build`. Declared here so the set this tab
        # owns is readable in one place rather than scattered through 260
        # lines of builder.
        self._root = None
        self._status_label = None
        self._detail_tabs = None
        self._stat_value_rows: dict = {}
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

    def _reset_live_player_stats_ui(self, status_text: str, *, items_text: str = "--") -> None:
        _set_text(self._status_label, status_text)
        for label in self._stat_value_rows.values():
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
        _set_text(self._new_items_label, "Live snapshot")
        _set_text(self._banishes_label, "No banishes yet")
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
        get_chest_stats = getattr(self._live_run_tracker(), "get_chest_stats", None)
        if callable(get_chest_stats):
            self._update_live_chest_summary(get_chest_stats())
        if new_items_text is not None:
            _set_text(self._new_items_label, new_items_text)
        else:
            _set_text(self._new_items_label, "Live snapshot")
        _set_text(self._banishes_label, formatting.format_banishes_rich_text(banishes))
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

    def refresh_player_stats_timeline_ui(self, *, update_slider: bool = True):
        """Re-render the recording timeline strip.

        A `PlayerStatsView` operation with eight app-layer callers plus the two
        outside `app/` this module's header names; the rendering itself lives
        in `RecordingTimelineView`. The name and signature predate the pilot.
        """
        self._recording_timeline.refresh(update_slider=update_slider)

    def toggle_player_items_expanded(self) -> None:
        self._items_section.toggle_expanded()

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
        items_group = QGroupBox("Items")
        items_layout = QVBoxLayout(items_group)
        items_label = QLabel("--")
        items_label.setTextFormat(Qt.RichText)
        items_label.setWordWrap(True)
        items_layout.addWidget(items_label)
        items_toggle_btn = QPushButton("Show more")
        items_toggle_btn.clicked.connect(self.toggle_player_items_expanded)
        items_toggle_btn.setProperty("class", "SmallGhostButton")
        _retain_hidden_widget_size(items_toggle_btn)
        items_toggle_btn.setEnabled(False)
        items_actions = QHBoxLayout()
        items_rarity_label = QLabel("")
        items_rarity_label.setTextFormat(Qt.RichText)
        items_rarity_label.setStyleSheet("font-size: 14px;")
        items_rarity_label.setVisible(False)
        items_sort_combo = QComboBox()
        for mode, label in ITEM_SORT_LABELS.items():
            items_sort_combo.addItem(label, mode)
        self._items_section = ItemsSectionView(
            group=items_group,
            label=items_label,
            rarity_label=items_rarity_label,
            toggle_btn=items_toggle_btn,
            sort_combo=items_sort_combo,
        )
        items_sort_combo.currentIndexChanged.connect(
            lambda _index: self._items_section.on_sort_changed()
        )
        items_actions.addWidget(items_toggle_btn, 0, Qt.AlignLeft)
        items_actions.addWidget(items_rarity_label, 0, Qt.AlignLeft)
        items_actions.addStretch(1)
        items_actions.addWidget(QLabel("Sort:"))
        items_actions.addWidget(items_sort_combo)
        items_layout.addLayout(items_actions)
        player_content_layout.addWidget(items_group)
        live_summary_grid = QGridLayout()
        live_summary_grid.setContentsMargins(0, 0, 0, 0)
        live_summary_grid.setHorizontalSpacing(8)
        live_summary_grid.setVerticalSpacing(8)
        chest_rate_group = QGroupBox("Run Summary")
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
        live_summary_grid.addWidget(chest_rate_group, 0, 0)
        live_stage_summary_group = QGroupBox("Stage Summary")
        live_stage_summary_layout = QGridLayout(live_stage_summary_group)
        live_stage_summary_layout.setContentsMargins(10, 10, 10, 10)
        live_stage_summary_layout.setHorizontalSpacing(10)
        live_stage_summary_layout.setVerticalSpacing(4)
        for column, header in enumerate(("Stage", "Time", "Kills", "Items")):
            label = QLabel(header)
            label.setStyleSheet("font-weight: 700; color: #F3F4F6;")
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
        _apply_stage_summary_column_baseline(
            live_stage_summary_layout,
            self._stage_summary_labels,
        )
        live_stage_summary_layout.setColumnStretch(0, 1)
        live_stage_summary_layout.setColumnStretch(1, 2)
        live_stage_summary_layout.setColumnStretch(2, 1)
        live_stage_summary_layout.setColumnStretch(3, 1)
        live_summary_grid.addWidget(live_stage_summary_group, 0, 1)
        self._powerups_group = QGroupBox("Powerups")
        live_powerups_layout = QVBoxLayout(self._powerups_group)
        self._powerup_labels = {}
        for effect_name in ("Rage", "Clock", "Shield", "Stonks"):
            label = QLabel(f"{effect_name}: --")
            _apply_summary_label_padding(label)
            live_powerups_layout.addWidget(label)
            self._powerup_labels[effect_name] = label
        _apply_powerups_card_baselines(self._powerup_labels)
        live_summary_grid.addWidget(self._powerups_group, 0, 2)
        live_banishes_group = QGroupBox("Banishes")
        live_banishes_layout = QVBoxLayout(live_banishes_group)
        self._banishes_label = QLabel("No banishes yet")
        self._banishes_label.setTextFormat(Qt.RichText)
        self._banishes_label.setWordWrap(True)
        _apply_summary_label_padding(self._banishes_label)
        live_banishes_layout.addWidget(self._banishes_label)
        live_summary_grid.addWidget(live_banishes_group, 0, 3)
        for column in range(4):
            live_summary_grid.setColumnStretch(column, 1)
        player_content_layout.addLayout(live_summary_grid)
        self._detail_tabs = QTabWidget()
        player_stats_tab = QWidget()
        player_stats_tab_layout = QVBoxLayout(player_stats_tab)
        player_stats_scroll, _player_stats_scroll_content, player_stats_scroll_layout = _make_scroll_section()
        player_stats_tab_layout.addWidget(player_stats_scroll)
        player_stats_grid = QGridLayout()
        player_stats_grid.setContentsMargins(0, 0, 0, 0)
        player_stats_grid.setHorizontalSpacing(8)
        player_stats_grid.setVerticalSpacing(8)
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
                self._stat_value_rows[spec.label] = value_label
                group_layout.addRow(spec.label, value_label)
            player_stats_grid.addWidget(
                stat_group,
                index // LIVE_STATS_CARD_COLUMNS,
                index % LIVE_STATS_CARD_COLUMNS,
            )
        placeholder_index = len(PLAYER_STAT_GROUPS)
        placeholder_group, self._chests_card_values = _build_chests_stats_card()
        player_stats_grid.addWidget(
            placeholder_group,
            placeholder_index // LIVE_STATS_CARD_COLUMNS,
            placeholder_index % LIVE_STATS_CARD_COLUMNS,
        )
        for column in range(LIVE_STATS_CARD_COLUMNS):
            player_stats_grid.setColumnStretch(column, 1)
        player_stats_scroll_layout.addLayout(player_stats_grid)
        player_stats_scroll_layout.addStretch(1)
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
        )
        self._detail_tabs.addTab(player_stats_tab, "Stats")
        self._detail_tabs.addTab(weapons_tab, "Weapons")
        self._detail_tabs.addTab(tomes_tab, "Tomes")
        self._detail_tabs.addTab(chaos_tab, "Chaos")
        self._detail_tabs.addTab(damage_sources_tab, "Damage Sources")
        player_content_layout.addWidget(self._detail_tabs)
        player_stats_tab_layout.setContentsMargins(0, 0, 0, 0)
        weapons_tab_layout.setContentsMargins(0, 0, 0, 0)
        tomes_tab_layout.setContentsMargins(0, 0, 0, 0)
        chaos_tab_layout.setContentsMargins(0, 0, 0, 0)
        damage_sources_tab_layout.setContentsMargins(0, 0, 0, 0)
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
