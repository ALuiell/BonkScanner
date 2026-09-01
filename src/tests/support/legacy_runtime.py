"""Explicit test fixture for legacy ``object.__new__(MegabonkApp)`` doubles.

Production has no owner-based service resolvers.  Older integration tests still
exercise a deliberately partial app shell, so this module wires its services in
one test-only composition root until those scenarios become component tests.
"""

from __future__ import annotations

from types import SimpleNamespace
import inspect

from app import config
from app.player_stats_memory import PlayerStatsMemory
from app.player_stats_refresh import PlayerStatsRefresh
from app.player_stats_view import PlayerStatsView, OverlayView, RecordingsListView
from app.refresh_coordinator import RefreshCoordinator
from app.refresh_tasks import (
    RefreshTasks,
    build_refresh_coordinator,
    in_game_overlay_requires_player_stats_refresh,
)
from app.run_lifecycle import RunLifecycle
from app.snapshot_selection import player_stats_snapshot_is_pinned
from app.snapshot_store import LiveSnapshotStore
from app.vod_capture import VodCapture
from app.shutdown import ShutdownReport


class _LegacyRuntime(SimpleNamespace):
    def __getattr__(self, name):
        if name == "ports":
            ports = SimpleNamespace(
                player_stats_view=lambda: player_stats_view(self.owner),
                overlay_view=lambda: overlay_view(self.owner),
                recordings_list_view=lambda: recordings_list_view(self.owner),
            )
            self.ports = ports
            return ports
        if name == "shutdown":
            return lambda deadline: _legacy_shutdown(self.owner, deadline)
        factories = {
            "snapshot_store": live_snapshot_store,
            "player_stats_memory": player_stats_memory,
            "run_lifecycle": run_lifecycle,
            "vod_capture": vod_capture,
            "refresh_tasks": refresh_tasks,
            "refresh_coordinator": ensure_refresh_coordinator,
            "player_stats_refresh": player_stats_refresh,
        }
        factory = factories.get(name)
        if factory is None:
            raise AttributeError(name)
        return factory(self.owner)


def _runtime(owner):
    runtime = owner.__dict__.get("runtime")
    if runtime is None:
        runtime = _LegacyRuntime(owner=owner)
        owner.__dict__["runtime"] = runtime
    return runtime


def _legacy_shutdown(owner, deadline) -> ShutdownReport:
    errors = []
    timed_out = []

    def step(name, callback):
        try:
            return callback()
        except Exception as exc:
            errors.append((name, f"{type(exc).__name__}: {exc}"))
            return None

    run_control = owner.__dict__.get("_run_control")
    if run_control is not None:
        step("hotkeys", run_control.stop_hotkeys)
    overlay = step("in_game_overlay", lambda: _deadline_call(owner.shutdown_in_game_overlay, deadline))
    timed_out.extend(f"in_game_overlay.{name}" for name in (overlay or ()) if name)
    recorder = owner.__dict__.get("player_stats_vod_recorder")
    if recorder is not None:
        step("vod_recorder", recorder.stop if recorder.is_recording else recorder.close)
    scanner = owner.__dict__.get("_scanner")
    if scanner is not None:
        scanner_result = step("scanner", lambda: _deadline_call(scanner.shutdown, deadline))
        if scanner_result is False:
            timed_out.append("scanner")
    twitch = step("twitch", lambda: _deadline_call(owner.stop_twitch_bot, deadline))
    timed_out.extend(f"twitch.{name}" for name in (twitch or ()) if name)
    wait_background = getattr(owner, "_wait_for_background_threads", None)
    if callable(wait_background):
        background = step("background_threads", lambda: wait_background(deadline=deadline))
        timed_out.extend(f"background.{name}" for name in (background or ()) if name)
    coordinator = owner.__dict__.get("coordinator")
    if coordinator is not None:
        step("coordinator", coordinator.shutdown)
    else:
        if scanner is not None:
            step("scanner_client", scanner.close_client)
        memory = player_stats_memory(owner)
        step("player_stats_client", memory.close_player_stats_client)
        step("player_stats_game_data_client", memory.close_player_stats_game_data_client)
    step("overlay_server", owner.close_overlay_server)
    return ShutdownReport(
        errors=tuple(errors),
        timed_out_resources=tuple(timed_out),
        elapsed_ms=deadline.elapsed_ms(),
    )


def _deadline_call(callback, deadline):
    try:
        parameters = tuple(inspect.signature(callback).parameters.values())
    except (TypeError, ValueError):
        return callback(deadline)
    return callback() if not parameters else callback(deadline)


