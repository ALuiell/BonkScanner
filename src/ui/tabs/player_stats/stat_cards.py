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

from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.stats.types import TomeSnapshot, WeaponSnapshot
from core.tracker.chaos import CHAOS_FINGERPRINTS, CHAOS_TOME_GAME_STAT_ORDER
from projections import formatting
from ui.shared import _clear_layout, _set_text


def chaos_card_column_count(
    width: int,
    *,
    minimum_card_width: int = 160,
    spacing: int = 6,
) -> int:
    """Use five Chaos cards only when all five fit at their intended width."""
    five_column_width = minimum_card_width * 5 + max(0, spacing) * 4
    return 5 if max(0, int(width)) >= five_column_width else 4


def damage_source_column_count(
    width: int,
    *,
    minimum_card_width: int = 290,
    spacing: int = 8,
) -> int:
    """Use three damage cards when they fit; otherwise keep a readable pair."""
    three_column_width = minimum_card_width * 3 + max(0, spacing) * 2
    return 3 if max(0, int(width)) >= three_column_width else 2


def damage_source_share_text(damage: float, total_damage: float) -> str:
    """Format one source's share without rounding a real contribution to zero."""
    damage = max(0.0, float(damage))
    total_damage = max(0.0, float(total_damage))
    if total_damage <= 0.0 or damage <= 0.0:
        return "0%"
    percentage = min(100.0, damage / total_damage * 100.0)
    if percentage < 0.1:
        return "<0.1%"
    if percentage >= 99.95:
        return "100%"
    return f"{percentage:.1f}%"


class _DamageSourceCard(QFrame):
    """One damage source, built once and rewritten in place afterwards.

    The panel is the most expensive of the four -- 48 ms of a scrub frame with
    twenty-odd sources on screen -- and almost all of it was construction:
    every render tore the whole grid down and built a fresh `QFrame`, four
    `QLabel`s and a `QProgressBar` per source. Nothing about a source changes
    which *widgets* it needs, only what they say, so the cards outlive the
    render now and `update` writes them.

    Style sheets are set once in `__init__` for the same reason: re-applying
    one forces Qt to re-parse it and re-polish the widget, which is a large
    part of what made the rebuild expensive. The two that genuinely vary --
    the name and value colours, which grey out at zero damage -- are the only
    ones `update` touches, and only when they actually change.
    """

    _ACTIVE_COLOR = "#F3F4F6"
    _IDLE_COLOR = "#98A7BA"

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StatCard")
        card_layout = QVBoxLayout(self)
        card_layout.setContentsMargins(10, 9, 10, 9)
        card_layout.setSpacing(7)

        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(7)

        self._rank_label = QLabel()
        self._rank_label.setObjectName("DamageSourceRank")
        self._rank_label.setStyleSheet(
            "font-size: 12px; color: #65758B; font-weight: 700; background: transparent;"
        )
        top_layout.addWidget(self._rank_label)

        self._name_label = QLabel()
        self._name_label.setObjectName("DamageSourceName")
        self._name_label.setWordWrap(True)
        top_layout.addWidget(self._name_label, 1)

        self._damage_label = QLabel()
        self._damage_label.setObjectName("DamageSourceValue")
        self._damage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top_layout.addWidget(self._damage_label)

        self._percentage_label = QLabel()
        self._percentage_label.setObjectName("DamageSourcePercent")
        self._percentage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._percentage_label.setStyleSheet(
            "font-size: 12px; color: #98A7BA; font-weight: 600; background: transparent;"
        )
        top_layout.addWidget(self._percentage_label)
        card_layout.addLayout(top_layout)

        self._bar = QProgressBar()
        self._bar.setObjectName("DamageSourceBar")
        self._bar.setRange(0, 1000)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            "QProgressBar {"
            " background: #111923;"
            " border: 0;"
            " border-radius: 3px;"
            "}"
            "QProgressBar::chunk {"
            " background: #60A5FA;"
            " border-radius: 3px;"
            "}"
        )
        card_layout.addWidget(self._bar)
        self._text_color: str | None = None

    def update_source(self, source, *, rank: int, total_damage: float) -> None:
        damage = max(0.0, float(getattr(source, "damage", 0.0) or 0.0))
        source_name = str(
            getattr(source, "source_name", "")
            or getattr(source, "source_key", "")
            or "Unknown source"
        )
        percentage = damage / total_damage if total_damage > 0.0 else 0.0
        share_text = damage_source_share_text(damage, total_damage)

        _set_text(self._rank_label, f"#{rank}")
        _set_text(self._name_label, source_name)
        self._name_label.setToolTip(source_name)
        _set_text(self._damage_label, formatting.format_damage_source_value(damage))
        _set_text(self._percentage_label, share_text)
        self._bar.setValue(round(min(1.0, max(0.0, percentage)) * 1000))
        self._bar.setToolTip(f"{share_text} of total damage")

        text_color = self._ACTIVE_COLOR if damage > 0.0 else self._IDLE_COLOR
        if text_color != self._text_color:
            self._text_color = text_color
            self._name_label.setStyleSheet(
                f"font-size: 14px; color: {text_color};"
                " font-weight: 700; background: transparent;"
            )
            self._damage_label.setStyleSheet(
                f"font-size: 15px; color: {text_color};"
                " font-weight: 800; background: transparent;"
            )


