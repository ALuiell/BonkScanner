"""Stage summary, the powerups card and the chests card.

What is left of `PlayerStatsCardsMixin` after step 19 converted both halves of
the cards renderer:

* Weapons/Tomes/Chaos/Damage -> `stat_cards.StatCardsView` (two scopes, no
  Compare Runs involvement).
* The Items panel -> `items_section.ItemsSectionView` (four scopes, one
  ordinary instance each, including the two compare sides).

Neither composes attribute names as strings any more, and `_scope_prefix` --
the function that turned a scope into an attribute-name prefix -- has no
callers left and is gone with them.

These four are what remains, and they are a different shape: `labels` and
`values` arrive as *arguments*, so they never had the string-keyed lookup
problem. `_apply_live_powerups_card` and `format_live_powerups_card` still read
`self` (`player_stats_powerups_group`, `live_run_tracker`), which is why this is
still a mixin; the powerups card belongs to whichever step converts the Live
Stats tab itself.
"""
from __future__ import annotations

from math import isfinite

from projections import formatting
from ui.shared import _set_text


class PlayerStatsCardsMixin:
    @staticmethod
    def _set_stage_summary_labels(labels, rows) -> None:
        default_rows = [
            {
                "label": f"Stage {index}",
                "kills": "--",
                "time": "--",
                "items": "--",
            }
            for index in range(1, 5)
        ]
        rows = rows or default_rows
        for labels_by_column, row in zip(labels, rows):
            if isinstance(labels_by_column, dict):
                labels_by_column["stage"].setText(str(row["label"]).replace("Stage ", ""))
                labels_by_column["time"].setText(row["time"])
                labels_by_column["kills"].setText(row["kills"])
                labels_by_column["items"].setText(row["items"])
            else:
                labels_by_column.setText(
                    f"{row['label']}: Kills {row['kills']} | Time {row['time']} | Items {row['items']}"
                )
    def _apply_live_powerups_card(self, stats) -> None:
        group = getattr(self, "player_stats_powerups_group", None)
        labels = getattr(self, "player_stats_live_powerup_labels", None)
        if group is None or not isinstance(labels, dict):
            return
        title, values = self.format_live_powerups_card(stats)
        group.setTitle(title)
        for effect_name, label in labels.items():
            _set_text(label, f"{effect_name}: {values.get(effect_name, '--')}")

    @staticmethod
    def _set_chests_card_values(labels, values: dict[str, str] | None) -> None:
        if not labels:
            return
        values = values or formatting.chests_card_values(
            None, None, None, None, None, None, None, None, None
        )
        for key, label in labels.items():
            _set_text(label, values.get(key, "--"))

    def format_live_powerups_card(self, stats) -> tuple[str, dict[str, str]]:
        values = {name: "--" for name in ("Rage", "Clock", "Shield", "Stonks")}
        title = "Powerups"

        snapshot_reader = getattr(self.live_run_tracker, "powerups_snapshot", None)
        snapshot = snapshot_reader() if callable(snapshot_reader) else None
        if getattr(snapshot, "available", False):
            pm_display = str(getattr(snapshot, "powerup_multiplier_display", "--") or "--")
            if pm_display != "--":
                title = f"Powerups (PM {pm_display})"
            active_by_name = {
                str(getattr(effect, "name", "")): effect
                for effect in getattr(snapshot, "active", ()) or ()
            }
            for effect_name in values:
                effect = active_by_name.get(effect_name)
                if effect is not None:
                    left_text = f"({formatting.format_seconds_compact(effect.remaining_seconds)}s)"
                    if (
                        getattr(effect, "pickup_ui", None) is None
                        or getattr(effect, "expires_ui", None) is None
                    ):
                        values[effect_name] = left_text
                    else:
                        values[effect_name] = (
                            f"{effect.pickup_ui} -> {effect.expires_ui} "
                            f"{left_text}"
                        )
                    continue
                duration = (
                    getattr(snapshot, "clock_duration_seconds", None)
                    if effect_name == "Clock"
                    else getattr(snapshot, "standard_duration_seconds", None)
                )
                if duration is not None:
                    values[effect_name] = f"-- ({formatting.format_seconds_compact(duration)}s)"
            return title, values

        stat = (stats or {}).get("Powerup Multiplier")
        try:
            powerup_multiplier = float(getattr(stat, "value", None))
        except (TypeError, ValueError):
            return title, values
        if not isfinite(powerup_multiplier):
            return title, values

        pm_display = str(getattr(stat, "display_value", "") or "").strip()
        if pm_display:
            title = f"Powerups (PM {pm_display})"
        standard_duration = formatting.format_seconds_compact(15.0 * powerup_multiplier)
        clock_duration = formatting.format_seconds_compact(12.0 * powerup_multiplier)
        values["Rage"] = f"-- ({standard_duration}s)"
        values["Clock"] = f"-- ({clock_duration}s)"
        values["Shield"] = f"-- ({standard_duration}s)"
        values["Stonks"] = f"-- ({standard_duration}s)"
        return title, values
