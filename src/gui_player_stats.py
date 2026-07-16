from __future__ import annotations

import datetime
import html
from math import isfinite
import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

import config
import run_summary
from game_data import GameDataClient, RuntimeGameMode, RuntimeGameState, MapStat
from gui_dialogs import CleanupRecordingsDialog, ConfirmDeleteRecordingDialog
from gui_shared import _clear_layout, _clear_text_input, _read_text, _set_text, _set_text_input
from gui_styles import (
    COLOR_MAP,
    ITEM_RARITY_BY_NAME,
    ITEM_RARITY_COLOR_MAP,
    ITEM_RARITY_SORT_ORDER,
    ITEM_SORT_DEFAULT,
    ITEM_SORT_RARITY_ASC,
    ITEM_SORT_RARITY_DESC,
    PLAYER_STATS_ACTIVE_BUTTON_COLOR,
    PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR,
    PLAYER_STATS_INACTIVE_BUTTON_COLOR,
    PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR,
    PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS,
    PLAYER_STATS_LABEL_FONT_SIZE,
    PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS,
    PLAYER_STATS_REFRESH_MS,
    PLAYER_STATS_STAGE4_GHOST_ENTRY_MAX_SECONDS,
    PLAYER_STATS_STAGE4_GHOST_TIMER_SECONDS,
    PLAYER_STATS_STAGE4_RESET_WINDOW_SECONDS,
    PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS,
    PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS,
    PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS,
    PLAYER_STATS_VALUE_FONT_SIZE,
    _button_state_stylesheet,
)
from item_metadata import item_display_color, normalize_item_name_for_display, normalize_item_name_for_rarity
from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from live_run_tracker import (
    CHAOS_TOME_GAME_STAT_ORDER,
    LiveRunSnapshot,
    LiveRunTracker,
    PowerupMapContext,
)
from player_stats import (
    PLAYER_STAT_GROUPS,
    DamageSourceSnapshot,
    PlayerStatsClient,
    TomeSnapshot,
    WeaponSnapshot,
    calculate_chests_per_minute,
)
from refresh_coordinator import RefreshCoordinator, RefreshTask, RefreshTickContext
from vod_storage import (
    delete_vod,
    delete_vods_below_snapshot_count,
    load_vod,
    refresh_vod_metadata_index,
    rename_vod,
)
from vod_projection import build_vod_capture_kwargs

COMPARE_RUN_STAT_LABELS = (
    "Damage",
    "Attack Speed",
    "Luck",
    "XP Gain",
    "Difficulty",
    "Powerup Multiplier",
    "Powerup Drop Chance",
)
COMPARE_RUN_STAT_CONFIG_KEY = "COMPARE_RUN_STAT_LABELS"
COMPARE_RUN_SECTIONS_CONFIG_KEY = "COMPARE_RUN_SECTIONS"
COMPARE_RUN_SECTION_DEFAULTS = {
    "items": False,
    "stage_summary": False,
    "weapons": False,
    "tomes": False,
    "chaos": False,
}
CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS = 1.0
PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD = 3


def _set_items_text(widget, items=(), *, items_text: str | None = None) -> None:
    text = items_text if items_text is not None else PlayerStatsMixin.format_items(items)
    if widget is None:
        return
    if hasattr(widget, "setTextFormat"):
        widget.setText(PlayerStatsMixin.format_items_rich_text(items) if items_text is None else text)
        return
    _set_text(widget, text)

