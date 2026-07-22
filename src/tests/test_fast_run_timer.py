"""Step 28c commit 1: the tracker's dedicated fast run clock, and the declared
second-order blast radius of ``mob_kills`` moving from ``None`` to ``0``.

Two independent things land here, and step_28_plan.md section 12.8 requires
both to be treated as declared trace surface rather than as untouched
territory:

1. ``LiveRunTracker`` publishes the run clock from every successful RUN_TIMER
   read (section 12.2), so a genuine kills failure withholds only the
   combat/KPS projection and no longer freezes the Stage Summary time.
2. The slow 10 s snapshot's ``mob_kills`` is now ``0`` rather than ``None``
   before the first kill, which reaches ``core/run_summary.build_stage_summary``
   (section 12.9's required differential).
"""
from __future__ import annotations

import src  # noqa: F401

import unittest
from types import SimpleNamespace

from app.read_sources import KPS_GROUP_SPAN_LIMIT_SECONDS, MOB_KILLS, RUN_TIMER
from app.refresh_coordinator import RefreshTickContext
from core.run_summary import build_stage_summary
from core.tracker.live_run import FAST_RUN_TIMER_TTL_SECONDS, LiveRunTracker
from core.tracker.snapshots import LiveRunSnapshot
from infra.memory.reader import MemoryReadError
from tests.support.refresh_tasks import build_refresh_tasks


def _snapshot(game_time, mob_kills, stage_index):
    return SimpleNamespace(
        game_time_seconds=game_time,
        mob_kills=mob_kills,
        stage_index=stage_index,
        items=(),
        items_available=True,
    )


def _live_snapshot(*, game_time_seconds, mob_kills):
    """A stored slow-tick snapshot: what the fast projection is measured against."""
    return LiveRunSnapshot(
        captured_at=0.0,
        stats={},
        game_time_seconds=game_time_seconds,
        mob_kills=mob_kills,
        stage_index=0,
    )


def _sequence(pre_first_kill_value):
    """One run: nothing dies for the opening stretch, then kills accrue.

    ``pre_first_kill_value`` is what the slow snapshot carried for that
    stretch: ``None`` before this slice, ``0`` after it.
    """
    p = pre_first_kill_value
    return [
        _snapshot(0.0, p, 0),
        _snapshot(10.0, p, 0),
        _snapshot(20.0, p, 1),
        _snapshot(30.0, p, 1),
        _snapshot(40.0, 3, 1),
        _snapshot(50.0, 9, 1),
    ]


class StageSummaryNoneToZeroDifferentialTests(unittest.TestCase):
    """Required by section 12.9: drive the same snapshot sequence with ``None``
    and with ``0`` and diff the stage rows, including the first stage's kill
    attribution and ``final_total``.

    **They differ, and the difference is a deliberate correction, not a
    regression.** The declared change, for the sequence above (four
    pre-first-kill snapshots spanning a stage 1 -> stage 2 transition, then
    kills 3 and 9):

        stage 1   old: kills "--"   new: kills "0"
        stage 2   old: kills "6"    new: kills "9"

    The old rows *lost kills*: with a ``None`` baseline the stage 2 row could
    not establish a start count and fell back to the first readable sample (3),
    so the run's first three kills were attributed to no stage at all and the
    stage totals summed to 6 against a true final total of 9. With the baseline
    known to be 0 the totals reconcile exactly. Stage 1 reading "0" rather than
    "--" is likewise the truth: nothing died there.

    This is the direction section 12.8 predicted -- "zero kills *is* the truth
    before the first kill" -- and it is why this is a correction rather than
    stop condition 5a. Note also that the substitution only ever applies where
    the truth *is* zero: a genuine structural read failure still yields
    ``None``, so a late attach mid-run is unaffected.
    """

    def test_the_new_rows_are_the_declared_corrected_rows(self) -> None:
        rows = build_stage_summary(_sequence(0))

        self.assertEqual(rows[0]["kills"], "0")
        self.assertEqual(rows[1]["kills"], "9")

    def test_the_old_rows_are_the_declared_pre_slice_rows(self) -> None:
        """Pins what the change moved away from, so the correction is recorded
        in the suite and not only in a commit message."""
        rows = build_stage_summary(_sequence(None))

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "6")

    def test_only_the_corrected_rows_reconcile_with_the_true_final_total(self) -> None:
        """The substantive claim. Stage kills must sum to the run's final
        total; before the correction they did not."""
        true_final_total = 9

        def total(rows):
            return sum(int(row["kills"]) for row in rows if row["kills"] != "--")

        self.assertEqual(total(build_stage_summary(_sequence(0))), true_final_total)
        self.assertEqual(total(build_stage_summary(_sequence(None))), 6)

    def test_stage_times_are_untouched_by_the_change(self) -> None:
        """The correction is confined to kill attribution: no row's time moves."""
        old_rows = build_stage_summary(_sequence(None))
        new_rows = build_stage_summary(_sequence(0))

        self.assertEqual(
            [row["time"] for row in old_rows], [row["time"] for row in new_rows]
        )

    def test_a_run_where_nothing_ever_dies_reads_zero_not_unknown(self) -> None:
        rows = build_stage_summary([_snapshot(t, 0, 0) for t in (0.0, 10.0, 20.0)])

        self.assertEqual(rows[0]["kills"], "0")


