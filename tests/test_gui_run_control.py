from __future__ import annotations

import types
import unittest
from copy import deepcopy
from unittest.mock import patch

import gui
import window_control


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

    def test_wait_for_game_window_focus_delegates_to_window_control(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.is_hook_run_control_active = lambda: True
        app.is_game_window_active = lambda _process_name: True
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        logs: list[tuple[str, str | None]] = []
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(window_control, "wait_for_game_window_focus", return_value=True) as wait_for_focus:
            self.assertTrue(gui.MegabonkApp.wait_for_game_window_focus(app, "Megabonk.exe"))

        wait_for_focus.assert_called_once()

    def test_handle_confirmed_target_window_delegates_to_window_control(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        app = object.__new__(gui.MegabonkApp)
        app.is_hook_run_control_active = lambda: False
        app.bring_game_window_to_front = lambda _process_name: True
        app.wait_for_game_window_focus = lambda _process_name: True

        with patch.object(gui, "keyboard", fake_keyboard):
            with patch.object(window_control, "handle_confirmed_target_window", return_value=True) as handle_target:
                self.assertTrue(gui.MegabonkApp.handle_confirmed_target_window(app, "Megabonk.exe"))

        handle_target.assert_called_once()

    def test_bring_game_window_to_front_delegates_to_window_control(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.client = object()
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(window_control, "bring_game_window_to_front", return_value=True) as bring_window:
            self.assertTrue(gui.MegabonkApp.bring_game_window_to_front(app, "Megabonk.exe"))

        bring_window.assert_called_once()

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
