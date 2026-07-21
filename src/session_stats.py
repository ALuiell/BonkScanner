"""Session-wide statistics shared by UI and integrations.

This read model is deliberately independent of OBS, the in-game overlay and
Twitch.  Scanner updates refresh its immutable snapshot; consumers can render
that data for their own medium without owning the underlying session state.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from app import config
from projections.tracked_items import tracked_item_command_label
from tracked_item_rules import tracked_item_rules_from_config


class SessionStats:
    def __init__(
        self,
        tracker: Any,
        *,
        template_stats: Callable[[], dict[str, Any]],
        rerolls: Callable[[], int],
        snapshot_tracked_item_config: Callable[[], dict[str, Any]],
    ) -> None:
        self._tracker = tracker
        self._template_stats = template_stats
        self._rerolls = rerolls
        self._snapshot_tracked_item_config = snapshot_tracked_item_config
        self._snapshot: dict[str, Any] = {
            "rerolls": 0,
            "seeds_found": 0,
            "tracked_rows": (),
        }
        self._snapshot_lock = threading.Lock()

    def found_seed_count(self) -> int:
        count = 0
        for data in self._template_stats().values():
            if not isinstance(data, dict):
                continue
            history = data.get("history")
            if isinstance(history, (list, tuple)):
                count += len(history)
        return count

    def tracked_item_stat_rows(self, rule_config: dict[str, Any]) -> list[dict[str, Any]]:
        rules = tracked_item_rules_from_config(rule_config)
        rows = self._tracker.tracked_item_rows_for_rules(rules)
        seed_count = self.found_seed_count()
        formatted_rows: list[dict[str, Any]] = []
        for row in rows:
            count = int(row.get("count") or 0)
            formatted_rows.append(
                {
                    "label": tracked_item_command_label(row),
                    "count": count,
                    "percent": (count / seed_count * 100.0) if seed_count > 0 else None,
                }
            )
        return formatted_rows

    def session_tracked_item_stat_rows(self) -> list[dict[str, Any]]:
        return self.tracked_item_stat_rows(config.SESSION_TRACKED_ITEMS)

    def refresh_snapshot(self) -> None:
        snapshot = {
            "rerolls": max(0, int(self._rerolls() or 0)),
            "seeds_found": max(0, int(self.found_seed_count())),
            "tracked_rows": tuple(
                dict(row)
                for row in self.tracked_item_stat_rows(
                    self._snapshot_tracked_item_config()
                )
            ),
        }
        with self._snapshot_lock:
            self._snapshot = snapshot

    def snapshot(self) -> dict[str, Any]:
        with self._snapshot_lock:
            snapshot = dict(self._snapshot)
            snapshot["tracked_rows"] = tuple(
                dict(row) for row in snapshot.get("tracked_rows", ())
            )
            return snapshot
