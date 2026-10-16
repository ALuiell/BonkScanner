"""Focused permission, release-repair and keyboard-send regressions. No real input."""
from __future__ import annotations

import src  # noqa: F401

import os
import threading
import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

import gui_run_control
import gui_scanner
from core.run_control import RunControlError
from gui_run_control import RunControl
from infra.hotkeys import HotkeyBinding, ModifierAwareHotkeyManager
from infra.input_permissions import ProcessPrivileges, inspect_privileges, privilege_relation
from infra.key_state import WindowsKeyState
from infra.keyboard_run_control import KeyboardRunControlProvider
from infra.keyboard_runtime import keyboard_operation
from tests.support.scanner import build_pair, build_run_control
from tests.test_hotkey_manager import FakeKeyboard


class PrivilegeTests(unittest.TestCase):
    def test_integrity_comparison(self):
        for source, target, expected in (
            (8192, 8192, "no_mismatch"), (12288, 8192, "no_mismatch"),
            (8192, 12288, "mismatch"), (None, 12288, "unknown"),
            (8192, None, "unknown"),
        ):
            with self.subTest(source=source, target=target):
                self.assertEqual(privilege_relation(
                    ProcessPrivileges(source, False), ProcessPrivileges(target, False)), expected)

    def test_ui_access_exception_and_unknown_are_not_blindly_reported_as_mismatch(self):
        target = ProcessPrivileges(12288, False)
        self.assertEqual(privilege_relation(ProcessPrivileges(8192, True), target), "no_mismatch")
        self.assertEqual(privilege_relation(ProcessPrivileges(8192, None), target), "unknown")

    def test_invalid_process_is_unknown(self):
        for pid in (None, 0, -1):
            self.assertIsNone(inspect_privileges(pid).integrity)

    @unittest.skipUnless(os.name == "nt", "Windows token API")
    def test_failed_token_read_is_unknown_and_closes_handles(self):
        import win32api
        import win32security
        handle, token = Mock(), Mock()
        with patch.object(win32api, "OpenProcess", return_value=handle), \
                patch.object(win32security, "OpenProcessToken", return_value=token), \
                patch.object(win32security, "GetTokenInformation", side_effect=OSError("access denied")):
            result = inspect_privileges(42)
        self.assertIsNone(result.integrity)
        handle.Close.assert_called_once()
        token.Close.assert_called_once()

    def control(self):
        control = build_run_control()
        control.check_restart_permissions = MethodType(RunControl.check_restart_permissions, control)
        control.get_game_process_id = lambda: 42
        return control

    def test_conflict_warns_once_per_activation(self):
        control = self.control()
        with patch.object(gui_run_control.os, "name", "nt"), patch.object(
            gui_run_control, "inspect_privileges",
            side_effect=[ProcessPrivileges(8192, False), ProcessPrivileges(12288, False)],
        ) as inspect:
            self.assertFalse(control.check_restart_permissions())
            self.assertFalse(control.check_restart_permissions(42))
        self.assertEqual(inspect.call_count, 2)
        self.assertEqual(len(control.calls["log"]), 1)
        self.assertIn("Restart BonkScanner as administrator", control.calls["log"][0][0])

    def test_success_is_silent_checked_once_and_new_start_checks_again(self):
        control = self.control()
        with patch.object(gui_run_control.os, "name", "nt"), patch.object(
            gui_run_control, "inspect_privileges", return_value=ProcessPrivileges(8192, False),
        ) as inspect:
            self.assertTrue(control.check_restart_permissions())
            self.assertTrue(control.check_restart_permissions())
            self.assertEqual(inspect.call_count, 2)
            control.reset_restart_permission_check()
            self.assertTrue(control.check_restart_permissions())
            self.assertEqual(inspect.call_count, 4)
        self.assertEqual(control.calls["log"], [])

    def test_unknown_does_not_blame_permissions(self):
        control = self.control()
        with patch.object(gui_run_control.os, "name", "nt"), patch.object(
            gui_run_control, "inspect_privileges", return_value=ProcessPrivileges(),
        ):
            self.assertTrue(control.check_restart_permissions())
        self.assertEqual(control.calls["log"], [])

    def test_missing_game_defers_check_instead_of_claiming_success(self):
        control = self.control()
        control.get_game_process_id = lambda: None
        with patch.object(gui_run_control.os, "name", "nt"), \
                patch.object(gui_run_control, "inspect_privileges") as inspect:
            self.assertTrue(control.check_restart_permissions())
        inspect.assert_not_called()
        self.assertEqual(control.calls["log"], [])

    def test_new_process_does_not_inherit_old_permission_result(self):
        control = self.control()
        with patch.object(gui_run_control.os, "name", "nt"), patch.object(
            gui_run_control, "inspect_privileges", side_effect=[
                ProcessPrivileges(8192, False), ProcessPrivileges(8192, False),
                ProcessPrivileges(8192, False), ProcessPrivileges(12288, False),
            ],
        ):
            self.assertTrue(control.check_restart_permissions(42))
            self.assertFalse(control.check_restart_permissions(43))


