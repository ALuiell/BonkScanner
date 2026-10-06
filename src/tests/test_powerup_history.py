from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import src  # noqa: F401

from app.active_recording_feed import ActiveRecordingFeed
from app.prepared_recording import prepare_loaded_recording, replace_prepared_metadata
from app.vod_library import VodLibrary
from core.powerup_history import (PowerupHistory, PowerupObservation, RecordedEffect,
                                 observation_from_snapshot)
from core.stats.types import PowerupReadHealth, PowerupTrackingSnapshot, StatusEffectSnapshot
from core.vod_capture import VodCapturePayload
from infra.vod_storage import VodMetadata, VodRecorder, VodSnapshot, load_vod, load_vod_metadata, rename_vod
from projections.powerup_history import PowerupProjection
from tests.support.player_stats import build_recordings_tab
from tests.support.refresh_tasks import build_refresh_tasks
from tests.support.compare_runs import build_compare_runs_tab
from tests.support.vod_capture import build_vod_capture


def observation(at, effects=(), *, my=None, axis=None, valid=True, run="run"):
    return PowerupObservation(float(at), float(at if my is None else my) if valid else None,
                             float(at if axis is None else axis) if valid else None,
                             run, valid, tuple(RecordedEffect(*e) for e in effects))


def history_until(end=20):
    samples = []
    for tick in range(end * 2 + 1):
        at = tick / 2
        effects = []
        if 2 <= at < 10:
            effects.append((1, 2, 10 if at < 6 else 14))
        elif 10 <= at < 14:
            effects.append((1, 2, 14))
        if 5 <= at < 9:
            effects.append((3, 5, 9))
        samples.append(observation(at, effects))
    return PowerupHistory(tuple(samples))


