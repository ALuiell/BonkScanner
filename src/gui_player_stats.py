from __future__ import annotations

from math import isfinite
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QVBoxLayout,
)

from app import config
from core.game_state import MapStat, RuntimeGameMode, RuntimeGameState
from infra.memory.game_data_client import GameDataClient
from gui_dialogs import CleanupRecordingsDialog, ConfirmDeleteRecordingDialog
from gui_shared import _clear_layout, _clear_text_input, _read_text, _set_text, _set_text_input
from gui_styles import (
    ITEM_RARITY_BY_NAME,
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
    PLAYER_STATS_STAGE4_GHOST_ENTRY_MAX_SECONDS,
    PLAYER_STATS_STAGE4_GHOST_TIMER_SECONDS,
    PLAYER_STATS_STAGE4_RESET_WINDOW_SECONDS,
    PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS,
    PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS,
    PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS,
    PLAYER_STATS_VALUE_FONT_SIZE,
    _button_state_stylesheet,
)
from infra.memory.reader import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from live_run_tracker import (
    CHAOS_TOME_GAME_STAT_ORDER,
    LiveRunSnapshot,
    LiveRunTracker,
    PowerupMapContext,
)
from core.stats.types import DamageSourceSnapshot, PLAYER_STAT_GROUPS, TomeSnapshot, WeaponSnapshot, calculate_chests_per_minute
from infra.memory.player_stats_client import PlayerStatsClient
from app.refresh_tasks import (
    PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD,
    ensure_refresh_coordinator,
    overlay_widget_refresh_active,
    record_player_stats_memory_failure,
    record_player_stats_memory_success,
)
from app.snapshot_store import LiveSnapshotStore
from infra.vod_storage import delete_vod, delete_vods_below_snapshot_count, load_vod, refresh_vod_metadata_index, rename_vod
from projections.vod import build_vod_capture_kwargs
from projections import formatting

CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS = 1.0


def _set_items_text(widget, items=(), *, items_text: str | None = None) -> None:
    text = items_text if items_text is not None else PlayerStatsMixin.format_items(items)
    if widget is None:
        return
    if hasattr(widget, "setTextFormat"):
        widget.setText(PlayerStatsMixin.format_items_rich_text(items) if items_text is None else text)
        return
    _set_text(widget, text)

