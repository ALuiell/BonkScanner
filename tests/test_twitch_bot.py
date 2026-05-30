import unittest
from unittest.mock import MagicMock, patch
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
        old_cooldown = TWITCH_BOT.get("cooldown_seconds")
        old_commands = TWITCH_BOT.get("commands", {})
        
        TWITCH_BOT["access_tier"] = "Everyone"
        TWITCH_BOT["cooldown_seconds"] = 5
        TWITCH_BOT["commands"] = {"stats": True, "bans": True}
        
        with patch('time.time', return_value=100.0):
            self.bot.last_command_times = {}
            self.bot._handle_stats = MagicMock()
            line = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!stats"
            self.bot._handle_line(line, "channel")
            self.bot._handle_stats.assert_called_once()
            self.assertEqual(self.bot.last_command_times["!stats"], 100.0)
            
            self.bot._handle_stats.reset_mock()
            self.bot._handle_line(line, "channel")
            self.bot._handle_stats.assert_not_called()
            
            self.bot._handle_bans = MagicMock()
            line_bans = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!bans"
            self.bot._handle_line(line_bans, "channel")
            self.bot._handle_bans.assert_called_once()
            
        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

if __name__ == '__main__':
    unittest.main()
