"""Explicit, transactional ownership of BonkScanner's JSON configuration."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
import threading
from weakref import WeakValueDictionary
from typing import Any, Callable
from uuid import uuid4

from core.json_safety import dumps_strict_json, loads_legacy_json
from infra.data_storage import owns_profile_lock, profile_read_only_reason, profile_write_error


_locks_guard = threading.Lock()
_path_locks = WeakValueDictionary()


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
        with _locks_guard:
            key = os.path.normcase(str(self.path.resolve()))
            self.lock = _path_locks.setdefault(key, threading.RLock())
        self._snapshot: dict[str, Any] = {}
        self._loaded = False
        self._baseline: bytes | None = None
        self._load_error = ""
        self.read_only_reason = ""

    def load(self) -> ConfigLoadResult:
        with self.lock:
            existed = True
            try:
                existed = self.path.is_file()
                raw = self.path.read_bytes()
                loaded = loads_legacy_json(raw.decode("utf-8-sig"))
                if not isinstance(loaded, dict):
                    raise ValueError("The configuration must contain a settings object.")
                error = ""
            except FileNotFoundError:
                raw = None
                loaded = {}
                backup_exists = self.path.name in ("config.json", "config_advanced.json") and self.path.with_name(self.path.name + ".bak").exists()
                error = "The configuration is missing; existing data was kept for recovery." if existed or backup_exists else ""
            except Exception as exc:
                raw = None
                loaded = {}
                error = f"{type(exc).__name__}: {exc}"
            self._snapshot = deepcopy(loaded)
            self._baseline = raw
            self._load_error = error
            self._loaded = not bool(error)
            if self._loaded and owns_profile_lock(self.path):
                self._cleanup_stale_temps()
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

    @property
    def loaded_successfully(self) -> bool:
        return self._loaded

    def commit(self, candidate: dict[str, Any]) -> RepositorySaveResult:
        with self.lock:
            reason = profile_write_error(self.path)
            if self.read_only_reason or (reason and profile_read_only_reason()):
                self._snapshot = deepcopy(candidate)
                return RepositorySaveResult(True, self.read_only_reason or reason)
            if reason:
                return RepositorySaveResult(False, reason)
            if not self._loaded:
                return RepositorySaveResult(False, self._load_error or "Load the configuration before saving it.")
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
                if previous_payload != self._baseline:
                    return RepositorySaveResult(False, "The configuration changed outside this window. Restart BonkScanner before saving.")
                if previous_payload is not None and previous_payload.decode("utf-8-sig").replace("\r\n", "\n") == payload:
                    self._snapshot = deepcopy(candidate)
                    return RepositorySaveResult(True)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with temp_path.open("w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Preserve one last-good config, reusing the same file each time.
                # Cache repositories do not create backups.
                if self.path.name in ("config.json", "config_advanced.json") and previous_payload is not None:
                    backup = self.path.with_name(self.path.name + ".bak")
                    with rollback_path.open("wb") as stream:
                        stream.write(previous_payload)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(rollback_path, backup)
                current = self.path.read_bytes() if self.path.exists() else None
                if current != self._baseline:
                    return RepositorySaveResult(False, "The configuration changed outside this window. Restart BonkScanner before saving.")
                os.replace(temp_path, self.path)
                replaced = True
                saved_payload = self.path.read_text(encoding="utf-8")
                if saved_payload != payload:
                    raise OSError(
                        "BonkScanner wrote config.json, but its contents could not be verified."
                    )
                committed_bytes = self.path.read_bytes()
                self._snapshot = deepcopy(candidate)
                self._loaded = True
                self._baseline = committed_bytes
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