class PlayerStatsMixin:
    def _ensure_live_snapshot_store(self) -> LiveSnapshotStore:
        store = self.__dict__.get("_live_snapshot_store")
        if store is None:
            store = LiveSnapshotStore()
            self.__dict__["_live_snapshot_store"] = store
        return store

    # Backward-compatible attribute access over LiveSnapshotStore's fields.
    # Production code should call _ensure_live_snapshot_store() and use its
    # methods directly; these properties exist so external pokes (tests, and
    # any object.__new__()-built app double that never runs __init__) keep
    # working unchanged.
    @property
    def player_stats_last_known_items(self):
        return self._ensure_live_snapshot_store().last_known_items

    @player_stats_last_known_items.setter
    def player_stats_last_known_items(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_items = value

    @property
    def player_stats_last_known_weapons(self):
        return self._ensure_live_snapshot_store().last_known_weapons

    @player_stats_last_known_weapons.setter
    def player_stats_last_known_weapons(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_weapons = value

    @property
    def player_stats_last_known_tomes(self):
        return self._ensure_live_snapshot_store().last_known_tomes

    @player_stats_last_known_tomes.setter
    def player_stats_last_known_tomes(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_tomes = value

    @property
    def player_stats_last_known_damage_sources(self):
        return self._ensure_live_snapshot_store().last_known_damage_sources

    @player_stats_last_known_damage_sources.setter
    def player_stats_last_known_damage_sources(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_damage_sources = value

    @property
    def player_stats_last_known_banishes(self):
        return self._ensure_live_snapshot_store().last_known_banishes

    @player_stats_last_known_banishes.setter
    def player_stats_last_known_banishes(self, value) -> None:
        self._ensure_live_snapshot_store().last_known_banishes = value

    @property
    def player_stats_live_banishes(self):
        return self._ensure_live_snapshot_store().live_banishes

    @player_stats_live_banishes.setter
    def player_stats_live_banishes(self, value) -> None:
        self._ensure_live_snapshot_store().live_banishes = value

    @property
    def player_stats_last_seed(self):
        return self._ensure_live_snapshot_store().last_seed

    @player_stats_last_seed.setter
    def player_stats_last_seed(self, value) -> None:
        self._ensure_live_snapshot_store().last_seed = value

    @property
    def player_stats_last_run_timer(self):
        return self._ensure_live_snapshot_store().last_run_timer

    @player_stats_last_run_timer.setter
    def player_stats_last_run_timer(self, value) -> None:
        self._ensure_live_snapshot_store().last_run_timer = value

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
        """The single refresh driver.

        Every cadence lives in a registered task's ``interval_ms``, not in a
        timer: this callback only ticks. Recording lifecycle work that used to
        sit in a second 10 s timer is now the ``recording_lifecycle`` task, which
        keeps its 10 s interval.
        """
        if self._is_shutting_down:
            return
        try:
            self._refresh_core_run_lifecycle_state()
            ensure_refresh_coordinator(self).tick()
        finally:
            if not self._is_shutting_down:
                self.after(
                    int(getattr(config, "FAST_TRACKER_INTERVAL_MS", 500)),
                    self.update_player_stats_timer,
                )

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

    def _overlay_requires_player_snapshot(self) -> bool:
        return any(
            overlay_widget_refresh_active(self, widget_id)
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
        self._ensure_live_snapshot_store().reset_for_new_match()
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
        snapshot_store = self._ensure_live_snapshot_store()
        is_new_match = snapshot_store.is_new_match(map_seed=map_seed, run_timer_seconds=run_timer_seconds)

        if is_new_match:
            self.player_stats_disabled_items_refresh_pending = True
            snapshot_store.reset_for_new_match()

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
        snapshot_store.record_match_tick(map_seed=map_seed, run_timer_seconds=run_timer_seconds)

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
            record_player_stats_memory_failure(self, exc)
            try:
                self.mark_overlay_read_failed(no_game=False)
            except Exception:
                pass
            return False
        except Exception as exc:
            record_player_stats_memory_failure(self, exc)
            try:
                self.mark_overlay_read_failed(no_game=False)
            except Exception:
                pass
            return False

        record_player_stats_memory_success(self)

        chests_per_minute = self.calculate_player_chests_per_minute(stats)
        items_text = None if items_available else "Items unavailable"
        snapshot_store = self._ensure_live_snapshot_store()

        merged_items = snapshot_store.merge_items(items, items_available)
        effective_items = merged_items.effective
        items_available = merged_items.available

        merged_weapons = snapshot_store.merge_weapons(weapons, weapons_available)
        effective_weapons = merged_weapons.effective
        weapons_available = merged_weapons.available
        effective_weapons_available = merged_weapons.effective_available

        merged_tomes = snapshot_store.merge_tomes(tomes, tomes_available)
        effective_tomes = merged_tomes.effective
        tomes_available = merged_tomes.available
        effective_tomes_available = merged_tomes.effective_available

        merged_damage_sources = snapshot_store.merge_damage_sources(damage_sources, damage_sources_available)
        effective_damage_sources = merged_damage_sources.effective
        damage_sources_available = merged_damage_sources.available
        effective_damage_sources_available = merged_damage_sources.effective_available

        merged_banishes = snapshot_store.merge_banishes(
            banishes,
            banishes_available,
            merge_fn=self.merge_banish_appearance_order,
        )
        banishes = merged_banishes.banishes
        banishes_available = merged_banishes.available

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
            record_player_stats_memory_success(self)
            return result
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError, ValueError) as exc:
            record_player_stats_memory_failure(self, exc)
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
    def _empty_item_rarity_totals(cls) -> dict[str, int]:
        return formatting._empty_item_rarity_totals()

    @classmethod
    def format_items_rarity_summary_rich_text(cls, items) -> str:
        return formatting.format_items_rarity_summary_rich_text(items)

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
        return formatting._item_rarity_rank(item_text)

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
        return formatting.format_duration(seconds)

    @staticmethod
    def format_elapsed_time(seconds: float | int) -> str:
        return formatting.format_elapsed_time(seconds)

    @classmethod
    def format_in_game_time(cls, seconds: float | None) -> str:
        return formatting.format_in_game_time(seconds)

    @staticmethod
    def format_mob_kills(value: int | None, kps: int | None = None) -> str:
        return formatting.format_mob_kills(value, kps)

    @staticmethod
    def format_kps_averages(
        minute_avg_kps: int | None,
        five_minute_avg_kps: int | None,
    ) -> str:
        return formatting.format_kps_averages(minute_avg_kps, five_minute_avg_kps)

    @staticmethod
    def format_count(value: int | float) -> str:
        return formatting.format_count(value)

    @staticmethod
    def format_damage_source_value(value: int | float) -> str:
        return formatting.format_damage_source_value(value)

    @staticmethod
    def format_player_level(value: int | None) -> str:
        return formatting.format_player_level(value)

    @staticmethod
    def format_items(items) -> str:
        return formatting.format_items(items)










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
    def _format_compare_entity_label(cls, name: str, value_a, value_b) -> str:
        return formatting._format_compare_entity_label(name, value_a, value_b)

    @staticmethod
    def _weapon_stat_label(weapon_a, weapon_b, stat_id: int) -> str:
        return formatting._weapon_stat_label(weapon_a, weapon_b, stat_id)

    @staticmethod
    def _tome_value_label(tome_a, tome_b) -> str:
        return formatting._tome_value_label(tome_a, tome_b)

    @staticmethod
    def _metric_value(value, display_value):
        return formatting._metric_value(value, display_value)

    @classmethod
    def _format_compare_metric_row(cls, label: str, value_a, value_b) -> tuple[str, str, str, str]:
        return formatting._format_compare_metric_row(label, value_a, value_b)

    @staticmethod
    def _level_display(value) -> str:
        return formatting._level_display(value)

    @classmethod
    def _level_delta(cls, value_a, value_b) -> str:
        return formatting._level_delta(value_a, value_b)

    @classmethod
    def format_snapshot_new_items(cls, previous_snapshot, snapshot) -> str:
        return formatting.format_snapshot_new_items(previous_snapshot, snapshot)

    @classmethod
    def format_snapshot_item_gains_preview(cls, previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
        return formatting.format_snapshot_item_gains_preview(previous_snapshot, snapshot, segment_snapshots=segment_snapshots)

    @classmethod
    def diff_new_items(cls, previous_items, current_items) -> tuple[str, ...]:
        return formatting.diff_new_items(previous_items, current_items)

    @classmethod
    def diff_item_gains(cls, previous_items, current_items) -> tuple[tuple[str, int], ...]:
        return formatting.diff_item_gains(previous_items, current_items)

    @classmethod
    def diff_item_losses(cls, previous_items, current_items) -> tuple[tuple[str, int], ...]:
        changes = cls.summarize_item_count_changes(previous_items, current_items)
        return changes["lost"]

    @classmethod
    def summarize_item_count_changes(cls, previous_items, current_items) -> dict[str, tuple[tuple[str, int], ...]]:
        return formatting.summarize_item_count_changes(previous_items, current_items)

    @classmethod
    def summarize_item_segment_changes(cls, snapshots) -> dict[str, tuple[tuple[str, int], ...]]:
        return formatting.summarize_item_segment_changes(snapshots)

    @classmethod
    def format_snapshot_item_changes_details(cls, previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
        return formatting.format_snapshot_item_changes_details(previous_snapshot, snapshot, segment_snapshots=segment_snapshots)

    @classmethod
    def format_item_gains_by_rarity(
        cls,
        gains: tuple[tuple[str, int], ...],
        *,
        max_items: int | None = None,
    ) -> str:
        return formatting.format_item_gains_by_rarity(gains, max_items=max_items)

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
        return formatting.format_snapshot_compare_summary(base_snapshot, snapshot, base_index=base_index, current_index=current_index, segment_snapshots=segment_snapshots)

    @classmethod
    def format_banishes_rich_text(cls, banishes) -> str:
        return formatting.format_banishes_rich_text(banishes)

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
        return formatting._item_counts(items)

    @classmethod
    def build_stage_summary(cls, snapshots) -> list[dict[str, str]]:
        return formatting.build_stage_summary(snapshots)

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
        return formatting._format_stage_item_rarity_summary(rarity_totals)

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
        return formatting.format_items_rich_text(items)

    @staticmethod
    def _split_item_stack_suffix(item_text: str) -> tuple[str, str]:
        return formatting._split_item_stack_suffix(item_text)

    @staticmethod
    def _normalize_item_name_for_rarity(item_name: str) -> str:
        return formatting._normalize_item_name_for_rarity(item_name)

    @staticmethod
    def _normalize_item_name_for_display(item_name: str) -> str:
        return formatting._normalize_item_name_for_display(item_name)

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
        return formatting.format_chests_per_minute(value)

    @classmethod
    def format_powerups_duration(cls, stats) -> str:
        return formatting.format_powerups_duration(stats)

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
        return formatting.format_seconds_compact(value)

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
        self._ensure_live_snapshot_store().reset_match_metadata()
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
