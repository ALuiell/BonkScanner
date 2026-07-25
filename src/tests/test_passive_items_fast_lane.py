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

The task has since become the whole *loot sample*: `MAP_ACTIVITY_VALUES` and
`LUCK` are read in the same pass as the inventory. That is one change, not
three reads -- a key resolves once per `RefreshTickContext`, so items, the
interactable counters and Luck carry one timestamp and are coherent by
construction rather than by matching timestamps afterwards.
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import config
from app.read_sources import LUCK, MAP_ACTIVITY_VALUES, PASSIVE_ITEMS
from app.refresh_coordinator import RefreshTickContext
from app.refresh_tasks import (
    PASSIVE_ITEMS_REFRESH_MS,
    in_game_overlay_requires_player_stats_refresh,
)
from core import run_summary
from core.tracker.live_run import (
    FAST_ITEMS_TTL_SECONDS,
    FAST_LUCK_TTL_SECONDS,
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
        from app.refresh_tasks import ensure_refresh_coordinator, refresh_tasks

        owner = SimpleNamespace(coordinator=None)
        coordinator = ensure_refresh_coordinator(owner)
        by_id = coordinator._tasks

        self.assertIn("passive_items", by_id)
        self.assertEqual(by_id["passive_items"].interval_ms, PASSIVE_ITEMS_REFRESH_MS)
        self.assertEqual(PASSIVE_ITEMS_REFRESH_MS, 1_000)
        # `assertEqual`, not `assertIs`: each attribute access on a bound method
        # builds a fresh object, so identity never holds even for the same
        # function on the same instance.
        self.assertEqual(
            by_id["passive_items"].required,
            refresh_tasks(owner)._should_refresh_passive_items,
        )

    def test_the_demand_is_wider_than_the_snapshots_never_narrower(self) -> None:
        """This task feeds the same tracked-item state recordings consume, so a
        window where the snapshot runs and this does not would leave a gap in
        the data rather than merely a stale label -- which is why the two shared
        one predicate. The extra arm is the Luck widget, which reads this task's
        `LUCK` source now instead of the snapshot's per-stat walk, so it has to
        be able to demand *this* task."""
        service, world = build_refresh_tasks()

        with patch.object(config, "IN_GAME_OVERLAY", {}):
            for demanded in (False, True):
                world.lifecycle.is_active_run = lambda demanded=demanded: demanded
                self.assertEqual(
                    service._should_refresh_passive_items(),
                    service._should_refresh_full_player_snapshot(),
                )

        luck_only = {"enabled": True, "widgets": {"luck_rarity": {"enabled": True}}}
        with patch.object(config, "IN_GAME_OVERLAY", luck_only):
            world.lifecycle.is_active_run = lambda: False
            self.assertFalse(service._should_refresh_full_player_snapshot())
            self.assertTrue(service._should_refresh_passive_items())

    def test_the_luck_widget_no_longer_demands_the_full_stat_walk(self) -> None:
        """The other half of the same change. `luck_rarity` demanded the 10 s
        snapshot only because Luck was reachable nowhere else; leaving it in
        `in_game_overlay_requires_player_stats_refresh` would keep paying for a
        per-stat walk it no longer reads from."""
        luck_only = {"enabled": True, "widgets": {"luck_rarity": {"enabled": True}}}
        with patch.object(config, "IN_GAME_OVERLAY", luck_only):
            self.assertFalse(in_game_overlay_requires_player_stats_refresh())

        stats_widget = {"enabled": True, "widgets": {"stats": {"enabled": True}}}
        with patch.object(config, "IN_GAME_OVERLAY", stats_widget):
            self.assertTrue(in_game_overlay_requires_player_stats_refresh())


class LootSamplePassTests(unittest.TestCase):
    """Items, the interactable counters and Luck, read in **one** pass.

    Not "three sources are read" -- three sources read *together*. A key
    resolves once per `RefreshTickContext`, so every consumer of this pass sees
    one value from one moment, which is what makes "did the counter move before
    or after this gain" and "which Luck applied to this roll" stop being
    questions instead of being answered by matching two buffers.
    """

    def _stats_client(self, *, items=("Anvil x1",), luck=1.25):
        return type(
            "Client",
            (),
            {
                "resolve_owner_stats": lambda self: 0x1234,
                "get_passive_items": lambda self, owner=None: (
                    items() if callable(items) else items
                ),
                "get_luck": lambda self, owner=None: (
                    luck() if callable(luck) else luck
                ),
            },
        )()

    def _game_data_client(self, activity=None, *, calls=None):
        if activity is None:
            activity = {"Moais": SimpleNamespace(current=1, max=3)}

        def get_map_activity_values(_self):
            if calls is not None:
                calls.append(1)
            return activity() if callable(activity) else activity

        return type(
            "GameData",
            (),
            {"get_map_activity_values": get_map_activity_values},
        )()

    def setUp(self) -> None:
        self.context = RefreshTickContext(pass_id=1, started_at=0.0, clock=lambda: 0.0)

    def _build(self, **kwargs):
        world_state = SimpleNamespace(luck=[], contexts=[], items=[])
        service, world = build_refresh_tasks(world=world_state, **kwargs)
        world.tracker.update_fast_luck = lambda value: world.luck.append(value)
        world.tracker.update_powerup_map_context = lambda ctx: world.contexts.append(ctx)
        world.tracker.update_items = lambda items: world.items.append(items) or True
        return service, world

    def test_one_tick_yields_items_counters_and_luck_together(self) -> None:
        service, world = self._build(
            stats_client=self._stats_client(),
            game_data_client=self._game_data_client(),
        )

        self.assertTrue(service._refresh_passive_items_task(self.context))

        self.assertEqual(world.items, [("Anvil x1",)])
        self.assertEqual(world.luck, [1.25])
        self.assertEqual([ctx.activity_max for ctx in world.contexts], [{"Moais": 3}])
        # The load-bearing assertion: all three resolved inside *this* pass, so
        # they carry one timestamp. Three sources read on three passes would
        # satisfy every assertion above and none of this one.
        for key in (PASSIVE_ITEMS, MAP_ACTIVITY_VALUES, LUCK):
            self.assertIsNotNone(self.context.metadata_for(key), key)

    def test_the_counters_cost_no_extra_read_when_the_snapshot_is_also_due(self) -> None:
        """`get_map_activity_values` already walks the whole dictionary and
        returns every key. Both consumers resolve the one `MAP_ACTIVITY_VALUES`
        key, so the pass cache shares the single physical walk."""
        calls: list[int] = []
        service, world = self._build(
            stats_client=self._stats_client(),
            game_data_client=self._game_data_client(calls=calls),
        )

        # The 10 s snapshot's own entry point, resolving the same key.
        world.memory.read_map_activity_values(self.context)
        service._refresh_passive_items_task(self.context)

        self.assertEqual(calls, [1])

    def test_a_counter_read_failure_leaves_the_health_streaks_to_the_snapshot(self) -> None:
        """Error policy, decided: the full snapshot stays the health owner for
        `MAP_ACTIVITY_VALUES`. It records health in its own task body from the
        cached result, so a second consumer must not steal that accounting nor
        advance the streak twice for one physical read."""
        service, world = self._build(
            stats_client=self._stats_client(),
            game_data_client=self._game_data_client(
                activity=lambda: (_ for _ in ()).throw(MemoryReadError("no map"))
            ),
        )

        self.assertTrue(service._refresh_passive_items_task(self.context))

        self.assertEqual(world.memory._player_stats_game_data_memory_error_streak, 0)
        self.assertEqual(world.memory._game_data_source_error_streaks, {})
        self.assertEqual(world.contexts, [])

    def test_the_snapshot_still_sees_a_counter_failure_this_task_swallowed(self) -> None:
        """Swallowing must not hide the failure from the health owner. The pass
        caches the *exception*, so the snapshot's own resolution of the key
        re-raises it and records its health exactly as before -- one physical
        read, one accounting, and it is still the snapshot's."""
        calls: list[int] = []

        def failing():
            calls.append(1)
            raise MemoryReadError("no map")

        service, world = self._build(
            stats_client=self._stats_client(),
            game_data_client=self._game_data_client(activity=failing, calls=None),
        )
        service._refresh_passive_items_task(self.context)

        with self.assertRaises(MemoryReadError):
            world.memory.read_map_activity_values(self.context)
        self.assertEqual(calls, [1])

    def test_an_empty_counter_dictionary_does_not_blank_a_good_map_context(self) -> None:
        """`get_map_activity_values` returns `{}` whenever a pointer in its
        chain reads zero, and outside a run that is legitimate. Publishing an
        empty context would replace a good reading with a blank one; deciding
        that empty-during-a-run is a failure belongs to the snapshot, which
        raises on it."""
        service, world = self._build(
            stats_client=self._stats_client(),
            game_data_client=self._game_data_client(activity={}),
        )

        service._refresh_passive_items_task(self.context)

        self.assertEqual(world.contexts, [])

    def test_a_failing_inventory_read_still_publishes_luck_and_the_counters(self) -> None:
        """Per-source failure isolation. The inventory is the one source here
        that raises, and it is read last for exactly this reason."""
        service, world = self._build(
            stats_client=self._stats_client(
                items=lambda: (_ for _ in ()).throw(MemoryReadError("inventory gone"))
            ),
            game_data_client=self._game_data_client(),
        )

        self.assertFalse(service._refresh_passive_items_task(self.context))

        self.assertEqual(world.items, [])
        self.assertEqual(world.luck, [1.25])
        self.assertEqual(len(world.contexts), 1)

    def test_an_unreadable_luck_clears_the_reading_rather_than_publishing_zero(self) -> None:
        """`None` is "no fresh read". Zero is a real Luck the rarity model
        produces a valid distribution from, so publishing it for a failed read
        would render a failure as a reading."""
        service, world = self._build(
            stats_client=self._stats_client(luck=None),
            game_data_client=self._game_data_client(),
        )

        service._refresh_passive_items_task(self.context)

        self.assertEqual(world.luck, [None])


class FastLuckPublicationTests(unittest.TestCase):
    def test_the_runtime_snapshot_carries_the_fast_luck(self) -> None:
        tracker = tracker_with_baseline()

        tracker.update_fast_luck(2.5)

        self.assertEqual(tracker.runtime_snapshot().luck, 2.5)

    def test_a_stale_luck_is_withheld_rather_than_published(self) -> None:
        now = [1000.0]
        tracker = tracker_with_baseline(clock=lambda: now[0])
        tracker.update_fast_luck(2.5)
        now[0] += FAST_LUCK_TTL_SECONDS + 0.1

        self.assertIsNone(tracker.runtime_snapshot().luck)

    def test_luck_is_cleared_on_a_new_run(self) -> None:
        tracker = tracker_with_baseline()
        tracker.update_fast_luck(2.5)

        tracker._reset_for_new_run()

        self.assertIsNone(tracker.runtime_snapshot().luck)


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