class FastRunTimerTests(unittest.TestCase):
    """Section 12.2: the run clock is published by the timer, not by the kill
    sample. Stop condition 5 fires if the Stage Summary still takes its fast
    clock from ``_recent_kills_history``."""

    def _tracker(self, now):
        return LiveRunTracker(clock=lambda: now[0])

    def test_the_clock_advances_before_the_first_kill_exists(self) -> None:
        now = [100.0]
        tracker = self._tracker(now)

        tracker.update_fast_run_timer(12.5)

        self.assertEqual(tracker._fresh_fast_run_timer_unlocked(), 12.5)
        # And nothing was invented for the kill history (section 12.2).
        self.assertEqual(len(tracker._recent_kills_history), 0)

    def test_a_kills_failure_does_not_freeze_the_clock(self) -> None:
        """The defect this slice closes, at the tracker level: the timer keeps
        advancing across passes where no kill sample is recorded at all."""
        now = [100.0]
        tracker = self._tracker(now)

        tracker.update_fast_run_timer(1.0)
        first = tracker._fresh_fast_run_timer_unlocked()
        now[0] += 0.5
        tracker.update_fast_run_timer(1.5)
        second = tracker._fresh_fast_run_timer_unlocked()

        self.assertEqual((first, second), (1.0, 1.5))
        self.assertEqual(len(tracker._recent_kills_history), 0)

    def test_the_clock_goes_stale_after_its_ttl(self) -> None:
        now = [100.0]
        tracker = self._tracker(now)
        tracker.update_fast_run_timer(1.0)

        now[0] += FAST_RUN_TIMER_TTL_SECONDS + 0.01

        self.assertIsNone(tracker._fresh_fast_run_timer_unlocked())

    def test_a_none_timer_clears_the_clock(self) -> None:
        now = [100.0]
        tracker = self._tracker(now)
        tracker.update_fast_run_timer(1.0)

        tracker.update_fast_run_timer(None)

        self.assertIsNone(tracker._fresh_fast_run_timer_unlocked())

    def test_the_fast_stage_summary_clock_comes_from_the_timer_not_the_kill_history(
        self,
    ) -> None:
        """Stop condition 5, asserted directly on the projection rather than on
        the state behind it.

        With an **empty** kill history the pre-28c code returned ``None`` from
        `_fast_stage_summary_snapshot_unlocked` at its
        ``if self._recent_kills_history:`` guard, which is exactly why the
        Stage Summary card waited for the first kill. Tamper-testing found this
        gap: reverting the projection to read
        ``_recent_kills_history[-1][0]`` passed the whole suite, because every
        other test in this class exercises the timer state directly instead of
        the projection that consumes it.
        """
        now = [100.0]
        tracker = self._tracker(now)
        tracker.update(_live_snapshot(game_time_seconds=10.0, mob_kills=0))

        tracker.update_fast_run_timer(19.0)

        self.assertEqual(len(tracker._recent_kills_history), 0)
        fast = tracker._fast_stage_summary_snapshot_unlocked()
        self.assertIsNotNone(fast)
        self.assertEqual(fast.game_time_seconds, 19.0)

    def test_the_fast_clock_keeps_advancing_across_passes_with_no_kill_samples(
        self,
    ) -> None:
        now = [100.0]
        tracker = self._tracker(now)
        tracker.update(_live_snapshot(game_time_seconds=10.0, mob_kills=0))

        observed = []
        for timer in (11.0, 12.0, 13.0):
            tracker.update_fast_run_timer(timer)
            observed.append(tracker._fast_stage_summary_snapshot_unlocked().game_time_seconds)

        self.assertEqual(observed, [11.0, 12.0, 13.0])
        self.assertEqual(len(tracker._recent_kills_history), 0)

    def test_a_new_run_resets_the_clock(self) -> None:
        now = [100.0]
        tracker = self._tracker(now)
        tracker.update_fast_run_timer(1.0)

        tracker._reset_for_new_run()

        self.assertIsNone(tracker._fresh_fast_run_timer_unlocked())