class KeyRepairTests(unittest.TestCase):
    def manager(self, state=None):
        keyboard = FakeKeyboard()
        keyboard.scan_codes["f6"] = (64,)
        calls = []
        manager = ModifierAwareHotkeyManager(
            keyboard, allowed_game_keys=("w",), is_game_window_active=lambda: True)
        manager.start((HotkeyBinding("f6", lambda: calls.append("f6")),))
        # Deterministic tests drive the same repair method without starting a timer.
        manager._state_reader = lambda codes: {code: state for code in codes}
        self.addCleanup(manager.stop)
        return keyboard, manager, calls

    def sample(self, manager, now):
        with patch("infra.hotkeys.time.monotonic", return_value=now):
            return manager.reconcile_pressed_keys()

    def test_lost_modifier_up_is_repaired_without_firing_f6(self):
        keyboard, manager, calls = self.manager(False)
        keyboard.emit("ctrl", "down")
        keyboard.emit("f6", "down")
        keyboard.emit("f6", "up")
        self.assertEqual(calls, [])
        self.assertEqual(self.sample(manager, 10), 0)
        self.assertEqual(self.sample(manager, 10.3), 1)
        self.assertEqual(calls, [])
        keyboard.emit("f6", "down")
        self.assertEqual(calls, ["f6"])

    def test_lost_f6_up_is_repaired_but_requires_a_new_press(self):
        keyboard, manager, calls = self.manager(False)
        keyboard.emit("f6", "down")
        keyboard.emit("f6", "down")
        self.sample(manager, 10)
        self.assertEqual(self.sample(manager, 10.3), 1)
        self.assertEqual(calls, ["f6"])
        keyboard.emit("f6", "down")
        self.assertEqual(calls, ["f6", "f6"])

    def test_two_samples_must_be_separated_in_time(self):
        keyboard, manager, _ = self.manager(False)
        keyboard.emit("f6", "down")
        for now in (10, 10, 10.05):
            self.assertEqual(self.sample(manager, now), 0)
        self.assertTrue(manager.any_key_pressed(("f6",)))

    def test_held_key_is_never_cleared_or_retriggered(self):
        keyboard, manager, calls = self.manager(True)
        keyboard.emit("f6", "down")
        for now in (10, 20, 30):
            keyboard.emit("f6", "down")
            self.assertEqual(self.sample(manager, now), 0)
        self.assertEqual(calls, ["f6"])
        self.assertTrue(manager.any_key_pressed(("f6",)))

    def test_unknown_breaks_release_confirmation_sequence(self):
        keyboard, manager, _ = self.manager(False)
        keyboard.emit("ctrl", "down")
        self.sample(manager, 10)
        manager._state_reader = lambda codes: {}
        self.sample(manager, 10.3)
        manager._state_reader = lambda codes: {code: False for code in codes}
        self.assertEqual(self.sample(manager, 10.6), 0)
        self.assertEqual(self.sample(manager, 10.9), 1)

    def test_probe_error_is_unknown_not_release(self):
        keyboard, manager, _ = self.manager(False)
        keyboard.emit("ctrl", "down")
        self.sample(manager, 10)
        manager._state_reader = Mock(side_effect=OSError("unavailable"))
        self.assertEqual(self.sample(manager, 10.3), 0)
        self.assertTrue(manager.any_key_pressed(("ctrl",)))
        self.assertEqual(manager._release_seen, {})

    def test_new_down_during_probe_invalidates_older_sample(self):
        keyboard, manager, _ = self.manager(False)
        keyboard.emit("ctrl", "down")
        self.sample(manager, 10)
        def racing_probe(codes):
            keyboard.emit("ctrl", "down")
            return {code: False for code in codes}
        manager._state_reader = racing_probe
        self.assertEqual(self.sample(manager, 10.3), 0)
        self.assertTrue(manager.any_key_pressed(("ctrl",)))

    def test_rebind_during_probe_cannot_clear_a_new_press(self):
        keyboard, manager, _ = self.manager(False)
        keyboard.emit("ctrl", "down")
        self.sample(manager, 10)
        def racing_probe(codes):
            manager._state_reader = None
            manager.start((HotkeyBinding("f6", lambda: None),))
            keyboard.emit("ctrl", "down")
            return {code: False for code in codes}
        manager._state_reader = racing_probe
        self.assertEqual(self.sample(manager, 10.3), 0)
        self.assertTrue(manager.any_key_pressed(("ctrl",)))

    def test_poll_only_visits_cached_keys_and_never_generates_movement(self):
        keyboard, manager, calls = self.manager(False)
        reader = Mock(side_effect=lambda codes: {code: False for code in codes})
        manager._state_reader = reader
        self.sample(manager, 10)
        reader.assert_not_called()
        keyboard.emit("w", "down")
        self.sample(manager, 10.3)
        self.sample(manager, 10.6)
        self.assertEqual(set(reader.call_args.args[0]), {17})
        self.assertEqual(calls, [])

    def test_old_queued_down_after_repair_cannot_toggle_again(self):
        keyboard, manager, calls = self.manager(False)
        keyboard.emit("f6", "down")
        with patch("infra.hotkeys.time.time", return_value=100):
            self.sample(manager, 10)
            self.sample(manager, 10.3)
            manager._on_keyboard_event(SimpleNamespace(scan_code=64, event_type="down", time=99))
            manager._on_keyboard_event(SimpleNamespace(scan_code=64, event_type="up", time=99.5))
        self.assertEqual(calls, ["f6"])
        manager._on_keyboard_event(SimpleNamespace(scan_code=64, event_type="down", time=101))
        self.assertEqual(calls, ["f6", "f6"])

    def test_real_down_after_sample_is_not_discarded_as_old_queue(self):
        keyboard, manager, calls = self.manager(False)
        keyboard.emit("f6", "down")
        with patch("infra.hotkeys.time.time", return_value=100):
            self.sample(manager, 10)
            self.sample(manager, 10.3)
        manager._on_keyboard_event(SimpleNamespace(scan_code=64, event_type="down", time=100.1))
        self.assertEqual(calls, ["f6", "f6"])

    def test_clock_rollback_does_not_permanently_block_repaired_key(self):
        keyboard, manager, calls = self.manager(False)
        keyboard.emit("f6", "down")
        with patch("infra.hotkeys.time.time", return_value=100):
            self.sample(manager, 10)
            self.sample(manager, 10.3)
        with patch("infra.hotkeys.time.time", return_value=50):
            manager._on_keyboard_event(SimpleNamespace(scan_code=64, event_type="down", time=49.9))
        self.assertEqual(calls, ["f6", "f6"])

    def test_modifier_repair_does_not_reinterpret_an_old_f6(self):
        keyboard, manager, calls = self.manager(False)
        keyboard.emit("ctrl", "down")
        with patch("infra.hotkeys.time.time", return_value=100):
            self.sample(manager, 10)
            self.sample(manager, 10.3)
            manager._on_keyboard_event(SimpleNamespace(scan_code=64, event_type="down", time=99))
            manager._on_keyboard_event(SimpleNamespace(scan_code=64, event_type="up", time=99.5))
        self.assertEqual(calls, [])
        manager._on_keyboard_event(SimpleNamespace(scan_code=64, event_type="down", time=101))
        self.assertEqual(calls, ["f6"])

    def test_repair_timer_starts_and_stops_with_manager(self):
        keyboard = FakeKeyboard()
        sampled = threading.Event()
        def reader(codes):
            sampled.set()
            return {code: None for code in codes}
        manager = ModifierAwareHotkeyManager(
            keyboard, allowed_game_keys=(), is_game_window_active=lambda: True, state_reader=reader)
        self.addCleanup(manager.stop)
        manager.start((HotkeyBinding("f9", lambda: None),))
        worker = manager._reconcile_thread
        keyboard.emit("f9", "down")
        self.assertTrue(sampled.wait(2))
        manager.stop()
        self.assertFalse(worker.is_alive())


