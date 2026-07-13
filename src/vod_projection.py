"""Projection of runtime state into the existing VOD capture contract."""
from __future__ import annotations

from typing import Any

from live_run_tracker import RuntimeStateSnapshot


def build_vod_capture_kwargs(
    runtime: RuntimeStateSnapshot,
    *,
    chaos_tome: Any = None,
) -> dict[str, Any]:
    """Return recorder arguments without UI placeholders or memory reads."""
    snapshot = runtime.latest_snapshot
    if snapshot is None:
        return {}
    chests = runtime.chest_stats
    return {
        "stats": dict(snapshot.stats),
        # A snapshot may intentionally carry the last known good value while
        # its availability flag marks the current memory read as failed.
        "items": snapshot.items,
        "weapons": snapshot.weapons,
        "tomes": snapshot.tomes,
        "banishes": snapshot.banishes,
        "damage_sources": snapshot.damage_sources,
        "chaos_tome": chaos_tome,
        "chests_per_minute": snapshot.chests_per_minute,
        "game_time_seconds": snapshot.game_time_seconds,
        "mob_kills": snapshot.mob_kills,
        "kps_at_capture": runtime.kps["current"],
        "minute_avg_kps_at_capture": runtime.kps["minute_avg"],
        "five_minute_avg_kps_at_capture": runtime.kps["five_minute_avg"],
        "run_avg_kps_at_capture": runtime.kps["run_avg"],
        "player_level": snapshot.player_level,
        "map_seed": snapshot.map_seed,
        "stage_ptr": snapshot.stage_ptr,
        "stage_index": snapshot.stage_index,
        "stage_time_seconds": snapshot.stage_timer_seconds,
        "chests_opened": chests.total_opened,
        "chests_total": snapshot.chests_total,
        "pots_total": snapshot.pots_total,
        "paid_chests": chests.paid,
        "key_procs": chests.key_procs,
        "free_chests": chests.free_chests,
        "keys_count": chests.keys_count,
        "expected_key_procs": (
            chests.expected_key_procs if chests.expected_available else None
        ),
        "chests_opened_by_stage": dict(chests.opened_by_stage),
        "chests_total_by_stage": dict(chests.total_by_stage),
    }
