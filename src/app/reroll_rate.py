"""Peak average speed over ten consecutive, fully loaded reroll cycles."""

from __future__ import annotations

from collections import deque


class RerollCyclePeak:
    WINDOW_CYCLES = 10

    def __init__(self) -> None:
        self._ready_times: deque[float] = deque(maxlen=self.WINDOW_CYCLES + 1)
        self._restart_pending = False
        self.maximum: float | None = None

    def start(self) -> None:
        self.break_sequence()
        self.maximum = None

    def break_sequence(self) -> None:
        """Discard unfinished measurements while preserving the session peak."""
        self._ready_times.clear()
        self._restart_pending = False

    def restarted(self) -> None:
        """A successful restart must be followed by a confirmed ready map."""
        if self._restart_pending:
            self.break_sequence()
        self._restart_pending = bool(self._ready_times)

    def map_ready(self, now: float) -> None:
        """Measure ready-to-ready time, including evaluation, reset and loading."""
        if not self._restart_pending or (
            self._ready_times and now <= self._ready_times[-1]
        ):
            self.break_sequence()
        self._restart_pending = False
        self._ready_times.append(now)
        if len(self._ready_times) == self.WINDOW_CYCLES + 1:
            elapsed = now - self._ready_times[0]
            rpm = 60.0 * self.WINDOW_CYCLES / elapsed
            self.maximum = max(rpm, self.maximum or 0.0)
