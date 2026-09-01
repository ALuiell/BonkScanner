"""Explicit, transactional ownership of BonkScanner's JSON configuration."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
import threading
from typing import Any, Callable
from uuid import uuid4

from core.json_safety import dumps_strict_json, load_legacy_json


@dataclass(frozen=True)
class ConfigLoadResult:
    snapshot: dict[str, Any]
    existed: bool
    error: str = ""


@dataclass(frozen=True)
class RepositorySaveResult:
    success: bool
    reason: str = ""


class ConfigRepository:
    """Load, snapshot and atomically commit one config.json file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock = threading.RLock()
        self._snapshot: dict[str, Any] = {}
        self._loaded = False

    def load(self) -> ConfigLoadResult:
        with self.lock:
            self._cleanup_stale_temps()
            existed = self.path.is_file()
            try:
                with self.path.open("r", encoding="utf-8") as stream:
                    loaded = load_legacy_json(stream)
                if not isinstance(loaded, dict):
                    loaded = {}
                error = ""
            except FileNotFoundError:
                loaded = {}
                error = ""
            except Exception as exc:
                loaded = {}
                error = f"{type(exc).__name__}: {exc}"
            self._snapshot = deepcopy(loaded)
            self._loaded = True
            return ConfigLoadResult(deepcopy(self._snapshot), existed, error)

    def _cleanup_stale_temps(self) -> None:
        try:
            candidates = self.path.parent.glob(f"{self.path.name}.*.tmp")
            for candidate in candidates:
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError:
            pass

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return deepcopy(self._snapshot)

    def commit(self, candidate: dict[str, Any]) -> RepositorySaveResult:
        with self.lock:
            temp_path = self.path.with_name(
                f"{self.path.name}.{uuid4().hex}.tmp"
            )
            rollback_path = self.path.with_name(
                f"{self.path.name}.{uuid4().hex}.rollback.tmp"
            )
            previous_payload: bytes | None = None
            replaced = False
            try:
                payload = dumps_strict_json(candidate, indent=4)
                try:
                    previous_payload = self.path.read_bytes()
                except FileNotFoundError:
                    previous_payload = None
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with temp_path.open("w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, self.path)
                replaced = True
                saved_payload = self.path.read_text(encoding="utf-8")
                if saved_payload != payload:
                    raise OSError(
                        "BonkScanner wrote config.json, but its contents could not be verified."
                    )
                self._snapshot = deepcopy(candidate)
                self._loaded = True
                return RepositorySaveResult(True)
            except Exception as exc:
                rollback_error = ""
                if replaced:
                    try:
                        if previous_payload is None:
                            self.path.unlink(missing_ok=True)
                        else:
                            with rollback_path.open("wb") as stream:
                                stream.write(previous_payload)
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.replace(rollback_path, self.path)
                    except Exception as rollback_exc:
                        rollback_error = (
                            " Restoring the previous config also failed: "
                            f"{type(rollback_exc).__name__}: {rollback_exc}"
                        )
                return RepositorySaveResult(
                    False,
                    f"BonkScanner could not save config.json: {exc}{rollback_error}",
                )
            finally:
                for cleanup_path in (temp_path, rollback_path):
                    try:
                        cleanup_path.unlink(missing_ok=True)
                    except OSError:
                        pass

    def update(
        self,
        mutate: Callable[[dict[str, Any]], None],
    ) -> RepositorySaveResult:
        with self.lock:
            candidate = deepcopy(self._snapshot)
            mutate(candidate)
            return self.commit(candidate)
