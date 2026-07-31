"""The data the redesigned Compare Runs Overview draws, with no markup.

The old Overview was a three-line `QLabel` verdict next to a six-row snapshot
table, and roughly a fifth of its width was an empty stretch. Both halves said
the same four numbers -- kills, level, items, time -- which the run plaques
above and the timeline legend beside them had already said.

This module answers a different question, which is the one the page is for:
**where do these two runs actually differ, and was it the build or the loot?**

Two projections:

* `build_compare_runs_axis` ranks every comparable metric by how far apart the
  runs are and names the leader, so the page needs no delta sign convention at
  all -- a row says "A +572", not "+572";
* `build_compare_runs_luck_loot` compares what dropped against what the game
  was expected to drop at each run's Luck. Nothing else in the app answers
  "did B win, or did B get lucky".

Both are frozen dataclasses so the tab's diff cache can compare a rendered
payload with `==`, exactly as it does for `MetricTable`.

One rule runs through the loot half, and it is the reason it has as many
"unavailable" fields as it has values: `loot_actual`/`loot_expected` are `None`
for a recording made before the tracker measured them, and `None` means **not
measured**, never zero. A comparison that read absence as zero would report
"no legendaries dropped" where the truth is "we do not know". The two sides
fail apart, too: run A can be measured while run B is not, and the half that
can still be computed is still shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.luck_rarity import LUCK_RARITY_ORDER, format_expected_count
from projections import formatting


#: Which side a row favours. `NEITHER` is a row the runs agree on, which the
#: axis drops entirely -- it exists so a caller can ask without a `None` check.
LEAD_A = "a"
LEAD_B = "b"
LEAD_NEITHER = ""


@dataclass(frozen=True)
class AxisRow:
    """One metric, and how far apart the two runs are on it.

    `magnitude` is 0..1 relative to the widest row in the same table, so the
    bars are comparable within one axis and meaningless across two -- which is
    correct: the axis ranks *this* pair of runs, it is not a scale.
    """

    label: str
    lead: str
    magnitude: float
    value_a: str
    value_b: str
    summary: str


@dataclass(frozen=True)
class AxisTable:
    rows: tuple[AxisRow, ...] = field(default_factory=tuple)
    empty_text: str = ""

    def __bool__(self) -> bool:
        return bool(self.rows)


@dataclass(frozen=True)
class LootRung:
    """One rarity tier. `ratio_*` is actual/expected, `None` when unmeasured."""

    rarity: str
    actual_a: str
    expected_a: str
    ratio_a: float | None
    actual_b: str
    expected_b: str
    ratio_b: float | None


@dataclass(frozen=True)
class ChestRow:
    label: str
    value_a: str
    value_b: str


@dataclass(frozen=True)
class LuckLoot:
    """The Luck & Loot block. `available_*` gates the loot half per side."""

    available_a: bool = False
    available_b: bool = False
    index_a: str = "--"
    index_b: str = "--"
    detail_a: str = ""
    detail_b: str = ""
    luck_a: str = "--"
    luck_b: str = "--"
    luck_delta: str = "--"
    verdict: str = ""
    verdict_detail: str = ""
    rungs: tuple[LootRung, ...] = field(default_factory=tuple)
    chests: tuple[ChestRow, ...] = field(default_factory=tuple)
    notice: str = ""


EMPTY_AXIS_TABLE = AxisTable(empty_text="Select two recordings")
EMPTY_LUCK_LOOT = LuckLoot()

#: Shown when both runs sit on identical values for everything comparable.
AXIS_NO_DIFFERENCE_TEXT = "These two runs match on every comparable metric"
#: Shown when neither recording carries loot measurements.
LOOT_UNMEASURED_TEXT = (
    "Neither recording measured its loot. These runs were recorded before the "
    "tracker could count drops -- that is \"not measured\", not \"nothing dropped\"."
)


# --------------------------------------------------------------------------
# Axis
# --------------------------------------------------------------------------


def _count(snapshot, attr: str) -> float | None:
    value = getattr(snapshot, attr, None)
    return None if value is None else float(value)


def _stat_value(snapshot, label: str) -> float | None:
    stats = getattr(snapshot, "stats", None)
    stat = stats.get(label) if isinstance(stats, dict) else None
    value = getattr(stat, "value", None)
    return None if value is None else float(value)


def _stat(snapshot, label: str):
    stats = getattr(snapshot, "stats", None)
    return stats.get(label) if isinstance(stats, dict) else None


def _stat_display(snapshot, label: str) -> str:
    stat = _stat(snapshot, label)
    return str(getattr(stat, "display_value", "--")) if stat is not None else "--"


def _stat_gap_text(snapshot_a, snapshot_b, label: str) -> str | None:
    """The gap between two stats, in the units that stat is displayed in.

    A stat is `1212%` or `2.07x`, never a bare float, so a summary built from
    `value_a - value_b` reads `+102.857` where the column beside it reads
    `+102.86%`. This borrows the formatter the Stats table already uses and
    drops the sign, because the leader is named separately.
    """
    stat_a = _stat(snapshot_a, label)
    stat_b = _stat(snapshot_b, label)
    if stat_a is None or stat_b is None:
        return None
    if getattr(stat_a, "value", None) is None or getattr(stat_b, "value", None) is None:
        return None
    return formatting._format_compare_run_stat_delta(stat_a, stat_b).lstrip("+-")


def _item_total(snapshot) -> float:
    return float(formatting._snapshot_item_total(snapshot))


def build_compare_runs_axis(
    snapshot_a,
    snapshot_b,
    *,
    stat_labels: tuple[str, ...] = (),
) -> AxisTable:
    """Rank the metrics these two runs disagree on, widest gap first.

    Rows the runs agree on are dropped rather than greyed: the axis exists to
    show divergence, and a screen full of centred zero-length bars would hide
    the three rows that matter.
    """
    if snapshot_a is None or snapshot_b is None:
        return EMPTY_AXIS_TABLE

    # `(label, value A, value B, display A, display B, gap text or None)`.
    # A `None` gap text means "count it", which is the four run-progress rows;
    # a stat brings its own, in its own units.
    candidates: list[tuple[str, float | None, float | None, str, str, str | None]] = [
        (
            "Kills",
            _count(snapshot_a, "mob_kills"),
            _count(snapshot_b, "mob_kills"),
            formatting.format_count(getattr(snapshot_a, "mob_kills", None) or 0),
            formatting.format_count(getattr(snapshot_b, "mob_kills", None) or 0),
            None,
        ),
        (
            "Level",
            _count(snapshot_a, "player_level"),
            _count(snapshot_b, "player_level"),
            str(getattr(snapshot_a, "player_level", None) or "--"),
            str(getattr(snapshot_b, "player_level", None) or "--"),
            None,
        ),
        (
            "Items",
            _item_total(snapshot_a),
            _item_total(snapshot_b),
            formatting.format_count(int(_item_total(snapshot_a))),
            formatting.format_count(int(_item_total(snapshot_b))),
            None,
        ),
        (
            "Chests opened",
            _count(snapshot_a, "chests_opened"),
            _count(snapshot_b, "chests_opened"),
            formatting.format_count(getattr(snapshot_a, "chests_opened", None) or 0),
            formatting.format_count(getattr(snapshot_b, "chests_opened", None) or 0),
            None,
        ),
    ]
    for label in stat_labels:
        candidates.append(
            (
                str(label),
                _stat_value(snapshot_a, label),
                _stat_value(snapshot_b, label),
                _stat_display(snapshot_a, label),
                _stat_display(snapshot_b, label),
                _stat_gap_text(snapshot_a, snapshot_b, label),
            )
        )

    scored: list[tuple[float, str, str, float, str, str, str]] = []
    for label, value_a, value_b, display_a, display_b, gap_text in candidates:
        if value_a is None or value_b is None or value_a == value_b:
            continue
        scale = max(abs(value_a), abs(value_b))
        if not scale:
            continue
        relative = abs(value_a - value_b) / scale
        lead = LEAD_A if value_a > value_b else LEAD_B
        summary = _axis_summary(lead, abs(value_a - value_b), gap_text)
        scored.append((relative, label, lead, relative, display_a, display_b, summary))

    if not scored:
        return AxisTable(empty_text=AXIS_NO_DIFFERENCE_TEXT)

    widest = max(row[0] for row in scored)
    scored.sort(key=lambda row: (-row[0], row[1].casefold()))
    rows = tuple(
        AxisRow(
            label=label,
            lead=lead,
            # The widest row fills its half; everything else is drawn against
            # it. Dividing by the widest rather than by 1.0 is what keeps a
            # table of three near-identical rows readable.
            magnitude=min(1.0, relative / widest) if widest else 0.0,
            value_a=display_a,
            value_b=display_b,
            summary=summary,
        )
        for _score, label, lead, relative, display_a, display_b, summary in scored
    )
    return AxisTable(rows=rows)


def _axis_summary(lead: str, gap: float, gap_text: str | None) -> str:
    """`A +572` -- the leader named, so the row needs no sign convention."""
    side = "A" if lead == LEAD_A else "B"
    formatted = gap_text if gap_text else formatting.format_count(int(round(gap)))
    return f"{side} +{formatted}"


# --------------------------------------------------------------------------
# Luck & Loot
# --------------------------------------------------------------------------


def _loot_totals(snapshot) -> tuple[bool, float, float]:
    """`(measured, actual total, expected total)` for one side."""
    actual = getattr(snapshot, "loot_actual", None)
    expected = getattr(snapshot, "loot_expected", None)
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return False, 0.0, 0.0
    actual_total = float(sum(max(0, int(count)) for count in actual.values()))
    expected_total = float(sum(max(0.0, float(count)) for count in expected.values()))
    return True, actual_total, expected_total


def _luck_index(actual: float, expected: float) -> tuple[str, float | None]:
    if expected <= 0:
        return "--", None
    ratio = actual / expected
    return f"{ratio:.2f}x", ratio


def build_compare_runs_luck_loot(snapshot_a, snapshot_b) -> LuckLoot:
    """Compare what dropped against what each run's Luck predicted.

    The Luck *stat* half is always available -- it is read straight off the
    snapshot -- while the counts half needs both `loot_actual` and
    `loot_expected`. They are reported separately for exactly that reason, the
    same split the live rarity card already makes.
    """
    if snapshot_a is None or snapshot_b is None:
        return EMPTY_LUCK_LOOT

    available_a, actual_a, expected_a = _loot_totals(snapshot_a)
    available_b, actual_b, expected_b = _loot_totals(snapshot_b)
    index_a, ratio_a = _luck_index(actual_a, expected_a) if available_a else ("--", None)
    index_b, ratio_b = _luck_index(actual_b, expected_b) if available_b else ("--", None)

    luck_a = _stat_display(snapshot_a, "Luck")
    luck_b = _stat_display(snapshot_b, "Luck")
    luck_raw_a = _stat_value(snapshot_a, "Luck")
    luck_raw_b = _stat_value(snapshot_b, "Luck")
    stat_a = _stat(snapshot_a, "Luck")
    stat_b = _stat(snapshot_b, "Luck")
    # Same formatter as the Stats table, so the tile agrees with the column.
    luck_delta = (
        formatting._format_compare_run_stat_delta(stat_a, stat_b)
        if stat_a is not None and stat_b is not None and luck_raw_a is not None
        and luck_raw_b is not None
        else "--"
    )

    notice = ""
    if not available_a and not available_b:
        notice = LOOT_UNMEASURED_TEXT
    elif not available_b:
        notice = "Run B did not measure its loot. Run A is still compared; B reads as not measured."
    elif not available_a:
        notice = "Run A did not measure its loot. Run B is still compared; A reads as not measured."

    return LuckLoot(
        available_a=available_a,
        available_b=available_b,
        index_a=index_a,
        index_b=index_b,
        detail_a=_loot_detail(available_a, actual_a, expected_a),
        detail_b=_loot_detail(available_b, actual_b, expected_b),
        luck_a=luck_a,
        luck_b=luck_b,
        luck_delta=luck_delta,
        verdict=_verdict(ratio_a, ratio_b, luck_raw_a, luck_raw_b),
        verdict_detail=_verdict_detail(ratio_a, ratio_b),
        rungs=_build_rungs(snapshot_a, snapshot_b, available_a, available_b),
        chests=_build_chest_rows(snapshot_a, snapshot_b),
        notice=notice,
    )


def _loot_detail(available: bool, actual: float, expected: float) -> str:
    if not available:
        return "loot not recorded"
    return f"{int(actual)} items · expected {format_expected_count(expected)}"


def _build_rungs(snapshot_a, snapshot_b, available_a: bool, available_b: bool):
    actual_a = getattr(snapshot_a, "loot_actual", None) or {}
    expected_a = getattr(snapshot_a, "loot_expected", None) or {}
    actual_b = getattr(snapshot_b, "loot_actual", None) or {}
    expected_b = getattr(snapshot_b, "loot_expected", None) or {}
    if not available_a and not available_b:
        return ()

    def cell(available, actual, expected, rarity):
        if not available:
            return "--", "--", None
        count = int(actual.get(rarity, 0) or 0)
        predicted = float(expected.get(rarity, 0.0) or 0.0)
        ratio = count / predicted if predicted > 0 else None
        return str(count), format_expected_count(predicted), ratio

    rungs = []
    for rarity in LUCK_RARITY_ORDER:
        count_a, predicted_a, ratio_a = cell(available_a, actual_a, expected_a, rarity)
        count_b, predicted_b, ratio_b = cell(available_b, actual_b, expected_b, rarity)
        rungs.append(
            LootRung(
                rarity=rarity.title(),
                actual_a=count_a,
                expected_a=predicted_a,
                ratio_a=ratio_a,
                actual_b=count_b,
                expected_b=predicted_b,
                ratio_b=ratio_b,
            )
        )
    return tuple(rungs)


#: The chest rows the Overview carries. The rest of `chests_card_values` --
#: per-stage totals, key counts, the proc chance -- belongs to a dedicated
#: card, not to a verdict page.
_CHEST_ROWS = (
    ("Opened / total", "total"),
    ("Paid / free", "paid_free"),
    ("Key procs", "key_procs"),
    ("Chests / min", "chests_per_minute"),
)


def _chest_values(snapshot) -> dict[str, str]:
    return formatting.chests_card_values(
        getattr(snapshot, "chests_opened_by_stage", None),
        getattr(snapshot, "chests_total_by_stage", None),
        getattr(snapshot, "chests_opened", None),
        getattr(snapshot, "chests_total", None),
        getattr(snapshot, "paid_chests", None),
        getattr(snapshot, "key_procs", None),
        getattr(snapshot, "free_chests", None),
        getattr(snapshot, "keys_count", None),
        getattr(snapshot, "expected_key_procs", None),
        False,
        chests_per_minute=formatting.resolve_snapshot_chests_per_minute(snapshot),
    )


def _build_chest_rows(snapshot_a, snapshot_b) -> tuple[ChestRow, ...]:
    values_a = _chest_values(snapshot_a)
    values_b = _chest_values(snapshot_b)
    return tuple(
        ChestRow(label, values_a.get(key, "--"), values_b.get(key, "--"))
        for label, key in _CHEST_ROWS
    )


def _verdict(ratio_a, ratio_b, luck_a, luck_b) -> str:
    """One sentence, and only when the two halves actually disagree.

    A verdict that fired on every frame would be noise, and one computed from a
    handful of drops would be superstition dressed as analysis -- so it stays
    silent unless both sides were measured and the gap is wide enough to mean
    something.
    """
    if ratio_a is None or ratio_b is None:
        return ""
    if abs(ratio_a - ratio_b) < 0.15:
        return "Both runs landed close to their expected loot"
    lucky, unlucky = ("A", "B") if ratio_a > ratio_b else ("B", "A")
    if luck_a is not None and luck_b is not None:
        higher_luck = "A" if luck_a > luck_b else "B" if luck_b > luck_a else ""
        if higher_luck and higher_luck == unlucky:
            return f"{higher_luck} carried more Luck but drew less loot"
    return f"{lucky} drew more loot than expected"


# --------------------------------------------------------------------------
# Hub tiles
# --------------------------------------------------------------------------


def _changed_rows(section) -> int:
    return sum(
        1
        for row in section.rows
        if str(row.delta).strip() not in {"", "--", "0", "+0", "-0", "+0s", "-0s"}
    )


def build_hub_facts(
    snapshot_a,
    snapshot_b,
    *,
    stages_table=None,
    weapons_table=None,
    enabled: dict[str, bool] | None = None,
) -> dict[str, str]:
    """One headline per destination, and nothing for a section that is off.

    A tile that jumped to a disabled -- and therefore empty -- tab would be
    worse than no tile, so a section the user has switched off simply does not
    get one. That is also why the facts are derived from the tables the tab has
    *already* built rather than recomputed: an off section has no table.
    """
    enabled = enabled or {}
    facts: dict[str, str] = {}

    if enabled.get("stage_summary") and stages_table is not None:
        widest = None
        for section in getattr(stages_table, "sections", ()):
            for row in section.rows:
                if str(row.label).casefold() != "time" or row.delta in {"--", ""}:
                    continue
                try:
                    gap = abs(float(str(row.delta).rstrip("s")))
                except ValueError:
                    continue
                if widest is None or gap > widest[0]:
                    # The stages table carries raw seconds (`+1079s`), which is
                    # fine in a column of them and unreadable in a sentence.
                    lead = "A" if str(row.delta).startswith("-") else "B"
                    widest = (
                        gap,
                        section.title or "Stage",
                        f"{lead} −{formatting.format_elapsed_time(gap)}",
                    )
        if widest is not None:
            facts["Stages"] = f"{widest[1]} diverges most · {widest[2]}"

    if enabled.get("items") and snapshot_a is not None and snapshot_b is not None:
        gap = int(_item_total(snapshot_a) - _item_total(snapshot_b))
        facts["Items"] = (
            "Both runs hold the same number of items"
            if gap == 0
            else f"{'A' if gap > 0 else 'B'} holds {abs(gap)} more items"
        )

    if enabled.get("weapons") and weapons_table is not None:
        busiest = None
        for section in getattr(weapons_table, "sections", ()):
            changes = _changed_rows(section)
            if changes and (busiest is None or changes > busiest[0]):
                busiest = (changes, section.title or "Weapon")
        if busiest is not None:
            facts["Weapons"] = f"{busiest[1]} · {busiest[0]} differences"

    return facts


def _verdict_detail(ratio_a, ratio_b) -> str:
    if ratio_a is None or ratio_b is None:
        return ""
    return f"A {ratio_a:.2f}x · B {ratio_b:.2f}x against expectation"
