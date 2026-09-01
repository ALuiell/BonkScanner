from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.runtime import AppRuntime, AppRuntimePorts
from app.shutdown import ShutdownDeadline


class _Recorder:
    def __init__(self, calls: list[str]) -> None:
        self.is_recording = False
        self._calls = calls

    def close(self) -> None:
        self._calls.append("vod")

    def stop(self) -> None:
        self._calls.append("vod_stop")


class _Coordinator:
    def __init__(self, calls: list[str]) -> None:
        self.snapshot_store = object()
        self.live_run_tracker = SimpleNamespace(character_passive_snapshot=lambda: None)
        self.vod_recorder = _Recorder(calls)
        self.build_progression_service = object()
        self.player_stats_client = None
        self.player_stats_game_data_client = None
        self.refresh_coordinator = None
        self._calls = calls
        self.start_calls = 0

    def start_refresh_loop(self, **_kwargs) -> None:
        self.start_calls += 1

    def stop_refresh_loop(self) -> None:
        self._calls.append("refresh_loop")

    def shutdown(self) -> None:
        self._calls.append("coordinator")
        return ()


def _ports(calls: list[str], deadlines: list[object], *, scanner_result=True) -> AppRuntimePorts:
    def with_deadline(name, result=None):
        def callback(deadline):
            calls.append(name)
            deadlines.append(deadline)
            return result

        return callback

    return AppRuntimePorts(
        shutdown_requested=lambda: False,
        live_stats_tab_active=lambda: False,
        twitch_bot_active=lambda: False,
        overlay_refresh_wanted=lambda: False,
        overlay_widget_refresh_active=lambda _widget_id: False,
        read_disabled_items_cache=lambda: None,
        write_disabled_items_cache=lambda _value: None,
        read_disabled_items_refresh_pending=lambda: False,
        write_disabled_items_refresh_pending=lambda _value: None,
        player_stats_view=lambda: None,
        overlay_view=lambda: None,
        recordings_list_view=lambda: None,
        snapshot_buffer=lambda: (),
        reset_snapshot_buffer=lambda: None,
        selected_snapshot_index=lambda: None,
        select_snapshot=lambda _value: None,
        snapshot_pinned=lambda: False,
        sync_overlay_state=lambda: None,
        sync_in_game_kps=lambda: None,
        refresh_session_tracked_items=lambda: None,
        log=lambda *_args, **_kwargs: None,
        stop_hotkeys=lambda: calls.append("hotkeys"),
        stop_in_game_overlay=with_deadline("in_game_overlay", ()),
        stop_scanner=with_deadline("scanner", scanner_result),
        stop_twitch=with_deadline("twitch", ()),
        wait_background_threads=with_deadline("background", ()),
        close_overlay_server=with_deadline("overlay", True),
    )


class AppRuntimeTests(unittest.TestCase):
    def test_create_is_the_production_coordinator_composition_root(self) -> None:
        calls: list[str] = []
        coordinator = _Coordinator(calls)
        ports = _ports(calls, [])
        with patch("app.runtime.AppCoordinator", return_value=coordinator) as constructor:
            runtime = AppRuntime.create(
                ports=ports,
                tracked_item_rules=("rule",),
                stale_after_seconds=25.0,
                overlay_host="127.0.0.1",
                overlay_port=17845,
                vod_interval_seconds=30.0,
            )

        self.assertIs(runtime.coordinator, coordinator)
        constructor.assert_called_once_with(
            tracked_item_rules=("rule",),
            stale_after_seconds=25.0,
            overlay_host="127.0.0.1",
            overlay_port=17845,
            vod_interval_seconds=30.0,
        )

    def test_start_is_idempotent_and_diagnostics_are_a_tuple(self) -> None:
        calls: list[str] = []
        coordinator = _Coordinator(calls)
        runtime = AppRuntime(coordinator, _ports(calls, []))

        runtime.start(schedule=lambda _delay, _callback: None, is_active=lambda: True, interval_ms=lambda: 10)
        runtime.start(schedule=lambda _delay, _callback: None, is_active=lambda: True, interval_ms=lambda: 10)

        self.assertEqual(coordinator.start_calls, 1)
        self.assertIsInstance(runtime.diagnostics(), tuple)

    def test_runtime_scheduler_relations_are_described_by_task_data(self) -> None:
        runtime = AppRuntime(_Coordinator([]), _ports([], []))

        order = [entry.task_id for entry in runtime.diagnostics()]

        self.assertLess(order.index("run_lifecycle_probe"), order.index("recording_lifecycle"))
        self.assertLess(order.index("recording_lifecycle"), order.index("full_player_snapshot"))
        self.assertLess(order.index("charge_shrines"), order.index("chaos_tome"))

    def test_shutdown_closes_gates_first_and_shares_one_deadline(self) -> None:
        calls: list[str] = []
        deadlines: list[object] = []
        coordinator = _Coordinator(calls)
        runtime = AppRuntime(coordinator, _ports(calls, deadlines))
        deadline = ShutdownDeadline.after(15.0)

        report = runtime.shutdown(deadline)

        self.assertTrue(report.completed)
        self.assertEqual(
            calls,
            [
                "hotkeys",
                "refresh_loop",
                "in_game_overlay",
                "vod",
                "overlay",
                "scanner",
                "twitch",
                "background",
                "coordinator",
            ],
        )
        self.assertEqual(deadlines, [deadline, deadline, deadline, deadline, deadline])
        self.assertIs(runtime.shutdown(deadline), report)

    def test_shutdown_reports_a_stuck_worker(self) -> None:
        calls: list[str] = []
        runtime = AppRuntime(_Coordinator(calls), _ports(calls, [], scanner_result=False))

        report = runtime.shutdown(ShutdownDeadline.after(0.0))

        self.assertEqual(report.timed_out_resources, ("scanner",))
        self.assertFalse(report.completed)


if __name__ == "__main__":
    unittest.main()
