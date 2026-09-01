"""The `config`-backed implementations of the settings ports.

These live in `app/` because they know `config`; `infra/` sees only the protocols
in `core/settings.py`.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app import config
from app.config_repository import ConfigRepository
from core.settings import DEFAULT_MINIMUM_SNAPSHOT_COUNT


class ConfigOverlaySettings:
    def read(self) -> dict[str, Any]:
        return config.OVERLAY or {}

    def update(self, mutate: Callable[[dict[str, Any]], None]):
        overlay = dict(config.OVERLAY)
        mutate(overlay)
        result = config.update_config(
            lambda candidate: candidate.__setitem__("OVERLAY", overlay)
        )
        if not result.success:
            return result
        config.OVERLAY = overlay
        config.user_config["OVERLAY"] = overlay
        return result


class ConfigRecordingSettings:
    # The leading underscore is part of the stored key, not a typo: changing it
    # would orphan every existing user's index.
    _INDEX_KEY = "_VOD_METADATA_INDEX"

    def __init__(self, *, index_path: str | Path | None = None) -> None:
        self._index_repository = ConfigRepository(
            index_path or Path(config.application_path) / "vod_metadata_index.json"
        )

    def read_metadata_index(self) -> dict[str, Any]:
        loaded = self._index_repository.load()
        if loaded.snapshot:
            return loaded.snapshot

        with config.config_lock:
            legacy = config.user_config.get(self._INDEX_KEY)
            if not isinstance(legacy, dict):
                return {}
            migrated = deepcopy(legacy)
            result = self._index_repository.commit(migrated)
            if not result.success:
                return migrated
            config.update_config(lambda candidate: candidate.pop(self._INDEX_KEY, None))
            return migrated

    def write_metadata_index(self, payload: dict[str, Any]) -> None:
        result = self._index_repository.commit(deepcopy(payload))
        if not result.success:
            raise OSError(result.reason)

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

    def write_minimum_snapshot_count(self, value: int):
        normalized = max(0, int(value))
        return config.update_config(
            lambda candidate: candidate.__setitem__(
                self._MINIMUM_SNAPSHOT_COUNT_KEY,
                normalized,
            )
        )


class ConfigBuildProgressionSettings:
    def read(self) -> dict[str, Any]:
        with config.config_lock:
            return deepcopy(config.BUILD_PROGRESSION)

    def write(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = config.normalize_build_progression_config(payload)
        try:
            save_result = config.update_config(
                lambda candidate: candidate.__setitem__(
                    "BUILD_PROGRESSION",
                    deepcopy(normalized),
                )
            )
        except Exception as exc:
            detail = str(exc) or type(exc).__name__
            raise OSError(
                f"BonkScanner could not save Build Progression: {detail}."
            ) from exc
        if not save_result.success:
            raise OSError(
                "BonkScanner could not save Build Progression: "
                f"{save_result.reason or 'unknown error'}."
            )
        config.BUILD_PROGRESSION = normalized
        config.user_config["BUILD_PROGRESSION"] = normalized
        return deepcopy(normalized)