class WindowsKeyStateTests(unittest.TestCase):
    def reader(self, result, context=123):
        class ReaderStub:
            __call__ = WindowsKeyState.__call__

        reader = ReaderStub()
        reader._readable_foreground = Mock(return_value=context)
        reader._virtual_keys = lambda code: (code,)
        reader._user = SimpleNamespace(GetAsyncKeyState=Mock(return_value=result))
        return reader

    def test_uses_down_bit_not_recent_press_bit(self):
        self.assertEqual(self.reader(1)((64,)), {64: False})
        self.assertEqual(self.reader(0x8000)((64,)), {64: True})

    def test_zero_without_proven_context_is_unknown(self):
        self.assertEqual(self.reader(0, None)((64,)), {64: None})

    def test_focus_change_invalidates_release_sample(self):
        reader = self.reader(0)
        reader._readable_foreground.side_effect = [123, 456]
        self.assertEqual(reader((64,)), {64: None})

    def test_unmapped_scan_code_is_unknown(self):
        reader = self.reader(0)
        reader._virtual_keys = lambda code: ()
        self.assertEqual(reader((999,)), {999: None})

    def test_shared_scan_code_preserves_either_held_physical_key(self):
        reader = self.reader(0)
        reader._virtual_keys = MethodType(WindowsKeyState._virtual_keys, reader)
        reader._user.GetAsyncKeyState.side_effect = lambda vk: 0x8000 if vk == 0x68 else 0
        self.assertEqual(reader((72,)), {72: True})


