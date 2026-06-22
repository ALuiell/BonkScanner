from __future__ import annotations

import html

from gui_styles import (
    COLOR_MAP,
    ITEM_RARITY_BY_NAME,
    ITEM_RARITY_COLOR_MAP,
    PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS,
    PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS,
    PLAYER_STATS_STAGE4_GHOST_ENTRY_MAX_SECONDS,
    PLAYER_STATS_STAGE4_GHOST_TIMER_SECONDS,
    PLAYER_STATS_STAGE4_RESET_WINDOW_SECONDS,
    PLAYER_STATS_STAGE4_TIMER_JUMP_SECONDS,
    PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS,
)
from item_metadata import (
    normalize_item_name_for_display,
    normalize_item_name_for_rarity,
)


def default_stage_summary_rows() -> list[dict[str, str]]:
    return [
        {
            "label": f"Stage {index}",
            "kills": "--",
            "time": "--",
            "items": "--",
        }
        for index in range(1, 5)
    ]


def format_elapsed_time(seconds: float | int) -> str:
    minutes, seconds = divmod(max(int(seconds), 0), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_count(value: int | float) -> str:
    return f"{max(0, int(value)):,}"


def split_item_stack_suffix(item_text: str) -> tuple[str, str]:
    if not item_text:
        return "", ""
    name, separator, suffix = item_text.rpartition(" x")
    if separator and suffix.isdigit():
        return name, f"{separator}{suffix}"
    return item_text, ""


def item_counts(items) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items or ():
        name, suffix = split_item_stack_suffix(str(item))
        name = normalize_item_name_for_display(name)
        count = 1
        if suffix.startswith(" x") and suffix[2:].isdigit():
            count = int(suffix[2:])
        counts[name] = counts.get(name, 0) + max(1, count)
    return counts


def empty_item_rarity_totals() -> dict[str, int]:
    return {
        "LEGENDARY": 0,
        "RARE": 0,
        "UNCOMMON": 0,
        "COMMON": 0,
    }


def create_stage_item_gain_tracker(items) -> dict[str, dict[str, int]]:
    return {
        "confirmed_counts": item_counts(items),
        "pending_drop_streaks": {},
    }


def update_stage_item_gain_tracker(tracker: dict[str, dict[str, int]], items) -> dict[str, int]:
    confirmed_counts = tracker.setdefault("confirmed_counts", {})
    pending_drop_streaks = tracker.setdefault("pending_drop_streaks", {})
    current_counts = item_counts(items)
    rarity_gains = empty_item_rarity_totals()

    for name in set(confirmed_counts) | set(current_counts) | set(pending_drop_streaks):
        current_count = current_counts.get(name, 0)
        confirmed_count = confirmed_counts.get(name, 0)
        if current_count >= confirmed_count:
            pending_drop_streaks.pop(name, None)
            gain = current_count - confirmed_count
            if gain > 0:
                rarity_name = normalize_item_name_for_rarity(name)
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


def format_stage_item_rarity_summary(rarity_totals: dict[str, int]) -> str:
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


def build_stage_summary(snapshots) -> list[dict[str, str]]:
    rows = default_stage_summary_rows()
    if not snapshots:
        return rows

    stage_buckets: dict[int, list[object]] = {index: [] for index in range(1, 5)}
    stage_item_gains: dict[int, dict[str, int]] = {
        index: empty_item_rarity_totals() for index in range(1, 5)
    }
    stage_kill_baselines: dict[int, int] = {1: 0}
    last_known_mob_kills: int | None = None
    current_stage_index = resolve_initial_stage_index(snapshots[0])
    item_gain_tracker = None
    previous_snapshot = None
    for snapshot in snapshots:
        snapshot_mob_kills = getattr(snapshot, "mob_kills", None)
        if item_gain_tracker is None:
            item_gain_tracker = create_stage_item_gain_tracker(getattr(snapshot, "items", ()))
        if previous_snapshot is not None:
            previous_stage_index = current_stage_index
            next_stage_index = resolve_next_stage_index(
                current_stage_index,
                previous_snapshot,
                snapshot,
            )
            current_stage_index = min(max(next_stage_index, current_stage_index), 4)
            if (
                current_stage_index > previous_stage_index
                and is_stage_transition_boundary_snapshot(snapshot)
            ):
                stage_buckets[previous_stage_index].append(snapshot)
            if current_stage_index > previous_stage_index:
                baseline = getattr(snapshot, "mob_kills", None)
                if baseline is None:
                    baseline = last_known_mob_kills
                if baseline is not None:
                    stage_kill_baselines[current_stage_index] = max(0, int(baseline))
            item_gains = update_stage_item_gain_tracker(
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
            duration_text = format_elapsed_time(max(0.0, end_run_time - start_run_time))

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
            kills_text = format_count(int(last_kills) - int(first_kills))

        items_text = format_stage_item_rarity_summary(stage_item_gains[stage_index])
        rows[stage_index - 1] = {
            "label": f"Stage {stage_index}",
            "kills": kills_text,
            "time": duration_text,
            "items": items_text,
            "item_rarities": dict(stage_item_gains[stage_index]),
        }

    reconcile_stage_summary_kills(rows, snapshots)
    return rows


def reconcile_stage_summary_kills(rows: list[dict[str, str]], snapshots) -> None:
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
    first_known_index = None
    for index, count in enumerate(parsed_counts):
        if count is not None:
            first_known_index = index
            break
    if first_known_index is not None and first_known_index > 0:
        return
    last_index = None
    for index, count in enumerate(parsed_counts):
        if count is not None:
            last_index = index
    if last_index is None:
        return
    updated_total = max(0, int(parsed_counts[last_index] or 0) + delta)
    rows[last_index]["kills"] = format_count(updated_total)


def resolve_next_stage_index(current_stage_index: int, previous_snapshot, snapshot) -> int:
    raw_stage_number = raw_stage_index_to_stage_number(getattr(snapshot, "stage_index", None))
    if current_stage_index < 4 and raw_stage_number is not None:
        current_stage_index = raw_stage_number
    if current_stage_index == 3 and looks_like_stage_four_from_map_activity(snapshot):
        return 4

    previous_stage_ptr = int(getattr(previous_snapshot, "stage_ptr", 0) or 0)
    current_stage_ptr = int(getattr(snapshot, "stage_ptr", 0) or 0)
    previous_seed = getattr(previous_snapshot, "map_seed", None)
    current_seed = getattr(snapshot, "map_seed", None)
    if (
        current_stage_index < 3
        and raw_stage_number is None
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

    if current_stage_index == 3 and looks_like_stage_four_transition(previous_snapshot, snapshot):
        return 4
    return current_stage_index


def resolve_initial_stage_index(snapshot) -> int:
    raw_stage_number = raw_stage_index_to_stage_number(getattr(snapshot, "stage_index", None))
    if raw_stage_number == 3 and looks_like_stage_four_from_map_activity(snapshot):
        return 4
    if raw_stage_number is not None:
        return raw_stage_number
    return 1


def raw_stage_index_to_stage_number(raw_stage_index) -> int | None:
    try:
        raw_value = int(raw_stage_index)
    except (TypeError, ValueError):
        return None
    if 0 <= raw_value <= 2:
        return raw_value + 1
    return None


def looks_like_stage_four_from_map_activity(snapshot) -> bool:
    raw_stage_number = raw_stage_index_to_stage_number(getattr(snapshot, "stage_index", None))
    if raw_stage_number != 3:
        return False
    chest_total = _coerce_positive_int(getattr(snapshot, "chests_total", None))
    if chest_total is not None and chest_total < 46:
        return True
    pots_total = _coerce_positive_int(getattr(snapshot, "pots_total", None))
    return pots_total is not None and pots_total < 55


def _coerce_positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def is_stage_transition_boundary_snapshot(snapshot) -> bool:
    stage_time = getattr(snapshot, "stage_time_seconds", None)
    if stage_time is None:
        return False
    return 0.0 <= float(stage_time) <= PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS


def looks_like_stage_four_transition(previous_snapshot, snapshot) -> bool:
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
        and previous_stage_time > PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS
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
