from __future__ import annotations

import types
import unittest
from copy import deepcopy
from unittest.mock import patch

import gui
from memory import MemoryReadError
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

    def set(self, value: bool) -> None:
        self.value = value


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


class FakeCtypesFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class FakeUser32:
    def __init__(self) -> None:
        self.attach_calls: list[tuple[int, int, bool]] = []
        self.keybd_event_calls: list[tuple[int, int, int, int]] = []
        self.AttachThreadInput = FakeCtypesFunction(self._attach_thread_input)
        self.keybd_event = FakeCtypesFunction(self._keybd_event)

    def _attach_thread_input(self, current_thread: int, target_thread: int, attach: bool) -> bool:
        self.attach_calls.append((current_thread, target_thread, attach))
        return True

    def _keybd_event(self, key: int, scan: int, flags: int, extra: int) -> None:
        self.keybd_event_calls.append((key, scan, flags, extra))


class FakeKernel32:
    def __init__(self, current_thread: int = 10) -> None:
        self.GetCurrentThreadId = FakeCtypesFunction(lambda: current_thread)


class FakeWindll:
    def __init__(self, user32: FakeUser32, kernel32: FakeKernel32) -> None:
        self.user32 = user32
        self.kernel32 = kernel32


class FakeForegroundGui:
    def __init__(self, *, fail_always: bool = False) -> None:
        self.fail_always = fail_always
        self.foreground_window = 222
        self.set_foreground_calls: list[int] = []
        self.show_window_calls: list[tuple[int, int]] = []
        self.bring_window_to_top_calls: list[int] = []

    def IsIconic(self, _window: int) -> bool:
        return False

    def ShowWindow(self, window: int, command: int) -> None:
        self.show_window_calls.append((window, command))

    def SetForegroundWindow(self, window: int) -> None:
        self.set_foreground_calls.append(window)
        if self.fail_always or len(self.set_foreground_calls) == 1:
            raise RuntimeError("foreground denied")
        self.foreground_window = window

    def GetForegroundWindow(self) -> int:
        return self.foreground_window

    def BringWindowToTop(self, window: int) -> None:
        self.bring_window_to_top_calls.append(window)


