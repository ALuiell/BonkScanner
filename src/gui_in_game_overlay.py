"""The in-game overlay component and its composition root.

`InGameOverlayMixin` was seventeen hidden reads -- the second-worst ratio in
the tree, three assignments against thirty-one reads. Ten of the seventeen were
its own widgets, written onto it from `gui_in_game_overlay_settings.py`; the
other seven were four different owners' state discovered through the shared
`self`: the scanner thread, the VOD recorder, the live-run tracker, the two
window-focus helpers on `RunControlMixin`, and the Qt scheduler.

`InGameOverlay` takes those seven as constructor ports and owns the ten
widgets outright, so the class holds no ambient `self` at all. The window, the
timers and the widget geometry stay where step 24's roadmap entry puts them:
the window owns its widgets and its layout, this owns the cadence.

**Every port is a supplier, not a value**, the rule steps 20 and 23 both
follow. `live_run_tracker` is `None` until `initialize_overlay_runtime` runs
and the scanner thread is replaced on every start, so a value captured at
construction would freeze what the app had at build time -- which is what the
mixin's late `self` reads were doing correctly by accident.

The class is not a `MegabonkApp` base. `gui_app.py` keeps thin delegators for
the three external entries measured before the split: `stop_in_game_overlay`
(`gui_scanner.py`'s shutdown path, step 25),
`hotkey_toggle_in_game_overlay_edit` (`gui_run_control.py`'s hotkey binding,
step 25) and the tab, which `gui_layout.py` adds to the tab bar (step 26).
"""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QRect, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from app import config
from projections.in_game import project_in_game_overlay
from projections.in_game_html import (
    build_event_timer_overlay_html,
    build_kps_overlay_html_from_values,
    build_luck_rarity_overlay_html,
    build_powerups_overlay_html,
    build_stats_overlay_html,
    build_status_indicator_html,
    calculate_luck_rarity_probabilities,
)
from gui_in_game_overlay_settings import (
    InGameWidgetSettingsDialog,
    build_in_game_overlay_tab,
    update_in_game_overlay_status_ui,
)
from gui_in_game_overlay_window import InGameOverlayWindow

try:
    from gui_run_control import win32gui
except Exception:
    win32gui = None


