from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401

from app import config
from session_stats import SessionStats


class SessionStatsTests(unittest.TestCase):
    def test_snapshot_is_session_owned_and_returned_as_a_defensive_copy(self) -> None:
        tracker = SimpleNamespace(
            tracked_item_rows_for_rules=lambda _rules: [
                {"label": "Kevin", "count": 2, "mode": "all_run"}
            ]
        )
        stats = SessionStats(
            tracker,
            template_stats=lambda: {"template": {"history": [1, 2, 3, 4]}},
            rerolls=lambda: 10,
            snapshot_tracked_item_config=lambda: config.TWITCH_BOT,
        )

        with patch.object(
            config,
            "TWITCH_BOT",
            {"tracked_items_source": "custom", "tracked_items": [{"item_names": ["Kevin"]}]},
        ):
            stats.refresh_snapshot()

        first = stats.snapshot()
        first["tracked_rows"][0]["count"] = 999

        self.assertEqual(stats.snapshot()["rerolls"], 10)
        self.assertEqual(stats.snapshot()["seeds_found"], 4)
        self.assertEqual(stats.snapshot()["tracked_rows"][0]["count"], 2)

    def test_session_rows_are_calculated_without_presentation_concerns(self) -> None:
        tracker = SimpleNamespace(
            tracked_item_rows_for_rules=lambda _rules: [
                {"label": "Kevin", "count": 1, "mode": "map_1_only"}
            ]
        )
        stats = SessionStats(
            tracker,
            template_stats=lambda: {"template": {"history": [1, 2]}},
            rerolls=lambda: 0,
            snapshot_tracked_item_config=lambda: config.TWITCH_BOT,
        )

        with patch.object(
            config,
            "SESSION_TRACKED_ITEMS",
            {"tracked_items": [{"item_names": ["Kevin"], "mode": "map_1_only"}]},
        ):
            rows = stats.session_tracked_item_stat_rows()

        self.assertEqual(rows, [{"label": "Kevin T1", "count": 1, "percent": 50.0}])


if __name__ == "__main__":
    unittest.main()
