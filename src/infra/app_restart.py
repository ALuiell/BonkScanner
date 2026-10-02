"""Restart only after shutdown, and wait before touching the old profile."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


_WAIT_FLAG = "--bonkscanner-restart-after="


def launch_restart() -> None:
    pids = [os.getpid()]
    frozen = bool(getattr(sys, "frozen", False))
    # One-file builds have a launcher which outlives the Python process.
    if frozen and os.environ.get("_PYI_PARENT_PROCESS_LEVEL") == "1":
        pids.append(os.getppid())
    command = [sys.executable]
    if not frozen:
        command.append(str(Path(__file__).resolve().parents[1] / "main.py"))
    command.extend(arg for arg in sys.argv[1:] if not arg.startswith(_WAIT_FLAG))
    command.append(_WAIT_FLAG + ",".join(map(str, pids)))
    environment = os.environ.copy()
    # The old one-file launcher removes its extraction directory on exit.
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(command, env=environment, close_fds=True)


def wait_for_previous_instance() -> None:
    arguments = [arg for arg in sys.argv[1:] if arg.startswith(_WAIT_FLAG)]
    if not arguments:
        return
    if os.name != "nt":
        raise OSError("Automatic restart is supported only on Windows.")
    for argument in arguments:
        try:
            pids = [int(value) for value in argument[len(_WAIT_FLAG):].split(",")]
        except ValueError as exc:
            raise OSError("Invalid restart process ID.") from exc
        for pid in pids:
            if pid <= 0 or pid == os.getpid():
                raise OSError("Invalid restart process ID.")
            _wait_for_process(pid)
        sys.argv.remove(argument)


def _wait_for_process(pid: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # The previous process has already exited.
            return
        raise ctypes.WinError(error)
    try:
        if kernel32.WaitForSingleObject(handle, 60_000) != 0:
            raise OSError("The previous BonkScanner process did not exit. Start BonkScanner again after closing it.")
    finally:
        kernel32.CloseHandle(handle)
