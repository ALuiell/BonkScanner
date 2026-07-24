"""The data a compare-runs metric card shows, with no markup attached.

The Weapons, Tomes and Chaos cards are the same shape -- a stack of sections,
each a small four-column table of `label | run A | run B | delta`. That shape
used to exist only as HTML strings built in `formatting.py`, which meant the
renderer was fixed: a `QLabel` re-parsing and re-laying-out a 12--16 KB
document on every scrub frame, measured at 63--65 ms per card against 0.26 ms
for the entire Python half of the frame.

These types are the seam that lets the same content be rendered by widgets
instead. They are plain frozen dataclasses so a rendered payload can be
compared with `==` for the diff-card dirty check, and so the *content* can be
tested without a `QApplication`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


#: A delta's direction, resolved once here rather than re-derived by each
#: renderer from the sign character.
DELTA_NEUTRAL = "neutral"
DELTA_POSITIVE = "positive"
DELTA_NEGATIVE = "negative"


def delta_direction(delta: str) -> str:
    """Mirror of `_format_metric_delta_rich_text`'s colour choice.

    The `--` check has to come first and has to be exact: it is the "nothing to
    compare" dash, and testing `startswith("-")` on it paints a missing value
    red. That ordering is the one the HTML renderer already used.
    """
    text = str(delta or "").strip()
    if text == "--":
        return DELTA_NEUTRAL
    if text.startswith("+"):
        return DELTA_POSITIVE
    if text.startswith("-"):
        return DELTA_NEGATIVE
    return DELTA_NEUTRAL


@dataclass(frozen=True)
class MetricRow:
    """One metric compared across the two runs.

    `label_color` is for the Items card, whose row labels are item names
    coloured by rarity. Empty means the renderer's default label colour, which
    is what every other card wants.
    """

    label: str
    value_a: str
    value_b: str
    delta: str
    label_color: str = ""

    @property
    def direction(self) -> str:
        return delta_direction(self.delta)


@dataclass(frozen=True)
class MetricSection:
    """One card within a card: a heading and the rows under it.

    `title` is an entity name (a weapon, a tome) and `subtitle` its level
    transition; a section that heads a plain table instead -- Chaos -- leaves
    both empty and puts its column name in `headers[0]`.
    """

    headers: tuple[str, str, str, str]
    rows: tuple[MetricRow, ...] = ()
    title: str = ""
    subtitle: str = ""


@dataclass(frozen=True)
class MetricTable:
    """Everything one diff card renders.

    `empty_text` is shown in place of the sections when there are none, which
    is the "No weapon data" case the HTML formatters also carry.
    """

    sections: tuple[MetricSection, ...] = field(default_factory=tuple)
    empty_text: str = ""

    def __bool__(self) -> bool:
        return bool(self.sections)


EMPTY_METRIC_TABLE = MetricTable()
