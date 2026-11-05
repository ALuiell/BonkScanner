"""Keep source-run data below the checkout without changing EXE storage.

Legacy entries move on the same volume by atomic rename. A small plan survives
an interrupted move, so the next launch finishes it before opening the profile.
Existing runtime profiles are never merged with an older root-level profile.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from infra import data_storage as storage


RUNTIME_DIRECTORY = "runtime"
SOURCE_MARKER = ".bonkscanner-shared.json"
PLAN_NAME = ".source-migration.json"


def runtime_directory(installation: Path) -> Path:
    return installation / RUNTIME_DIRECTORY


def _allowed_name(name: str) -> bool:
    return (
        name in storage.LEGACY_CLEANUP_FILES + storage.MIGRATION_DIRECTORIES
        or name in (SOURCE_MARKER, "restart-diagnostics.log")
        or name in tuple(config + ".bak" for config in storage.CONFIG_FILE_NAMES)
        or any(name.startswith(base + ".") and name.endswith(".tmp")
               for base in storage.MIGRATION_FILES + (SOURCE_MARKER,))
        or (name.startswith("merchant_history.jsonl.broken-") and Path(name).name == name)
    )


def _legacy_entries(installation: Path) -> list[Path]:
    return sorted(
        (path for path in installation.iterdir() if _allowed_name(path.name)),
        key=lambda path: path.name,
    )


def _validate_entry(path: Path) -> None:
    if storage._is_reparse_point(path):
        raise storage.StorageError(f"Source data migration refused a linked path: {path}")
    if path.is_dir():
        # Check every child, including lock/temp files that the EXE migrator skips.
        for current, directories, files in os.walk(path, followlinks=False):
            for name in directories + files:
                child = Path(current) / name
                if storage._is_reparse_point(child):
                    raise storage.StorageError(f"Source data migration refused a linked path: {child}")
    elif not path.is_file():
        raise storage.StorageError(f"Unexpected source data path: {path}")


def _load_plan(path: Path) -> dict[str, str]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise storage.StorageError(f"Cannot read source data migration plan: {path}") from exc
    if not isinstance(plan, dict) or not plan:
        raise storage.StorageError(f"Invalid source data migration plan: {path}")
    for name, target in plan.items():
        if not isinstance(name, str) or not _allowed_name(name) or Path(name).name != name:
            raise storage.StorageError(f"Invalid source data migration entry: {name}")
        if not isinstance(target, str):
            raise storage.StorageError(f"Invalid source data migration destination: {target}")
        relative = Path(target)
        parts = relative.parts
        if not (
            target == name
            or (len(parts) == 3 and parts[0] == "legacy-backup"
                and len(parts[1]) == 32 and all(c in "0123456789abcdef" for c in parts[1])
                and parts[2] == name)
        ):
            raise storage.StorageError(f"Invalid source data migration destination: {target}")
    return plan


def prepare_source_runtime(installation: Path, *, shared_data: Path | None = None) -> Path:
    runtime = runtime_directory(installation)
    storage._reject_linked_destination(installation, runtime)
    storage._ensure_writable(runtime)
    plan_path = runtime / PLAN_NAME
    storage._reject_linked_destination(runtime, plan_path)
    entries = _legacy_entries(installation)
    old_lock_path = installation / storage.DATA_LOCK_NAME
    if not entries and not plan_path.exists() and not old_lock_path.exists():
        return runtime
    if shared_data is not None and (
        storage._normalized_path(shared_data) == storage._normalized_path(installation)
        or any(path.is_dir() and storage._paths_overlap(path, shared_data) for path in entries)
    ):
        raise storage.StorageError(
            "A legacy source data path is selected as a shared data folder. Move that shared "
            "profile using Data Storage before migrating source-run files into runtime."
        )

    locks = [
        storage._ProcessFileLock(runtime / ".source-migration.lock"),
        storage._ProcessFileLock(runtime / storage.DATA_LOCK_NAME),
        storage._ProcessFileLock(old_lock_path),
    ]
    acquired = []
    completed = False
    try:
        for lock in locks:
            storage._reject_linked_destination(installation, lock.path)
            if not lock.acquire():
                raise storage.StorageError(
                    "Source data is in use by another BonkScanner. Close it before migrating into runtime."
                )
            acquired.append(lock)
        entries = _legacy_entries(installation)
        if plan_path.exists():
            plan = _load_plan(plan_path)
            if any(path.name not in plan for path in entries):
                raise storage.StorageError("New root-level data appeared during source migration. Nothing was overwritten.")
        else:
            for path in entries:
                _validate_entry(path)
            backup = Path("legacy-backup") / uuid4().hex
            # An existing profile means the old profile must stay together as a backup.
            existing_profile = storage._profile_exists(runtime)
            plan = {}
            for path in entries:
                target = Path(path.name)
                if ((path.name != SOURCE_MARKER and existing_profile)
                        or (runtime / path.name).exists()):
                    target = backup / path.name
                plan[path.name] = target.as_posix()
            if plan:
                storage._write_journal(plan_path, plan)

        # Validate the whole plan before moving its first entry.
        for name, relative in plan.items():
            source, destination = installation / name, runtime / relative
            storage._reject_linked_destination(installation, source)
            storage._reject_linked_destination(runtime, destination)
            if source.exists():
                _validate_entry(source)
                if destination.exists():
                    raise storage.StorageError(f"Source migration destination already exists: {destination}")
            elif not destination.exists():
                raise storage.StorageError(f"Source migration data is missing: {source}")
            else:
                _validate_entry(destination)

        for name, relative in plan.items():
            source, destination = installation / name, runtime / relative
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                source.rename(destination)
        plan_path.unlink(missing_ok=True)
        completed = True
    finally:
        for lock in reversed(acquired):
            lock.release()
        if completed:
            # Windows refuses this unlink if an older scanner acquired the lock.
            try:
                old_lock_path.unlink(missing_ok=True)
            except OSError:
                pass
    return runtime
