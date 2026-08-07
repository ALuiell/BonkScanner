"""Step 25: the scan worker and run control, driven as objects.

Twenty-four tests **moved** here from `test_gui_run_control.py`, not copied --
the migration rule `test_componentization_inventory`'s header states is that a
call site is migrated by the step that converts its subject, and step 25 is
what converted these. Each one built `object.__new__(MegabonkApp)` and called
an unbound mixin method with a hand-stubbed `self`; each now calls a real
constructor through `tests/support/scanner.py`.

The two `on_closing` tests stayed behind on purpose. Their subject is
`MegabonkApp.on_closing`, which is the application's shutdown *order* over nine
owners and not a component method, so an app double is still the honest fixture
for them.

What the move buys, concretely: an `object.__new__` double absorbs a new
dependency silently, as an `AttributeError` at the first read on whichever
branch happens to run. These fixtures fail at construction instead. Three of
the tests below (`focus_wait_*`, `confirmed_target_*`, `reconnect_*`) cross the
scanner/run-control boundary and use `build_pair`, because a port wired to the
wrong object still passes a one-sided test -- which is the specific way this
step could ship broken.
"""

from __future__ import annotations

import ctypes
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

import gui_run_control
import gui_scanner
from app import config
from infra.keyboard_run_control import KeyboardRunControlProvider
from tests.support.scanner import (
    AliveThread,
    DeadThread,
    FakeLabel,
    FakeLogBox,
    FakeThread,
    build_pair,
    build_run_control,
    build_scanner,
)
from tests.test_gui_run_control import (
    FakeForegroundGui,
    FakeForegroundProcess,
    FakeKernel32,
    FakeKeyboardModule,
    FakeUser32,
    FakeWindll,
    patch_everywhere,
)

PROCESS_NAME = "Megabonk.exe"


