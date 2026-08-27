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

from collections import deque
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from typing import Any, Callable

from PySide6.QtCore import QPoint, QRect, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from app import config
from app.map_marker_hotkeys import MapMarkerHotkeyController
from app.map_marker_tracker import MapMarkerTracker
from core.map_markers import MapMarkerSnapshot
from infra.crash_journal import log_runtime_event
from infra.map_marker_input import WindowsMapMarkerInput
from projections.in_game import project_in_game_overlay
from projections.in_game_html import (
    build_build_progression_overlay_html,
    build_event_timer_overlay_html,
    build_kps_overlay_html_from_values,
    build_luck_rarity_overlay_html_for_probabilities,
    build_item_cooldowns_overlay_html,
    build_powerups_overlay_html,
    build_stats_overlay_html,
    build_status_indicator_html,
)
from projections.build_progression import build_progression_payload
# `calculate_luck_rarity_probabilities` is `core.luck_rarity`'s, and was reached
# through `projections.in_game_html` -- which imported it, never used it, and so
# was a re-export this module was the only reader of. Taken from its owner, on
# the import line this module already had for that owner.
from core.luck_rarity import (
    calculate_luck_rarity_probabilities,
    resolve_luck_expected_status_text,
)
from gui_in_game_overlay_settings import (
    IGO_SCALE_SPIN_ATTRIBUTES,
    IN_GAME_WIDGET_ROWS,
    InGameWidgetSettingsDialog,
    build_in_game_overlay_tab,
    refresh_in_game_overlay_hotkey_ui,
    update_in_game_overlay_status_ui,
)
from gui_in_game_overlay_window import InGameOverlayWindow

try:
    from gui_run_control import win32gui
except Exception:
    win32gui = None


