"""Passive items on the fast lane, and the stage boundary that closes on them.

Two changes, one mechanism. `tracked_items` used to cost a full
`PLAYER_STATS_REFRESH_MS` *plus* a confirmation tick, because
`items.process_item_deltas` credits a raised count only on the next read that
agrees -- 10--20 s end to end for the OBS overlay, Session Stats and the Twitch
commands. Reading `PASSIVE_ITEMS` on a 1 s task collapses that to ~1--2 s.

Having a fresh inventory then makes the fast stage boundary carry one. That
boundary already existed (`_fast_stage_boundaries`, committed by
`update_fast_stage_timer` with a 2-sample confirmation) and already fed
`build_stage_summary`; it simply had `items_available=False` because nothing on
the fast lane could supply an inventory. With one, it becomes the closing
observation a stage needs to keep its own pickups.
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest
from types import SimpleNamespace

from app.read_sources import PASSIVE_ITEMS
from app.refresh_coordinator import RefreshTickContext
from app.refresh_tasks import PASSIVE_ITEMS_REFRESH_MS
from core import run_summary
from core.tracker.live_run import (
    FAST_ITEMS_TTL_SECONDS,
    LiveRunSnapshot,
    LiveRunTracker,
    TrackedItemRule,
)
from core.stats.types import InvalidItemStackCountError
from infra.memory.reader import MemoryReadError
from tests.support.refresh_tasks import build_refresh_tasks


ANVIL_RULE = TrackedItemRule(
    id="anvils_total",
    label="Anvils",
    item_names=("Anvil",),
    mode="all_run",
)


def snapshot(
    *,
    time_seconds: float,
    items=(),
    map_seed: int = 100,
    stage_ptr: int = 1000,
    stage_index: int | None = None,
    stage_time_seconds: float | None = None,
    mob_kills: int | None = None,
) -> LiveRunSnapshot:
    return LiveRunSnapshot(
        captured_at=time_seconds,
        stats={},
        items=tuple(items),
        game_time_seconds=time_seconds,
        stage_time_seconds=(
            stage_time_seconds if stage_time_seconds is not None else time_seconds
        ),
        mob_kills=mob_kills,
        map_seed=map_seed,
        stage_ptr=stage_ptr,
        stage_index=stage_index,
    )


def tracker_with_baseline(*, clock=None) -> LiveRunTracker:
    """A tracker mid-run with an established item baseline.

    The fast lane deliberately refuses to seed a run: `update_items` returns
    early until the slow path has published a snapshot, because
    `process_item_deltas`' first call installs the initial-inventory candidates
    and racing it there would attribute a run's starting items to nothing.
    """
    tracker = LiveRunTracker(
        tracked_item_rules=(ANVIL_RULE,),
        clock=clock or (lambda: 1000.0),
    )
    tracker.update(snapshot(time_seconds=100.0, items=("Wrench x1",)))
    tracker.update(snapshot(time_seconds=110.0, items=("Wrench x1",)))
    return tracker


def anvils(tracker: LiveRunTracker) -> int:
    return next(
        int(row["count"])
        for row in tracker.tracked_item_rows()
        if row["id"] == "anvils_total"
    )


class FastLaneItemDeltaTests(unittest.TestCase):
    def test_a_pickup_is_credited_after_one_confirming_fast_read(self) -> None:
        """The confirmation ladder is kept, not bypassed. It costs one *fast*
        tick now instead of one 10 s snapshot, and a shorter window between the
        two reads makes it stricter rather than weaker."""
        tracker = tracker_with_baseline()

        tracker.update_items(("Wrench x1", "Anvil x1"))
        self.assertEqual(anvils(tracker), 0)  # seen once, not yet confirmed

        tracker.update_items(("Wrench x1", "Anvil x1"))
        self.assertEqual(anvils(tracker), 1)

    def test_a_level_up_on_an_existing_entry_is_credited(self) -> None:
        tracker = tracker_with_baseline()
        tracker.update_items(("Wrench x1", "Anvil x1"))
        tracker.update_items(("Wrench x1", "Anvil x1"))

        tracker.update_items(("Wrench x1", "Anvil x3"))
        tracker.update_items(("Wrench x1", "Anvil x3"))

        self.assertEqual(anvils(tracker), 3)

    def test_a_transiently_empty_dictionary_does_not_discard_a_pending_gain(self) -> None:
        """The game exposes an empty inventory dictionary for a single read
        while it rebuilds it in place. Credited, that empty read would drop
        `current_count` below the confirmed count and silently discard the
        pending increase -- the same failure `LiveSnapshotStore.merge_items`
        exists to prevent on the slow path."""
        tracker = tracker_with_baseline()
        tracker.update_items(("Wrench x1", "Anvil x1"))

        self.assertFalse(tracker.update_items(()))

        tracker.update_items(("Wrench x1", "Anvil x1"))
        self.assertEqual(anvils(tracker), 1)

    def test_items_are_not_credited_across_a_run_boundary(self) -> None:
        """New-match detection and `reset_for_new_match` live on the 10 s path.
        Between a new run actually starting and the slow path noticing, the
        newest stored snapshot still belongs to the *previous* run, so a fast
        read of the new run's starting inventory would be diffed against the old
        run's counts."""
        tracker = tracker_with_baseline()
        # The run clock going backwards is the same signal
        # `_should_reset_for_snapshot` uses; the fast lane defers to it rather
        # than deciding run identity itself.
        tracker.update_fast_run_timer(3.0)

        self.assertFalse(tracker.update_items(("Anvil x1",)))
        self.assertFalse(tracker.update_items(("Anvil x1",)))
        self.assertEqual(anvils(tracker), 0)

    def test_the_fast_lane_does_not_seed_a_run_without_a_slow_snapshot(self) -> None:
        tracker = LiveRunTracker(tracked_item_rules=(ANVIL_RULE,), clock=lambda: 1000.0)

        self.assertFalse(tracker.update_items(("Anvil x1",)))
        self.assertEqual(len(tracker.snapshots), 0)

    def test_the_fast_pass_does_not_append_to_the_snapshot_deque(self) -> None:
        """`update_items` is not `update()`. Appending here would give the
        Stage Summary fold, the recordings timeline and VOD capture a stream of
        1 s frames built from a 10 s snapshot's stale stats."""
        tracker = tracker_with_baseline()
        before = len(tracker.snapshots)

        tracker.update_items(("Wrench x1", "Anvil x1"))
        tracker.update_items(("Wrench x1", "Anvil x1"))

        self.assertEqual(len(tracker.snapshots), before)


