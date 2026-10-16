"""Read-only roll presentation shared by lifetime and recording views.

The 27-stat reference model describes the archived game build, not a runtime
verification of the game version in an arbitrary recording. See the mechanics
proof in docs/research/roll_analytics_enhancements.md. It predicts stat identity,
not bonus strength, rarity or the next outcome.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

from core.roll_analytics import (
    ROLL_SOURCES, ROLL_STAT_IDS, RollAnalyticsSnapshot,
    aggregate_roll_counts, confirmed_roll_counts,
)

REFERENCE_STAT_IDS = frozenset({
    0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 15, 16, 17, 18, 19,
    23, 24, 25, 29, 30, 31, 32, 38, 39, 40, 41, 46,
})
REFERENCE_MODEL_LABEL = "27-stat reference model"
REFERENCE_MODEL_NOTE = (
    "Expected = confirmed rolls / 27 per stat. Verified against the archived "
    "game build; the game version of lifetime data or a recording is not verified. "
    "This is a reference model, not a prediction or a luck score."
)


def normalize_selected_stats(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (tuple, list, set, frozenset)):
        return ()
    return tuple(sorted({v for v in value if type(v) is int and v in ROLL_STAT_IDS}))


def expected_rolls(source: str, total: int, stat_ids) -> float | None:
    """No expectation for an empty sample or a drifted/unrecognized stat pool."""
    if source not in ROLL_SOURCES or total <= 0 or ROLL_STAT_IDS != REFERENCE_STAT_IDS:
        return None
    return total * len(set(stat_ids) & REFERENCE_STAT_IDS) / len(REFERENCE_STAT_IDS)


@dataclass(frozen=True, slots=True)
class SelectedRollSummary:
    selected_stats: int
    count: int
    total: int
    percent: float | None
    expected: float | None

    @property
    def difference(self) -> float | None:
        return self.count - self.expected if self.expected is not None else None


def summarize_selected(snapshot: RollAnalyticsSnapshot, selected) -> SelectedRollSummary:
    selected = frozenset(normalize_selected_stats(selected))
    count = sum(row.count for row in snapshot.rows if row.stat_id in selected)
    return SelectedRollSummary(
        len(selected), count, snapshot.total,
        count / snapshot.total * 100 if snapshot.total and selected else None,
        expected_rolls(snapshot.source, snapshot.total, selected) if selected else None,
    )


@dataclass(frozen=True, slots=True)
class RecordedRollSource:
    source: str
    analytics: RollAnalyticsSnapshot | None = None
    game_time_seconds: float | None = None
    elapsed_seconds: float | None = None
    older_snapshot: bool = False
    reason: str = "No confirmed roll counters in the final snapshots."


def finite_time(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if isfinite(value) and value >= 0 else None


def valid_recorded_counter_block(raw: Any, source: str) -> bool:
    """Reject legacy missing counts and malformed numbers before permissive VOD coercion.

    Presence must not be reconstructed as zero. `pending` is deliberately not a
    rejection rule: Dice may have unrelated source candidates in its queue.
    """
    if (source not in ROLL_SOURCES or not isinstance(raw, Mapping)
            or type(raw.get("level")) is not int or raw["level"] < 0):
        return False
    # VOD's permissive integer coercion can turn a malformed ambiguity value
    # (negative, fractional, missing-value marker) into zero. Do not let that
    # manufacture a confirmed source. Absence remains valid for legacy files.
    ambiguity_key = "ambiguous_rolls" if source == "chaos" else "ambiguous"
    ambiguity = raw.get(ambiguity_key, 0)
    if type(ambiguity) is not int or ambiguity < 0:
        return False
    key, counter = ("stats", "rolls") if source == "chaos" else ("effects", "count")
    rows = raw.get(key)
    if not isinstance(rows, list):
        return False
    seen = set()
    total = 0
    for row in rows:
        if not isinstance(row, Mapping):
            return False
        if source == "dice" and row.get("kind") != "permanent_roll":
            continue
        stat_id, count = row.get("stat_id"), row.get(counter)
        if (type(stat_id) is not int or stat_id not in ROLL_STAT_IDS or stat_id in seen
                or type(count) is not int or count < 0):
            return False
        seen.add(stat_id)
        total += count
    return total == raw["level"]


def recorded_source_from_snapshot(snapshot, source: str, *, older: bool = False) -> RecordedRollSource:
    """Adapt an already-loaded immutable VOD snapshot without I/O or recounting."""
    if source not in ROLL_SOURCES:
        raise ValueError("Unknown roll source")
    chaos = getattr(snapshot, "chaos_tome", None)
    passive = getattr(snapshot, "character_passive", None)
    available = confirmed_roll_counts(chaos, passive)
    counts = available.get(source)
    block = chaos if source == "chaos" else passive
    # Older loaders may yield a supported passive with counts missing. A matching
    # level budget is required here in addition to the live source-quality gate.
    if counts is None or block is None or sum(counts.values()) != block.level:
        return RecordedRollSource(source)
    return RecordedRollSource(
        source, aggregate_roll_counts(source, counts),
        finite_time(getattr(snapshot, "game_time_seconds", None)),
        finite_time(getattr(snapshot, "elapsed_seconds", None)), older, "",
    )
