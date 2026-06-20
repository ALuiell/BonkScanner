import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

mock_pyside = MagicMock()
mock_pyside.QtCore.QThread = MagicMock
mock_pyside.QtCore.Signal = MagicMock
sys.modules['PySide6'] = mock_pyside
sys.modules['PySide6.QtCore'] = mock_pyside.QtCore

from twitch_bot import TwitchBotWorker
from player_stats import DisabledItemsReadResult, DisabledItemsReadStatus

class TestTwitchBotWorker(unittest.TestCase):
    def setUp(self):
        self.run_tracker = MagicMock()
        self.bot = TwitchBotWorker(self.run_tracker)

    def test_byte_truncation(self):
        self.bot.sock = MagicMock()
        self.bot.log_message = MagicMock()

        long_str = "a" * 1000
        self.bot._send_chat("test_channel", long_str)

        self.bot.sock.send.assert_called_once()
        args = self.bot.sock.send.call_args[0][0]
        self.assertTrue(len(args) <= 512)
        self.assertTrue(args.endswith(b"\r\n"))

    def test_access_tier_mods_vips(self):
        from config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        TWITCH_BOT["access_tier"] = "Mods & VIPs"
        self.assertTrue(self.bot._check_access("badges=moderator/1,subscriber/0"))
        self.assertTrue(self.bot._check_access("badges=vip/1"))
        self.assertFalse(self.bot._check_access("badges=subscriber/1"))
        self.assertTrue(self.bot._check_access("badges=broadcaster/1"))
        TWITCH_BOT["access_tier"] = old_tier

    def test_access_tier_subs_mods(self):
        from config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        TWITCH_BOT["access_tier"] = "Subs & Mods"
        self.assertTrue(self.bot._check_access("badges=moderator/1"))
        self.assertTrue(self.bot._check_access("badges=subscriber/1,vip/0"))
        self.assertFalse(self.bot._check_access("badges=vip/1"))
        self.assertTrue(self.bot._check_access("badges=broadcaster/1"))
        TWITCH_BOT["access_tier"] = old_tier

    def test_cooldown_per_command(self):
        from config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        old_global_cooldown = TWITCH_BOT.get("global_cooldown_seconds")
        old_cooldown = TWITCH_BOT.get("cooldown_seconds")
        old_commands = TWITCH_BOT.get("commands", {})

        TWITCH_BOT["access_tier"] = "Everyone"
        TWITCH_BOT["global_cooldown_seconds"] = 2
        TWITCH_BOT["cooldown_seconds"] = 5
        TWITCH_BOT["commands"] = {"stats": True, "bans": True}

        with patch('time.time', return_value=100.0):
            self.bot.last_command_times = {}
            self.bot._handle_stats = MagicMock()
            line = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!stats"
            self.bot._handle_line(line, "channel")
            self.bot._handle_stats.assert_called_once()
            self.assertEqual(self.bot.last_command_times["!stats"], 100.0)
            self.assertEqual(self.bot.last_global_command_time, 100.0)

            # Spamming the exact same command instantly -> blocked by global and per-command cooldown
            self.bot._handle_stats.reset_mock()
            self.bot._handle_line(line, "channel")
            self.bot._handle_stats.assert_not_called()

            # Sending a DIFFERENT command after 1 second -> blocked by configured global cooldown
            with patch('time.time', return_value=101.0):
                self.bot._handle_bans = MagicMock()
                line_bans = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!bans"
                self.bot._handle_line(line_bans, "channel")
                self.bot._handle_bans.assert_not_called()

            # Sending a DIFFERENT command after 3 seconds -> passes global, passes its own cooldown
            with patch('time.time', return_value=103.0):
                self.bot._handle_line(line_bans, "channel")
                self.bot._handle_bans.assert_called_once()

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

    def test_opt_in_commands_stay_disabled_when_missing_from_partial_config(self):
        import config

        with patch.dict(config.TWITCH_BOT, {"commands": {"stats": True}}):
            enabled_commands = self.bot._enabled_command_names()
            self.assertIn("!stats", enabled_commands)
            self.assertNotIn("!chests", enabled_commands)
            self.assertNotIn("!presets", enabled_commands)
            self.assertIn("!bonkhelp", enabled_commands)
            self.assertNotIn("!disabled", enabled_commands)

            self.bot._handle_chests = MagicMock()
            self.bot._handle_presets = MagicMock()
            self.bot._handle_commands = MagicMock()
            for command in ("!chests", "!presets", "!bonkhelp"):
                line = f"@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :{command}"
                with patch("time.time", return_value=100.0):
                    self.bot._handle_line(line, "channel")

            self.bot._handle_chests.assert_not_called()
            self.bot._handle_presets.assert_not_called()
            self.bot._handle_commands.assert_called_once_with("channel")

    def test_safe_formatter_missing_keys(self):
        from twitch_bot import SafeFormatter
        fmt = SafeFormatter()
        res = fmt.format("Hello {name}, your age is {age}", name="John")
        self.assertEqual(res, "Hello John, your age is --")

    def test_safe_formatter_invalid_format_spec(self):
        from config import TWITCH_BOT
        old_templates = TWITCH_BOT.get("templates")

        # stats has an invalid format spec or missing key that fails to format with invalid specs
        TWITCH_BOT["templates"] = {"stats": "Live Stats: {Damage:invalid_spec}"}
        res = self.bot._format_template("stats", "Default Stats: {Damage}", Damage="100")
        self.assertEqual(res, "Default Stats: 100")

        TWITCH_BOT["templates"] = old_templates

    def test_handle_session_uses_session_stats_provider(self):
        provider = SimpleNamespace(format_twitch_session_summary=lambda: "328 resets, 17 seeds found (5.18%)")
        bot = TwitchBotWorker(self.run_tracker, session_stats_provider=provider)
        bot._send_chat = MagicMock()

        bot._handle_session("channel")

        bot._send_chat.assert_called_once_with("channel", "328 resets, 17 seeds found (5.18%)")

    def test_handle_session_without_provider(self):
        self.bot._send_chat = MagicMock()

        self.bot._handle_session("channel")

        self.bot._send_chat.assert_called_once_with("channel", "Session stats are not available yet.")

    def test_twitch_tracked_items_source_defaults_to_custom(self):
        from config import normalize_twitch_bot_config

        bot_cfg = normalize_twitch_bot_config(
            {
                "tracked_items": [
                    {
                        "id": "twitch_custom",
                        "label": "Twitch Custom",
                        "item_names": ["Anvil"],
                        "mode": "all_run",
                    }
                ]
            }
        )

        self.assertEqual(bot_cfg["tracked_items_source"], "custom")
        self.assertEqual(bot_cfg["tracked_items"][0]["id"], "twitch_custom")

    def test_handle_powerups_uses_powerup_multiplier(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.latest_snapshot.return_value = SimpleNamespace(
            stats={
                "Powerup Multiplier": SimpleNamespace(value=1.5, display_value="1.5x")
            }
        )

        self.bot._handle_powerups("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "Powerups: none active | Durations: standard 22.5s, clock 18s (PM 1.5x)"
        )

    def test_handle_powerups_uses_tracker_snapshot_when_available(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.latest_snapshot.return_value = SimpleNamespace(stats={})
        self.run_tracker.powerups_snapshot.return_value = SimpleNamespace(
            available=True,
            powerup_multiplier_display="5.43x",
            standard_duration_seconds=81.435,
            clock_duration_seconds=65.148,
        )
        self.run_tracker.powerups_summary_text.return_value = (
            "Rage 01:33 -> 00:11 (80s left)"
        )

        self.bot._handle_powerups("channel")

        self.run_tracker.powerups_summary_text.assert_called_once_with(
            include_left_word=True
        )
        self.bot._send_chat.assert_called_once_with(
            "channel",
            "Powerups: Rage 01:33 -> 00:11 (80s left) (PM 5.43x)",
        )

    def test_handle_chaos_uses_tracker_totals(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.chaos_tome_level.return_value = 5
        self.run_tracker.chaos_tome_summary_parts.return_value = ["DMG +16.8%", "Luck +14%"]

        self.bot._handle_chaos("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "Chaos Tome Lv5: DMG +17% | Luck +14%",
        )

    def test_handle_chaos_rounds_flat_values_to_whole_numbers(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.chaos_tome_level.return_value = 547
        self.run_tracker.chaos_tome_summary_parts.return_value = ["HP +1062.6", "Pickup +16.4"]

        self.bot._handle_chaos("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "Chaos Tome Lv547: HP +1063 | Pickup +16.4",
        )

    def test_handle_chaos_keeps_pickup_meter_value(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.chaos_tome_level.return_value = 99
        self.run_tracker.chaos_tome_summary_parts.return_value = ["Pickup +24.5"]

        self.bot._handle_chaos("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "Chaos Tome Lv99: Pickup +24.5",
        )

    def test_powerups_command_routes_through_chat_handler(self):
        from config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        old_global_cooldown = TWITCH_BOT.get("global_cooldown_seconds")
        old_cooldown = TWITCH_BOT.get("cooldown_seconds")
        old_commands = TWITCH_BOT.get("commands", {})

        TWITCH_BOT["access_tier"] = "Everyone"
        TWITCH_BOT["global_cooldown_seconds"] = 0
        TWITCH_BOT["cooldown_seconds"] = 0
        TWITCH_BOT["commands"] = {"powerups": True}

        self.bot._handle_powerups = MagicMock()
        line = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!powerups"
        with patch('time.time', return_value=100.0):
            self.bot._handle_line(line, "channel")

        self.bot._handle_powerups.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!powerups"], 100.0)

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

    def test_target_channel_defaults_to_authorized_username(self):
        cfg = {"username": "BotAccount", "target_channel": ""}
        self.assertEqual(TwitchBotWorker._target_channel(cfg), "botaccount")

    def test_target_channel_can_differ_from_authorized_username(self):
        cfg = {"username": "BotAccount", "target_channel": "#StreamerChannel"}
        self.assertEqual(TwitchBotWorker._target_channel(cfg), "streamerchannel")

    def test_handle_chests(self):
        from config import TWITCH_BOT
        from live_run_tracker import ChestStatsSnapshot

        TWITCH_BOT.setdefault("templates", {})["chests"] = (
            "Chests: {stages} | Total: {opened}/{total} | Paid: {paid} | "
            "Key Procs: {procs}/{normal} ({proc_rate}) | Expected: {expected} | Free Chests: {free} | "
            "Keys: {keys} ({chance})"
        )
        self.bot._send_chat = MagicMock()
        self.run_tracker.has_active_run.return_value = True
        self.run_tracker.latest_snapshot.return_value = SimpleNamespace(stats={})
    
        # Test with 1 key
        self.run_tracker.get_chest_stats.return_value = ChestStatsSnapshot(
            5, 46, 1, 3, 1, 1, {1: 5}, {1: 46}, True, 0.4, 4, True
        )
        self.bot._handle_chests("channel")
        self.bot._send_chat.assert_called_with(
            "channel", "Chests: T1:5/46 | Total: 5/46 | Paid: 3 | Key Procs: 1/4 (25.0%) | Expected: 0.4 | Free Chests: 1 | Keys: 1 (9.1%)"
        )
        
        # Test with 10 keys (and multiple maps)
        self.run_tracker.get_chest_stats.return_value = ChestStatsSnapshot(
            10, 46, 10, 30, 15, 5, {1: 40, 2: 10}, {1: 46, 2: 46}, True, 21.75, 45, True
        )
        self.bot._handle_chests("channel")
        self.bot._send_chat.assert_called_with(
            "channel", "Chests: T1:40/46 T2:10/46 | Total: 50/92 | Paid: 30 | Key Procs: 15/45 (33.3%) | Expected: 21.8 | Free Chests: 5 | Keys: 10 (50.0%)"
        )
        
        # Test with multiple maps, where one map has 0 opened chests (e.g. immediately after transition)
        self.run_tracker.get_chest_stats.return_value = ChestStatsSnapshot(
            0, 46, 10, 20, 18, 2, {1: 40, 2: 0}, {1: 46, 2: 46}, True, 19.0, 38, True
        )
        self.bot._handle_chests("channel")
        self.bot._send_chat.assert_called_with(
            "channel", "Chests: T1:40/46 T2:0/46 | Total: 40/92 | Paid: 20 | Key Procs: 18/38 (47.4%) | Expected: 19.0 | Free Chests: 2 | Keys: 10 (50.0%)"
        )
        
        # Test with 0 keys
        self.run_tracker.get_chest_stats.return_value = ChestStatsSnapshot(
            20, 46, 0, 18, 0, 2, {1: 20}, {1: 46}, True
        )
        self.bot._handle_chests("channel")
        self.bot._send_chat.assert_called_with(
            "channel", "Chests: T1:20/46 | Total: 20/46 | Paid: 18 | Key Procs: 0/18 (0.0%) | Expected: -- | Free Chests: 2 | Keys: 0 (0.0%)"
        )


    def test_handle_chests_without_active_run(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.has_active_run.return_value = False
        self.run_tracker.latest_snapshot.return_value = None

        self.bot._handle_chests("channel")

        self.bot._send_chat.assert_called_once_with("channel", "No active run detected.")
        self.run_tracker.get_chests_and_keys.assert_not_called()

    def test_chests_command_routes_through_chat_handler(self):
        from config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        old_global_cooldown = TWITCH_BOT.get("global_cooldown_seconds")
        old_cooldown = TWITCH_BOT.get("cooldown_seconds")
        old_commands = TWITCH_BOT.get("commands", {})

        TWITCH_BOT["access_tier"] = "Everyone"
        TWITCH_BOT["global_cooldown_seconds"] = 0
        TWITCH_BOT["cooldown_seconds"] = 0
        TWITCH_BOT["commands"] = {"chests": True}

        self.bot._handle_chests = MagicMock()
        line = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!chests"
        with patch('time.time', return_value=100.0):
            self.bot._handle_line(line, "channel")

        self.bot._handle_chests.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!chests"], 100.0)

        # Test alias !chest
        self.bot._handle_chests.reset_mock()
        line_alias = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!chest"
        with patch('time.time', return_value=101.0):
            self.bot._handle_line(line_alias, "channel")

        self.bot._handle_chests.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!chest"], 101.0)

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

    def test_handle_presets_templates_mode(self):
        from unittest.mock import patch
        import config
        self.bot._send_chat = MagicMock()
        
        with patch.object(config, 'EVALUATION_MODE', 'templates'), \
             patch.object(config, 'ACTIVE_TEMPLATES', ['LIGHT', 'MERCHANT']), \
             patch.object(config, 'TEMPLATES', [
                 {"id": 1, "name": "LIGHT", "color": "WHITE", "desc": "", "sm_total": 7, "micro": 2, "boss": 2},
                 {"id": 2, "name": "MERCHANT", "color": "CYAN", "desc": "", "sm_total": 10, "shady": 3, "moai": 7, "micro": 1, "boss": 2}
             ]):
            self.bot._handle_presets("channel")
            self.bot._send_chat.assert_called_once_with(
                "channel",
                "[Reroller] Mode: Templates | Active: LIGHT(S+M:7, Mic:2, B:2), MERCHANT(S:3, M:7, Mic:1, B:2)"
            )

    def test_handle_presets_scores_mode(self):
        from unittest.mock import patch
        import config
        self.bot._send_chat = MagicMock()
        
        scores_system_mock = {
            "active_tiers": ["Light", "Perfect"],
            "thresholds": {"Light": 14.0, "Perfect": 25.0},
            "weights": {"moais": 3.0, "shady": 2.0, "boss": 1.0, "magnet": 0.5}
        }
        
        with patch.object(config, 'EVALUATION_MODE', 'scores'), \
             patch.object(config, 'SCORES_SYSTEM', scores_system_mock):
            self.bot._handle_presets("channel")
            self.bot._send_chat.assert_called_once_with(
                "channel",
                "[Reroller] Mode: Scores | Active Tiers: Light (14.0+), Perfect (25.0+) | Weights: Moais=3.0, Shady=2.0, Boss=1.0, Magnet=0.5"
            )

    def test_presets_command_routes_through_chat_handler(self):
        from config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        old_global_cooldown = TWITCH_BOT.get("global_cooldown_seconds")
        old_cooldown = TWITCH_BOT.get("cooldown_seconds")
        old_commands = TWITCH_BOT.get("commands", {})

        TWITCH_BOT["access_tier"] = "Everyone"
        TWITCH_BOT["global_cooldown_seconds"] = 0
        TWITCH_BOT["cooldown_seconds"] = 0
        TWITCH_BOT["commands"] = {"presets": True}

        self.bot._handle_presets = MagicMock()
        line = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!presets"
        with patch('time.time', return_value=100.0):
            self.bot._handle_line(line, "channel")

        self.bot._handle_presets.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!presets"], 100.0)

        # Test alias !preset
        self.bot._handle_presets.reset_mock()
        line_alias = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!preset"
        with patch('time.time', return_value=101.0):
            self.bot._handle_line(line_alias, "channel")

        self.bot._handle_presets.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!preset"], 101.0)

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

    def test_handle_commands_lists_enabled_only(self):
        from unittest.mock import patch
        import config
        self.bot._send_chat = MagicMock()

        mock_commands_cfg = {
            "stats": True,
            "session": True,
            "bans": False,
            "items": True,
            "weapons": False,
            "tomes": True,
            "chaos": False,
            "stages": True,
            "powerups": False,
            "scanner": True,
            "chests": False,
            "presets": True,
            "bonkhelp": True,
            "disabled": False
        }
        with patch.dict(config.TWITCH_BOT, {"commands": mock_commands_cfg}):
            self.bot._handle_commands("channel")
            self.bot._send_chat.assert_called_once_with(
                "channel",
                "Available commands: !stats, !session, !items, !tomes, !stages, !scanner, !presets, !bonkhelp"
            )

    def test_handle_commands_uses_configured_template(self):
        import config

        self.bot._send_chat = MagicMock()
        mock_commands_cfg = {key: False for key in config.DEFAULT_TWITCH_BOT["commands"]}
        mock_commands_cfg["stats"] = True
        mock_commands_cfg["bonkhelp"] = True
        with patch.dict(
            config.TWITCH_BOT,
            {
                "commands": mock_commands_cfg,
                "templates": {"bonkhelp": "Commands -> {commands_list}"},
            },
        ):
            self.bot._handle_commands("channel")

        self.bot._send_chat.assert_called_once_with("channel", "Commands -> !stats, !bonkhelp")

    def test_twitch_template_defaults_include_configurable_commands_and_session(self):
        import config

        bot_cfg = config.normalize_twitch_bot_config({"templates": {}})

        self.assertIn("bonkhelp", bot_cfg["templates"])
        self.assertIn("session", bot_cfg["templates"])

    def test_legacy_commands_key_migrates_to_bonkhelp(self):
        import config

        bot_cfg = config.normalize_twitch_bot_config(
            {
                "commands": {"commands": True},
                "templates": {"commands": "Commands -> {commands_list}"},
            }
        )

        self.assertTrue(bot_cfg["commands"]["bonkhelp"])
        self.assertNotIn("commands", bot_cfg["commands"])
        self.assertEqual(bot_cfg["templates"]["bonkhelp"], "Commands -> {commands_list}")
        self.assertNotIn("commands", bot_cfg["templates"])

    def test_legacy_powerups_template_migrates_to_live_format(self):
        import config

        bot_cfg = config.normalize_twitch_bot_config(
            {
                "templates": {
                    "powerups": "Powerups: Rage/Shield/Coin/Speed {standard_duration}s | Clock {clock_duration}s (PM {pm})",
                },
            }
        )

        self.assertEqual(
            bot_cfg["templates"]["powerups"],
            "Powerups: {powerups} (PM {pm})",
        )

    def test_commands_announcement_uses_configured_interval(self):
        import config

        self.bot._handle_commands = MagicMock()
        with patch.dict(
            config.TWITCH_BOT,
            {
                "commands_announcements": True,
                "commands_announcement_interval_minutes": 30,
            },
        ):
            self.bot._check_commands_announcement("channel", now=100.0)
            self.bot._check_commands_announcement("channel", now=1899.0)
            self.bot._handle_commands.assert_not_called()

            self.bot._check_commands_announcement("channel", now=1900.0)
            self.bot._handle_commands.assert_called_once_with("channel")

            self.bot._check_commands_announcement("channel", now=2000.0)
            self.bot._handle_commands.assert_called_once_with("channel")

    def test_commands_announcement_restarts_timer_when_enabled(self):
        import config

        self.bot._handle_commands = MagicMock()
        with patch.dict(
            config.TWITCH_BOT,
            {
                "commands_announcements": False,
                "commands_announcement_interval_minutes": 1,
            },
        ):
            self.bot._check_commands_announcement("channel", now=100.0)
            config.TWITCH_BOT["commands_announcements"] = True
            self.bot._check_commands_announcement("channel", now=159.0)
            self.bot._handle_commands.assert_not_called()
            self.bot._check_commands_announcement("channel", now=218.0)
            self.bot._handle_commands.assert_not_called()
            self.bot._check_commands_announcement("channel", now=219.0)
            self.bot._handle_commands.assert_called_once_with("channel")

    def test_commands_announcement_skips_when_no_commands_are_enabled(self):
        import config

        self.bot._handle_commands = MagicMock()
        disabled_commands = {
            key: False for key in config.DEFAULT_TWITCH_BOT["commands"]
        }
        with patch.dict(
            config.TWITCH_BOT,
            {
                "commands_announcements": True,
                "commands_announcement_interval_minutes": 1,
                "commands": disabled_commands,
            },
        ):
            self.bot._check_commands_announcement("channel", now=100.0)
            self.bot._check_commands_announcement("channel", now=160.0)

        self.bot._handle_commands.assert_not_called()

    def test_commands_command_routes_through_chat_handler(self):
        from config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        old_global_cooldown = TWITCH_BOT.get("global_cooldown_seconds")
        old_cooldown = TWITCH_BOT.get("cooldown_seconds")
        old_commands = TWITCH_BOT.get("commands", {})

        TWITCH_BOT["access_tier"] = "Everyone"
        TWITCH_BOT["global_cooldown_seconds"] = 0
        TWITCH_BOT["cooldown_seconds"] = 0
        TWITCH_BOT["commands"] = {"bonkhelp": True}

        # Test main command !bonkhelp
        self.bot._handle_commands = MagicMock()
        line = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!bonkhelp"
        with patch('time.time', return_value=100.0):
            self.bot._handle_line(line, "channel")

        self.bot._handle_commands.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!bonkhelp"], 100.0)

        # Test alias !bonkcmds
        self.bot._handle_commands.reset_mock()
        line_alias = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!bonkcmds"
        with patch('time.time', return_value=101.0):
            self.bot._handle_line(line_alias, "channel")

        self.bot._handle_commands.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!bonkcmds"], 101.0)

        # Test alias !bonkcommands
        self.bot._handle_commands.reset_mock()
        line_alias2 = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!bonkcommands"
        with patch('time.time', return_value=102.0):
            self.bot._handle_line(line_alias2, "channel")

        self.bot._handle_commands.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!bonkcommands"], 102.0)

        # Test alias !bhelp
        self.bot._handle_commands.reset_mock()
        line_alias3 = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!bhelp"
        with patch('time.time', return_value=103.0):
            self.bot._handle_line(line_alias3, "channel")

        self.bot._handle_commands.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!bhelp"], 103.0)

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

    def test_handle_disabled_without_cached_data(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.get_disabled_items.return_value = DisabledItemsReadResult(
            DisabledItemsReadStatus.NOT_INITIALIZED
        )

        self.bot._handle_disabled("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel", "Disabled items data is not available yet."
        )

    def test_handle_disabled_with_run(self):
        from config import TWITCH_BOT
        old_highlighted = TWITCH_BOT.get("highlighted_disabled_items")
        old_templates = TWITCH_BOT.get("templates")

        TWITCH_BOT["highlighted_disabled_items"] = ["Soul Harvester", "Sucky Magnet"]
        TWITCH_BOT.setdefault("templates", {})["disabled"] = "Disabled Items: {items}"

        self.bot._send_chat = MagicMock()
        # Scenario A: Soul Harvester is disabled, Magnet is enabled
        self.run_tracker.get_disabled_items.return_value = DisabledItemsReadResult(
            DisabledItemsReadStatus.AVAILABLE,
            ("Soul Harvester", "Golden Ring"),
        )
        self.bot._handle_disabled("channel")
        self.bot._send_chat.assert_called_with("channel", "Disabled Items: Soul Harvester")

        # Scenario B: No highlighted items are disabled
        self.bot._send_chat.reset_mock()
        TWITCH_BOT["highlighted_disabled_items"] = ["Golden Sneakers"]
        self.run_tracker.get_disabled_items.return_value = DisabledItemsReadResult(
            DisabledItemsReadStatus.AVAILABLE,
            ("Forbidden Juice", "Golden sneakers"),
        )
        self.bot._handle_disabled("channel")
        self.bot._send_chat.assert_called_with("channel", "Disabled Items: Golden Sneakers")

        TWITCH_BOT["highlighted_disabled_items"] = old_highlighted
        TWITCH_BOT["templates"] = old_templates

    def test_disabled_command_routes_through_chat_handler(self):
        from config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        old_global_cooldown = TWITCH_BOT.get("global_cooldown_seconds")
        old_cooldown = TWITCH_BOT.get("cooldown_seconds")
        old_commands = TWITCH_BOT.get("commands", {})

        TWITCH_BOT["access_tier"] = "Everyone"
        TWITCH_BOT["global_cooldown_seconds"] = 0
        TWITCH_BOT["cooldown_seconds"] = 0
        TWITCH_BOT["commands"] = {"disabled": True}

        self.bot._handle_disabled = MagicMock()
        line = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!disabled"
        with patch('time.time', return_value=100.0):
            self.bot._handle_line(line, "channel")

        self.bot._handle_disabled.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!disabled"], 100.0)

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

if __name__ == '__main__':
    unittest.main()
