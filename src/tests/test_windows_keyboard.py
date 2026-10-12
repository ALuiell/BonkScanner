"""Native pump and recovery regressions. No real hooks or keyboard injection."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from infra.windows_keyboard import (
    WindowsKeyboardRuntime, _WindowsApi, install_windows_keyboard_runtime,
)
from infra.hotkeys import ModifierAwareHotkeyManager
from infra.keyboard_runtime import keyboard_operation


class FakeApi:
    callback_type = staticmethod(lambda callback: callback)

    def __init__(self, messages=(1, 0)):
        self.messages = iter(messages)
        self.callback = None
        self.dispatched = []
        self.uninstalled = []
        self.sent = []

    def install(self, callback):
        self.callback = callback
        return 77

    def uninstall(self, handle):
        self.uninstalled.append(handle)

    def message_buffer(self):
        message = wintypes.MSG()
        return message, ctypes.byref(message)

    def get_message(self, pointer):
        assert pointer._obj is not None
        result = next(self.messages)
        if isinstance(result, Exception):
            raise result
        return result

    def dispatch(self, pointer):
        self.dispatched.append(pointer)

    @staticmethod
    def packet(pointer):
        return pointer

    @staticmethod
    def next_hook(*args):
        return 1

    def send(self, vk, code, flags, marker):
        self.sent.append((vk, code, flags, marker))


def make_keyboard(listener=None):
    codes = {"ctrl": 29, "f6": 64, "p": 25, "r": 19}
    backend = SimpleNamespace(
        shift_is_pressed=False, altgr_is_pressed=False, ignore_next_right_alt=False,
        user32=SimpleNamespace(GetKeyState=lambda vk: 0),
        to_name={}, get_event_names=lambda code, vk, ext, mods: [str(code)],
        keypad_keys=set(), keyboard_event_types={0x100: "down", 0x101: "up"},
        scan_code_to_vk={25: 0x50, 29: 0x11, 64: 0x75},
    )
    if listener is None:
        listener = SimpleNamespace(
            listening=True, lock=threading.Lock(),
            pre_process_event=lambda event: True,
            listen=lambda: None, process=lambda: None,
        )
    return SimpleNamespace(
        _os_keyboard=backend, _listener=listener,
        KeyboardEvent=lambda event_type, scan_code, **kwargs: SimpleNamespace(
            event_type=event_type, scan_code=scan_code, time=time.time(), **kwargs),
        key_to_scan_codes=lambda name: (codes[name],),
        parse_hotkey=lambda name: (((codes[name],),),),
    )


def packet(code=64, *, flags=0, extra=0):
    return SimpleNamespace(scan_code=code, vk_code={64: 0x75, 29: 0x11, 25: 0x50}[code],
                           flags=flags, extra_info=extra)


class WindowsMessagePumpTests(unittest.TestCase):
    def test_message_buffer_owns_an_actual_msg_structure(self):
        message, pointer = _WindowsApi.message_buffer()
        self.assertIs(pointer._obj, message)
        self.assertNotEqual(ctypes.cast(pointer, ctypes.c_void_p).value, 0)

    def test_positive_messages_are_dispatched_until_quit_and_handle_is_released(self):
        api = FakeApi((1, 1, 0))
        runtime = WindowsKeyboardRuntime(make_keyboard(), api=api)
        runtime.listen(lambda event: True)
        self.assertEqual(len(api.dispatched), 2)
        self.assertEqual(api.uninstalled, [77])
        self.assertIsNone(runtime.last_error)

    def test_quit_is_not_dispatched(self):
        api = FakeApi((0,))
        WindowsKeyboardRuntime(make_keyboard(), api=api).listen(lambda event: True)
        self.assertEqual(api.dispatched, [])
        self.assertEqual(api.uninstalled, [77])

    def test_message_error_releases_hook_for_recovery(self):
        api = FakeApi((OSError("GetMessage failed"),))
        runtime = WindowsKeyboardRuntime(make_keyboard(), api=api)
        runtime.listen(lambda event: True)
        self.assertIn("GetMessage failed", runtime.last_error)
        self.assertEqual(api.uninstalled, [77])

    def test_failed_install_does_not_unhook_an_invalid_handle(self):
        api = FakeApi()
        api.install = Mock(side_effect=OSError("SetWindowsHookEx failed"))
        runtime = WindowsKeyboardRuntime(make_keyboard(), api=api)
        runtime.listen(lambda event: True)
        self.assertEqual(api.uninstalled, [])
        self.assertIn("SetWindowsHookEx failed", runtime.last_error)


class TaggedInputTests(unittest.TestCase):
    def test_only_our_injected_events_are_ignored(self):
        runtime = WindowsKeyboardRuntime(make_keyboard(), api=FakeApi(), marker=123)
        delivered = []
        callback = lambda event: delivered.append(event) or True
        runtime._dispatch(callback, 0, 0x100, packet(flags=0x10, extra=123))
        runtime._dispatch(callback, 0, 0x100, packet(flags=0x10, extra=456))
        runtime._dispatch(callback, 0, 0x101, packet(flags=0, extra=123))
        self.assertEqual([event.event_type for event in delivered], ["down", "up"])

    def test_negative_hook_code_passes_through_without_reading_packet(self):
        api = FakeApi()
        api.packet = Mock(side_effect=AssertionError("must not read"))
        runtime = WindowsKeyboardRuntime(make_keyboard(), api=api)
        self.assertEqual(runtime._dispatch(lambda event: False, -1, 0x100, None), 1)

    def test_suppressed_event_still_stops_the_hook_chain(self):
        runtime = WindowsKeyboardRuntime(make_keyboard(), api=FakeApi())
        self.assertEqual(runtime._dispatch(lambda event: False, 0, 0x100, packet()), -1)

    def test_real_ctrl_release_during_send_reaches_actual_keyboard_listener(self):
        import keyboard as library

        listener = library._KeyboardListener()
        with patch.object(library._os_keyboard, "init"):
            listener.init()
        keyboard = make_keyboard(listener)
        keyboard.KeyboardEvent = library.KeyboardEvent
        api = FakeApi()
        runtime = WindowsKeyboardRuntime(keyboard, api=api, marker=123)
        keyboard._bonkscanner_windows_runtime = runtime
        runtime.install()
        calls = []
        manager = ModifierAwareHotkeyManager(
            keyboard, allowed_game_keys=(), is_game_window_active=lambda: True)
        manager._bindings = (manager._parse_single_step_binding(
            keyboard.parse_hotkey("f6")[0], lambda: calls.append("f6")),)

        def drain():
            while True:
                try:
                    event = listener.queue.get_nowait()
                except queue.Empty:
                    return
                if listener.pre_process_event(event):
                    manager._on_keyboard_event(event)
                listener.queue.task_done()

        def send(vk, code, flags, marker):
            self.assertFalse(listener.is_replaying)
            runtime._dispatch(listener.direct_callback, 0, 0x101, packet(29))
            runtime._dispatch(listener.direct_callback, 0, 0x100,
                              packet(25, flags=0x10, extra=marker))

        api.send = send
        with patch.object(library, "is_modifier", side_effect=lambda code: code == 29):
            runtime._dispatch(listener.direct_callback, 0, 0x100, packet(29))
            drain()
            keyboard_operation(keyboard, "press", "p")
            drain()
            self.assertNotIn(29, manager._pressed_scan_codes)
            self.assertNotIn(25, manager._pressed_scan_codes)
            runtime._dispatch(listener.direct_callback, 0, 0x100, packet(64))
            drain()
            runtime._dispatch(listener.direct_callback, 0, 0x101, packet(64))
            drain()
        self.assertEqual(calls, ["f6"])

    def test_combination_release_order_and_marker_are_preserved(self):
        keyboard = make_keyboard()
        keyboard.parse_hotkey = lambda key: (((29,), (25,)),)
        api = FakeApi()
        runtime = WindowsKeyboardRuntime(keyboard, api=api, marker=123)
        runtime.send("press_and_release", "ctrl+p")
        self.assertEqual([(code, flags, mark) for vk, code, flags, mark in api.sent],
                         [(29, 0, 123), (25, 0, 123), (25, 2, 123), (29, 2, 123)])


class ListenerRecoveryTests(unittest.TestCase):
    def test_dead_receiver_restarts_once_preserving_live_consumer_and_handlers(self):
        listener = make_keyboard()._listener
        listener.listening_thread = SimpleNamespace(is_alive=lambda: False)
        consumer = listener.processing_thread = SimpleNamespace(is_alive=lambda: True)
        ready, finish = threading.Event(), threading.Event()
        listener.handlers = [Mock()]
        original_handlers = listener.handlers
        listener.listen = lambda: (ready.set(), finish.wait(2))
        runtime = WindowsKeyboardRuntime(make_keyboard(listener), api=FakeApi())
        try:
            self.assertTrue(runtime.recover())
            self.assertTrue(ready.wait(1))
            receiver = listener.listening_thread
            self.assertTrue(receiver.is_alive())
            self.assertIs(listener.processing_thread, consumer)
            self.assertIs(listener.handlers, original_handlers)
            runtime._next_recovery = 0
            self.assertFalse(runtime.recover())
            self.assertIs(listener.listening_thread, receiver)
            original_handlers[0].assert_not_called()
        finally:
            finish.set()
            listener.listening_thread.join(1)

    def test_dead_consumer_discards_old_presses_and_accepts_new_input(self):
        keyboard = make_keyboard()
        runtime = WindowsKeyboardRuntime(keyboard, api=FakeApi())
        runtime.install()
        listener = keyboard._listener
        listener.listening_thread = SimpleNamespace(is_alive=lambda: True)
        listener.processing_thread = SimpleNamespace(is_alive=lambda: False)
        ready, finish = threading.Event(), threading.Event()
        listener.process = lambda: (ready.set(), finish.wait(2))
        try:
            self.assertTrue(runtime.recover())
            self.assertTrue(ready.wait(1))
            self.assertFalse(listener.pre_process_event(SimpleNamespace(
                time=runtime.discard_before - 1)))
            self.assertTrue(listener.pre_process_event(SimpleNamespace(time=time.time())))
        finally:
            finish.set()
            listener.processing_thread.join(1)

    def test_unstarted_listener_is_not_started_by_watchdog(self):
        keyboard = make_keyboard()
        keyboard._listener.listening = False
        self.assertFalse(WindowsKeyboardRuntime(keyboard, api=FakeApi()).recover())

    def test_missing_consumer_after_partial_start_is_recovered(self):
        keyboard = make_keyboard()
        listener = keyboard._listener
        listener.listening_thread = SimpleNamespace(is_alive=lambda: True)
        ready, finish = threading.Event(), threading.Event()
        listener.process = lambda: (ready.set(), finish.wait(2))
        runtime = WindowsKeyboardRuntime(keyboard, api=FakeApi())
        try:
            self.assertTrue(runtime.recover())
            self.assertTrue(ready.wait(1))
            self.assertTrue(listener.processing_thread.is_alive())
        finally:
            finish.set()
            listener.processing_thread.join(1)

    def test_failed_thread_start_keeps_watchdog_available_and_backs_off(self):
        keyboard = make_keyboard()
        listener = keyboard._listener
        listener.listening_thread = SimpleNamespace(is_alive=lambda: False)
        listener.processing_thread = SimpleNamespace(is_alive=lambda: True)
        runtime = WindowsKeyboardRuntime(keyboard, api=FakeApi())
        with patch("infra.windows_keyboard.threading.Thread.start",
                   side_effect=RuntimeError("thread temporarily unavailable")) as start:
            self.assertTrue(runtime.recover())
            self.assertFalse(runtime.recover())
        self.assertEqual(start.call_count, 1)
        self.assertIn("thread temporarily unavailable", runtime.last_error)


class InstallationTests(unittest.TestCase):
    def test_installation_is_idempotent_and_keeps_existing_handler_tables(self):
        keyboard = make_keyboard()
        keyboard.version = "0.13.5"
        keyboard._os_keyboard.__name__ = "keyboard._winkeyboard"
        keyboard._listener.handlers = [Mock()]
        handlers = keyboard._listener.handlers
        with patch("infra.windows_keyboard.os.name", "nt"), patch(
                "infra.windows_keyboard._WindowsApi", return_value=FakeApi()) as api:
            first = install_windows_keyboard_runtime(keyboard)
            second = install_windows_keyboard_runtime(keyboard)
        self.assertIs(first, second)
        self.assertIs(keyboard._listener.handlers, handlers)
        self.assertEqual(api.call_count, 1)

    def test_other_keyboard_backends_are_not_modified(self):
        keyboard = make_keyboard()
        self.assertIsNone(install_windows_keyboard_runtime(keyboard))


if __name__ == "__main__":
    unittest.main()