class PowerupProjectionTests(unittest.TestCase):
    def test_cumulative_and_reversed_segment_clip_each_effect(self):
        projection = PowerupProjection(history_until())
        self.assertEqual(projection.totals(4)[1], 2)
        self.assertEqual(projection.totals(20)[1], 12)
        self.assertEqual(projection.totals(20)[3], 4)
        self.assertEqual(projection.totals(8, 4), projection.totals(4, 8))
        self.assertEqual(projection.totals(4, 8)[1], 4)
        self.assertEqual(projection.totals(4, 8)[3], 3)
        self.assertTrue(all(v == 0 for v in projection.totals(8, 8).values()))

    def test_extension_is_not_visible_in_historical_cursor(self):
        projection = PowerupProjection(history_until())
        self.assertEqual(projection.active(4)[0].end_axis, 10)
        self.assertEqual(projection.active(7)[0].end_axis, 14)
        self.assertNotIn("00:14", projection.tooltip(1, 4))
        self.assertEqual(len([s for s in projection.intervals if s.effect_id == 1]), 1)

    def test_incremental_projection_matches_full_and_keeps_previous_immutable(self):
        history = history_until()
        previous = None
        for count in range(1, len(history.observations) + 1):
            partial = PowerupHistory(history.observations[:count])
            updated = PowerupProjection(partial, previous=previous)
            full = PowerupProjection(partial)
            self.assertEqual(updated.intervals, full.intervals)
            self.assertEqual(updated.coverage, full.coverage)
            for capture in (0, 4, 8, 12, 20):
                self.assertEqual(updated.totals(capture), full.totals(capture))
                self.assertEqual(updated.active(capture), full.active(capture))
            if previous is not None:
                self.assertEqual(len(previous.observations), count - 1)
            previous = updated

    def test_finalization_closes_observed_intervals_but_preserves_known_expiry(self):
        samples = tuple(observation(at, ((1, 0, 10),)) for at in (0, 1, 2))
        projection = PowerupProjection(PowerupHistory(samples, finalized=True))
        self.assertEqual(projection.active(1)[0].end_axis, 10)
        self.assertEqual(projection.intervals[0].end_axis, 2)
        self.assertEqual(projection.totals(20)[1], 2)

    def test_zero_range_in_unknown_gap_still_reports_partial_observations(self):
        samples = (observation(0), observation(1, valid=False), observation(2))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertFalse(projection.complete(1, 1))
        self.assertTrue(projection.complete(2, 2))
        self.assertTrue(all(value == 0 for value in projection.totals(1, 1).values()))

    def test_mid_poll_pickup_uses_raw_start_and_expiry(self):
        samples = (observation(0), observation(1, ((2, .25, .75),)))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertEqual(projection.totals(1)[2], .5)
        self.assertEqual(projection.intervals[0].start_axis, .25)

    def test_same_effect_repicked_between_polls_keeps_real_gap(self):
        samples = (observation(0, ((1, 0, .25),)), observation(1, ((1, .5, 2),)))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertEqual(projection.totals(1)[1], .75)
        self.assertEqual(len(projection.intervals), 2)

    def test_repeat_with_new_added_time_does_not_double_count_or_reset_interval_start(self):
        samples = (observation(0, ((1, 0, 2),)), observation(1, ((1, .5, 3),)),
                   observation(2, ((1, .5, 3),)))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertEqual(projection.totals(2)[1], 2)
        self.assertEqual(projection.active(1)[0].start_axis, 0)

    def test_extension_at_expiry_keeps_continuous_time_between_healthy_polls(self):
        samples = (observation(0, ((1, 0, .75),)),
                   observation(.5, ((1, 0, .75),)), observation(1, ((1, 0, 2),)))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertEqual(projection.totals(1)[1], 1)
        self.assertEqual(len(projection.intervals), 1)
        self.assertEqual(projection.active(.5)[0].end_axis, .75)
        self.assertEqual(projection.active(1)[0].end_axis, 2)

    def test_pause_does_not_count_wall_time(self):
        effects = ((4, 100, 110),)
        samples = (observation(0, effects, my=100, axis=0),
                   observation(1, effects, my=101, axis=1),
                   observation(60, effects, my=101, axis=1),
                   observation(61, effects, my=102, axis=2))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertEqual(projection.totals(61)[4], 2)
        self.assertTrue(projection.complete(61))
        self.assertEqual(projection.totals(1, 60)[4], 0)

    def test_frozen_axis_still_counts_effect_clock(self):
        samples = tuple(observation(i, ((4, 0, 5),), axis=0) for i in range(6))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertEqual(projection.totals(5)[4], 5)
        self.assertEqual(projection.intervals[0].start_axis, projection.intervals[0].end_axis)

    def test_boss_transition_micro_rewind_does_not_drop_effect_clock_time(self):
        samples = tuple(observation(i, ((1, 100, 110),), my=100+i, axis=axis)
                        for i, axis in enumerate((286.086, 286.0, 286.0, 287.0)))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertEqual(projection.totals(3)[1], 3)
        self.assertTrue(projection.complete(0, 3))
        self.assertEqual(len(projection.intervals), 1)

    def test_range_tooltip_uses_clock_anchors_inside_merged_interval(self):
        samples = tuple(observation(i, ((1, 0, 10),), axis=axis)
                        for i, axis in enumerate((0, 1, 1, 1, 2)))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertIn('00:01 → 00:01', projection.tooltip(1, 1, 3))
        self.assertEqual(projection.totals(1, 3)[1], 2)

    def test_failed_reads_and_unpolled_gaps_are_unknown(self):
        effects = ((1, 0, 20),)
        samples = (observation(0, effects), observation(1, effects),
                   observation(2, valid=False), observation(3, effects),
                   observation(4, effects), observation(10, effects), observation(11, effects))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertEqual(projection.totals(11)[1], 3)
        self.assertFalse(projection.complete(11))
        self.assertTrue(projection.complete(3, 4))
        self.assertFalse(projection.active(2.5))

    def test_late_start_does_not_invent_past_and_is_partial(self):
        samples = (observation(0, ((1, 50, 200),), my=100, axis=60),
                   observation(1, ((1, 50, 200),), my=101, axis=61))
        projection = PowerupProjection(PowerupHistory(samples))
        self.assertEqual(projection.totals(1)[1], 1)
        self.assertEqual(projection.active(0)[0].start_axis, 60)
        self.assertFalse(projection.complete(1))

    def test_run_boundaries_do_not_bridge(self):
        samples = (observation(0, ((1, 0, 10),)),
                   observation(1, ((1, 0, 10),), run="other"))
        self.assertEqual(PowerupProjection(PowerupHistory(samples)).totals(1)[1], 0)

    def test_pm_failure_does_not_discard_healthy_raw_effects(self):
        snapshot = PowerupTrackingSnapshot(100, 5, 5, 0, 5, None, "",
                    effects=(StatusEffectSnapshot(1, "Rage", 99, 110),),
                    multiplier_health=PowerupReadHealth(available=False, complete=False))
        result = observation_from_snapshot(snapshot, "run", captured_at=1)
        self.assertTrue(result.valid)
        self.assertEqual(result.effects[0].expires, 110)

    def test_partial_effect_read_and_nonfinite_timing_are_unavailable(self):
        snapshot = PowerupTrackingSnapshot(float("nan"), 5, 5, 0, 5, 1, "1x")
        self.assertFalse(observation_from_snapshot(snapshot, "run", captured_at=1).valid)


