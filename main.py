import os
import time
import mss
import keyboard
from colorama import Fore, Style
import config
import ui
import logic
import scanner

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


def run_scanner(region):
    global is_running, return_to_menu

    # Reset state
    is_running = False
    return_to_menu = False

    # Use mss context manager for fast screenshots
    with mss.mss() as sct:
        while True:
            # Check if we need to break out to the menu
            if return_to_menu:
                break

            # If script isn't active, sleep briefly and wait
            if not is_running:
                time.sleep(0.1)
                continue

            try:
                # Capture and read text from the screen using scanner module
                text = scanner.capture_and_read(region, sct)
                
                # Extract stats using logic module
                stats = logic.extract_stats(text)

                # Fetch required stats for logging
                shady = stats.get("Shady Guy", 0)
                moai = stats.get("Moais", 0)
                microwaves = stats.get("Microwaves", 0)
                boss = stats.get("Boss Curses", 0)

                if logic.conditions_met(stats, active_templates, config.TEMPLATES):
                    print(f"Current Map Stats: Shady: {shady}, Moai: {moai}, Microwaves: {microwaves}, Boss: {boss}")
                    print("Target Map Found!")
                    keyboard.press_and_release('esc')
                    is_running = False  # Stop the loop, wait for manual trigger
                else:
                    # Double-check logic for "near PERFECT+" to prevent false rerolls
                    if "PERFECT+" in active_templates and logic.is_near_perfect_plus(stats):
                        print(f"Stats: S: {shady}, M: {moai}, Micro: {microwaves}, Boss: {boss}")
                        print(f"{Fore.YELLOW}Near PERFECT+ detected, rechecking...{Style.RESET_ALL}")

                        time.sleep(0.15)  # wait briefly

                        # Re-run OCR
                        text2 = scanner.capture_and_read(region, sct)
                        stats2 = logic.extract_stats(text2)

                        shady2 = stats2.get("Shady Guy", 0)
                        moai2 = stats2.get("Moais", 0)
                        microwaves2 = stats2.get("Microwaves", 0)
                        boss2 = stats2.get("Boss Curses", 0)

                        if logic.conditions_met(stats2, active_templates, config.TEMPLATES):
                            print(f"Current Map Stats (Recheck): Shady: {shady2}, Moai: {moai2}, Microwaves: {microwaves2}, Boss: {boss2}")
                            print(f"{Fore.GREEN}Recheck confirmed! Target Map Found!{Style.RESET_ALL}")
                            keyboard.press_and_release('esc')
                            is_running = False
                            continue
                        else:
                            print(f"Recheck Stats: S: {shady2}, M: {moai2}, Micro: {microwaves2}, Boss: {boss2} ... Reseting...")
                    else:
                        print(f"Stats: S: {shady}, M: {moai}, Micro: {microwaves}, Boss: {boss} ... Reseting...")

                    # Restart Macro
                    keyboard.press(config.RESET_HOTKEY)
                    time.sleep(config.RESET_HOLD_DURATION)
                    keyboard.release(config.RESET_HOTKEY)

                    # Wait for map load delay
                    time.sleep(config.MAP_LOAD_DELAY)

            except Exception as e:
                print(f"Error during execution (OCR failure?): {e}. Retrying...")
                time.sleep(1)


def main():
    global active_templates
    if not os.path.exists(config.TESSERACT_PATH):
        print(f"{Fore.RED}[CRITICAL ERROR] Tesseract engine not found!{Style.RESET_ALL}")
        print(f"Path searched: {config.TESSERACT_PATH}")
        print("Please make sure the 'Tesseract-OCR' folder is in the same directory as this script.")
        input("\nPress Enter to exit...")
        return
    
    # Check resolution once
    screen_width, screen_height = scanner.get_screen_resolution()
    region, region_name = scanner.get_region_for_resolution(screen_width, screen_height)
    
    if region_name.endswith("(Fallback)"):
        print(f"{Fore.YELLOW}Warning: Unsupported resolution ({screen_width}x{screen_height}) detected, defaulting to 2K coordinates.{Style.RESET_ALL}")

    # Register the hotkeys once
    keyboard.add_hotkey(config.HOTKEY, toggle_script)
    keyboard.add_hotkey(config.MENU_HOTKEY, trigger_return_to_menu)

    while True:
        # Show the interactive setup menu and fetch active templates
        active_templates = ui.setup_templates(
            screen_width, screen_height, region_name, region, 
            config.TEMPLATES, config.HOTKEY, config.MENU_HOTKEY
        )

        # Start the main scanning loop block
        run_scanner(region)

        # Clear the console visually
        print("\n" * 5)


if __name__ == "__main__":
    main()