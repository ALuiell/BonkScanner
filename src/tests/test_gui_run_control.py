from __future__ import annotations

import src

import types
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import gui
from game_data import RuntimeGameMode, RuntimeGameState
from run_control import KeyboardRunControlProvider


class FakeEntry:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def text(self) -> str:
        return self.value

    def setText(self, value: str) -> None:
        self.value = value


class FakeVar:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value

    def set(self, value: bool) -> None:
        self.value = value


class FakeSpinBox:
    def __init__(self, value: int) -> None:
        self._value = value

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:
        self._value = value


class FakeComboBox:
    def __init__(self, value: str) -> None:
        self.value = value

    def currentText(self) -> str:
        return self.value


class FakeCheckbox:
    def __init__(self, value: bool) -> None:
        self.value = value

    def isChecked(self) -> bool:
        return self.value

    def setChecked(self, value: bool) -> None:
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


class FakeKeyboardModule:
    def __init__(self) -> None:
        self.press_and_release_calls: list[str] = []
        self.add_hotkey_calls: list[tuple[str, object]] = []
        self.hook_calls: list[object] = []
        self.hook_remove_calls = 0
        self.unhook_all_calls = 0
        self._scan_codes: dict[str, int] = {}

    def press_and_release(self, key: str) -> None:
        self.press_and_release_calls.append(key)

    def key_to_scan_codes(self, key_name: str) -> tuple[int, ...]:
        normalized = key_name.strip().lower()
        if normalized not in self._scan_codes:
            self._scan_codes[normalized] = len(self._scan_codes) + 1
        return (self._scan_codes[normalized],)

    def parse_hotkey(self, hotkey: str):
        return tuple(
            tuple(self.key_to_scan_codes(key) for key in step.split("+"))
            for step in hotkey.split(",")
        )

    def hook(self, callback: object):
        self.hook_calls.append(callback)

        def remove() -> None:
            self.hook_remove_calls += 1

        return remove

    def add_hotkey(self, hotkey: str, callback: object):
        self.add_hotkey_calls.append((hotkey, callback))
        return lambda: None

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

    def capture(
        self,
        stats,
        items=(),
        weapons=(),
        tomes=(),
        banishes=(),
        damage_sources=(),
        *,
        chaos_tome=None,
        chests_per_minute=None,
        game_time_seconds=None,
        mob_kills=None,
        kps_at_capture=None,
        minute_avg_kps_at_capture=None,
        five_minute_avg_kps_at_capture=None,
        run_avg_kps_at_capture=None,
        player_level=None,
        map_seed=None,
        stage_ptr=0,
        stage_time_seconds=None,
        chests_opened=None,
        chests_total=None,
        paid_chests=None,
        key_procs=None,
        free_chests=None,
        keys_count=None,
        expected_key_procs=None,
        chests_opened_by_stage=None,
        chests_total_by_stage=None,
    ):
        snapshot = SimpleNamespace(
            stats=stats,
            items=tuple(items),
            weapons=tuple(weapons),
            tomes=tuple(tomes),
            chaos_tome=chaos_tome,
            banishes=tuple(banishes),
            damage_sources=tuple(damage_sources),
            chests_per_minute=chests_per_minute,
            game_time_seconds=game_time_seconds,
            mob_kills=mob_kills,
            kps_at_capture=kps_at_capture,
            minute_avg_kps_at_capture=minute_avg_kps_at_capture,
            five_minute_avg_kps_at_capture=five_minute_avg_kps_at_capture,
            run_avg_kps_at_capture=run_avg_kps_at_capture,
            player_level=player_level,
            map_seed=map_seed,
            stage_ptr=stage_ptr,
            stage_time_seconds=stage_time_seconds,
            chests_opened=chests_opened,
            chests_total=chests_total,
            paid_chests=paid_chests,
            key_procs=key_procs,
            free_chests=free_chests,
            keys_count=keys_count,
            expected_key_procs=expected_key_procs,
            chests_opened_by_stage=chests_opened_by_stage,
            chests_total_by_stage=chests_total_by_stage,
            time_label="00:00",
        )
        self.capture_calls.append(
            {
                "stats": stats,
                "items": tuple(items),
                "weapons": tuple(weapons),
                "tomes": tuple(tomes),
                "chaos_tome": chaos_tome,
                "banishes": tuple(banishes),
                "damage_sources": tuple(damage_sources),
                "chests_per_minute": chests_per_minute,
                "game_time_seconds": game_time_seconds,
                "mob_kills": mob_kills,
                "kps_at_capture": kps_at_capture,
                "minute_avg_kps_at_capture": minute_avg_kps_at_capture,
                "five_minute_avg_kps_at_capture": five_minute_avg_kps_at_capture,
                "run_avg_kps_at_capture": run_avg_kps_at_capture,
                "player_level": player_level,
                "map_seed": map_seed,
                "stage_ptr": stage_ptr,
                "stage_time_seconds": stage_time_seconds,
                "chests_opened": chests_opened,
                "chests_total": chests_total,
                "paid_chests": paid_chests,
                "key_procs": key_procs,
                "free_chests": free_chests,
                "keys_count": keys_count,
                "expected_key_procs": expected_key_procs,
                "chests_opened_by_stage": chests_opened_by_stage,
                "chests_total_by_stage": chests_total_by_stage,
            }
        )
        self.should_capture_value = False
        return snapshot


