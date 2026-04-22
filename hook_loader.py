from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class HookLoadError(Exception):
    """Raised when the native hook cannot be injected or initialized."""


class HookProcessNotFoundError(HookLoadError):
    """Raised when the target game process is not running."""


@dataclass(frozen=True)
class HookLoadResult:
    pid: int
    dll_path: Path
    initialized: bool
    skipped: bool = False


class NativeHookLoader:
    DEFAULT_RELATIVE_DLL = Path(
        "native",
        "BonkHook",
        "bin",
        "Release",
        "net8.0",
        "win-x64",
        "publish",
        "BonkHook.dll",
    )

    PROCESS_CREATE_THREAD = 0x0002
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_VM_OPERATION = 0x0008
    PROCESS_VM_WRITE = 0x0020
    PROCESS_VM_READ = 0x0010
    PROCESS_ALL_FOR_INJECTION = (
        PROCESS_CREATE_THREAD
        | PROCESS_QUERY_INFORMATION
        | PROCESS_VM_OPERATION
        | PROCESS_VM_WRITE
        | PROCESS_VM_READ
    )

    MEM_COMMIT = 0x1000
    MEM_RESERVE = 0x2000
    MEM_RELEASE = 0x8000
    PAGE_READWRITE = 0x04
    INFINITE = 0xFFFFFFFF
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    LIST_MODULES_ALL = 0x03
    MAX_PATH = 260

    def __init__(
        self,
        process_name: str,
        *,
        dll_path: str | os.PathLike[str] | None = None,
        base_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.process_name = process_name
        self.dll_path = self.resolve_dll_path(dll_path=dll_path, base_path=base_path)
        self._injected_pids: set[int] = set()
        self._operation_lock = threading.RLock()
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self._configure_api()

    @classmethod
    def resolve_dll_path(
        cls,
        *,
        dll_path: str | os.PathLike[str] | None = None,
        base_path: str | os.PathLike[str] | None = None,
    ) -> Path:
        if dll_path:
            return Path(dll_path).expanduser().resolve()

        root = Path(base_path) if base_path else Path(getattr(sys, "_MEIPASS", Path.cwd()))
        return (root / cls.DEFAULT_RELATIVE_DLL).resolve()

    def inject_once(self) -> HookLoadResult:
        with self._operation_lock:
            if not self.dll_path.exists():
                raise HookLoadError(f"Native hook DLL was not found: {self.dll_path}")

            pid = self._find_process_id()
            if pid is None:
                raise HookProcessNotFoundError(f"Waiting for process '{self.process_name}'.")

            if pid in self._injected_pids:
                return HookLoadResult(pid=pid, dll_path=self.dll_path, initialized=True, skipped=True)

            self._inject_into_pid(pid)
            self._injected_pids.add(pid)
            return HookLoadResult(pid=pid, dll_path=self.dll_path, initialized=True)

    def request_restart_run(self) -> HookLoadResult:
        with self._operation_lock:
            result = self.inject_once()
            exit_code = self._invoke_export_in_pid(result.pid, b"RequestRestartRun", 0)
            if exit_code != 0:
                raise HookLoadError(f"BonkHook RequestRestartRun failed with status {exit_code}.")
            return result

    def wait_for_snapshot_ready(self, *, timeout: float = 10.0, poll_interval: float = 0.05) -> bool:
        with self._operation_lock:
            result = self.inject_once()
            timeout_seconds = max(0.0, min(float(timeout), 60.0))
            poll_seconds = max(0.0, float(poll_interval))
            deadline = time.monotonic() + timeout_seconds

            while True:
                exit_code = self._invoke_export_in_pid(result.pid, b"WaitForSnapshotReady", 0)
                if exit_code == 1:
                    return True
                if exit_code != 0:
                    raise HookLoadError(f"BonkHook WaitForSnapshotReady failed with status {exit_code}.")

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False

                time.sleep(min(poll_seconds, remaining))

    def uninitialize(self) -> HookLoadResult:
        with self._operation_lock:
            pid = self._find_process_id()
            if pid is None:
                raise HookProcessNotFoundError(f"Waiting for process '{self.process_name}'.")

            exit_code = self._invoke_export_in_pid(pid, b"Uninitialize", 0)
            if exit_code != 0:
                raise HookLoadError(f"BonkHook Uninitialize failed with status {exit_code}.")

            self._injected_pids.discard(pid)
            return HookLoadResult(pid=pid, dll_path=self.dll_path, initialized=False)

    def try_inject_once(
        self,
        log: Callable[[str], None] | None = None,
    ) -> HookLoadResult | None:
        try:
            return self.inject_once()
        except HookLoadError as exc:
            if log is not None:
                log(str(exc))
            return None

    def _inject_into_pid(self, pid: int) -> None:
        process = self._open_process(pid)
        try:
            self._remote_load_library(process, self.dll_path)
            remote_module = self._find_remote_module_base(process, self.dll_path.name)
            if remote_module is None:
                raise HookLoadError(f"Injected DLL was not found in process modules: {self.dll_path.name}")

            local_module = self._kernel32.LoadLibraryW(str(self.dll_path))
            if not local_module:
                raise self._last_error("LoadLibraryW(local hook DLL) failed")

            initialize = self._kernel32.GetProcAddress(local_module, b"Initialize")
            if not initialize:
                raise self._last_error("GetProcAddress(Initialize) failed")

            initialize_offset = initialize - local_module
            remote_initialize = remote_module + initialize_offset
            exit_code = self._create_remote_thread(process, remote_initialize, 0)
            if exit_code != 0:
                raise HookLoadError(f"BonkHook Initialize failed with status {exit_code}.")
        finally:
            self._kernel32.CloseHandle(process)

    def _invoke_export_in_pid(self, pid: int, export_name: bytes, parameter: int) -> int:
        process = self._open_process(pid)
        try:
            remote_module = self._find_remote_module_base(process, self.dll_path.name)
            if remote_module is None:
                raise HookLoadError(f"Injected DLL was not found in process modules: {self.dll_path.name}")

            local_module = self._kernel32.LoadLibraryW(str(self.dll_path))
            if not local_module:
                raise self._last_error("LoadLibraryW(local hook DLL) failed")

            export = self._kernel32.GetProcAddress(local_module, export_name)
            if not export:
                export_text = export_name.decode("ascii", errors="replace")
                raise self._last_error(f"GetProcAddress({export_text}) failed")

            export_offset = export - local_module
            remote_export = remote_module + export_offset
            return self._create_remote_thread(process, remote_export, parameter)
        finally:
            self._kernel32.CloseHandle(process)

    def _remote_load_library(self, process: int, dll_path: Path) -> None:
        data = (str(dll_path) + "\0").encode("utf-16-le")
        remote_buffer = self._kernel32.VirtualAllocEx(
            process,
            None,
            len(data),
            self.MEM_RESERVE | self.MEM_COMMIT,
            self.PAGE_READWRITE,
        )
        if not remote_buffer:
            raise self._last_error("VirtualAllocEx failed")

        try:
            written = ctypes.c_size_t()
            buffer = ctypes.create_string_buffer(data)
            ok = self._kernel32.WriteProcessMemory(
                process,
                remote_buffer,
                ctypes.byref(buffer),
                len(data),
                ctypes.byref(written),
            )
            if not ok or written.value != len(data):
                raise self._last_error("WriteProcessMemory failed")

            load_library = self._kernel32.GetProcAddress(
                self._kernel32.GetModuleHandleW("kernel32.dll"),
                b"LoadLibraryW",
            )
            if not load_library:
                raise self._last_error("GetProcAddress(LoadLibraryW) failed")

            self._create_remote_thread(process, load_library, remote_buffer)
        finally:
            self._kernel32.VirtualFreeEx(process, remote_buffer, 0, self.MEM_RELEASE)

    def _create_remote_thread(self, process: int, start_address: int, parameter: int) -> int:
        thread = self._kernel32.CreateRemoteThread(
            process,
            None,
            0,
            start_address,
            parameter,
            0,
            None,
        )
        if not thread:
            raise self._last_error("CreateRemoteThread failed")

        try:
            wait_result = self._kernel32.WaitForSingleObject(thread, self.INFINITE)
            if wait_result != 0:
                raise self._last_error("WaitForSingleObject failed")

            exit_code = ctypes.c_ulong()
            if not self._kernel32.GetExitCodeThread(thread, ctypes.byref(exit_code)):
                raise self._last_error("GetExitCodeThread failed")

            return int(exit_code.value)
        finally:
            self._kernel32.CloseHandle(thread)

    def _open_process(self, pid: int) -> int:
        process = self._kernel32.OpenProcess(self.PROCESS_ALL_FOR_INJECTION, False, pid)
        if not process:
            raise self._last_error(f"OpenProcess({pid}) failed")
        return process

    def _find_process_id(self) -> int | None:
        snapshot = self._kernel32.CreateToolhelp32Snapshot(self.TH32CS_SNAPPROCESS, 0)
        if snapshot == self.INVALID_HANDLE_VALUE:
            raise self._last_error("CreateToolhelp32Snapshot failed")

        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if not self._kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return None

            process_name = self.process_name.casefold()
            while True:
                if entry.szExeFile.casefold() == process_name:
                    return int(entry.th32ProcessID)

                if not self._kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    return None
        finally:
            self._kernel32.CloseHandle(snapshot)

    def _find_remote_module_base(self, process: int, module_name: str) -> int | None:
        needed = ctypes.c_ulong()
        modules = (ctypes.c_void_p * 1024)()
        if not self._psapi.EnumProcessModulesEx(
            process,
            modules,
            ctypes.sizeof(modules),
            ctypes.byref(needed),
            self.LIST_MODULES_ALL,
        ):
            raise self._last_error("EnumProcessModulesEx failed")

        count = min(needed.value // ctypes.sizeof(ctypes.c_void_p), len(modules))
        expected_name = module_name.casefold()
        for index in range(count):
            module = modules[index]
            if not module:
                continue

            buffer = ctypes.create_unicode_buffer(self.MAX_PATH)
            length = self._psapi.GetModuleFileNameExW(
                process,
                module,
                buffer,
                self.MAX_PATH,
            )
            if length == 0:
                continue

            if Path(buffer.value).name.casefold() == expected_name:
                return int(module)

        return None

    def _configure_api(self) -> None:
        self._kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
        self._kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        self._kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        self._kernel32.Process32FirstW.restype = ctypes.c_bool
        self._kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
        self._kernel32.Process32NextW.restype = ctypes.c_bool
        self._kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        self._kernel32.OpenProcess.restype = ctypes.c_void_p
        self._kernel32.VirtualAllocEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        self._kernel32.VirtualAllocEx.restype = ctypes.c_void_p
        self._kernel32.VirtualFreeEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_ulong,
        ]
        self._kernel32.VirtualFreeEx.restype = ctypes.c_bool
        self._kernel32.WriteProcessMemory.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._kernel32.WriteProcessMemory.restype = ctypes.c_bool
        self._kernel32.CreateRemoteThread.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        self._kernel32.CreateRemoteThread.restype = ctypes.c_void_p
        self._kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self._kernel32.WaitForSingleObject.restype = ctypes.c_ulong
        self._kernel32.GetExitCodeThread.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        self._kernel32.GetExitCodeThread.restype = ctypes.c_bool
        self._kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        self._kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        self._kernel32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
        self._kernel32.LoadLibraryW.restype = ctypes.c_void_p
        self._kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self._kernel32.GetProcAddress.restype = ctypes.c_void_p
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle.restype = ctypes.c_bool
        self._psapi.EnumProcessModulesEx.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_ulong,
        ]
        self._psapi.EnumProcessModulesEx.restype = ctypes.c_bool
        self._psapi.GetModuleFileNameExW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_ulong,
        ]
        self._psapi.GetModuleFileNameExW.restype = ctypes.c_ulong

    @staticmethod
    def _last_error(message: str) -> HookLoadError:
        error = ctypes.get_last_error()
        return HookLoadError(f"{message}. Win32 error: {error}")


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]
