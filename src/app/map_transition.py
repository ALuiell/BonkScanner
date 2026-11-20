"""Scanner-owned restart gate and confirmed kept-map generation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class MapTransition:
    """Coordinate independent readers without treating a timeout as a map.

    Only the scanner writes; readers may query from any thread. The sample
    epoch invalidates reads that overlap even an unsuccessful input attempt.
    The settled generation advances only after a dispatched restart and a
    readiness check which confirmed the changed map.
    """

    RECOVERY_GRACE_SECONDS = 1.0

    def __init__(
        self, *, clock: Callable[[], float] = time.monotonic, stall_seconds: float = 1.0
    ) -> None:
        self._clock = clock
        self._stall_seconds = float(stall_seconds)
        self._lock = threading.Lock()
        self._epoch = 0
        self._sent_count = 0
        self._abandoned_count = 0
        self._settled = 0
        self._deadline: float | None = None
        self._dispatched = False
        self._recording_wait = False
        self._grace_started: float | None = None
        self._previous_gate: tuple[float | None, bool, float | None] | None = None

    def _active_locked(self) -> bool:
        return self._recording_wait and (self._deadline is None or self._clock() < self._deadline)

    def active(self) -> bool:
        with self._lock:
            return self._active_locked()

    def generation(self) -> int:
        with self._lock:
            return self._epoch

    def dispatch_count(self) -> int:
        """Let the scanner distinguish an input sent from later errors."""
        with self._lock:
            return self._sent_count

    def abandoned_restart_count(self) -> int:
        """Count unresolved dispatched restarts explicitly abandoned by Scanner."""
        with self._lock:
            return self._abandoned_count

    def recovery_grace_active(self) -> bool:
        """Suppress transient pointer failures only early in one restart series."""
        with self._lock:
            return bool(
                self._active_locked()
                and self._grace_started is not None
                and self._clock() < self._grace_started + self.RECOVERY_GRACE_SECONDS
            )

    def recording_generation(self) -> int | None:
        """Keep recording boundaries deferred after the reader stall bound."""
        with self._lock:
            return None if self._recording_wait else self._settled

    def begin(self) -> None:
        with self._lock:
            self._previous_gate = (
                self._deadline, self._recording_wait, self._grace_started
            )
            if not self._recording_wait:
                self._grace_started = self._clock()
            self._epoch += 1
            self._deadline = None
            self._recording_wait = True

    def restart_sent(self) -> None:
        with self._lock:
            self._dispatched = True
            self._sent_count += 1
            self._deadline = self._clock() + self._stall_seconds
            self._previous_gate = None

    def cancel(self) -> None:
        """Undo a failed input attempt without losing an earlier restart."""
        with self._lock:
            if self._previous_gate is not None:
                self._deadline, self._recording_wait, self._grace_started = self._previous_gate
                self._previous_gate = None

    def abandon(self) -> None:
        """Release waits and report an unresolved dispatched restart once."""
        self.settle(confirmed=False)

    def settle(self, *, confirmed: bool) -> None:
        """Release the gate and report the outcome of any dispatched restart."""
        with self._lock:
            if self._dispatched:
                if confirmed:
                    self._settled += 1
                else:
                    self._abandoned_count += 1
            self._dispatched = False
            self._deadline = None
            self._recording_wait = False
            self._grace_started = None
            self._previous_gate = None
