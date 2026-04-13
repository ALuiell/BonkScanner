import sys
import os
from colorama import Fore, Style
import config

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header():
    header = fr"""
{Fore.MAGENTA}{Style.BRIGHT}
 __  __ ______ _____          ____   ____  _   _ _  __
|  \/  |  ____/ ____|   /\   |  _ \ / __ \| \ | | |/ /
| \  / | |__ | |  __   /  \  | |_) | |  | |  \| | ' / 
| |\/| |  __|| | |_ | / /\ \ |  _ <| |  | | . ` |  <  
| |  | | |___| |__| |/ ____ \| |_) | |__| | |\  | . \ 
|_|  |_|______\_____/_/    \_\____/ \____/|_| \_|_|\_\\
{Style.RESET_ALL}
"""
    print(header)

def get_int_input(prompt: str) -> int:
    """Safely get an integer input from the user, defaulting to 0 if empty or invalid."""
    user_val = input(prompt).strip()
    if not user_val:
        return 0
    if user_val.isdigit():
        return int(user_val)
    print(f"{Fore.YELLOW}Invalid number. Defaulting to 0.{Style.RESET_ALL}")
    return 0

def create_template(templates):
    """Interactive flow to create a new template."""
    print(f"\n{Fore.CYAN}--- Create New Custom Template ---{Style.RESET_ALL}")
    name = input("Template Name: ").strip()
    if not name:
        print(f"{Fore.RED}Creation cancelled. Name cannot be empty.{Style.RESET_ALL}")
        input("Press Enter to return...")
        return

    shady = get_int_input("Required Shady Guy (default 0): ")
    moais = get_int_input("Required Moais (default 0): ")
    micro = get_int_input("Required Microwaves (default 0): ")
    boss = get_int_input("Required Boss Curses (default 0): ")

    max_id = max([t.get("id", 0) for t in templates] + [0])
    new_id = max_id + 1

    new_template = {
        "id": new_id,
        "name": name,
        "shady": shady,
        "moai": moais,
        "micro": micro,
        "boss": boss
    }

    templates.append(new_template)
    config.user_config["TEMPLATES"] = templates
    config.save_config(config.user_config)
    
    print(f"{Fore.GREEN}Template '{name}' successfully created and saved!{Style.RESET_ALL}")
    input("Press Enter to continue...")

def delete_template(templates):
    """Interactive flow to delete an existing custom template."""
    print(f"\n{Fore.CYAN}--- Delete Custom Template ---{Style.RESET_ALL}")
    target_id_str = input("Enter the ID of the template to delete (or leave empty to cancel): ").strip()
    
    if not target_id_str:
        return
        
    if not target_id_str.isdigit():
        print(f"{Fore.RED}Invalid ID format.{Style.RESET_ALL}")
        input("Press Enter to return...")
        return
        
    target_id = int(target_id_str)
    
    if target_id <= 7:
        print(f"{Fore.RED}Error: You cannot delete the built-in profiles (IDs 1-7).{Style.RESET_ALL}")
        input("Press Enter to return...")
        return

    target_template = next((t for t in templates if t.get("id") == target_id), None)
    
    if not target_template:
        print(f"{Fore.RED}Template with ID {target_id} not found.{Style.RESET_ALL}")
        input("Press Enter to return...")
        return
        
    confirm = input(f"Are you sure you want to delete '{target_template['name']}'? (y/n): ").strip().lower()
    if confirm in ['y', 'yes']:
        templates.remove(target_template)
        config.user_config["TEMPLATES"] = templates
        config.save_config(config.user_config)
        print(f"{Fore.GREEN}Template '{target_template['name']}' deleted successfully.{Style.RESET_ALL}")
    else:
        print(f"{Fore.YELLOW}Deletion cancelled.{Style.RESET_ALL}")
        
    input("Press Enter to continue...")

def format_template_desc(t: dict) -> str:
    """Returns the provided desc or generates one dynamically based on stats."""
    if "desc" in t:
        return t["desc"]
    
    parts = []
    if t.get("shady", 0) > 0: parts.append(f"Shady: {t['shady']}")
    if t.get("moai", 0) > 0: parts.append(f"Moai: {t['moai']}")
    if t.get("micro", 0) > 0: parts.append(f"Micro: {t['micro']}")
    if t.get("boss", 0) > 0: parts.append(f"Boss: {t['boss']}")
    
    if parts:
        return ", ".join(parts)
    return "Any"

def setup_templates(templates, hotkey, menu_hotkey, process_name):
    """
    Shows the interactive setup menu in a loop to handle CRUD operations.
    Returns the list of active template names selected by the user.
    """
    active_templates = []
    
    while True:
        clear_console()
        print_header()

        print(f"{Fore.BLUE}Data Source: Process memory{Style.RESET_ALL}")
        print(f"{Fore.BLUE}Target Process: {process_name}{Style.RESET_ALL}\n")

        print("Available Templates:")
        print("-" * 40)
        for t in templates:
            color_name = t.get("color", "LIGHTBLUE_EX").upper()
            color_val = getattr(Fore, color_name, Fore.LIGHTBLUE_EX)
            desc = format_template_desc(t)
            print(f"[{t['id']}] {color_val}{t['name']}{Style.RESET_ALL} ({desc})")
            
        print("-" * 40)
        print("Options:")
        print(f"  [{Fore.CYAN}N{Style.RESET_ALL}] Create New Custom Template")
        print(f"  [{Fore.RED}D{Style.RESET_ALL}] Delete a Custom Template")
        print("\nEnter the numbers of templates you want to INCLUDE")
        print(f"(separated by space, or {Fore.YELLOW}press Enter to include ALL{Style.RESET_ALL}):")
        print("(type 'q' or 'quit' to exit the script)")

        user_input = input("\n> ").strip().lower()

        if user_input in ['q', 'quit', 'exit']:
            print("Exiting...")
            sys.exit(0)
            
        if user_input == 'n':
            create_template(templates)
            continue
            
        if user_input == 'd':
            delete_template(templates)
            continue

        if not user_input:
            active_templates = [t['name'] for t in templates]
            break

        try:
            included_ids = [int(x) for x in user_input.split()]
            active_templates = [t['name'] for t in templates if t['id'] in included_ids]

            if not active_templates:
                print(f"{Fore.RED}Error: You did not select any valid template numbers.{Style.RESET_ALL}")
                print(f"{Fore.YELLOW}Please try again, or just press Enter to select ALL templates.{Style.RESET_ALL}")
                input("Press Enter to continue...")
                continue
            break
        except ValueError:
            print(f"{Fore.RED}Invalid input. Please enter numbers separated by spaces, or press Enter for ALL.{Style.RESET_ALL}")
            print("You can also type 'N' or 'D' to manage templates.")
            input("Press Enter to continue...")

    # Rendering confirmation
    colored_active_templates = []
    for temp_name in active_templates:
        for t in templates:
            if t['name'] == temp_name:
                color_name = t.get("color", "LIGHTBLUE_EX").upper()
                color_val = getattr(Fore, color_name, Fore.LIGHTBLUE_EX)
                colored_active_templates.append(f"{color_val}{temp_name}{Fore.GREEN}")

    print(f"\n{Fore.GREEN}Monitoring prepared! Looking for: {', '.join(colored_active_templates)}{Style.RESET_ALL}")
    print("After the game is detected, the scanner will arm automatically.")
    print(f"Then press '{hotkey}' to start or stop scanning.")
    print(f"Press '{menu_hotkey}' to return to this menu.\n")
    
    return active_templates