class SendSafetyTests(unittest.TestCase):
    def keyboard(self, press_error=None, release_error=None):
        state = SimpleNamespace(is_replaying=False)
        keyboard = SimpleNamespace(_listener=state, events=[])
        def press(key):
            keyboard.events.append(("press", key))
            state.is_replaying = True
            if press_error:
                raise press_error
            state.is_replaying = False
        def release(key):
            keyboard.events.append(("release", key))
            state.is_replaying = True
            if release_error:
                raise release_error
            state.is_replaying = False
        keyboard.press, keyboard.release = press, release
        return keyboard

    def provider(self, keyboard):
        return KeyboardRunControlProvider(keyboard, reset_hotkey="r", reset_hold_duration=0.1,
                                          sleep=lambda _: None)

    def test_partial_press_error_restores_replay_and_attempts_release(self):
        keyboard = self.keyboard(press_error=ValueError("press failed"))
        with self.assertRaisesRegex(ValueError, "press failed"):
            self.provider(keyboard).restart_run()
        self.assertEqual(keyboard.events, [("press", "r"), ("release", "r")])
        self.assertFalse(keyboard._listener.is_replaying)

    def test_release_error_does_not_replace_original_press_error(self):
        keyboard = self.keyboard(ValueError("original"), OSError("release"))
        with self.assertRaisesRegex(ValueError, "original"):
            self.provider(keyboard).restart_run()
        self.assertFalse(keyboard._listener.is_replaying)

    def test_release_error_without_prior_error_is_propagated_and_cleaned(self):
        keyboard = self.keyboard(release_error=OSError("release"))
        with self.assertRaisesRegex(OSError, "release"):
            self.provider(keyboard).restart_run()
        self.assertFalse(keyboard._listener.is_replaying)

    def test_already_active_sender_is_not_reset_or_released(self):
        keyboard = self.keyboard()
        keyboard._listener.is_replaying = True
        with self.assertRaises(RunControlError):
            self.provider(keyboard).restart_run()
        self.assertTrue(keyboard._listener.is_replaying)
        self.assertEqual(keyboard.events, [])

    def test_hold_does_not_leave_replay_enabled(self):
        keyboard = self.keyboard()
        provider = self.provider(keyboard)
        provider._sleep = lambda _: self.assertFalse(keyboard._listener.is_replaying)
        provider.restart_run()
        self.assertEqual(keyboard.events, [("press", "r"), ("release", "r")])

    def test_invalid_hotkey_never_enters_keyboard_send(self):
        keyboard = self.keyboard()
        keyboard.parse_hotkey = Mock(side_effect=ValueError("bad binding"))
        with self.assertRaisesRegex(ValueError, "bad binding"):
            self.provider(keyboard).restart_run()
        self.assertEqual(keyboard.events, [])
        self.assertFalse(keyboard._listener.is_replaying)

    def test_esc_send_uses_same_exception_cleanup(self):
        keyboard = self.keyboard()
        keyboard.press_and_release = keyboard.press
        keyboard.press = Mock()
        def failed_esc(key):
            keyboard._listener.is_replaying = True
            raise ValueError("esc failed")
        keyboard.press_and_release = failed_esc
        with self.assertRaisesRegex(ValueError, "esc failed"):
            keyboard_operation(keyboard, "press_and_release", "esc")
        self.assertFalse(keyboard._listener.is_replaying)


