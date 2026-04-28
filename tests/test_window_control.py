from __future__ import annotations

import types
import unittest

import window_control


class FakeCtypesFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class FakeUser32:
    def __init__(self) -> None:
        self.attach_calls: list[tuple[int, int, bool]] = []
        self.keybd_event_calls: list[tuple[int, int, int, int]] = []
        self.AttachThreadInput = FakeCtypesFunction(self._attach_thread_input)
        self.keybd_event = FakeCtypesFunction(self._keybd_event)

    def _attach_thread_input(self, current_thread: int, target_thread: int, attach: bool) -> bool:
        self.attach_calls.append((current_thread, target_thread, attach))
        return True

    def _keybd_event(self, key: int, scan: int, flags: int, extra: int) -> None:
        self.keybd_event_calls.append((key, scan, flags, extra))


class FakeKernel32:
    def __init__(self, current_thread: int = 10) -> None:
        self.GetCurrentThreadId = FakeCtypesFunction(lambda: current_thread)


class FakeWindll:
    def __init__(self, user32: FakeUser32, kernel32: FakeKernel32) -> None:
        self.user32 = user32
        self.kernel32 = kernel32


class FakeForegroundGui:
    def __init__(self, *, fail_always: bool = False, title: str = "Megabonk") -> None:
        self.fail_always = fail_always
        self.foreground_window = 222
        self.title = title
        self.set_foreground_calls: list[int] = []
        self.show_window_calls: list[tuple[int, int]] = []
        self.bring_window_to_top_calls: list[int] = []

    def IsIconic(self, _window: int) -> bool:
        return False

    def ShowWindow(self, window: int, command: int) -> None:
        self.show_window_calls.append((window, command))

    def SetForegroundWindow(self, window: int) -> None:
        self.set_foreground_calls.append(window)
        if self.fail_always or len(self.set_foreground_calls) == 1:
            raise RuntimeError("foreground denied")
        self.foreground_window = window

    def GetForegroundWindow(self) -> int:
        return self.foreground_window

    def BringWindowToTop(self, window: int) -> None:
        self.bring_window_to_top_calls.append(window)

    def GetWindowText(self, _window: int) -> str:
        return self.title

    def IsWindowVisible(self, _window: int) -> bool:
        return True

    def EnumWindows(self, callback, extra) -> None:
        for window in (111, 222):
            callback(window, extra)


class FakeForegroundProcess:
    def __init__(self, process_ids: dict[int, int] | None = None) -> None:
        self.process_ids = process_ids or {
            111: 9111,
            222: 9222,
        }

    def GetWindowThreadProcessId(self, window: int) -> tuple[int, int]:
        thread_by_window = {
            111: 20,
            222: 30,
        }
        return thread_by_window.get(window, 40), self.process_ids.get(window, 9000 + window)


