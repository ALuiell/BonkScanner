"""Pure Twitch presentation helpers over runtime snapshots."""
from __future__ import annotations

from typing import Any, Callable

from core.luck_rarity import (
    GAME_RARITY_NAMES,
    LUCK_RARITY_ORDER,
    calculate_luck_rarity_probabilities,
    format_expected_count,
    format_luck_rarity_percent,
)


def truncate_chat_message(text: str) -> str:
    return text[:447] + "..." if len(text) > 450 else text


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

    Two halves, and only the second one can go missing. The chance depends on
    nothing but the Luck the player holds right now, so it survives a late
    attach that leaves the totals unmeasurable -- and when it does, the actual
    and expected halves *drop out* rather than being filled with `--`. A shorter
    line reads as a shorter answer; a line of dashes reads as a fault. (`!chests`
    keeps its own `Expected: --` for the opposite reason: there the value sits
    inside one whole message, where a gap would look like something broke.)

    Rarity names are the game's, not ours -- see `GAME_RARITY_NAMES`. No
    abbreviations: the full line runs ~120 characters against a 500-character
    limit, so shortening buys nothing and costs readability.
    """
    loot = getattr(runtime, "loot_stats", None)
    probabilities = calculate_luck_rarity_probabilities(getattr(runtime, "luck", None))
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
    if runtime.status == "no_game":
        return "Kills Per Second is not available because no run is active."
    kps = runtime.kps["current"]
    if kps is None:
        return "Not enough data yet to calculate Kills Per Second."
    minute = runtime.kps["minute_avg"]
    five_minute = runtime.kps["five_minute_avg"]
    run = runtime.kps["run_avg"]
    return format_template(
        "kps",
        "KPS: {kps} | 60s Avg: {minute_avg} | 5m Avg: {five_minute_avg} | Run Avg: {run_avg}",
        kps=f"{kps:,}/s",
        minute_avg="--" if minute is None else f"{minute:,}/s",
        five_minute_avg="--" if five_minute is None else f"{five_minute:,}/s",
        run_avg="--" if run is None else f"{run:,}/s",
    )
