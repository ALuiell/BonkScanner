import src

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# `TwitchBotWorker` is a `QThread` with two `Signal`s, and these tests want it
# as a plain object -- so PySide6 is mocked while the module is imported and the
# class is built. `QThread` and `Signal` are resolved once, at class-definition
# time, so the class keeps its stand-in base for the life of the process and
# every test below behaves exactly as it did.
#
# What changed is the *scope*. This used to assign into `sys.modules` at import
# and never put it back, which left a MagicMock standing where PySide6 belongs
# for the whole process:
#
#   * on its own, this file died with an access violation before its first test
#     -- pytest-qt processes the Qt event loop in `pytest_runtest_setup`, and by
#     then the real bindings had been displaced under a live QApplication;
#   * in a full run it was worse and looked unrelated, because pytest imports
#     every test module during *collection*. This file poisoned PySide6 before
#     any test ran, so the crash surfaced in whichever Qt test happened to go
#     first -- `test_banishes_section` at the time, which had nothing to do
#     with it.
#
# `twitch_bot` is dropped from `sys.modules` on both sides: before, so the class
# is built under the stand-ins even if something imported it already; after, so
# `gui_twitch` and the rest get the real module rather than this one's.
# Two keys are saved and put back by hand rather than with `patch.dict`, which
# is the obvious tool and the wrong one: on exit it *clears* the dict and
# restores its snapshot, so every module imported inside the block is evicted
# too. `twitch_bot` pulls in `app.config` on the way, and evicting that meant
# the next `from app.config import ...` built a **second** config module. The
# tests then mutated one `TWITCH_BOT` dict while the bot read another, and
# fifteen of them failed on settings that had been applied to the wrong object.
_mock_pyside = MagicMock()
_mock_pyside.QtCore.QThread = MagicMock
_mock_pyside.QtCore.Signal = MagicMock
_real_pyside = {name: sys.modules.get(name) for name in ("PySide6", "PySide6.QtCore")}
sys.modules["PySide6"] = _mock_pyside
sys.modules["PySide6.QtCore"] = _mock_pyside.QtCore
try:
    sys.modules.pop("twitch_bot", None)
    from twitch_bot import TwitchBotWorker
finally:
    for _name, _module in _real_pyside.items():
        if _module is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _module
sys.modules.pop("twitch_bot", None)
from core.stats.types import DisabledItemsReadResult, DisabledItemsReadStatus
from core.tracker.live_run import LiveRunTracker
from core.tracker.snapshots import LiveRunSnapshot, PowerupMapContext