class RunControlTests(unittest.TestCase):
    def test_apply_run_control_mode_enables_keyboard_provider(self) -> None:
        run_control = build_run_control(provider=object())

        run_control.apply_run_control_mode()

        self.assertIsInstance(run_control.run_control_provider, KeyboardRunControlProvider)

    def test_check_admin_rights_logs_keyboard_warnings_without_admin(self) -> None:
        run_control = build_run_control()

        with patch.object(gui_run_control.os, "name", "nt"), \
                patch.object(gui_run_control.process, "is_running_as_admin", lambda: False):
            run_control.check_admin_rights()

        messages = [message for message, _tag in run_control.calls["log"]]
        self.assertTrue(any("WARNING: Script is not running as Administrator" in m for m in messages))
        self.assertTrue(any("Hotkeys may not work while the game window is active" in m for m in messages))

    def test_game_window_focus_requires_foreground_pid_match(self) -> None:
        run_control = build_run_control()
        run_control.get_game_process_id = lambda: 1234
        fake_gui = SimpleNamespace(GetForegroundWindow=lambda: 111)
        fake_process = SimpleNamespace(GetWindowThreadProcessId=lambda _window: (10, 5678))

        with patch_everywhere("win32gui", fake_gui):
            with patch_everywhere("win32process", fake_process):
                self.assertFalse(run_control.is_game_window_active(PROCESS_NAME))

    def test_game_window_focus_returns_false_without_game_pid(self) -> None:
        run_control = build_run_control()
        run_control.get_game_process_id = lambda: None
        fake_gui = SimpleNamespace(GetForegroundWindow=lambda: 111)
        fake_process = SimpleNamespace(GetWindowThreadProcessId=lambda _window: (10, 1234))

        with patch_everywhere("win32gui", fake_gui):
            with patch_everywhere("win32process", fake_process):
                self.assertFalse(run_control.is_game_window_active(PROCESS_NAME))

    def test_game_window_focus_can_match_foreground_window_without_scanner_pid(self) -> None:
        run_control = build_run_control()
        run_control._process_id_matches_name = lambda process_id, process_name: (
            process_id == 1234 and process_name == PROCESS_NAME
        )
        run_control.find_game_window_by_pid = lambda process_id, process_name=None: (
            111 if process_id == 1234 and process_name == PROCESS_NAME else None
        )
        fake_gui = SimpleNamespace(GetForegroundWindow=lambda: 111)
        fake_process = SimpleNamespace(GetWindowThreadProcessId=lambda _window: (10, 1234))

        with patch_everywhere("win32gui", fake_gui):
            with patch_everywhere("win32process", fake_process):
                self.assertTrue(run_control.is_game_window_active(PROCESS_NAME))

    def test_game_window_focus_recovers_after_game_restarts_with_a_new_pid(self) -> None:
        client = SimpleNamespace(memory=SimpleNamespace(_pm=SimpleNamespace(process_id=1234)))
        run_control = build_run_control(client=lambda: client)
        run_control._process_id_matches_name = lambda process_id, process_name: (
            process_id == 5678 and process_name == PROCESS_NAME
        )
        run_control.find_game_window_by_pid = lambda process_id, process_name=None: (
            222 if process_id == 5678 and process_name == PROCESS_NAME else None
        )
        fake_gui = SimpleNamespace(GetForegroundWindow=lambda: 222)
        fake_process = SimpleNamespace(GetWindowThreadProcessId=lambda _window: (10, 5678))

        with patch_everywhere("win32gui", fake_gui):
            with patch_everywhere("win32process", fake_process):
                self.assertTrue(run_control.is_game_window_active(PROCESS_NAME))

    def test_bring_game_window_to_front_uses_alt_attach_fallback_after_direct_failure(self) -> None:
        fake_gui = FakeForegroundGui()
        fake_process = FakeForegroundProcess()
        fake_user32 = FakeUser32()
        fake_windll = FakeWindll(fake_user32, FakeKernel32())
        run_control = build_run_control()
        run_control.find_game_window = lambda _process_name: 111

        with patch_everywhere("win32gui", fake_gui):
            with patch_everywhere("win32process", fake_process):
                with patch.object(ctypes, "windll", fake_windll):
                    self.assertTrue(run_control.bring_game_window_to_front(PROCESS_NAME))

        self.assertEqual(fake_gui.show_window_calls, [(111, 5)])
        self.assertEqual(fake_gui.set_foreground_calls, [111, 111])
        self.assertEqual(fake_gui.bring_window_to_top_calls, [111])
        self.assertEqual(
            fake_user32.attach_calls,
            [(10, 20, True), (10, 30, True), (10, 20, False), (10, 30, False)],
        )
        self.assertEqual(fake_user32.keybd_event_calls, [(0x12, 0, 0, 0), (0x12, 0, 0x0002, 0)])
        self.assertEqual(run_control.calls["log"], [])

    def test_alt_attach_fallback_detaches_threads_when_foreground_fails(self) -> None:
        fake_gui = FakeForegroundGui(fail_always=True)
        fake_process = FakeForegroundProcess()
        fake_user32 = FakeUser32()
        fake_windll = FakeWindll(fake_user32, FakeKernel32())
        run_control = build_run_control()

        with patch_everywhere("win32gui", fake_gui):
            with patch_everywhere("win32process", fake_process):
                with patch.object(ctypes, "windll", fake_windll):
                    with self.assertRaisesRegex(RuntimeError, "foreground denied"):
                        run_control.try_attach_foreground_window(111)

        self.assertEqual(
            fake_user32.attach_calls,
            [(10, 20, True), (10, 30, True), (10, 20, False), (10, 30, False)],
        )

    def test_find_game_window_falls_back_to_name_lookup_without_scanner_pid(self) -> None:
        run_control = build_run_control()
        run_control.find_game_window_by_name = lambda process_name: (
            222 if process_name == PROCESS_NAME else None
        )

        self.assertEqual(run_control.find_game_window(PROCESS_NAME), 222)

    def test_find_game_window_by_name_prefers_largest_matching_main_window(self) -> None:
        run_control = build_run_control()
        run_control._process_id_matches_name = lambda process_id, process_name: (
            process_name == "megabonk.exe" and process_id in {2001, 2002}
        )

        windows = [11, 22, 33]
        rects = {11: (0, 0, 200, 120), 22: (0, 0, 1280, 720), 33: (0, 0, 900, 600)}
        titles = {11: "Megabonk Helper", 22: "Megabonk", 33: "Settings"}
        process_by_window = {11: (10, 2001), 22: (10, 2001), 33: (10, 2002)}
        fake_gui = SimpleNamespace(
            EnumWindows=lambda callback, extra: [callback(window, extra) for window in windows],
            IsWindowVisible=lambda _window: True,
            GetWindowRect=lambda window: rects[window],
            GetWindowText=lambda window: titles[window],
            GetParent=lambda _window: 0,
            GetWindow=lambda _window, _flag: 0,
            GetWindowLong=lambda _window, _index: 0,
        )
        fake_process = SimpleNamespace(
            GetWindowThreadProcessId=lambda window: process_by_window[window]
        )

        with patch_everywhere("win32gui", fake_gui):
            with patch_everywhere("win32process", fake_process):
                self.assertEqual(run_control.find_game_window_by_name(PROCESS_NAME), 22)