class _DamageSourcesSummaryCard(QFrame):
    """The panel's total line, rewritten in place for the same reason."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("StatCard")
        summary_layout = QHBoxLayout(self)
        summary_layout.setContentsMargins(10, 8, 10, 8)
        summary_layout.setSpacing(8)

        title_label = QLabel("Total Damage")
        title_label.setStyleSheet(
            "font-size: 13px; color: #D7DEE8; font-weight: 700; background: transparent;"
        )
        summary_layout.addWidget(title_label)

        self._value_label = QLabel()
        self._value_label.setObjectName("DamageSourcesSummaryValue")
        self._value_label.setStyleSheet(
            "font-size: 15px; color: #F3F4F6; font-weight: 800; background: transparent;"
        )
        summary_layout.addWidget(self._value_label)
        summary_layout.addStretch(1)

        self._count_label = QLabel()
        self._count_label.setObjectName("DamageSourcesSummaryCount")
        self._count_label.setStyleSheet(
            "font-size: 12px; color: #98A7BA; font-weight: 600; background: transparent;"
        )
        summary_layout.addWidget(self._count_label)

    def update_totals(self, *, total_damage: float, source_count: int) -> None:
        _set_text(self._value_label, formatting.format_damage_source_value(total_damage))
        _set_text(
            self._count_label,
            f"{source_count} {'source' if source_count == 1 else 'sources'}",
        )


#: Which detail tab each deferrable panel lives on, by that tab's title. Only
#: these four are deferred; Stats and Loot are label writes and cost nothing.
#:
#: Matched on the tab's *text* rather than its index: both tabs add their six
#: a hundred lines away from here, and an index would silently point at the
#: wrong panel the first time somebody reorders them.
DEFERRABLE_SECTION_TAB_TITLES = {
    "weapons": "Weapons",
    "tomes": "Tomes",
    "chaos": "Chaos",
    "damage_sources": "Damage Sources",
}


def section_visibility_over(detail_tabs: Callable[[], object]) -> Callable[[str], bool]:
    """A `section_visible` port reading whichever detail tab is on screen.

    Takes a supplier rather than the widget: both tabs build their
    `QTabWidget` and their `StatCardsView` in the same method, and a test
    harness may never build either. A supplier that returns `None` answers
    "visible", so an unbuilt tab renders everything rather than deferring a
    render the test is asserting on.
    """

    def visible(section: str) -> bool:
        tabs = detail_tabs()
        if tabs is None:
            return True
        wanted = DEFERRABLE_SECTION_TAB_TITLES.get(section)
        if wanted is None:
            return True
        return tabs.tabText(tabs.currentIndex()) == wanted

    return visible


class _ResponsiveStatCardGrid(QWidget):
    """Reflow one stat-card collection when its scroll viewport resizes."""

    def __init__(
        self,
        *,
        object_name: str,
        column_count: Callable[[int], int],
        minimum_card_width: int,
        spacing: int,
        maximum_columns: int,
    ) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._column_count = column_count
        self._minimum_card_width = minimum_card_width
        self._spacing = spacing
        self._maximum_columns = maximum_columns
        self._columns = 0
        self._cards: list[QWidget] = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(spacing)
        self._grid.setVerticalSpacing(spacing)

    def add_card(self, card: QWidget) -> None:
        card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._cards.append(card)
        self._reflow(self.width())

    def trim_to(self, count: int) -> None:
        """Drop trailing cards so the grid holds at most `count`.

        Paired with `add_card` by panels that reuse their cards across renders
        rather than rebuilding them: growing is `add_card`, shrinking is this,
        and neither destroys the cards in between.
        """
        count = max(0, int(count))
        if count >= len(self._cards):
            return
        for card in self._cards[count:]:
            self._grid.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        del self._cards[count:]
        # `_reflow` returns early when the column count and the child count
        # both look unchanged; the removals above already changed the latter,
        # so force the relayout rather than relying on that comparison.
        self._columns = 0
        self._reflow(self.width())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow(event.size().width())

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        columns = self._column_count(width)
        row_heights: list[int] = []
        for index, card in enumerate(self._cards):
            row = index // columns
            if row == len(row_heights):
                row_heights.append(0)
            row_heights[row] = max(row_heights[row], card.sizeHint().height())
        return sum(row_heights) + self._spacing * max(0, len(row_heights) - 1)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._minimum_card_width, self.heightForWidth(self._minimum_card_width))

    def sizeHint(self) -> QSize:
        # The scroll viewport decides the useful width; never request five
        # columns from the parent and thereby create a horizontal scrollbar.
        return self.minimumSizeHint()

    def _reflow(self, width: int) -> None:
        columns = self._column_count(width)
        required_height = self.heightForWidth(width)
        if self.minimumHeight() != required_height:
            self.setMinimumHeight(required_height)
        if columns == self._columns and self._grid.count() == len(self._cards):
            return
        while self._grid.count():
            self._grid.takeAt(0)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // columns, index % columns)
        for column in range(self._maximum_columns):
            self._grid.setColumnStretch(column, 1 if column < columns else 0)
        self._columns = columns
        self.updateGeometry()


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
        section_visible: Callable[[str], bool] | None = None,
    ) -> None:
        # Rebuilding a panel nobody is looking at is the whole cost of a scrub
        # frame: measured on a 713-snapshot recording, the four panels here
        # were 95 ms of a 103 ms frame, and the tab defaults to *Stats*, where
        # none of them is on screen. `section_visible` lets the owner say which
        # panel is showing; the rest record their last call and render it when
        # they are next shown.
        #
        # Optional, and `None` means "always render": Live Stats and Compare
        # Runs construct this view too, and neither asked for the change.
        self._section_visible = section_visible
        self._pending: dict[str, tuple[tuple, dict]] = {}
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
        # Reused across renders rather than rebuilt. `None` means "not built
        # yet, or torn down because the panel went empty".
        self._damage_sources_grid = None
        self._damage_sources_summary = None
        self._damage_source_cards: list = []

    # -- deferred rendering ---------------------------------------------------

    def _defer(self, section: str, args: tuple, kwargs: dict) -> bool:
        """Record the call and return ``True`` when the panel is not showing.

        The signature caches below are deliberately *not* updated on a deferred
        call: the panel still holds whatever it drew last, so the render that
        eventually happens must not be suppressed as a repeat.
        """
        visible = self._section_visible
        if visible is None or visible(section):
            return False
        self._pending[section] = (args, dict(kwargs))
        return True

    def flush_pending(self) -> None:
        """Draw whatever the now-visible panels missed while hidden.

        Called by the owner when its detail tab changes. Panels still hidden
        keep their recorded call rather than losing it, so switching between
        two hidden panels does not drop the one you skipped over.
        """
        visible = self._section_visible
        for section in tuple(self._pending):
            if visible is not None and not visible(section):
                continue
            args, kwargs = self._pending.pop(section)
            _SECTION_RENDERERS[section](self, *args, **kwargs)

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
        if self._defer("weapons", (weapons,), {"status_text": status_text}):
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
        weapon_name_label.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent;")
        weapon_level_label = QLabel(f"Lv. {weapon.level}")
        weapon_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        weapon_level_label.setStyleSheet(
            "font-size: 12px; color: #98A7BA; font-weight: 700; background: transparent;"
        )
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
            name_label = QLabel(stat.label)
            name_label.setStyleSheet(
                "font-size: 13px; color: #D7DEE8; background: transparent;"
            )
            value_label = QLabel(stat.display_value)
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value_label.setStyleSheet(
                "font-size: 14px; color: #F3F4F6; font-weight: 700; background: transparent;"
            )
            rows.addRow(name_label, value_label)
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
        if self._defer("tomes", (tomes,), {"status_text": status_text}):
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
        tome_name_label.setStyleSheet("font-size: 15px; font-weight: 700; background: transparent;")
        tome_level_label = QLabel(f"Lv. {tome.level}")
        tome_level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tome_level_label.setStyleSheet(
            "font-size: 12px; color: #98A7BA; font-weight: 700; background: transparent;"
        )
        header_layout.addWidget(tome_name_label, 1)
        header_layout.addWidget(tome_level_label)
        layout.addLayout(header_layout)

        rows = QFormLayout()
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setVerticalSpacing(6)
        stat_name_label = QLabel(tome.stat_label)
        stat_name_label.setStyleSheet(
            "font-size: 13px; color: #D7DEE8; background: transparent;"
        )
        value_label = QLabel(tome.display_value)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setStyleSheet(
            "font-size: 14px; color: #F3F4F6; font-weight: 700; background: transparent;"
        )
        rows.addRow(stat_name_label, value_label)
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
        if self._defer("chaos", (chaos_tome,), {"status_text": status_text}):
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

        stats = chaos_stats_by_roll_count(chaos_tome)
        summary_card = self._build_chaos_summary_card(chaos_tome)
        layout.addWidget(summary_card)

        if not stats:
            layout.addStretch(1)
            return

        grid = _ResponsiveStatCardGrid(
            object_name="ChaosCardGrid",
            column_count=chaos_card_column_count,
            minimum_card_width=160,
            spacing=6,
            maximum_columns=5,
        )
        for stat in stats:
            grid.add_card(self._build_chaos_stat_card(stat))
        layout.addWidget(grid)
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
        title_label.setStyleSheet("font-size: 14px; font-weight: 700; background: transparent;")
        level_label = QLabel(f"Lv. {int(getattr(chaos_tome, 'level', 0))}")
        level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        level_label.setStyleSheet(
            "font-size: 12px; color: #98A7BA; font-weight: 700; background: transparent;"
        )
        header_layout.addWidget(title_label, 1)
        header_layout.addWidget(level_label)
        layout.addLayout(header_layout)

        rolls = sum(int(getattr(stat, "rolls", 0) or 0) for stat in stats)
        summary = QLabel(f"Tracked rolls: {rolls} | Stats: {len(stats)}")
        summary.setStyleSheet(
            "font-size: 12px; color: #98A7BA; background: transparent;"
        )
        layout.addWidget(summary)
        return card

    def _build_chaos_stat_card(self, stat) -> QFrame:
        card = QFrame()
        card.setObjectName("StatCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        name_label = QLabel(chaos_stat_label(stat))
        name_label.setStyleSheet(
            "font-size: 13px; color: #D7DEE8; font-weight: 700; background: transparent;"
        )
        value_label = QLabel(getattr(stat, "display_delta", "--"))
        value_label.setStyleSheet(
            "font-size: 14px; color: #F3F4F6; font-weight: 700; background: transparent;"
        )
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(name_label, 1)
        row.addWidget(value_label)
        layout.addLayout(row)

        rolls = max(0, int(getattr(stat, "rolls", 0) or 0))
        quality = chaos_average_roll_quality(stat)
        quality_color = chaos_roll_quality_color(quality)
        rolls_word = "roll" if rolls == 1 else "rolls"
        rolls_label = QLabel(f"● {rolls} {rolls_word}")
        rolls_label.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {quality_color}; "
            "background: transparent;"
        )
        if quality is not None:
            rolls_label.setToolTip(
                f"Average roll quality: {round(quality * 100)}% of this stat's range"
            )
        layout.addWidget(rolls_label)
        return card

    # -- damage sources -------------------------------------------------------

    def display_damage_sources(self, damage_sources, *, status_text: str | None = None) -> None:
        layout = self._damage_sources_layout
        status_label = self._damage_sources_status_label
        if layout is None or status_label is None:
            return
        # Deferred before the sort: it is the most expensive of the four to
        # rebuild, and the sort is not free either.
        if self._defer("damage_sources", (damage_sources,), {"status_text": status_text}):
            return

        damage_sources = tuple(
            sorted(
                tuple(damage_sources or ()),
                key=lambda source: (
                    -max(0.0, float(getattr(source, "damage", 0.0) or 0.0)),
                    str(
                        getattr(source, "source_name", "")
                        or getattr(source, "source_key", "")
                    ).casefold(),
                ),
            )
        )
        signature = self._damage_source_signature_for(damage_sources)
        if self._damage_source_signature == signature and status_text is None:
            return

        self._damage_source_signature = signature

        if status_text is not None:
            _set_text(status_label, status_text)
        else:
            _set_text(status_label, "" if damage_sources else "No damage source data yet")

        if not damage_sources:
            _clear_layout(layout)
            self._damage_sources_grid = None
            self._damage_sources_summary = None
            self._damage_source_cards = []
            return

        total_damage = sum(
            max(0.0, float(getattr(source, "damage", 0.0) or 0.0))
            for source in damage_sources
        )

        # Built on the first render and kept. The tear-down-and-rebuild this
        # replaced was 48 ms of a scrub frame with twenty sources; the widgets
        # a source needs never change, only their text.
        if self._damage_sources_grid is None:
            _clear_layout(layout)
            self._damage_sources_summary = _DamageSourcesSummaryCard()
            layout.addWidget(self._damage_sources_summary)
            self._damage_sources_grid = _ResponsiveStatCardGrid(
                object_name="DamageSourcesCardGrid",
                column_count=damage_source_column_count,
                minimum_card_width=290,
                spacing=8,
                maximum_columns=3,
            )
            self._damage_source_cards = []
            layout.addWidget(self._damage_sources_grid)
            layout.addStretch(1)

        self._damage_sources_summary.update_totals(
            total_damage=total_damage,
            source_count=len(damage_sources),
        )

        while len(self._damage_source_cards) < len(damage_sources):
            card = _DamageSourceCard()
            self._damage_source_cards.append(card)
            self._damage_sources_grid.add_card(card)
        if len(self._damage_source_cards) > len(damage_sources):
            self._damage_sources_grid.trim_to(len(damage_sources))
            del self._damage_source_cards[len(damage_sources):]

        for index, source in enumerate(damage_sources):
            self._damage_source_cards[index].update_source(
                source,
                rank=index + 1,
                total_damage=total_damage,
            )

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


def chaos_stats_by_roll_count(chaos_tome) -> tuple:
    """Chaos Tome stats ordered by roll count, with a stable game-order tie-break."""
    return tuple(
        sorted(
            tuple(getattr(chaos_tome, "stats", ()) or ()),
            key=lambda stat: (
                -max(0, int(getattr(stat, "rolls", 0) or 0)),
                CHAOS_TOME_GAME_STAT_ORDER.get(int(getattr(stat, "stat_id", -1)), 999),
                str(getattr(stat, "label", "")).casefold(),
            ),
        )
    )


def chaos_average_roll_quality(stat) -> float | None:
    """Return the average roll's position in this stat's possible value range."""
    rolls = max(0, int(getattr(stat, "rolls", 0) or 0))
    if rolls <= 0:
        return None
    try:
        total = abs(float(getattr(stat, "value", None)))
    except (TypeError, ValueError):
        return None
    fingerprints = tuple(
        abs(float(value))
        for value in CHAOS_FINGERPRINTS.get(int(getattr(stat, "stat_id", -1)), ())
    )
    if not fingerprints:
        return None
    minimum = min(fingerprints)
    maximum = max(fingerprints)
    if maximum <= minimum:
        return 1.0
    average = total / rolls
    return max(0.0, min(1.0, (average - minimum) / (maximum - minimum)))


def chaos_roll_quality_color(quality: float | None) -> str:
    """Map normalized roll quality to the four visual tiers used by the card."""
    if quality is None or quality < 0.34:
        return "#98A7BA"
    if quality < 0.67:
        return "#60A5FA"
    if quality < 0.90:
        return "#C084FC"
    return "#FACC15"


def chaos_stat_label(stat) -> str:
    label = str(getattr(stat, "label", ""))
    return label or f"Stat {getattr(stat, 'stat_id', '?')}"


#: Which method redraws each deferrable panel. Spelled out rather than derived
#: from the section name, so renaming one fails here loudly instead of silently
#: leaving that panel stale forever.
_SECTION_RENDERERS = {
    "weapons": StatCardsView.display_weapons,
    "tomes": StatCardsView.display_tomes,
    "chaos": StatCardsView.display_chaos_tome,
    "damage_sources": StatCardsView.display_damage_sources,
}