class TestTwitchBotWorker(unittest.TestCase):
    def setUp(self):
        self.run_tracker = MagicMock()
        def runtime_snapshot():
            latest = self.run_tracker.latest_snapshot()
            chaos_level = self.run_tracker.chaos_tome_level()
            chaos_parts = self.run_tracker.chaos_tome_summary_parts()
            chaos = None if chaos_level is None else SimpleNamespace(
                level=chaos_level,
                stats=(),
                legacy_parts=chaos_parts,
            )
            disabled = self.run_tracker.get_disabled_items()
            return SimpleNamespace(
                latest_snapshot=latest,
                status=self.run_tracker.status(),
                run_id=self.run_tracker.run_identity()[0],
                current_stage_index=self.run_tracker.run_identity()[1],
                stage_summary=self.run_tracker.stage_summary_rows(),
                chest_stats=self.run_tracker.get_chest_stats(),
                kps={
                    "current": self.run_tracker.current_ui_kps(),
                    "minute_avg": self.run_tracker.current_minute_avg_kps(),
                    "five_minute_avg": self.run_tracker.current_five_minute_avg_kps(),
                    "run_avg": self.run_tracker.current_run_avg_kps(),
                },
                chaos_tome=chaos,
                powerups=self.run_tracker.powerups_snapshot(),
                powerups_recent=self.run_tracker.recent_powerups_snapshot(),
                legacy_disabled=disabled,
            )
        self.run_tracker.runtime_snapshot.side_effect = runtime_snapshot
        self.bot = TwitchBotWorker(self.run_tracker)

    def test_scanner_command_links_to_the_latest_release(self):
        from app import config

        self.bot._send_chat = MagicMock()

        with patch.dict(config.TWITCH_BOT, {"templates": {"scanner": "{github_url}"}}):
            self.bot._handle_scanner("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "https://github.com/ALuiell/BonkScanner/releases/latest",
        )

    def test_stop_before_run_is_not_lost_when_qthread_start_is_delayed(self):
        """Closing during QThread.start() must not resurrect the bot worker."""
        self.bot.status_updated = MagicMock()

        self.bot.stop()
        self.bot.run()

        self.assertFalse(self.bot.running)
        self.assertTrue(self.bot._stop_event.is_set())
        self.bot.status_updated.emit.assert_not_called()

    def test_byte_truncation(self):
        self.bot.sock = MagicMock()
        self.bot.log_message = MagicMock()

        long_str = "a" * 1000
        self.bot._send_chat("test_channel", long_str)

        self.bot.sock.send.assert_called_once()
        args = self.bot.sock.send.call_args[0][0]
        self.assertTrue(len(args) <= 512)
        self.assertTrue(args.endswith(b"\r\n"))

    def test_stats_uses_runtime_snapshot_without_legacy_getters(self):
        tracker = SimpleNamespace(
            runtime_snapshot=lambda: SimpleNamespace(
                latest_snapshot=SimpleNamespace(
                    stats={"Damage": SimpleNamespace(display_value="150%")},
                ),
            ),
            latest_snapshot=lambda: (_ for _ in ()).throw(AssertionError("legacy getter")),
        )
        bot = TwitchBotWorker(tracker)
        bot._send_chat = MagicMock()

        bot._handle_stats("channel")

        bot._send_chat.assert_called_once()
        self.assertIn("150%", bot._send_chat.call_args.args[1])

    def test_access_tier_mods_vips(self):
        from app.config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        TWITCH_BOT["access_tier"] = "Mods & VIPs"
        self.assertTrue(self.bot._check_access("badges=moderator/1,subscriber/0"))
        self.assertTrue(self.bot._check_access("badges=vip/1"))
        self.assertFalse(self.bot._check_access("badges=subscriber/1"))
        self.assertTrue(self.bot._check_access("badges=broadcaster/1"))
        TWITCH_BOT["access_tier"] = old_tier

    def test_access_tier_subs_mods(self):
        from app.config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        TWITCH_BOT["access_tier"] = "Subs & Mods"
        self.assertTrue(self.bot._check_access("badges=moderator/1"))
        self.assertTrue(self.bot._check_access("badges=subscriber/1,vip/0"))
        self.assertFalse(self.bot._check_access("badges=vip/1"))
        self.assertTrue(self.bot._check_access("badges=broadcaster/1"))
        TWITCH_BOT["access_tier"] = old_tier

    def test_cooldown_per_command(self):
        from app.config import TWITCH_BOT
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

    def test_command_aliases_share_the_same_cooldown(self):
        from app.config import TWITCH_BOT
        old_tier = TWITCH_BOT.get("access_tier")
        old_global_cooldown = TWITCH_BOT.get("global_cooldown_seconds")
        old_cooldown = TWITCH_BOT.get("cooldown_seconds")
        old_commands = TWITCH_BOT.get("commands", {})

        TWITCH_BOT["access_tier"] = "Everyone"
        TWITCH_BOT["global_cooldown_seconds"] = 1
        TWITCH_BOT["cooldown_seconds"] = 10
        TWITCH_BOT["commands"] = {"stats": True}
        self.bot._handle_stats = MagicMock()

        stats_line = ":user!user@host PRIVMSG #channel :!stats"
        alias_line = ":user!user@host PRIVMSG #channel :!bonkstats"
        with patch("time.time", return_value=100.0):
            self.bot._handle_line(stats_line, "channel")
        with patch("time.time", return_value=102.0):
            self.bot._handle_line(alias_line, "channel")

        self.bot._handle_stats.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times, {"!stats": 100.0})

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

    def test_opt_in_commands_stay_disabled_when_missing_from_partial_config(self):
        from app import config

        with patch.dict(config.TWITCH_BOT, {"commands": {"stats": True}}):
            enabled_commands = self.bot._enabled_command_names()
            self.assertIn("!stats", enabled_commands)
            self.assertIn("!kps", enabled_commands)
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
        from app.config import TWITCH_BOT
        old_templates = TWITCH_BOT.get("templates")

        # stats has an invalid format spec or missing key that fails to format with invalid specs
        TWITCH_BOT["templates"] = {"stats": "Live Stats: {Damage:invalid_spec}"}
        res = self.bot._format_template("stats", "Default Stats: {Damage}", Damage="100")
        self.assertEqual(res, "Default Stats: 100")

        TWITCH_BOT["templates"] = old_templates

    def test_handle_session_formats_the_session_snapshot(self):
        snapshot = lambda: {
            "rerolls": 328,
            "seeds_found": 17,
            "tracked_rows": (),
        }
        bot = TwitchBotWorker(self.run_tracker, session_snapshot=snapshot)
        bot._send_chat = MagicMock()

        bot._handle_session("channel")

        bot._send_chat.assert_called_once_with(
            "channel",
            "328 resets, 17 seeds found (5.18%) | Tracked Items: None",
        )

    def test_handle_session_without_snapshot_callback(self):
        self.bot._send_chat = MagicMock()

        self.bot._handle_session("channel")

        self.bot._send_chat.assert_called_once_with("channel", "Session stats are not available yet.")

    def test_twitch_tracked_items_source_defaults_to_custom(self):
        from app.config import normalize_twitch_bot_config

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

    def _bot_on_a_real_tracker(self, clock):
        """A real ``TwitchBotWorker`` over a real ``LiveRunTracker``.

        The other powerup tests here hand the bot a hand-built snapshot, which
        proves how it formats but not that the tracker actually publishes what
        it formats. The staleness the bot keys on is produced by the tracker's
        own clock against its own TTLs, so nothing but a real tracker can show
        that ``powerups_recent`` carries it -- and a live run cannot show it
        either, because the reader has to miss a tick first.
        """
        tracker = LiveRunTracker(clock=clock)
        tracker.update(
            LiveRunSnapshot(
                captured_at=clock(),
                # The player stats are read on their own schedule, so the
                # multiplier is still there when the powerup snapshot is not --
                # which is what the last branch reports durations from.
                stats={
                    "Powerup Multiplier": SimpleNamespace(
                        value=1.5, display_value="1.5x"
                    )
                },
                items=(),
                game_time_seconds=100.0,
                stage_time_seconds=100.0,
                mob_kills=0,
                map_seed=100,
                stage_ptr=1000,
                stage_index=1,
                chests_total=46,
                pots_total=55,
            )
        )
        tracker.update_powerups(
            SimpleNamespace(
                my_time_seconds=1000.0,
                stage_timer_seconds=440.0,
                stage_index=1,
                stage_time_seconds=540.0,
                powerup_multiplier=1.5,
                powerup_multiplier_display="1.5x",
                effects=(
                    SimpleNamespace(
                        effect_id=1,
                        name="Rage",
                        added_time=999.0,
                        expiration_time=1021.5,
                    ),
                ),
            ),
            map_context=PowerupMapContext.from_activity_max(
                {"Chests": 46, "Pots": 55}, captured_at=clock()
            ),
        )
        bot = TwitchBotWorker(tracker)
        bot._send_chat = MagicMock()
        return bot

    def test_powerups_over_a_real_tracker_never_says_none_active_while_a_buff_runs(self):
        """End to end: tracker -> runtime_snapshot -> chat, at three read ages.

        This is the wiring the live run could not exercise -- 353 recorded
        ticks never had a gap over 0.505 s, so the snapshot never went stale
        and the bot took the fresh branch every single time.
        """
        now = [1000.0]
        bot = self._bot_on_a_real_tracker(lambda: now[0])

        # Fresh: inside POWERUPS_SNAPSHOT_TTL_SECONDS.
        bot._handle_powerups("channel")
        fresh = bot._send_chat.call_args[0][1]

        # Stale: past the TTL, inside POWERUPS_SNAPSHOT_GRACE_SECONDS.
        now[0] = 1003.0
        bot._handle_powerups("channel")
        stale = bot._send_chat.call_args[0][1]

        # Gone: past the grace window as well.
        now[0] = 1010.0
        bot._handle_powerups("channel")
        gone = bot._send_chat.call_args[0][1]

        self.assertIn("Rage", fresh)
        self.assertNotIn("updating", fresh)

        self.assertIn("Rage", stale)
        self.assertIn("(updating...)", stale)

        self.assertIn("refreshing", gone)

        for text in (fresh, stale, gone):
            self.assertNotIn("none active", text)

    def _powerups_snapshot(self, *, available=False, stale=False, active=()):
        return SimpleNamespace(
            available=available,
            stale=stale,
            powerup_multiplier_display="5.43x",
            standard_duration_seconds=81.435,
            clock_duration_seconds=65.148,
            active=active,
        )

    def _rage(self):
        return SimpleNamespace(
            name="Rage",
            remaining_seconds=80.0,
            pickup_ui="01:33",
            expires_ui="00:11",
        )

    def test_handle_powerups_without_a_read_does_not_claim_none_active(self):
        """No usable read is not the same fact as "nothing is active".

        The two used to produce the same chat line, so a single missed
        background tick told viewers a buff that was plainly on screen had
        ended. Durations still come from the player stats -- those are read on
        their own schedule -- but the active set must not be invented.
        """
        self.bot._send_chat = MagicMock()
        self.run_tracker.recent_powerups_snapshot.return_value = self._powerups_snapshot()
        self.run_tracker.latest_snapshot.return_value = SimpleNamespace(
            stats={
                "Powerup Multiplier": SimpleNamespace(value=1.5, display_value="1.5x")
            }
        )

        self.bot._handle_powerups("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "Powerups: refreshing, try again in a moment | "
            "Durations: standard 22s, clock 18s (PM 1.5x)"
        )

    def test_handle_powerups_uses_tracker_snapshot_when_available(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.latest_snapshot.return_value = SimpleNamespace(stats={})
        self.run_tracker.recent_powerups_snapshot.return_value = self._powerups_snapshot(
            available=True,
            active=(self._rage(),),
        )

        self.bot._handle_powerups("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "Powerups: Rage 01:33 -> 00:11 (80s left) | Durations: standard 81s, clock 65s (PM 5.43x)",
        )

    def test_handle_powerups_quotes_a_stale_read_rather_than_dropping_it(self):
        """A read past its TTL is still the best answer available.

        The overlay can afford to discard it -- it repaints four times a
        second -- but chat gets one reply and keeps it, so the last known
        effects are reported and marked as catching up.
        """
        self.bot._send_chat = MagicMock()
        self.run_tracker.latest_snapshot.return_value = SimpleNamespace(stats={})
        self.run_tracker.recent_powerups_snapshot.return_value = self._powerups_snapshot(
            stale=True,
            active=(self._rage(),),
        )

        self.bot._handle_powerups("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "Powerups: Rage 01:33 -> 00:11 (80s left) | Durations: standard 81s, clock 65s "
            "(PM 5.43x) (updating...)",
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

    def test_handle_stats_uses_shared_stat_abbreviations(self):
        from app.config import TWITCH_BOT

        self.bot._send_chat = MagicMock()
        self.run_tracker.latest_snapshot.return_value = SimpleNamespace(
            stats={
                "Damage": SimpleNamespace(display_value="150%"),
                "Powerup Drop Chance": SimpleNamespace(display_value="+20%"),
            }
        )
        old_selected_stats = TWITCH_BOT.get("selected_stats")
        old_templates = TWITCH_BOT.get("templates")
        TWITCH_BOT["selected_stats"] = ["Damage", "Powerup Drop Chance"]
        TWITCH_BOT["templates"] = dict(TWITCH_BOT.get("templates", {}))
        TWITCH_BOT["templates"]["stats"] = "{stats}"
        try:
            self.bot._handle_stats("channel")
        finally:
            TWITCH_BOT["selected_stats"] = old_selected_stats
            TWITCH_BOT["templates"] = old_templates

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "DMG: 150% | PDC: +20%",
        )

    def test_powerups_command_routes_through_chat_handler(self):
        from app.config import TWITCH_BOT
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
        from app.config import TWITCH_BOT
        from core.tracker.live_run import ChestStatsSnapshot

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

        # Never publish a stale numeric Expected when fast tracking missed opens.
        self.run_tracker.get_chest_stats.return_value = ChestStatsSnapshot(
            24, 46, 7, 20, 2, 2, {1: 24}, {1: 46}, True, 0.0, 0, True
        )
        self.bot._handle_chests("channel")
        self.bot._send_chat.assert_called_with(
            "channel", "Chests: T1:24/46 | Total: 24/46 | Paid: 20 | Key Procs: 2/22 (9.1%) | Expected: -- | Free Chests: 2 | Keys: 7 (41.2%)"
        )

        # Test with 0 keys
        self.run_tracker.get_chest_stats.return_value = ChestStatsSnapshot(
            20, 46, 0, 18, 0, 2, {1: 20}, {1: 46}, True
        )
        self.bot._handle_chests("channel")
        self.bot._send_chat.assert_called_with(
            "channel", "Chests: T1:20/46 | Total: 20/46 | Paid: 18 | Key Procs: 0/18 (0.0%) | Expected: -- | Free Chests: 2 | Keys: 0 (0.0%)"
        )

        self.run_tracker.get_chest_stats.return_value = ChestStatsSnapshot(
            20, 46, 0, 17, 34, None, {1: -1, 2: 20}, {1: 46, 2: 46}, True, 0.0, 0, False, 51, True
        )
        self.bot._handle_chests("channel")
        self.bot._send_chat.assert_called_with(
            "channel", "Chests: T1:--/46 T2:20/46 | Total: 51+/92 | Paid: 17 | Key Procs: 34/51 (66.7%) | Expected: -- | Free Chests: -- | Keys: 0 (0.0%)"
        )


    def test_handle_chests_without_active_run(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.has_active_run.return_value = False
        self.run_tracker.latest_snapshot.return_value = None

        self.bot._handle_chests("channel")

        self.bot._send_chat.assert_called_once_with("channel", "No active run detected.")
        self.run_tracker.get_chests_and_keys.assert_not_called()

    def test_chests_command_routes_through_chat_handler(self):
        from app.config import TWITCH_BOT
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
        self.assertEqual(self.bot.last_command_times["!chests"], 101.0)

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

    def test_handle_presets_templates_mode(self):
        from unittest.mock import patch
        from app import config
        self.bot._send_chat = MagicMock()

        with patch.object(config, 'EVALUATION_MODE', 'templates'), \
             patch.object(config, 'ACTIVE_TEMPLATES', ['LIGHT', 'MERCHANT']), \
             patch.object(config, 'TEMPLATES', [
                 {"id": 1, "name": "LIGHT", "color": "WHITE", "desc": "", "sm_total": 7, "micro": 2, "boss": 2},
                 {"id": 2, "name": "MERCHANT", "color": "CYAN", "desc": "", "sm_total": 10, "shady": 3, "moai": 7, "micro": 1, "boss": 2, "magnet": 2}
             ]):
            self.bot._handle_presets("channel")
            self.bot._send_chat.assert_called_once_with(
                "channel",
                "[Reroller] Mode: Templates | Active: LIGHT(S+M≥7, Mic≥2, B≥2), MERCHANT(S+M≥10, S≥3, M≥7, Mic≥1, B≥2, Mag≥2)"
            )

    def test_handle_presets_scores_mode(self):
        from unittest.mock import patch
        from app import config
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
        from app.config import TWITCH_BOT
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
        self.assertEqual(self.bot.last_command_times["!presets"], 101.0)

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

    def test_handle_commands_lists_enabled_only(self):
        from unittest.mock import patch
        from app import config
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
            "kps": False,
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
                "Available commands: !stats, !session, !items, !tomes, !stages, !scanner, !presets, !build, !bonkhelp"
            )

    def test_handle_commands_uses_configured_template(self):
        from app import config

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
        from app import config

        bot_cfg = config.normalize_twitch_bot_config({"templates": {}})

        self.assertIn("bonkhelp", bot_cfg["templates"])
        self.assertIn("session", bot_cfg["templates"])

    def test_legacy_commands_key_migrates_to_bonkhelp(self):
        from app import config

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
        from app import config

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

    def test_intermediate_powerups_template_with_durations_tail_migrates_to_live_format(self):
        from app import config

        bot_cfg = config.normalize_twitch_bot_config(
            {
                "templates": {
                    "powerups": "Powerups: {powerups} | Durations: standard {standard_duration}s, clock {clock_duration}s (PM {pm})",
                },
            }
        )

        self.assertEqual(
            bot_cfg["templates"]["powerups"],
            "Powerups: {powerups} (PM {pm})",
        )

    def test_commands_announcement_uses_configured_interval(self):
        from app import config

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
        from app import config

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
        from app import config

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
        from app.config import TWITCH_BOT
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
        self.assertEqual(self.bot.last_command_times["!bonkhelp"], 101.0)

        # Test alias !bonkcommands
        self.bot._handle_commands.reset_mock()
        line_alias2 = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!bonkcommands"
        with patch('time.time', return_value=102.0):
            self.bot._handle_line(line_alias2, "channel")

        self.bot._handle_commands.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!bonkhelp"], 102.0)

        # Test alias !bhelp
        self.bot._handle_commands.reset_mock()
        line_alias3 = "@badges=moderator/1 :user!user@user.tmi.twitch.tv PRIVMSG #channel :!bhelp"
        with patch('time.time', return_value=103.0):
            self.bot._handle_line(line_alias3, "channel")

        self.bot._handle_commands.assert_called_once_with("channel")
        self.assertEqual(self.bot.last_command_times["!bonkhelp"], 103.0)

        TWITCH_BOT["access_tier"] = old_tier
        TWITCH_BOT["global_cooldown_seconds"] = old_global_cooldown
        TWITCH_BOT["cooldown_seconds"] = old_cooldown
        TWITCH_BOT["commands"] = old_commands

    def test_handle_kps_reports_no_game_state(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.status.return_value = "no_game"

        self.bot._handle_kps("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "Kills Per Second is not available because no run is active.",
        )

    def test_handle_kps_reports_current_value(self):
        self.bot._send_chat = MagicMock()
        self.run_tracker.status.return_value = "live"
        self.run_tracker.current_ui_kps.return_value = 150
        self.run_tracker.current_minute_avg_kps.return_value = 243
        self.run_tracker.current_five_minute_avg_kps.return_value = 221
        self.run_tracker.current_run_avg_kps.return_value = 138

        self.bot._handle_kps("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "KPS: 150/s | 60s Avg: 243/s | 5m Avg: 221/s | Run Avg: 138/s",
        )

    def test_handle_kps_uses_custom_template(self):
        from app.config import TWITCH_BOT

        old_templates = TWITCH_BOT.get("templates")
        TWITCH_BOT["templates"] = dict(old_templates or {})
        TWITCH_BOT["templates"]["kps"] = "KPS now {kps} | short {minute_avg} | mid {five_minute_avg} | full {run_avg}"

        self.bot._send_chat = MagicMock()
        self.run_tracker.status.return_value = "live"
        self.run_tracker.current_ui_kps.return_value = 150
        self.run_tracker.current_minute_avg_kps.return_value = 243
        self.run_tracker.current_five_minute_avg_kps.return_value = 221
        self.run_tracker.current_run_avg_kps.return_value = 138

        self.bot._handle_kps("channel")

        self.bot._send_chat.assert_called_once_with(
            "channel",
            "KPS now 150/s | short 243/s | mid 221/s | full 138/s",
        )

        TWITCH_BOT["templates"] = old_templates

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
        from app.config import TWITCH_BOT
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
        from app.config import TWITCH_BOT
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

class OneRingAnnouncerTests(unittest.TestCase):
    """One message per run, on the first ring, on Forest and Desert only.

    Driven through `_check_one_ring_announcement` on a mutable fake runtime,
    which is what the bot's socket loop does every ~0.5 s -- so "announces once"
    here means "stayed quiet on every later tick", not "was called once".
    """

    def setUp(self):
        from app.config import TWITCH_BOT

        self.sent: list[str] = []
        self.state = SimpleNamespace(
            run_id="run-1",
            items=(),
            items_available=True,
            # The 1 s lane carries the inventory by default, as it does in a
            # live run. `fast_lane` False drops it to the 10 s snapshot's copy,
            # which is the fallback path.
            fast_lane=True,
            is_graveyard=False,
            map_context_known=True,
            stage_index=2,
            game_time_seconds=125.0,
        )

        def runtime_snapshot():
            return SimpleNamespace(
                run_id=self.state.run_id,
                current_stage_index=self.state.stage_index,
                fast_items=(
                    tuple(self.state.items)
                    if self.state.fast_lane and self.state.items_available
                    else None
                ),
                latest_snapshot=SimpleNamespace(
                    items=self.state.items,
                    items_available=self.state.items_available,
                    game_time_seconds=self.state.game_time_seconds,
                ),
                powerup_map_context=(
                    PowerupMapContext(
                        is_graveyard=self.state.is_graveyard,
                        captured_at=1.0,
                    )
                    if self.state.map_context_known
                    else None
                ),
            )

        self.bot = TwitchBotWorker(SimpleNamespace(runtime_snapshot=runtime_snapshot))
        self.bot._send_chat = lambda _channel, message: self.sent.append(message)

        # The announcer is opt-in, so every case here has to switch it on --
        # except the one that asserts the toggle silences it.
        self._previous_enabled = TWITCH_BOT.get("one_ring_announcements")
        TWITCH_BOT["one_ring_announcements"] = True
        self.addCleanup(
            lambda: TWITCH_BOT.__setitem__(
                "one_ring_announcements", self._previous_enabled
            )
        )

        # The draw memory is persisted config state; leaving a test's draws in
        # it would bias the next test's exclusion, and saving it would rewrite
        # the developer's real config.json.
        self._previous_recent = TWITCH_BOT.get("announcer_recent_lines")
        TWITCH_BOT["announcer_recent_lines"] = {}
        saver = patch("app.config.save_config", lambda *_args, **_kwargs: None)
        saver.start()
        self.addCleanup(saver.stop)
        self.addCleanup(
            lambda: TWITCH_BOT.__setitem__(
                "announcer_recent_lines", self._previous_recent
            )
        )

    def set_pool(self, template_key, *phrases):
        """Replace one pool for the duration of the test."""
        from app.config import TWITCH_BOT

        templates = TWITCH_BOT.setdefault("templates", {})
        previous = templates.get(template_key)
        templates[template_key] = "\n".join(phrases)
        self.addCleanup(lambda: templates.__setitem__(template_key, previous))

    def tick(self, count=1):
        for _ in range(count):
            self.bot._check_one_ring_announcement("channel")

    def test_pickup_on_forest_announces_once(self):
        self.set_pool("one_ring_announcement", "the ring is ours now")
        self.tick()  # the run's first sighting: empty bag, nothing to say
        self.state.items = ("Key x2", "The One Ring x1")
        self.tick(4)

        self.assertEqual(self.sent, ["the ring is ours now"])

    def test_the_ring_is_caught_on_the_fast_lane_not_the_10_s_snapshot(self):
        # The pickup reaches `fast_items` a second after it happens and
        # `latest_snapshot.items` up to ten seconds later. Announcing off the
        # slow copy would put the message that far behind the stream.
        self.tick()

        def runtime_snapshot():
            return SimpleNamespace(
                run_id="run-1",
                current_stage_index=1,
                fast_items=("The One Ring x1",),
                latest_snapshot=SimpleNamespace(
                    items=(),
                    items_available=True,
                    game_time_seconds=10.0,
                ),
                powerup_map_context=PowerupMapContext(captured_at=1.0),
            )

        self.bot.run_tracker = SimpleNamespace(runtime_snapshot=runtime_snapshot)
        self.tick()

        self.assertEqual(len(self.sent), 1)

    def test_a_stale_fast_read_falls_back_to_the_snapshot_inventory(self):
        self.tick()
        self.state.fast_lane = False
        self.state.items = ("The One Ring x1",)
        self.tick(3)

        self.assertEqual(len(self.sent), 1)

    def test_a_duplicate_ring_uses_the_duplicate_pool(self):
        self.set_pool("one_ring_announcement", "first")
        self.set_pool("one_ring_duplicate_announcement", "ring number {count}")
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick()
        self.state.items = ("The One Ring x2",)
        self.tick(3)
        self.state.items = ("The One Ring x3",)
        self.tick(3)

        self.assertEqual(self.sent, ["first", "ring number 2", "ring number 3"])

    def test_a_ring_count_that_does_not_grow_says_nothing(self):
        self.set_pool("one_ring_announcement", "first")
        self.set_pool("one_ring_duplicate_announcement", "duplicate")
        self.tick()
        self.state.items = ("The One Ring x2",)
        self.tick(4)

        # Two rings arriving between one tick and the next is one event, not
        # two: the first-pickup line is what a viewer needs, and the duplicate
        # pool must not also fire for the same observation.
        self.assertEqual(self.sent, ["first"])

    def test_the_tags_are_filled_from_the_run(self):
        self.set_pool(
            "one_ring_announcement",
            "{streamer} @ stage {stage}, {time}, ring {count}",
        )
        self.state.stage_index = 3
        self.state.game_time_seconds = 125.0
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick()

        self.assertEqual(self.sent, ["channel @ stage 3, 02:05, ring 1"])

    def test_an_unknown_tag_renders_as_a_dash_rather_than_breaking(self):
        self.set_pool("one_ring_announcement", "it found {nonsense}")
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick()

        self.assertEqual(self.sent, ["it found --"])

    def test_one_run_spends_every_duplicate_phrase_before_repeating(self):
        self.set_pool("one_ring_announcement", "first")
        self.set_pool("one_ring_duplicate_announcement", "a", "b", "c", "d", "e")
        self.tick()
        for count in range(1, 7):
            self.state.items = (f"The One Ring x{count}",)
            self.tick()

        # Rings 2..6 are five draws from a five-line pool inside one run, and
        # the run-scoped exclusion is absolute -- so they are a permutation,
        # not a sample.
        duplicates = self.sent[1:]
        self.assertEqual(sorted(duplicates), ["a", "b", "c", "d", "e"])

    def test_a_spent_pool_starts_over_instead_of_going_silent(self):
        self.set_pool("one_ring_announcement", "first")
        self.set_pool("one_ring_duplicate_announcement", "a", "b")
        self.tick()
        for count in range(1, 6):
            self.state.items = (f"The One Ring x{count}",)
            self.tick()

        # Two-line pool, four duplicate rings: the cycle has to wrap.
        self.assertEqual(len(self.sent), 5)
        self.assertEqual(sorted(self.sent[1:3]), ["a", "b"])
        self.assertEqual(sorted(self.sent[3:]), ["a", "b"])

    def test_a_new_run_forgets_what_the_previous_one_spent(self):
        # Asserted on the record rather than on the drawn lines, and
        # deliberately. Stated behaviourally this test is vacuous: a pool that
        # the previous run left spent is re-filled by the exhaustion branch
        # anyway, so the observable sequence is identical whether or not the
        # run change cleared anything -- which is exactly what a tamper run
        # showed. The record is the only place the difference is visible.
        self.set_pool("one_ring_announcement", "first")
        self.set_pool("one_ring_duplicate_announcement", "a", "b", "c", "d")
        self.tick()
        for count in (1, 2, 3):
            self.state.items = (f"The One Ring x{count}",)
            self.tick()
        self.assertEqual(
            len(self.bot._pool_lines_used_this_run["one_ring_duplicate_announcement"]),
            2,
        )

        self.state.run_id = "run-2"
        self.state.items = ()
        self.tick()

        self.assertEqual(self.bot._pool_lines_used_this_run, {})

    def test_the_pool_draws_every_phrase_before_repeating_one(self):
        self.set_pool("one_ring_announcement", "a", "b", "c", "d")
        for index in range(4):
            self.state.run_id = f"run-{index}"
            self.state.items = ()
            self.tick()
            self.state.items = ("The One Ring x1",)
            self.tick()

        # Four draws from a four-line pool with a two-line exclusion cannot be
        # a perfect permutation, but no line may repeat while an unused one is
        # still available -- which for the first three draws is exact.
        self.assertEqual(len(self.sent), 4)
        self.assertEqual(len(set(self.sent[:3])), 3)

    def test_the_exclusion_is_persisted_so_it_survives_a_restart(self):
        from app.config import TWITCH_BOT

        self.set_pool("one_ring_announcement", "a", "b", "c", "d")
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick()

        remembered = TWITCH_BOT["announcer_recent_lines"]["one_ring_announcement"]
        self.assertEqual(remembered, self.sent)

        # A fresh worker -- the restart -- must not draw what the old one just
        # did. In-memory state would have been lost here; the config was not.
        #
        # One draw, not several: the memory is half the pool, so on a pool of
        # four the third draw may legitimately bring the first phrase back. The
        # claim under test is "the next line after a restart is a different
        # one", and asserting past that is asserting more than the design
        # promises -- which is how a test starts failing at random.
        fresh = TwitchBotWorker(self.bot.run_tracker)
        self.assertNotEqual(
            fresh._draw_from_pool("one_ring_announcement", "unused default"),
            self.sent[0],
        )

    def test_a_cleared_pool_falls_back_to_the_default_rather_than_going_silent(self):
        self.set_pool("one_ring_announcement", "", "   ")
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick()

        from app import config

        self.assertEqual(len(self.sent), 1)
        default_lines = {
            line.strip()
            for line in config.DEFAULT_TWITCH_BOT["templates"][
                "one_ring_announcement"
            ].splitlines()
        }
        # The drawn line has its tags filled, so compare on the leading literal.
        self.assertTrue(
            any(self.sent[0].startswith(line.split("{")[0]) for line in default_lines)
        )

    def test_the_scanner_spelling_is_matched_too(self):
        # Older recordings and the scanner name the item "Golden Ring"; the
        # memory client formats it "The One Ring". Both are the same item.
        self.tick()
        self.state.items = ("Golden Ring x1",)
        self.tick()

        self.assertEqual(len(self.sent), 1)

    def test_a_ring_shaped_name_is_not_the_ring(self):
        self.tick()
        self.state.items = ("Beefy Ring x1", "Slippery Ring x1")
        self.tick(3)

        self.assertEqual(self.sent, [])

    def test_graveyard_announces_like_any_other_map(self):
        # This was Forest/Desert-only in its first version. Nothing in the
        # announcer ever depended on the map, and `run_id` holds across
        # Graveyard's crypt and boss-room transitions, so the latch cannot
        # double-fire there.
        self.state.is_graveyard = True
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick(3)

        self.assertEqual(len(self.sent), 1)

    def test_an_unknown_map_does_not_hold_the_announcement(self):
        # The map gate is gone, so an absent `powerup_map_context` is no longer
        # a reason to wait for the next 10 s republish.
        self.state.map_context_known = False
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick(3)

        self.assertEqual(len(self.sent), 1)

    def test_connecting_mid_run_does_not_announce_a_ring_already_held(self):
        self.state.items = ("The One Ring x1",)
        self.tick(4)

        self.assertEqual(self.sent, [])

    def test_a_new_run_re_arms_the_announcer(self):
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick()
        self.assertEqual(len(self.sent), 1)

        self.state.run_id = "run-2"
        self.state.items = ()
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick()

        self.assertEqual(len(self.sent), 2)

    def test_an_unavailable_item_read_is_not_an_empty_inventory(self):
        # The bot connects mid-run while the item read is failing. If the failed
        # read seeded the run as "no ring", the first read that succeeds would
        # announce a ring the chat was already told about.
        self.state.items = ("The One Ring x1",)
        self.state.items_available = False
        self.tick(2)
        self.assertEqual(self.sent, [])

        self.state.items_available = True
        self.tick(2)
        self.assertEqual(self.sent, [])

    def test_the_toggle_silences_it(self):
        from app.config import TWITCH_BOT

        # `setUp` switches the announcer on for every other case here; this one
        # switches it back off, which is also its shipped default.
        TWITCH_BOT["one_ring_announcements"] = False
        self.tick()
        self.state.items = ("The One Ring x1",)
        self.tick(3)

        self.assertEqual(self.sent, [])

    def test_it_is_off_until_the_streamer_turns_it_on(self):
        from app import config

        self.assertFalse(config.DEFAULT_TWITCH_BOT["one_ring_announcements"])
        self.assertFalse(
            config.normalize_twitch_bot_config({})["one_ring_announcements"]
        )


if __name__ == '__main__':
    unittest.main()