class FakeForegroundProcess:
    def GetWindowThreadProcessId(self, window: int) -> tuple[int, int]:
        thread_by_window = {
            111: 20,
            222: 30,
        }
        return thread_by_window.get(window, 40), 9000 + window


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

    def test_native_hook_toggle_prompts_for_confirmation_on_enable(self) -> None:
        dialog = types.SimpleNamespace(
            native_hook_enabled_var=FakeVar(True),
            _native_hook_toggle_guard=False,
        )

        with patch.object(gui.SettingsDialog, "prompt_native_hook_enable_confirmation", return_value=True) as prompt:
            gui.SettingsDialog.on_native_hook_toggle(dialog)

        prompt.assert_called_once_with(dialog)
        self.assertTrue(dialog.native_hook_enabled_var.get())

    def test_native_hook_toggle_reverts_checkbox_when_confirmation_is_cancelled(self) -> None:
        dialog = types.SimpleNamespace(
            native_hook_enabled_var=FakeVar(True),
            _native_hook_toggle_guard=False,
        )

        with patch.object(gui.SettingsDialog, "prompt_native_hook_enable_confirmation", return_value=False) as prompt:
            gui.SettingsDialog.on_native_hook_toggle(dialog)

        prompt.assert_called_once_with(dialog)
        self.assertFalse(dialog.native_hook_enabled_var.get())
        self.assertFalse(dialog._native_hook_toggle_guard)

    def test_native_hook_toggle_does_not_prompt_when_disabling(self) -> None:
        dialog = types.SimpleNamespace(
            native_hook_enabled_var=FakeVar(False),
            _native_hook_toggle_guard=False,
        )

        with patch.object(gui.SettingsDialog, "prompt_native_hook_enable_confirmation") as prompt:
            gui.SettingsDialog.on_native_hook_toggle(dialog)

        prompt.assert_not_called()
        self.assertFalse(dialog.native_hook_enabled_var.get())

    def test_settings_save_persists_confirmed_native_hook_enable(self) -> None:
        master = FakeSettingsMaster()
        destroyed: list[bool] = []
        dialog = types.SimpleNamespace(
            hotkey_entry=FakeEntry("f7"),
            reset_hotkey_entry=FakeEntry("r"),
            map_load_delay_entry=FakeEntry("0.5"),
            reset_hold_duration_entry=FakeEntry("0.25"),
            native_hook_enabled_var=FakeVar(True),
            master=master,
            destroy=lambda: destroyed.append(True),
        )

        with patch.object(gui.config, "save_config") as save_config:
            with patch.object(gui.config, "update_game_reset_time") as update_game_reset_time:
                gui.SettingsDialog.save(dialog)

        self.assertTrue(gui.config.NATIVE_HOOK_ENABLED)
        self.assertTrue(gui.config.user_config["NATIVE_HOOK_ENABLED"])
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

    def test_bring_game_window_to_front_uses_alt_attach_fallback_after_direct_failure(self) -> None:
        fake_gui = FakeForegroundGui()
        fake_process = FakeForegroundProcess()
        fake_user32 = FakeUser32()
        fake_windll = FakeWindll(fake_user32, FakeKernel32())
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.find_game_window = lambda _process_name: 111
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui, "win32gui", fake_gui):
            with patch.object(gui, "win32process", fake_process):
                with patch.object(gui.ctypes, "windll", fake_windll):
                    self.assertTrue(gui.MegabonkApp.bring_game_window_to_front(app, "Megabonk.exe"))

        self.assertEqual(fake_gui.show_window_calls, [(111, 5)])
        self.assertEqual(fake_gui.set_foreground_calls, [111, 111])
        self.assertEqual(fake_gui.bring_window_to_top_calls, [111])
        self.assertEqual(
            fake_user32.attach_calls,
            [
                (10, 20, True),
                (10, 30, True),
                (10, 20, False),
                (10, 30, False),
            ],
        )
        self.assertEqual(fake_user32.keybd_event_calls, [(0x12, 0, 0, 0), (0x12, 0, 0x0002, 0)])
        self.assertEqual(logs, [])

    def test_alt_attach_fallback_detaches_threads_when_foreground_fails(self) -> None:
        fake_gui = FakeForegroundGui(fail_always=True)
        fake_process = FakeForegroundProcess()
        fake_user32 = FakeUser32()
        fake_windll = FakeWindll(fake_user32, FakeKernel32())
        app = object.__new__(gui.MegabonkApp)

        with patch.object(gui, "win32gui", fake_gui):
            with patch.object(gui, "win32process", fake_process):
                with patch.object(gui.ctypes, "windll", fake_windll):
                    with self.assertRaisesRegex(RuntimeError, "foreground denied"):
                        gui.MegabonkApp.try_alt_attach_foreground_window(app, 111)

        self.assertEqual(
            fake_user32.attach_calls,
            [
                (10, 20, True),
                (10, 30, True),
                (10, 20, False),
                (10, 30, False),
            ],
        )

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

    def test_background_loop_reuses_stable_snapshot_for_candidate(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.get_map_stats_calls = 0
                self.get_shady_guy_items_calls = 0

            def wait_for_map_ready(self, **_kwargs: object) -> dict[str, int]:
                return {"Moais": 4, "Microwaves": 1}

            def get_map_generation_state(self) -> object:
                return object()

            def get_map_stats(self) -> dict[str, int]:
                self.get_map_stats_calls += 1
                return {"Moais": 999}

            def get_shady_guy_items(self) -> list[object]:
                self.get_shady_guy_items_calls += 1
                return [types.SimpleNamespace(name="Key")]

        app = object.__new__(gui.MegabonkApp)
        app.client = FakeClient()
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True
        app.after = lambda _delay, callback: callback()
        app.update_status_ui = lambda: None
        app.wait_for_game_window_focus = lambda _process_name: True
        app.check_best_map = lambda _stats: None
        app.check_worst_map = lambda _stats: None
        app.evaluate_candidate = lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None
        app.log_target_found = lambda _name: None
        app.handle_confirmed_target_window = lambda _process_name: app.stop_event.set() or True
        app.close_client = lambda: None
        logs: list[tuple[str, str | None]] = []
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui, "adapt_map_stats", lambda raw_stats: raw_stats):
            gui.MegabonkApp.background_loop(app)

        self.assertEqual(app.client.get_map_stats_calls, 0)
        self.assertEqual(app.client.get_shady_guy_items_calls, 1)
        self.assertIn(("Shady Guy items: [Key]", "success"), logs)

    def test_background_loop_rejects_candidate_when_shady_guy_items_empty(self) -> None:
        class FakeClient:
            def wait_for_map_ready(self, **_kwargs: object) -> dict[str, int]:
                return {"Moais": 4, "Microwaves": 1}

            def get_map_generation_state(self) -> object:
                return object()

            def get_shady_guy_items(self) -> list[object]:
                return []

        app = object.__new__(gui.MegabonkApp)
        app.client = FakeClient()
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True
        app.after = lambda _delay, callback: callback()
        app.update_status_ui = lambda: None
        app.wait_for_game_window_focus = lambda _process_name: True
        app.check_best_map = lambda _stats: None
        app.check_worst_map = lambda _stats: None
        app.evaluate_candidate = lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None
        log_target_found_calls: list[str] = []
        app.log_target_found = lambda name: log_target_found_calls.append(name)
        handle_calls: list[str] = []
        app.handle_confirmed_target_window = lambda _process_name: handle_calls.append("called") or True
        app.close_client = lambda: None
        reroll_calls: list[str] = []
        app.reroll_map = lambda: reroll_calls.append("called") or app.stop_event.set()
        logs: list[tuple[str, str | None]] = []
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui, "adapt_map_stats", lambda raw_stats: raw_stats):
            with patch.object(gui.config, "MIN_DELAY", 0):
                gui.MegabonkApp.background_loop(app)

        self.assertEqual(log_target_found_calls, [])
        self.assertEqual(handle_calls, [])
        self.assertEqual(reroll_calls, ["called"])
        self.assertTrue(
            any(
                tag == "warning" and "rejected: Shady Guy items are empty" in message
                for message, tag in logs
            )
        )

    def test_background_loop_rejects_candidate_when_required_shady_guy_items_missing(self) -> None:
        class FakeClient:
            def wait_for_map_ready(self, **_kwargs: object) -> dict[str, int]:
                return {"Moais": 4, "Microwaves": 1}

            def get_map_generation_state(self) -> object:
                return object()

            def get_shady_guy_items(self) -> list[object]:
                return [types.SimpleNamespace(name="GymSauce"), types.SimpleNamespace(name="Beacon")]

        app = object.__new__(gui.MegabonkApp)
        app.client = FakeClient()
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True
        app.after = lambda _delay, callback: callback()
        app.update_status_ui = lambda: None
        app.wait_for_game_window_focus = lambda _process_name: True
        app.check_best_map = lambda _stats: None
        app.check_worst_map = lambda _stats: None
        app.evaluate_candidate = lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None
        log_target_found_calls: list[str] = []
        app.log_target_found = lambda name: log_target_found_calls.append(name)
        handle_calls: list[str] = []
        app.handle_confirmed_target_window = lambda _process_name: handle_calls.append("called") or True
        app.close_client = lambda: None
        reroll_calls: list[str] = []
        app.reroll_map = lambda: reroll_calls.append("called") or app.stop_event.set()
        logs: list[tuple[str, str | None]] = []
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui, "adapt_map_stats", lambda raw_stats: raw_stats):
            with patch.object(gui.config, "MIN_DELAY", 0):
                gui.MegabonkApp.background_loop(app)

        self.assertEqual(log_target_found_calls, [])
        self.assertEqual(handle_calls, [])
        self.assertEqual(reroll_calls, ["called"])
        self.assertTrue(
            any(
                tag == "warning" and "none of the required Shady Guy items were found" in message
                for message, tag in logs
            )
        )

    def test_background_loop_rejects_candidate_when_shady_guy_item_read_fails(self) -> None:
        class FakeClient:
            def wait_for_map_ready(self, **_kwargs: object) -> dict[str, int]:
                return {"Moais": 4, "Microwaves": 1}

            def get_map_generation_state(self) -> object:
                return object()

            def get_shady_guy_items(self) -> list[object]:
                raise MemoryReadError("boom")

        app = object.__new__(gui.MegabonkApp)
        app.client = FakeClient()
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True
        app.after = lambda _delay, callback: callback()
        app.update_status_ui = lambda: None
        app.wait_for_game_window_focus = lambda _process_name: True
        app.check_best_map = lambda _stats: None
        app.check_worst_map = lambda _stats: None
        app.evaluate_candidate = lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None
        log_target_found_calls: list[str] = []
        app.log_target_found = lambda name: log_target_found_calls.append(name)
        handle_calls: list[str] = []
        app.handle_confirmed_target_window = lambda _process_name: handle_calls.append("called") or True
        app.close_client = lambda: None
        reroll_calls: list[str] = []
        app.reroll_map = lambda: reroll_calls.append("called") or app.stop_event.set()
        logs: list[tuple[str, str | None]] = []
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui, "adapt_map_stats", lambda raw_stats: raw_stats):
            with patch.object(gui.config, "MIN_DELAY", 0):
                gui.MegabonkApp.background_loop(app)

        self.assertEqual(log_target_found_calls, [])
        self.assertEqual(handle_calls, [])
        self.assertEqual(reroll_calls, ["called"])
        self.assertTrue(
            any(
                tag == "warning" and "rejected: failed to read Shady Guy items" in message
                for message, tag in logs
            )
        )

    def test_background_loop_rerolls_when_shady_guy_item_count_does_not_match_vendor_count(self) -> None:
        class FakeClient:
            def wait_for_map_ready(self, **_kwargs: object) -> dict[object, object]:
                return {
                    gui.MapStat.SHADY_GUY: types.SimpleNamespace(max=2),
                    "Moais": 4,
                    "Microwaves": 1,
                }

            def get_map_generation_state(self) -> object:
                return object()

            def get_shady_guy_items(self) -> list[object]:
                return [types.SimpleNamespace(name="Key")]

        app = object.__new__(gui.MegabonkApp)
        app.client = FakeClient()
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True
        app.after = lambda _delay, callback: callback()
        app.update_status_ui = lambda: None
        app.wait_for_game_window_focus = lambda _process_name: True
        app.check_best_map = lambda _stats: None
        app.check_worst_map = lambda _stats: None
        app.evaluate_candidate = lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None
        log_target_found_calls: list[str] = []
        app.log_target_found = lambda name: log_target_found_calls.append(name)
        handle_calls: list[str] = []
        app.handle_confirmed_target_window = lambda _process_name: handle_calls.append("called") or True
        app.close_client = lambda: None
        reroll_calls: list[str] = []
        app.reroll_map = lambda: reroll_calls.append("called") or app.stop_event.set()
        logs: list[tuple[str, str | None]] = []
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui, "adapt_map_stats", lambda raw_stats: {"Moais": 4, "Microwaves": 1, "Shady Guy": 2}):
            gui.MegabonkApp.background_loop(app)

        self.assertEqual(log_target_found_calls, [])
        self.assertEqual(handle_calls, [])
        self.assertEqual(reroll_calls, ["called"])
        self.assertTrue(
            any(
                tag == "warning" and "expected 6 Shady Guy items from 2 vendors, but read 1" in message
                for message, tag in logs
            )
        )

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
