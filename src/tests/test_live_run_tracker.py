from __future__ import annotations

import src

import unittest
from dataclasses import replace
from types import SimpleNamespace

from core.tracker.live_run import (
    FeatureAvailability,
    LiveRunSnapshot,
    LiveRunTracker,
    PowerupMapContext,
    TrackedItemRule,
)
from core.stats.formats import PlayerStatFormat
from core import run_summary
from projections.vod import build_vod_capture_kwargs


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

    def graveyard_crypt_context(self) -> PowerupMapContext:
        return PowerupMapContext.from_activity_max(
            {"Crypt Chests": 6, "Crypt Pots": 25},
            captured_at=1000.0,
        )

    def graveyard_boss_room_context(self) -> PowerupMapContext:
        # Boss-room activity has no strong Graveyard marker by itself. The
        # tracker keeps the identity established by the preceding outdoor read.
        return PowerupMapContext.from_activity_max(
            {"Boss Curses": 8, "Chests": 4},
            captured_at=1000.0,
        )

    def test_vod_projection_keeps_last_known_optional_values_after_failed_read(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        weapon = SimpleNamespace(name="Bone")
        tome = SimpleNamespace(name="Damage")
        damage = SimpleNamespace(source_name="Bone", damage=123.0)
        tracker.update(
            LiveRunSnapshot(
                captured_at=1000.0,
                stats={},
                game_time_seconds=10.0,
                items=("Wrench x2",),
                items_available=False,
                weapons=(weapon,),
                weapons_available=False,
                tomes=(tome,),
                tomes_available=False,
                banishes=("Clover",),
                damage_sources=(damage,),
                damage_sources_available=False,
            )
        )

        values = build_vod_capture_kwargs(tracker.runtime_snapshot())

        self.assertEqual(values["items"], ("Wrench x2",))
        self.assertEqual(values["weapons"], (weapon,))
        self.assertEqual(values["tomes"], (tome,))
        self.assertEqual(values["banishes"], ("Clover",))
        self.assertEqual(values["damage_sources"], (damage,))

    def test_tracker_counts_anvil_map_one_only_before_stage_transition(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0))
        tracker.update(snapshot(time_seconds=20.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=180.0, items=("Anvil x1",), stage_ptr=2000, stage_time_seconds=1.0))
        tracker.update(snapshot(time_seconds=190.0, items=("Anvil x2",), stage_ptr=2000, stage_time_seconds=10.0))
        tracker.update(snapshot(time_seconds=200.0, items=("Anvil x2",), stage_ptr=2000, stage_time_seconds=20.0))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_map_1"]["count"], 1)
        self.assertEqual(rows["anvils_total"]["count"], 2)

    def test_tracker_counts_stack_delta_as_multiple_items(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x3",)))
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x3",)))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_map_1"]["count"], 3)
        self.assertEqual(rows["anvils_total"]["count"], 3)

    def test_tracker_waits_for_next_snapshot_before_counting_positive_increase(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x2",)))

        pending_rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(pending_rows["anvils_total"]["count"], 1)

        tracker.update(snapshot(time_seconds=4.0, items=("Anvil x2",)))

        confirmed_rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(confirmed_rows["anvils_total"]["count"], 2)

    def test_tracker_discards_single_snapshot_positive_spike(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x258",)))
        tracker.update(snapshot(time_seconds=4.0, items=("Anvil x1",)))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_total"]["count"], 1)

    def test_tracker_replaces_unconfirmed_initial_spike_with_stable_count(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x258",)))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",)))

        pending_rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(pending_rows["anvils_total"]["count"], 0)

        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",)))

        confirmed_rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(confirmed_rows["anvils_total"]["count"], 1)

    def test_tracker_does_not_double_count_after_transient_item_drop(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, items=("Anvil x2",)))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x2",)))
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=4.0, items=("Anvil x2",)))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_total"]["count"], 2)

    def test_tracker_counts_late_first_snapshot_for_map_one_counter_while_still_on_first_map(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=30.0, items=("Anvil x2",)))
        tracker.update(snapshot(time_seconds=31.0, items=("Anvil x2",)))

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
        tracker.update(
            snapshot(
                time_seconds=121.0,
                items=("Anvil x2",),
                stage_ptr=2000,
                stage_time_seconds=6.0,
            )
        )

        row = {row["id"]: row for row in tracker.tracked_item_rows()}["anvils_map_1"]
        self.assertEqual(row["count"], 0)

    def test_tracker_accepts_early_first_snapshot_for_map_one_counter(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=5.0, items=("Anvil x2",)))
        tracker.update(snapshot(time_seconds=6.0, items=("Anvil x2",)))

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
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",)))
        run_id = tracker.run_id
        tracker.update(snapshot(time_seconds=2.0, items=(), map_seed=200))

        self.assertNotEqual(tracker.run_id, run_id)
        self.assertEqual(len(tracker.snapshots), 1)
        self.assertEqual({row["id"]: row for row in tracker.tracked_item_rows()}["anvils_total"]["count"], 1)

    def test_tracker_counts_new_run_items_into_session_total(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",), map_seed=100))
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",), map_seed=100))
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x2",), map_seed=200))
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x2",), map_seed=200))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["anvils_map_1"]["count"], 3)
        self.assertEqual(rows["anvils_total"]["count"], 3)

    def test_tracker_keeps_counts_when_same_rules_are_reapplied(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=2.0, items=("Anvil x1",)))
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1",)))
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
        tracker.update(snapshot(time_seconds=3.0, items=("Anvil x1", "Soul Harvester x2")))

        tracker.set_tracked_item_rules((soul_rule,))

        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertNotIn("anvil_map_1", rows)
        self.assertEqual(rows["soul_harvester_map_1"]["count"], 2)

        tracker.update(snapshot(time_seconds=4.0, items=("Anvil x1", "Soul Harvester x3")))
        tracker.update(snapshot(time_seconds=5.0, items=("Anvil x1", "Soul Harvester x3")))
        rows = {row["id"]: row for row in tracker.tracked_item_rows()}
        self.assertEqual(rows["soul_harvester_map_1"]["count"], 3)

    def test_tracker_marks_state_stale_after_missing_updates(self) -> None:
        now = [1000.0]
        tracker = LiveRunTracker(
            clock=lambda: now[0],
            stale_after_seconds=5.0,
            reconnect_grace_seconds=0.0,
        )
        tracker.update(snapshot(time_seconds=1.0))
        self.assertEqual(tracker.status(), "live")
        now[0] = 1007.0
        self.assertEqual(tracker.status(), "stale")

    def test_tracker_reports_reconnecting_inside_the_restart_grace_window(self) -> None:
        now = [1000.0]
        tracker = LiveRunTracker(
            clock=lambda: now[0],
            stale_after_seconds=5.0,
            reconnect_grace_seconds=10.0,
        )
        tracker.update(snapshot(time_seconds=1.0))

        now[0] = 1004.0
        self.assertEqual(tracker.status(), "live")
        # Past the stale window but inside the grace window: a game restart, not
        # something the overlay should announce.
        now[0] = 1007.0
        self.assertEqual(tracker.status(), "reconnecting")
        now[0] = 1015.0
        self.assertEqual(tracker.status(), "reconnecting")
        # Past the grace window the silence is worth reporting.
        now[0] = 1016.0
        self.assertEqual(tracker.status(), "stale")

        # A resumed feed leaves the quiet state immediately.
        tracker.update(snapshot(time_seconds=2.0))
        self.assertEqual(tracker.status(), "live")

    def test_reconnecting_never_masks_a_lost_game_process(self) -> None:
        now = [1000.0]
        tracker = LiveRunTracker(clock=lambda: now[0], stale_after_seconds=5.0)
        tracker.update(snapshot(time_seconds=1.0))
        now[0] = 1006.0
        tracker.mark_read_failed(no_game=True)
        self.assertEqual(tracker.status(), "no_game")

    def test_runtime_snapshot_is_coherent_and_records_feature_status(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=1.0, mob_kills=10))

        runtime = tracker.runtime_snapshot()

        self.assertEqual(runtime.current_stage_index, 1)
        self.assertEqual(runtime.latest_snapshot.mob_kills, 10)
        self.assertEqual(runtime.feature_status["player"].availability, FeatureAvailability.FRESH)
        self.assertEqual(runtime.feature_status["combat"].availability, FeatureAvailability.FRESH)

    def test_completed_run_keeps_latest_snapshot_until_next_run(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=20.0, map_seed=1))
        completed_snapshot = tracker.latest_snapshot()
        tracker.mark_run_completed()

        self.assertEqual(tracker.runtime_snapshot().lifecycle.value, "completed")
        self.assertEqual(tracker.latest_snapshot(), completed_snapshot)

        tracker.update(snapshot(time_seconds=1.0, map_seed=2))
        self.assertEqual(tracker.runtime_snapshot().lifecycle.value, "active")

    def test_current_kps_clears_when_game_disappears(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_fast_run_timer(10.0)
        tracker.track_kills(10.0, 100)
        tracker.update_fast_run_timer(13.0)
        tracker.track_kills(13.0, 160)

        self.assertEqual(tracker.current_kps(), 20)

        tracker.mark_read_failed(no_game=True)

        self.assertIsNone(tracker.current_kps())

    def test_current_ui_kps_uses_valid_one_second_tick(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_fast_run_timer(100.0)
        tracker.track_kills(100.0, 1_000)
        tracker.update_fast_run_timer(100.5)
        tracker.track_kills(100.5, 1_100)
        self.assertIsNone(tracker.current_ui_kps())

        tracker.update_fast_run_timer(101.0)

        tracker.track_kills(101.0, 1_300)

        self.assertEqual(tracker.current_ui_kps(), 300)

    def test_current_ui_kps_ignores_tiny_timer_jump_after_pause(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_fast_run_timer(586.522217)
        tracker.track_kills(586.522217, 48_349)
        tracker.update_fast_run_timer(586.522217)
        tracker.track_kills(586.522217, 48_349)
        tracker.update_fast_run_timer(586.770508)
        tracker.track_kills(586.770508, 48_462)

        self.assertIsNone(tracker.current_ui_kps())
        self.assertEqual(tracker.current_kps(), 455)

    def test_track_kills_does_not_bloat_history_while_game_is_paused(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_fast_run_timer(586.522217)
        tracker.track_kills(586.522217, 48_349)
        tracker.update_fast_run_timer(586.522217)
        tracker.track_kills(586.522217, 48_349)
        tracker.update_fast_run_timer(586.522217)
        tracker.track_kills(586.522217, 48_360)
        tracker.update_fast_run_timer(586.522217)
        tracker.track_kills(586.522217, 48_360)

        self.assertEqual(len(tracker._recent_kills_history), 1)
        self.assertEqual(tracker._recent_kills_history[-1], (586.522217, 48_360))

    def test_stage_summary_uses_latest_fast_combat_sample_for_time_and_kills(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=10.0, mob_kills=100, items=("Anvil x1",)))
        items_before_fast_sample = tracker.stage_summary_rows()[0]["items"]

        tracker.update_fast_run_timer(19.8)

        tracker.track_kills(19.8, 275)

        rows = tracker.stage_summary_rows()

        self.assertEqual(rows[0]["time"], "00:19")
        self.assertEqual(rows[0]["kills"], "275")
        self.assertEqual(rows[0]["items"], items_before_fast_sample)

    def test_stage_summary_does_not_apply_fast_sample_from_before_full_snapshot(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(snapshot(time_seconds=10.0, mob_kills=100))
        tracker.update_fast_run_timer(12.0)
        tracker.track_kills(12.0, 125)
        tracker.update(snapshot(time_seconds=20.0, mob_kills=200))

        rows = tracker.stage_summary_rows()

        self.assertEqual(rows[0]["time"], "00:20")
        self.assertEqual(rows[0]["kills"], "200")

    def test_fast_stage_index_closes_stage_summary_at_fast_combat_sample(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=100.0,
                mob_kills=1_000,
                stage_index=0,
                stage_time_seconds=100.0,
            )
        )
        tracker.update_fast_run_timer(105.0)
        tracker.track_kills(105.0, 1_075)

        tracker.update_fast_stage_timer(
            stage_timer_seconds=1.0,
            stage_index=1,
            stage_duration_seconds=600.0,
        )
        tracker.update_fast_stage_timer(
            stage_timer_seconds=2.0,
            stage_index=1,
            stage_duration_seconds=600.0,
        )

        _, stage_index = tracker.run_identity()
        rows = tracker.stage_summary_rows()
        self.assertEqual(stage_index, 2)
        self.assertEqual(rows[0]["time"], "01:45")
        self.assertEqual(rows[0]["kills"], "1,075")
        self.assertEqual(rows[1]["time"], "00:00")
        self.assertEqual(rows[1]["kills"], "0")

    def test_fast_stage_transition_commits_first_candidate_kill_boundary(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=100.0,
                mob_kills=10_000,
                stage_index=0,
                stage_time_seconds=100.0,
            )
        )
        tracker.update_fast_run_timer(110.0)
        tracker.track_kills(110.0, 11_730)

        tracker.update_fast_stage_timer(
            stage_timer_seconds=1.0,
            stage_index=1,
            stage_duration_seconds=600.0,
        )
        tracker.update_fast_run_timer(111.0)
        tracker.track_kills(111.0, 11_780)
        tracker.update_fast_stage_timer(
            stage_timer_seconds=2.0,
            stage_index=1,
            stage_duration_seconds=600.0,
        )
        tracker.update_fast_run_timer(113.0)
        tracker.track_kills(113.0, 11_830)

        rows = tracker.stage_summary_rows()

        self.assertEqual(rows[0]["kills"], "11,730")
        self.assertEqual(rows[1]["kills"], "100")

    def test_explicit_stage_index_transition_does_not_reconcile_gap_into_new_stage(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=100.0,
                mob_kills=10_000,
                stage_index=0,
                stage_time_seconds=100.0,
            )
        )
        tracker.update(
            snapshot(
                time_seconds=110.0,
                mob_kills=11_730,
                stage_index=1,
                stage_time_seconds=6.0,
            )
        )
        tracker.update(
            snapshot(
                time_seconds=113.0,
                mob_kills=11_830,
                stage_index=1,
                stage_time_seconds=9.0,
            )
        )

        rows = tracker.stage_summary_rows()

        self.assertEqual(rows[0]["kills"], "11,730")
        self.assertEqual(rows[1]["kills"], "100")

    def test_fast_stage_four_requires_the_flag_not_the_timer_heuristic(self) -> None:
        # This used to assert the opposite -- that a bare timer collapse promoted
        # on the fast lane -- and that behaviour was the live bug: entering
        # Stage 3 was counted as Stage 4.
        #
        # The heuristics' only defence against an ordinary stage change is that a
        # real boundary loads a new ``stage_ptr`` while the boss room reuses the
        # old one. The fast sample is built with ``replace(latest_snapshot, ...)``
        # and *inherits* the pointer, so that check can never fail here and a
        # merely-old slow snapshot reads as a collapse. On this lane the flag is
        # the signal; the slow lane, where both pointers are real, keeps them.
        def drive(*, is_final_boss_stage: bool) -> int:
            tracker = LiveRunTracker(clock=lambda: 1000.0)
            tracker.update(
                snapshot(
                    time_seconds=500.0,
                    mob_kills=5_000,
                    stage_index=2,
                    stage_time_seconds=500.0,
                )
            )
            tracker.update_fast_run_timer(501.0)
            tracker.track_kills(501.0, 5_050)
            for timer in (1.0, 2.0):
                tracker.update_fast_stage_timer(
                    stage_timer_seconds=timer,
                    stage_index=2,
                    stage_duration_seconds=600.0,
                    is_final_boss_stage=is_final_boss_stage,
                )
            return tracker.run_identity()[1]

        self.assertEqual(drive(is_final_boss_stage=False), 3)
        self.assertEqual(drive(is_final_boss_stage=True), 4)

    def test_fast_stage_transition_survives_transient_timer_read_failure(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=100.0,
                mob_kills=1_000,
                stage_index=0,
                stage_time_seconds=100.0,
            )
        )
        tracker.update_fast_run_timer(105.0)
        tracker.track_kills(105.0, 1_075)
        for stage_time in (1.0, 2.0):
            tracker.update_fast_stage_timer(
                stage_timer_seconds=stage_time,
                stage_index=1,
                stage_duration_seconds=540.0,
            )

        tracker.update_fast_stage_timer(
            stage_timer_seconds=None,
            stage_index=None,
            stage_duration_seconds=None,
        )

        _, stage_index = tracker.run_identity()
        rows = tracker.stage_summary_rows()
        self.assertEqual(stage_index, 2)
        self.assertEqual(rows[0]["kills"], "1,075")
        self.assertEqual(rows[1]["kills"], "0")

    def test_new_run_clears_fast_stage_boundaries_and_context(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=100.0,
                mob_kills=1_000,
                map_seed=1,
                stage_index=0,
                stage_time_seconds=100.0,
            )
        )
        tracker.update_fast_run_timer(105.0)
        tracker.track_kills(105.0, 1_075)
        for stage_time in (1.0, 2.0):
            tracker.update_fast_stage_timer(
                stage_timer_seconds=stage_time,
                stage_index=1,
                stage_duration_seconds=540.0,
            )

        tracker.update(
            snapshot(
                time_seconds=1.0,
                mob_kills=0,
                map_seed=2,
                stage_index=0,
                stage_time_seconds=1.0,
            )
        )

        _, stage_index = tracker.run_identity()
        rows = tracker.stage_summary_rows()
        self.assertEqual(stage_index, 1)
        self.assertEqual(rows[0]["kills"], "0")
        self.assertEqual(rows[1]["kills"], "--")
        self.assertEqual(tracker._fast_stage_boundaries, [])
        self.assertIsNone(tracker.fast_stage_timer_context())

    def test_fast_stage_transition_requires_confirmation(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=100.0,
                mob_kills=1_000,
                stage_index=0,
                stage_time_seconds=100.0,
            )
        )
        tracker.update_fast_run_timer(101.0)
        tracker.track_kills(101.0, 1_010)

        tracker.update_fast_stage_timer(
            stage_timer_seconds=1.0,
            stage_index=2,
            stage_duration_seconds=480.0,
        )

        _, stage_index = tracker.run_identity()
        rows = tracker.stage_summary_rows()
        self.assertEqual(stage_index, 1)
        self.assertEqual(tracker._fast_stage_boundaries, [])
        self.assertEqual(rows[1]["kills"], "--")
        self.assertEqual(rows[2]["kills"], "--")

    def test_current_minute_avg_kps_uses_last_sixty_seconds(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_fast_run_timer(0.0)
        tracker.track_kills(0.0, 0)
        tracker.update_fast_run_timer(10.0)
        tracker.track_kills(10.0, 100)
        tracker.update_fast_run_timer(70.0)
        tracker.track_kills(70.0, 1_300)

        self.assertEqual(tracker.current_minute_avg_kps(), 20)

    def test_current_run_avg_kps_uses_whole_run(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_fast_run_timer(10.0)
        tracker.track_kills(10.0, 100)
        tracker.update_fast_run_timer(70.0)
        tracker.track_kills(70.0, 1_300)

        # 1300 kills / 70 seconds = 18.57 → rounds to 19
        self.assertEqual(tracker.current_run_avg_kps(), 19)

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
        tracker.update(snapshot(time_seconds=41.0, items=("Gloves Power x1",)))

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
                tracker.update(snapshot(time_seconds=41.0, items=(f"{live_name} x1",)))

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
        tracker.update(snapshot(time_seconds=3.0, items=("Kevin x1", "Electric Plug x1"), map_seed=200))

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

    def test_chaos_tracker_recovers_mixed_stacked_rolls_on_late_attach(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        tracker.update_chaos_tome(
            chaos_level=2,
            permanent_modifiers={
                12: (
                    SimpleNamespace(
                        stat_id=12,
                        label="Damage",
                        value=1.210,  # 0.672 + 0.538
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                ),
            },
        )

        chaos = tracker.chaos_tome_snapshot()
        self.assertEqual(tracker.chaos_tome_summary_parts(), ["DMG +121%"])
        self.assertEqual(chaos.stats[0].rolls, 2)

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
        self.assertEqual(rows[2]["time"], "02:20")
        self.assertEqual(rows[3]["kills"], "--")

    def test_stage_summary_late_attach_restores_elapsed_stage_two_time(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=240.0,
                map_seed=200,
                stage_ptr=2000,
                stage_index=1,
                stage_time_seconds=60.0,
                mob_kills=2_000,
            )
        )
        tracker.update_fast_run_timer(243.0)
        tracker.track_kills(243.0, 2_100)

        rows = tracker.stage_summary_rows()

        self.assertEqual(rows[1]["time"], "01:03")

    def test_stage_summary_does_not_backfill_unconfirmed_stage_four_time(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=1_000.0,
                map_seed=300,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=590.0,
                mob_kills=20_000,
            )
        )
        tracker.update_fast_run_timer(1_003.0)
        tracker.track_kills(1_003.0, 20_100)

        rows = tracker.stage_summary_rows()

        self.assertEqual(rows[2]["time"], "00:03")

    def test_stage_summary_late_attach_on_first_map_includes_current_items(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        tracker.update(
            snapshot(
                time_seconds=240.0,
                items=("Za Warudo x2", "Clover x1"),
                map_seed=100,
                stage_ptr=1000,
                stage_index=0,
                stage_time_seconds=240.0,
                mob_kills=2_000,
            )
        )

        rows = tracker.stage_summary_rows()

        self.assertIn(">2</span>", rows[0]["items"])
        self.assertIn(">1</span>", rows[0]["items"])

    def test_stage_summary_late_attach_on_second_map_does_not_include_current_items(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        tracker.update(
            snapshot(
                time_seconds=240.0,
                items=("Za Warudo x2",),
                map_seed=200,
                stage_ptr=2000,
                stage_index=1,
                stage_time_seconds=60.0,
                mob_kills=2_000,
            )
        )

        rows = tracker.stage_summary_rows()

        self.assertEqual(rows[1]["items"], '<span style="color:#98A7BA;">--</span>')

    def test_tracked_stage_three_promotes_on_later_collapsed_map_total(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=1.0,
                map_seed=100,
                stage_ptr=1000,
                stage_index=0,
                stage_time_seconds=1.0,
                mob_kills=10,
                chests_total=46,
            )
        )
        tracker.update(
            snapshot(
                time_seconds=61.0,
                map_seed=200,
                stage_ptr=2000,
                stage_index=1,
                stage_time_seconds=1.0,
                mob_kills=100,
                chests_total=46,
            )
        )
        tracker.update(
            snapshot(
                time_seconds=121.0,
                map_seed=300,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=1.0,
                mob_kills=200,
                chests_total=15,
            )
        )
        tracker.update(
            snapshot(
                time_seconds=181.0,
                map_seed=300,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=61.0,
                mob_kills=300,
                chests_total=15,
            )
        )

        _, stage_index = tracker.run_identity()
        rows = tracker.stage_summary_rows()

        self.assertEqual(stage_index, 4)
        self.assertEqual(rows[2]["kills"], "0")
        self.assertEqual(rows[3]["kills"], "100")

    def test_stage_two_to_three_raw_transition_ignores_stage_four_timer_heuristic(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=1000.0,
                map_seed=22,
                stage_ptr=2000,
                stage_index=1,
                stage_time_seconds=500.0,
                mob_kills=10_000,
            )
        )
        tracker.update(
            snapshot(
                time_seconds=1001.0,
                map_seed=22,
                stage_ptr=2000,
                stage_index=2,
                stage_time_seconds=1.0,
                mob_kills=10_100,
            )
        )

        _, stage_index = tracker.run_identity()
        rows = tracker.stage_summary_rows()

        self.assertEqual(stage_index, 3)
        self.assertEqual(rows[2]["kills"], "0")
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

    def test_run_identity_promotes_raw_stage_three_attach_to_stage_four_from_zero_chest_total(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        tracker.update(
            snapshot(
                time_seconds=240.0,
                map_seed=100,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=80.0,
                mob_kills=2_000,
                chests_total=0,
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

    def test_fast_two_to_three_does_not_flip_to_stage_four_from_stale_map_two_interactables(self) -> None:
        # Regression: after a raw 1 -> 2 (Stage 2 -> Stage 3) transition confirmed
        # via update_fast_stage_timer, the fast_snapshot used to inherit the
        # previous map's ``chests_total``/``pots_total`` from the latest
        # snapshot (map 2 typically has max=1/1 for chests/pots).  On the tick
        # after the boundary was committed, both prev_tracked and current
        # settled at stage 3, and ``looks_like_stage_four_from_map_activity``
        # flipped on the stale <46 / <55 readings, promoting to stage 4 within
        # one second of "Moving to Stage 3".
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=500.0,
                map_seed=200,
                stage_ptr=2000,
                stage_index=1,
                stage_time_seconds=500.0,
                mob_kills=5_000,
                chests_total=1,
                pots_total=1,
            )
        )
        tracker.update_fast_run_timer(501.0)
        tracker.track_kills(501.0, 5_050)

        # Confirm the fast 2 -> 3 boundary.
        tracker.update_fast_stage_timer(
            stage_timer_seconds=1.0,
            stage_index=2,
            stage_duration_seconds=600.0,
        )
        tracker.update_fast_stage_timer(
            stage_timer_seconds=2.0,
            stage_index=2,
            stage_duration_seconds=600.0,
        )
        # Two more ticks with a normally-advancing timer must not promote to 4.
        tracker.update_fast_stage_timer(
            stage_timer_seconds=3.0,
            stage_index=2,
            stage_duration_seconds=600.0,
        )
        tracker.update_fast_stage_timer(
            stage_timer_seconds=4.0,
            stage_index=2,
            stage_duration_seconds=600.0,
        )

        _, stage_index = tracker.run_identity()
        self.assertEqual(stage_index, 3)

    def _stage_three_tracker_on_fast_lane(self) -> LiveRunTracker:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=280.0,
                map_seed=200,
                stage_ptr=2000,
                stage_index=2,
                stage_time_seconds=90.0,
                mob_kills=5_000,
                chests_total=46,
                pots_total=55,
            )
        )
        _, stage_index = tracker.run_identity()
        self.assertEqual(stage_index, 3)
        return tracker

    def test_final_boss_stage_flag_promotes_without_any_side_effect(self) -> None:
        # The flag is the game naming the boss room. It must stand alone: no
        # interactable wipe, no timer collapse, nothing for the heuristics to
        # work with.
        previous = snapshot(
            time_seconds=286.0,
            stage_index=2,
            stage_time_seconds=97.0,
            chests_total=46,
            pots_total=55,
        )
        current = snapshot(
            time_seconds=286.5,
            stage_index=2,
            stage_time_seconds=97.5,
            chests_total=46,
            pots_total=55,
        )
        self.assertEqual(run_summary.resolve_next_stage_index(3, previous, current), 3)

        flagged = replace(current, is_final_boss_stage=True)
        self.assertTrue(run_summary.reports_final_boss_stage(flagged))
        self.assertEqual(run_summary.resolve_next_stage_index(3, previous, flagged), 4)

    def test_final_boss_stage_flag_promotes_a_late_attach(self) -> None:
        # Attaching mid-boss-room has no previous sample to diff against, so the
        # flag is the only signal that works from a single read.
        attach = snapshot(
            time_seconds=300.0,
            stage_index=2,
            stage_time_seconds=42.0,
            chests_total=46,
            pots_total=55,
        )
        self.assertEqual(run_summary.resolve_initial_stage_index(attach), 3)
        self.assertEqual(
            run_summary.resolve_initial_stage_index(replace(attach, is_final_boss_stage=True)),
            4,
        )

    def test_final_boss_stage_flag_is_never_read_as_a_denial(self) -> None:
        # ``False`` covers both "not the boss room" and "the read failed", so a
        # false flag must never veto what the fallback heuristics still see.
        previous = snapshot(
            time_seconds=286.0,
            stage_index=2,
            stage_time_seconds=97.0,
            chests_total=46,
            pots_total=55,
        )
        wiped = snapshot(
            time_seconds=286.5,
            stage_index=2,
            stage_time_seconds=97.5,
            chests_total=4,
            pots_total=6,
        )
        self.assertFalse(run_summary.reports_final_boss_stage(wiped))
        self.assertEqual(run_summary.resolve_next_stage_index(3, previous, wiped), 4)

    def test_fast_lane_flag_promotes_through_a_stuck_desync_veto(self) -> None:
        # The flag needs none of the guards the inferences do, so it also walks
        # straight past the veto that used to strand the whole boss room.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=200.0,
                map_seed=200,
                stage_ptr=2000,
                stage_index=1,
                stage_time_seconds=500.0,
                mob_kills=4_000,
            )
        )
        tracker.update(
            snapshot(
                time_seconds=205.0,
                map_seed=200,
                stage_ptr=2000,
                stage_index=2,
                stage_time_seconds=505.0,
                mob_kills=4_100,
            )
        )
        self.assertIsNotNone(tracker._slow_stage_timer_reset_pending_from)

        for timer in (3.0, 3.5):
            tracker.update_fast_stage_timer(
                stage_timer_seconds=timer,
                stage_index=2,
                stage_duration_seconds=480.0,
                is_final_boss_stage=True,
            )

        self.assertEqual(tracker.run_identity()[1], 4)

    def test_stage_four_transition_survives_frozen_run_clock(self) -> None:
        # The live trace caught the run clock rewinding a fraction
        # (286.086 -> 286.000) and then freezing across the boss intro, over the
        # single sample where the stage timer collapses.  The old strict
        # monotonic guard threw that sample away and the window never reopened.
        previous = snapshot(
            time_seconds=286.086,
            stage_index=2,
            stage_time_seconds=97.092,
        )
        current = snapshot(
            time_seconds=286.0,
            stage_index=2,
            stage_time_seconds=0.0,
        )
        self.assertTrue(
            run_summary.looks_like_stage_four_transition(previous, current)
        )

    def test_stage_four_transition_still_rejects_new_run_clock_reset(self) -> None:
        # Tolerating the fractional dip above must not tolerate a real new run,
        # where the clock falls by hundreds of seconds.
        previous = snapshot(
            time_seconds=600.0,
            stage_index=2,
            stage_time_seconds=97.0,
        )
        current = snapshot(
            time_seconds=1.0,
            stage_index=2,
            stage_time_seconds=0.0,
        )
        self.assertFalse(
            run_summary.looks_like_stage_four_transition(previous, current)
        )

    def test_fast_two_to_three_with_lagging_timer_reset_does_not_flip_to_stage_four(self) -> None:
        # Regression for the second propagation path of the same live bug: the
        # game advances its raw stage index ~1 s before it resets the stage
        # timer (map_monitor_log.jsonl: stage_index_changed at :28.84,
        # timer_dropped 546.3 -> 0.0 at :29.87).  The fast tick that detects the
        # 1 -> 2 index change therefore still carries the previous map's timer,
        # and that sample used to become the committed boundary.  One tick later
        # the real reset arrived and read as a stage-4 timer collapse against
        # the corrupted boundary (same ptr, same seed, timer 500 -> ~1),
        # promoting to Stage 4 within a second of "Moving to Stage 3".
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=500.0,
                map_seed=200,
                stage_ptr=2000,
                stage_index=1,
                stage_time_seconds=500.0,
                mob_kills=5_000,
            )
        )
        tracker.update_fast_run_timer(501.0)
        tracker.track_kills(501.0, 5_050)

        # Desync window: index already reads 2, timer still continues map 2's.
        tracker.update_fast_stage_timer(
            stage_timer_seconds=501.0,
            stage_index=2,
            stage_duration_seconds=600.0,
        )
        tracker.update_fast_run_timer(502.0)
        tracker.track_kills(502.0, 5_060)
        tracker.update_fast_stage_timer(
            stage_timer_seconds=502.0,
            stage_index=2,
            stage_duration_seconds=600.0,
        )
        # The timer finally resets to the new map and advances normally.
        tracker.update_fast_run_timer(503.0)
        tracker.track_kills(503.0, 5_070)
        tracker.update_fast_stage_timer(
            stage_timer_seconds=0.9,
            stage_index=2,
            stage_duration_seconds=600.0,
        )
        tracker.update_fast_run_timer(504.0)
        tracker.track_kills(504.0, 5_080)
        tracker.update_fast_stage_timer(
            stage_timer_seconds=1.9,
            stage_index=2,
            stage_duration_seconds=600.0,
        )

        _, stage_index = tracker.run_identity()
        self.assertEqual(stage_index, 3)

    def test_slow_two_to_three_with_lagging_timer_reset_does_not_flip_to_stage_four(self) -> None:
        # Third propagation path of the same live bug, and the one the two 8b
        # fixes left open: they both guarded the fast tick, but ``update``
        # stores every slow-tick read verbatim.  A sample landing inside the
        # ~1 s index/timer desync window keeps the previous map's stage_time,
        # and one tick later it is the ``previous_snapshot`` that
        # ``looks_like_stage_four_transition`` measures the real reset against
        # (same ptr, same seed, 501 -> 1.0) -- a stage-4 promotion within a
        # second of "Moving to Stage 3".
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=500.0,
                map_seed=200,
                stage_ptr=2000,
                stage_index=1,
                stage_time_seconds=500.0,
                mob_kills=5_000,
            )
        )
        # Desync window: raw index and map identity already advanced, timer not.
        tracker.update(
            snapshot(
                time_seconds=501.0,
                map_seed=300,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=501.0,
                mob_kills=5_010,
            )
        )
        self.assertEqual(tracker.run_identity()[1], 3)
        # The real reset arrives on the next slow tick.
        tracker.update(
            snapshot(
                time_seconds=502.0,
                map_seed=300,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=1.0,
                mob_kills=5_020,
            )
        )

        _, stage_index = tracker.run_identity()
        self.assertEqual(stage_index, 3)

    def test_slow_stage_desync_spanning_two_ticks_still_reaches_stage_four_later(self) -> None:
        # The hold must survive a desync that spans more than one slow tick (at
        # a 500 ms cadence the ~1 s window covers two), and must clear once the
        # reset is observed so a genuine stage 4 -- virtual: same ptr, same raw
        # index, only the timer collapses -- still promotes later in map 3.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update(
            snapshot(
                time_seconds=500.0,
                map_seed=200,
                stage_ptr=2000,
                stage_index=1,
                stage_time_seconds=500.0,
                mob_kills=5_000,
            )
        )
        for offset, stage_time, kills in (
            (0.5, 500.5, 5_005),
            (1.0, 501.0, 5_010),
            (1.5, 1.0, 5_015),
        ):
            tracker.update(
                snapshot(
                    time_seconds=500.0 + offset,
                    map_seed=300,
                    stage_ptr=3000,
                    stage_index=2,
                    stage_time_seconds=stage_time,
                    mob_kills=kills,
                )
            )
        self.assertEqual(tracker.run_identity()[1], 3)

        game_time, stage_time, kills = 501.5, 1.0, 5_015
        for _ in range(120):
            game_time += 1.0
            stage_time += 1.0
            kills += 10
            tracker.update(
                snapshot(
                    time_seconds=game_time,
                    map_seed=300,
                    stage_ptr=3000,
                    stage_index=2,
                    stage_time_seconds=stage_time,
                    mob_kills=kills,
                )
            )
        self.assertEqual(tracker.run_identity()[1], 3)

        tracker.update(
            snapshot(
                time_seconds=game_time + 1.0,
                map_seed=300,
                stage_ptr=3000,
                stage_index=2,
                stage_time_seconds=5.1,
                mob_kills=kills + 10,
            )
        )

        _, stage_index = tracker.run_identity()
        self.assertEqual(stage_index, 4)

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

    def _rage_powerup_read(
        self,
        *,
        my_time: float,
        stage_timer: float,
        expiration_time: float,
        added_time: float = 999.0,
        powerup_multiplier: float = 1.5,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            my_time_seconds=my_time,
            stage_timer_seconds=stage_timer,
            stage_index=1,
            stage_time_seconds=540.0,
            powerup_multiplier=powerup_multiplier,
            powerup_multiplier_display=f"{powerup_multiplier}x",
            effects=(
                SimpleNamespace(
                    effect_id=1,
                    name="Rage",
                    added_time=added_time,
                    expiration_time=expiration_time,
                ),
            ),
        )

    def test_powerups_pickup_mark_survives_repeated_pickups_of_the_same_buff(self) -> None:
        """Re-picking an active buff must not move where it says it started.

        The game refreshes ``expiration_time`` but leaves ``added_time`` at the
        *first* pickup, so the gap between them grows past the sanity window
        that exists to reject records surviving a timer epoch. Rejecting a mark
        we have watched continuously is what made the pickup time jump.
        """
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        context = self.non_graveyard_context()

        # Picked up at my_time 999 with a 1.5x multiplier: 22.5 s of Rage.
        tracker.update_powerups(
            self._rage_powerup_read(
                my_time=1000.0, stage_timer=440.0, expiration_time=1021.5
            ),
            map_context=context,
        )
        first = tracker.powerups_snapshot().active[0].pickup_ui

        # Two refreshes. added_time stays at 999 throughout, so by the last one
        # expiration - added_time is 53.5 s -- well past max(2 * 22.5, 32.5).
        tracker.update_powerups(
            self._rage_powerup_read(
                my_time=1015.0, stage_timer=455.0, expiration_time=1037.5
            ),
            map_context=context,
        )
        tracker.update_powerups(
            self._rage_powerup_read(
                my_time=1030.0, stage_timer=470.0, expiration_time=1052.5
            ),
            map_context=context,
        )
        effect = tracker.powerups_snapshot().active[0]

        self.assertEqual(first, "01:41")
        self.assertEqual(effect.pickup_ui, "01:41")
        self.assertEqual(effect.expires_ui, "00:47")

    def test_powerups_duration_is_frozen_against_a_multiplier_dip(self) -> None:
        """An untouched buff keeps the duration the game already granted it.

        The multiplier is re-read every tick and its cache is busted the moment
        the active set changes, so a single bad frame at 1.0x would re-time a
        buff mid-flight -- shortening it from 22.5 s to 15 s and dragging its
        marks with it.
        """
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        context = self.non_graveyard_context()

        tracker.update_powerups(
            self._rage_powerup_read(
                my_time=1000.0, stage_timer=440.0, expiration_time=1021.5
            ),
            map_context=context,
        )
        tracker.update_powerups(
            self._rage_powerup_read(
                my_time=1001.0,
                stage_timer=441.0,
                expiration_time=1021.5,
                powerup_multiplier=1.0,
            ),
            map_context=context,
        )

        self.assertEqual(tracker.powerups_snapshot().active[0].duration_seconds, 22.5)

    def test_powerups_repeat_pickup_takes_its_duration_from_the_game(self) -> None:
        """A stale multiplier must not decide how long a re-picked buff runs.

        Numbers are lifted from a live run (tick #138 of
        powerup_monitor_log.jsonl): Rage was re-picked while the multiplier
        cache still held 6.538 and memory already said 7.456, so the recorded
        duration came out 98.07 s against the 111.6 s the game had actually
        granted. The multiplier read is only force-refreshed when the *set* of
        active effects changes, and re-picking an already-active buff does not
        change it, so the cache can be a full TTL behind at exactly this
        moment.
        """
        context = self.non_graveyard_context()

        def run(multiplier_at_repickup: float) -> float:
            tracker = LiveRunTracker(clock=lambda: 1000.0)
            tracker.update_powerups(
                self._rage_powerup_read(
                    my_time=681.27,
                    stage_timer=440.0,
                    expiration_time=765.48,
                    added_time=680.85,
                    powerup_multiplier=5.642,
                ),
                map_context=context,
            )
            tracker.update_powerups(
                self._rage_powerup_read(
                    my_time=692.74,
                    stage_timer=451.47,
                    expiration_time=804.31,
                    added_time=680.85,
                    powerup_multiplier=multiplier_at_repickup,
                ),
                map_context=context,
            )
            return tracker.powerups_snapshot().active[0].duration_seconds

        # Stale multiplier: 15 * 6.538 = 98.07 lands below the window the
        # game's own numbers allow, so it is rejected for the lower bound.
        self.assertAlmostEqual(run(6.538), 111.57, places=2)

        # Current multiplier: 15 * 7.456 = 111.84 lands inside the window, so
        # the exact grant value is kept rather than rounded to the bound.
        self.assertAlmostEqual(run(7.456), 111.84, places=2)

    def test_powerups_recent_snapshot_separates_a_late_read_from_an_empty_one(self) -> None:
        """Past the strict TTL the read is still quotable, and says so.

        ``powerups`` empties on the first missed tick, and an empty snapshot is
        indistinguishable from a successful read that found nothing -- which is
        how ``!powerups`` came to announce "none active" over a live buff.
        """
        now = 1000.0
        tracker = LiveRunTracker(clock=lambda: now)
        tracker.update_powerups(
            self._rage_powerup_read(
                my_time=1000.0, stage_timer=440.0, expiration_time=1021.5
            ),
            map_context=self.non_graveyard_context(),
        )

        now = 1002.0  # past POWERUPS_SNAPSHOT_TTL_SECONDS, inside the grace
        runtime = tracker.runtime_snapshot()

        self.assertFalse(runtime.powerups.available)
        self.assertEqual(runtime.powerups.active, ())
        self.assertFalse(runtime.powerups_recent.available)
        self.assertTrue(runtime.powerups_recent.stale)
        self.assertEqual(len(runtime.powerups_recent.active), 1)

        now = 1010.0  # past the grace window too
        self.assertFalse(tracker.runtime_snapshot().powerups_recent.stale)

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

    def test_powerups_snapshot_stays_available_within_ttl_after_last_good_read(self) -> None:
        current_time = 1000.0
        tracker = LiveRunTracker(clock=lambda: current_time)
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
                        effect_id=4,
                        name="Clock",
                        added_time=1004.0,
                        expiration_time=1018.0,
                    ),
                ),
            ),
            map_context=self.non_graveyard_context(),
        )

        current_time = 1001.0

        snapshot = tracker.powerups_snapshot()
        self.assertTrue(snapshot.available)
        self.assertEqual([effect.name for effect in snapshot.active], ["Clock"])

    def test_powerups_snapshot_expires_after_ttl_without_new_reads(self) -> None:
        current_time = 1000.0
        tracker = LiveRunTracker(clock=lambda: current_time)
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
                        effect_id=4,
                        name="Clock",
                        added_time=1004.0,
                        expiration_time=1018.0,
                    ),
                ),
            ),
            map_context=self.non_graveyard_context(),
        )

        current_time = 1001.6

        self.assertFalse(tracker.powerups_snapshot().available)
        self.assertEqual(tracker.format_powerups_summary(), "Powerups: --")

    def test_powerups_reject_partial_snapshot_without_clearing_last_good_state(self) -> None:
        current_time = 1000.0
        tracker = LiveRunTracker(clock=lambda: current_time)
        complete_health = SimpleNamespace(available=True, complete=True, failure_reason=None)
        partial_health = SimpleNamespace(
            available=True,
            complete=False,
            failure_reason="status_effects_partial",
        )
        good_snapshot = SimpleNamespace(
            my_time_seconds=1000.0,
            stage_timer_seconds=440.0,
            stage_index=1,
            stage_time_seconds=540.0,
            powerup_multiplier=1.5,
            powerup_multiplier_display="1.5x",
            effects=(
                SimpleNamespace(
                    effect_id=4,
                    name="Clock",
                    added_time=1000.0,
                    expiration_time=1018.0,
                ),
            ),
            status_effects_health=complete_health,
            timing_health=complete_health,
            multiplier_health=complete_health,
        )
        self.assertTrue(tracker.update_powerups(good_snapshot))

        current_time = 1001.0
        rejected_snapshot = SimpleNamespace(
            my_time_seconds=1001.0,
            stage_timer_seconds=439.0,
            stage_index=1,
            stage_time_seconds=540.0,
            powerup_multiplier=1.5,
            powerup_multiplier_display="1.5x",
            effects=(),
            status_effects_health=partial_health,
            timing_health=complete_health,
            multiplier_health=complete_health,
        )
        self.assertFalse(tracker.update_powerups(rejected_snapshot))

        retained = tracker.powerups_snapshot()
        self.assertEqual([effect.name for effect in retained.active], ["Clock"])
        self.assertEqual(
            tracker.runtime_snapshot().feature_status["powerups"].last_error,
            "status_effects_partial",
        )

    def test_powerups_reject_snapshot_when_multiplier_read_is_unavailable(self) -> None:
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        complete_health = SimpleNamespace(available=True, complete=True, failure_reason=None)
        partial_health = SimpleNamespace(
            available=False,
            complete=False,
            failure_reason="powerup_multiplier_unavailable",
        )
        active_snapshot = SimpleNamespace(
            my_time_seconds=1000.0,
            stage_timer_seconds=440.0,
            stage_index=1,
            stage_time_seconds=540.0,
            powerup_multiplier=1.5,
            powerup_multiplier_display="1.5x",
            effects=(
                SimpleNamespace(
                    effect_id=4,
                    name="Clock",
                    added_time=1000.0,
                    expiration_time=1018.0,
                ),
            ),
            status_effects_health=complete_health,
            timing_health=complete_health,
            multiplier_health=complete_health,
        )
        tracker.update_powerups(active_snapshot)

        active_snapshot.multiplier_health = partial_health
        self.assertFalse(tracker.update_powerups(active_snapshot))
        self.assertEqual([effect.name for effect in tracker.powerups_snapshot().active], ["Clock"])

        empty_snapshot = SimpleNamespace(
            my_time_seconds=1002.0,
            stage_timer_seconds=438.0,
            stage_index=1,
            stage_time_seconds=540.0,
            powerup_multiplier=1.5,
            powerup_multiplier_display="1.5x",
            effects=(),
            status_effects_health=complete_health,
            timing_health=complete_health,
            multiplier_health=complete_health,
        )
        self.assertTrue(tracker.update_powerups(empty_snapshot))
        self.assertEqual(tracker.powerups_snapshot().active, ())

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

    def test_powerups_summary_ignores_stale_added_time_from_previous_timer_epoch(self) -> None:
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
                powerup_multiplier=3.0,
                powerup_multiplier_display="3x",
                effects=(
                    SimpleNamespace(
                        effect_id=2,
                        name="Shield",
                        added_time=600.0,
                        expiration_time=1045.0,
                    ),
                ),
            ),
            map_context=self.graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield +02:50 -> +03:35 (45s left) | Durations: standard 45s, clock 36s (PM 3x)",
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

    def test_powerups_summary_uses_final_swarm_clock_in_graveyard_post_boss_outdoors(self) -> None:
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
            map_context=self.graveyard_crypt_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def test_powerups_summary_uses_seconds_in_crypt_for_effect_picked_up_before_entering(self) -> None:
        # A crypt has no meaningful stage clock (the stage timer is frozen near
        # zero), so an effect picked up before entering used to be rendered
        # against it and came out as nonsense -- "Shield 17:00 -> 15:05" for an
        # effect with 15 s left. Being in the crypt is what decides the format,
        # not when the effect was picked up.
        # duration 15 * 7.61 = 114.15 s puts the pickup well before the crypt
        # window (1000 - 76 = 924), which is what used to fall through.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=0.0,
                stage_index=0,
                stage_time_seconds=960.0,
                final_swarm_timer_seconds=0.0,
                crypt_timer_seconds=76.0,
                powerup_multiplier=7.61,
                powerup_multiplier_display="7.61x",
                effects=(
                    SimpleNamespace(
                        effect_id=2,
                        name="Shield",
                        added_time=900.0,
                        expiration_time=1015.0,
                    ),
                ),
            ),
            map_context=self.graveyard_crypt_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield (15s left) | Durations: standard 114s, clock 91s (PM 7.61x)",
        )

    def test_powerups_summary_keeps_stage_times_outside_crypt_while_crypt_timer_lingers(self) -> None:
        # Guards the other side of the fix above: `crypt_timer` stays non-zero
        # after leaving a crypt, so it cannot mean "in a crypt" by itself. With
        # the stage timer running again the stage-limit format must come back,
        # otherwise the whole graveyard map would lose its times.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=300.0,
                stage_index=0,
                stage_time_seconds=960.0,
                final_swarm_timer_seconds=0.0,
                crypt_timer_seconds=76.0,
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
            map_context=self.graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield 11:00 -> 10:45 (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def _fast_fallback_snapshot(self, **overrides):
        base = dict(
            my_time_seconds=1000.0,
            stage_timer_seconds=300.0,
            run_timer_seconds=300.0,
            stage_index=2,
            stage_time_seconds=600.0,
            final_swarm_timer_seconds=0.0,
            crypt_timer_seconds=0.0,
            is_final_boss_stage=False,
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
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_powerups_fallback_in_forest_boss_room_from_is_final_boss_stage(self) -> None:
        # Forest/Desert boss room: MapController.isFinalBossStage is the game's
        # own flag. Without it a non-graveyard map shows stage marks; the flag
        # alone must switch to seconds-only. Tamper guard: the negative case
        # proves the flag, not the map, is what suppresses the marks.
        def run(is_final_boss_stage: bool) -> str:
            tracker = LiveRunTracker(clock=lambda: 1000.0)
            tracker.update_powerups(
                self._fast_fallback_snapshot(is_final_boss_stage=is_final_boss_stage),
                map_context=self.non_graveyard_context(),
            )
            return tracker.format_powerups_summary()

        self.assertNotIn("->", run(True))
        self.assertIn("->", run(False))

    def test_powerups_fallback_from_crypt_timer_delta_before_activity_dict_updates(self) -> None:
        # Entering a crypt, the activity dictionary still reads outdoor for up
        # to its 10 s slow tick, but crypt_timer advances every fast tick. The
        # delta must switch to seconds-only immediately, without the dict.
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        def push(crypt_timer: float) -> str:
            tracker.update_powerups(
                self._fast_fallback_snapshot(
                    stage_index=0,
                    stage_time_seconds=960.0,
                    crypt_timer_seconds=crypt_timer,
                ),
                map_context=self.graveyard_context(),
            )
            return tracker.format_powerups_summary()

        # No previous reading yet -> not advancing -> outdoor marks.
        self.assertIn("->", push(40.0))
        # Advanced since last tick -> fallback, despite the stale outdoor dict.
        self.assertNotIn("->", push(40.5))

    def test_powerups_keeps_marks_when_crypt_timer_frozen_outdoors(self) -> None:
        # crypt_timer retains its last value outdoors (measured frozen at ~70.7
        # across the whole main map). Two ticks at the SAME non-zero reading
        # must NOT read as "in a crypt" -- only an advancing timer does. Guards
        # against a naive ``crypt_timer > 0`` implementation.
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        def push() -> str:
            tracker.update_powerups(
                self._fast_fallback_snapshot(
                    stage_index=0,
                    stage_time_seconds=960.0,
                    crypt_timer_seconds=70.7,
                ),
                map_context=self.graveyard_context(),
            )
            return tracker.format_powerups_summary()

        push()
        self.assertIn("->", push())

    def test_powerups_fallback_in_graveyard_boss_room_from_is_fighting_boss(self) -> None:
        # The Graveyard boss room keeps the full outdoor activity set, so the
        # dictionary cannot tell it from the main map; only the RSG flag can.
        # isFinalBossStage reads False here, so this is the Graveyard-only path.
        def run(fighting: bool) -> str:
            tracker = LiveRunTracker(clock=lambda: 1000.0)
            tracker.update_powerups(
                self._fast_fallback_snapshot(
                    stage_index=0,
                    stage_time_seconds=960.0,
                    stage_timer_seconds=590.0,
                    graveyard_boss_fighting=fighting,
                ),
                map_context=self.graveyard_context(),
            )
            return tracker.format_powerups_summary()

        self.assertNotIn("->", run(True))
        self.assertIn("->", run(False))

    def test_powerups_post_kill_gap_is_fallback_then_overtime_shows_marks(self) -> None:
        # isFightingBoss drops at the kill; isBossDefeated latches. In the ~10 s
        # gap before the swarm timer starts (final_swarm == 0, stage_timer
        # jumped to ~590) the latch holds fallback so no nonsense marks show.
        # The moment overtime begins (final_swarm > 0) the latch stops forcing
        # fallback and the post-boss ghost phase renders +MM:SS, like the
        # pre-boss ghost phase -- both ghost phases are overtime.
        tracker = LiveRunTracker(clock=lambda: 1000.0)

        def push(final_swarm: float, defeated: bool) -> str:
            tracker.update_powerups(
                self._fast_fallback_snapshot(
                    stage_index=0,
                    stage_time_seconds=960.0,
                    stage_timer_seconds=590.0,
                    final_swarm_timer_seconds=final_swarm,
                    graveyard_boss_fighting=False,
                    graveyard_boss_defeated=defeated,
                ),
                map_context=self.graveyard_context(),
            )
            return tracker.format_powerups_summary()

        # Post-kill gap: latched, swarm not started -> fallback.
        self.assertNotIn("->", push(final_swarm=0.0, defeated=True))
        # Overtime running (defeated no longer readable on the main map): the
        # latch releases, overtime marks return.
        overtime = push(final_swarm=30.0, defeated=False)
        self.assertIn("->", overtime)
        self.assertIn("+", overtime)

    def test_powerups_post_boss_latch_is_gated_on_graveyard(self) -> None:
        # A stray isBossDefeated read on another map must not latch: the gate is
        # is_graveyard, so a non-graveyard map ignores it entirely.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            self._fast_fallback_snapshot(graveyard_boss_defeated=True),
            map_context=self.non_graveyard_context(),
        )
        self.assertIn("->", tracker.format_powerups_summary())

    def test_powerups_first_ghost_phase_stays_overtime_not_fallback(self) -> None:
        # The pre-boss main-map ghost phase (16-min expiry) also has final_swarm
        # > 0, but it is the main map, not a boss room: it must keep the overtime
        # marks, NOT collapse to seconds-only. Guards against using final_swarm
        # as a post-boss marker -- only isBossDefeated separates the two ghost
        # phases, and here the boss is not defeated.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            self._fast_fallback_snapshot(
                stage_index=0,
                stage_time_seconds=960.0,
                stage_timer_seconds=965.0,
                final_swarm_timer_seconds=20.0,
                graveyard_boss_fighting=False,
                graveyard_boss_defeated=False,
            ),
            map_context=self.graveyard_context(),
        )
        summary = tracker.format_powerups_summary()
        self.assertIn("->", summary)
        self.assertIn("+", summary)

    def test_powerups_summary_uses_seconds_when_stage_timer_outran_the_run_timer(self) -> None:
        # The boss room replaces outdoor activity with unmarked entries and
        # temporarily fast-forwards the stage clock. The stored Graveyard
        # identity tells us this is a boss room, not a normal map.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerup_map_context(self.graveyard_context())
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=590.27,
                run_timer_seconds=189.99,
                stage_index=0,
                stage_time_seconds=960.0,
                final_swarm_timer_seconds=0.0,
                crypt_timer_seconds=17.79,
                powerup_multiplier=1.0,
                powerup_multiplier_display="1x",
                effects=(
                    SimpleNamespace(
                        effect_id=2,
                        name="Shield",
                        added_time=900.0,
                        expiration_time=1015.0,
                    ),
                ),
            ),
            map_context=self.graveyard_boss_room_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def test_powerups_summary_keeps_stage_times_on_normal_map_after_fast_stage_clock(self) -> None:
        # A fast stage clock alone is not a reason to discard exact times:
        # only the identified Graveyard boss room has that exceptional clock.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=590.27,
                run_timer_seconds=189.99,
                stage_index=0,
                stage_time_seconds=960.0,
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
            map_context=self.non_graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield 06:19 -> 05:54 (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def test_powerups_summary_follows_final_swarm_clock_on_normal_map(self) -> None:
        # FinalSwarm mirrors the UI stage clock on ordinary maps and includes
        # manual time changes, so it must win when it differs from stage_timer.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=600.0,
                stage_index=0,
                stage_time_seconds=960.0,
                final_swarm_timer_seconds=1200.0,
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
            map_context=self.non_graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield +19:50 -> +20:15 (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
        )

    def test_powerups_summary_keeps_stage_times_while_stage_timer_trails_the_run(self) -> None:
        # The other side of the guard: on the graveyard main map the stage timer
        # legitimately trails the run timer (94.66 vs 115.44 as captured), and
        # the 16-minute stage format must survive.
        tracker = LiveRunTracker(clock=lambda: 1000.0)
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=94.66,
                run_timer_seconds=115.44,
                stage_index=0,
                stage_time_seconds=960.0,
                final_swarm_timer_seconds=0.0,
                crypt_timer_seconds=16.94,
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
            map_context=self.graveyard_context(),
        )

        self.assertEqual(
            tracker.format_powerups_summary(),
            "Powerups: Shield 14:25 -> 14:10 (15s left) | Durations: standard 15s, clock 12s (PM 1x)",
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

    def test_powerup_map_context_accessor_respects_ttl(self) -> None:
        now = 1000.0
        tracker = LiveRunTracker(clock=lambda: now)
        context = PowerupMapContext.from_activity_max(
            {"Chests": 69},
            captured_at=now,
        )
        tracker.update_powerup_map_context(context)

        self.assertIsNotNone(tracker.powerup_map_context())

        now += 16.0
        self.assertIsNone(tracker.powerup_map_context())


    def test_graveyard_event_timer_uses_activity_dictionary_and_final_swarm(self) -> None:
        tracker = LiveRunTracker()
        context_gy = PowerupMapContext.from_activity_max({"Chests": 69})
        snap = SimpleNamespace(
            powerup_multiplier=1.0,
            my_time_seconds=250.0,
            stage_timer_seconds=250.0,
            stage_time_seconds=960.0,
            stage_index=2,
            crypt_timer_seconds=76.0,
            final_swarm_timer_seconds=0.0,
            effects=[],
        )

        tracker.update_powerups(snap, map_context=context_gy)
        self.assertTrue(tracker.graveyard_main_map_events_active())

        # A non-zero crypt timer can persist after leaving the crypt.
        snap.crypt_timer_seconds = 120.0
        tracker.update_powerups(snap)
        self.assertTrue(tracker.graveyard_main_map_events_active())

        tracker.update_powerup_map_context(
            PowerupMapContext.from_activity_max({"Chests": 69, "Crypt Chests": 6})
        )
        tracker.update_powerups(snap)
        self.assertFalse(tracker.graveyard_main_map_events_active())

        tracker.update_powerup_map_context(context_gy)
        snap.final_swarm_timer_seconds = 0.1
        tracker.update_powerups(snap)
        self.assertFalse(tracker.graveyard_main_map_events_active())


if __name__ == "__main__":
    unittest.main()