class HotkeyRegistrationTests(unittest.TestCase):
    def test_setup_hotkeys_registers_supported_hotkeys(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        run_control = build_run_control()

        with patch_everywhere("keyboard", fake_keyboard):
            with patch.object(config, "HOTKEY", "f6"):
                with patch.object(config, "PLAYER_STATS_RECORD_HOTKEY", "f8"):
                    run_control.setup_hotkeys()

        self.assertEqual(fake_keyboard.unhook_all_calls, 0)
        self.assertEqual(len(fake_keyboard.hook_calls), 1)
        self.assertEqual(fake_keyboard.add_hotkey_calls, [])
        self.assertIsNotNone(run_control._hotkey_manager)
        self.assertEqual(run_control.calls["log"], [])

    def test_the_overlay_edit_binding_is_the_only_conditional_one(self) -> None:
        """Sceglierne uno: F9 registers only when the port is wired.

        This is the `hasattr(self, "hotkey_toggle_in_game_overlay_edit")`
        branch, and it is asserted separately from "hotkeys are registered"
        because it is the only one of the three bindings that has ever been
        conditional. Step 24 made the old guard permanently true by leaving a
        delegator on `MegabonkApp`; a component without the attribute would
        have made it quietly false, and the only symptom would have been F9
        doing nothing in a running app with a green suite.
        """
        registered: list[list[str]] = []

        class Manager:
            def __init__(self, _module, **_kwargs) -> None:
                pass

            def start(self, bindings) -> None:
                registered.append([binding.hotkey for binding in bindings])

            def stop(self) -> None:
                pass

        with patch_everywhere("keyboard", FakeKeyboardModule()), \
                patch.object(gui_run_control, "ModifierAwareHotkeyManager", Manager), \
                patch.object(config, "HOTKEY", "f6"), \
                patch.object(config, "PLAYER_STATS_RECORD_HOTKEY", "f8"), \
                patch.object(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9"):
            build_run_control(toggle_overlay_edit=None).setup_hotkeys()
            build_run_control(toggle_overlay_edit=lambda: None).setup_hotkeys()

        self.assertEqual(registered, [["f6", "f8"], ["f6", "f8", "f9"]])

    def test_the_overlay_edit_hotkey_reaches_the_wired_port(self) -> None:
        toggles: list[str] = []
        run_control = build_run_control(toggle_overlay_edit=lambda: toggles.append("edit"))

        run_control.hotkey_toggle_in_game_overlay_edit()

        self.assertEqual(toggles, ["edit"])

    def test_hotkey_with_held_game_key_requires_matching_foreground_pid(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        run_control = build_run_control()
        run_control.get_game_process_id = lambda: 1234
        fake_gui = SimpleNamespace(GetForegroundWindow=lambda: 111)
        fake_process = SimpleNamespace(GetWindowThreadProcessId=lambda _window: (10, 5678))

        with patch_everywhere("keyboard", fake_keyboard):
            with patch_everywhere("win32gui", fake_gui):
                with patch_everywhere("win32process", fake_process):
                    with patch.object(config, "HOTKEY_GAME_KEY_WHITELIST", ("w",)):
                        with patch.object(config, "HOTKEY", "f6"):
                            run_control.setup_hotkeys()

                            hook = fake_keyboard.hook_calls[0]
                            hook(SimpleNamespace(
                                scan_code=fake_keyboard.key_to_scan_codes("w")[0],
                                event_type="down",
                            ))
                            hook(SimpleNamespace(
                                scan_code=fake_keyboard.key_to_scan_codes("f6")[0],
                                event_type="down",
                            ))

        self.assertEqual(run_control.calls["toggle_scan"], 0)

    def test_stop_hotkeys_swallows_a_failing_manager_and_clears_it(self) -> None:
        class Manager:
            def stop(self) -> None:
                raise RuntimeError("hook already gone")

        run_control = build_run_control()
        run_control._hotkey_manager = Manager()

        run_control.stop_hotkeys()

        self.assertIsNone(run_control._hotkey_manager)


class ScanLifecycleTests(unittest.TestCase):
    """`toggle_main_loop`, the pause hotkey, and what each writes.

    Every test that starts the monitor stubs `refresh_stats_ui`, exactly as the
    app doubles these replaced did. It is not decoration: the real one builds a
    `QLabel` per active template, and a test that builds real Qt widgets after
    an earlier test has created a `QApplication` takes the interpreter down
    mid-run with 0xC0000409 -- no traceback, and every later test silently
    unreported. Step 23 measured that; this file rediscovered it.
    """

    @staticmethod
    def _quiet(scanner):
        repaints: list[int] = []
        scanner.refresh_stats_ui = lambda: repaints.append(1)
        return repaints

    def test_toggle_main_loop_clears_stale_scan_event_before_starting_worker(self) -> None:
        scanner = build_scanner(selected_template_names=lambda: ["LIGHT"])
        self._quiet(scanner)
        scanner.stop_event.set()
        scanner.scan_event.set()
        scanner.is_running = True
        scanner.is_ready_to_start = True

        with patch.dict(config.user_config, {"SKIP_REROLL_WARNING": True}):
            with patch.object(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False):
                with patch.object(config, "EVALUATION_MODE", "templates"):
                    with patch.object(threading, "Thread", FakeThread):
                        scanner.toggle_main_loop()

        self.assertFalse(scanner.scan_event.is_set())
        self.assertFalse(scanner.stop_event.is_set())
        self.assertFalse(scanner.is_running)
        self.assertFalse(scanner.is_ready_to_start)
        self.assertTrue(scanner.scanner_thread.started)

    def test_starting_a_scan_rechecks_the_game_reset_threshold(self) -> None:
        """Import-time is too early: the game rewrites its config when it exits,
        so a hold that matched at launch can be too short by the time a scan
        starts -- and a too-short hold never restarts the run at all."""
        scanner = build_scanner(selected_template_names=lambda: ["LIGHT"])
        self._quiet(scanner)

        with patch.dict(config.user_config, {"SKIP_REROLL_WARNING": True}):
            with patch.object(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False):
                with patch.object(config, "EVALUATION_MODE", "templates"):
                    with patch.object(threading, "Thread", FakeThread):
                        with patch.object(
                            config, "refresh_reset_hold_duration", return_value=0.25
                        ) as refresh:
                            with patch.object(config, "RESET_HOLD_DURATION", 1.05):
                                scanner.toggle_main_loop()

        refresh.assert_called_once()
        messages = [str(message) for message, _tag in scanner.calls["log"]]
        self.assertTrue(
            any("0.25" in m and "1.05" in m for m in messages),
            f"expected a raised-hold notice naming both values, got {messages}",
        )

    def test_starting_a_scan_stays_quiet_when_the_threshold_still_matches(self) -> None:
        scanner = build_scanner(selected_template_names=lambda: ["LIGHT"])
        self._quiet(scanner)

        with patch.dict(config.user_config, {"SKIP_REROLL_WARNING": True}):
            with patch.object(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False):
                with patch.object(config, "EVALUATION_MODE", "templates"):
                    with patch.object(threading, "Thread", FakeThread):
                        with patch.object(
                            config, "refresh_reset_hold_duration", return_value=None
                        ) as refresh:
                            scanner.toggle_main_loop()

        refresh.assert_called_once()
        messages = [str(message) for message, _tag in scanner.calls["log"]]
        self.assertFalse(
            any("Reset Hold Duration was" in m for m in messages),
            f"a scan start must not log a correction that did not happen: {messages}",
        )

    def test_the_scan_worker_is_a_daemon_running_the_background_loop(self) -> None:
        """Pinned because the daemon flag is the whole shutdown contract.

        The worker is never joined; `stop_event` plus `scan_event` unblock it
        and it exits on its own. A non-daemon worker would keep the process
        alive after the window closed, and nothing else in the suite reads
        this argument.
        """
        scanner = build_scanner(selected_template_names=lambda: ["LIGHT"])
        self._quiet(scanner)

        with patch.dict(config.user_config, {"SKIP_REROLL_WARNING": True}):
            with patch.object(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False):
                with patch.object(config, "EVALUATION_MODE", "templates"):
                    with patch.object(threading, "Thread", FakeThread):
                        scanner.toggle_main_loop()

        self.assertIs(scanner.scanner_thread.daemon, True)
        self.assertEqual(scanner.scanner_thread.target, scanner.background_loop)

    def test_toggle_main_loop_logs_scores_tiers_with_colors(self) -> None:
        scanner = build_scanner()
        self._quiet(scanner)
        updated_scores = dict(config.SCORES_SYSTEM)
        updated_scores["active_tiers"] = ["Light", "Perfect", "Perfect+"]

        with patch.dict(config.user_config, {"SKIP_REROLL_WARNING": True}):
            with patch.object(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False):
                with patch.object(config, "EVALUATION_MODE", "scores"):
                    with patch.object(config, "SCORES_SYSTEM", updated_scores):
                        with patch.object(threading, "Thread", FakeThread):
                            scanner.toggle_main_loop()

        self.assertIn(
            (
                ["[*] Active Tiers: ", "Light", ", ", "Perfect", ", ", "Perfect+"],
                [None, "WHITE", None, "YELLOW", None, "LIGHTRED_EX"],
            ),
            scanner.calls["log"],
        )
        self.assertEqual(
            scanner.template_stats,
            {
                "Light": {"rerolls_since_last": 0, "history": []},
                "Perfect": {"rerolls_since_last": 0, "history": []},
                "Perfect+": {"rerolls_since_last": 0, "history": []},
            },
        )
        self.assertTrue(scanner.scanner_thread.started)

    def test_toggle_main_loop_refuses_to_start_without_a_template(self) -> None:
        scanner = build_scanner(selected_template_names=lambda: [])

        with patch.dict(config.user_config, {"SKIP_REROLL_WARNING": True}):
            with patch.object(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False):
                with patch.object(config, "EVALUATION_MODE", "templates"):
                    with patch.object(threading, "Thread", FakeThread):
                        scanner.toggle_main_loop()

        self.assertIsNone(scanner.scanner_thread)
        messages = [message for message, _tag in scanner.calls["log"]]
        self.assertTrue(any("must select at least one template" in str(m) for m in messages))

    def test_toggle_main_loop_shows_obs_reminder_once_per_session(self) -> None:
        shown: list[str] = []

        class Dialog:
            def exec(self):
                shown.append("exec")
                return 1

        scanner = build_scanner(
            selected_template_names=lambda: ["LIGHT"],
            obs_reminder_dialog=lambda: (shown.append("built"), Dialog())[1],
        )
        self._quiet(scanner)

        def start_once():
            with patch.dict(
                config.user_config,
                {"SKIP_REROLL_WARNING": True, "SHOW_OBS_REMINDER_ON_START_SCANNER": True},
            ):
                with patch.object(config, "SHOW_OBS_REMINDER_ON_START_SCANNER", True):
                    with patch.object(config, "EVALUATION_MODE", "templates"):
                        with patch.object(threading, "Thread", FakeThread):
                            scanner.toggle_main_loop()

        start_once()
        self.assertEqual(shown, ["built", "exec"])
        self.assertTrue(scanner.obs_recording_reminder_shown)
        self.assertTrue(scanner.scanner_thread.started)

        scanner.scanner_thread = None
        start_once()
        self.assertEqual(shown, ["built", "exec"])
        self.assertTrue(scanner.scanner_thread.started)

    def test_toggle_main_loop_aborts_when_the_reroll_warning_is_declined(self) -> None:
        scanner = build_scanner(
            reroll_warning_dialog=lambda: SimpleNamespace(
                exec=lambda: 0, result=False, dont_show_again=False
            ),
        )

        with patch.dict(config.user_config, {"SKIP_REROLL_WARNING": False}):
            with patch.object(threading, "Thread", FakeThread):
                scanner.toggle_main_loop()

        self.assertIsNone(scanner.scanner_thread)

    def test_hotkey_starts_scanning_inside_running_monitor(self) -> None:
        scanner = build_scanner()
        scanner.scanner_thread = AliveThread()
        scanner.is_ready_to_start = True
        scanner.is_running = False

        scanner.toggle_scan_event()

        self.assertTrue(scanner.is_running)
        self.assertTrue(scanner.scan_event.is_set())
        self.assertIn(
            ("[*] Scan started. Looking for selected target...", None), scanner.calls["log"]
        )

    def test_hotkey_pauses_scanning_without_stopping_monitor(self) -> None:
        scanner = build_scanner()
        scanner.scanner_thread = AliveThread()
        scanner.scan_event.set()
        scanner.is_ready_to_start = True
        scanner.is_running = True

        scanner.toggle_scan_event()

        self.assertFalse(scanner.is_running)
        self.assertFalse(scanner.scan_event.is_set())
        self.assertIn(
            ("[*] Scan paused. Press the scan hotkey again to resume.", None),
            scanner.calls["log"],
        )

    def test_the_scan_hotkey_reaches_the_scanner_through_run_control(self) -> None:
        """The boundary itself: the hotkey is run control's, the state is not.

        `toggle_scan_event` moved to `Scanner` in step 25c, so this asserts the
        wiring rather than either half -- a `toggle_scan` port left pointing at
        a stub would pass every single-object test above.
        """
        scanner, run_control = build_pair()
        scanner.scanner_thread = AliveThread()
        scanner.is_ready_to_start = True

        run_control.hotkey_toggle_scanning()

        self.assertTrue(scanner.is_running)
        self.assertTrue(scanner.scan_event.is_set())

    def test_the_scan_hotkey_refuses_before_the_monitor_is_started(self) -> None:
        scanner = build_scanner()
        scanner.scanner_thread = DeadThread()

        scanner.toggle_scan_event()

        self.assertFalse(scanner.is_running)
        messages = [str(message) for message, _tag in scanner.calls["log"]]
        self.assertTrue(any("Press Start first" in m for m in messages))

    def test_the_scan_hotkey_refuses_while_the_scanner_is_still_connecting(self) -> None:
        scanner = build_scanner()
        scanner.scanner_thread = AliveThread()
        scanner.is_ready_to_start = False

        scanner.toggle_scan_event()

        self.assertFalse(scanner.is_running)
        self.assertFalse(scanner.scan_event.is_set())
        messages = [str(message) for message, _tag in scanner.calls["log"]]
        self.assertTrue(any("still connecting" in m for m in messages))


class FocusWaitTests(unittest.TestCase):
    """`wait_for_game_window_focus` is the only place run control reads scan state."""

    def test_keyboard_mode_still_waits_when_game_window_is_not_active(self) -> None:
        scanner, run_control = build_pair()
        scanner.scan_event.set()
        active_results = [False, False, True]
        run_control.is_game_window_active = lambda _process_name: active_results.pop(0)
        sleeps: list[float] = []

        with patch.object(time, "sleep", sleeps.append):
            self.assertTrue(run_control.wait_for_game_window_focus(PROCESS_NAME))

        self.assertEqual(sleeps, [0.3])
        messages = [str(message) for message, _tag in run_control.calls["log"]]
        self.assertIn("[WAIT] Game window is not active. Auto-reroll paused...", messages)
        self.assertIn("[+] Game window active again. Auto-reroll resumed.", messages)

    def test_the_focus_wait_gives_up_when_the_scan_is_paused(self) -> None:
        scanner, run_control = build_pair()
        scanner.scan_event.clear()
        run_control.is_game_window_active = lambda _process_name: False

        with patch.object(time, "sleep", lambda _seconds: self.fail("must not poll")):
            self.assertFalse(run_control.wait_for_game_window_focus(PROCESS_NAME))

        messages = [str(message) for message, _tag in run_control.calls["log"]]
        self.assertNotIn("[+] Game window active again. Auto-reroll resumed.", messages)

    def test_the_focus_wait_gives_up_when_the_run_is_stopped(self) -> None:
        scanner, run_control = build_pair()
        scanner.scan_event.set()
        scanner.stop_event.set()
        run_control.is_game_window_active = lambda _process_name: False

        with patch.object(time, "sleep", lambda _seconds: self.fail("must not poll")):
            self.assertFalse(run_control.wait_for_game_window_focus(PROCESS_NAME))

    def test_confirmed_target_in_keyboard_mode_keeps_focus_check_and_esc(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        focus_checks: list[str] = []
        scanner, run_control = build_pair(
            provider=KeyboardRunControlProvider(
                fake_keyboard,
                reset_hotkey="r",
                reset_hold_duration=0.1,
            ),
        )
        del scanner  # the subject is run control; the pair is here for the port
        run_control.wait_for_game_window_focus = (
            lambda process_name: focus_checks.append(process_name) or True
        )
        run_control.bring_game_window_to_front = lambda _process_name: self.fail(
            "keyboard mode should not bring window forward"
        )

        with patch_everywhere("keyboard", fake_keyboard):
            self.assertTrue(run_control.handle_confirmed_target_window(PROCESS_NAME))

        self.assertEqual(focus_checks, [PROCESS_NAME])
        self.assertEqual(fake_keyboard.press_and_release_calls, ["esc"])

    def test_confirmed_target_presses_nothing_without_the_keyboard_module(self) -> None:
        run_control = build_run_control()

        with patch.object(gui_run_control, "keyboard", None):
            self.assertTrue(run_control.handle_confirmed_target_window(PROCESS_NAME))

        self.assertEqual(run_control.calls["log"], [])


class BackgroundLoopTests(unittest.TestCase):
    def test_background_loop_cleanup_clears_scan_event_after_stop_wake(self) -> None:
        scanner = build_scanner()
        scanner.stop_event.set()
        scanner.scan_event.set()
        scanner.is_running = True
        scanner.is_ready_to_start = True
        scanner.client = object()

        scanner.background_loop()

        self.assertFalse(scanner.scan_event.is_set())
        self.assertFalse(scanner.is_running)
        self.assertFalse(scanner.is_ready_to_start)

    def test_background_loop_reuses_stable_snapshot_for_candidate(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.get_map_stats_calls = 0

            def wait_for_map_ready(self, **_kwargs: object) -> dict[str, int]:
                return {"Moais": 4, "Microwaves": 1}

            def get_map_generation_state(self) -> object:
                return object()

            def get_map_stats(self) -> dict[str, int]:
                self.get_map_stats_calls += 1
                return {"Moais": 999}

            def close(self) -> None:
                pass

        client = FakeClient()
        scanner, run_control = build_pair()
        scanner.client = client
        scanner.scan_event.set()
        scanner.is_running = True
        scanner.is_ready_to_start = True
        run_control.is_game_window_active = lambda _process_name: True
        run_control.wait_for_game_window_focus = lambda _process_name: True
        run_control.handle_confirmed_target_window = (
            lambda _process_name: scanner.stop_event.set() or True
        )

        with patch_everywhere("adapt_map_stats", lambda raw_stats: raw_stats), patch.object(
            gui_scanner,
            "evaluate_candidate",
            lambda stats, _active, context=None: (
                {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None
            ),
        ):
            scanner.background_loop()

        # Held locally: the loop's exit block calls `close_client`, which sets
        # `client` to None. The pre-step version of this test stubbed that
        # method out on the app double.
        self.assertEqual(client.get_map_stats_calls, 0)

    def test_background_loop_reconnects_new_game_pid_and_keeps_scanning(self) -> None:
        class FakeClient:
            def __init__(self, process_id: int) -> None:
                self.memory = SimpleNamespace(_pm=SimpleNamespace(process_id=process_id))
                self.closed = False
                self.wait_calls = 0

            def close(self) -> None:
                self.closed = True

            def wait_for_map_ready(self, **_kwargs: object) -> dict[str, int]:
                self.wait_calls += 1
                return {"Moais": 4, "Microwaves": 1}

            def get_map_generation_state(self) -> object:
                return object()

        old_client = FakeClient(1234)
        new_client = FakeClient(5678)
        created_clients: list[str] = []

        scanner, run_control = build_pair()
        scanner.client = old_client
        scanner.scan_event.set()
        scanner.is_running = True
        scanner.is_ready_to_start = True
        run_control.is_game_window_active = lambda _process_name: True
        run_control.wait_for_game_window_focus = lambda _process_name: True
        run_control.foreground_game_process_id = lambda _process_name: 5678
        run_control.handle_confirmed_target_window = (
            lambda _process_name: scanner.stop_event.set() or True
        )

        def create_client(*, process_name: str) -> FakeClient:
            created_clients.append(process_name)
            return new_client

        with patch.object(gui_scanner, "GameDataClient", create_client), patch.object(
            gui_scanner, "adapt_map_stats", lambda raw_stats: raw_stats
        ), patch.object(
            gui_scanner,
            "evaluate_candidate",
            lambda _stats, _active, context=None: {"name": "Perfect", "color": "GREEN"},
        ):
            scanner.background_loop()

        self.assertTrue(old_client.closed)
        self.assertEqual(created_clients, [PROCESS_NAME])
        self.assertEqual(new_client.wait_calls, 1)
        self.assertTrue(new_client.closed)

    def test_the_stale_client_disconnect_disarms_the_scanner(self) -> None:
        """The `is_ready_to_start` reset is invisible after the loop exits.

        The loop's normal-exit block clears the flag anyway, so a test that
        runs the loop to completion cannot tell whether the disconnect reset
        it. Calling the method directly is the only place the difference shows.
        """
        client = SimpleNamespace(
            memory=SimpleNamespace(_pm=SimpleNamespace(process_id=1234)),
            close=lambda: None,
        )
        scanner, run_control = build_pair()
        scanner.client = client
        scanner.is_ready_to_start = True
        run_control.foreground_game_process_id = lambda _process_name: 5678

        self.assertTrue(scanner._disconnect_stale_scanner_client(PROCESS_NAME))

        self.assertIsNone(scanner.client)
        self.assertFalse(scanner.is_ready_to_start)

    def test_the_stale_client_disconnect_is_skipped_when_the_pid_matches(self) -> None:
        client = SimpleNamespace(
            memory=SimpleNamespace(_pm=SimpleNamespace(process_id=1234)),
            close=lambda: self.fail("must not close a live client"),
        )
        scanner, run_control = build_pair()
        scanner.client = client
        scanner.is_ready_to_start = True
        run_control.foreground_game_process_id = lambda _process_name: 1234

        self.assertFalse(scanner._disconnect_stale_scanner_client(PROCESS_NAME))
        self.assertIs(scanner.client, client)
        self.assertTrue(scanner.is_ready_to_start)

    def test_reroll_map_returns_false_when_scan_is_paused(self) -> None:
        scanner, run_control = build_pair(
            provider=SimpleNamespace(
                restart_run=lambda: self.fail("restart_run should not be called while paused"),
            ),
        )
        scanner.client = None

        self.assertFalse(scanner.reroll_map())

    def test_reroll_map_refuses_without_a_run_control_provider(self) -> None:
        scanner, run_control = build_pair(provider=None)
        scanner.scan_event.set()

        self.assertFalse(scanner.reroll_map())

        messages = [str(message) for message, _tag in scanner.calls["log"]]
        self.assertTrue(any("Run control provider is not available" in m for m in messages))

    def test_the_lost_connection_branch_clears_scan_event_and_the_client(self) -> None:
        """The three exceptional branches differ only *inside* the loop.

        `MemoryReadError` is the one that disarms: it clears `scan_event`,
        drops both flags and closes the client. Sampling after the loop returns
        cannot distinguish it from the other two, because the normal-exit block
        does all four of those things as well.
        """
        from infra.memory.reader import MemoryReadError

        sampled: dict[str, object] = {}
        closes: list[str] = []

        class FakeClient:
            def wait_for_map_ready(self, **_kwargs):
                raise MemoryReadError("module gone")

            def close(self):
                closes.append("closed")

        scanner, run_control = build_pair()
        scanner.client = FakeClient()
        scanner.scan_event.set()
        scanner.is_running = True
        scanner.is_ready_to_start = True
        run_control.is_game_window_active = lambda _process_name: True
        run_control.wait_for_game_window_focus = lambda _process_name: True

        def reconnect(*, process_name):
            sampled.update({
                "is_running": scanner.is_running,
                "is_ready_to_start": scanner.is_ready_to_start,
                "scan_event": scanner.scan_event.is_set(),
                "client_is_none": scanner.client is None,
            })
            scanner.stop_event.set()
            scanner.scan_event.set()
            return FakeClient()

        with patch.object(gui_scanner, "GameDataClient", reconnect), \
                patch.object(time, "sleep", lambda _seconds: None):
            scanner.background_loop()

        self.assertEqual(sampled, {
            "is_running": False,
            "is_ready_to_start": False,
            "scan_event": False,
            "client_is_none": True,
        })
        self.assertEqual(closes, ["closed", "closed"])


class SessionStatsTests(unittest.TestCase):
    def test_log_reroll_stats_tracks_session_and_persistent_totals(self) -> None:
        refreshed: list[int] = []
        scanner = build_scanner(
            refresh_session_stats_snapshot=lambda: refreshed.append(scanner.session_rerolls),
        )
        scanner.session_rerolls = 3
        scanner.template_stats = {"Perfect": {"rerolls_since_last": 2, "history": []}}

        with patch.object(config, "TOTAL_REROLLS", 10):
            with patch.object(config, "save_config") as save_config:
                scanner.log_reroll_stats()

                self.assertEqual(scanner.session_rerolls, 4)
                self.assertEqual(scanner.template_stats["Perfect"]["rerolls_since_last"], 3)
                self.assertEqual(config.TOTAL_REROLLS, 11)
                self.assertEqual(config.user_config["TOTAL_REROLLS"], 11)
                save_config.assert_not_called()
                self.assertTrue(scanner._total_rerolls_dirty)
                self.assertEqual(refreshed, [4])

                scanner._flush_total_rerolls(force=True)
                save_config.assert_called_once_with(config.user_config)

    # `build_session_stats_tab` is deliberately **not** called from this suite.
    # Step 23 measured what happens: a test that builds real Qt widgets after
    # some earlier test has created a `QApplication` takes the interpreter down
    # mid-run with 0xC0000409 and exit 127 -- no traceback, a truncated report,
    # and every test after it silently unreported. This exact test did it while
    # being written. The live construction is covered where real widgets are
    # safe: `tools/step23_startup_smoke.py` builds the real `MegabonkApp` and
    # asserts the tab list still reads
    # ['Logs', 'Session Stats', 'Live Stats', ...] in order. What is checkable
    # here without widgets is the ownership, below.

    def test_the_status_repaint_reports_every_scan_state(self) -> None:
        status = FakeLabel()
        toggle = FakeLabel()
        scanner = build_scanner(status_label=lambda: status, toggle_btn=lambda: toggle)

        scanner.update_status_ui()
        idle = (status.text(), toggle.text())

        scanner.scanner_thread = AliveThread()
        scanner.update_status_ui()
        waiting = status.text()
        scanner.is_ready_to_start = True
        scanner.update_status_ui()
        armed = status.text()
        scanner.is_running = True
        scanner.update_status_ui()
        running = status.text()

        self.assertEqual(idle[1], "Start Scanner")
        self.assertIn("IDLE", idle[0])
        self.assertIn("WAITING FOR GAME", waiting)
        self.assertIn("ARMED", armed)
        self.assertIn("RUNNING", running)
        self.assertEqual(toggle.text(), "Stop Scanner")

    def test_the_log_is_silent_without_an_invoker(self) -> None:
        """Step 19's failure shape, pinned rather than fixed.

        `log` does not raise when it cannot post -- it stops writing, and the
        only symptom is an empty Logs panel. The point of asserting it is that
        a port wired to the wrong owner produces exactly this and nothing else.
        """
        box = FakeLogBox()
        posted = build_scanner(log_box=lambda: box, can_log=lambda: True)
        posted.log("hello")
        self.assertIn("hello", box.text())

        silent_box = FakeLogBox()
        silent = build_scanner(log_box=lambda: silent_box, can_log=lambda: False)
        silent.log("hello")
        self.assertEqual(silent_box.text(), "")

    def test_the_session_clock_reschedules_itself_and_stops_at_shutdown(self) -> None:
        scheduled: list[int] = []
        scanner = build_scanner(
            schedule=lambda delay_ms, _callback: scheduled.append(int(delay_ms)),
        )
        scanner.update_timer()
        self.assertEqual(scheduled, [1000])

        shutting_down = build_scanner(
            schedule=lambda delay_ms, _callback: scheduled.append(int(delay_ms)),
            is_shutting_down=lambda: True,
        )
        shutting_down.update_timer()
        self.assertEqual(scheduled, [1000])

    def test_shutdown_releases_the_worker_and_forces_the_reroll_flush(self) -> None:
        scanner = build_scanner()
        scanner._total_rerolls_dirty = True

        with patch.object(config, "save_config") as save_config:
            scanner.shutdown()

        self.assertTrue(scanner.stop_event.is_set())
        self.assertTrue(scanner.scan_event.is_set())
        save_config.assert_called_once_with(config.user_config)


class BoundaryStructureTests(unittest.TestCase):
    """One AST pass over both modules, rather than a test per forbidden name.

    Step 25's "done when" clause is that no line of either component reaches
    `window`, `tabview`, `log_box`, the VOD recorder or the Twitch thread
    through an ambient `self`. That is a property of the source, so it is
    checked once against the source -- and it keeps holding for names nobody
    thinks to write a test for, which a hand-listed set does not.
    """

    FORBIDDEN = {
        # `gui_layout`'s widgets -- step 26's, reached through ports.
        "window", "tabview", "log_box", "status_label", "toggle_btn",
        # other owners' runtimes, reached by `MegabonkApp.on_closing` instead.
        "player_stats_vod_recorder", "twitch_auth_thread", "coordinator",
        "close_overlay_server", "stop_in_game_overlay", "stop_twitch_bot",
        "destroy",
        # `_invoker` and `_is_shutting_down` are deliberately absent: both are
        # ports (`can_log`, `is_shutting_down`) stored under names that read
        # like the app attributes they replaced. What matters is that the value
        # is supplied at construction, not what the field is called.
    }

    def _self_reads(self, module):
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(module))
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        reads: dict[str, set[str]] = {}
        for class_def in classes:
            names = set()
            for node in ast.walk(class_def):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"
                    and isinstance(node.ctx, ast.Load)
                ):
                    names.add(node.attr)
            reads[class_def.name] = names
        return reads

    def test_neither_component_reaches_another_owner_through_self(self) -> None:
        for module in (gui_scanner, gui_run_control):
            for class_name, names in self._self_reads(module).items():
                trespass = sorted(names & self.FORBIDDEN)
                self.assertEqual(
                    trespass,
                    [],
                    f"{module.__name__}.{class_name} reads {trespass} off `self`; "
                    "those belong to gui_layout or to another component and must "
                    "arrive as named ports",
                )

    def test_the_two_mixins_are_gone(self) -> None:
        for module, gone in ((gui_scanner, "ScannerMixin"), (gui_run_control, "RunControlMixin")):
            self.assertFalse(
                hasattr(module, gone),
                f"{gone} is back; step 25 converted it into a component",
            )
        self.assertTrue(hasattr(gui_scanner, "Scanner"))
        self.assertTrue(hasattr(gui_run_control, "RunControl"))

    def test_the_abort_predicate_has_exactly_one_definition(self) -> None:
        """The hand-written copies of the cancellation condition are gone.

        `stop_event.is_set() or not scan_event.is_set()` was written out in
        four places before step 25 -- once as `_scan_abort_requested`, twice in
        `wait_for_game_window_focus` and once in the loop's `abort_condition`
        lambda. Four copies of one rule is how a fix lands in three of them.
        """
        import ast
        import inspect

        def code_only(module, class_name):
            """One class's source, with docstrings and comments removed.

            Scoped to the class rather than the module for two reasons. Both
            modules *describe* the predicate in prose, so a substring count
            over raw source finds the documentation as well as the code and
            reports three. And `build_run_control` legitimately names
            `toggle_scan_event` -- which contains `scan_event` as a substring
            -- because wiring the port is exactly the composition root's job.
            `ast.unparse` drops comments; the walk below drops docstrings.
            """
            tree = ast.parse(inspect.getsource(module))
            tree = next(
                node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            )
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if (
                    isinstance(body, list)
                    and body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    body.pop(0)
            return ast.unparse(tree)

        scanner_code = code_only(gui_scanner, "Scanner")
        run_control_code = code_only(gui_run_control, "RunControl")
        self.assertEqual(
            (scanner_code + run_control_code).count(
                "self.stop_event.is_set() or not self.scan_event.is_set()"
            ),
            1,
        )
        # And run control names neither event at all -- it asks the predicate.
        self.assertNotIn("scan_event", run_control_code)
        self.assertNotIn("stop_event", run_control_code)


if __name__ == "__main__":
    unittest.main()
