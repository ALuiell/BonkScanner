from __future__ import annotations

import types
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gui
from run_control import HookRunControlProvider, KeyboardRunControlProvider


class FakeEntry:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class FakeVar:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = value


class FakeCheckbox:
    def __init__(self, value: bool) -> None:
        self.value = value

    def isChecked(self) -> bool:
        return self.value


class FakeSettingsMaster:
    def __init__(self) -> None:
        self.events: list[str] = []

    def setup_hotkeys(self) -> None:
        self.events.append("setup_hotkeys")

    def update_status_ui(self) -> None:
        self.events.append("update_status_ui")

    def apply_run_control_mode(self) -> None:
        self.events.append("apply_run_control_mode")

    def log(self, _message: str, tag: str | None = None) -> None:
        del tag
        self.events.append("log")


class FakeDetachLoader:
    def __init__(self, pid: int = 1234, error: Exception | None = None) -> None:
        self.pid = pid
        self.error = error
        self.uninitialize_calls = 0

    def uninitialize(self) -> types.SimpleNamespace:
        self.uninitialize_calls += 1
        if self.error is not None:
            raise self.error
        return types.SimpleNamespace(pid=self.pid)


class FakeThread:
    def __init__(self, *, target: object, args: tuple[object, ...] = (), daemon: bool) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return self.started


class FakeAliveThread:
    def is_alive(self) -> bool:
        return True


class FakeLabel:
    def __init__(self, text: str = "") -> None:
        self.value = text

    def setText(self, text: str) -> None:
        self.value = text

    def text(self) -> str:
        return self.value


class FakeTabWidget:
    def __init__(self, active_tab: str) -> None:
        self.active_tab = active_tab

    def currentIndex(self) -> int:
        return 0

    def tabText(self, _index: int) -> str:
        return self.active_tab


class FakeHookLoopLoader:
    def __init__(
        self,
        *,
        pid: int = 1234,
        skipped: bool = False,
        inject_error: Exception | list[Exception | None] | None = None,
    ) -> None:
        self.pid = pid
        self.skipped = skipped
        self.inject_error = inject_error
        self.inject_calls = 0

    def inject_once(self) -> types.SimpleNamespace:
        self.inject_calls += 1
        inject_error = self.inject_error
        if isinstance(inject_error, list):
            inject_error = inject_error.pop(0) if inject_error else None
        if inject_error is not None:
            raise inject_error
        return types.SimpleNamespace(pid=self.pid, skipped=self.skipped)


class FakeKeyboardModule:
    def __init__(self) -> None:
        self.press_and_release_calls: list[str] = []
        self.add_hotkey_calls: list[tuple[str, object]] = []
        self.unhook_all_calls = 0

    def press_and_release(self, key: str) -> None:
        self.press_and_release_calls.append(key)

    def add_hotkey(self, hotkey: str, callback: object) -> None:
        self.add_hotkey_calls.append((hotkey, callback))

    def unhook_all(self) -> None:
        self.unhook_all_calls += 1


class FakeRecordingRecorder:
    def __init__(self, *, is_recording: bool = True, should_capture: bool = False) -> None:
        self.is_recording = is_recording
        self.should_capture_value = should_capture
        self.start_calls: list[dict[str, object]] = []
        self.stop_calls = 0
        self.capture_calls: list[dict[str, object]] = []

    def start(self, *, name: str | None = None, seed: int | None = None) -> Path:
        self.is_recording = True
        self.start_calls.append({"name": name, "seed": seed})
        return Path(f"recording-{len(self.start_calls)}.jsonl")

    def stop(self) -> None:
        self.is_recording = False
        self.stop_calls += 1

    def should_capture(self) -> bool:
        return self.should_capture_value

    def capture(self, stats, items=(), weapons=(), *, chests_per_minute=None, game_time_seconds=None):
        snapshot = SimpleNamespace(
            stats=stats,
            items=tuple(items),
            weapons=tuple(weapons),
            chests_per_minute=chests_per_minute,
            game_time_seconds=game_time_seconds,
            time_label="00:00",
        )
        self.capture_calls.append(
            {
                "stats": stats,
                "items": tuple(items),
                "weapons": tuple(weapons),
                "chests_per_minute": chests_per_minute,
                "game_time_seconds": game_time_seconds,
            }
        )
        self.should_capture_value = False
        return snapshot


class FakeSeedStateClient:
    def __init__(self, seeds: list[int | None]) -> None:
        self.seeds = list(seeds)
        self.close_calls = 0

    def get_map_generation_state(self) -> SimpleNamespace:
        seed = self.seeds.pop(0) if self.seeds else None
        return SimpleNamespace(map_seed=seed)

    def close(self) -> None:
        self.close_calls += 1


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
    def __init__(self, *, fail_always: bool = False) -> None:
        self.fail_always = fail_always
        self.foreground_window = 222
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


class FakeForegroundProcess:
    def GetWindowThreadProcessId(self, window: int) -> tuple[int, int]:
        thread_by_window = {
            111: 20,
            222: 30,
        }
        return thread_by_window.get(window, 40), 9000 + window