def live_snapshot_store(owner) -> LiveSnapshotStore:
    runtime = _runtime(owner)
    store = runtime.__dict__.get("snapshot_store")
    if store is None:
        coordinator = owner.__dict__.get("coordinator")
        store = getattr(coordinator, "snapshot_store", None) or LiveSnapshotStore()
        runtime.snapshot_store = store
    return store


def player_stats_view(owner) -> PlayerStatsView:
    return owner.__dict__.get("_player_stats_view") or owner


def overlay_view(owner) -> OverlayView:
    return owner.__dict__.get("_overlay_view") or owner


def recordings_list_view(owner) -> RecordingsListView:
    return owner.__dict__.get("_recordings_list_view") or owner


def player_stats_memory(owner) -> PlayerStatsMemory:
    runtime = _runtime(owner)
    existing = runtime.__dict__.get("player_stats_memory")
    if existing is not None:
        return existing
    service = PlayerStatsMemory(
        read_stats_client=lambda: owner.player_stats_client,
        write_stats_client=lambda value: setattr(owner, "player_stats_client", value),
        read_game_data_client=lambda: owner.player_stats_game_data_client,
        write_game_data_client=lambda value: setattr(owner, "player_stats_game_data_client", value),
        snapshot_store=lambda: live_snapshot_store(owner),
        recording_active=lambda: owner.player_stats_vod_recorder.is_recording,
        live_stats_tab_active=lambda: owner._is_live_stats_tab_active(),
        twitch_bot_active=lambda: owner._is_twitch_bot_active(),
        overlay_refresh_wanted=lambda: owner.overlay_should_refresh_live_stats(),
        read_disabled_items_cache=lambda: getattr(owner, "player_stats_disabled_items_cache", None),
        write_disabled_items_cache=lambda value: setattr(owner, "player_stats_disabled_items_cache", value),
        read_disabled_items_refresh_pending=lambda: getattr(owner, "player_stats_disabled_items_refresh_pending", False),
        write_disabled_items_refresh_pending=lambda value: setattr(owner, "player_stats_disabled_items_refresh_pending", value),
    )
    runtime.player_stats_memory = service
    coordinator = owner.__dict__.get("coordinator")
    if coordinator is not None:
        coordinator.player_stats_memory = service
    return service


def run_lifecycle(owner) -> RunLifecycle:
    runtime = _runtime(owner)
    existing = runtime.__dict__.get("run_lifecycle")
    if existing is not None:
        return existing
    lifecycle = RunLifecycle(
        read_activity_state=lambda context=None: player_stats_memory(owner)._read_player_stats_runtime_activity_state_safe(context),
        read_game_state=lambda context=None: player_stats_memory(owner)._read_player_stats_runtime_game_state_safe(context),
        live_run_tracker=lambda: owner.live_run_tracker,
    )
    runtime.run_lifecycle = lifecycle
    return lifecycle


def _reset_snapshot_buffer(owner) -> None:
    owner.player_stats_vod_snapshots = []
    owner.player_stats_selected_snapshot_index = None
    owner.player_stats_snapshot_pinned = False


def _read_owner_character_identity(owner) -> tuple[int, str] | None:
    try:
        client = player_stats_memory(owner)._get_player_stats_client()
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
    tracker = getattr(owner, "live_run_tracker", None)
    reader = getattr(tracker, "character_passive_snapshot", None)
    snapshot = reader() if callable(reader) else None
    if snapshot is not None and int(getattr(snapshot, "character_id", -1)) >= 0:
        name = str(getattr(snapshot, "character_name", "") or "").strip()
        if name:
            return int(snapshot.character_id), name
    return None


def vod_capture(owner) -> VodCapture:
    runtime = _runtime(owner)
    existing = runtime.__dict__.get("vod_capture")
    if existing is not None:
        return existing
    service = VodCapture(
        recorder=lambda: owner.player_stats_vod_recorder,
        read_recording_state=lambda context=None: player_stats_memory(owner)._read_player_stats_recording_state_safe(context),
        read_run_timer=lambda context=None: player_stats_memory(owner)._read_player_stats_recording_run_timer_safe(context),
        close_game_data_client=lambda: player_stats_memory(owner).close_player_stats_game_data_client(),
        run_lifecycle=lambda: run_lifecycle(owner),
        refresh_now=lambda **kwargs: player_stats_refresh(owner).refresh_now(**kwargs),
        player_stats_view=lambda: player_stats_view(owner),
        recordings_list_view=lambda: recordings_list_view(owner),
        is_live_stats_tab_active=lambda: owner._is_live_stats_tab_active(),
        log=lambda message, tag=None: owner.log(message, tag=tag),
        reset_snapshot_buffer=lambda: _reset_snapshot_buffer(owner),
        read_character_identity=lambda: _read_owner_character_identity(owner),
    )
    runtime.vod_capture = service
    return service


