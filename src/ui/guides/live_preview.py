"""Compact Live Stats examples rendered with the guide's own controls."""
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from core.item_metadata import ITEM_RARITY_COLOR_MAP
from core.luck_rarity import format_expected_count, game_rarity_name
from ui import i18n as l10n
from ui.tabs.player_stats.stat_cards import (
    chaos_average_roll_quality,
    chaos_roll_quality_color,
    chaos_stats_by_roll_count,
    shrine_average_roll_quality,
)

from .guide_locale import bind, message, ui
from .run_sample import load_run_example


_STYLE = """
QWidget#GuideLivePreview { background:#141d29; }
QFrame#GuideLiveCard { background:#172333; border:1px solid #2d4258; border-radius:11px; }
QLabel#GuideLiveCardTitle { background:transparent; color:#d7eaff; font-size:16px; font-weight:700; }
QLabel#GuideLiveCardBody { background:transparent; color:#cbd9e8; font-size:13px; }
QFrame#GuideLiveMetrics { background:transparent; border:0; border-top:1px solid #30465b; }
QLabel#GuideLiveMetricName { background:transparent; color:#c6dbef; font-size:12px; font-weight:600; }
QLabel#GuideLiveMetricValue { background:transparent; color:#f0f7ff; font-size:23px; font-weight:700; }
QLabel#GuideLiveMetricNote { background:transparent; color:#a7bcd1; font-size:12px; }
"""

_LIVE_TABS = (
    ("loot", "Loot"), ("chaos", "Chaos"), ("shrines", "Shrines"), ("passives", "Passives"),
)


@dataclass(frozen=True)
class _Metric:
    name: Callable[[], str]
    value: str
    note: Callable[[], str] | None = None
    color: str | None = None


def _roll_metric(stat, count, *, color=None):
    return _Metric(
        lambda: str(l10n.stat(stat.label)), stat.display_delta,
        (lambda: str(l10n.tr("● Rolls: {count}", count=count))) if count is not None else None,
        color,
    )


def _run_metrics():
    example = load_run_example()
    loot = example.live_snapshot
    legendary = "LEGENDARY"
    expected = format_expected_count(loot.loot_expected.get(legendary))
    chaos = next((s.chaos_tome for s in reversed(example.snapshots) if s.chaos_tome and s.chaos_tome.stats), None)
    passive = next((s.character_passive for s in reversed(example.snapshots)
                    if s.character_passive and s.character_passive.effects), None)
    shrines = example.live_shrines
    shrine_stats = sorted(shrines.stats, key=lambda stat: (-stat.rolls, stat.stat_id)) if shrines else ()
    return {
        "loot": (
            _Metric(
                lambda: str(l10n.game("rarities", game_rarity_name(legendary))),
                str(loot.loot_actual.get(legendary, 0)),
                lambda: message("run.metric.expected", count=expected),
                ITEM_RARITY_COLOR_MAP[legendary],
            ),
            _Metric(
                lambda: message("run.metric.chests"), f"{loot.chests_opened} / {loot.chests_total}",
                lambda: message("run.metric.keys", count=loot.key_procs),
            ),
        ),
        "chaos": tuple(
            _roll_metric(stat, stat.rolls, color=chaos_roll_quality_color(chaos_average_roll_quality(stat)))
            for stat in chaos_stats_by_roll_count(chaos)[:2]
        ),
        "shrines": tuple(
            _roll_metric(stat, stat.rolls, color=chaos_roll_quality_color(shrine_average_roll_quality(stat)))
            for stat in shrine_stats[:2]
        ),
        "passives": tuple(_roll_metric(effect, effect.count) for effect in passive.effects[:2]) if passive else (),
    }


def _label(role, text) -> QLabel:
    label = QLabel()
    label.setObjectName(role)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return bind(label, text)


def _metric_strip(metrics) -> QFrame:
    strip = QFrame()
    strip.setObjectName("GuideLiveMetrics")
    grid = QGridLayout(strip)
    grid.setContentsMargins(0, 10, 0, 0)
    grid.setHorizontalSpacing(14)
    grid.setVerticalSpacing(4)
    for column, metric in enumerate(metrics):
        grid.setColumnStretch(column, 1)
        grid.addWidget(_label("GuideLiveMetricName", metric.name), 0, column)
        value = _label("GuideLiveMetricValue", lambda item=metric: item.value)
        grid.addWidget(value, 1, column)
        if metric.note is not None:
            note = _label("GuideLiveMetricNote", metric.note)
            if metric.color is not None:
                note.setStyleSheet(f"color:{metric.color};")
            grid.addWidget(note, 2, column)
    return strip


class LiveStatsGuidePreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("GuideLivePreview")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet(_STYLE)
        self._columns = 0
        self._cards = []
        self._grid = QGridLayout()
        self._grid.setSpacing(14)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._grid)
        layout.addStretch(1)

        examples = _run_metrics()
        for key, caption in _LIVE_TABS:
            card = QFrame()
            card.setObjectName("GuideLiveCard")
            card.setMinimumHeight(166)
            body = QVBoxLayout(card)
            body.setContentsMargins(17, 15, 17, 15)
            body.setSpacing(8)
            body.addWidget(_label("GuideLiveCardTitle", lambda label=caption: ui(label)))
            body.addWidget(_label("GuideLiveCardBody", lambda feature=key: message(f"run.card.{feature}")))
            body.addStretch(1)
            if examples[key]:
                body.addWidget(_metric_strip(examples[key]))
            self._cards.append(card)
        self._reflow_cards()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_cards()

    def _reflow_cards(self):
        columns = 1 if self.width() < 480 else 2
        if columns == self._columns:
            return
        self._columns = columns
        for index, card in enumerate(self._cards):
            self._grid.removeWidget(card)
            self._grid.addWidget(card, index // columns, index % columns)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, int(columns == 2))
