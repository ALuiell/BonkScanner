from __future__ import annotations

import types
import unittest
from dataclasses import dataclass
from unittest.mock import patch

import app_run_control
from hook_loader import HookLoadError, HookProcessNotFoundError, HookProcessNotReadyError
from run_control import HookRunControlProvider, KeyboardRunControlProvider


@dataclass
class FakeConfig:
    PROCESS_NAME: str = "Megabonk.exe"
    NATIVE_HOOK_ENABLED: bool = True
    NATIVE_HOOK_DLL_PATH: str = ""
    application_path: str = "C:/BonkScanner"
    MIN_DELAY: float = 0.4
    RESET_HOTKEY: str = "r"
    RESET_HOLD_DURATION: float = 0.25


class FakeThread:
    def __init__(self, *, target: object, args: tuple[object, ...] = (), daemon: bool) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True


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


class AppRunControlTests(unittest.TestCase):
    def make_controller(self, **overrides: object) -> app_run_control.AppRunControl:
        config = overrides.pop("config", FakeConfig())
        stop_event = overrides.pop("stop_event", types.SimpleNamespace(is_set=lambda: False, wait=lambda _s: None))
        log = overrides.pop("log", lambda _message, tag=None: None)
        return app_run_control.AppRunControl(
            config=config,
            keyboard_module=overrides.pop("keyboard_module", None),
            threading_module=overrides.pop("threading_module", app_run_control.threading),
            NativeHookLoader=overrides.pop("NativeHookLoader", app_run_control.NativeHookLoader),
            HookRunControlProvider=overrides.pop("HookRunControlProvider", HookRunControlProvider),
            KeyboardRunControlProvider=overrides.pop("KeyboardRunControlProvider", KeyboardRunControlProvider),
            log=log,
            stop_event=stop_event,
            native_hook_loader=overrides.pop("native_hook_loader", None),
            native_hook_thread=overrides.pop("native_hook_thread", None),
            native_hook_generation=overrides.pop("native_hook_generation", 0),
            run_control_provider=overrides.pop("run_control_provider", None),
            native_hook_admin_warning_logged=overrides.pop("native_hook_admin_warning_logged", False),
            is_running_as_admin=overrides.pop("is_running_as_admin", None),
        )

    def test_apply_run_control_mode_switches_to_keyboard_and_detaches_loader(self) -> None:
        loader = FakeDetachLoader()
        logs: list[tuple[str, str | None]] = []
        controller = self.make_controller(
            config=FakeConfig(NATIVE_HOOK_ENABLED=False),
            native_hook_loader=loader,
            native_hook_thread=object(),
            native_hook_generation=1,
            run_control_provider=object(),
            native_hook_admin_warning_logged=True,
            log=lambda message, tag=None: logs.append((message, tag)),
        )

        controller.apply_run_control_mode()

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertIsNone(controller.native_hook_loader)
        self.assertIsNone(controller.native_hook_thread)
        self.assertEqual(controller.native_hook_generation, 2)
        self.assertIsInstance(controller.run_control_provider, KeyboardRunControlProvider)
        self.assertFalse(controller._native_hook_admin_warning_logged)
        self.assertIn(("[+] Native hooks detached for PID 1234.", "success"), logs)

    def test_enable_hook_run_control_starts_daemon_worker_and_logs_restart(self) -> None:
        fake_loader = object()
        logs: list[tuple[str, str | None]] = []
        controller = self.make_controller(
            config=FakeConfig(NATIVE_HOOK_ENABLED=True),
            run_control_provider=object(),
            log=lambda message, tag=None: logs.append((message, tag)),
            is_running_as_admin=lambda: True,
            NativeHookLoader=lambda *args, **kwargs: fake_loader,
            threading_module=types.SimpleNamespace(Thread=FakeThread),
        )

        controller.enable_hook_run_control()

        self.assertIs(controller.native_hook_loader, fake_loader)
        self.assertIsInstance(controller.run_control_provider, HookRunControlProvider)
        self.assertEqual(controller.native_hook_generation, 1)
        self.assertTrue(controller.native_hook_thread.started)
        self.assertIn(("[*] Native hook restart control enabled.", None), logs)

    def test_admin_warning_is_logged_once_across_startup_and_hook_enable(self) -> None:
        fake_loader = object()
        logs: list[tuple[str, str | None]] = []
        controller = self.make_controller(
            config=FakeConfig(NATIVE_HOOK_ENABLED=True),
            run_control_provider=object(),
            log=lambda message, tag=None: logs.append((message, tag)),
            is_running_as_admin=lambda: False,
            NativeHookLoader=lambda *args, **kwargs: fake_loader,
            threading_module=types.SimpleNamespace(Thread=FakeThread),
        )

        with patch.object(app_run_control.os, "name", "nt"):
            controller.check_admin_rights()
            controller.enable_hook_run_control()

        warning = (
            "[*] Native hook may not inject without Administrator privileges; attempting anyway.",
            "warning",
        )
        self.assertEqual(logs.count(warning), 1)

    def test_check_admin_rights_logs_keyboard_warnings_when_native_hook_is_disabled(self) -> None:
        logs: list[tuple[str, str | None]] = []
        controller = self.make_controller(
            config=FakeConfig(NATIVE_HOOK_ENABLED=False),
            log=lambda message, tag=None: logs.append((message, tag)),
            is_running_as_admin=lambda: False,
        )

        with patch.object(app_run_control.os, "name", "nt"):
            controller.check_admin_rights()

        self.assertIn(("⚠️ WARNING: Script is not running as Administrator!", "warning"), logs)
        self.assertIn(("⚠️ Hotkeys may not work while the game window is active.", "warning"), logs)
        self.assertNotIn(
            ("[*] Native hook may not inject without Administrator privileges; attempting anyway.", "warning"),
            logs,
        )

    def test_native_hook_loop_logs_success_and_skipped_results(self) -> None:
        success_logs: list[tuple[str, str | None]] = []
        skipped_logs: list[tuple[str, str | None]] = []
        success_controller = self.make_controller(
            config=FakeConfig(),
            native_hook_generation=1,
            log=lambda message, tag=None: success_logs.append((message, tag)),
        )
        skipped_controller = self.make_controller(
            config=FakeConfig(),
            native_hook_generation=1,
            log=lambda message, tag=None: skipped_logs.append((message, tag)),
        )

        success_controller.native_hook_loop(FakeHookLoopLoader(pid=6728), 1)
        skipped_controller.native_hook_loop(FakeHookLoopLoader(pid=6728, skipped=True), 1)

        self.assertIn(("[+] Native hook injected into PID 6728.", "success"), success_logs)
        self.assertIn(("[*] Native hook already injected for PID 6728.", None), skipped_logs)

    def test_native_hook_loop_retries_when_runtime_is_not_ready(self) -> None:
        loader = FakeHookLoopLoader(
            inject_error=[HookProcessNotReadyError("runtime not ready"), None],
        )
        waits: list[float] = []
        logs: list[tuple[str, str | None]] = []
        controller = self.make_controller(
            config=FakeConfig(),
            native_hook_generation=1,
            stop_event=types.SimpleNamespace(is_set=lambda: False, wait=lambda seconds: waits.append(seconds)),
            log=lambda message, tag=None: logs.append((message, tag)),
            is_running_as_admin=lambda: True,
        )

        controller.native_hook_loop(loader, 1)

        self.assertEqual(loader.inject_calls, 2)
        self.assertEqual(waits, [1.0])
        self.assertIn(("[WAIT] runtime not ready", None), logs)
        self.assertIn(("[+] Native hook injected into PID 1234.", "success"), logs)

    def test_native_hook_loop_logs_load_and_unexpected_errors(self) -> None:
        load_logs: list[tuple[str, str | None]] = []
        unexpected_logs: list[tuple[str, str | None]] = []
        load_controller = self.make_controller(
            config=FakeConfig(),
            native_hook_generation=1,
            log=lambda message, tag=None: load_logs.append((message, tag)),
        )
        unexpected_controller = self.make_controller(
            config=FakeConfig(),
            native_hook_generation=1,
            log=lambda message, tag=None: unexpected_logs.append((message, tag)),
        )

        load_controller.native_hook_loop(FakeHookLoopLoader(inject_error=HookLoadError("OpenProcess(1234) failed")), 1)
        unexpected_controller.native_hook_loop(FakeHookLoopLoader(inject_error=RuntimeError("boom")), 1)

        self.assertIn(("[-] Native hook injection failed: OpenProcess(1234) failed", "error"), load_logs)
        self.assertIn(("[-] Unexpected native hook loader error: boom", "error"), unexpected_logs)

    def test_native_hook_loop_returns_without_work_when_loader_is_missing(self) -> None:
        controller = self.make_controller(config=FakeConfig())

        controller.native_hook_loop(None, 1)


if __name__ == "__main__":
    unittest.main()
