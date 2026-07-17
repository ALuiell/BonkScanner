from __future__ import annotations

import threading

from app.update_flow import check_and_update
from ui.dialogs.update_dialog import show_update_dialog


def start_update_check(app_instance, *, force_check: bool) -> None:
    """Run the update check off the GUI thread, prompting through the Qt dialog.

    The flow in ``app/`` owns the decisions and knows nothing about widgets; this
    is the adapter that hands it a way to ask, to log, and to get back onto the
    GUI thread before the dialog is built.
    """

    def confirm(latest_version: str, release_notes: str) -> bool | None:
        parent = getattr(app_instance, "window", app_instance)
        return show_update_dialog(parent, latest_version, release_notes)

    log = getattr(app_instance, "log", None) if app_instance else None
    after = getattr(app_instance, "after", None) if app_instance else None
    schedule = (lambda callback: after(0, callback)) if after else None

    threading.Thread(
        target=check_and_update,
        kwargs={
            "confirm": confirm,
            "log": log,
            "schedule": schedule,
            "force_check": force_check,
        },
        daemon=True,
    ).start()
