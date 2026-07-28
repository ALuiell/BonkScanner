"""Weapons, Tomes, Chaos Tome and Damage Sources, as an owned view.

Step 19, first commit. This is the half of ``PlayerStatsCardsMixin`` that
step 18 identified as the blocker for converting any Player Stats tab: eight
widgets looked up by composed name (``getattr(self, f"{prefix}_weapons_layout",
None)``) behind guards that ``return`` silently on ``None``, so making a tab's
widgets private stops these panels rendering without raising and without
failing a test.

Why this half, and why it needs no Compare Runs adapter
=======================================================

The step-19 brief poses a fork: convert ``cards.py`` whole including the
``compare_a``/``compare_b`` scopes, or keep a scope registry with a temporary
adapter for the compare scopes that dies at step 21. Measured against the call
sites, **neither is necessary here**, because the four scopes are not uniform
across the renderer. Splitting the 23 name templates by which scopes actually
reach them:

===========================  =========  ==================================
Section                      Templates  Scopes that reach it
===========================  =========  ==================================
Items                        9          live, vod, compare_a, compare_b
Weapons/Tomes/Chaos/Damage   14         live, vod
===========================  =========  ==================================

``ui/tabs/compare_runs/tab.py`` calls ``_update_items_section`` and nothing
else; it never calls ``display_weapon_cards``, ``display_tome_cards``,
``display_chaos_tome_card`` or ``display_damage_source_rows``, and
``gui_app.py`` allocates no ``compare_run_*`` weapon/tome/chaos/damage state.
So these 14 templates are a **two-scope** surface, live and vod, both of which
step 19 owns outright. The seam is the section, not the scope, and this half
crosses no step-21 boundary at all. The items section, which genuinely is
four-scope, is handled separately and on its own terms.

What the constructor makes visible
==================================

Eight widgets, previously reached by composed name against the shared ``self``,
now constructor arguments -- so a missing one is a ``TypeError`` at the
composition root instead of a panel that quietly stops painting.

The four signature caches move inside too. They were ``{prefix}_weapon_signature``
and friends on ``MegabonkApp``: repaint-suppression state that only this
renderer reads or writes, sitting in the shared namespace where any of the
other 270 attributes could collide with it. ``invalidate()`` replaces the
``self.player_stats_weapon_signature = None`` idiom at the two reset sites.

Recorded while measuring, deliberately *not* acted on: every existing caller of
that idiom sets the signature to ``None`` and then immediately calls the
renderer with a non-``None`` ``status_text``, which already bypasses the cache
check (``... and status_text is None``). The resets are therefore redundant at
all six call sites. ``invalidate()`` preserves them verbatim rather than
dropping them, because "this looks unreachable" is exactly the reasoning step
14c had to walk back, and removing them is not needed for this step.
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
from projections import formatting
from ui.shared import _clear_layout, _set_text


class StatCardsView:
    """The Weapons, Tomes, Chaos and Damage Sources panels of one tab."""

    def __init__(
        self,
        *,
        weapons_layout,
        weapons_status_label,
        tomes_layout,
        tomes_status_label,
        chaos_layout,
        chaos_status_label,
        damage_sources_layout,
        damage_sources_status_label,
    ) -> None:
        self._weapons_layout = weapons_layout
        self._weapons_status_label = weapons_status_label
        self._tomes_layout = tomes_layout
        self._tomes_status_label = tomes_status_label
        self._chaos_layout = chaos_layout
        self._chaos_status_label = chaos_status_label
        self._damage_sources_layout = damage_sources_layout
        self._damage_sources_status_label = damage_sources_status_label

        self._weapon_signature = None
        self._tome_signature = None
        self._chaos_signature = None
        self._damage_source_signature = None
        self._weapon_cards: list = []
        self._tome_cards: list = []

    # -- cache control --------------------------------------------------------

    def invalidate(self) -> None:
        """Drop every repaint-suppression signature.

        Replaces the four ``self.<prefix>_<kind>_signature = None`` writes that
        `_reset_live_player_stats_ui` and `_clear_vod_snapshot_ui` performed
        directly on the shared namespace.
        """
        self._weapon_signature = None
        self._tome_signature = None
        self._chaos_signature = None
        self._damage_source_signature = None

    # -- weapons --------------------------------------------------------------

    def display_weapons(self, weapons, *, status_text: str | None = None) -> None:
        layout = self._weapons_layout
        status_label = self._weapons_status_label
        if layout is None or status_label is None:
            return

        weapons = tuple(weapons or ())
        signature = self._weapon_signature_for(weapons)
        if self._weapon_signature == signature and status_text is None:
            return

        self._weapon_signature = signature
        _clear_layout(layout)
        self._weapon_cards = []

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
        self._weapon_cards = cards

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
        weapon_name_label.setStyleSheet("font-size: 14px; font-weight: 700; background: transparent;")
        weapon_level_label = QLabel(f"Lv. {weapon.level}")
        weapon_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        weapon_level_label.setStyleSheet("font-size: 14px; font-weight: 700; background: transparent;")
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
    def _weapon_signature_for(weapons) -> tuple:
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

    # -- tomes ----------------------------------------------------------------

    def display_tomes(self, tomes, *, status_text: str | None = None) -> None:
        layout = self._tomes_layout
        status_label = self._tomes_status_label
        if layout is None or status_label is None:
            return

        tomes = tuple(tomes or ())
        signature = self._tome_signature_for(tomes)
        if self._tome_signature == signature and status_text is None:
            return

        self._tome_signature = signature
        _clear_layout(layout)
        self._tome_cards = []

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
        self._tome_cards = cards

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
        tome_name_label.setStyleSheet("font-size: 14px; font-weight: 700; background: transparent;")
        tome_level_label = QLabel(f"Lv. {tome.level}")
        tome_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tome_level_label.setStyleSheet("font-size: 14px; font-weight: 700; background: transparent;")
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
    def _tome_signature_for(tomes) -> tuple:
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

    # -- chaos tome -----------------------------------------------------------

    def display_chaos_tome(self, chaos_tome, *, status_text: str | None = None) -> None:
        layout = self._chaos_layout
        status_label = self._chaos_status_label
        if layout is None or status_label is None:
            return

        signature = self._chaos_tome_signature_for(chaos_tome)
        if self._chaos_signature == signature and status_text is None:
            return

        self._chaos_signature = signature
        _clear_layout(layout)

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if chaos_tome is not None else "No Chaos Tome data")

        if chaos_tome is None:
            return

        stats = chaos_stats_in_game_order(chaos_tome)
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
    def _chaos_tome_signature_for(chaos_tome) -> tuple:
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
                # Module-level, not `StatCardsView._chaos_stats_in_game_order`.
                # The class-qualified spelling is the exact shape that broke at
                # step 14b and is the single remaining production entry in the
                # step-18 class-qualified inventory; a free function cannot be
                # orphaned by a class moving.
                for stat in chaos_stats_in_game_order(chaos_tome)
            ),
        )

    def _build_chaos_summary_card(self, chaos_tome) -> QFrame:
        stats = chaos_stats_in_game_order(chaos_tome)
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title_label = QLabel("Chaos Tome")
        title_label.setStyleSheet("font-size: 13px; font-weight: 700; background: transparent;")
        level_label = QLabel(f"Lv. {int(getattr(chaos_tome, 'level', 0))}")
        level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        level_label.setStyleSheet("font-size: 13px; font-weight: 700; background: transparent;")
        header_layout.addWidget(title_label, 1)
        header_layout.addWidget(level_label)
        layout.addLayout(header_layout)

        rolls = sum(int(getattr(stat, "rolls", 0) or 0) for stat in stats)
        summary = QLabel(f"Tracked rolls: {rolls} | Stats: {len(stats)}")
        summary.setStyleSheet("color: #98A7BA; background: transparent;")
        layout.addWidget(summary)

        if stats:
            top_text = " | ".join(
                f"{chaos_stat_label(stat)} {getattr(stat, 'display_delta', '--')}"
                for stat in stats[:3]
            )
        else:
            top_text = "Tracking rolls..."
        top_label = QLabel(top_text)
        top_label.setWordWrap(True)
        top_label.setStyleSheet("font-weight: 700; background: transparent;")
        layout.addWidget(top_label)
        return card

    def _build_chaos_stat_card(self, stat) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        name_label = QLabel(chaos_stat_label(stat))
        name_label.setStyleSheet("font-size: 12px; font-weight: 700; background: transparent;")
        value_label = QLabel(getattr(stat, "display_delta", "--"))
        value_label.setStyleSheet("font-size: 12px; font-weight: 700; background: transparent;")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(name_label, 1)
        row.addWidget(value_label)
        layout.addLayout(row)
        return card

    # -- damage sources -------------------------------------------------------

    def display_damage_sources(self, damage_sources, *, status_text: str | None = None) -> None:
        layout = self._damage_sources_layout
        status_label = self._damage_sources_status_label
        if layout is None or status_label is None:
            return

        damage_sources = tuple(damage_sources or ())
        signature = self._damage_source_signature_for(damage_sources)
        if self._damage_source_signature == signature and status_text is None:
            return

        self._damage_source_signature = signature
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
            name_label.setStyleSheet("font-size: 16px; font-weight: 700; background: transparent;")
            cell_layout.addWidget(name_label, 1)

            dmg_label = QLabel(formatting.format_damage_source_value(source.damage))
            dmg_label.setStyleSheet("font-size: 17px; font-weight: 700; color: #F3F4F6; background: transparent;")
            dmg_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            cell_layout.addWidget(dmg_label)

            grid.addWidget(cell, index // 4, index % 4)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

    @staticmethod
    def _damage_source_signature_for(damage_sources) -> tuple:
        return tuple(
            (
                source.source_key,
                source.source_name,
                round(float(source.damage), 3),
            )
            for source in damage_sources
        )


def chaos_stats_in_game_order(chaos_tome) -> tuple:
    """Chaos Tome stats in the order the game itself shows them.

    Module-level and public on purpose. As `PlayerStatsCardsMixin._chaos_stats_in_game_order`
    this was the one remaining *production* class-qualified call site in the
    step-18 inventory, and the same name whose class-qualified spelling broke
    the Chaos Tome panel for two commits at step 14b.
    """
    return tuple(
        sorted(
            tuple(getattr(chaos_tome, "stats", ()) or ()),
            key=lambda stat: (
                CHAOS_TOME_GAME_STAT_ORDER.get(int(getattr(stat, "stat_id", -1)), 999),
                str(getattr(stat, "label", "")).casefold(),
            ),
        )
    )


def chaos_stat_label(stat) -> str:
    label = str(getattr(stat, "label", ""))
    return label or f"Stat {getattr(stat, 'stat_id', '?')}"
