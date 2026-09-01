"""Minimal process bootstrap for BonkScanner.

Qt and optional dependencies are loaded only after the crash journal is active.
"""

from __future__ import annotations

import os

from infra.crash_journal import (
    install_crash_journal,
    log_runtime_event,
    mark_clean_exit,
)


_UNLOADED = object()
keyboard = _UNLOADED
MegabonkApp = _UNLOADED
_config_initialized = False


def _load_keyboard_dependency():
    global keyboard
    if keyboard is not _UNLOADED:
        return keyboard
    try:
        import keyboard as loaded_keyboard
    except ImportError:
        loaded_keyboard = None
    keyboard = loaded_keyboard
    return keyboard


def _load_gui_application():
    global MegabonkApp
    if MegabonkApp is _UNLOADED:
        _initialize_configuration()
        from gui_app import MegabonkApp as loaded_app

        MegabonkApp = loaded_app
    return MegabonkApp


def _initialize_configuration() -> None:
    global _config_initialized
    if _config_initialized:
        return
    from app.config import initialize_config

    initialize_config()
    _config_initialized = True


def _terminate_process(exit_code: int) -> None:
    os._exit(int(exit_code))


def main():
    install_crash_journal()
    _initialize_configuration()
    if _load_keyboard_dependency() is None:
        mark_clean_exit()
        print("[CRITICAL ERROR] Missing dependency: keyboard.")
        print("Install it with: pip install keyboard")
        return

    app_type = _load_gui_application()
    log_runtime_event("application.constructing")
    app = app_type(terminate_process=_terminate_process)
    event_loop_failed = False
    try:
        app.protocol("WM_DELETE_WINDOW", app.on_closing)
        app.start()
        log_runtime_event("application.mainloop_enter")
        app.mainloop()
    except BaseException:
        event_loop_failed = True
        raise
    finally:
        # A normal window close already runs this through ``closeEvent``.  The
        # idempotent second call also covers QApplication.quit(), event-loop
        # termination by the OS, and an exception escaping ``exec()``.
        clean_shutdown = app.on_closing()
    log_runtime_event("application.mainloop_return")
    if not event_loop_failed and clean_shutdown is not False:
        mark_clean_exit()

if __name__ == "__main__":
    main()
