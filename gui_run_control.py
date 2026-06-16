from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from functools import partial

from PySide6.QtWidgets import QMessageBox

import config
from gui_dialogs import NativeHookWarningDialog
from hook_loader import (
    HookDllAccessError,
    HookLoadError,
    HookProcessNotFoundError,
    HookProcessNotReadyError,
    NativeHookLoader,
)
from hotkey_manager import HotkeyBinding, ModifierAwareHotkeyManager
from run_control import HookRunControlProvider, KeyboardRunControlProvider, RunControlError

try:
    import win32gui
    import win32process
except ImportError:
    win32gui = None
    win32process = None

try:
    import keyboard
except ImportError:
    keyboard = None

class RunControlMixin:

    def initialize_run_control(self):
        if not getattr(config, "NATIVE_HOOK_ENABLED", True):
            self.enable_keyboard_run_control()
            return
        self.enable_hook_run_control()

    def apply_run_control_mode(self, *, detach_hooks: bool = True):
        if getattr(config, "NATIVE_HOOK_ENABLED", True):
            self.enable_hook_run_control()
        else:
            previous_loader = self.native_hook_loader
            self.native_hook_generation += 1
            self.native_hook_loader = None
            self.native_hook_thread = None

            if detach_hooks and previous_loader is not None:
                try:
                    previous_loader.uninitialize()
                    self.log("[+] Game restart helper disconnected.", tag="success")
                except HookProcessNotFoundError:
                    self.log("[WAIT] Game is already closed; restart helper disconnected.", tag="warning")
                except HookLoadError as exc:
                    self.log(
                        f"[WAIT] Could not disconnect game restart helper; switching to keyboard restart. Details: {exc}",
                        tag="warning",
                    )

            self.enable_keyboard_run_control()

    def enable_keyboard_run_control(self):
        self._native_hook_admin_warning_logged = False
        self.run_control_provider = KeyboardRunControlProvider(
            keyboard,
            reset_hotkey=lambda: config.RESET_HOTKEY,
            reset_hold_duration=lambda: config.RESET_HOLD_DURATION,
            map_load_delay=lambda: config.MIN_DELAY,
        )

    def enable_hook_run_control(self):
        if isinstance(self.run_control_provider, HookRunControlProvider):
            return

        self.warn_if_native_hook_needs_admin()

        dll_path = getattr(config, "NATIVE_HOOK_DLL_PATH", "") or None
        try:
            self.native_hook_loader = NativeHookLoader(
                config.PROCESS_NAME,
                dll_path=dll_path,
                base_path=config.application_path,
            )
        except HookLoadError as exc:
            self.handle_native_hook_unavailable(exc)
            return
        self.run_control_provider = HookRunControlProvider(
            self.native_hook_loader,
            map_load_delay=lambda: config.MIN_DELAY,
        )
        self.native_hook_generation += 1
        generation = self.native_hook_generation
        self.native_hook_thread = threading.Thread(
            target=self.native_hook_loop,
            args=(self.native_hook_loader, generation),
            daemon=True,
        )
        self.native_hook_thread.start()
        self.log("[*] Game restart helper enabled.")

    def handle_native_hook_unavailable(self, exc: Exception) -> None:
        self.native_hook_loader = None
        self.native_hook_thread = None
        self.enable_keyboard_run_control()
        self.log("[WAIT] Native helper is unavailable. Switching to keyboard restart.", tag="warning")
        self.log(f"[WAIT] Details: {exc}", tag="warning")
        self.after_idle(lambda: self.show_native_hook_error_dialog(exc))

    def show_native_hook_error_dialog(self, exc: Exception) -> None:
        if self._native_hook_error_dialog_visible:
            return

        self._native_hook_error_dialog_visible = True
        try:
            message_box = QMessageBox(self.window)
            message_box.setIcon(QMessageBox.Warning)
            message_box.setWindowTitle("Native Helper Blocked")
            message_box.setText("BonkScanner could not access BonkHook.dll.")
            message_box.setInformativeText(
                "This usually means your antivirus or another security tool "
                "quarantined or blocked the native helper."
            )
            instructions = (
                "What happened:\n"
                "BonkScanner uses BonkHook.dll for native restart control. Windows security software "
                "appears to have blocked or removed that file.\n\n"
                "What to do:\n"
                "1. Open your antivirus or Windows Security.\n"
                "2. Check quarantine / protection history.\n"
                "3. Restore BonkHook.dll or BonkScanner.exe if it was quarantined.\n"
                "4. Allow the file on this device or add an exclusion for the app folder.\n"
                "5. Restart BonkScanner after restoring the file.\n\n"
                "BonkScanner has switched to keyboard restart mode for now."
            )
            if isinstance(exc, HookDllAccessError):
                instructions += f"\n\nDetails:\n{exc}"
            message_box.setDetailedText(instructions)
            message_box.setStandardButtons(QMessageBox.Ok)
            message_box.exec()
        finally:
            self._native_hook_error_dialog_visible = False

    def native_hook_loop(self, loader: NativeHookLoader, generation: int):
        if loader is None:
            return

        logged_waiting = False
        while not self.stop_event.is_set() and generation == self.native_hook_generation:
            try:
                result = loader.inject_once()
                if generation != self.native_hook_generation:
                    return
                if result.skipped:
                    self.log("[*] Game restart helper is already connected.")
                else:
                    self.log("[+] Game restart helper connected successfully.", tag="success")
                return
            except HookProcessNotFoundError:
                if not logged_waiting:
                    self.log("[WAIT] Waiting for the game before connecting restart helper.")
                    logged_waiting = True
                self.stop_event.wait(1.0)
            except HookProcessNotReadyError:
                if not logged_waiting:
                    self.log("[WAIT] Game is starting up. Restart helper will connect automatically.")
                    logged_waiting = True
                self.stop_event.wait(1.0)
            except HookLoadError as exc:
                self.log(f"[-] Could not connect game restart helper. Details: {exc}", tag="error")
                if isinstance(exc, HookDllAccessError):
                    self.handle_native_hook_unavailable(exc)
                return
            except Exception as exc:
                self.log(f"[-] Unexpected restart helper error. Details: {exc}", tag="error")
                return

    def check_admin_rights(self):
        if os.name != "nt":
            return
        if not self.is_running_as_admin():
            if getattr(config, "NATIVE_HOOK_ENABLED", True):
                self.warn_if_native_hook_needs_admin()
                return
            self.log("\u26a0\ufe0f WARNING: Script is not running as Administrator!", tag="warning")
            self.log("\u26a0\ufe0f Hotkeys may not work while the game window is active.", tag="warning")

    def is_running_as_admin(self) -> bool:
        if os.name != "nt":
            return True
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def warn_if_native_hook_needs_admin(self):
        if self._native_hook_admin_warning_logged:
            return
        if not self.is_running_as_admin():
            self.log("[*] Game restart helper may need Administrator privileges; trying anyway.", tag="warning")
        self._native_hook_admin_warning_logged = True

    def toggle_game_setting(self, setting_key: str, label: str) -> bool:
        if not getattr(config, "NATIVE_HOOK_GAME_SETTING_HOTKEYS_ENABLED", False):
            self.log(
                f"[WAIT] {label} hotkey is disabled because hook-based game-setting hotkeys are off in Settings.",
                tag="warning",
            )
            return False

        loader = getattr(self, "native_hook_loader", None)
        if loader is None:
            dll_path = getattr(config, "NATIVE_HOOK_DLL_PATH", "") or None
            loader = NativeHookLoader(
                config.PROCESS_NAME,
                dll_path=dll_path,
                base_path=config.application_path,
            )

        try:
            if setting_key == "skip_chest_animation":
                toggled = loader.toggle_skip_chest_animation()
            elif setting_key == "auto_select_upgrades":
                toggled = loader.toggle_auto_select_upgrades()
            elif setting_key == "particle_opacity":
                toggled = loader.toggle_particles_opacity()
            else:
                self.log(f"[WAIT] Unsupported game setting toggle: {label}", tag="warning")
                return False
        except HookLoadError as exc:
            self.log(f"[WAIT] Could not toggle '{label}' live in the game. Details: {exc}", tag="warning")
            return False

        state_text = "ON" if toggled else "OFF"
        self.log(f"[+] {label}: {state_text}", tag="success")
        return True

    def setup_hotkeys(self):
        if keyboard:
            try:
                previous_manager = getattr(self, "_hotkey_manager", None)
                if previous_manager is not None:
                    previous_manager.stop()
                    self._hotkey_manager = None
                manager = ModifierAwareHotkeyManager(
                    keyboard,
                    allowed_game_keys=getattr(config, "HOTKEY_GAME_KEY_WHITELIST", ()),
                    is_game_window_active=lambda: self.is_game_window_active(config.PROCESS_NAME),
                )
                manager.start(
                    (
                        HotkeyBinding(config.HOTKEY, self.hotkey_toggle_scanning),
                        HotkeyBinding(config.PLAYER_STATS_RECORD_HOTKEY, self.hotkey_toggle_player_stats_recording),
                        HotkeyBinding(
                            config.TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY,
                            self.hotkey_toggle_skip_chest_animation,
                        ),
                        HotkeyBinding(
                            config.TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY,
                            self.hotkey_toggle_auto_select_upgrades,
                        ),
                        HotkeyBinding(
                            config.TOGGLE_PARTICLES_OPACITY_HOTKEY,
                            self.hotkey_toggle_particles_opacity,
                        ),
                    )
                )
                self._hotkey_manager = manager
            except Exception as exc:
                self.log(f"[WAIT] Could not register hotkeys: {exc}", tag="warning")

    def hotkey_toggle_scanning(self):
        self.after(0, self.toggle_scan_event)

    def toggle_scan_event(self):
        if self.scanner_thread is None or not self.scanner_thread.is_alive():
            self.log(f"[WAIT] Press Start first, then press {config.HOTKEY.upper()} in game to begin scanning.", tag="warning")
            self.update_status_ui()
            return

        if not self.is_ready_to_start:
            self.log("[WAIT] Scanner is still connecting to the game. Try the hotkey again once it is ARMED.", tag="warning")
            self.update_status_ui()
            return

        if self.is_running:
            self.is_running = False
            self.scan_event.clear()
            self.log("[*] Scan paused. Press the scan hotkey again to resume.")
        else:
            self.is_running = True
            self.scan_event.set()
            self.log("[*] Scan started. Looking for selected target...")
        self.update_status_ui()

    def hotkey_toggle_player_stats_recording(self):
        self.after(0, self.toggle_player_stats_recording)

    def hotkey_toggle_skip_chest_animation(self):
        self.after(0, partial(self.toggle_game_setting, "skip_chest_animation", "Skip Chest Animation"))

    def hotkey_toggle_auto_select_upgrades(self):
        self.after(0, partial(self.toggle_game_setting, "auto_select_upgrades", "Auto Level-Up"))

    def hotkey_toggle_particles_opacity(self):
        self.after(0, partial(self.toggle_game_setting, "particle_opacity", "Particles Opacity"))

    def get_game_process_id(self) -> int | None:
        if self.client is None:
            return None
        memory = getattr(self.client, "memory", None)
        pymem_client = getattr(memory, "_pm", None)
        process_id = getattr(pymem_client, "process_id", None)
        try:
            return int(process_id) if process_id else None
        except (TypeError, ValueError):
            return None

    def is_hook_run_control_active(self) -> bool:
        return isinstance(self.run_control_provider, HookRunControlProvider)

    def is_keyboard_run_control_active(self) -> bool:
        return isinstance(self.run_control_provider, KeyboardRunControlProvider)

    def is_game_window_active(self, process_name: str) -> bool:
        if win32gui is None or win32process is None:
            return True
        foreground_window = win32gui.GetForegroundWindow()
        if not foreground_window:
            return False
        game_process_id = self.get_game_process_id()
        if game_process_id is not None:
            try:
                _, foreground_process_id = win32process.GetWindowThreadProcessId(foreground_window)
                if int(foreground_process_id) == game_process_id:
                    return True
            except Exception:
                pass
        try:
            foreground_title = win32gui.GetWindowText(foreground_window) or ""
        except Exception:
            return False
        expected_title = os.path.splitext(process_name)[0]
        return bool(expected_title and expected_title.lower() in foreground_title.lower())

    def wait_for_game_window_focus(self, process_name: str) -> bool:
        if self.is_hook_run_control_active():
            return True
        if self.is_game_window_active(process_name):
            return True
        self.log("[WAIT] Game window is not active. Auto-reroll paused...", tag="warning")
        while not self.stop_event.is_set() and self.scan_event.is_set() and not self.is_game_window_active(process_name):
            time.sleep(0.3)
        if self.stop_event.is_set() or not self.scan_event.is_set():
            return False
        self.log("[+] Game window active again. Auto-reroll resumed.", tag="success")
        return True

    def bring_game_window_to_front(self, process_name: str) -> bool:
        if win32gui is None or win32process is None:
            self.log("[WAIT] Cannot bring game window to front: pywin32 is unavailable.", tag="warning")
            return False
        window = self.find_game_window(process_name)
        if not window:
            self.log("[WAIT] Cannot bring game window to front: game window was not found.", tag="warning")
            return False
        try:
            self.show_game_window(window)
            win32gui.SetForegroundWindow(window)
            return True
        except Exception as direct_exc:
            try:
                self.try_attach_foreground_window(window)
                return True
            except Exception as fallback_exc:
                self.log(
                    f"[WAIT] Cannot bring game window to front: {direct_exc}; ALT attach fallback failed: {fallback_exc}",
                    tag="warning",
                )
                return False

    @staticmethod
    def show_game_window(window: int) -> None:
        if hasattr(win32gui, "IsIconic") and win32gui.IsIconic(window):
            win32gui.ShowWindow(window, 9)
        elif hasattr(win32gui, "ShowWindow"):
            win32gui.ShowWindow(window, 5)

    def try_attach_foreground_window(self, window: int) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        current_thread = int(kernel32.GetCurrentThreadId())
        target_thread, _ = win32process.GetWindowThreadProcessId(window)
        foreground_window = win32gui.GetForegroundWindow()
        foreground_thread = None
        if foreground_window:
            foreground_thread, _ = win32process.GetWindowThreadProcessId(foreground_window)

        attached_threads = []
        seen_threads = set()
        for thread_id in (target_thread, foreground_thread):
            thread_id = int(thread_id) if thread_id else 0
            if not thread_id or thread_id == current_thread or thread_id in seen_threads:
                continue
            seen_threads.add(thread_id)
            if user32.AttachThreadInput(current_thread, thread_id, True):
                attached_threads.append(thread_id)

        try:
            self.send_alt_keypress(user32)
            if hasattr(win32gui, "BringWindowToTop"):
                win32gui.BringWindowToTop(window)
            win32gui.SetForegroundWindow(window)
        finally:
            for thread_id in attached_threads:
                user32.AttachThreadInput(current_thread, thread_id, False)

    @staticmethod
    def send_alt_keypress(user32) -> None:
        vk_menu = 0x12
        keyeventf_keyup = 0x0002
        user32.keybd_event(vk_menu, 0, 0, 0)
        user32.keybd_event(vk_menu, 0, keyeventf_keyup, 0)

    @staticmethod
    def is_visible_window(window: int) -> bool:
        try:
            return bool(window and (not hasattr(win32gui, "IsWindowVisible") or win32gui.IsWindowVisible(window)))
        except Exception:
            return False

    def find_game_window(self, process_name: str) -> int | None:
        game_process_id = self.get_game_process_id()
        if game_process_id is not None:
            window = self.find_game_window_by_pid(game_process_id)
            if window:
                return window
        return self.find_game_window_by_title(process_name)

    def find_game_window_by_pid(self, process_id: int) -> int | None:
        found_window = None

        def enum_callback(window, _extra):
            nonlocal found_window
            if found_window is not None or not self.is_visible_window(window):
                return
            try:
                _, window_process_id = win32process.GetWindowThreadProcessId(window)
            except Exception:
                return
            if int(window_process_id) == process_id:
                found_window = window

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as exc:
            self.log(f"[WAIT] Could not check the game window yet. Details: {exc}", tag="warning")
        return found_window

    def find_game_window_by_title(self, process_name: str) -> int | None:
        expected_title = os.path.splitext(process_name)[0]
        if not expected_title:
            return None

        found_window = None

        def enum_callback(window, _extra):
            nonlocal found_window
            if found_window is not None or not self.is_visible_window(window):
                return
            try:
                window_title = win32gui.GetWindowText(window) or ""
            except Exception:
                return
            if expected_title.lower() in window_title.lower():
                found_window = window

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as exc:
            self.log(f"[WAIT] Could not check the game window yet. Details: {exc}", tag="warning")
        return found_window

    def handle_confirmed_target_window(self, process_name: str) -> bool:
        if self.is_hook_run_control_active():
            self.bring_game_window_to_front(process_name)
            if keyboard:
                time.sleep(0.15)
                keyboard.press_and_release("esc")
            return True

        if keyboard:
            if not self.wait_for_game_window_focus(process_name):
                return False
            keyboard.press_and_release("esc")

        return True
