"""Owned Windows message pump for the pinned keyboard 0.13.5 backend.

Keep keyboard's event parsing/dispatch, but own the native hook lifetime. Our
tagged sends bypass its process-wide replay flag so real releases are not lost.
"""
from __future__ import annotations

import ctypes
import os
import secrets
import threading
import time
from types import MethodType


class _KeyPacket(ctypes.Structure):
    _fields_ = [("vk_code", ctypes.c_uint32), ("scan_code", ctypes.c_uint32),
                ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                ("extra_info", ctypes.c_size_t)]


class _WindowsApi:
    def __init__(self):
        from ctypes import wintypes

        self.user = ctypes.WinDLL("user32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        signatures = {
            "SetWindowsHookExW": ([ctypes.c_int, self.callback_type,
                                   wintypes.HINSTANCE, wintypes.DWORD], wintypes.HHOOK),
            "UnhookWindowsHookEx": ([wintypes.HHOOK], wintypes.BOOL),
            "CallNextHookEx": ([wintypes.HHOOK, ctypes.c_int,
                                wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t),
            "GetMessageW": ([ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                             wintypes.UINT, wintypes.UINT], wintypes.BOOL),
            "TranslateMessage": ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
            "DispatchMessageW": ([ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
            "keybd_event": ([wintypes.BYTE, wintypes.BYTE, wintypes.DWORD,
                             ctypes.c_size_t], None),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.user, name)
            fn.argtypes, fn.restype = args, result
        kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel.GetModuleHandleW.restype = wintypes.HMODULE
        self.module_handle = kernel.GetModuleHandleW(None)

    def install(self, callback):
        handle = self.user.SetWindowsHookExW(13, callback, self.module_handle, 0)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def uninstall(self, handle):
        self.user.UnhookWindowsHookEx(handle)

    def next_hook(self, code, message, pointer):
        return self.user.CallNextHookEx(None, code, message, pointer)

    @staticmethod
    def packet(pointer):
        return ctypes.cast(pointer, ctypes.POINTER(_KeyPacket)).contents

    @staticmethod
    def message_buffer():
        from ctypes import wintypes

        message = wintypes.MSG()
        return message, ctypes.byref(message)

    def get_message(self, pointer):
        result = self.user.GetMessageW(pointer, None, 0, 0)
        if result == -1:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def dispatch(self, pointer):
        self.user.TranslateMessage(pointer)
        self.user.DispatchMessageW(pointer)

    def send(self, vk, code, flags, marker):
        self.user.keybd_event(vk, code, flags, marker)


class WindowsKeyboardRuntime:
    def __init__(self, keyboard, *, api=None, marker=None):
        self.keyboard = keyboard
        self.backend = keyboard._os_keyboard
        self.api = api if api is not None else _WindowsApi()
        self.marker = secrets.randbits(32) if marker is None else marker
        self.discard_before = 0.0
        self._next_recovery = 0.0
        self._recovery_lock = threading.Lock()
        self.last_error = None

    def install(self):
        self.backend.listen = self.listen
        listener = self.keyboard._listener
        original_preprocess = listener.pre_process_event

        def preprocess(_listener, event):
            # A restarted consumer must not replay old F6 presses from its queue.
            event_time = getattr(event, "time", None)
            if event_time is not None and event_time < self.discard_before:
                return False
            return original_preprocess(event)

        listener.pre_process_event = MethodType(preprocess, listener)

    def _event(self, packet, event_type):
        backend = self.backend
        vk, code = int(packet.vk_code), int(packet.scan_code)
        if vk == 0xA5 and backend.ignore_next_right_alt:
            backend.ignore_next_right_alt = False
            return None
        modifiers = (
            ("shift",) * backend.shift_is_pressed
            + ("alt gr",) * backend.altgr_is_pressed
            + ("num lock",) * (backend.user32.GetKeyState(0x90) & 1)
            + ("caps lock",) * (backend.user32.GetKeyState(0x14) & 1)
            + ("scroll lock",) * (backend.user32.GetKeyState(0x91) & 1)
        )
        entry = (code, vk, bool(packet.flags & 1), modifiers)
        names = backend.to_name.get(entry)
        if names is None:
            names = backend.to_name[entry] = list(backend.get_event_names(*entry))
        if vk in (0x10, 0xA0, 0xA1):
            backend.shift_is_pressed = event_type == "down"
        if code == 541 and vk == 162:
            backend.ignore_next_right_alt = True
            backend.altgr_is_pressed = event_type == "down"
        return self.keyboard.KeyboardEvent(
            event_type, code or -vk, name=names[0] if names else None,
            is_keypad=(code, vk, bool(packet.flags & 1)) in backend.keypad_keys)

    def _dispatch(self, callback, code, message, pointer):
        if code >= 0:
            try:
                packet = self.api.packet(pointer)
                # Ignore only our tagged injection, not real input or other apps.
                ours = packet.flags & 0x10 and packet.extra_info == self.marker
                fake_alt = packet.flags & 0x30 == 0x30
                event_type = self.backend.keyboard_event_types.get(message)
                if not ours and not fake_alt and packet.vk_code != 0xE7 and event_type:
                    event = self._event(packet, event_type)
                    if event is not None and not callback(event):
                        return -1
            except Exception as exc:
                # Never do file I/O inside the time-limited Windows hook callback.
                self.last_error = repr(exc)
        return self.api.next_hook(code, message, pointer)

    def listen(self, callback):
        handle = None
        try:
            native_callback = self.api.callback_type(
                lambda code, message, pointer: self._dispatch(
                    callback, code, message, pointer))
            handle = self.api.install(native_callback)
            self.last_error = None
            message, pointer = self.api.message_buffer()
            while self.api.get_message(pointer) != 0:
                self.api.dispatch(pointer)
        except Exception as exc:
            self.last_error = repr(exc)
        finally:
            if handle is not None:
                self.api.uninstall(handle)

    def recover(self):
        """Restart dead dispatch threads without reinitializing handler tables."""
        now = time.monotonic()
        if now < self._next_recovery:
            return False
        with self._recovery_lock, self.keyboard._listener.lock:
            if now < self._next_recovery:
                return False
            listener = self.keyboard._listener
            if not listener.listening:
                return False
            dead = [(attr, target) for attr, target in (
                ("listening_thread", listener.listen),
                ("processing_thread", listener.process),
            ) if (thread := getattr(listener, attr, None)) is None
                or not thread.is_alive()]
            if not dead:
                return False
            self._next_recovery = now + 1.0
            self.discard_before = time.time()
            for attr, target in dead:
                thread = threading.Thread(target=target,
                                          name="BonkScannerKeyboard-" + attr, daemon=True)
                setattr(listener, attr, thread)
                try:
                    thread.start()
                except RuntimeError as exc:
                    self.last_error = repr(exc)
            return True

    def send(self, operation, hotkey):
        if operation not in ("press", "release", "press_and_release", "send"):
            raise ValueError("Unsupported keyboard operation: " + operation)
        for step in self.keyboard.parse_hotkey(hotkey):
            if operation != "release":
                for codes in step:
                    self._send_code(codes[0], 0)
            if operation != "press":
                for codes in reversed(step):
                    self._send_code(codes[0], 2)

    def _send_code(self, code, flags):
        if code == 541:
            for vk in (0x11, 0x12):
                self.api.send(vk, code, flags, self.marker)
        elif code > 0:
            self.api.send(self.backend.scan_code_to_vk.get(code, 0), code, flags, self.marker)
        else:
            self.api.send(-code, 0, flags, self.marker)


_INSTALL_LOCK = threading.Lock()


def install_windows_keyboard_runtime(keyboard):
    existing = getattr(keyboard, "_bonkscanner_windows_runtime", None)
    if isinstance(existing, WindowsKeyboardRuntime):
        return existing
    backend = getattr(keyboard, "_os_keyboard", None)
    if (os.name != "nt" or getattr(keyboard, "version", None) != "0.13.5"
            or getattr(backend, "__name__", None) != "keyboard._winkeyboard"):
        return None
    with _INSTALL_LOCK:
        existing = getattr(keyboard, "_bonkscanner_windows_runtime", None)
        if isinstance(existing, WindowsKeyboardRuntime):
            return existing
        runtime = WindowsKeyboardRuntime(keyboard)
        runtime.install()
        keyboard._bonkscanner_windows_runtime = runtime
        return runtime
