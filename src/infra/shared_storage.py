"""Opt-in shared data with independent edition configs.

A virtual installation named ``shared`` owns the existing migration journal and
one data_path in LocalAppData. All linked installations follow that path. Source
checkouts require a local opt-in marker; an ordinary checkout never consults the
shared profile. Attaching does NOT merge or delete the old data library.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
from typing import TYPE_CHECKING
from uuid import uuid4

from infra import edition

if TYPE_CHECKING:
    from infra.data_storage import MigrationActionResult, StorageContext

SHARED_KEY = "shared"
SOURCE_MARKER = ".bonkscanner-shared.json"
IGNORE_SHARED_ENV = "BONKSCANNER_IGNORE_SHARED_STORAGE"


def _member_key(installation: Path) -> str:
    from infra import data_storage as storage
    return f"{storage._installation_key(installation)}-{edition.EDITION}"


def _members(entry: dict) -> dict:
    from infra import data_storage as storage
    members = entry.get("members")
    if not isinstance(members, dict):
        raise storage.StorageError("The shared profile has an invalid installation list.")
    return members


def _copy_config_if_missing(source: Path, destination: Path) -> bool:
    """Publish a verified copy exclusively; never replace an existing config."""
    from infra import data_storage as storage
    storage._reject_linked_destination(destination.parent, destination)
    if destination.exists():
        storage._validate_config(destination)
        return False
    if not source.is_file():
        return False
    storage._reject_linked_destination(source.parent, source)
    storage._validate_config(source)
    before = storage._file_signature(source)
    temporary = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        copied = storage._file_signature(temporary)
        if (copied[0] != before[0] or copied[2] != before[2]
                or storage._file_signature(source) != before):
            raise storage.StorageError("The source configuration changed while it was being copied.")
        # Same-volume hard-link publication is atomic and fails rather than
        # overwriting a newly created destination.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            storage._reject_linked_destination(destination.parent, destination)
            storage._validate_config(destination)
            return False
        return True
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def prepare_edition_config(data_dir: Path) -> None:
    """One-time upgrade of Advanced's previous local config; no runtime fallback."""
    if edition.EDITION == "advanced":
        _copy_config_if_missing(data_dir / "config.json", data_dir / edition.CONFIG_FILE_NAME)


def selected_shared_context(installation: Path, *, source_run: bool) -> StorageContext | None:
    from infra import data_storage as storage
    if os.environ.get(IGNORE_SHARED_ENV) == "1":
        return None
    marker = installation / SOURCE_MARKER
    if source_run:
        if not marker.exists() and not marker.is_symlink():
            return None
        storage._reject_linked_destination(installation, marker)
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise storage.StorageError(f"The source shared-profile selection is unreadable: {marker}") from exc
        if payload != {"shared_profile": 1}:
            raise storage.StorageError(f"The source shared-profile selection is invalid: {marker}")
    recommended = storage.recommended_data_directory()
    state = storage._load_state(recommended)
    entry = storage._entry_for(state, recommended, SHARED_KEY)
    if entry is None:
        if source_run:
            raise storage.StorageError("This checkout selected shared data, but the shared profile is missing.")
        return None
    member = _members(entry).get(_member_key(installation))
    if member is None:
        if source_run:
            raise storage.StorageError("This checkout is not registered with the shared profile.")
        # Installed copies using the default location follow the shared profile.
        # A private/legacy profile is never silently discarded.
        private = storage._entry_for(state, installation, storage._installation_key(installation))
        if storage._profile_exists(installation) and not (private and private.get("mode") == "local"):
            return None
        if private and private.get("data_path"):
            if storage._normalized_path(storage._storage_path(private["data_path"])) != storage._normalized_path(recommended):
                return None
    else:
        if (not isinstance(member, dict) or member.get("edition") != edition.EDITION
                or not isinstance(member.get("installation_path"), str)
                or storage._normalized_path(Path(member["installation_path"])) != storage._normalized_path(installation)):
            raise storage.StorageError("The shared profile installation identity is invalid.")

    context = storage._load_selected_context(recommended, recommended, SHARED_KEY)
    if not context.data_dir.is_dir() or not storage._profile_exists(context.data_dir):
        raise storage.StorageError(f"The shared data folder is missing or has no profile: {context.data_dir}")
    return replace(context, mode="shared", installation_dir=installation)


def shared_status(context: StorageContext) -> StorageContext:
    from infra import data_storage as storage
    state = storage._load_state(context.recommended_dir)
    selected = storage._context_from_state(context.recommended_dir, context.recommended_dir, SHARED_KEY, state)
    return replace(selected, mode="shared", installation_dir=context.installation_dir, data_dir=context.data_dir)


