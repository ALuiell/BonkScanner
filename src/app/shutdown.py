"""Shared application shutdown deadline and result contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable


DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 15.0
FORCED_SHUTDOWN_EXIT_CODE = 3


@dataclass(frozen=True)
class ShutdownDeadline:
    """One monotonic budget shared by every runtime owner."""

    started_at: float
    expires_at: float
    _clock: Callable[[], float] = field(repr=False, compare=False)

    @classmethod
    def after(
        cls,
        seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> "ShutdownDeadline":
        started_at = clock()
        return cls(
            started_at=started_at,
            expires_at=started_at + max(0.0, float(seconds)),
            _clock=clock,
        )

    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at - self._clock())

    def remaining_ms(self) -> int:
        return max(0, int(self.remaining_seconds() * 1000))

    def elapsed_ms(self) -> int:
        return max(0, round((self._clock() - self.started_at) * 1000))

    def expired(self) -> bool:
        return self.remaining_seconds() <= 0.0


@dataclass(frozen=True)
class ShutdownReport:
    """The complete, serialisable outcome of application teardown."""

    errors: tuple[tuple[str, str], ...] = ()
    timed_out_resources: tuple[str, ...] = ()
    elapsed_ms: int = 0

    @property
    def completed(self) -> bool:
        return not self.errors and not self.timed_out_resources