class WindowControlTests(unittest.TestCase):
    def test_get_game_process_id_returns_none_without_client(self) -> None:
        self.assertIsNone(window_control.get_game_process_id(None))

    def test_get_game_process_id_converts_valid_process_id_to_int(self) -> None:
        client = types.SimpleNamespace(memory=types.SimpleNamespace(_pm=types.SimpleNamespace(process_id="1234")))

        self.assertEqual(window_control.get_game_process_id(client), 1234)

    def test_is_game_window_active_returns_true_when_pywin32_is_unavailable(self) -> None:
        self.assertTrue(
            window_control.is_game_window_active(
                "Megabonk.exe",
                None,
                win32gui_module=None,
                win32process_module=None,
            )
        )

    def test_is_game_window_active_matches_foreground_process_id(self) -> None:
        fake_gui = FakeForegroundGui()
        fake_process = FakeForegroundProcess({222: 1234})
        client = types.SimpleNamespace(memory=types.SimpleNamespace(_pm=types.SimpleNamespace(process_id=1234)))

        self.assertTrue(
            window_control.is_game_window_active(
                "Megabonk.exe",
                client,
                win32gui_module=fake_gui,
                win32process_module=fake_process,
            )
        )

    def test_is_game_window_active_falls_back_to_title_matching_without_client_pid(self) -> None:
        fake_gui = FakeForegroundGui(title="Megabonk - Main Menu")
        fake_process = FakeForegroundProcess()

        self.assertTrue(
            window_control.is_game_window_active(
                "Megabonk.exe",
                None,
                win32gui_module=fake_gui,
                win32process_module=fake_process,
            )
        )

    def test_wait_for_game_window_focus_bypasses_focus_checks_in_hook_mode(self) -> None:
        def fail_if_called(_process_name: str) -> bool:
            self.fail("hook mode should not check focus")

        self.assertTrue(
            window_control.wait_for_game_window_focus(
                "Megabonk.exe",
                is_hook_run_control_active=lambda: True,
                is_game_window_active=fail_if_called,
                stop_event=types.SimpleNamespace(is_set=lambda: False),
                scan_event=types.SimpleNamespace(is_set=lambda: True),
                log=lambda _message, tag=None: None,
            )
        )

    def test_wait_for_game_window_focus_waits_until_window_becomes_active(self) -> None:
        logs: list[tuple[str, str | None]] = []
        sleeps: list[float] = []
        active_results = [False, False, True]

        self.assertTrue(
            window_control.wait_for_game_window_focus(
                "Megabonk.exe",
                is_hook_run_control_active=lambda: False,
                is_game_window_active=lambda _process_name: active_results.pop(0),
                stop_event=types.SimpleNamespace(is_set=lambda: False),
                scan_event=types.SimpleNamespace(is_set=lambda: True),
                log=lambda message, tag=None: logs.append((message, tag)),
                sleep=sleeps.append,
            )
        )

        self.assertEqual(sleeps, [0.3])
        self.assertIn(("[WAIT] Game window is not active. Auto-reroll paused...", "warning"), logs)
        self.assertIn(("[+] Game window active again. Auto-reroll resumed.", "success"), logs)

    def test_bring_game_window_to_front_uses_alt_attach_fallback_after_direct_failure(self) -> None:
        fake_gui = FakeForegroundGui()
        fake_process = FakeForegroundProcess()
        fake_user32 = FakeUser32()
        fake_windll = FakeWindll(fake_user32, FakeKernel32())
        fake_ctypes = types.SimpleNamespace(windll=fake_windll)
        logs: list[tuple[str, str | None]] = []
        client = types.SimpleNamespace(memory=types.SimpleNamespace(_pm=types.SimpleNamespace(process_id=9111)))

        self.assertTrue(
            window_control.bring_game_window_to_front(
                "Megabonk.exe",
                client,
                lambda message, tag=None: logs.append((message, tag)),
                win32gui_module=fake_gui,
                win32process_module=fake_process,
                ctypes_module=fake_ctypes,
            )
        )

        self.assertEqual(fake_gui.show_window_calls, [(111, 5)])
        self.assertEqual(fake_gui.set_foreground_calls, [111, 111])
        self.assertEqual(fake_gui.bring_window_to_top_calls, [111])
        self.assertEqual(
            fake_user32.attach_calls,
            [
                (10, 20, True),
                (10, 30, True),
                (10, 20, False),
                (10, 30, False),
            ],
        )
        self.assertEqual(fake_user32.keybd_event_calls, [(0x12, 0, 0, 0), (0x12, 0, 0x0002, 0)])
        self.assertEqual(logs, [])

    def test_bring_game_window_to_front_logs_warning_when_no_window_found(self) -> None:
        fake_gui = types.SimpleNamespace(
            GetForegroundWindow=lambda: 0,
            EnumWindows=lambda _callback, _extra: None,
        )
        fake_process = FakeForegroundProcess()
        logs: list[tuple[str, str | None]] = []

        self.assertFalse(
            window_control.bring_game_window_to_front(
                "Megabonk.exe",
                None,
                lambda message, tag=None: logs.append((message, tag)),
                win32gui_module=fake_gui,
                win32process_module=fake_process,
                ctypes_module=types.SimpleNamespace(),
            )
        )

        self.assertEqual(
            logs,
            [("[WAIT] Cannot bring game window to front: game window was not found.", "warning")],
        )

    def test_try_attach_foreground_window_detaches_threads_when_foreground_fails(self) -> None:
        fake_gui = FakeForegroundGui(fail_always=True)
        fake_process = FakeForegroundProcess()
        fake_user32 = FakeUser32()
        fake_windll = FakeWindll(fake_user32, FakeKernel32())
        fake_ctypes = types.SimpleNamespace(windll=fake_windll)

        with self.assertRaisesRegex(RuntimeError, "foreground denied"):
            window_control.try_attach_foreground_window(
                111,
                win32gui_module=fake_gui,
                win32process_module=fake_process,
                ctypes_module=fake_ctypes,
            )

        self.assertEqual(
            fake_user32.attach_calls,
            [
                (10, 20, True),
                (10, 30, True),
                (10, 20, False),
                (10, 30, False),
            ],
        )

    def test_handle_confirmed_target_window_in_hook_mode_brings_game_forward_then_presses_esc(self) -> None:
        pressed_keys: list[str] = []
        sleeps: list[float] = []
        keyboard_module = types.SimpleNamespace(press_and_release=pressed_keys.append)
        bring_calls: list[str] = []

        self.assertTrue(
            window_control.handle_confirmed_target_window(
                "Megabonk.exe",
                is_hook_run_control_active=lambda: True,
                bring_game_window_to_front=bring_calls.append,
                wait_for_game_window_focus=lambda _process_name: self.fail("hook mode should not wait for focus"),
                keyboard_module=keyboard_module,
                sleep=sleeps.append,
            )
        )

        self.assertEqual(bring_calls, ["Megabonk.exe"])
        self.assertEqual(sleeps, [0.15])
        self.assertEqual(pressed_keys, ["esc"])

    def test_handle_confirmed_target_window_in_keyboard_mode_waits_then_presses_esc(self) -> None:
        focus_checks: list[str] = []
        pressed_keys: list[str] = []
        keyboard_module = types.SimpleNamespace(press_and_release=pressed_keys.append)

        self.assertTrue(
            window_control.handle_confirmed_target_window(
                "Megabonk.exe",
                is_hook_run_control_active=lambda: False,
                bring_game_window_to_front=lambda _process_name: self.fail(
                    "keyboard mode should not bring window forward"
                ),
                wait_for_game_window_focus=lambda process_name: focus_checks.append(process_name) or True,
                keyboard_module=keyboard_module,
            )
        )

        self.assertEqual(focus_checks, ["Megabonk.exe"])
        self.assertEqual(pressed_keys, ["esc"])


if __name__ == "__main__":
    unittest.main()