class FastLaneTaskTests(unittest.TestCase):
    def _client(self, get_passive_items):
        return type(
            "Client",
            (),
            {
                "resolve_owner_stats": lambda self: 0x1234,
                "get_passive_items": lambda self, owner=None: get_passive_items(),
            },
        )()

    def test_the_task_forwards_the_inventory_to_the_narrow_tracker_entry_point(self) -> None:
        seen: list[tuple] = []
        service, world = build_refresh_tasks(
            stats_client=self._client(lambda: ("Anvil x1",))
        )
        world.tracker.update_items = lambda items: seen.append(items) or True

        result = service._refresh_passive_items_task(
            RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        )

        self.assertTrue(result)
        self.assertEqual(seen, [("Anvil x1",)])

    def test_the_full_snapshot_and_the_fast_task_share_one_physical_read(self) -> None:
        """The point of resolving through the named `PASSIVE_ITEMS` key. On a
        pass where both are due, the item dictionary is walked **once**.
        Asserted on the shared source key, not on wall-clock timing."""
        reads: list[int] = []
        service, world = build_refresh_tasks(
            stats_client=self._client(lambda: reads.append(1) or ("Anvil x1",))
        )
        context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

        # The full snapshot's own entry point, the one `refresh_now` uses.
        world.memory.read_passive_items_only(0x1234, context)
        service._refresh_passive_items_task(context)

        self.assertEqual(reads, [1])
        self.assertIsNotNone(context.metadata_for(PASSIVE_ITEMS))

    def test_the_items_panel_is_repainted_on_the_live_tab(self) -> None:
        """The panel renders exactly what this task already holds, so keeping it
        fresh costs no read. It was the last surface still waiting for the 10 s
        `display_player_stats` payload."""
        painted: list[tuple] = []
        service, world = build_refresh_tasks(
            stats_client=self._client(lambda: ("Anvil x1",)),
            tab_active=True,
        )
        world.view.set_items = lambda items: painted.append(items)

        service._refresh_passive_items_task(
            RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        )

        self.assertEqual(painted, [("Anvil x1",)])

    def test_a_scrubbed_timeline_is_not_repainted_over(self) -> None:
        """The guard the two fast stage-summary writes were missing in
        `9c59abd`: at a fast cadence an unguarded write repaints live values
        over the snapshot the user scrubbed to, about once a second."""
        painted: list[tuple] = []
        service, world = build_refresh_tasks(
            stats_client=self._client(lambda: ("Anvil x1",)),
            tab_active=True,
            pinned=True,
        )
        world.view.set_items = lambda items: painted.append(items)

        service._refresh_passive_items_task(
            RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        )

        self.assertEqual(painted, [])

    def test_a_skipped_pass_leaves_the_last_good_reading_on_screen(self) -> None:
        """A transiently empty dictionary must not blank the panel. The tracker
        reports the pass as not applied and the repaint is skipped with it."""
        painted: list[tuple] = []
        service, world = build_refresh_tasks(
            stats_client=self._client(lambda: ()),
            tab_active=True,
        )
        world.tracker.update_items = lambda _items: False
        world.view.set_items = lambda items: painted.append(items)

        service._refresh_passive_items_task(
            RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        )

        self.assertEqual(painted, [])

    def test_the_session_stats_panel_is_refreshed_from_the_same_pass(self) -> None:
        """Session Stats is one of the three surfaces this change exists for,
        and its panel was repainted only by `refresh_now` on the 10 s path.

        Unconditional, matching that caller: the panel lives on a different tab
        from Live Stats, so the Live Stats guards are not the right gate."""
        service, world = build_refresh_tasks(
            stats_client=self._client(lambda: ("Anvil x1",))
        )

        service._refresh_passive_items_task(
            RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        )

        self.assertEqual(len(world.session_tracked_item_refreshes), 1)

    def test_the_overlay_is_republished_for_the_tracked_items_widget(self) -> None:
        """The fast tasks republished the overlay only for `kps` and
        `stage_summary`. An overlay running Tracked Items with Stage Summary
        switched off therefore fell back to the 10 s cadence -- exactly the
        surface the fast lane was built for."""
        service, world = build_refresh_tasks(
            stats_client=self._client(lambda: ("Anvil x1",)),
            widget_refresh_active=lambda widget_id: widget_id == "tracked_items",
        )

        service._refresh_passive_items_task(
            RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        )

        self.assertEqual(len(world.overlay_syncs), 1)

    def test_no_overlay_republish_without_the_widget(self) -> None:
        service, world = build_refresh_tasks(
            stats_client=self._client(lambda: ("Anvil x1",)),
            widget_refresh_active=False,
        )

        service._refresh_passive_items_task(
            RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        )

        self.assertEqual(world.overlay_syncs, [])

    def test_a_skipped_pass_publishes_nothing(self) -> None:
        """Nothing changed, so no consumer is told anything did."""
        service, world = build_refresh_tasks(
            stats_client=self._client(lambda: ()),
            widget_refresh_active=lambda widget_id: widget_id == "tracked_items",
        )
        world.tracker.update_items = lambda _items: False

        service._refresh_passive_items_task(
            RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        )

        self.assertEqual(world.overlay_syncs, [])
        self.assertEqual(world.session_tracked_item_refreshes, [])

    def test_a_read_failure_leaves_the_reconnect_streak_to_the_full_snapshot(self) -> None:
        """Memory health for `PASSIVE_ITEMS` belongs to the primary consumer.
        A second consumer recording its own failure would advance the streak
        twice for what may be a single physical read."""
        service, world = build_refresh_tasks(
            stats_client=self._client(
                lambda: (_ for _ in ()).throw(MemoryReadError("inventory unavailable"))
            )
        )

        result = service._refresh_passive_items_task(
            RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
        )

        self.assertFalse(result)
        self.assertEqual(world.memory._player_stats_memory_error_streak, 0)

    def test_an_invalid_item_stack_count_is_contained(self) -> None:
        service, world = build_refresh_tasks(
            stats_client=self._client(
                lambda: (_ for _ in ()).throw(InvalidItemStackCountError("torn read"))
            )
        )
        world.tracker.update_items = lambda _items: self.fail(
            "a failed read must not reach the tracker"
        )

        self.assertFalse(
            service._refresh_passive_items_task(
                RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)
            )
        )

    def test_the_task_is_registered_on_its_own_cadence(self) -> None:
        """Tamper guard. Every assertion above drives the task body directly, so
        deleting the registration would leave them all passing while the feature
        is dead in the app. This is the test that fails when the task is removed
        or folded back onto the 10 s interval."""
        from app.refresh_tasks import ensure_refresh_coordinator

        owner = SimpleNamespace(coordinator=None)
        coordinator = ensure_refresh_coordinator(owner)
        by_id = coordinator._tasks

        self.assertIn("passive_items", by_id)
        self.assertEqual(by_id["passive_items"].interval_ms, PASSIVE_ITEMS_REFRESH_MS)
        self.assertEqual(PASSIVE_ITEMS_REFRESH_MS, 1_000)
        # Same demand as the full snapshot: a window where one runs and the
        # other does not would leave a gap in data recordings consume.
        # `assertEqual`, not `assertIs`: each attribute access on a bound method
        # builds a fresh object, so identity never holds even for the same
        # function on the same instance.
        self.assertEqual(
            by_id["passive_items"].required,
            by_id["full_player_snapshot"].required,
        )


