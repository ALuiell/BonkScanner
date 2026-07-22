"""Step 28c commit 2: the run timer is read once per pass and shared by every
due on-tick consumer.

This is the file that decides stop condition 6 -- "the address-level run-timer
duplicate count does not fall after 28c commit 2". Before this slice three
independent code paths each issued their own physical read of
``0x2f62398+0x20`` on a tick where all three were due:

    app/refresh_tasks.py       the combat task            (RUN_TIMER source)
    app/player_stats_memory.py the 10 s full snapshot     (direct get_run_timer)
    app/player_stats_memory.py the recording lifecycle    (direct get_run_timer)

The count is asserted here dynamically rather than read off a hand-maintained
table in the census, because a static map cannot tell whether the collapse
actually happened -- it only records what someone believed.
"""
from __future__ import annotations

import src  # noqa: F401

import unittest

from app.read_sources import RUN_TIMER
from app.refresh_coordinator import RefreshTickContext
from infra.memory.reader import MemoryReadError
from tests.support.refresh_tasks import build_refresh_tasks


def _client(reads, *, run_timer=21.5, raises=None):
    def get_run_timer():
        reads.append(1)
        if raises is not None:
            raise raises
        return run_timer

    return type(
        "Client",
        (),
        {
            "resolve_owner_stats": lambda self: 0x1234,
            "get_run_timer": lambda self: get_run_timer(),
            "get_killed_mobs": lambda self: 37,
        },
    )()


class RunTimerIsReadOncePerPassTests(unittest.TestCase):
    def _world(self, reads, **kwargs):
        service, world = build_refresh_tasks(stats_client=_client(reads, **kwargs))
        return service, world

    def _drive_all_three_consumers(self, service, world, context):
        """The three on-tick run-timer consumers, driven on one pass."""
        service._refresh_combat_metrics_task(context)
        world.memory._resolve_run_timer(context)  # the full-snapshot path
        world.memory._read_player_stats_recording_run_timer_safe(context)

    def test_three_consumers_on_one_pass_take_one_physical_read(self) -> None:
        reads: list[int] = []
        service, world = self._world(reads)
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        self._drive_all_three_consumers(service, world, context)

        self.assertEqual(len(reads), 1)

    def test_without_a_pass_each_consumer_still_reads_for_itself(self) -> None:
        """The off-tick behaviour, unchanged. This is the number the pass
        collapses, and pinning it is what makes the test above meaningful --
        without it, a client that simply stopped being called would pass."""
        reads: list[int] = []
        service, world = self._world(reads)

        world.memory._resolve_run_timer(None)
        world.memory._read_player_stats_recording_run_timer_safe(None)

        self.assertEqual(len(reads), 2)

    def test_every_consumer_sees_the_same_value(self) -> None:
        reads: list[int] = []
        service, world = self._world(reads, run_timer=42.25)
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        service._refresh_combat_metrics_task(context)

        self.assertEqual(world.memory._resolve_run_timer(context), 42.25)
        self.assertEqual(
            world.memory._read_player_stats_recording_run_timer_safe(context), 42.25
        )
        self.assertEqual(context.metadata_for(RUN_TIMER).pass_id, 1)

    def test_a_cached_failure_is_not_counted_against_memory_health_twice(self) -> None:
        """Section 12.5 / stop condition 3: one physical failure, one streak
        advance, however many consumers receive the cached exception."""
        reads: list[int] = []
        service, world = self._world(reads, raises=MemoryReadError("timer unavailable"))
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        service._refresh_combat_metrics_task(context)
        self.assertIsNone(
            world.memory._read_player_stats_recording_run_timer_safe(context)
        )

        self.assertEqual(len(reads), 1)
        self.assertEqual(world.memory._player_stats_memory_error_streak, 1)

    def test_two_passes_take_two_reads(self) -> None:
        """A pass is a tick: the cache must not outlive it."""
        reads: list[int] = []
        service, world = self._world(reads)

        for pass_id in (1, 2):
            world.memory._resolve_run_timer(
                RefreshTickContext(pass_id=pass_id, started_at=0.0, clock=lambda: 0.0)
            )

        self.assertEqual(len(reads), 2)


class TasksThreadTheContextDownTests(unittest.TestCase):
    """The tests above drive the memory service directly, which proves the
    service *can* share a pass but not that the tasks actually hand it one.

    Tamper-testing found exactly that gap: deleting ``context`` from both task
    call sites left the whole suite green, because every sharing assertion
    entered below the task layer. These two tests close it at the seam the
    tamper broke.
    """

    def test_the_recording_lifecycle_task_hands_its_pass_to_sync_run_state(self) -> None:
        received: list = []
        service, world = build_refresh_tasks(stats_client=_client([]))
        world.capture.sync_run_state = lambda context=None: (
            received.append(context) or "running"
        )
        context = RefreshTickContext(pass_id=7, started_at=0.0, clock=lambda: 0.0)

        service._refresh_recording_lifecycle_task(context)

        self.assertEqual(len(received), 1)
        self.assertIs(received[0], context)

    def test_the_full_snapshot_task_hands_its_pass_to_refresh_now(self) -> None:
        """`full_player_snapshot` is registered as an owner-resolved lambda, so
        the context has to survive `MegabonkApp.refresh_live_player_stats_now`'s
        `**kwargs` hop to reach `PlayerStatsRefresh.refresh_now`."""
        from app.refresh_tasks import ensure_refresh_coordinator

        received: list = []

        class Owner:
            player_stats_client = None
            player_stats_game_data_client = None
            live_run_tracker = None
            overlay_server = None

            def refresh_live_player_stats_now(self, **kwargs):
                received.append(kwargs.get("context", "MISSING"))
                return True

            def _is_live_stats_tab_active(self):
                return False

            def _is_twitch_bot_active(self):
                return False

            def overlay_should_refresh_live_stats(self):
                return False

            def log(self, message, tag=None):
                pass

        owner = Owner()
        coordinator = ensure_refresh_coordinator(owner)
        task = dict(coordinator._tasks)["full_player_snapshot"]
        context = RefreshTickContext(pass_id=11, started_at=0.0, clock=lambda: 0.0)

        task.run(context)

        self.assertEqual(len(received), 1)
        self.assertIs(received[0], context)


if __name__ == "__main__":
    unittest.main()
