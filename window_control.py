from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Callable

try:
    import win32gui
    import win32process
except ImportError:
    win32gui = None
    win32process = None


def get_game_process_id(client) -> int | None:
    if client is None:
        return None

    memory = getattr(client, "memory", None)
    pymem_client = getattr(memory, "_pm", None)
    process_id = getattr(pymem_client, "process_id", None)

    try:
        return int(process_id) if process_id else None
    except (TypeError, ValueError):
        return None


def is_game_window_active(
    process_name: str,
    client,
    win32gui_module=win32gui,
    win32process_module=win32process,
) -> bool:
    if win32gui_module is None or win32process_module is None:
        return True

    foreground_window = win32gui_module.GetForegroundWindow()
    if not foreground_window:
        return False

    game_process_id = get_game_process_id(client)
    if game_process_id is not None:
        try:
            _, foreground_process_id = win32process_module.GetWindowThreadProcessId(foreground_window)
            return int(foreground_process_id) == game_process_id
        except Exception:
            return False

    try:
        foreground_title = win32gui_module.GetWindowText(foreground_window) or ""
    except Exception:
        return False

    expected_title = os.path.splitext(process_name)[0]
    return bool(expected_title and expected_title.lower() in foreground_title.lower())


def wait_for_game_window_focus(
    process_name: str,
    *,
    is_hook_run_control_active: Callable[[], bool],
    is_game_window_active: Callable[[str], bool],
    stop_event,
    scan_event,
    log: Callable[[str], None],
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    if is_hook_run_control_active():
        return True

    if is_game_window_active(process_name):
        return True

    log("[WAIT] Game window is not active. Auto-reroll paused...", tag="warning")

    while (
        not stop_event.is_set()
        and scan_event.is_set()
        and not is_game_window_active(process_name)
    ):
        sleep(0.3)

    if stop_event.is_set() or not scan_event.is_set():
        return False

    log("[+] Game window active again. Auto-reroll resumed.", tag="success")
    return True


def bring_game_window_to_front(
    process_name: str,
    client,
    log: Callable[[str], None],
    win32gui_module=win32gui,
    win32process_module=win32process,
    ctypes_module=ctypes,
) -> bool:
    if win32gui_module is None or win32process_module is None:
        log("[WAIT] Cannot bring game window to front: pywin32 is unavailable.", tag="warning")
        return False

    window = find_game_window(
        process_name,
        client,
        log,
        win32gui_module=win32gui_module,
        win32process_module=win32process_module,
    )
    if not window:
        log("[WAIT] Cannot bring game window to front: game window was not found.", tag="warning")
        return False

    try:
        show_game_window(window, win32gui_module=win32gui_module)
        win32gui_module.SetForegroundWindow(window)
        return True
    except Exception as direct_exc:
        try:
            try_attach_foreground_window(
                window,
                win32gui_module=win32gui_module,
                win32process_module=win32process_module,
                ctypes_module=ctypes_module,
            )
            return True
        except Exception as fallback_exc:
            log(
                f"[WAIT] Cannot bring game window to front: {direct_exc}; "
                f"ALT attach fallback failed: {fallback_exc}",
                tag="warning",
            )
            return False


def show_game_window(window: int, *, win32gui_module=win32gui) -> None:
    if hasattr(win32gui_module, "IsIconic") and win32gui_module.IsIconic(window):
        win32gui_module.ShowWindow(window, 9)  # SW_RESTORE
    elif hasattr(win32gui_module, "ShowWindow"):
        win32gui_module.ShowWindow(window, 5)  # SW_SHOW


def try_attach_foreground_window(
    window: int,
    *,
    win32gui_module=win32gui,
    win32process_module=win32process,
    ctypes_module=ctypes,
) -> None:
    user32 = ctypes_module.windll.user32
    kernel32 = ctypes_module.windll.kernel32
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    current_thread = int(kernel32.GetCurrentThreadId())
    target_thread, _ = win32process_module.GetWindowThreadProcessId(window)
    foreground_window = win32gui_module.GetForegroundWindow()
    foreground_thread = None
    if foreground_window:
        foreground_thread, _ = win32process_module.GetWindowThreadProcessId(foreground_window)

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
        send_alt_keypress(user32)
        if hasattr(win32gui_module, "BringWindowToTop"):
            win32gui_module.BringWindowToTop(window)
        win32gui_module.SetForegroundWindow(window)
    finally:
        for thread_id in attached_threads:
            user32.AttachThreadInput(current_thread, thread_id, False)


def send_alt_keypress(user32) -> None:
    vk_menu = 0x12
    keyeventf_keyup = 0x0002
    user32.keybd_event(vk_menu, 0, 0, 0)
    user32.keybd_event(vk_menu, 0, keyeventf_keyup, 0)


def is_visible_window(window: int, *, win32gui_module=win32gui) -> bool:
    try:
        return bool(
            window
            and (
                not hasattr(win32gui_module, "IsWindowVisible")
                or win32gui_module.IsWindowVisible(window)
            )
        )
    except Exception:
        return False


def find_game_window(
    process_name: str,
    client,
    log: Callable[[str], None],
    *,
    win32gui_module=win32gui,
    win32process_module=win32process,
) -> int | None:
    game_process_id = get_game_process_id(client)
    if game_process_id is not None:
        window = find_game_window_by_pid(
            game_process_id,
            log,
            win32gui_module=win32gui_module,
            win32process_module=win32process_module,
        )
        if window:
            return window

    return find_game_window_by_title(
        process_name,
        log,
        win32gui_module=win32gui_module,
    )


def find_game_window_by_pid(
    process_id: int,
    log: Callable[[str], None],
    *,
    win32gui_module=win32gui,
    win32process_module=win32process,
) -> int | None:
    found_window = None

    def enum_callback(window, _extra):
        nonlocal found_window
        if found_window is not None or not is_visible_window(window, win32gui_module=win32gui_module):
            return

        try:
            _, window_process_id = win32process_module.GetWindowThreadProcessId(window)
        except Exception:
            return

        if int(window_process_id) == process_id:
            found_window = window

    try:
        win32gui_module.EnumWindows(enum_callback, None)
    except Exception as exc:
        log(f"[WAIT] Failed to enumerate game windows by PID: {exc}", tag="warning")

    return found_window


def find_game_window_by_title(
    process_name: str,
    log: Callable[[str], None],
    *,
    win32gui_module=win32gui,
) -> int | None:
    expected_title = os.path.splitext(process_name)[0]
    if not expected_title:
        return None

    found_window = None

    def enum_callback(window, _extra):
        nonlocal found_window
        if found_window is not None or not is_visible_window(window, win32gui_module=win32gui_module):
            return

        try:
            window_title = win32gui_module.GetWindowText(window) or ""
        except Exception:
            return

        if expected_title.lower() in window_title.lower():
            found_window = window

    try:
        win32gui_module.EnumWindows(enum_callback, None)
    except Exception as exc:
        log(f"[WAIT] Failed to enumerate game windows by title: {exc}", tag="warning")

    return found_window


def handle_confirmed_target_window(
    process_name: str,
    *,
    is_hook_run_control_active: Callable[[], bool],
    bring_game_window_to_front: Callable[[str], bool],
    wait_for_game_window_focus: Callable[[str], bool],
    keyboard_module,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    if is_hook_run_control_active():
        bring_game_window_to_front(process_name)
        if keyboard_module:
            sleep(0.15)
            keyboard_module.press_and_release("esc")
        return True

    if keyboard_module:
        if not wait_for_game_window_focus(process_name):
            return False
        keyboard_module.press_and_release("esc")

    return True