def _build_map_marker_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="map-marker-reader")


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
        overlay_tab_active: Callable[[], bool] = lambda: True,
        rebind_hotkeys: Callable[[], None] = lambda: None,
        can_run: Callable[[], bool] = lambda: True,
        log: Callable[..., None] = lambda *_args, **_kwargs: None,
        widget_settings_dialog: Callable[["InGameOverlay", QWidget | None], Any] = InGameWidgetSettingsDialog,
        timer_factory: Callable[[], Any] = QTimer,
        map_marker_tracker_factory: Callable[[str], Any] = MapMarkerTracker,
        map_marker_executor_factory: Callable[[], Executor] = _build_map_marker_executor,
        map_marker_input_factory: Callable[[], Any] = WindowsMapMarkerInput,
        map_marker_hotkey_controller_factory: Callable[[Any], Any] = MapMarkerHotkeyController,
        build_progression_snapshot: Callable[[], Any] = lambda: None,
        open_build_progression_settings: Callable[[], None] = lambda: None,
    ) -> None:
        self._tracker = tracker
        self._build_progression_snapshot = build_progression_snapshot
        self._open_build_progression_settings = open_build_progression_settings
        self._is_scanning = is_scanning
        self._is_recording = is_recording
        self._is_game_window_active = is_game_window_active
        self._find_game_window = find_game_window
        self._schedule = schedule
        self._schedule_idle = schedule_idle
        # Two new ports, both for the tab rather than for the overlay window:
        # one so the preview only repaints while it is being looked at, one so
        # an edited hotkey takes effect without a restart. Defaulted because the
        # suite builds this component without an app.
        self._overlay_tab_active = overlay_tab_active
        self._rebind_hotkeys = rebind_hotkeys
        self._can_run = can_run
        self._log = log
        self._widget_settings_dialog = widget_settings_dialog
        self._map_marker_tracker = map_marker_tracker_factory(config.PROCESS_NAME)
        self._map_marker_executor_factory = map_marker_executor_factory
        self._map_marker_executor: Executor | None = None
        self._map_marker_future: Future[MapMarkerSnapshot] | None = None
        self._map_marker_future_generation = 0
        self._map_marker_close_future: Future[Any] | None = None
        self._map_marker_generation = 0
        self._map_marker_pending_poll: dict[str, Any] | None = None
        self._map_marker_pending_placements: deque[
            tuple[str, float, float, float]
        ] = deque()
        self._map_marker_latest_snapshot = MapMarkerSnapshot()
        self._map_marker_worker_active = False
        self._map_marker_worker_shutdown = False
        self._map_marker_input = map_marker_input_factory()
        self._map_marker_hotkeys = map_marker_hotkey_controller_factory(
            self._map_marker_input
        )

        # The tab and its nine checkboxes. `build_in_game_overlay_tab` writes
        # them onto this object; before the split it wrote them onto the app,
        # which is where ten of the seventeen hidden reads came from. Declared
        # here so the surface is readable without chasing the builder.
        self.tab_in_game_overlay: QWidget | None = None
        self.igo_hero = None
        self.igo_status_label = None
        self.igo_toggle_btn = None
        self.igo_hotkey_entry = None
        self.igo_target_window_label = None
        self.igo_widget_settings_btn = None
        self.igo_auto_start_cb = None
        self.igo_scanner_cb = None
        self.igo_recording_cb = None
        self.igo_kps_cb = None
        self.igo_powerups_cb = None
        self.igo_luck_rarity_cb = None
        self.igo_stats_cb = None
        self.igo_event_timer_cb = None
        self.igo_item_cooldowns_cb = None
        self.igo_build_progression_cb = None
        self.igo_map_markers_cb = None
        self.igo_map_markers_scale_spin = None
        self.igo_map_markers_summary = None
        self.igo_map_markers_settings_btn = None

        self.in_game_overlay_window: InGameOverlayWindow | None = None
        self._shutting_down = False
        self._map_marker_tick_active = False
        self._overlay_fast_tick_active = False

        # The regular overlay no longer needs its old 10 s companion timer.
        # Map markers use a separate 25 ms timer because a nearby interactable
        # may only remain current for a fraction of a second.
        self.overlay_fast_timer = timer_factory()
        self.overlay_fast_timer.timeout.connect(self._overlay_fast_tick)
        self.overlay_fast_timer.setInterval(500)
        self.map_marker_timer = timer_factory()
        self.map_marker_timer.timeout.connect(self._map_marker_tick)
        self.map_marker_timer.setInterval(25)

    # -- lifecycle ---------------------------------------------------------

    def start_runtime(self) -> None:
        """Defer window construction to the idle callback, as the mixin did."""
        if not self._runtime_available():
            return
        self._schedule_idle(self._init_in_game_overlay)

    def _init_in_game_overlay(self) -> None:
        if not self._runtime_available() or self.in_game_overlay_window is not None:
            return
        window = None
        try:
            window = InGameOverlayWindow(self)
            self.in_game_overlay_window = window
            # Capture the exact wrapper.  The QObject passed by ``destroyed``
            # is not guaranteed to be the same Python wrapper, and an old
            # window must never clear a replacement created after it.
            window.destroyed.connect(
                lambda *_args, expected=window: (
                    self._on_in_game_overlay_window_destroyed(expected)
                )
            )

            # ``enabled`` is the current runtime state, not a second startup
            # preference. A user can enable auto-start while the overlay is stopped,
            # which persists ``auto_start=True`` beside ``enabled=False``. Requiring
            # both values here made that perfectly valid combination skip startup.
            # At process start the preference decides the initial runtime state.
            auto_start = bool(config.IN_GAME_OVERLAY.get("auto_start", False))
            config.IN_GAME_OVERLAY["enabled"] = auto_start
            if auto_start:
                self.start_in_game_overlay()

            self._update_igo_status_ui()
        except Exception as exc:
            if self.in_game_overlay_window is window:
                self.in_game_overlay_window = None
            if window is not None:
                try:
                    window.parent_mixin = None
                    window.close()
                    window.deleteLater()
                except Exception:
                    pass
            config.IN_GAME_OVERLAY["enabled"] = False
            detail = f"{type(exc).__name__}: {exc}"
            log_runtime_event("in_game_overlay.initialize.failed", error=detail)
            self._log(
                f"[!] In-game overlay could not be initialized: {detail}",
                tag="warning",
            )

    def start_in_game_overlay(self, *, initial_refresh: bool = True) -> None:
        if not self._runtime_available() or not self.in_game_overlay_window:
            return
        self.overlay_fast_timer.start()
        self._sync_map_marker_runtime()
        if initial_refresh:
            self._overlay_fast_tick()

    def stop_in_game_overlay(self) -> None:
        # Stop is also used while a top-level Qt wrapper is being destroyed.
        # One stale widget must not prevent the worker and hotkeys from being
        # released, so every independent cleanup step gets its own guard.
        cleanup_errors = []
        for cleanup in (
            self.overlay_fast_timer.stop,
            self.map_marker_timer.stop,
            (
                self.in_game_overlay_window.hide
                if self.in_game_overlay_window is not None
                else None
            ),
            lambda: self._stop_map_marker_worker(wait=False),
            self._map_marker_hotkeys.reset,
            lambda: self._set_map_marker_snapshot(MapMarkerSnapshot()),
            lambda: self._set_map_marker_palette(None),
        ):
            if cleanup is None:
                continue
            try:
                cleanup()
            except Exception as exc:
                cleanup_errors.append(f"{type(exc).__name__}: {exc}")
        if cleanup_errors:
            log_runtime_event(
                "in_game_overlay.stop_cleanup.failed",
                errors=cleanup_errors,
            )
            self._log(
                "[!] In-game overlay stopped with cleanup warnings: "
                + "; ".join(cleanup_errors),
                tag="warning",
            )

    def shutdown(self) -> None:
        """Permanently stop callbacks and dispose the parentless tool window."""
        if self._shutting_down:
            return
        self._shutting_down = True
        self.stop_in_game_overlay()
        self._shutdown_map_marker_worker()

        window, self.in_game_overlay_window = self.in_game_overlay_window, None
        if window is None:
            return
        window.parent_mixin = None
        window.close()
        window.deleteLater()

    def _on_in_game_overlay_window_destroyed(self, expected=None) -> None:
        if expected is None or self.in_game_overlay_window is expected:
            self.in_game_overlay_window = None

    def _runtime_available(self) -> bool:
        if self._shutting_down:
            return False
        try:
            if not self._can_run():
                return False
        except Exception:
            return False
        app = QApplication.instance()
        return app is None or not app.closingDown()

    def apply_in_game_overlay_settings(self) -> None:
        if not self._runtime_available():
            return
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
            # These two hide themselves from the fast tick when they have
            # nothing to say -- no buff up, no timed item held -- so applying
            # settings may only ever *hide* them. Showing here would put an
            # empty box on screen until the next tick took it away again.
            if widget_id in ("powerups", "item_cooldowns"):
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
        self._update_igo_status_ui()

    # -- geometry ----------------------------------------------------------

    def _in_game_overlay_target_geometry(self) -> QRect | None:
        physical_geometry = self._in_game_overlay_physical_client_geometry()
        if physical_geometry is not None:
            return self._qt_geometry_from_physical(physical_geometry)

        overlay_window = self.in_game_overlay_window
        if overlay_window is None or not getattr(overlay_window, "edit_mode", False):
            return None

        screen = overlay_window.screen() if overlay_window is not None else None
        if screen is None:
            screen = QApplication.primaryScreen()
        return screen.geometry() if screen is not None else None

    def _qt_geometry_from_physical(self, geometry: QRect) -> QRect:
        """Translate a native Win32 rectangle into Qt device-independent pixels.

        Win32 reports the Unity client in physical pixels.  ``QWidget.setGeometry``
        consumes Qt logical pixels and scales them once more for the monitor.  At
        125%, passing a 2560x1440 native rectangle straight through therefore made
        the transparent overlay 3200x1800 physical pixels while the game remained
        2560x1440.

        Qt keeps each Windows screen's virtual-desktop origin in native screen
        coordinates, but scales the screen's size.  Preserve that origin and only
        scale the offset within the matching screen plus the rectangle's size.
        """

        screens_reader = getattr(QApplication, "screens", None)
        screens = list(screens_reader()) if callable(screens_reader) else []
        center = geometry.center()
        target_screen = None
        target_scale = 1.0
        for screen in screens:
            screen_geometry = screen.geometry()
            scale_reader = getattr(screen, "devicePixelRatio", None)
            scale = float(scale_reader()) if callable(scale_reader) else 1.0
            scale = max(0.01, scale)
            physical_screen = QRect(
                screen_geometry.left(),
                screen_geometry.top(),
                int(round(screen_geometry.width() * scale)),
                int(round(screen_geometry.height() * scale)),
            )
            if physical_screen.contains(center):
                target_screen = screen
                target_scale = scale
                break

        if target_screen is None:
            overlay_window = self.in_game_overlay_window
            target_screen = (
                overlay_window.screen() if overlay_window is not None else None
            )
            if target_screen is not None:
                scale_reader = getattr(target_screen, "devicePixelRatio", None)
                target_scale = (
                    float(scale_reader()) if callable(scale_reader) else 1.0
                )
                target_scale = max(0.01, target_scale)

        if target_screen is None:
            return geometry

        screen_geometry = target_screen.geometry()
        left = screen_geometry.left() + int(
            round((geometry.left() - screen_geometry.left()) / target_scale)
        )
        top = screen_geometry.top() + int(
            round((geometry.top() - screen_geometry.top()) / target_scale)
        )
        return QRect(
            left,
            top,
            int(round(geometry.width() / target_scale)),
            int(round(geometry.height() / target_scale)),
        )

    def _in_game_overlay_physical_client_geometry(self) -> QRect | None:
        """Return the Win32 client rectangle in physical desktop pixels."""

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
        return None

    def hotkey_toggle_in_game_overlay_edit(self) -> None:
        if not self._runtime_available():
            return
        self._schedule(self._toggle_igo_edit_mode)

    # -- cadence -----------------------------------------------------------

    def _sync_map_marker_runtime(self) -> None:
        enabled = bool(
            self._runtime_available()
            and config.IN_GAME_OVERLAY.get("enabled", False)
            and (config.IN_GAME_OVERLAY.get("map_markers", {}) or {}).get(
                "enabled", False
            )
        )
        if enabled:
            self.map_marker_timer.start()
            return
        self.map_marker_timer.stop()
        self._stop_map_marker_worker(wait=False)
        self._map_marker_hotkeys.reset()
        self._set_map_marker_snapshot(MapMarkerSnapshot())
        self._set_map_marker_palette(None)

    def _map_marker_tick(self) -> bool:
        # QDialog.exec() runs a nested event loop.  Updating a transparent
        # top-level window while another GUI operation is only half-finished is
        # unnecessary and makes lifetime/reentrancy bugs much harder to contain.
        if (
            not self._runtime_available()
            or self._map_marker_tick_active
            or QApplication.activeModalWidget() is not None
        ):
            return False

        self._map_marker_tick_active = True
        try:
            return self._map_marker_tick_once()
        except Exception as exc:
            # Never let an exception escape a high-frequency Qt timeout.  It
            # cannot catch a native abort, but it prevents a recoverable stale
            # wrapper/read failure from being delivered repeatedly by Qt.
            self.map_marker_timer.stop()
            try:
                self._stop_map_marker_worker(wait=False)
            except Exception:
                pass
            try:
                self._map_marker_hotkeys.reset()
            except Exception:
                pass
            detail = f"{type(exc).__name__}: {exc}"
            log_runtime_event("in_game_overlay.map_marker_tick.failed", error=detail)
            self._log(
                f"[!] Map Activity Markers stopped after an internal error: {detail}",
                tag="warning",
            )
            return False
        finally:
            self._map_marker_tick_active = False

    def _map_marker_tick_once(self) -> bool:
        window = self.in_game_overlay_window
        if window is None:
            return False
        marker_cfg = config.IN_GAME_OVERLAY.get("map_markers", {}) or {}
        if not (
            config.IN_GAME_OVERLAY.get("enabled", False)
            and marker_cfg.get("enabled", False)
        ):
            self._set_map_marker_snapshot(MapMarkerSnapshot())
            return False

        scale_reader = getattr(window, "devicePixelRatioF", None)
        display_scale = float(scale_reader()) if callable(scale_reader) else 1.0
        display_scale = max(0.01, display_scale)
        physical_geometry = self._in_game_overlay_physical_client_geometry()
        if physical_geometry is not None:
            client_height = physical_geometry.height()
            client_width = physical_geometry.width()
        else:
            height_reader = getattr(window, "height", None)
            width_reader = getattr(window, "width", None)
            logical_height = int(height_reader()) if callable(height_reader) else 0
            logical_width = int(width_reader()) if callable(width_reader) else 0
            client_height = max(1, int(round(logical_height * display_scale)))
            client_width = max(1, int(round(logical_width * display_scale)))
        snapshot = self._request_map_marker_sample(
            client_height=client_height,
            client_width=client_width,
            display_scale=display_scale,
            automatic_discovery=bool(
                marker_cfg.get("automatic_discovery", False)
            ),
        )

        cursor_x, cursor_y = self._map_marker_input.cursor_position()
        if snapshot.map_open and physical_geometry is not None:
            cursor_x = (cursor_x - physical_geometry.left()) / display_scale
            cursor_y = (cursor_y - physical_geometry.top()) / display_scale
        else:
            # Fallback for tests/non-Windows platforms. GetCursorPos uses native
            # pixels on Windows, whereas mapFromGlobal expects Qt logical pixels.
            map_from_global = getattr(window, "mapFromGlobal", None)
            if callable(map_from_global):
                local_cursor = map_from_global(
                    QPoint(
                        int(round(cursor_x / display_scale)),
                        int(round(cursor_y / display_scale)),
                    )
                )
                cursor_x, cursor_y = local_cursor.x(), local_cursor.y()

        gesture = self._map_marker_hotkeys.poll(
            marker_cfg.get("hotkeys"),
            snapshot,
            cursor_x=float(cursor_x),
            cursor_y=float(cursor_y),
            scale=float(marker_cfg.get("scale", 1.0)),
        )
        if gesture.placement is not None:
            action_id, placement_x, placement_y = gesture.placement
            snapshot = self._request_map_marker_placement(
                action_id,
                screen_x=placement_x,
                screen_y=placement_y,
                scale=float(marker_cfg.get("scale", 1.0)),
            )
        self._set_map_marker_palette(gesture.palette)

        # The normal overlay cadence is 500 ms, longer than many deliberate
        # quick Tab checks.  The 25 ms marker path makes the click-through window
        # ready as soon as the game's own mapsOpen flag flips.
        if snapshot.map_open and self._is_game_window_active(config.PROCESS_NAME):
            if not window.isVisible():
                window.sync_geometry_to_target()
                window.show()
        self._set_map_marker_snapshot(snapshot)
        return snapshot.map_open

    def _request_map_marker_sample(self, **kwargs) -> MapMarkerSnapshot:
        """Queue one latest-wins memory read and return without waiting for it."""
        if self._map_marker_worker_shutdown:
            return MapMarkerSnapshot()
        self._collect_map_marker_future()
        self._map_marker_pending_poll = dict(kwargs)
        self._pump_map_marker_worker()
        # Deterministic executors used by the test suite can finish inline.
        self._collect_map_marker_future()
        return self._map_marker_latest_snapshot

    def _request_map_marker_placement(
        self,
        action_id: str,
        *,
        screen_x: float,
        screen_y: float,
        scale: float,
    ) -> MapMarkerSnapshot:
        if self._map_marker_worker_shutdown:
            return MapMarkerSnapshot()
        self._collect_map_marker_future()
        self._map_marker_pending_placements.append(
            (action_id, float(screen_x), float(screen_y), float(scale))
        )
        self._pump_map_marker_worker()
        self._collect_map_marker_future()
        return self._map_marker_latest_snapshot

    def _pump_map_marker_worker(self) -> None:
        self._collect_map_marker_close_future()
        if (
            self._map_marker_worker_shutdown
            or self._map_marker_future is not None
            or self._map_marker_close_future is not None
        ):
            return
        executor = self._map_marker_executor
        if executor is None:
            executor = self._map_marker_executor_factory()
            self._map_marker_executor = executor

        self._map_marker_worker_active = True
        if self._map_marker_pending_placements:
            action_id, screen_x, screen_y, scale = (
                self._map_marker_pending_placements.popleft()
            )
            self._map_marker_future = executor.submit(
                self._place_map_marker_in_worker,
                action_id,
                screen_x=screen_x,
                screen_y=screen_y,
                scale=scale,
            )
            self._map_marker_future_generation = self._map_marker_generation
            return
        request, self._map_marker_pending_poll = self._map_marker_pending_poll, None
        if request is None:
            return
        self._map_marker_future = executor.submit(
            self._map_marker_tracker.tick,
            **request,
        )
        self._map_marker_future_generation = self._map_marker_generation

    def _place_map_marker_in_worker(
        self,
        action_id: str,
        *,
        screen_x: float,
        screen_y: float,
        scale: float,
    ) -> MapMarkerSnapshot:
        self._map_marker_tracker.place_manual_marker(
            action_id,
            screen_x=screen_x,
            screen_y=screen_y,
            scale=scale,
        )
        return self._map_marker_tracker.snapshot

    def _collect_map_marker_future(self) -> None:
        self._collect_map_marker_close_future()
        future = self._map_marker_future
        if future is None or not future.done():
            return
        self._map_marker_future = None
        generation = self._map_marker_future_generation
        try:
            snapshot = future.result()
        except Exception:
            # A Stop invalidates the operation.  Its failure is stale too and
            # must not disable a newly restarted marker runtime.
            if generation != self._map_marker_generation:
                return
            raise
        if (
            generation == self._map_marker_generation
            and isinstance(snapshot, MapMarkerSnapshot)
        ):
            self._map_marker_latest_snapshot = snapshot

    def _collect_map_marker_close_future(self) -> None:
        future = self._map_marker_close_future
        if future is None or not future.done():
            return
        self._map_marker_close_future = None
        try:
            future.result()
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            log_runtime_event("in_game_overlay.map_marker_close.failed", error=detail)
            self._log(
                f"[!] Map Activity Markers cleanup failed: {detail}",
                tag="warning",
            )
        finally:
            self._map_marker_worker_active = False

    def _stop_map_marker_worker(self, *, wait: bool = False) -> None:
        """Invalidate pending work and queue client cleanup without blocking Qt.

        The production executor has one worker, so ``close`` is serialized
        behind an in-flight memory read.  Interactive Stop therefore returns
        immediately, while terminal shutdown opts into draining both futures.
        """
        self._map_marker_generation += 1
        self._map_marker_pending_poll = None
        self._map_marker_pending_placements.clear()
        self._map_marker_latest_snapshot = MapMarkerSnapshot()

        executor = self._map_marker_executor
        if (
            self._map_marker_worker_active
            and executor is not None
            and self._map_marker_close_future is None
        ):
            try:
                self._map_marker_close_future = executor.submit(
                    self._map_marker_tracker.close
                )
            except Exception as exc:
                self._map_marker_worker_active = False
                detail = f"{type(exc).__name__}: {exc}"
                log_runtime_event(
                    "in_game_overlay.map_marker_close_submit.failed", error=detail
                )
                self._log(
                    f"[!] Map Activity Markers cleanup could not start: {detail}",
                    tag="warning",
                )

        # Inline executors complete during submit.  Collecting an already-done
        # future is nonblocking and keeps deterministic tests and state tidy.
        self._collect_map_marker_close_future()
        if not wait:
            return

        future = self._map_marker_future
        if future is not None:
            try:
                future.result()
            except Exception:
                pass
            self._map_marker_future = None
        close_future = self._map_marker_close_future
        if close_future is not None:
            try:
                close_future.result()
            except Exception:
                pass
            self._map_marker_close_future = None
        self._map_marker_worker_active = False

    def _shutdown_map_marker_worker(self) -> None:
        if self._map_marker_worker_shutdown:
            return
        self._stop_map_marker_worker(wait=True)
        self._map_marker_worker_shutdown = True
        executor, self._map_marker_executor = self._map_marker_executor, None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    def _set_map_marker_snapshot(self, snapshot: MapMarkerSnapshot) -> None:
        window = self.in_game_overlay_window
        layer = getattr(window, "map_marker_layer", None) if window is not None else None
        setter = getattr(layer, "set_snapshot", None)
        if callable(setter):
            marker_cfg = config.IN_GAME_OVERLAY.get("map_markers", {}) or {}
            setter(snapshot, scale=float(marker_cfg.get("scale", 1.0)))

    def _set_map_marker_palette(self, palette) -> None:
        window = self.in_game_overlay_window
        layer = getattr(window, "map_marker_layer", None) if window is not None else None
        setter = getattr(layer, "set_palette", None)
        if callable(setter):
            setter(palette)

    def _overlay_fast_tick(self) -> bool:
        # Modal dialogs run nested event loops; avoid updating a parentless
        # transparent window while their widget graph is mid-transition.
        if (
            not self._runtime_available()
            or self._overlay_fast_tick_active
            or QApplication.activeModalWidget() is not None
        ):
            return False

        self._overlay_fast_tick_active = True
        try:
            return self._overlay_fast_tick_once()
        except Exception as exc:
            config.IN_GAME_OVERLAY["enabled"] = False
            try:
                self.stop_in_game_overlay()
            except Exception:
                self.overlay_fast_timer.stop()
                self.map_marker_timer.stop()
            detail = f"{type(exc).__name__}: {exc}"
            log_runtime_event("in_game_overlay.fast_tick.failed", error=detail)
            self._log(
                f"[!] In-game overlay stopped after an internal error: {detail}",
                tag="warning",
            )
            try:
                self._update_igo_status_ui()
            except Exception:
                pass
            return False
        finally:
            self._overlay_fast_tick_active = False

    def _overlay_fast_tick_once(self) -> bool:
        if not self._runtime_available() or not self.in_game_overlay_window:
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
        # KPS is painted through the shared entry rather than off `projection`,
        # so the widget has one painter no matter which pass triggers it. See
        # `refresh_kps_widget` for why the combat pass is the one that matters.
        self.refresh_kps_widget()

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

        if cfg["widgets"].get("build_progression", {}).get("enabled", False):
            payload = build_progression_payload(
                self._build_progression_snapshot(),
                cfg["widgets"]["build_progression"],
            )
            html = build_build_progression_overlay_html(
                payload,
                edit_mode=self.in_game_overlay_window.edit_mode,
            )
            widgets["build_progression"].set_text(html)
            widgets["build_progression"].setVisible(
                bool(html) or self.in_game_overlay_window.edit_mode
            )

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

        # Its own widget rather than a block inside Powerups above, because that
        # one hides itself whenever no buff is up while an item cooldown runs
        # for the whole run -- sharing it would mean deleting that rule and
        # making Powerups permanently visible for everyone already using it.
        if cfg["widgets"].get("item_cooldowns", {}).get("enabled", False):
            html = build_item_cooldowns_overlay_html(
                projection,
                edit_mode=self.in_game_overlay_window.edit_mode,
            )
            if html:
                widgets["item_cooldowns"].set_text(html)
                widgets["item_cooldowns"].setVisible(True)
            else:
                widgets["item_cooldowns"].setVisible(False)

        self._refresh_in_game_overlay_luck_widget(projection)

        return not was_visible and self.in_game_overlay_window.isVisible()

    def refresh_kps_widget(self) -> None:
        """Paint the KPS widget. Called by whichever pass has fresh numbers.

        The instant value is published by ``track_ui_kps`` on each crossing of
        an integer ``run_timer`` second, inside the combat pass -- which runs on
        the fast tracker timer. Painting the widget from ``_overlay_fast_tick``
        put a *second*, unrelated 500 ms timer between that publication and the
        screen: the two are both wall-clock ``QTimer``s with independent phase,
        so they beat against each other and the moment the number changed
        wandered by up to a whole tick against the game's own counter, on top of
        the 0--0.5 s the poll phase already costs. The combat pass now calls
        this the moment it publishes.

        The fast tick still calls it too. That repaint is redundant while the
        combat pass is running -- same values, same HTML -- and it is the only
        thing that paints the widget when the pass is not: a widget switched on
        from the settings dialog mid-run, or the first frame after the window
        becomes visible, would otherwise sit blank until the next publication.

        Reads the four tracker accessors rather than ``runtime_snapshot``: the
        snapshot deep-copies the whole run state, which is the wrong price to
        pay on a path whose entire job is to be prompt.
        """
        window = self.in_game_overlay_window
        if window is None or not window.isVisible():
            return

        widget_cfg = (config.IN_GAME_OVERLAY.get("widgets", {}) or {}).get("kps", {}) or {}
        if not widget_cfg.get("enabled", False):
            return
        widget = window.widgets.get("kps")
        if widget is None:
            return

        tracker = self._tracker()
        if tracker is None:
            return

        def value(name: str) -> int | None:
            reader = getattr(tracker, name, None)
            return reader() if callable(reader) else None

        values = {
            "current": value("current_ui_kps"),
            "minute_avg": value("current_minute_avg_kps"),
            "five_minute_avg": value("current_five_minute_avg_kps"),
            "run_avg": value("current_run_avg_kps"),
        }
        widget.set_text(
            build_kps_overlay_html_from_values(
                values, widget_cfg.get("metrics", ["instant"])
            )
        )

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

    def _refresh_in_game_overlay_luck_widget(self, projection=None) -> None:
        """`luck_rarity`, on the fast tick.

        It was the only widget on a 10 s tick, and the pairing was correct at
        the time: it read `latest_snapshot.stats`, which cannot be fresher than
        the snapshot carrying it. Luck is now read on its own `LUCK` source by
        the 1 s loot pass, so the input is fresh and the slow paint was the only
        thing making the widget lag -- by up to a whole snapshot interval.

        `projection.luck` is `None` when that pass has not produced a reading
        yet (before the first one, or after a failed read expires). The 10 s
        snapshot's copy is the fallback, because a stale Luck is a better answer
        than none and the widget renders base probabilities without one.
        """
        if not self.in_game_overlay_window:
            return

        widgets = self.in_game_overlay_window.widgets
        cfg = config.IN_GAME_OVERLAY
        widget_cfg = cfg.get("widgets", {})

        if widget_cfg.get("luck_rarity", {}).get("enabled", False):
            latest_snapshot = getattr(projection, "latest_snapshot", None) if projection is not None else None
            luck_value = getattr(projection, "luck", None) if projection is not None else None
            if luck_value is None:
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
            if hasattr(widget, "set_expected"):
                loot = getattr(projection, "loot_stats", None) if projection is not None else None
                # A run the tracker cannot measure draws a status line rather
                # than showing zeros: both halves are wrong once the inventory
                # already held was absorbed into the item baseline, and a zero
                # that looks like a count is worse than no block. The row above
                # keeps rendering -- it depends on Luck alone.
                toggle_on = bool(widget_cfg.get("luck_rarity", {}).get("show_expected", False))
                available = bool(getattr(loot, "available", False))
                availability_decided = bool(getattr(loot, "availability_decided", False))
                widget.set_expected(
                    getattr(loot, "actual", None),
                    getattr(loot, "expected", None),
                    show_expected=toggle_on and available,
                    status_message=(
                        resolve_luck_expected_status_text(
                            available=available, availability_decided=availability_decided
                        )
                        if toggle_on
                        else None
                    ),
                    layout=widget_cfg.get("luck_rarity", {}).get("expected_layout", "column"),
                )
            else:
                # The probabilities are already resolved above, and resolving
                # them again from `latest_snapshot` would silently drop the fast
                # Luck this method exists to use.
                widget.set_text(
                    build_luck_rarity_overlay_html_for_probabilities(probabilities)
                )

    # -- the settings tab --------------------------------------------------

    def build(self) -> QWidget:
        """Build the In-Game Overlay tab and return it for the tab bar."""
        build_in_game_overlay_tab(self)
        return self.tab_in_game_overlay

    def _toggle_in_game_overlay(self) -> None:
        if not self._runtime_available():
            return
        cfg = config.IN_GAME_OVERLAY
        cfg["enabled"] = not cfg["enabled"]
        self.apply_in_game_overlay_settings()
        config.save_config(config.user_config)

    def _update_igo_status_ui(self) -> None:
        update_in_game_overlay_status_ui(self)

    def _on_igo_settings_changed(self, *_args) -> None:
        """Save everything the widgets table holds.

        It used to save only the seven enable toggles, because the scales and
        per-widget flags lived in a modal with a saver of its own. They are
        columns of the same table now, so there is one saver -- which is also
        one less way for the two to disagree about what a widget's settings are.
        """
        cfg = config.IN_GAME_OVERLAY
        widgets = cfg["widgets"]
        cfg["auto_start"] = self.igo_auto_start_cb.isChecked()

        for widget_id, _label, attribute in IN_GAME_WIDGET_ROWS:
            widgets[widget_id]["enabled"] = getattr(self, attribute).isChecked()
            spin = getattr(self, IGO_SCALE_SPIN_ATTRIBUTES[widget_id], None)
            if spin is not None:
                widgets[widget_id]["scale"] = spin.value()

        metrics = [
            key
            for attribute, key in (
                ("igo_kps_instant_cb", "instant"),
                ("igo_kps_60s_cb", "60s"),
                ("igo_kps_5m_cb", "5m"),
                ("igo_kps_run_cb", "run"),
            )
            if getattr(self, attribute, None) is not None
            and getattr(self, attribute).isChecked()
        ]
        # Never stored empty: the widget falls back to the instant reading, and
        # an empty list would make "I unticked them all" indistinguishable from
        # "I never chose".
        widgets["kps"]["metrics"] = metrics or ["instant"]

        if getattr(self, "igo_luck_bar_cb", None) is not None:
            widgets["luck_rarity"]["show_bar"] = self.igo_luck_bar_cb.isChecked()
            widgets["luck_rarity"]["show_expected"] = self.igo_luck_expected_cb.isChecked()
            widgets["luck_rarity"]["expected_layout"] = (
                self.igo_luck_layout_combo.currentData() or "column"
            )
        if getattr(self, "igo_event_warning_spin", None) is not None:
            widgets["event_timer"]["warning_seconds"] = self.igo_event_warning_spin.value()
        if getattr(self, "igo_build_max_rows_spin", None) is not None:
            widgets["build_progression"]["max_rows"] = self.igo_build_max_rows_spin.value()
            widgets["build_progression"]["show_completed"] = self.igo_build_completed_cb.isChecked()

        marker_cfg = cfg.setdefault("map_markers", {})
        if self.igo_map_markers_cb is not None:
            marker_cfg["enabled"] = self.igo_map_markers_cb.isChecked()
        if self.igo_map_markers_scale_spin is not None:
            marker_cfg["scale"] = self.igo_map_markers_scale_spin.value()

        self.apply_in_game_overlay_settings()
        config.save_config(config.user_config)

    def _toggle_igo_edit_mode(self) -> None:
        if not self._runtime_available() or not self.in_game_overlay_window:
            return

        is_edit_mode = not self.in_game_overlay_window.edit_mode
        self.in_game_overlay_window.toggle_edit_mode(is_edit_mode)

        # The tab's `Edit Layout` button is gone, and with it the caption swap
        # and the inline green stylesheet that lived here. Layout mode is
        # entered by hotkey; while it is on, the overlay itself shows a
        # `Save Layout & Exit` button over the game, which is where you are
        # looking at the time. The hero badge reads LAYOUT MODE meanwhile.
        if is_edit_mode:
            if not self.in_game_overlay_window.isVisible():
                self.in_game_overlay_window.show()
        else:
            self.apply_in_game_overlay_settings()
            config.save_config(config.user_config)

        self._update_igo_status_ui()

    # -- ports the tab needs -------------------------------------------------

    def is_in_game_overlay_tab_active(self) -> bool:
        """Whether this tab is the one on screen.

        The preview repaints on a timer and reads the game window while it does;
        a background tab doing that once a second is work for nobody.
        """
        return bool(self._overlay_tab_active())

    def refresh_hotkey_ui(self) -> None:
        """Re-read the layout hotkey into the field and the tip.

        Called when the Settings dialog saves. The tab and that dialog are both
        editors of this value, and only the one that saved knows it changed.
        """
        refresh_in_game_overlay_hotkey_ui(self)

    def rebind_hotkeys(self) -> None:
        """Re-register the hotkeys after this tab edited one of them.

        `setup_hotkeys` tears the previous manager down and builds a new one, so
        it is safe to call repeatedly -- and it is not optional: without it a
        saved key does nothing until restart, while the tip beside the field is
        already telling the user to press it.
        """
        self._rebind_hotkeys()

    def _open_igo_widget_settings_dialog(self) -> None:
        dialog = self._widget_settings_dialog(self, self.tab_in_game_overlay)
        try:
            dialog.exec()
        finally:
            delete_later = getattr(dialog, "deleteLater", None)
            if callable(delete_later):
                delete_later()

    def _open_build_progression_dialog(self) -> None:
        self._open_build_progression_settings()


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
        build_progression_snapshot=lambda: app.coordinator.build_progression_service.snapshot(),
        open_build_progression_settings=lambda: _open_build_progression_for_app(app),
        is_scanning=lambda: app._scanner.is_scanning(),
        is_recording=lambda: (
            getattr(app, "player_stats_vod_recorder", None) is not None
            and app.player_stats_vod_recorder.is_recording
        ),
        is_game_window_active=lambda process_name: app._run_control.is_game_window_active(process_name),
        find_game_window=lambda process_name: app._run_control.find_game_window(process_name),
        schedule=lambda callback: app.after(0, callback),
        schedule_idle=lambda callback: app.after_idle(callback),
        overlay_tab_active=lambda: app._is_in_game_overlay_tab_active(),
        rebind_hotkeys=lambda: app._run_control.setup_hotkeys(),
        can_run=lambda: not getattr(app, "_is_shutting_down", False),
        log=lambda *args, **kwargs: app.log(*args, **kwargs),
        timer_factory=lambda: QTimer(app.window),
    )


def _open_build_progression_for_app(app: Any) -> None:
    from ui.dialogs.build_progression import show_build_progression_manager

    show_build_progression_manager(
        app.coordinator.build_progression_settings,
        app.coordinator.build_progression_service,
        getattr(app, "window", None),
    )
