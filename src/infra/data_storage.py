"""Select and migrate BonkScanner's writable application data directory.

Source checkouts deliberately remain portable: they keep their data in the
repository root and never consult the installed-build migration state. Frozen
builds use one shared LocalAppData directory unless the executable directory
already contains a legacy BonkScanner profile.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


STATE_SCHEMA_VERSION = 1
DATA_DIRECTORY_NAME = "BonkScanner"
STATE_FILE_NAME = ".storage-state.json"
STATE_LOCK_NAME = ".storage-state.lock"
DATA_LOCK_NAME = ".bonkscanner-data.lock"

PROFILE_FILES = (
    "config.json",
    "merchant_history.jsonl",
    "vod_metadata_index.json",
)
PROFILE_DIRECTORIES = ("stats_recordings", "vods")
MIGRATION_FILES = PROFILE_FILES + ("supporter_access_cache.json",)
MIGRATION_DIRECTORIES = PROFILE_DIRECTORIES + ("logs",)
LEGACY_CLEANUP_FILES = MIGRATION_FILES + ("merchant_history.jsonl.lock",)


class StorageError(RuntimeError):
    """A user-presentable storage bootstrap or migration failure."""


@dataclass(frozen=True, slots=True)
class StorageContext:
    mode: str
    installation_dir: Path
    data_dir: Path
    recommended_dir: Path | None
    installation_key: str | None
    migration_status: str = ""
    migration_message: str = ""
    legacy_dir: Path | None = None
    legacy_cleanup_status: str = ""
    legacy_cleanup_message: str = ""

    @property
    def can_migrate(self) -> bool:
        return self.mode == "legacy" and self.recommended_dir is not None


@dataclass(frozen=True, slots=True)
class MigrationActionResult:
    success: bool
    status: str
    message: str = ""


class _ProcessFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = None

    def acquire(self) -> bool:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("a+b")
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                if self.path.stat().st_size == 0:
                    self._file.write(b"0")
                    self._file.flush()
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, IOError):
            self.release()
            return False

    def release(self) -> None:
        stream = self._file
        self._file = None
        if stream is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError):
            pass
        try:
            stream.close()
        except OSError:
            pass


_context_lock = threading.RLock()
_context: StorageContext | None = None
_active_lock: _ProcessFileLock | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def is_frozen_build() -> bool:
    return bool(getattr(sys, "frozen", False))


def installation_directory() -> Path:
    if is_frozen_build():
        return Path(sys.executable).resolve().parent
    return _source_root()


def _local_appdata_root() -> Path:
    value = os.environ.get("LOCALAPPDATA", "").strip()
    if not value:
        profile = os.environ.get("USERPROFILE", "").strip()
        if profile:
            value = str(Path(profile) / "AppData" / "Local")
    if not value:
        raise StorageError(
            "BonkScanner could not find the current user's Local AppData folder."
        )
    return Path(value).expanduser().resolve()


def recommended_data_directory() -> Path:
    return _local_appdata_root() / DATA_DIRECTORY_NAME


def _normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path.resolve())))


def _installation_key(path: Path) -> str:
    normalized = _normalized_path(path)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _profile_exists(root: Path) -> bool:
    return any((root / name).is_file() for name in PROFILE_FILES) or any(
        (root / name).is_dir() for name in PROFILE_DIRECTORIES
    )


def _empty_state() -> dict[str, Any]:
    return {"schema_version": STATE_SCHEMA_VERSION, "installations": {}}


def _state_path(recommended: Path) -> Path:
    return recommended / STATE_FILE_NAME


def _journal_path(recommended: Path, key: str) -> Path:
    return recommended / f".migration-{key}.journal.json"


def _load_state(recommended: Path) -> dict[str, Any]:
    path = _state_path(recommended)
    if not path.exists():
        return _empty_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StorageError(
            f"BonkScanner could not read its storage state at {path}: {exc}"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != STATE_SCHEMA_VERSION
        or not isinstance(payload.get("installations"), dict)
    ):
        raise StorageError(f"BonkScanner storage state is invalid: {path}")
    return payload


def _write_state(recommended: Path, state: dict[str, Any]) -> None:
    recommended.mkdir(parents=True, exist_ok=True)
    target = _state_path(recommended)
    temporary = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
    rendered = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        raise StorageError(f"BonkScanner could not save its storage state: {exc}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _write_journal(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _entry_for(
    state: dict[str, Any], installation: Path, key: str, *, create: bool = False
) -> dict[str, Any] | None:
    installations = state["installations"]
    entry = installations.get(key)
    if entry is not None and not isinstance(entry, dict):
        raise StorageError("BonkScanner storage state contains an invalid installation entry.")
    if entry is None and create:
        entry = {"installation_path": str(installation)}
        installations[key] = entry
    if entry is not None:
        saved_path = entry.get("installation_path")
        if saved_path and _normalized_path(Path(saved_path)) != _normalized_path(installation):
            raise StorageError("BonkScanner storage state has an installation-key collision.")
    return entry


def _ensure_writable(root: Path) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd, probe_name = tempfile.mkstemp(prefix=".bonkscanner-write-", suffix=".tmp", dir=root)
        os.close(fd)
        Path(probe_name).unlink()
    except OSError as exc:
        raise StorageError(f"BonkScanner cannot write to its data folder {root}: {exc}") from exc


def _is_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attributes & reparse_flag)
    except OSError:
        return True


def _should_skip_file(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".lock") or name.endswith(".tmp")


def _iter_tree_files(root: Path) -> Iterable[Path]:
    if _is_reparse_point(root):
        raise StorageError(f"Migration refused a linked directory: {root}")
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory in tuple(directories):
            child = current_path / directory
            if _is_reparse_point(child):
                raise StorageError(f"Migration refused a linked directory: {child}")
        for filename in files:
            path = current_path / filename
            if _should_skip_file(path):
                continue
            if _is_reparse_point(path):
                raise StorageError(f"Migration refused a linked file: {path}")
            yield path


def _migration_sources(source: Path) -> tuple[tuple[Path, Path], ...]:
    pairs: list[tuple[Path, Path]] = []
    for name in MIGRATION_FILES:
        path = source / name
        if path.exists() and _is_reparse_point(path):
            raise StorageError(f"Migration refused a linked file: {path}")
        if path.is_file() and not _should_skip_file(path):
            pairs.append((path, Path(name)))
    for path in sorted(source.glob("merchant_history.jsonl.broken-*")):
        if _is_reparse_point(path):
            raise StorageError(f"Migration refused a linked file: {path}")
        if path.is_file() and not _should_skip_file(path):
            pairs.append((path, Path(path.name)))
    for name in MIGRATION_DIRECTORIES:
        root = source / name
        if not root.is_dir():
            continue
        for path in _iter_tree_files(root):
            pairs.append((path, Path(name) / path.relative_to(root)))
    return tuple(sorted(pairs, key=lambda pair: pair[1].as_posix().lower()))


def _legacy_cleanup_targets(source: Path) -> tuple[Path, ...]:
    targets: list[Path] = []
    for name in LEGACY_CLEANUP_FILES:
        path = source / name
        if path.exists() or path.is_symlink():
            targets.append(path)
    targets.extend(
        path
        for path in sorted(source.glob("merchant_history.jsonl.broken-*"))
        if path.exists() or path.is_symlink()
    )
    for name in MIGRATION_DIRECTORIES:
        path = source / name
        if path.exists() or path.is_symlink():
            targets.append(path)
    return tuple(dict.fromkeys(targets))


def _validate_legacy_cleanup_target(path: Path) -> None:
    if _is_reparse_point(path):
        raise StorageError(f"Cleanup refused a linked path: {path}")
    if path.is_dir():
        tuple(_iter_tree_files(path))
        return
    if not path.is_file():
        raise StorageError(f"Cleanup refused an unexpected path type: {path}")


def _remove_legacy_cleanup_target(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def legacy_data_exists(source: Path) -> bool:
    try:
        return bool(_legacy_cleanup_targets(Path(source)))
    except OSError:
        # Keep the action available so the cleanup service can report the
        # concrete access error instead of silently hiding the button.
        return True


def _file_signature(path: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, digest.hexdigest()


def _validate_config(path: Path) -> None:
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StorageError(f"The legacy config.json could not be validated: {exc}") from exc
    if not isinstance(payload, dict):
        raise StorageError("The legacy config.json does not contain a settings object.")


def _validate_merchant_history(path: Path) -> None:
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict) or payload.get("v") != 1:
                    raise ValueError("unsupported record")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise StorageError(
            f"The legacy merchant history could not be validated at line {line_number if 'line_number' in locals() else 1}: {exc}"
        ) from exc


def _target_has_profile(target: Path) -> bool:
    return _profile_exists(target)


def _current_instance_process_ids() -> set[int]:
    """Return the Python child and its one-file PyInstaller launcher, if any."""
    return {os.getpid(), os.getppid()}


def _running_process_from_installation(installation: Path) -> bool | None:
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        snapshot_flag = 0x00000002
        query_limited_information = 0x1000
        invalid_handle = ctypes.c_void_p(-1).value

        class ProcessEntry32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(snapshot_flag, 0)
        if snapshot == invalid_handle:
            return None
        try:
            entry = ProcessEntry32W()
            entry.dwSize = ctypes.sizeof(entry)
            found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            expected = _normalized_path(installation)
            # A one-file PyInstaller build keeps a small launcher process alive
            # while the extracted Python child runs.  Both processes report the
            # installed BonkScanner.exe path, so the launcher is part of this
            # instance rather than a competing legacy instance.
            current_instance_pids = _current_instance_process_ids()
            unverified_process = False
            while found:
                pid = int(entry.th32ProcessID)
                if (
                    pid not in current_instance_pids
                    and str(entry.szExeFile).lower() == "bonkscanner.exe"
                ):
                    process = kernel32.OpenProcess(query_limited_information, False, pid)
                    if process:
                        try:
                            size = wintypes.DWORD(32768)
                            buffer = ctypes.create_unicode_buffer(size.value)
                            if kernel32.QueryFullProcessImageNameW(
                                process, 0, buffer, ctypes.byref(size)
                            ):
                                if _normalized_path(Path(buffer.value).parent) == expected:
                                    return True
                            else:
                                unverified_process = True
                        finally:
                            kernel32.CloseHandle(process)
                    else:
                        unverified_process = True
                found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            if unverified_process:
                return None
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception:
        return None
    return False


def _publish_staging(staging: Path, target: Path, published: list[Path]) -> None:
    for child in sorted(staging.iterdir(), key=lambda value: value.name.lower()):
        destination = target / child.name
        if child.name == "supporter_access_cache.json" and destination.exists():
            continue
        if child.name == "logs" and destination.is_dir():
            for log_path in _iter_tree_files(child):
                relative = log_path.relative_to(child)
                log_destination = destination / relative
                if log_destination.exists():
                    continue
                log_destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(log_path, log_destination)
                published.append(log_destination)
            continue
        if destination.exists():
            raise StorageError(f"The destination changed during migration: {destination}")
        os.replace(child, destination)
        published.append(destination)
def _rollback_published(paths: Iterable[Path]) -> bool:
    complete = True
    for path in reversed(tuple(paths)):
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            complete = False
    return complete


def _publish_manifest(staging: Path, target: Path) -> dict[str, dict[str, Any]]:
    manifest: dict[str, dict[str, Any]] = {}
    for path in _iter_tree_files(staging):
        relative = path.relative_to(staging)
        destination = target / relative
        if destination.exists():
            if relative == Path("supporter_access_cache.json") or relative.parts[0] == "logs":
                continue
            raise StorageError(f"The destination changed during migration: {destination}")
        size, _mtime_ns, digest = _file_signature(path)
        manifest[relative.as_posix()] = {"size": size, "sha256": digest}
    return manifest


def _safe_manifest_relative(raw: str) -> Path:
    relative = Path(str(raw))
    if (
        relative.is_absolute()
        or relative.drive
        or not relative.parts
        or ".." in relative.parts
    ):
        raise StorageError("The migration recovery journal contains an unsafe path.")
    return relative


def _recover_interrupted_publish(recommended: Path, key: str, source: Path) -> None:
    journal_path = _journal_path(recommended, key)
    if not journal_path.exists():
        return
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StorageError(f"The migration recovery journal is unreadable: {exc}") from exc
    if (
        not isinstance(journal, dict)
        or journal.get("schema_version") != 1
        or _normalized_path(Path(str(journal.get("source") or "")))
        != _normalized_path(source)
        or not isinstance(journal.get("files"), dict)
    ):
        raise StorageError("The migration recovery journal is invalid.")

    paths_to_remove: list[Path] = []
    for raw_relative, expected in journal["files"].items():
        if not isinstance(expected, dict):
            raise StorageError("The migration recovery journal contains an invalid file entry.")
        relative = _safe_manifest_relative(raw_relative)
        destination = recommended / relative
        if not destination.exists():
            continue
        if not destination.is_file() or destination.is_symlink():
            raise StorageError(
                f"Migration recovery stopped because this path changed: {destination}"
            )
        size, _mtime_ns, digest = _file_signature(destination)
        if size != expected.get("size") or digest != expected.get("sha256"):
            raise StorageError(
                f"Migration recovery stopped because this copied file changed: {destination}"
            )
        paths_to_remove.append(destination)

    for path in sorted(paths_to_remove, key=lambda value: len(value.parts), reverse=True):
        try:
            path.unlink()
        except OSError as exc:
            raise StorageError(
                f"Migration recovery could not remove its partial copy {path}: {exc}"
            ) from exc
    for directory_name in MIGRATION_DIRECTORIES:
        root = recommended / directory_name
        if not root.is_dir() or root.is_symlink():
            continue
        directories = sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda value: len(value.parts),
            reverse=True,
        )
        for directory in (*directories, root):
            try:
                directory.rmdir()
            except OSError:
                pass
    try:
        journal_path.unlink()
    except OSError as exc:
        raise StorageError(
            f"Migration recovery could not finish removing {journal_path}: {exc}"
        ) from exc


def _guard_other_installation_journals(
    recommended: Path, state: dict[str, Any], current_key: str
) -> None:
    prefix = ".migration-"
    suffix = ".journal.json"
    for journal in recommended.glob(f"{prefix}*{suffix}"):
        key = journal.name[len(prefix) : -len(suffix)]
        if key == current_key:
            continue
        raw_entry = state["installations"].get(key)
        migration = raw_entry.get("migration") if isinstance(raw_entry, dict) else None
        if (
            isinstance(migration, dict)
            and migration.get("status") == "success"
        ):
            try:
                journal.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        if journal.exists():
            raise StorageError(
                "Another BonkScanner installation has an interrupted data migration. "
                "Start that original installation once to recover it before using this copy."
            )


def _perform_pending_migration(
    installation: Path,
    recommended: Path,
    key: str,
    state: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any]:
    migration = entry.get("migration")
    if not isinstance(migration, dict) or migration.get("status") != "pending":
        return state
    source = Path(str(migration.get("source") or installation)).resolve()
    if _normalized_path(source) != _normalized_path(installation):
        raise StorageError("The pending migration source does not match this installation.")

    staging = recommended / f".migration-{key}"
    source_lock = _ProcessFileLock(source / DATA_LOCK_NAME)
    target_lock = _ProcessFileLock(recommended / DATA_LOCK_NAME)
    published: list[Path] = []
    journal_path = _journal_path(recommended, key)
    try:
        process_check = _running_process_from_installation(installation)
        if process_check is None:
            raise StorageError(
                "BonkScanner could not verify that the legacy installation is closed."
            )
        if process_check:
            raise StorageError("Another BonkScanner from the legacy folder is still running.")
        if not source_lock.acquire():
            raise StorageError("The legacy data folder is in use by another BonkScanner instance.")
        if not target_lock.acquire():
            raise StorageError("The recommended data folder is in use by another BonkScanner instance.")
        _recover_interrupted_publish(recommended, key, source)
        if _target_has_profile(recommended):
            raise StorageError(
                "The recommended folder already contains another BonkScanner profile. Nothing was overwritten."
            )
        _validate_config(source / "config.json")
        _validate_merchant_history(source / "merchant_history.jsonl")
        sources = _migration_sources(source)
        before = {relative: _file_signature(path) for path, relative in sources}

        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for source_path, relative in sources:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            copied = _file_signature(destination)
            if copied[0] != before[relative][0] or copied[2] != before[relative][2]:
                raise StorageError(f"Migration verification failed for {relative}.")

        current_sources = _migration_sources(source)
        current_relatives = tuple(relative for _, relative in current_sources)
        if current_relatives != tuple(before):
            raise StorageError("Legacy data changed while it was being copied. Try again after closing other copies.")
        for source_path, relative in current_sources:
            if _file_signature(source_path) != before[relative]:
                raise StorageError(f"Legacy data changed during migration: {relative}")
        process_check = _running_process_from_installation(installation)
        if process_check is None:
            raise StorageError(
                "BonkScanner could not recheck that the legacy installation is closed."
            )
        if process_check:
            raise StorageError(
                "Another BonkScanner from the legacy folder started during migration."
            )

        # The recording index contains absolute legacy paths. Let the normal
        # library refresh rebuild it against the newly selected data directory.
        index_path = staging / "vod_metadata_index.json"
        index_path.unlink(missing_ok=True)

        manifest = _publish_manifest(staging, recommended)
        _write_journal(
            journal_path,
            {
                "schema_version": 1,
                "source": str(source),
                "created_at": _utc_now(),
                "files": manifest,
            },
        )
        _publish_staging(staging, recommended, published)
        entry["mode"] = "local"
        entry["legacy_path"] = str(source)
        entry["migration"] = {
            "status": "success",
            "source": str(source),
            "completed_at": _utc_now(),
            "message": "Data was copied and verified. The original files were kept.",
        }
        _write_state(recommended, state)
        try:
            journal_path.unlink(missing_ok=True)
        except OSError:
            pass
        return state
    except Exception as exc:
        rollback_complete = _rollback_published(published)
        if isinstance(exc, StorageError):
            message = str(exc)
        else:
            message = f"Migration failed: {type(exc).__name__}: {exc}"
        entry["migration"] = {
            "status": "failed",
            "source": str(source),
            "failed_at": _utc_now(),
            "message": message,
        }
        if rollback_complete:
            try:
                journal_path.unlink(missing_ok=True)
            except OSError:
                pass
        _write_state(recommended, state)
        return state
    finally:
        try:
            if staging.exists():
                shutil.rmtree(staging)
        except OSError:
            pass
        target_lock.release()
        source_lock.release()


def _context_from_state(
    installation: Path,
    recommended: Path,
    key: str,
    state: dict[str, Any],
) -> StorageContext:
    entry = _entry_for(state, installation, key)
    migration = entry.get("migration", {}) if entry else {}
    status = str(migration.get("status") or "") if isinstance(migration, dict) else ""
    message = str(migration.get("message") or "") if isinstance(migration, dict) else ""
    cleanup = entry.get("legacy_cleanup", {}) if entry else {}
    cleanup_status = str(cleanup.get("status") or "") if isinstance(cleanup, dict) else ""
    cleanup_message = str(cleanup.get("message") or "") if isinstance(cleanup, dict) else ""
    legacy_dir = None
    if entry and entry.get("legacy_path"):
        legacy_dir = Path(str(entry["legacy_path"]))
    if _normalized_path(installation) == _normalized_path(recommended):
        mode = "local"
        data_dir = recommended
    elif entry and entry.get("mode") == "local":
        mode = "local"
        data_dir = recommended
    elif _profile_exists(installation):
        mode = "legacy"
        data_dir = installation
    else:
        mode = "local"
        data_dir = recommended
    return StorageContext(
        mode=mode,
        installation_dir=installation,
        data_dir=data_dir,
        recommended_dir=recommended,
        installation_key=key,
        migration_status=status,
        migration_message=message,
        legacy_dir=legacy_dir,
        legacy_cleanup_status=cleanup_status,
        legacy_cleanup_message=cleanup_message,
    )


def initialize_storage(*, acquire_active_lock: bool = True) -> StorageContext:
    global _context, _active_lock
    with _context_lock:
        if _context is not None:
            if acquire_active_lock and _active_lock is None:
                active_lock = _ProcessFileLock(_context.data_dir / DATA_LOCK_NAME)
                if not active_lock.acquire():
                    raise StorageError(
                        f"Another BonkScanner instance is already using {_context.data_dir}."
                    )
                _active_lock = active_lock
            return _context
        installation = installation_directory()
        if not is_frozen_build():
            context = StorageContext(
                mode="source",
                installation_dir=installation,
                data_dir=installation,
                recommended_dir=None,
                installation_key=None,
            )
        else:
            recommended = recommended_data_directory()
            _ensure_writable(recommended)
            key = _installation_key(installation)
            state_lock = _ProcessFileLock(recommended / STATE_LOCK_NAME)
            if not state_lock.acquire():
                raise StorageError("BonkScanner storage state is being changed by another instance.")
            try:
                state = _load_state(recommended)
                _guard_other_installation_journals(recommended, state, key)
                entry = _entry_for(state, installation, key)
                current_journal = _journal_path(recommended, key)
                migration = entry.get("migration") if entry else None
                if current_journal.exists() and (
                    not isinstance(migration, dict)
                    or migration.get("status") != "success"
                ):
                    _recover_interrupted_publish(recommended, key, installation)
                if entry and entry.get("mode") == "local":
                    migration = entry.get("migration")
                    if isinstance(migration, dict) and migration.get("status") == "success":
                        try:
                            _journal_path(recommended, key).unlink(missing_ok=True)
                        except OSError:
                            pass
                if entry and isinstance(entry.get("migration"), dict):
                    state = _perform_pending_migration(
                        installation, recommended, key, state, entry
                    )
                context = _context_from_state(installation, recommended, key, state)
            finally:
                state_lock.release()
        _ensure_writable(context.data_dir)
        if acquire_active_lock:
            active_lock = _ProcessFileLock(context.data_dir / DATA_LOCK_NAME)
            if not active_lock.acquire():
                raise StorageError(
                    f"Another BonkScanner instance is already using {context.data_dir}."
                )
            _active_lock = active_lock
        _context = context
        return context


def storage_context() -> StorageContext:
    with _context_lock:
        if _context is not None:
            return _context
    return initialize_storage(acquire_active_lock=False)


def active_data_directory() -> Path:
    return storage_context().data_dir


def migration_status() -> StorageContext:
    context = storage_context()
    if context.mode == "source" or context.recommended_dir is None:
        return context
    with _context_lock:
        state = _load_state(context.recommended_dir)
        return _context_from_state(
            context.installation_dir,
            context.recommended_dir,
            str(context.installation_key),
            state,
        )


def request_migration() -> MigrationActionResult:
    context = storage_context()
    if not context.can_migrate or context.recommended_dir is None:
        return MigrationActionResult(False, "unavailable", "This installation does not need migration.")
    state_lock = _ProcessFileLock(context.recommended_dir / STATE_LOCK_NAME)
    if not state_lock.acquire():
        return MigrationActionResult(False, "failed", "Storage state is in use by another instance.")
    try:
        state = _load_state(context.recommended_dir)
        entry = _entry_for(
            state,
            context.installation_dir,
            str(context.installation_key),
            create=True,
        )
        assert entry is not None
        entry["migration"] = {
            "status": "pending",
            "source": str(context.installation_dir),
            "requested_at": _utc_now(),
            "message": "Migration is scheduled for the next BonkScanner start.",
        }
        _write_state(context.recommended_dir, state)
        return MigrationActionResult(True, "pending", str(entry["migration"]["message"]))
    except StorageError as exc:
        return MigrationActionResult(False, "failed", str(exc))
    finally:
        state_lock.release()


def cancel_migration() -> MigrationActionResult:
    context = storage_context()
    if context.mode != "legacy" or context.recommended_dir is None:
        return MigrationActionResult(False, "unavailable", "There is no pending migration.")
    state_lock = _ProcessFileLock(context.recommended_dir / STATE_LOCK_NAME)
    if not state_lock.acquire():
        return MigrationActionResult(False, "failed", "Storage state is in use by another instance.")
    try:
        state = _load_state(context.recommended_dir)
        entry = _entry_for(state, context.installation_dir, str(context.installation_key))
        migration = entry.get("migration") if entry else None
        if not isinstance(migration, dict) or migration.get("status") != "pending":
            return MigrationActionResult(False, "unavailable", "There is no pending migration.")
        entry["migration"] = {
            "status": "cancelled",
            "source": str(context.installation_dir),
            "cancelled_at": _utc_now(),
            "message": "The scheduled migration was cancelled.",
        }
        _write_state(context.recommended_dir, state)
        return MigrationActionResult(True, "cancelled", str(entry["migration"]["message"]))
    except StorageError as exc:
        return MigrationActionResult(False, "failed", str(exc))
    finally:
        state_lock.release()


def remove_legacy_data() -> MigrationActionResult:
    context = migration_status()
    if (
        context.mode != "local"
        or context.migration_status != "success"
        or context.recommended_dir is None
        or context.legacy_dir is None
    ):
        return MigrationActionResult(
            False,
            "unavailable",
            "Old data can be removed only after a successful migration.",
        )
    source = Path(os.path.abspath(context.legacy_dir))
    if _normalized_path(source) in {
        _normalized_path(context.data_dir),
        _normalized_path(context.recommended_dir),
    }:
        return MigrationActionResult(
            False,
            "failed",
            "Cleanup refused to remove the active data folder.",
        )

    state_lock = _ProcessFileLock(context.recommended_dir / STATE_LOCK_NAME)
    if not state_lock.acquire():
        return MigrationActionResult(False, "failed", "Storage state is in use by another instance.")
    source_lock = _ProcessFileLock(source / DATA_LOCK_NAME)
    source_lock_acquired = False
    try:
        state = _load_state(context.recommended_dir)
        entry = _entry_for(
            state,
            context.installation_dir,
            str(context.installation_key),
        )
        migration = entry.get("migration") if entry else None
        if (
            entry is None
            or not isinstance(migration, dict)
            or migration.get("status") != "success"
            or _normalized_path(Path(str(entry.get("legacy_path") or "")))
            != _normalized_path(source)
        ):
            return MigrationActionResult(
                False,
                "failed",
                "The successful migration record does not match this old folder.",
            )

        try:
            source_stat = source.lstat()
        except FileNotFoundError:
            message = "The old data folder no longer exists; there is nothing to remove."
            entry["legacy_cleanup"] = {
                "status": "success",
                "completed_at": _utc_now(),
                "message": message,
            }
            _write_state(context.recommended_dir, state)
            return MigrationActionResult(True, "success", message)
        except OSError as exc:
            message = f"BonkScanner could not inspect the old data folder: {exc}"
            entry["legacy_cleanup"] = {
                "status": "failed",
                "attempted_at": _utc_now(),
                "message": message,
            }
            _write_state(context.recommended_dir, state)
            return MigrationActionResult(False, "failed", message)

        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        is_linked_source = stat.S_ISLNK(source_stat.st_mode) or bool(
            getattr(source_stat, "st_file_attributes", 0) & reparse_flag
        )
        if is_linked_source:
            message = f"Cleanup refused a linked old data folder: {source}"
            entry["legacy_cleanup"] = {
                "status": "failed",
                "attempted_at": _utc_now(),
                "message": message,
            }
            _write_state(context.recommended_dir, state)
            return MigrationActionResult(False, "failed", message)
        if not stat.S_ISDIR(source_stat.st_mode):
            message = f"Cleanup refused an unexpected old data path: {source}"
            entry["legacy_cleanup"] = {
                "status": "failed",
                "attempted_at": _utc_now(),
                "message": message,
            }
            _write_state(context.recommended_dir, state)
            return MigrationActionResult(False, "failed", message)

        process_check = _running_process_from_installation(source)
        if process_check is None:
            return MigrationActionResult(
                False,
                "failed",
                "BonkScanner could not verify that no other copy is using the old folder.",
            )
        if process_check:
            return MigrationActionResult(
                False,
                "failed",
                "Another BonkScanner from the old folder is still running.",
            )
        source_lock_acquired = source_lock.acquire()
        if not source_lock_acquired:
            return MigrationActionResult(
                False,
                "failed",
                "The old data folder is in use by another BonkScanner instance.",
            )

        try:
            targets = _legacy_cleanup_targets(source)
            for target in targets:
                _validate_legacy_cleanup_target(target)
        except (OSError, StorageError) as exc:
            message = f"BonkScanner could not safely inspect old data: {exc}"
            entry["legacy_cleanup"] = {
                "status": "failed",
                "attempted_at": _utc_now(),
                "message": message,
            }
            _write_state(context.recommended_dir, state)
            return MigrationActionResult(False, "failed", message)

        failures: list[str] = []
        removed = 0
        for target in targets:
            try:
                _validate_legacy_cleanup_target(target)
                _remove_legacy_cleanup_target(target)
                removed += 1
            except (OSError, StorageError) as exc:
                failures.append(f"{target}: {exc}")

        if failures:
            message = (
                f"Removed {removed} old data item(s), but some paths could not be removed: "
                + "; ".join(failures)
            )
            status = "partial"
            success = False
        else:
            message = (
                "Old migrated data was removed. BonkScanner.exe, updater files, "
                "unknown files, and unfinished temporary files were left in place."
            )
            status = "success"
            success = True
        entry["legacy_cleanup"] = {
            "status": status,
            "completed_at": _utc_now(),
            "message": message,
        }
        _write_state(context.recommended_dir, state)
        return MigrationActionResult(success, status, message)
    except StorageError as exc:
        return MigrationActionResult(False, "failed", str(exc))
    finally:
        source_lock.release()
        state_lock.release()
        if source_lock_acquired:
            try:
                (source / DATA_LOCK_NAME).unlink(missing_ok=True)
            except OSError:
                pass


def release_storage_lock() -> None:
    global _active_lock
    with _context_lock:
        lock = _active_lock
        _active_lock = None
    if lock is not None:
        lock.release()


def _reset_for_tests() -> None:
    global _context
    release_storage_lock()
    with _context_lock:
        _context = None


atexit.register(release_storage_lock)
