try:
    import keyboard
except ImportError:
    keyboard = None

from gui_app import MegabonkApp
from infra.crash_journal import (
    install_crash_journal,
    log_runtime_event,
    mark_clean_exit,
)

def main():
    install_crash_journal()
    if keyboard is None:
        mark_clean_exit()
        print("[CRITICAL ERROR] Missing dependency: keyboard.")
        print("Install it with: pip install keyboard")
        return

    log_runtime_event("application.constructing")
    app = MegabonkApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    log_runtime_event("application.mainloop_enter")
    app.mainloop()
    log_runtime_event("application.mainloop_return")
    mark_clean_exit()

if __name__ == "__main__":
    main()
