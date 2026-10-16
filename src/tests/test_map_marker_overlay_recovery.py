"""Exercise actual overlay/tracker recovery with deterministic executors."""
from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication

from app import config
from infra.memory.map_marker_client import FullMapNotReadyError, MapScopeNotReadyError
from infra.memory.reader import MemoryReadError
import gui_in_game_overlay
from tests import test_map_marker_runtime as memory_fixtures
from tests import test_gui_run_control as ui_fixtures


class OverlayMarkerRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture = memory_fixtures.MapMarkerResilienceTests()
        self.fixture.setUp()
        self.tracker = self.fixture.tracker
        self.client = self.fixture.client
        self.memory = self.fixture.memory
        self.now = self.fixture.now
        self.obj = self.fixture.object_ptr
        self.client._class_name_from_ptr.return_value = "InteractableMicrowave"
        self.state(uses=1)
        self.before = self.fixture.remember_markers()
        self.tracker.close = Mock(wraps=self.tracker.close)
        self.tracker.recover = Mock(wraps=self.tracker.recover)
        self.original_tick = self.tracker.tick
        self.tracker.tick = Mock(wraps=self.original_tick)
        self.input = SimpleNamespace(cursor_position=lambda: (0, 0), is_map_surface_key_pressed=lambda: False)
        self.hotkeys = SimpleNamespace(
            poll=lambda *_args, **_kwargs: SimpleNamespace(placement=None, palette=None), reset=Mock()
        )
        self.logs = []
        self.overlay = gui_in_game_overlay.InGameOverlay(
            tracker=lambda: None,
            is_scanning=lambda: False,
            is_recording=lambda: False,
            is_game_window_active=lambda _name: False,
            find_game_window=None,
            schedule=lambda callback: callback(),
            schedule_idle=lambda _callback: None,
            timer_factory=ui_fixtures.FakeOverlayTimer,
            map_marker_tracker_factory=lambda _: self.tracker,
            map_marker_executor_factory=ui_fixtures.InlineMapMarkerExecutor,
            map_marker_input_factory=lambda: self.input,
            map_marker_hotkey_controller_factory=lambda _: self.hotkeys,
            map_marker_clock=lambda: self.now[0],
            has_premium_access=lambda: True,
            log=lambda message, **kwargs: self.logs.append((message, kwargs)),
        )
        self.window = ui_fixtures.FakeInGameOverlayWindow(visible=True)
        self.window.devicePixelRatioF = lambda: 1.0
        self.window.height = self.window.width = lambda: 600
        self.layer = SimpleNamespace(set_snapshot=Mock(), set_palette=Mock())
        self.window.map_marker_layer = self.layer
        self.overlay.in_game_overlay_window = self.window
        self.cfg = {
            "enabled": True,
            "map_markers": {
                "enabled": True, "automatic_discovery": True,
                "minimap_enabled": True, "merchant_memory_enabled": True,
                "scale": 1.0, "hotkeys": [],
            },
        }
        patches = [
            patch.object(config, "IN_GAME_OVERLAY", self.cfg),
            patch.object(gui_in_game_overlay.QApplication, "activeModalWidget", return_value=None),
            patch.object(gui_in_game_overlay, "log_runtime_event"),
        ]
        self.runtime_log = None
        for item in patches:
            value = item.start()
            self.addCleanup(item.stop)
            self.runtime_log = value
        self.overlay._sync_map_marker_runtime()

    def state(self, *, uses=0, cooking=0, item=0):
        self.memory.i32s[self.obj + self.client.MICROWAVE_USES_LEFT_OFFSET] = uses
        self.memory.u8s[self.obj + self.client.MICROWAVE_IS_COOKING_OFFSET] = cooking
        self.memory.u8s[self.obj + self.client.MICROWAVE_HAS_ITEM_OFFSET] = item

    def tick(self, elapsed=0.0):
        self.now[0] += elapsed
        return self.overlay._map_marker_tick()

    def ids(self, snapshot):
        return {m.marker_id for m in snapshot.markers}

    def exhaust(self):
        self.state(cooking=1)
        self.tick(0.1)
        self.state(item=1)
        self.tick(0.1)
        self.state()
        self.tick(0.1)  # Provisional completion.

    def test_last_use_redraw_error_recovers_other_markers_without_clearing_tracker(self):
        self.tick()
        self.exhaust()
        failed = False
        def redraw(snapshot, **_kwargs):
            nonlocal failed
            if len(snapshot.markers) == 2 and not failed:
                failed = True
                raise RuntimeError("injected last-use redraw failure")
        self.layer.set_snapshot.side_effect = redraw
        self.assertFalse(self.tick(0.4))
        self.assertTrue(failed)
        remaining = self.ids(self.before) - {f"auto:{self.obj:X}"}
        self.assertEqual(self.ids(self.tracker.snapshot), remaining)
        self.tracker.close.assert_not_called()
        self.assertEqual(self.overlay.map_marker_timer.stop_calls, 0)
        calls = self.tracker.tick.call_count
        self.assertFalse(self.tick(0.49))
        self.assertEqual(self.tracker.tick.call_count, calls)
        self.assertTrue(self.tick(0.01))
        self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), remaining)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.tracker.recover.assert_not_called()  # UI failure did not break the memory client.
        events = [call.args[0] for call in self.runtime_log.call_args_list]
        self.assertIn("in_game_overlay.map_marker_tick.failed", events)
        self.assertIn("in_game_overlay.map_marker_tick.recovered", events)

    def test_worker_failure_after_last_use_reconnects_without_losing_other_markers(self):
        self.tick()
        self.exhaust()
        failed = False
        def read(**kwargs):
            nonlocal failed
            snapshot = self.original_tick(**kwargs)
            if len(snapshot.markers) == 2 and not failed:
                failed = True
                raise RuntimeError("injected failure after exhausted object removal")
            return snapshot
        self.tracker.tick.side_effect = read
        self.assertFalse(self.tick(0.4))
        self.assertTrue(self.overlay._map_marker_reconnect_pending)
        replacement = self.fixture.make_client()
        self.fixture.factory.return_value = replacement
        self.assertTrue(self.tick(0.5))
        self.tracker.recover.assert_called_once_with()
        self.tracker.close.assert_not_called()
        self.assertIs(self.tracker._client, replacement)
        self.assertEqual(len(self.overlay._map_marker_latest_snapshot.markers), 2)
        self.assertEqual(self.overlay._map_marker_failures, 0)

    def test_new_map_during_recovery_never_restores_old_markers(self):
        self.tick()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        self.fixture.state["stage"] += 0x1000
        self.tick(0.5)
        self.assertEqual(self.overlay._map_marker_latest_snapshot.markers, ())
        self.assertEqual(self.tracker._retired_markers, {})
        self.assertEqual(self.overlay._map_marker_failures, 0)

    def test_stop_during_backoff_cancels_retry_and_performs_real_cleanup(self):
        self.tick()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        calls = self.tracker.tick.call_count
        self.cfg["enabled"] = False
        self.overlay.stop_in_game_overlay()
        self.tracker.close.assert_called_once_with()
        self.assertEqual(self.tracker.snapshot.markers, ())
        self.assertFalse(self.tick(5))
        self.assertEqual(self.tracker.tick.call_count, calls)
        self.tracker.recover.assert_not_called()
        self.assertEqual(self.overlay._map_marker_retry_at, 0.0)

    def test_shutdown_during_backoff_does_not_restart_runtime(self):
        self.tick()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        calls = self.tracker.tick.call_count
        self.assertEqual(self.overlay.shutdown(), ())
        self.assertFalse(self.tick(10))
        self.assertEqual(self.tracker.tick.call_count, calls)
        self.assertTrue(self.overlay._map_marker_worker_shutdown)

    def test_persistent_failure_has_capped_backoff_and_throttled_logs(self):
        self.tracker.tick.side_effect = RuntimeError("persistent failure")
        for expected in (0.5, 1.0, 2.0, 4.0, 5.0, 5.0):
            self.assertFalse(self.tick())
            self.assertAlmostEqual(self.overlay._map_marker_retry_at - self.now[0], expected)
            calls = self.tracker.tick.call_count
            self.tick(expected - 0.01)
            self.assertEqual(self.tracker.tick.call_count, calls)
            self.now[0] += 0.01
        self.assertEqual(self.runtime_log.call_count, 1)
        self.assertEqual(self.overlay._map_marker_failures, 6)
        self.tracker.close.assert_not_called()
        self.tracker.tick.side_effect = None
        self.assertTrue(self.tick())
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), self.ids(self.before))

    def manual_executor(self):
        executor = ui_fixtures.ManualMapMarkerExecutor()
        self.overlay._map_marker_executor_factory = lambda: executor
        return executor

    def test_old_inflight_completion_is_ignored_after_ui_failure(self):
        executor = self.manual_executor()
        self.tick()
        old_future = self.overlay._map_marker_future
        self.overlay._fail_map_marker_update(RuntimeError("input failed while worker runs"))
        self.assertEqual(len(executor.tasks), 1)
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(old_future)
        self.assertEqual(self.overlay._map_marker_latest_snapshot.markers, ())
        self.tracker.close.assert_not_called()
        self.tick(0.5)
        self.assertEqual(len(executor.tasks), 1)
        future = self.overlay._map_marker_future
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(future)
        self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), self.ids(self.before))
        self.assertEqual(self.overlay._map_marker_failures, 0)

    def test_completion_redraw_failure_keeps_ledger_and_recovers_on_next_result(self):
        executor = self.manual_executor()
        self.tick()
        future = self.overlay._map_marker_future
        executor.run_next()
        failed = False
        def redraw(snapshot, **_kwargs):
            nonlocal failed
            if snapshot.markers and not failed:
                failed = True
                raise RuntimeError("completion redraw failed")
        self.layer.set_snapshot.side_effect = redraw
        self.overlay._on_map_marker_sample_ready(future)
        self.assertTrue(failed)
        self.assertEqual(self.overlay._map_marker_failures, 1)
        self.assertEqual(self.ids(self.tracker.snapshot), self.ids(self.before))
        self.assertEqual(self.overlay.map_marker_timer.stop_calls, 0)
        self.tracker.close.assert_not_called()
        self.tick(0.5)
        self.assertEqual(len(executor.tasks), 1)
        recovered = self.overlay._map_marker_future
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(recovered)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), self.ids(self.before))

    def test_cached_empty_tick_does_not_claim_recovery_before_worker_completes(self):
        executor = self.manual_executor()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        self.tick(0.5)
        self.tick(0.025)
        self.assertEqual(self.overlay._map_marker_failures, 1)
        self.assertEqual(len(executor.tasks), 1)
        future = self.overlay._map_marker_future
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(future)
        self.assertEqual(self.overlay._map_marker_failures, 0)

    def test_stop_start_ignores_failure_from_old_generation(self):
        executor = self.manual_executor()
        self.tracker.tick.side_effect = [RuntimeError("stale failure"), self.before]
        self.tick()
        self.overlay._stop_map_marker_worker(wait=False)
        self.tick()
        self.assertEqual(len(executor.tasks), 2)  # Original read then serialized close.
        executor.run_next()
        self.tick()
        executor.run_next()
        self.tick()
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(len(executor.tasks), 1)
        future = self.overlay._map_marker_future
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(future)
        self.assertEqual(self.overlay._map_marker_failures, 0)

    def test_premium_loss_during_recovery_does_not_republish_old_stock(self):
        self.tick()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        self.overlay._has_premium_access = lambda: False
        self.tick(0.5)
        snapshot = self.overlay._map_marker_latest_snapshot
        self.assertEqual(snapshot.merchant_stocks, ())
        self.assertIsNone(snapshot.minimap_projection)
        self.assertEqual(self.tracker._merchant_stocks, {})

    def test_diagnostic_failure_does_not_disable_retry(self):
        self.tick()
        self.runtime_log.side_effect = OSError("log unavailable")
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        self.assertTrue(self.tick(0.5))
        self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), self.ids(self.before))
        self.assertEqual(self.overlay._map_marker_failures, 0)


    def recovery_events(self):
        return [call.args[0] for call in self.runtime_log.call_args_list
                if call.args[0] == "in_game_overlay.map_marker_tick.recovered"]

    def test_ui_and_inflight_read_failures_reconnect_on_first_retry(self):
        executor = self.manual_executor()
        self.tracker.tick.side_effect = RuntimeError("worker failed after UI error")
        self.tick()
        old_future = self.overlay._map_marker_future
        self.overlay._fail_map_marker_update(RuntimeError("UI failed during read"))
        retry_at = self.overlay._map_marker_retry_at
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(old_future)
        self.tracker.tick.side_effect = None
        replacement = self.fixture.make_client()
        self.fixture.factory.return_value = replacement

        self.tick(0.5)
        self.assertEqual(self.overlay._map_marker_failures, 1)
        self.assertEqual(self.overlay._map_marker_retry_at, retry_at)
        self.assertEqual(len(executor.tasks), 1)
        future = self.overlay._map_marker_future
        executor.run_next()
        self.tracker.recover.assert_called_once_with()
        self.assertIs(self.tracker._client, replacement)
        self.overlay._on_map_marker_sample_ready(future)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), self.ids(self.before))
        self.tracker.close.assert_not_called()
        self.assertEqual(len(self.recovery_events()), 1)

    def test_ui_failure_then_stop_start_does_not_reconnect_for_old_read_failure(self):
        executor = self.manual_executor()
        self.tracker.tick.side_effect = RuntimeError("old worker error")
        self.tick()
        old_future = self.overlay._map_marker_future
        self.overlay._fail_map_marker_update(RuntimeError("old UI error"))
        self.overlay._stop_map_marker_worker(wait=False)
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(old_future)
        self.tick()
        self.assertFalse(self.overlay._map_marker_reconnect_pending)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        executor.run_next()  # Serialized close completes before the new read.
        self.tracker.tick.side_effect = None
        self.tick()
        future = self.overlay._map_marker_future
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(future)
        self.tracker.recover.assert_not_called()
        self.assertFalse(self.overlay._map_marker_reconnect_pending)
        self.assertEqual(self.recovery_events(), [])

    def test_map_fallbacks_preserve_markers_without_claiming_recovery(self):
        for error in (FullMapNotReadyError("map waiting"),
                      MapScopeNotReadyError("stage waiting"),
                      MemoryReadError("map read failed")):
            with self.subTest(error=type(error).__name__):
                self.tick(1.1)
                old_scope = self.tracker._map_scope
                old_events = len(self.recovery_events())
                self.overlay._fail_map_marker_update(RuntimeError("redraw"))
                with patch.object(self.client, "poll", side_effect=error):
                    for delay in (0.5, 1.0, 1.0):
                        self.tick(delay)
                        self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), self.ids(self.before))
                        self.assertEqual(self.tracker._map_scope, old_scope)
                        self.assertEqual(self.overlay._map_marker_failures, 1)
                        self.assertEqual(len(self.recovery_events()), old_events)
                        self.assertIsNotNone(self.tracker._poll_problem)
                self.tick(1.1)
                self.assertEqual(self.overlay._map_marker_failures, 0)
                self.assertEqual(len(self.recovery_events()), old_events + 1)
                self.assertIsNone(self.tracker._poll_problem)

    def test_connection_wait_is_not_recovery_even_without_poll_problem(self):
        self.tick()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        self.tracker.recover()
        with patch.object(self.tracker, "_client_factory", side_effect=MemoryReadError("offline")):
            self.tick(0.5)
            self.tick(0.025)
            self.assertIsNone(self.tracker._client)
            self.assertIsNone(self.tracker._poll_problem)
            self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), self.ids(self.before))
            self.assertEqual(self.overlay._map_marker_failures, 1)
            self.assertEqual(self.recovery_events(), [])
        self.tick(1.1)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(len(self.recovery_events()), 1)

    def test_valid_closed_empty_map_still_confirms_recovery(self):
        self.tick()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        self.fixture.state["seed"] += 1
        self.memory.i32s[self.fixture.state["full_map"] + self.client.FULL_MAP_OPEN_COUNT_OFFSET] = 0
        self.cfg["map_markers"]["minimap_enabled"] = False
        self.tick(0.5)
        snapshot = self.overlay._map_marker_latest_snapshot
        self.assertEqual(snapshot.markers, ())
        self.assertFalse(snapshot.map_open)
        self.assertIsNone(snapshot.minimap_projection)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(len(self.recovery_events()), 1)

    def test_manual_placement_is_not_a_fresh_map_read(self):
        self.tick()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        self.now[0] += 0.5
        reads = self.tracker.tick.call_count
        self.overlay._request_map_marker_placement("moai", screen_x=50, screen_y=50, scale=1.0)
        self.overlay._map_marker_update_succeeded()
        self.assertEqual(self.tracker.tick.call_count, reads)
        self.assertEqual(self.overlay._map_marker_failures, 1)
        self.assertEqual(self.recovery_events(), [])
        self.tick()
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(len(self.recovery_events()), 1)

    def test_manual_placement_exception_keeps_healthy_memory_client(self):
        self.tick()
        before = self.overlay._map_marker_latest_snapshot
        self.tracker.place_manual_marker = Mock(side_effect=ValueError("bad placement"))

        result = self.overlay._request_map_marker_placement(
            "moai", screen_x=50, screen_y=50, scale=1.0,
        )

        self.assertEqual(result.markers, before.markers)
        self.assertFalse(self.overlay._map_marker_reconnect_pending)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertIs(self.tracker._client, self.client)
        self.tracker.recover.assert_not_called()
        self.assertIn(
            "in_game_overlay.map_marker_placement.failed",
            [call.args[0] for call in self.runtime_log.call_args_list],
        )
        self.assertTrue(self.tick(0.1))


    def test_surface_invalidation_keeps_worker_reconnect_without_ui_backoff(self):
        executor = self.manual_executor()
        self.tracker.tick.side_effect = RuntimeError("read failed across map toggle")
        self.tick()
        self.overlay._invalidate_map_marker_samples()
        executor.run_next()
        self.tracker.tick.side_effect = None
        self.tick(0.025)
        future = self.overlay._map_marker_future
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(future)
        self.tracker.recover.assert_called_once_with()
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(self.overlay._map_marker_retry_at, 0.0)
        self.assertEqual(self.runtime_log.call_count, 0)
        self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), self.ids(self.before))

    def test_fallback_completion_callback_waits_for_successful_map_read(self):
        executor = self.manual_executor()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        with patch.object(self.client, "poll", side_effect=FullMapNotReadyError("map waiting")):
            self.tick(0.5)
            future = self.overlay._map_marker_future
            executor.run_next()
            self.overlay._on_map_marker_sample_ready(future)
            self.assertEqual(self.overlay._map_marker_failures, 1)
            self.assertEqual(self.recovery_events(), [])
            self.assertFalse(self.overlay._map_marker_latest_snapshot.map_read_succeeded)
            self.assertEqual(self.ids(self.overlay._map_marker_latest_snapshot), self.ids(self.before))
        self.tick(0.025)
        future = self.overlay._map_marker_future
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(future)
        self.assertTrue(self.overlay._map_marker_latest_snapshot.map_read_succeeded)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(len(self.recovery_events()), 1)
        self.overlay._on_map_marker_sample_ready(future)
        self.assertEqual(len(self.recovery_events()), 1)

    def test_status_belongs_to_completed_result_not_mutable_tracker(self):
        executor = self.manual_executor()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        self.tick(0.5)
        future = self.overlay._map_marker_future
        with patch.object(self.client, "poll", side_effect=FullMapNotReadyError("map waiting")):
            executor.run_next()
        retained_result = future.result()
        self.assertFalse(retained_result.map_read_succeeded)
        # Advance the tracker independently before delivering that earlier result.
        # The UI must not query the mutable _poll_problem to classify a snapshot.
        healthy = self.original_tick(**self.fixture.options)
        self.assertTrue(healthy.map_read_succeeded)
        self.assertIsNone(self.tracker._poll_problem)
        self.assertFalse(retained_result.map_read_succeeded)
        self.overlay._on_map_marker_sample_ready(future)
        self.assertEqual(self.overlay._map_marker_failures, 1)
        self.assertEqual(self.recovery_events(), [])

    def test_newer_fallback_cannot_reuse_earlier_success_to_claim_recovery(self):
        executor = self.manual_executor()
        self.overlay._fail_map_marker_update(RuntimeError("redraw"))
        self.tick(0.5)
        executor.run_next()  # Healthy completion has not yet reached the UI.
        # Next submit finishes immediately, like a fast read between collect calls.
        self.overlay._map_marker_executor = ui_fixtures.InlineMapMarkerExecutor()
        with patch.object(self.client, "poll", side_effect=FullMapNotReadyError("map waiting")):
            self.tick(0.025)
        self.assertFalse(self.overlay._map_marker_latest_snapshot.map_read_succeeded)
        self.assertEqual(self.overlay._map_marker_failures, 1)
        self.assertEqual(self.recovery_events(), [])
        self.tick(0.025)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(len(self.recovery_events()), 1)

    def test_waiting_fallback_does_not_reset_next_failure_backoff(self):
        self.tick()
        self.overlay._fail_map_marker_update(RuntimeError("redraw one"))
        with patch.object(self.client, "poll", side_effect=FullMapNotReadyError("map waiting")):
            self.tick(0.5)
        self.overlay._fail_map_marker_update(RuntimeError("redraw two"))
        self.assertEqual(self.overlay._map_marker_failures, 2)
        self.assertAlmostEqual(self.overlay._map_marker_retry_at - self.now[0], 1.0)
        self.assertEqual(self.recovery_events(), [])
        self.tick(1.0)
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(len(self.recovery_events()), 1)

    def test_reconnect_and_close_clear_read_evidence_without_mutating_old_result(self):
        self.tick()
        healthy = self.overlay._map_marker_latest_snapshot
        self.assertTrue(healthy.map_read_succeeded)
        self.tracker.recover()
        self.assertFalse(self.tracker.snapshot.map_read_succeeded)
        self.assertTrue(healthy.map_read_succeeded)
        self.assertEqual(self.ids(self.tracker.snapshot), self.ids(healthy))
        self.tick()
        self.assertTrue(self.tracker.snapshot.map_read_succeeded)
        self.tracker.close()
        self.assertFalse(self.tracker.snapshot.map_read_succeeded)

    def test_repeated_ui_failures_do_not_lose_same_session_read_failure(self):
        executor = self.manual_executor()
        self.tracker.tick.side_effect = RuntimeError("late read failure")
        self.tick()
        self.overlay._fail_map_marker_update(RuntimeError("redraw one"))
        self.overlay._fail_map_marker_update(RuntimeError("redraw two"))
        deadline = self.overlay._map_marker_retry_at
        executor.run_next()
        self.tracker.tick.side_effect = None
        self.tick(1.0)
        self.assertEqual(self.overlay._map_marker_failures, 2)
        self.assertEqual(self.overlay._map_marker_retry_at, deadline)
        future = self.overlay._map_marker_future
        executor.run_next()
        self.overlay._on_map_marker_sample_ready(future)
        self.tracker.recover.assert_called_once_with()
        self.assertEqual(self.overlay._map_marker_failures, 0)
        self.assertEqual(len(self.recovery_events()), 1)


if __name__ == "__main__":
    unittest.main()
