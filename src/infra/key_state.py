"""Conservative Windows key-state reads; no input injection or token polling."""
from __future__ import annotations

from typing import Callable, Iterable


class WindowsKeyState:
    def __init__(self, keyboard_module, foreground_accessible: Callable[[int], bool]) -> None:
        import ctypes
        from ctypes import wintypes

        self.keyboard = keyboard_module
        self._foreground_accessible = foreground_accessible
        self._ctypes = ctypes
        self._wintypes = wintypes
        self._user = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "GetAsyncKeyState": ([ctypes.c_int], ctypes.c_short),
            "OpenInputDesktop": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "CloseDesktop": ([wintypes.HANDLE], wintypes.BOOL),
            "GetThreadDesktop": ([wintypes.DWORD], wintypes.HANDLE),
            "GetUserObjectInformationW": ([wintypes.HANDLE, ctypes.c_int,
                                            ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "GetForegroundWindow": ([], wintypes.HWND),
            "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._user, name)
            function.argtypes, function.restype = arguments, result
        self._kernel.GetCurrentThreadId.argtypes = []
        self._kernel.GetCurrentThreadId.restype = wintypes.DWORD

    def _desktop_name(self, handle) -> str | None:
        buffer = self._ctypes.create_unicode_buffer(256)
        needed = self._wintypes.DWORD()
        if not handle or not self._user.GetUserObjectInformationW(
            handle, 2, buffer, self._ctypes.sizeof(buffer), self._ctypes.byref(needed)
        ):
            return None
        return buffer.value

    def _readable_foreground(self) -> int | None:
        # Zero from GetAsyncKeyState can also mean inaccessible input. Require
        # the active desktop and HOOKCONTROL, plus previously established UIPI
        # access. The permission result is reused, not queried on each poll.
        desktop = self._user.OpenInputDesktop(0, False, 0x0001 | 0x0008)
        if not desktop:
            return None
        try:
            name = self._desktop_name(desktop)
            current = self._desktop_name(self._user.GetThreadDesktop(
                self._kernel.GetCurrentThreadId()))
            if not name or name != current:
                return None
        finally:
            self._user.CloseDesktop(desktop)
        window = self._user.GetForegroundWindow()
        pid = self._wintypes.DWORD()
        if (not window or not self._user.GetWindowThreadProcessId(window, self._ctypes.byref(pid))
                or not self._foreground_accessible(pid.value)):
            return None
        return int(window)

    def _virtual_keys(self, code: int) -> tuple[int, ...]:
        # keyboard merges some extended/nonextended scan codes. Neither
        # physical key may still be held before clearing their shared entry.
        special = {
            29: (0x11,), 56: (0x12,), 42: (0xA0,), 54: (0xA1,),
            55: (0x6A, 0x2C), 69: (0x90, 0x13),
            71: (0x24, 0x67), 72: (0x26, 0x68), 73: (0x21, 0x69),
            75: (0x25, 0x64), 77: (0x27, 0x66), 79: (0x23, 0x61),
            80: (0x28, 0x62), 81: (0x22, 0x63), 82: (0x2D, 0x60),
            83: (0x2E, 0x6E), 541: (0x11, 0x12),
        }
        if code in special:
            return special[code]
        if code < 0:
            return (-code,)
        backend = getattr(self.keyboard, "_os_keyboard", None)
        vk = getattr(backend, "scan_code_to_vk", {}).get(code)
        return (int(vk),) if vk else ()

    def __call__(self, scan_codes: Iterable[int]) -> dict[int, bool | None]:
        codes = tuple(scan_codes)
        try:
            before = self._readable_foreground()
            result = {}
            for code in codes:
                keys = self._virtual_keys(code)
                down = any(self._user.GetAsyncKeyState(vk) & 0x8000 for vk in keys)
                result[code] = True if down else (False if before and keys else None)
            if before is None or before != self._readable_foreground():
                return {code: True if down is True else None for code, down in result.items()}
            return result
        except Exception:
            return {code: None for code in codes}