class ScannerPermissionTests(unittest.TestCase):
    def pair(self):
        scanner, control = build_pair()
        control.check_restart_permissions = MethodType(RunControl.check_restart_permissions, control)
        control.get_game_process_id = lambda: 42
        return scanner, control

    def test_start_with_mismatch_stops_before_memory_open(self):
        scanner, control = self.pair()
        with patch.object(gui_run_control.os, "name", "nt"), patch.object(
            gui_run_control, "inspect_privileges",
            side_effect=[ProcessPrivileges(8192, False), ProcessPrivileges(12288, False)],
        ), patch.object(gui_scanner, "GameDataClient") as client:
            scanner.background_loop()
        client.assert_not_called()
        self.assertFalse(scanner.scan_event.is_set())
        self.assertFalse(scanner.is_running)
        self.assertFalse(scanner.is_ready_to_start)
        self.assertEqual(len(control.calls["log"]), 1)

    def test_game_appearing_after_start_gets_checked_before_attachment(self):
        scanner, control = self.pair()
        current_pid = [None]
        control.get_game_process_id = lambda: current_pid[0]
        with patch.object(gui_run_control.os, "name", "nt"), patch.object(
            gui_run_control, "inspect_privileges",
            side_effect=[ProcessPrivileges(8192, False), ProcessPrivileges(12288, False)],
        ), patch.object(gui_scanner, "GameDataClient", side_effect=gui_scanner.ProcessNotFoundError) as client, \
                patch.object(scanner.stop_event, "wait", side_effect=lambda _: current_pid.__setitem__(0, 42)):
            scanner.background_loop()
        self.assertEqual(client.call_count, 1)
        self.assertEqual(len(control.calls["log"]), 1)
        self.assertFalse(scanner.is_ready_to_start)

    def test_success_is_not_rechecked_while_waiting_for_f6(self):
        scanner, control = self.pair()
        client = SimpleNamespace(memory=SimpleNamespace(_pm=SimpleNamespace(process_id=42)), close=lambda: None)
        waits = []
        def wait(timeout):
            waits.append(timeout)
            if len(waits) == 3:
                scanner.stop_event.set()
            return False
        with patch.object(gui_run_control.os, "name", "nt"), patch.object(
            gui_run_control, "inspect_privileges", return_value=ProcessPrivileges(8192, False),
        ) as inspect, patch.object(gui_scanner, "GameDataClient", return_value=client), \
                patch.object(scanner.scan_event, "wait", side_effect=wait):
            scanner.background_loop()
        self.assertEqual(inspect.call_count, 2)
        self.assertEqual(len(waits), 3)
        self.assertEqual(control.calls["log"], [])

    def test_actual_attachment_to_different_pid_is_checked(self):
        scanner, control = self.pair()
        client = SimpleNamespace(memory=SimpleNamespace(_pm=SimpleNamespace(process_id=43)), close=Mock())
        with patch.object(gui_run_control.os, "name", "nt"), patch.object(
            gui_run_control, "inspect_privileges", side_effect=[
                ProcessPrivileges(8192, False), ProcessPrivileges(8192, False),
                ProcessPrivileges(8192, False), ProcessPrivileges(12288, False),
            ],
        ), patch.object(gui_scanner, "GameDataClient", return_value=client):
            scanner.background_loop()
        self.assertFalse(scanner.scan_event.is_set())
        self.assertFalse(scanner.is_ready_to_start)
        client.close.assert_called_once()

    def test_restart_and_counter_keep_previous_behavior_without_permission_query(self):
        restarted = Mock()
        scanner, control = build_pair(provider=SimpleNamespace(restart_run=restarted))
        control.check_restart_permissions = Mock(side_effect=AssertionError("must not recheck"))
        scanner.log_reroll_stats = Mock()
        scanner.scan_event.set()
        self.assertTrue(scanner.reroll_map())
        restarted.assert_called_once()
        scanner.log_reroll_stats.assert_called_once()
        control.check_restart_permissions.assert_not_called()

    def test_key_state_reuses_only_approved_attached_process(self):
        control = build_run_control()
        control._restart_permission = (42, "no_mismatch")
        control.attached_game_process_id = lambda: 42
        self.assertTrue(control._key_state_foreground_accessible(os.getpid()))
        self.assertTrue(control._key_state_foreground_accessible(42))
        self.assertFalse(control._key_state_foreground_accessible(43))
        control.reset_restart_permission_check()
        self.assertFalse(control._key_state_foreground_accessible(42))


if __name__ == "__main__":
    unittest.main()