class InGameOverlay:
    """The transparent in-game overlay: cadence, edit mode and its settings tab."""

    def __init__(
        self,
        *,
        tracker: Callable[[], Any],
        is_scanning: Callable[[], bool],
        is_recording: Callable[[], bool],
        is_game_window_active: Callable[[str], bool],
        find_game_window: Callable[[str], Any] | None,
        schedule: Callable[[Callable[[], None]], None],
        schedule_idle: Callable[[Callable[[], None]], None],
        widget_settings_dialog: Callable[["InGameOverlay", QWidget | None], Any] = InGameWidgetSettingsDialog,
        timer_factory: Callable[[], Any] = QTimer,
    ) -> None:
        self._tracker = tracker
        self._is_scanning = is_scanning
        self._is_recording = is_recording
        self._is_game_window_active = is_game_window_active
        self._find_game_window = find_game_window
        self._schedule = schedule
        self._schedule_idle = schedule_idle
        self._widget_settings_dialog = widget_settings_dialog

        # The tab and its nine checkboxes. `build_in_game_overlay_tab` writes
        # them onto this object; before the split it wrote them onto the app,
        # which is where ten of the seventeen hidden reads came from. Declared
        # here so the surface is readable without chasing the builder.
        self.tab_in_game_overlay: QWidget | None = None
        self.igo_status_label = None
        self.igo_toggle_btn = None
        self.igo_edit_btn = None
        self.igo_widget_settings_btn = None
        self.igo_auto_start_cb = None
        self.igo_scanner_cb = None
        self.igo_recording_cb = None
        self.igo_kps_cb = None
        self.igo_powerups_cb = None
        self.igo_luck_rarity_cb = None
        self.igo_stats_cb = None
        self.igo_event_timer_cb = None

        self.in_game_overlay_window: InGameOverlayWindow | None = None

        self.overlay_fast_timer = timer_factory()
        self.overlay_fast_timer.timeout.connect(self._overlay_fast_tick)
        self.overlay_fast_timer.setInterval(500)

        self.overlay_slow_timer = timer_factory()
        self.overlay_slow_timer.timeout.connect(self._overlay_slow_tick)
        self.overlay_slow_timer.setInterval(10000)

    # -- lifecycle ---------------------------------------------------------

    def start_runtime(self) -> None:
        """Defer window construction to the idle callback, as the mixin did."""
        self._schedule_idle(self._init_in_game_overlay)

    def _init_in_game_overlay(self) -> None:
        self.in_game_overlay_window = InGameOverlayWindow(self)

        if not config.IN_GAME_OVERLAY.get("auto_start", False):
            config.IN_GAME_OVERLAY["enabled"] = False

        if config.IN_GAME_OVERLAY["enabled"] and config.IN_GAME_OVERLAY.get("auto_start", False):
            self.start_in_game_overlay()

        self._update_igo_status_ui()

    def start_in_game_overlay(self, *, initial_refresh: bool = True) -> None:
        if not self.in_game_overlay_window:
            return
        self.overlay_fast_timer.start()
        self.overlay_slow_timer.start()
        if initial_refresh:
            became_visible = self._overlay_fast_tick()
            if not became_visible:
                self._overlay_slow_tick()

    def stop_in_game_overlay(self) -> None:
        if self.in_game_overlay_window:
            self.in_game_overlay_window.hide()
        self.overlay_fast_timer.stop()
        self.overlay_slow_timer.stop()

    def apply_in_game_overlay_settings(self) -> None:
        cfg = config.IN_GAME_OVERLAY
        if not self.in_game_overlay_window:
            return

        if cfg["enabled"]:
            # The window can already be visible from edit mode while the periodic
            # overlay timers are still stopped, so visibility is not a reliable
            # proxy for an active runtime.
            self.start_in_game_overlay(initial_refresh=False)
        else:
            self.stop_in_game_overlay()
            self._update_igo_status_ui()
            return

        for widget_id, widget_cfg in cfg["widgets"].items():
            widget = self.in_game_overlay_window.widgets.get(widget_id)
            if widget is None:
                continue
            if widget_id == "powerups":
                if not widget_cfg["enabled"]:
                    widget.setVisible(False)
            else:
                widget.setVisible(widget_cfg["enabled"])
            widget.update_scale(widget_cfg.get("scale", 1.0))
            if widget_id == "luck_rarity" and hasattr(widget, "set_show_bar"):
                widget.set_show_bar(widget_cfg.get("show_bar", True))
            if not self.in_game_overlay_window.edit_mode:
                widget.move(widget_cfg["x"], widget_cfg["y"])

        self._overlay_fast_tick()
        self._overlay_slow_tick()
        self._update_igo_status_ui()

    # -- geometry ----------------------------------------------------------

    def _in_game_overlay_target_geometry(self) -> QRect | None:
        if win32gui is not None and self._find_game_window is not None:
            try:
                game_window = self._find_game_window(config.PROCESS_NAME)
            except Exception:
                game_window = None
            if game_window:
                try:
                    get_client_rect = getattr(win32gui, "GetClientRect", None)
                    client_to_screen = getattr(win32gui, "ClientToScreen", None)
                    if callable(get_client_rect) and callable(client_to_screen):
                        client_left, client_top, client_right, client_bottom = get_client_rect(
                            game_window
                        )
                        left, top = client_to_screen(
                            game_window, (client_left, client_top)
                        )
                        right, bottom = client_to_screen(
                            game_window, (client_right, client_bottom)
                        )
                    else:
                        left, top, right, bottom = win32gui.GetWindowRect(game_window)
                except Exception:
                    game_window = None
                else:
                    width = max(0, int(right) - int(left))
                    height = max(0, int(bottom) - int(top))
                    if width > 0 and height > 0:
                        return QRect(int(left), int(top), width, height)

        overlay_window = self.in_game_overlay_window
        if overlay_window is None or not getattr(overlay_window, "edit_mode", False):
            return None

        screen = overlay_window.screen() if overlay_window is not None else None
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.geometry() if screen is not None else None

    def hotkey_toggle_in_game_overlay_edit(self) -> None:
        self._schedule(self._toggle_igo_edit_mode)

    # -- cadence -----------------------------------------------------------

    def _overlay_fast_tick(self) -> bool:
        if not self.in_game_overlay_window:
            return False

        cfg = config.IN_GAME_OVERLAY
        was_visible = self.in_game_overlay_window.isVisible()
        if not cfg.get("enabled", False) and not self.in_game_overlay_window.edit_mode:
            if self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.hide()
            return False

        if self.in_game_overlay_window.edit_mode:
            self.in_game_overlay_window.sync_geometry_to_target()
            if not self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.show()
        else:
            is_game_active = self._is_game_window_active(config.PROCESS_NAME)
            if is_game_active:
                self.in_game_overlay_window.sync_geometry_to_target()
                if not self.in_game_overlay_window.isVisible():
                    self.in_game_overlay_window.show()
            elif self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.hide()

        if not self.in_game_overlay_window.isVisible():
            return False

        widgets = self.in_game_overlay_window.widgets
        # The two status plaques, before the runtime snapshot is even read.
        #
        # They were on the 10 s tick, but neither reads game memory: `Scanner`
        # flips the instant the user starts or stops a scan, and `REC` flips
        # either on the record button or on `sync_run_state`, which the
        # `recording_lifecycle` task runs every second. A streamer starting a
        # recording watched the plaque appear up to ten seconds later.
        #
        # Placed above the `runtime_snapshot is None` return deliberately: no
        # game attached is exactly when a scan gets started or stopped, and that
        # early return is what kept the plaques frozen through it.
        self._refresh_in_game_overlay_status_widgets()
        runtime_snapshot_reader = getattr(self._tracker(), "runtime_snapshot", None)
        runtime_snapshot = (
            runtime_snapshot_reader() if callable(runtime_snapshot_reader) else None
        )
        if runtime_snapshot is None:
            return False
        projection = project_in_game_overlay(runtime_snapshot)
        if cfg["widgets"]["kps"]["enabled"]:
            metrics_cfg = cfg["widgets"]["kps"].get("metrics", ["instant"])
            widgets["kps"].set_text(
                build_kps_overlay_html_from_values(projection.kps, metrics_cfg)
            )

        # Retrieve snapshot and powerups map context to determine stage metadata
        latest_snapshot = projection.latest_snapshot
        is_graveyard = projection.is_graveyard

        stage_index = 0
        stage_time_seconds = 0.0
        stage_timer_seconds = 0.0
        if latest_snapshot is not None:
            if getattr(latest_snapshot, "stage_index", None) is not None:
                stage_index = int(latest_snapshot.stage_index)
            stage_time_seconds = float(
                getattr(latest_snapshot, "stage_duration_seconds", 0.0) or 0.0
            )
            stage_timer_seconds = float(
                getattr(
                    latest_snapshot,
                    "stage_timer_seconds",
                    getattr(latest_snapshot, "stage_time_seconds", 0.0),
                )
                or 0.0
            )

        # The stage context both the Event Timer and the Stats caps are read
        # against. `latest_snapshot` supplies it at the 10 s snapshot cadence;
        # the fast stage timer overrides it within ~1 s where it is available.
        # Named `active_` rather than `event_` because the Event Timer is no
        # longer its only consumer.
        active_stage_index = stage_index
        active_stage_time_seconds = stage_time_seconds
        active_stage_timer_seconds = stage_timer_seconds
        fast_stage_context = projection.fast_stage_timer
        if fast_stage_context is not None:
            if getattr(fast_stage_context, "stage_index", None) is not None:
                active_stage_index = int(fast_stage_context.stage_index)
            active_stage_timer_seconds = float(
                getattr(
                    fast_stage_context,
                    "stage_timer_seconds",
                    active_stage_timer_seconds,
                )
                or 0.0
            )

        if cfg["widgets"].get("stats", {}).get("enabled", False):
            selected_stats = cfg["widgets"]["stats"].get("selected_stats", ["Damage", "Difficulty", "XP Gain", "Luck"])
            # The *stats* here are the 10 s snapshot's and cannot be fresher,
            # but the stage index and stage timer are not decoration: they pick
            # the Difficulty and XP Gain caps inside `_build_in_game_stats_rows`.
            # Read against `latest_snapshot` they switched up to a snapshot late,
            # while the Event Timer beside them had already moved on the fast
            # context computed directly above. Caps now follow the same clock
            # the widget next to them does.
            html = build_stats_overlay_html(
                latest_snapshot,
                selected_stats,
                active_stage_index,
                active_stage_timer_seconds,
                active_stage_time_seconds,
                is_graveyard,
            )
            widgets["stats"].set_text(html)

        if cfg["widgets"].get("event_timer", {}).get("enabled", False):
            warning_seconds = cfg["widgets"]["event_timer"].get("warning_seconds", 15)
            graveyard_events_active = False
            graveyard_events_active = projection.graveyard_main_map_events_active

            html = build_event_timer_overlay_html(
                active_stage_index,
                active_stage_timer_seconds,
                active_stage_time_seconds,
                is_graveyard,
                warning_seconds,
                graveyard_main_map_events_active=graveyard_events_active,
                edit_mode=self.in_game_overlay_window.edit_mode,
            )
            widgets["event_timer"].set_text(html)

        if cfg["widgets"]["powerups"]["enabled"]:
            snapshot = projection.powerups
            html = build_powerups_overlay_html(
                snapshot,
                edit_mode=self.in_game_overlay_window.edit_mode,
            )
            if html:
                widgets["powerups"].set_text(html)
                widgets["powerups"].setVisible(True)
            else:
                widgets["powerups"].setVisible(False)

        became_visible = not was_visible and self.in_game_overlay_window.isVisible()
        if became_visible:
            self._refresh_in_game_overlay_slow_widgets(projection)
        return became_visible

    def _overlay_slow_tick(self) -> None:
        if not self.in_game_overlay_window or not self.in_game_overlay_window.isVisible():
            return

        tracker = self._tracker()
        runtime_snapshot = tracker.runtime_snapshot() if tracker is not None else None
        projection = project_in_game_overlay(runtime_snapshot) if runtime_snapshot is not None else None
        self._refresh_in_game_overlay_slow_widgets(projection)

    def _refresh_in_game_overlay_status_widgets(self) -> None:
        """The Scanner and REC plaques, both driven by app state rather than by
        a memory read, so they can be painted on every fast tick for free."""
        if not self.in_game_overlay_window:
            return
        widgets = self.in_game_overlay_window.widgets
        widget_cfg = config.IN_GAME_OVERLAY.get("widgets", {})

        if widget_cfg.get("scanner", {}).get("enabled", False):
            widgets["scanner"].set_text(
                build_status_indicator_html("Scanner", bool(self._is_scanning()))
            )

        if widget_cfg.get("recording", {}).get("enabled", False):
            widgets["recording"].set_text(
                build_status_indicator_html("REC", bool(self._is_recording()))
            )

    def _refresh_in_game_overlay_slow_widgets(self, projection=None) -> None:
        """The 10 s widgets. `luck_rarity` alone now: it reads
        `latest_snapshot.stats`, which cannot be fresher than the snapshot that
        carries it, so a slow paint of slow data is the correct pairing."""
        if not self.in_game_overlay_window:
            return

        widgets = self.in_game_overlay_window.widgets
        cfg = config.IN_GAME_OVERLAY
        widget_cfg = cfg.get("widgets", {})

        if widget_cfg.get("luck_rarity", {}).get("enabled", False):
            latest_snapshot = getattr(projection, "latest_snapshot", None) if projection is not None else None
            luck_stat = None
            if latest_snapshot is not None and isinstance(getattr(latest_snapshot, "stats", None), dict):
                luck_stat = latest_snapshot.stats.get("Luck")
            luck_value = getattr(luck_stat, "value", None)
            probabilities = calculate_luck_rarity_probabilities(luck_value)
            widget = widgets["luck_rarity"]
            if hasattr(widget, "set_probabilities"):
                widget.set_probabilities(
                    probabilities,
                    show_bar=widget_cfg.get("luck_rarity", {}).get("show_bar", True),
                )
            else:
                widget.set_text(build_luck_rarity_overlay_html(latest_snapshot))

    # -- the settings tab --------------------------------------------------

    def build(self) -> QWidget:
        """Build the In-Game Overlay tab and return it for the tab bar."""
        build_in_game_overlay_tab(self)
        return self.tab_in_game_overlay

    def _toggle_in_game_overlay(self) -> None:
        cfg = config.IN_GAME_OVERLAY
        cfg["enabled"] = not cfg["enabled"]
        self.apply_in_game_overlay_settings()
        config.save_config(config.user_config)

    def _update_igo_status_ui(self) -> None:
        update_in_game_overlay_status_ui(self)

    def _on_igo_settings_changed(self, *_args) -> None:
        cfg = config.IN_GAME_OVERLAY
        cfg["auto_start"] = self.igo_auto_start_cb.isChecked()
        cfg["widgets"]["scanner"]["enabled"] = self.igo_scanner_cb.isChecked()
        cfg["widgets"]["recording"]["enabled"] = self.igo_recording_cb.isChecked()
        cfg["widgets"]["kps"]["enabled"] = self.igo_kps_cb.isChecked()
        cfg["widgets"]["powerups"]["enabled"] = self.igo_powerups_cb.isChecked()
        cfg["widgets"]["luck_rarity"]["enabled"] = self.igo_luck_rarity_cb.isChecked()
        cfg["widgets"]["stats"]["enabled"] = self.igo_stats_cb.isChecked()
        cfg["widgets"]["event_timer"]["enabled"] = self.igo_event_timer_cb.isChecked()
        self.apply_in_game_overlay_settings()
        config.save_config(config.user_config)

    def _toggle_igo_edit_mode(self) -> None:
        if not self.in_game_overlay_window:
            return

        is_edit_mode = not self.in_game_overlay_window.edit_mode
        self.in_game_overlay_window.toggle_edit_mode(is_edit_mode)

        if is_edit_mode:
            self.igo_edit_btn.setText("Save Layout")
            self.igo_edit_btn.setStyleSheet("background-color: #22c55e; color: white;")
            if not self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.show()
        else:
            self.igo_edit_btn.setText("Edit Layout")
            self.igo_edit_btn.setStyleSheet("")
            self.apply_in_game_overlay_settings()
            config.save_config(config.user_config)

        self._update_igo_status_ui()

    def _open_igo_widget_settings_dialog(self) -> None:
        dialog = self._widget_settings_dialog(self, self.tab_in_game_overlay)
        dialog.exec()


