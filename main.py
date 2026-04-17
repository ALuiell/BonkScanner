try:
    import keyboard
except ImportError:
    keyboard = None

from gui import MegabonkApp
from updater import check_and_update

def main():
    if keyboard is None:
        print("[CRITICAL ERROR] Missing dependency: keyboard.")
        print("Install it with: pip install keyboard")
        return

    app = MegabonkApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()


if __name__ == "__main__":
    check_and_update()
    main()
