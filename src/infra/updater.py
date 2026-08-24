from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse
import uuid

from core.update_types import PreparedUpdate, ProgressCallback, ReleaseInfo

# `requests` is deliberately imported inside the functions that use it. It is
# one of the heaviest imports in the application and neither checking GitHub nor
# downloading a release belongs on the first-window path.


GITHUB_REPO = "ALuiell/BonkScanner"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
EXPECTED_ASSET_NAME = "BonkScanner.exe"
MAX_UPDATE_BYTES = 250 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
INSTALLER_WAIT_ATTEMPTS = 120
INSTALLER_MOVE_ATTEMPTS = 30
UPDATE_RESULT_NAME = ".bonkscanner-update-result.txt"
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){2}$")
_SHA256_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")
_TRUSTED_REDIRECT_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
_REQUEST_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "BonkScanner-Updater",
}

#: The supporters list changes independently of application releases.
SUPPORTERS_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/supporters.json"
)
SUPPORTERS_KEY = "supporters"


class UpdateError(RuntimeError):
    """A safe, user-presentable updater failure."""


def frozen_exe_path() -> str | None:
    if getattr(sys, "frozen", False):
        return sys.executable
    return None


def _release_version(tag_name: object) -> str:
    if not isinstance(tag_name, str):
        raise UpdateError("The latest GitHub release has no valid version tag.")
    version = tag_name.strip()
    if version[:1].lower() == "v":
        version = version[1:]
    if not _VERSION_RE.fullmatch(version):
        raise UpdateError(f"Unsupported release version: {tag_name!r}.")
    return version


def _sha256_from_digest(value: object) -> str:
    if not isinstance(value, str):
        raise UpdateError("The release asset has no SHA-256 digest.")
    match = _SHA256_RE.fullmatch(value.strip())
    if match is None:
        raise UpdateError("The release asset has an invalid SHA-256 digest.")
    return match.group(1).lower()


def _validate_asset_url(url: object, *, redirected: bool = False) -> str:
    if not isinstance(url, str) or not url:
        raise UpdateError("The release asset has no download URL.")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https":
        raise UpdateError("The update URL is not HTTPS.")
    if redirected:
        if host not in _TRUSTED_REDIRECT_HOSTS:
            raise UpdateError(
                f"The update redirected to an untrusted host: {host or 'unknown'}."
            )
        return url

    expected_prefix = f"/{GITHUB_REPO}/releases/download/".casefold()
    if host != "github.com" or not parsed.path.casefold().startswith(expected_prefix):
        raise UpdateError("The release asset URL does not belong to BonkScanner on GitHub.")
    return url


def _asset_size(value: object) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise UpdateError("The release asset has no valid size.") from exc
    if size <= 0:
        raise UpdateError("The release asset is empty.")
    if size > MAX_UPDATE_BYTES:
        raise UpdateError("The release asset is unexpectedly large.")
    return size


def fetch_latest_release() -> ReleaseInfo:
    import requests

    response = requests.get(
        GITHUB_API_URL,
        headers=_REQUEST_HEADERS,
        timeout=(5, 10),
    )
    response.raise_for_status()
    release_data = response.json()
    if not isinstance(release_data, dict):
        raise UpdateError("GitHub returned an invalid release response.")

    matching_assets = [
        asset
        for asset in release_data.get("assets", ())
        if isinstance(asset, dict) and asset.get("name") == EXPECTED_ASSET_NAME
    ]
    if len(matching_assets) != 1:
        raise UpdateError(
            f"The release must contain exactly one {EXPECTED_ASSET_NAME} asset."
        )
    asset = matching_assets[0]

    notes = release_data.get("body")
    if not isinstance(notes, str) or not notes.strip():
        notes = "No release notes provided."

    return ReleaseInfo(
        version=_release_version(release_data.get("tag_name")),
        notes=notes,
        exe_download_url=_validate_asset_url(asset.get("browser_download_url")),
        exe_size=_asset_size(asset.get("size")),
        exe_digest=_sha256_from_digest(asset.get("digest")),
    )


def clean_supporters(payload) -> list:
    """Keep only the entries the support popup knows how to draw."""
    if isinstance(payload, dict):
        payload = payload.get(SUPPORTERS_KEY)
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, (str, dict))]


def fetch_supporters() -> list:
    import requests

    response = requests.get(SUPPORTERS_URL, timeout=5)
    response.raise_for_status()
    return clean_supporters(response.json())


