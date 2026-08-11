"""Presentation-neutral serialization of evaluated Build Progression state."""
from __future__ import annotations

from typing import Any

from core.build_progression import (
    BuildProgressionSnapshot,
    RequirementStatus,
    format_clock,
)
from core.item_metadata import item_display_color
from core.stat_labels import abbreviate_stat_label


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
    incomplete = [
        row
        for row in snapshot.rows
        if row.status is not RequirementStatus.SATISFIED
    ]
    completed = [
        row
        for row in snapshot.rows
        if row.status is RequirementStatus.SATISFIED
    ]
    show_headings = bool(options.get("show_section_headings", True))
    if show_headings:
        incomplete = [
            row
            for kind in ("item", "stat")
            for row in incomplete
            if row.kind.value == kind
        ]
        completed = [
            row
            for kind in ("item", "stat")
            for row in completed
            if row.kind.value == kind
        ]
    shown_incomplete = incomplete[:max_rows]
    # Completed rows are an explicit opt-in group below the useful live rows.
    # Applying the same cap to the combined list made the checkbox appear broken:
    # remaining/failed rows filled every slot before a completed row could reach
    # the renderer. The cap therefore governs only the always-visible group.
    shown = shown_incomplete + (completed if show_completed else [])
    rows = []
    for row in shown:
        value = f"{row.current_display}/{row.required_display}"
        time_text = ""
        if show_time:
            # Always show the configured target. Runtime state is already
            # conveyed by symbol and colour; changing this cell into a
            # countdown or lateness timer makes the deadline itself disappear.
            time_text = row.deadline_label
        rows.append(
            {
                "id": row.id,
                "kind": row.kind.value,
                # The editor deliberately keeps the readable full name. Every
                # live surface is space-constrained, so stats use the exact
                # compact vocabulary of the regular Stats widget instead.
                "label": (
                    abbreviate_stat_label(row.target)
                    if row.kind.value == "stat"
                    else row.target
                ),
                "value": value,
                "status": row.status.value,
                "symbol": row.symbol,
                "time": time_text,
                "label_color": (
                    item_display_color(row.target) or "#E5E7EB"
                    if row.kind.value == "item"
                    else "#93C5FD"
                ),
            }
        )
    hidden_completed = 0 if show_completed else len(completed)
    hidden_remaining = max(0, len(incomplete) - len(shown_incomplete))
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


def format_twitch_build(snapshot: BuildProgressionSnapshot, *, max_chars: int = 430) -> dict[str, str]:
    if not snapshot.configured:
        return {
            "name": "Build Progression",
            "progress": "not configured",
            "requirements": "Build not configured",
            "failed_requirements": "",
            "completed_requirements": "",
            "remaining_suffix": "",
            "completion_time": "--:--",
        }
    if snapshot.complete:
        return {
            "name": snapshot.name,
            "progress": f"BUILD COMPLETE · {format_clock(snapshot.completion_time_seconds)}",
            "requirements": "",
            "failed_requirements": "",
            "completed_requirements": "",
            "remaining_suffix": "",
            "completion_time": format_clock(snapshot.completion_time_seconds),
        }
    incomplete = [
        row
        for row in snapshot.rows
        if row.status not in {RequirementStatus.SATISFIED, RequirementStatus.OVERDUE}
    ]
    failed = [row for row in snapshot.rows if row.status is RequirementStatus.OVERDUE]
    completed = [row for row in snapshot.rows if row.status is RequirementStatus.SATISFIED]

    def chunk(row) -> str:
        value = f"{row.current_display}/{row.required_display}"
        label = (
            abbreviate_stat_label(row.target)
            if row.kind.value == "stat"
            else row.target
        )
        return " ".join(
            part for part in (row.symbol, label, value, row.deadline_label) if part
        )

    def bounded(prefix: str, rows, *, limit: int = max_chars) -> str:
        chunks: list[str] = []
        for index, row in enumerate(rows):
            candidate = " | ".join((*chunks, chunk(row)))
            remaining = len(rows) - index - 1
            suffix = f" | +{remaining} more" if remaining else ""
            if len(prefix) + len(candidate) + len(suffix) > limit:
                break
            chunks.append(chunk(row))
        hidden = max(0, len(rows) - len(chunks))
        body = " | ".join(chunks)
        if hidden:
            body = f"{body} | +{hidden} more" if body else f"+{hidden} more"
        return f"{prefix}{body}" if body else ""

    if incomplete and failed:
        failed_reserve = len("FAILED: +999 more") + len(" | ")
        requirements = bounded(
            "REMAINING: ",
            incomplete,
            limit=max(1, max_chars - failed_reserve),
        )
        failed_requirements = bounded(
            "FAILED: ",
            failed,
            limit=max(1, max_chars - len(requirements) - len(" | ")),
        )
    else:
        requirements = bounded("REMAINING: ", incomplete)
        failed_requirements = bounded("FAILED: ", failed)
    completed_requirements = bounded("COMPLETED: ", completed)
    return {
        "name": snapshot.name,
        "progress": f"{snapshot.completed}/{snapshot.total}",
        "requirements": requirements,
        "failed_requirements": failed_requirements,
        "completed_requirements": completed_requirements,
        "remaining_suffix": "",
        "completion_time": "--:--",
    }


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
