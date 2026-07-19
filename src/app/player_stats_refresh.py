"""The player-stats refresh orchestration -- the fast-tick body, the demand
predicates that decide whether a refresh is owed, and
``refresh_live_player_stats_now``, the seam that turns one memory read into a
tracker update and a UI render.

Split out of ``PlayerStatsMixin`` in step 14c, alongside
``app/player_stats_memory.py``; the two moved together because the twelve
``PlayerStatsMixin._record_player_stats_game_data_memory_*`` class-qualified
call sites span both, and a qualified call left pointing at a class its target
has left is a silent ``AttributeError`` (see the Chaos Tome regression fixed
earlier in this step).

**Known debt, carried not deepened:** ``refresh_live_player_stats_now`` still
calls seven UI methods through the shared ``self`` --
``display_player_stats``, ``display_player_stats_snapshot``,
``refresh_player_stats_timeline_ui``, ``_refresh_vods_list_if_visible``,
``mark_overlay_read_failed``, ``refresh_session_tracked_item_stats_ui`` and
``update_overlay_state_from_tracker``. That is the same Qt leak step 6 carried
into ``app/refresh_tasks.py``, and inverting it into callbacks (the step-10d
pattern) is the next commit, deliberately kept separate from this relocation.

``ModuleNotFoundError`` is ``infra.memory.reader``'s, not the builtin. It
shadows it, and the ``except`` clauses depend on that.
"""
from __future__ import annotations

import time

from app import config
from app.player_stats_memory import PlayerStatsMemoryMixin
from app.player_stats_view import (
    overlay_view,
    player_stats_view,
    recordings_list_view,
)
from app.refresh_tasks import (
    ensure_refresh_coordinator,
    overlay_widget_refresh_active,
    record_player_stats_memory_failure,
    record_player_stats_memory_success,
)
from core.game_state import MapStat, RuntimeGameMode, RuntimeGameState
from infra.memory.game_data_client import GameDataClient
from infra.memory.reader import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from live_run_tracker import LiveRunSnapshot, PowerupMapContext
from projections.vod import build_vod_capture_kwargs
from projections import formatting

def player_stats_snapshot_is_pinned(owner) -> bool:
    """Has the user scrubbed the Live Stats timeline to a specific snapshot?

    Before this predicate, every live refresh tick ran
    ``player_stats_selected_snapshot_index = None`` and repainted live values,
    unconditionally. Dragging the slider mid-recording therefore showed the
    chosen snapshot for exactly one tick before the Run Summary and stage
    summary cards reverted to the live run -- reported from a live drive on
    2026-07-19, and present long before the step-18 pilot that made the path
    easy to exercise.

    A module-level function rather than a method: this is a decision the app
    layer makes about its own state, and ``MegabonkApp``'s MRO does not need
    another name in it.

    The range check is what stops a stale pin from freezing the view. If the
    snapshot list is emptied (recording stops, a new run starts) the pin cannot
    be honoured even if the flag were missed, so the display falls back to live
    rather than sticking.
    """
    if not getattr(owner, "player_stats_snapshot_pinned", False):
        return False
    index = getattr(owner, "player_stats_selected_snapshot_index", None)
    if index is None:
        return False
    snapshots = getattr(owner, "player_stats_vod_snapshots", None) or ()
    return 0 <= index < len(snapshots)


# The cadence at which the core run-lifecycle probe re-reads runtime state.
# gui_styles.py's PLAYER_STATS_* comment refers to this value by name.
CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS = 1.0


class PlayerStatsRefreshMixin:
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

    def _overlay_requires_player_snapshot(self) -> bool:
        return any(
            overlay_widget_refresh_active(self, widget_id)
            for widget_id in ("stage_summary", "tracked_items", "stats", "banishes")
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
                overlay_view(self).mark_overlay_read_failed(no_game=False)
            except Exception:
                pass
            return False
        except Exception as exc:
            record_player_stats_memory_failure(self, exc)
            try:
                overlay_view(self).mark_overlay_read_failed(no_game=False)
            except Exception:
                pass
            return False

        record_player_stats_memory_success(self)

        chests_per_minute = formatting.calculate_player_chests_per_minute(stats)
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
            merge_fn=formatting.merge_banish_appearance_order,
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
            PlayerStatsMemoryMixin._record_player_stats_game_data_memory_success(self)
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
            PlayerStatsMemoryMixin._record_player_stats_game_data_memory_failure(self, exc)
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

        view = player_stats_view(self)
        overlay = overlay_view(self)
        if hasattr(overlay, "refresh_session_tracked_item_stats_ui"):
            overlay.refresh_session_tracked_item_stats_ui()
        chaos_snapshot_reader = getattr(self.live_run_tracker, "chaos_tome_snapshot", None)
        chaos_tome_snapshot = chaos_snapshot_reader() if callable(chaos_snapshot_reader) else None
        overlay.update_overlay_state_from_tracker()
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
            pinned = player_stats_snapshot_is_pinned(self)
            self.player_stats_vod_snapshots.append(snapshot)
            if not pinned:
                self.player_stats_selected_snapshot_index = len(self.player_stats_vod_snapshots) - 1
            view.refresh_player_stats_timeline_ui()
            recordings_list_view(self)._refresh_vods_list_if_visible()
            if is_live_tab_active and not pinned:
                view.display_player_stats_snapshot(snapshot, items_text=items_text)
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
            if player_stats_snapshot_is_pinned(self):
                # The user scrubbed the timeline to a specific snapshot. Leave
                # their reading on screen instead of repainting live values over
                # it one tick later. Unpinning is `_select_snapshot` returning to
                # the newest snapshot, or the recording stopping.
                return True
            self.player_stats_selected_snapshot_index = None
            view.display_player_stats(
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
