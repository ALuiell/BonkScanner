"""Values shared by the updater's infrastructure, application and UI layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    notes: str
    exe_download_url: str
    exe_size: int
    exe_digest: str


@dataclass(frozen=True)
class PreparedUpdate:
    """A verified executable and the helper that will install it after exit."""

    version: str
    exe_path: str
    new_exe_path: str
    installer_path: str
    downloaded_size: int
    sha256: str


ProgressCallback = Callable[[int, int], None]
