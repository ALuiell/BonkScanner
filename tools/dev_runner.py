"""Run BonkScanner and restart it when Python or QSS sources change.

This intentionally has no third-party dependency.  The normal ``run.bat``
stays detached and quiet; ``run_dev.bat`` keeps this process visible so a
developer can see restarts and application errors.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable


POLL_SECONDS = 0.25
DEBOUNCE_SECONDS = 0.45
GRACEFUL_CLOSE_SECONDS = 5.0
WATCH_SUFFIXES = frozenset({".py", ".qss"})
WATCH_DIRECTORIES = ("src", "redisign_ui")

FileState = tuple[int, int]
WatchSnapshot = dict[Path, FileState]


def scan_watch_files(
    project_root: Path,
    *,
    directories: Iterable[str] = WATCH_DIRECTORIES,
) -> WatchSnapshot:
    """Return stable file metadata for every watched source under the project."""
    snapshot: WatchSnapshot = {}
    for directory in directories:
        root = project_root / directory
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if (
                not path.is_file()
                or path.suffix.casefold() not in WATCH_SUFFIXES
                or "__pycache__" in path.parts
            ):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[path] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


def changed_paths(before: WatchSnapshot, after: WatchSnapshot) -> tuple[Path, ...]:
    """Files added, removed, or modified between two watcher snapshots."""
    paths = set(before) | set(after)
    return tuple(sorted(path for path in paths if before.get(path) != after.get(path)))


def _start_app(project_root: Path) -> subprocess.Popen:
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"
    environment["BONKSCANNER_DEV_RUN"] = "1"
    command = [sys.executable, str(project_root / "src" / "main.py")]
    return subprocess.Popen(command, cwd=project_root, env=environment)


def _post_windows_close(process_id: int) -> bool:
    """Ask every visible top-level window owned by ``process_id`` to close."""
    if os.name != "nt":
        return False

    user32 = ctypes.windll.user32
    posted = False
    enum_callback = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    @enum_callback
    def close_window(window_handle, _parameter):
        nonlocal posted
        owner_process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(
            window_handle,
            ctypes.byref(owner_process_id),
        )
        if owner_process_id.value == process_id and user32.IsWindowVisible(window_handle):
            user32.PostMessageW(window_handle, 0x0010, 0, 0)  # WM_CLOSE
            posted = True
        return True

    user32.EnumWindows(close_window, 0)
    return posted


def _stop_app(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    requested_graceful_close = _post_windows_close(process.pid)
    if requested_graceful_close:
        try:
            process.wait(timeout=GRACEFUL_CLOSE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass

    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def _wait_until_changes_settle(
    project_root: Path,
    previous: WatchSnapshot,
) -> tuple[WatchSnapshot, tuple[Path, ...]]:
    current = scan_watch_files(project_root)
    accumulated = set(changed_paths(previous, current))
    deadline = time.monotonic() + DEBOUNCE_SECONDS

    while time.monotonic() < deadline:
        time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
        updated = scan_watch_files(project_root)
        newly_changed = changed_paths(current, updated)
        if newly_changed:
            accumulated.update(newly_changed)
            current = updated
            deadline = time.monotonic() + DEBOUNCE_SECONDS

    return current, tuple(sorted(accumulated))


def run(project_root: Path) -> int:
    snapshot = scan_watch_files(project_root)
    print(f"[dev] Watching {len(snapshot)} Python/QSS files.")
    process = _start_app(project_root)
    print(f"[dev] BonkScanner started (PID {process.pid}).")

    try:
        while True:
            time.sleep(POLL_SECONDS)
            exit_code = process.poll()
            if exit_code is not None:
                print(f"[dev] BonkScanner exited with code {exit_code}; watcher stopped.")
                return int(exit_code)

            latest = scan_watch_files(project_root)
            if latest == snapshot:
                continue

            snapshot, changed = _wait_until_changes_settle(project_root, snapshot)
            relative = [
                str(path.relative_to(project_root))
                for path in changed
                if path.is_relative_to(project_root)
            ]
            preview = ", ".join(relative[:4])
            if len(relative) > 4:
                preview += f", +{len(relative) - 4} more"
            print(f"[dev] Change detected: {preview or 'source tree'}")

            _stop_app(process)
            process = _start_app(project_root)
            print(f"[dev] BonkScanner restarted (PID {process.pid}).")
    except KeyboardInterrupt:
        print("\n[dev] Stopping...")
        _stop_app(process)
        return 0


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    return run(project_root)


if __name__ == "__main__":
    raise SystemExit(main())