class FakeSeedStateClient:
    def __init__(self, states: list[object]) -> None:
        self.states = list(states)
        self.close_calls = 0

    def get_map_generation_state(self) -> SimpleNamespace:
        state = self.states.pop(0) if self.states else None
        if isinstance(state, SimpleNamespace):
            return state
        if isinstance(state, dict):
            return SimpleNamespace(
                map_seed=state.get("map_seed"),
                current_stage_ptr=state.get("current_stage_ptr", 0),
            )
        return SimpleNamespace(map_seed=state, current_stage_ptr=0)

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
    def test_formats_full_chests_card(self) -> None:
        self.assertEqual(
            gui.MegabonkApp.chests_card_values(
                {1: 46, 2: 46, 3: 42},
                {1: 46, 2: 46, 3: 46},
                134,
                138,
                52,
                71,
                11,
                17,
                75.44,
            ),
            {
                "maps": "T1:46/46 T2:46/46 T3:42/46",
                "total": "134/138",
                "paid_free": "52 / 11",
                "key_procs": "71/123 (57.7%)",
                "expected": "75.4",
                "keys": "17 (63.0%)",
            },
        )

    def test_formats_midrun_chests_card_with_minimum_total(self) -> None:
        self.assertEqual(
            gui.MegabonkApp.chests_card_values(
                {1: -1, 2: 20},
                {1: 46, 2: 46},
                51,
                92,
                17,
                34,
                None,
                0,
                None,
                True,
            ),
            {
                "maps": "T1:--/46 T2:20/46",
                "total": "51+/92",
                "paid_free": "17 / --",
                "key_procs": "34/51 (66.7%)",
                "expected": "--",
                "keys": "0 (0.0%)",
            },
        )

    def build_recording_app(self) -> gui.MegabonkApp:
        app = object.__new__(gui.MegabonkApp)
        app.player_stats_vod_recorder = FakeRecordingRecorder()
        app.player_stats_vod_snapshots = ["snapshot"]
        app.player_stats_selected_snapshot_index = 0
        app.player_stats_recording_seed = None
        app.player_stats_recording_stage_ptr = 0
        app.player_stats_recording_seed_missing_since = None
        app.player_stats_recording_run_time_seconds = None
        app.player_stats_recording_armed = False
        app.player_stats_recording_waiting_mode = None
        app.player_stats_auto_recording_suppressed = False
        app.player_stats_auto_start_detection_streak = 0
        app.player_stats_game_data_client = None
        app.player_stats_client = SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
            get_live_tomes=lambda owner_stats=None: (),
        )
        app.player_stats_status_label = FakeLabel()
        app.player_stats_rows = {}
        app.player_stats_items_label = FakeLabel()
        app.player_stats_banishes_label = FakeLabel()
        app.player_stats_live_banishes = ()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app.player_stats_powerups_duration_label = FakeLabel()
        app.player_stats_mob_kills_label = FakeLabel()
        app.player_stats_level_label = FakeLabel()
        app.player_stats_new_items_label = FakeLabel()
        app.player_stats_stage_summary_labels = []
        app.player_stats_tome_signature = None
        app.player_stats_tomes_status_label = FakeLabel()
        app.player_stats_tomes_layout = None
        app.player_stats_damage_sources_status_label = FakeLabel()
        app.player_stats_damage_sources_layout = None
        app.player_stats_damage_source_signature = None
        app.vods_banishes_label = FakeLabel()
        app.vods_damage_sources_status_label = FakeLabel()
        app.vods_damage_sources_layout = None
        app.vods_damage_source_signature = None
        app.refresh_player_stats_timeline_ui = lambda *args, **kwargs: None
        app._refresh_vods_list_if_visible = lambda: None
        app.display_player_stats = lambda *args, **kwargs: None
        app.display_player_stats_snapshot = lambda *args, **kwargs: None
        app.display_tome_cards = lambda *args, **kwargs: None
        app.display_damage_source_rows = lambda *args, **kwargs: None
        app.close_player_stats_client = lambda: None
        app.read_player_stats_only = lambda: ({}, 0x1234)
        app.read_passive_items_only = lambda owner_stats=None: ()
        app.read_player_stats_runtime_game_state = lambda: RuntimeGameState(
            mode=RuntimeGameMode.IN_GAME,
            is_playing=True,
        )
        app._is_live_stats_tab_active = lambda: True
        app.log_messages = []
        app.log = lambda message, tag=None: app.log_messages.append((message, tag))
        app.live_run_tracker = SimpleNamespace(
            update=lambda *args, **kwargs: None,
            update_chests_and_keys=lambda *args, **kwargs: None,
            mark_read_failed=lambda *args, **kwargs: None,
            stage_summary_rows=lambda: [],
            current_ui_kps=lambda: None,
        )
        app.overlay_state_store = None
        return app

    def setUp(self) -> None:
        self.original_config_values = {
            "HOTKEY": gui.config.HOTKEY,
            "HOTKEY_GAME_KEY_WHITELIST": deepcopy(gui.config.HOTKEY_GAME_KEY_WHITELIST),
            "RESET_HOTKEY": gui.config.RESET_HOTKEY,
            "PLAYER_STATS_RECORD_HOTKEY": gui.config.PLAYER_STATS_RECORD_HOTKEY,
            "AUTO_START_RECORDING": gui.config.AUTO_START_RECORDING,
            "SHOW_OBS_REMINDER_ON_START_SCANNER": gui.config.SHOW_OBS_REMINDER_ON_START_SCANNER,
            "MAP_LOAD_DELAY": gui.config.MAP_LOAD_DELAY,
            "RESET_HOLD_DURATION": gui.config.RESET_HOLD_DURATION,
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

    def test_enabling_twitch_help_shows_alias_dialog(self) -> None:
        import gui_dialogs

        shown = []
        saved = []

        class FakeAliasDialog:
            def __init__(self, parent):
                shown.append(parent)
                self.dont_show_again = True

            def exec(self):
                return 1

        app = object.__new__(gui.MegabonkApp)
        app.window = object()
        app.twitch_cmd_commands_cb = FakeCheckbox(True)
        app.save_twitch_settings = lambda *args: saved.append(True)
        gui.config.user_config["SKIP_TWITCH_HELP_WARNING"] = False

        with patch.object(gui_dialogs, "TwitchCommandsHelpDialog", FakeAliasDialog), patch.object(
            gui.config, "save_config"
        ):
            gui.MegabonkApp.on_twitch_commands_toggled(app)

        self.assertEqual(shown, [app.window])
        self.assertTrue(gui.config.user_config["SKIP_TWITCH_HELP_WARNING"])
        self.assertEqual(saved, [True])

    def test_save_twitch_settings_does_not_depend_on_main_interval_widget(self) -> None:
        app = types.SimpleNamespace(
            twitch_tier_combo=FakeComboBox("Everyone"),
            twitch_target_channel_entry=types.SimpleNamespace(text=lambda: "#bonk"),
            twitch_global_cooldown_spin=FakeSpinBox(5),
            twitch_cooldown_spin=FakeSpinBox(7),
            twitch_stage_announcements_cb=FakeCheckbox(True),
            twitch_commands_announcements_cb=FakeCheckbox(True),
            twitch_cmd_stats_cb=FakeCheckbox(True),
            twitch_cmd_session_cb=FakeCheckbox(True),
            twitch_cmd_bans_cb=FakeCheckbox(False),
            twitch_cmd_items_cb=FakeCheckbox(True),
            twitch_cmd_weapons_cb=FakeCheckbox(True),
            twitch_cmd_tomes_cb=FakeCheckbox(True),
            twitch_cmd_chaos_cb=FakeCheckbox(True),
            twitch_cmd_stages_cb=FakeCheckbox(True),
            twitch_cmd_powerups_cb=FakeCheckbox(True),
            twitch_cmd_kps_cb=FakeCheckbox(True),
            twitch_cmd_scanner_cb=FakeCheckbox(True),
            twitch_cmd_chests_cb=FakeCheckbox(True),
            twitch_cmd_presets_cb=FakeCheckbox(True),
            twitch_cmd_commands_cb=FakeCheckbox(True),
            twitch_cmd_disabled_cb=FakeCheckbox(False),
        )

        with patch.object(gui.config, "save_config") as save_config:
            gui.MegabonkApp.save_twitch_settings(app)

        self.assertEqual(gui.config.TWITCH_BOT["target_channel"], "bonk")
        self.assertEqual(gui.config.TWITCH_BOT["global_cooldown_seconds"], 5)
        self.assertEqual(gui.config.TWITCH_BOT["cooldown_seconds"], 7)
        self.assertTrue(gui.config.TWITCH_BOT["commands_announcements"])
        self.assertTrue(save_config.called)

    def test_save_twitch_auto_connect_persists_checkbox_state(self) -> None:
        app = types.SimpleNamespace(twitch_auto_connect_cb=FakeCheckbox(True))

        with patch.dict(gui.config.TWITCH_BOT, {"auto_connect": False}), patch.object(
            gui.config, "save_config"
        ) as save_config:
            gui.MegabonkApp.save_twitch_auto_connect(app)

            self.assertTrue(gui.config.TWITCH_BOT["auto_connect"])
            save_config.assert_called_once_with(gui.config.user_config)

    def test_twitch_auth_success_starts_bot_when_auto_connect_is_enabled(self) -> None:
        app = types.SimpleNamespace(
            twitch_connect_btn=MagicMock(),
            twitch_disconnect_btn=MagicMock(),
            twitch_auth_status_label=MagicMock(),
            twitch_target_channel_entry=MagicMock(),
            log=MagicMock(),
            start_twitch_bot=MagicMock(),
        )

        with patch.dict(gui.config.TWITCH_BOT, {"auto_connect": True}), patch(
            "gui_twitch.set_twitch_oauth_token"
        ), patch.object(gui.config, "save_config"):
            gui.MegabonkApp.on_twitch_auth_success(app, "bonk", "token")

            self.assertEqual(gui.config.TWITCH_BOT["username"], "bonk")
            app.start_twitch_bot.assert_called_once_with()

    def test_twitch_bot_status_value_does_not_repeat_status_label(self) -> None:
        status_label = MagicMock()
        app = types.SimpleNamespace(twitch_bot_status_label=status_label)

        gui.MegabonkApp._update_twitch_bot_status_ui(app, "Connected")

        formatted = status_label.setText.call_args.args[0]
        self.assertNotIn("Status:", formatted)
        self.assertIn("Connected", formatted)

    def test_settings_save_updates_community_settings_and_applies_run_control_mode(self) -> None:
        master = FakeSettingsMaster()
        master.player_stats_auto_recording_suppressed = True
        destroyed: list[bool] = []
        dialog = types.SimpleNamespace(
            hotkey_entry=FakeEntry("f7"),
            reset_hotkey_entry=FakeEntry("r"),
            record_hotkey_entry=FakeEntry("f8"),
            auto_start_recording_var=FakeVar(True),
            show_obs_reminder_on_start_scanner_var=FakeVar(True),
            map_load_delay_entry=FakeEntry("0.5"),
            reset_hold_duration_entry=FakeEntry("0.25"),
            record_interval_entry=FakeEntry("60"),
            master=master,
            destroy=lambda: destroyed.append(True),
        )

        with patch.object(gui.config, "save_config") as save_config:
            with patch.object(gui.config, "update_game_reset_time") as update_game_reset_time:
                gui.SettingsDialog.save(dialog)

        self.assertTrue(gui.config.AUTO_START_RECORDING)
        self.assertTrue(gui.config.SHOW_OBS_REMINDER_ON_START_SCANNER)
        self.assertFalse(master.player_stats_auto_recording_suppressed)
        self.assertTrue(gui.config.user_config["AUTO_START_RECORDING"])
        self.assertTrue(gui.config.user_config["SHOW_OBS_REMINDER_ON_START_SCANNER"])
        self.assertIn("apply_run_control_mode", master.events)
        self.assertTrue(save_config.called)
        self.assertTrue(update_game_reset_time.called)
        self.assertEqual(destroyed, [True])

    def test_twitch_command_settings_save_persists_commands_announcement_interval(self) -> None:
        accepted: list[bool] = []
        dialog = types.SimpleNamespace(
            stat_checkboxes={"Damage": FakeCheckbox(True)},
            stats_tpl_entry=FakeEntry("Live Stats: {Damage}"),
            templates_entries={"stats": FakeEntry("Live Stats: {Damage}")},
            disabled_item_checkboxes={"Anvil": FakeCheckbox(True), "Coin": FakeCheckbox(False)},
            commands_announcement_interval_spin=FakeSpinBox(42),
            accept=lambda: accepted.append(True),
        )

        with patch.object(gui.config, "save_config") as save_config:
            gui.TwitchCommandSettingsDialog.save(dialog)

        self.assertEqual(gui.config.TWITCH_BOT["commands_announcement_interval_minutes"], 42)
        self.assertEqual(gui.config.TWITCH_BOT["highlighted_disabled_items"], ["Anvil"])
        self.assertEqual(accepted, [True])
        save_config.assert_called_once_with(gui.config.user_config)

    def test_twitch_command_settings_filter_shows_ingame_disabled_items_without_show_all(self) -> None:
        class FakeGridItem:
            def __init__(self, widget: object) -> None:
                self._widget = widget

            def widget(self) -> object:
                return self._widget

        class FakeGrid:
            def __init__(self) -> None:
                self.widgets: list[object] = []

            def count(self) -> int:
                return len(self.widgets)

            def itemAt(self, index: int) -> FakeGridItem:
                return FakeGridItem(self.widgets[index])

            def removeWidget(self, widget: object) -> None:
                self.widgets.remove(widget)

            def addWidget(self, widget: object, _row: int, _col: int) -> None:
                self.widgets.append(widget)

        class FilterCheckbox(FakeCheckbox):
            def __init__(self, value: bool, *, is_disabled_ingame: bool = False) -> None:
                super().__init__(value)
                self.visible = True
                self.props = {"is_disabled_ingame": is_disabled_ingame}

            def property(self, name: str) -> object:
                return self.props.get(name)

            def setVisible(self, value: bool) -> None:
                self.visible = value

        grid = FakeGrid()
        disabled_cb = FilterCheckbox(False, is_disabled_ingame=True)
        normal_cb = FilterCheckbox(False)
        selected_cb = FilterCheckbox(True)
        dialog = types.SimpleNamespace(
            disabled_search_input=FakeEntry(""),
            show_all_disabled_items_cb=FakeCheckbox(False),
            disabled_grid=grid,
            disabled_item_checkboxes={
                "Disabled Sword": disabled_cb,
                "Normal Ring": normal_cb,
                "Selected Tome": selected_cb,
            },
        )

        gui.TwitchCommandSettingsDialog.filter_disabled_items(dialog)

        self.assertEqual(grid.widgets, [disabled_cb, selected_cb])
        self.assertTrue(disabled_cb.visible)
        self.assertFalse(normal_cb.visible)
        self.assertTrue(selected_cb.visible)

    def test_twitch_command_settings_reset_restores_default_interval(self) -> None:
        dialog = types.SimpleNamespace(
            _init_guard=False,
            stat_checkboxes={"Damage": FakeCheckbox(False), "XP Gain": FakeCheckbox(False)},
            stats_tpl_entry=FakeEntry("custom"),
            disabled_item_checkboxes={"Anvil": FakeCheckbox(True)},
            templates_entries={"stats": FakeEntry("custom"), "disabled": FakeEntry("custom")},
            commands_announcement_interval_spin=FakeSpinBox(99),
        )

        gui.TwitchCommandSettingsDialog.reset_to_defaults(dialog)

        self.assertEqual(
            dialog.commands_announcement_interval_spin.value(),
            gui.config.DEFAULT_TWITCH_BOT["commands_announcement_interval_minutes"],
        )

    def test_apply_run_control_mode_enables_keyboard_provider(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = object()

        gui.MegabonkApp.apply_run_control_mode(app)

        self.assertIsInstance(app.run_control_provider, KeyboardRunControlProvider)

    def test_check_admin_rights_logs_keyboard_warnings_without_admin(self) -> None:
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.is_running_as_admin = lambda: False

        with patch.object(gui.os, "name", "nt"):
            gui.MegabonkApp.check_admin_rights(app)

        self.assertTrue(any("WARNING: Script is not running as Administrator" in message for message, _tag in logs))
        self.assertTrue(any("Hotkeys may not work while the game window is active" in message for message, _tag in logs))
    def test_game_window_focus_falls_back_to_title_when_attached_pid_differs(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.get_game_process_id = lambda: 1234
        fake_gui = SimpleNamespace(
            GetForegroundWindow=lambda: 111,
            GetWindowText=lambda _window: "Megabonk",
        )
        fake_process = SimpleNamespace(GetWindowThreadProcessId=lambda _window: (10, 5678))

        with patch.object(gui, "win32gui", fake_gui):
            with patch.object(gui, "win32process", fake_process):
                self.assertTrue(gui.MegabonkApp.is_game_window_active(app, "Megabonk.exe"))

    def test_game_window_focus_rejects_unrelated_title_when_attached_pid_differs(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.get_game_process_id = lambda: 1234
        fake_gui = SimpleNamespace(
            GetForegroundWindow=lambda: 111,
            GetWindowText=lambda _window: "BonkScanner",
        )
        fake_process = SimpleNamespace(GetWindowThreadProcessId=lambda _window: (10, 5678))

        with patch.object(gui, "win32gui", fake_gui):
            with patch.object(gui, "win32process", fake_process):
                self.assertFalse(gui.MegabonkApp.is_game_window_active(app, "Megabonk.exe"))

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

        with patch.dict(gui.config.user_config, {"SKIP_REROLL_WARNING": True}):
            with patch.object(gui.config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False):
                with patch.object(gui.config, "EVALUATION_MODE", "templates"):
                    with patch.object(gui.threading, "Thread", FakeThread):
                        gui.MegabonkApp.toggle_main_loop(app)

        self.assertFalse(app.scan_event.is_set())
        self.assertFalse(app.stop_event.is_set())
        self.assertFalse(app.is_running)
        self.assertFalse(app.is_ready_to_start)
        self.assertTrue(app.scanner_thread.started)

    def test_toggle_main_loop_logs_scores_tiers_with_colors(self) -> None:
        logs: list[tuple[object, object | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.scanner_thread = None
        app.refresh_stats_ui = lambda: None
        app.background_loop = lambda: None
        app.update_status_ui = lambda: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.is_running = False
        app.is_ready_to_start = False

        original_scores = deepcopy(gui.config.SCORES_SYSTEM)
        updated_scores = deepcopy(gui.config.SCORES_SYSTEM)
        updated_scores["active_tiers"] = ["Light", "Perfect", "Perfect+"]
        gui.config.SCORES_SYSTEM = updated_scores

        try:
            with patch.dict(gui.config.user_config, {"SKIP_REROLL_WARNING": True}):
                with patch.object(gui.config, "SHOW_OBS_REMINDER_ON_START_SCANNER", False):
                    with patch.object(gui.config, "EVALUATION_MODE", "scores"):
                        with patch.object(gui.threading, "Thread", FakeThread):
                            gui.MegabonkApp.toggle_main_loop(app)
        finally:
            gui.config.SCORES_SYSTEM = original_scores

        self.assertIn(
            (
                ["[*] Active Tiers: ", "Light", ", ", "Perfect", ", ", "Perfect+"],
                [None, "WHITE", None, "YELLOW", None, "LIGHTRED_EX"],
            ),
            logs,
        )
        self.assertEqual(
            app.template_stats,
            {
                "Light": {"rerolls_since_last": 0, "history": []},
                "Perfect": {"rerolls_since_last": 0, "history": []},
                "Perfect+": {"rerolls_since_last": 0, "history": []},
            },
        )
        self.assertTrue(app.scanner_thread.started)

    def test_toggle_main_loop_shows_obs_reminder_when_enabled(self) -> None:
        logs: list[tuple[object, object | None]] = []
        shown = []
        app = object.__new__(gui.MegabonkApp)
        app.window = object()
        app.scanner_thread = None
        app.checkboxes = {"Any": FakeVar(True)}
        app.refresh_stats_ui = lambda: None
        app.background_loop = lambda: None
        app.update_status_ui = lambda: None
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.is_running = False
        app.is_ready_to_start = False
        app.obs_recording_reminder_shown = False

        class FakeObsRecordingReminderDialog:
            def __init__(self, parent):
                shown.append(parent)

            def exec(self):
                shown.append("exec")
                return 1

        with patch.dict(
            gui.config.user_config,
            {"SKIP_REROLL_WARNING": True, "SHOW_OBS_REMINDER_ON_START_SCANNER": True},
        ):
            with patch.object(gui.config, "SHOW_OBS_REMINDER_ON_START_SCANNER", True):
                with patch.object(gui.config, "EVALUATION_MODE", "templates"):
                    with patch.object(gui.threading, "Thread", FakeThread):
                        with patch("gui_dialogs.ObsRecordingReminderDialog", FakeObsRecordingReminderDialog):
                            gui.MegabonkApp.toggle_main_loop(app)

        self.assertEqual(shown, [app.window, "exec"])
        self.assertTrue(app.obs_recording_reminder_shown)
        self.assertTrue(app.scanner_thread.started)

        app.scanner_thread = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()

        with patch.dict(
            gui.config.user_config,
            {"SKIP_REROLL_WARNING": True, "SHOW_OBS_REMINDER_ON_START_SCANNER": True},
        ):
            with patch.object(gui.config, "SHOW_OBS_REMINDER_ON_START_SCANNER", True):
                with patch.object(gui.config, "EVALUATION_MODE", "templates"):
                    with patch.object(gui.threading, "Thread", FakeThread):
                        with patch("gui_dialogs.ObsRecordingReminderDialog", FakeObsRecordingReminderDialog):
                            gui.MegabonkApp.toggle_main_loop(app)

        self.assertEqual(shown, [app.window, "exec"])
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

    def test_setup_hotkeys_registers_supported_hotkeys(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        logs: list[tuple[str, str | None]] = []
        app = object.__new__(gui.MegabonkApp)
        app.log = lambda message, tag=None: logs.append((message, tag))
        app.hotkey_toggle_scanning = lambda: None
        app.hotkey_toggle_player_stats_recording = lambda: None

        with patch.object(gui, "keyboard", fake_keyboard):
            with patch.object(gui.config, "HOTKEY", "f6"):
                with patch.object(gui.config, "PLAYER_STATS_RECORD_HOTKEY", "f8"):
                    gui.MegabonkApp.setup_hotkeys(app)

        self.assertEqual(fake_keyboard.unhook_all_calls, 0)
        self.assertEqual(len(fake_keyboard.hook_calls), 1)
        self.assertEqual(fake_keyboard.add_hotkey_calls, [])
        self.assertIsNotNone(app._hotkey_manager)
        self.assertEqual(logs, [])

    def test_hotkey_with_held_game_key_uses_title_fallback_for_active_window(self) -> None:
        fake_keyboard = FakeKeyboardModule()
        scan_toggles: list[str] = []
        app = object.__new__(gui.MegabonkApp)
        app.log = lambda _message, tag=None: None
        app.get_game_process_id = lambda: 1234
        app.hotkey_toggle_scanning = lambda: scan_toggles.append("scan")
        app.hotkey_toggle_player_stats_recording = lambda: None
        fake_gui = SimpleNamespace(
            GetForegroundWindow=lambda: 111,
            GetWindowText=lambda _window: "Megabonk",
        )
        fake_process = SimpleNamespace(GetWindowThreadProcessId=lambda _window: (10, 5678))

        with patch.object(gui, "keyboard", fake_keyboard):
            with patch.object(gui, "win32gui", fake_gui):
                with patch.object(gui, "win32process", fake_process):
                    with patch.object(gui.config, "HOTKEY_GAME_KEY_WHITELIST", ("w",)):
                        with patch.object(gui.config, "HOTKEY", "f6"):
                            gui.MegabonkApp.setup_hotkeys(app)

                            hook = fake_keyboard.hook_calls[0]
                            hook(SimpleNamespace(scan_code=fake_keyboard.key_to_scan_codes("w")[0], event_type="down"))
                            hook(SimpleNamespace(scan_code=fake_keyboard.key_to_scan_codes("f6")[0], event_type="down"))

        self.assertEqual(scan_toggles, ["scan"])

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
        self.assertEqual(app.template_stats["Beta"], {"rerolls_since_last": 1, "history": [4]})
        self.assertEqual(logs, [("[*] Active templates updated live: Alpha, Gamma", None)])
        save_config.assert_called_once_with(gui.config.user_config)

    def test_format_stats_includes_bald_heads_when_active_template_requires_it(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.active_templates = ["BALD"]
        stats = {
            "Shady Guy": 1,
            "Moais": 2,
            "Microwaves": 7,
            "Chests": 69,
            "Boss Curses": 3,
            "Magnet Shrines": 1,
            "Bald Heads": 4,
        }

        with patch.object(gui.config, "EVALUATION_MODE", "templates"):
            with patch.object(gui.config, "TEMPLATES", [{"name": "BALD", "bald_heads": 2}]):
                text = gui.MegabonkApp.format_stats(app, stats)

        self.assertIn("Bald Heads: 4", text)
        self.assertIn("Microwaves: 7", text)

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
                "Good": {"rerolls_since_last": 4, "history": [2]},
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
        app.evaluate_candidate = lambda stats, context=None: {"name": "Perfect", "color": "GREEN"} if stats["Moais"] == 4 else None
        app.log_target_found = lambda _name: None
        app.handle_confirmed_target_window = lambda _process_name: app.stop_event.set() or True
        app.close_client = lambda: None
        app.log = lambda _message, tag=None: None

        with patch.object(gui, "adapt_map_stats", lambda raw_stats: raw_stats):
            gui.MegabonkApp.background_loop(app)

        self.assertEqual(app.client.get_map_stats_calls, 0)

    def test_reroll_map_returns_false_when_scan_is_paused(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.run_control_provider = SimpleNamespace(
            restart_run=lambda: self.fail("restart_run should not be called while paused"),
            wait_for_next_run=lambda **_kwargs: self.fail("wait_for_next_run should not be called while paused"),
        )
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.log = lambda _message, tag=None: None

        self.assertFalse(gui.MegabonkApp.reroll_map(app))

    def test_recording_run_state_split_starts_new_file_when_seed_changes(self) -> None:
        app = self.build_recording_app()
        app.player_stats_recording_seed = 111
        app.player_stats_recording_stage_ptr = 0x1000
        app.player_stats_recording_run_time_seconds = 120.0
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: 4.0, get_killed_mobs=lambda: 37)
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=222, current_stage_ptr=0x2000)]
        )

        action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        self.assertEqual(action, "split")
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [{"name": None, "seed": 222}])
        self.assertEqual(app.player_stats_recording_seed, 222)
        self.assertEqual(app.player_stats_vod_snapshots, [])
        self.assertIn("auto-split", app.log_messages[0][0])

    def test_recording_run_state_does_not_split_when_seed_changes_between_stages(self) -> None:
        app = self.build_recording_app()
        app.player_stats_recording_seed = 111
        app.player_stats_recording_stage_ptr = 0x1000
        app.player_stats_recording_run_time_seconds = 120.0
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: 123.0, get_killed_mobs=lambda: 37)
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=222, current_stage_ptr=0x2000)]
        )

        action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        self.assertIsNone(action)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 0)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertEqual(app.player_stats_recording_seed, 222)
        self.assertEqual(app.player_stats_recording_stage_ptr, 0x2000)
        self.assertEqual(app.player_stats_recording_run_time_seconds, 123.0)
        self.assertEqual(app.log_messages, [])

    def test_recording_run_state_does_not_split_when_stage_ptr_changes_inside_same_run(self) -> None:
        app = self.build_recording_app()
        app.player_stats_recording_seed = 111
        app.player_stats_recording_stage_ptr = 0x1000
        app.player_stats_recording_run_time_seconds = 120.0
        app.player_stats_client = SimpleNamespace(get_run_timer=lambda: 123.0, get_killed_mobs=lambda: 37)
        app.player_stats_game_data_client = FakeSeedStateClient(
            [SimpleNamespace(map_seed=111, current_stage_ptr=0x2000)]
        )

        action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        self.assertIsNone(action)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 0)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertEqual(app.player_stats_recording_seed, 111)
        self.assertEqual(app.player_stats_recording_stage_ptr, 0x2000)
        self.assertEqual(app.player_stats_recording_run_time_seconds, 123.0)
        self.assertEqual(app.log_messages, [])

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

    def test_recording_run_state_keeps_file_open_while_paused(self) -> None:
        app = self.build_recording_app()
        app.read_player_stats_runtime_game_state = lambda: RuntimeGameState(
            mode=RuntimeGameMode.PAUSED_IN_GAME,
            is_playing=True,
            is_paused=True,
        )

        action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        self.assertEqual(action, "paused")
        self.assertTrue(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 0)
        self.assertEqual(app.player_stats_recording_waiting_mode, RuntimeGameMode.PAUSED_IN_GAME.value)

    def test_recording_run_state_waits_after_game_over_without_disarming(self) -> None:
        app = self.build_recording_app()
        app.player_stats_recording_armed = True
        app.read_player_stats_runtime_game_state = lambda: RuntimeGameState(
            mode=RuntimeGameMode.GAME_OVER,
            is_playing=True,
            is_game_over=True,
        )

        action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        self.assertEqual(action, "waiting")
        self.assertFalse(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertTrue(app.player_stats_recording_armed)
        self.assertEqual(app.player_stats_recording_waiting_mode, RuntimeGameMode.GAME_OVER.value)

    def test_recording_run_state_waits_after_manual_menu_without_disarming(self) -> None:
        app = self.build_recording_app()
        app.player_stats_recording_armed = True
        app.read_player_stats_runtime_game_state = lambda: RuntimeGameState(
            mode=RuntimeGameMode.MAIN_MENU,
        )

        action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        self.assertEqual(action, "waiting")
        self.assertFalse(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertTrue(app.player_stats_recording_armed)
        self.assertEqual(app.player_stats_recording_waiting_mode, RuntimeGameMode.MAIN_MENU.value)

    def test_recording_run_state_starts_new_file_from_waiting_when_game_resumes(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder.is_recording = False
        app.player_stats_recording_armed = True
        app.player_stats_recording_waiting_mode = RuntimeGameMode.MAIN_MENU.value
        app.read_player_stats_runtime_game_state = lambda: RuntimeGameState(
            mode=RuntimeGameMode.IN_GAME,
            is_playing=True,
        )
        app.read_player_stats_recording_state = lambda: SimpleNamespace(
            map_seed=333,
            current_stage_ptr=0x3000,
        )

        action = gui.MegabonkApp._sync_player_stats_recording_run_state(app)

        self.assertEqual(action, "started")
        self.assertTrue(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [{"name": None, "seed": 333}])
        self.assertEqual(app.player_stats_recording_stage_ptr, 0x3000)
        self.assertIsNone(app.player_stats_recording_waiting_mode)

    def test_toggle_recording_stops_auto_recording_waiting_mode_for_session(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder.is_recording = False
        app.player_stats_recording_armed = False
        app.player_stats_recording_waiting_mode = RuntimeGameMode.MAIN_MENU.value
        app.refresh_live_player_stats_now = lambda *args, **kwargs: None

        with patch.object(gui.config, "AUTO_START_RECORDING", True):
            self.assertTrue(gui.MegabonkApp._is_player_stats_recording_armed(app))

            gui.MegabonkApp.toggle_player_stats_recording(app)

            self.assertFalse(gui.MegabonkApp._is_player_stats_recording_armed(app))

        self.assertTrue(app.player_stats_auto_recording_suppressed)
        self.assertFalse(app.player_stats_recording_armed)
        self.assertFalse(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertIn(("[*] Player stats recording stopped.", None), app.log_messages)

    def test_auto_start_recording_respects_session_suppression(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder.is_recording = False
        app.player_stats_auto_recording_suppressed = True

        with patch.object(gui.config, "AUTO_START_RECORDING", True):
            started = gui.MegabonkApp._maybe_auto_start_player_stats_recording(
                app,
                stats={"Damage": SimpleNamespace(display_value="123", value=1.23)},
                run_timer_seconds=21.5,
                player_level=2,
                map_seed=777,
                stage_ptr=2,
            )

        self.assertFalse(started)
        self.assertEqual(app.player_stats_auto_start_detection_streak, 0)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])

    def test_build_stage_summary_tracks_stage_transitions_and_item_stack_gains(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=100,
                items=("Wrench x1",),
            ),
            SimpleNamespace(
                game_time_seconds=40.0,
                stage_time_seconds=40.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=160,
                items=("Wrench x2", "Beacon x1"),
            ),
            SimpleNamespace(
                game_time_seconds=60.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=200,
                items=("Wrench x2", "Beacon x1"),
            ),
            SimpleNamespace(
                game_time_seconds=90.0,
                stage_time_seconds=31.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=260,
                items=("Wrench x3", "Beacon x1", "Ghost x1"),
            ),
            SimpleNamespace(
                game_time_seconds=120.0,
                stage_time_seconds=45.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=300,
                items=("Wrench x3", "Beacon x1", "Ghost x1"),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=2.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=360,
                items=("Wrench x3", "Beacon x2", "Ghost x1"),
            ),
            SimpleNamespace(
                game_time_seconds=180.0,
                stage_time_seconds=590.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=420,
                items=("Wrench x3", "Beacon x3", "Ghost x2"),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "200")
        self.assertEqual(rows[0]["time"], "01:00")
        self.assertIn("#60A5FA", rows[0]["items"])
        self.assertIn(">1</span>", rows[0]["items"])
        self.assertIn("#22C55E", rows[0]["items"])
        self.assertEqual(rows[1]["kills"], "60")
        self.assertEqual(rows[1]["time"], "00:30")
        self.assertIn("#22C55E", rows[1]["items"])
        self.assertEqual(rows[2]["kills"], "60")
        self.assertEqual(rows[2]["time"], "00:30")
        self.assertIn("#98A7BA", rows[2]["items"])
        self.assertEqual(rows[3]["kills"], "100")
        self.assertEqual(rows[3]["time"], "00:30")
        self.assertIn("#60A5FA", rows[3]["items"])

    def test_build_stage_summary_uses_early_new_stage_snapshot_as_previous_boundary(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=1310.0,
                stage_time_seconds=1310.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=90_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=1320.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=92_100,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=1380.0,
                stage_time_seconds=61.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=101_000,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "92,100")
        self.assertEqual(rows[0]["time"], "22:00")
        self.assertEqual(rows[1]["kills"], "8,900")
        self.assertEqual(rows[1]["time"], "01:00")

    def test_build_stage_summary_time_ignores_stage_timer_boss_skips(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=0.0,
                stage_time_seconds=0.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=0,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=480.0,
                stage_time_seconds=480.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=481.0,
                stage_time_seconds=595.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20_500,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=1320.0,
                stage_time_seconds=1330.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=110_000,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["time"], "22:00")

    def test_build_stage_summary_detects_stage_four_after_wide_reset_gap(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=1_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=80.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=4_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=7_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=220.0,
                stage_time_seconds=220.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=10_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=280.0,
                stage_time_seconds=45.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=12_000,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[2]["kills"], "3,000")
        self.assertEqual(rows[2]["time"], "01:20")
        self.assertEqual(rows[3]["kills"], "2,000")
        self.assertEqual(rows[3]["time"], "00:00")

    def test_build_stage_summary_does_not_treat_early_stage_three_timer_reset_as_stage_four(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=300,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=80.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=900,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=1_500,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=2.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=1_525,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=152.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=1_550,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[2]["kills"], "50")
        self.assertEqual(rows[2]["time"], "00:12")
        self.assertEqual(rows[3]["kills"], "--")

    def test_build_stage_summary_detects_stage_four_when_boss_lives_past_one_minute(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=300,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=80.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=900,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=1_500,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=450.0,
                stage_time_seconds=100.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=2_500,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=472.0,
                stage_time_seconds=590.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=2_564,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[2]["kills"], "1,000")
        self.assertEqual(rows[2]["time"], "05:10")
        self.assertEqual(rows[3]["kills"], "64")
        self.assertEqual(rows[3]["time"], "00:00")

    def test_build_stage_summary_detects_stage_four_when_first_visible_snapshot_is_ghost_phase(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=1_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=80.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=4_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=1.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=7_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=5089.87,
                stage_time_seconds=2121.84,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=583_852,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=5109.79,
                stage_time_seconds=604.39,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=584_478,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[2]["kills"], "0")
        self.assertEqual(rows[2]["time"], "00:00")
        self.assertEqual(rows[3]["kills"], "577,478")
        self.assertEqual(rows[3]["time"], "00:19")

    def test_build_stage_summary_reconciles_last_stage_kills_with_final_total(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=100,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=40.0,
                stage_time_seconds=40.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=160,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=60.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=200,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=90.0,
                stage_time_seconds=31.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=260,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=120.0,
                stage_time_seconds=45.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=300,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=2.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=360,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=180.0,
                stage_time_seconds=590.0,
                stage_ptr=0x3000,
                map_seed=33,
                mob_kills=425,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "200")
        self.assertEqual(rows[1]["kills"], "60")
        self.assertEqual(rows[2]["kills"], "60")
        self.assertEqual(rows[3]["kills"], "105")

    def test_build_stage_summary_stage_one_time_starts_from_run_zero(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=180.0,
                stage_time_seconds=180.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=12_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=1320.0,
                stage_time_seconds=1320.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=110_000,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["time"], "22:00")

    def test_build_stage_summary_stage_one_kills_ignores_missing_initial_kill_reads(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=0.0,
                stage_time_seconds=0.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=None,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=10.0,
                stage_time_seconds=10.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=None,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=12,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=30.0,
                stage_time_seconds=30.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=128,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "128")

    def test_build_stage_summary_later_stage_kills_use_transition_baseline_when_reads_are_missing(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=100.0,
                stage_time_seconds=100.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=10_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=120.0,
                stage_time_seconds=1.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=12_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=130.0,
                stage_time_seconds=11.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=None,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=140.0,
                stage_time_seconds=21.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=None,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=31.0,
                stage_ptr=0x2000,
                map_seed=22,
                mob_kills=18_500,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[1]["kills"], "6,500")

    def test_build_stage_summary_counts_duplicate_item_entries(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=5.0,
                stage_time_seconds=5.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=10,
                items=("Wrench x1", "Cheese x1"),
            ),
            SimpleNamespace(
                game_time_seconds=15.0,
                stage_time_seconds=15.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20,
                items=("Wrench x3", "Cheese x1", "Cheese x1", "Anvil x2"),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertIn("#FACC15", rows[0]["items"])
        self.assertIn("#22C55E", rows[0]["items"])

    def test_build_stage_summary_ignores_single_snapshot_item_drop_recoveries(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=10.0,
                stage_time_seconds=10.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=10,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20,
                items=("Za Warudo x1",),
            ),
            SimpleNamespace(
                game_time_seconds=30.0,
                stage_time_seconds=30.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=30,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=40.0,
                stage_time_seconds=40.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=40,
                items=("Za Warudo x1",),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["items"].count("&#9679;"), 1)
        self.assertIn(">1</span>", rows[0]["items"])

    def test_build_stage_summary_counts_reacquired_items_after_confirmed_consumption(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=10.0,
                stage_time_seconds=10.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=10,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=20.0,
                stage_time_seconds=20.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=20,
                items=("Za Warudo x1",),
            ),
            SimpleNamespace(
                game_time_seconds=30.0,
                stage_time_seconds=30.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=30,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=40.0,
                stage_time_seconds=40.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=40,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=50.0,
                stage_time_seconds=50.0,
                stage_ptr=0x1000,
                map_seed=11,
                mob_kills=50,
                items=("Za Warudo x1",),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertIn(">2</span>", rows[0]["items"])

    def test_build_stage_summary_late_attach_uses_raw_stage_two_row(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=120.0,
                stage_time_seconds=40.0,
                stage_ptr=0x2000,
                map_seed=22,
                stage_index=1,
                mob_kills=1_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=150.0,
                stage_time_seconds=70.0,
                stage_ptr=0x2000,
                map_seed=22,
                stage_index=1,
                mob_kills=1_250,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "250")
        self.assertEqual(rows[1]["time"], "00:30")
        self.assertEqual(rows[2]["kills"], "--")

    def test_build_stage_summary_late_attach_uses_raw_stage_three_row_without_auto_stage_four(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=240.0,
                stage_time_seconds=80.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                mob_kills=2_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=300.0,
                stage_time_seconds=140.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                mob_kills=2_600,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "--")
        self.assertEqual(rows[2]["kills"], "600")
        self.assertEqual(rows[2]["time"], "01:00")
        self.assertEqual(rows[3]["kills"], "--")

    def test_build_stage_summary_attach_on_stage_four_uses_collapsed_chest_total_marker(self) -> None:
        snapshots = [
            SimpleNamespace(
                game_time_seconds=240.0,
                stage_time_seconds=80.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                chests_total=15,
                mob_kills=2_000,
                items=(),
            ),
            SimpleNamespace(
                game_time_seconds=300.0,
                stage_time_seconds=140.0,
                stage_ptr=0x3000,
                map_seed=33,
                stage_index=2,
                chests_total=15,
                mob_kills=2_600,
                items=(),
            ),
        ]

        rows = gui.MegabonkApp.build_stage_summary(snapshots)

        self.assertEqual(rows[0]["kills"], "--")
        self.assertEqual(rows[1]["kills"], "--")
        self.assertEqual(rows[2]["kills"], "--")
        self.assertEqual(rows[3]["kills"], "600")
        self.assertEqual(rows[3]["time"], "01:00")

    def test_item_total_count_includes_stacks_and_duplicate_entries(self) -> None:
        total = gui.MegabonkApp._item_total_count(
            ("Wrench x3", "Anvil x2", "Anvil x1", "Moldy Cheese")
        )

        self.assertEqual(total, 7)

    def test_sort_items_for_display_supports_rarity_modes(self) -> None:
        items = ("Wrench x1", "Anvil x1", "Beacon x1", "Spiky Shield x1", "Key x1")

        self.assertEqual(
            gui.MegabonkApp.sort_items_for_display(items, gui.ITEM_SORT_DEFAULT),
            items,
        )
        self.assertEqual(
            gui.MegabonkApp.sort_items_for_display(items, gui.ITEM_SORT_RARITY_DESC),
            ("Anvil x1", "Spiky Shield x1", "Beacon x1", "Wrench x1", "Key x1"),
        )
        self.assertEqual(
            gui.MegabonkApp.sort_items_for_display(items, gui.ITEM_SORT_RARITY_ASC),
            ("Wrench x1", "Key x1", "Beacon x1", "Spiky Shield x1", "Anvil x1"),
        )

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
        app.overlay_should_refresh_live_stats = lambda: False
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        read_calls: list[str] = []
        app.read_player_stats_only = lambda: read_calls.append("stats") or ({}, 0x1234)

        gui.MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(read_calls, [])
        self.assertEqual(len(app.after_calls), 1)

    def test_update_player_stats_timer_refreshes_hidden_live_stats_when_auto_start_enabled(self) -> None:
        app = self.build_recording_app()
        app._is_shutting_down = False
        app.player_stats_vod_recorder.is_recording = False
        app._is_live_stats_tab_active = lambda: False
        app.after_calls = []
        app.after = lambda delay, callback: app.after_calls.append((delay, callback))
        app._sync_player_stats_recording_run_state = lambda: None
        refresh_calls: list[str] = []
        app.refresh_live_player_stats_now = lambda *args, **kwargs: refresh_calls.append("refresh")

        with patch.object(gui.config, "AUTO_START_RECORDING", True):
            gui.MegabonkApp.update_player_stats_timer(app)

        self.assertEqual(refresh_calls, ["refresh"])
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
        app.player_stats_banishes_label = FakeLabel()
        app.player_stats_live_banishes = ()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app.player_stats_powerups_duration_label = FakeLabel()
        app.player_stats_mob_kills_label = FakeLabel()
        app.player_stats_level_label = FakeLabel()
        app.player_stats_new_items_label = FakeLabel()
        app.player_stats_stage_summary_labels = []
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        app.close_player_stats_client = lambda: None
        app.refresh_player_stats_timeline_ui = lambda *args, **kwargs: None
        app._refresh_vods_list_if_visible = lambda: None
        app._is_live_stats_tab_active = lambda: True
        app.read_player_stats_only = lambda: (
            {
                "Damage": SimpleNamespace(display_value="123", value=1.23),
                "Powerup Multiplier": SimpleNamespace(display_value="1.5x", value=1.5),
            },
            0x1234,
        )

        def fail_items(owner_stats=None):
            raise gui.MemoryReadError("items missing")

        app.read_passive_items_only = fail_items
        app.live_run_tracker = SimpleNamespace(
            update=lambda *args, **kwargs: None,
            update_chests_and_keys=lambda *args, **kwargs: None,
            mark_read_failed=lambda *args, **kwargs: None,
            stage_summary_rows=lambda: [],
            current_ui_kps=lambda: None,
        )
        app.overlay_state_store = None
        result = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_status_label.text(), "Live player stats")
        self.assertEqual(stat_label.text(), "123")
        self.assertEqual(app.player_stats_items_label.text(), "Items unavailable")
        self.assertEqual(app.player_stats_chests_per_minute_label.text(), "Average chests/min: --")
        self.assertEqual(app.player_stats_powerups_duration_label.text(), "Powerups: 22s | Clock: 18s")
        self.assertEqual(app.player_stats_in_game_time_label.text(), "In-Game Time: 00:21")
        self.assertEqual(app.player_stats_mob_kills_label.text(), "Mob Kills: 37")
        self.assertEqual(app.player_stats_level_label.text(), "Level: 2")
        self.assertEqual(app.player_stats_new_items_label.text(), "Live snapshot")
        self.assertEqual(app.player_stats_banishes_label.text(), "No banishes yet")

    def test_chaos_refresh_throttles_expected_chest_reads_to_500ms(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        expected_reads: list[int] = []
        tracked: list[tuple[int, int]] = []
        client = SimpleNamespace(
            resolve_owner_stats=lambda: 0x1234,
            get_expected_chest_inputs=lambda owner_stats: (
                expected_reads.append(owner_stats) or 7,
                3,
            ),
            get_chaos_tracking_state=lambda owner_stats: (None, {}),
        )
        app._get_player_stats_client = lambda: client
        app.live_run_tracker = SimpleNamespace(
            track_expected_key_procs=lambda bought, keys: tracked.append(
                (bought, keys)
            ),
            update_chaos_tome=lambda **kwargs: None,
            track_kills=lambda *args, **kwargs: None,
            current_ui_kps=lambda: None,
        )

        with patch.object(gui.time, "monotonic", side_effect=(100.0, 100.25, 100.5)):
            self.assertTrue(gui.MegabonkApp.refresh_chaos_tome_tracker_now(app))
            self.assertTrue(gui.MegabonkApp.refresh_chaos_tome_tracker_now(app))
            self.assertTrue(gui.MegabonkApp.refresh_chaos_tome_tracker_now(app))

        self.assertEqual(expected_reads, [0x1234, 0x1234])
        self.assertEqual(tracked, [(7, 3), (7, 3)])

    def test_refresh_live_player_stats_now_captures_while_hidden_recording(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        tome = SimpleNamespace(
            name="Damage",
            level=3,
            stat_id=12,
            stat_label="Damage",
            display_value="1.25x",
            tome_id=0,
        )
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (tome,),
            get_live_banishes=lambda: ("Clover", "Golden Tome"),
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
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
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["tomes"], (tome,))
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["banishes"], ("Clover", "Golden Tome"))
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["game_time_seconds"], 21.5)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["mob_kills"], 37)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls[0]["player_level"], 2)
        self.assertEqual(snapshot_calls, [])
        self.assertEqual(timeline_calls, ["timeline"])

    def test_refresh_live_player_stats_now_does_not_capture_while_paused(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        app.read_player_stats_runtime_game_state = lambda: RuntimeGameState(
            mode=RuntimeGameMode.PAUSED_IN_GAME,
            is_playing=True,
            is_paused=True,
        )
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (),
            get_live_banishes=lambda: (),
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        app.read_player_stats_only = lambda: (
            {"Damage": SimpleNamespace(display_value="123", value=1.23)},
            0x1234,
        )
        app.read_passive_items_only = lambda owner_stats=None: ("Wrench x2",)

        result = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls, [])
        self.assertEqual(app.player_stats_vod_snapshots, [])

    def test_refresh_live_player_stats_now_does_not_capture_when_runtime_state_is_unknown(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        app.read_player_stats_runtime_game_state = lambda: (_ for _ in ()).throw(
            gui.MemoryReadError("runtime state unavailable")
        )
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (),
            get_live_banishes=lambda: (),
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        app.read_player_stats_only = lambda: (
            {"Damage": SimpleNamespace(display_value="123", value=1.23)},
            0x1234,
        )
        app.read_passive_items_only = lambda owner_stats=None: ("Wrench x2",)

        result = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_vod_recorder.capture_calls, [])
        self.assertEqual(app.player_stats_vod_snapshots, [])

    def test_refresh_live_player_stats_now_updates_live_view_while_recording(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: True
        tome = SimpleNamespace(
            name="Armor",
            level=2,
            stat_id=4,
            stat_label="Armor",
            display_value="20%",
            tome_id=5,
        )
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (tome,),
            get_live_banishes=lambda: ("Clover", "Golden Tome"),
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
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
        self.assertEqual(display_calls[0]["kwargs"]["tomes"], (tome,))
        self.assertEqual(display_calls[0]["kwargs"]["banishes"], ("Clover", "Golden Tome"))
        self.assertEqual(display_calls[0]["kwargs"]["status_text"], "Live player stats (recording)")

    def test_refresh_live_player_stats_now_auto_starts_recording_after_stable_run_detection(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False, should_capture=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        app.read_player_stats_only = lambda: ({"Damage": SimpleNamespace(display_value="123", value=1.23)}, 0x1234)
        app.read_passive_items_only = lambda owner_stats=None: ()
        app.read_player_stats_recording_state = lambda: SimpleNamespace(map_seed=777, current_stage_ptr=2)
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )

        with patch.object(gui.config, "AUTO_START_RECORDING", True):
            first = gui.MegabonkApp.refresh_live_player_stats_now(app)
            second = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [{"name": None, "seed": 777}])
        self.assertTrue(app.player_stats_vod_recorder.is_recording)
        self.assertEqual(app.player_stats_recording_stage_ptr, 2)
        self.assertEqual(app.player_stats_recording_run_time_seconds, 21.5)
        self.assertIn(("[*] Player stats recording auto-started: recording-1.jsonl", "success"), app.log_messages)

    def test_refresh_live_player_stats_now_does_not_auto_start_without_active_run_signal(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False, should_capture=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        app.read_player_stats_only = lambda: ({}, 0x1234)
        app.read_passive_items_only = lambda owner_stats=None: ()
        app.read_player_stats_recording_state = lambda: SimpleNamespace(map_seed=None, current_stage_ptr=0)
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 0.0,
            get_stage_timer=lambda: None,
            get_killed_mobs=lambda: None,
            get_player_level=lambda owner_stats=None: None,
        )

        with patch.object(gui.config, "AUTO_START_RECORDING", True):
            result = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertFalse(app.player_stats_vod_recorder.is_recording)

    def test_refresh_live_player_stats_now_does_not_auto_start_when_runtime_state_is_unknown(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False, should_capture=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app._is_live_stats_tab_active = lambda: False
        app.read_player_stats_runtime_game_state = lambda: (_ for _ in ()).throw(
            gui.MemoryReadError("runtime state unavailable")
        )
        app.read_player_stats_only = lambda: (
            {"Damage": SimpleNamespace(display_value="123", value=1.23)},
            0x1234,
        )
        app.read_passive_items_only = lambda owner_stats=None: ()
        app.read_player_stats_recording_state = lambda: SimpleNamespace(map_seed=777, current_stage_ptr=2)
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )

        with patch.object(gui.config, "AUTO_START_RECORDING", True):
            result = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(app.player_stats_auto_start_detection_streak, 0)
        self.assertEqual(app.player_stats_vod_recorder.start_calls, [])
        self.assertFalse(app.player_stats_vod_recorder.is_recording)

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

    def test_refresh_live_player_stats_now_preserves_last_known_items_when_read_fails(self) -> None:
        app = self.build_recording_app()
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=True, should_capture=True)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app.player_stats_last_known_items = ("Wrench x2", "Clover x1")
        app._is_live_stats_tab_active = lambda: False
        app.read_player_stats_only = lambda: (
            {"Damage": SimpleNamespace(display_value="123", value=1.23)},
            0x1234,
        )

        def fail_items(owner_stats=None):
            raise gui.MemoryReadError("items missing")

        app.read_passive_items_only = fail_items
        app.read_player_stats_recording_state = lambda: SimpleNamespace(map_seed=777, current_stage_ptr=2)
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_stage_timer=lambda: 9.0,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
            get_live_weapons=lambda owner_stats=None: (),
            get_live_tomes=lambda owner_stats=None: (),
            get_live_banishes=lambda: (),
            get_live_damage_sources=lambda: (),
        )

        result = gui.MegabonkApp.refresh_live_player_stats_now(app)

        self.assertTrue(result)
        self.assertEqual(len(app.player_stats_vod_recorder.capture_calls), 1)
        self.assertEqual(
            app.player_stats_vod_recorder.capture_calls[0]["items"],
            ("Wrench x2", "Clover x1"),
        )

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
        app.player_stats_banishes_label = FakeLabel()
        app.player_stats_live_banishes = ()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app.player_stats_mob_kills_label = FakeLabel()
        app.player_stats_level_label = FakeLabel()
        app.player_stats_new_items_label = FakeLabel()
        app.player_stats_stage_summary_labels = []
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
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
        app.live_run_tracker = SimpleNamespace(
            update=lambda *args, **kwargs: None,
            update_chests_and_keys=lambda *args, **kwargs: None,
            mark_read_failed=lambda *args, **kwargs: None,
            stage_summary_rows=lambda: [],
            current_ui_kps=lambda: None,
        )
        app.overlay_state_store = None
        gui.MegabonkApp._stop_player_stats_recording(app)

        self.assertEqual(app.player_stats_vod_recorder.stop_calls, 1)
        self.assertEqual(app.player_stats_status_label.text(), "Live player stats")
        self.assertEqual(stat_label.text(), "123")
        self.assertEqual(app.player_stats_items_label.text(), "Items unavailable")
        self.assertEqual(app.player_stats_in_game_time_label.text(), "In-Game Time: 00:21")
        self.assertEqual(app.player_stats_mob_kills_label.text(), "Mob Kills: 37")
        self.assertEqual(app.player_stats_level_label.text(), "Level: 2")
        self.assertEqual(app.player_stats_new_items_label.text(), "Live snapshot")

    def test_display_player_stats_snapshot_shows_in_game_time_in_status_and_summary(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.player_stats_vod_snapshots = []
        calls: list[dict[str, object]] = []
        snapshot = SimpleNamespace(
            stats={"Damage": SimpleNamespace(display_value="123", value=1.23)},
            items=("Wrench x2",),
            tomes=(SimpleNamespace(name="Damage", level=3, stat_id=12, stat_label="Damage", display_value="1.25x", tome_id=0),),
            banishes=("Clover", "Golden Tome"),
            chests_per_minute=1.5,
            game_time_seconds=81.75,
            mob_kills=42,
            player_level=4,
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
        self.assertEqual(calls[0]["kwargs"]["mob_kills"], 42)
        self.assertEqual(calls[0]["kwargs"]["player_level"], 4)
        self.assertEqual(calls[0]["kwargs"]["tomes"], snapshot.tomes)
        self.assertEqual(calls[0]["kwargs"]["banishes"], snapshot.banishes)

    def test_display_player_stats_snapshot_uses_compact_segment_compare_text(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        calls: list[dict[str, object]] = []
        previous = SimpleNamespace(
            stats={},
            items=("Wrench x1",),
            game_time_seconds=60.0,
            mob_kills=100,
            player_level=3,
            time_label="01:00",
        )
        current = SimpleNamespace(
            stats={},
            items=("Wrench x3", "Za Warudo x1"),
            tomes=(),
            banishes=(),
            chests_per_minute=None,
            game_time_seconds=90.0,
            mob_kills=133,
            player_level=3,
            time_label="01:30",
        )
        app.player_stats_vod_snapshots = [previous, current]
        app.display_player_stats = lambda stats, items=(), **kwargs: calls.append(
            {"stats": stats, "items": tuple(items), "kwargs": kwargs}
        )

        gui.MegabonkApp.display_player_stats_snapshot(app, current)

        self.assertIn("+3</span>", calls[0]["kwargs"]["new_items_text"])
        self.assertIn("Time:</span> 00:30", calls[0]["kwargs"]["new_items_text"])
        self.assertIn("Kills:</span> +33", calls[0]["kwargs"]["new_items_text"])
        self.assertNotIn("Za Warudo +1", calls[0]["kwargs"]["new_items_text"])

    def test_display_loaded_vod_snapshot_shows_legacy_in_game_fallback(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.vods_status_label = FakeLabel()
        app.vods_slider_time_label = FakeLabel()
        app.vods_items_label = FakeLabel()
        app.vods_in_game_time_label = FakeLabel()
        app.vods_chests_per_minute_label = FakeLabel()
        app.vods_mob_kills_label = FakeLabel()
        app.vods_kps_averages_label = FakeLabel()
        app.vods_level_label = FakeLabel()
        app.vods_new_items_label = FakeLabel()
        app.vods_banishes_label = FakeLabel()
        app.vods_stage_summary_labels = []
        app.vods_rows = {"Damage": FakeLabel()}
        app.display_weapon_cards = lambda *args, **kwargs: None
        app.display_tome_cards = lambda *args, **kwargs: None
        app.loaded_vod_snapshot_index = None
        snapshot = SimpleNamespace(
            stats={"Damage": SimpleNamespace(display_value="123", value=1.23)},
            items=("Wrench x1",),
            tomes=(),
            banishes=(),
            chests_per_minute=1.23,
            game_time_seconds=None,
            mob_kills=None,
            player_level=None,
            time_label="00:00",
        )
        metadata = SimpleNamespace(name="Legacy run")
        app.loaded_vod = SimpleNamespace(metadata=metadata, snapshots=[snapshot])

        gui.MegabonkApp.display_loaded_vod_snapshot(app, 0)

        self.assertEqual(app.vods_status_label.text(), "Legacy run | 1/1 at 00:00 | In-Game Time: --")
        self.assertEqual(app.vods_in_game_time_label.text(), "In-Game Time: --")
        self.assertEqual(app.vods_mob_kills_label.text(), "Mob Kills: --")
        self.assertEqual(app.vods_kps_averages_label.text(), "KPS Avg: 60s -- | 5m --")
        self.assertEqual(app.vods_level_label.text(), "Level: --")
        self.assertEqual(app.vods_new_items_label.text(), "No previous snapshot")
        self.assertEqual(app.vods_banishes_label.text(), "No banishes yet")
        self.assertEqual(app.vods_items_label.text(), "Wrench x1")

    def test_display_loaded_vod_snapshot_updates_damage_sources_tab(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.vods_status_label = FakeLabel()
        app.vods_slider_time_label = FakeLabel()
        app.vods_items_label = FakeLabel()
        app.vods_in_game_time_label = FakeLabel()
        app.vods_chests_per_minute_label = FakeLabel()
        app.vods_mob_kills_label = FakeLabel()
        app.vods_kps_averages_label = FakeLabel()
        app.vods_level_label = FakeLabel()
        app.vods_new_items_label = FakeLabel()
        app.vods_banishes_label = FakeLabel()
        app.vods_stage_summary_labels = []
        app.vods_rows = {}
        app.display_weapon_cards = lambda *args, **kwargs: None
        app.display_tome_cards = lambda *args, **kwargs: None
        damage_calls: list[tuple[tuple[object, ...], str]] = []
        app.display_damage_source_rows = lambda sources, *, scope, status_text=None: damage_calls.append((tuple(sources), scope))
        app._update_items_section = lambda *args, **kwargs: None
        app.resolve_snapshot_chests_per_minute = lambda snapshot: getattr(snapshot, "chests_per_minute", None)
        app._set_stage_summary_labels = lambda *args, **kwargs: None
        app._resolve_vod_compare_base_snapshot = lambda index: None
        app._vod_compare_segment_snapshots = lambda index: ()
        app._refresh_vod_compare_controls = lambda *args, **kwargs: None
        app._refresh_vod_compare_details = lambda *args, **kwargs: None
        app.loaded_vod_compare_start_index = None
        app.vods_compare_details_expanded = False
        snapshot = SimpleNamespace(
            stats={},
            items=(),
            weapons=(),
            tomes=(),
            banishes=(),
            damage_sources=(SimpleNamespace(source_key="Katana", source_name="Katana", damage=1234.0),),
            chests_per_minute=1.23,
            game_time_seconds=60.0,
            mob_kills=10,
            kps_at_capture=150,
            minute_avg_kps_at_capture=243,
            five_minute_avg_kps_at_capture=221,
            run_avg_kps_at_capture=138,
            player_level=2,
            time_label="01:00",
        )
        metadata = SimpleNamespace(name="Run")
        app.loaded_vod = SimpleNamespace(metadata=metadata, snapshots=[snapshot])

        gui.MegabonkApp.display_loaded_vod_snapshot(app, 0)

        self.assertEqual(len(damage_calls), 1)
        self.assertEqual(damage_calls[0][1], "vod")
        self.assertEqual(damage_calls[0][0][0].source_name, "Katana")
        self.assertEqual(app.vods_mob_kills_label.text(), "Mob Kills: 10 (150/s)")
        self.assertEqual(app.vods_kps_averages_label.text(), "KPS Avg: 60s 243/s | 5m 221/s")

    def test_format_in_game_time_truncates_fractional_seconds(self) -> None:
        self.assertEqual(gui.MegabonkApp.format_in_game_time(None), "In-Game Time: --")
        self.assertEqual(gui.MegabonkApp.format_in_game_time(21.52338219), "In-Game Time: 00:21")
        self.assertEqual(gui.MegabonkApp.format_in_game_time(3661.9), "In-Game Time: 01:01:01")

    def test_format_mob_kills_formats_missing_and_positive_values(self) -> None:
        self.assertEqual(gui.MegabonkApp.format_mob_kills(None), "Mob Kills: --")
        self.assertEqual(gui.MegabonkApp.format_mob_kills(42), "Mob Kills: 42")
        self.assertEqual(gui.MegabonkApp.format_mob_kills(1291146), "Mob Kills: 1,291,146")

    def test_format_kps_averages_formats_missing_and_positive_values(self) -> None:
        self.assertEqual(
            gui.MegabonkApp.format_kps_averages(None, None),
            "KPS Avg: 60s -- | 5m --",
        )
        self.assertEqual(
            gui.MegabonkApp.format_kps_averages(243, 221),
            "KPS Avg: 60s 243/s | 5m 221/s",
        )

    def test_format_player_level_formats_missing_and_positive_values(self) -> None:
        self.assertEqual(gui.MegabonkApp.format_player_level(None), "Level: --")
        self.assertEqual(gui.MegabonkApp.format_player_level(4), "Level: 4")

    def test_format_powerups_duration_uses_powerup_multiplier(self) -> None:
        stats = {
            "Powerup Multiplier": SimpleNamespace(value=1.5, display_value="1.5x"),
        }

        self.assertEqual(
            gui.MegabonkApp.format_powerups_duration(stats),
            "Powerups: 22s | Clock: 18s",
        )
        self.assertEqual(gui.MegabonkApp.format_powerups_duration({}), "Powerups: --")

    def test_nearest_snapshot_index_prefers_in_game_time(self) -> None:
        snapshots = (
            SimpleNamespace(game_time_seconds=10.0, elapsed_seconds=100),
            SimpleNamespace(game_time_seconds=40.0, elapsed_seconds=200),
            SimpleNamespace(game_time_seconds=90.0, elapsed_seconds=300),
        )

        self.assertEqual(gui.MegabonkApp._nearest_snapshot_index(snapshots, 43.0), 1)

    def test_format_compare_runs_diff_shows_core_deltas(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x1", "Za Warudo x1"),
            stats={"Damage": SimpleNamespace(value=1.25, display_value="1.25x")},
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=126.0,
            elapsed_seconds=130,
            mob_kills=1500,
            player_level=12,
            items=("Key x3",),
            stats={"Damage": SimpleNamespace(value=1.5, display_value="1.50x")},
        )
        vod_a = SimpleNamespace(metadata=SimpleNamespace(name="Run A"))
        vod_b = SimpleNamespace(metadata=SimpleNamespace(name="Run B"))

        result = gui.MegabonkApp.format_compare_runs_diff(vod_a, snapshot_a, vod_b, snapshot_b)

        self.assertIn("Mode:</span> Run B compared to Run A", result)
        self.assertIn("Time offset:</span> +00:06", result)
        self.assertIn("Kill Difference:</span> +500", result)
        self.assertIn("Level Difference:</span> +2", result)
        self.assertIn("Item Difference:</span> +1", result)
        self.assertIn("Damage:</span> 1.25x -> 1.50x (+0.25)", result)

    def test_format_compare_runs_diff_uses_selected_stat_labels(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={
                "Damage": SimpleNamespace(value=1.25, display_value="1.25x"),
                "Luck": SimpleNamespace(value=0.5, display_value="50%"),
            },
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={
                "Damage": SimpleNamespace(value=1.5, display_value="1.50x"),
                "Luck": SimpleNamespace(value=0.75, display_value="75%"),
            },
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = gui.MegabonkApp.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            stat_labels=("Damage",),
        )

        self.assertIn("Damage:</span>", result)
        self.assertNotIn("Luck:</span>", result)

    def test_format_compare_runs_diff_formats_percent_stat_delta_from_display(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={"Difficulty": SimpleNamespace(value=1.0, display_value="100%")},
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={"Difficulty": SimpleNamespace(value=2.0, display_value="200%")},
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = gui.MegabonkApp.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            stat_labels=("Difficulty",),
        )

        self.assertIn("Difficulty:</span> 100% -> 200% (+100%)", result)

    def test_format_compare_runs_diff_can_include_item_difference_section(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x4", "Giant Fork x1"),
            stats={},
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x1", "Lightning Orb x2", "Beefy Ring x1"),
            stats={},
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = gui.MegabonkApp.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            include_items=True,
            stat_labels=(),
        )

        self.assertIn(">Items</span>", result)
        self.assertIn("B has more:</span>", result)
        self.assertIn("Lightning Orb</span> +2", result)
        self.assertIn("Beefy Ring</span> +1", result)
        self.assertIn("A has more:</span>", result)
        self.assertIn("Giant Fork</span> -1", result)
        self.assertIn("Key</span> -3", result)

    def test_format_compare_runs_diff_can_expand_item_details_by_rarity(self) -> None:
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x4", "Giant Fork x1"),
            stats={},
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=("Key x1", "Lightning Orb x2", "Beefy Ring x1"),
            stats={},
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = gui.MegabonkApp.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            include_items=True,
            item_details_expanded=True,
            stat_labels=(),
        )

        self.assertIn("<table", result)
        self.assertIn(">Name</td>", result)
        self.assertIn(">A</td>", result)
        self.assertIn(">B</td>", result)
        self.assertIn(">Diff</td>", result)
        self.assertIn("Lightning Orb</span>", result)
        self.assertIn("+2</span>", result)
        self.assertIn("Key</span>", result)
        self.assertIn("-3</span>", result)
        self.assertGreaterEqual(result.count("&#9679;"), 3)

    def test_format_compare_runs_diff_can_include_weapon_and_tome_sections(self) -> None:
        weapon_stat_a = SimpleNamespace(label="Damage", display_value="10")
        weapon_stat_b = SimpleNamespace(label="Damage", display_value="20")
        weapon_a = SimpleNamespace(
            name="Sword",
            level=2,
            upgrade_stat_ids=(12,),
            upgraded_stats={12: weapon_stat_a},
        )
        weapon_b = SimpleNamespace(
            name="Sword",
            level=4,
            upgrade_stat_ids=(12,),
            upgraded_stats={12: weapon_stat_b},
        )
        tome_a = SimpleNamespace(name="Damage", level=1, stat_label="Damage", display_value="1.10x")
        tome_b = SimpleNamespace(name="Damage", level=3, stat_label="Damage", display_value="1.30x")
        snapshot_a = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={},
            weapons=(weapon_a,),
            tomes=(tome_a,),
        )
        snapshot_b = SimpleNamespace(
            game_time_seconds=120.0,
            elapsed_seconds=100,
            mob_kills=1000,
            player_level=10,
            items=(),
            stats={},
            weapons=(weapon_b,),
            tomes=(tome_b,),
        )
        vod = SimpleNamespace(metadata=SimpleNamespace(name="Run"))

        result = gui.MegabonkApp.format_compare_runs_diff(
            vod,
            snapshot_a,
            vod,
            snapshot_b,
            include_weapons=True,
            include_tomes=True,
            stat_labels=(),
        )

        self.assertIn(">Weapons</span>", result)
        self.assertIn(">Sword</span>", result)
        self.assertIn(">Damage</td>", result)
        self.assertIn(">A</td>", result)
        self.assertIn(">B</td>", result)
        self.assertIn(">Diff</td>", result)
        self.assertIn(">10</td>", result)
        self.assertIn(">20</td>", result)
        self.assertIn(">+10</span>", result)
        self.assertIn(">Tomes</span>", result)
        self.assertIn("Lv. 1 -> 3", result)
        self.assertIn(">+0.20x</span>", result)

    def test_configured_compare_run_stat_labels_reads_valid_saved_config(self) -> None:
        original_config = deepcopy(gui.config.user_config)
        try:
            gui.config.user_config.clear()
            gui.config.user_config["COMPARE_RUN_STAT_LABELS"] = ["Luck", "Not Real", "Damage"]

            result = gui.MegabonkApp.configured_compare_run_stat_labels()

            self.assertEqual(result, ("Luck", "Damage"))
        finally:
            gui.config.user_config.clear()
            gui.config.user_config.update(original_config)

    def test_configured_compare_run_sections_reads_saved_config(self) -> None:
        original_config = deepcopy(gui.config.user_config)
        try:
            gui.config.user_config.clear()
            gui.config.user_config["COMPARE_RUN_SECTIONS"] = {
                "items": True,
                "stage_summary": True,
                "weapons": False,
                "tomes": True,
                "unknown": True,
            }

            result = gui.MegabonkApp.configured_compare_run_sections()

            self.assertEqual(
                result,
                {
                    "items": True,
                    "stage_summary": True,
                    "weapons": False,
                    "tomes": True,
                    "chaos": False,
                },
            )
        finally:
            gui.config.user_config.clear()
            gui.config.user_config.update(original_config)

    def test_format_compare_runs_stage_summary_diff_uses_selected_snapshot_progress(self) -> None:
        snapshot_a_1 = SimpleNamespace(
            game_time_seconds=30.0,
            mob_kills=10,
            items=("Key x1",),
            stage_ptr=0,
            map_seed=11,
            stage_time_seconds=30.0,
        )
        snapshot_a_2 = SimpleNamespace(
            game_time_seconds=60.0,
            mob_kills=25,
            items=("Key x2",),
            stage_ptr=0,
            map_seed=11,
            stage_time_seconds=60.0,
        )
        snapshot_b_1 = SimpleNamespace(
            game_time_seconds=35.0,
            mob_kills=12,
            items=("Key x1", "Wrench x1"),
            stage_ptr=0,
            map_seed=22,
            stage_time_seconds=35.0,
        )
        snapshot_b_2 = SimpleNamespace(
            game_time_seconds=75.0,
            mob_kills=40,
            items=("Key x3", "Wrench x1"),
            stage_ptr=0,
            map_seed=22,
            stage_time_seconds=75.0,
        )
        vod_a = SimpleNamespace(snapshots=(snapshot_a_1, snapshot_a_2))
        vod_b = SimpleNamespace(snapshots=(snapshot_b_1, snapshot_b_2))

        result = gui.MegabonkApp.format_compare_runs_stage_summary_diff(vod_a, 1, vod_b, 1)

        self.assertIn("Stage 1", result)
        self.assertIn("01:00", result)
        self.assertIn("01:15", result)
        self.assertIn("(+00:15)", result)
        self.assertIn("25", result)
        self.assertIn("40", result)
        self.assertIn("(+15)", result)
        self.assertIn("&rarr;", result)

    def test_save_compare_run_stat_selection_persists_checked_labels(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.compare_runs_stat_checkboxes = {
            "Damage": SimpleNamespace(isChecked=lambda: True),
            "Luck": SimpleNamespace(isChecked=lambda: False),
            "Difficulty": SimpleNamespace(isChecked=lambda: True),
        }

        with patch.object(gui.config, "save_config") as save_config:
            gui.MegabonkApp._save_compare_run_stat_selection(app)

        self.assertEqual(gui.config.user_config["COMPARE_RUN_STAT_LABELS"], ["Damage", "Difficulty"])
        save_config.assert_called_once_with(gui.config.user_config)

    def test_auto_close_compare_runs_chooser_if_ready_closes_after_both_runs_selected(self) -> None:
        refreshed = []
        app = SimpleNamespace(
            compare_runs_chooser_expanded=True,
            compare_runs_guided_selection_active=True,
            compare_run_a_vod=object(),
            compare_run_b_vod=object(),
            set_compare_runs_chooser_expanded=lambda expanded, guided=False: refreshed.append((expanded, guided)),
        )

        gui.MegabonkApp._auto_close_compare_runs_chooser_if_ready(app)

        self.assertEqual(refreshed, [(False, False)])

    def test_auto_close_compare_runs_chooser_if_ready_keeps_open_when_selection_incomplete(self) -> None:
        refreshed = []
        app = SimpleNamespace(
            compare_runs_chooser_expanded=True,
            compare_runs_guided_selection_active=True,
            compare_run_a_vod=object(),
            compare_run_b_vod=None,
            _refresh_compare_runs_chooser=lambda: refreshed.append(True),
        )

        gui.MegabonkApp._auto_close_compare_runs_chooser_if_ready(app)

        self.assertTrue(app.compare_runs_chooser_expanded)
        self.assertEqual(refreshed, [])

    def test_auto_close_compare_runs_chooser_if_ready_keeps_manual_chooser_open(self) -> None:
        refreshed = []
        app = SimpleNamespace(
            compare_runs_chooser_expanded=True,
            compare_runs_guided_selection_active=False,
            compare_run_a_vod=object(),
            compare_run_b_vod=object(),
            set_compare_runs_chooser_expanded=lambda expanded, guided=False: refreshed.append((expanded, guided)),
        )

        gui.MegabonkApp._auto_close_compare_runs_chooser_if_ready(app)

        self.assertEqual(refreshed, [])

    def test_ensure_compare_runs_chooser_for_empty_selection_opens_guided_mode(self) -> None:
        calls = []
        app = SimpleNamespace(
            compare_run_a_vod=None,
            compare_run_b_vod=None,
            compare_runs_chooser_expanded=False,
            _is_compare_runs_tab_active=lambda: True,
            set_compare_runs_chooser_expanded=lambda expanded, guided=False: calls.append((expanded, guided)),
        )

        gui.MegabonkApp.ensure_compare_runs_chooser_for_empty_selection(app)

        self.assertEqual(calls, [(True, True)])

    def test_ensure_compare_runs_chooser_for_empty_selection_skips_when_runs_already_selected(self) -> None:
        calls = []
        app = SimpleNamespace(
            compare_run_a_vod=object(),
            compare_run_b_vod=object(),
            compare_runs_chooser_expanded=False,
            _is_compare_runs_tab_active=lambda: True,
            set_compare_runs_chooser_expanded=lambda expanded, guided=False: calls.append((expanded, guided)),
        )

        gui.MegabonkApp.ensure_compare_runs_chooser_for_empty_selection(app)

        self.assertEqual(calls, [])

    def test_diff_new_items_includes_new_stacks_and_new_names(self) -> None:
        result = gui.MegabonkApp.diff_new_items(
            ("Wrench x1", "Dice x1"),
            ("Wrench x3", "Dice x1", "Holy Book x1"),
        )

        self.assertEqual(result, ("Holy Book x1", "Wrench x2"))

    def test_diff_item_gains_sorts_by_rarity_and_gain(self) -> None:
        result = gui.MegabonkApp.diff_item_gains(
            ("Wrench x1", "Key x1", "Beefy Ring x1"),
            ("Wrench x3", "Key x7", "Beefy Ring x6", "Za Warudo x4", "Golden Shield x1"),
        )

        self.assertEqual(
            result,
            (
                ("Za Warudo", 4),
                ("Beefy Ring", 5),
                ("Golden Shield", 1),
                ("Key", 6),
                ("Wrench", 2),
            ),
        )

    def test_format_item_gains_by_rarity_uses_one_dot_per_rarity_row(self) -> None:
        result = gui.MegabonkApp.format_item_gains_by_rarity(
            (
                ("Za Warudo", 4),
                ("Wizards Hat", 3),
                ("Beefy Ring", 5),
                ("Key", 6),
            )
        )

        self.assertIn("Za Warudo +4</span> |", result)
        self.assertIn("Wizard&#x27;s Hat +3</span>", result)
        self.assertIn("Beefy Ring +5", result)
        self.assertIn("Key +6", result)
        self.assertEqual(result.count("&#9679;"), 3)

    def test_format_snapshot_item_gains_preview_uses_compact_totals(self) -> None:
        base = SimpleNamespace(
            game_time_seconds=120.0,
            mob_kills=100,
            player_level=4,
            items=("Wrench x1",),
        )
        current = SimpleNamespace(
            game_time_seconds=270.0,
            mob_kills=420,
            player_level=9,
            items=("Wrench x3", "Za Warudo x4", "Beefy Ring x5"),
        )

        result = gui.MegabonkApp.format_snapshot_item_gains_preview(base, current)

        self.assertIn("Items:", result)
        self.assertIn("+11</span>", result)
        self.assertIn("Time:</span> 02:30", result)
        self.assertIn("Kills:</span> +320", result)
        self.assertIn("Levels:</span> +5", result)
        self.assertNotIn("Za Warudo +4", result)

    def test_segment_changes_track_broken_za_warudo_and_lost_items(self) -> None:
        snapshots = (
            SimpleNamespace(items=("Wrench x1",)),
            SimpleNamespace(items=("Wrench x1", "Za Warudo x1", "Key x3")),
            SimpleNamespace(items=("Wrench x1", "Key x1")),
        )

        result = gui.MegabonkApp.summarize_item_segment_changes(snapshots)

        self.assertEqual(result["gained"], (("Za Warudo", 1), ("Key", 3)))
        self.assertEqual(result["broken"], (("Za Warudo", 1),))
        self.assertEqual(result["lost"], (("Key", 2),))

    def test_format_snapshot_item_gains_preview_counts_broken_items_as_gained(self) -> None:
        base = SimpleNamespace(
            game_time_seconds=120.0,
            mob_kills=100,
            player_level=4,
            items=("Wrench x1",),
        )
        middle = SimpleNamespace(
            game_time_seconds=180.0,
            mob_kills=150,
            player_level=4,
            items=("Wrench x1", "Za Warudo x1"),
        )
        current = SimpleNamespace(
            game_time_seconds=240.0,
            mob_kills=250,
            player_level=5,
            items=("Wrench x1",),
        )

        result = gui.MegabonkApp.format_snapshot_item_gains_preview(
            base,
            current,
            segment_snapshots=(base, middle, current),
        )

        self.assertIn("+1</span>", result)
        self.assertNotIn("Broken:</span>", result)
        self.assertNotIn("Za Warudo -1", result)

    def test_format_snapshot_item_gains_preview_hides_zero_item_total(self) -> None:
        base = SimpleNamespace(
            game_time_seconds=120.0,
            mob_kills=100,
            player_level=4,
            items=("Wrench x1",),
        )
        current = SimpleNamespace(
            game_time_seconds=150.0,
            mob_kills=110,
            player_level=4,
            items=("Wrench x1",),
        )

        result = gui.MegabonkApp.format_snapshot_item_gains_preview(base, current)

        self.assertIn("Items:</span> <span style=\"color:#98A7BA;\">--</span>", result)
        self.assertNotIn("+0", result)

    def test_format_snapshot_item_changes_details_separates_gained_broken_and_lost(self) -> None:
        base = SimpleNamespace(items=("Wrench x1",))
        middle = SimpleNamespace(items=("Wrench x1", "Za Warudo x1", "Key x3"))
        current = SimpleNamespace(items=("Wrench x1", "Key x1"))

        result = gui.MegabonkApp.format_snapshot_item_changes_details(
            base,
            current,
            segment_snapshots=(base, middle, current),
        )

        self.assertIn("Gained", result)
        self.assertIn("Za Warudo +1", result)
        self.assertIn("Broken", result)
        self.assertIn("Za Warudo -1 broken", result)
        self.assertIn("Lost", result)
        self.assertIn("Key -2", result)

    def test_format_snapshot_compare_summary_includes_segment_deltas(self) -> None:
        base = SimpleNamespace(
            game_time_seconds=120.0,
            mob_kills=100,
            player_level=4,
            items=("Wrench x1",),
        )
        current = SimpleNamespace(
            game_time_seconds=270.0,
            mob_kills=420,
            player_level=9,
            items=("Wrench x3", "Za Warudo x1"),
        )

        result = gui.MegabonkApp.format_snapshot_compare_summary(base, current, base_index=3, current_index=8)

        self.assertEqual(
            result,
            "Snapshot 4 -> 9 | 02:00 -> 04:30 | +320 kills | +5 levels | +3 items",
        )

    def test_format_snapshot_new_items_handles_first_snapshot_and_no_changes(self) -> None:
        snapshot = SimpleNamespace(items=("Wrench x1",))

        self.assertEqual(gui.MegabonkApp.format_snapshot_new_items(None, snapshot), "No previous snapshot")
        self.assertEqual(
            gui.MegabonkApp.format_snapshot_new_items(snapshot, SimpleNamespace(items=("Wrench x1",))),
            "No new items since previous snapshot",
        )

    def test_merge_banish_appearance_order_preserves_existing_sequence_and_appends_new(self) -> None:
        result = gui.MegabonkApp.merge_banish_appearance_order(
            ("Clover", "Golden Tome"),
            ("Golden Tome", "Clover", "Battery"),
        )

        self.assertEqual(result, ("Clover", "Golden Tome", "Battery"))

    def test_format_items_rich_text_colors_name_only(self) -> None:
        result = gui.MegabonkApp.format_items_rich_text(("Wrench x2", "Bonker x1", "Crypt Key x1"))

        self.assertIn('color: #22C55E', result)
        self.assertIn('>Wrench</span> x2', result)
        self.assertIn('color: #FACC15', result)
        self.assertIn('>Big Bonk</span> x1', result)
        self.assertIn('Crypt key x1', result)
        self.assertNotIn('color: #22C55E;">Wrench x2</span>', result)

    def test_format_items_rich_text_supports_gloves_aliases(self) -> None:
        result = gui.MegabonkApp.format_items_rich_text(("Gloves Blood x1", "Gloves Power x1"))

        self.assertIn('>Slurp Gloves</span> x1', result)
        self.assertIn('color: #E879F9', result)
        self.assertIn('>Power Gloves</span> x1', result)
        self.assertIn('color: #FACC15', result)

    def test_format_items_rich_text_supports_flappy_feathers_alias(self) -> None:
        result = gui.MegabonkApp.format_items_rich_text(("Flappy Feathers x1",))

        self.assertIn('>Feathers</span> x1', result)
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

        self.assertIn('>Borgar</span> x1', result)
        self.assertIn('color: #22C55E', result)
        self.assertIn(">Bob&#x27;s Light</span> x1", result)
        self.assertIn(">Grandma&#x27;s Secret Tonic</span> x1", result)
        self.assertIn(">Cursed Grabbies</span> x1", result)
        self.assertIn('color: #E879F9', result)
        self.assertIn(">The One Ring</span> x1", result)
        self.assertIn("color: #F97316", result)
        self.assertIn('>Pot (stainless steel)</span> x1', result)
        self.assertIn(">Sucky Magnet</span> x1", result)
        self.assertIn('color: #FACC15', result)

    def test_normalize_item_name_for_rarity_handles_aliases_and_gloves_rule(self) -> None:
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Flappy Feathers"), "Feathers")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Gloves Power"), "Glove Power")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Borgor"), "Borgar")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Bob Lantern"), "Bobs Lantern")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Bob's Lantern"), "Bobs Lantern")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Gloves Cursed"), "Glove Curse")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("No Implementation"), "Golden Ring")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("The One Ring"), "Golden Ring")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Pot Steel"), "Pot")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Sucky Hoof"), "Sucky Magnet")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_rarity("Wrench"), "Wrench")

    def test_tracked_item_display_name_prefers_live_inventory_aliases(self) -> None:
        self.assertEqual(gui.OverlayMixin._tracked_item_display_name("Glove Power"), "Power Gloves")
        self.assertEqual(gui.OverlayMixin._tracked_item_display_name("Glove Blood"), "Slurp Gloves")
        self.assertEqual(gui.OverlayMixin._tracked_item_display_name("Glove Lightning"), "Thunder Mitts")
        self.assertEqual(gui.OverlayMixin._tracked_item_display_name("Pot"), "Pot (stainless steel)")
        self.assertEqual(gui.OverlayMixin._tracked_item_display_name("Wrench"), "Wrench")

    def test_overlay_available_item_names_use_game_ui_names(self) -> None:
        names = gui.OverlayMixin._overlay_available_item_names()

        self.assertIn("Bob's Light", names)
        self.assertIn("Crypt key", names)
        self.assertIn("Golden key", names)
        self.assertIn("Slurp Gloves", names)
        self.assertIn("The One Ring", names)
        self.assertNotIn("Bobs Lantern", names)

    def test_overlay_settings_persist_auto_start_checkbox(self) -> None:
        app = types.SimpleNamespace(
            overlay_port_entry=FakeEntry("17845"),
            overlay_auto_start_cb=FakeCheckbox(True),
            overlay_widget_checkboxes={},
            overlay_stats_checkboxes=None,
            overlay_stage_summary_bg_checkbox=None,
            overlay_banishes_bg_checkbox=None,
            overlay_tracked_rules_list=None,
            overlay_server=types.SimpleNamespace(is_running=False),
            live_run_tracker=MagicMock(),
            _overlay_widget_config_by_id=lambda: {},
            _combined_tracked_item_rules=lambda: [],
            update_overlay_state_from_tracker=MagicMock(),
            refresh_overlay_ui=MagicMock(),
        )
        overlay = deepcopy(gui.config.DEFAULT_OVERLAY)

        with patch.object(gui.config, "OVERLAY", overlay), \
             patch.object(gui.config, "user_config", {}), \
             patch.object(gui.config, "save_config") as save_config:
            gui.OverlayMixin.save_overlay_settings_from_ui(app)

            self.assertTrue(gui.config.OVERLAY["auto_start"])
            self.assertTrue(gui.config.user_config["OVERLAY"]["auto_start"])
            save_config.assert_called_once_with(gui.config.user_config)

    def test_overlay_autostart_uses_auto_start_setting(self) -> None:
        app = types.SimpleNamespace(
            start_overlay_server=MagicMock(),
            update_overlay_state_from_tracker=MagicMock(),
        )

        with patch.object(gui.config, "OVERLAY", {"enabled": True, "auto_start": False}):
            gui.OverlayMixin.apply_overlay_autostart(app)
        app.start_overlay_server.assert_not_called()

        with patch.object(gui.config, "OVERLAY", {"enabled": False, "auto_start": True}):
            gui.OverlayMixin.apply_overlay_autostart(app)
        app.start_overlay_server.assert_called_once_with()
        self.assertEqual(app.update_overlay_state_from_tracker.call_count, 2)

    def test_tracked_rule_display_label_prefers_live_alias_for_default_labels(self) -> None:
        self.assertEqual(
            gui.OverlayMixin._tracked_rule_display_label(
                {"label": "Glove Power Map 1"},
                ["Glove Power"],
                "map_1_only",
            ),
            "Power Gloves Map 1",
        )
        self.assertEqual(
            gui.OverlayMixin._tracked_rule_display_label(
                {"label": "Glove Blood"},
                ["Glove Blood"],
                "all_run",
            ),
            "Slurp Gloves",
        )
        self.assertEqual(
            gui.OverlayMixin._tracked_rule_display_label(
                {"label": "Custom Gloves Label"},
                ["Glove Power"],
                "all_run",
            ),
            "Custom Gloves Label",
        )

    def test_normalize_item_name_for_display_replaces_no_implementation(self) -> None:
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_display("No Implementation"), "The One Ring")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_display("Golden Ring"), "The One Ring")
        self.assertEqual(gui.MegabonkApp._normalize_item_name_for_display("Sucky Hoof"), "Sucky Magnet")

    def test_split_item_stack_suffix_handles_plain_names(self) -> None:
        self.assertEqual(gui.MegabonkApp._split_item_stack_suffix("Wrench x2"), ("Wrench", " x2"))
        self.assertEqual(gui.MegabonkApp._split_item_stack_suffix("Ghost"), ("Ghost", ""))

    def test_on_closing_stops_supported_runtime_resources(self) -> None:
        destroyed: list[bool] = []
        closed: list[str] = []
        app = object.__new__(gui.MegabonkApp)
        app.client = None
        app.stop_event = gui.threading.Event()
        app.scan_event = gui.threading.Event()
        app.log = lambda _message, tag=None: None
        app.destroy = lambda: destroyed.append(True)
        app._is_shutting_down = False
        app._cancel_right_tab_transition = lambda: closed.append("transition")
        app.close_client = lambda: closed.append("client")
        app.close_player_stats_client = lambda: closed.append("player_stats")
        app.close_player_stats_game_data_client = lambda: closed.append("player_stats_game_data")
        app.close_overlay_server = lambda: closed.append("overlay")
        app.stop_twitch_bot = lambda: closed.append("twitch")
        app.twitch_auth_thread = None
        app.player_stats_vod_recorder = None
        app._hotkey_manager = None

        with patch.object(gui, "keyboard", None):
            gui.MegabonkApp.on_closing(app)

        self.assertTrue(app.stop_event.is_set())
        self.assertTrue(app.scan_event.is_set())
        self.assertEqual(destroyed, [True])
        self.assertEqual(
            closed,
            ["transition", "client", "player_stats", "player_stats_game_data", "overlay", "twitch"],
        )
    def test_refresh_live_player_stats_now_parses_single_key(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.player_stats_vod_recorder = FakeRecordingRecorder(is_recording=False)
        app.player_stats_vod_snapshots = []
        app.player_stats_selected_snapshot_index = None
        app.player_stats_status_label = FakeLabel()
        app.player_stats_rows = {}
        app.player_stats_items_label = FakeLabel()
        app.player_stats_banishes_label = FakeLabel()
        app.player_stats_live_banishes = ()
        app.player_stats_in_game_time_label = FakeLabel()
        app.player_stats_chests_per_minute_label = FakeLabel()
        app.player_stats_mob_kills_label = FakeLabel()
        app.player_stats_level_label = FakeLabel()
        app.player_stats_new_items_label = FakeLabel()
        app.player_stats_stage_summary_labels = []
        app._get_player_stats_client = lambda: SimpleNamespace(
            get_run_timer=lambda: 21.5,
            get_killed_mobs=lambda: 37,
            get_player_level=lambda owner_stats=None: 2,
        )
        app.close_player_stats_client = lambda: None
        app.close_player_stats_game_data_client = lambda: None
        app.refresh_player_stats_timeline_ui = lambda *args, **kwargs: None
        app._refresh_vods_list_if_visible = lambda: None
        app._is_live_stats_tab_active = lambda: False
        app.overlay_should_refresh_live_stats = lambda: False
        app._is_twitch_bot_active = lambda: False
        app.read_player_stats_only = lambda: ({}, 0x1234)
        app.read_passive_items_only = lambda owner_stats=None: ("Key",)
        app.read_player_stats_recording_state = lambda: SimpleNamespace(
            map_seed=None,
            current_stage_ptr=0,
        )
        app._read_player_stats_runtime_game_state_safe = lambda: None
        app._maybe_auto_start_player_stats_recording = lambda **kwargs: None
        app.mark_overlay_read_failed = lambda *args, **kwargs: None
        app.update_overlay_state_from_tracker = lambda: None
        app.refresh_session_tracked_item_stats_ui = lambda: None

        chests_and_keys_args = []
        app.live_run_tracker = SimpleNamespace(
            update=lambda *args, **kwargs: None,
            get_chests_and_keys=lambda: (12, 50, 3, 1, {1: 12}, {1: 50}),
            update_chests_and_keys=lambda chests, total, keys: chests_and_keys_args.append((chests, total, keys)),
            mark_read_failed=lambda *args, **kwargs: None,
            stage_summary_rows=lambda: [],
            current_ui_kps=lambda: None,
        )

        def fail_map_stats():
            raise RuntimeError("temporary map stats failure")

        app.player_stats_game_data_client = SimpleNamespace(
            get_map_stats=fail_map_stats
        )
        app.overlay_state_store = None

        result = gui.MegabonkApp.refresh_live_player_stats_now(app)
        self.assertTrue(result)
        self.assertEqual(chests_and_keys_args, [(12, 50, 1)])

    def test_session_tracked_items_stats_tab_includes_seed_percent(self) -> None:
        app = object.__new__(gui.MegabonkApp)
        app.template_stats = {
            "template_a": {"history": [1, 2]},
            "template_b": {"history": [3, 4]},
        }
        app.live_run_tracker = SimpleNamespace(
            tracked_item_rows_for_rules=lambda _rules: [
                {
                    "id": "kevin_plug",
                    "label": "Kevin + Electric Plug",
                    "count": 2,
                    "mode": "map_1_only",
                }
            ]
        )

        text = gui.MegabonkApp.format_session_tracked_items_for_stats_tab(app)

        self.assertEqual(text, "Kevin + Electric Plug T1: 2 (50.00%)")


if __name__ == "__main__":
    unittest.main()
