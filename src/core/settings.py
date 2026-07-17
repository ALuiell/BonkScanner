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


class RecordingSettings(Protocol):
    def read_metadata_index(self) -> dict[str, Any]:
        """The stored VOD metadata index, or an empty mapping."""

    def write_metadata_index(self, payload: dict[str, Any]) -> None:
        """Persist the VOD metadata index."""


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
