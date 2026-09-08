"""Pure Twitch presentation helpers over runtime snapshots."""
from __future__ import annotations

from typing import Any, Callable
from core.stats.weapon_tracker import WEAPON_TRACKER_METRIC_ORDER, calculate_weapon_tracker_rows

from core.luck_rarity import (
    GAME_RARITY_NAMES,
    LUCK_RARITY_ORDER,
    calculate_luck_rarity_probabilities,
    format_expected_count,
    format_luck_rarity_percent,
)


NO_RUN_DATA_MESSAGE = "No run data available yet."
NO_ACTIVE_RUN_MESSAGE = "No active run detected."


def run_fallback_message(
    runtime: Any,
    *,
    live_only: bool = False,
    has_data: bool = False,
) -> str | None:
    """Return the shared Twitch fallback for a run-backed command.

    A completed run deliberately keeps its last snapshot so summary commands
    can still answer. Fast readers may also publish useful data before that
    first full snapshot; callers report that through ``has_data``. Live-only
    commands cannot use a frozen completed frame: KPS and powerups must say that
    there is no active run instead.
    """
    if getattr(runtime, "latest_snapshot", None) is None and not has_data:
        return NO_RUN_DATA_MESSAGE
    if not live_only:
        return None

    lifecycle = getattr(runtime, "lifecycle", None)
    lifecycle_value = str(getattr(lifecycle, "value", lifecycle) or "").casefold()
    status = str(getattr(runtime, "status", "") or "").casefold()
    if lifecycle_value == "completed" or status == "no_game":
        return NO_ACTIVE_RUN_MESSAGE
    return None


def truncate_chat_message(text: str) -> str:
    return text[:447] + "..." if len(text) > 450 else text


def format_effective_weapons(snapshot) -> str:
    rows = calculate_weapon_tracker_rows(
        snapshot.weapons, snapshot.stats, WEAPON_TRACKER_METRIC_ORDER,
    )
    parts = [
        f"{row.name} Lv{row.level} [" + ", ".join(
            f"{metric.label}: {metric.display_value}" for metric in row.metrics
        ) + "]"
        for row in rows
    ]
    return truncate_chat_message(
        "Weapons with global stats: " + (" | ".join(parts) or "Unavailable")
    )


def format_powerups(powerups: Any, *, include_left_word: bool = True) -> str:
    durations_text = None
    if (
        powerups.standard_duration_seconds is not None
        and powerups.clock_duration_seconds is not None
    ):
        durations_text = (
            "Durations: "
            f"standard {int(round(powerups.standard_duration_seconds))}s, "
            f"clock {int(round(powerups.clock_duration_seconds))}s"
        )

    if powerups.active:
        suffix = " left" if include_left_word else ""
        parts = []
        for effect in powerups.active:
            remaining = f"({int(round(effect.remaining_seconds))}s{suffix})"
            if effect.pickup_ui is None or effect.expires_ui is None:
                parts.append(f"{effect.name} {remaining}")
            else:
                parts.append(
                    f"{effect.name} {effect.pickup_ui} -> {effect.expires_ui} {remaining}"
                )
        if durations_text is not None:
            parts.append(durations_text)
        return " | ".join(parts)

    if durations_text is None:
        return "none active"
    return f"none active | {durations_text}"


def format_luck(
    runtime: Any,
    format_template: Callable[..., str],
) -> str:
    """The `!luck` line: each tier's current chance, and what it has produced.

    Two halves, and only the second one can go missing. During a live run the
    chance uses the freshest Luck reading; after completion it falls back to the
    value in the retained final snapshot. That keeps the last-run summary whole.
    A late attach can still leave the totals unmeasurable, and when it does the
    actual and expected halves *drop out* rather than being filled with `--`. A
    shorter line reads as a shorter answer; a line of dashes reads as a fault.
    (`!chests` keeps its own `Expected: --` for the opposite reason: there the
    value sits inside one whole message, where a gap would look like something
    broke.)

    Rarity names are the game's, not ours -- see `GAME_RARITY_NAMES`. No
    abbreviations: the full line runs ~120 characters against a 500-character
    limit, so shortening buys nothing and costs readability.
    """
    loot = getattr(runtime, "loot_stats", None)
    luck = getattr(runtime, "luck", None)
    if luck is None:
        snapshot = getattr(runtime, "latest_snapshot", None)
        stats = getattr(snapshot, "stats", None) if snapshot is not None else None
        stat = stats.get("Luck") if stats else None
        luck = getattr(stat, "value", None)
    probabilities = calculate_luck_rarity_probabilities(luck)
    measurable = bool(getattr(loot, "available", False))

    parts: list[str] = []
    for tier in LUCK_RARITY_ORDER:
        chance = format_luck_rarity_percent(probabilities.get(tier))
        name = GAME_RARITY_NAMES[tier]
        if not measurable:
            parts.append(f"{name} {chance}")
            continue
        actual = int(loot.actual.get(tier, 0))
        expected = format_expected_count(loot.expected.get(tier))
        parts.append(f"{name} {chance} - {actual} (exp {expected})")

    return format_template("luck", "Luck: {tiers}", tiers=" | ".join(parts))


def format_kps(
    runtime: Any,
    format_template: Callable[..., str],
) -> str:
    kps_values = getattr(runtime, "kps", None) or {}
    kps = kps_values.get("current")
    fallback = run_fallback_message(
        runtime,
        live_only=True,
        has_data=kps is not None,
    )
    if fallback is not None:
        return fallback
    if kps is None:
        return "Not enough data yet to calculate Kills Per Second."
    minute = kps_values.get("minute_avg")
    five_minute = kps_values.get("five_minute_avg")
    run = kps_values.get("run_avg")
    return format_template(
        "kps",
        "KPS: {kps} | 60s Avg: {minute_avg} | 5m Avg: {five_minute_avg} | Run Avg: {run_avg}",
        kps=f"{kps:,}/s",
        minute_avg="--" if minute is None else f"{minute:,}/s",
        five_minute_avg="--" if five_minute is None else f"{five_minute:,}/s",
        run_avg="--" if run is None else f"{run:,}/s",
    )