def request_shared_folder(destination: str | Path) -> MigrationActionResult:
    """Connect on next launch, preserving both configs and all old library files."""
    from infra import data_storage as storage
    context = storage.storage_context()
    state_lock = None
    acquired = []
    try:
        if context.migration_status == "pending":
            raise storage.StorageError("Cancel the scheduled migration before connecting a shared folder.")
        target = storage._storage_path(destination)
        source = storage._storage_path(context.data_dir)
        if not target.is_dir() or not storage._profile_exists(target):
            raise storage.StorageError("Choose an existing BonkScanner data folder, not an empty directory.")
        same = storage._normalized_path(source) == storage._normalized_path(target)
        if not same and storage._paths_overlap(source, target):
            raise storage.StorageError("The current and shared data folders must be separate.")
        recommended = storage.recommended_data_directory()
        state_lock = storage._ProcessFileLock(recommended / storage.STATE_LOCK_NAME)
        if not state_lock.acquire():
            raise storage.StorageError("Storage state is in use by another instance.")
        state = storage._load_state(recommended)
        before = deepcopy(state)
        if context.mode != "shared" and context.installation_key is not None:
            private = storage._entry_for(state, context.installation_dir, str(context.installation_key))
            pending = private.get("migration") if private else None
            if isinstance(pending, dict) and pending.get("status") == "pending":
                raise storage.StorageError("Cancel the scheduled migration before connecting a shared folder.")
        entry = storage._entry_for(state, recommended, SHARED_KEY)
        if entry is not None:
            _members(entry)
            current = storage._selected_data_path(entry, recommended)
            if storage._normalized_path(current) != storage._normalized_path(target):
                raise storage.StorageError(
                    f"The shared profile already uses {current}. Connect to it, or move the shared profile from its Data page."
                )
            migration = entry.get("migration")
            if isinstance(migration, dict) and migration.get("status") == "pending":
                raise storage.StorageError("Cancel the shared profile's scheduled migration first.")
        if storage._active_lock is None:
            lock = storage._ProcessFileLock(source / storage.DATA_LOCK_NAME)
            if not lock.acquire():
                raise storage.StorageError("The current data folder is in use by another instance.")
            acquired.append(lock)
        if not same:
            lock = storage._ProcessFileLock(target / storage.DATA_LOCK_NAME)
            if not lock.acquire():
                raise storage.StorageError("The shared folder is in use. Close the other BonkScanner edition first.")
            acquired.append(lock)
        storage._guard_other_installation_journals(target, state, SHARED_KEY)
        if storage._journal_path(target, SHARED_KEY).exists():
            raise storage.StorageError("Start a linked copy to recover the interrupted shared migration first.")
        # This also rejects linked recording/log directories before any shared
        # reader can follow a path outside the selected data folder.
        storage._migration_sources(target)
        for name in edition.CONFIG_FILE_NAMES:
            storage._reject_linked_destination(target, target / name)
            storage._validate_config(target / name)
        storage._validate_merchant_history(target / "merchant_history.jsonl")
        config_source = source / edition.CONFIG_FILE_NAME
        if edition.EDITION == "advanced" and not config_source.exists():
            config_source = source / "config.json"
        _copy_config_if_missing(config_source, target / edition.CONFIG_FILE_NAME)
        entry = storage._entry_for(state, recommended, SHARED_KEY, create=True)
        entry.setdefault("members", {})[_member_key(context.installation_dir)] = {
            "installation_path": str(context.installation_dir), "edition": edition.EDITION,
        }
        entry["mode"] = "local"
        entry["data_path"] = str(target)
        storage._write_state(recommended, state)
        try:
            if not storage.is_frozen_build():
                marker = context.installation_dir / SOURCE_MARKER
                storage._reject_linked_destination(context.installation_dir, marker)
                storage._write_journal(marker, {"shared_profile": 1})
        except Exception:
            storage._write_state(recommended, before)
            raise
        return storage.MigrationActionResult(
            True, "connected",
            f"Shared data selected: {target}. Restart BonkScanner to use it. "
            f"This edition uses {edition.CONFIG_FILE_NAME}. Existing destination settings were kept; "
            "the old recordings and history were not copied or removed.",
        )
    except (OSError, ValueError, storage.StorageError) as exc:
        return storage.MigrationActionResult(False, "failed", str(exc))
    finally:
        for lock in reversed(acquired):
            lock.release()
        if state_lock is not None:
            state_lock.release()
