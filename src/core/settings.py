"""The settings ports.

`infra/` must not import `app`, but the overlay server and the VOD storage both
need live, persistent settings: the overlay server is not a *consumer* of overlay
settings, it is their editor -- the OBS widget POSTs its new geometry and the
server persists it. Passing a snapshot at construction cannot express that, so
`infra` depends on these protocols and `app` injects the `config`-backed
implementations.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol


class OverlaySettings(Protocol):
    def read(self) -> dict[str, Any]:
        """The current overlay settings. Callers must not mutate the result."""

    def update(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        """Apply `mutate` to a copy of the settings and persist it, atomically.

        `mutate` runs while the settings are locked, so it must not block.
        """


#: Recordings shorter than this are discarded when the recorder stops.
#:
#: ``1`` is the historical behaviour spelled as a threshold: the rule used to
#: be ``snapshot_count == 0``, which is exactly ``< 1``. Keeping it as the
#: default means turning the setting into a knob changes nothing for anyone who
#: never touches it.
DEFAULT_MINIMUM_SNAPSHOT_COUNT = 1


class RecordingSettings(Protocol):
    def read_metadata_index(self) -> dict[str, Any]:
        """The stored VOD metadata index, or an empty mapping."""

    def write_metadata_index(self, payload: dict[str, Any]) -> None:
        """Persist the VOD metadata index."""

    def read_minimum_snapshot_count(self) -> int:
        """Shortest run worth keeping, in snapshots.

        Read by the recorder when it stops, and by the cleanup dialog as its
        suggested threshold -- one number rather than the two that used to
        disagree: a hard-coded discard rule in ``VodRecorder.stop`` and a
        free-text field in ``CleanupRecordingsDialog``.
        """

    def write_minimum_snapshot_count(self, value: int) -> None:
        """Persist the shortest run worth keeping."""


class NullOverlaySettings:
    """Settings that hold nothing and persist nothing.

    The default for a server built without a settings store -- a test, or any
    caller with nothing to persist to. It serves the built-in defaults and drops
    updates. Stated once here rather than as a `settings is not None` check at
    every use, which is a check someone eventually forgets.
    """

    def read(self) -> dict[str, Any]:
        return {}

    def update(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        return None
