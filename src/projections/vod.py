"""Projection of runtime state into the existing VOD capture contract."""
from __future__ import annotations

from typing import Any

from core.tracker.snapshots import RuntimeStateSnapshot


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
    loot = runtime.loot_stats
    fast_stage = runtime.fast_stage_timer
    use_fast_stage = bool(
        fast_stage is not None
        and float(fast_stage.captured_at) >= float(snapshot.captured_at)
    )
    observed_run_times = tuple(
        float(value)
        for value in (snapshot.game_time_seconds, runtime.run_timer_seconds)
        if value is not None
    )
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
        "shrines": runtime.shrines,
        "character_passive": runtime.character_passive,
        "chests_per_minute": snapshot.chests_per_minute,
        "game_time_seconds": max(observed_run_times) if observed_run_times else None,
        "mob_kills": (
            runtime.mob_kills
            if runtime.mob_kills is not None
            else snapshot.mob_kills
        ),
        "kps_at_capture": runtime.kps["current"],
        "minute_avg_kps_at_capture": runtime.kps["minute_avg"],
        "five_minute_avg_kps_at_capture": runtime.kps["five_minute_avg"],
        "run_avg_kps_at_capture": runtime.kps["run_avg"],
        "player_level": snapshot.player_level,
        "map_seed": snapshot.map_seed,
        "stage_ptr": snapshot.stage_ptr,
        "stage_index": (
            fast_stage.stage_index
            if use_fast_stage and fast_stage.stage_index is not None
            else snapshot.stage_index
        ),
        "stage_time_seconds": (
            fast_stage.stage_timer_seconds
            if use_fast_stage and fast_stage.stage_timer_seconds is not None
            else snapshot.stage_timer_seconds
        ),
        "chests_opened": chests.total_opened,
        "chests_total": snapshot.chests_total,
        "pots_total": snapshot.pots_total,
        "paid_chests": chests.paid,
        "key_procs": chests.key_procs,
        "free_chests": chests.free_chests,
        "keys_count": chests.keys_count,
        "expected_key_procs": (
            chests.expected_key_procs if chests.expected_complete else None
        ),
        "chests_opened_by_stage": dict(chests.opened_by_stage),
        "chests_total_by_stage": dict(chests.total_by_stage),
        # Only when the run is measurable. An unmeasurable one records nothing
        # rather than zeros, which is the same thing an older file says: "not
        # recorded". A zero would claim the run gained no items of that tier.
        "loot_actual": dict(loot.actual) if loot.available else None,
        "loot_expected": dict(loot.expected) if loot.available else None,
    }
