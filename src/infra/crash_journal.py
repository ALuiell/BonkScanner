"""Crash-only diagnostics for the frozen desktop application.

Normal runs leave no ``logs`` directory beside the executable.  A small pending
journal lives under the user's temporary directory while BonkScanner is running.
It is deleted after a clean return from the Qt event loop.  A Qt fatal message is
promoted immediately; any other unclean exit is promoted on the next launch.
"""
from __future__ import annotations

import faulthandler
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from typing import Any

from infra.paths import application_path


_LOCK = threading.RLock()
_MAX_CRASH_LOGS = 5
_SESSION_STARTED = "session.started"
_SESSION_CLEAN = "session.clean"

_installed = False
_pending_path: Path | None = None
_pending_stream = None
_qt_handler = None
_previous_qt_handler = None
_previous_sys_excepthook = None
_previous_threading_excepthook = None
_previous_unraisablehook = None


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _safe_value(value: Any) -> str:
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


def _pending_directory() -> Path:
    return Path(tempfile.gettempdir()) / "BonkScanner"


def _installation_key() -> str:
    installed_at = str(Path(application_path()).resolve()).casefold()
    return hashlib.sha256(installed_at.encode("utf-8")).hexdigest()[:12]


def _pending_pattern() -> str:
    return f"pending-{_installation_key()}-*.log"


def _new_pending_path(directory: Path) -> Path:
    return directory / f"pending-{_installation_key()}-{os.getpid()}.log"


def _logs_directory() -> Path:
    override = os.environ.get("BONKSCANNER_CRASH_LOG_DIR")
    if override:
        return Path(override)
    return Path(application_path()) / "logs"


def _crash_log_name() -> str:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    return f"crash-{stamp}.log"


def _write(event: str, *, durable: bool = False, **fields: Any) -> None:
    stream = _pending_stream
    if stream is None:
        return
    parts = [
        _timestamp(),
        f"pid={os.getpid()}",
        f"thread={_safe_value(threading.current_thread().name)}",
        event,
    ]
    parts.extend(f"{key}={_safe_value(value)}" for key, value in fields.items())
    line = " | ".join(parts) + "\n"
    try:
        with _LOCK:
            stream.write(line)
            stream.flush()
            if durable:
                os.fsync(stream.fileno())
    except Exception:
        # Diagnostics must never turn a recoverable application error into a
        # second failure while the process is already shutting down.
        pass


def log_runtime_event(event: str, **fields: Any) -> None:
    """Append lifecycle context to the pending journal, if it is installed."""
    _write(event, **fields)