class PowerupStorageTests(unittest.TestCase):
    def test_roundtrip_does_not_change_snapshot_count_and_rename_keeps_history(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = VodRecorder(vods_dir=Path(directory), clock=lambda: 100)
            path = recorder.start(name="History")
            recorder.capture(VodCapturePayload(stats={}))
            for sample in history_until(3).observations:
                recorder.observe_powerups(sample)
            recorder.stop()
            loaded = load_vod(path)
            self.assertEqual(loaded.metadata.snapshot_count, 1)
            self.assertEqual(load_vod_metadata(path).snapshot_count, 1)
            self.assertEqual(loaded.powerup_history.observations, history_until(3).observations)
            self.assertTrue(loaded.powerup_history.finalized)
            prepared = prepare_loaded_recording(loaded, series_keys=("@powerups", "Difficulty"))
            renamed, vod = replace_prepared_metadata(prepared, loaded, loaded.metadata)
            self.assertIs(vod.powerup_history, loaded.powerup_history)
            self.assertIs(renamed.powerups, prepared.powerups)
            metadata = rename_vod(path, "Renamed")
            self.assertEqual(load_vod(metadata.path).powerup_history, loaded.powerup_history)

    def test_old_recording_history_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.jsonl"
            path.write_text('{"type":"metadata","version":11,"name":"Old"}\n', encoding="utf-8")
            self.assertIsNone(load_vod(path).powerup_history)

    def test_invalid_observation_is_rejected(self):
        record = observation(1).to_record()
        record["effects"] = [[1, 2, 1]]
        with self.assertRaises(ValueError):
            PowerupObservation.from_record(record)

    def test_new_run_sample_does_not_enter_old_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = VodRecorder(vods_dir=Path(directory))
            recorder.start()
            recorder.observe_powerups(observation(1, ((1, 0, 10),)))
            recorder.observe_powerups(observation(2, ((2, 0, 20),), run="new"))
            self.assertFalse(recorder.powerup_history.observations[-1].valid)
            recorder.close()


class PowerupLiveTests(unittest.TestCase):
    def test_capture_publishes_raw_history_and_final_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [100.0]
            recorder = VodRecorder(vods_dir=Path(directory), clock=lambda: now[0])
            recorder.start(name="Capture history")
            recorder.capture(VodCapturePayload(stats={}))
            feed = ActiveRecordingFeed()
            feed.start(recorder.current_metadata())
            service, _ = build_vod_capture(recorder=recorder, active_recording_feed=feed,
                                          clock=lambda: now[0])
            for index in range(3):
                now[0] = 100 + index
                raw = PowerupTrackingSnapshot(index, index, index, 0, index, None, "",
                      effects=(StatusEffectSnapshot(1, "Rage", 0, 10),),
                      timing_health=PowerupReadHealth(captured_at=now[0]))
                service.observe_powerups(raw, "run")
            service.stop_recording(finalize_snapshot=False, refresh_live_stats=False, refresh_library=False)
            self.assertTrue(feed.state_for(recorder.path).powerup_history.finalized)
            self.assertEqual(PowerupProjection(load_vod(recorder.path).powerup_history).totals(102)[1], 2)

    def test_capture_preserves_history_in_memory_on_write_error(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = VodRecorder(vods_dir=Path(directory), clock=lambda: 100)
            recorder.start(name="Write failure")
            feed = ActiveRecordingFeed()
            feed.start(recorder.current_metadata())
            service, world = build_vod_capture(recorder=recorder, active_recording_feed=feed)
            raw = PowerupTrackingSnapshot(1, 1, 1, 0, 1, 1, "1x")
            with patch.object(recorder, "_write_record", side_effect=OSError("disk full")):
                service.observe_powerups(raw, "run")
            self.assertEqual(len(feed.active_state.powerup_history.observations), 1)
            self.assertIn("disk full", world.log[-1][0])
            recorder.close()

    def test_feed_update_keeps_snapshots_and_survives_append_and_finalization_failure(self):
        metadata = VodMetadata(Path("live.jsonl"), "Live", "2026-10-07", 10, 0, 0)
        feed = ActiveRecordingFeed()
        feed.start(metadata)
        original = feed.append(metadata, VodSnapshot(0, 0, {}))
        history = history_until(3)
        updated = feed.update_powerups(history)
        self.assertIs(updated.snapshots, original.snapshots)
        self.assertGreater(updated.revision, original.revision)
        feed.append(metadata, VodSnapshot(10, 10, {}))
        failed = feed.fail_finalize("disk full")
        self.assertIs(failed.loaded_vod.powerup_history, history)

    def test_recording_alone_demands_powerup_poll(self):
        service, _ = build_refresh_tasks(vod_recorder=SimpleNamespace(is_recording=True),
                                        lifecycle=SimpleNamespace(completed_run=False))
        self.assertTrue(service._should_refresh_powerup_tracker())

    def test_history_only_live_revision_reuses_numeric_preparation(self):
        metadata = VodMetadata(Path("live.jsonl"), "Live", "2026-10-07", 10, 0, 0)
        feed = ActiveRecordingFeed()
        feed.start(metadata)
        state = feed.append(metadata, VodSnapshot(0, 0, {}))
        view = build_recordings_tab(active_recording_feed=feed,
                    vod_library=VodLibrary(load_cached=tuple, refresh_index=tuple, active_recording_feed=feed))
        prepared = prepare_loaded_recording(state.loaded_vod, series_keys=view._recording_model_keys())
        view._prepared_recording = prepared
        view._loaded_vod = prepared.vod
        view._snapshot_index = 0
        view._refresh_live_controls = lambda: None
        with patch("ui.tabs.player_stats.recordings.prepare_loaded_recording", side_effect=AssertionError("heavy preparation")):
            view._submit_live_state(feed.update_powerups(history_until(3)))
        self.assertIs(view._prepared_recording.scrubber_model, prepared.scrubber_model)
        self.assertIs(view._prepared_recording.time_index, prepared.time_index)
        self.assertEqual(view._snapshot_index, 0)
        self.assertEqual(view._prepared_recording.powerups.totals(3)[1], 1)

    def test_compare_history_update_reuses_numeric_preparation_and_manual_cursor(self):
        metadata = VodMetadata(Path("live.jsonl"), "Live", "2026-10-07", 10, 0, 0)
        feed = ActiveRecordingFeed()
        feed.start(metadata)
        state = feed.append(metadata, VodSnapshot(0, 0, {}))
        view = build_compare_runs_tab(active_recording_feed=feed,
                    vod_library=VodLibrary(load_cached=tuple, refresh_index=tuple, active_recording_feed=feed))
        prepared = prepare_loaded_recording(state.loaded_vod, series_keys=view._compare_model_keys(),
                                            cap_keys=view._enabled_cap_keys())
        view._prepared_sides["a"] = prepared
        view._vod_a = prepared.vod
        view._index_a = 0
        view._live_follow = False
        view._refresh_compare_live_controls = lambda side: None
        with patch("ui.tabs.compare_runs.tab.prepare_loaded_recording", side_effect=AssertionError("heavy preparation")):
            view._submit_compare_live_state("a", feed.update_powerups(history_until(3)))
        self.assertIs(view._prepared_sides["a"].scrubber_model, prepared.scrubber_model)
        self.assertIs(view._prepared_sides["a"].time_index, prepared.time_index)
        self.assertEqual(view._index_a, 0)

    def test_async_recording_preparation_coalesces_effect_ticks_and_keeps_manual_cursor(self):
        feed, old_state, state = self._live_states_for_async_preparation()
        view = build_recordings_tab(active_recording_feed=feed,
                    vod_library=VodLibrary(load_cached=tuple, refresh_index=tuple, active_recording_feed=feed))
        old = prepare_loaded_recording(old_state.loaded_vod, series_keys=view._recording_model_keys())
        view._loaded_vod = old.vod
        view._prepared_recording = old
        view._snapshot_index = 1
        view._live_follow = False
        view._refresh_live_controls = lambda: None
        view._set_vod_loading_state = lambda _loading: None
        view.refresh_loaded_vod_ui = lambda **_kwargs: None
        view._load_lane.dispose()
        lane = DeferredPreparationLane()
        view._load_lane = lane
        view._schedule = lambda _callback: None
        view._submit_live_state(state)
        latest = feed.update_powerups(history_until(3))
        # A drag caption has advanced, but its throttled detail frame is pending.
        view._requested_snapshot_index = 0
        view._snapshot_throttle = SimpleNamespace(has_pending=True)
        view._submit_live_state(latest)
        self.assertEqual(len(lane.requests), 1)
        prepared = prepare_loaded_recording(state.loaded_vod, revision=state.revision,
                                            series_keys=view._recording_model_keys())
        lane.requests[0][1]['complete'](prepared, None)
        self.assertEqual(view._live_applied_revision, latest.revision)
        self.assertIs(view._prepared_recording.scrubber_model, prepared.scrubber_model)
        self.assertIs(view._loaded_vod.powerup_history, latest.powerup_history)
        self.assertEqual(view._snapshot_index, 0)
        self.assertIsNone(view._live_prepare_request)

    def test_fast_compare_follow_refreshes_diff_only_when_other_snapshot_changes(self):
        metadata = VodMetadata(Path('live.jsonl'), 'Live', '2026-10-07', 10, 0, 0)
        feed = ActiveRecordingFeed()
        feed.start(metadata)
        state = feed.append(metadata, VodSnapshot(0, 0, {}))
        view = build_compare_runs_tab(active_recording_feed=feed,
                    vod_library=VodLibrary(load_cached=tuple, refresh_index=tuple, active_recording_feed=feed))
        prepared = prepare_loaded_recording(state.loaded_vod, series_keys=view._compare_model_keys())
        view._vod_a = prepared.vod
        view._prepared_sides['a'] = prepared
        view._vod_b = SimpleNamespace(metadata=SimpleNamespace(path=Path('other.jsonl')),
                    snapshots=(VodSnapshot(0, 0, {}), VodSnapshot(10, 10, {})))
        view._index_a = view._index_b = 0
        view._live_follow = True
        renders = []
        view._refresh_compare_live_controls = lambda _side: None
        view.refresh_compare_runs_ui = lambda: renders.append(view._index_b)
        view._diff_throttle = SimpleNamespace(request=lambda callback: callback())
        view._timeline = SimpleNamespace(common_duration=10, set_powerups=lambda *_args: None,
                    set_position=lambda *_args: None, nearest_indices=lambda: (0, 1))
        view._submit_compare_live_state('a', feed.update_powerups(history_until(3)))
        view._submit_compare_live_state('a', feed.update_powerups(history_until(4)))
        self.assertEqual(renders, [1])

    def test_async_compare_preparation_coalesces_effect_ticks_and_keeps_manual_cursor(self):
        feed, old_state, state = self._live_states_for_async_preparation()
        view = build_compare_runs_tab(active_recording_feed=feed,
                    vod_library=VodLibrary(load_cached=tuple, refresh_index=tuple, active_recording_feed=feed))
        old = prepare_loaded_recording(old_state.loaded_vod, series_keys=view._compare_model_keys())
        view._vod_a = old.vod
        view._prepared_sides['a'] = old
        view._index_a = 1
        view._live_follow = False
        view._refresh_compare_live_controls = lambda _side: None
        view.refresh_compare_runs_ui = lambda **_kwargs: None
        view._install_prepared_compare_lane = lambda _side, _prepared: None
        view._load_lanes['a'].dispose()
        lane = DeferredPreparationLane()
        view._load_lanes['a'] = lane
        view._schedule = lambda _callback: None
        view._submit_compare_live_state('a', state)
        latest = feed.update_powerups(history_until(3))
        view._index_a = 0
        view._submit_compare_live_state('a', latest)
        self.assertEqual(len(lane.requests), 1)
        prepared = prepare_loaded_recording(state.loaded_vod, revision=state.revision,
                                            series_keys=view._compare_model_keys())
        lane.requests[0][1]['complete'](prepared, None)
        self.assertEqual(view._live_applied_revision['a'], latest.revision)
        self.assertIs(view._prepared_sides['a'].scrubber_model, prepared.scrubber_model)
        self.assertIs(view._vod_a.powerup_history, latest.powerup_history)
        self.assertEqual(view._index_a, 0)
        self.assertIsNone(view._live_requested_revision['a'])
        self.assertIsNone(view._live_prepare_requests['a'])

    @staticmethod
    def _live_states_for_async_preparation():
        metadata = VodMetadata(Path('live.jsonl'), 'Live', '2026-10-07', 10, 0, 0)
        feed = ActiveRecordingFeed()
        feed.start(metadata)
        feed.append(metadata, VodSnapshot(0, 0, {}))
        old = feed.append(metadata, VodSnapshot(1, 1, {}))
        state = feed.append(metadata, VodSnapshot(2, 2, {}))
        return feed, old, state


class DeferredPreparationLane:
    """Keep a completion pending while real feed revisions arrive."""
    def __init__(self):
        self.requests = []

    def submit(self, value, **callbacks):
        self.requests.append((value, callbacks))

    def dispose(self):
        pass
