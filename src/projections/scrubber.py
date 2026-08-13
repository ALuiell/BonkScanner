"""Read model behind the Recordings scrubber.

Everything the scrubber paints, derived from a loaded recording's snapshots and
nothing else: stage bands, plottable series, the Difficulty/XP-Gain cap
staircase, and the event markers. Qt-free on purpose -- the widget in
``ui/tabs/player_stats/recording_scrubber.py`` owns pixels, this owns meaning,
and the split is what lets the arithmetic be tested without an offscreen
``QApplication``.

Built once per loaded recording, not per frame. A run is up to ~900 snapshots
and a scrub drag repaints at pointer rate; recomputing 30 stat series inside
``paintEvent`` would put the whole walk on the drag path.

**What recordings do not carry**, and so what this model cannot answer:

* ``is_graveyard``. The overlay reads it from live game state; nothing persists
  it, so cap steps here are always computed as a normal map stage. A graveyard
  run therefore gets stage-2 caps where the overlay would use stage-0's. Fixing
  it means recording one more field, not changing this file.
* ``stage_index`` is absent from older recordings (``885k``, ``970k``,
  ``874k``). Bands survive that -- the stage walk falls back to stage-pointer
  and map-seed changes -- but the Difficulty cap staircase does not, because
  the cap table is keyed on the raw index and there is nothing to key on.
  Those recordings get bands and no caps, and ``available`` on each part says
  which, rather than the model inventing zeroes: "no data" and "zero" are
  different answers and a chart that conflates them lies.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.item_metadata import ITEM_RARITY_BY_NAME, normalize_item_name_for_rarity
from core.run_summary import item_counts, stage_number_sequence
from core.stage_rules import XP_GAIN_CAP, difficulty_cap, stage_duration_seconds
from core.stats.types import PLAYER_STAT_GROUPS


#: Series that are not player stats. Keyed the same way so a slot holds one
#: string either way and does not need to remember which kind it picked.
KILLS_SERIES = "@kills"
ITEMS_SERIES = "@items"

SYNTHETIC_SERIES_LABELS = {KILLS_SERIES: "Kills", ITEMS_SERIES: "Items"}

#: Series sharing an axis group are normalised against the group's maximum
#: rather than their own, so their relative magnitude survives. Powerup
#: Multiplier and Powerup Drop Chance both start at 1.0 and stay within one
#: order of magnitude of each other, which is what makes a shared axis honest
#: for them and dishonest for, say, Kills against Items.
AXIS_GROUPS: dict[str, str] = {
    "Powerup Multiplier": "powerups",
    "Powerup Drop Chance": "powerups",
}

#: An empty slot: selected nothing, draws nothing. Distinct from a slot whose
#: series has no data in *this* recording -- that one still says which series
#: it is holding, and says the recording cannot answer for it.
EMPTY_SLOT: tuple[str, ...] = ()

#: What the four slots hold on a fresh install. Two filled and two empty: four
#: curves at once is legible only once you already know what you are looking
#: for, and a first-run screen that starts crowded teaches nothing about which
#: line is which.
DEFAULT_SLOTS: tuple[tuple[str, ...], ...] = (
    (KILLS_SERIES,),
    ("Powerup Multiplier", "Powerup Drop Chance"),
    EMPTY_SLOT,
    EMPTY_SLOT,
)

#: Series colours, matched to the mockup in ``ui_mockups/``.
SERIES_COLORS: dict[str, str] = {
    KILLS_SERIES: "#38BDF8",
    ITEMS_SERIES: "#4ADE80",
    "Powerup Multiplier": "#FACC15",
    "Powerup Drop Chance": "#F59E0B",
    "Difficulty": "#F0787E",
    "XP Gain": "#C084FC",
    "Luck": "#60A5FA",
}
FALLBACK_SERIES_COLOR = "#94A3B8"

#: Rarities worth a marker on the track. Uncommon and Common are dropped: a
#: legendary pickup is an event, a common one is background noise, and at ~900
#: snapshots marking every gain would produce a solid bar.
MARKED_RARITIES = ("LEGENDARY", "RARE")

RARITY_MARKER_COLORS = {"LEGENDARY": "#FACC15", "RARE": "#A78BFA"}
BANISH_MARKER_COLOR = "#F0787E"


def available_series_keys() -> tuple[str, ...]:
    """Every key a slot may hold, in the order a picker should show them."""
    stat_labels = tuple(spec.label for group in PLAYER_STAT_GROUPS for spec in group)
    return (KILLS_SERIES, ITEMS_SERIES) + stat_labels


def series_label(key: str) -> str:
    return SYNTHETIC_SERIES_LABELS.get(key, key)


def series_color(key: str) -> str:
    return SERIES_COLORS.get(key, FALLBACK_SERIES_COLOR)


@dataclass(frozen=True)
class StageBand:
    """One run of consecutive snapshots sharing a stage."""

    start: int
    end: int
    stage_index: int | None
    label: str
    elapsed_seconds: int

    @property
    def span(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True)
class CapStep:
    """The cap in force across ``[start, end]``, in raw stat units."""

    start: int
    end: int
    value: float


@dataclass(frozen=True)
class Marker:
    """A point event: an item gain worth noticing, or a banish."""

    index: int
    kind: str
    color: str
    text: str


@dataclass(frozen=True)
class Series:
    key: str
    label: str
    color: str
    values: tuple[float | None, ...]
    #: What the curve is scaled against. Equals this series' own maximum unless
    #: it shares an axis group.
    scale: float
    available: bool

    def normalised(self, index: int) -> float | None:
        """``0.0..1.0``, or ``None`` where this snapshot has no reading."""
        if not self.available or self.scale <= 0.0:
            return None
        value = self.values[index] if 0 <= index < len(self.values) else None
        if value is None:
            return None
        return max(0.0, min(1.0, value / self.scale))


@dataclass(frozen=True)
class ScrubberModel:
    """Everything the widget paints for one loaded recording."""

    count: int
    stages: tuple[StageBand, ...] = ()
    markers: tuple[Marker, ...] = ()
    _series: dict[str, Series] = field(default_factory=dict)
    _caps: dict[str, tuple[CapStep, ...]] = field(default_factory=dict)

    def series(self, key: str) -> Series | None:
        return self._series.get(key)

    def caps(self, key: str) -> tuple[CapStep, ...]:
        return self._caps.get(key, ())

    def cap_at(self, key: str, index: int) -> float | None:
        for step in self.caps(key):
            if step.start <= index <= step.end:
                return step.value
        return None

    def series_scale(self, key: str, *, include_cap: bool = False) -> float:
        """The vertical scale for ``key``, optionally including its ceiling.

        A curve normally uses its own recorded maximum so a quiet run remains
        readable. Once its cap is drawn, however, both values share an axis: a
        cap above the recording must expand that axis instead of being clamped
        onto the curve's maximum at the top edge.
        """
        series = self.series(key)
        scale = float(series.scale) if series is not None else 0.0
        if include_cap:
            scale = max(scale, *(float(step.value) for step in self.caps(key)))
        return scale

    def position(self, index: int) -> float:
        """Where snapshot ``index`` sits along the track, ``0.0..1.0``."""
        if self.count <= 1:
            return 0.0
        return min(max(index, 0), self.count - 1) / (self.count - 1)

    def index_at(self, position: float) -> int:
        if self.count <= 1:
            return 0
        return min(max(int(round(position * (self.count - 1))), 0), self.count - 1)


def _stat_value(snapshot, label: str) -> float | None:
    stats = getattr(snapshot, "stats", None)
    if not isinstance(stats, dict):
        return None
    stat = stats.get(label)
    value = getattr(stat, "value", None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _item_total(snapshot) -> float:
    """Items held, counting stacks.

    Stacks rather than distinct names because the panel header already reads
    "262", and because the distinct count barely moves late in a run where the
    stacks keep climbing.
    """
    return float(sum(item_counts(getattr(snapshot, "items", ())).values()))


def _raw_values(snapshots, key: str) -> tuple[float | None, ...]:
    if key == KILLS_SERIES:
        return tuple(
            None if getattr(snapshot, "mob_kills", None) is None else float(snapshot.mob_kills)
            for snapshot in snapshots
        )
    if key == ITEMS_SERIES:
        return tuple(_item_total(snapshot) for snapshot in snapshots)
    return tuple(_stat_value(snapshot, key) for snapshot in snapshots)


def build_series(snapshots, keys) -> dict[str, Series]:
    """One ``Series`` per requested key, with axis groups already resolved."""
    raw = {key: _raw_values(snapshots, key) for key in keys}
    own_max: dict[str, float] = {}
    for key, values in raw.items():
        readings = [value for value in values if value is not None]
        own_max[key] = max(readings) if readings else 0.0

    group_max: dict[str, float] = {}
    for key in raw:
        group = AXIS_GROUPS.get(key)
        if group is not None:
            group_max[group] = max(group_max.get(group, 0.0), own_max[key])

    built: dict[str, Series] = {}
    for key, values in raw.items():
        group = AXIS_GROUPS.get(key)
        scale = group_max[group] if group is not None else own_max[key]
        built[key] = Series(
            key=key,
            label=series_label(key),
            color=series_color(key),
            values=values,
            scale=scale,
            available=any(value is not None for value in values) and scale > 0.0,
        )
    return built


def build_stage_bands(snapshots) -> tuple[StageBand, ...]:
    """Consecutive runs of the same stage, as bands.

    Grouped on ``run_summary.stage_number_sequence`` and **not** on the raw
    ``stage_index``. The raw index stays at 2 for the whole boss room, so
    grouping on it drew three bands for a run whose Stage Summary showed four
    rows -- the track and the cards under it disagreeing about the same run.

    A missing ``stage_index`` is **not** a reason to give up: the walk falls
    back to stage-pointer and map-seed changes, and the three oldest recordings
    in the library (``885k``, ``970k``, ``874k``) resolve to four stages that
    way. Gating on ``stage_index`` -- which this function did at first -- threw
    those bands away for a field the answer does not depend on.

    A run that produces a single Stage 1 band is reporting that no transition
    was observed, which for a short recording is simply true.
    """
    snapshots = tuple(snapshots or ())
    if not snapshots:
        return ()

    numbers = stage_number_sequence(snapshots)
    if not numbers:
        return ()

    bands: list[StageBand] = []
    start = 0

    def close(end: int, stage_number: int) -> None:
        elapsed = int(getattr(snapshots[end], "elapsed_seconds", 0) or 0) - int(
            getattr(snapshots[start], "elapsed_seconds", 0) or 0
        )
        bands.append(
            StageBand(
                start=start,
                end=end,
                # `stage_index` on a band is the zero-based number the widget
                # and the stage cards key off, kept as-is so `+ 1` stays the
                # human stage everywhere it is read.
                stage_index=stage_number - 1,
                label=f"Stage {stage_number}",
                elapsed_seconds=max(0, elapsed),
            )
        )

    for index in range(1, len(numbers)):
        if numbers[index] != numbers[index - 1]:
            close(index - 1, numbers[start])
            start = index
    close(len(numbers) - 1, numbers[start])
    return tuple(bands)


def build_cap_steps(snapshots, key: str) -> tuple[CapStep, ...]:
    """The cap staircase for ``key``, collapsed to runs of equal value.

    Difficulty's cap depends on the stage *and* on whether the ghosts have been
    out two minutes, so it is a staircase that steps at stage boundaries and
    again inside a stage. XP Gain's is flat, and falls out of the same shape.
    """
    if not snapshots:
        return ()
    if key == "XP Gain":
        return (CapStep(start=0, end=len(snapshots) - 1, value=XP_GAIN_CAP),)
    if key != "Difficulty":
        return ()

    steps: list[CapStep] = []
    for index, snapshot in enumerate(snapshots):
        stage_index = getattr(snapshot, "stage_index", None)
        stage_timer = float(getattr(snapshot, "stage_time_seconds", 0.0) or 0.0)
        # `is_graveyard=False` is not an assumption about this run so much as
        # the only answer available: see the module docstring.
        value = difficulty_cap(
            stage_index,
            stage_timer,
            is_graveyard=False,
            cap_stage_duration=stage_duration_seconds(stage_index, is_graveyard=False),
        )
        if value is None:
            continue
        if steps and steps[-1].end == index - 1 and steps[-1].value == value:
            steps[-1] = CapStep(start=steps[-1].start, end=index, value=value)
        else:
            steps.append(CapStep(start=index, end=index, value=value))
    return _absorb_cap_spikes(tuple(steps))


#: A cap step this short between two identical neighbours is not a real step.
CAP_SPIKE_MAX_SPAN = 2


def _absorb_cap_spikes(steps: tuple[CapStep, ...]) -> tuple[CapStep, ...]:
    """Merge away one- or two-snapshot steps wedged between equal neighbours.

    Not cosmetic smoothing: after the Graveyard boss the stage timer resumes
    from an offset on the main map -- expected behaviour, recorded in
    ``docs/`` as such -- which drops the elapsed timer back under the
    ghosts threshold for a snapshot or two and makes the cap appear to jump up
    and immediately back down. Painting that produces a spike the player never
    experienced, so a step that both neighbours disagree with and that lasts
    barely longer than the 10 s snapshot cadence is absorbed into them.
    """
    if len(steps) < 3:
        return steps
    merged = [steps[0]]
    index = 1
    while index < len(steps):
        step = steps[index]
        previous = merged[-1]
        following = steps[index + 1] if index + 1 < len(steps) else None
        span = step.end - step.start + 1
        if (
            following is not None
            and span <= CAP_SPIKE_MAX_SPAN
            and previous.value == following.value
            and previous.value != step.value
        ):
            merged[-1] = CapStep(start=previous.start, end=following.end, value=previous.value)
            index += 2
            continue
        merged.append(step)
        index += 1
    return tuple(merged)


def _rarity_of(item_name: str) -> str | None:
    return ITEM_RARITY_BY_NAME.get(normalize_item_name_for_rarity(item_name))


def build_markers(snapshots) -> tuple[Marker, ...]:
    """Legendary/rare item gains and banishes, one marker per event."""
    markers: list[Marker] = []
    previous_counts: dict[str, int] = {}
    previous_banishes: set[str] = set()
    for index, snapshot in enumerate(snapshots):
        counts = item_counts(getattr(snapshot, "items", ()))
        if index:
            for name, count in counts.items():
                gained = count - previous_counts.get(name, 0)
                if gained <= 0:
                    continue
                rarity = _rarity_of(name)
                if rarity not in MARKED_RARITIES:
                    continue
                markers.append(
                    Marker(
                        index=index,
                        kind=rarity.lower(),
                        color=RARITY_MARKER_COLORS[rarity],
                        text=f"{name} +{gained}",
                    )
                )
        previous_counts = counts

        banishes = {str(name) for name in (getattr(snapshot, "banishes", ()) or ())}
        for name in sorted(banishes - previous_banishes):
            if index:
                markers.append(
                    Marker(index=index, kind="banish", color=BANISH_MARKER_COLOR, text=f"Banish: {name}")
                )
        previous_banishes |= banishes
    return tuple(markers)


def build_model(snapshots, *, series_keys=()) -> ScrubberModel:
    """The whole model for one recording. Call once per load, not per frame."""
    snapshots = tuple(snapshots or ())
    if not snapshots:
        return ScrubberModel(count=0)
    keys = tuple(dict.fromkeys(series_keys)) or tuple(
        key for slot in DEFAULT_SLOTS for key in slot
    )
    caps = {key: build_cap_steps(snapshots, key) for key in ("Difficulty", "XP Gain")}
    return ScrubberModel(
        count=len(snapshots),
        stages=build_stage_bands(snapshots),
        markers=build_markers(snapshots),
        _series=build_series(snapshots, keys),
        _caps={key: steps for key, steps in caps.items() if steps},
    )
