"""The `config`-backed implementations of the settings ports.

These live in `app/` because they know `config`; `infra/` sees only the protocols
in `core/settings.py`.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from app import config
from core.settings import DEFAULT_MINIMUM_SNAPSHOT_COUNT


class ConfigOverlaySettings:
    def read(self) -> dict[str, Any]:
        return config.OVERLAY or {}

    def update(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        with config.config_lock:
            overlay = dict(config.OVERLAY)
            mutate(overlay)
            config.OVERLAY = overlay
            config.user_config["OVERLAY"] = config.OVERLAY
            config.save_config(config.user_config)


class ConfigRecordingSettings:
    # The leading underscore is part of the stored key, not a typo: changing it
    # would orphan every existing user's index.
    _INDEX_KEY = "_VOD_METADATA_INDEX"

    def read_metadata_index(self) -> dict[str, Any]:
        return config.user_config.get(self._INDEX_KEY, {})

    def write_metadata_index(self, payload: dict[str, Any]) -> None:
        config.user_config[self._INDEX_KEY] = payload
        config.save_config(config.user_config)

    #: Unlike `_INDEX_KEY` this one is new, so it gets an ordinary name.
    _MINIMUM_SNAPSHOT_COUNT_KEY = "recordings_minimum_snapshot_count"

    def read_minimum_snapshot_count(self) -> int:
        stored = config.user_config.get(self._MINIMUM_SNAPSHOT_COUNT_KEY)
        try:
            value = int(stored)
        except (TypeError, ValueError):
            return DEFAULT_MINIMUM_SNAPSHOT_COUNT
        # Zero means "keep everything, even a run with no snapshots at all",
        # which is a choice the user is allowed to make; negative is not a
        # choice, it is a corrupt config.
        return max(0, value)

    def write_minimum_snapshot_count(self, value: int) -> None:
        config.user_config[self._MINIMUM_SNAPSHOT_COUNT_KEY] = max(0, int(value))
        config.save_config(config.user_config)


class ConfigBuildProgressionSettings:
    def read(self) -> dict[str, Any]:
        with config.config_lock:
            return deepcopy(config.BUILD_PROGRESSION)

    def write(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = config.normalize_build_progression_config(payload)
        with config.config_lock:
            config.BUILD_PROGRESSION = normalized
            config.user_config["BUILD_PROGRESSION"] = deepcopy(normalized)
            config.save_config(config.user_config)
        return deepcopy(normalized)
