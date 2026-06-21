import socket
import ssl
import time
import re
import string
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from PySide6.QtCore import QThread, Signal
import config
from twitch_credentials import get_twitch_oauth_token


class SafeFormatter(string.Formatter):
    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, "--")
        return super().get_value(key, args, kwargs)


def _round_chaos_summary_part(part: str) -> str:
    if part.startswith("Pickup "):
        return re.sub(
            r"(?P<sign>[+-])(?P<value>\d+(?:\.\d+)?)(?P<suffix>%?)$",
            lambda match: f"{match.group('sign')}{float(match.group('value')):.2f}".rstrip("0").rstrip(".") + match.group('suffix'),
            part,
        )

    def replace_value(match: re.Match[str]) -> str:
        value = Decimal(match.group("value")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{match.group('sign')}{value}{match.group('suffix')}"

    return re.sub(
        r"(?P<sign>[+-])(?P<value>\d+(?:\.\d+)?)(?P<suffix>%?)$",
        replace_value,
        part,
    )


class TwitchBotWorker(QThread):
    status_updated = Signal(str)
    log_message = Signal(str)

    def __init__(self, run_tracker, parent=None, session_stats_provider=None):
        super().__init__(parent)
        self.run_tracker = run_tracker
        self.session_stats_provider = session_stats_provider
        self.running = False
        self.sock = None
        self.last_command_time = 0
        self._last_run_id = None
        self._last_commands_announcement_at = None
        self._commands_announcements_were_enabled = False
        self.last_command_times: dict[str, float] = {}
        self.last_global_command_time: float = 0.0

    def run(self):
        self.running = True
        bot_cfg = config.TWITCH_BOT
        username = str(bot_cfg.get("username") or "").strip().lstrip("#").lower()
        target_channel = self._target_channel(bot_cfg)
        token = get_twitch_oauth_token()

        if not username or not target_channel or not token:
            self.status_updated.emit("Error: Missing credentials")
            self.running = False
            return

        import time
        while self.running:
            self.status_updated.emit("Connecting to Twitch...")

            try:
                raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                raw_sock.settimeout(10.0)
                context = ssl.create_default_context()
                self.sock = context.wrap_socket(raw_sock, server_hostname="irc.chat.twitch.tv")
                self.sock.connect(("irc.chat.twitch.tv", 6697))
                self.sock.settimeout(None)

                self._send(f"PASS oauth:{token}")
                self._send(f"NICK {username}")
                self._send(f"JOIN #{target_channel}")
                self._send("CAP REQ :twitch.tv/tags twitch.tv/commands")

                self.status_updated.emit(f"Connected to #{target_channel}")
                self.log_message.emit("Bot joined chat.")
                self._last_commands_announcement_at = time.monotonic()
                self._commands_announcements_were_enabled = bool(
                    config.TWITCH_BOT.get("commands_announcements", False)
                )

                buffer = ""
                self._last_run_id, self._last_stage_index = self.run_tracker.run_identity()

                while self.running:
                    self._check_stage_transitions(target_channel)
                    self._check_commands_announcement(target_channel)

                    self.sock.settimeout(0.5)
                    try:
                        data = self.sock.recv(4096)
                    except socket.timeout:
                        continue
                    except Exception as e:
                        self.log_message.emit(f"Socket error: {e}")
                        break

                    if not data:
                        break

                    buffer += data.decode("utf-8", errors="replace")
                    lines = buffer.split("\r\n")
                    buffer = lines.pop()

                    for line in lines:
                        try:
                            self._handle_line(line, target_channel)
                        except Exception as e:
                            import traceback
                            self.log_message.emit(f"Command error: {e}")
                            traceback.print_exc()

            except Exception as e:
                self.log_message.emit(f"Bot exception: {e}")
                self.status_updated.emit(f"Error: {e}")

            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
            self.sock = None

            if self.running:
                self.log_message.emit("Reconnecting in 2 seconds...")
                self.status_updated.emit("Reconnecting...")
                time.sleep(2)

    @staticmethod
    def _target_channel(bot_cfg: dict) -> str:
        username = str(bot_cfg.get("username") or "").strip().lstrip("#").lower()
        target_channel = str(bot_cfg.get("target_channel") or "").strip().lstrip("#").lower()
        return target_channel or username

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except Exception:
                pass

    def _send(self, msg: str):
        if self.sock:
            try:
                self.sock.send(f"{msg}\r\n".encode("utf-8"))
            except:
                pass

    def _send_chat(self, channel: str, msg: str):
        full_prefix = f"PRIVMSG #{channel} :"
        suffix = "\r\n"
        max_msg_bytes = 512 - len(full_prefix.encode("utf-8")) - len(suffix.encode("utf-8"))
        encoded_msg = msg.encode("utf-8")
        if len(encoded_msg) > max_msg_bytes:
            msg = encoded_msg[:max_msg_bytes].decode("utf-8", errors="ignore")

        self._send(f"PRIVMSG #{channel} :{msg}")
        self.log_message.emit(f"Bot: {msg}")

    def _handle_line(self, line: str, channel: str):
        if line.startswith("PING"):
            self._send(line.replace("PING", "PONG", 1))
            return

        match = re.match(r"^(?:@([^ ]+) )?:([^!]+)![^ ]+ PRIVMSG #([^ ]+) :(.+)$", line)
        if not match:
            return

        tags_str, sender, msg_channel, message = match.groups()
        message = message.strip()

        if not message.startswith("!"):
            return

        if not self._check_access(tags_str):
            return

        now = time.time()
        global_cooldown = config.TWITCH_BOT.get("global_cooldown_seconds", 1)
        command_cooldown = config.TWITCH_BOT.get("cooldown_seconds", 5)

        cmd = message.split()[0].lower()
        time_since_global = now - self.last_global_command_time
        time_since_cmd = now - self.last_command_times.get(cmd, 0.0)

        if time_since_global < global_cooldown or time_since_cmd < command_cooldown:
            return

        handled = False
        commands_cfg = config.TWITCH_BOT.get("commands", {})

        if cmd in ("!stats", "!bonkstats") and commands_cfg.get("stats", True):
            self._handle_stats(channel)
            handled = True
        elif cmd == "!session" and commands_cfg.get("session", True):
            self._handle_session(channel)
            handled = True
        elif cmd in ("!bans", "!banishes") and commands_cfg.get("bans", True):
            self._handle_bans(channel)
            handled = True
        elif cmd in ("!items", "!tracked") and commands_cfg.get("items", True):
            self._handle_items(channel)
            handled = True
        elif cmd == "!weapons" and commands_cfg.get("weapons", True):
            self._handle_weapons(channel)
            handled = True
        elif cmd == "!tomes" and commands_cfg.get("tomes", True):
            self._handle_tomes(channel)
            handled = True
        elif cmd in ("!chaos", "!chaostome") and commands_cfg.get("chaos", True):
            self._handle_chaos(channel)
            handled = True
        elif cmd == "!stages" and commands_cfg.get("stages", True):
            self._handle_stages(channel)
            handled = True
        elif cmd == "!powerups" and commands_cfg.get("powerups", True):
            self._handle_powerups(channel)
            handled = True
        elif cmd == "!scanner" and commands_cfg.get("scanner", True):
            self._handle_scanner(channel)
            handled = True
        elif cmd in ("!chests", "!chest") and commands_cfg.get("chests", False):
            self._handle_chests(channel)
            handled = True
        elif cmd in ("!presets", "!preset") and commands_cfg.get("presets", False):
            self._handle_presets(channel)
            handled = True
        elif cmd == "!disabled" and commands_cfg.get("disabled", False):
            self._handle_disabled(channel)
            handled = True
        elif cmd in ("!bonkhelp", "!bonkcmds", "!bonkcommands", "!bhelp") and commands_cfg.get(
            "bonkhelp",
            commands_cfg.get("commands", True),
        ):
            self._handle_commands(channel)
            handled = True

        if handled:
            self.last_global_command_time = now
            self.last_command_times[cmd] = now

    def _check_access(self, tags_str: str) -> bool:
        tier = config.TWITCH_BOT.get("access_tier", "Everyone")
        if tier == "Everyone":
            return True

        if not tags_str:
            return False

        tags = dict(part.split("=", 1) if "=" in part else (part, "") for part in tags_str.split(";"))
        badges = tags.get("badges", "")

        is_broadcaster = "broadcaster/" in badges
        is_mod = "moderator/" in badges
        is_vip = "vip/" in badges
        is_sub = "subscriber/" in badges or "founder/" in badges

        if is_broadcaster:
            return True

        if tier == "Mods & VIPs":
            return is_mod or is_vip
        elif tier == "Subs & Mods":
            return is_mod or is_sub

        return False

    def _stat_val(self, stats: dict, key: str) -> str:
        """Helper to safely extract a display value from stats dict."""
        if key in stats and stats[key] is not None:
            return getattr(stats[key], "display_value", "--")
        return "--"

    def _format_template(self, template_key: str, default_template: str, **kwargs) -> str:
        templates = config.TWITCH_BOT.get("templates", {})
        tpl = templates.get(template_key, default_template)
        if not tpl:
            tpl = default_template
        try:
            return SafeFormatter().format(tpl, **kwargs)
        except Exception as e:
            try:
                return SafeFormatter().format(default_template, **kwargs)
            except Exception:
                return f"Formatting error in '{template_key}' template: {e}"

    def _handle_stats(self, channel: str):
        snap = self.run_tracker.latest_snapshot()
        if not snap:
            self._send_chat(channel, "No active run detected.")
            return

        s = snap.stats
        stats_data = {}
        for name in s:
            stats_data[name] = self._stat_val(s, name)

        stat_abbrevs = {
            "Max HP": "HP",
            "HP Regen": "Regen",
            "Overheal": "Overheal",
            "Shield": "Shield",
            "Armor": "Armor",
            "Evasion": "Evasion",
            "Lifesteal": "Lifesteal",
            "Thorns": "Thorns",
            "Damage": "DMG",
            "Crit Chance": "Crit",
            "Crit Damage": "CritDMG",
            "Attack Speed": "AS",
            "Projectile Count": "Proj",
            "Projectile Bounces": "Bounces",
            "Size": "Size",
            "Projectile Speed": "ProjSpeed",
            "Duration": "Dur",
            "Damage to Elites": "EliteDMG",
            "Knockback": "KB",
            "Movement Speed": "MS",
            "Extra Jumps": "Jumps",
            "Jump Height": "JumpHeight",
            "Luck": "Luck",
            "Difficulty": "Diff",
            "Pickup Range": "Pickup",
            "XP Gain": "XP",
            "Gold Gain": "Gold",
            "Elite Spawn Increase": "ESI",
            "Powerup Multiplier": "PM",
            "Powerup Drop Chance": "PDC",
        }

        # Populate short abbreviations in stats_data
        for name, abbrev in stat_abbrevs.items():
            stats_data[abbrev] = stats_data.get(name, "--")

        selected = config.TWITCH_BOT.get("selected_stats", [])
        if not selected:
            selected = ["Damage", "XP Gain", "Luck", "Difficulty", "Powerup Drop Chance", "Elite Spawn Increase", "Powerup Multiplier", "Size"]

        parts = [f"{stat_abbrevs.get(name, name)}: {stats_data.get(name, '--')}" for name in selected]
        stats_data["stats"] = " | ".join(parts)

        msg = self._format_template(
            "stats",
            "Live Stats: DMG: {Damage} | XP: {XP Gain} | Luck: {Luck} | Size: {Size}",
            **stats_data
        )
        if len(msg) > 450:
            msg = msg[:447] + "..."
        self._send_chat(channel, msg)

    def _handle_bans(self, channel: str):
        snap = self.run_tracker.latest_snapshot()
        if not snap or not snap.banishes:
            self._send_chat(channel, "No banished items.")
            return

        banish_list = ", ".join(snap.banishes)
        count = len(snap.banishes)
        text = self._format_template(
            "bans",
            "Bans ({count}): {items}",
            count=count,
            items=banish_list
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_session(self, channel: str):
        formatter = getattr(self.session_stats_provider, "format_twitch_session_summary", None)
        if not callable(formatter):
            self._send_chat(channel, "Session stats are not available yet.")
            return
        text = str(formatter() or "").strip()
        if not text:
            self._send_chat(channel, "Session stats are not available yet.")
            return
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_disabled(self, channel: str):
        result = self.run_tracker.get_disabled_items()
        if not result.available:
            self._send_chat(channel, "Disabled items data is not available yet.")
            return

        disabled_in_game = result.items
        highlighted = config.TWITCH_BOT.get("highlighted_disabled_items", [])

        if highlighted:
            highlighted_by_folded_name = {item.casefold(): item for item in highlighted}
            active_disabled = [
                highlighted_by_folded_name[item.casefold()]
                for item in disabled_in_game
                if item.casefold() in highlighted_by_folded_name
            ]
        else:
            active_disabled = []

        if not active_disabled:
            items_str = "None"
        else:
            items_str = ", ".join(active_disabled)

        text = self._format_template(
            "disabled",
            "Disabled Items: {items}",
            items=items_str
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_items(self, channel: str):
        snap = self.run_tracker.latest_snapshot()
        if not snap or not snap.items:
            self._send_chat(channel, "No items found in current run.")
            return

        items_list = [item for item in snap.items if item]
        if not items_list:
            self._send_chat(channel, "No items found in current run.")
            return

        from run_summary import split_item_stack_suffix, normalize_item_name_for_display, normalize_item_name_for_rarity
        from gui_styles import ITEM_RARITY_BY_NAME

        legendary_items = []
        rare_items = []
        uncommon_items = []
        common_items = []
        unknown_items = []

        for item_str in items_list:
            name, suffix = split_item_stack_suffix(item_str)
            display_name = normalize_item_name_for_display(name)
            norm_name = normalize_item_name_for_rarity(display_name)
            rarity = ITEM_RARITY_BY_NAME.get(norm_name, "UNKNOWN")

            item_entry = {"name": display_name, "suffix": suffix, "full_str": f"{display_name}{suffix}"}
            if rarity == "LEGENDARY":
                legendary_items.append(item_entry)
            elif rarity == "RARE":
                rare_items.append(item_entry)
            elif rarity == "UNCOMMON":
                uncommon_items.append(item_entry)
            elif rarity == "COMMON":
                common_items.append(item_entry)
            else:
                unknown_items.append(item_entry)

        legendary_items.sort(key=lambda x: x["name"].lower())
        rare_items.sort(key=lambda x: x["name"].lower())
        uncommon_items.sort(key=lambda x: x["name"].lower())
        common_items.sort(key=lambda x: x["name"].lower())
        unknown_items.sort(key=lambda x: x["name"].lower())

        all_ordered = legendary_items + rare_items + uncommon_items + common_items + unknown_items
        full_list = [x["full_str"] for x in all_ordered]
        total_count = 0
        for x in all_ordered:
            suffix = x["suffix"]
            item_count = 1
            if suffix.startswith(" x") and suffix[2:].isdigit():
                item_count = int(suffix[2:])
            total_count += max(1, item_count)

        def get_formatted_text(items_str: str) -> str:
            return self._format_template(
                "items",
                "Items ({count}): {items}",
                count=total_count,
                items=items_str
            )

        # Try fully expanded
        full_text = get_formatted_text(", ".join(full_list))
        if len(full_text) <= 450:
            self._send_chat(channel, full_text)
            return

        # Collapse commons & unknowns
        collapsed_count = len(common_items) + len(unknown_items)
        if collapsed_count > 0:
            collapse_str = f"+{collapsed_count} Common"
            parts = [x["full_str"] for x in legendary_items + rare_items + uncommon_items] + [collapse_str]
            text = get_formatted_text(", ".join(parts))
            if len(text) <= 450:
                self._send_chat(channel, text)
                return

        # Collapse uncommons too
        parts = [x["full_str"] for x in legendary_items + rare_items]
        uncommon_count = len(uncommon_items)
        if uncommon_count > 0:
            parts.append(f"+{uncommon_count} Uncommon")
        if collapsed_count > 0:
            parts.append(f"+{collapsed_count} Common")
        text = get_formatted_text(", ".join(parts))
        if len(text) <= 450:
            self._send_chat(channel, text)
            return

        # Collapse rares too
        parts = [x["full_str"] for x in legendary_items]
        rare_count = len(rare_items)
        if rare_count > 0:
            parts.append(f"+{rare_count} Rare")
        if uncommon_count > 0:
            parts.append(f"+{uncommon_count} Uncommon")
        if collapsed_count > 0:
            parts.append(f"+{collapsed_count} Common")
        text = get_formatted_text(", ".join(parts))
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_weapons(self, channel: str):
        snap = self.run_tracker.latest_snapshot()
        if not snap or not snap.weapons:
            self._send_chat(channel, "No weapons found.")
            return

        parts = []
        for w in snap.weapons:
            stat_parts = []
            for stat_val in w.upgraded_stats.values():
                stat_parts.append(f"{stat_val.label}: {stat_val.display_value}")
            if stat_parts:
                parts.append(f"{w.name} Lv{w.level} [{', '.join(stat_parts)}]")
            else:
                parts.append(f"{w.name} Lv{w.level}")
        text = self._format_template(
            "weapons",
            "Weapons: {weapons}",
            weapons=" | ".join(parts)
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_tomes(self, channel: str):
        snap = self.run_tracker.latest_snapshot()
        if not snap or not snap.tomes:
            self._send_chat(channel, "No tomes found.")
            return

        parts = []
        for t in snap.tomes:
            if t.name == "Chaos":
                parts.append(f"{t.name} Lv{t.level}")
            elif t.value is not None:
                parts.append(f"{t.name} Lv{t.level} ({t.display_value})")
            else:
                parts.append(f"{t.name} Lv{t.level}")
        text = self._format_template(
            "tomes",
            "Tomes: {tomes}",
            tomes=", ".join(parts)
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_chaos(self, channel: str):
        chaos_level = self.run_tracker.chaos_tome_level()
        if chaos_level is None:
            self._send_chat(channel, "No Chaos Tome detected yet.")
            return

        parts = self.run_tracker.chaos_tome_summary_parts()
        if not parts:
            self._send_chat(channel, f"Chaos Tome Lv{chaos_level}: no rolls tracked yet.")
            return

        chaos_text = " | ".join(_round_chaos_summary_part(part) for part in parts)
        text = self._format_template(
            "chaos",
            "Chaos Tome Lv{level}: {chaos}",
            level=chaos_level,
            chaos=chaos_text,
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_stages(self, channel: str):
        rows = self.run_tracker.stage_summary_rows()
        if not rows:
            self._send_chat(channel, "No stage data available.")
            return

        parts = []
        for row in rows:
            kills = row.get("kills", "--")
            time_val = row.get("time", "--")
            if kills == "--" and time_val == "--":
                continue
            parts.append(f"{row['label']}: kills {kills}, time {time_val}")

        if not parts:
            self._send_chat(channel, "No stage data recorded yet.")
            return

        text = self._format_template(
            "stages",
            "{stages}",
            stages=" | ".join(parts)
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    @staticmethod
    def _format_seconds(value: float) -> str:
        return str(int(round(value)))

    def _handle_powerups(self, channel: str):
        snap = self.run_tracker.latest_snapshot()
        if not snap:
            self._send_chat(channel, "No active run detected.")
            return

        powerups_snapshot = getattr(self.run_tracker, "powerups_snapshot", None)
        format_powerups_summary = getattr(self.run_tracker, "format_powerups_summary", None)
        powerups_summary_text = getattr(self.run_tracker, "powerups_summary_text", None)
        if callable(powerups_snapshot) and callable(format_powerups_summary):
            try:
                snapshot = powerups_snapshot()
                if getattr(snapshot, "available", False) is True:
                    if callable(powerups_summary_text):
                        powerups_text = powerups_summary_text(include_left_word=True)
                        text = self._format_template(
                            "powerups",
                            "Powerups: {powerups} (PM {pm})",
                            powerups=powerups_text,
                            standard_duration=self._format_seconds(
                                getattr(snapshot, "standard_duration_seconds", 0.0) or 0.0
                            ),
                            clock_duration=self._format_seconds(
                                getattr(snapshot, "clock_duration_seconds", 0.0) or 0.0
                            ),
                            pm=getattr(snapshot, "powerup_multiplier_display", "--"),
                        )
                    else:
                        text = format_powerups_summary(include_left_word=True)
                    if len(text) > 450:
                        text = text[:447] + "..."
                    self._send_chat(channel, text)
                    return
            except Exception:
                pass

        stat = snap.stats.get("Powerup Multiplier") if getattr(snap, "stats", None) else None
        try:
            powerup_multiplier = float(getattr(stat, "value", None))
        except (TypeError, ValueError):
            powerup_multiplier = float("nan")

        if not isfinite(powerup_multiplier):
            self._send_chat(channel, "Powerup Multiplier is not available.")
            return

        standard_duration = 15.0 * powerup_multiplier
        clock_duration = 12.0 * powerup_multiplier
        text = self._format_template(
            "powerups",
            "Powerups: {powerups} (PM {pm})",
            powerups=(
                "none active | Durations: "
                f"standard {self._format_seconds(standard_duration)}s, "
                f"clock {self._format_seconds(clock_duration)}s"
            ),
            standard_duration=self._format_seconds(standard_duration),
            clock_duration=self._format_seconds(clock_duration),
            pm=getattr(stat, "display_value", f"{self._format_seconds(powerup_multiplier)}x"),
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_scanner(self, channel: str):
        text = self._format_template(
            "scanner",
            "Download it here: {github_url} | Support the creator here: {patreon_url} | Try !bonkhelp.",
            patreon_url=config.PATREON_SUPPORT_URL,
            github_url=config.GITHUB_REPOSITORY_URL,
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_chests(self, channel: str):
        has_active_run = getattr(self.run_tracker, "has_active_run", None)
        is_active = has_active_run() if callable(has_active_run) else bool(self.run_tracker.latest_snapshot())
        if not is_active:
            self._send_chat(channel, "No active run detected.")
            return

        get_chest_stats = getattr(self.run_tracker, "get_chest_stats", None)
        if callable(get_chest_stats):
            stats = get_chest_stats()
            keys_count = stats.keys_count
            paid_opens = stats.paid
            key_procs = stats.key_procs
            free_chests = stats.free_chests
            chests_by_stage = stats.opened_by_stage
            total_by_stage = stats.total_by_stage
            total_opened = stats.total_opened
            total_opened_is_minimum = stats.total_opened_is_minimum
            total_chests = stats.total_chests
            normal_opened = stats.normal_opened
            expected_procs = (
                f"{stats.expected_key_procs:.1f}"
                if stats.expected_available
                else "--"
            )
        else:
            chests_opened, chests_total, keys_count, key_procs, chests_by_stage, total_by_stage = self.run_tracker.get_chests_and_keys()
            paid_opens = max(0, chests_opened - key_procs)
            free_chests = 0
            total_opened = sum(chests_by_stage.values()) if chests_by_stage else chests_opened
            total_opened_is_minimum = False
            total_chests = sum(total_by_stage.values()) if total_by_stage else chests_total
            normal_opened = paid_opens + key_procs
            expected_procs = "--"

        stage_parts = []
        for stage, count in sorted(chests_by_stage.items()):
            stage_total = total_by_stage.get(stage, 0)
            if int(count) < 0:
                stage_parts.append(f"T{stage}:--/{stage_total}")
            else:
                stage_parts.append(f"T{stage}:{count}/{stage_total}")
        opened_text = "--" if total_opened is None else str(total_opened)
        if total_opened is not None and total_opened_is_minimum:
            opened_text += "+"
        total_text = str(total_chests)
        stages_str = " ".join(stage_parts) if stage_parts else f"T1:{opened_text}/{total_text}"

        if keys_count <= 0:
            chance_val = 0.0
        else:
            chance_val = (0.10 * keys_count) / (0.10 * keys_count + 1.0) * 100.0
        chance_str = f"{chance_val:.1f}%"
        proc_rate = (key_procs / normal_opened * 100.0) if normal_opened > 0 else 0.0
        proc_rate_str = f"{proc_rate:.1f}%"
        free_text = "--" if free_chests is None else str(free_chests)
        text = self._format_template(
            "chests",
            "Chests: {stages} | Total: {opened}/{total} | Paid: {paid} | Key Procs: {procs}/{normal} ({proc_rate}) | Expected: {expected} | Free Chests: {free} | Keys: {keys} ({chance})",
            stages=stages_str,
            opened=opened_text,
            total=total_text,
            paid=paid_opens,
            keys=keys_count,
            chance=chance_str,
            procs=key_procs,
            normal=normal_opened,
            proc_rate=proc_rate_str,
            expected=expected_procs,
            free=free_text,
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_presets(self, channel: str):
        mode = getattr(config, "EVALUATION_MODE", "templates")
        
        if mode == "templates":
            active_names = getattr(config, "ACTIVE_TEMPLATES", [])
            templates_list = getattr(config, "TEMPLATES", [])
            
            # Create a lookup map for easy access
            templates_by_name = {t["name"]: t for t in templates_list if "name" in t}
            
            active_parts = []
            for name in active_names:
                template = templates_by_name.get(name)
                if template:
                    conds = []
                    sm_total = template.get("sm_total", 0)
                    shady = template.get("shady", 0)
                    moai = template.get("moai", 0)
                    micro = template.get("micro", 0)
                    boss = template.get("boss", 0)

                    if shady > 0 or moai > 0:
                        if shady > 0:
                            conds.append(f"S:{shady}")
                        if moai > 0:
                            conds.append(f"M:{moai}")
                    elif sm_total > 0:
                        conds.append(f"S+M:{sm_total}")
                    if micro > 0:
                        conds.append(f"Mic:{micro}")
                    if boss > 0:
                        conds.append(f"B:{boss}")

                    conds_str = ", ".join(conds) if conds else "Any"
                    active_parts.append(f"{name}({conds_str})")
                else:
                    active_parts.append(name)
                    
            if not active_parts:
                msg = "[Reroller] Mode: Templates | Active: None"
            else:
                msg = f"[Reroller] Mode: Templates | Active: {', '.join(active_parts)}"
                
        elif mode == "scores":
            scores_sys = getattr(config, "SCORES_SYSTEM", {})
            active_tiers = scores_sys.get("active_tiers", [])
            thresholds = scores_sys.get("thresholds", {})
            weights = scores_sys.get("weights", {})
            
            tier_parts = [f"{tier} ({thresholds.get(tier, 0.0):.1f}+)" for tier in active_tiers]
            
            key_names = {"moais": "Moais", "shady": "Shady", "boss": "Boss", "magnet": "Magnet"}
            weight_parts = [f"{key_names.get(k, k.capitalize())}={v}" for k, v in weights.items()]
            
            tiers_str = ", ".join(tier_parts) if tier_parts else "None"
            weights_str = ", ".join(weight_parts) if weight_parts else "None"
            
            msg = f"[Reroller] Mode: Scores | Active Tiers: {tiers_str} | Weights: {weights_str}"
        else:
            msg = f"[Reroller] Mode: Unknown ({mode})"
            
        self._send_chat(channel, msg)

    @staticmethod
    def _enabled_command_names() -> list[str]:
        commands_cfg = config.TWITCH_BOT.get("commands", {})
        cmd_mapping = [
            ("stats", "!stats"),
            ("session", "!session"),
            ("bans", "!bans"),
            ("items", "!items"),
            ("weapons", "!weapons"),
            ("tomes", "!tomes"),
            ("chaos", "!chaos"),
            ("stages", "!stages"),
            ("powerups", "!powerups"),
            ("scanner", "!scanner"),
            ("chests", "!chests"),
            ("presets", "!presets"),
            ("disabled", "!disabled"),
        ]
        command_defaults = config.DEFAULT_TWITCH_BOT["commands"]
        enabled_cmds = [
            display_name
            for key, display_name in cmd_mapping
            if commands_cfg.get(key, command_defaults[key])
        ]
        if commands_cfg.get("bonkhelp", command_defaults["bonkhelp"]):
            enabled_cmds.append("!bonkhelp")

        return enabled_cmds

    def _handle_commands(self, channel: str):
        enabled_cmds = self._enabled_command_names()

        if not enabled_cmds:
            msg = "No Twitch bot commands are currently enabled."
        else:
            commands_list = ', '.join(enabled_cmds)
            msg = self._format_template(
                "bonkhelp",
                "Available commands: {commands_list}",
                commands_list=commands_list
            )
            
        self._send_chat(channel, msg)

    def _check_commands_announcement(self, channel: str, now: float | None = None):
        if now is None:
            now = time.monotonic()

        enabled = bool(config.TWITCH_BOT.get("commands_announcements", False))
        if not enabled:
            self._last_commands_announcement_at = now
            self._commands_announcements_were_enabled = False
            return

        if not self._commands_announcements_were_enabled:
            self._commands_announcements_were_enabled = True
            self._last_commands_announcement_at = now
            return

        interval_minutes = max(
            1,
            int(config.TWITCH_BOT.get("commands_announcement_interval_minutes", 30)),
        )
        if self._last_commands_announcement_at is None:
            self._last_commands_announcement_at = now
            return

        if now - self._last_commands_announcement_at < interval_minutes * 60:
            return

        self._last_commands_announcement_at = now
        if not self._enabled_command_names():
            return
        self._handle_commands(channel)

    def _check_stage_transitions(self, channel: str):
        if not config.TWITCH_BOT.get("stage_announcements", True):
            return

        run_id, stage_index = self.run_tracker.run_identity()

        if run_id != self._last_run_id:
            self._last_run_id = run_id
            self._last_stage_index = stage_index
            return

        if stage_index > self._last_stage_index:
            prev_stage = self._last_stage_index
            self._last_stage_index = stage_index

            rows = self.run_tracker.stage_summary_rows()
            prev_row = None
            for row in rows:
                if row.get("label") == f"Stage {prev_stage}":
                    prev_row = row
                    break

            if prev_row:
                kills = prev_row.get("kills", "--")
                time_val = prev_row.get("time", "--")
                msg = self._format_template(
                    "stage_announcement",
                    "🚩 Stage {stage} completed! Kills: {kills} | Time: {time}. Moving to Stage {next_stage}! 🚩",
                    stage=prev_stage,
                    kills=kills,
                    time=time_val,
                    next_stage=stage_index
                )
                self._send_chat(channel, msg)
            else:
                msg = self._format_template(
                    "stage_announcement_simple",
                    "🚩 Moving to Stage {next_stage}! 🚩",
                    next_stage=stage_index
                )
                self._send_chat(channel, msg)
