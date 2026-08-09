from __future__ import annotations

import threading

from app.supporters import load_supporters
from app.update_flow import check_and_update
from ui.dialogs.update_dialog import show_update_dialog


def _start_registered_thread(app_instance, *, target, args=(), kwargs=None, name: str):
    thread = threading.Thread(
        target=target,
        args=args,
        kwargs=kwargs or {},
        name=name,
        daemon=True,
    )
    if app_instance is not None:
        try:
            registry = app_instance.__dict__.setdefault("_background_threads", set())
            registry.add(thread)
        except (AttributeError, TypeError):
            pass
    thread.start()
    return thread


def start_update_check(app_instance, *, force_check: bool):
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

    # Same `getattr` shape as `log` and `after` above, and for the same reason:
    # this function is driven by stand-in app objects in the suite, and by the
    # real one before `build_layout` has run. No footer means no report -- the
    # flow keeps printing its outcome and nothing else changes.
    footer = getattr(app_instance, "footer", None) if app_instance else None

    def report_to_footer(state: str, version: str) -> None:
        # `check_and_update` runs on the thread started below; the strip is a
        # widget. `schedule` is the hop back, the same one the dialog uses.
        schedule(lambda: footer.set_update_status(state, version))

    report = report_to_footer if (footer is not None and schedule is not None) else None

    return _start_registered_thread(
        app_instance,
        target=check_and_update,
        kwargs={
            "confirm": confirm,
            "log": log,
            "schedule": schedule,
            "report": report,
            "force_check": force_check,
        },
        name="BonkUpdateCheck",
    )


def start_supporters_load(app_instance):
    """Fill the footer's supporters list, off the GUI thread.

    Deliberately its own request and its own thread rather than a passenger on
    the update check, which returns before it reaches the network on a source
    run (`check_and_update` -> `frozen_exe_path`). Riding along would mean the
    list is invisible to everyone running from source, including while working
    on it -- a difference that reads as a bug every time it is rediscovered.
    """
    footer = getattr(app_instance, "footer", None) if app_instance else None
    after = getattr(app_instance, "after", None) if app_instance else None
    # Same shape as the `report` wiring above: driven by stand-in app objects in
    # the suite, and by the real one before `build_layout` has run.
    if footer is None or after is None:
        return None

    def report_to_footer(supporters: list) -> None:
        # `load_supporters` runs on the thread started below; the strip is a
        # widget. Same hop as `report_to_footer` above, for the same reason.
        after(0, lambda: footer.set_supporters(supporters))

    return _start_registered_thread(
        app_instance,
        target=load_supporters,
        args=(report_to_footer,),
        name="BonkSupportersLoad",
    )