class CombatTaskIndependentPublicationTests(unittest.TestCase):
    """Section 12.2/12.4 at the task level."""

    def _client(self, *, get_run_timer, get_killed_mobs):
        return type(
            "Client",
            (),
            {
                "resolve_owner_stats": lambda self: 0x1234,
                "get_run_timer": lambda self: get_run_timer(),
                "get_killed_mobs": lambda self: get_killed_mobs(),
            },
        )()

    def _service(self, client):
        service, world = build_refresh_tasks(stats_client=client)
        world.published_timers = []
        world.tracked_kills = []
        world.tracker.update_fast_run_timer = lambda t: world.published_timers.append(t)
        world.tracker.track_kills = lambda t, k: world.tracked_kills.append((t, k))
        return service, world

    def test_a_genuine_kills_failure_publishes_the_timer_and_withholds_kps(self) -> None:
        """A *structural* failure, not the lazy absence of the "kills" entry --
        section 12.1 explicitly supersedes using that absence as a failure
        fixture, because after this slice it is the value zero."""
        service, world = self._service(
            self._client(
                get_run_timer=lambda: 21.5,
                get_killed_mobs=lambda: (_ for _ in ()).throw(
                    MemoryReadError("RunStats static fields are not initialized.")
                ),
            )
        )
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        self.assertFalse(service._refresh_combat_metrics_task(context))

        self.assertEqual(world.published_timers, [21.5])
        self.assertEqual(world.tracked_kills, [])
        # One physical failure, one health record (section 12.5).
        self.assertEqual(world.memory._player_stats_memory_error_streak, 1)

    def test_zero_kills_is_a_normal_accepted_pair(self) -> None:
        service, world = self._service(
            self._client(get_run_timer=lambda: 0.5, get_killed_mobs=lambda: 0)
        )
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        self.assertTrue(service._refresh_combat_metrics_task(context))

        self.assertEqual(world.published_timers, [0.5])
        self.assertEqual(world.tracked_kills, [(0.5, 0)])

    def test_an_excessive_span_withholds_track_kills_but_not_the_timer(self) -> None:
        """Section 12.4: "both successful facts remain published and reusable;
        only track_kills/the KPS projection is withheld for that pass. The
        successful timer still updates the fast Stage Summary clock."""
        service, world = self._service(
            self._client(get_run_timer=lambda: 21.5, get_killed_mobs=lambda: 37)
        )
        # Scripted so the group span exceeds the accepted limit.
        ticks = iter([0.0, 0.0, KPS_GROUP_SPAN_LIMIT_SECONDS * 3] + [10.0] * 20)
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: next(ticks))

        self.assertTrue(service._refresh_combat_metrics_task(context))

        span = service._combat_group_span_seconds(context)
        self.assertGreater(span, KPS_GROUP_SPAN_LIMIT_SECONDS)
        self.assertEqual(world.published_timers, [21.5])
        self.assertEqual(world.tracked_kills, [])

    def test_a_normal_span_accepts_the_pair(self) -> None:
        service, world = self._service(
            self._client(get_run_timer=lambda: 21.5, get_killed_mobs=lambda: 37)
        )
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        self.assertTrue(service._refresh_combat_metrics_task(context))

        span = service._combat_group_span_seconds(context)
        self.assertLessEqual(span, KPS_GROUP_SPAN_LIMIT_SECONDS)
        self.assertEqual(world.tracked_kills, [(21.5, 37)])

    def test_the_span_covers_both_members_of_the_group(self) -> None:
        service, world = self._service(
            self._client(get_run_timer=lambda: 21.5, get_killed_mobs=lambda: 37)
        )
        # Four clock reads land before the group: the PLAYER_STATS_CLIENT
        # collaborator resolves through the same pass and takes a start/finish
        # pair of its own. The group span must cover the *group's* two members
        # and nothing else -- run_timer [1.02, 1.04], mob_kills [1.04, 1.06].
        ticks = iter([1.0, 1.01, 1.02, 1.04, 1.04, 1.06] + [1.06] * 20)
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: next(ticks))

        service._refresh_combat_metrics_task(context)

        run_timer_meta = context.metadata_for(RUN_TIMER)
        mob_kills_meta = context.metadata_for(MOB_KILLS)
        self.assertEqual(run_timer_meta.pass_id, mob_kills_meta.pass_id)
        self.assertEqual(run_timer_meta.started_at, 1.02)
        self.assertEqual(mob_kills_meta.finished_at, 1.06)
        self.assertAlmostEqual(service._combat_group_span_seconds(context), 0.04)


if __name__ == "__main__":
    unittest.main()
