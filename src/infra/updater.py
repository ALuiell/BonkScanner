from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass

# `requests` is imported inside the two functions that call it, not here.
# It is the heaviest thing this application imports -- 14.7 MB and 346ms,
# measured -- and it exists for one HTTP call that happens after the window is
# up, if it happens at all. At module scope it was on the startup path through
# `ui.dialogs.update_prompt` -> `app.update_flow` -> here.


GITHUB_REPO = "ALuiell/BonkScanner"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    notes: str
    exe_download_url: str | None


def frozen_exe_path() -> str | None:
    if getattr(sys, "frozen", False):
        return sys.executable
    return None


def fetch_latest_release() -> ReleaseInfo:
    import requests

    response = requests.get(GITHUB_API_URL, timeout=5)
    response.raise_for_status()
    release_data = response.json()

    exe_download_url = None
    for asset in release_data.get("assets", []):
        if asset["name"].endswith(".exe"):
            exe_download_url = asset["browser_download_url"]
            break

    return ReleaseInfo(
        version=release_data.get("tag_name", "").lstrip("v"),
        notes=release_data.get("body", "No release notes provided."),
        exe_download_url=exe_download_url,
    )


def download_and_apply_update(exe_path, download_url):
    new_exe_path = exe_path + ".new"
    exe_dir = os.path.dirname(exe_path)
    exe_name = os.path.basename(exe_path)
    new_exe_name = exe_name + ".new"
    backup_exe_name = exe_name + ".old"
    bat_path = os.path.join(exe_dir, "update.bat")

    import requests

    try:
        r = requests.get(download_url, stream=True, timeout=10)
        r.raise_for_status()
        expected_size = int(r.headers.get("content-length", "0") or "0")
        downloaded_size = 0
        with open(new_exe_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                downloaded_size += len(chunk)
                f.write(chunk)
        if downloaded_size == 0 or (expected_size and downloaded_size != expected_size):
            raise RuntimeError("Downloaded update is empty or incomplete.")
    except Exception as e:
        print(f"Error downloading update: {e}")
        if os.path.exists(new_exe_path):
            os.remove(new_exe_path)
        return

    bat_content = f"""@echo off
chcp 65001 > nul
cd /d "%~dp0"

:wait_loop
ping 127.0.0.1 -n 2 > nul
if exist "{backup_exe_name}" del "{backup_exe_name}" > nul 2>&1
ren "{exe_name}" "{backup_exe_name}" > nul 2>&1
if errorlevel 1 goto wait_loop

move /y "{new_exe_name}" "{exe_name}" > nul 2>&1
if errorlevel 1 goto restore_old
if not exist "{exe_name}" goto restore_old

del "{backup_exe_name}" > nul 2>&1
start "" "{exe_name}"
(goto) 2>nul & del "%~f0"

:restore_old
if not exist "{exe_name}" if exist "{backup_exe_name}" ren "{backup_exe_name}" "{exe_name}" > nul 2>&1
start "" "{exe_name}"
(goto) 2>nul & del "%~f0"
"""
    with open(bat_path, "w", encoding="utf-8") as bat_file:
        bat_file.write(bat_content)

    print("Update downloaded. The program will be restarted...")

    env = os.environ.copy()
    keys_to_remove = [key for key in env.keys() if key.startswith("_MEI") or key.startswith("_PYI")]
    for key in keys_to_remove:
        env.pop(key, None)

    env.pop("TCL_LIBRARY", None)
    env.pop("TK_LIBRARY", None)
    env.pop("_PYVENV_LAUNCHER_", None)

    if "PATH" in env:
        paths = env["PATH"].split(os.pathsep)
        env["PATH"] = os.pathsep.join(path for path in paths if "_MEI" not in path.upper())

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE

    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=env,
        startupinfo=startupinfo,
        close_fds=True,
    )

    os._exit(0)
