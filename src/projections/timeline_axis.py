"""Shared, Qt-free axis projection for recording timelines."""
from __future__ import annotations

import bisect
from dataclasses import dataclass
from math import isfinite

from projections import formatting


AXIS_TIME = "time"
AXIS_PROGRESS = "progress"
AXIS_MODES = (AXIS_TIME, AXIS_PROGRESS)


def _safe_time(snapshot, fallback: float) -> float:
    value = formatting._snapshot_compare_time(snapshot)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return value if isfinite(value) else fallback


def snapshot_times(snapshots) -> tuple[float, ...]:
    """Monotonic compare-times, with index progress as a stable fallback."""
    values: list[float] = []
    previous = 0.0
    for index, snapshot in enumerate(snapshots or ()):
        value = max(previous, _safe_time(snapshot, float(index)))
        values.append(value)
        previous = value
    return tuple(values)


@dataclass(frozen=True)
class TimelineAxisProjection:
    """Prepared positions and nearest-snapshot lookup for one timeline lane."""

    times: tuple[float, ...]
    positions: tuple[float, ...]
    duration: float
    mode: str

    def nearest_index(self, position: float) -> int | None:
        if not self.positions:
            return None
        target = max(0.0, min(1.0, float(position)))
        at = bisect.bisect_left(self.positions, target)
        candidates: set[int] = set()
        for neighbour in (at - 1, at):
            if not 0 <= neighbour < len(self.positions):
                continue
            value = self.positions[neighbour]
            # Positions preserve original snapshot order, so the left edge of
            # a duplicate run is also its lowest original index. Do not expand
            # the whole run here: nearest lookup is on the pointer-rate path.
            candidates.add(bisect.bisect_left(self.positions, value))
        if not candidates:
            return 0
        return min(candidates, key=lambda index: (abs(self.positions[index] - target), index))

    def nearest_time(self, target_time: float) -> int | None:
        return self.nearest_index(float(target_time) / max(self.duration, 1.0))


def build_axis_projection(
    snapshots,
    *,
    mode: str = AXIS_TIME,
    common_duration: float | None = None,
) -> TimelineAxisProjection:
    snapshots = tuple(snapshots or ())
    mode = mode if mode in AXIS_MODES else AXIS_TIME
    times = snapshot_times(snapshots)
    own_duration = times[-1] if times else 0.0
    duration = max(float(common_duration or 0.0), own_duration, 1.0)
    if mode == AXIS_PROGRESS:
        denominator = max(len(snapshots) - 1, 1)
        positions = tuple(index / denominator for index in range(len(snapshots)))
    else:
        positions = tuple(max(0.0, min(1.0, value / duration)) for value in times)
    return TimelineAxisProjection(times, positions, duration, mode)


def axis_positions(
    snapshots,
    *,
    mode: str,
    common_duration: float | None = None,
) -> tuple[float, ...]:
    """Compatibility wrapper for the former Compare Runs helper."""
    return build_axis_projection(
        snapshots,
        mode=mode,
        common_duration=common_duration,
    ).positions
