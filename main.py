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
is_ready_to_start = False
active_templates = []
in_menu = True
WAIT_RETRY_DELAY = 1.0


def toggle_script():
    """Toggle the running state of the loop when the hotkey is pressed."""
    global is_running, in_menu
    
    if in_menu:
        return
        
    if not is_ready_to_start:
        print(f"{Fore.YELLOW}[WAIT] Scanner is not ready yet. Finish process wait first.{Style.RESET_ALL}")
        return

    is_running = not is_running
    status = "STARTED" if is_running else "STOPPED"
    print(f"\n[!] Script {status}")


def trigger_return_to_menu():
    """Signal the main loop to break and return to the setup menu."""
    global return_to_menu, is_running, is_ready_to_start, in_menu
    
    if in_menu:
        return
        
    is_running = False
    is_ready_to_start = False
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


def close_client(client: GameDataClient | None) -> None:
    if client is None:
        return

    try:
        client.close()
    except Exception:
        pass


def print_wait_status(state: str, process_name: str, exc: Exception | None = None) -> None:
    if state == "process":
        print(f"{Fore.YELLOW}[WAIT] Waiting for process '{process_name}'...{Style.RESET_ALL}")
    elif state == "module":
        print(f"{Fore.YELLOW}[WAIT] Process found. Waiting for GameAssembly.dll...{Style.RESET_ALL}")
    elif state == "ready":
        print(f"{Fore.GREEN}[WAIT] Game detected. Press '{config.HOTKEY}' to start scanning.{Style.RESET_ALL}")
    elif state == "reconnect":
        detail = f" ({exc})" if exc is not None else ""
        print(f"{Fore.YELLOW}[WAIT] Lost connection to the game{detail}. Returning to wait mode...{Style.RESET_ALL}")


def wait_for_game_client(
    process_name: str,
    *,
    client_factory=GameDataClient,
    sleep_fn=time.sleep,
    print_fn=print_wait_status,
    retry_delay: float = WAIT_RETRY_DELAY,
) -> GameDataClient | None:
    global return_to_menu

    wait_state = None

    while True:
        if return_to_menu:
            return None

        try:
            client = client_factory(process_name=process_name)
            if wait_state is not None:
                print_fn("ready", process_name)
            return client
        except ProcessNotFoundError:
            if wait_state != "process":
                print_fn("process", process_name)
                wait_state = "process"
        except ModuleNotFoundError:
            if wait_state != "module":
                print_fn("module", process_name)
                wait_state = "module"

        sleep_fn(retry_delay)


def reset_client_after_disconnect(
    client: GameDataClient | None,
    exc: Exception,
    *,
    sleep_fn=time.sleep,
    print_fn=print_wait_status,
    process_name: str = "",
    retry_delay: float = WAIT_RETRY_DELAY,
) -> None:
    close_client(client)
    print_fn("reconnect", process_name, exc)
    sleep_fn(retry_delay)


def run_scanner(client: GameDataClient) -> str:
    global is_running, return_to_menu, is_ready_to_start

    is_ready_to_start = True
    is_running = False

    while True:
        if return_to_menu:
            close_client(client)
            is_ready_to_start = False
            return "menu"

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
        except (ProcessNotFoundError, ModuleNotFoundError, MemoryReadError) as exc:
            is_running = False
            is_ready_to_start = False
            reset_client_after_disconnect(client, exc, process_name=client.memory.process_name if hasattr(client, "memory") and hasattr(client.memory, "process_name") else "")
            return "reconnect"
        except Exception as e:
            print(f"Error during execution: {e}. Retrying...")
            time.sleep(1)


def main():
    global active_templates, return_to_menu, is_ready_to_start, in_menu

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
        keyboard.add_hotkey(config.HOTKEY, toggle_script)
        keyboard.add_hotkey(config.MENU_HOTKEY, trigger_return_to_menu)

        while True:
            return_to_menu = False
            is_ready_to_start = False
            in_menu = True
            
            active_templates = ui.setup_templates(
                config.TEMPLATES,
                config.HOTKEY,
                config.MENU_HOTKEY,
                process_name,
            )
            
            in_menu = False

            while True:
                client = wait_for_game_client(process_name)
                if client is None:
                    return_to_menu = False
                    break

                result = run_scanner(client)
                if result == "reconnect":
                    return_to_menu = False
                    print("\n" * 2)
                    continue

                return_to_menu = False
                print("\n" * 5)
                break
    except MemoryReadError as exc:
        print(f"{Fore.RED}[CRITICAL ERROR] Failed to initialize memory reader: {exc}{Style.RESET_ALL}")
        input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
