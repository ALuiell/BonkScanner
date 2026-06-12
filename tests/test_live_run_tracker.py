from __future__ import annotations

import unittest
from types import SimpleNamespace

from live_run_tracker import LiveRunSnapshot, LiveRunTracker, TrackedItemRule
from player_stats import PlayerStatFormat


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

    def test_tracker_matches_gloves_power_inventory_alias(self) -> None:
        tracker = LiveRunTracker(
            clock=lambda: 1000.0,
            tracked_item_rules=(
                TrackedItemRule(
                    id="glove_power_map_1",
                    label="Glove Power Map 1",
                    item_names=("Glove Power",),
                    mode="map_1_only",
                ),
            ),
        )
        tracker.update(snapshot(time_seconds=20.0, items=()))
        tracker.update(snapshot(time_seconds=40.0, items=("Gloves Power x1",)))

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["glove_power_map_1"]
        self.assertEqual(row["count"], 1)

    def test_tracker_matches_known_item_aliases(self) -> None:
        alias_pairs = (
            ("Glove Blood", "Gloves Blood"),
            ("Glove Curse", "Gloves Cursed"),
            ("Golden Ring", "No Implementation"),
            ("Sucky Magnet", "Sucky Hoof"),
            ("Pot", "Pot Steel"),
            ("Bobs Lantern", "Bob Lantern"),
            ("Feathers", "Flappy Feathers"),
        )

        for canonical_name, live_name in alias_pairs:
            with self.subTest(canonical_name=canonical_name, live_name=live_name):
                tracker = LiveRunTracker(
                    clock=lambda: 1000.0,
                    tracked_item_rules=(
                        TrackedItemRule(
                            id="tracked_item",
                            label=canonical_name,
                            item_names=(canonical_name,),
                            mode="all_run",
                        ),
                    ),
                )
                tracker.update(snapshot(time_seconds=20.0, items=()))
                tracker.update(snapshot(time_seconds=40.0, items=(f"{live_name} x1",)))

                row = {row["id"]: row for row in tracker.tracked_item_rows()}["tracked_item"]
                self.assertEqual(row["count"], 1)

    def test_chaos_tracker_sums_large_new_modifiers_on_level_gain(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_chaos_tome(
            chaos_level=1,
            permanent_modifiers={
                12: (
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.01,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                )
            },
        )
        tracker.update_chaos_tome(
            chaos_level=2,
            permanent_modifiers={
                12: (
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.01,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.168,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                ),
                30: (
                    SimpleNamespace(
                        stat_id=30,
                        label="Luck",
                        value=0.005,
                        value_format=PlayerStatFormat.PERCENT,
                    ),
                ),
            },
        )

        self.assertEqual(tracker.chaos_tome_level(), 2)
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +16.8%"])

    def test_chaos_tracker_updates_baseline_when_level_does_not_change(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        damage_small = SimpleNamespace(
            stat_id=12,
            label="Damage",
            value=0.01,
            value_format=PlayerStatFormat.MULTIPLIER,
        )
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: ()})
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (damage_small,)})
        tracker.update_chaos_tome(
            chaos_level=2,
            permanent_modifiers={
                12: (
                    damage_small,
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.329,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                )
            },
        )

        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +32.9%"])

    def test_chaos_tracker_omits_roll_counts_from_summary(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        first = SimpleNamespace(
            stat_id=30,
            label="Luck",
            value=0.07,
            value_format=PlayerStatFormat.PERCENT,
        )
        second = SimpleNamespace(
            stat_id=30,
            label="Luck",
            value=0.07,
            value_format=PlayerStatFormat.PERCENT,
        )
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={30: ()})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={30: (first,)})
        tracker.update_chaos_tome(chaos_level=3, permanent_modifiers={30: (first, second)})

        self.assertEqual(tracker.chaos_tome_summary_parts(), ["Luck +14%"])

    def test_chaos_tracker_uses_stats_command_abbreviations(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        gold = SimpleNamespace(
            stat_id=31,
            label="Gold Gain",
            value=0.206,
            value_format=PlayerStatFormat.MULTIPLIER,
        )
        movement_speed = SimpleNamespace(
            stat_id=25,
            label="Movement Speed",
            value=0.112,
            value_format=PlayerStatFormat.MULTIPLIER,
        )
        powerup_drop = SimpleNamespace(
            stat_id=41,
            label="Powerup Drop Chance",
            value=0.179,
            value_format=PlayerStatFormat.MULTIPLIER,
        )
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={})
        tracker.update_chaos_tome(
            chaos_level=4,
            permanent_modifiers={
                31: (gold,),
                25: (movement_speed,),
                41: (powerup_drop,),
            },
        )

        self.assertEqual(
            tracker.chaos_tome_summary_parts(),
            ["MS +11.2%", "Gold +20.6%", "PDC +17.9%"],
        )

    def test_chaos_tracker_exposes_structured_snapshot(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={})
        tracker.update_chaos_tome(
            chaos_level=3,
            permanent_modifiers={
                12: (
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.168,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                ),
                30: (
                    SimpleNamespace(
                        stat_id=30,
                        label="Luck",
                        value=0.07,
                        value_format=PlayerStatFormat.PERCENT,
                    ),
                ),
            },
        )

        snapshot = tracker.chaos_tome_snapshot()

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.level, 3)
        self.assertEqual(
            [(stat.stat_id, stat.label, stat.display_delta) for stat in snapshot.stats],
            [(12, "Damage", "+16.8%"), (30, "Luck", "+7%")],
        )

    def test_chaos_tracker_handles_stacked_modifiers(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={})
        tracker.update_chaos_tome(
            chaos_level=2,
            permanent_modifiers={
                12: (
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.168,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                ),
            },
        )
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +16.8%"])

        tracker.update_chaos_tome(
            chaos_level=3,
            permanent_modifiers={
                12: (
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.336,  # 0.168 + 0.168
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                ),
            },
        )
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +33.6%"])

    def test_chaos_tracker_handles_delayed_memory_writes(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={})
        
        # Level increases by 3 (from 1 to 4), but no modifiers arrive yet.
        tracker.update_chaos_tome(chaos_level=4, permanent_modifiers={})
        self.assertEqual(tracker.chaos_tome_summary_parts(), [])
        
        # Next tick, level is still 4. 1 valid modifier arrives.
        tracker.update_chaos_tome(
            chaos_level=4,
            permanent_modifiers={
                12: (
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.168,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                )
            },
        )
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +16.8%"])
        
        # Next tick, 2 more modifiers arrive.
        tracker.update_chaos_tome(
            chaos_level=4,
            permanent_modifiers={
                12: (
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.168,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.168,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                ),
                30: (
                    SimpleNamespace(
                        stat_id=30,
                        label="Luck",
                        value=0.07,
                        value_format=PlayerStatFormat.PERCENT,
                    ),
                )
            },
        )
        # Should sum to 2x DMG (1st tick + 2nd tick) and 1x Luck
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +33.6%", "Luck +7%"])
        
        # Next tick, 1 more valid modifier arrives. But we only had available_rolls=3 (levels 2, 3, 4).
        # We already processed 3 rolls (1 in tick 1, 2 in tick 2).
        # It should ignore the new modifier because available_rolls is 0.
        tracker.update_chaos_tome(
            chaos_level=4,
            permanent_modifiers={
                12: (
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.168,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=0.168,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                ),
                30: (
                    SimpleNamespace(
                        stat_id=30,
                        label="Luck",
                        value=0.07,
                        value_format=PlayerStatFormat.PERCENT,
                    ),
                    SimpleNamespace(
                        stat_id=30,
                        label="Luck",
                        value=0.07,
                        value_format=PlayerStatFormat.PERCENT,
                    ),
                )
            },
        )
        
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +33.6%", "Luck +7%"])

    def test_chests_first_chest_tracked(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        # Initialize
        tracker.track_chest_opening(0, 100)
        # First chest opened with same gold (free proc)
        tracker.track_chest_opening(1, 100)
        _, _, _, free_opens, _, _ = tracker.get_chests_and_keys()
        self.assertEqual(free_opens, 1)

    def test_first_chest_sample_after_new_run_only_sets_baseline(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, map_seed=100))

        tracker.track_chest_opening(1, 90)

        _, _, _, free_opens, _, _ = tracker.get_chests_and_keys()
        self.assertEqual(free_opens, 0)

    def test_has_active_run_clears_when_game_is_gone(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0))
        self.assertTrue(tracker.has_active_run())

        tracker.mark_read_failed(no_game=True)
        self.assertFalse(tracker.has_active_run())

    def test_has_active_run_rejects_inactive_latest_snapshot(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0))
        tracker.update(LiveRunSnapshot(captured_at=2.0, stats={}))

        self.assertFalse(tracker.has_active_run())

    def test_disabled_items_cache_survives_unavailable_snapshots(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(LiveRunSnapshot(
            captured_at=1.0,
            stats={},
            game_time_seconds=1.0,
            disabled_items=("Battery",),
            disabled_items_available=True,
        ))
        tracker.update(LiveRunSnapshot(
            captured_at=2.0,
            stats={},
            game_time_seconds=2.0,
            disabled_items_available=False,
        ))

        result = tracker.get_disabled_items()

        self.assertTrue(result.available)
        self.assertEqual(result.items, ("Battery",))

    def test_chests_stage_transition_residual_filtered(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        # Stage 1: opened 28 chests
        tracker.update(snapshot(time_seconds=1.0, stage_ptr=1000, stage_time_seconds=10.0))
        tracker.update_chests_and_keys(28, 46, 0)
        
        # Transition to Stage 2 (time resets, pointer changes)
        # Snapshot for stage 2 with low stage time
        tracker.update(snapshot(time_seconds=20.0, stage_ptr=2000, stage_time_seconds=1.0))
        
        # Suppose game data client reads residual chests_opened = 28
        tracker.update_chests_and_keys(28, 46, 0)
        
        _, _, _, _, opened_by_stage, _ = tracker.get_chests_and_keys()
        self.assertEqual(opened_by_stage[2], 0)

    def test_chests_stage_transition_residual_filtered_high_stage_time(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        # Stage 1: opened 28 chests
        tracker.update(snapshot(time_seconds=1.0, stage_ptr=1000, stage_time_seconds=10.0))
        tracker.update_chests_and_keys(28, 46, 0)
        
        # Transition to Stage 2 (pointer changes, but first refresh happens late at 8.0s)
        tracker.update(snapshot(time_seconds=20.0, stage_ptr=2000, stage_time_seconds=8.0))
        
        # Suppose game data client reads residual chests_opened = 28
        tracker.update_chests_and_keys(28, 46, 0)
        
        _, _, _, _, opened_by_stage, _ = tracker.get_chests_and_keys()
        # Should still filter to 0 even though stage_time_seconds >= 5.0
        self.assertEqual(opened_by_stage[2], 0)

    def test_chests_stage_four_same_ptr_shares_stage_three_stats(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        # Stage 3: opened 15 chests, stage_ptr = 3000
        tracker.update(snapshot(time_seconds=1.0, stage_ptr=3000, stage_time_seconds=10.0))
        tracker.update_chests_and_keys(15, 46, 0)
        
        # Transition to Stage 4 (virtual stage transition, pointer remains 3000)
        tracker.update(snapshot(time_seconds=20.0, stage_ptr=3000, stage_time_seconds=1.0))
        # Boss room reports max chests = 15 instead of 46
        tracker.update_chests_and_keys(15, 15, 0)
        
        _, _, _, _, opened_by_stage, total_by_stage = tracker.get_chests_and_keys()
        # Stage 4 should not be created as a separate entry, stage 3 should still be 15, and total should be preserved as 46
        self.assertEqual(len(opened_by_stage), 1)
        self.assertEqual(opened_by_stage[1], 15)
        self.assertEqual(total_by_stage[1], 46)


if __name__ == "__main__":
    unittest.main()
