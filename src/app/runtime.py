"""Explicit application composition root and runtime lifecycle owner."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable

from app import config
from app.coordinator import AppCoordinator
from app.player_stats_memory import PlayerStatsMemory
from app.player_stats_refresh import PlayerStatsRefresh
from app.refresh_tasks import (
    RefreshTasks,
    build_refresh_coordinator,
    in_game_overlay_requires_player_stats_refresh,
)
from app.run_lifecycle import RunLifecycle
from app.shutdown import ShutdownDeadline, ShutdownReport
from app.snapshot_selection import player_stats_snapshot_is_pinned
from app.vod_capture import VodCapture
from app.vod_library import VodLibrary
from infra.crash_journal import log_runtime_event


@dataclass(frozen=True)
class AppRuntimePorts:
    shutdown_requested: Callable[[], bool]
    live_stats_tab_active: Callable[[], bool]
    twitch_bot_active: Callable[[], bool]
    overlay_refresh_wanted: Callable[[], bool]
    overlay_widget_refresh_active: Callable[[str], bool]
    read_disabled_items_cache: Callable[[], Any]
    write_disabled_items_cache: Callable[[Any], None]
    read_disabled_items_refresh_pending: Callable[[], bool]
    write_disabled_items_refresh_pending: Callable[[bool], None]
    player_stats_view: Callable[[], Any]
    overlay_view: Callable[[], Any]
    recordings_list_view: Callable[[], Any]
    snapshot_buffer: Callable[[], Any]
    reset_snapshot_buffer: Callable[[], None]
    selected_snapshot_index: Callable[[], Any]
    select_snapshot: Callable[[Any], None]
    snapshot_pinned: Callable[[], bool]
    sync_overlay_state: Callable[[], None]
    sync_in_game_kps: Callable[[], None]
    refresh_session_tracked_items: Callable[[], None]
    log: Callable[..., None]
    stop_hotkeys: Callable[[], Any]
    stop_in_game_overlay: Callable[..., Any]
    stop_scanner: Callable[..., Any]
    stop_twitch: Callable[..., Any]
    wait_background_threads: Callable[..., Any]
    close_overlay_server: Callable[..., Any]


class AppRuntime:
    """Own every non-widget runtime service and its teardown order."""

    def __init__(self, coordinator: Any, ports: AppRuntimePorts) -> None:
        self.coordinator = coordinator
        self.ports = ports
        self.snapshot_store = coordinator.snapshot_store
        self.live_run_tracker = coordinator.live_run_tracker
        self.vod_recorder = coordinator.vod_recorder
        self.vod_library: VodLibrary | None = None
        self._started = False
        self._shutdown_report: ShutdownReport | None = None
        self._shutdown_errors: list[tuple[str, str]] = []

        self.player_stats_memory = PlayerStatsMemory(
            read_stats_client=lambda: coordinator.player_stats_client,
            write_stats_client=lambda value: setattr(coordinator, "player_stats_client", value),
            read_game_data_client=lambda: coordinator.player_stats_game_data_client,
            write_game_data_client=lambda value: setattr(
                coordinator, "player_stats_game_data_client", value
            ),
            snapshot_store=lambda: self.snapshot_store,
            recording_active=lambda: bool(self.vod_recorder.is_recording),
            live_stats_tab_active=ports.live_stats_tab_active,
            twitch_bot_active=ports.twitch_bot_active,
            overlay_refresh_wanted=ports.overlay_refresh_wanted,
            read_disabled_items_cache=ports.read_disabled_items_cache,
            write_disabled_items_cache=ports.write_disabled_items_cache,
            read_disabled_items_refresh_pending=ports.read_disabled_items_refresh_pending,
            write_disabled_items_refresh_pending=ports.write_disabled_items_refresh_pending,
        )
        self.run_lifecycle = RunLifecycle(
            read_activity_state=lambda context=None: self.player_stats_memory._read_player_stats_runtime_activity_state_safe(context),
            read_game_state=lambda context=None: self.player_stats_memory._read_player_stats_runtime_game_state_safe(context),
            live_run_tracker=lambda: self.live_run_tracker,
        )
        self.vod_capture = VodCapture(
            recorder=lambda: self.vod_recorder,
            read_recording_state=lambda context=None: self.player_stats_memory._read_player_stats_recording_state_safe(context),
            read_run_timer=lambda context=None: self.player_stats_memory._read_player_stats_recording_run_timer_safe(context),
            close_game_data_client=self.player_stats_memory.close_player_stats_game_data_client,
            run_lifecycle=lambda: self.run_lifecycle,
            refresh_now=lambda **kwargs: self.player_stats_refresh.refresh_now(**kwargs),
            player_stats_view=ports.player_stats_view,
            recordings_list_view=ports.recordings_list_view,
            is_live_stats_tab_active=ports.live_stats_tab_active,
            log=ports.log,
            reset_snapshot_buffer=ports.reset_snapshot_buffer,
            read_character_identity=self._read_character_identity,
        )
        self.refresh_tasks = RefreshTasks(
            memory=lambda: self.player_stats_memory,
            lifecycle=lambda: self.run_lifecycle,
            view=ports.player_stats_view,
            capture=lambda: self.vod_capture,
            tracker=lambda: self.live_run_tracker,
            vod_recorder=lambda: self.vod_recorder,
            tab_active=ports.live_stats_tab_active,
            twitch_active=ports.twitch_bot_active,
            pinned=ports.snapshot_pinned,
            widget_refresh_active=ports.overlay_widget_refresh_active,
            sync_overlay_state=ports.sync_overlay_state,
            sync_in_game_kps=ports.sync_in_game_kps,
            refresh_session_tracked_items=ports.refresh_session_tracked_items,
            refresh_required=self._player_stats_refresh_required,
            build_progression_service=lambda: coordinator.build_progression_service,
        )
        self.refresh_coordinator = build_refresh_coordinator(
            self.refresh_tasks,
            refresh_full_snapshot=lambda **kwargs: self.player_stats_refresh.refresh_now(**kwargs),
        )
        coordinator.refresh_coordinator = self.refresh_coordinator
        self.player_stats_refresh = PlayerStatsRefresh(
            shutdown_requested=ports.shutdown_requested,
            lifecycle_service=lambda: self.run_lifecycle,
            coordinator_tick=self.refresh_coordinator.tick,
            memory_service=lambda: self.player_stats_memory,
            store=lambda: self.snapshot_store,
            live_stats_view=ports.player_stats_view,
            overlay=ports.overlay_view,
            recordings_list=ports.recordings_list_view,
            capture_service=lambda: self.vod_capture,
            live_tracker=lambda: self.live_run_tracker,
            recorder_handle=lambda: self.vod_recorder,
            tab_is_active=ports.live_stats_tab_active,
            snapshot_is_pinned=ports.snapshot_pinned,
            snapshot_buffer=ports.snapshot_buffer,
            select_snapshot=ports.select_snapshot,
            game_data_client=lambda: coordinator.player_stats_game_data_client,
            set_game_data_client=lambda value: setattr(
                coordinator, "player_stats_game_data_client", value
            ),
        )
        coordinator.player_stats_memory = self.player_stats_memory
        coordinator.run_lifecycle = self.run_lifecycle
        coordinator.vod_capture = self.vod_capture
        coordinator.refresh_tasks = self.refresh_tasks
        coordinator.player_stats_refresh = self.player_stats_refresh

    @classmethod
    def create(
        cls,
        *,
        ports: AppRuntimePorts,
        tracked_item_rules,
        stale_after_seconds: float,
        overlay_host: str,
        overlay_port: int,
        vod_interval_seconds: float,
    ) -> "AppRuntime":
        """Production composition root; concrete service creation stops here."""

        coordinator = AppCoordinator(
            tracked_item_rules=tracked_item_rules,
            stale_after_seconds=stale_after_seconds,
            overlay_host=overlay_host,
            overlay_port=overlay_port,
            vod_interval_seconds=vod_interval_seconds,
        )
        return cls(coordinator, ports)

    def start(
        self,
        *,
        schedule: Callable[[int, Callable[[], None]], Any],
        is_active: Callable[[], bool],
        interval_ms: Callable[[], int],
    ) -> None:
        if self._started:
            return
        self._started = True
        self.coordinator.start_refresh_loop(
            tick=self.player_stats_refresh.tick,
            schedule=schedule,
            is_active=is_active,
            interval_ms=interval_ms,
        )

    def create_vod_library(
        self,
        *,
        schedule: Callable[[Callable[[], None]], Any],
    ) -> VodLibrary:
        if self.vod_library is None:
            self.vod_library = VodLibrary(
                settings=self.coordinator.recording_settings,
                schedule=schedule,
            )
        return self.vod_library

    def diagnostics(self) -> tuple[Any, ...]:
        return self.refresh_coordinator.diagnostics()

    def shutdown(self, deadline: ShutdownDeadline) -> ShutdownReport:
        if self._shutdown_report is not None:
            return self._shutdown_report
        timed_out: list[str] = []
        self._step("hotkeys", self.ports.stop_hotkeys)
        self._step("refresh_loop", self.coordinator.stop_refresh_loop)
        overlay_result = self._step(
            "in_game_overlay", lambda: self._with_deadline(self.ports.stop_in_game_overlay, deadline)
        )
        timed_out.extend(f"in_game_overlay.{name}" for name in self._pending(overlay_result))
        self._step(
            "vod_recorder",
            lambda: self.vod_recorder.stop()
            if self.vod_recorder.is_recording
            else self.vod_recorder.close(),
        )
        if self.vod_library is not None:
            library_result = self._step(
                "vod_library", lambda: self.vod_library.shutdown(deadline)
            )
            timed_out.extend(
                f"vod_library.{name}" for name in self._pending(library_result)
            )
        server_result = self._step(
            "overlay_server",
            lambda: self._with_deadline(self.ports.close_overlay_server, deadline),
        )
        if server_result is False:
            timed_out.append("overlay_server")
        scanner_result = self._step(
            "scanner", lambda: self._with_deadline(self.ports.stop_scanner, deadline)
        )
        if scanner_result is False:
            timed_out.append("scanner")
        twitch_result = self._step(
            "twitch", lambda: self._with_deadline(self.ports.stop_twitch, deadline)
        )
        timed_out.extend(f"twitch.{name}" for name in self._pending(twitch_result))
        background_result = self._step(
            "background_threads",
            lambda: self._with_deadline(self.ports.wait_background_threads, deadline),
        )
        timed_out.extend(f"background.{name}" for name in self._pending(background_result))
        coordinator_errors = self._step("coordinator", self.coordinator.shutdown)
        if isinstance(coordinator_errors, (tuple, list)):
            self._shutdown_errors.extend(
                (f"coordinator.{name}", str(detail))
                for name, detail in coordinator_errors
            )
        self._shutdown_report = ShutdownReport(
            errors=tuple(self._shutdown_errors),
            timed_out_resources=tuple(dict.fromkeys(timed_out)),
            elapsed_ms=deadline.elapsed_ms(),
        )
        return self._shutdown_report

    def _player_stats_refresh_required(self) -> bool:
        return not self.run_lifecycle.completed_run and (
            self.ports.live_stats_tab_active()
            or self.vod_recorder.is_recording
            or self.vod_capture.is_recording_armed()
            or bool(getattr(config, "AUTO_START_RECORDING", False))
            or any(
                self.ports.overlay_widget_refresh_active(widget_id)
                for widget_id in (
                    "stage_summary",
                    "tracked_items",
                    "stats",
                    "banishes",
                    "build_progression",
                )
            )
            or in_game_overlay_requires_player_stats_refresh()
            or self.ports.twitch_bot_active()
        )

    def _read_character_identity(self) -> tuple[int, str] | None:
        try:
            client = self.player_stats_memory._get_player_stats_client()
            owner_stats = client.resolve_owner_stats()
            reader = getattr(client, "get_character_identity", None)
            if callable(reader):
                character_id, character_name = reader(owner_stats)
            else:
                reading = client.get_character_passive_reading(owner_stats)
                character_id, character_name = reading.character_id, reading.character_name
            if int(character_id) >= 0 and str(character_name).strip():
                return int(character_id), str(character_name).strip()
        except Exception:
            pass
        reader = getattr(self.live_run_tracker, "character_passive_snapshot", None)
        snapshot = reader() if callable(reader) else None
        if snapshot is not None and int(getattr(snapshot, "character_id", -1)) >= 0:
            name = str(getattr(snapshot, "character_name", "") or "").strip()
            if name:
                return int(snapshot.character_id), name
        return None

    def _step(self, name: str, callback: Callable[[], Any]) -> Any:
        try:
            return callback()
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            self._shutdown_errors.append((name, detail))
            log_runtime_event("application.shutdown.step_failed", step=name, error=detail)
            return None

    @staticmethod
    def _with_deadline(callback: Callable[..., Any], deadline: ShutdownDeadline) -> Any:
        try:
            parameters = tuple(inspect.signature(callback).parameters.values())
        except (TypeError, ValueError):
            return callback(deadline)
        return callback() if not parameters else callback(deadline)

    @staticmethod
    def _pending(result: Any) -> tuple[str, ...]:
        if result is False:
            return ("timeout",)
        if isinstance(result, (tuple, list, set)):
            return tuple(str(name) for name in result if name)
        return ()
