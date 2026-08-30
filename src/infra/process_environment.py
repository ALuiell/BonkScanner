"""Read-only process-environment snapshots for run verification.

Only portable evidence is serialized. Absolute module paths are reduced to a
location category plus a one-way path ID, so shared reports cannot leak a
Windows username or personal directory structure.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading
from typing import Any, Iterable

from core.run_verifier import (
    ENVIRONMENT_SCHEMA_VERSION,
    environment_digest,
    known_environment_module_classification,
)


MAX_HASH_BYTES = 32 * 1024 * 1024
MAX_TOTAL_HASH_BYTES = 64 * 1024 * 1024
MAX_PLUGIN_ARTIFACTS = 256
MAX_PRIVATE_EXECUTABLE_REGIONS = 4096

MOD_LOADER_TOKENS = (
    "bepinex",
    "doorstop",
    "melonloader",
    "0harmony",
    "il2cppinterop",
    "unityexplorer",
)
PROXY_LOADER_NAMES = frozenset(
    {"winhttp.dll", "version.dll", "dxgi.dll", "dinput8.dll", "winmm.dll"}
)

_HASH_CACHE: dict[tuple[str, int, int], str | None] = {}
_HASH_CACHE_LOCK = threading.RLock()


class _HashBudget:
    def __init__(self, remaining: int) -> None:
        self.remaining = max(0, int(remaining))
        self._accounted_paths: set[str] = set()

    def reserve(self, path: Path, size: int) -> bool:
        token = _normal_path(path)
        if token in self._accounted_paths:
            return True
        if size > self.remaining:
            return False
        self.remaining -= max(0, int(size))
        self._accounted_paths.add(token)
        return True


def _normal_path(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _within(path: Path | str, root: Path | str | None) -> bool:
    if root is None:
        return False
    try:
        normalized_root = _normal_path(root)
        return os.path.commonpath((_normal_path(path), normalized_root)) == normalized_root
    except (OSError, ValueError):
        return False


def _path_id(path: Path | str) -> str:
    raw = _normal_path(path).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:24]


def _sha256_file(
    path: Path,
    *,
    max_bytes: int = MAX_HASH_BYTES,
    budget: _HashBudget | None = None,
) -> str | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file() or stat.st_size < 0 or stat.st_size > max_bytes:
        return None
    if budget is not None and not budget.reserve(path, int(stat.st_size)):
        return None
    key = (_normal_path(path), int(stat.st_size), int(stat.st_mtime_ns))
    with _HASH_CACHE_LOCK:
        if key in _HASH_CACHE:
            return _HASH_CACHE[key]
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                digest.update(chunk)
        value: str | None = digest.hexdigest()
    except OSError:
        value = None
    with _HASH_CACHE_LOCK:
        if len(_HASH_CACHE) >= 512:
            _HASH_CACHE.pop(next(iter(_HASH_CACHE)))
        _HASH_CACHE[key] = value
    return value


def _game_directory(modules: Iterable[Any]) -> Path | None:
    module_rows = tuple(modules)
    for preferred in ("megabonk.exe", "gameassembly.dll"):
        for module in module_rows:
            if str(getattr(module, "name", "")).casefold() == preferred:
                filename = str(getattr(module, "filename", "") or "").strip()
                if filename:
                    return Path(filename).parent
    return None


def _location(path: Path, *, game_directory: Path | None) -> str:
    if _within(path, game_directory):
        return "game"
    windows = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windows and _within(path, windows):
        return "system"
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        root = os.environ.get(variable)
        if root and _within(path, root):
            return "program_files"
    return "other"


def _classification(name: str, location: str) -> str:
    folded = name.casefold()
    if any(token in folded for token in MOD_LOADER_TOKENS):
        return "mod_loader"
    if location == "game" and folded in PROXY_LOADER_NAMES:
        return "mod_loader"
    known = known_environment_module_classification(name, location)
    if known is not None:
        return known
    if location == "game":
        return "unknown"
    if location == "system":
        return "system"
    if location == "program_files":
        return "third_party"
    return "unknown"


def _module_rows(
    modules: Iterable[Any],
    game_directory: Path | None,
    hash_budget: _HashBudget,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ordered_modules = sorted(
        modules,
        key=lambda module: (
            _normal_path(str(getattr(module, "filename", "") or "")),
            str(getattr(module, "name", "") or "").casefold(),
        ),
    )
    for module in ordered_modules:
        name = Path(str(getattr(module, "name", "") or "").strip()).name
        raw_filename = str(getattr(module, "filename", "") or "").strip()
        if not name or not raw_filename:
            continue
        path = Path(raw_filename)
        location = _location(path, game_directory=game_directory)
        classification = _classification(name, location)
        size = max(0, int(getattr(module, "size", 0) or 0))
        should_hash = classification in {"mod_loader", "third_party", "unknown"}
        rows.append(
            {
                "id": _path_id(path),
                "name": name,
                "location": location,
                "size": size,
                "sha256": (
                    _sha256_file(path, budget=hash_budget) if should_hash else None
                ),
                "classification": classification,
            }
        )
    rows.sort(key=lambda row: (row["name"].casefold(), row["id"]))
    return rows


def _artifact_row(
    path: Path,
    root: Path,
    kind: str,
    hash_budget: _HashBudget,
) -> dict[str, Any] | None:
    if not _within(path, root):
        return None
    try:
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size if path.is_file() else 0
    except (OSError, ValueError):
        return None
    return {
        "id": _path_id(path),
        "path": relative,
        "kind": kind,
        "size": max(0, int(size)),
        "sha256": (
            _sha256_file(path, budget=hash_budget) if path.is_file() else None
        ),
    }


def _artifact_rows(
    game_directory: Path | None,
    hash_budget: _HashBudget,
) -> list[dict[str, Any]]:
    if game_directory is None or not game_directory.is_dir():
        return []
    found: dict[str, dict[str, Any]] = {}
    direct = {
        "doorstop_config.ini": "mod_loader_file",
        ".doorstop_version": "mod_loader_file",
        "winhttp.dll": "proxy_loader",
        "version.dll": "proxy_loader",
        "dxgi.dll": "proxy_loader",
        "dinput8.dll": "proxy_loader",
        "winmm.dll": "proxy_loader",
        "BepInEx": "mod_loader_directory",
        "MelonLoader": "mod_loader_directory",
    }
    for relative, kind in direct.items():
        path = game_directory / relative
        if path.exists():
            row = _artifact_row(path, game_directory, kind, hash_budget)
            if row is not None:
                found[row["id"]] = row

    plugin_roots = (
        game_directory / "BepInEx" / "plugins",
        game_directory / "MelonLoader" / "Mods",
    )
    plugin_count = 0
    for plugin_root in plugin_roots:
        if plugin_count >= MAX_PLUGIN_ARTIFACTS:
            break
        if not plugin_root.is_dir():
            continue
        try:
            for path in plugin_root.rglob("*.dll"):
                if plugin_count >= MAX_PLUGIN_ARTIFACTS:
                    break
                row = _artifact_row(path, game_directory, "plugin", hash_budget)
                if row is not None:
                    found[row["id"]] = row
                    plugin_count += 1
        except OSError:
            continue
    return sorted(found.values(), key=lambda row: (row["path"].casefold(), row["id"]))


def _private_executable_region_rows(memory: Any) -> list[dict[str, Any]]:
    reader = getattr(memory, "private_executable_regions", None)
    if not callable(reader):
        raise RuntimeError(
            "The memory backend cannot enumerate private executable regions."
        )
    regions = tuple(reader())
    if len(regions) > MAX_PRIVATE_EXECUTABLE_REGIONS:
        raise RuntimeError("The private executable-region safety limit was exceeded.")
    rows: dict[str, dict[str, Any]] = {}
    for region in regions:
        base = max(0, int(getattr(region, "base_address", 0) or 0))
        allocation_base = max(
            0,
            int(getattr(region, "allocation_base", base) or base),
        )
        size = max(0, int(getattr(region, "size", 0) or 0))
        protection = max(0, int(getattr(region, "protection", 0) or 0))
        if not size:
            continue
        token = hashlib.sha256(
            f"{allocation_base:016x}:{base:016x}".encode("ascii")
        ).hexdigest()[:24]
        base_protection = protection & 0xFF
        rows[token] = {
            "id": token,
            "size": size,
            "protection": base_protection,
            "writable": base_protection in {0x40, 0x80},
            "guarded": bool(protection & 0x100),
        }
    return sorted(rows.values(), key=lambda row: row["id"])


def scan_process_environment(memory: Any) -> dict[str, Any]:
    """Return one privacy-safe native-module and mod-artifact inventory."""
    reader = getattr(memory, "loaded_modules", None)
    if not callable(reader):
        raise RuntimeError("The memory backend cannot enumerate process modules.")
    raw_modules = tuple(reader())
    if not raw_modules:
        raise RuntimeError("The process module scan returned no modules.")
    game_directory = _game_directory(raw_modules)
    if game_directory is None:
        raise RuntimeError("The game directory could not be identified from loaded modules.")
    hash_budget = _HashBudget(MAX_TOTAL_HASH_BYTES)
    modules = _module_rows(raw_modules, game_directory, hash_budget)
    if not modules:
        raise RuntimeError("The process module scan contained no usable module paths.")
    artifacts = _artifact_rows(game_directory, hash_budget)
    private_executable_regions = _private_executable_region_rows(memory)
    return {
        "schema": ENVIRONMENT_SCHEMA_VERSION,
        "modules": modules,
        "artifacts": artifacts,
        "private_executable_regions": private_executable_regions,
        "digest": environment_digest(
            modules,
            artifacts,
            private_executable_regions,
        ),
    }
