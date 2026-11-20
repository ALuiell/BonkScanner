"""Transition gating and scanner-owned confirmation, without a game process."""
from types import SimpleNamespace

import unittest
from unittest.mock import patch

import src  # noqa: F401
import gui_scanner
from app.map_transition import MapTransition
from core.run_control import RunControlError
from infra.memory.reader import MemoryReadError
from tests.support.scanner import build_pair


class MapTransitionTests(unittest.TestCase):
    def _patch(self, target, name, value):
        patcher = patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_scanner_input_failure_never_advances_recording_generation(self):
        for failure in (RunControlError("refused"), RuntimeError("failed")):
            with self.subTest(failure=type(failure).__name__):
                self._assert_input_failure(failure)

    def test_abandon_counts_only_unresolved_sent_restart_once(self):
        state = MapTransition()
        state.abandon()
        state.begin()
        state.cancel()
        state.abandon()
        assert state.abandoned_restart_count() == 0
        state.begin()
        state.restart_sent()
        state.begin()
        state.cancel()
        state.abandon()
        assert not state.active()
        assert state.recording_generation() == 0
        assert state.abandoned_restart_count() == 1
        state.abandon()
        state.settle(confirmed=True)
        assert state.abandoned_restart_count() == 1
        assert state.recording_generation() == 0
        state.begin()
        state.restart_sent()
        state.settle(confirmed=True)
        state.abandon()
        assert state.abandoned_restart_count() == 1
        assert state.recording_generation() == 1

    def test_recovery_grace_is_bounded_across_consecutive_restarts(self):
        now = [0.0]
        state = MapTransition(clock=lambda: now[0])
        assert not state.recovery_grace_active()
        state.begin()
        assert state.recovery_grace_active()
        state.restart_sent()
        now[0] = 0.8
        state.begin()
        state.restart_sent()
        assert state.recovery_grace_active()
        now[0] = 1.0
        assert state.active() and not state.recovery_grace_active()
        now[0] = 2.0
        assert not state.active() and not state.recovery_grace_active()
        state.begin()  # Still the same unresolved series after the stall bound.
        assert state.active() and not state.recovery_grace_active()
        state.restart_sent()
        state.settle(confirmed=True)
        now[0] = 3.0
        state.begin()
        assert state.recovery_grace_active()
        state.cancel()
        assert not state.recovery_grace_active()
        now[0] = 4.0
        state.begin()
        assert state.recovery_grace_active()

    def test_worker_stop_abandons_an_unresolved_restart(self):
        scanner, _control = build_pair()
        state = scanner._coordinator.map_transition
        state.begin()
        state.restart_sent()
        scanner.stop_event.set()
        scanner.background_loop()
        assert state.abandoned_restart_count() == 1
        assert state.recording_generation() == 0

    def test_scan_pause_abandons_before_waiting_for_resume(self):
        scanner, _control = build_pair()
        state = scanner._coordinator.map_transition
        state.begin()
        state.restart_sent()
        scanner.client = SimpleNamespace(close=lambda: None)
        observed = []

        def wait_for_resume(timeout):
            observed.append((state.abandoned_restart_count(), state.recording_generation()))
            scanner.stop_event.set()
            return False

        scanner.scan_event.wait = wait_for_resume
        scanner.background_loop()
        assert observed == [(1, 0)]
        assert state.abandoned_restart_count() == 1

    def test_connection_loss_abandons_before_retry(self):
        scanner, control = build_pair()
        state = scanner._coordinator.map_transition
        state.begin()
        state.restart_sent()
        observed = []

        class Client:
            def wait_for_map_ready(self, **_kwargs):
                raise MemoryReadError("lost")

            def close(self):
                pass

        scanner.client = Client()
        scanner.scan_event.set()
        control.is_game_window_active = lambda _process: True
        control.wait_for_game_window_focus = lambda _process: True

        def stop_on_retry(_seconds):
            observed.append((state.abandoned_restart_count(), state.recording_generation()))
            scanner.stop_event.set()
            return True

        scanner.stop_event.wait = stop_on_retry
        scanner.background_loop()
        assert observed == [(1, 0)]
        assert state.abandoned_restart_count() == 1

    def test_forced_readiness_timeout_abandons_before_pause(self):
        scanner, control = build_pair()
        state = scanner._coordinator.map_transition
        observed = []
        control.run_control_provider = SimpleNamespace(restart_run=lambda: None)

        class Client:
            def wait_for_map_ready(self, **_kwargs):
                raise TimeoutError("unconfirmed")

            def close(self):
                pass

        scanner.client = Client()
        scanner.scan_event.set()
        scanner._force_reset_requested = True
        scanner._can_force_reset = lambda *_args: True
        control.is_game_window_active = lambda _process: True
        control.wait_for_game_window_focus = lambda _process: True

        def pause(*, reset_sent):
            observed.append((reset_sent, state.abandoned_restart_count(), state.recording_generation()))
            scanner.stop_event.set()

        scanner._pause_after_force_reset_failure = pause
        scanner.background_loop()
        assert observed == [(True, 1, 0)]

    def test_timeout_releases_readers_but_not_recording_or_claims_of_success(self):
        now = [0.0]
        state = MapTransition(clock=lambda: now[0])
        assert state.generation() == state.recording_generation() == 0
        state.begin()
        now[0] = 20.0  # The deadline starts after the input returns.
        assert state.active() and state.recording_generation() is None
        state.restart_sent()
        now[0] = 20.99
        assert state.active()
        now[0] = 21.0
        assert not state.active()
        assert state.recording_generation() is None
        state.settle(confirmed=False)
        assert state.recording_generation() == 0
        state.settle(confirmed=True)


    def test_continuous_restarts_confirm_only_the_final_kept_map(self):
        state = MapTransition()
        state.begin()
        state.restart_sent()
        state.begin()
        state.restart_sent()
        assert state.generation() == 2
        assert state.recording_generation() is None
        state.settle(confirmed=True)
        assert state.recording_generation() == 1
        state.settle(confirmed=True)
        assert state.recording_generation() == 1


    def test_failed_second_input_restores_prior_restart_and_deadline(self):
        now = [0.0]
        state = MapTransition(clock=lambda: now[0])
        state.begin()
        state.restart_sent()
        now[0] = 0.3
        state.begin()
        state.cancel()
        assert state.active()
        assert state.recording_generation() is None
        now[0] = 1.0
        assert not state.active()
        assert state.recording_generation() is None
        state.settle(confirmed=True)
        assert state.recording_generation() == 1


    def _assert_input_failure(self, failure):
        seen = []
        scanner, control = build_pair()
        state = scanner._coordinator.map_transition

        def restart():
            seen.append((state.active(), state.generation(), state.recording_generation()))
            raise failure

        control.run_control_provider = SimpleNamespace(restart_run=restart)
        scanner.scan_event.set()
        if isinstance(failure, RunControlError):
            assert not scanner.reroll_map()
        else:
            with self.assertRaises(RuntimeError):
                scanner.reroll_map()
        assert seen == [(True, 1, None)]
        assert not state.active()
        assert state.recording_generation() == 0


    def test_ready_changed_target_is_settled_before_target_focus_action(self):
        scanner, control = build_pair()
        state = scanner._coordinator.map_transition
        calls = []
        control.run_control_provider = SimpleNamespace(restart_run=lambda: calls.append("restart"))

        class Client:
            def wait_for_map_ready(self, **kwargs):
                calls.append((kwargs["require_change"], state.recording_generation()))
                return {"Moais": 1}

            def get_map_generation_state(self):
                return object()

            def close(self):
                pass

        def evaluate(*_args, **_kwargs):
            return {"name": "Target", "color": "GREEN"} if "restart" in calls else None

        def target_action(_process):
            calls.append(("target", state.recording_generation()))
            scanner.stop_event.set()
            return True

        scanner.client = Client()
        scanner.scan_event.set()
        scanner.is_running = scanner.is_ready_to_start = True
        control.is_game_window_active = lambda _process: True
        control.wait_for_game_window_focus = lambda _process: True
        control.handle_confirmed_target_window = target_action
        self._patch(gui_scanner, "adapt_map_stats", lambda raw: raw)
        self._patch(gui_scanner, "evaluate_candidate", evaluate)
        scanner.background_loop()

        assert calls == [(False, 0), "restart", (True, None), ("target", 1)]
        assert state.recording_generation() == 1


    def test_timeout_then_first_scan_does_not_claim_a_new_map(self):
        scanner, control = build_pair()
        state = scanner._coordinator.map_transition
        observed = []
        control.run_control_provider = SimpleNamespace(restart_run=lambda: None)

        class Client:
            count = 0

            def wait_for_map_ready(self, **kwargs):
                self.count += 1
                observed.append((kwargs["require_change"], state.recording_generation()))
                if self.count == 2:
                    raise TimeoutError("unconfirmed")
                return {"Moais": self.count}

            def get_map_generation_state(self):
                return object()

            def close(self):
                pass

        scanner.client = Client()
        scanner.scan_event.set()
        scanner.is_running = scanner.is_ready_to_start = True
        control.is_game_window_active = lambda _process: True
        control.wait_for_game_window_focus = lambda _process: True
        control.handle_confirmed_target_window = lambda _process: scanner.stop_event.set() or True
        self._patch(gui_scanner, "adapt_map_stats", lambda raw: raw)
        self._patch(gui_scanner, "evaluate_candidate", lambda stats, *_args, **_kwargs:
                            {"name": "Target", "color": "GREEN"} if stats["Moais"] == 3 else None)
        scanner.background_loop()
        assert observed == [(False, 0), (True, None), (False, None)]
        assert state.recording_generation() == 0


    def test_forced_restart_kept_map_is_confirmed(self):
        scanner, control = build_pair()
        state = scanner._coordinator.map_transition
        observed = []
        control.run_control_provider = SimpleNamespace(
            restart_run=lambda: observed.append(("restart", state.recording_generation()))
        )

        class Client:
            def wait_for_map_ready(self, **kwargs):
                observed.append((kwargs["require_change"], state.recording_generation()))
                return {"Moais": 1}

            def get_map_generation_state(self):
                return object()

            def close(self):
                pass

        scanner.client = Client()
        scanner.scan_event.set()
        scanner.is_running = scanner.is_ready_to_start = True
        scanner._force_reset_requested = True
        scanner._can_force_reset = lambda *_args: True
        control.is_game_window_active = lambda _process: True
        control.wait_for_game_window_focus = lambda _process: True
        control.handle_confirmed_target_window = lambda _process: scanner.stop_event.set() or True
        self._patch(gui_scanner, "adapt_map_stats", lambda raw: raw)
        self._patch(gui_scanner, "evaluate_candidate", lambda *_args, **_kwargs:
                            {"name": "Target", "color": "GREEN"})
        scanner.background_loop()
        assert observed == [("restart", None), (True, None)]
        assert state.recording_generation() == 1

    def test_error_after_dispatch_does_not_settle_the_new_transition(self):
        scanner, control = build_pair()
        state = scanner._coordinator.map_transition
        observed = []
        control.run_control_provider = SimpleNamespace(restart_run=lambda: None)

        class Client:
            def wait_for_map_ready(self, **_kwargs):
                return {"Moais": 1}

            def get_map_generation_state(self):
                return object()

            def close(self):
                pass

        scanner.client = Client()
        scanner.scan_event.set()
        scanner.is_running = scanner.is_ready_to_start = True
        control.is_game_window_active = lambda _process: True
        control.wait_for_game_window_focus = lambda _process: True
        self._patch(gui_scanner, "adapt_map_stats", lambda raw: raw)
        self._patch(gui_scanner, "evaluate_candidate", lambda *_args, **_kwargs: None)

        def fail_after_input():
            raise RuntimeError("stats UI failed after reset input")

        def stop_on_retry(_seconds):
            observed.append((state.active(), state.recording_generation()))
            scanner.stop_event.set()
            return True

        scanner.log_reroll_stats = fail_after_input
        scanner.stop_event.wait = stop_on_retry
        scanner.background_loop()
        assert observed == [(True, None)]