class GuiRunControlTests(unittest.TestCase):
    def build_recording_app(self) -> gui.MegabonkApp:
        app = object.__new__(gui.MegabonkApp)
        app.player_stats_vod_recorder = FakeRecordingRecorder()
        app.player_stats_vod_snapshots = ["snapshot"]
        app.player_stats_selected_snapshot_index = 0
        app.player_stats_recording_seed = None
        app.player_stats_recording_seed_missing_since = None
        app.player_stats_game_data_client = None
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: 21.5)
        app.player_stats_status_label = FakeLabel()
        app.player_stats_rows = {}
        app.player_stats_items_label = FakeLabel()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app.refresh_player_stats_timeline_ui = lambda *args, **kwargs: None
        app._refresh_vods_list_if_visible = lambda: None
        app.display_player_stats = lambda *args, **kwargs: None
        app.display_player_stats_snapshot = lambda *args, **kwargs: None
        app.close_player_stats_client = lambda: None
        app.read_player_stats_only = lambda: ({}, 0x1234)
        app.read_passive_items_only = lambda owner_stats=None: ()
        app._is_live_stats_tab_active = lambda: True
        app.log_messages = []
        app.log = lambda message, tag=None: app.log_messages.append((message, tag))
        return app

    def setUp(self) -> None:
        self.original_config_values = {
            "HOTKEY": gui.config.HOTKEY,
            "RESET_HOTKEY": gui.config.RESET_HOTKEY,
            "PLAYER_STATS_RECORD_HOTKEY": gui.config.PLAYER_STATS_RECORD_HOTKEY,
            "MAP_LOAD_DELAY": gui.config.MAP_LOAD_DELAY,
            "RESET_HOLD_DURATION": gui.config.RESET_HOLD_DURATION,
            "TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY": gui.config.TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY,
            "TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY": gui.config.TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY,
            "TOGGLE_PARTICLES_OPACITY_HOTKEY": gui.config.TOGGLE_PARTICLES_OPACITY_HOTKEY,
            "NATIVE_HOOK_ENABLED": gui.config.NATIVE_HOOK_ENABLED,
            "TOTAL_REROLLS": gui.config.TOTAL_REROLLS,
            "ACTIVE_TEMPLATES": deepcopy(gui.config.ACTIVE_TEMPLATES),
            "EVALUATION_MODE": gui.config.EVALUATION_MODE,
            "SCORES_SYSTEM": deepcopy(gui.config.SCORES_SYSTEM),
            "TEMPLATES": deepcopy(gui.config.TEMPLATES),
        }
        self.original_user_config = deepcopy(gui.config.user_config)

    def tearDown(self) -> None:
        for name, value in self.original_config_values.items():
            setattr(gui.config, name, value)
        gui.config.user_config.clear()
        gui.config.user_config.update(self.original_user_config)

    def test_settings_save_updates_native_hook_enabled_and_applies_run_control_mode(self) -> None:
        master = FakeSettingsMaster()
        destroyed: list[bool] = []
        dialog = types.SimpleNamespace(
            hotkey_entry=FakeEntry("f7"),
            reset_hotkey_entry=FakeEntry("r"),
            record_hotkey_entry=FakeEntry("f8"),
            toggle_skip_chest_animation_hotkey_entry=FakeEntry("f11"),
            toggle_auto_select_upgrades_hotkey_entry=FakeEntry("f10"),
            toggle_particles_opacity_hotkey_entry=FakeEntry("f7"),
            map_load_delay_entry=FakeEntry("0.5"),
            reset_hold_duration_entry=FakeEntry("0.25"),
            record_interval_entry=FakeEntry("60"),
            native_hook_enabled_var=FakeVar(False),
            master=master,
            destroy=lambda: destroyed.append(True),
        )

        with patch.object(gui.config, "save_config") as save_config:
            with patch.object(gui.config, "update_game_reset_time") as update_game_reset_time:
                gui.SettingsDialog.save(dialog)

        self.assertFalse(gui.config.NATIVE_HOOK_ENABLED)
        self.assertFalse(gui.config.user_config["NATIVE_HOOK_ENABLED"])
        self.assertIn("apply_run_control_mode", master.events)
        self.assertTrue(save_config.called)
        self.assertTrue(update_game_reset_time.called)
        self.assertEqual(destroyed, [True])

    def test_native_hook_toggle_prompts_for_confirmation_on_enable(self) -> None:
        dialog = types.SimpleNamespace(
            native_hook_enabled_var=FakeVar(True),
            _native_hook_toggle_guard=False,
        )

        with patch.object(gui.SettingsDialog, "prompt_native_hook_enable_confirmation", return_value=True) as prompt:
            gui.SettingsDialog.on_native_hook_toggle(dialog)

        prompt.assert_called_once_with(dialog)
        self.assertTrue(dialog.native_hook_enabled_var.get())

    def test_native_hook_toggle_reverts_checkbox_when_confirmation_is_cancelled(self) -> None:
        dialog = types.SimpleNamespace(
            native_hook_enabled_var=FakeVar(True),
            _native_hook_toggle_guard=False,
        )

        with patch.object(gui.SettingsDialog, "prompt_native_hook_enable_confirmation", return_value=False) as prompt:
            gui.SettingsDialog.on_native_hook_toggle(dialog)

        prompt.assert_called_once_with(dialog)
        self.assertFalse(dialog.native_hook_enabled_var.get())
        self.assertFalse(dialog._native_hook_toggle_guard)

    def test_native_hook_toggle_does_not_prompt_when_disabling(self) -> None:
        dialog = types.SimpleNamespace(
            native_hook_enabled_var=FakeVar(False),
            _native_hook_toggle_guard=False,
        )

        with patch.object(gui.SettingsDialog, "prompt_native_hook_enable_confirmation") as prompt:
            gui.SettingsDialog.on_native_hook_toggle(dialog)

        prompt.assert_not_called()
        self.assertFalse(dialog.native_hook_enabled_var.get())

    def test_settings_save_persists_confirmed_native_hook_enable(self) -> None:
        master = FakeSettingsMaster()
        destroyed: list[bool] = []
        dialog = types.SimpleNamespace(
            hotkey_entry=FakeEntry("f7"),
            reset_hotkey_entry=FakeEntry("r"),
            record_hotkey_entry=FakeEntry("f8"),
            toggle_skip_chest_animation_hotkey_entry=FakeEntry("f11"),
            toggle_auto_select_upgrades_hotkey_entry=FakeEntry("f10"),
            toggle_particles_opacity_hotkey_entry=FakeEntry("f7"),
            map_load_delay_entry=FakeEntry("0.5"),
            reset_hold_duration_entry=FakeEntry("0.25"),
            record_interval_entry=FakeEntry("60"),
            native_hook_enabled_var=FakeVar(True),
            master=master,
            destroy=lambda: destroyed.append(True),
        )

        with patch.object(gui.config, "save_config") as save_config:
            with patch.object(gui.config, "update_game_reset_time") as update_game_reset_time:
                gui.SettingsDialog.save(dialog)

        self.assertTrue(gui.config.NATIVE_HOOK_ENABLED)
        self.assertTrue(gui.config.user_config["NATIVE_HOOK_ENABLED"])
        self.assertIn("apply_run_control_mode", master.events)
        self.assertTrue(save_config.called)
        self.assertTrue(update_game_reset_time.called)
        self.assertEqual(destroyed, [True])

    def test_apply_run_control_mode_detaches_hook_and_switches_to_keyboard_provider(self) -> None:
        loader = FakeDetachLoader()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = loader
        app.native_hook_thread = object()
        app.native_hook_generation = 1
        app.run_control_provider = object()
        app._native_hook_admin_warning_logged = True
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", False):
            gui.MegabonkApp.apply_run_control_mode(app)

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertIsNone(app.native_hook_loader)
        self.assertIsNone(app.native_hook_thread)
        self.assertEqual(app.native_hook_generation, 2)
        self.assertIsInstance(app.run_control_provider, KeyboardRunControlProvider)
        self.assertIn(("[+] Game restart helper disconnected.", "success"), logs)

    def test_apply_run_control_mode_enables_hook_provider_and_starts_worker(self) -> None:
        fake_loader = object()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = None
        app.native_hook_thread = None
        app.native_hook_generation = 0
        app.run_control_provider = object()
        app._native_hook_admin_warning_logged = False
        app.native_hook_loop = lambda *_args: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: True

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            with patch.object(gui, "NativeHookLoader", return_value=fake_loader):
                with patch.object(gui.threading, "Thread", FakeThread):
                    gui.MegabonkApp.apply_run_control_mode(app)

        self.assertIs(app.native_hook_loader, fake_loader)
        self.assertIsInstance(app.run_control_provider, HookRunControlProvider)
        self.assertEqual(app.native_hook_generation, 1)
        self.assertTrue(app.native_hook_thread.started)
        self.assertIn(("[*] Game restart helper enabled.", None), logs)

    def test_check_admin_rights_logs_hook_warning_when_hook_mode_is_enabled_without_admin(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False
        app._native_hook_admin_warning_logged = False

        with patch.object(gui.os, "name", "nt"):
            with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
                gui.MegabonkApp.check_admin_rights(app)

        self.assertIn(
            ("[*] Game restart helper may need Administrator privileges; trying anyway.", "warning"),
            logs,
        )
        self.assertNotIn(("⚠️ WARNING: Script is not running as Administrator!", "warning"), logs)
        self.assertNotIn(("⚠️ Hotkeys may not work while the game window is active.", "warning"), logs)

    def test_check_admin_rights_logs_keyboard_warnings_when_hook_mode_is_disabled(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.os, "name", "nt"):
            with patch.object(gui.config, "NATIVE_HOOK_ENABLED", False):
                gui.MegabonkApp.check_admin_rights(app)

        self.assertNotIn(
            ("[*] Game restart helper may need Administrator privileges; trying anyway.", "warning"),
            logs,
        )
        self.assertIn(("⚠️ WARNING: Script is not running as Administrator!", "warning"), logs)
        self.assertIn(("⚠️ Hotkeys may not work while the game window is active.", "warning"), logs)

    def test_enable_hook_run_control_logs_hook_warning_without_admin(self) -> None:
        fake_loader = object()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = None
        app.native_hook_thread = None
        app.native_hook_generation = 0
        app.run_control_provider = object()
        app._native_hook_admin_warning_logged = False
        app.native_hook_loop = lambda *_args: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            with patch.object(gui, "NativeHookLoader", return_value=fake_loader):
                with patch.object(gui.threading, "Thread", FakeThread):
                    gui.MegabonkApp.enable_hook_run_control(app)

        self.assertIn(
            ("[*] Game restart helper may need Administrator privileges; trying anyway.", "warning"),
            logs,
        )

    def test_startup_admin_warning_is_not_duplicated_by_hook_enable(self) -> None:
        fake_loader = object()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = None
        app.native_hook_thread = None
        app.native_hook_generation = 0
        app.run_control_provider = object()
        app._native_hook_admin_warning_logged = False
        app.native_hook_loop = lambda *_args: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.os, "name", "nt"):
            with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
                gui.MegabonkApp.check_admin_rights(app)
                with patch.object(gui, "NativeHookLoader", return_value=fake_loader):
                    with patch.object(gui.threading, "Thread", FakeThread):
                        gui.MegabonkApp.enable_hook_run_control(app)

        hook_warning = ("[*] Game restart helper may need Administrator privileges; trying anyway.", "warning")
        self.assertEqual(logs.count(hook_warning), 1)

    def test_keyboard_mode_resets_hook_admin_warning_for_later_hook_enable(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app._native_hook_admin_warning_logged = True
        app.log = lambda message, tag=None: logs.append((message, tag))

        gui.MegabonkApp.enable_keyboard_run_control(app)

        self.assertFalse(app._native_hook_admin_warning_logged)

    def test_hook_mode_bypasses_game_window_focus_wait(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = HookRunControlProvider(object(), map_load_delay=0)
        app.is_game_window_active = lambda _process_name: self.fail("hook mode should not check focus")

        self.assertTrue(gui.MegabonkApp.wait_for_game_window_focus(app, "Megabonk.exe"))

    def test_keyboard_mode_still_waits_when_game_window_is_not_active(self) -> None:
        logs: list[tuple[str, str | None]] = []
        sleeps: list[float] = []
        active_results = [False, False, True]
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = KeyboardRunControlProvider(
            None,
            reset_hotkey="r",
            reset_hold_duration=0.1,
            map_load_delay=0.2,
        )
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.scan_event.set()
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_game_window_active = lambda _process_name: active_results.pop(0)

        with patch.object(gui.time, "sleep", sleeps.append):
            self.assertTrue(gui.MegabonkApp.wait_for_game_window_focus(app, "Megabonk.exe"))

        self.assertEqual(sleeps, [0.3])
        self.assertIn(("[WAIT] Game window is not active. Auto-reroll paused...", "warning"), logs)
        self.assertIn(("[+] Game window active again. Auto-reroll resumed.", "success"), logs)

    def test_confirmed_target_in_hook_mode_brings_game_forward_and_closes_menu(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = HookRunControlProvider(object(), map_load_delay=0)
        app.bring_game_window_to_front_calls: list[str] = []
        app.bring_game_window_to_front = app.bring_game_window_to_front_calls.append
        app.wait_for_game_window_focus = lambda _process_name: self.fail("hook mode should not wait for focus")

        with patch.object(gui, "keyboard", fake_keyboard):
            self.assertTrue(gui.MegabonkApp.handle_confirmed_target_window(app, "Megabonk.exe"))

        self.assertEqual(app.bring_game_window_to_front_calls, ["Megabonk.exe"])
        self.assertEqual(fake_keyboard.press_and_release_calls, ["esc"])

    def test_confirmed_target_in_keyboard_mode_keeps_focus_check_and_esc(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        focus_checks: list[str] = []
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = KeyboardRunControlProvider(
            fake_keyboard,
            reset_hotkey="r",
            reset_hold_duration=0.1,
            map_load_delay=0.2,
        )
        app.wait_for_game_window_focus = lambda process_name: focus_checks.append(process_name) or True
        app.bring_game_window_to_front = lambda _process_name: self.fail("keyboard mode should not bring window forward")

        with patch.object(gui, "keyboard", fake_keyboard):
            self.assertTrue(gui.MegabonkApp.handle_confirmed_target_window(app, "Megabonk.exe"))

        self.assertEqual(focus_checks, ["Megabonk.exe"])
        self.assertEqual(fake_keyboard.press_and_release_calls, ["esc"])

    def test_bring_game_window_to_front_uses_alt_attach_fallback_after_direct_failure(self) -> None:
        fake_gui = FakeForegroundGui()
        fake_process = FakeForegroundProcess()
        fake_user32 = FakeUser32()
        fake_windll = FakeWindll(fake_user32, FakeKernel32())
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.find_game_window = lambda _process_name: 111
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui, "win32gui", fake_gui):
            with patch.object(gui, "win32process", fake_process):
                with patch.object(gui.ctypes, "windll", fake_windll):
                    self.assertTrue(gui.MegabonkApp.bring_game_window_to_front(app, "Megabonk.exe"))

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

    def test_alt_attach_fallback_detaches_threads_when_foreground_fails(self) -> None:
        fake_gui = FakeForegroundGui(fail_always=True)
        fake_process = FakeForegroundProcess()
        fake_user32 = FakeUser32()
        fake_windll = FakeWindll(fake_user32, FakeKernel32())
        app = object.__new__(gui.MegabonkApp)

        with patch.object(gui, "win32gui", fake_gui):
            with patch.object(gui, "win32process", fake_process):
                with patch.object(gui.ctypes, "windll", fake_windll):
                    with self.assertRaisesRegex(RuntimeError, "foreground denied"):
                        gui.MegabonkApp.try_attach_foreground_window(app, 111)

        self.assertEqual(
            fake_user32.attach_calls,
            [
                (10, 20, True),
                (10, 30, True),
                (10, 20, False),
                (10, 30, False),
            ],
        )

    def test_toggle_main_loop_clears_stale_scan_event_before_starting_worker(self) -> None:
        logs: list[tuple[object, object | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.scanner_thread = None
        app.checkboxes = {"Any": FakeVar(True)}
        app.refresh_stats_ui = lambda: None
        app.background_loop = lambda: None
        app.update_status_ui = lambda: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.stop_event.set()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True

        with patch.object(gui.config, "EVALUATION_MODE", "templates"):
            with patch.object(gui.threading, "Thread", FakeThread):
                gui.MegabonkApp.toggle_main_loop(app)

        self.assertFalse(app.scan_event.is_set())
        self.assertFalse(app.stop_event.is_set())
        self.assertFalse(app.is_running)
        self.assertFalse(app.is_ready_to_start)
        self.assertTrue(app.scanner_thread.started)

    def test_hotkey_starts_scanning_inside_running_monitor(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.scanner_thread = FakeAliveThread()
        app.scan_event = gui.threading.Event()
        app.is_ready_to_start = True
        app.is_running = False
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.update_status_ui = lambda: None

        gui.MegabonkApp.toggle_scan_event(app)

        self.assertTrue(app.is_running)
        self.assertTrue(app.scan_event.is_set())
        self.assertIn(("[*] Scan started. Looking for selected target...", None), logs)

    def test_hotkey_pauses_scanning_without_stopping_monitor(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.scanner_thread = FakeAliveThread()
        app.scan_event = gui.threading.Event()
        app.scan_event.set()
        app.is_ready_to_start = True
        app.is_running = True
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.update_status_ui = lambda: None

        gui.MegabonkApp.toggle_scan_event(app)

        self.assertFalse(app.is_running)
        self.assertFalse(app.scan_event.is_set())
        self.assertIn(("[*] Scan paused. Press the scan hotkey again to resume.", None), logs)

    def test_toggle_game_setting_logs_new_enabled_state(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = types.SimpleNamespace(toggle_skip_chest_animation=lambda: True)
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(app.native_hook_loader, "toggle_skip_chest_animation", return_value=True) as toggle_setting:
            changed = gui.MegabonkApp.toggle_game_setting(app, "skip_chest_animation", "Skip Chest Animation")

        self.assertTrue(changed)
        toggle_setting.assert_called_once_with()
        self.assertIn(("[+] Skip Chest Animation: ON", "success"), logs)

    def test_toggle_game_setting_supports_particles_opacity(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.native_hook_loader = types.SimpleNamespace(toggle_particles_opacity=lambda: True)
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(app.native_hook_loader, "toggle_particles_opacity", return_value=False) as toggle_setting:
            changed = gui.MegabonkApp.toggle_game_setting(app, "particle_opacity", "Particles Opacity")

        self.assertTrue(changed)
        toggle_setting.assert_called_once_with()
        self.assertIn(("[+] Particles Opacity: OFF", "success"), logs)

    def test_setup_hotkeys_registers_game_setting_hotkeys(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.hotkey_toggle_scanning = lambda: None
        app.hotkey_toggle_player_stats_recording = lambda: None
        app.hotkey_toggle_skip_chest_animation = lambda: None
        app.hotkey_toggle_auto_select_upgrades = lambda: None
        app.hotkey_toggle_particles_opacity = lambda: None

        with patch.object(gui, "keyboard", fake_keyboard):
            with patch.object(gui.config, "HOTKEY", "f6"):
                with patch.object(gui.config, "PLAYER_STATS_RECORD_HOTKEY", "f8"):
                    with patch.object(gui.config, "TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY", "f11"):
                        with patch.object(gui.config, "TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY", "f10"):
                            with patch.object(gui.config, "TOGGLE_PARTICLES_OPACITY_HOTKEY", "f7"):
                                gui.MegabonkApp.setup_hotkeys(app)

        self.assertEqual(fake_keyboard.unhook_all_calls, 1)
        registered_hotkeys = [hotkey for hotkey, _callback in fake_keyboard.add_hotkey_calls]
        self.assertEqual(registered_hotkeys, ["f6", "f8", "f11", "f10", "f7"])
        self.assertEqual(logs, [])

    def test_load_selected_vod_converts_qt_string_path_to_path(self) -> None:
        loaded_vod = types.SimpleNamespace(
            metadata=types.SimpleNamespace(path=Path("run.jsonl"), name="Run"),
            snapshots=(),
        )
        app = object.__new__(gui.MegabonkApp)
        app.loaded_vod = None
        app.loaded_vod_snapshot_index = None
        app.vods_name_entry = None
        app.refresh_loaded_vod_ui = lambda: None
        app.refresh_vods_list = lambda: None

        with patch.object(gui, "load_vod", return_value=loaded_vod) as load_vod:
            gui.MegabonkApp.load_selected_vod(app, "C:/tmp/run.jsonl")

        load_vod.assert_called_once_with(Path("C:/tmp/run.jsonl"))
        self.assertIs(app.loaded_vod, loaded_vod)

    def test_edit_template_dialog_opens_template_manager(self) -> None:
        opened: list[object] = []
        fake_dialog = types.SimpleNamespace(exec=lambda: opened.append("exec"))
        app = object.__new__(gui.MegabonkApp)
        app.window = object()
        app.apply_template_edit = lambda original, updated: opened.append((original, updated))
        templates = [{"id": 1, "name": "LIGHT"}]

        with patch.object(gui.config, "TEMPLATES", templates):
            with patch.object(gui, "TemplateManagerDialog", return_value=fake_dialog) as dialog_cls:
                gui.MegabonkApp.edit_template_dialog(app)

        dialog_cls.assert_called_once_with(app.window, templates, app.apply_template_edit)
        self.assertEqual(opened, ["exec"])

    def test_template_manager_dialog_expands_selected_template(self) -> None:
        gui.MegabonkApp._ensure_qt_application()
        templates = [
            {"id": 1, "name": "LIGHT", "color": "GREEN"},
            {"id": 2, "name": "PERFECT", "color": "YELLOW"},
        ]
        dialog = gui.TemplateManagerDialog(None, templates, lambda _original, _updated: True)

        first_details = dialog.card_widgets[1]["details"]
        second_details = dialog.card_widgets[2]["details"]
        self.assertTrue(first_details.isHidden())
        self.assertTrue(second_details.isHidden())

        dialog.toggle_template(2)
        self.assertEqual(dialog.expanded_template_id, 2)
        self.assertTrue(first_details.isHidden())
        self.assertFalse(second_details.isHidden())

        dialog.close()

    def test_template_manager_dialog_save_updates_template_and_collapses_card(self) -> None:
        gui.MegabonkApp._ensure_qt_application()
        saved: list[tuple[dict, dict]] = []
        templates = [{"id": 9, "name": "Custom", "micro": 1, "color": "MAGENTA"}]
        dialog = gui.TemplateManagerDialog(None, templates, lambda original, updated: saved.append((original, updated)) or True)

        form = dialog.card_widgets[9]["form"]
        form.micro_entry.setText("3")
        dialog.toggle_template(9)
        dialog.save_template(9, form)

        self.assertEqual(saved[0][0]["id"], 9)
        self.assertEqual(saved[0][1]["micro"], 3)
        self.assertEqual(dialog.templates[0]["micro"], 3)
        self.assertIsNone(dialog.expanded_template_id)
        self.assertTrue(dialog.card_widgets[9]["details"].isHidden())

        dialog.close()

    def test_log_reroll_stats_tracks_session_and_persistent_totals(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.session_rerolls = 3
        app.template_stats = {"Perfect": {"rerolls_since_last": 2, "history": []}}
        app.after = lambda _delay, callback: callback()
        app.log = lambda _message, tag=None: None
        app.best_map_stats = None
        app.worst_map_stats = None

        with patch.object(gui.config, "TOTAL_REROLLS", 10):
            with patch.object(gui.config, "save_config") as save_config:
                gui.MegabonkApp.log_reroll_stats(app)

                self.assertEqual(app.session_rerolls, 4)
                self.assertEqual(app.template_stats["Perfect"]["rerolls_since_last"], 3)
                self.assertEqual(gui.config.TOTAL_REROLLS, 11)
                self.assertEqual(gui.config.user_config["TOTAL_REROLLS"], 11)
                save_config.assert_called_once_with(gui.config.user_config)

    def test_save_checkbox_state_updates_runtime_templates_without_restart(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.checkboxes = {
            "Alpha": FakeCheckbox(True),
            "Beta": FakeCheckbox(False),
            "Gamma": FakeCheckbox(True),
        }
        app.active_templates = ["Alpha"]
        app.template_stats = {
            "Alpha": {"rerolls_since_last": 2, "history": [3]},
            "Beta": {"rerolls_since_last": 1, "history": [4]},
        }
        app.session_rerolls = 7
        app.scanner_thread = FakeAliveThread()
        app.stats_avg_labels = {}
        app.stats_avg_layout = SimpleNamespace(removeWidget=lambda _widget: None)
        app.refresh_stats_ui = lambda: None
        logs: list[tuple[str, str | None]] = []
        app.log = lambda message, tag=None: logs.append((message, tag))

        with patch.object(gui.config, "EVALUATION_MODE", "templates"):
            with patch.object(gui.config, "save_config") as save_config:
                gui.MegabonkApp.save_checkbox_state(app)

        self.assertEqual(gui.config.ACTIVE_TEMPLATES, ["Alpha", "Gamma"])
        self.assertEqual(app.active_templates, ["Alpha", "Gamma"])
        self.assertEqual(app.template_stats["Alpha"]["history"], [3])
        self.assertEqual(app.template_stats["Gamma"], {"rerolls_since_last": 0, "history": []})
        self.assertNotIn("Beta", app.template_stats)
        self.assertEqual(logs, [("[*] Active templates updated live: Alpha, Gamma", None)])
        save_config.assert_called_once_with(gui.config.user_config)

    def test_refresh_scores_ui_updates_runtime_tiers_without_restart(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.scores_desc_label = SimpleNamespace(setHtml=lambda _text: None)
        app.scores_checkboxes = {
            "Light": FakeCheckbox(True),
            "Good": FakeCheckbox(False),
            "Perfect": FakeCheckbox(True),
            "Perfect+": FakeCheckbox(False),
        }
        app.template_stats = {"Good": {"rerolls_since_last": 4, "history": [2]}}
        app.scanner_thread = FakeAliveThread()
        app.stats_avg_labels = {}
        app.stats_avg_layout = SimpleNamespace(removeWidget=lambda _widget: None)
        app.refresh_stats_ui = lambda: None
        logs: list[tuple[str, str | None]] = []
        app.log = lambda message, tag=None: logs.append((message, tag))

        original_scores = deepcopy(gui.config.SCORES_SYSTEM)
        updated_scores = deepcopy(gui.config.SCORES_SYSTEM)
        updated_scores["active_tiers"] = ["Good"]
        gui.config.SCORES_SYSTEM = updated_scores
        gui.config.user_config["SCORES_SYSTEM"] = updated_scores

        with patch.object(gui.config, "EVALUATION_MODE", "scores"):
            with patch.object(gui.config, "save_config") as save_config:
                gui.MegabonkApp.refresh_scores_ui(app)

        self.assertEqual(gui.config.SCORES_SYSTEM["active_tiers"], ["Light", "Perfect"])
        self.assertEqual(
            app.template_stats,
            {
                "Light": {"rerolls_since_last": 0, "history": []},
                "Perfect": {"rerolls_since_last": 0, "history": []},
            },
        )
        self.assertEqual(logs, [("[*] Active tiers updated live: Light, Perfect", None)])
        save_config.assert_called_once_with(gui.config.user_config)
        gui.config.SCORES_SYSTEM = original_scores
        gui.config.user_config["SCORES_SYSTEM"] = original_scores

    def test_background_loop_cleanup_clears_scan_event_after_stop_wake(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.stop_event.set()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True
        app.after = lambda _delay, callback: callback()
        app.update_status_ui = lambda: None

        gui.MegabonkApp.background_loop(app)

        self.assertFalse(app.scan_event.is_set())
        self.assertFalse(app.is_running)
        self.assertFalse(app.is_ready_to_start)

    def test_background_loop_reuses_stable_snapshot_for_candidate(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.get_map_stats_calls = 0

            def wait_for_map_ready(self, **_kwargs: object) -> dict[str, int]:
                return {"Moais": 4, "Microwaves": 1}

            def get_map_generation_state(self) -> object:
                return object()

            def get_map_stats(self) -> dict[str, int]:
                self.get_map_stats_calls += 1
                return {"Moais": 999}

        app = object.__new__(gui.MegabonkApp)
        app.client = FakeClient()
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.scan_event.set()
        app.is_running = True
        app.is_ready_to_start = True
        app.after = lambda _delay, callback: callback()
        app.update_status_ui = lambda: None
        app.wait_for_game_window_focus = lambda _process_name: True
        app.check_best_map = lambda _stats: None
        app.check_worst_map = lambda _stats: None
        app.evaluate_candidate = lambda stats: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None
        app.log_target_found = lambda _name: None
        app.handle_confirmed_target_window = lambda _process_name: app.stop_event.set() or True
        app.close_client = lambda: None
        app.log = lambda _message, tag=None: None

        with patch.object(gui, "adapt_map_stats", lambda raw_stats: raw_stats):
            gui.MegabonkApp.background_loop(app)

        self.assertEqual(app.client.get_map_stats_calls, 0)

    def test_recording_run_state_split_starts_new_file_when_seed_changes(self) -> None:
        app = self.build_recording_app()
        app.player_stats_recording_seed = 111
        app.player_stats_game_data_client = FakeSeedStateClient([222])

        action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        self.assertEqual(action, "split")
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [{"name": None, "seed": 222}])
        self.assertEqual(app.player_stats_recording_seed, 222)
        self.assertEqual(app.player_stats_vod_snapshots, [])
        self.assertIn("auto-split", app.log_messages[0][0])

    def test_recording_run_state_stops_after_seed_missing_grace_period(self) -> None:
        app = self.build_recording_app()
        app.player_stats_recording_seed = 111
        app.player_stats_game_data_client = FakeSeedStateClient([None, None])

        with patch.object(gui.time, "monotonic", return_value=100.0):
            first_action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        with patch.object(
            gui.time,
            "monotonic",
            return_value=100.0 + gui.PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS + 1.0,
        ):
            second_action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        self.assertIsNone(first_action)
        self.assertEqual(second_action, "stopped")
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertFalse(app.player_stats_vod_recorder.is_recording)
        self.assertIsNone(app.player_stats_recording_seed)
        self.assertIn("auto-stopped", app.log_messages[0][0])

    def test_update_player_stats_timer_auto_stops_recording_when_game_is_closed(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        app.player_stats_recording_seed = 111
        app.player_stats_game_data_client = FakeSeedStateClient([None, None])

        def failing_read_player_stats_only() -> tuple[dict[str, object], int]:
            raise gui.ProcessNotFoundError("game closed")

        app.read_player_stats_only = failing_read_player_stats_only

        with patch.object(gui.time, "monotonic", return_value=100.0):
            gui.MegabonkApp.update_player_stats_timer(app)

        with patch.object(
            gui.time,
            "monotonic",
            return_value=100.0 + gui.PLAYER_STATS_RECORDING_SEED_GRACE_SECONDS + 1.0,
        ):
            gui.MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertFalse(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(len(app.after_calls), 2)

    def test_refresh_right_tab_after_switch_immediately_refreshes_live_stats(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.tabview = FakeTabWidget("Live Stats")
        calls: list[str] = []
        app.refresh_vods_list = lambda: calls.append("vods")
        app.refresh_live_player_stats_now = lambda *args, **kwargs: calls.append("live")

        gui.MegabonkApp._refresh_right_tab_after_switch(app)

        self.assertEqual(calls, ["live"])

    def test_update_player_stats_timer_skips_hidden_live_stats_when_not_recording(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        read_calls: list[str] = []
        app.read_player_stats_only = lambda: read_calls.append("stats") or ({}, 0x1234)

        gui.MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(read_calls, [])
        self.assertEqual(len(app.after_calls), 1)

    def test_refresh_live_player_stats_now_keeps_stats_when_items_fail(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app.player_stats_status_label = FakeLabel()
        stat_label = FakeLabel()
        app.player_stats_rows = {"Damage": stat_label}
        app.player_stats_items_label = FakeLabel()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app._get_player_stats_client = lambda: SimpleNamespace(get_run_timer=lambda: 21.5)
        app.close_player_stats_client = lambda: None
        app.refresh_player_stats_timeline_ui = lambda *args, **kwargs: None
        app._refresh_vods_list_if_visible = lambda: None
        app._is_live_stats_tab_active = lambda: True
        app.read_player_stats_only = lambda: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)

        def fail_items(owner_stats=None):
            raise gui.MemoryReadError("items missing")

        app.read_passive_items_only = fail_items

        result = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_status_label.text(), "Live player stats")
        self.assertEqual(stat_label.text(), "123")
        self.assertEqual(app.player_stats_items_label.text(), "Items unavailable")
        self.assertEqual(app.player_stats_chests_per_minute_label.text(), "Average chests/min: --")
        self.assertEqual(app.player_stats_in_game_time_label.text(), "In-Game Time: 00:21")

    def test_refresh_live_player_stats_now_captures_while_hidden_recording(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        timeline_calls: list[str] = []
        snapshot_calls: list[str] = []
        app.refresh_player_stats_timeline_ui = lambda *args, **kwargs: timeline_calls.append("timeline")
        app.display_player_stats_snapshot = lambda *args, **kwargs: snapshot_calls.append("snapshot")
        app.read_player_stats_only = lambda: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)
        app.read_passive_items_only = lambda owner_stats=None: ("Wrench x2",)

        result = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(len(app.player_stats_vod_recorder.capture_calls), 1)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["items"], ("Wrench x2",))
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["game_time_seconds"], 21.5)
        self.assertEqual(snapshot_calls, [])
        self.assertEqual(timeline_calls, ["timeline"])

    def test_refresh_live_player_stats_now_updates_live_view_while_recording(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: True
        display_calls: list[dict[str, object]] = []
        app.display_player_stats = lambda stats, items=(), **kwargs: display_calls.append(
            {"stats": stats, "items": tuple(items), "kwargs": kwargs}
        )
        app.read_player_stats_only = lambda: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)
        app.read_passive_items_only = lambda owner_stats=None: ("Wrench x2",)

        result = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(len(display_calls), 1)
        self.assertEqual(display_calls[0]["items"], ("Wrench x2",))
        self.assertEqual(display_calls[0]["kwargs"]["status_text"], "Live player stats (recording)")

    def test_toggle_player_stats_recording_captures_snapshot_without_items(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._read_player_stats_recording_seed_safe = lambda: 321
        app.read_player_stats_only = lambda: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)

        def fail_items(owner_stats=None):
            raise gui.MemoryReadError("items missing")

        app.read_passive_items_only = fail_items

        gui.MegabonkApp.toggle_player_stats_recording(app)

        self.assertEqual(len(app.player_stats_vod_recorder.capture_calls), 1)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["items"], ())

    def test_stop_player_stats_recording_refreshes_live_stats_without_items(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True)
        app.player_stats_vod_snapshots = ["snapshot"]
        app.player_stats_selected_snapshot_index = 0
        app.player_stats_recording_seed = 111
        app.player_stats_recording_seed_missing_since = 200.0
        app.player_stats_status_label = FakeLabel()
        stat_label = FakeLabel()
        app.player_stats_rows = {"Damage": stat_label}
        app.player_stats_items_label = FakeLabel()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app._get_player_stats_client = lambda: SimpleNamespace(get_run_timer=lambda: 21.5)
        app.close_player_stats_client = lambda: None
        app.close_player_stats_game_data_client = lambda: None
        app.refresh_player_stats_timeline_ui = lambda *args, **kwargs: None
        app._refresh_vods_list_if_visible = lambda: None
        app._is_live_stats_tab_active = lambda: True
        app.log = lambda *args, **kwargs: None
        app.read_player_stats_only = lambda: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)

        def fail_items(owner_stats=None):
            raise gui.MemoryReadError("items missing")

        app.read_passive_items_only = fail_items

        gui.MegabonkApp._stop_player_stats_recording(app)

        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertEqual(app.player_stats_status_label.text(), "Live player stats")
        self.assertEqual(stat_label.text(), "123")
        self.assertEqual(app.player_stats_items_label.text(), "Items unavailable")
        self.assertEqual(app.player_stats_in_game_time_label.text(), "In-Game Time: 00:21")

    def test_display_player_stats_snapshot_shows_in_game_time_in_status_and_summary(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.player_stats_vod_snapshots = []
        calls: list[dict[str, object]] = []
        snapshot = SimpleNamespace(
            stats={"Damage": SimpleNamespace(display_value="123", value=1.23)},
            items=("Wrench x2",),
            chests_per_minute=1.5,
            game_time_seconds=81.75,
            time_label="01:00",
        )
        app.player_stats_vod_snapshots = [snapshot]
        app.display_player_stats = lambda stats, items=(), **kwargs: calls.append(
            {"stats": stats, "items": tuple(items), "kwargs": kwargs}
        )

        gui.MegabonkApp.display_player_stats_snapshot(app, snapshot)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["kwargs"]["status_text"], "Recorded snapshot 1/1 at 01:00 | In-Game Time: 01:21")
        self.assertEqual(calls[0]["kwargs"]["game_time_seconds"], 81.75)

    def test_display_loaded_vod_snapshot_shows_legacy_in_game_fallback(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.vods_status_label = FakeLabel()
        app.vods_slider_time_label = FakeLabel()
        app.vods_items_label = FakeLabel()
        app.vods_in_game_time_label = FakeLabel()
        app.vods_chests_per_minute_label = FakeLabel()
        app.vods_rows = {"Damage": FakeLabel()}
        app.loaded_vod_snapshot_index = None
        snapshot = SimpleNamespace(
            stats={"Damage": SimpleNamespace(display_value="123", value=1.23)},
            items=("Wrench x1",),
            chests_per_minute=1.23,
            game_time_seconds=None,
            time_label="00:00",
        )
        metadata = SimpleNamespace(name="Legacy run")
        app.loaded_vod = SimpleNamespace(metadata=metadata, snapshots=[snapshot])

        gui.MegabonkApp.display_loaded_vod_snapshot(app, 0)

        self.assertEqual(app.vods_status_label.text(), "Legacy run | 1/1 at 00:00 | In-Game Time: --")
        self.assertEqual(app.vods_in_game_time_label.text(), "In-Game Time: --")
        self.assertEqual(app.vods_items_label.text(), "Wrench x1")

    def test_format_in_game_time_truncates_fractional_seconds(self) -> None:
        self.assertEqual(gui.MegabonkApp.format_in_game_time(None), "In-Game Time: --")
        self.assertEqual(gui.MegabonkApp.format_in_game_time(21.52338219), "In-Game Time: 00:21")
        self.assertEqual(gui.MegabonkApp.format_in_game_time(3661.9), "In-Game Time: 01:01:01")

    def test_format_items_rich_text_colors_name_only(self) -> None:
        result = gui.MegabonkApp.format_items_rich_text(("Wrench x2", "Bonker x1", "Crypt Key x1"))

        self.assertIn('color: #22C55E', result)
        self.assertIn('>Wrench</span> x2', result)
        self.assertIn('color: #FACC15', result)
        self.assertIn('>Bonker</span> x1', result)
        self.assertIn('Crypt Key x1', result)
        self.assertNotIn('color: #22C55E;">Wrench x2</span>', result)

    def test_format_items_rich_text_supports_gloves_aliases(self) -> None:
        result = gui.MegabonkApp.format_items_rich_text(("Gloves Blood x1", "Gloves Power x1"))

        self.assertIn('>Gloves Blood</span> x1', result)
        self.assertIn('color: #E879F9', result)
        self.assertIn('>Gloves Power</span> x1', result)
        self.assertIn('color: #FACC15', result)

    def test_format_items_rich_text_supports_flappy_feathers_alias(self) -> None:
        result = gui.MegabonkApp.format_items_rich_text(("Flappy Feathers x1",))

        self.assertIn('>Flappy Feathers</span> x1', result)
        self.assertIn('color: #60A5FA', result)

    def test_format_items_rich_text_handles_display_name_variants(self) -> None:
        result = gui.MegabonkApp.format_items_rich_text(
            (
                "Borgor x1",
                "Bob Lantern x1",
                "Bob's Lantern x1",
                "Grandma's Secret Tonic x1",
                "Gloves Cursed x1",
                "No Implementation x1",
                "Pot Steel x1",
                "Sucky Hoof x1",
            )
        )

        self.assertIn('>Borgor</span> x1', result)
        self.assertIn('color: #22C55E', result)
        self.assertIn(">Bob Lantern</span> x1", result)
        self.assertIn(">Bob&#x27;s Lantern</span> x1", result)
        self.assertIn(">Grandma&#x27;s Secret Tonic</span> x1", result)
        self.assertIn(">Gloves Cursed</span> x1", result)
        self.assertIn('color: #E879F9', result)
        self.assertIn(">Golden Ring</span> x1", result)
        self.assertIn('>Pot Steel</span> x1', result)
        self.assertIn(">Sucky Hoof</span> x1", result)
        self.assertIn('color: #FACC15', result)

    def test_normalize_item_name_for_rarity_handles_aliases_and_gloves_rule(self) -> None:
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Flappy Feathers"), "Feathers")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Gloves Power"), "Glove Power")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Borgor"), "Borgar")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Bob Lantern"), "Bobs Lantern")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Bob's Lantern"), "Bobs Lantern")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Gloves Cursed"), "Glove Curse")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("No Implementation"), "Golden Ring")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Pot Steel"), "Pot")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Sucky Hoof"), "Sucky Magnet")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Wrench"), "Wrench")

    def test_normalize_item_name_for_display_replaces_no_implementation(self) -> None:
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_display("No Implementation"), "Golden Ring")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_display("Sucky Hoof"), "Sucky Hoof")

    def test_split_item_stack_suffix_handles_plain_names(self) -> None:
        self.assertEqual(gui.MegabonkApp._split_item_stack_suffix("Wrench x2"), ("Wrench", " x2"))
        self.assertEqual(gui.MegabonkApp._split_item_stack_suffix("Ghost"), ("Ghost", ""))

    def test_on_closing_detaches_native_hooks_and_invalidates_worker(self) -> None:
        loader = FakeDetachLoader()
        logs: list[tuple[str, str | None]] = []
        destroyed: list[bool] = []
        app = object.__new__(gui.MegabonkApp)
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.native_hook_loader = loader
        app.native_hook_thread = object()
        app.native_hook_generation = 7
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.destroy = lambda: destroyed.append(True)

        with patch.object(gui, "keyboard", None):
            gui.MegabonkApp.on_closing(app)

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertTrue(app.stop_event.is_set())
        self.assertTrue(app.scan_event.is_set())
        self.assertIsNone(app.native_hook_loader)
        self.assertIsNone(app.native_hook_thread)
        self.assertEqual(app.native_hook_generation, 8)
        self.assertEqual(destroyed, [True])
        self.assertIn(("[+] Game restart helper disconnected.", "success"), logs)

    def test_on_closing_continues_when_native_hook_detach_fails(self) -> None:
        loader = FakeDetachLoader(error=gui.HookLoadError("remote status 17"))
        logs: list[tuple[str, str | None]] = []
        destroyed: list[bool] = []
        app = object.__new__(gui.MegabonkApp)
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.native_hook_loader = loader
        app.native_hook_thread = object()
        app.native_hook_generation = 2
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.destroy = lambda: destroyed.append(True)

        with patch.object(gui, "keyboard", None):
            gui.MegabonkApp.on_closing(app)

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertIsNone(app.native_hook_loader)
        self.assertIsNone(app.native_hook_thread)
        self.assertEqual(app.native_hook_generation, 3)
        self.assertEqual(destroyed, [True])
        self.assertIn(
            ("[WAIT] Could not disconnect restart helper during shutdown. Details: remote status 17", "warning"),
            logs,
        )

    def test_on_closing_continues_when_game_process_is_gone(self) -> None:
        loader = FakeDetachLoader(error=gui.HookProcessNotFoundError("Waiting for process 'Megabonk.exe'."))
        logs: list[tuple[str, str | None]] = []
        destroyed: list[bool] = []
        app = object.__new__(gui.MegabonkApp)
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.native_hook_loader = loader
        app.native_hook_thread = object()
        app.native_hook_generation = 4
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.destroy = lambda: destroyed.append(True)

        with patch.object(gui, "keyboard", None):
            gui.MegabonkApp.on_closing(app)

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertIsNone(app.native_hook_loader)
        self.assertIsNone(app.native_hook_thread)
        self.assertEqual(app.native_hook_generation, 5)
        self.assertEqual(destroyed, [True])
        self.assertIn(
            (
                "[WAIT] Game is already closed; restart helper shutdown skipped.",
                "warning",
            ),
            logs,
        )

    def test_native_hook_loop_attempts_injection_without_admin(self) -> None:
        loader = FakeHookLoopLoader()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.stop_event = types.SimpleNamespace(is_set=lambda: False, wait=lambda _seconds: None)
        app.native_hook_generation = 1
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            gui.MegabonkApp.native_hook_loop(app, loader, 1)

        self.assertEqual(loader.inject_calls, 1)
        self.assertIn(("[+] Game restart helper connected successfully.", "success"), logs)

    def test_native_hook_loop_logs_injection_failure_without_admin(self) -> None:
        loader = FakeHookLoopLoader(inject_error=gui.HookLoadError("OpenProcess(1234) failed"))
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.stop_event = types.SimpleNamespace(is_set=lambda: False, wait=lambda _seconds: None)
        app.native_hook_generation = 1
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            gui.MegabonkApp.native_hook_loop(app, loader, 1)

        self.assertEqual(loader.inject_calls, 1)
        self.assertIn(
            ("[-] Could not connect game restart helper. Details: OpenProcess(1234) failed", "error"),
            logs,
        )
        self.assertNotIn(("[+] Game restart helper connected successfully.", "success"), logs)

    def test_native_hook_loop_retries_when_game_runtime_is_not_ready(self) -> None:
        loader = FakeHookLoopLoader(
            inject_error=[gui.HookProcessNotReadyError("runtime not ready"), None],
        )
        waits: list[float] = []
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.stop_event = types.SimpleNamespace(is_set=lambda: False, wait=lambda seconds: waits.append(seconds))
        app.native_hook_generation = 1
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: True

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            gui.MegabonkApp.native_hook_loop(app, loader, 1)

        self.assertEqual(loader.inject_calls, 2)
        self.assertEqual(waits, [1.0])
        self.assertIn(("[WAIT] Game is starting up. Restart helper will connect automatically.", None), logs)
        self.assertIn(("[+] Game restart helper connected successfully.", "success"), logs)

    def test_native_hook_loop_logs_success_for_admin_injection(self) -> None:
        loader = FakeHookLoopLoader(pid=6728)
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.stop_event = types.SimpleNamespace(is_set=lambda: False, wait=lambda _seconds: None)
        app.native_hook_generation = 1
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: True

        with patch.object(gui.config, "NATIVE_HOOK_ENABLED", True):
            gui.MegabonkApp.native_hook_loop(app, loader, 1)

        self.assertEqual(loader.inject_calls, 1)
        self.assertIn(("[+] Game restart helper connected successfully.", "success"), logs)


if __name__ == "__main__":
    unittest.main()
