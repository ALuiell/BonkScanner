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


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
GW_OWNER = 4


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
        process_id = self._attached_game_process_id()
        if process_id is not None:
            return process_id
        return self.find_game_process_id(config.PROCESS_NAME)

    def _attached_game_process_id(self) -> int | None:
        client = getattr(self, "client", None)
        if client is None:
            return None
        memory = getattr(client, "memory", None)
        pymem_client = getattr(memory, "_pm", None)
        process_id = getattr(pymem_client, "process_id", None)
        try:
            return int(process_id) if process_id else None
        except (TypeError, ValueError):
            return None

    def is_keyboard_run_control_active(self) -> bool:
        return isinstance(self.run_control_provider, KeyboardRunControlProvider)

    def is_game_window_active(self, process_name: str) -> bool:
        if win32gui is None or win32process is None:
            return True
        foreground_window = win32gui.GetForegroundWindow()
        if not foreground_window:
            return False
        try:
            _, foreground_process_id = win32process.GetWindowThreadProcessId(foreground_window)
        except Exception:
            return False
        try:
            foreground_process_id = int(foreground_process_id)
        except (TypeError, ValueError):
            return False
        if foreground_process_id <= 0:
            return False

        attached_process_id = self._attached_game_process_id()
        if attached_process_id is not None:
            return (
                foreground_process_id == attached_process_id
                and self.find_game_window_by_pid(attached_process_id, process_name=process_name) is not None
            )

        if not self._process_id_matches_name(foreground_process_id, process_name):
            return False
        return self.find_game_window_by_pid(foreground_process_id, process_name=process_name) is not None

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

    @staticmethod
    def _normalize_process_name(process_name: str) -> str:
        return os.path.basename(str(process_name or "")).strip().lower()

    @staticmethod
    def _window_process_id(window: int) -> int | None:
        if win32process is None:
            return None
        try:
            _, process_id = win32process.GetWindowThreadProcessId(window)
        except Exception:
            return None
        try:
            process_id = int(process_id)
        except (TypeError, ValueError):
            return None
        return process_id if process_id > 0 else None

    @staticmethod
    def _process_image_name(process_id: int) -> str | None:
        if os.name != "nt":
            return None
        try:
            process_id = int(process_id)
        except (TypeError, ValueError):
            return None
        if process_id <= 0:
            return None

        kernel32 = getattr(ctypes, "windll", None)
        kernel32 = getattr(kernel32, "kernel32", None)
        if kernel32 is None:
            return None

        open_process = getattr(kernel32, "OpenProcess", None)
        query_full_process_image_name = getattr(kernel32, "QueryFullProcessImageNameW", None)
        close_handle = getattr(kernel32, "CloseHandle", None)
        if open_process is None or query_full_process_image_name is None or close_handle is None:
            return None

        process_handle = open_process(PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not process_handle:
            return None

        try:
            buffer_size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(buffer_size.value)
            if not query_full_process_image_name(process_handle, 0, buffer, ctypes.byref(buffer_size)):
                return None
            return os.path.basename(buffer.value).strip().lower() or None
        except Exception:
            return None
        finally:
            try:
                close_handle(process_handle)
            except Exception:
                pass

    def _process_id_matches_name(self, process_id: int, process_name: str) -> bool:
        normalized_process_name = self._normalize_process_name(process_name)
        if not normalized_process_name:
            return False
        image_name = self._process_image_name(process_id)
        return bool(image_name and image_name == normalized_process_name)

    @staticmethod
    def _window_rect(window: int) -> tuple[int, int, int, int] | None:
        if win32gui is None or not hasattr(win32gui, "GetWindowRect"):
            return None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(window)
        except Exception:
            return None
        try:
            return int(left), int(top), int(right), int(bottom)
        except (TypeError, ValueError):
            return None

    def _window_selection_score(self, window: int, *, process_name: str | None = None) -> tuple[int, int, int] | None:
        rect = self._window_rect(window)
        if rect is None:
            return None
        left, top, right, bottom = rect
        width = max(0, right - left)
        height = max(0, bottom - top)
        if width <= 0 or height <= 0:
            return None

        title = ""
        if win32gui is not None and hasattr(win32gui, "GetWindowText"):
            try:
                title = str(win32gui.GetWindowText(window) or "").strip()
            except Exception:
                title = ""

        process_stem = os.path.splitext(self._normalize_process_name(process_name or ""))[0]
        title_lower = title.lower()
        title_matches_process = bool(process_stem and process_stem in title_lower)
        area = width * height
        return (
            1 if title_matches_process else 0,
            1 if title else 0,
            area,
        )

    def _is_strict_window_candidate(self, window: int) -> bool:
        rect = self._window_rect(window)
        if rect is None:
            return False
        left, top, right, bottom = rect
        width = max(0, right - left)
        height = max(0, bottom - top)
        if width < 320 or height < 180:
            return False

        if win32gui is not None:
            if hasattr(win32gui, "GetParent"):
                try:
                    if win32gui.GetParent(window):
                        return False
                except Exception:
                    pass
            if hasattr(win32gui, "GetWindow"):
                try:
                    if win32gui.GetWindow(window, GW_OWNER):
                        return False
                except Exception:
                    pass
            if hasattr(win32gui, "GetWindowLong"):
                try:
                    ex_style = int(win32gui.GetWindowLong(window, GWL_EXSTYLE))
                except Exception:
                    ex_style = 0
                if ex_style & WS_EX_TOOLWINDOW:
                    return False
        return True

    def find_game_process_id(self, process_name: str) -> int | None:
        window = self.find_game_window(process_name)
        if not window:
            return None
        return self._window_process_id(window)

    def find_game_window(self, process_name: str) -> int | None:
        attached_process_id = self._attached_game_process_id()
        if attached_process_id is not None:
            found_window = self.find_game_window_by_pid(attached_process_id, process_name=process_name)
            if found_window is not None:
                return found_window
        return self.find_game_window_by_name(process_name)

    def find_game_window_by_name(self, process_name: str) -> int | None:
        if win32gui is None or win32process is None:
            return None
        normalized_process_name = self._normalize_process_name(process_name)
        if not normalized_process_name:
            return None

        strict_candidates: list[tuple[tuple[int, int, int], int]] = []
        relaxed_candidates: list[tuple[tuple[int, int, int], int]] = []

        def enum_callback(window, _extra):
            if not self.is_visible_window(window):
                return
            window_process_id = self._window_process_id(window)
            if window_process_id is None or not self._process_id_matches_name(window_process_id, normalized_process_name):
                return
            score = self._window_selection_score(window, process_name=normalized_process_name)
            if score is None:
                return
            relaxed_candidates.append((score, window))
            if self._is_strict_window_candidate(window):
                strict_candidates.append((score, window))

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as exc:
            self.log(f"[WAIT] Could not check the game window yet. Details: {exc}", tag="warning")
        candidates = strict_candidates or relaxed_candidates
        if not candidates:
            return None
        return max(candidates, key=lambda entry: entry[0])[1]

    def find_game_window_by_pid(self, process_id: int, *, process_name: str | None = None) -> int | None:
        if win32gui is None or win32process is None:
            return None
        strict_candidates: list[tuple[tuple[int, int, int], int]] = []
        relaxed_candidates: list[tuple[tuple[int, int, int], int]] = []

        def enum_callback(window, _extra):
            if not self.is_visible_window(window):
                return
            window_process_id = self._window_process_id(window)
            if window_process_id != process_id:
                return
            score = self._window_selection_score(window, process_name=process_name)
            if score is None:
                return
            relaxed_candidates.append((score, window))
            if self._is_strict_window_candidate(window):
                strict_candidates.append((score, window))

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as exc:
            self.log(f"[WAIT] Could not check the game window yet. Details: {exc}", tag="warning")
        candidates = strict_candidates or relaxed_candidates
        if not candidates:
            return None
        return max(candidates, key=lambda entry: entry[0])[1]

    def handle_confirmed_target_window(self, process_name: str) -> bool:
        if keyboard:
            if not self.wait_for_game_window_focus(process_name):
                return False
            keyboard.press_and_release("esc")

        return True
