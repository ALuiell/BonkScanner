from __future__ import annotations

import unittest
from types import SimpleNamespace

from live_run_tracker import (
    LiveRunSnapshot,
    LiveRunTracker,
    PowerupMapContext,
    TrackedItemRule,
)
from player_stats import PlayerStatFormat


def snapshot(
    *,
    time_seconds: float,
    items=(),
    map_seed: int = 100,
    stage_ptr: int = 1000,
    stage_index: int | None = None,
    stage_time_seconds: float | None = None,
    mob_kills: int | None = None,
    chests_total: int | None = None,
    pots_total: int | None = None,
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
        stage_index=stage_index,
        chests_total=chests_total,
        pots_total=pots_total,
    )


class LiveRunTrackerTests(unittest.TestCase):
    def non_graveyard_context(self) -> PowerupMapContext:
        return PowerupMapContext.from_activity_max(
            {"Chests": 46, "Pots": 55},
            captured_at=1000.0,
        )

    def graveyard_context(self) -> PowerupMapContext:
        return PowerupMapContext.from_activity_max(
            {"Chests": 69, "Pumpkin": 105, "Gravestones": 22},
            captured_at=1000.0,
        )

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

    def test_tracker_counts_late_first_snapshot_for_map_one_counter_while_still_on_first_map(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=30.0, items=("Anvil x2",)))

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["anvils_map_1"]
        self.assertEqual(row["count"], 2)
        self.assertNotIn("unknown_starting_inventory", row)

    def test_tracker_ignores_late_first_snapshot_for_map_one_counter_after_stage_transition(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=120.0,
                items=("Anvil x2",),
                stage_ptr=2000,
                stage_time_seconds=5.0,
            )
        )

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["anvils_map_1"]
        self.assertEqual(row["count"], 0)

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

    def test_current_kps_clears_when_game_disappears(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.track_kills(10.0, 100)
        tracker.track_kills(13.0, 160)

        self.assertEqual(tracker.current_kps(), 20)

        tracker.mark_read_failed(no_game=True)

        self.assertIsNone(tracker.current_kps())

    def test_current_ui_kps_uses_valid_one_second_tick(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.track_kills(100.0, 1_000)
        tracker.track_kills(100.5, 1_100)
        self.assertIsNone(tracker.current_ui_kps())

        tracker.track_kills(101.0, 1_300)

        self.assertEqual(tracker.current_ui_kps(), 300)

    def test_current_ui_kps_ignores_tiny_timer_jump_after_pause(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.track_kills(586.522217, 48_349)
        tracker.track_kills(586.522217, 48_349)
        tracker.track_kills(586.770508, 48_462)

        self.assertIsNone(tracker.current_ui_kps())
        self.assertEqual(tracker.current_kps(), 455)

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

    def test_tracker_counts_combo_rule_when_all_items_are_present(self) -> None:
        tracker = LiveRunTracker(
            clock=lambda: 1000.0,
            tracked_item_rules=(
                TrackedItemRule(
                    id="kevin_plug",
                    label="Kevin + Electric Plug",
                    item_names=("Kevin", "Electric Plug"),
                    mode="all_run",
                ),
            ),
        )

        tracker.update(snapshot(time_seconds=20.0, items=("Kevin x1",)))
        tracker.update(snapshot(time_seconds=40.0, items=("Kevin x1", "Electric Plug x1")))
        tracker.update(snapshot(time_seconds=50.0, items=("Kevin x2", "Electric Plug x1")))
        tracker.update(snapshot(time_seconds=60.0, items=("Kevin x2", "Electric Plug x2")))

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["kevin_plug"]
        self.assertEqual(row["count"], 1)

    def test_tracker_combo_map_one_only_requires_full_combo_on_first_map(self) -> None:
        tracker = LiveRunTracker(
            clock=lambda: 1000.0,
            tracked_item_rules=(
                TrackedItemRule(
                    id="kevin_plug_map_1",
                    label="Kevin + Electric Plug Map 1",
                    item_names=("Kevin", "Electric Plug"),
                    mode="map_1_only",
                ),
            ),
        )

        tracker.update(snapshot(time_seconds=20.0, items=("Kevin x1",)))
        tracker.update(
            snapshot(
                time_seconds=180.0,
                items=("Kevin x1", "Electric Plug x1"),
                stage_ptr=2000,
                stage_time_seconds=1.0,
            )
        )

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["kevin_plug_map_1"]
        self.assertEqual(row["count"], 0)

    def test_tracker_counts_combo_once_per_run_and_again_after_new_run(self) -> None:
        tracker = LiveRunTracker(
            clock=lambda: 1000.0,
            tracked_item_rules=(
                TrackedItemRule(
                    id="kevin_plug_map_1",
                    label="Kevin + Electric Plug Map 1",
                    item_names=("Kevin", "Electric Plug"),
                    mode="map_1_only",
                ),
            ),
        )

        tracker.update(snapshot(time_seconds=2.0, items=("Kevin x1", "Electric Plug x1"), map_seed=100))
        tracker.update(snapshot(time_seconds=10.0, items=("Kevin x2", "Electric Plug x2"), map_seed=100))
        tracker.update(snapshot(time_seconds=20.0, items=("Kevin x2", "Electric Plug x1"), map_seed=100))
        tracker.update(snapshot(time_seconds=2.0, items=("Kevin x1", "Electric Plug x1"), map_seed=200))

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["kevin_plug_map_1"]
        self.assertEqual(row["count"], 2)

    def test_tracker_does_not_retroactively_count_combo_when_rule_is_added_mid_run(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0, tracked_item_rules=())
        tracker.update(snapshot(time_seconds=20.0, items=("Kevin x1", "Electric Plug x1"), map_seed=100))

        tracker.set_tracked_item_rules(
            (
                TrackedItemRule(
                    id="kevin_plug",
                    label="Kevin + Electric Plug",
                    item_names=("Kevin", "Electric Plug"),
                    mode="all_run",
                ),
            )
        )
        tracker.update(snapshot(time_seconds=30.0, items=("Kevin x1", "Electric Plug x1"), map_seed=100))
        tracker.update(snapshot(time_seconds=40.0, items=("Kevin x2", "Electric Plug x1"), map_seed=100))
        tracker.update(snapshot(time_seconds=50.0, items=("Kevin x2", "Electric Plug x2"), map_seed=100))

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["kevin_plug"]
        self.assertEqual(row["count"], 0)

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

    def test_chaos_tracker_counts_initial_modifier_when_tome_is_first_seen(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_chaos_tome(
            chaos_level=1,
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

        self.assertEqual(tracker.chaos_tome_level(), 1)
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +16.8%"])
        self.assertEqual(tracker.chaos_tome_snapshot().stats[0].rolls, 1)

    def test_chaos_tracker_counts_initial_modifier_after_delayed_first_write(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        modifier = SimpleNamespace(
            stat_id=30,
            label="Luck",
            value=0.07,
            value_format=PlayerStatFormat.PERCENT,
        )

        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={30: ()})
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={30: (modifier,)})

        self.assertEqual(tracker.chaos_tome_summary_parts(), ["Luck +7%"])
        self.assertEqual(tracker.chaos_tome_snapshot().stats[0].rolls, 1)

    def test_chaos_tracker_waits_for_positive_initial_level(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        modifier = SimpleNamespace(
            stat_id=3,
            label="Thorns",
            value=8.4,
            value_format=PlayerStatFormat.FLAT,
        )

        for _ in range(5):
            tracker.update_chaos_tome(chaos_level=0, permanent_modifiers={3: (modifier,)})

        self.assertIsNone(tracker.chaos_tome_level())
        self.assertEqual(tracker.chaos_tome_summary_parts(), [])

        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={3: (modifier,)})

        self.assertEqual(tracker.chaos_tome_level(), 1)
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["Thorns +8.4"])
        self.assertEqual(tracker.chaos_tome_snapshot().stats[0].rolls, 1)

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

    def test_chaos_tracker_crit_damage_summary_uses_effective_scale(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        crit_damage = SimpleNamespace(
            stat_id=19,
            label="Crit Damage",
            value=0.14,
            value_format=PlayerStatFormat.MULTIPLIER,
        )
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={19: (crit_damage,)})

        self.assertEqual(tracker.chaos_tome_summary_parts(), ["CritDMG +28%"])

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

        # Next tick, 1 more valid modifier arrives. We had available_rolls=4
        # (levels 1, 2, 3, 4), so the delayed initial roll is counted too.
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

        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +33.6%", "Luck +14%"])

    def test_chaos_tracker_keeps_state_across_transient_missing_tome_read(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        powerup = lambda value: SimpleNamespace(
            stat_id=40,
            label="Powerup Multiplier",
            value=value,
            value_format=PlayerStatFormat.MULTIPLIER,
        )

        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={40: (powerup(0.0),)})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={40: (powerup(0.224),)})
        tracker.update_chaos_tome(chaos_level=None, permanent_modifiers={})
        tracker.update_chaos_tome(chaos_level=5, permanent_modifiers={40: (powerup(1.568),)})

        self.assertEqual(tracker.chaos_tome_level(), 5)
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["PM +156.8%"])
        self.assertEqual(tracker.chaos_tome_snapshot().stats[0].rolls, 4)

    def test_chaos_tracker_keeps_state_across_prolonged_missing_tome_reads(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        powerup = lambda value: SimpleNamespace(
            stat_id=40,
            label="Powerup Multiplier",
            value=value,
            value_format=PlayerStatFormat.MULTIPLIER,
        )

        tracker.update_chaos_tome(chaos_level=138, permanent_modifiers={40: ()})

        for _ in range(20):
            tracker.update_chaos_tome(chaos_level=None, permanent_modifiers={})

        tracker.update_chaos_tome(
            chaos_level=141,
            permanent_modifiers={40: (powerup(1.344),)},
        )

        self.assertEqual(tracker.chaos_tome_level(), 141)
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["PM +134.4%"])
        self.assertEqual(tracker.chaos_tome_snapshot().stats[0].rolls, 3)

    def test_chaos_tracker_ignores_transient_level_decrease(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        powerup = lambda value: SimpleNamespace(
            stat_id=40,
            label="Powerup Multiplier",
            value=value,
            value_format=PlayerStatFormat.MULTIPLIER,
        )

        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={40: ()})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={40: (powerup(0.448),)})
        tracker.update_chaos_tome(chaos_level=None, permanent_modifiers={})
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={40: ()})
        tracker.update_chaos_tome(chaos_level=3, permanent_modifiers={40: (powerup(0.672),)})

        self.assertEqual(tracker.chaos_tome_level(), 3)
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["PM +67.2%"])
        self.assertEqual(tracker.chaos_tome_snapshot().stats[0].rolls, 2)

    def test_chaos_tracker_expires_unbudgeted_fingerprint_before_future_roll(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        damage = SimpleNamespace(
            stat_id=12,
            label="Damage",
            value=0.168,
            value_format=PlayerStatFormat.MULTIPLIER,
        )
        powerup = SimpleNamespace(
            stat_id=40,
            label="Powerup Multiplier",
            value=0.448,
            value_format=PlayerStatFormat.MULTIPLIER,
        )

        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (), 40: ()})
        for _ in range(4):
            tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (damage,), 40: ()})

        tracker.update_chaos_tome(
            chaos_level=2,
            permanent_modifiers={12: (damage,), 40: (powerup,)},
        )

        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +16.8%", "PM +44.8%"])

    def test_chaos_tracker_allows_modifier_to_arrive_one_tick_before_level(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        powerup = SimpleNamespace(
            stat_id=40,
            label="Powerup Multiplier",
            value=0.448,
            value_format=PlayerStatFormat.MULTIPLIER,
        )

        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={40: ()})
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={40: (powerup,)})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={40: (powerup,)})

        self.assertEqual(tracker.chaos_tome_summary_parts(), ["PM +44.8%"])

    def test_chest_counters_derive_exact_breakdown(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, map_seed=100, stage_ptr=1000))
        tracker.update_chests_and_keys(10, 46, 5)

        self.assertTrue(tracker.update_chest_counters(8, 3))
        stats = tracker.get_chest_stats()

        self.assertEqual(stats.total_opened, 10)
        self.assertEqual(stats.paid, 3)
        self.assertEqual(stats.key_procs, 5)
        self.assertEqual(stats.free_chests, 2)
        self.assertEqual(stats.normal_opened, 8)

    def test_chest_counters_reject_inconsistent_snapshot(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, map_seed=100, stage_ptr=1000))
        tracker.update_chests_and_keys(4, 46, 0)
        self.assertTrue(tracker.update_chest_counters(3, 2))

        self.assertFalse(tracker.update_chest_counters(5, 2))
        stats = tracker.get_chest_stats()

        self.assertEqual((stats.paid, stats.key_procs, stats.free_chests), (2, 1, 1))

    def test_chest_counters_self_heal_after_new_stage_is_observed(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, map_seed=100, stage_ptr=1000))
        tracker.update_chests_and_keys(41, 46, 0)
        self.assertTrue(tracker.update_chest_counters(41, 20))

        self.assertFalse(tracker.update_chest_counters(42, 20))
        tracker.update(snapshot(time_seconds=2.0, map_seed=100, stage_ptr=2000))
        tracker.update_chests_and_keys(1, 46, 0)

        self.assertTrue(tracker.update_chest_counters(42, 20))
        stats = tracker.get_chest_stats()
        self.assertEqual(stats.total_opened, 42)
        self.assertEqual((stats.paid, stats.key_procs, stats.free_chests), (20, 22, 0))

    def test_chests_midrun_start_marks_missing_prior_stage_unknown(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=120.0, map_seed=100, stage_ptr=2000, stage_index=1))
        tracker.update_chests_and_keys(20, 46, 0)
        self.assertTrue(tracker.update_chest_counters(51, 17))
        stats = tracker.get_chest_stats()

        self.assertEqual(stats.total_opened, 51)
        self.assertTrue(stats.total_opened_is_minimum)
        self.assertEqual(stats.total_chests, 92)
        self.assertEqual(stats.opened_by_stage, {1: -1, 2: 20})
        self.assertEqual(stats.total_by_stage, {1: 46, 2: 46})
        self.assertEqual((stats.paid, stats.key_procs, stats.free_chests), (17, 34, None))

    def test_run_identity_starts_from_raw_stage_index_on_late_attach(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        tracker.update(snapshot(time_seconds=120.0, map_seed=100, stage_ptr=2000, stage_index=1))

        _, stage_index = tracker.run_identity()
        self.assertEqual(stage_index, 2)

    def test_stage_summary_late_attach_starts_at_raw_stage_three(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=240.0, map_seed=100, stage_ptr=3000, stage_index=2, stage_time_seconds=80.0, mob_kills=2_000))
        tracker.update(snapshot(time_seconds=300.0, map_seed=100, stage_ptr=3000, stage_index=2, stage_time_seconds=140.0, mob_kills=2_600))

        rows = tracker.stage_summary_rows()

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "--")
        self.assertEqual(rows[2]["kills"], "600")
        self.assertEqual(rows[3]["kills"], "--")

    def test_run_identity_promotes_raw_stage_three_attach_to_stage_four_from_chest_total(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        tracker.update(
            snapshot(
                time_seconds=240.0,
                map_seed=100,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=80.0,
                mob_kills=2_000,
                chests_total=15,
            ),
        )

        _, stage_index = tracker.run_identity()
        self.assertEqual(stage_index, 4)

    def test_stage_summary_starts_at_stage_four_when_attach_snapshot_has_collapsed_pots_total(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=240.0,
                map_seed=100,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=80.0,
                mob_kills=2_000,
                pots_total=5,
            ),
        )
        tracker.update(
            snapshot(
                time_seconds=300.0,
                map_seed=100,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=140.0,
                mob_kills=2_600,
                pots_total=5,
            ),
        )

        rows = tracker.stage_summary_rows()

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "--")
        self.assertEqual(rows[2]["kills"], "--")
        self.assertEqual(rows[3]["kills"], "600")

    def test_expected_key_procs_accumulate_sampled_probabilities(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        tracker.track_expected_key_procs(0, 10)
        tracker.track_expected_key_procs(2, 10)
        tracker.track_expected_key_procs(3, 20)
        stats = tracker.get_chest_stats()

        self.assertTrue(stats.expected_available)
        self.assertEqual(stats.expected_tracked_opens, 3)
        self.assertAlmostEqual(stats.expected_key_procs, 5.0 / 3.0)
        self.assertEqual(stats.keys_count, 20)

    def test_expected_key_procs_use_key_dropped_by_same_chest(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        tracker.track_expected_key_procs(0, 0)
        tracker.track_expected_key_procs(1, 1)

        stats = tracker.get_chest_stats()
        self.assertAlmostEqual(stats.expected_key_procs, 1.0 / 11.0)

    def test_expected_key_procs_are_unavailable_when_tracking_starts_mid_run(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        tracker.track_expected_key_procs(12, 10)
        tracker.track_expected_key_procs(13, 10)

        stats = tracker.get_chest_stats()
        self.assertFalse(stats.expected_available)
        self.assertEqual(stats.expected_tracked_opens, 1)

    def test_expected_key_procs_reset_when_run_counter_rolls_back(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.track_expected_key_procs(0, 10)
        tracker.track_expected_key_procs(4, 10)

        tracker.track_expected_key_procs(0, 2)
        tracker.track_expected_key_procs(1, 2)
        stats = tracker.get_chest_stats()

        self.assertTrue(stats.expected_available)
        self.assertEqual(stats.expected_tracked_opens, 1)
        self.assertAlmostEqual(stats.expected_key_procs, 1.0 / 6.0)

    def test_full_run_reset_preserves_expected_data_after_fast_counter_reset(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.track_expected_key_procs(20, 10)
        tracker.track_expected_key_procs(0, 4)
        tracker.track_expected_key_procs(1, 4)

        tracker._reset_for_new_run()
        stats = tracker.get_chest_stats()

        self.assertTrue(stats.expected_available)
        self.assertEqual(stats.expected_tracked_opens, 1)
        self.assertAlmostEqual(stats.expected_key_procs, 2.0 / 7.0)

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

    def test_powerups_summary_formats_active_effects_with_stage_timer(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=440.0,
                stage_index=1,
                stage_time_seconds=540.0,
                powerup_multiplier=1.5,
                powerup_multiplier_display="1.5x",
                effects=(
                    SimpleNamespace(
                        effect_id=1,
                        name="Rage",
                        added_time=999.0,
                        expiration_time=1022.5,
                    ),
                    SimpleNamespace(
                        effect_id=4,
                        name="Clock",
                        added_time=1004.0,
                        expiration_time=1018.0,
                    ),
                ),
            ),
            map_context=self.non_graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Rage 01:41 -> 01:17 (22s left) | Clock 01:40 -> 01:22 (18s left) | Durations: standard 22s, clock 18s (PM 1.5x)",
        )

    def test_powerups_summary_uses_duration_fallback_when_none_active(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=440.0,
                stage_index=1,
                stage_time_seconds=540.0,
                powerup_multiplier=1.5,
                powerup_multiplier_display="1.5x",
                effects=(),
            ),
            map_context=self.non_graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: none active | Durations: standard 22s, clock 18s (PM 1.5x)",
        )

    def test_powerups_summary_formats_overtime(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=550.0,
                stage_index=1,
                stage_time_seconds=540.0,
                powerup_multiplier=1.0,
                powerup_multiplier_display="1x",
                effects=(
                    SimpleNamespace(
                        effect_id=2,
                        name="Shield",
                        added_time=1000.0,
                        expiration_time=1015.0,
                    ),
                ),
            ),
            map_context=self.non_graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield +00:10 -> +00:25 (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def test_powerups_summary_prefers_added_time_over_current_multiplier(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=440.0,
                stage_index=1,
                stage_time_seconds=540.0,
                powerup_multiplier=3.0,
                powerup_multiplier_display="3x",
                effects=(
                    SimpleNamespace(
                        effect_id=2,
                        name="Shield",
                        added_time=995.0,
                        expiration_time=1015.0,
                    ),
                ),
            ),
            map_context=self.non_graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield 01:45 -> 01:25 (15s left) | Durations: standard 45s, clock 36s (PM 3x)",
        )

    def test_powerups_summary_skips_malformed_effects(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=440.0,
                stage_index=1,
                stage_time_seconds=540.0,
                powerup_multiplier=1.5,
                powerup_multiplier_display="1.5x",
                effects=(
                    SimpleNamespace(
                        effect_id=1,
                        name="Rage",
                        expiration_time="not-a-float",
                    ),
                    SimpleNamespace(
                        effect_id=4,
                        name="Clock",
                        expiration_time=1018.0,
                    ),
                ),
            ),
            map_context=self.non_graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Clock 01:40 -> 01:22 (18s left) | Durations: standard 22s, clock 18s (PM 1.5x)",
        )

    def test_powerups_summary_uses_final_swarm_timer_for_graveyard_ghost_phase(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=1000.0,
                stage_index=0,
                chests_total=69,
                pots_total=None,
            ),
        )
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=771.0,
                stage_index=0,
                stage_time_seconds=600.0,
                final_swarm_timer_seconds=170.0,
                crypt_timer_seconds=39.0,
                powerup_multiplier=1.0,
                powerup_multiplier_display="1x",
                effects=(
                    SimpleNamespace(
                        effect_id=2,
                        name="Shield",
                        added_time=990.0,
                        expiration_time=1015.0,
                    ),
                ),
            ),
            map_context=self.graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield +02:40 -> +03:05 (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def test_powerups_summary_uses_graveyard_stage_limit_before_final_swarm(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=1000.0,
                stage_index=0,
                chests_total=69,
                pots_total=None,
            ),
        )
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=771.0,
                stage_index=0,
                stage_time_seconds=600.0,
                final_swarm_timer_seconds=0.0,
                crypt_timer_seconds=0.0,
                powerup_multiplier=1.0,
                powerup_multiplier_display="1x",
                effects=(
                    SimpleNamespace(
                        effect_id=2,
                        name="Shield",
                        added_time=990.0,
                        expiration_time=1015.0,
                    ),
                ),
            ),
            map_context=self.graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield 03:19 -> 02:54 (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def test_powerups_summary_uses_safe_format_for_graveyard_crypt_phase(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=0.0,
                stage_index=0,
                stage_time_seconds=600.0,
                final_swarm_timer_seconds=0.0,
                crypt_timer_seconds=76.0,
                powerup_multiplier=1.0,
                powerup_multiplier_display="1x",
                effects=(
                    SimpleNamespace(
                        effect_id=2,
                        name="Shield",
                        added_time=990.0,
                        expiration_time=1015.0,
                    ),
                ),
            ),
            map_context=self.graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def test_powerups_summary_uses_safe_format_without_fresh_map_context(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=440.0,
                stage_index=1,
                stage_time_seconds=540.0,
                powerup_multiplier=1.0,
                powerup_multiplier_display="1x",
                effects=(
                    SimpleNamespace(
                        effect_id=2,
                        name="Shield",
                        added_time=1000.0,
                        expiration_time=1015.0,
                    ),
                ),
            )
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def test_powerup_map_context_detects_graveyard_from_strong_markers(self) -> None:
        self.assertTrue(PowerupMapContext.from_activity_max({"Pumpkin": 105}).is_graveyard)
        self.assertTrue(PowerupMapContext.from_activity_max({"Gravestones": 22}).is_graveyard)
        self.assertTrue(PowerupMapContext.from_activity_max({"Crypt Chests": 6}).is_graveyard)
        self.assertTrue(PowerupMapContext.from_activity_max({"Crypt Pots": 25}).is_graveyard)
        self.assertTrue(PowerupMapContext.from_activity_max({"Chests": 69}).is_graveyard)
        self.assertFalse(PowerupMapContext.from_activity_max({"Chests": 46}).is_graveyard)
        self.assertFalse(PowerupMapContext.from_activity_max({"Pots": 55}).is_graveyard)


if __name__ == "__main__":
    unittest.main()
