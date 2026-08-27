"""Game window, process and hotkey ownership -- the run-control component.

Step 25 took `RunControlMixin` off `MegabonkApp`. What is left here is one
object that owns two things and borrows the rest through named ports: the
`RunControlProvider` that restarts a run, and the hotkey manager that binds the
three global hotkeys.

The one port worth reading twice is `abort_requested`. Cancellation is the
scanner's: `stop_event` and `scan_event` are its fields, and
`wait_for_game_window_focus` was the only place run control touched either. It
spelled the scanner's `_scan_abort_requested()` out by hand
(`stop_event.is_set() or not scan_event.is_set()`) in two of its own lines,
which is what made the two mixins look like one lifecycle split across two
files. They are not: `stop_event` had exactly one writer and `scan_event`'s
second writer was the pause hotkey, which is a scan-lifecycle operation and
went to the scanner with the rest. The focus wait asks a question; it does not
own the answer.
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Any, Callable

from app import config
from app.vod_capture import vod_capture
from infra.hotkeys import HotkeyBinding, ModifierAwareHotkeyManager
from infra.keyboard_run_control import KeyboardRunControlProvider
from infra import process

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


PLAYER_MOVEMENT_KEYS = ("w", "a", "s", "d", "space")


class RunControl:
    """Owns `run_control_provider` and `_hotkey_manager`; borrows the rest."""

    def __init__(
        self,
        *,
        log: Callable[..., None],
        schedule: Callable[[int, Callable[[], None]], None],
        client: Callable[[], Any],
        abort_requested: Callable[[], bool],
        toggle_scan: Callable[[], None],
        player_movement: Callable[[], None],
        toggle_recording: Callable[[], None],
        toggle_overlay_edit: Callable[[], None] | None,
    ) -> None:
        # Seven ports, and the three that are *not* here are the measurement.
        # Run control reached for `update_status_ui`, `is_ready_to_start` and
        # `scanner_thread` in exactly one method -- `toggle_scan_event` -- which
        # is scan lifecycle and went to the scanner. Once it did, run control
        # needed nothing else of the scanner's: it asks whether the scan was
        # cancelled and it asks for the client's PID. That is the whole of the
        # "mutual" coupling the two files appeared to have.
        self._log = log
        self._schedule = schedule
        self._client = client
        self._abort_requested = abort_requested
        self._toggle_scan = toggle_scan
        self._player_movement = player_movement
        self._toggle_recording = toggle_recording
        # Explicitly optional, and the reason is a live failure mode rather
        # than taste. The binding used to be added under
        # `hasattr(self, "hotkey_toggle_in_game_overlay_edit")`, which step 24
        # made permanently true by leaving a delegator on `MegabonkApp`. A
        # component with no such attribute would have made that `hasattr` go
        # quietly false: the app still starts, the suite still passes, and F9
        # simply stops working. It is the only one of the three bindings that
        # is conditional at all, so it is `None` or a callable here and the
        # trace counts the bindings.
        self._toggle_overlay_edit = toggle_overlay_edit

        self.run_control_provider = None
        self._hotkey_manager = None
        self.player_movement_guard_available = not bool(
            getattr(config, "STOP_SCANNING_ON_PLAYER_MOVEMENT", True)
        )

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
        )

    def check_admin_rights(self):
        if os.name != "nt":
            return
        if not process.is_running_as_admin():
            self._log("\u26a0\ufe0f WARNING: Script is not running as Administrator!", tag="warning")
            self._log("\u26a0\ufe0f Hotkeys may not work while the game window is active.", tag="warning")


    def setup_hotkeys(self):
        guard_enabled = bool(
            getattr(config, "STOP_SCANNING_ON_PLAYER_MOVEMENT", True)
        )
        if not keyboard:
            self.player_movement_guard_available = not guard_enabled
            return
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
            if self._toggle_overlay_edit is not None:
                bindings.append(HotkeyBinding(
                    getattr(config, "IN_GAME_OVERLAY_EDIT_HOTKEY", "f9"),
                    self.hotkey_toggle_in_game_overlay_edit
                ))
            if guard_enabled:
                bindings.extend(
                    HotkeyBinding(
                        key,
                        self.hotkey_player_movement,
                        require_game_window=True,
                    )
                    for key in PLAYER_MOVEMENT_KEYS
                )
            manager.start(tuple(bindings))
            self._hotkey_manager = manager
            self.player_movement_guard_available = True
        except Exception as exc:
            self.player_movement_guard_available = not guard_enabled
            self._log(f"[WAIT] Could not register hotkeys: {exc}", tag="warning")

    # The other half of `setup_hotkeys`. It stood inline at the end of
    # `ScannerMixin.on_closing`, which made `_hotkey_manager` a name written by
    # two mixins -- one of the two `PRE_EXISTING_COLLISIONS` entries, and one
    # the scanner had no reason to own beyond running the shutdown sequence.
    #
    # Paying it here rather than letting step 25b's move retire the register
    # entry is the whole point of the register: moving `on_closing` onto
    # `MegabonkApp` takes the second writer out of the *scan*, so the staleness
    # test would have deleted the entry while two writers were still writing the
    # same attribute on the same object. That is a debt recorded as paid because
    # a class left a list, which is what caught step 22b.
    def stop_hotkeys(self):
        manager = getattr(self, "_hotkey_manager", None)
        if manager is None:
            return
        try:
            manager.stop()
        except Exception:
            pass
        self._hotkey_manager = None

    def hotkey_toggle_scanning(self):
        self._schedule(0, self._toggle_scan)

    def hotkey_player_movement(self):
        # This callback runs on the keyboard hook thread. The scanner's handler
        # only mutates thread-safe events under its restart lock; GUI work is
        # scheduled separately by that handler.
        self._player_movement()

    def is_player_movement_pressed(self) -> bool:
        manager = self._hotkey_manager
        if manager is None:
            return False
        try:
            return bool(manager.any_key_pressed(PLAYER_MOVEMENT_KEYS))
        except Exception:
            return False

    def hotkey_toggle_player_stats_recording(self):
        self._schedule(0, self._toggle_recording)

    def hotkey_toggle_in_game_overlay_edit(self):
        if self._toggle_overlay_edit is not None:
            # The keyboard package invokes bindings on its hook thread. The
            # overlay edit handler creates/shows Qt widgets, so it must cross
            # the same GUI-thread scheduler as the scan and recording hotkeys.
            self._schedule(0, self._toggle_overlay_edit)

    # `toggle_scan_event` was here. It is `Scanner.toggle_scan_event` now: it
    # writes `is_running` and `scan_event` and reads `scanner_thread` and
    # `is_ready_to_start`, i.e. four pieces of scan lifecycle and nothing that
    # belongs to run control. It is also the second of `scan_event`'s two
    # writers, so moving it is what leaves the scanner as the only one.
    # `is_running` was the last `PRE_EXISTING_COLLISIONS` entry and this is how
    # it was paid.

    def get_game_process_id(self) -> int | None:
        process_id = self.attached_game_process_id()
        if (
            process_id is not None
            and self._process_id_matches_name(process_id, config.PROCESS_NAME)
        ):
            return process_id
        return self.find_game_process_id(config.PROCESS_NAME)

    def attached_game_process_id(self) -> int | None:
        client = self._client()
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

    def foreground_game_process_id(self, process_name: str) -> int | None:
        if win32gui is None or win32process is None:
            return None
        foreground_window = win32gui.GetForegroundWindow()
        if not foreground_window:
            return None
        try:
            _, foreground_process_id = win32process.GetWindowThreadProcessId(foreground_window)
        except Exception:
            return None
        try:
            foreground_process_id = int(foreground_process_id)
        except (TypeError, ValueError):
            return None
        if foreground_process_id <= 0:
            return None

        attached_process_id = self.attached_game_process_id()
        if attached_process_id is not None:
            if (
                foreground_process_id == attached_process_id
                and self.find_game_window_by_pid(attached_process_id, process_name=process_name) is not None
            ):
                return foreground_process_id

        if not self._process_id_matches_name(foreground_process_id, process_name):
            return None
        if self.find_game_window_by_pid(foreground_process_id, process_name=process_name) is None:
            return None
        return foreground_process_id

    def is_game_window_active(self, process_name: str) -> bool:
        if win32gui is None or win32process is None:
            return True
        return self.foreground_game_process_id(process_name) is not None

    def wait_for_game_window_focus(self, process_name: str) -> bool:
        if self.is_game_window_active(process_name):
            return True
        self._log("[WAIT] Game window is not active. Auto-reroll paused...", tag="warning")
        while not self._abort_requested() and not self.is_game_window_active(process_name):
            time.sleep(0.3)
        if self._abort_requested():
            return False
        self._log("[+] Game window active again. Auto-reroll resumed.", tag="success")
        return True

    def bring_game_window_to_front(self, process_name: str) -> bool:
        if win32gui is None or win32process is None:
            self._log("[WAIT] Cannot bring game window to front: pywin32 is unavailable.", tag="warning")
            return False
        window = self.find_game_window(process_name)
        if not window:
            self._log("[WAIT] Cannot bring game window to front: game window was not found.", tag="warning")
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
                self._log(
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
        normalized_process_name = process.normalize_process_name(process_name)
        if not normalized_process_name:
            return False
        image_name = self._process_image_name(process_id)
        return bool(image_name and image_name == normalized_process_name)




    def find_game_process_id(self, process_name: str) -> int | None:
        window = self.find_game_window(process_name)
        if not window:
            return None
        return process.window_process_id(window)

    def find_game_window(self, process_name: str) -> int | None:
        attached_process_id = self.attached_game_process_id()
        if attached_process_id is not None:
            found_window = self.find_game_window_by_pid(attached_process_id, process_name=process_name)
            if found_window is not None:
                return found_window
        return self.find_game_window_by_name(process_name)

    def find_game_window_by_name(self, process_name: str) -> int | None:
        if win32gui is None or win32process is None:
            return None
        normalized_process_name = process.normalize_process_name(process_name)
        if not normalized_process_name:
            return None

        strict_candidates: list[tuple[tuple[int, int, int], int]] = []
        relaxed_candidates: list[tuple[tuple[int, int, int], int]] = []

        def enum_callback(window, _extra):
            if not process.is_visible_window(window):
                return
            window_process_id = process.window_process_id(window)
            if window_process_id is None or not self._process_id_matches_name(window_process_id, normalized_process_name):
                return
            score = process.window_selection_score(window, process_name=normalized_process_name)
            if score is None:
                return
            relaxed_candidates.append((score, window))
            if process.is_strict_window_candidate(window):
                strict_candidates.append((score, window))

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as exc:
            self._log(f"[WAIT] Could not check the game window yet. Details: {exc}", tag="warning")
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
            if not process.is_visible_window(window):
                return
            window_process_id = process.window_process_id(window)
            if window_process_id != process_id:
                return
            score = process.window_selection_score(window, process_name=process_name)
            if score is None:
                return
            relaxed_candidates.append((score, window))
            if process.is_strict_window_candidate(window):
                strict_candidates.append((score, window))

        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception as exc:
            self._log(f"[WAIT] Could not check the game window yet. Details: {exc}", tag="warning")
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


def build_run_control(app: Any) -> RunControl:
    """Wire run control to its measured owners without giving it the app.

    Every port is a late-bound lambda, so this can be called before the scanner
    exists -- which it is, because the scanner takes the object this returns.
    The two components are mutually referential by nature (one asks whether the
    scan was cancelled, the other asks where the game window is); a lambda is
    what keeps that from becoming a construction order puzzle, and it is the
    same rule steps 20-24's composition roots follow.
    """
    return RunControl(
        log=lambda message, tag=None: app.log(message, tag=tag),
        schedule=lambda delay_ms, callback: app.after(delay_ms, callback),
        client=lambda: app.client,
        abort_requested=lambda: app._scanner._scan_abort_requested(),
        toggle_scan=lambda: app._scanner.toggle_scan_event(),
        player_movement=lambda: app._scanner.handle_player_movement(),
        toggle_recording=lambda: vod_capture(app).toggle_recording(),
        # Present, so F9 is registered. `hotkey_toggle_in_game_overlay_edit` is
        # `MegabonkApp`'s step-24 delegator into the in-game overlay component;
        # naming it here is what makes the binding's condition a wiring
        # decision at the composition root instead of a `hasattr` that nothing
        # would report on if it went false.
        toggle_overlay_edit=lambda: app.hotkey_toggle_in_game_overlay_edit(),
    )