def _safe_executable_name(exe_path: str) -> str:
    name = Path(exe_path).name
    if not _SAFE_FILENAME_RE.fullmatch(name) or not name.lower().endswith(".exe"):
        raise UpdateError(
            "The running executable has an unsafe filename. "
            "Rename it to BonkScanner.exe and try again."
        )
    return name


def _installer_script(
    *,
    exe_name: str,
    new_exe_name: str,
    backup_exe_name: str,
    parent_pid: int,
    version: str,
) -> str:
    """Build a bounded same-directory replacement with a one-step rollback."""
    return f"""@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 > nul
cd /d "%~dp0"
set "TARGET={exe_name}"
set "NEW={new_exe_name}"
set "BACKUP={backup_exe_name}"
set "RESULT={UPDATE_RESULT_NAME}"
set /a ATTEMPTS=0
if exist "%RESULT%" del /f /q "%RESULT%" >nul 2>&1

:wait_loop
tasklist /FI "PID eq {parent_pid}" /NH 2>nul | findstr /R /C:"[ ]{parent_pid}[ ]" >nul
if errorlevel 1 goto replace
set /a ATTEMPTS+=1
if %ATTEMPTS% GEQ {INSTALLER_WAIT_ATTEMPTS} goto timed_out
ping 127.0.0.1 -n 2 >nul
goto wait_loop

:replace
if not exist "%NEW%" goto install_failed
if exist "%BACKUP%" del /f /q "%BACKUP%" >nul 2>&1

REM PyInstaller's outer one-file launcher can keep TARGET locked briefly after
REM the GUI PID exits. Retry the filesystem hand-off instead of treating that
REM normal shutdown race as a failed update.
set /a MOVE_ATTEMPTS=0
:move_old
if not exist "%TARGET%" goto move_new
move /y "%TARGET%" "%BACKUP%" >nul 2>&1
if not errorlevel 1 goto move_new
set /a MOVE_ATTEMPTS+=1
if %MOVE_ATTEMPTS% GEQ {INSTALLER_MOVE_ATTEMPTS} goto install_failed
ping 127.0.0.1 -n 2 >nul
goto move_old

:move_new
set /a MOVE_ATTEMPTS=0
:move_new_loop
move /y "%NEW%" "%TARGET%" >nul 2>&1
if not errorlevel 1 goto install_succeeded
set /a MOVE_ATTEMPTS+=1
if %MOVE_ATTEMPTS% GEQ {INSTALLER_MOVE_ATTEMPTS} goto restore_old
ping 127.0.0.1 -n 2 >nul
goto move_new_loop

:install_succeeded
if not exist "%TARGET%" goto restore_old
> "%RESULT%" echo SUCCESS {version}
start "" "%TARGET%"
if errorlevel 1 goto restore_old
if exist "%BACKUP%" del /f /q "%BACKUP%" >nul 2>&1
(goto) 2>nul & del /f /q "%~f0"

:restore_old
if exist "%TARGET%" del /f /q "%TARGET%" >nul 2>&1
if exist "%BACKUP%" move /y "%BACKUP%" "%TARGET%" >nul 2>&1
> "%RESULT%" echo ERROR The update could not be installed. The previous version was restored.
if exist "%TARGET%" start "" "%TARGET%"
if exist "%NEW%" del /f /q "%NEW%" >nul 2>&1
(goto) 2>nul & del /f /q "%~f0"

:install_failed
if exist "%BACKUP%" if not exist "%TARGET%" move /y "%BACKUP%" "%TARGET%" >nul 2>&1
> "%RESULT%" echo ERROR The update could not replace the application. The previous version was kept.
if exist "%TARGET%" start "" "%TARGET%"
if exist "%NEW%" del /f /q "%NEW%" >nul 2>&1
(goto) 2>nul & del /f /q "%~f0"

:timed_out
> "%RESULT%" echo ERROR The updater timed out while waiting for BonkScanner to close.
if exist "%NEW%" del /f /q "%NEW%" >nul 2>&1
(goto) 2>nul & del /f /q "%~f0"
"""


