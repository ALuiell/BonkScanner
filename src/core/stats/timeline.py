"""Recording timeline over player-stats snapshots."""

from __future__ import annotations

import time

from core.stats.types import (
    PlayerStatValue,
    PlayerStatsSnapshot,
    TomeSnapshot,
    WeaponSnapshot,
)


class PlayerStatsTimeline:
    def __init__(
        self,
        *,
        interval_seconds: int = 60,
        clock=time.monotonic,
    ) -> None:
        self.interval_seconds = max(1, int(interval_seconds))
        self.clock = clock
        self.snapshots: list[PlayerStatsSnapshot] = []
        self.is_recording = False
        self.start_time: float | None = None
        self.last_snapshot_time: float | None = None

    def start(self) -> None:
        now = self.clock()
        self.snapshots.clear()
        self.is_recording = True
        self.start_time = now
        self.last_snapshot_time = None

    def stop(self) -> None:
        self.is_recording = False

    def elapsed_seconds(self) -> int:
        if self.start_time is None:
            return 0
        return max(0, int(self.clock() - self.start_time))

    def elapsed_label(self) -> str:
        minutes, seconds = divmod(self.elapsed_seconds(), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def should_capture(self) -> bool:
        if not self.is_recording:
            return False
        if self.last_snapshot_time is None:
            return True
        return self.clock() - self.last_snapshot_time >= self.interval_seconds

    def capture(
        self,
        stats: dict[str, PlayerStatValue],
        items: tuple[str, ...] = (),
        weapons: tuple[WeaponSnapshot, ...] = (),
        tomes: tuple[TomeSnapshot, ...] = (),
        banishes: tuple[str, ...] = (),
    ) -> PlayerStatsSnapshot:
        now = self.clock()
        start_time = self.start_time if self.start_time is not None else now
        snapshot = PlayerStatsSnapshot(
            elapsed_seconds=int(now - start_time),
            captured_at=now,
            stats=dict(stats),
            items=tuple(items),
            weapons=tuple(weapons),
            tomes=tuple(tomes),
            banishes=tuple(banishes),
        )
        self.snapshots.append(snapshot)
        self.last_snapshot_time = now
        return snapshot

    def get_snapshot(self, index: int) -> PlayerStatsSnapshot | None:
        if not self.snapshots:
            return None
        index = min(max(index, 0), len(self.snapshots) - 1)
        return self.snapshots[index]
