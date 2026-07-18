"""Card and row rendering shared by the Live Stats and Recordings tabs.

Items, weapons, tomes, the Chaos Tome panel, damage sources, the stage-summary
labels, the powerups card and the chests card. Both tabs render the same shapes
from different sources -- live memory reads on one side, a loaded recording on
the other -- so these sit in neither tab.

``ui/tabs/compare_runs/tab.py`` also calls ``_update_items_section``; it resolves
through ``MegabonkApp``'s MRO like every other cross-mixin call here.

Still a mixin, for step 9's reason: the suite calls several of these
class-qualified (``gui.MegabonkApp.sort_items_for_display(...)``), which only
resolves through the MRO. Tabs-as-classes is a behaviour change and is not this
move.

The ``format_*`` helpers these call stay on ``PlayerStatsMixin`` -- they are thin
delegators to ``projections.formatting`` and are not view code. ``_set_items_text``
came along because it writes a widget and ``_update_items_section`` is its only
caller; it still routes through ``PlayerStatsMixin`` rather than calling
``projections.formatting`` directly, so that a test patching the mixin's
formatter still reaches it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from core.stats.types import TomeSnapshot, WeaponSnapshot
from core.tracker.chaos import CHAOS_TOME_GAME_STAT_ORDER
from gui_player_stats import PlayerStatsMixin
from gui_shared import _clear_layout, _set_text
from gui_styles import ITEM_SORT_DEFAULT


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
        self._set_items_group_title(group, self._item_total_count(items))
        self._set_items_rarity_summary_label(rarity_label, items)
        sorted_items = self.sort_items_for_display(
            items,
            self.__dict__.get(f"{prefix}_items_sort_mode", ITEM_SORT_DEFAULT),
        )
        preview_items, has_more = self._items_preview(sorted_items)
        visible_items = sorted_items if expanded or not has_more else preview_items
        if sort_combo is not None:
            sort_combo.setEnabled(bool(items))
        if hasattr(label, "setTextFormat"):
            text = self.format_items_rich_text(visible_items)
            if has_more and not expanded:
                text = f'{text} <span style="color:#98A7BA;">...</span>'
            label.setText(text)
        else:
            text = self.format_items(visible_items)
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
        text = PlayerStatsMixin.format_items_rarity_summary_rich_text(items)
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
    def display_weapon_cards(self, weapons, *, scope: str, status_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        layout_attr = f"{prefix}_weapons_layout"
        status_attr = f"{prefix}_weapons_status_label"
        cards_attr = f"{prefix}_weapon_cards"
        signature_attr = f"{prefix}_weapon_signature"

        layout = getattr(self, layout_attr, None)
        status_label = getattr(self, status_attr, None)
        if layout is None or status_label is None:
            return

        weapons = tuple(weapons or ())
        signature = self._weapon_signature(weapons)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)
        setattr(self, cards_attr, [])

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if weapons else "No weapons available")

        if not weapons:
            return

        cards = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, weapon in enumerate(weapons):
            card = self._build_weapon_card(weapon)
            grid.addWidget(card, index // 2, index % 2)
            cards.append(card)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        setattr(self, cards_attr, cards)
    def _build_weapon_card(self, weapon: WeaponSnapshot) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        weapon_name_label = QLabel(weapon.name)
        weapon_name_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        weapon_level_label = QLabel(f"Lv. {weapon.level}")
        weapon_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        weapon_level_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        header_layout.addWidget(weapon_name_label, 1)
        header_layout.addWidget(weapon_level_label)
        layout.addLayout(header_layout)

        rows = QFormLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setVerticalSpacing(6)
        has_rows = False
        for stat_id in weapon.upgrade_stat_ids:
            stat = weapon.upgraded_stats.get(stat_id)
            if stat is None:
                continue
            value_label = QLabel(stat.display_value)
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rows.addRow(stat.label, value_label)
            has_rows = True
        if has_rows:
            layout.addLayout(rows)
        else:
            layout.addWidget(QLabel("No upgraded stats decoded"))
        layout.addStretch(1)
        return card

    @staticmethod
    def _weapon_signature(weapons) -> tuple:
        return tuple(
            (
                weapon.weapon_id,
                weapon.level,
                tuple(
                    (stat_id, weapon.upgraded_stats[stat_id].display_value)
                    for stat_id in weapon.upgrade_stat_ids
                    if stat_id in weapon.upgraded_stats
                ),
            )
            for weapon in weapons
        )
    def display_tome_cards(
        self,
        tomes,
        *,
        scope: str,
        status_text: str | None = None,
    ) -> None:
        prefix = self._scope_prefix(scope)
        layout_attr = f"{prefix}_tomes_layout"
        status_attr = f"{prefix}_tomes_status_label"
        cards_attr = f"{prefix}_tome_cards"
        signature_attr = f"{prefix}_tome_signature"

        layout = getattr(self, layout_attr, None)
        status_label = getattr(self, status_attr, None)
        if layout is None or status_label is None:
            return

        tomes = tuple(tomes or ())
        signature = self._tome_signature(tomes)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)
        setattr(self, cards_attr, [])

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if tomes else "No tomes available")

        if not tomes:
            return

        cards = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, tome in enumerate(tomes):
            card = self._build_tome_card(tome)
            grid.addWidget(card, index // 2, index % 2)
            cards.append(card)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addStretch(1)
        setattr(self, cards_attr, cards)
    def _build_tome_card(self, tome: TomeSnapshot) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        tome_name_label = QLabel(tome.name)
        tome_name_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        tome_level_label = QLabel(f"Lv. {tome.level}")
        tome_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tome_level_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        header_layout.addWidget(tome_name_label, 1)
        header_layout.addWidget(tome_level_label)
        layout.addLayout(header_layout)

        rows = QFormLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setVerticalSpacing(6)
        value_label = QLabel(tome.display_value)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rows.addRow(tome.stat_label, value_label)
        layout.addLayout(rows)
        return card

    @staticmethod
    def _tome_signature(tomes) -> tuple:
        return tuple(
            (
                tome.tome_id,
                tome.level,
                tome.stat_id,
                tome.stat_label,
                tome.display_value,
            )
            for tome in tomes
        )
    def display_chaos_tome_card(self, chaos_tome, *, scope: str, status_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        layout = getattr(self, f"{prefix}_chaos_layout", None)
        status_label = getattr(self, f"{prefix}_chaos_status_label", None)
        signature_attr = f"{prefix}_chaos_signature"
        if layout is None or status_label is None:
            return

        signature = self._chaos_tome_signature(chaos_tome)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if chaos_tome is not None else "No Chaos Tome data")

        if chaos_tome is None:
            return

        stats = self._chaos_stats_in_game_order(chaos_tome)
        summary_card = self._build_chaos_summary_card(chaos_tome)
        layout.addWidget(summary_card)

        if not stats:
            layout.addStretch(1)
            return

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for index, stat in enumerate(stats):
            grid.addWidget(self._build_chaos_stat_card(stat), index // 4, index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

    @staticmethod
    def _chaos_tome_signature(chaos_tome) -> tuple:
        if chaos_tome is None:
            return ()
        return (
            int(getattr(chaos_tome, "level", 0)),
            int(getattr(chaos_tome, "ambiguous_rolls", 0)),
            tuple(
                (
                    int(getattr(stat, "stat_id", -1)),
                    str(getattr(stat, "label", "")),
                    getattr(stat, "display_delta", "--"),
                    int(getattr(stat, "rolls", 0)),
                )
                for stat in PlayerStatsCardsMixin._chaos_stats_in_game_order(chaos_tome)
            ),
        )
    def _build_chaos_summary_card(self, chaos_tome) -> QFrame:
        stats = self._chaos_stats_in_game_order(chaos_tome)
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title_label = QLabel("Chaos Tome")
        title_label.setStyleSheet("font-size: 13px; font-weight: 700;")
        level_label = QLabel(f"Lv. {int(getattr(chaos_tome, 'level', 0))}")
        level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        level_label.setStyleSheet("font-size: 13px; font-weight: 700;")
        header_layout.addWidget(title_label, 1)
        header_layout.addWidget(level_label)
        layout.addLayout(header_layout)

        rolls = sum(int(getattr(stat, "rolls", 0) or 0) for stat in stats)
        summary = QLabel(f"Tracked rolls: {rolls} | Stats: {len(stats)}")
        summary.setStyleSheet("color: #98A7BA;")
        layout.addWidget(summary)

        if stats:
            top_text = " | ".join(
                f"{self._chaos_stat_label(stat)} {getattr(stat, 'display_delta', '--')}"
                for stat in stats[:3]
            )
        else:
            top_text = "Tracking rolls..."
        top_label = QLabel(top_text)
        top_label.setWordWrap(True)
        top_label.setStyleSheet("font-weight: 700;")
        layout.addWidget(top_label)
        return card
    def _build_chaos_stat_card(self, stat) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        name_label = QLabel(self._chaos_stat_label(stat))
        name_label.setStyleSheet("font-size: 12px; font-weight: 700;")
        value_label = QLabel(getattr(stat, "display_delta", "--"))
        value_label.setStyleSheet("font-size: 12px; font-weight: 700;")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(name_label, 1)
        row.addWidget(value_label)
        layout.addLayout(row)
        return card

    @staticmethod
    def _chaos_stats_in_game_order(chaos_tome) -> tuple:
        return tuple(
            sorted(
                tuple(getattr(chaos_tome, "stats", ()) or ()),
                key=lambda stat: (
                    CHAOS_TOME_GAME_STAT_ORDER.get(int(getattr(stat, "stat_id", -1)), 999),
                    str(getattr(stat, "label", "")).casefold(),
                ),
            )
        )

    @staticmethod
    def _chaos_stat_label(stat) -> str:
        label = str(getattr(stat, "label", ""))
        return label or f"Stat {getattr(stat, 'stat_id', '?')}"
    def display_damage_source_rows(self, damage_sources, *, scope: str, status_text: str | None = None) -> None:
        prefix = self._scope_prefix(scope)
        layout_attr = f"{prefix}_damage_sources_layout"
        status_attr = f"{prefix}_damage_sources_status_label"
        signature_attr = f"{prefix}_damage_source_signature"

        layout = getattr(self, layout_attr, None)
        status_label = getattr(self, status_attr, None)
        if layout is None or status_label is None:
            return

        damage_sources = tuple(damage_sources or ())
        signature = self._damage_source_signature(damage_sources)
        if getattr(self, signature_attr, None) == signature and status_text is None:
            return

        setattr(self, signature_attr, signature)
        _clear_layout(layout)

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if damage_sources else "No damage source data yet")

        if not damage_sources:
            return

        grid = QGridLayout()
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        for index, source in enumerate(damage_sources):
            cell = QFrame()
            cell.setObjectName("StatCard")
            cell.setMinimumHeight(54)
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(12, 8, 12, 8)
            cell_layout.setSpacing(10)

            name_label = QLabel(source.source_name or source.source_key)
            name_label.setWordWrap(True)
            name_label.setStyleSheet("font-size: 16px; font-weight: 700;")
            cell_layout.addWidget(name_label, 1)

            dmg_label = QLabel(self.format_damage_source_value(source.damage))
            dmg_label.setStyleSheet("font-size: 17px; font-weight: 700; color: #F3F4F6;")
            dmg_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            cell_layout.addWidget(dmg_label)

            grid.addWidget(cell, index // 4, index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

    @staticmethod
    def _damage_source_signature(damage_sources) -> tuple:
        return tuple(
            (
                source.source_key,
                source.source_name,
                round(float(source.damage), 3),
            )
            for source in damage_sources
        )

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
        values = values or PlayerStatsMixin.chests_card_values(
            None, None, None, None, None, None, None, None, None
        )
        for key, label in labels.items():
            _set_text(label, values.get(key, "--"))

def _set_items_text(widget, items=(), *, items_text: str | None = None) -> None:
    text = items_text if items_text is not None else PlayerStatsMixin.format_items(items)
    if widget is None:
        return
    if hasattr(widget, "setTextFormat"):
        widget.setText(PlayerStatsMixin.format_items_rich_text(items) if items_text is None else text)
        return
    _set_text(widget, text)
