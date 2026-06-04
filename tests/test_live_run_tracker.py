from __future__ import annotations

import unittest

from live_run_tracker import LiveRunSnapshot, LiveRunTracker, TrackedItemRule


def snapshot(
    *,
    time_seconds: float,
    items=(),
    map_seed: int = 100,
    stage_ptr: int = 1000,
    stage_time_seconds: float | None = None,
    mob_kills: int | None = None,
) -> LiveRunSnapshot:
    return LiveRunSnapshot(
        captured_at=time_seconds,
        stats={},
        items=tuple(items),
        game_time_seconds=time_seconds,
        stage_time_seconds=stage_time_seconds if stage_time_seconds is not None else time_seconds,
        mob_kills=mob_kills,
        map_seed=map_seed,
        stage_ptr=stage_ptr,
    )


class LiveRunTrackerTests(unittest.TestCase):
    def test_tracker_counts_anvil_map_one_only_before_stage_transition(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0))
        tracker.update(snapshot(time_seconds=20.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=180.0, items=("Anvil x1",), stage_ptr=2000, stage_time_seconds=1.0))
        tracker.update(snapshot(time_seconds=190.0, items=("Anvil x2",), stage_ptr=2000, stage_time_seconds=10.0))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_map_1"]["count"], 1)
        self.assertEqual(rows["anvils_total"]["count"], 2)

    def test_tracker_counts_stack_delta_as_multiple_items(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x3",)))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_map_1"]["count"], 3)
        self.assertEqual(rows["anvils_total"]["count"], 3)

    def test_tracker_does_not_double_count_after_transient_item_drop(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x2",)))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x2",)))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_total"]["count"], 2)

    def test_tracker_ignores_late_first_snapshot_for_map_one_counter(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=30.0, items=("Anvil x2",)))

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["anvils_map_1"]
        self.assertEqual(row["count"], 0)
        self.assertNotIn("unknown_starting_inventory", row)

    def test_tracker_accepts_early_first_snapshot_for_map_one_counter(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=5.0, items=("Anvil x2",)))

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["anvils_map_1"]
        self.assertEqual(row["count"], 2)
        self.assertNotIn("unknown_starting_inventory", row)

    def test_tracker_does_not_reset_on_seed_change_when_run_time_continues(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=40.0, map_seed=1, stage_ptr=1000))
        run_id = tracker.run_id
        tracker.update(snapshot(time_seconds=80.0, map_seed=2, stage_ptr=2000, stage_time_seconds=1.0))

        self.assertEqual(tracker.run_id, run_id)
        self.assertEqual(len(tracker.snapshots), 2)

    def test_tracker_keeps_tracked_counts_when_run_time_resets(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",)))
        run_id = tracker.run_id
        tracker.update(snapshot(time_seconds=2.0, items=(), map_seed=200))

        self.assertNotEqual(tracker.run_id, run_id)
        self.assertEqual(len(tracker.snapshots), 1)
        self.assertEqual({row["id"]: row for row in tracker.tracked_item_rows()}["anvils_total"]["count"], 1)

    def test_tracker_counts_new_run_items_into_session_total(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",), map_seed=100))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x2",), map_seed=200))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_map_1"]["count"], 3)
        self.assertEqual(rows["anvils_total"]["count"], 3)

    def test_tracker_keeps_counts_when_same_rules_are_reapplied(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",)))
        tracker.set_tracked_item_rules(tracker.tracked_item_rules)

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_map_1"]["count"], 1)
        self.assertEqual(rows["anvils_total"]["count"], 1)

    def test_tracker_keeps_remaining_rule_counts_when_one_rule_is_removed(self) -> None:
        anvil_rule = TrackedItemRule(
            id="anvil_map_1",
            label="Anvil Map 1",
            item_names=("Anvil",),
            mode="map_1_only",
        )
        soul_rule = TrackedItemRule(
            id="soul_harvester_map_1",
            label="Soul Harvester Map 1",
            item_names=("Soul Harvester",),
            mode="map_1_only",
        )
        tracker = LiveRunTracker(
            clock=lambda: 1000.0,
            tracked_item_rules=(anvil_rule, soul_rule),
        )
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1", "Soul Harvester x2")))

        tracker.set_tracked_item_rules((soul_rule,))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertNotIn("anvil_map_1", rows)
        self.assertEqual(rows["soul_harvester_map_1"]["count"], 2)

        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1", "Soul Harvester x3")))
        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["soul_harvester_map_1"]["count"], 3)

    def test_tracker_marks_state_stale_after_missing_updates(self) -> None:
        now = [1000.0]
        tracker = LiveRunTracker(clock=lambda: now[0], stale_after_seconds=5.0)
        tracker.update(snapshot(time_seconds=1.0))
        self.assertEqual(tracker.status(), "live")
        now[0] = 1007.0
        self.assertEqual(tracker.status(), "stale")

    def test_tracker_counts_configured_non_anvil_map_one_item(self) -> None:
        tracker = LiveRunTracker(
            clock=lambda: 1000.0,
            tracked_item_rules=(
                TrackedItemRule(
                    id="wrench_map_1",
                    label="Wrench Map 1",
                    item_names=("Wrench",),
                    mode="map_1_only",
                ),
            ),
        )
        tracker.update(snapshot(time_seconds=2.0, items=("Wrench x1",)))
        tracker.update(snapshot(time_seconds=180.0, items=("Wrench x2",), stage_ptr=2000, stage_time_seconds=1.0))

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["wrench_map_1"]
        self.assertEqual(row["count"], 1)


if __name__ == "__main__":
    unittest.main()
