"""Pure presentation helpers for session-wide statistics."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def format_tracked_item_rows_for_stats_tab(
    rows: Iterable[Mapping[str, Any]],
) -> str:
    parts = []
    for row in rows:
        percent = row.get("percent")
        if percent is None:
            parts.append(f"{row['label']}: {row['count']}")
        else:
            parts.append(f"{row['label']}: {row['count']} ({percent:.2f}%)")
    return " | ".join(parts)
