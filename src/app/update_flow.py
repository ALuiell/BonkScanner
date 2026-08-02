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
#: ``("current" | "available", version)``. See `check_and_update`.
ReportCallback = Callable[[str, str], None]


def check_and_update(
    *,
    confirm: ConfirmCallback,
    log: LogCallback | None = None,
    schedule: ScheduleCallback | None = None,
    report: ReportCallback | None = None,
    force_check: bool = False,
) -> None:
    """Compare against the latest release, and offer the update if there is one.

    ``report`` is what this answered to nobody until now: every outcome below
    went to ``print`` and, on one branch, to the log. A caller that wants to
    *show* the result -- the footer strip does -- had no way to learn it. It is
    called with the same answer on both of the two branches that reached the
    network, and **not at all** on the paths that never compared anything: a
    source run, a skipped version, or a failed request. That silence is the
    point. "We don't know" and "you are up to date" are different facts, and a
    strip that says the second when it means the first is lying about a version
    check that never happened.

    It runs on whatever thread this does -- a daemon one, from
    ``start_update_check`` -- so a caller touching widgets must hop threads
    itself. ``ui/dialogs/update_prompt.py`` routes it through ``schedule`` for
    exactly that reason.
    """
    exe_path = updater.frozen_exe_path()
    if exe_path is None:
        if report is not None:
            report("unavailable", "")
        print("Running from source code. Auto-update disabled.")
        return

    try:
        release = updater.fetch_latest_release()

        if not force_check and config.SKIPPED_UPDATE_VERSION == release.version:
            # Reported, not swallowed. Skipping a version silences the *modal*;
            # it was never meant to mean "and never mention it again", and with
            # a status line on screen that distinction finally has somewhere to
            # show. Without this the footer sits on "Check for updates" forever
            # for anyone who ever pressed Skip.
            if report is not None:
                report("available", release.version)
            print(f"Update to {release.version} was skipped by user.")
            return

        if parse_version(release.version) > parse_version(CURRENT_VERSION):
            if report is not None:
                report("available", release.version)
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
            if report is not None:
                report("current", CURRENT_VERSION)
            if force_check and log is not None:
                log(f"[*] You already have the latest version (v{CURRENT_VERSION}).", tag="success")
            print("You have the latest version installed.")
    except Exception as e:
        # Back to "not checked yet" rather than leaving the caller on whatever
        # it showed while waiting. A failed request is not an answer, and a
        # status line stuck on "Checking…" because the network dropped is a
        # control the user can never press again.
        if report is not None:
            report("unknown", "")
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
