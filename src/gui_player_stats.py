from __future__ import annotations

from math import isfinite
import time

from app import config
from core.game_state import MapStat, RuntimeGameMode, RuntimeGameState
from infra.memory.game_data_client import GameDataClient
from gui_shared import _set_text
from gui_styles import (
    ITEM_RARITY_BY_NAME,
    ITEM_SORT_DEFAULT,
    ITEM_SORT_RARITY_ASC,
    ITEM_SORT_RARITY_DESC,
    PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS,
    PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS,
    PLAYER_STATS_STAGE4_GHOST_ENTRY_MAX_SECONDS,
    PLAYER_STATS_STAGE4_GHOST_TIMER_SECONDS,
    PLAYER_STATS_STAGE4_RESET_WINDOW_SECONDS,
    PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS,
    PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS,
    PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS,
)
from infra.memory.reader import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from live_run_tracker import (
    LiveRunSnapshot,
    LiveRunTracker,
    PowerupMapContext,
)
from core.stats.types import DamageSourceSnapshot, TomeSnapshot, WeaponSnapshot, calculate_chests_per_minute
from infra.memory.player_stats_client import PlayerStatsClient
from app.refresh_tasks import (
    PLAYER_STATS_MEMORY_ERROR_RECONNECT_THRESHOLD,
    ensure_refresh_coordinator,
    overlay_widget_refresh_active,
    record_player_stats_memory_failure,
    record_player_stats_memory_success,
)
from app.snapshot_store import LiveSnapshotStore
from projections.vod import build_vod_capture_kwargs
from projections import formatting

CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS = 1.0



