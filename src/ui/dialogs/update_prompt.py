from __future__ import annotations

import threading

from app.supporters import load_supporters
from app.update_flow import (
    UpdateCheckResult,
    check_for_update,
    consume_update_result,
    launch_prepared_update,
    prepare_update,
    skip_update_version,
)
from ui.dialogs.update_dialog import show_update_dialog


SUPPORTERS_REFRESH_INTERVAL_MS = 10 * 60 * 1000
_SUPPORTERS_REFRESH_STARTED_KEY = "_supporters_refresh_started"
_SUPPORTERS_REFRESH_THREAD_KEY = "_supporters_refresh_thread"


def _start_registered_thread(app_instance, *, target, args=(), kwargs=None, name: str):
    registry = None
    if app_instance is not None:
        try:
            registry = app_instance.__dict__.setdefault("_background_threads", set())
        except (AttributeError, TypeError):
            registry = None

    def run() -> None:
        try:
            target(*args, **(kwargs or {}))
        finally:
            if isinstance(registry, set):
                registry.discard(threading.current_thread())

    thread = threading.Thread(
        target=run,
        name=name,
        daemon=True,
    )
    if isinstance(registry, set):
        registry.add(thread)
    try:
        thread.start()
    except Exception:
        if isinstance(registry, set):
            registry.discard(thread)
        raise
    return thread


def _safe_log(log, message: str, *, tag: str) -> None:
    if not callable(log):
        return
    try:
        log(message, tag=tag)
    except Exception:
        # Logging is diagnostic. It must never break a button callback or keep
        # an update session claimed forever.
        pass