def _prune_crash_logs(directory: Path) -> None:
    logs = sorted(
        directory.glob("crash-*.log"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale in logs[_MAX_CRASH_LOGS:]:
        try:
            stale.unlink()
        except OSError:
            pass


def _unique_crash_path(directory: Path) -> Path:
    candidate = directory / _crash_log_name()
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{candidate.stem}-{suffix}{candidate.suffix}"
        suffix += 1
    return candidate


def _promote(path: Path) -> Path | None:
    """Move a pending journal beside the executable after an abnormal exit."""
    if not path.exists():
        return None
    try:
        directory = _logs_directory()
        directory.mkdir(parents=True, exist_ok=True)
        destination = _unique_crash_path(directory)
        os.replace(path, destination)
        _prune_crash_logs(directory)
        return destination
    except OSError:
        return None


def _recover_previous_session(pending: Path) -> Path | None:
    """Promote only journals that did not record a clean event-loop return."""
    if not pending.exists():
        return None
    try:
        tail = pending.read_bytes()[-4096:].decode("utf-8", errors="replace")
    except OSError:
        tail = ""
    if _SESSION_CLEAN in tail or "session.promoted" in tail:
        try:
            pending.unlink()
        except OSError:
            pass
        return None
    return _promote(pending)


def _format_exception(exc_type, exc_value, exc_traceback) -> str:
    return "".join(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    ).rstrip()


def _install_python_hooks() -> None:
    global _previous_sys_excepthook
    global _previous_threading_excepthook
    global _previous_unraisablehook

    _previous_sys_excepthook = sys.excepthook

    def sys_hook(exc_type, exc_value, exc_traceback):
        _write(
            "python.unhandled",
            durable=True,
            traceback=_format_exception(exc_type, exc_value, exc_traceback),
        )
        _promote_current()
        if _previous_sys_excepthook is not None:
            _previous_sys_excepthook(exc_type, exc_value, exc_traceback)

    sys.excepthook = sys_hook

    _previous_threading_excepthook = threading.excepthook

    def threading_hook(args):
        _write(
            "python.thread_unhandled",
            durable=True,
            worker=getattr(args.thread, "name", "unknown"),
            traceback=_format_exception(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            ),
        )
        _promote_current()
        if _previous_threading_excepthook is not None:
            _previous_threading_excepthook(args)

    threading.excepthook = threading_hook

    _previous_unraisablehook = sys.unraisablehook

    def unraisable_hook(args):
        _write(
            "python.unraisable",
            durable=True,
            object=repr(getattr(args, "object", None)),
            traceback=_format_exception(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
            ),
        )
        _promote_current()
        if _previous_unraisablehook is not None:
            _previous_unraisablehook(args)

    sys.unraisablehook = unraisable_hook


def _install_qt_hook() -> None:
    global _qt_handler, _previous_qt_handler
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception as exc:
        _write("crash_journal.qt_hook_unavailable", error=repr(exc))
        return

    names = {
        QtMsgType.QtDebugMsg: "debug",
        QtMsgType.QtInfoMsg: "info",
        QtMsgType.QtWarningMsg: "warning",
        QtMsgType.QtCriticalMsg: "critical",
        QtMsgType.QtFatalMsg: "fatal",
    }

    def handler(message_type, context, message):
        level = names.get(message_type, str(message_type))
        fatal = message_type == QtMsgType.QtFatalMsg
        _write(
            f"qt.{level}",
            durable=fatal,
            message=message,
            category=getattr(context, "category", None),
            function=getattr(context, "function", None),
            file=getattr(context, "file", None),
            line=getattr(context, "line", None),
        )
        if fatal:
            _promote_current()
        previous = _previous_qt_handler
        if callable(previous):
            previous(message_type, context, message)

    _qt_handler = handler
    _previous_qt_handler = qInstallMessageHandler(handler)


def _promote_current() -> Path | None:
    stream = _pending_stream
    path = _pending_path
    if stream is None or path is None:
        return None
    try:
        with _LOCK:
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        pass
    # Windows does not reliably allow renaming a file while faulthandler holds
    # its descriptor. Copy the already-flushed fatal record instead; the stale
    # pending journal is dealt with on the next launch.
    try:
        directory = _logs_directory()
        directory.mkdir(parents=True, exist_ok=True)
        destination = _unique_crash_path(directory)
        shutil.copyfile(path, destination)
        _prune_crash_logs(directory)
        _write("session.promoted", destination=destination)
        return destination
    except OSError:
        return None


def install_crash_journal() -> Path | None:
    """Install crash hooks before QApplication and any worker are constructed."""
    global _installed, _pending_path, _pending_stream
    if _installed:
        return _pending_path
    _installed = True

    try:
        directory = _pending_directory()
        directory.mkdir(parents=True, exist_ok=True)
        pending = _new_pending_path(directory)
        for previous in directory.glob(_pending_pattern()):
            if previous != pending:
                _recover_previous_session(previous)
        _pending_stream = pending.open("w", encoding="utf-8", buffering=1)
        _pending_path = pending
    except OSError:
        return None

    _write(
        _SESSION_STARTED,
        executable=sys.executable,
        frozen=bool(getattr(sys, "frozen", False)),
    )
    try:
        faulthandler.enable(_pending_stream, all_threads=True)
    except Exception as exc:
        _write("crash_journal.faulthandler_unavailable", error=repr(exc))
    _install_python_hooks()
    _install_qt_hook()
    return _pending_path


def mark_clean_exit() -> None:
    """Remove the pending journal after the Qt event loop returns normally."""
    global _pending_stream, _pending_path
    stream = _pending_stream
    path = _pending_path
    if stream is None or path is None:
        return
    _write(_SESSION_CLEAN, durable=True)
    try:
        faulthandler.disable()
    except Exception:
        pass
    try:
        stream.close()
    except OSError:
        pass
    _pending_stream = None
    _pending_path = None
    try:
        path.unlink()
    except OSError:
        pass
