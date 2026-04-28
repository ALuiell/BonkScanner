from __future__ import annotations

import os
import threading
from typing import Callable

from hook_loader import HookLoadError, HookProcessNotFoundError, HookProcessNotReadyError, NativeHookLoader
from run_control import HookRunControlProvider, KeyboardRunControlProvider, RunControlError


LogFunction = Callable[[str, str | None], None]


class AppRunControl:
    def __init__(
        self,
        *,
        config,
        keyboard_module,
        threading_module=threading,
        NativeHookLoader=NativeHookLoader,
        HookRunControlProvider=HookRunControlProvider,
        KeyboardRunControlProvider=KeyboardRunControlProvider,
        log: LogFunction,
        stop_event,
        native_hook_loader=None,
        native_hook_thread=None,
        native_hook_generation: int = 0,
        run_control_provider=None,
        native_hook_admin_warning_logged: bool = False,
        is_running_as_admin: Callable[[], bool] | None = None,
    ) -> None:
        self.config = config
        self.keyboard_module = keyboard_module
        self.threading_module = threading_module
        self.NativeHookLoader = NativeHookLoader
        self.HookRunControlProvider = HookRunControlProvider
        self.KeyboardRunControlProvider = KeyboardRunControlProvider
        self.log = log
        self.stop_event = stop_event
        self.native_hook_loader = native_hook_loader
        self.native_hook_thread = native_hook_thread
        self.native_hook_generation = native_hook_generation
        self.run_control_provider = run_control_provider
        self._native_hook_admin_warning_logged = native_hook_admin_warning_logged
        self._is_running_as_admin = is_running_as_admin

    def apply_run_control_mode(self, *, detach_hooks: bool = True) -> None:
        if getattr(self.config, "NATIVE_HOOK_ENABLED", True):
            self.enable_hook_run_control()
            return

        previous_loader = self.native_hook_loader
        self.native_hook_generation += 1
        self.native_hook_loader = None
        self.native_hook_thread = None

        if detach_hooks and previous_loader is not None:
            try:
                result = previous_loader.uninitialize()
                self.log(f"[+] Native hooks detached for PID {result.pid}.", tag="success")
            except HookProcessNotFoundError as exc:
                self.log(f"[WAIT] Native hook detach skipped: {exc}", tag="warning")
            except HookLoadError as exc:
                self.log(f"[WAIT] Native hook detach failed; switching to keyboard restart: {exc}", tag="warning")

        self.enable_keyboard_run_control()

    def enable_keyboard_run_control(self) -> None:
        self._native_hook_admin_warning_logged = False
        self.run_control_provider = self.KeyboardRunControlProvider(
            self.keyboard_module,
            reset_hotkey=lambda: self.config.RESET_HOTKEY,
            reset_hold_duration=lambda: self.config.RESET_HOLD_DURATION,
            map_load_delay=lambda: self.config.MIN_DELAY,
        )

    def enable_hook_run_control(self) -> None:
        if isinstance(self.run_control_provider, self.HookRunControlProvider):
            return

        self.warn_if_native_hook_needs_admin()

        dll_path = getattr(self.config, "NATIVE_HOOK_DLL_PATH", "") or None
        self.native_hook_loader = self.NativeHookLoader(
            self.config.PROCESS_NAME,
            dll_path=dll_path,
            base_path=self.config.application_path,
        )
        self.run_control_provider = self.HookRunControlProvider(
            self.native_hook_loader,
            map_load_delay=lambda: self.config.MIN_DELAY,
        )
        self.native_hook_generation += 1
        generation = self.native_hook_generation
        self.native_hook_thread = self.threading_module.Thread(
            target=self.native_hook_loop,
            args=(self.native_hook_loader, generation),
            daemon=True,
        )
        self.native_hook_thread.start()
        self.log("[*] Native hook restart control enabled.")

    def native_hook_loop(self, loader: NativeHookLoader, generation: int) -> None:
        if loader is None:
            return

        logged_waiting = False
        while not self.stop_event.is_set() and generation == self.native_hook_generation:
            try:
                result = loader.inject_once()
                if generation != self.native_hook_generation:
                    return
                if result.skipped:
                    self.log(f"[*] Native hook already injected for PID {result.pid}.")
                else:
                    self.log(f"[+] Native hook injected into PID {result.pid}.", tag="success")
                return
            except HookProcessNotFoundError:
                if not logged_waiting:
                    self.log(f"[WAIT] Waiting for process '{self.config.PROCESS_NAME}' before native hook injection.")
                    logged_waiting = True
                self.stop_event.wait(1.0)
            except HookProcessNotReadyError as exc:
                if not logged_waiting:
                    self.log(f"[WAIT] {exc}")
                    logged_waiting = True
                self.stop_event.wait(1.0)
            except HookLoadError as exc:
                self.log(f"[-] Native hook injection failed: {exc}", tag="error")
                return
            except Exception as exc:
                self.log(f"[-] Unexpected native hook loader error: {exc}", tag="error")
                return

    def shutdown(self) -> None:
        hook_loader = self.native_hook_loader
        if hook_loader is None:
            return

        self.native_hook_generation += 1
        self.native_hook_loader = None
        self.native_hook_thread = None
        try:
            result = hook_loader.uninitialize()
            self.log(f"[+] Native hooks detached for PID {result.pid}.", tag="success")
        except HookProcessNotFoundError as exc:
            self.log(f"[WAIT] Native hook detach skipped during shutdown: {exc}", tag="warning")
        except HookLoadError as exc:
            self.log(f"[WAIT] Native hook detach failed during shutdown: {exc}", tag="warning")
        except Exception as exc:
            self.log(f"[WAIT] Unexpected native hook detach error during shutdown: {exc}", tag="warning")

    def check_admin_rights(self) -> None:
        if os.name != "nt":
            return

        if not self.is_running_as_admin():
            if getattr(self.config, "NATIVE_HOOK_ENABLED", True):
                self.warn_if_native_hook_needs_admin()
                return

            self.log("⚠️ WARNING: Script is not running as Administrator!", tag="warning")
            self.log("⚠️ Hotkeys may not work while the game window is active.", tag="warning")

    def is_running_as_admin(self) -> bool:
        if self._is_running_as_admin is not None:
            return bool(self._is_running_as_admin())

        if os.name != "nt":
            return True

        import ctypes

        try:
            return os.getuid() == 0
        except AttributeError:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0

    def warn_if_native_hook_needs_admin(self) -> None:
        if (
            getattr(self.config, "NATIVE_HOOK_ENABLED", True)
            and not getattr(self, "_native_hook_admin_warning_logged", False)
            and not self.is_running_as_admin()
        ):
            self.log(
                "[*] Native hook may not inject without Administrator privileges; attempting anyway.",
                tag="warning",
            )
            self._native_hook_admin_warning_logged = True
