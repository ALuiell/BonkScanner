"""Pure Twitch presentation helpers over runtime snapshots."""
from __future__ import annotations

from typing import Any, Callable


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
