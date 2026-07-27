"""Panels whose data was already fast and whose paint was not.

Both cases here are the same defect as the run clock in `4168c4a`: a fact read
and folded on a fast task, rendered only by the 10 s `display_player_stats`
payload. Neither fix reads anything new -- the task already holds the value.

- The KPS averages line sits directly under the instant KPS, and both read the
  same `_recent_kills_history`. `set_mob_kills_text` has painted the top one at
  the fast cadence since step 17; the line beneath it was a 10 s reading of the
  same deque.
- The Chaos Tome card is folded by `update_chaos_tome` every fast tick. Because
  the Twitch `!chaos` command reads the tracker at command time, chat could see
  a roll the app's own card had not shown yet.
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest
from unittest.mock import patch

from app import config
from app.refresh_coordinator import RefreshTickContext
from tests.support.refresh_tasks import build_refresh_tasks


def context() -> RefreshTickContext:
    return RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)


def combat_client():
    return type(
        "Client",
        (),
        {
            "resolve_owner_stats": lambda self: 0x1234,
            "get_run_timer": lambda self: 30.0,
            "get_killed_mobs": lambda self: 100,
        },
    )()


def chaos_client():
    return type(
        "Client",
        (),
        {
            "resolve_owner_stats": lambda self: 0x1234,
            "get_chaos_tracking_state": lambda self, owner=None: (37, {}),
        },
    )()


class KpsAveragesRepaintTests(unittest.TestCase):
    def test_the_averages_are_painted_on_the_same_tick_as_the_instant_kps(self) -> None:
        painted: list[str] = []
        service, world = build_refresh_tasks(
            stats_client=combat_client(),
            tab_active=True,
        )
        world.tracker.current_minute_avg_kps = lambda: 90
        world.tracker.current_five_minute_avg_kps = lambda: 75
        world.view.set_kps_averages_text = lambda text: painted.append(text)

        self.assertTrue(service._refresh_combat_metrics_task(context()))

        self.assertEqual(len(painted), 1)
        self.assertIn("90", painted[0])
        self.assertIn("75", painted[0])

    def test_a_scrubbed_timeline_is_not_repainted_over(self) -> None:
        painted: list[str] = []
        service, world = build_refresh_tasks(
            stats_client=combat_client(),
            tab_active=True,
            pinned=True,
        )
        world.view.set_kps_averages_text = lambda text: painted.append(text)

        service._refresh_combat_metrics_task(context())

        self.assertEqual(painted, [])


class InGameOverlayKpsRepaintTests(unittest.TestCase):
    """The same defect one surface over: the value was fast, the paint was not.

    The in-game overlay painted KPS off its own 500 ms `QTimer`, whose phase is
    unrelated to the pass that publishes the value, so the number reached the
    screen up to a whole tick after it existed -- and the lag drifted, because
    the two timers are independent wall-clock timers.
    """

    @staticmethod
    def overlay_config(*, enabled: bool, widget_enabled: bool = True) -> dict:
        return {
            "enabled": enabled,
            "widgets": {"kps": {"enabled": widget_enabled}},
        }

    def test_the_widget_is_repainted_by_the_pass_that_publishes_the_value(self) -> None:
        service, world = build_refresh_tasks(stats_client=combat_client())

        with patch.object(config, "IN_GAME_OVERLAY", self.overlay_config(enabled=True)):
            self.assertTrue(service._refresh_combat_metrics_task(context()))

        self.assertEqual(world.in_game_kps_syncs, [1])

    def test_a_disabled_widget_costs_the_pass_nothing(self) -> None:
        service, world = build_refresh_tasks(stats_client=combat_client())

        with patch.object(
            config, "IN_GAME_OVERLAY", self.overlay_config(enabled=True, widget_enabled=False)
        ):
            self.assertTrue(service._refresh_combat_metrics_task(context()))
        with patch.object(config, "IN_GAME_OVERLAY", self.overlay_config(enabled=False)):
            self.assertTrue(service._refresh_combat_metrics_task(context()))

        self.assertEqual(world.in_game_kps_syncs, [])


class ChaosTomeCardRepaintTests(unittest.TestCase):
    def test_the_card_is_painted_from_the_task_that_folds_the_reading(self) -> None:
        painted: list = []
        service, world = build_refresh_tasks(
            stats_client=chaos_client(),
            tab_active=True,
        )
        world.tracker.chaos_tome_snapshot = lambda: {"level": 37}
        world.view.set_chaos_tome_card = lambda card: painted.append(card)

        self.assertTrue(service._refresh_chaos_tome_task(context()))

        self.assertEqual(painted, [{"level": 37}])

    def test_a_scrubbed_timeline_is_not_repainted_over(self) -> None:
        painted: list = []
        service, world = build_refresh_tasks(
            stats_client=chaos_client(),
            tab_active=True,
            pinned=True,
        )
        world.view.set_chaos_tome_card = lambda card: painted.append(card)

        service._refresh_chaos_tome_task(context())

        self.assertEqual(painted, [])

    def test_a_failed_read_paints_nothing(self) -> None:
        """The card keeps its last good reading rather than being blanked by a
        transient failure -- the 10 s payload still owns the empty state."""
        painted: list = []
        client = type(
            "Client",
            (),
            {
                "resolve_owner_stats": lambda self: 0x1234,
                "get_chaos_tracking_state": lambda self, owner=None: (
                    _ for _ in ()
                ).throw(RuntimeError("chaos read failed")),
            },
        )()
        service, world = build_refresh_tasks(stats_client=client, tab_active=True)
        world.view.set_chaos_tome_card = lambda card: painted.append(card)

        self.assertFalse(service._refresh_chaos_tome_task(context()))

        self.assertEqual(painted, [])


if __name__ == "__main__":
    unittest.main()