def _safe_footer_status(footer, state: str, version: str = "") -> None:
    if footer is None:
        return
    try:
        footer.set_update_status(state, version)
    except Exception:
        # A queued result can arrive while the main window is being torn down.
        pass


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

    try:
        previous_result = consume_update_result()
    except Exception as exc:
        previous_result = None
        _safe_log(
            log,
            f"[!] Could not read the previous updater result: {exc}",
            tag="warning",
        )
    if previous_result is not None:
        state, message = previous_result
        if state == "success":
            _safe_log(
                log,
                f"[+] BonkScanner updated successfully to v{message}.",
                tag="success",
            )
        else:
            _safe_log(log, f"[!] Update installation failed: {message}", tag="error")

    _safe_footer_status(footer, "checking")

    def finish() -> None:
        _finish_update_session(app_instance)

    def handle_result(result) -> None:
        try:
            _safe_footer_status(footer, result.state, result.version)

            if result.state == "current":
                if force_check:
                    _safe_log(
                        log,
                        f"[*] You already have the latest version (v{result.version}).",
                        tag="success",
                    )
                return
            if result.state == "unavailable":
                return
            if result.state == "unknown":
                _safe_log(
                    log,
                    (
                        "[!] Failed to check for updates: "
                        f"{result.error or 'unknown error'}"
                    ),
                    tag="warning",
                )
                return
            if not result.should_prompt or result.release is None or result.exe_path is None:
                return

            release = result.release

            def start_download(progress, ready, failed):
                _safe_footer_status(footer, "downloading", release.version)
                _safe_log(
                    log,
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
                        try:
                            after(
                                0,
                                lambda: _safe_footer_status(
                                    footer, "available", release.version
                                ),
                            )
                        except Exception:
                            pass
                        try:
                            failed(str(exc))
                        except RuntimeError:
                            pass
                        return
                    try:
                        ready(prepared)
                    except RuntimeError:
                        pass

                return _start_registered_thread(
                    app_instance,
                    target=worker,
                    name="BonkUpdateDownload",
                )

            def install_update(prepared) -> None:
                shutdown = getattr(app_instance, "on_closing", None)
                if not callable(shutdown):
                    shutdown = getattr(app_instance, "destroy", None)
                if not callable(shutdown):
                    raise RuntimeError("BonkScanner could not start its clean shutdown.")
                launch_prepared_update(prepared)
                _safe_footer_status(footer, "installing", release.version)
                _safe_log(
                    log,
                    (
                        f"[+] Update v{release.version} verified. "
                        "Restarting BonkScanner..."
                    ),
                    tag="success",
                )
                try:
                    after(150, shutdown)
                except Exception:
                    # The verified helper is already running. Fall back to a
                    # direct clean shutdown instead of presenting a retry that
                    # could launch a second helper.
                    shutdown()

            parent = getattr(app_instance, "window", app_instance)
            decision = show_update_dialog(
                parent,
                release,
                start_download=start_download,
                install_update=install_update,
            )
            if decision == "skip":
                skip_result = skip_update_version(release.version)
                if getattr(skip_result, "success", True) is False:
                    raise RuntimeError(
                        getattr(skip_result, "reason", "")
                        or "The skipped update preference could not be saved."
                    )
                _safe_log(
                    log,
                    f"[*] Update v{release.version} skipped. "
                    "It remains available from the footer.",
                    tag="warning",
                )
            elif decision == "later":
                _safe_log(
                    log,
                    f"[*] Update v{release.version} postponed.",
                    tag="warning",
                )
        except Exception as exc:
            _safe_log(log, f"[!] Updater error: {exc}", tag="error")
            _safe_footer_status(
                footer,
                "available" if getattr(result, "release", None) is not None else "unknown",
                getattr(result, "version", ""),
            )
        finally:
            finish()

    def check_worker() -> None:
        try:
            result = check_for_update(force_check=force_check)
        except Exception as exc:
            result = UpdateCheckResult(state="unknown", error=str(exc))
        if bool(getattr(app_instance, "_is_shutting_down", False)):
            finish()
            return
        try:
            after(0, lambda: handle_result(result))
        except Exception as exc:
            _safe_log(log, f"[!] Updater error: {exc}", tag="error")
            finish()

    try:
        return _start_registered_thread(
            app_instance,
            target=check_worker,
            name="BonkUpdateCheck",
        )
    except Exception as exc:
        finish()
        _safe_footer_status(footer, "unknown")
        _safe_log(log, f"[!] Updater could not start: {exc}", tag="error")
        return None


def start_supporters_load(app_instance):
    """Fill the footer off the GUI thread now and refresh it every ten minutes."""
    footer = getattr(app_instance, "footer", None) if app_instance else None
    after = getattr(app_instance, "after", None) if app_instance else None
    if footer is None or after is None:
        return None

    state = getattr(app_instance, "__dict__", None)
    if not isinstance(state, dict) or state.get(_SUPPORTERS_REFRESH_STARTED_KEY):
        return None
    state[_SUPPORTERS_REFRESH_STARTED_KEY] = True

    def is_shutting_down() -> bool:
        return bool(state.get("_is_shutting_down", False))

    def schedule(delay_ms: int, callback) -> bool:
        if is_shutting_down():
            return False
        try:
            after(delay_ms, callback)
        except RuntimeError:
            # Qt can tear the invoker down between the shutdown check and emit.
            return False
        return True

    def report_to_footer(supporters: list) -> None:
        if is_shutting_down():
            return

        def apply() -> None:
            if not is_shutting_down():
                try:
                    footer.set_supporters(supporters)
                except Exception:
                    pass

        schedule(0, apply)

    def refresh_worker() -> None:
        try:
            load_supporters(report_to_footer)
        finally:
            schedule(SUPPORTERS_REFRESH_INTERVAL_MS, refresh)

    def refresh():
        if is_shutting_down():
            return None
        previous = state.get(_SUPPORTERS_REFRESH_THREAD_KEY)
        registry = state.get("_background_threads")
        is_alive = getattr(previous, "is_alive", None)
        if isinstance(registry, set) and callable(is_alive) and not is_alive():
            registry.discard(previous)

        worker = _start_registered_thread(
            app_instance,
            target=refresh_worker,
            name="BonkSupportersLoad",
        )
        state[_SUPPORTERS_REFRESH_THREAD_KEY] = worker
        return worker

    try:
        return refresh()
    except Exception:
        state.pop(_SUPPORTERS_REFRESH_STARTED_KEY, None)
        raise