def build_in_game_overlay(app: Any) -> InGameOverlay:
    """Wire the component to the app, one named port per measured owner.

    Every argument here was a hidden read before the split, and each names the
    owner the arch metric attributed it to:

    * `tracker`      -- `live_run_tracker`, built by `gui_overlay` (step 24c).
    * `is_scanning`  -- `Scanner`'s thread (step 25c).
    * `is_recording` -- `player_stats_vod_recorder`, `AppCoordinator`'s.
    * the two window helpers -- `RunControl`'s (step 25c).
    * `schedule` / `schedule_idle` -- the Qt scheduler on `MegabonkApp`.

    All seven are re-read on every call for the reason `build_twitch_session`
    records: the tracker is `None` until the overlay runtime initialises and
    the scanner thread is replaced on every start.

    Step 25c pointed three of them at the components instead of at the app.
    They were the only production readers of `scanner_thread`,
    `is_game_window_active` and `find_game_window` outside the two subjects, so
    repointing them is what let step 25 avoid keeping three app delegators
    whose sole caller was this function -- which is what the note above them
    said step 25 would do.
    """
    return InGameOverlay(
        tracker=lambda: getattr(app, "live_run_tracker", None),
        is_scanning=lambda: app._scanner.is_scanning(),
        is_recording=lambda: (
            getattr(app, "player_stats_vod_recorder", None) is not None
            and app.player_stats_vod_recorder.is_recording
        ),
        is_game_window_active=lambda process_name: app._run_control.is_game_window_active(process_name),
        find_game_window=lambda process_name: app._run_control.find_game_window(process_name),
        schedule=lambda callback: app.after(0, callback),
        schedule_idle=lambda callback: app.after_idle(callback),
    )
