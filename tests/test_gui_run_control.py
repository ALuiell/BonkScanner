from __future__ import annotations

import types
import unittest
from copy import deepcopy
from unittest.mock import patch

import gui
from run_control import HookRunControlProvider, KeyboardRunControlProvider


class FakeEntry:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class FakeVar:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value


class FakeSettingsMaster:
    def __init__(self) -> None:
        self.events: list[str] = []

    def setup_hotkeys(self) -> None:
        self.events.append("setup_hotkeys")

    def update_status_ui(self) -> None:
        self.events.append("update_status_ui")

    def apply_run_control_mode(self) -> None:
        self.events.append("apply_run_control_mode")

    def log(self, _message: str, tag: str | None = None) -> None:
        del tag
        self.events.append("log")


class FakeDetachLoader:
    def __init__(self, pid: int = 1234, error: Exception | None = None) -> None:
        self.pid = pid
        self.error = error
        self.uninitialize_calls = 0

    def uninitialize(self) -> types.SimpleNamespace:
        self.uninitialize_calls += 1
        if self.error is not None:
            raise self.error
        return types.SimpleNamespace(pid=self.pid)


class FakeThread:
    def __init__(self, *, target: object, args: tuple[object, ...] = (), daemon: bool) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True


class FakeHookLoopLoader:
    def __init__(
        self,
        *,
        pid: int = 1234,
        skipped: bool = False,
        inject_error: Exception | list[Exception | None] | None = None,
    ) -> None:
        self.pid = pid
        self.skipped = skipped
        self.inject_error = inject_error
        self.inject_calls = 0

    def inject_once(self) -> types.SimpleNamespace:
        self.inject_calls += 1
        inject_error = self.inject_error
        if isinstance(inject_error, list):
            inject_error = inject_error.pop(0) if inject_error else None
        if inject_error is not None:
            raise inject_error
        return types.SimpleNamespace(pid=self.pid, skipped=self.skipped)


class FakeKeyboardModule:
    def __init__(self) -> None:
        self.press_and_release_calls: list[str] = []

    def press_and_release(self, key: str) -> None:
        self.press_and_release_calls.append(key)


class FakeForegroundGui:
    def __init__(self) -> None:
        self.foreground_window = 222
        self.set_foreground_calls = 0
        self.set_window_pos_calls: list[tuple[int, int]] = []

    def IsIconic(self, _window: int) -> bool:
        return False

    def ShowWindow(self, _window: int, _command: int) -> None:
        pass

    def BringWindowToTop(self, _window: int) -> None:
        pass

    def SetForegroundWindow(self, window: int) -> None:
        self.set_foreground_calls += 1
        if self.set_foreground_calls == 1:
            raise RuntimeError("direct foreground denied")
        self.foreground_window = window

    def GetForegroundWindow(self) -> int:
        return self.foreground_window

    def SetWindowPos(self, window: int, insert_after: int, *_args: object) -> None:
        self.set_window_pos_calls.append((window, insert_after))

    def IsWindowVisible(self, _window: int) -> bool:
        return True


class GuiRunControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config_values = {
            "HOTKEY": gui.config.HOTKEY,
            "RESET_HOTKEY": gui.config.RESET_HOTKEY,
            "MAP_LOAD_DELAY": gui.config.MAP_LOAD_DELAY,
            "RESET_HOLD_DURATION": gui.config.RESET_HOLD_DURATION,
            "NATIVE_HOOK_ENABLED": gui.config.NATIVE_HOOK_ENABLED,
        }
        self.original_user_config = deepcopy(gui.config.user_config)

    def tearDown(self) -> None:
        for name, value in self.original_config_values.items():
            setattr(gui.config, name, value)
        gui.config.user_config.clear()
        gui.config.user_config.update(self.original_user_config)

    def test_settings_save_updates_native_hook_enabled_and_applies_run_control_mode(self) -> None:
        master = FakeSettingsMaster()
        destroyed: list[bool] = []
        dialog = types.SimpleNamespace(
            hotkey_entry=FakeEntry("f7"),
            reset_hotkey_entry=FakeEntry("r"),
            map_load_delay_entry=FakeEntry("0.5"),
            reset_hold_duration_entry=FakeEntry("0.25"),
            native_hook_enabled_var=FakeVar(False),
            master=master,
            destroy=lambda: destroyed.append(True),
        )

        with patch.object(gui.config, "save_config") as save_config:
            with patch.object(gui.config, "update_game_reset_time") as update_game_reset_time:
                gui.SettingsDialog.save(dialog)

        self.assertFalse(gui.config.NATIVE_HOOK_ENABLED)
        self.assertFalse(gui.config.user_config["NATIVE_HOOK_ENABLED"])
        self.assertIn("apply_run_control_mode", master.events)
        self.assertTrue(save_config.called)
        self.assertTrue(update_game_reset_time.called)
        self.assertEqual(destroyed, [True])

    def test_apply_run_control_mode_detaches_hook_and_switches_to_keyboard_provider(self) -> None:
        loader = FakeDetachLoader()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = loader
        app.native_hook_thread = object()
        app.native_hook_generation = 1
        app.run_control_provider = object()
        app._native_hook_admin_warning_logged = True
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", False):
            gui.MegabonkApp.apply_run_control_mode(app)

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertIsNone(app.native_hook_loader)
        self.assertIsNone(app.native_hook_thread)
        self.assertEqual(app.native_hook_generation, 2)
        self.assertIsInstance(app.run_control_provider, KeyboardRunControlProvider)
        self.assertIn(("[+] Native hooks detached for PID 1234.", "success"), logs)

    def test_apply_run_control_mode_enables_hook_provider_and_starts_worker(self) -> None:
        fake_loader = object()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = None
        app.native_hook_thread = None
        app.native_hook_generation = 0
        app.run_control_provider = object()
        app._native_hook_admin_warning_logged = False
        app.native_hook_loop = lambda *_args: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: True

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            with patch.object(gui, "NativeHookLoader", return_value=fake_loader):
                with patch.object(gui.threading, "Thread", FakeThread):
                    gui.MegabonkApp.apply_run_control_mode(app)

        self.assertIs(app.native_hook_loader, fake_loader)
        self.assertIsInstance(app.run_control_provider, HookRunControlProvider)
        self.assertEqual(app.native_hook_generation, 1)
        self.assertTrue(app.native_hook_thread.started)
        self.assertIn(("[*] Native hook restart control enabled.", None), logs)

    def test_check_admin_rights_logs_hook_warning_when_hook_mode_is_enabled_without_admin(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False
        app._native_hook_admin_warning_logged = False

        with patch.object(gui.os, "name", "nt"):
            with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
                gui.MegabonkApp.check_admin_rights(app)

        self.assertIn(
            ("[*] Native hook may not inject without Administrator privileges; attempting anyway.", "warning"),
            logs,
        )
        self.assertNotIn(("⚠️ WARNING: Script is not running as Administrator!", "warning"), logs)
        self.assertNotIn(("⚠️ Hotkeys may not work while the game window is active.", "warning"), logs)

    def test_check_admin_rights_logs_keyboard_warnings_when_hook_mode_is_disabled(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.os, "name", "nt"):
            with patch.object(gui.config, "NATIVE_HOOK_ENABLED", False):
                gui.MegabonkApp.check_admin_rights(app)

        self.assertNotIn(
            ("[*] Native hook may not inject without Administrator privileges; attempting anyway.", "warning"),
            logs,
        )
        self.assertIn(("⚠️ WARNING: Script is not running as Administrator!", "warning"), logs)
        self.assertIn(("⚠️ Hotkeys may not work while the game window is active.", "warning"), logs)

    def test_enable_hook_run_control_logs_hook_warning_without_admin(self) -> None:
        fake_loader = object()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = None
        app.native_hook_thread = None
        app.native_hook_generation = 0
        app.run_control_provider = object()
        app._native_hook_admin_warning_logged = False
        app.native_hook_loop = lambda *_args: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            with patch.object(gui, "NativeHookLoader", return_value=fake_loader):
                with patch.object(gui.threading, "Thread", FakeThread):
                    gui.MegabonkApp.enable_hook_run_control(app)

        self.assertIn(
            ("[*] Native hook may not inject without Administrator privileges; attempting anyway.", "warning"),
            logs,
        )

    def test_startup_admin_warning_is_not_duplicated_by_hook_enable(self) -> None:
        fake_loader = object()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = None
        app.native_hook_thread = None
        app.native_hook_generation = 0
        app.run_control_provider = object()
        app._native_hook_admin_warning_logged = False
        app.native_hook_loop = lambda *_args: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.os, "name", "nt"):
            with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
                gui.MegabonkApp.check_admin_rights(app)
                with patch.object(gui, "NativeHookLoader", return_value=fake_loader):
                    with patch.object(gui.threading, "Thread", FakeThread):
                        gui.MegabonkApp.enable_hook_run_control(app)

        hook_warning = ("[*] Native hook may not inject without Administrator privileges; attempting anyway.", "warning")
        self.assertEqual(logs.count(hook_warning), 1)

    def test_keyboard_mode_resets_hook_admin_warning_for_later_hook_enable(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app._native_hook_admin_warning_logged = True
        app.log = lambda message, tag=None: logs.append((message, tag))

        gui.MegabonkApp.enable_keyboard_run_control(app)

        self.assertFalse(app._native_hook_admin_warning_logged)

    def test_hook_mode_bypasses_game_window_focus_wait(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = HookRunControlProvider(object(), map_load_delay=0)
        app.is_game_window_active = lambda _process_name: self.fail("hook mode should not check focus")

        self.assertTrue(gui.MegabonkApp.wait_for_game_window_focus(app, "Megabonk.exe"))

    def test_keyboard_mode_still_waits_when_game_window_is_not_active(self) -> None:
        logs: list[tuple[str, str | None]] = []
        sleeps: list[float] = []
        active_results = [False, False, True]
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = KeyboardRunControlProvider(
            None,
            reset_hotkey="r",
            reset_hold_duration=0.1,
            map_load_delay=0.2,
        )
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.scan_event.set()
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_game_window_active = lambda _process_name: active_results.pop(0)

        with patch.object(gui.time, "sleep", sleeps.append):
            self.assertTrue(gui.MegabonkApp.wait_for_game_window_focus(app, "Megabonk.exe"))

        self.assertEqual(sleeps, [0.3])
        self.assertIn(("[WAIT] Game window is not active. Auto-reroll paused...", "warning"), logs)
        self.assertIn(("[+] Game window active again. Auto-reroll resumed.", "success"), logs)

    def test_confirmed_target_in_hook_mode_brings_game_forward_without_esc(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = HookRunControlProvider(object(), map_load_delay=0)
        app.bring_game_window_to_front_calls: list[str] = []
        app.bring_game_window_to_front = app.bring_game_window_to_front_calls.append
        app.wait_for_game_window_focus = lambda _process_name: self.fail("hook mode should not wait for focus")

        with patch.object(gui, "keyboard", fake_keyboard):
            self.assertTrue(gui.MegabonkApp.handle_confirmed_target_window(app, "Megabonk.exe"))

        self.assertEqual(app.bring_game_window_to_front_calls, ["Megabonk.exe"])
        self.assertEqual(fake_keyboard.press_and_release_calls, [])

    def test_confirmed_target_in_keyboard_mode_keeps_focus_check_and_esc(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        focus_checks: list[str] = []
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = KeyboardRunControlProvider(
            fake_keyboard,
            reset_hotkey="r",
            reset_hold_duration=0.1,
            map_load_delay=0.2,
        )
        app.wait_for_game_window_focus = lambda process_name: focus_checks.append(process_name) or True
        app.bring_game_window_to_front = lambda _process_name: self.fail("keyboard mode should not bring window forward")

        with patch.object(gui, "keyboard", fake_keyboard):
            self.assertTrue(gui.MegabonkApp.handle_confirmed_target_window(app, "Megabonk.exe"))

        self.assertEqual(focus_checks, ["Megabonk.exe"])
        self.assertEqual(fake_keyboard.press_and_release_calls, ["esc"])

    def test_activate_game_window_uses_topmost_fallback_when_direct_foreground_fails(self) -> None:
        fake_gui = FakeForegroundGui()
        app = object.__new__(gui.MegabonkApp)
        app.try_attached_foreground_window = lambda _window: False

        with patch.object(gui, "win32gui", fake_gui):
            ok, error = gui.MegabonkApp.activate_game_window(app, 111)

        self.assertTrue(ok)
        self.assertEqual(error, "")
        self.assertEqual(fake_gui.set_foreground_calls, 2)
        self.assertEqual(fake_gui.set_window_pos_calls, [(111, -1), (111, -2)])

    def test_toggle_main_loop_clears_stale_scan_event_before_starting_worker(self) -> None:
        logs: list[tuple[object, object | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.scanner_thread = None
        app.checkboxes = {"Any": FakeVar(True)}
        app.refresh_stats_ui = lambda: None
        app.background_loop = lambda: None
        app.update_status_ui = lambda: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.stop_event.set()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True

        with patch.object(gui.config, "EVALUATION_MODE", "templates"):
            with patch.object(gui.threading, "Thread", FakeThread):
                gui.MegabonkApp.toggle_main_loop(app)

        self.assertFalse(app.scan_event.is_set())
        self.assertFalse(app.stop_event.is_set())
        self.assertFalse(app.is_running)
        self.assertFalse(app.is_ready_to_start)
        self.assertTrue(app.scanner_thread.started)

    def test_background_loop_cleanup_clears_scan_event_after_stop_wake(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.stop_event.set()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True
        app.after = lambda _delay, callback: callback()
        app.update_status_ui = lambda: None

        gui.MegabonkApp.background_loop(app)

        self.assertFalse(app.scan_event.is_set())
        self.assertFalse(app.is_running)
        self.assertFalse(app.is_ready_to_start)

    def test_on_closing_detaches_native_hooks_and_invalidates_worker(self) -> None:
        loader = FakeDetachLoader()
        logs: list[tuple[str, str | None]] = []
        destroyed: list[bool] = []
        app = object.__new__(gui.MegabonkApp)
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.native_hook_loader = loader
        app.native_hook_thread = object()
        app.native_hook_generation = 7
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.destroy = lambda: destroyed.append(True)

        with patch.object(gui, "keyboard", None):
            gui.MegabonkApp.on_closing(app)

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertTrue(app.stop_event.is_set())
        self.assertTrue(app.scan_event.is_set())
        self.assertIsNone(app.native_hook_loader)
        self.assertIsNone(app.native_hook_thread)
        self.assertEqual(app.native_hook_generation, 8)
        self.assertEqual(destroyed, [True])
        self.assertIn(("[+] Native hooks detached for PID 1234.", "success"), logs)

    def test_on_closing_continues_when_native_hook_detach_fails(self) -> None:
        loader = FakeDetachLoader(error=gui.HookLoadError("remote status 17"))
        logs: list[tuple[str, str | None]] = []
        destroyed: list[bool] = []
        app = object.__new__(gui.MegabonkApp)
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.native_hook_loader = loader
        app.native_hook_thread = object()
        app.native_hook_generation = 2
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.destroy = lambda: destroyed.append(True)

        with patch.object(gui, "keyboard", None):
            gui.MegabonkApp.on_closing(app)

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertIsNone(app.native_hook_loader)
        self.assertIsNone(app.native_hook_thread)
        self.assertEqual(app.native_hook_generation, 3)
        self.assertEqual(destroyed, [True])
        self.assertIn(
            ("[WAIT] Native hook detach failed during shutdown: remote status 17", "warning"),
            logs,
        )

    def test_on_closing_continues_when_game_process_is_gone(self) -> None:
        loader = FakeDetachLoader(error=gui.HookProcessNotFoundError("Waiting for process 'Megabonk.exe'."))
        logs: list[tuple[str, str | None]] = []
        destroyed: list[bool] = []
        app = object.__new__(gui.MegabonkApp)
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.native_hook_loader = loader
        app.native_hook_thread = object()
        app.native_hook_generation = 4
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.destroy = lambda: destroyed.append(True)

        with patch.object(gui, "keyboard", None):
            gui.MegabonkApp.on_closing(app)

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertIsNone(app.native_hook_loader)
        self.assertIsNone(app.native_hook_thread)
        self.assertEqual(app.native_hook_generation, 5)
        self.assertEqual(destroyed, [True])
        self.assertIn(
            (
                "[WAIT] Native hook detach skipped during shutdown: Waiting for process 'Megabonk.exe'.",
                "warning",
            ),
            logs,
        )

    def test_native_hook_loop_attempts_injection_without_admin(self) -> None:
        loader = FakeHookLoopLoader()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.stop_event = types.SimpleNamespace(is_set=lambda: False, wait=lambda _seconds: None)
        app.native_hook_generation = 1
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            gui.MegabonkApp.native_hook_loop(app, loader, 1)

        self.assertEqual(loader.inject_calls, 1)
        self.assertIn(("[+] Native hook injected into PID 1234.", "success"), logs)

    def test_native_hook_loop_logs_injection_failure_without_admin(self) -> None:
        loader = FakeHookLoopLoader(inject_error=gui.HookLoadError("OpenProcess(1234) failed"))
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.stop_event = types.SimpleNamespace(is_set=lambda: False, wait=lambda _seconds: None)
        app.native_hook_generation = 1
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            gui.MegabonkApp.native_hook_loop(app, loader, 1)

        self.assertEqual(loader.inject_calls, 1)
        self.assertIn(
            ("[-] Native hook injection failed: OpenProcess(1234) failed", "error"),
            logs,
        )
        self.assertNotIn(("[+] Native hook injected into PID 1234.", "success"), logs)

    def test_native_hook_loop_retries_when_game_runtime_is_not_ready(self) -> None:
        loader = FakeHookLoopLoader(
            inject_error=[gui.HookProcessNotReadyError("runtime not ready"), None],
        )
        waits: list[float] = []
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.stop_event = types.SimpleNamespace(is_set=lambda: False, wait=lambda seconds: waits.append(seconds))
        app.native_hook_generation = 1
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: True

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            gui.MegabonkApp.native_hook_loop(app, loader, 1)

        self.assertEqual(loader.inject_calls, 2)
        self.assertEqual(waits, [1.0])
        self.assertIn(("[WAIT] runtime not ready", None), logs)
        self.assertIn(("[+] Native hook injected into PID 1234.", "success"), logs)

    def test_native_hook_loop_logs_success_for_admin_injection(self) -> None:
        loader = FakeHookLoopLoader(pid=6728)
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.stop_event = types.SimpleNamespace(is_set=lambda: False, wait=lambda _seconds: None)
        app.native_hook_generation = 1
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: True

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            gui.MegabonkApp.native_hook_loop(app, loader, 1)

        self.assertEqual(loader.inject_calls, 1)
        self.assertIn(("[+] Native hook injected into PID 6728.", "success"), logs)


if __name__ == "__main__":
    unittest.main()
