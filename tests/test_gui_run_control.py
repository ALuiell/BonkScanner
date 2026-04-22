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
    def __init__(self, pid: int = 1234) -> None:
        self.pid = pid
        self.uninitialize_calls = 0

    def uninitialize(self) -> types.SimpleNamespace:
        self.uninitialize_calls += 1
        return types.SimpleNamespace(pid=self.pid)


class FakeThread:
    def __init__(self, *, target: object, args: tuple[object, ...], daemon: bool) -> None:
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
        inject_error: Exception | None = None,
    ) -> None:
        self.pid = pid
        self.skipped = skipped
        self.inject_error = inject_error
        self.inject_calls = 0

    def inject_once(self) -> types.SimpleNamespace:
        self.inject_calls += 1
        if self.inject_error is not None:
            raise self.inject_error
        return types.SimpleNamespace(pid=self.pid, skipped=self.skipped)


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
