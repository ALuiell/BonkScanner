"""Read-only integrity checks. Unknown tokens do not prove a permission problem."""
from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ProcessPrivileges:
    integrity: int | None = None
    ui_access: bool | None = None


def inspect_privileges(pid: int | None) -> ProcessPrivileges:
    if os.name != "nt" or not pid or pid <= 0:
        return ProcessPrivileges()
    process_handle = token = None
    try:
        import win32api
        import win32con
        import win32security

        process_handle = win32api.OpenProcess(0x1000, False, pid)
        token = win32security.OpenProcessToken(process_handle, win32con.TOKEN_QUERY)
        sid = win32security.GetTokenInformation(token, win32security.TokenIntegrityLevel)
        if isinstance(sid, tuple):
            sid = sid[0]
        return ProcessPrivileges(
            integrity=int(sid.GetSubAuthority(sid.GetSubAuthorityCount() - 1)),
            ui_access=bool(win32security.GetTokenInformation(token, win32security.TokenUIAccess)),
        )
    except Exception:
        return ProcessPrivileges()
    finally:
        for handle in (token, process_handle):
            if handle is not None:
                try:
                    handle.Close()
                except Exception:
                    pass


def privilege_relation(source: ProcessPrivileges, target: ProcessPrivileges) -> str:
    if source.integrity is None or target.integrity is None or source.ui_access is None:
        return "unknown"
    if source.ui_access or source.integrity >= target.integrity:
        return "no_mismatch"
    return "mismatch"