def overlay_widget_refresh_active(owner, widget_id: str) -> bool:
    server = getattr(owner, "overlay_server", None)
    if server is None or not bool(getattr(server, "is_running", False)):
        return False
    overlay = getattr(config, "OVERLAY", {}) or {}
    return any(
        isinstance(widget, dict)
        and str(widget.get("id") or "") == widget_id
        and bool(widget.get("enabled", False))
        for widget in overlay.get("widgets", ()) or ()
    )


def player_stats_refresh_required(owner) -> bool:
    return not run_lifecycle(owner).completed_run and (
        owner._is_live_stats_tab_active()
        or owner.player_stats_vod_recorder.is_recording
        or vod_capture(owner).is_recording_armed()
        or bool(getattr(config, "AUTO_START_RECORDING", False))
        or any(
            overlay_widget_refresh_active(owner, widget_id)
            for widget_id in ("stage_summary", "tracked_items", "stats", "banishes", "build_progression")
        )
        or in_game_overlay_requires_player_stats_refresh()
        or owner._is_twitch_bot_active()
    )


def refresh_tasks(owner) -> RefreshTasks:
    runtime = _runtime(owner)
    existing = runtime.__dict__.get("refresh_tasks")
    if existing is not None:
        return existing
    service = RefreshTasks(
        memory=lambda: player_stats_memory(owner),
        lifecycle=lambda: run_lifecycle(owner),
        view=lambda: player_stats_view(owner),
        capture=lambda: vod_capture(owner),
        tracker=lambda: owner.live_run_tracker,
        vod_recorder=lambda: getattr(owner, "player_stats_vod_recorder", None),
        tab_active=lambda: owner._is_live_stats_tab_active(),
        twitch_active=lambda: owner._is_twitch_bot_active(),
        pinned=lambda: player_stats_snapshot_is_pinned(owner),
        widget_refresh_active=lambda widget_id: overlay_widget_refresh_active(owner, widget_id),
        sync_overlay_state=lambda: owner.update_overlay_state_from_tracker(),
        sync_in_game_kps=lambda: owner.refresh_in_game_overlay_kps(),
        refresh_session_tracked_items=lambda: owner.refresh_session_tracked_item_stats_ui(),
        refresh_required=lambda: player_stats_refresh_required(owner),
        build_progression_service=lambda: getattr(owner, "build_progression_service", getattr(getattr(owner, "coordinator", None), "build_progression_service", None)),
    )
    runtime.refresh_tasks = service
    return service


def ensure_refresh_coordinator(owner) -> RefreshCoordinator:
    runtime = _runtime(owner)
    existing = runtime.__dict__.get("refresh_coordinator")
    if existing is not None:
        return existing
    coordinator = build_refresh_coordinator(
        refresh_tasks(owner),
        refresh_full_snapshot=lambda **kwargs: owner.refresh_live_player_stats_now(**kwargs),
    )
    runtime.refresh_coordinator = coordinator
    app_coordinator = owner.__dict__.get("coordinator")
    if app_coordinator is not None:
        app_coordinator.refresh_coordinator = coordinator
    return coordinator


def player_stats_refresh(owner) -> PlayerStatsRefresh:
    runtime = _runtime(owner)
    existing = runtime.__dict__.get("player_stats_refresh")
    if existing is not None:
        return existing
    service = PlayerStatsRefresh(
        shutdown_requested=lambda: owner._is_shutting_down,
        lifecycle_service=lambda: run_lifecycle(owner),
        coordinator_tick=lambda: ensure_refresh_coordinator(owner).tick(),
        memory_service=lambda: player_stats_memory(owner),
        store=lambda: live_snapshot_store(owner),
        live_stats_view=lambda: player_stats_view(owner),
        overlay=lambda: overlay_view(owner),
        recordings_list=lambda: recordings_list_view(owner),
        capture_service=lambda: vod_capture(owner),
        live_tracker=lambda: owner.live_run_tracker,
        recorder_handle=lambda: owner.player_stats_vod_recorder,
        tab_is_active=lambda: owner._is_live_stats_tab_active(),
        snapshot_is_pinned=lambda: player_stats_snapshot_is_pinned(owner),
        snapshot_buffer=lambda: owner.player_stats_vod_snapshots,
        select_snapshot=lambda index: setattr(owner, "player_stats_selected_snapshot_index", index),
        game_data_client=lambda: owner.player_stats_game_data_client,
        set_game_data_client=lambda value: setattr(owner, "player_stats_game_data_client", value),
    )
    runtime.player_stats_refresh = service
    return service
