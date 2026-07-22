"""Step 28b: the combat task's ``RUN_TIMER``/``MOB_KILLS`` reads go through
the pass with identical observable output.

docs/updates/architecture_updates/step_28_plan.md section 12.8's 28b: "the
current short-circuit and outer all-or-nothing task behaviour remain for this
slice. Metadata and span are recorded but do not yet reject output." The one
new mechanic this slice must get right is that the pre-existing outer
``except`` no longer double-records health for a failure ``read_memory_source``
already recorded (section 12.5).
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest

from app.read_sources import MOB_KILLS, RUN_TIMER
from app.refresh_coordinator import RefreshTickContext
from infra.memory.reader import MemoryReadError
from tests.support.refresh_tasks import build_refresh_tasks


def _client(*, get_run_timer, get_killed_mobs):
    return type(
        "Client",
        (),
        {
            "resolve_owner_stats": lambda self: 0x1234,
            "get_expected_chest_inputs": lambda self, owner: (7, 3),
            "get_run_timer": lambda self: get_run_timer(),
            "get_killed_mobs": lambda self: get_killed_mobs(),
            "get_chaos_tracking_state": lambda self, owner: (None, {}),
        },
    )()


class CombatPairThroughThePassTests(unittest.TestCase):
    def test_run_timer_and_mob_kills_share_one_pass_id(self) -> None:
        run_timer_reads: list[int] = []
        mob_kill_reads: list[int] = []
        client = _client(
            get_run_timer=lambda: run_timer_reads.append(1) or 21.5,
            get_killed_mobs=lambda: mob_kill_reads.append(1) or 37,
        )
        service, world = build_refresh_tasks(stats_client=client)

        context = RefreshTickContext(pass_id=9, started_at=0.0, clock=lambda: 0.0)
        self.assertTrue(service._refresh_combat_metrics_task(context))

        # Both physical reads actually happened -- not just cached.
        self.assertEqual(run_timer_reads, [1])
        self.assertEqual(mob_kill_reads, [1])

        run_timer_meta = context.metadata_for(RUN_TIMER)
        mob_kills_meta = context.metadata_for(MOB_KILLS)
        self.assertIsNotNone(run_timer_meta)
        self.assertIsNotNone(mob_kills_meta)
        self.assertEqual(run_timer_meta.pass_id, mob_kills_meta.pass_id)
        self.assertEqual(run_timer_meta.pass_id, 9)
        self.assertTrue(run_timer_meta.succeeded)
        self.assertTrue(mob_kills_meta.succeeded)

    def test_a_run_timer_failure_records_health_failure_exactly_once(self) -> None:
        """The regression this slice must avoid: the task's pre-existing
        catch-all used to be the *only* place that recorded a memory failure.
        Routing the read through ``read_memory_source`` must not also record
        it there, or a single physical failure would advance the reconnect
        streak twice -- tampering the ``source_health_recorded`` guard in
        ``refresh_tasks._refresh_combat_metrics_task`` reproduces exactly this
        failure (streak becomes 2, not 1)."""
        client = _client(
            get_run_timer=lambda: (_ for _ in ()).throw(MemoryReadError("run timer unavailable")),
            get_killed_mobs=lambda: 37,
        )
        service, world = build_refresh_tasks(stats_client=client)

        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        result = service._refresh_combat_metrics_task(context)

        self.assertFalse(result)
        self.assertEqual(world.memory._player_stats_memory_error_streak, 1)

    def test_frozen_timer_short_circuit_still_skips_the_mob_kills_read(self) -> None:
        """Byte-identical behaviour with the pre-28b code: unchanged in this
        slice (28c moves the short-circuit into the projection, not here)."""
        run_timer_reads: list[int] = []
        mob_kill_reads: list[int] = []
        tracked_kills: list[tuple] = []
        client = _client(
            get_run_timer=lambda: run_timer_reads.append(1) or 21.5,
            get_killed_mobs=lambda: mob_kill_reads.append(1) or 37,
        )
        service, world = build_refresh_tasks(stats_client=client)
        world.tracker.track_kills = lambda run_timer, mob_kills: tracked_kills.append(
            (run_timer, mob_kills)
        )

        # First tick: no prior game time, so the short-circuit does not fire
        # and both sources are read. Second tick: the same timer value, so the
        # short-circuit fires and `mob_kills` must not be read again.
        self.assertTrue(
            service._refresh_combat_metrics_task(
                RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
            )
        )
        self.assertTrue(
            service._refresh_combat_metrics_task(
                RefreshTickContext(pass_id=2, started_at=0.0, clock=lambda: 0.0)
            )
        )

        self.assertEqual(run_timer_reads, [1, 1])
        self.assertEqual(mob_kill_reads, [1])
        self.assertEqual(tracked_kills, [(21.5, 37)])


if __name__ == "__main__":
    unittest.main()
