"""Peak reroll count over completed rolling one-minute windows."""

from __future__ import annotations

from collections import deque


class RollingRerollPeak:
    WINDOW_SECONDS = 60.0

    def __init__(self) -> None:
        self.started_at: float | None = None
        self._reroll_times: deque[float] = deque()
        self.maximum: int | None = None

    def start(self, now: float) -> None:
        self.started_at = now
        self._reroll_times.clear()
        self.maximum = None

    def record(self, now: float) -> None:
        if self.started_at is None:
            return
        self._reroll_times.append(now)
        self.sample(now)

    def sample(self, now: float) -> int | None:
        if self.started_at is None:
            return self.maximum
        if self.maximum is None and now - self.started_at >= self.WINDOW_SECONDS:
            # The first complete window can finish between UI ticks. Count it
            # before expiring its earliest rerolls from the rolling deque.
            first_end = self.started_at + self.WINDOW_SECONDS
            self.maximum = sum(
                self.started_at < recorded_at <= first_end
                for recorded_at in self._reroll_times
            )
        cutoff = now - self.WINDOW_SECONDS
        while self._reroll_times and self._reroll_times[0] <= cutoff:
            self._reroll_times.popleft()
        if now - self.started_at >= self.WINDOW_SECONDS:
            count = len(self._reroll_times)
            self.maximum = max(count, self.maximum or 0)
        return self.maximum
