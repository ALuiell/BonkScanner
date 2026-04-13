from colorama import Fore, Style


def find_matching_template(stats: dict, active_names: list, all_templates: list) -> dict | None:
    """Return the first active template matched by the provided stats."""
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    microwaves = stats.get("Microwaves", 0)
    boss = stats.get("Boss Curses", 0)
    sm_total = shady + moai

    sorted_templates = sorted(all_templates, key=lambda t: t.get("id", 0), reverse=True)

    for template in sorted_templates:
        if template.get("name") not in active_names:
            continue

        meets_conditions = True

        if "sm_total" in template and sm_total < template["sm_total"]:
            meets_conditions = False
        if "shady" in template and shady < template["shady"]:
            meets_conditions = False
        if "moai" in template and moai < template["moai"]:
            meets_conditions = False
        if "micro" in template and microwaves < template["micro"]:
            meets_conditions = False
        if "boss" in template and boss < template["boss"]:
            meets_conditions = False

        if meets_conditions:
            return template

    return None


def print_match(template: dict) -> None:
    color_name = template.get("color", "LIGHTBLUE_EX").upper()
    color_val = getattr(Fore, color_name, Fore.LIGHTBLUE_EX)
    print(f"\n[+] Find good map! type: {color_val}{template.get('name')}{Style.RESET_ALL}")


def conditions_met(stats: dict, active_names: list, all_templates: list) -> bool:
    """Check map against active profiles dynamically."""
    template = find_matching_template(stats, active_names, all_templates)
    if template is None:
        return False

    print_match(template)
    return True
