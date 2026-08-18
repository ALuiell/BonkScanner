"""Presentation-neutral serialization of evaluated Build Progression state."""
from __future__ import annotations

from typing import Any

from core.build_progression import (
    BuildProgressionSnapshot,
    RequirementStatus,
    format_clock,
)
from core.item_metadata import (
    ITEM_RARITY_BY_NAME,
    ITEM_RARITY_COLOR_MAP,
    normalize_item_name_for_rarity,
)
from core.stat_labels import abbreviate_stat_label


SECTION_KINDS = ("item", "stat", "progress")


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
            for kind in SECTION_KINDS
            for row in incomplete
            if row.kind.value == kind
        ]
        completed = [
            row
            for kind in SECTION_KINDS
            for row in completed
            if row.kind.value == kind
        ]
    shown_incomplete = incomplete[:max_rows]
    if show_headings:
        shown = [
            row
            for kind in SECTION_KINDS
            for row in (shown_incomplete + (completed if show_completed else []))
            if row.kind.value == kind
        ]
    else:
        shown = shown_incomplete + (completed if show_completed else [])

    rows = []
    for row in shown:
        progress_hint = _progress_hint(row)
        rows.append(
            {
                "id": row.id,
                "kind": row.kind.value,
                "label": (
                    abbreviate_stat_label(row.target)
                    if row.kind.value == "stat"
                    else row.target
                ),
                "value": f"{row.current_display}/{row.required_display}",
                "status": row.status.value,
                "symbol": row.symbol,
                "time": (row.deadline_label or progress_hint) if show_time else "",
                "label_color": (
                    _item_rarity_color(row.target)
                    if row.kind.value == "item"
                    else ("#93C5FD" if row.kind.value == "stat" else "#5EEAD4")
                ),
                "late": row.late,
                "cap_unresolved": row.cap_unresolved,
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
        "late_complete": snapshot.late_complete,
        "completion_time": format_clock(snapshot.completion_time_seconds),
        "rows": rows,
        "hidden_completed": hidden_completed,
        "hidden_remaining": hidden_remaining,
        "show_section_headings": show_headings,
    }


def _progress_hint(row) -> str:
    if row.status is RequirementStatus.SATISFIED:
        if row.cap_tracking or row.max_required is not None:
            return ""
        return "NO DEADLINE" if not row.deadline_label else ""
    if row.min_met and row.cap_tracking:
        return "CAP ACTIVE"
    if row.min_met and row.max_required is not None:
        # The stat editor calls the second target "Ideal", but overlays only
        # replace the numeric target after Min is reached; they do not expose
        # either internal/semantic label.
        return "TO MAX" if row.kind.value == "item" else ""
    return "NO DEADLINE" if not row.deadline_label else ""


def _item_rarity_color(item_name: str) -> str:
    canonical_name = normalize_item_name_for_rarity(item_name)
    rarity = ITEM_RARITY_BY_NAME.get(canonical_name)
    return ITEM_RARITY_COLOR_MAP.get(rarity, "#E5E7EB")


def format_twitch_build(
    snapshot: BuildProgressionSnapshot, *, max_chars: int = 430
) -> dict[str, str]:
    if not snapshot.configured:
        return {
            "name": "Build Progression",
            "progress": "not configured",
            "requirements": "Build not configured",
            "failed_requirements": "",
            "late_requirements": "",
            "completed_requirements": "",
            "remaining_suffix": "",
            "completion_time": "--:--",
        }
    if snapshot.complete:
        prefix = "! BUILD COMPLETE" if snapshot.late_complete else "BUILD COMPLETE"
        return {
            "name": snapshot.name,
            "progress": f"{prefix} · {format_clock(snapshot.completion_time_seconds)}",
            "requirements": "",
            "failed_requirements": "",
            "late_requirements": "",
            "completed_requirements": "",
            "remaining_suffix": "",
            "completion_time": format_clock(snapshot.completion_time_seconds),
        }

    late = [row for row in snapshot.rows if row.late]
    incomplete = [
        row
        for row in snapshot.rows
        if row.status not in {RequirementStatus.SATISFIED, RequirementStatus.OVERDUE}
        and not row.late
    ]
    failed = [
        row for row in snapshot.rows
        if row.status is RequirementStatus.OVERDUE and not row.late
    ]
    completed = [
        row for row in snapshot.rows
        if row.status is RequirementStatus.SATISFIED and not row.late
    ]

    def chunk(row) -> str:
        value = f"{row.current_display}/{row.required_display}"
        label = abbreviate_stat_label(row.target) if row.kind.value == "stat" else row.target
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

    active_groups = []
    if incomplete:
        active_groups.append(("REMAINING: ", incomplete, "requirements"))
    if failed:
        active_groups.append(("FAILED: ", failed, "failed_requirements"))
    if late:
        active_groups.append(("LATE: ", late, "late_requirements"))

    formatted: dict[str, str] = {
        "requirements": "",
        "failed_requirements": "",
        "late_requirements": "",
    }
    current_limit = max_chars
    for idx, (prefix, rows, key) in enumerate(active_groups):
        remaining_reserve = sum(
            len(p) + len("+999 more") + len(" | ")
            for p, _r, _k in active_groups[idx + 1 :]
        )
        group_limit = max(1, current_limit - remaining_reserve)
        res = bounded(prefix, rows, limit=group_limit)
        formatted[key] = res
        current_limit = max(1, current_limit - len(res) - len(" | "))

    return {
        "name": snapshot.name,
        "progress": f"{snapshot.completed}/{snapshot.total}",
        "requirements": formatted["requirements"],
        "failed_requirements": formatted["failed_requirements"],
        "late_requirements": formatted["late_requirements"],
        "completed_requirements": bounded("COMPLETED: ", completed),
        "remaining_suffix": "",
        "completion_time": "--:--",
    }


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
