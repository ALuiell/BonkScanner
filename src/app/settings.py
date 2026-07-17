"""The `config`-backed implementations of the settings ports.

These live in `app/` because they know `config`; `infra/` sees only the protocols
in `core/settings.py`.
"""
from __future__ import annotations

from typing import Any, Callable

from app import config


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
