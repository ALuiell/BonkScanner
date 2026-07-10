"""Pure Twitch presentation helpers over runtime snapshots."""
from __future__ import annotations

from typing import Any, Callable


def truncate_chat_message(text: str) -> str:
    return text[:447] + "..." if len(text) > 450 else text


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
