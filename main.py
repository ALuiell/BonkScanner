import time
from colorama import Fore, Style
import config
from game_data import GameDataClient
import logic
from memory import MemoryReadError, ModuleNotFoundError, ProcessNotFoundError
from runtime_stats import adapt_map_stats
import ui

try:
    import keyboard
except ImportError:
    keyboard = None

# ==========================================
# SCRIPT STATE
# ==========================================
is_running = False
return_to_menu = False
active_templates = []


def toggle_script():
    """Toggle the running state of the loop when the hotkey is pressed."""
    global is_running
    is_running = not is_running
    status = "STARTED" if is_running else "STOPPED"
    print(f"\n[!] Script {status}")


def trigger_return_to_menu():
    """Signal the main loop to break and return to the setup menu."""
    global return_to_menu, is_running
    is_running = False
    return_to_menu = True
    print(f"\n[!] Returning to menu...")


def fetch_runtime_stats(client: GameDataClient) -> dict[str, int]:
    return adapt_map_stats(client.get_map_stats())


def format_stats(stats: dict[str, int]) -> str:
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    microwaves = stats.get("Microwaves", 0)
    boss = stats.get("Boss Curses", 0)
    return f"Shady: {shady}, Moai: {moai}, Microwaves: {microwaves}, Boss: {boss}"


def confirm_template_match(
    initial_stats: dict[str, int],
    confirmed_stats: dict[str, int],
    selected_templates: list[str],
    all_templates: list[dict],
) -> dict | None:
    initial_template = logic.find_matching_template(
        initial_stats,
        selected_templates,
        all_templates,
    )
    if initial_template is None:
        return None

    return logic.find_matching_template(
        confirmed_stats,
        selected_templates,
        all_templates,
    )


def reroll_map() -> None:
    if keyboard is None:
        raise RuntimeError("keyboard module is not available.")

    keyboard.press(config.RESET_HOTKEY)
    time.sleep(config.RESET_HOLD_DURATION)
    keyboard.release(config.RESET_HOTKEY)
    time.sleep(config.MAP_LOAD_DELAY)


def run_scanner(client: GameDataClient):
    global is_running, return_to_menu

    is_running = False
    return_to_menu = False

    while True:
        if return_to_menu:
            break

        if not is_running:
            time.sleep(0.1)
            continue

        try:
            stats = fetch_runtime_stats(client)
            candidate_template = logic.find_matching_template(
                stats,
                active_templates,
                config.TEMPLATES,
            )

            if candidate_template is not None:
                print(f"{Fore.YELLOW}Candidate map found. Confirming...{Style.RESET_ALL}")
                time.sleep(0.15)
                confirmed_stats = fetch_runtime_stats(client)
                confirmed_template = confirm_template_match(
                    stats,
                    confirmed_stats,
                    active_templates,
                    config.TEMPLATES,
                )

                if confirmed_template is not None:
                    logic.print_match(confirmed_template)
                    print(f"Max Map Stats: {format_stats(confirmed_stats)}")
                    print(f"{Fore.GREEN}Target Map Found!{Style.RESET_ALL}")
                    keyboard.press_and_release("esc")
                    is_running = False
                    continue

                print(f"Confirmation failed. Stats: {format_stats(confirmed_stats)} ... Reseting...")
            else:
                print(f"Stats: {format_stats(stats)} ... Reseting...")

            reroll_map()
        except Exception as e:
            print(f"Error during execution: {e}. Retrying...")
            time.sleep(1)


def main():
    global active_templates

    if keyboard is None:
        print(f"{Fore.RED}[CRITICAL ERROR] Missing dependency: keyboard.{Style.RESET_ALL}")
        print("Install it with: pip install keyboard")
        input("\nPress Enter to exit...")
        return

    process_name = config.PROCESS_NAME.strip()
    if not process_name:
        print(f"{Fore.RED}[CRITICAL ERROR] PROCESS_NAME is not configured.{Style.RESET_ALL}")
        print("Set PROCESS_NAME in config.json to the game executable name, for example 'Game.exe'.")
        input("\nPress Enter to exit...")
        return

    try:
        with GameDataClient(process_name=process_name) as client:
            keyboard.add_hotkey(config.HOTKEY, toggle_script)
            keyboard.add_hotkey(config.MENU_HOTKEY, trigger_return_to_menu)

            while True:
                active_templates = ui.setup_templates(
                    config.TEMPLATES,
                    config.HOTKEY,
                    config.MENU_HOTKEY,
                    process_name,
                )
                run_scanner(client)
                print("\n" * 5)
    except ProcessNotFoundError:
        print(f"{Fore.RED}[CRITICAL ERROR] Could not open process '{process_name}'.{Style.RESET_ALL}")
        print("Make sure the game is running and PROCESS_NAME matches the executable name.")
        input("\nPress Enter to exit...")
    except ModuleNotFoundError:
        print(f"{Fore.RED}[CRITICAL ERROR] GameAssembly.dll is not loaded in the target process.{Style.RESET_ALL}")
        print("Open the game fully before starting the scanner.")
        input("\nPress Enter to exit...")
    except MemoryReadError as exc:
        print(f"{Fore.RED}[CRITICAL ERROR] Failed to initialize memory reader: {exc}{Style.RESET_ALL}")
        input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