class PlayerStatsMixin:
    def _ensure_live_snapshot_store(self) -> LiveSnapshotStore:
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            return coordinator.snapshot_store
        # No coordinator means an app double built without __init__. Constructing
        # one here would bind an overlay HTTP port, so those keep a bare store.
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
        """The per-tick body of the fast refresh loop.

        The loop itself -- the interval, the is-active gate, and the ``after``
        thread hop that reschedules it -- is owned by
        ``AppCoordinator.start_refresh_loop`` (step 12a). This method is only the
        work done on each tick. Every cadence still lives in a registered task's
        ``interval_ms``, not here: this only ticks. Recording lifecycle work that
        used to sit in a second 10 s timer is the ``recording_lifecycle`` task.
        """
        if self._is_shutting_down:
            return
        self._refresh_core_run_lifecycle_state()
        ensure_refresh_coordinator(self).tick()

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


    # Owned by AppCoordinator (step 12b). These properties delegate to it, with a
    # __dict__ fallback so app doubles built with object.__new__ (no coordinator)
    # keep working: a test that sets app.player_stats_client = <fake> round-trips
    # through _player_stats_client with zero test changes.
    @property
    def player_stats_client(self):
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            return coordinator.player_stats_client
        return self.__dict__.get("_player_stats_client")

    @player_stats_client.setter
    def player_stats_client(self, value) -> None:
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            coordinator.player_stats_client = value
        else:
            self.__dict__["_player_stats_client"] = value

    @property
    def player_stats_game_data_client(self):
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            return coordinator.player_stats_game_data_client
        return self.__dict__.get("_player_stats_game_data_client")

    @player_stats_game_data_client.setter
    def player_stats_game_data_client(self, value) -> None:
        coordinator = self.__dict__.get("coordinator")
        if coordinator is not None:
            coordinator.player_stats_game_data_client = value
        else:
            self.__dict__["_player_stats_game_data_client"] = value

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
                stage_index=runtime_state.current_stage_index,
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
            stage_index = state.stage_index if state is not None else None
            run_time_seconds = self._read_player_stats_recording_run_timer_safe()
            runtime_state = self._runtime_game_state_or_unknown()
            if runtime_state.mode is RuntimeGameMode.IN_GAME:
                vod_path = self._start_player_stats_recording(
                    seed=seed,
                    stage_ptr=stage_ptr,
                    stage_index=stage_index,
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
    def _stage_index_signals_new_run(
        previous_index: int | None,
        current_index: int | None,
        previous_run_time_seconds: float | None,
        current_run_time_seconds: float | None,
    ) -> bool | None:
        """Decide "same run" vs. "new run" from stage_index direction.

        stage_index is a MapController static-field ordinal that survives the
        loading screen, unlike the run timer this replaced (step 8b): a failed
        timer read used to be treated as "different run" and split a recording
        on an ordinary map transition.

        Returns True to split, False to continue the current recording, or
        None when the index could not be read this tick -- the caller must not
        decide from that, only wait for the next sample.
        """
        if current_index is None:
            return None
        if previous_index is None:
            # No baseline yet (the index was unreadable when this recording
            # started). Adopt it without splitting; there is nothing to compare.
            return False
        if current_index > previous_index:
            return False  # map transition within the same run (e.g. 1 -> 2 -> 3)
        if current_index < previous_index:
            return True  # index reset -- a new run started
        # Unchanged. Live-verified (Graveyard, and the virtual stage-4 boss
        # room): this game never changes stage_ptr or seed without stage_index
        # also moving, except when a new run starts at the same index a
        # finished run held (typically 0). The run timer resetting confirms
        # that case. Missing timer data must not manufacture a split -- that is
        # exactly the failure this guard replaces -- so treat it as "continue".
        if current_run_time_seconds is None or previous_run_time_seconds is None:
            return False
        return (
            current_run_time_seconds + PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS
            < previous_run_time_seconds
        )

    def _start_player_stats_recording(
        self,
        *,
        seed: int | None = None,
        stage_ptr: int = 0,
        stage_index: int | None = None,
        run_time_seconds: float | None = None,
    ):
        vod_path = self.player_stats_vod_recorder.start(seed=seed)
        self.player_stats_vod_snapshots = []
        self.player_stats_selected_snapshot_index = None
        self.player_stats_recording_seed = seed
        self.player_stats_recording_stage_ptr = stage_ptr
        self.player_stats_recording_stage_index = stage_index
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
        self.player_stats_recording_stage_index = None
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
        # Reuses the lifecycle state the 500 ms driver already refreshes once a
        # second, rather than issuing its own uncached get_runtime_game_state().
        # At this task's old 10 s cadence that extra heavy read was affordable;
        # at 1 s it would be ten times a second, for a mode the cheaper cached
        # reader computes identically (verified exhaustively -- the extra
        # `and not is_game_over` in get_runtime_game_state is unreachable).
        # Only `.mode` is used here, which is all the cached state carries.
        runtime_state = self._runtime_state_for_refresh()
        if runtime_state.mode is RuntimeGameMode.GAME_OVER:
            self._player_stats_completed_run = True
            mark_completed = getattr(self.live_run_tracker, "mark_run_completed", None)
            if callable(mark_completed):
                mark_completed()
        if runtime_state.mode is RuntimeGameMode.IN_GAME:
            self._player_stats_completed_run = False
            was_paused = self.player_stats_recording_waiting_mode == RuntimeGameMode.PAUSED_IN_GAME.value
            self.player_stats_recording_waiting_mode = None
            if was_paused and self.player_stats_vod_recorder.is_recording:
                self.refresh_player_stats_timeline_ui()
                if self._is_live_stats_tab_active():
                    _set_text(self.player_stats_status_label, "Live player stats (recording)")
            if self._is_player_stats_recording_armed() and not self.player_stats_vod_recorder.is_recording:
                current_state = self._read_player_stats_recording_state_safe()
                current_seed = current_state.map_seed if current_state is not None else None
                current_stage_ptr = (
                    current_state.current_stage_ptr if current_state is not None else 0
                )
                current_stage_index = (
                    getattr(current_state, "stage_index", None) if current_state is not None else None
                )
                current_run_time_seconds = self._read_player_stats_recording_run_timer_safe()
                vod_path = self._start_player_stats_recording(
                    seed=current_seed,
                    stage_ptr=current_stage_ptr,
                    stage_index=current_stage_index,
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
            was_paused = self.player_stats_recording_waiting_mode == runtime_state.mode.value
            self.player_stats_recording_waiting_mode = runtime_state.mode.value
            if not was_paused:
                self.refresh_player_stats_timeline_ui()
                if self._is_live_stats_tab_active():
                    _set_text(self.player_stats_status_label, "Live player stats (recording paused)")
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
        current_stage_index = (
            getattr(current_state, "stage_index", None) if current_state is not None else None
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
            self.player_stats_recording_stage_index = current_stage_index
        if (
            current_seed == self.player_stats_recording_seed
            and current_stage_ptr == self.player_stats_recording_stage_ptr
        ):
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        previous_seed = self.player_stats_recording_seed
        previous_run_time_seconds = self.player_stats_recording_run_time_seconds
        decision = self._stage_index_signals_new_run(
            self.player_stats_recording_stage_index,
            current_stage_index,
            previous_run_time_seconds,
            current_run_time_seconds,
        )
        if decision is None:
            # stage_index unreadable this tick. Absence of data is not an
            # answer -- the bug this guard replaces -- so wait for the next
            # sample instead of deciding from it.
            return None
        if not decision:
            self.player_stats_recording_seed = current_seed
            self.player_stats_recording_stage_ptr = current_stage_ptr
            self.player_stats_recording_stage_index = current_stage_index
            self.player_stats_recording_run_time_seconds = current_run_time_seconds
            return None

        self._stop_player_stats_recording(refresh_live_stats=False)
        vod_path = self._start_player_stats_recording(
            seed=current_seed,
            stage_ptr=current_stage_ptr,
            stage_index=current_stage_index,
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
        stage_index: int | None = None,
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
            stage_index=stage_index,
            run_time_seconds=run_timer_seconds,
        )
        self.log(f"[*] Player stats recording auto-started: {vod_path.name}", tag="success")
        return True












































































    @classmethod
    def _item_total_count(cls, items) -> int:
        return sum(cls._item_counts(items).values())

    @classmethod
    def _empty_item_rarity_totals(cls) -> dict[str, int]:
        return formatting._empty_item_rarity_totals()

    @classmethod
    def format_items_rarity_summary_rich_text(cls, items) -> str:
        return formatting.format_items_rarity_summary_rich_text(items)

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



    def close_player_stats_client(self):
        # The instance is owned by the coordinator now (step 12b); reach it through
        # the property rather than __dict__, which no longer holds it.
        player_stats_client = self.player_stats_client
        if player_stats_client:
            try:
                player_stats_client.close()
            except Exception:
                pass
            self.player_stats_client = None
        self._ensure_live_snapshot_store().reset_match_metadata()
        self._player_stats_memory_error_streak = 0

    def close_player_stats_game_data_client(self):
        game_data_client = self.player_stats_game_data_client
        if game_data_client:
            try:
                game_data_client.close()
            except Exception:
                pass
            self.player_stats_game_data_client = None
        self._player_stats_game_data_memory_error_streak = 0