class FastStageBoundaryItemsTests(unittest.TestCase):
    def test_the_fast_projection_carries_the_fast_inventory(self) -> None:
        tracker = tracker_with_baseline()
        tracker.update_items(("Wrench x1", "Anvil x1"))

        projection = tracker._fast_stage_summary_snapshot_unlocked()

        self.assertIsNotNone(projection)
        self.assertTrue(projection.items_available)
        self.assertEqual(projection.items, ("Wrench x1", "Anvil x1"))

    def test_a_stale_fast_inventory_is_withheld_rather_than_projected(self) -> None:
        """Expiry degrades to the pre-fast-lane behaviour -- a boundary with no
        inventory -- rather than to a wrong one: an inventory observed seconds
        earlier must not be presented as the state at the transition."""
        now = [1000.0]
        tracker = tracker_with_baseline(clock=lambda: now[0])
        tracker.update_items(("Wrench x1", "Anvil x1"))
        now[0] += FAST_ITEMS_TTL_SECONDS + 0.1
        tracker.update_fast_run_timer(200.0)

        projection = tracker._fast_stage_summary_snapshot_unlocked()

        self.assertIsNotNone(projection)
        self.assertFalse(projection.items_available)

    def test_fast_items_are_cleared_on_a_new_run(self) -> None:
        tracker = tracker_with_baseline()
        tracker.update_items(("Wrench x1", "Anvil x1"))

        tracker._reset_for_new_run()

        self.assertIsNone(tracker._fresh_fast_items_unlocked())


