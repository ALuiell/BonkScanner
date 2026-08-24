from __future__ import annotations

import threading

from app.supporters import load_supporters
from app.update_flow import (
    check_for_update,
    consume_update_result,
    launch_prepared_update,
    prepare_update,
    skip_update_version,
)
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


def _claim_update_session(app_instance) -> bool:
    """Allow one check/dialog/download session for this application at a time."""
    if app_instance is None:
        return False
    state = getattr(app_instance, "__dict__", None)
    if state is None:
        return False
    lock = state.setdefault("_update_session_lock", threading.Lock())
    with lock:
        if state.get("_update_session_active", False):
            return False
        state["_update_session_active"] = True
        return True


def _finish_update_session(app_instance) -> None:
    state = getattr(app_instance, "__dict__", None)
    if state is None:
        return
    lock = state.get("_update_session_lock")
    if lock is None:
        state["_update_session_active"] = False
        return
    with lock:
        state["_update_session_active"] = False


def start_update_check(app_instance, *, force_check: bool):
    """Check in the background, then own one complete modal update session."""
    if not _claim_update_session(app_instance):
        return None

    log = getattr(app_instance, "log", None)
    after = getattr(app_instance, "after", None)
    footer = getattr(app_instance, "footer", None)
    if after is None:
        _finish_update_session(app_instance)
        return None

    previous_result = consume_update_result()
    if previous_result is not None and callable(log):
        state, message = previous_result
        if state == "success":
            log(f"[+] BonkScanner updated successfully to v{message}.", tag="success")
        else:
            log(f"[!] Update installation failed: {message}", tag="error")

    if footer is not None:
        footer.set_update_status("checking")

    def finish() -> None:
        _finish_update_session(app_instance)

    def handle_result(result) -> None:
        if footer is not None:
            footer.set_update_status(result.state, result.version)

        if result.state == "current":
            if force_check and callable(log):
                log(
                    f"[*] You already have the latest version (v{result.version}).",
                    tag="success",
                )
            finish()
            return
        if result.state == "unavailable":
            finish()
            return
        if result.state == "unknown":
            if callable(log):
                log(
                    f"[!] Failed to check for updates: {result.error or 'unknown error'}",
                    tag="warning",
                )
            finish()
            return
        if not result.should_prompt or result.release is None or result.exe_path is None:
            finish()
            return

        release = result.release

        def start_download(progress, ready, failed):
            if footer is not None:
                footer.set_update_status("downloading", release.version)
            if callable(log):
                log(
                    f"[*] Downloading and verifying update v{release.version}...",
                    tag="warning",
                )

            def worker() -> None:
                try:
                    prepared = prepare_update(
                        result.exe_path,
                        release,
                        progress=progress,
                    )
                except Exception as exc:
                    if footer is not None:
                        after(
                            0,
                            lambda: footer.set_update_status("available", release.version),
                        )
                    failed(str(exc))
                    return
                ready(prepared)

            return _start_registered_thread(
                app_instance,
                target=worker,
                name="BonkUpdateDownload",
            )

        def install_update(prepared) -> None:
            launch_prepared_update(prepared)
            if footer is not None:
                footer.set_update_status("installing", release.version)
            if callable(log):
                log(
                    f"[+] Update v{release.version} verified. Restarting BonkScanner...",
                    tag="success",
                )
            shutdown = getattr(app_instance, "on_closing", None)
            if not callable(shutdown):
                shutdown = getattr(app_instance, "destroy", None)
            if not callable(shutdown):
                raise RuntimeError("BonkScanner could not start its clean shutdown.")
            after(150, shutdown)

        try:
            parent = getattr(app_instance, "window", app_instance)
            decision = show_update_dialog(
                parent,
                release,
                start_download=start_download,
                install_update=install_update,
            )
            if decision == "skip":
                skip_update_version(release.version)
                if callable(log):
                    log(
                        f"[*] Update v{release.version} skipped. "
                        "It remains available from the footer.",
                        tag="warning",
                    )
            elif decision == "later" and callable(log):
                log(
                    f"[*] Update v{release.version} postponed.",
                    tag="warning",
                )
        except Exception as exc:
            if callable(log):
                log(f"[!] Updater error: {exc}", tag="error")
            if footer is not None:
                footer.set_update_status("available", release.version)
        finally:
            finish()

    def check_worker() -> None:
        result = check_for_update(force_check=force_check)
        after(0, lambda: handle_result(result))

    return _start_registered_thread(
        app_instance,
        target=check_worker,
        name="BonkUpdateCheck",
    )


def start_supporters_load(app_instance):
    """Fill the footer supporters list off the GUI thread."""
    footer = getattr(app_instance, "footer", None) if app_instance else None
    after = getattr(app_instance, "after", None) if app_instance else None
    if footer is None or after is None:
        return None

    def report_to_footer(supporters: list) -> None:
        after(0, lambda: footer.set_supporters(supporters))

    return _start_registered_thread(
        app_instance,
        target=load_supporters,
        args=(report_to_footer,),
        name="BonkSupportersLoad",
    )
