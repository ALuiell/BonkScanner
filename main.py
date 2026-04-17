try:
    import keyboard
except ImportError:
    keyboard = None

import threading
from gui import MegabonkApp
from updater import check_and_update

def main():
    if keyboard is None:
        print("[CRITICAL ERROR] Missing dependency: keyboard.")
        print("Install it with: pip install keyboard")
        return

    app = MegabonkApp()

    # Pass the app instance to check_and_update so it can spawn the dialog properly on top
    threading.Thread(target=check_and_update, args=(app,), daemon=True).start()

    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()

if __name__ == "__main__":
    main()
