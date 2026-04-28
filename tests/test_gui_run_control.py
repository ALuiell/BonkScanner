from __future__ import annotations

import types
import unittest
from copy import deepcopy
from unittest.mock import patch

import gui


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


class FakeKeyboardModule:
    def __init__(self) -> None:
        self.unhook_all_calls = 0

    def unhook_all(self) -> None:
        self.unhook_all_calls += 1


class FakeClient:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeThread:
    def __init__(self, *, target: object, args: tuple[object, ...] = (), daemon: bool) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True


class GuiRunControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_config_values = {
            "HOTKEY": gui.config.HOTKEY,
            "RESET_HOTKEY": gui.config.RESET_HOTKEY,
            "MAP_LOAD_DELAY": gui.config.MAP_LOAD_DELAY,
            "RESET_HOLD_DURATION": gui.config.RESET_HOLD_DURATION,
            "NATIVE_HOOK_ENABLED": gui.config.NATIVE_HOOK_ENABLED,
            "EVALUATION_MODE": gui.config.EVALUATION_MODE,
        }
        self.original_user_config = deepcopy(gui.config.user_config)
        self.original_templates = deepcopy(gui.config.TEMPLATES)
        self.original_scores_system = deepcopy(gui.config.SCORES_SYSTEM)

    def tearDown(self) -> None:
        for name, value in self.original_config_values.items():
            setattr(gui.config, name, value)
        gui.config.user_config.clear()
        gui.config.user_config.update(self.original_user_config)
        gui.config.TEMPLATES[:] = self.original_templates
        gui.config.SCORES_SYSTEM.clear()
        gui.config.SCORES_SYSTEM.update(self.original_scores_system)

    def test_settings_save_updates_native_hook_enabled_and_applies_run_control_mode(self) -> None:
        master = FakeSettingsMaster()
        destroyed: list[bool] = []
        dialog = types.SimpleNamespace(
            hotkey_entry=FakeEntry("f7"),
            reset_hotkey_entry=FakeEntry("r"),
            map_load_delay_entry=FakeEntry("0.5"),
            reset_hold_duration_entry=FakeEntry("0.25"),
            native_hook_enabled_var=FakeVar(False),
            master=master,
            destroy=lambda: destroyed.append(True),
        )

        with patch.object(gui.config, "save_config") as save_config:
            with patch.object(gui.config, "update_game_reset_time") as update_game_reset_time:
                gui.SettingsDialog.save(dialog)

        self.assertFalse(gui.config.NATIVE_HOOK_ENABLED)
        self.assertFalse(gui.config.user_config["NATIVE_HOOK_ENABLED"])
        self.assertIn("setup_hotkeys", master.events)
        self.assertIn("update_status_ui", master.events)
        self.assertIn("apply_run_control_mode", master.events)
        self.assertIn("log", master.events)
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

    def test_toggle_main_loop_templates_mode_starts_worker_with_active_templates(self) -> None:
        logs: list[tuple[object, object | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.scanner_thread = None
        app.checkboxes = {"Alpha": FakeVar(True), "Beta": FakeVar(False), "Gamma": FakeVar(True)}
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
        app.session_start_time = None
        app.total_rerolls = 12
        app.best_map_stats = object()
        app.best_map_score = 9.9
        app.worst_map_stats = object()
        app.worst_map_score = 1.2
        app.template_stats = {}
        app.active_templates = []

        with patch.object(gui.config, "EVALUATION_MODE", "templates"):
            with patch.object(
                gui.config,
                "TEMPLATES",
                [
                    {"name": "Alpha", "color": "cyan"},
                    {"name": "Gamma", "color": "green"},
                ],
            ):
                with patch.object(gui.threading, "Thread", FakeThread):
                    gui.MegabonkApp.toggle_main_loop(app)

        self.assertEqual(app.active_templates, ["Alpha", "Gamma"])
        self.assertEqual(
            app.template_stats,
            {
                "Alpha": {"rerolls_since_last": 0, "history": []},
                "Gamma": {"rerolls_since_last": 0, "history": []},
            },
        )
        self.assertIsNotNone(app.session_start_time)
        self.assertEqual(app.total_rerolls, 0)
        self.assertIsNone(app.best_map_stats)
        self.assertEqual(app.best_map_score, -1)
        self.assertIsNone(app.worst_map_stats)
        self.assertEqual(app.worst_map_score, float("inf"))
        self.assertFalse(app.stop_event.is_set())
        self.assertFalse(app.scan_event.is_set())
        self.assertFalse(app.is_running)
        self.assertFalse(app.is_ready_to_start)
        self.assertTrue(app.scanner_thread.started)
        self.assertTrue(
            any(
                isinstance(message, list)
                and message[0] == "[*] Active profiles: "
                and message[1:] == ["Alpha", ", ", "Gamma"]
                for message, _tag in logs
            )
        )

    def test_toggle_main_loop_scores_mode_logs_active_tiers_and_starts_worker(self) -> None:
        logs: list[tuple[object, object | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.scanner_thread = None
        app.checkboxes = {}
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
        app.session_start_time = None
        app.total_rerolls = 5
        app.best_map_stats = object()
        app.best_map_score = 2.0
        app.worst_map_stats = object()
        app.worst_map_score = 8.0
        app.template_stats = {}
        app.active_templates = []

        with patch.object(gui.config, "EVALUATION_MODE", "scores"):
            with patch.object(gui.config, "SCORES_SYSTEM", {"active_tiers": ["Light", "Perfect"]}):
                with patch.object(gui.threading, "Thread", FakeThread):
                    gui.MegabonkApp.toggle_main_loop(app)

        self.assertEqual(app.template_stats, {"Light": {"rerolls_since_last": 0, "history": []}, "Perfect": {"rerolls_since_last": 0, "history": []}})
        self.assertIsNotNone(app.session_start_time)
        self.assertEqual(app.total_rerolls, 0)
        self.assertIsNone(app.best_map_stats)
        self.assertEqual(app.best_map_score, -1)
        self.assertIsNone(app.worst_map_stats)
        self.assertEqual(app.worst_map_score, float("inf"))
        self.assertFalse(app.stop_event.is_set())
        self.assertFalse(app.scan_event.is_set())
        self.assertFalse(app.is_running)
        self.assertFalse(app.is_ready_to_start)
        self.assertTrue(app.scanner_thread.started)
        self.assertIn(("[*] Active Tiers: Light, Perfect", None), logs)

    def test_hotkey_toggle_scanning_refuses_before_ready(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.is_ready_to_start = False
        app.is_running = False
        app.scan_event = gui.threading.Event()
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.update_status_ui = lambda: None

        gui.MegabonkApp.hotkey_toggle_scanning(app)

        self.assertFalse(app.is_running)
        self.assertFalse(app.scan_event.is_set())
        self.assertIn(("[WAIT] Scanner is not ready yet. Please wait for the game.", "warning"), logs)

    def test_hotkey_toggle_scanning_toggles_scan_event_after_ready(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.is_ready_to_start = True
        app.is_running = False
        app.scan_event = gui.threading.Event()
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.update_status_ui = lambda: None

        gui.MegabonkApp.hotkey_toggle_scanning(app)
        self.assertTrue(app.is_running)
        self.assertTrue(app.scan_event.is_set())
        self.assertIn(("\n[!!!] Script STARTED via Hotkey", "success"), logs)

        gui.MegabonkApp.hotkey_toggle_scanning(app)
        self.assertFalse(app.is_running)
        self.assertFalse(app.scan_event.is_set())
        self.assertIn(("\n[!!!] Script STOPPED via Hotkey", "warning"), logs)

    def test_on_closing_signals_stop_wakes_scanner_detaches_hooks_and_destroys_window(self) -> None:
        loader = FakeDetachLoader()
        logs: list[tuple[str, str | None]] = []
        destroyed: list[bool] = []
        keyboard_module = FakeKeyboardModule()
        client = FakeClient()
        app = object.__new__(gui.MegabonkApp)
        app.client = client
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.native_hook_loader = loader
        app.native_hook_thread = object()
        app.native_hook_generation = 7
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.destroy = lambda: destroyed.append(True)

        with patch.object(gui, "keyboard", keyboard_module):
            gui.MegabonkApp.on_closing(app)

        self.assertEqual(loader.uninitialize_calls, 1)
        self.assertEqual(client.close_calls, 1)
        self.assertIsNone(app.client)
        self.assertTrue(app.stop_event.is_set())
        self.assertTrue(app.scan_event.is_set())
        self.assertIsNone(app.native_hook_loader)
        self.assertIsNone(app.native_hook_thread)
        self.assertEqual(app.native_hook_generation, 8)
        self.assertEqual(keyboard_module.unhook_all_calls, 1)
        self.assertEqual(destroyed, [True])
        self.assertIn(("[+] Native hooks detached for PID 1234.", "success"), logs)


if __name__ == "__main__":
    unittest.main()
