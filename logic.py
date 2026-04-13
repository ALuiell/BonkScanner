import re
from colorama import Fore, Style
from difflib import get_close_matches

# ==========================================
# DEFINITIONS
# ==========================================
KNOWN_KEYS = [
    "Boss Curses",
    "Challenges",
    "Charge Shrines",
    "Chests",
    "Greed Shrines",
    "Magnet Shrines",
    "Microwaves",
    "Moais",
    "Pots",
    "Shady Guy"
]

ALIASES = {
    "boss curse": "Boss Curses",
    "boss curses": "Boss Curses",

    "challenge": "Challenges",
    "challenges": "Challenges",

    "charge shrine": "Charge Shrines",
    "charge shrines": "Charge Shrines",

    "chest": "Chests",
    "chests": "Chests",

    "greed shrine": "Greed Shrines",
    "greed shrines": "Greed Shrines",

    "magnet shrine": "Magnet Shrines",
    "magnet shrines": "Magnet Shrines",

    "microwave": "Microwaves",
    "microwaves": "Microwaves",
    "microwoves": "Microwaves",
    "microwavs": "Microwaves",

    "moai": "Moais",
    "moais": "Moais",
    "maais": "Moais",
    "moals": "Moais",

    "pot": "Pots",
    "pots": "Pots",

    "shady guy": "Shady Guy",
    "shady gvy": "Shady Guy",
    "shady guv": "Shady Guy",
}

# ==========================================
# OCR TEXT PARSING & FUZZY MATCHING
# ==========================================
def normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r'[^a-z0-9/ ]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def fuzzy_find_key(line: str) -> str | None:
    line_norm = normalize_text(line)

    # Убираем числа вида 0/5, чтобы сравнивать только название
    label_only = re.sub(r'\d+\s*/\s*\d+', '', line_norm).strip()

    if not label_only:
        return None

    # 1. Сначала точечные alias для типичных OCR-ошибок
    for alias, canonical in ALIASES.items():
        if alias in label_only:
            return canonical

    # 2. Потом fuzzy fallback
    normalized_map = {normalize_text(k): k for k in KNOWN_KEYS}
    # n=1: return only top match, cutoff=0.55: minimum similarity score
    match = get_close_matches(label_only, normalized_map.keys(), n=1, cutoff=0.55)

    if match:
        return normalized_map[match[0]]

    return None

def extract_stats(text: str) -> dict:
    """Extract the total values from the OCR text using fuzzy matching."""
    stats = {
        "Boss Curses": 0, "Challenges": 0, "Charge Shrines": 0, "Chests": 0,
        "Greed Shrines": 0, "Magnet Shrines": 0, "Microwaves": 0,
        "Moais": 0, "Pots": 0, "Shady Guy": 0
    }

    lines = text.split('\n')

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # 1. Сначала пытаемся понять, о каком стате идет речь в этой строке
        found_key = fuzzy_find_key(line)
        if not found_key:
            continue

        # 2. Если стат опознан, вытаскиваем из строки число, идущее после слеша
        match = re.search(r'/\s*(\d+)', line)
        if match:
            try:
                val = int(match.group(1))

                # Фильтр: отсекаем явно ошибочные значения OCR (больше 14)
                # Так как в игре физически не может быть 15 Moais или 15 Shady Guy
                if val <= 14:
                    stats[found_key] = val
            except ValueError:
                pass

    return stats


# ==========================================
# CONDITION EVALUATION
# ==========================================
def is_near_perfect_plus(stats: dict) -> bool:
    """
    VERY broad check for 'maybe PERFECT+' maps.
    Designed to minimize false rerolls, even if OCR lost one of the key stats.
    """
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    microwaves = stats.get("Microwaves", 0)
    boss = stats.get("Boss Curses", 0)

    sm_total = shady + moai

    # Без 2 microwaves смысла почти нет
    if microwaves < 2:
        return False

    # Без 2 boss тоже почти нет смысла
    if boss < 2:
        return False

    # 1. Очевидно сильные случаи
    if sm_total >= 8:
        return True

    if shady >= 8 or moai >= 8:
        return True

    # 2. Сильные раздельные комбинации
    strong_pairs = [(7, 1), (6, 2), (5, 3), (4, 4), (3, 5), (2, 6), (1, 7)]
    for s_req, m_req in strong_pairs:
        if shady >= s_req and moai >= m_req:
            return True
        if shady >= m_req and moai >= s_req:
            return True

    # 3. Если boss уже 3+, можно быть еще мягче
    if boss >= 3:
        if sm_total >= 6: return True
        if shady >= 7 or moai >= 7: return True
        if shady >= 5 and moai >= 1: return True
        if shady >= 1 and moai >= 5: return True
        if shady >= 4 and moai >= 2: return True
        if shady >= 2 and moai >= 4: return True
        if shady >= 3 and moai >= 3: return True
        if shady == 0 and moai >= 3: return True
        if moai == 0 and shady >= 3: return True

    # 4. Если один стат очень высокий, второй мог просто потеряться OCR'ом
    if shady >= 7: return True
    if moai >= 7: return True
    if shady >= 6 and boss >= 2: return True
    if moai >= 6 and boss >= 2: return True

    # 5. Защита от случаев, когда OCR занизил total
    if sm_total >= 7 and boss >= 2: return True
    if sm_total >= 5 and boss >= 3: return True

    # 6. Подозрительные асимметричные кейсы
    if shady >= 5 and moai == 0 and boss >= 3: return True
    if moai >= 5 and shady == 0 and boss >= 3: return True
    if shady >= 4 and moai == 0 and boss >= 3: return True
    if moai >= 4 and shady == 0 and boss >= 3: return True

    return False


def conditions_met(stats: dict, active_names: list, all_templates: list) -> bool:
    """Check map against active profiles dynamically."""
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    microwaves = stats.get("Microwaves", 0)
    boss = stats.get("Boss Curses", 0)
    sm_total = shady + moai

    # Sort templates by ID descending so stricter templates (like PERFECT+ ID 5, BOSS RUSH+ ID 7) are checked first
    sorted_templates = sorted(all_templates, key=lambda t: t.get("id", 0), reverse=True)

    for template in sorted_templates:
        if template.get("name") not in active_names:
            continue

        meets_conditions = True

        # Hybrid Logic: Check key if it exists
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
            # Dynamic Coloring
            color_name = template.get("color", "LIGHTBLUE_EX").upper()
            color_val = getattr(Fore, color_name, Fore.LIGHTBLUE_EX)
            print(f"\n[+] Find good map! type: {color_val}{template.get('name')}{Style.RESET_ALL}")
            return True

    return False