def prepare_update(
    exe_path: str,
    release: ReleaseInfo,
    *,
    progress: ProgressCallback | None = None,
) -> PreparedUpdate:
    """Download and verify an update without closing or replacing the app."""
    import requests

    target = Path(exe_path).resolve()
    exe_name = _safe_executable_name(str(target))
    if not target.is_file():
        raise UpdateError("The running BonkScanner executable could not be found.")

    expected_size = _asset_size(release.exe_size)
    expected_digest = _sha256_from_digest(f"sha256:{release.exe_digest}")
    download_url = _validate_asset_url(release.exe_download_url)
    token = f"{os.getpid()}-{uuid.uuid4().hex[:10]}"
    new_path = target.with_name(f".{target.stem}-{token}.new.exe")
    installer_path = target.with_name(f".bonkscanner-update-{token}.bat")
    backup_name = f".{target.stem}-{token}.old.exe"

    downloaded_size = 0
    digest = hashlib.sha256()
    last_percentage = -1
    try:
        response = requests.get(
            download_url,
            headers=_REQUEST_HEADERS,
            stream=True,
            timeout=(10, 30),
        )
        response.raise_for_status()
        _validate_asset_url(getattr(response, "url", download_url), redirected=True)

        content_length = response.headers.get("content-length")
        if content_length not in (None, ""):
            try:
                response_size = int(content_length)
            except ValueError as exc:
                raise UpdateError("The update server returned an invalid file size.") from exc
            if response_size != expected_size:
                raise UpdateError("The downloaded update size does not match the GitHub release.")

        if progress is not None:
            progress(0, expected_size)
        with new_path.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                downloaded_size += len(chunk)
                if downloaded_size > expected_size or downloaded_size > MAX_UPDATE_BYTES:
                    raise UpdateError("The downloaded update is larger than expected.")
                digest.update(chunk)
                stream.write(chunk)
                percentage = int(downloaded_size * 100 / expected_size)
                if progress is not None and percentage != last_percentage:
                    progress(downloaded_size, expected_size)
                    last_percentage = percentage
            stream.flush()
            os.fsync(stream.fileno())

        if downloaded_size != expected_size:
            raise UpdateError("The downloaded update is incomplete.")
        actual_digest = digest.hexdigest().lower()
        if actual_digest != expected_digest:
            raise UpdateError("The downloaded update failed SHA-256 verification.")

        installer_path.write_text(
            _installer_script(
                exe_name=exe_name,
                new_exe_name=new_path.name,
                backup_exe_name=backup_name,
                parent_pid=os.getpid(),
                version=release.version,
            ),
            encoding="utf-8",
            newline="\r\n",
        )
        if progress is not None:
            progress(expected_size, expected_size)
        return PreparedUpdate(
            version=release.version,
            exe_path=str(target),
            new_exe_path=str(new_path),
            installer_path=str(installer_path),
            downloaded_size=downloaded_size,
            sha256=actual_digest,
        )
    except Exception:
        for path in (new_path, installer_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _clean_subprocess_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("_MEI") or key.startswith("_PYI"):
            env.pop(key, None)
    env.pop("TCL_LIBRARY", None)
    env.pop("TK_LIBRARY", None)
    env.pop("_PYVENV_LAUNCHER_", None)
    if "PATH" in env:
        paths = env["PATH"].split(os.pathsep)
        env["PATH"] = os.pathsep.join(
            path for path in paths if "_MEI" not in path.upper()
        )
    return env


def consume_update_result(exe_path: str | None = None) -> tuple[str, str] | None:
    """Return and remove the previous helper's one-line result, if present."""
    target = exe_path or frozen_exe_path()
    if not target:
        return None
    result_path = Path(target).resolve().with_name(UPDATE_RESULT_NAME)
    try:
        text = result_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    try:
        result_path.unlink()
    except OSError:
        pass
    if text.startswith("SUCCESS "):
        return "success", text.removeprefix("SUCCESS ").strip()
    if text.startswith("ERROR "):
        return "error", text.removeprefix("ERROR ").strip()
    return "error", "The updater returned an unknown result."


def launch_prepared_update(prepared: PreparedUpdate) -> subprocess.Popen:
    """Start the waiting helper; the GUI remains responsible for clean exit."""
    installer = Path(prepared.installer_path)
    new_exe = Path(prepared.new_exe_path)
    if not installer.is_file() or not new_exe.is_file():
        raise UpdateError("The prepared update files are missing.")

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    try:
        return subprocess.Popen(
            ["cmd.exe", "/d", "/c", str(installer)],
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=_clean_subprocess_environment(),
            startupinfo=startupinfo,
            close_fds=True,
        )
    except Exception as exc:
        raise UpdateError(f"Could not start the update installer: {exc}") from exc
