"""Row rendering still shared by the Player Stats tabs, and by Compare Runs.

What is left after step 19's first commit: the items section, the stage-summary
labels, the powerups card and the chests card.

Weapons, Tomes, the Chaos Tome panel and Damage Sources are **gone from here** --
they are ``ui/tabs/player_stats/stat_cards.py``'s ``StatCardsView``, constructed
once by each tab with its eight widgets as named arguments. That half needed no
Compare Runs adapter, because the compare scopes never reached it; see that
module's docstring for the measurement.

What still composes attribute names as strings is the **items section**, and
that one genuinely is four-scope: ``ui/tabs/compare_runs/tab.py`` calls
``_update_items_section`` for ``compare_a`` and ``compare_b``, and
``gui_layout._build_compare_run_panel`` builds the widgets it reaches. Its nine
name templates are the remaining blocker for making a tab's widgets private.

Still a mixin, for step 9's reason: the suite calls several of these
class-qualified, which only resolves through the MRO.

The ``format_*`` helpers these call stay on ``PlayerStatsMixin`` -- they are thin
delegators to ``projections.formatting`` and are not view code. ``_set_items_text``
came along because it writes a widget and ``_update_items_section`` is its only
caller; it still routes through ``PlayerStatsMixin`` rather than calling
``projections.formatting`` directly, so that a test patching the mixin's
formatter still reaches it.
"""
from __future__ import annotations

from ui.shared import _set_text
from projections.item_sort import ITEM_SORT_DEFAULT
from math import isfinite

from projections import formatting


class PlayerStatsCardsMixin:
    def on_items_sort_changed(self, scope: str) -> None:
        prefix = self._scope_prefix(scope)
        combo = self.__dict__.get(f"{prefix}_items_sort_combo")
        mode = ITEM_SORT_DEFAULT
        if combo is not None and hasattr(combo, "currentData"):
            mode = combo.currentData() or ITEM_SORT_DEFAULT
        setattr(self, f"{prefix}_items_sort_mode", mode)
        self._update_items_section(
            scope,
            self.__dict__.get(f"{prefix}_items_current", ()),
            items_text=self.__dict__.get(f"{prefix}_items_text_current"),
        )
    def _update_items_section(self, scope: str, items=(), *, items_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        group = self.__dict__.get(f"{prefix}_items_group")
        label = self.__dict__.get(f"{prefix}_items_label")
        rarity_label = self.__dict__.get(f"{prefix}_items_rarity_label")
        button = self.__dict__.get(f"{prefix}_items_toggle_btn")
        sort_combo = self.__dict__.get(f"{prefix}_items_sort_combo")
        expanded = bool(self.__dict__.get(f"{prefix}_items_expanded", False))
        setattr(self, f"{prefix}_items_current", tuple(items or ()))
        setattr(self, f"{prefix}_items_text_current", items_text)

        if label is None:
            return

        if items_text is not None:
            self._set_items_group_title(group, None)
            _set_items_text(label, items_text=items_text)
            self._set_items_rarity_summary_label(rarity_label, ())
            if button is not None:
                button.setVisible(True)
                button.setEnabled(False)
                button.setText("Show more")
            if sort_combo is not None:
                sort_combo.setEnabled(False)
            return

        items = tuple(items or ())
        self._set_items_group_title(group, formatting._item_total_count(items))
        self._set_items_rarity_summary_label(rarity_label, items)
        sorted_items = formatting.sort_items_for_display(
            items,
            self.__dict__.get(f"{prefix}_items_sort_mode", ITEM_SORT_DEFAULT),
        )
        preview_items, has_more = self._items_preview(sorted_items)
        visible_items = sorted_items if expanded or not has_more else preview_items
        if sort_combo is not None:
            sort_combo.setEnabled(bool(items))
        if hasattr(label, "setTextFormat"):
            text = formatting.format_items_rich_text(visible_items)
            if has_more and not expanded:
                text = f'{text} <span style="color:#98A7BA;">...</span>'
            label.setText(text)
        else:
            text = formatting.format_items(visible_items)
            if has_more and not expanded:
                text = f"{text} ..."
            _set_text(label, text)

        if button is not None:
            button.setVisible(True)
            button.setEnabled(has_more)
            button.setText("Show less" if expanded and has_more else "Show more")

    @staticmethod
    def _set_items_rarity_summary_label(label, items) -> None:
        if label is None:
            return
        text = formatting.format_items_rarity_summary_rich_text(items)
        label.setVisible(bool(text))
        label.setText(text)

    @staticmethod
    def _set_items_group_title(group, total_count: int | None) -> None:
        if group is None or not hasattr(group, "setTitle"):
            return
        title = "Items" if total_count is None else f"Items ({total_count} total)"
        group.setTitle(title)

    @staticmethod
    def _items_preview(items) -> tuple[tuple[str, ...], bool]:
        items = tuple(items or ())
        if len(items) <= 1:
            return items, False

        preview: list[str] = []
        max_chars = 90
        current_length = 0
        for item in items:
            separator_length = 2 if preview else 0
            projected_length = current_length + separator_length + len(item)
            if preview and projected_length > max_chars:
                break
            preview.append(item)
            current_length = projected_length

        if not preview:
            preview.append(items[0])
        return tuple(preview), len(preview) < len(items)







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

def _set_items_text(widget, items=(), *, items_text: str | None = None) -> None:
    text = items_text if items_text is not None else formatting.format_items(items)
    if widget is None:
        return
    if hasattr(widget, "setTextFormat"):
        widget.setText(formatting.format_items_rich_text(items) if items_text is None else text)
        return
    _set_text(widget, text)

