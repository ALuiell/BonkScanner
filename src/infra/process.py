"""Pure OS and window-system primitives.

Extracted from ``RunControlMixin``. Every function here is genuinely free of
application state -- it calls Windows APIs and returns a value. The mixin keeps
the orchestration that decides *which* window or process matters, because that
needs the attached memory client and the UI log.

The roadmap listed ``check_admin_rights``, ``get_game_process_id`` and
``_foreground_game_process_id`` for this module. They do not belong: the first
writes to the UI log, and the other two read ``self.client`` to find the
attached game process. Only ``is_running_as_admin`` of the named four was pure.
The ~90-line estimate was right; the function list was not.
"""
from __future__ import annotations

import ctypes
import os

try:
    import win32gui
    import win32process
except ImportError:
    win32gui = None
    win32process = None


GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
GW_OWNER = 4


def is_running_as_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def is_visible_window(window: int) -> bool:
    try:
        return bool(window and (not hasattr(win32gui, "IsWindowVisible") or win32gui.IsWindowVisible(window)))
    except Exception:
        return False

def normalize_process_name(process_name: str) -> str:
    return os.path.basename(str(process_name or "")).strip().lower()

def window_process_id(window: int) -> int | None:
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

def window_rect(window: int) -> tuple[int, int, int, int] | None:
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

def window_selection_score(window: int, *, process_name: str | None = None) -> tuple[int, int, int] | None:
    rect = window_rect(window)
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

    process_stem = os.path.splitext(normalize_process_name(process_name or ""))[0]
    title_lower = title.lower()
    title_matches_process = bool(process_stem and process_stem in title_lower)
    area = width * height
    return (
        1 if title_matches_process else 0,
        1 if title else 0,
        area,
    )

def is_strict_window_candidate(window: int) -> bool:
    rect = window_rect(window)
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