class ClosingSnapshotAttributionTests(unittest.TestCase):
    """`build_stage_summary` is a pure fold, so this is testable without a
    tracker at all."""

    def _snapshots(self):
        return [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=100,
                items=("Wrench x1",),
            ),
            SimpleNamespace(
                game_time_seconds=520.0,
                stage_time_seconds=520.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=500,
                items=("Wrench x1",),
            ),
            # The closing observation: the transition is detected, and this is
            # the first read that shows the Anvil picked up in the tail of
            # Stage 1.
            SimpleNamespace(
                game_time_seconds=540.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=520,
                items=("Wrench x1", "Anvil x1"),
            ),
        ]

    def test_a_closing_snapshot_credits_the_stage_it_closes(self) -> None:
        rows = run_summary.build_stage_summary(self._snapshots())

        self.assertEqual(rows[0]["item_rarities"]["LEGENDARY"], 1)
        self.assertEqual(rows[1]["item_rarities"]["LEGENDARY"], 0)

    def test_a_pickup_after_the_boundary_still_belongs_to_the_new_stage(self) -> None:
        snapshots = self._snapshots()
        snapshots.append(
            SimpleNamespace(
                game_time_seconds=560.0,
                stage_time_seconds=21.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=540,
                items=("Wrench x1", "Anvil x2"),
            )
        )

        rows = run_summary.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["item_rarities"]["LEGENDARY"], 1)
        self.assertEqual(rows[1]["item_rarities"]["LEGENDARY"], 1)

    def test_no_gain_is_counted_twice_across_the_boundary(self) -> None:
        rows = run_summary.build_stage_summary(self._snapshots())

        total = sum(
            row["item_rarities"]["LEGENDARY"]
            for row in rows
            if isinstance(row.get("item_rarities"), dict)
        )
        self.assertEqual(total, 1)


if __name__ == "__main__":
    unittest.main()
