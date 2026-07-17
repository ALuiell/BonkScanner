from __future__ import annotations

import threading
from typing import Callable

from app import config
from app.version import CURRENT_VERSION, parse_version
from infra import updater
from infra.updater import ReleaseInfo

ConfirmCallback = Callable[[str, str], "bool | None"]
LogCallback = Callable[..., None]
ScheduleCallback = Callable[[Callable[[], None]], None]


def check_and_update(
    *,
    confirm: ConfirmCallback,
    log: LogCallback | None = None,
    schedule: ScheduleCallback | None = None,
    force_check: bool = False,
) -> None:
    exe_path = updater.frozen_exe_path()
    if exe_path is None:
        print("Running from source code. Auto-update disabled.")
        return

    try:
        release = updater.fetch_latest_release()

        if not force_check and config.SKIPPED_UPDATE_VERSION == release.version:
            print(f"Update to {release.version} was skipped by user.")
            return

        if parse_version(release.version) > parse_version(CURRENT_VERSION):
            if release.exe_download_url:
                def prompt_user() -> None:
                    _prompt_and_apply(exe_path, release, confirm, log)

                if schedule is not None:
                    schedule(prompt_user)
                else:
                    prompt_user()
            else:
                print("Error: No .exe file found in the GitHub release.")
        else:
            if force_check and log is not None:
                log(f"[*] You already have the latest version (v{CURRENT_VERSION}).", tag="success")
            print("You have the latest version installed.")
    except Exception as e:
        print(f"Failed to check for updates: {e}")


def _prompt_and_apply(
    exe_path: str,
    release: ReleaseInfo,
    confirm: ConfirmCallback,
    log: LogCallback | None,
) -> None:
    accepted = confirm(release.version, release.notes)
    if accepted is True:
        # The download only goes to a thread when there is a log to report it
        # through; without one the caller gets the blocking download instead.
        if log is not None:
            log(f"[*] Downloading update v{release.version}... Please wait.", tag="warning")
            threading.Thread(
                target=updater.download_and_apply_update,
                args=(exe_path, release.exe_download_url),
                daemon=True,
            ).start()
        else:
            updater.download_and_apply_update(exe_path, release.exe_download_url)
    elif accepted is False:
        config.SKIPPED_UPDATE_VERSION = release.version
        config.user_config["SKIPPED_UPDATE_VERSION"] = release.version
        config.save_config(config.user_config)
        if log is not None:
            log(
                f"[*] Update to v{release.version} skipped. You can update manually in settings.",
                tag="warning",
            )
