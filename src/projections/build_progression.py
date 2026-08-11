"""Presentation-neutral serialization of evaluated Build Progression state."""
from __future__ import annotations

from typing import Any

from core.build_progression import (
    BuildProgressionSnapshot,
    RequirementStatus,
    format_clock,
)


def build_progression_payload(
    snapshot: BuildProgressionSnapshot | None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    if snapshot is None:
        return {"configured": False, "available": False, "rows": []}
    max_rows = max(1, min(_int(options.get("max_rows"), 6), 20))
    show_completed = bool(options.get("show_completed", False))
    show_time = bool(options.get("show_target_time", True))
    visible = [
        row
        for row in snapshot.rows
        if show_completed or row.status is not RequirementStatus.SATISFIED
    ]
    show_headings = bool(options.get("show_section_headings", False))
    if show_headings:
        visible = [row for kind in ("item", "stat") for row in visible if row.kind.value == kind]
    shown = visible[:max_rows]
    rows = []
    for row in shown:
        value = f"{row.current_display}/{row.required_display}"
        if row.ideal_display is not None:
            value += f" · ideal {row.ideal_display}"
        time_text = ""
        if show_time:
            if row.time_delta_seconds is not None:
                if row.time_delta_seconds < 0:
                    time_text = f"+{format_clock(abs(row.time_delta_seconds))}"
                elif row.status is RequirementStatus.WARNING:
                    time_text = format_clock(row.time_delta_seconds)
                else:
                    time_text = row.deadline_label
            else:
                time_text = row.deadline_label
        rows.append(
            {
                "id": row.id,
                "kind": row.kind.value,
                "label": row.target,
                "value": value,
                "priority": row.priority.value,
                "status": row.status.value,
                "symbol": row.symbol,
                "time": time_text,
            }
        )
    hidden_completed = sum(
        row.status is RequirementStatus.SATISFIED for row in snapshot.rows
    ) if not show_completed else 0
    hidden_remaining = sum(
        row.status is not RequirementStatus.SATISFIED for row in visible[max_rows:]
    )
    return {
        "configured": snapshot.configured,
        "available": snapshot.available,
        "name": snapshot.name,
        "progress": f"{snapshot.completed}/{snapshot.total}",
        "run_time": format_clock(snapshot.run_time_seconds),
        "complete": snapshot.complete,
        "completion_time": format_clock(snapshot.completion_time_seconds),
        "rows": rows,
        "hidden_completed": hidden_completed,
        "hidden_remaining": hidden_remaining,
        "show_section_headings": show_headings,
    }


def format_twitch_build(snapshot: BuildProgressionSnapshot, *, max_rows: int = 2) -> dict[str, str]:
    if not snapshot.configured:
        return {
            "name": "Build Progression",
            "progress": "not configured",
            "requirements": "Build not configured",
            "remaining_suffix": "",
            "completion_time": "--:--",
        }
    if snapshot.complete:
        return {
            "name": snapshot.name,
            "progress": f"BUILD COMPLETE · {format_clock(snapshot.completion_time_seconds)}",
            "requirements": "",
            "remaining_suffix": "",
            "completion_time": format_clock(snapshot.completion_time_seconds),
        }
    incomplete = [
        row for row in snapshot.rows if row.status is not RequirementStatus.SATISFIED
    ]
    chunks = []
    for row in incomplete[:max_rows]:
        value = f"{row.current_display}/{row.required_display}"
        timing = row.deadline_label
        if row.time_delta_seconds is not None and row.time_delta_seconds < 0:
            timing = f"+{format_clock(abs(row.time_delta_seconds))}"
        chunks.append(
            " ".join(part for part in (row.symbol, row.target, value, f"· {timing}" if timing else "") if part)
        )
    remaining = max(0, len(incomplete) - len(chunks))
    return {
        "name": snapshot.name,
        "progress": f"{snapshot.completed}/{snapshot.total}",
        "requirements": f" | {' | '.join(chunks)}" if chunks else "",
        "remaining_suffix": f" | +{remaining} remaining" if remaining else "",
        "completion_time": "--:--",
    }


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
