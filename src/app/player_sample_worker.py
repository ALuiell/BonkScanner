"""Read complete player samples without using the fast lane's memory handles."""

from concurrent.futures import ThreadPoolExecutor

from app.player_stats_memory import PlayerStatsMemory
from app.snapshot_store import LiveSnapshotStore
from infra.memory.reader import MemoryReadError


class PlayerSampleWorker:
    def __init__(self, *, map_transition_recovery_grace=lambda: False):
        self._stats = self._game_data = self._disabled_items = None
        self._refresh_disabled = True
        self._include_optional = False
        store = LiveSnapshotStore()
        self._memory = PlayerStatsMemory(
            read_stats_client=lambda: self._stats,
            write_stats_client=lambda value: setattr(self, "_stats", value),
            read_game_data_client=lambda: self._game_data,
            write_game_data_client=lambda value: setattr(self, "_game_data", value),
            snapshot_store=lambda: store,
            recording_active=lambda: self._include_optional,
            live_stats_tab_active=lambda: False,
            twitch_bot_active=lambda: False,
            overlay_refresh_wanted=lambda: False,
            read_disabled_items_cache=lambda: self._disabled_items,
            write_disabled_items_cache=lambda value: setattr(self, "_disabled_items", value),
            read_disabled_items_refresh_pending=lambda: self._refresh_disabled,
            write_disabled_items_refresh_pending=lambda value: setattr(self, "_refresh_disabled", value),
            map_transition_recovery_grace=map_transition_recovery_grace,
        )
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="player-sample")
        self._closing = None

    def submit(self, include_optional, active_run):
        return self._executor.submit(self._read, include_optional, active_run)

    def _read(self, include_optional, active_run):
        self._include_optional = include_optional
        try:
            sample = self._memory.read_full_sample()
        except Exception as exc:
            self._memory.record_memory_failure(exc)
            raise
        self._memory.record_memory_success()
        try:
            activity = self._memory.read_map_activity_values() or {}
            if not activity and active_run:
                raise MemoryReadError("Map activity unavailable during an active run.")
        except Exception as exc:
            self._memory.record_game_data_source_failure("map_activity", exc)
            activity = {}
        else:
            self._memory.record_game_data_source_success("map_activity")
        return sample, activity

    def begin_close(self):
        if self._closing is None:
            self._closing = self._executor.submit(self._close_handles)
            self._executor.shutdown(wait=False)
        return self._closing

    def _close_handles(self):
        self._memory.close_player_stats_client()
        self._memory.close_player_stats_game_data_client()
