import sys
import unittest
from unittest.mock import MagicMock, patch

mock_pyside = MagicMock()
mock_pyside.QtCore.QThread = MagicMock
mock_pyside.QtCore.Signal = MagicMock
sys.modules['PySide6'] = mock_pyside
sys.modules['PySide6.QtCore'] = mock_pyside.QtCore

from twitch_bot import TwitchBotWorker

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

    def test_target_channel_defaults_to_authorized_username(self):
        cfg = {"username": "BotAccount", "target_channel": ""}
        self.assertEqual(TwitchBotWorker._target_channel(cfg), "botaccount")

    def test_target_channel_can_differ_from_authorized_username(self):
        cfg = {"username": "BotAccount", "target_channel": "#StreamerChannel"}
        self.assertEqual(TwitchBotWorker._target_channel(cfg), "streamerchannel")

if __name__ == '__main__':
    unittest.main()
