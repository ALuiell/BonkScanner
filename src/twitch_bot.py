import random
import socket
import ssl
import threading
import time
import re
import string
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from PySide6.QtCore import QThread, Signal
from app import config
from core import run_summary
from core.luck_rarity import game_rarity_name
from core.stat_labels import STAT_LABEL_ABBREVIATIONS, abbreviate_stat_label
from core.template_conditions import format_template_conditions
from core.tracker.items import fold_item_match_name
from infra.twitch_credentials import get_twitch_oauth_token
from core.stats.formatters import format_chaos_tome_stat_delta, format_shrine_stat_delta
from projections.twitch import (
    format_kps,
    format_luck,
    format_powerups,
    truncate_chat_message,
)
from projections.build_progression import format_twitch_build


COMMAND_COOLDOWN_KEYS = {
    "!bonkstats": "!stats",
    "!banishes": "!bans",
    "!tracked": "!items",
    "!chaostome": "!chaos",
    "!chest": "!chests",
    "!preset": "!presets",
    "!bonkcmds": "!bonkhelp",
    "!bonkcommands": "!bonkhelp",
    "!bhelp": "!bonkhelp",
}


# The One Ring reaches this file under four spellings: the enum's `GoldenRing`,
# the scanner's `Golden Ring`, the display name the memory client formats
# (`The One Ring`) and the game's own `No Implementation` placeholder. Folding
# through the tracker's matcher collapses all of them onto one key instead of
# keeping a list here that would drift from `core/item_metadata.py`.
ONE_RING_MATCH_NAME = fold_item_match_name("GoldenRing")


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

    def __init__(self, run_tracker, parent=None, session_snapshot=None, build_progression_service=None):
        super().__init__(parent)
        self.run_tracker = run_tracker
        self.session_snapshot = session_snapshot
        self.build_progression_service = build_progression_service
        self.running = False
        self._stop_event = threading.Event()
        self.sock = None
        self.last_command_time = 0
        self._last_run_id = None
        self._last_commands_announcement_at = None
        self._commands_announcements_were_enabled = False
        self._one_ring_run_id = None
        # How many rings this run has already been announced for, not a bool:
        # the duplicate pool needs to know that ring 2 is new while ring 1 is
        # old, and a bool cannot say that.
        self._one_ring_announced_count = 0
        # Phrases already drawn from each pool *in the current run*, cleared
        # when the run changes. The absolute half of the two exclusions in
        # `_draw_from_pool`; see its docstring for how the two compose.
        self._pool_lines_used_this_run: dict[str, list[str]] = {}
        self.last_command_times: dict[str, float] = {}
        self.last_global_command_time: float = 0.0

    def _runtime_snapshot(self):
        return self.run_tracker.runtime_snapshot()

    def run(self):
        # ``QThread.start()`` only schedules this method.  The window can close
        # and call ``stop()`` before the new native thread gets to its first
        # instruction.  Clearing the event here used to lose that cancellation:
        # ``run`` set ``running`` back to true, connected to Twitch, and survived
        # the bounded shutdown wait until Qt destroyed a still-running QThread.
        # On Windows that Qt abort is reported by Event Viewer as
        # ucrtbase.dll / 0xC0000409.
        self.running = True
        if self._stop_event.is_set():
            self.running = False
            return
        bot_cfg = config.TWITCH_BOT
        username = str(bot_cfg.get("username") or "").strip().lstrip("#").lower()
        target_channel = self._target_channel(bot_cfg)
        token = get_twitch_oauth_token()

        if not username or not target_channel or not token:
            self.status_updated.emit("Error: Missing credentials")
            self.running = False
            return

        import time
        while self.running and not self._stop_event.is_set():
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
                runtime = self._runtime_snapshot()
                self._last_run_id, self._last_stage_index = runtime.run_id, runtime.current_stage_index

                while self.running and not self._stop_event.is_set():
                    self._check_stage_transitions(target_channel)
                    self._check_one_ring_announcement(target_channel)
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

            if self.running and not self._stop_event.is_set():
                self.log_message.emit("Reconnecting in 2 seconds...")
                self.status_updated.emit("Reconnecting...")
                self._stop_event.wait(2)

        self.running = False

    @staticmethod
    def _target_channel(bot_cfg: dict) -> str:
        username = str(bot_cfg.get("username") or "").strip().lstrip("#").lower()
        target_channel = str(bot_cfg.get("target_channel") or "").strip().lstrip("#").lower()
        return target_channel or username

    def stop(self):
        self.running = False
        self._stop_event.set()
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
        cooldown_key = COMMAND_COOLDOWN_KEYS.get(cmd, cmd)
        time_since_global = now - self.last_global_command_time
        time_since_cmd = now - self.last_command_times.get(cooldown_key, 0.0)

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
        elif cmd == "!shrines" and commands_cfg.get("shrines", True):
            self._handle_shrines(channel)
            handled = True
        elif cmd == "!stages" and commands_cfg.get("stages", True):
            self._handle_stages(channel)
            handled = True
        elif cmd == "!powerups" and commands_cfg.get("powerups", True):
            self._handle_powerups(channel)
            handled = True
        elif cmd == "!kps" and commands_cfg.get("kps", True):
            self._handle_kps(channel)
            handled = True
        elif cmd == "!build" and commands_cfg.get("build", True):
            self._handle_build(channel)
            handled = True
        elif cmd == "!scanner" and commands_cfg.get("scanner", True):
            self._handle_scanner(channel)
            handled = True
        elif cmd in ("!chests", "!chest") and commands_cfg.get("chests", False):
            self._handle_chests(channel)
            handled = True
        elif cmd == "!luck" and commands_cfg.get("luck", False):
            self._handle_luck(channel)
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
            self.last_command_times[cooldown_key] = now

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
            stat = stats[key]
            return getattr(stat, "capped_display_value", getattr(stat, "display_value", "--"))
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
        snap = self._runtime_snapshot().latest_snapshot
        if not snap:
            self._send_chat(channel, "No active run detected.")
            return

        s = snap.stats
        stats_data = {}
        for name in s:
            stats_data[name] = self._stat_val(s, name)

        # Populate short abbreviations in stats_data
        for name, abbrev in STAT_LABEL_ABBREVIATIONS.items():
            stats_data[abbrev] = stats_data.get(name, "--")

        selected = config.TWITCH_BOT.get("selected_stats", [])
        if not selected:
            selected = ["Damage", "XP Gain", "Luck", "Difficulty", "Powerup Drop Chance", "Elite Spawn Increase", "Powerup Multiplier", "Size"]

        parts = [f"{abbreviate_stat_label(name)}: {stats_data.get(name, '--')}" for name in selected]
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
        snap = self._runtime_snapshot().latest_snapshot
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
        if not callable(self.session_snapshot):
            self._send_chat(channel, "Session stats are not available yet.")
            return
        snapshot = self.session_snapshot() or {}
        rerolls = max(0, int(snapshot.get("rerolls", 0) or 0))
        seeds_found = max(0, int(snapshot.get("seeds_found", 0) or 0))
        seed_rate = f"{(seeds_found / rerolls * 100.0) if rerolls > 0 else 0.0:.2f}"
        tracked_parts = []
        for row in snapshot.get("tracked_rows", ()):
            percent = row.get("percent")
            if percent is None:
                tracked_parts.append(f"{row['label']} {row['count']}")
            else:
                tracked_parts.append(f"{row['label']} {row['count']} ({percent:.2f}%)")
        text = self._format_template(
            "session",
            "{resets} resets, {seeds} seeds found ({seed_rate}%) | Tracked Items: {items}",
            resets=rerolls,
            seeds=seeds_found,
            seed_rate=seed_rate,
            items=", ".join(tracked_parts) if tracked_parts else "None",
        ).strip()
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_disabled(self, channel: str):
        runtime = self._runtime_snapshot()
        snap = runtime.latest_snapshot
        legacy_disabled = getattr(runtime, "legacy_disabled", None)
        if legacy_disabled is not None:
            if not legacy_disabled.available:
                self._send_chat(channel, "Disabled items data is not available yet.")
                return
            disabled_in_game = legacy_disabled.items
        elif not snap or not snap.disabled_items_available:
            self._send_chat(channel, "Disabled items data is not available yet.")
            return
        else:
            disabled_in_game = snap.disabled_items
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
        snap = self._runtime_snapshot().latest_snapshot
        if not snap or not snap.items:
            self._send_chat(channel, "No items found in current run.")
            return

        items_list = [item for item in snap.items if item]
        if not items_list:
            self._send_chat(channel, "No items found in current run.")
            return

        from core.run_summary import split_item_stack_suffix, normalize_item_name_for_display, normalize_item_name_for_rarity
        from core.item_metadata import ITEM_RARITY_BY_NAME

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
            collapse_str = f"+{collapsed_count} {game_rarity_name('COMMON')}"
            parts = [x["full_str"] for x in legendary_items + rare_items + uncommon_items] + [collapse_str]
            text = get_formatted_text(", ".join(parts))
            if len(text) <= 450:
                self._send_chat(channel, text)
                return

        # Collapse uncommons too
        parts = [x["full_str"] for x in legendary_items + rare_items]
        uncommon_count = len(uncommon_items)
        if uncommon_count > 0:
            parts.append(f"+{uncommon_count} {game_rarity_name('UNCOMMON')}")
        if collapsed_count > 0:
            parts.append(f"+{collapsed_count} {game_rarity_name('COMMON')}")
        text = get_formatted_text(", ".join(parts))
        if len(text) <= 450:
            self._send_chat(channel, text)
            return

        # Collapse rares too
        parts = [x["full_str"] for x in legendary_items]
        rare_count = len(rare_items)
        if rare_count > 0:
            parts.append(f"+{rare_count} {game_rarity_name('RARE')}")
        if uncommon_count > 0:
            parts.append(f"+{uncommon_count} {game_rarity_name('UNCOMMON')}")
        if collapsed_count > 0:
            parts.append(f"+{collapsed_count} {game_rarity_name('COMMON')}")
        text = get_formatted_text(", ".join(parts))
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_weapons(self, channel: str):
        snap = self._runtime_snapshot().latest_snapshot
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
        snap = self._runtime_snapshot().latest_snapshot
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
        chaos = self._runtime_snapshot().chaos_tome
        if chaos is None:
            self._send_chat(channel, "No Chaos Tome detected yet.")
            return

        parts = list(getattr(chaos, "legacy_parts", ())) or [
            f"{abbreviate_stat_label(stat.label)} "
            f"{format_chaos_tome_stat_delta(stat.label, stat.value, stat.value_format)}"
            for stat in chaos.stats
        ]
        if not parts:
            self._send_chat(channel, f"Chaos Tome Lv{chaos.level}: no rolls tracked yet.")
            return

        chaos_text = " | ".join(_round_chaos_summary_part(part) for part in parts)
        text = self._format_template(
            "chaos",
            "Chaos Tome Lv{level}: {chaos}",
            level=chaos.level,
            chaos=chaos_text,
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_shrines(self, channel: str):
        shrines = getattr(self._runtime_snapshot(), "shrines", None)
        if shrines is None:
            self._send_chat(channel, "No Charge Shrine data detected yet.")
            return

        charged = max(0, int(getattr(shrines, "charged", 0) or 0))
        selected = max(0, int(getattr(shrines, "selected", 0) or 0))
        pending = max(0, int(getattr(shrines, "pending", 0) or 0))
        parts = []
        for stat in getattr(shrines, "stats", ()) or ():
            label = abbreviate_stat_label(str(getattr(stat, "label", "")))
            delta = format_shrine_stat_delta(
                str(getattr(stat, "label", "")),
                getattr(stat, "value", None),
                getattr(stat, "value_format", None),
            )
            parts.append(f"{label} {delta}")

        template_values = {
            # Legacy placeholders remain available for user-defined templates.
            "stage": "--",
            "charged": charged,
            "total": "--",
            "selected": selected,
            "rewards": selected,
            "pending": pending,
        }
        if not parts:
            empty = "no bonuses tracked yet"
            if pending:
                empty += f" ({pending} reward{'s' if pending != 1 else ''} pending)"
            self._send_chat(
                channel,
                self._format_template(
                    "shrines",
                    "Shrines: {shrines}",
                    shrines=empty,
                    **template_values,
                ),
            )
            return

        chunks: list[list[str]] = []
        current: list[str] = []
        for part in parts:
            candidate = current + [part]
            rendered = self._format_template(
                "shrines",
                "Shrines: {shrines}",
                shrines=" | ".join(candidate),
                **template_values,
            )
            if current and len(rendered) > 450:
                chunks.append(current)
                current = [part]
            else:
                current = candidate
        if current:
            chunks.append(current)
        for chunk in chunks:
            text = self._format_template(
                "shrines",
                "Shrines: {shrines}",
                shrines=" | ".join(chunk),
                **template_values,
            )
            self._send_chat(channel, truncate_chat_message(text))

    def _handle_stages(self, channel: str):
        rows = self._runtime_snapshot().stage_summary
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
        runtime = self._runtime_snapshot()
        snap = runtime.latest_snapshot
        if not snap:
            self._send_chat(channel, "No active run detected.")
            return

        # `runtime.powerups` is emptied the moment its 1.5 s TTL lapses, and an
        # empty snapshot looks exactly like one that read successfully and
        # found nothing. The overlay never notices -- it repaints 4x a second
        # and the next tick corrects it -- but chat gets one answer and keeps
        # it, so a single late read used to be published as "none active".
        # `powerups_recent` keeps the last read for a few seconds longer and
        # flags it, which is what separates the two cases here.
        powerups = runtime.powerups_recent
        if powerups.available is True or powerups.stale is True:
            text = self._format_template(
                "powerups", "Powerups: {powerups} (PM {pm})",
                powerups=format_powerups(powerups),
                standard_duration=self._format_seconds(powerups.standard_duration_seconds or 0.0),
                clock_duration=self._format_seconds(powerups.clock_duration_seconds or 0.0),
                pm=powerups.powerup_multiplier_display,
            )
            if powerups.stale is True:
                text = f"{text} (updating...)"
            self._send_chat(channel, text[:447] + "..." if len(text) > 450 else text)
            return

        # No usable read at all. The durations below come from the player
        # stats, which are read on their own schedule, so they are still worth
        # reporting -- but they say nothing about what is active, and this
        # branch must not pretend otherwise.
        stat = snap.stats.get("Powerup Multiplier") if getattr(snap, "stats", None) else None
        try:
            powerup_multiplier = float(getattr(stat, "value", None))
        except (TypeError, ValueError):
            powerup_multiplier = float("nan")

        if not isfinite(powerup_multiplier):
            self._send_chat(channel, "Powerup tracking is not available right now.")
            return

        standard_duration = 15.0 * powerup_multiplier
        clock_duration = 12.0 * powerup_multiplier
        text = self._format_template(
            "powerups",
            "Powerups: {powerups} (PM {pm})",
            powerups=(
                "refreshing, try again in a moment | Durations: "
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
            github_url=f"{config.GITHUB_REPOSITORY_URL}/latest",
        )
        if len(text) > 450:
            text = text[:447] + "..."
        self._send_chat(channel, text)

    def _handle_chests(self, channel: str):
        runtime = self._runtime_snapshot()
        is_active = bool(runtime.latest_snapshot)
        if not is_active:
            self._send_chat(channel, "No active run detected.")
            return

        if runtime.latest_snapshot is not None:
            stats = runtime.chest_stats
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
                if stats.expected_complete
                else "--"
            )

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

    def _handle_luck(self, channel: str):
        runtime = self._runtime_snapshot()
        if not runtime.latest_snapshot:
            self._send_chat(channel, "No active run detected.")
            return
        self._send_chat(
            channel, truncate_chat_message(format_luck(runtime, self._format_template))
        )

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
                    active_parts.append(f"{name}({format_template_conditions(template)})")
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

            key_names = {
                "moais": "Moais",
                "shady": "Shady",
                "boss": "Boss",
                "magnet": "Magnet",
                "challenges": "Challenges",
            }
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
            ("shrines", "!shrines"),
            ("stages", "!stages"),
            ("powerups", "!powerups"),
            ("scanner", "!scanner"),
            ("chests", "!chests"),
            ("luck", "!luck"),
            ("presets", "!presets"),
            ("disabled", "!disabled"),
            ("kps", "!kps"),
            ("build", "!build"),
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

    def _handle_kps(self, channel: str):
        runtime = self._runtime_snapshot()
        self._send_chat(channel, truncate_chat_message(format_kps(runtime, self._format_template)))

    def _handle_build(self, channel: str):
        if self.build_progression_service is None:
            self._send_chat(channel, "Build Progression is not available.")
            return
        snapshot = self.build_progression_service.snapshot()
        if not snapshot.available:
            self._send_chat(channel, "No active run detected.")
            return
        values = format_twitch_build(snapshot)
        if not snapshot.configured:
            self._send_chat(channel, values["requirements"])
            return
        default = config.DEFAULT_TWITCH_BOT["templates"]["build"]
        header_values = dict(values)
        header_values["requirements"] = ""
        header_values["failed_requirements"] = ""
        header_values["late_requirements"] = ""
        header_values["remaining_suffix"] = ""
        header = self._format_template("build", default, **header_values).strip()
        # Older saved defaults placed the separator in the template itself.
        # Lists now have their own chat messages, so do not leave a dangling bar
        # on the progress-only header.
        header = header.rstrip(" |;")
        remaining = str(values.get("requirements") or "").strip()
        failed = str(values.get("failed_requirements") or "").strip()
        late = str(values.get("late_requirements") or "").strip()
        first_message = " | ".join(
            part for part in (header, remaining, failed, late) if part
        )
        self._send_chat(channel, truncate_chat_message(first_message))
        completed = str(values.get("completed_requirements") or "").strip()
        if completed:
            self._send_chat(channel, truncate_chat_message(completed))

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

        runtime = self._runtime_snapshot()
        run_id = runtime.run_id
        stage_index = runtime.current_stage_index
        rows = runtime.stage_summary

        if run_id != self._last_run_id:
            self._last_run_id = run_id
            self._last_stage_index = stage_index
            return

        if stage_index > self._last_stage_index:
            prev_stage = self._last_stage_index
            self._last_stage_index = stage_index

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

    @staticmethod
    def _one_ring_count(items) -> int:
        """How many copies of The One Ring the inventory holds.

        A count rather than a boolean because the announcer distinguishes the
        first ring from a duplicate, and because `x2` is one entry in the item
        list rather than two.
        """
        for name in items or ():
            stack_name, suffix = run_summary.split_item_stack_suffix(str(name))
            if fold_item_match_name(stack_name) != ONE_RING_MATCH_NAME:
                continue
            return int(suffix[2:]) if suffix else 1
        return 0

    def _pool_lines(self, template_key: str, default_pool: str) -> list[str]:
        """A template read as a pool: one phrase per line, blanks dropped.

        A single-line template is a pool of one, which is what makes the
        original one-phrase config a valid pool without migrating anything.
        An all-blank pool falls back to the default rather than going silent --
        a cleared field is far more likely a mistake than a request for no
        announcement, and the checkbox is how you ask for that.
        """
        templates = config.TWITCH_BOT.get("templates", {})
        lines = [line.strip() for line in str(templates.get(template_key) or "").splitlines()]
        lines = [line for line in lines if line]
        if lines:
            return lines
        return [line.strip() for line in default_pool.splitlines() if line.strip()]

    @staticmethod
    def _recent_pool_lines(template_key: str) -> list[str]:
        recent = config.TWITCH_BOT.get("announcer_recent_lines") or {}
        return [str(line) for line in recent.get(template_key) or ()]

    @staticmethod
    def _remember_pool_line(template_key: str, line: str, *, keep: int) -> None:
        """Persist the draw so the exclusion survives a restart.

        `config.user_config["TWITCH_BOT"]` **is** `config.TWITCH_BOT` (bound at
        [app/config.py:1050]), so mutating the dict and saving is enough, and
        `save_config` takes `config_lock` -- writing it from the bot thread does
        not race the GUI's own saves.
        """
        recent = config.TWITCH_BOT.setdefault("announcer_recent_lines", {})
        history = [str(item) for item in recent.get(template_key) or () if item != line]
        history.append(line)
        recent[template_key] = history[-max(1, keep):]
        try:
            config.save_config(config.user_config)
        except Exception:
            # The exclusion is a nicety. Failing to persist it must never cost
            # the announcement it was drawn for.
            pass

    def _draw_from_pool(self, template_key: str, default_pool: str) -> str:
        """Draw one phrase at random under two exclusions of different scope.

        Flat odds, no weights. The One Ring turns up on the order of once a
        session, so a "rare" line at a tenth of the weight would simply never be
        read -- with an event this infrequent the useful knob is *variety per
        sighting*, which is what equal odds plus an exclusion give.

        **Within one run the exclusion is absolute**: nothing repeats until
        every variant has been spent, then the cycle starts over. This is the
        exclusion that matters for the duplicate pool, where one run can draw
        several times.

        **Across runs it is a soft preference**: the last ``len(pool) // 2``
        draws are avoided when possible, and that memory is persisted, so a new
        run does not open by repeating what the last one said and a restart does
        not forget. It yields to the run-scoped rule whenever the two disagree
        -- long enough to be felt, never long enough to force a repeat inside a
        run or to corner a hand-shortened pool.

        Both memories hold phrase text, so editing a line simply makes it a line
        nobody has drawn.
        """
        lines = self._pool_lines(template_key, default_pool)
        if not lines:
            return ""

        used_this_run = self._pool_lines_used_this_run.setdefault(template_key, [])
        candidates = [line for line in lines if line not in used_this_run]
        if not candidates:
            # Every variant spent in this run. Start the cycle over rather than
            # going silent -- and clear the record, so the next pass through the
            # pool is a fresh permutation instead of a locked-out set.
            used_this_run.clear()
            candidates = list(lines)

        recent = set(self._recent_pool_lines(template_key))
        chosen = random.choice(
            [line for line in candidates if line not in recent] or candidates
        )
        used_this_run.append(chosen)
        self._remember_pool_line(template_key, chosen, keep=len(lines) // 2)
        return chosen

    def _format_pool_message(self, template_key: str, default_pool: str, **tags) -> str:
        """Draw one line from the pool and fill its tags.

        Not `_format_template`: that reads the whole template back out of the
        config, which for a pool is every phrase at once -- the draw has to
        happen first, and the drawn line is what gets formatted. `SafeFormatter`
        renders an unknown tag as `--`, so only malformed braces can fail here.
        """
        line = self._draw_from_pool(template_key, default_pool)
        if not line:
            return ""
        try:
            return SafeFormatter().format(line, **tags)
        except Exception as exc:
            return f"Formatting error in '{template_key}' template: {exc}"

    @staticmethod
    def _announcer_inventory(runtime) -> tuple[str, ...] | None:
        """The freshest inventory this runtime view can offer, or ``None``.

        ``fast_items`` is the 1 s ``PASSIVE_ITEMS`` pass and is what the ring
        should be caught on; ``latest_snapshot.items`` is the same source
        re-published on the 10 s full snapshot, and is the fallback for the
        window where the fast read is stale or the app attached mid-tick.

        ``None`` means no usable read at all -- which is *not* an empty
        inventory, and the difference is load-bearing for the caller.
        """
        fast_items = getattr(runtime, "fast_items", None)
        if fast_items is not None:
            return tuple(fast_items)
        snapshot = runtime.latest_snapshot
        if snapshot is None or not snapshot.items_available:
            return None
        return tuple(snapshot.items or ())

    def _check_one_ring_announcement(self, channel: str):
        """Announce The One Ring: once for the first, once per duplicate, each
        from its own pool.

        Level-triggered on the inventory rather than edge-triggered on a pickup
        event, and deliberately: an edge would have to survive a torn read, a
        skipped pass or a reconnect to fire at all, while "the bag holds more
        rings than have been announced" is true on every tick until it is
        answered.

        **Map-agnostic.** This shipped Forest/Desert-only, gated on a fresh
        `powerup_map_context` that was not Graveyard, purely to keep the first
        version small. Nothing here ever depended on the map -- the inventory
        and `run_id` are the same facts everywhere, and `run_id` in particular
        holds across Graveyard's crypt and boss-room transitions, so the latch
        cannot double-fire there. The gate is gone rather than inverted, which
        also removes the wait for a map context that no longer decides
        anything.
        """
        if not config.TWITCH_BOT.get("one_ring_announcements", False):
            return

        runtime = self._runtime_snapshot()
        items = self._announcer_inventory(runtime)
        if items is None:
            # No usable read. Not an empty inventory, and in particular it must
            # not be allowed to seed a run below as "no rings": that is how a
            # failed first read turns into an announcement for a ring the player
            # had picked up before the bot was watching.
            return
        ring_count = self._one_ring_count(items)

        if runtime.run_id != self._one_ring_run_id:
            # First sight of this run. Whatever the inventory already holds was
            # not picked up under the bot's watch -- seeding from it is what
            # stops a mid-run connect (or a reconnect after a dropped socket)
            # from announcing a ring the chat was already told about.
            self._one_ring_run_id = runtime.run_id
            self._one_ring_announced_count = ring_count
            # A new run is a new audience for the same jokes.
            self._pool_lines_used_this_run.clear()
            return

        if ring_count <= self._one_ring_announced_count:
            return

        first_ring = self._one_ring_announced_count == 0
        self._one_ring_announced_count = ring_count
        template_key = (
            "one_ring_announcement" if first_ring else "one_ring_duplicate_announcement"
        )
        default_pool = config.DEFAULT_TWITCH_BOT["templates"][template_key]
        snapshot = runtime.latest_snapshot
        game_time = getattr(snapshot, "game_time_seconds", None)
        message = self._format_pool_message(
            template_key,
            default_pool,
            streamer=channel,
            stage=runtime.current_stage_index,
            time=(
                run_summary.format_elapsed_time(game_time)
                if game_time is not None
                else "--"
            ),
            count=ring_count,
        )
        if message:
            self._send_chat(channel, message)
