from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

import config
from hotkey_manager import HotkeyBinding, ModifierAwareHotkeyManager
from run_control import KeyboardRunControlProvider

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
        self.enable_keyboard_run_control()

    def apply_run_control_mode(self, *, detach_hooks: bool = True):
        del detach_hooks
        self.enable_keyboard_run_control()

    def enable_keyboard_run_control(self):
        self.run_control_provider = KeyboardRunControlProvider(
            keyboard,
            reset_hotkey=lambda: config.RESET_HOTKEY,
            reset_hold_duration=lambda: config.RESET_HOLD_DURATION,
            map_load_delay=lambda: config.MIN_DELAY,
        )

    def check_admin_rights(self):
        if os.name != "nt":
            return
        if not self.is_running_as_admin():
            self.log("\u26a0\ufe0f WARNING: Script is not running as Administrator!", tag="warning")
            self.log("\u26a0\ufe0f Hotkeys may not work while the game window is active.", tag="warning")

    def is_running_as_admin(self) -> bool:
        if os.name != "nt":
            return True
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

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
                bindings = [
                    HotkeyBinding(config.HOTKEY, self.hotkey_toggle_scanning),
                    HotkeyBinding(config.PLAYER_STATS_RECORD_HOTKEY, self.hotkey_toggle_player_stats_recording),
                ]
                if hasattr(self, "hotkey_toggle_in_game_overlay_edit"):
                    bindings.append(HotkeyBinding(
                        getattr(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9"),
                        self.hotkey_toggle_in_game_overlay_edit
                    ))
                manager.start(tuple(bindings))
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

    def is_keyboard_run_control_active(self) -> bool:
        return isinstance(self.run_control_provider, KeyboardRunControlProvider)

    def is_game_window_active(self, process_name: str) -> bool:
        del process_name
        if win32gui is None or win32process is None:
            return True
        foreground_window = win32gui.GetForegroundWindow()
        if not foreground_window:
            return False
        game_process_id = self.get_game_process_id()
        if game_process_id is None:
            return False
        try:
            _, foreground_process_id = win32process.GetWindowThreadProcessId(foreground_window)
        except Exception:
            return False
        return int(foreground_process_id) == game_process_id

    def wait_for_game_window_focus(self, process_name: str) -> bool:
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
        del process_name
        game_process_id = self.get_game_process_id()
        if game_process_id is not None:
            return self.find_game_window_by_pid(game_process_id)
        return None

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

    def handle_confirmed_target_window(self, process_name: str) -> bool:
        if keyboard:
            if not self.wait_for_game_window_focus(process_name):
                return False
            keyboard.press_and_release("esc")

        return True