class PlayerStatsMixin:
    def _is_player_stats_recording_armed(self) -> bool:
        auto_recording_enabled = bool(getattr(config, "AUTO_START_RECORDING", False))
        auto_recording_suppressed = bool(
            getattr(self, "player_stats_auto_recording_suppressed", False)
        )
        return bool(getattr(self, "player_stats_recording_armed", False)) or bool(
            auto_recording_enabled and not auto_recording_suppressed
        )

    @staticmethod
    def _in_game_overlay_widget_enabled(widget_id: str) -> bool:
        overlay = getattr(config, "IN_GAME_OVERLAY", {}) or {}
        if not overlay.get("enabled", False):
            return False
        widgets = overlay.get("widgets", {}) or {}
        if not isinstance(widgets, dict):
            return False
        widget_cfg = widgets.get(widget_id, {})
        return isinstance(widget_cfg, dict) and bool(widget_cfg.get("enabled", False))

    def _in_game_overlay_requires_player_stats_refresh(self) -> bool:
        return (
            self._in_game_overlay_widget_enabled("luck_rarity")
            or self._in_game_overlay_widget_enabled("stats")
            or self._in_game_overlay_widget_enabled("event_timer")
        )

    def update_player_stats_timer(self):
        if self._is_shutting_down:
            return
        try:
            recording_state_action = self._sync_player_stats_recording_run_state()
            self._refresh_core_run_lifecycle_state()
            self._player_stats_refresh_status_text = (
                "Live player stats"
                if recording_state_action != "stopped"
                else "Live player stats (recording auto-stopped after run end)"
            )
            self._ensure_refresh_coordinator().tick()
        finally:
            if not self._is_shutting_down:
                self.after(PLAYER_STATS_REFRESH_MS, self.update_player_stats_timer)

    def _player_stats_refresh_required(self) -> bool:
        return not bool(getattr(self, "_player_stats_completed_run", False)) and (
            self._is_live_stats_tab_active()
            or self.player_stats_vod_recorder.is_recording
            or self._is_player_stats_recording_armed()
            or bool(getattr(config, "AUTO_START_RECORDING", False))
            or self._overlay_requires_player_snapshot()
            or self._in_game_overlay_requires_player_stats_refresh()
            or self._is_twitch_bot_active()
        )

    def update_chaos_tome_tracker_timer(self):
        if self._is_shutting_down:
            return
        try:
            self._refresh_core_run_lifecycle_state()
            self._ensure_refresh_coordinator().tick()
        finally:
            if not self._is_shutting_down:
                self.after(
                    int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500)),
                    self.update_chaos_tome_tracker_timer,
                )

    def _ensure_refresh_coordinator(self) -> RefreshCoordinator:
        coordinator = getattr(self, "_refresh_coordinator", None)
        if coordinator is not None:
            return coordinator
        coordinator = RefreshCoordinator()
        coordinator.register(
            RefreshTask(
                task_id="full_player_snapshot",
                interval_ms=PLAYER_STATS_REFRESH_MS,
                required=self._should_refresh_full_player_snapshot,
                run=lambda _context: self.refresh_live_player_stats_now(
                    status_text=getattr(
                        self,
                        "_player_stats_refresh_status_text",
                        "Live player stats",
                    )
                ),
            )
        )
        coordinator.register(
            RefreshTask(
                task_id="combat_metrics",
                interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
                required=self._should_refresh_fast_kps,
                run=self._refresh_combat_metrics_task,
            )
        )
        coordinator.register(
            RefreshTask(
                task_id="powerups",
                interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
                required=self._should_refresh_powerup_tracker,
                run=self._refresh_powerups_task,
            )
        )
        coordinator.register(
            RefreshTask(
                task_id="expected_chest_inputs",
                interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
                required=self._should_refresh_expected_chest_inputs,
                run=self._refresh_expected_chest_inputs_task,
            )
        )
        coordinator.register(
            RefreshTask(
                task_id="event_timer",
                interval_ms=1_000,
                required=self._should_refresh_fast_stage_timer,
                run=self._refresh_event_timer_task,
            )
        )
        coordinator.register(
            RefreshTask(
                task_id="chaos_tome",
                interval_ms=max(100, int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500))),
                required=self._should_refresh_chaos_tome,
                run=self._refresh_chaos_tome_task,
            )
        )
        self._refresh_coordinator = coordinator
        return coordinator

    def _fast_task_client(self, context: RefreshTickContext) -> PlayerStatsClient:
        return context.get_or_create("player_stats_client", self._get_player_stats_client)

    def _fast_task_owner_stats(self, context: RefreshTickContext) -> int:
        return context.get_or_create(
            "owner_stats",
            lambda: self._fast_task_client(context).resolve_owner_stats(),
        )

    def _mark_fast_feature_available(self, feature: str) -> None:
        marker = getattr(self.live_run_tracker, "mark_feature_available", None)
        if callable(marker):
            try:
                marker(feature)
            except Exception:
                pass

    def _mark_fast_feature_failed(self, feature: str, error: Exception) -> None:
        marker = getattr(self.live_run_tracker, "mark_feature_failed", None)
        if callable(marker):
            try:
                marker(feature, error)
            except Exception:
                pass

    def _record_player_stats_memory_success(self) -> None:
        self._player_stats_memory_error_streak = 0

    def _record_player_stats_memory_failure(self, error: Exception) -> None:
        if not isinstance(error, (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError)):
            return
        streak = int(getattr(self, "_player_stats_memory_error_streak", 0)) + 1
        self._player_stats_memory_error_streak = streak
        if streak < PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD:
            return
        try:
            self.close_player_stats_client()
        finally:
            self._player_stats_memory_error_streak = 0

    def _record_player_stats_game_data_memory_success(self) -> None:
        self._player_stats_game_data_memory_error_streak = 0

    def _record_player_stats_game_data_memory_failure(self, error: Exception) -> None:
        if not isinstance(error, (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError)):
            return
        streak = int(getattr(self, "_player_stats_game_data_memory_error_streak", 0)) + 1
        self._player_stats_game_data_memory_error_streak = streak
        if streak < PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD:
            return
        try:
            self.close_player_stats_game_data_client()
        finally:
            self._player_stats_game_data_memory_error_streak = 0

    def _refresh_powerups_task(self, context: RefreshTickContext) -> bool:
        try:
            snapshot = self._fast_task_client(context).get_powerup_tracking_snapshot(
                self._fast_task_owner_stats(context)
            )
            self._record_player_stats_memory_success()
            accepted = self.live_run_tracker.update_powerups(snapshot)
            self._refresh_live_powerups_label()
            return accepted is not False
        except Exception as exc:
            self._record_player_stats_memory_failure(exc)
            self._mark_fast_feature_failed("powerups", exc)
            self._refresh_live_powerups_label()
            return False

    def _refresh_expected_chest_inputs_task(self, context: RefreshTickContext) -> bool:
        try:
            chests_bought, keys_count = self._fast_task_client(context).get_expected_chest_inputs(
                self._fast_task_owner_stats(context)
            )
            self._record_player_stats_memory_success()
            self.live_run_tracker.track_expected_key_procs(chests_bought, keys_count)
            self._mark_fast_feature_available("expected_chests")
            return True
        except Exception as exc:
            self._record_player_stats_memory_failure(exc)
            self._mark_fast_feature_failed("expected_chests", exc)
            return False

    def _refresh_combat_metrics_task(self, context: RefreshTickContext) -> bool:
        try:
            client = self._fast_task_client(context)
            run_timer_seconds = client.get_run_timer()
            self._record_player_stats_memory_success()
            self._mark_fast_feature_available("combat")
            previous_game_time = getattr(self, "_last_fast_kps_game_time_seconds", None)
            if (
                run_timer_seconds is not None
                and previous_game_time is not None
                and abs(float(run_timer_seconds) - float(previous_game_time)) < 0.001
            ):
                return True
            mob_kills = client.get_killed_mobs()
            self._record_player_stats_memory_success()
            self.live_run_tracker.track_kills(run_timer_seconds, mob_kills)
            self._last_fast_kps_game_time_seconds = run_timer_seconds
            if self._is_live_stats_tab_active():
                _set_text(
                    self.player_stats_mob_kills_label,
                    self.format_mob_kills(mob_kills, self.live_run_tracker.current_ui_kps()),
                )
                self._set_stage_summary_labels(
                    getattr(self, "player_stats_stage_summary_labels", None),
                    self.live_run_tracker.stage_summary_rows(),
                )
            if (
                self._overlay_widget_refresh_active("kps")
                or self._overlay_widget_refresh_active("stage_summary")
            ):
                self.update_overlay_state_from_tracker()
            return True
        except Exception as exc:
            self._record_player_stats_memory_failure(exc)
            self._mark_fast_feature_failed("combat", exc)
            return False

    def _refresh_event_timer_task(self, context: RefreshTickContext) -> bool:
        update_fast_stage_timer = getattr(self.live_run_tracker, "update_fast_stage_timer", None)
        if not callable(update_fast_stage_timer):
            return True
        try:
            stage_timer_seconds, stage_index, stage_duration_seconds = (
                self._fast_task_client(context).get_stage_timer_context()
            )
            self._record_player_stats_memory_success()
            update_fast_stage_timer(
                stage_timer_seconds=stage_timer_seconds,
                stage_index=stage_index,
                stage_duration_seconds=stage_duration_seconds,
            )
            self._mark_fast_feature_available("stage_timer")
            if self._is_live_stats_tab_active():
                self._set_stage_summary_labels(
                    getattr(self, "player_stats_stage_summary_labels", None),
                    self.live_run_tracker.stage_summary_rows(),
                )
            if self._overlay_widget_refresh_active("stage_summary"):
                self.update_overlay_state_from_tracker()
            return True
        except Exception as exc:
            self._record_player_stats_memory_failure(exc)
            update_fast_stage_timer(
                stage_timer_seconds=None,
                stage_index=None,
                stage_duration_seconds=None,
            )
            self._mark_fast_feature_failed("stage_timer", exc)
            return False

    def _refresh_chaos_tome_task(self, context: RefreshTickContext) -> bool:
        try:
            chaos_level, permanent_modifiers = self._fast_task_client(
                context
            ).get_chaos_tracking_state(self._fast_task_owner_stats(context))
            self._record_player_stats_memory_success()
            self.live_run_tracker.update_chaos_tome(
                chaos_level=chaos_level,
                permanent_modifiers=permanent_modifiers if chaos_level is not None else {},
            )
            return True
        except Exception as exc:
            self._record_player_stats_memory_failure(exc)
            self._mark_fast_feature_failed("chaos_tome", exc)
            return False

    def _should_refresh_powerup_tracker(self) -> bool:
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        is_live_stats_tab_active = getattr(self, "_is_live_stats_tab_active", None)
        if callable(is_live_stats_tab_active):
            try:
                if is_live_stats_tab_active():
                    return True
            except Exception:
                pass
        if (
            self._in_game_overlay_widget_enabled("powerups")
            or self._in_game_overlay_widget_enabled("event_timer")
        ):
            return True
        is_twitch_bot_active = getattr(self, "_is_twitch_bot_active", None)
        commands_cfg = config.TWITCH_BOT.get("commands", {})
        if callable(is_twitch_bot_active):
            try:
                return bool(is_twitch_bot_active() and commands_cfg.get("powerups", True))
            except Exception:
                return False
        return False

    def _should_refresh_fast_kps(self, _now: float | None = None) -> bool:
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        is_live_stats_tab_active = getattr(self, "_is_live_stats_tab_active", None)
        if callable(is_live_stats_tab_active):
            try:
                if is_live_stats_tab_active():
                    return True
            except Exception:
                pass
        if self._is_vod_recording():
            return True
        if (
            self._in_game_overlay_widget_enabled("kps")
            or self._in_game_overlay_widget_enabled("stage_summary")
        ):
            return True
        if (
            self._overlay_widget_refresh_active("kps")
            or self._overlay_widget_refresh_active("stage_summary")
        ):
            return True
        if self._twitch_stage_summary_refresh_active():
            return True
        is_twitch_bot_active = getattr(self, "_is_twitch_bot_active", None)
        commands_cfg = config.TWITCH_BOT.get("commands", {})
        if callable(is_twitch_bot_active):
            try:
                return bool(is_twitch_bot_active() and commands_cfg.get("kps", True))
            except Exception:
                return False
        return False

    def _should_refresh_expected_chest_inputs(self) -> bool:
        core_run_active = getattr(self, "_core_run_active", None)
        if callable(core_run_active) and core_run_active():
            return True
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        if self._is_live_stats_tab_active() or self._is_vod_recording():
            return True
        return self._twitch_command_refresh_active("chests")

    def _should_refresh_full_player_snapshot(self) -> bool:
        core_run_active = getattr(self, "_core_run_active", None)
        return bool(callable(core_run_active) and core_run_active()) or self._player_stats_refresh_required()

    def _core_run_active(self) -> bool:
        state = getattr(self, "_core_runtime_game_state", None)
        return bool(state is not None and state.is_active_run)

    def _should_refresh_chaos_tome(self) -> bool:
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        if self._is_live_stats_tab_active() or self._is_vod_recording():
            return True
        return self._twitch_command_refresh_active("chaos")

    def _twitch_command_refresh_active(self, command: str) -> bool:
        is_twitch_bot_active = getattr(self, "_is_twitch_bot_active", None)
        if not callable(is_twitch_bot_active):
            return False
        try:
            if not is_twitch_bot_active():
                return False
        except Exception:
            return False
        commands = config.TWITCH_BOT.get("commands", {})
        default = config.DEFAULT_TWITCH_BOT["commands"].get(command, False)
        return bool(commands.get(command, default))

    def _is_vod_recording(self) -> bool:
        recorder = getattr(self, "player_stats_vod_recorder", None)
        return bool(recorder is not None and getattr(recorder, "is_recording", False))

    def _should_refresh_fast_stage_timer(self) -> bool:
        if bool(getattr(self, "_player_stats_completed_run", False)):
            return False
        is_live_stats_tab_active = getattr(self, "_is_live_stats_tab_active", None)
        if callable(is_live_stats_tab_active):
            try:
                if is_live_stats_tab_active():
                    return True
            except Exception:
                pass
        if self._is_vod_recording() or self._twitch_stage_summary_refresh_active():
            return True
        return (
            self._in_game_overlay_widget_enabled("event_timer")
            or self._in_game_overlay_widget_enabled("stage_summary")
            or self._overlay_widget_refresh_active("stage_summary")
        )

    def _twitch_stage_summary_refresh_active(self) -> bool:
        is_twitch_bot_active = getattr(self, "_is_twitch_bot_active", None)
        if not callable(is_twitch_bot_active):
            return False
        try:
            if not is_twitch_bot_active():
                return False
        except Exception:
            return False
        commands = config.TWITCH_BOT.get("commands", {})
        stages_enabled = bool(
            commands.get("stages", config.DEFAULT_TWITCH_BOT["commands"].get("stages", False))
        )
        return stages_enabled or bool(config.TWITCH_BOT.get("stage_announcements", True))

    def _overlay_widget_refresh_active(self, widget_id: str) -> bool:
        server = getattr(self, "overlay_server", None)
        if server is None or not bool(getattr(server, "is_running", False)):
            return False
        overlay = getattr(config, "OVERLAY", {}) or {}
        return any(
            isinstance(widget, dict)
            and str(widget.get("id") or "") == widget_id
            and bool(widget.get("enabled", False))
            for widget in overlay.get("widgets", ()) or ()
        )

    def _overlay_requires_player_snapshot(self) -> bool:
        return any(
            self._overlay_widget_refresh_active(widget_id)
            for widget_id in ("stage_summary", "tracked_items", "stats", "banishes")
        )

    def _refresh_live_powerups_label(self) -> None:
        self._apply_live_powerups_card(None)

    def _get_player_stats_client(self) -> PlayerStatsClient:
        if self.player_stats_client is None:
            self.player_stats_client = PlayerStatsClient(config.PROCESS_NAME)
        return self.player_stats_client

    def read_player_stats_only(self):
        client = self._get_player_stats_client()
        owner_stats = client.resolve_owner_stats()
        return client.get_player_stats(owner_stats), owner_stats

    def read_passive_items_only(self, owner_stats: int | None = None):
        client = self._get_player_stats_client()
        return client.get_passive_items(owner_stats)

    def read_player_stats(self):
        stats, owner_stats = self.read_player_stats_only()
        return stats, self.read_passive_items_only(owner_stats)

    def read_player_stats_recording_state(self):
        if self.player_stats_game_data_client is None:
            self.player_stats_game_data_client = GameDataClient(config.PROCESS_NAME)
        return self.player_stats_game_data_client.get_map_generation_state()

    def read_player_stats_runtime_game_state(self):
        if self.player_stats_game_data_client is None:
            self.player_stats_game_data_client = GameDataClient(config.PROCESS_NAME)
        return self.player_stats_game_data_client.get_runtime_game_state()

    def read_player_stats_runtime_activity_state(self):
        if self.player_stats_game_data_client is None:
            self.player_stats_game_data_client = GameDataClient(config.PROCESS_NAME)
        reader = getattr(self.player_stats_game_data_client, "get_runtime_activity_state", None)
        if callable(reader):
            return reader()
        return self.player_stats_game_data_client.get_runtime_game_state()

    def read_player_stats_recording_seed(self) -> int | None:
        return self.read_player_stats_recording_state().map_seed

    def _reset_live_player_stats_ui(self, status_text: str, *, items_text: str = "--") -> None:
        _set_text(self.player_stats_status_label, status_text)
        for label in self.player_stats_rows.values():
            _set_text(label, "--")
        self.player_stats_items_expanded = False
        self.player_stats_last_known_items = None
        self.player_stats_last_known_weapons = None
        self.player_stats_last_known_tomes = None
        self.player_stats_last_known_damage_sources = None
        self.player_stats_last_known_banishes = None
        self._update_items_section("live", items_text=items_text)
        _set_text(self.player_stats_chests_per_minute_label, "Average chests/min: --")
        self._apply_live_powerups_card(None)
        _set_text(self.player_stats_in_game_time_label, "In-Game Time: --")
        _set_text(self.player_stats_mob_kills_label, "Mob Kills: --")
        _set_text(getattr(self, "player_stats_kps_averages_label", None), "KPS: --")
        _set_text(self.player_stats_level_label, "Level: --")
        self._set_chests_card_values(
            getattr(self, "player_stats_chests_card_values", None),
            None,
        )
        _set_text(getattr(self, "player_stats_new_items_label", None), "Live snapshot")
        _set_text(self.player_stats_banishes_label, "No banishes yet")
        self.player_stats_live_banishes = ()
        self._set_stage_summary_labels(self.player_stats_stage_summary_labels, None)
        self.player_stats_weapon_signature = None
        self.display_weapon_cards(
            (),
            scope="live",
            status_text="Waiting for weapon data...",
        )
        self.player_stats_tome_signature = None
        self.display_tome_cards(
            (),
            scope="live",
            status_text="Waiting for tome data...",
        )
        self.player_stats_chaos_signature = None
        self.display_chaos_tome_card(
            None,
            scope="live",
            status_text="Waiting for Chaos Tome data...",
        )
        self.player_stats_damage_source_signature = None
        self.display_damage_source_rows(
            (),
            scope="live",
            status_text="Waiting for damage source data...",
        )

    def _read_live_player_stats_data(self):
        stats, owner_stats = self.read_player_stats_only()
        items = ()
        items_available = True
        weapons: tuple[WeaponSnapshot, ...] = ()
        weapons_available = False
        tomes: tuple[TomeSnapshot, ...] = ()
        tomes_available = False
        banishes: tuple[str, ...] = ()
        banishes_available = False
        disabled_items = ()
        disabled_items_available = False
        damage_sources: tuple[DamageSourceSnapshot, ...] = ()
        damage_sources_available = False

        # 1. Read run timer and stage timer first to support match start detection
        run_timer_seconds = None
        stage_timer_seconds = None
        stage_index = None
        stage_duration_seconds = None
        try:
            client = self._get_player_stats_client()
            run_timer_seconds = client.get_run_timer()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            run_timer_seconds = None
        except Exception:
            run_timer_seconds = None

        try:
            client = self._get_player_stats_client()
            stage_timer_seconds, stage_index, stage_duration_seconds = (
                client.get_stage_timer_context()
            )
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            stage_timer_seconds = None
            stage_index = None
            stage_duration_seconds = None
        except Exception:
            stage_timer_seconds = None
            stage_index = None
            stage_duration_seconds = None

        # 2. Read map seed and stage ptr
        map_seed = None
        stage_ptr = 0
        try:
            recording_state = self.read_player_stats_recording_state()
            PlayerStatsMixin._record_player_stats_game_data_memory_success(self)
            map_seed = recording_state.map_seed
            stage_ptr = recording_state.current_stage_ptr
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            PlayerStatsMixin._record_player_stats_game_data_memory_failure(self, exc)
            map_seed = None
            stage_ptr = 0
        except Exception:
            self.close_player_stats_game_data_client()
            map_seed = None
            stage_ptr = 0

        # 3. Detect match start
        is_new_match = False
        prev_seed = getattr(self, "player_stats_last_seed", None)
        prev_time = getattr(self, "player_stats_last_run_timer", None)
        if run_timer_seconds is not None:
            if prev_time is None and run_timer_seconds <= 5.0:
                is_new_match = True

            # Map seed changed or appeared on low game time
            if map_seed is not None and (prev_seed is None or int(map_seed) != int(prev_seed)):
                if run_timer_seconds <= 5.0:
                    is_new_match = True

            # Timer went backward (reset)
            if prev_time is not None and run_timer_seconds + 1.0 < prev_time:
                is_new_match = True

        if is_new_match:
            self.player_stats_disabled_items_refresh_pending = True
            self.player_stats_last_known_items = None
            self.player_stats_last_known_weapons = None
            self.player_stats_last_known_tomes = None
            self.player_stats_last_known_damage_sources = None
            self.player_stats_last_known_banishes = None
            self.player_stats_live_banishes = ()

        # 4. Read passive items
        try:
            items = self.read_passive_items_only(owner_stats)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            items_available = False
        except Exception:
            items_available = False

        # 5. Read optional live stats if relevant tabs/features are active
        if (
            self.player_stats_vod_recorder.is_recording
            or self._is_live_stats_tab_active()
            or self.overlay_should_refresh_live_stats()
            or self._is_twitch_bot_active()
        ):
            try:
                client = self._get_player_stats_client()
                weapons = client.get_live_weapons(owner_stats)
                weapons_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                weapons = ()
                weapons_available = False
            except Exception:
                weapons = ()
                weapons_available = False

            try:
                client = self._get_player_stats_client()
                tomes = client.get_live_tomes(owner_stats)
                tomes_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                tomes = ()
                tomes_available = False
            except Exception:
                tomes = ()
                tomes_available = False

            try:
                client = self._get_player_stats_client()
                banishes = client.get_live_banishes()
                banishes_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                banishes = ()
                banishes_available = False
            except Exception:
                banishes = ()
                banishes_available = False

            # Refresh once per run, retrying until memory exposes a complete pool.
            try:
                should_read_disabled = (
                    getattr(self, "player_stats_disabled_items_refresh_pending", False)
                    or getattr(self, "player_stats_disabled_items_cache", None) is None
                )
                if should_read_disabled:
                    client = self._get_player_stats_client()
                    result = client.get_disabled_items()
                    if result.available:
                        self.player_stats_disabled_items_cache = result.items
                        self.player_stats_disabled_items_refresh_pending = False
                    cache = getattr(self, "player_stats_disabled_items_cache", None)
                    if cache is not None:
                        disabled_items = cache
                        disabled_items_available = True
                else:
                    disabled_items = getattr(self, "player_stats_disabled_items_cache", ())
                    disabled_items_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                disabled_items = ()
                disabled_items_available = False
            except Exception:
                disabled_items = ()
                disabled_items_available = False

            try:
                client = self._get_player_stats_client()
                damage_sources = client.get_live_damage_sources()
                damage_sources_available = True
            except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
                damage_sources = ()
                damage_sources_available = False
            except Exception:
                damage_sources = ()
                damage_sources_available = False

        # 6. Read mob kills and player level
        try:
            client = self._get_player_stats_client()
            mob_kills = client.get_killed_mobs()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            mob_kills = None
        except Exception:
            mob_kills = None

        try:
            client = self._get_player_stats_client()
            player_level = client.get_player_level(owner_stats)
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError):
            player_level = None
        except Exception:
            player_level = None

        # Update last seed and run timer values for the next tick
        self.player_stats_last_seed = map_seed
        self.player_stats_last_run_timer = run_timer_seconds

        return (
            stats,
            items,
            items_available,
            weapons,
            weapons_available,
            tomes,
            tomes_available,
            banishes,
            banishes_available,
            damage_sources,
            damage_sources_available,
            run_timer_seconds,
            stage_timer_seconds,
            stage_duration_seconds,
            mob_kills,
            player_level,
            map_seed,
            stage_ptr,
            stage_index,
            disabled_items,
            disabled_items_available,
        )

    def refresh_live_player_stats_now(
        self,
        *,
        status_text: str = "Live player stats",
        waiting_status_text: str = "Waiting for game/player stats...",
        unavailable_status_prefix: str = "Player stats unavailable",
    ) -> bool:
        try:
            (
                stats,
                items,
                items_available,
                weapons,
                weapons_available,
                tomes,
                tomes_available,
                banishes,
                banishes_available,
                damage_sources,
                damage_sources_available,
                run_timer_seconds,
                stage_timer_seconds,
                stage_duration_seconds,
                mob_kills,
                player_level,
                map_seed,
                stage_ptr,
                stage_index,
                disabled_items,
                disabled_items_available,
            ) = self._read_live_player_stats_data()
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            self._record_player_stats_memory_failure(exc)
            try:
                self.mark_overlay_read_failed(no_game=False)
            except Exception:
                pass
            return False
        except Exception as exc:
            self._record_player_stats_memory_failure(exc)
            try:
                self.mark_overlay_read_failed(no_game=False)
            except Exception:
                pass
            return False

        self._record_player_stats_memory_success()

        chests_per_minute = self.calculate_player_chests_per_minute(stats)
        items_text = None if items_available else "Items unavailable"
        last_known_items = getattr(self, "player_stats_last_known_items", None)
        if items_available and (items or last_known_items is None):
            effective_items = items
            self.player_stats_last_known_items = items
        elif last_known_items is not None:
            # The game can expose an empty inventory dictionary for a single
            # refresh while it is being updated. Do not turn that into a real
            # item loss or let it reset the stage-summary item baseline.
            effective_items = last_known_items
            items_available = False
        else:
            effective_items = ()

        last_known_weapons = getattr(self, "player_stats_last_known_weapons", None)
        if weapons_available:
            if weapons or last_known_weapons is None:
                effective_weapons = weapons
                self.player_stats_last_known_weapons = weapons
                effective_weapons_available = True
            else:
                effective_weapons = last_known_weapons
                weapons_available = False
                effective_weapons_available = True
        else:
            effective_weapons = last_known_weapons or ()
            effective_weapons_available = last_known_weapons is not None

        last_known_tomes = getattr(self, "player_stats_last_known_tomes", None)
        if tomes_available:
            if tomes or last_known_tomes is None:
                effective_tomes = tomes
                self.player_stats_last_known_tomes = tomes
                effective_tomes_available = True
            else:
                effective_tomes = last_known_tomes
                tomes_available = False
                effective_tomes_available = True
        else:
            effective_tomes = last_known_tomes or ()
            effective_tomes_available = last_known_tomes is not None

        last_known_damage_sources = getattr(
            self,
            "player_stats_last_known_damage_sources",
            None,
        )
        if damage_sources_available:
            if damage_sources or last_known_damage_sources is None:
                effective_damage_sources = damage_sources
                self.player_stats_last_known_damage_sources = damage_sources
                effective_damage_sources_available = True
            else:
                effective_damage_sources = last_known_damage_sources
                damage_sources_available = False
                effective_damage_sources_available = True
        else:
            effective_damage_sources = last_known_damage_sources or ()
            effective_damage_sources_available = last_known_damage_sources is not None

        if banishes_available:
            last_known_banishes = getattr(self, "player_stats_last_known_banishes", None)
            if banishes or last_known_banishes is None:
                banishes = self.merge_banish_appearance_order(
                    self.player_stats_live_banishes,
                    banishes,
                )
                self.player_stats_live_banishes = banishes
                self.player_stats_last_known_banishes = banishes
            else:
                banishes = last_known_banishes
                banishes_available = False
        else:
            last_known_banishes = getattr(self, "player_stats_last_known_banishes", None)
            banishes = (
                last_known_banishes
                if last_known_banishes is not None
                else self.player_stats_live_banishes
            )
        is_live_tab_active = self._is_live_stats_tab_active()
        map_stats = {}
        map_chests_total = None
        map_pots_total = None
        map_activity_max = {}
        try:
            if self.player_stats_game_data_client is None:
                self.player_stats_game_data_client = GameDataClient(config.PROCESS_NAME)
            map_activity_values = (
                self.player_stats_game_data_client.get_map_activity_values() or {}
            )
            PlayerStatsMixin._record_player_stats_game_data_memory_success(self)
            map_activity_max = {
                label: int(value.max)
                for label, value in map_activity_values.items()
            }
            map_stats = {
                stat: value
                for label, value in map_activity_values.items()
                if (stat := GameDataClient.LABEL_TO_STAT.get(label)) is not None
            }
            chest_stat = map_stats.get(MapStat.CHESTS)
            if chest_stat is not None:
                map_chests_total = chest_stat.max
            pots_stat = map_stats.get(MapStat.POTS)
            if pots_stat is not None:
                map_pots_total = pots_stat.max
        except Exception as exc:
            PlayerStatsMixin._record_player_stats_game_data_memory_failure(self, exc)
            map_stats = {}
            map_activity_max = {}
        if map_activity_max and hasattr(
            self.live_run_tracker,
            "update_powerup_map_context",
        ):
            self.live_run_tracker.update_powerup_map_context(
                PowerupMapContext.from_activity_max(
                    map_activity_max,
                    captured_at=time.monotonic(),
                )
            )
        live_snapshot = LiveRunSnapshot(
            captured_at=time.monotonic(),
            stats=stats,
            items=effective_items,
            items_available=items_available,
            weapons=effective_weapons,
            weapons_available=weapons_available,
            tomes=effective_tomes,
            tomes_available=tomes_available,
            banishes=banishes,
            disabled_items=disabled_items if disabled_items_available else (),
            disabled_items_available=disabled_items_available,
            damage_sources=effective_damage_sources,
            damage_sources_available=damage_sources_available,
            chests_per_minute=chests_per_minute,
            game_time_seconds=run_timer_seconds,
            stage_timer_seconds=stage_timer_seconds,
            stage_time_seconds=stage_timer_seconds,
            stage_duration_seconds=stage_duration_seconds,
            mob_kills=mob_kills,
            player_level=player_level,
            map_seed=map_seed,
            stage_ptr=stage_ptr,
            stage_index=stage_index,
            chests_total=map_chests_total,
            pots_total=map_pots_total,
        )
        self.live_run_tracker.update(live_snapshot)

        # Update chests and keys without replacing valid data after a transient read failure.
        previous_chests = (0, 46, 0, 0, {}, {})
        get_chests_and_keys = getattr(self.live_run_tracker, "get_chests_and_keys", None)
        if callable(get_chests_and_keys):
            previous_chests = get_chests_and_keys()
        chests_opened, chests_total, keys_count = previous_chests[:3]
        should_update_chests_and_keys = False

        if items_available:
            keys_count = 0
            for item_str in effective_items:
                if item_str == "Key":
                    keys_count = 1
                    break
                elif item_str.startswith("Key x"):
                    try:
                        keys_count = int(item_str.split(" x")[-1])
                    except ValueError:
                        keys_count = 0
                    break
            should_update_chests_and_keys = True

        chest_stat = map_stats.get(MapStat.CHESTS) if map_stats else None
        if chest_stat is not None:
            chests_opened = chest_stat.current
            chests_total = chest_stat.max
            should_update_chests_and_keys = True
        if should_update_chests_and_keys:
            self.live_run_tracker.update_chests_and_keys(chests_opened, chests_total, keys_count)

        try:
            client = self._get_player_stats_client()
            chests_bought, chests_purchased = client.get_chest_counters()
            self.live_run_tracker.update_chest_counters(
                chests_bought,
                chests_purchased,
            )
        except Exception:
            pass

        if hasattr(self, "refresh_session_tracked_item_stats_ui"):
            self.refresh_session_tracked_item_stats_ui()
        chaos_snapshot_reader = getattr(self.live_run_tracker, "chaos_tome_snapshot", None)
        chaos_tome_snapshot = chaos_snapshot_reader() if callable(chaos_snapshot_reader) else None
        self.update_overlay_state_from_tracker()
        live_stage_summary_rows = self.live_run_tracker.stage_summary_rows()
        runtime_state = self._runtime_state_for_refresh()
        if runtime_state.mode is RuntimeGameMode.IN_GAME:
            self._maybe_auto_start_player_stats_recording(
                stats=stats,
                run_timer_seconds=run_timer_seconds,
                player_level=player_level,
                map_seed=map_seed,
                stage_ptr=stage_ptr,
            )
        else:
            self.player_stats_auto_start_detection_streak = 0

        can_capture_recording = (
            self.player_stats_vod_recorder.is_recording
            and runtime_state.mode is RuntimeGameMode.IN_GAME
        )
        if can_capture_recording and self.player_stats_vod_recorder.should_capture():
            capture_kwargs = build_vod_capture_kwargs(
                self.live_run_tracker.runtime_snapshot(),
                chaos_tome=chaos_tome_snapshot,
            )
            snapshot = self.player_stats_vod_recorder.capture(**capture_kwargs)
            self.player_stats_vod_snapshots.append(snapshot)
            self.player_stats_selected_snapshot_index = len(self.player_stats_vod_snapshots) - 1
            self.refresh_player_stats_timeline_ui()
            self._refresh_vods_list_if_visible()
            if is_live_tab_active:
                self.display_player_stats_snapshot(snapshot, items_text=items_text)
            return True

        if is_live_tab_active:
            current_ui_kps_reader = getattr(self.live_run_tracker, "current_ui_kps", None)
            current_minute_kps_reader = getattr(self.live_run_tracker, "current_minute_avg_kps", None)
            current_five_minute_kps_reader = getattr(self.live_run_tracker, "current_five_minute_avg_kps", None)
            if self.player_stats_vod_recorder.is_recording:
                if runtime_state is not None and runtime_state.mode is RuntimeGameMode.PAUSED_IN_GAME:
                    status_text_val = "Live player stats (recording paused)"
                else:
                    status_text_val = "Live player stats (recording)"
            elif self._is_player_stats_recording_armed():
                status_text_val = "Live player stats (recording armed)"
            else:
                status_text_val = status_text
            self.player_stats_selected_snapshot_index = None
            self.display_player_stats(
                stats,
                effective_items,
                weapons=effective_weapons,
                tomes=effective_tomes,
                chaos_tome=chaos_tome_snapshot,
                banishes=banishes,
                damage_sources=effective_damage_sources,
                weapons_available=effective_weapons_available,
                tomes_available=effective_tomes_available,
                damage_sources_available=effective_damage_sources_available,
                status_text=status_text_val,
                chests_per_minute=chests_per_minute,
                items_text=items_text,
                game_time_seconds=run_timer_seconds,
                mob_kills=mob_kills,
                kps=current_ui_kps_reader() if callable(current_ui_kps_reader) else None,
                minute_avg_kps=(
                    current_minute_kps_reader() if callable(current_minute_kps_reader) else None
                ),
                five_minute_avg_kps=(
                    current_five_minute_kps_reader() if callable(current_five_minute_kps_reader) else None
                ),
                player_level=player_level,
                stage_summary_rows=live_stage_summary_rows,
            )
        return True

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
            _set_text(self.player_stats_status_label, status_text)
        for label, stat in stats.items():
            value_label = self.player_stats_rows.get(label)
            if value_label is not None:
                _set_text(value_label, stat.display_value)
        self._update_items_section("live", items, items_text=items_text)
        if chests_per_minute is None:
            chests_per_minute = self.calculate_player_chests_per_minute(stats)
        _set_text(
            self.player_stats_chests_per_minute_label,
            self.format_chests_per_minute(chests_per_minute),
        )
        _set_text(
            getattr(self, "player_stats_powerups_duration_label", None),
            self.format_live_powerups(stats),
        )
        self._apply_live_powerups_card(stats)
        _set_text(
            self.player_stats_in_game_time_label,
            self.format_in_game_time(game_time_seconds),
        )
        _set_text(
            self.player_stats_mob_kills_label,
            self.format_mob_kills(mob_kills, kps),
        )
        _set_text(
            getattr(self, "player_stats_kps_averages_label", None),
            self.format_kps_averages(minute_avg_kps, five_minute_avg_kps),
        )
        _set_text(
            self.player_stats_level_label,
            self.format_player_level(player_level),
        )
        get_chest_stats = getattr(self.live_run_tracker, "get_chest_stats", None)
        if callable(get_chest_stats):
            self._update_live_chest_summary(get_chest_stats())
        if new_items_text is not None:
            _set_text(getattr(self, "player_stats_new_items_label", None), new_items_text)
        else:
            _set_text(getattr(self, "player_stats_new_items_label", None), "Live snapshot")
        _set_text(self.player_stats_banishes_label, self.format_banishes_rich_text(banishes))
        self._set_stage_summary_labels(self.player_stats_stage_summary_labels, stage_summary_rows)
        self.display_weapon_cards(
            weapons if weapons_available else (),
            scope="live",
            status_text=None if weapons_available else "Weapons unavailable",
        )
        self.display_tome_cards(
            tomes if tomes_available else (),
            scope="live",
            status_text=None if tomes_available else "Tomes unavailable",
        )
        self.display_chaos_tome_card(
            chaos_tome,
            scope="live",
            status_text=None if chaos_tome is not None else "No Chaos Tome data yet",
        )
        self.display_damage_source_rows(
            damage_sources if damage_sources_available else (),
            scope="live",
            status_text=None if damage_sources_available else "Damage sources unavailable",
        )

    def display_player_stats_snapshot(self, snapshot, *, items_text: str | None = None):
        index = self.player_stats_vod_snapshots.index(snapshot) + 1
        total = len(self.player_stats_vod_snapshots)
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
                f" | {self.format_in_game_time(snapshot.game_time_seconds)}"
            ),
            chests_per_minute=self.resolve_snapshot_chests_per_minute(snapshot),
            items_text=items_text,
            game_time_seconds=snapshot.game_time_seconds,
            mob_kills=getattr(snapshot, "mob_kills", None),
            kps=getattr(snapshot, "kps_at_capture", None),
            minute_avg_kps=getattr(snapshot, "minute_avg_kps_at_capture", None),
            five_minute_avg_kps=getattr(snapshot, "five_minute_avg_kps_at_capture", None),
            player_level=getattr(snapshot, "player_level", None),
            new_items_text=self.format_snapshot_item_gains_preview(
                self._previous_player_stats_snapshot(snapshot),
                snapshot,
                segment_snapshots=self._player_stats_snapshot_segment(snapshot),
            ),
            stage_summary_rows=self.build_stage_summary(
                self.player_stats_vod_snapshots[:index]
            ),
        )

    def _previous_player_stats_snapshot(self, snapshot):
        try:
            index = self.player_stats_vod_snapshots.index(snapshot)
        except ValueError:
            return None
        if index <= 0:
            return None
        return self.player_stats_vod_snapshots[index - 1]

    def _player_stats_snapshot_segment(self, snapshot) -> tuple[object, ...]:
        try:
            index = self.player_stats_vod_snapshots.index(snapshot)
        except ValueError:
            return (snapshot,)
        start_index = max(0, index - 1)
        return tuple(self.player_stats_vod_snapshots[start_index : index + 1])

    def toggle_player_stats_recording(self):
        if self.player_stats_vod_recorder.is_recording or self._is_player_stats_recording_armed():
            self.player_stats_recording_armed = False
            self.player_stats_recording_waiting_mode = None
            if bool(getattr(config, "AUTO_START_RECORDING", False)):
                self.player_stats_auto_recording_suppressed = True
            self._stop_player_stats_recording(log_message="[*] Player stats recording stopped.")
        else:
            self.player_stats_recording_armed = True
            self.player_stats_auto_recording_suppressed = False
            state = self._read_player_stats_recording_state_safe()
            seed = state.map_seed if state is not None else None
            stage_ptr = state.current_stage_ptr if state is not None else 0
            run_time_seconds = self._read_player_stats_recording_run_timer_safe()
            runtime_state = self._runtime_game_state_or_unknown()
            if runtime_state.mode is RuntimeGameMode.IN_GAME:
                vod_path = self._start_player_stats_recording(
                    seed=seed,
                    stage_ptr=stage_ptr,
                    run_time_seconds=run_time_seconds,
                )
                self.log(f"[*] Player stats recording started: {vod_path.name}", tag="success")
            else:
                self.player_stats_recording_waiting_mode = runtime_state.mode.value
                self.log(
                    "[*] Player stats recording armed; waiting for an active run.",
                    tag="success",
                )
            self.refresh_live_player_stats_now(
                waiting_status_text="Recording stats; waiting for game/player stats...",
                unavailable_status_prefix="Recording stats; player stats unavailable",
            )
            self._refresh_vods_list_if_visible()

        self.refresh_player_stats_timeline_ui()

    def _read_player_stats_recording_seed_safe(self) -> int | None:
        try:
            result = self.read_player_stats_recording_seed()
            PlayerStatsMixin._record_player_stats_game_data_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            PlayerStatsMixin._record_player_stats_game_data_memory_failure(self, exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_recording_state_safe(self):
        try:
            result = self.read_player_stats_recording_state()
            PlayerStatsMixin._record_player_stats_game_data_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            PlayerStatsMixin._record_player_stats_game_data_memory_failure(self, exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_runtime_game_state_safe(self):
        try:
            result = self.read_player_stats_runtime_game_state()
            PlayerStatsMixin._record_player_stats_game_data_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            PlayerStatsMixin._record_player_stats_game_data_memory_failure(self, exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _read_player_stats_runtime_activity_state_safe(self):
        try:
            result = self.read_player_stats_runtime_activity_state()
            PlayerStatsMixin._record_player_stats_game_data_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            PlayerStatsMixin._record_player_stats_game_data_memory_failure(self, exc)
            return None
        except Exception:
            self.close_player_stats_game_data_client()
            return None

    def _refresh_core_run_lifecycle_state(self) -> RuntimeGameState:
        now = time.monotonic()
        last_checked_at = getattr(self, "_core_runtime_game_state_checked_at", None)
        cached_state = getattr(self, "_core_runtime_game_state", None)
        if (
            cached_state is not None
            and last_checked_at is not None
            and now - last_checked_at < CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS
        ):
            return cached_state

        state = self._read_player_stats_runtime_activity_state_safe()
        if state is None:
            state = RuntimeGameState(mode=RuntimeGameMode.UNKNOWN)
        self._core_runtime_game_state = state
        self._core_runtime_game_state_checked_at = now

        if state.is_active_run:
            self._player_stats_completed_run = False
        elif state.mode is RuntimeGameMode.GAME_OVER and not bool(
            getattr(self, "_player_stats_completed_run", False)
        ):
            self._player_stats_completed_run = True
            mark_completed = getattr(self.live_run_tracker, "mark_run_completed", None)
            if callable(mark_completed):
                mark_completed()
        return state

    def _runtime_game_state_or_unknown(self):
        state = self._read_player_stats_runtime_game_state_safe()
        if state is None:
            return RuntimeGameState(mode=RuntimeGameMode.UNKNOWN)
        return state

    def _runtime_state_for_refresh(self) -> RuntimeGameState:
        cached_state = getattr(self, "_core_runtime_game_state", None)
        checked_at = getattr(self, "_core_runtime_game_state_checked_at", None)
        if cached_state is not None and checked_at is not None:
            if time.monotonic() - checked_at <= CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS:
                return cached_state
        return self._runtime_game_state_or_unknown()

    def _read_player_stats_recording_run_timer_safe(self) -> float | None:
        try:
            result = self._get_player_stats_client().get_run_timer()
            self._record_player_stats_memory_success()
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            self._record_player_stats_memory_failure(exc)
            return None
        except Exception:
            self.close_player_stats_client()
            return None

    @staticmethod
    def _seed_change_looks_like_same_run(
        previous_run_time_seconds: float | None,
        current_run_time_seconds: float | None,
    ) -> bool:
        if previous_run_time_seconds is None or current_run_time_seconds is None:
            return False
        return (
            current_run_time_seconds + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
            >= previous_run_time_seconds
        )

    @staticmethod
    def _stage_change_looks_like_same_run(
        previous_stage_ptr: int,
        current_stage_ptr: int,
        previous_run_time_seconds: float | None,
        current_run_time_seconds: float | None,
    ) -> bool:
        if (
            not previous_stage_ptr
            or not current_stage_ptr
            or previous_stage_ptr == current_stage_ptr
        ):
            return False
        return PlayerStatsMixin._seed_change_looks_like_same_run(
            previous_run_time_seconds,
            current_run_time_seconds,
        )

    def _start_player_stats_recording(
        self,
        *,
        seed: int | None = None,
        stage_ptr: int = 0,
        run_time_seconds: float | None = None,
    ):
        vod_path = self.player_stats_vod_recorder.start(seed=seed)
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_recording_seed = seed
        self.player_stats_recording_stage_ptr = stage_ptr
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = run_time_seconds
        self.player_stats_recording_waiting_mode = None
        self.player_stats_auto_recording_suppressed = False
        self.player_stats_auto_start_detection_streak = 0
        return vod_path

    def _stop_player_stats_recording(
        self,
        *,
        log_message: str | None = None,
        log_tag: str | None = None,
        refresh_live_stats: bool = True,
    ) -> None:
        self.player_stats_vod_recorder.stop()
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_recording_seed = None
        self.player_stats_recording_stage_ptr = 0
        self.player_stats_recording_seed_missing_since = None
        self.player_stats_recording_run_time_seconds = None
        self.player_stats_recording_waiting_mode = None
        self.player_stats_auto_start_detection_streak = 0
        self.close_player_stats_game_data_client()
        if log_message:
            self.log(log_message, tag=log_tag)
        if refresh_live_stats:
            self.refresh_live_player_stats_now()
        self._refresh_vods_list_if_visible()

    def _sync_player_stats_recording_run_state(self) -> str | None:
        runtime_state = self._runtime_game_state_or_unknown()
        if runtime_state.mode is RuntimeGameMode.GAME_OVER:
            self._player_stats_completed_run = True
            mark_completed = getattr(self.live_run_tracker, "mark_run_completed", None)
            if callable(mark_completed):
                mark_completed()
        if runtime_state.mode is RuntimeGameMode.IN_GAME:
            self._player_stats_completed_run = False
            self.player_stats_recording_waiting_mode = None
            if self._is_player_stats_recording_armed() and not self.player_stats_vod_recorder.is_recording:
                current_state = self._read_player_stats_recording_state_safe()
                current_seed = current_state.map_seed if current_state is not None else None
                current_stage_ptr = (
                    current_state.current_stage_ptr if current_state is not None else 0
                )
                current_run_time_seconds = self._read_player_stats_recording_run_timer_safe()
                vod_path = self._start_player_stats_recording(
                    seed=current_seed,
                    stage_ptr=current_stage_ptr,
                    run_time_seconds=current_run_time_seconds,
                )
                self.log(
                    f"[*] Player stats recording started from waiting mode: {vod_path.name}",
                    tag="success",
                )
                self.refresh_player_stats_timeline_ui()
                return "started"

        if not self.player_stats_vod_recorder.is_recording:
            return None

        if runtime_state.mode is RuntimeGameMode.PAUSED_IN_GAME:
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            return "paused"
        if runtime_state.mode in {RuntimeGameMode.GAME_OVER, RuntimeGameMode.MAIN_MENU}:
            mode_text = "game over" if runtime_state.mode is RuntimeGameMode.GAME_OVER else "main menu"
            should_remain_armed = self._is_player_stats_recording_armed()
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            self._stop_player_stats_recording(
                log_message=f"[*] Player stats recording waiting: {mode_text}.",
                log_tag="warning",
                refresh_live_stats=False,
            )
            if not should_remain_armed:
                self.player_stats_recording_armed = False
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            self.refresh_player_stats_timeline_ui()
            return "waiting"
        if runtime_state.mode is RuntimeGameMode.UNKNOWN:
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            return None

        now = time.monotonic()
        current_state = self._read_player_stats_recording_state_safe()
        current_seed = current_state.map_seed if current_state is not None else None
        current_stage_ptr = (
            current_state.current_stage_ptr if current_state is not None else 0
        )
        current_run_time_seconds = self._read_player_stats_recording_run_timer_safe()
        if current_seed is None:
            if self.player_stats_recording_seed_missing_since is None:
                self.player_stats_recording_seed_missing_since = now
                return None
            if now - self.player_stats_recording_seed_missing_since < PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS:
                return None
            self.player_stats_recording_armed = False
            self._stop_player_stats_recording(
                log_message="[*] Player stats recording auto-stopped: run seed disappeared.",
                log_tag="warning",
                refresh_live_stats=False,
            )
            self.refresh_player_stats_timeline_ui()
            return "stopped"

        self.player_stats_recording_seed_missing_since = None
        if self.player_stats_recording_seed is None:
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
        if (
            current_seed == self.player_stats_recording_seed
            and current_stage_ptr == self.player_stats_recording_stage_ptr
        ):
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        previous_seed = self.player_stats_recording_seed
        previous_stage_ptr = self.player_stats_recording_stage_ptr
        previous_run_time_seconds = self.player_stats_recording_run_time_seconds
        if self._stage_change_looks_like_same_run(
            previous_stage_ptr,
            current_stage_ptr,
            previous_run_time_seconds,
            current_run_time_seconds,
        ):
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None
        if self._seed_change_looks_like_same_run(
            previous_run_time_seconds,
            current_run_time_seconds,
        ):
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        self._stop_player_stats_recording(refresh_live_stats=False)
        vod_path = self._start_player_stats_recording(
            seed=current_seed,
            stage_ptr=current_stage_ptr,
            run_time_seconds=current_run_time_seconds,
        )
        self.log(
            f"[*] Player stats recording auto-split: seed {previous_seed} -> {current_seed}; new file {vod_path.name}",
            tag="success",
        )
        self.refresh_player_stats_timeline_ui()
        return "split"

    @staticmethod
    def _looks_like_active_run_for_auto_recording(
        *,
        stats,
        run_timer_seconds: float | None,
        player_level: int | None,
        map_seed: int | None,
        stage_ptr: int,
    ) -> bool:
        if run_timer_seconds is None or float(run_timer_seconds) <= 0:
            return False
        if map_seed is not None:
            return True
        if int(stage_ptr or 0) > 0:
            return True
        if player_level is not None and int(player_level) > 0:
            return True
        return bool(stats)

    def _maybe_auto_start_player_stats_recording(
        self,
        *,
        stats,
        run_timer_seconds: float | None,
        player_level: int | None,
        map_seed: int | None,
        stage_ptr: int,
    ) -> bool:
        if self.player_stats_vod_recorder.is_recording:
            self.player_stats_auto_start_detection_streak = 0
            return False
        if bool(getattr(self, "player_stats_auto_recording_suppressed", False)):
            self.player_stats_auto_start_detection_streak = 0
            return False
        if not bool(getattr(config, "AUTO_START_RECORDING", False)):
            self.player_stats_auto_start_detection_streak = 0
            return False
        if not self._looks_like_active_run_for_auto_recording(
            stats=stats,
            run_timer_seconds=run_timer_seconds,
            player_level=player_level,
            map_seed=map_seed,
            stage_ptr=stage_ptr,
        ):
            self.player_stats_auto_start_detection_streak = 0
            return False

        self.player_stats_auto_start_detection_streak = int(
            getattr(self, "player_stats_auto_start_detection_streak", 0)
        ) + 1
        if self.player_stats_auto_start_detection_streak < 2:
            return False

        vod_path = self._start_player_stats_recording(
            seed=map_seed,
            stage_ptr=stage_ptr,
            run_time_seconds=run_timer_seconds,
        )
        self.log(f"[*] Player stats recording auto-started: {vod_path.name}", tag="success")
        return True

    def on_player_stats_slider_changed(self, value):
        snapshot_count = len(self.player_stats_vod_snapshots)
        if snapshot_count == 0:
            return
        index = min(max(int(round(float(value))), 0), snapshot_count - 1)
        if self.player_stats_selected_snapshot_index == index:
            return
        self.player_stats_selected_snapshot_index = index
        self.display_player_stats_snapshot(self.player_stats_vod_snapshots[index])
        self.refresh_player_stats_timeline_ui(update_slider=False)

    def refresh_player_stats_timeline_ui(self, *, update_slider: bool = True):
        snapshot_count = len(self.player_stats_vod_snapshots)
        recording_armed = self._is_player_stats_recording_armed()
        waiting_mode = getattr(self, "player_stats_recording_waiting_mode", None)

        if self.player_stats_vod_recorder.is_recording or recording_armed:
            self.player_stats_record_btn.setText("Stop Recording")
            self.player_stats_record_btn.setStyleSheet(
                _button_state_stylesheet(
                    PLAYER_STATS_ACTIVE_BUTTON_COLOR,
                    PLAYER_STATS_ACTIVE_BUTTON_HOVER_COLOR,
                )
            )
        else:
            self.player_stats_record_btn.setText(f"Start Recording ({config.PLAYER_STATS_RECORD_HOTKEY.upper()})")
            self.player_stats_record_btn.setStyleSheet(
                _button_state_stylesheet(
                    PLAYER_STATS_INACTIVE_BUTTON_COLOR,
                    PLAYER_STATS_INACTIVE_BUTTON_HOVER_COLOR,
                )
            )

        if self.player_stats_vod_recorder.is_recording and snapshot_count:
            self.player_stats_slider.setEnabled(True)
            self.player_stats_slider.setMaximum(max(snapshot_count - 1, 1))
            if update_slider:
                index = self.player_stats_selected_snapshot_index
                self.player_stats_slider.setValue(index if index is not None else snapshot_count - 1)
        else:
            self.player_stats_slider.setEnabled(False)
            self.player_stats_slider.setMaximum(1)
            self.player_stats_slider.setValue(0)

        if self.player_stats_vod_recorder.is_recording:
            prefix = f"Recording {self.player_stats_vod_recorder.elapsed_label()} | "
            if snapshot_count:
                selected = self.player_stats_selected_snapshot_index
                mode = self.player_stats_vod_snapshots[selected].time_label if selected is not None else "--"
                self.player_stats_timeline_label.setText(f"{prefix}{snapshot_count} snapshots | {mode}")
            elif waiting_mode == RuntimeGameMode.PAUSED_IN_GAME.value:
                self.player_stats_timeline_label.setText(f"{prefix}Paused in game")
            else:
                self.player_stats_timeline_label.setText(f"{prefix}No snapshots")
        elif recording_armed:
            self.player_stats_timeline_label.setText("Recording armed | waiting for run")
        else:
            self.player_stats_timeline_label.setText("Live stats")

        if self.player_stats_vod_recorder.is_recording and snapshot_count:
            first = self.player_stats_vod_snapshots[0].time_label
            last = self.player_stats_vod_snapshots[-1].time_label
            selected = self.player_stats_selected_snapshot_index
            current = self.player_stats_vod_snapshots[selected].time_label if selected is not None else "--"
            self.player_stats_slider_time_label.setText(f"Timeline: {first} - {last} | Selected: {current}")
        elif self.player_stats_vod_recorder.is_recording:
            self.player_stats_slider_time_label.setText(
                f"Timeline: recording {self.player_stats_vod_recorder.elapsed_label()} | waiting for first snapshot"
            )
        elif recording_armed:
            self.player_stats_slider_time_label.setText("Timeline: recording armed | waiting for run")
        else:
            self.player_stats_slider_time_label.setText("Timeline: live stats")

    def refresh_vods_list(self):
        if self.vods_list_frame is None:
            return

        vods = list(getattr(self, "_vod_metadata_index", ()))
        selected_path = self.loaded_vod.metadata.path if self.loaded_vod is not None else None
        signature = (
            str(selected_path) if selected_path is not None else "",
            tuple((str(vod.path), vod.name, vod.snapshot_count, vod.duration_seconds) for vod in vods),
        )
        self._ensure_vod_metadata_refresh()
        if self.vods_list_signature == signature:
            return

        self.vods_list_frame.blockSignals(True)
        self.vods_list_frame.clear()
        if not vods:
            item = QListWidgetItem("No saved recordings")
            item.setFlags(Qt.NoItemFlags)
            self.vods_list_frame.addItem(item)
            self.vods_list_frame.blockSignals(False)
            self.vods_list_signature = signature
            return

        selected_row = None
        for row, vod in enumerate(vods):
            duration = self.format_duration(vod.duration_seconds)
            item = QListWidgetItem(f"{vod.name}\n{vod.snapshot_count} snapshots | {duration}")
            item.setData(Qt.UserRole, str(vod.path))
            self.vods_list_frame.addItem(item)
            if selected_path == vod.path:
                selected_row = row
        if selected_row is not None:
            self.vods_list_frame.setCurrentRow(selected_row)
        self.vods_list_frame.blockSignals(False)
        self.vods_list_signature = signature

    def _ensure_vod_metadata_refresh(self) -> None:
        if getattr(self, "_vod_metadata_refresh_running", False):
            return
        self._vod_metadata_refresh_running = True
        generation = int(getattr(self, "_vod_metadata_refresh_generation", 0)) + 1
        self._vod_metadata_refresh_generation = generation

        def refresh() -> None:
            try:
                vods = refresh_vod_metadata_index()
                error = None
            except Exception as exc:
                vods = []
                error = exc

            def apply_result() -> None:
                if generation != getattr(self, "_vod_metadata_refresh_generation", 0):
                    return
                self._vod_metadata_refresh_running = True
                if error is not None:
                    self._vod_metadata_refresh_running = False
                    _set_text(getattr(self, "vods_status_label", None), f"Could not refresh recordings: {error}")
                    return
                self._vod_metadata_index = tuple(vods)
                self.vods_list_signature = None
                self.compare_runs_list_signature = None
                self.refresh_vods_list()
                self.refresh_compare_runs_list()
                self._vod_metadata_refresh_running = False

            after = getattr(self, "after", None)
            if callable(after) and getattr(self, "_invoker", None) is not None:
                after(0, apply_result)
            else:
                apply_result()

        threading.Thread(target=refresh, name="vod-metadata-index", daemon=True).start()

    def toggle_recordings_chooser(self):
        next_expanded = not bool(getattr(self, "recordings_chooser_expanded", False))
        self.set_recordings_chooser_expanded(next_expanded, guided=False)

    def ensure_recordings_chooser_for_empty_selection(self) -> None:
        if not self._is_recordings_tab_active():
            return
        if self.loaded_vod is not None:
            return
        if bool(getattr(self, "recordings_chooser_expanded", False)):
            return
        self.set_recordings_chooser_expanded(True, guided=True)

    def set_recordings_chooser_expanded(self, expanded: bool, *, guided: bool) -> None:
        self.recordings_chooser_expanded = bool(expanded)
        self.recordings_guided_selection_active = bool(expanded and guided)
        self._refresh_recordings_chooser()

    def _refresh_recordings_chooser(self) -> None:
        expanded = bool(getattr(self, "recordings_chooser_expanded", False))
        chooser = getattr(self, "vods_chooser_group", None)
        button = getattr(self, "vods_select_btn", None)
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
        self._vod_load_in_progress = bool(loading)
        has_recording = not loading and self.loaded_vod is not None
        has_snapshots = bool(has_recording and self.loaded_vod.snapshots)
        enabled_by_name = {
            "vods_name_entry": has_recording,
            "vods_rename_btn": has_recording,
            "vods_cleanup_btn": not loading,
            "vods_delete_btn": has_recording,
            "vods_slider": has_snapshots,
        }
        for name, enabled in enabled_by_name.items():
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(enabled)
        self._refresh_vod_compare_controls()

    def load_selected_vod(self, path):
        path = Path(path)
        generation = int(getattr(self, "_vod_load_generation", 0)) + 1
        self._vod_load_generation = generation
        self.loaded_vod = None
        self.loaded_vod_snapshot_index = None
        self.loaded_vod_compare_start_index = None
        self._set_vod_loading_state(True)
        _set_text(getattr(self, "vods_status_label", None), "Loading recording…")

        def finish(loaded_vod, error) -> None:
            if generation != getattr(self, "_vod_load_generation", 0):
                return
            if error is not None:
                self._clear_loaded_vod_selection()
                _set_text(self.vods_status_label, f"Could not load recording: {error}")
                self._set_vod_loading_state(False)
                return
            self.loaded_vod = loaded_vod
            self.loaded_vod_snapshot_index = 0 if loaded_vod.snapshots else None
            self.loaded_vod_compare_start_index = None
            self.vods_compare_details_expanded = False
            _clear_text_input(self.vods_name_entry)
            _set_text_input(self.vods_name_entry, loaded_vod.metadata.name)
            self.refresh_loaded_vod_ui()
            self._set_vod_loading_state(False)
            self.refresh_vods_list()
            if bool(getattr(self, "recordings_chooser_expanded", False)) and bool(
                getattr(self, "recordings_guided_selection_active", False)
            ):
                self.set_recordings_chooser_expanded(False, guided=False)

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
            threading.Thread(target=load, name="vod-loader", daemon=True).start()
        else:
            load()

    def refresh_loaded_vod_ui(self, *, update_slider: bool = True):
        if self.loaded_vod is None:
            return

        snapshot_count = len(self.loaded_vod.snapshots)
        metadata = self.loaded_vod.metadata
        duration = self.format_duration(metadata.duration_seconds)
        _set_text(self.vods_status_label, f"{metadata.created_label} | {snapshot_count} snapshots | {duration}")

        if snapshot_count:
            self.vods_slider.setEnabled(True)
            self.vods_slider.setMaximum(max(snapshot_count - 1, 1))
            if update_slider:
                self.vods_slider.setValue(self.loaded_vod_snapshot_index or 0)
            self.display_loaded_vod_snapshot(self.loaded_vod_snapshot_index or 0)
        else:
            self.vods_slider.setEnabled(False)
            self.vods_slider.setMaximum(1)
            self.vods_slider.setValue(0)
            for label in self.vods_rows.values():
                _set_text(label, "--")
            _set_text(self.vods_slider_time_label, "Timeline: --")
            self.vods_items_expanded = False
            self._update_items_section("vod", items_text="--")
            _set_text(self.vods_chests_per_minute_label, "Average chests/min: --")
            _set_text(self.vods_in_game_time_label, "In-Game Time: --")
            _set_text(self.vods_mob_kills_label, "Mob Kills: --")
            _set_text(getattr(self, "vods_kps_averages_label", None), "KPS: --")
            _set_text(self.vods_level_label, "Level: --")
            self._set_chests_card_values(
                getattr(self, "vods_chests_card_values", None),
                None,
            )
            _set_text(self.vods_new_items_label, "No previous snapshot")
            self._refresh_vod_compare_controls()
            self._refresh_vod_compare_details(None, None, index=None)
            _set_text(self.vods_banishes_label, "No banishes yet")
            self._set_stage_summary_labels(self.vods_stage_summary_labels, None)
            self.vods_weapon_signature = None
            self.display_weapon_cards((), scope="vod", status_text="No weapon data in this recording")
            self.vods_tome_signature = None
            self.display_tome_cards((), scope="vod", status_text="No tome data in this recording")
            self.vods_chaos_signature = None
            self.display_chaos_tome_card(None, scope="vod", status_text="No Chaos Tome data in this recording")
            self.vods_damage_source_signature = None
            self.display_damage_source_rows((), scope="vod", status_text="No damage source data in this recording")

    def display_loaded_vod_snapshot(self, index: int):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return
        index = min(max(index, 0), len(self.loaded_vod.snapshots) - 1)
        self.loaded_vod_snapshot_index = index
        snapshot = self.loaded_vod.snapshots[index]
        _set_text(
            self.vods_status_label,
            (
                f"{self.loaded_vod.metadata.name} | {index + 1}/{len(self.loaded_vod.snapshots)}"
                f" at {snapshot.time_label} | {self.format_in_game_time(snapshot.game_time_seconds)}"
            ),
        )
        first = self.loaded_vod.snapshots[0].time_label
        last = self.loaded_vod.snapshots[-1].time_label
        _set_text(self.vods_slider_time_label, f"Timeline: {first} - {last} | Selected: {snapshot.time_label}")
        for spec_group in PLAYER_STAT_GROUPS:
            for spec in spec_group:
                value_label = self.vods_rows.get(spec.label)
                if value_label is not None:
                    stat = snapshot.stats.get(spec.label)
                    _set_text(value_label, stat.display_value if stat is not None else "--")
        self._update_items_section("vod", snapshot.items)
        _set_text(
            self.vods_chests_per_minute_label,
            self.format_chests_per_minute(self.resolve_snapshot_chests_per_minute(snapshot)),
        )
        _set_text(
            self.vods_in_game_time_label,
            self.format_in_game_time(snapshot.game_time_seconds),
        )
        _set_text(
            self.vods_mob_kills_label,
            self.format_mob_kills(
                getattr(snapshot, "mob_kills", None),
                getattr(snapshot, "kps_at_capture", None),
            ),
        )
        _set_text(
            getattr(self, "vods_kps_averages_label", None),
            self.format_kps_averages(
                getattr(snapshot, "minute_avg_kps_at_capture", None),
                getattr(snapshot, "five_minute_avg_kps_at_capture", None),
            ),
        )
        _set_text(
            self.vods_level_label,
            self.format_player_level(getattr(snapshot, "player_level", None)),
        )
        self._update_recorded_chest_summary(snapshot)
        self._set_stage_summary_labels(
            self.vods_stage_summary_labels,
            self.build_stage_summary(self.loaded_vod.snapshots[: index + 1]),
        )
        previous_snapshot = self._resolve_vod_compare_base_snapshot(index)
        segment_snapshots = self._vod_compare_segment_snapshots(index)
        _set_text(
            self.vods_new_items_label,
            self.format_snapshot_item_gains_preview(previous_snapshot, snapshot, segment_snapshots=segment_snapshots),
        )
        self._refresh_vod_compare_controls()
        self._refresh_vod_compare_details(previous_snapshot, snapshot, index=index, segment_snapshots=segment_snapshots)
        _set_text(
            self.vods_banishes_label,
            self.format_banishes_rich_text(getattr(snapshot, "banishes", ())),
        )
        self.display_weapon_cards(getattr(snapshot, "weapons", ()), scope="vod")
        self.display_tome_cards(getattr(snapshot, "tomes", ()), scope="vod")
        self.display_chaos_tome_card(
            getattr(snapshot, "chaos_tome", None),
            scope="vod",
            status_text=None if getattr(snapshot, "chaos_tome", None) is not None else "No Chaos Tome data in this snapshot",
        )
        self.display_damage_source_rows(getattr(snapshot, "damage_sources", ()), scope="vod")

    def on_vods_slider_changed(self, value):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return
        index = min(max(int(round(float(value))), 0), len(self.loaded_vod.snapshots) - 1)
        if self.loaded_vod_snapshot_index == index:
            return
        self.display_loaded_vod_snapshot(index)

    def set_vod_compare_start(self):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return
        index = self.loaded_vod_snapshot_index
        if index is None:
            index = 0
        self.loaded_vod_compare_start_index = min(max(int(index), 0), len(self.loaded_vod.snapshots) - 1)
        self.vods_compare_details_expanded = True
        self.display_loaded_vod_snapshot(self.loaded_vod_snapshot_index or 0)

    def clear_vod_compare_start(self):
        self.loaded_vod_compare_start_index = None
        self.vods_compare_details_expanded = False
        if self.loaded_vod is not None and self.loaded_vod.snapshots:
            self.display_loaded_vod_snapshot(self.loaded_vod_snapshot_index or 0)
        else:
            self._refresh_vod_compare_controls()
            self._refresh_vod_compare_details(None, None, index=None)

    def toggle_vod_compare_details(self):
        self.vods_compare_details_expanded = not bool(getattr(self, "vods_compare_details_expanded", False))
        if self.loaded_vod is not None and self.loaded_vod.snapshots:
            self.display_loaded_vod_snapshot(self.loaded_vod_snapshot_index or 0)
        else:
            self._refresh_vod_compare_details(None, None, index=None)

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
            duration = self.format_duration(vod.duration_seconds)
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

    @staticmethod
    def _set_visible(widget, visible: bool) -> None:
        if widget is not None and hasattr(widget, "setVisible"):
            widget.setVisible(visible)

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
        duration = self.format_duration(vod.metadata.duration_seconds)
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

    @staticmethod
    def _checkbox_checked(checkbox) -> bool:
        return bool(checkbox is not None and checkbox.isChecked())

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
        game_time = getattr(snapshot, "game_time_seconds", None)
        if game_time is not None:
            return float(game_time)
        elapsed = getattr(snapshot, "elapsed_seconds", None)
        if elapsed is not None:
            return float(elapsed)
        return None

    def _resolve_vod_compare_base_snapshot(self, index: int):
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return None
        compare_index = getattr(self, "loaded_vod_compare_start_index", None)
        if compare_index is not None:
            compare_index = min(max(int(compare_index), 0), len(self.loaded_vod.snapshots) - 1)
            return self.loaded_vod.snapshots[compare_index]
        if index <= 0:
            return None
        return self.loaded_vod.snapshots[index - 1]

    def _vod_compare_segment_snapshots(self, index: int) -> tuple[object, ...]:
        if self.loaded_vod is None or not self.loaded_vod.snapshots:
            return ()
        compare_index = getattr(self, "loaded_vod_compare_start_index", None)
        if compare_index is None:
            start_index = max(0, index - 1)
        else:
            start_index = min(max(int(compare_index), 0), len(self.loaded_vod.snapshots) - 1)
        end_index = min(max(int(index), 0), len(self.loaded_vod.snapshots) - 1)
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        return tuple(self.loaded_vod.snapshots[start_index : end_index + 1])

    def _refresh_vod_compare_controls(self) -> None:
        has_snapshots = bool(
            not getattr(self, "_vod_load_in_progress", False)
            and self.loaded_vod is not None
            and self.loaded_vod.snapshots
        )
        compare_index = getattr(self, "loaded_vod_compare_start_index", None)
        set_btn = getattr(self, "vods_compare_set_btn", None)
        clear_btn = getattr(self, "vods_compare_clear_btn", None)
        details_btn = getattr(self, "vods_compare_details_btn", None)
        if set_btn is not None:
            set_btn.setEnabled(has_snapshots)
        if clear_btn is not None:
            clear_btn.setEnabled(has_snapshots and compare_index is not None)
        if details_btn is not None:
            details_btn.setVisible(has_snapshots)
            expanded = bool(getattr(self, "vods_compare_details_expanded", False))
            details_btn.setText("Hide details" if expanded else "Show details")

    def _refresh_vod_compare_details(self, base_snapshot, snapshot, *, index: int | None, segment_snapshots=()) -> None:
        self._refresh_vod_compare_controls()
        expanded = bool(getattr(self, "vods_compare_details_expanded", False))
        group = getattr(self, "vods_compare_details_group", None)
        if group is not None:
            group.setVisible(expanded and base_snapshot is not None and snapshot is not None)
        if base_snapshot is None or snapshot is None:
            _set_text(getattr(self, "vods_compare_details_summary_label", None), "--")
            _set_text(getattr(self, "vods_compare_details_items_label", None), "--")
            return

        compare_index = getattr(self, "loaded_vod_compare_start_index", None)
        base_index = compare_index if compare_index is not None else (index - 1 if index is not None else None)
        summary = self.format_snapshot_compare_summary(
            base_snapshot,
            snapshot,
            base_index=base_index,
            current_index=index,
            segment_snapshots=segment_snapshots,
        )
        _set_text(getattr(self, "vods_compare_details_summary_label", None), summary)
        _set_text(
            getattr(self, "vods_compare_details_items_label", None),
            self.format_snapshot_item_changes_details(base_snapshot, snapshot, segment_snapshots=segment_snapshots),
        )

    def rename_selected_vod(self):
        if self.loaded_vod is None or self.vods_name_entry is None:
            return
        new_name = _read_text(self.vods_name_entry).strip()
        try:
            metadata = rename_vod(self.loaded_vod.metadata.path, new_name)
            self.loaded_vod = load_vod(metadata.path)
        except Exception as exc:
            _set_text(self.vods_status_label, f"Could not rename recording: {exc}")
            return
        self.refresh_loaded_vod_ui(update_slider=False)
        self.refresh_vods_list()

    def _clear_loaded_vod_selection(self) -> None:
        self.loaded_vod = None
        self.loaded_vod_snapshot_index = None
        self.loaded_vod_compare_start_index = None
        self.vods_compare_details_expanded = False
        _clear_text_input(self.vods_name_entry)
        _set_text(self.vods_status_label, "Select a recording")
        self.vods_slider.setEnabled(False)
        self.vods_slider.setMaximum(1)
        self.vods_slider.setValue(0)
        _set_text(self.vods_slider_time_label, "Timeline: --")
        for label in self.vods_rows.values():
            _set_text(label, "--")
        self.vods_items_expanded = False
        self._update_items_section("vod", items_text="--")
        _set_text(self.vods_chests_per_minute_label, "Average chests/min: --")
        _set_text(self.vods_in_game_time_label, "In-Game Time: --")
        _set_text(self.vods_mob_kills_label, "Mob Kills: --")
        _set_text(getattr(self, "vods_kps_averages_label", None), "KPS: --")
        _set_text(self.vods_level_label, "Level: --")
        self._set_chests_card_values(
            getattr(self, "vods_chests_card_values", None),
            None,
        )
        _set_text(self.vods_new_items_label, "No previous snapshot")
        self._refresh_vod_compare_controls()
        self._refresh_vod_compare_details(None, None, index=None)
        _set_text(self.vods_banishes_label, "No banishes yet")
        self._set_stage_summary_labels(self.vods_stage_summary_labels, None)
        self.vods_weapon_signature = None
        self.display_weapon_cards((), scope="vod", status_text="Select a recording")
        self.vods_tome_signature = None
        self.display_tome_cards((), scope="vod", status_text="Select a recording")
        self.vods_chaos_signature = None
        self.display_chaos_tome_card(None, scope="vod", status_text="Select a recording")
        self.vods_damage_source_signature = None
        self.display_damage_source_rows((), scope="vod", status_text="Select a recording")

    def cleanup_recordings_by_snapshot_count(self):
        dialog = CleanupRecordingsDialog(self.window)
        if dialog.exec() != QDialog.Accepted or dialog.threshold is None:
            return

        selected_path = self.loaded_vod.metadata.path if self.loaded_vod is not None else None
        recorder = getattr(self, "player_stats_vod_recorder", None)
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
            _set_text(self.vods_status_label, f"Could not clean recordings: {exc}")
            return

        if selected_path is not None and not selected_path.exists():
            self._clear_loaded_vod_selection()

        self.refresh_vods_list()
        message = f"[*] Removed {result.removed} recordings with snapshot count below {dialog.threshold}."
        skipped = result.skipped_active + result.skipped_locked
        if skipped:
            message += f" Skipped {skipped} active or locked recording(s)."
        self.log(message, tag="success")

    def delete_selected_vod(self):
        if self.loaded_vod is None:
            return
        dialog = ConfirmDeleteRecordingDialog(self.window, self.loaded_vod.metadata.name)
        dialog.exec()
        if not dialog.result:
            return
        path = self.loaded_vod.metadata.path
        try:
            delete_vod(path)
        except Exception as exc:
            _set_text(self.vods_status_label, f"Could not delete recording: {exc}")
            return
        self._clear_loaded_vod_selection()
        self.refresh_vods_list()

    def toggle_player_items_expanded(self) -> None:
        self.player_stats_items_expanded = not self.player_stats_items_expanded
        self._update_items_section(
            "live",
            self.player_stats_items_current,
            items_text=self.player_stats_items_text_current,
        )

    def toggle_vod_items_expanded(self) -> None:
        self.vods_items_expanded = not self.vods_items_expanded
        self._update_items_section(
            "vod",
            self.vods_items_current,
            items_text=self.vods_items_text_current,
        )

    def on_items_sort_changed(self, scope: str) -> None:
        prefix = self._scope_prefix(scope)
        combo = self.__dict__.get(f"{prefix}_items_sort_combo")
        mode = ITEM_SORT_DEFAULT
        if combo is not None and hasattr(combo, "currentData"):
            mode = combo.currentData() or ITEM_SORT_DEFAULT
        setattr(self, f"{prefix}_items_sort_mode", mode)
        self._update_items_section(
            scope,
            self.__dict__.get(f"{prefix}_items_current", ()),
            items_text=self.__dict__.get(f"{prefix}_items_text_current"),
        )

    def _update_items_section(self, scope: str, items=(), *, items_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        group = self.__dict__.get(f"{prefix}_items_group")
        label = self.__dict__.get(f"{prefix}_items_label")
        rarity_label = self.__dict__.get(f"{prefix}_items_rarity_label")
        button = self.__dict__.get(f"{prefix}_items_toggle_btn")
        sort_combo = self.__dict__.get(f"{prefix}_items_sort_combo")
        expanded = bool(self.__dict__.get(f"{prefix}_items_expanded", False))
        setattr(self, f"{prefix}_items_current", tuple(items or ()))
        setattr(self, f"{prefix}_items_text_current", items_text)

        if label is None:
            return

        if items_text is not None:
            self._set_items_group_title(group, None)
            _set_items_text(label, items_text=items_text)
            self._set_items_rarity_summary_label(rarity_label, ())
            if button is not None:
                button.setVisible(True)
                button.setEnabled(False)
                button.setText("Show more")
            if sort_combo is not None:
                sort_combo.setEnabled(False)
            return

        items = tuple(items or ())
        self._set_items_group_title(group, self._item_total_count(items))
        self._set_items_rarity_summary_label(rarity_label, items)
        sorted_items = self.sort_items_for_display(
            items,
            self.__dict__.get(f"{prefix}_items_sort_mode", ITEM_SORT_DEFAULT),
        )
        preview_items, has_more = self._items_preview(sorted_items)
        visible_items = sorted_items if expanded or not has_more else preview_items
        if sort_combo is not None:
            sort_combo.setEnabled(bool(items))
        if hasattr(label, "setTextFormat"):
            text = self.format_items_rich_text(visible_items)
            if has_more and not expanded:
                text = f'{text} <span style="color:#98A7BA;">...</span>'
            label.setText(text)
        else:
            text = self.format_items(visible_items)
            if has_more and not expanded:
                text = f"{text} ..."
            _set_text(label, text)

        if button is not None:
            button.setVisible(True)
            button.setEnabled(has_more)
            button.setText("Show less" if expanded and has_more else "Show more")

    @classmethod
    def _item_total_count(cls, items) -> int:
        return sum(cls._item_counts(items).values())

    @classmethod
    def _item_rarity_totals(cls, items) -> dict[str, int]:
        rarity_totals = {
            "LEGENDARY": 0,
            "RARE": 0,
            "UNCOMMON": 0,
            "COMMON": 0,
        }
        for item_name, count in cls._item_counts(items).items():
            display_name = cls._normalize_item_name_for_display(item_name)
            rarity_name = cls._normalize_item_name_for_rarity(display_name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
            if rarity in rarity_totals:
                rarity_totals[rarity] += count
        return rarity_totals

    @classmethod
    def _empty_item_rarity_totals(cls) -> dict[str, int]:
        return {
            "LEGENDARY": 0,
            "RARE": 0,
            "UNCOMMON": 0,
            "COMMON": 0,
        }

    @classmethod
    def format_items_rarity_summary_rich_text(cls, items) -> str:
        rarity_totals = cls._item_rarity_totals(items)
        parts: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
            total = rarity_totals.get(rarity, 0)
            if total <= 0:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            parts.append(
                f'<span style="color:{color}; font-weight:700;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{html.escape(str(total))}</span>'
            )
        return "  ".join(parts)

    @staticmethod
    def _set_items_rarity_summary_label(label, items) -> None:
        if label is None:
            return
        text = PlayerStatsMixin.format_items_rarity_summary_rich_text(items)
        label.setVisible(bool(text))
        label.setText(text)

    @staticmethod
    def _set_items_group_title(group, total_count: int | None) -> None:
        if group is None or not hasattr(group, "setTitle"):
            return
        title = "Items" if total_count is None else f"Items ({total_count} total)"
        group.setTitle(title)

    @classmethod
    def sort_items_for_display(cls, items, mode: str | None) -> tuple[str, ...]:
        items = tuple(items or ())
        if mode == ITEM_SORT_DEFAULT or not items:
            return items
        reverse = mode == ITEM_SORT_RARITY_DESC
        if mode not in (ITEM_SORT_RARITY_ASC, ITEM_SORT_RARITY_DESC):
            return items

        def sort_key(entry) -> tuple[int, int]:
            index, item = entry
            rarity_rank = cls._item_rarity_rank(str(item))
            return (-rarity_rank if reverse else rarity_rank, index)

        return tuple(item for _index, item in sorted(enumerate(items), key=sort_key))

    @classmethod
    def _item_rarity_rank(cls, item_text: str) -> int:
        item_name, _suffix = cls._split_item_stack_suffix(item_text)
        display_name = cls._normalize_item_name_for_display(item_name)
        rarity_name = cls._normalize_item_name_for_rarity(display_name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
        return ITEM_RARITY_SORT_ORDER.get(rarity, -1)

    @staticmethod
    def _items_preview(items) -> tuple[tuple[str, ...], bool]:
        items = tuple(items or ())
        if len(items) <= 1:
            return items, False

        preview: list[str] = []
        max_chars = 90
        current_length = 0
        for item in items:
            separator_length = 2 if preview else 0
            projected_length = current_length + separator_length + len(item)
            if preview and projected_length > max_chars:
                break
            preview.append(item)
            current_length = projected_length

        if not preview:
            preview.append(items[0])
        return tuple(preview), len(preview) < len(items)

    def display_weapon_cards(self, weapons, *, scope: str, status_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        layout_attr = f"{prefix}_weapons_layout"
        status_attr = f"{prefix}_weapons_status_label"
        cards_attr = f"{prefix}_weapon_cards"
        signature_attr = f"{prefix}_weapon_signature"

        layout = getattr(self, layout_attr, None)
        status_label = getattr(self, status_attr, None)
        if layout is None or status_label is None:
            return

        weapons = tuple(weapons or ())
        signature = self._weapon_signature(weapons)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)
        setattr(self, cards_attr, [])

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if weapons else "No weapons available")

        if not weapons:
            return

        cards = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, weapon in enumerate(weapons):
            card = self._build_weapon_card(weapon)
            grid.addWidget(card, index // 2, index % 2)
            cards.append(card)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        setattr(self, cards_attr, cards)

    def _build_weapon_card(self, weapon: WeaponSnapshot) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        weapon_name_label = QLabel(weapon.name)
        weapon_name_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        weapon_level_label = QLabel(f"Lv. {weapon.level}")
        weapon_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        weapon_level_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        header_layout.addWidget(weapon_name_label, 1)
        header_layout.addWidget(weapon_level_label)
        layout.addLayout(header_layout)

        rows = QFormLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setVerticalSpacing(6)
        has_rows = False
        for stat_id in weapon.upgrade_stat_ids:
            stat = weapon.upgraded_stats.get(stat_id)
            if stat is None:
                continue
            value_label = QLabel(stat.display_value)
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rows.addRow(stat.label, value_label)
            has_rows = True
        if has_rows:
            layout.addLayout(rows)
        else:
            layout.addWidget(QLabel("No upgraded stats decoded"))
        layout.addStretch(1)
        return card

    @staticmethod
    def _weapon_signature(weapons) -> tuple:
        return tuple(
            (
                weapon.weapon_id,
                weapon.level,
                tuple(
                    (stat_id, weapon.upgraded_stats[stat_id].display_value)
                    for stat_id in weapon.upgrade_stat_ids
                    if stat_id in weapon.upgraded_stats
                ),
            )
            for weapon in weapons
        )

    def display_tome_cards(
        self,
        tomes,
        *,
        scope: str,
        status_text: str | None = None,
    ) -> None:
        prefix = self._scope_prefix(scope)
        layout_attr = f"{prefix}_tomes_layout"
        status_attr = f"{prefix}_tomes_status_label"
        cards_attr = f"{prefix}_tome_cards"
        signature_attr = f"{prefix}_tome_signature"

        layout = getattr(self, layout_attr, None)
        status_label = getattr(self, status_attr, None)
        if layout is None or status_label is None:
            return

        tomes = tuple(tomes or ())
        signature = self._tome_signature(tomes)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)
        setattr(self, cards_attr, [])

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if tomes else "No tomes available")

        if not tomes:
            return

        cards = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, tome in enumerate(tomes):
            card = self._build_tome_card(tome)
            grid.addWidget(card, index // 2, index % 2)
            cards.append(card)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        setattr(self, cards_attr, cards)

    def _build_tome_card(self, tome: TomeSnapshot) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        tome_name_label = QLabel(tome.name)
        tome_name_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        tome_level_label = QLabel(f"Lv. {tome.level}")
        tome_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tome_level_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        header_layout.addWidget(tome_name_label, 1)
        header_layout.addWidget(tome_level_label)
        layout.addLayout(header_layout)

        rows = QFormLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setVerticalSpacing(6)
        value_label = QLabel(tome.display_value)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rows.addRow(tome.stat_label, value_label)
        layout.addLayout(rows)
        return card

    @staticmethod
    def _tome_signature(tomes) -> tuple:
        return tuple(
            (
                tome.tome_id,
                tome.level,
                tome.stat_id,
                tome.stat_label,
                tome.display_value,
            )
            for tome in tomes
        )

    def display_chaos_tome_card(self, chaos_tome, *, scope: str, status_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        layout = getattr(self, f"{prefix}_chaos_layout", None)
        status_label = getattr(self, f"{prefix}_chaos_status_label", None)
        signature_attr = f"{prefix}_chaos_signature"
        if layout is None or status_label is None:
            return

        signature = self._chaos_tome_signature(chaos_tome)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if chaos_tome is not None else "No Chaos Tome data")

        if chaos_tome is None:
            return

        stats = self._chaos_stats_in_game_order(chaos_tome)
        summary_card = self._build_chaos_summary_card(chaos_tome)
        layout.addWidget(summary_card)

        if not stats:
            layout.addStretch(1)
            return

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for index, stat in enumerate(stats):
            grid.addWidget(self._build_chaos_stat_card(stat), index // 4, index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

    @staticmethod
    def _chaos_tome_signature(chaos_tome) -> tuple:
        if chaos_tome is None:
            return ()
        return (
            int(getattr(chaos_tome, "level", 0)),
            int(getattr(chaos_tome, "ambiguous_rolls", 0)),
            tuple(
                (
                    int(getattr(stat, "stat_id", -1)),
                    str(getattr(stat, "label", "")),
                    getattr(stat, "display_delta", "--"),
                    int(getattr(stat, "rolls", 0)),
                )
                for stat in PlayerStatsMixin._chaos_stats_in_game_order(chaos_tome)
            ),
        )

    def _build_chaos_summary_card(self, chaos_tome) -> QFrame:
        stats = self._chaos_stats_in_game_order(chaos_tome)
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title_label = QLabel("Chaos Tome")
        title_label.setStyleSheet("font-size: 13px; font-weight: 700;")
        level_label = QLabel(f"Lv. {int(getattr(chaos_tome, 'level', 0))}")
        level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        level_label.setStyleSheet("font-size: 13px; font-weight: 700;")
        header_layout.addWidget(title_label, 1)
        header_layout.addWidget(level_label)
        layout.addLayout(header_layout)

        rolls = sum(int(getattr(stat, "rolls", 0) or 0) for stat in stats)
        summary = QLabel(f"Tracked rolls: {rolls} | Stats: {len(stats)}")
        summary.setStyleSheet("color: #98A7BA;")
        layout.addWidget(summary)

        if stats:
            top_text = " | ".join(
                f"{self._chaos_stat_label(stat)} {getattr(stat, 'display_delta', '--')}"
                for stat in stats[:3]
            )
        else:
            top_text = "Tracking rolls..."
        top_label = QLabel(top_text)
        top_label.setWordWrap(True)
        top_label.setStyleSheet("font-weight: 700;")
        layout.addWidget(top_label)
        return card

    def _build_chaos_stat_card(self, stat) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        name_label = QLabel(self._chaos_stat_label(stat))
        name_label.setStyleSheet("font-size: 12px; font-weight: 700;")
        value_label = QLabel(getattr(stat, "display_delta", "--"))
        value_label.setStyleSheet("font-size: 12px; font-weight: 700;")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(name_label, 1)
        row.addWidget(value_label)
        layout.addLayout(row)
        return card

    @staticmethod
    def _chaos_stats_in_game_order(chaos_tome) -> tuple:
        return tuple(
            sorted(
                tuple(getattr(chaos_tome, "stats", ()) or ()),
                key=lambda stat: (
                    CHAOS_TOME_GAME_STAT_ORDER.get(int(getattr(stat, "stat_id", -1)), 999),
                    str(getattr(stat, "label", "")).casefold(),
                ),
            )
        )

    @staticmethod
    def _chaos_stat_label(stat) -> str:
        label = str(getattr(stat, "label", ""))
        return label or f"Stat {getattr(stat, 'stat_id', '?')}"

    def display_damage_source_rows(self, damage_sources, *, scope: str, status_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        layout_attr = f"{prefix}_damage_sources_layout"
        status_attr = f"{prefix}_damage_sources_status_label"
        signature_attr = f"{prefix}_damage_source_signature"

        layout = getattr(self, layout_attr, None)
        status_label = getattr(self, status_attr, None)
        if layout is None or status_label is None:
            return

        damage_sources = tuple(damage_sources or ())
        signature = self._damage_source_signature(damage_sources)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if damage_sources else "No damage source data yet")

        if not damage_sources:
            return

        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, source in enumerate(damage_sources):
            cell = QFrame()
            cell.setObjectName("StatCard")
            cell.setMinimumHeight(54)
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(12, 8, 12, 8)
            cell_layout.setSpacing(10)

            name_label = QLabel(source.source_name or source.source_key)
            name_label.setWordWrap(True)
            name_label.setStyleSheet("font-size: 16px; font-weight: 700;")
            cell_layout.addWidget(name_label, 1)

            dmg_label = QLabel(self.format_damage_source_value(source.damage))
            dmg_label.setStyleSheet("font-size: 17px; font-weight: 700; color: #F3F4F6;")
            dmg_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            cell_layout.addWidget(dmg_label)

            grid.addWidget(cell, index // 4, index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

    @staticmethod
    def _damage_source_signature(damage_sources) -> tuple:
        return tuple(
            (
                source.source_key,
                source.source_name,
                round(float(source.damage), 3),
            )
            for source in damage_sources
        )

    @staticmethod
    def format_duration(seconds: int) -> str:
        return PlayerStatsMixin.format_elapsed_time(seconds)

    @staticmethod
    def format_elapsed_time(seconds: float | int) -> str:
        minutes, seconds = divmod(max(int(seconds), 0), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @classmethod
    def format_in_game_time(cls, seconds: float | None) -> str:
        if seconds is None:
            return "In-Game Time: --"
        return f"In-Game Time: {cls.format_elapsed_time(seconds)}"

    @staticmethod
    def format_mob_kills(value: int | None, kps: int | None = None) -> str:
        if value is None:
            return "Mob Kills: --"
        formatted_value = PlayerStatsMixin.format_count(value)
        if kps is not None:
            return f"Mob Kills: {formatted_value} ({PlayerStatsMixin.format_count(kps)}/s)"
        return f"Mob Kills: {formatted_value}"

    @staticmethod
    def format_kps_averages(
        minute_avg_kps: int | None,
        five_minute_avg_kps: int | None,
    ) -> str:
        values = []
        for label, value in (
            ("60s", minute_avg_kps),
            ("5m", five_minute_avg_kps),
        ):
            if value is None:
                values.append(f"{label} --")
            else:
                values.append(f"{label} {PlayerStatsMixin.format_count(value)}/s")
        return f"KPS: {' | '.join(values)}"

    @staticmethod
    def format_count(value: int | float) -> str:
        return f"{max(0, int(value)):,}"

    @staticmethod
    def format_damage_source_value(value: int | float) -> str:
        value = max(0.0, float(value))
        suffixes = (
            "",
            "K",
            "M",
            "B",
            "T",
            "Q",
            "QI",
            "SX",
            "SP",
            "OC",
            "NO",
            "DC",
        )
        if value < 1000:
            return f"{int(round(value)):,}"

        suffix_index = 0
        while value >= 1000.0 and suffix_index < len(suffixes) - 1:
            value /= 1000.0
            suffix_index += 1

        if value >= 100:
            formatted = f"{value:.0f}"
        elif value >= 10:
            formatted = f"{value:.1f}"
        else:
            formatted = f"{value:.2f}"
        return f"{formatted}{suffixes[suffix_index]}"

    @staticmethod
    def format_player_level(value: int | None) -> str:
        if value is None:
            return "Level: --"
        return f"Level: {max(0, int(value))}"

    @staticmethod
    def format_items(items) -> str:
        if not items:
            return "--"
        return ", ".join(items)

    @classmethod
    def format_compare_run_snapshot_summary(cls, vod, snapshot, index: int) -> str:
        item_total = cls._snapshot_item_total(snapshot)
        rows = [
            f'<span style="color:#98A7BA;">Snapshot:</span> {index + 1}/{len(vod.snapshots)}',
            f'<span style="color:#98A7BA;">Record Time:</span> {html.escape(snapshot.time_label)}',
            f'<span style="color:#98A7BA;">In-Game:</span> {html.escape(cls.format_in_game_time(getattr(snapshot, "game_time_seconds", None)).replace("In-Game Time: ", ""))}',
            f'<span style="color:#98A7BA;">Kills:</span> {html.escape(cls.format_mob_kills(getattr(snapshot, "mob_kills", None)).replace("Mob Kills: ", ""))}',
            f'<span style="color:#98A7BA;">Level:</span> {html.escape(cls.format_player_level(getattr(snapshot, "player_level", None)).replace("Level: ", ""))}',
            f'<span style="color:#98A7BA;">Items:</span> {cls.format_count(item_total)}',
        ]
        return "<br>".join(rows)

    @classmethod
    def format_compare_run_selected_stats(cls, snapshot, stat_labels: tuple[str, ...] | None = None) -> str:
        rows: list[str] = []
        for label in stat_labels or COMPARE_RUN_STAT_LABELS:
            stat = getattr(snapshot, "stats", {}).get(label)
            display = stat.display_value if stat is not None else "--"
            rows.append(f'<span style="color:#98A7BA;">{html.escape(label)}:</span> {html.escape(display)}')
        return "<br>".join(rows) if rows else "--"

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
        rows = [cls.format_compare_runs_overview_diff(vod_a, snapshot_a, vod_b, snapshot_b)]
        stat_text = cls.format_compare_runs_stats_diff(snapshot_a, snapshot_b, stat_labels=stat_labels)
        if stat_text and stat_text != "--":
            rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Selected Stats</span>')
            rows.append(stat_text)
        if include_items:
            rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Items</span>')
            rows.append(cls.format_compare_runs_items_diff(snapshot_a, snapshot_b, details_expanded=item_details_expanded))
        if include_weapons:
            rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Weapons</span>')
            rows.append(cls.format_compare_runs_weapons_diff(snapshot_a, snapshot_b))
        if include_tomes:
            rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Tomes</span>')
            rows.append(cls.format_compare_runs_tomes_diff(snapshot_a, snapshot_b))
        if include_chaos:
            rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Chaos</span>')
            rows.append(cls.format_compare_runs_chaos_diff(snapshot_a, snapshot_b))
        return "<br>".join(rows)

    @classmethod
    def format_compare_runs_overview_diff(cls, vod_a, snapshot_a, vod_b, snapshot_b) -> str:
        time_a = cls._snapshot_compare_time(snapshot_a)
        time_b = cls._snapshot_compare_time(snapshot_b)
        rows = [
            f'<span style="color:#98A7BA;">A:</span> {html.escape(vod_a.metadata.name)}',
            f'<span style="color:#98A7BA;">B:</span> {html.escape(vod_b.metadata.name)}',
            '<span style="color:#98A7BA;">Mode:</span> Run B compared to Run A',
        ]
        if time_a is not None and time_b is not None:
            rows.append(
                f'<span style="color:#98A7BA;">Time offset:</span> {cls._format_signed_seconds(time_b - time_a)}'
            )

        kill_delta = cls._raw_snapshot_int_delta(snapshot_a, snapshot_b, "mob_kills")
        if kill_delta is not None:
            rows.append(f'<span style="color:#98A7BA;">Kill Difference:</span> {cls._format_signed_count(kill_delta)}')

        level_delta = cls._raw_snapshot_int_delta(snapshot_a, snapshot_b, "player_level")
        if level_delta is not None:
            rows.append(f'<span style="color:#98A7BA;">Level Difference:</span> {cls._format_signed_count(level_delta)}')

        item_delta = cls._snapshot_item_total(snapshot_b) - cls._snapshot_item_total(snapshot_a)
        rows.append(f'<span style="color:#98A7BA;">Item Difference:</span> {cls._format_signed_count(item_delta)}')
        return "<br>".join(rows)

    @classmethod
    def format_compare_runs_stats_diff(cls, snapshot_a, snapshot_b, *, stat_labels: tuple[str, ...] | None = None) -> str:
        stat_rows = cls._format_compare_run_stat_deltas(snapshot_a, snapshot_b, stat_labels=stat_labels)
        return "<br>".join(stat_rows) if stat_rows else "--"

    @classmethod
    def format_compare_runs_items_diff(cls, snapshot_a, snapshot_b, *, details_expanded: bool = False) -> str:
        item_rows = cls._format_compare_run_item_deltas(
            snapshot_a,
            snapshot_b,
            details_expanded=details_expanded,
        )
        return "<br>".join(item_rows) if item_rows else "--"

    @classmethod
    def format_compare_runs_stage_summary_diff(cls, vod_a, index_a, vod_b, index_b) -> str:
        rows_a = cls._build_compare_run_stage_summary_rows(vod_a, index_a)
        rows_b = cls._build_compare_run_stage_summary_rows(vod_b, index_b)
        blocks: list[str] = []
        for row_a, row_b in zip(rows_a, rows_b):
            label = html.escape(str(row_a.get("label", row_b.get("label", "--"))))
            blocks.append(
                "<div style='margin-bottom:10px;'>"
                f"<span style='color:#E5E7EB; font-weight:700;'>{label}</span><br>"
                f"<span style='color:#98A7BA;'>Time:</span> {cls._format_compare_stage_summary_metric(row_a.get('time', '--'), row_b.get('time', '--'), metric='time')}<br>"
                f"<span style='color:#98A7BA;'>Kills:</span> {cls._format_compare_stage_summary_metric(row_a.get('kills', '--'), row_b.get('kills', '--'), metric='count')}<br>"
                f"<span style='color:#98A7BA;'>Items:</span> {cls._format_compare_stage_summary_items(row_a.get('items', '--'), row_b.get('items', '--'))}"
                "</div>"
            )
        return "".join(blocks) if blocks else "--"

    @classmethod
    def format_compare_runs_weapons_diff(cls, snapshot_a, snapshot_b) -> str:
        weapon_rows = cls._format_compare_run_weapon_deltas(snapshot_a, snapshot_b)
        return "<br>".join(weapon_rows) if weapon_rows else "--"

    @classmethod
    def format_compare_runs_tomes_diff(cls, snapshot_a, snapshot_b) -> str:
        tome_rows = cls._format_compare_run_tome_deltas(snapshot_a, snapshot_b)
        return "<br>".join(tome_rows) if tome_rows else "--"

    @classmethod
    def format_compare_runs_chaos_diff(cls, snapshot_a, snapshot_b) -> str:
        chaos_a = getattr(snapshot_a, "chaos_tome", None)
        chaos_b = getattr(snapshot_b, "chaos_tome", None)
        if chaos_a is None and chaos_b is None:
            return '<span style="color:#98A7BA;">No Chaos Tome data</span>'

        overview_rows = [
            cls._format_compare_metric_row(
                "Level",
                cls._metric_value(getattr(chaos_a, "level", None), getattr(chaos_a, "level", None)),
                cls._metric_value(getattr(chaos_b, "level", None), getattr(chaos_b, "level", None)),
            ),
            (
                "Tracked Rolls",
                cls._format_chaos_roll_count(chaos_a),
                cls._format_chaos_roll_count(chaos_b),
                cls._format_signed_count(cls._chaos_roll_count(chaos_b) - cls._chaos_roll_count(chaos_a)),
            ),
            (
                "Stats",
                str(cls._chaos_stat_count(chaos_a)),
                str(cls._chaos_stat_count(chaos_b)),
                cls._format_signed_count(cls._chaos_stat_count(chaos_b) - cls._chaos_stat_count(chaos_a)),
            ),
        ]
        blocks = [cls._format_compare_metric_table(("Metric", "A", "B", "Diff"), overview_rows)]

        stat_rows = cls._format_compare_run_chaos_stat_rows(chaos_a, chaos_b)
        if stat_rows:
            blocks.append(cls._format_compare_metric_table(("Stat", "A", "B", "Diff"), stat_rows))
        return "<br>".join(blocks)

    @classmethod
    def _format_compare_run_stat_deltas(cls, snapshot_a, snapshot_b, *, stat_labels: tuple[str, ...] | None = None) -> list[str]:
        rows: list[str] = []
        for label in stat_labels or COMPARE_RUN_STAT_LABELS:
            stat_a = getattr(snapshot_a, "stats", {}).get(label)
            stat_b = getattr(snapshot_b, "stats", {}).get(label)
            if stat_a is None and stat_b is None:
                continue
            display_a = stat_a.display_value if stat_a is not None else "--"
            display_b = stat_b.display_value if stat_b is not None else "--"
            delta_text = ""
            if stat_a is not None and stat_b is not None and stat_a.value is not None and stat_b.value is not None:
                delta_text = f" ({cls._format_compare_run_stat_delta(stat_a, stat_b)})"
            rows.append(
                f'<span style="color:#98A7BA;">{html.escape(label)}:</span> '
                f'{html.escape(display_a)} -> {html.escape(display_b)}{html.escape(delta_text)}'
            )
        return rows

    @classmethod
    def _snapshot_item_total(cls, snapshot) -> int:
        return sum(cls._item_counts(getattr(snapshot, "items", ())).values())

    @classmethod
    def _build_compare_run_stage_summary_rows(cls, vod, index) -> list[dict[str, str]]:
        if vod is None or index is None:
            return cls.build_stage_summary(())
        snapshots = getattr(vod, "snapshots", ()) or ()
        if not snapshots:
            return cls.build_stage_summary(())
        bounded_index = min(max(int(index), 0), len(snapshots) - 1)
        return cls.build_stage_summary(snapshots[: bounded_index + 1])

    @classmethod
    def _format_compare_stage_summary_metric(cls, value_a: str, value_b: str, *, metric: str) -> str:
        escaped_a = html.escape(str(value_a))
        escaped_b = html.escape(str(value_b))
        delta_text = ""
        if metric == "time":
            seconds_a = cls._parse_stage_summary_time(value_a)
            seconds_b = cls._parse_stage_summary_time(value_b)
            if seconds_a is not None and seconds_b is not None:
                delta_text = f" ({cls._format_signed_seconds(seconds_b - seconds_a)})"
        else:
            count_a = cls._parse_stage_summary_count(value_a)
            count_b = cls._parse_stage_summary_count(value_b)
            if count_a is not None and count_b is not None:
                delta_text = f" ({cls._format_signed_count(count_b - count_a)})"
        return f"{escaped_a} <span style='color:#98A7BA;'>&rarr;</span> {escaped_b}{html.escape(delta_text)}"

    @staticmethod
    def _format_compare_stage_summary_items(value_a: str, value_b: str) -> str:
        return (
            f"{value_a} <span style='color:#98A7BA;'>&rarr;</span> {value_b}"
            if value_a != "--" or value_b != "--"
            else "--"
        )

    @staticmethod
    def _parse_stage_summary_time(value: str | None) -> int | None:
        if value in (None, "--"):
            return None
        parts = str(value).split(":")
        if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
            return None
        total = 0
        for part in parts:
            total = total * 60 + int(part)
        return total

    @staticmethod
    def _parse_stage_summary_count(value: str | None) -> int | None:
        if value in (None, "--"):
            return None
        try:
            return int(str(value).replace(",", ""))
        except ValueError:
            return None

    @classmethod
    def _format_compare_run_item_deltas(cls, snapshot_a, snapshot_b, *, details_expanded: bool = False) -> list[str]:
        counts_a = cls._item_counts(getattr(snapshot_a, "items", ()))
        counts_b = cls._item_counts(getattr(snapshot_b, "items", ()))
        more_in_b: dict[str, int] = {}
        more_in_a: dict[str, int] = {}
        for name in set(counts_a) | set(counts_b):
            delta = counts_b.get(name, 0) - counts_a.get(name, 0)
            if delta > 0:
                more_in_b[name] = delta
            elif delta < 0:
                more_in_a[name] = abs(delta)

        rarity_rows = cls._format_item_delta_rarity_totals(more_in_b, more_in_a)
        if not more_in_b and not more_in_a:
            return [
                f'<span style="color:#98A7BA;">Rarity:</span> {rarity_rows}',
                '<span style="color:#98A7BA;">No item count differences</span>',
            ]
        rows = [f'<span style="font-size:14px;"><span style="color:#98A7BA; font-weight:700;">Rarity Delta:</span> {rarity_rows}</span>']
        if details_expanded:
            rows.append(cls._format_item_delta_table(counts_a, counts_b))
        else:
            if more_in_b:
                rows.append(f'<span style="color:#98A7BA;">B has more:</span> {cls._format_item_delta_inline(more_in_b, "+", max_items=3)}')
            if more_in_a:
                rows.append(f'<span style="color:#98A7BA;">A has more:</span> {cls._format_item_delta_inline(more_in_a, "-", max_items=3)}')
        return rows

    @classmethod
    def _format_item_delta_rarity_totals(cls, more_in_b: dict[str, int], more_in_a: dict[str, int]) -> str:
        parts: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
            total = 0
            for name, count in more_in_b.items():
                if cls._item_rarity_name(name) == rarity:
                    total += int(count)
            for name, count in more_in_a.items():
                if cls._item_rarity_name(name) == rarity:
                    total -= int(count)
            if total == 0:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            parts.append(
                f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{cls._format_signed_count(total)}</span>'
            )
        return " ".join(parts) if parts else '<span style="color:#98A7BA;">--</span>'

    @classmethod
    def _format_item_delta_inline(cls, deltas: dict[str, int], sign: str, *, max_items: int = 6) -> str:
        sorted_items = cls._sort_item_delta_pairs(deltas.items())
        visible_items = sorted_items[:max_items]
        parts = [
            f'{cls._format_item_delta_name(name)} {sign}{cls.format_count(count)}'
            for name, count in visible_items
        ]
        hidden_count = len(sorted_items) - len(visible_items)
        if hidden_count > 0:
            parts.append(f'<span style="color:#98A7BA;">+{hidden_count} more</span>')
        return " | ".join(parts) if parts else "--"

    @classmethod
    def _format_item_delta_table(cls, counts_a: dict[str, int], counts_b: dict[str, int]) -> str:
        header_style = "color:#98A7BA; font-weight:700; padding:4px 8px; border-bottom:1px solid #26364A;"
        cell_style = "padding:4px 8px; border-bottom:1px solid #1E2A3A;"
        rows: list[str] = [
            (
                '<table cellspacing="0" cellpadding="0" style="width:100%; border-collapse:collapse; font-size:14px;">'
                "<tr>"
                f'<td style="{header_style}">Name</td>'
                f'<td align="right" style="{header_style}">A</td>'
                f'<td align="right" style="{header_style}">B</td>'
                f'<td align="right" style="{header_style}">Diff</td>'
                "</tr>"
            )
        ]
        for row_index, (name, count_a, count_b, delta) in enumerate(cls._item_delta_table_rows(counts_a, counts_b)):
            background = "#0F1722" if row_index % 2 == 0 else "#121C28"
            rows.append(
                f'<tr style="background-color:{background};">'
                f'<td style="{cell_style}">{cls._format_item_delta_name(name)}</td>'
                f'<td align="right" style="{cell_style}; color:#E5E7EB;">{cls.format_count(count_a)}</td>'
                f'<td align="right" style="{cell_style}; color:#E5E7EB;">{cls.format_count(count_b)}</td>'
                f'<td align="right" style="{cell_style}">{cls._format_signed_delta_rich_text(delta)}</td>'
                "</tr>"
            )
        rows.append("</table>")
        return "".join(rows)

    @classmethod
    def _item_delta_table_rows(cls, counts_a: dict[str, int], counts_b: dict[str, int]) -> tuple[tuple[str, int, int, int], ...]:
        rows: list[tuple[str, int, int, int]] = []
        for name in set(counts_a) | set(counts_b):
            count_a = counts_a.get(name, 0)
            count_b = counts_b.get(name, 0)
            delta = count_b - count_a
            if delta == 0:
                continue
            rows.append((name, count_a, count_b, delta))
        return tuple(
            sorted(
                rows,
                key=lambda row: (
                    -cls._item_rarity_rank(row[0]),
                    -abs(row[3]),
                    cls._normalize_item_name_for_display(row[0]).casefold(),
                ),
            )
        )

    @classmethod
    def _format_signed_delta_rich_text(cls, value: int) -> str:
        color = "#22C55E" if value > 0 else "#FB7185" if value < 0 else "#98A7BA"
        return f'<span style="color:{color}; font-weight:700;">{cls._format_signed_count(value)}</span>'

    @classmethod
    def _format_item_delta_by_rarity(cls, deltas: dict[str, int], sign: str) -> str:
        grouped: dict[str, list[tuple[str, int]]] = {
            "LEGENDARY": [],
            "RARE": [],
            "UNCOMMON": [],
            "COMMON": [],
            "UNKNOWN": [],
        }
        for name, count in cls._sort_item_delta_pairs(deltas.items()):
            rarity = cls._item_rarity_name(name) or "UNKNOWN"
            if rarity not in grouped:
                rarity = "UNKNOWN"
            grouped[rarity].append((name, count))

        rows: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON", "UNKNOWN"):
            items = grouped[rarity]
            if not items:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            item_text = " | ".join(
                f'{cls._format_item_delta_name(name)} {sign}{cls.format_count(count)}'
                for name, count in items
            )
            rows.append(
                f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{item_text}</span>'
            )
        return "<br>".join(rows) if rows else "--"

    @classmethod
    def _format_item_delta_name(cls, item_name: str) -> str:
        display_name = cls._normalize_item_name_for_display(item_name)
        rarity = cls._item_rarity_name(display_name)
        color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
        color = item_display_color(display_name, color)
        return f'<span style="color:{color}; font-weight:700;">{html.escape(display_name)}</span>'

    @classmethod
    def _item_rarity_name(cls, item_name: str) -> str | None:
        display_name = cls._normalize_item_name_for_display(item_name)
        rarity_name = cls._normalize_item_name_for_rarity(display_name)
        return ITEM_RARITY_BY_NAME.get(rarity_name)

    @classmethod
    def _format_compare_run_weapon_deltas(cls, snapshot_a, snapshot_b) -> list[str]:
        weapons_a = cls._index_named_snapshots(getattr(snapshot_a, "weapons", ()))
        weapons_b = cls._index_named_snapshots(getattr(snapshot_b, "weapons", ()))
        rows: list[str] = []
        for name in sorted(set(weapons_a) | set(weapons_b), key=str.casefold):
            rows.append(cls._format_weapon_compare_card(name, weapons_a.get(name), weapons_b.get(name)))
        return rows or ['<span style="color:#98A7BA;">No weapon data</span>']

    @classmethod
    def _format_compare_run_tome_deltas(cls, snapshot_a, snapshot_b) -> list[str]:
        tomes_a = cls._index_named_snapshots(getattr(snapshot_a, "tomes", ()))
        tomes_b = cls._index_named_snapshots(getattr(snapshot_b, "tomes", ()))
        rows: list[str] = []
        for name in sorted(set(tomes_a) | set(tomes_b), key=str.casefold):
            card = cls._format_tome_compare_card(name, tomes_a.get(name), tomes_b.get(name))
            if card:
                rows.append(card)
        return rows or ['<span style="color:#98A7BA;">No tome data</span>']

    @classmethod
    def _format_compare_run_chaos_stat_rows(cls, chaos_a, chaos_b) -> list[tuple[str, str, str, str]]:
        stats_a = cls._index_chaos_stats(chaos_a)
        stats_b = cls._index_chaos_stats(chaos_b)
        rows: list[tuple[str, str, str, str]] = []
        for stat_id in sorted(
            set(stats_a) | set(stats_b),
            key=lambda value: (
                CHAOS_TOME_GAME_STAT_ORDER.get(int(value), 999),
                cls._chaos_compare_stat_label(stats_a.get(value), stats_b.get(value)).casefold(),
            ),
        ):
            stat_a = stats_a.get(stat_id)
            stat_b = stats_b.get(stat_id)
            label = cls._chaos_compare_stat_label(stat_a, stat_b)
            rows.append(
                cls._format_compare_metric_row(
                    label,
                    cls._chaos_compare_metric_value(stat_a),
                    cls._chaos_compare_metric_value(stat_b),
                )
            )
        return rows

    @classmethod
    def _chaos_compare_metric_value(cls, stat):
        if stat is None:
            return None
        return cls._metric_value(
            getattr(stat, "value", None),
            getattr(stat, "display_delta", None),
        )

    @staticmethod
    def _index_chaos_stats(chaos_tome) -> dict[int, object]:
        if chaos_tome is None:
            return {}
        stats: dict[int, object] = {}
        for stat in getattr(chaos_tome, "stats", ()) or ():
            try:
                stat_id = int(getattr(stat, "stat_id"))
            except (TypeError, ValueError):
                continue
            stats[stat_id] = stat
        return stats

    @staticmethod
    def _chaos_compare_stat_label(stat_a, stat_b) -> str:
        stat = stat_a if stat_a is not None else stat_b
        if stat is None:
            return "Unknown"
        return str(getattr(stat, "label", f"Stat {getattr(stat, 'stat_id', '?')}"))

    @staticmethod
    def _chaos_roll_count(chaos_tome) -> int:
        if chaos_tome is None:
            return 0
        return sum(int(getattr(stat, "rolls", 0) or 0) for stat in getattr(chaos_tome, "stats", ()) or ())

    @classmethod
    def _format_chaos_roll_count(cls, chaos_tome) -> str:
        if chaos_tome is None:
            return "--"
        return cls.format_count(cls._chaos_roll_count(chaos_tome))

    @staticmethod
    def _chaos_stat_count(chaos_tome) -> int:
        if chaos_tome is None:
            return 0
        return len(tuple(getattr(chaos_tome, "stats", ()) or ()))

    @staticmethod
    def _index_named_snapshots(snapshots) -> dict[str, object]:
        indexed: dict[str, object] = {}
        for snapshot in snapshots or ():
            name = getattr(snapshot, "name", "")
            if name:
                indexed[str(name)] = snapshot
        return indexed

    @classmethod
    def _format_named_level_deltas(cls, values_a: dict[str, object], values_b: dict[str, object], *, level_attr: str, value_formatter) -> list[str]:
        rows: list[str] = []
        for name in sorted(set(values_a) | set(values_b), key=str.casefold):
            value_a = values_a.get(name)
            value_b = values_b.get(name)
            if value_a is None:
                rows.append(f'<span style="color:#98A7BA;">{html.escape(name)}:</span> -- -> {value_formatter(value_b)}')
                continue
            if value_b is None:
                rows.append(f'<span style="color:#98A7BA;">{html.escape(name)}:</span> {value_formatter(value_a)} -> --')
                continue
            level_delta = int(getattr(value_b, level_attr, 0)) - int(getattr(value_a, level_attr, 0))
            rows.append(
                f'<span style="color:#98A7BA;">{html.escape(name)}:</span> '
                f'{value_formatter(value_a)} -> {value_formatter(value_b)} ({cls._format_signed_count(level_delta)} lv)'
            )
        return rows or ['<span style="color:#98A7BA;">No data</span>']

    @classmethod
    def _format_weapon_compare_block(cls, name: str, weapon_a, weapon_b) -> str:
        title = cls._format_compare_entity_title(name, weapon_a, weapon_b)
        stat_ids = set()
        for weapon in (weapon_a, weapon_b):
            if weapon is None:
                continue
            stat_ids.update(getattr(weapon, "upgrade_stat_ids", ()))
            stat_ids.update(getattr(weapon, "upgraded_stats", {}).keys())
        stat_rows = []
        for stat_id in sorted(stat_ids, key=lambda value: cls._weapon_stat_label(weapon_a, weapon_b, value).casefold()):
            stat_a = getattr(weapon_a, "upgraded_stats", {}).get(stat_id) if weapon_a is not None else None
            stat_b = getattr(weapon_b, "upgraded_stats", {}).get(stat_id) if weapon_b is not None else None
            label = cls._weapon_stat_label(weapon_a, weapon_b, stat_id)
            stat_rows.append(cls._format_compare_metric_row(label, stat_a, stat_b))
        table = cls._format_compare_metric_table(("Upgrade", "A", "B", "Diff"), stat_rows)
        return f'{title}<br>{table}'

    @classmethod
    def _weapon_compare_table_rows(cls, name: str, weapon_a, weapon_b) -> list[tuple[str, str, str, str, str]]:
        group_label = cls._format_compare_entity_label(name, weapon_a, weapon_b)
        stat_ids = set()
        for weapon in (weapon_a, weapon_b):
            if weapon is None:
                continue
            stat_ids.update(getattr(weapon, "upgrade_stat_ids", ()))
            stat_ids.update(getattr(weapon, "upgraded_stats", {}).keys())
        rows: list[tuple[str, str, str, str, str]] = []
        for stat_id in sorted(stat_ids, key=lambda value: cls._weapon_stat_label(weapon_a, weapon_b, value).casefold()):
            stat_a = getattr(weapon_a, "upgraded_stats", {}).get(stat_id) if weapon_a is not None else None
            stat_b = getattr(weapon_b, "upgraded_stats", {}).get(stat_id) if weapon_b is not None else None
            label, display_a, display_b, delta = cls._format_compare_metric_row(
                cls._weapon_stat_label(weapon_a, weapon_b, stat_id),
                stat_a,
                stat_b,
            )
            rows.append((group_label, label, display_a, display_b, delta))
        if not rows:
            rows.append((group_label, "Level", cls._level_display(weapon_a), cls._level_display(weapon_b), cls._level_delta(weapon_a, weapon_b)))
        return rows

    @classmethod
    def _format_weapon_compare_card(cls, name: str, weapon_a, weapon_b) -> str:
        metric_rows: list[tuple[str, str, str, str]] = [
            ("Level", cls._level_display(weapon_a), cls._level_display(weapon_b), cls._level_delta(weapon_a, weapon_b))
        ]
        stat_ids = set()
        for weapon in (weapon_a, weapon_b):
            if weapon is None:
                continue
            stat_ids.update(getattr(weapon, "upgrade_stat_ids", ()))
            stat_ids.update(getattr(weapon, "upgraded_stats", {}).keys())
        for stat_id in sorted(stat_ids, key=lambda value: cls._weapon_stat_label(weapon_a, weapon_b, value).casefold()):
            stat_a = getattr(weapon_a, "upgraded_stats", {}).get(stat_id) if weapon_a is not None else None
            stat_b = getattr(weapon_b, "upgraded_stats", {}).get(stat_id) if weapon_b is not None else None
            label, display_a, display_b, delta = cls._format_compare_metric_row(
                cls._weapon_stat_label(weapon_a, weapon_b, stat_id),
                stat_a,
                stat_b,
            )
            metric_rows.append((label, display_a, display_b, delta))
        return cls._format_compare_mini_card(name, weapon_a, weapon_b, metric_rows)

    @classmethod
    def _format_tome_compare_block(cls, name: str, tome_a, tome_b) -> str:
        title = cls._format_compare_entity_title(name, tome_a, tome_b)
        rows = [
            cls._format_compare_metric_row(
                "Level",
                cls._metric_value(getattr(tome_a, "level", None), getattr(tome_a, "level", None)),
                cls._metric_value(getattr(tome_b, "level", None), getattr(tome_b, "level", None)),
            )
        ]
        if name.casefold() != "chaos":
            label = cls._tome_value_label(tome_a, tome_b)
            rows.append(
                cls._format_compare_metric_row(
                    label,
                    cls._metric_value(getattr(tome_a, "value", None), getattr(tome_a, "display_value", None)),
                    cls._metric_value(getattr(tome_b, "value", None), getattr(tome_b, "display_value", None)),
                )
            )
        table = cls._format_compare_metric_table(("Metric", "A", "B", "Diff"), rows)
        return f'{title}<br>{table}'

    @classmethod
    def _tome_compare_table_rows(cls, name: str, tome_a, tome_b) -> list[tuple[str, str, str, str, str]]:
        group_label = cls._format_compare_entity_label(name, tome_a, tome_b)
        rows = [
            (
                group_label,
                *cls._format_compare_metric_row(
                    "Level",
                    cls._metric_value(getattr(tome_a, "level", None), getattr(tome_a, "level", None)),
                    cls._metric_value(getattr(tome_b, "level", None), getattr(tome_b, "level", None)),
                ),
            )
        ]
        if name.casefold() != "chaos":
            rows.append(
                (
                    group_label,
                    *cls._format_compare_metric_row(
                        cls._tome_value_label(tome_a, tome_b),
                        cls._metric_value(getattr(tome_a, "value", None), getattr(tome_a, "display_value", None)),
                        cls._metric_value(getattr(tome_b, "value", None), getattr(tome_b, "display_value", None)),
                    ),
                )
            )
        return rows

    @classmethod
    def _format_tome_compare_card(cls, name: str, tome_a, tome_b) -> str:
        metric_rows = []
        if name.casefold() == "chaos":
            metric_rows.append(("Level", cls._level_display(tome_a), cls._level_display(tome_b), cls._level_delta(tome_a, tome_b)))
        else:
            metric_rows.append(
                (
                    cls._tome_value_label(tome_a, tome_b),
                    *cls._format_compare_metric_values(
                        cls._metric_value(getattr(tome_a, "value", None), getattr(tome_a, "display_value", None)),
                        cls._metric_value(getattr(tome_b, "value", None), getattr(tome_b, "display_value", None)),
                    ),
                )
            )
        return cls._format_compare_mini_card(name, tome_a, tome_b, metric_rows)

    @classmethod
    def _format_compare_metric_transition(cls, value_a, value_b) -> tuple[str, str]:
        _label, display_a, display_b, delta = cls._format_compare_metric_row("", value_a, value_b)
        return f"{display_a} -> {display_b}", delta

    @classmethod
    def _format_compare_metric_values(cls, value_a, value_b) -> tuple[str, str, str]:
        _label, display_a, display_b, delta = cls._format_compare_metric_row("", value_a, value_b)
        return display_a, display_b, delta

    @classmethod
    def _format_compare_mini_card(cls, name: str, value_a, value_b, metric_rows: list[tuple[str, str, str, str]]) -> str:
        header = cls._format_compare_entity_title(name, value_a, value_b)
        if not metric_rows:
            return (
                '<table width="100%" cellspacing="0" cellpadding="0" '
                'style="background-color:#0F1722; border:1px solid #1E2A3A; border-collapse:collapse; margin-bottom:8px; font-size:14px;">'
                '<tr>'
                f'<td colspan="4" style="padding:8px 10px;">{header}</td>'
                '</tr>'
                '</table>'
            )
        rows = [
            '<table width="100%" cellspacing="0" cellpadding="0" '
            'style="background-color:#0F1722; border:1px solid #1E2A3A; border-collapse:collapse; margin-bottom:8px; font-size:14px;">',
            "<tr>",
            f'<td width="52%" style="color:#E5E7EB; font-weight:700; padding:7px 10px; border-bottom:1px solid #26364A;">{header}</td>',
            '<td width="16%" align="right" style="color:#98A7BA; font-weight:700; padding:7px 10px; border-left:1px solid #26364A; border-bottom:1px solid #26364A;">A</td>',
            '<td width="16%" align="right" style="color:#98A7BA; font-weight:700; padding:7px 10px; border-left:1px solid #26364A; border-bottom:1px solid #26364A;">B</td>',
            '<td width="16%" align="right" style="color:#98A7BA; font-weight:700; padding:7px 10px; border-left:1px solid #26364A; border-bottom:1px solid #26364A;">Diff</td>',
            "</tr>",
        ]
        metric_cell_style = "padding:5px 10px; border-bottom:1px solid #1E2A3A;"
        value_cell_style = "padding:5px 10px; border-left:1px solid #1E2A3A; border-bottom:1px solid #1E2A3A;"
        diff_cell_style = "padding:5px 10px; border-left:1px solid #1E2A3A; border-bottom:1px solid #1E2A3A;"
        for label, display_a, display_b, delta in metric_rows:
            rows.append(
                "<tr>"
                f'<td style="{metric_cell_style}; color:#98A7BA;">{html.escape(label)}</td>'
                f'<td align="right" style="{value_cell_style}; color:#E5E7EB;">{html.escape(display_a)}</td>'
                f'<td align="right" style="{value_cell_style}; color:#E5E7EB;">{html.escape(display_b)}</td>'
                f'<td align="right" style="{diff_cell_style}">{cls._format_metric_delta_rich_text(delta)}</td>'
                "</tr>"
            )
        rows.append("</table>")
        return "".join(rows)

    @classmethod
    def _format_compare_entity_title(cls, name: str, value_a, value_b) -> str:
        level_a = getattr(value_a, "level", None)
        level_b = getattr(value_b, "level", None)
        if level_a is None and level_b is None:
            level_text = "Lv. --"
        elif level_a is None:
            level_text = f"Lv. -- -> {int(level_b)}"
        elif level_b is None:
            level_text = f"Lv. {int(level_a)} -> --"
        else:
            level_text = f"Lv. {int(level_a)} -> {int(level_b)}"
        return f'<span style="color:#E5E7EB; font-weight:700;">{html.escape(name)}</span> <span style="color:#98A7BA;">({level_text})</span>'

    @classmethod
    def _format_compare_entity_label(cls, name: str, value_a, value_b) -> str:
        level_a = getattr(value_a, "level", None)
        level_b = getattr(value_b, "level", None)
        if level_a is None and level_b is None:
            level_text = "Lv. --"
        elif level_a is None:
            level_text = f"Lv. -- -> {int(level_b)}"
        elif level_b is None:
            level_text = f"Lv. {int(level_a)} -> --"
        else:
            level_text = f"Lv. {int(level_a)} -> {int(level_b)}"
        return f'<span style="font-weight:700;">{html.escape(name)}</span><br><span style="color:#98A7BA;">{level_text}</span>'

    @staticmethod
    def _weapon_stat_label(weapon_a, weapon_b, stat_id: int) -> str:
        for weapon in (weapon_a, weapon_b):
            if weapon is None:
                continue
            stat = getattr(weapon, "upgraded_stats", {}).get(stat_id)
            if stat is not None:
                return str(stat.label)
        return str(stat_id)

    @staticmethod
    def _tome_value_label(tome_a, tome_b) -> str:
        for tome in (tome_a, tome_b):
            label = getattr(tome, "stat_label", None)
            if label:
                return str(label)
        return "Value"

    @staticmethod
    def _metric_value(value, display_value):
        if value is None and display_value is None:
            return None
        return type("CompareMetricValue", (), {"value": value, "display_value": str(display_value)})()

    @classmethod
    def _format_compare_metric_row(cls, label: str, value_a, value_b) -> tuple[str, str, str, str]:
        display_a = getattr(value_a, "display_value", "--") if value_a is not None else "--"
        display_b = getattr(value_b, "display_value", "--") if value_b is not None else "--"
        delta = "--"
        if value_a is not None and value_b is not None:
            raw_a = getattr(value_a, "value", None)
            raw_b = getattr(value_b, "value", None)
            if raw_a is not None and raw_b is not None:
                delta = cls._format_compare_run_stat_delta(value_a, value_b)
            else:
                delta = cls._format_display_value_delta(display_a, display_b) or "--"
        return (label, str(display_a), str(display_b), delta)

    @classmethod
    def _format_compare_metric_table(cls, headers: tuple[str, str, str, str], rows: list[tuple[str, str, str, str]]) -> str:
        header_style = "color:#98A7BA; font-weight:700; padding:3px 7px; border-bottom:1px solid #26364A;"
        cell_style = "padding:3px 7px; border-bottom:1px solid #1E2A3A;"
        html_rows = [
            (
                '<table cellspacing="0" cellpadding="0" style="width:100%; border-collapse:collapse; margin-bottom:6px;">'
                "<tr>"
                f'<td style="{header_style}">{html.escape(headers[0])}</td>'
                f'<td align="right" style="{header_style}">{html.escape(headers[1])}</td>'
                f'<td align="right" style="{header_style}">{html.escape(headers[2])}</td>'
                f'<td align="right" style="{header_style}">{html.escape(headers[3])}</td>'
                "</tr>"
            )
        ]
        for row_index, (label, display_a, display_b, delta) in enumerate(rows):
            background = "#0F1722" if row_index % 2 == 0 else "#121C28"
            html_rows.append(
                f'<tr style="background-color:{background};">'
                f'<td style="{cell_style}; color:#E5E7EB;">{html.escape(label)}</td>'
                f'<td align="right" style="{cell_style}; color:#E5E7EB;">{html.escape(display_a)}</td>'
                f'<td align="right" style="{cell_style}; color:#E5E7EB;">{html.escape(display_b)}</td>'
                f'<td align="right" style="{cell_style}">{cls._format_metric_delta_rich_text(delta)}</td>'
                "</tr>"
            )
        html_rows.append("</table>")
        return "".join(html_rows)

    @classmethod
    def _format_grouped_compare_table(cls, headers: tuple[str, str, str, str, str], rows: list[tuple[str, str, str, str, str]]) -> str:
        header_style = "color:#98A7BA; font-weight:700; padding:3px 7px; border-bottom:1px solid #26364A;"
        cell_style = "padding:3px 7px; border-bottom:1px solid #1E2A3A;"
        html_rows = [
            (
                '<table cellspacing="0" cellpadding="0" style="width:100%; border-collapse:collapse; margin-bottom:6px;">'
                "<tr>"
                f'<td style="{header_style}">{html.escape(headers[0])}</td>'
                f'<td style="{header_style}">{html.escape(headers[1])}</td>'
                f'<td align="right" style="{header_style}">{html.escape(headers[2])}</td>'
                f'<td align="right" style="{header_style}">{html.escape(headers[3])}</td>'
                f'<td align="right" style="{header_style}">{html.escape(headers[4])}</td>'
                "</tr>"
            )
        ]
        last_group = None
        visible_group = ""
        for row_index, (group, metric, display_a, display_b, delta) in enumerate(rows):
            background = "#0F1722" if row_index % 2 == 0 else "#121C28"
            if group != last_group:
                visible_group = group
                last_group = group
            else:
                visible_group = ""
            html_rows.append(
                f'<tr style="background-color:{background};">'
                f'<td style="{cell_style}; color:#E5E7EB;">{visible_group}</td>'
                f'<td style="{cell_style}; color:#E5E7EB;">{html.escape(metric)}</td>'
                f'<td align="right" style="{cell_style}; color:#E5E7EB;">{html.escape(display_a)}</td>'
                f'<td align="right" style="{cell_style}; color:#E5E7EB;">{html.escape(display_b)}</td>'
                f'<td align="right" style="{cell_style}">{cls._format_metric_delta_rich_text(delta)}</td>'
                "</tr>"
            )
        html_rows.append("</table>")
        return "".join(html_rows)

    @staticmethod
    def _format_metric_delta_rich_text(delta: str) -> str:
        if delta == "--":
            return '<span style="color:#98A7BA;">--</span>'
        color = "#22C55E" if delta.startswith("+") else "#FB7185" if delta.startswith("-") else "#98A7BA"
        return f'<span style="color:{color}; font-weight:700;">{html.escape(delta)}</span>'

    @classmethod
    def _format_display_value_delta(cls, display_a: str, display_b: str) -> str | None:
        text_a = str(display_a).strip()
        text_b = str(display_b).strip()
        suffix = ""
        if text_a.endswith("%") and text_b.endswith("%"):
            suffix = "%"
            text_a = text_a[:-1]
            text_b = text_b[:-1]
        elif text_a.endswith("x") and text_b.endswith("x"):
            suffix = "x"
            text_a = text_a[:-1]
            text_b = text_b[:-1]
        try:
            value_a = float(text_a.replace(",", ""))
            value_b = float(text_b.replace(",", ""))
        except ValueError:
            return None
        delta = value_b - value_a
        if abs(delta) < 0.00001:
            formatted = "0"
        elif delta.is_integer():
            formatted = f"{int(delta):+d}"
        else:
            formatted = f"{delta:+.2f}"
        return f"{formatted}{suffix}"

    @staticmethod
    def _level_display(value) -> str:
        level = getattr(value, "level", None)
        return "--" if level is None else str(int(level))

    @classmethod
    def _level_delta(cls, value_a, value_b) -> str:
        level_a = getattr(value_a, "level", None)
        level_b = getattr(value_b, "level", None)
        if level_a is None or level_b is None:
            return "--"
        return cls._format_signed_count(int(level_b) - int(level_a))

    @staticmethod
    def _format_weapon_summary(weapon) -> str:
        level = getattr(weapon, "level", None)
        if level is None:
            return "--"
        stats = []
        for stat_id in getattr(weapon, "upgrade_stat_ids", ())[:2]:
            stat = getattr(weapon, "upgraded_stats", {}).get(stat_id)
            if stat is not None:
                stats.append(f"{stat.label} {stat.display_value}")
        suffix = f" [{', '.join(stats)}]" if stats else ""
        return f"Lv. {int(level)}{suffix}"

    @staticmethod
    def _format_tome_summary(tome) -> str:
        level = getattr(tome, "level", None)
        if level is None:
            return "--"
        stat_label = getattr(tome, "stat_label", "")
        display_value = getattr(tome, "display_value", "")
        suffix = f" [{stat_label} {display_value}]" if stat_label and display_value else ""
        return f"Lv. {int(level)}{suffix}"

    @staticmethod
    def _raw_snapshot_int_delta(base_snapshot, snapshot, attr_name: str) -> int | None:
        base_value = getattr(base_snapshot, attr_name, None)
        current_value = getattr(snapshot, attr_name, None)
        if base_value is None or current_value is None:
            return None
        return int(current_value) - int(base_value)

    @classmethod
    def _format_signed_count(cls, value: int | float) -> str:
        value = int(value)
        if value > 0:
            return f"+{cls.format_count(value)}"
        if value < 0:
            return f"-{cls.format_count(abs(value))}"
        return "0"

    @classmethod
    def _format_signed_seconds(cls, value: float) -> str:
        sign = "+" if value > 0 else "-" if value < 0 else ""
        return f"{sign}{cls.format_elapsed_time(abs(float(value)))}"

    @staticmethod
    def _format_signed_stat_delta(value: float) -> str:
        if abs(value) < 0.00001:
            return "0"
        if float(value).is_integer():
            return f"{int(value):+d}"
        return f"{value:+.2f}"

    @classmethod
    def _format_compare_run_stat_delta(cls, stat_a, stat_b) -> str:
        percent_delta = cls._display_percent_delta(
            getattr(stat_a, "display_value", ""),
            getattr(stat_b, "display_value", ""),
        )
        if percent_delta is not None:
            return cls._format_signed_percent_delta(percent_delta)
        return cls._format_signed_stat_delta(float(stat_b.value) - float(stat_a.value))

    @staticmethod
    def _display_percent_delta(display_a: str, display_b: str) -> float | None:
        text_a = str(display_a).strip()
        text_b = str(display_b).strip()
        if not text_a.endswith("%") or not text_b.endswith("%"):
            return None
        try:
            value_a = float(text_a[:-1].replace(",", ""))
            value_b = float(text_b[:-1].replace(",", ""))
        except ValueError:
            return None
        return value_b - value_a

    @staticmethod
    def _format_signed_percent_delta(value: float) -> str:
        if abs(value) < 0.00001:
            return "0%"
        sign = "+" if value > 0 else "-"
        magnitude = abs(value)
        if magnitude.is_integer():
            return f"{sign}{int(magnitude)}%"
        return f"{sign}{magnitude:.2f}%"

    @classmethod
    def format_snapshot_new_items(cls, previous_snapshot, snapshot) -> str:
        if previous_snapshot is None:
            return "No previous snapshot"
        new_items = cls.diff_new_items(getattr(previous_snapshot, "items", ()), getattr(snapshot, "items", ()))
        if not new_items:
            return "No new items since previous snapshot"
        return cls.format_new_items_rich_text(new_items)

    @classmethod
    def format_snapshot_item_gains_preview(cls, previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
        if previous_snapshot is None:
            return "No previous snapshot"
        changes = cls.summarize_item_segment_changes(segment_snapshots or (previous_snapshot, snapshot))
        gains = changes["gained"]
        broken = changes["broken"]
        lost = changes["lost"]
        total = sum(gain for _name, gain in gains)
        items_summary = cls.format_item_gain_rarity_totals(gains)
        if total > 0:
            items_summary = f'{items_summary} <span style="color:#98A7BA;">+{cls.format_count(total)}</span>'
        rows = [f'<span style="color:#98A7BA;">Items:</span> {items_summary}']
        time_delta = cls._snapshot_time_delta(previous_snapshot, snapshot)
        if time_delta is not None:
            rows.append(f'<span style="color:#98A7BA;">Time:</span> {cls.format_elapsed_time(time_delta)}')

        kill_delta = cls._snapshot_int_delta(previous_snapshot, snapshot, "mob_kills")
        if kill_delta is not None and kill_delta > 0:
            rows.append(f'<span style="color:#98A7BA;">Kills:</span> +{cls.format_count(kill_delta)}')

        level_delta = cls._snapshot_int_delta(previous_snapshot, snapshot, "player_level")
        if level_delta is not None and level_delta > 0:
            rows.append(f'<span style="color:#98A7BA;">Levels:</span> +{cls.format_count(level_delta)}')

        return "<br>".join(rows)

    @classmethod
    def diff_new_items(cls, previous_items, current_items) -> tuple[str, ...]:
        return tuple(f"{name} x{gain}" for name, gain in cls.diff_item_gains(previous_items, current_items))

    @classmethod
    def diff_item_gains(cls, previous_items, current_items) -> tuple[tuple[str, int], ...]:
        changes = cls.summarize_item_count_changes(previous_items, current_items)
        return changes["gained"]

    @classmethod
    def diff_item_losses(cls, previous_items, current_items) -> tuple[tuple[str, int], ...]:
        changes = cls.summarize_item_count_changes(previous_items, current_items)
        return changes["lost"]

    @classmethod
    def summarize_item_count_changes(cls, previous_items, current_items) -> dict[str, tuple[tuple[str, int], ...]]:
        previous_counts = cls._item_counts(previous_items)
        current_counts = cls._item_counts(current_items)
        gained: dict[str, int] = {}
        lost: dict[str, int] = {}
        broken: dict[str, int] = {}
        for name in set(previous_counts) | set(current_counts):
            current_count = current_counts.get(name, 0)
            delta = current_count - previous_counts.get(name, 0)
            if delta > 0:
                gained[name] = gained.get(name, 0) + delta
            elif delta < 0:
                target = broken if cls._is_breakable_consumed_item(name) else lost
                target[name] = target.get(name, 0) + abs(delta)
        return {
            "gained": cls._sort_item_delta_pairs(gained.items()),
            "lost": cls._sort_item_delta_pairs(lost.items()),
            "broken": cls._sort_item_delta_pairs(broken.items()),
        }

    @classmethod
    def summarize_item_segment_changes(cls, snapshots) -> dict[str, tuple[tuple[str, int], ...]]:
        snapshots = tuple(snapshots or ())
        gained: dict[str, int] = {}
        lost: dict[str, int] = {}
        broken: dict[str, int] = {}
        if len(snapshots) < 2:
            return {"gained": (), "lost": (), "broken": ()}

        previous_items = getattr(snapshots[0], "items", ())
        for snapshot in snapshots[1:]:
            changes = cls.summarize_item_count_changes(previous_items, getattr(snapshot, "items", ()))
            for bucket_name, target in (("gained", gained), ("lost", lost), ("broken", broken)):
                for name, count in changes[bucket_name]:
                    target[name] = target.get(name, 0) + count
            previous_items = getattr(snapshot, "items", ())

        return {
            "gained": cls._sort_item_delta_pairs(gained.items()),
            "lost": cls._sort_item_delta_pairs(lost.items()),
            "broken": cls._sort_item_delta_pairs(broken.items()),
        }

    @classmethod
    def _sort_item_delta_pairs(cls, items) -> tuple[tuple[str, int], ...]:
        return tuple(
            sorted(
                ((str(name), int(count)) for name, count in items if int(count) > 0),
                key=lambda item: (-cls._item_rarity_rank(item[0]), -item[1], item[0].casefold()),
            )
        )

    @classmethod
    def _is_breakable_consumed_item(cls, item_name: str) -> bool:
        rarity_name = cls._normalize_item_name_for_rarity(item_name)
        return rarity_name in {"Za Warudo", "Ze Warudo"}

    @classmethod
    def format_snapshot_item_changes_details(cls, previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
        changes = cls.summarize_item_segment_changes(segment_snapshots or (previous_snapshot, snapshot))
        sections: list[str] = []
        if changes["gained"]:
            sections.append(
                '<span style="color:#98A7BA; font-weight:700;">Gained</span><br>'
                f'{cls.format_item_gains_by_rarity(changes["gained"])}'
            )
        if changes["broken"]:
            sections.append(
                '<span style="color:#98A7BA; font-weight:700;">Broken</span><br>'
                f'{cls.format_item_losses_by_rarity(changes["broken"], suffix="broken")}'
            )
        if changes["lost"]:
            sections.append(
                '<span style="color:#98A7BA; font-weight:700;">Lost</span><br>'
                f'{cls.format_item_losses_by_rarity(changes["lost"])}'
            )
        if not sections:
            return '<span style="color:#98A7BA;">No item changes in this segment</span>'
        return "<br>".join(sections)

    @classmethod
    def format_item_gains_by_rarity(
        cls,
        gains: tuple[tuple[str, int], ...],
        *,
        max_items: int | None = None,
    ) -> str:
        if not gains:
            return '<span style="color:#98A7BA;">No item gains</span>'

        grouped: dict[str, list[tuple[str, int]]] = {
            "LEGENDARY": [],
            "RARE": [],
            "UNCOMMON": [],
            "COMMON": [],
            "UNKNOWN": [],
        }
        for name, gain in gains:
            rarity_name = cls._normalize_item_name_for_rarity(name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name, "UNKNOWN")
            if rarity not in grouped:
                rarity = "UNKNOWN"
            grouped[rarity].append((cls._normalize_item_name_for_display(name), int(gain)))

        remaining = max_items
        hidden_count = 0
        rows: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON", "UNKNOWN"):
            items = grouped[rarity]
            if not items:
                continue
            if remaining is not None:
                visible_items = items[:remaining]
                hidden_count += max(0, len(items) - len(visible_items))
                remaining -= len(visible_items)
                if not visible_items:
                    continue
            else:
                visible_items = items
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            item_text = " | ".join(
                cls._format_item_change_text(name, f"+{cls.format_count(gain)}")
                for name, gain in visible_items
            )
            rows.append(
                f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{item_text}</span>'
            )
            if remaining is not None and remaining <= 0:
                break

        if hidden_count > 0:
            rows.append(f'<span style="color:#98A7BA;">+{hidden_count} more gains...</span>')
        return "<br>".join(rows)

    @classmethod
    def format_item_losses_by_rarity(
        cls,
        losses: tuple[tuple[str, int], ...],
        *,
        suffix: str | None = None,
    ) -> str:
        if not losses:
            return '<span style="color:#98A7BA;">No item losses</span>'

        grouped: dict[str, list[tuple[str, int]]] = {
            "LEGENDARY": [],
            "RARE": [],
            "UNCOMMON": [],
            "COMMON": [],
            "UNKNOWN": [],
        }
        for name, loss in losses:
            rarity_name = cls._normalize_item_name_for_rarity(name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name, "UNKNOWN")
            if rarity not in grouped:
                rarity = "UNKNOWN"
            grouped[rarity].append((cls._normalize_item_name_for_display(name), int(loss)))

        rows: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON", "UNKNOWN"):
            items = grouped[rarity]
            if not items:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            item_text = " | ".join(
                cls._format_item_change_text(
                    name,
                    f"-{cls.format_count(loss)}{f' {suffix}' if suffix else ''}",
                )
                for name, loss in items
            )
            rows.append(
                f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{item_text}</span>'
            )
        return "<br>".join(rows)

    @classmethod
    def format_item_loss_inline(cls, losses: tuple[tuple[str, int], ...]) -> str:
        if not losses:
            return '<span style="color:#98A7BA;">--</span>'
        return " | ".join(
            cls._format_item_change_text(
                cls._normalize_item_name_for_display(name),
                f"-{cls.format_count(count)}",
            )
            for name, count in losses
        )

    @staticmethod
    def _format_item_change_text(display_name: str, suffix: str) -> str:
        color = item_display_color(display_name, "#E5E7EB")
        return (
            f'<span style="color:{color};">'
            f'{html.escape(display_name)} {html.escape(suffix)}</span>'
        )

    @classmethod
    def format_item_gain_rarity_totals(cls, gains: tuple[tuple[str, int], ...]) -> str:
        rarity_totals = cls._empty_item_rarity_totals()
        for name, gain in gains:
            rarity_name = cls._normalize_item_name_for_rarity(name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
            if rarity in rarity_totals:
                rarity_totals[rarity] += int(gain)

        parts: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
            total = rarity_totals.get(rarity, 0)
            if total <= 0:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            parts.append(
                f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{cls.format_count(total)}</span>'
            )
        return " ".join(parts) if parts else '<span style="color:#98A7BA;">--</span>'

    @classmethod
    def format_snapshot_compare_summary(
        cls,
        base_snapshot,
        snapshot,
        *,
        base_index: int | None,
        current_index: int | None,
        segment_snapshots=(),
    ) -> str:
        pieces: list[str] = []
        if base_index is not None and current_index is not None:
            pieces.append(f"Snapshot {int(base_index) + 1} -> {int(current_index) + 1}")
        base_time = getattr(base_snapshot, "game_time_seconds", None)
        current_time = getattr(snapshot, "game_time_seconds", None)
        if base_time is not None and current_time is not None:
            pieces.append(f"{cls.format_elapsed_time(base_time)} -> {cls.format_elapsed_time(current_time)}")
        kill_delta = cls._snapshot_int_delta(base_snapshot, snapshot, "mob_kills")
        if kill_delta is not None and kill_delta > 0:
            pieces.append(f"+{cls.format_count(kill_delta)} kills")
        level_delta = cls._snapshot_int_delta(base_snapshot, snapshot, "player_level")
        if level_delta is not None and level_delta > 0:
            pieces.append(f"+{cls.format_count(level_delta)} levels")
        changes = cls.summarize_item_segment_changes(segment_snapshots or (base_snapshot, snapshot))
        item_total = sum(gain for _name, gain in changes["gained"])
        pieces.append(f"+{cls.format_count(item_total)} items")
        broken_total = sum(count for _name, count in changes["broken"])
        if broken_total:
            pieces.append(f"{cls.format_count(broken_total)} broken")
        lost_total = sum(count for _name, count in changes["lost"])
        if lost_total:
            pieces.append(f"-{cls.format_count(lost_total)} lost")
        return " | ".join(pieces)

    @staticmethod
    def _snapshot_int_delta(base_snapshot, snapshot, attr_name: str) -> int | None:
        base_value = getattr(base_snapshot, attr_name, None)
        current_value = getattr(snapshot, attr_name, None)
        if base_value is None or current_value is None:
            return None
        return max(0, int(current_value) - int(base_value))

    @staticmethod
    def _snapshot_time_delta(base_snapshot, snapshot) -> float | None:
        base_time = getattr(base_snapshot, "game_time_seconds", None)
        current_time = getattr(snapshot, "game_time_seconds", None)
        if base_time is None or current_time is None:
            return None
        return max(0.0, float(current_time) - float(base_time))

    @classmethod
    def format_new_items_rich_text(cls, items) -> str:
        if not items:
            return "No new items since previous snapshot"
        return ", ".join(cls._format_single_item_rich_text(item) for item in items)

    @classmethod
    def format_banishes_rich_text(cls, banishes) -> str:
        banishes = tuple(str(item) for item in (banishes or ()))
        if not banishes:
            return "No banishes yet"
        return ", ".join(cls._format_single_banish_rich_text(item) for item in banishes)

    @classmethod
    def _format_single_banish_rich_text(cls, banish_text: str) -> str:
        if banish_text.endswith(" Tome"):
            tome_name = html.escape(banish_text)
            return f'<span style="font-weight: 700;">{tome_name}</span>'
        return cls._format_single_item_rich_text(banish_text)

    @staticmethod
    def merge_banish_appearance_order(previous_banishes, current_banishes) -> tuple[str, ...]:
        current = tuple(str(item) for item in (current_banishes or ()))
        if not current:
            return ()
        previous = tuple(str(item) for item in (previous_banishes or ()))
        merged = [item for item in previous if item in current]
        for item in current:
            if item not in merged:
                merged.append(item)
        return tuple(merged)

    @classmethod
    def _item_counts(cls, items) -> dict[str, int]:
        return run_summary.item_counts(items)

    @classmethod
    def build_stage_summary(cls, snapshots) -> list[dict[str, str]]:
        return run_summary.build_stage_summary(snapshots)

    @classmethod
    def _legacy_build_stage_summary(cls, snapshots) -> list[dict[str, str]]:
        rows = [
            {
                "label": f"Stage {index}",
                "kills": "--",
                "time": "--",
                "items": "--",
            }
            for index in range(1, 5)
        ]
        if not snapshots:
            return rows

        stage_buckets: dict[int, list[object]] = {index: [] for index in range(1, 5)}
        stage_item_gains: dict[int, dict[str, int]] = {
            index: cls._empty_item_rarity_totals() for index in range(1, 5)
        }
        stage_kill_baselines: dict[int, int] = {1: 0}
        last_known_mob_kills: int | None = None
        current_stage_index = 1
        item_gain_tracker = None
        previous_snapshot = None
        for snapshot in snapshots:
            snapshot_mob_kills = getattr(snapshot, "mob_kills", None)
            if item_gain_tracker is None:
                item_gain_tracker = cls._create_stage_item_gain_tracker(getattr(snapshot, "items", ()))
            if previous_snapshot is not None:
                previous_stage_index = current_stage_index
                next_stage_index = cls._resolve_next_stage_index(
                    current_stage_index,
                    previous_snapshot,
                    snapshot,
                )
                current_stage_index = min(max(next_stage_index, current_stage_index), 4)
                if (
                    current_stage_index > previous_stage_index
                    and cls._is_stage_transition_boundary_snapshot(snapshot)
                ):
                    stage_buckets[previous_stage_index].append(snapshot)
                if current_stage_index > previous_stage_index:
                    baseline = getattr(snapshot, "mob_kills", None)
                    if baseline is None:
                        baseline = last_known_mob_kills
                    if baseline is not None:
                        stage_kill_baselines[current_stage_index] = max(0, int(baseline))
                item_gains = cls._update_stage_item_gain_tracker(
                    item_gain_tracker,
                    getattr(snapshot, "items", ()),
                )
                for rarity, count in item_gains.items():
                    stage_item_gains[current_stage_index][rarity] += count
            stage_buckets[current_stage_index].append(snapshot)
            if snapshot_mob_kills is not None:
                last_known_mob_kills = max(0, int(snapshot_mob_kills))
            previous_snapshot = snapshot

        for stage_index, bucket in stage_buckets.items():
            if not bucket:
                continue
            first_snapshot = bucket[0]
            last_snapshot = bucket[-1]
            start_run_time = getattr(first_snapshot, "game_time_seconds", None)
            if stage_index == 1 and start_run_time is not None:
                start_run_time = 0.0
            end_run_time = getattr(last_snapshot, "game_time_seconds", None)
            duration_text = "--"
            if start_run_time is not None and end_run_time is not None:
                duration_text = cls.format_elapsed_time(max(0.0, end_run_time - start_run_time))

            kills_text = "--"
            kill_snapshots = [
                candidate
                for candidate in bucket
                if getattr(candidate, "mob_kills", None) is not None
            ]
            if kill_snapshots:
                first_kills = stage_kill_baselines.get(stage_index)
                if first_kills is None:
                    first_kills = getattr(kill_snapshots[0], "mob_kills", None)
                last_kills = getattr(kill_snapshots[-1], "mob_kills", None)
                kills_text = cls.format_count(int(last_kills) - int(first_kills))

            items_text = cls._format_stage_item_rarity_summary(stage_item_gains[stage_index])
            rows[stage_index - 1] = {
                "label": f"Stage {stage_index}",
                "kills": kills_text,
                "time": duration_text,
                "items": items_text,
            }

        cls._reconcile_stage_summary_kills(rows, snapshots)
        return rows

    @classmethod
    def _reconcile_stage_summary_kills(cls, rows: list[dict[str, str]], snapshots) -> None:
        final_snapshot = snapshots[-1] if snapshots else None
        final_total = getattr(final_snapshot, "mob_kills", None) if final_snapshot is not None else None
        if final_total is None:
            return
        parsed_counts: list[int | None] = []
        for row in rows:
            kills_text = str(row.get("kills", "--"))
            if kills_text == "--":
                parsed_counts.append(None)
                continue
            try:
                parsed_counts.append(int(kills_text.replace(",", "")))
            except ValueError:
                parsed_counts.append(None)
        known_total = sum(count for count in parsed_counts if count is not None)
        delta = int(final_total) - known_total
        if delta == 0:
            return
        last_index = None
        for index, count in enumerate(parsed_counts):
            if count is not None:
                last_index = index
        if last_index is None:
            return
        updated_total = max(0, int(parsed_counts[last_index] or 0) + delta)
        rows[last_index]["kills"] = cls.format_count(updated_total)

    @classmethod
    def _resolve_next_stage_index(cls, current_stage_index: int, previous_snapshot, snapshot) -> int:
        previous_stage_ptr = int(getattr(previous_snapshot, "stage_ptr", 0) or 0)
        current_stage_ptr = int(getattr(snapshot, "stage_ptr", 0) or 0)
        previous_seed = getattr(previous_snapshot, "map_seed", None)
        current_seed = getattr(snapshot, "map_seed", None)
        if (
            current_stage_index < 3
            and (
                (
                    previous_stage_ptr
                    and current_stage_ptr
                    and current_stage_ptr != previous_stage_ptr
                )
                or (
                    previous_stage_ptr == 0
                    and current_stage_ptr == 0
                    and previous_seed is not None
                    and current_seed is not None
                    and current_seed != previous_seed
                )
            )
        ):
            return current_stage_index + 1

        if current_stage_index == 3 and cls._looks_like_stage_four_transition(previous_snapshot, snapshot):
            return 4
        return current_stage_index

    @staticmethod
    def _is_stage_transition_boundary_snapshot(snapshot) -> bool:
        stage_time = getattr(snapshot, "stage_time_seconds", None)
        if stage_time is None:
            return False
        return 0.0 <= float(stage_time) <= PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS

    @classmethod
    def _looks_like_stage_four_transition(cls, previous_snapshot, snapshot) -> bool:
        previous_stage_ptr = int(getattr(previous_snapshot, "stage_ptr", 0) or 0)
        current_stage_ptr = int(getattr(snapshot, "stage_ptr", 0) or 0)
        previous_seed = getattr(previous_snapshot, "map_seed", None)
        current_seed = getattr(snapshot, "map_seed", None)
        previous_stage_time = getattr(previous_snapshot, "stage_time_seconds", None)
        current_stage_time = getattr(snapshot, "stage_time_seconds", None)
        previous_run_time = getattr(previous_snapshot, "game_time_seconds", None)
        current_run_time = getattr(snapshot, "game_time_seconds", None)
        if (
            not previous_stage_ptr
            or not current_stage_ptr
            or previous_stage_ptr != current_stage_ptr
            or previous_seed != current_seed
            or previous_stage_time is None
            or current_stage_time is None
            or previous_run_time is None
            or current_run_time is None
        ):
            return False
        if current_run_time <= previous_run_time:
            return False
        if (
            current_stage_time <= PLAYER_STATS_STAGE4_RESET_WINDOW_SECONDS
            and current_stage_time + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS < previous_stage_time
        ):
            return True
        if (
            PLAYER_STATS_STAGE4_GHOST_TIMER_SECONDS <= current_stage_time <= PLAYER_STATS_STAGE4_GHOST_ENTRY_MAX_SECONDS
            and previous_stage_time - current_stage_time >= PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS
        ):
            return True
        return (
            current_stage_time >= PLAYER_STATS_STAGE4_GHOST_TIMER_SECONDS
            and current_stage_time - previous_stage_time >= PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS
        )

    @classmethod
    def _item_gain_between_snapshots(cls, first_snapshot, last_snapshot) -> int:
        first_counts = cls._item_counts(getattr(first_snapshot, "items", ()))
        last_counts = cls._item_counts(getattr(last_snapshot, "items", ()))
        total_gain = 0
        for name, current_count in last_counts.items():
            total_gain += max(0, current_count - first_counts.get(name, 0))
        return total_gain

    @classmethod
    def _item_rarity_gain_between_snapshots(cls, first_snapshot, last_snapshot) -> dict[str, int]:
        first_counts = cls._item_counts(getattr(first_snapshot, "items", ()))
        last_counts = cls._item_counts(getattr(last_snapshot, "items", ()))
        rarity_gains = cls._empty_item_rarity_totals()
        for name, current_count in last_counts.items():
            gain = max(0, current_count - first_counts.get(name, 0))
            if gain <= 0:
                continue
            rarity_name = cls._normalize_item_name_for_rarity(name)
            rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
            if rarity in rarity_gains:
                rarity_gains[rarity] += gain
        return rarity_gains

    @classmethod
    def _create_stage_item_gain_tracker(cls, items) -> dict[str, dict[str, int]]:
        return {
            "confirmed_counts": cls._item_counts(items),
            "pending_drop_streaks": {},
        }

    @classmethod
    def _update_stage_item_gain_tracker(cls, tracker: dict[str, dict[str, int]], items) -> dict[str, int]:
        confirmed_counts = tracker.setdefault("confirmed_counts", {})
        pending_drop_streaks = tracker.setdefault("pending_drop_streaks", {})
        current_counts = cls._item_counts(items)
        rarity_gains = cls._empty_item_rarity_totals()

        for name in set(confirmed_counts) | set(current_counts) | set(pending_drop_streaks):
            current_count = current_counts.get(name, 0)
            confirmed_count = confirmed_counts.get(name, 0)
            if current_count >= confirmed_count:
                pending_drop_streaks.pop(name, None)
                gain = current_count - confirmed_count
                if gain > 0:
                    rarity_name = cls._normalize_item_name_for_rarity(name)
                    rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
                    if rarity in rarity_gains:
                        rarity_gains[rarity] += gain
                if current_count > 0:
                    confirmed_counts[name] = current_count
                else:
                    confirmed_counts.pop(name, None)
                continue

            streak = int(pending_drop_streaks.get(name, 0)) + 1
            if streak >= PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS:
                pending_drop_streaks.pop(name, None)
                if current_count > 0:
                    confirmed_counts[name] = current_count
                else:
                    confirmed_counts.pop(name, None)
                continue
            pending_drop_streaks[name] = streak

        return rarity_gains

    @classmethod
    def _format_stage_item_rarity_summary(cls, rarity_totals: dict[str, int]) -> str:
        parts: list[str] = []
        for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
            total = int(rarity_totals.get(rarity, 0))
            if total <= 0:
                continue
            color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
            parts.append(
                f'<span style="color:{color}; font-weight:700;">&#9679;</span> '
                f'<span style="color:#E5E7EB;">{html.escape(str(total))}</span>'
            )
        return " ".join(parts) if parts else '<span style="color:#98A7BA;">--</span>'

    @staticmethod
    def _set_stage_summary_labels(labels, rows) -> None:
        default_rows = [
            {
                "label": f"Stage {index}",
                "kills": "--",
                "time": "--",
                "items": "--",
            }
            for index in range(1, 5)
        ]
        rows = rows or default_rows
        for labels_by_column, row in zip(labels, rows):
            if isinstance(labels_by_column, dict):
                labels_by_column["stage"].setText(str(row["label"]).replace("Stage ", ""))
                labels_by_column["time"].setText(row["time"])
                labels_by_column["kills"].setText(row["kills"])
                labels_by_column["items"].setText(row["items"])
            else:
                labels_by_column.setText(
                    f"{row['label']}: Kills {row['kills']} | Time {row['time']} | Items {row['items']}"
                )

    @classmethod
    def format_items_rich_text(cls, items) -> str:
        if not items:
            return "--"
        return ", ".join(cls._format_single_item_rich_text(item) for item in items)

    @classmethod
    def _format_single_item_rich_text(cls, item_text: str) -> str:
        item_name, suffix = cls._split_item_stack_suffix(item_text)
        display_name = cls._normalize_item_name_for_display(item_name)
        rarity_name = cls._normalize_item_name_for_rarity(display_name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
        color = ITEM_RARITY_COLOR_MAP.get(rarity)
        color = item_display_color(display_name, color)
        escaped_name = html.escape(display_name)
        if color:
            escaped_name = f'<span style="color: {color}; font-weight: 700;">{escaped_name}</span>'
        escaped_suffix = html.escape(suffix)
        return f"{escaped_name}{escaped_suffix}"

    @staticmethod
    def _split_item_stack_suffix(item_text: str) -> tuple[str, str]:
        if not item_text:
            return "", ""
        name, separator, suffix = item_text.rpartition(" x")
        if separator and suffix.isdigit():
            return name, f"{separator}{suffix}"
        return item_text, ""

    @staticmethod
    def _normalize_item_name_for_rarity(item_name: str) -> str:
        return normalize_item_name_for_rarity(item_name)

    @staticmethod
    def _normalize_item_name_for_display(item_name: str) -> str:
        return normalize_item_name_for_display(item_name)

    @staticmethod
    def calculate_player_chests_per_minute(stats) -> float | None:
        elite_stat = stats.get("Elite Spawn Increase")
        powerup_stat = stats.get("Powerup Drop Chance")
        elite_spawn_increase = getattr(elite_stat, "value", None)
        powerup_drop_chance = getattr(powerup_stat, "value", None)
        if elite_spawn_increase is None or powerup_drop_chance is None:
            return None
        return calculate_chests_per_minute(elite_spawn_increase, powerup_drop_chance)

    @classmethod
    def resolve_snapshot_chests_per_minute(cls, snapshot) -> float | None:
        stored_value = getattr(snapshot, "chests_per_minute", None)
        if stored_value is not None:
            return stored_value
        return cls.calculate_player_chests_per_minute(snapshot.stats)

    @staticmethod
    def format_chests_per_minute(value: float | None) -> str:
        if value is None:
            return "Average chests/min: --"
        return f"Average chests/min: {value:.2f}"

    @classmethod
    def format_powerups_duration(cls, stats) -> str:
        stat = (stats or {}).get("Powerup Multiplier")
        try:
            powerup_multiplier = float(getattr(stat, "value", None))
        except (TypeError, ValueError):
            return "Powerups: --"
        if not isfinite(powerup_multiplier):
            return "Powerups: --"

        standard_duration = 15.0 * powerup_multiplier
        clock_duration = 12.0 * powerup_multiplier
        return (
            f"Powerups: {cls.format_seconds_compact(standard_duration)}s"
            f" | Clock: {cls.format_seconds_compact(clock_duration)}s"
        )

    def format_live_powerups(self, stats) -> str:
        formatter = getattr(self.live_run_tracker, "format_powerups_summary", None)
        snapshot_reader = getattr(self.live_run_tracker, "powerups_snapshot", None)
        if callable(formatter) and callable(snapshot_reader):
            try:
                if getattr(snapshot_reader(), "available", False) is True:
                    return formatter(include_left_word=False)
            except Exception:
                pass
        return self.format_powerups_duration(stats)

    def _apply_live_powerups_card(self, stats) -> None:
        group = getattr(self, "player_stats_powerups_group", None)
        labels = getattr(self, "player_stats_live_powerup_labels", None)
        if group is None or not isinstance(labels, dict):
            return
        title, values = self.format_live_powerups_card(stats)
        group.setTitle(title)
        for effect_name, label in labels.items():
            _set_text(label, f"{effect_name}: {values.get(effect_name, '--')}")

    def format_live_powerups_card(self, stats) -> tuple[str, dict[str, str]]:
        values = {name: "--" for name in ("Rage", "Clock", "Shield", "Stonks")}
        title = "Powerups"

        snapshot_reader = getattr(self.live_run_tracker, "powerups_snapshot", None)
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
                    left_text = f"({self.format_seconds_compact(effect.remaining_seconds)}s)"
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
                    values[effect_name] = f"-- ({self.format_seconds_compact(duration)}s)"
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
        standard_duration = self.format_seconds_compact(15.0 * powerup_multiplier)
        clock_duration = self.format_seconds_compact(12.0 * powerup_multiplier)
        values["Rage"] = f"-- ({standard_duration}s)"
        values["Clock"] = f"-- ({clock_duration}s)"
        values["Shield"] = f"-- ({standard_duration}s)"
        values["Stonks"] = f"-- ({standard_duration}s)"
        return title, values

    @staticmethod
    def format_seconds_compact(value: float) -> str:
        return str(int(round(value)))

    @staticmethod
    def chests_card_values(
        opened_by_stage: dict[int, int] | None,
        total_by_stage: dict[int, int] | None,
        opened: int | None,
        total: int | None,
        paid: int | None,
        key_procs: int | None,
        free: int | None,
        keys: int | None,
        expected: float | None,
        total_is_minimum: bool = False,
    ) -> dict[str, str]:
        if total is None:
            return {
                "maps": "--",
                "total": "--",
                "paid_free": "-- / --",
                "key_procs": "-- (--)",
                "expected": "--",
                "keys": "-- (--)",
            }

        stage_parts = []
        for stage, count in sorted((opened_by_stage or {}).items()):
            stage_total = (total_by_stage or {}).get(stage, 0)
            if int(count) < 0:
                stage_parts.append(f"T{stage}:--/{stage_total}")
            else:
                stage_parts.append(f"T{stage}:{count}/{stage_total}")
        opened_text = "--" if opened is None else str(opened)
        if opened is not None and total_is_minimum:
            opened_text += "+"
        total_text = str(total)
        stages = " ".join(stage_parts) if stage_parts else f"T1:{opened_text}/{total_text}"

        paid_text = "--" if paid is None else str(paid)
        free_text = "--" if free is None else str(free)
        normal = None if paid is None or key_procs is None else paid + key_procs
        procs_text = "--" if key_procs is None or normal is None else f"{key_procs}/{normal}"
        proc_rate = (
            "--"
            if key_procs is None or not normal
            else f"{key_procs / normal * 100.0:.1f}%"
        )
        expected_text = "--" if expected is None else f"{expected:.1f}"
        keys_text = "--" if keys is None else str(keys)
        chance = "--" if keys is None else f"{LiveRunTracker.key_proc_chance(keys) * 100.0:.1f}%"
        return {
            "maps": stages,
            "total": f"{opened_text}/{total_text}",
            "paid_free": f"{paid_text} / {free_text}",
            "key_procs": f"{procs_text} ({proc_rate})",
            "expected": expected_text,
            "keys": f"{keys_text} ({chance})",
        }

    @staticmethod
    def _set_chests_card_values(labels, values: dict[str, str] | None) -> None:
        if not labels:
            return
        values = values or PlayerStatsMixin.chests_card_values(
            None, None, None, None, None, None, None, None, None
        )
        for key, label in labels.items():
            _set_text(label, values.get(key, "--"))

    def _update_live_chest_summary(self, chest_stats) -> None:
        labels = getattr(self, "player_stats_chests_card_values", None)
        if labels:
            self._set_chests_card_values(
                labels,
                self.chests_card_values(
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

    def _update_recorded_chest_summary(self, snapshot) -> None:
        paid = getattr(snapshot, "paid_chests", None)
        key_procs = getattr(snapshot, "key_procs", None)
        labels = getattr(self, "vods_chests_card_values", None)
        if labels:
            self._set_chests_card_values(
                labels,
                self.chests_card_values(
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

    def close_player_stats_client(self):
        player_stats_client = self.__dict__.get("player_stats_client")
        if player_stats_client:
            try:
                player_stats_client.close()
            except Exception:
                pass
            self.player_stats_client = None
        self.player_stats_last_seed = None
        self.player_stats_last_run_timer = None
        self._player_stats_memory_error_streak = 0

    def close_player_stats_game_data_client(self):
        game_data_client = self.__dict__.get("player_stats_game_data_client")
        if game_data_client:
            try:
                game_data_client.close()
            except Exception:
                pass
            self.player_stats_game_data_client = None
        self._player_stats_game_data_memory_error_streak = 0
